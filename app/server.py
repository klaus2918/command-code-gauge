# -*- coding: utf-8 -*-
"""本地 HTTP 服务：前端 REST API + 同步引擎 + 定时调度。

- 仅绑定 127.0.0.1（随机端口），供 pywebview 窗口与浏览器同源访问
- 标准库实现（http.server），不引入额外 Web 框架
- 同步引擎：锚点翻页全量回溯 + 幂等增量追平；每次同步后刷新配额快照
"""
from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests

from . import APP_NAME, __version__
from .cc_api import AuthError, CommandCodeAPIError, CommandCodeClient, encode_cursor
from .db import Database

WEB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
CLI_AUTH_PATH = os.path.join(os.path.expanduser("~"), ".commandcode", "auth.json")
DEFAULT_SYNC_INTERVAL_MIN = 5
DEFAULT_SYNC_RANGE_DAYS = 90
FULL_SYNC_MAX_PAGES = 300          # 历史回填保护（300 × 100 = 3 万条）
INCREMENTAL_MAX_PAGES = 20         # 增量追新保护（通常 1~2 页即追平）
SYNC_MIN_INTERVAL_MIN = 1
SYNC_MAX_INTERVAL_MIN = 30
SCHEDULER_TICK_SEC = 20
QUOTA_MIN_INTERVAL_SEC = 300       # 配额刷新最小间隔（5 分钟），避免每次同步都拉 4 个接口
EXCHANGE_API_URL = "https://open.er-api.com/v6/latest/USD"
RATE_CACHE_SEC = 86400             # 汇率缓存 24 小时
RATE_FETCH_TIMEOUT_SEC = 15
CURRENCY_MODES = ("usd", "cny", "both")

PLAN_MONTHLY_CREDITS = {
    "individual-go": 10,
    "individual-provider": 15,
    "individual-pro": 30,
    "individual-pro-v1": 80,
    "teams-pro": 40,
    "individual-goat": 70,
    "individual-max": 150,
    "individual-ultra": 300,
}

PLAN_DISPLAY_NAMES = {
    "individual-go": "Go",
    "individual-provider": "Provider",
    "individual-pro": "Pro",
    "individual-pro-v1": "Pro",
    "teams-pro": "Teams Pro",
    "individual-goat": "GOAT",
    "individual-max": "Max",
    "individual-ultra": "Ultra",
}


def local_tz_offset_sec(ts: Optional[int] = None) -> int:
    """本地时区相对 UTC 的偏移秒数（东八区为 +28800）。"""
    if ts is None:
        ts = int(time.time())
    return int(time.mktime(time.localtime(ts)) - time.mktime(time.gmtime(ts)))


def plan_info(plan_id: Optional[str]) -> dict:
    """计划展示信息（名称与月度额度）。"""
    key = (plan_id or "").strip().lower().replace("_", "-")
    name = PLAN_DISPLAY_NAMES.get(key)
    if not name and key:
        name = key.replace("individual-", "").replace("teams-", "Teams ").title()
    return {"plan_id": plan_id, "name": name or None, "monthly_credits": PLAN_MONTHLY_CREDITS.get(key)}


def read_cli_api_key() -> str:
    """读取本机 CLI 凭据文件中的 API Key（配额/计划接口使用）。

    Command Code CLI 登录后会在 ``~/.commandcode/auth.json`` 保存 apiKey；
    本面板复用同一凭据，避免用户二次配置。
    """
    try:
        with open(CLI_AUTH_PATH, encoding="utf-8") as fh:
            return (json.load(fh).get("apiKey") or "").strip()
    except (OSError, ValueError):
        return ""


def fetch_usd_cny_rate(timeout: int = RATE_FETCH_TIMEOUT_SEC) -> Optional[float]:
    """获取 USD→CNY 实时汇率（open.er-api.com，免费无 Key）。

    返回 None 表示获取失败（调用方降级为仅显示美元）。
    """
    try:
        response = requests.get(
            EXCHANGE_API_URL,
            timeout=timeout,
            headers={"User-Agent": "CCGauge/0.1", "Accept": "application/json"},
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        value = (payload.get("rates") or {}).get("CNY")
        rate = float(value) if value else 0.0
        return rate if rate > 0 else None
    except Exception:  # noqa: BLE001 网络/解析异常统一降级
        return None


class AppContext:
    """共享上下文：数据库、API 客户端、同步状态、登录回调。"""

    def __init__(self, db: Database, on_login_request=None) -> None:
        self.db = db
        self.client = CommandCodeClient()
        self.on_login_request = on_login_request
        self.sync_lock = threading.Lock()
        self.syncing = False
        self._scheduler_stop = threading.Event()
        self._scheduler_thread: Optional[threading.Thread] = None
        self.reload_credentials()

    # -- 凭据 ---------------------------------------------------------------

    def reload_credentials(self) -> None:
        self.client.cookie_header = self.db.get_setting("cookie_header") or ""
        api_key = self.db.get_setting("api_key") or ""
        if not api_key:
            api_key = read_cli_api_key()
            if api_key:
                self.db.set_setting("api_key", api_key)
        self.client.api_key = api_key

    def has_cookie(self) -> bool:
        return bool(self.db.get_setting("cookie_header"))

    def has_api_key(self) -> bool:
        return bool(self.db.get_setting("api_key") or read_cli_api_key())

    # -- 范围 ---------------------------------------------------------------

    def resolve_range(self, range_key: Optional[str]) -> tuple[Optional[int], Optional[int]]:
        """把前端范围标识解析为 (start_ts, end_ts)。"""
        now = int(time.time())
        key = (range_key or "24h").strip().lower()
        if key in ("all", ""):
            return None, None
        if key == "today":
            lt = time.localtime(now)
            start = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))
            return start, now + 1
        if key == "billing":
            snapshot = self.db.latest_quota_snapshot() or {}
            start_iso = (((snapshot.get("subscription") or {}).get("data") or {}).get("currentPeriodStart"))
            start = _iso_to_ts(start_iso)
            return (start, now + 1) if start else (None, None)
        if key.endswith("h") and key[:-1].isdigit():
            return now - int(key[:-1]) * 3600, now + 1
        if key.endswith("d") and key[:-1].isdigit():
            return now - int(key[:-1]) * 86400, now + 1
        return now - 86400, now + 1

    # -- 同步 ---------------------------------------------------------------

    def refresh_quota(self, force: bool = False) -> dict:
        """拉取配额三件套并落快照（默认按最小间隔节流，避免频繁请求）。"""
        if not self.has_api_key():
            return {"ok": False, "error": "未配置 API Key"}
        if not force:
            last = _to_int(self.db.get_state("last_quota_at"), 0)
            if time.time() - last < QUOTA_MIN_INTERVAL_SEC:
                return {"ok": True, "skipped": True, "reason": "距上次配额刷新未到最小间隔"}
        try:
            bundle = self.client.fetch_quota_bundle()
        except AuthError:
            return {"ok": False, "error": "API Key 无效或已过期"}
        except CommandCodeAPIError as exc:
            return {"ok": False, "error": str(exc)}
        self.db.save_quota_snapshot(bundle)
        self.db.set_state("last_quota_at", int(time.time()))
        user = ((bundle.get("whoami") or {}).get("user") or {})
        plan_id = (((bundle.get("subscription") or {}).get("data") or {}).get("planId"))
        if user.get("userName"):
            self.db.set_setting("user_name", user.get("userName"))
        if plan_id:
            self.db.set_setting("plan_id", plan_id)
        return {"ok": True, "plan": plan_info(plan_id), "captured_at": int(time.time())}

    def should_sync_now(self) -> bool:
        """是否已到自动同步时机（避免启动/登录时做无谓请求）。"""
        interval_min = _to_int(self.db.get_setting("sync_interval_min"), DEFAULT_SYNC_INTERVAL_MIN)
        interval_min = max(SYNC_MIN_INTERVAL_MIN, min(interval_min, SYNC_MAX_INTERVAL_MIN))
        last_sync = _to_int(self.db.get_setting("last_sync_at"), 0)
        return time.time() - last_sync >= interval_min * 60

    # -- 汇率（USD→CNY，展示用） --------------------------------------------

    def refresh_rate(self, force: bool = False) -> dict:
        """获取/刷新 USD→CNY 汇率（24 小时缓存；失败时沿用旧值）。"""
        cached = self.db.get_setting("usd_cny_rate")
        fetched_at = _to_int(self.db.get_setting("usd_cny_rate_at"), 0)
        if not force and cached and time.time() - fetched_at < RATE_CACHE_SEC:
            return {"ok": True, "rate": float(cached), "fetched_at": fetched_at, "cached": True}
        rate = fetch_usd_cny_rate()
        if rate:
            now = int(time.time())
            self.db.set_setting("usd_cny_rate", str(rate))
            self.db.set_setting("usd_cny_rate_at", str(now))
            return {"ok": True, "rate": rate, "fetched_at": now, "cached": False}
        if cached:
            return {"ok": True, "rate": float(cached), "fetched_at": fetched_at,
                    "cached": True, "stale": True}
        return {"ok": False, "rate": None, "error": "汇率获取失败（将仅显示美元）"}

    def run_sync(self, mode: str = "incremental") -> dict:
        """执行一次同步（阻塞）。

        mode 语义（基于数据库已有数据规划，避免重复拉取）：
          - ``incremental``：增量追新——从最新往前翻，某页无新记录即停（日常调度，通常 1~2 次请求）
          - ``full``：历史回填——已有数据时从「最早记录」锚点继续向前补历史（断点续传）；
            空库时从最新翻到底。两种模式都不重复拉取已入库区间。
        """
        if not self.has_cookie():
            return {"ok": False, "error": "未登录：缺少网页会话凭据"}
        if not self.sync_lock.acquire(blocking=False):
            return {"ok": False, "error": "同步进行中"}
        self.syncing = True
        started = time.time()
        result = {"ok": True, "mode": mode, "inserted": 0, "pages": 0, "stop_reason": "", "error": None}
        try:
            self.reload_credentials()
            range_days = _to_int(self.db.get_setting("sync_range_days"), DEFAULT_SYNC_RANGE_DAYS)
            cutoff_ts = int(time.time() - range_days * 86400) if range_days > 0 else None
            max_pages = FULL_SYNC_MAX_PAGES if mode == "full" else INCREMENTAL_MAX_PAGES

            iterator = self._build_iterator(mode, max_pages)
            inserted_total = 0
            pages = 0
            for page in iterator:
                pages += 1
                records = page.records
                if cutoff_ts is not None:
                    records = [r for r in records
                               if r.created_ts and int(r.created_ts.timestamp()) >= cutoff_ts]
                new_count = self.db.upsert_records(records)
                inserted_total += new_count

                if new_count == 0:
                    result["stop_reason"] = "已追平（无新记录）" if mode == "incremental" else "历史已完整"
                    break
                if cutoff_ts is not None and page.earliest and page.earliest.created_ts \
                        and int(page.earliest.created_ts.timestamp()) < cutoff_ts:
                    result["stop_reason"] = "已到同步范围边界"
                    break
            result.update(inserted=inserted_total, pages=pages)
        except AuthError as exc:
            result.update(ok=False, error=f"登录态失效：{exc}")
            self.db.set_setting("cookie_valid", "0")
        except CommandCodeAPIError as exc:
            result.update(ok=False, error=str(exc))
        finally:
            self.syncing = False
            self.sync_lock.release()

        result["elapsed_sec"] = round(time.time() - started, 2)
        now = int(time.time())
        self.db.set_setting("last_sync_at", str(now))
        self.db.set_setting("last_sync_error", result.get("error") or "")
        self.db.set_state("last_sync_at", now)
        self.db.set_state("last_sync_mode", mode)
        self.db.set_state("last_sync_inserted", result.get("inserted", 0))
        if result["ok"]:
            self.refresh_quota()
        return result

    def _build_iterator(self, mode: str, max_pages: int):
        """构造翻页迭代器：回填从最早记录续传，增量从最新开始。"""
        if mode == "full":
            anchor = self.db.earliest_record()
            if anchor:
                start_cursor = encode_cursor(anchor["created_at"], anchor["id"], "", 0)
                return self.client.iter_usage(start_cursor=start_cursor, max_pages=max_pages)
        return self.client.iter_usage(max_pages=max_pages)

    def run_sync_async(self, mode: str = "incremental") -> bool:
        """后台线程执行同步。"""
        if self.syncing:
            return False
        threading.Thread(target=self.run_sync, args=(mode,), daemon=True).start()
        return True

    # -- 调度 ---------------------------------------------------------------

    def start_scheduler(self) -> None:
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return
        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()

    def stop_scheduler(self) -> None:
        self._scheduler_stop.set()

    def _scheduler_loop(self) -> None:
        while not self._scheduler_stop.wait(SCHEDULER_TICK_SEC):
            if not self.has_cookie():
                continue
            try:
                interval_min = _to_int(self.db.get_setting("sync_interval_min"), DEFAULT_SYNC_INTERVAL_MIN)
                interval_min = max(SYNC_MIN_INTERVAL_MIN, min(interval_min, SYNC_MAX_INTERVAL_MIN))
                last_sync = _to_int(self.db.get_setting("last_sync_at"), 0)
                if time.time() - last_sync >= interval_min * 60:
                    self.run_sync("incremental")
            except Exception:  # noqa: BLE001 调度循环不可中断
                continue


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _iso_to_ts(value) -> Optional[int]:
    if not value or not isinstance(value, str):
        return None
    try:
        from datetime import datetime, timezone
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())
    except ValueError:
        return None


class ApiHandler(BaseHTTPRequestHandler):
    """REST + 静态资源处理器。"""

    server_version = f"{APP_NAME}/{__version__}"
    ctx: AppContext = None  # 由 Server 注入

    def log_message(self, fmt, *args):  # noqa: A003 抑制默认访问日志
        pass

    # -- 分发 ---------------------------------------------------------------

    def do_GET(self):  # noqa: N802
        self._safe_dispatch("GET")

    def do_POST(self):  # noqa: N802
        self._safe_dispatch("POST")

    def _safe_dispatch(self, method: str) -> None:
        try:
            self._dispatch(method)
        except Exception as exc:  # noqa: BLE001 兜底避免连接悬挂
            self._send_json({"ok": False, "error": f"内部错误: {exc}"}, status=500)

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path.startswith("/api/"):
            route = _ROUTES.get((method, path))
            if route is None:
                self._send_json({"ok": False, "error": f"未知接口: {method} {path}"}, status=404)
                return
            getattr(self, route)(query)
            return
        if method == "GET":
            self._serve_static(path)
            return
        self._send_json({"ok": False, "error": "not found"}, status=404)

    # -- 工具 ---------------------------------------------------------------

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body_json(self) -> dict:
        length = _to_int(self.headers.get("Content-Length"), 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    def _serve_static(self, path: str) -> None:
        rel = unquote(path).lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(WEB_ROOT, rel))
        if not full.startswith(os.path.normpath(WEB_ROOT)) or not os.path.isfile(full):
            self.send_error(404, "Not Found")
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype if "text/" not in ctype else f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- 接口实现 -----------------------------------------------------------

    def _api_status(self, query) -> None:
        ctx = self.ctx
        db = ctx.db
        sync_state = db.get_sync_state()
        data = db.data_range()
        snapshot = db.latest_quota_snapshot() or {}
        plan_id = db.get_setting("plan_id")
        self._send_json({
            "ok": True,
            "version": __version__,
            "logged_in": ctx.has_cookie(),
            "cookie_valid": db.get_setting("cookie_valid") != "0" and ctx.has_cookie(),
            "api_key_set": ctx.has_api_key(),
            "user_name": db.get_setting("user_name"),
            "plan": plan_info(plan_id),
            "syncing": ctx.syncing,
            "sync": {
                "last_sync_at": _to_int(db.get_setting("last_sync_at"), 0),
                "last_error": db.get_setting("last_sync_error") or None,
                "interval_min": _to_int(db.get_setting("sync_interval_min"), DEFAULT_SYNC_INTERVAL_MIN),
                "range_days": _to_int(db.get_setting("sync_range_days"), DEFAULT_SYNC_RANGE_DAYS),
                "mode": sync_state.get("last_sync_mode"),
                "inserted": _to_int(sync_state.get("last_sync_inserted"), 0),
            },
            "data": data,
            "quota_captured_at": snapshot.get("_captured_at"),
        })

    def _api_overview(self, query) -> None:
        start, end = self.ctx.resolve_range(_first(query, "range"))
        self._send_json({"ok": True, "overview": self.ctx.db.overview(start, end)})

    def _api_series(self, query) -> None:
        start, end = self.ctx.resolve_range(_first(query, "range"))
        kind = (_first(query, "kind") or "hour").lower()
        tz = _to_int(_first(query, "tz"), local_tz_offset_sec())
        start = start if start is not None else 0
        end = end if end is not None else int(time.time()) + 1
        db = self.ctx.db
        series = db.series_hourly(start, end, tz) if kind == "hour" else db.series_daily(start, end, tz)
        self._send_json({"ok": True, "kind": kind, "series": series})

    def _api_models(self, query) -> None:
        start, end = self.ctx.resolve_range(_first(query, "range"))
        self._send_json({"ok": True, "models": self.ctx.db.model_breakdown(start, end)})

    def _api_modes(self, query) -> None:
        start, end = self.ctx.resolve_range(_first(query, "range"))
        self._send_json({"ok": True, "modes": self.ctx.db.mode_breakdown(start, end)})

    def _api_daily_models(self, query) -> None:
        start, end = self.ctx.resolve_range(_first(query, "range"))
        tz = _to_int(_first(query, "tz"), local_tz_offset_sec())
        start = start if start is not None else 0
        end = end if end is not None else int(time.time()) + 1
        self._send_json({"ok": True, "rows": self.ctx.db.daily_model_breakdown(start, end, tz)})

    def _api_records(self, query) -> None:
        start, end = self.ctx.resolve_range(_first(query, "range"))
        payload = self.ctx.db.query_records(
            page=_to_int(_first(query, "page"), 1),
            page_size=_to_int(_first(query, "page_size"), 50),
            model=_first(query, "model"),
            mode=_first(query, "mode"),
            start_ts=start,
            end_ts=end,
        )
        self._send_json({"ok": True, **payload})

    def _api_models_list(self, query) -> None:
        self._send_json({"ok": True, "models": self.ctx.db.list_models()})

    def _api_quota(self, query) -> None:
        ctx = self.ctx
        snapshot = ctx.db.latest_quota_snapshot() or {}
        credits = (snapshot.get("credits") or {}).get("credits") or {}
        windows = (snapshot.get("credits") or {}).get("windowLimits") or {}
        subscription = (snapshot.get("subscription") or {}).get("data") or {}
        summary = snapshot.get("summary") or {}
        plan_id = subscription.get("planId") or ctx.db.get_setting("plan_id")
        self._send_json({
            "ok": True,
            "captured_at": snapshot.get("_captured_at"),
            "plan": plan_info(plan_id),
            "subscription": {
                "status": subscription.get("status"),
                "current_period_start": subscription.get("currentPeriodStart"),
                "current_period_end": subscription.get("currentPeriodEnd"),
                "cancel_at_period_end": subscription.get("cancelAtPeriodEnd"),
            },
            "credits": {
                "monthly": credits.get("monthlyCredits", 0),
                "purchased": credits.get("purchasedCredits", 0),
                "free": credits.get("freeCredits", 0),
                "below_threshold": credits.get("belowThreshold"),
            },
            "windows": {
                "five_hour": _window_view(windows.get("fiveHour")),
                "weekly": _window_view(windows.get("weekly")),
            },
            "summary": {
                "total_count": summary.get("totalCount"),
                "total_cost": summary.get("totalCost"),
                "total_tokens_in": summary.get("totalTokensIn"),
                "total_tokens_out": summary.get("totalTokensOut"),
                "success_rate": summary.get("successRate"),
                "period_basis": summary.get("periodBasis"),
            },
        })

    def _api_settings_get(self, query) -> None:
        db = self.ctx.db
        settings = db.all_settings(mask_secrets=True)
        # 未显式设置时回填「生效值」，避免前端下拉框误显示为第一项
        settings["sync_interval_min"] = str(
            _to_int(db.get_setting("sync_interval_min"), DEFAULT_SYNC_INTERVAL_MIN))
        settings["sync_range_days"] = str(
            _to_int(db.get_setting("sync_range_days"), DEFAULT_SYNC_RANGE_DAYS))
        settings["currency_mode"] = db.get_setting("currency_mode") or "both"
        self._send_json({
            "ok": True,
            "settings": settings,
            "options": {
                "sync_interval_min": [1, 5, 15, 30],
                "sync_range_days": [30, 60, 90, 180, 0],
                "currency_mode": list(CURRENCY_MODES),
            },
        })

    def _api_settings_set(self, query) -> None:
        payload = self._read_body_json()
        db = self.ctx.db
        allowed = {"sync_interval_min", "sync_range_days", "theme", "lang",
                   "cookie_header", "api_key", "currency_mode"}
        updated = {}
        for key, value in payload.items():
            if key not in allowed:
                continue
            if key == "sync_interval_min":
                value = str(max(SYNC_MIN_INTERVAL_MIN, min(_to_int(value, DEFAULT_SYNC_INTERVAL_MIN), SYNC_MAX_INTERVAL_MIN)))
            elif key == "sync_range_days":
                value = str(max(0, _to_int(value, DEFAULT_SYNC_RANGE_DAYS)))
            elif key == "currency_mode":
                if value not in CURRENCY_MODES:
                    continue
            db.set_setting(key, None if value in (None, "") else str(value))
            updated[key] = True
        self.ctx.reload_credentials()
        self._send_json({"ok": True, "updated": sorted(updated.keys())})

    def _api_rate(self, query) -> None:
        """USD→CNY 汇率（24h 缓存；force=1 强制刷新）。"""
        force = (_first(query, "force") or "") in ("1", "true")
        result = self.ctx.refresh_rate(force=force)
        result["mode"] = self.ctx.db.get_setting("currency_mode") or "both"
        self._send_json(result)

    def _api_sync(self, query) -> None:
        payload = self._read_body_json()
        mode = (payload.get("mode") or "incremental").lower()
        if mode not in ("full", "incremental"):
            mode = "incremental"
        started = self.ctx.run_sync_async(mode)
        self._send_json({"ok": started, "mode": mode, "started": started})

    def _api_sync_wait(self, query) -> None:
        payload = self._read_body_json()
        mode = (payload.get("mode") or "incremental").lower()
        result = self.ctx.run_sync("full" if mode == "full" else "incremental")
        self._send_json(result)

    def _api_quota_refresh(self, query) -> None:
        self._send_json(self.ctx.refresh_quota(force=True))

    def _api_login(self, query) -> None:
        if self.ctx.on_login_request:
            self.ctx.on_login_request()
            self._send_json({"ok": True, "message": "登录窗口已打开"})
        else:
            self._send_json({"ok": False, "error": "当前环境不支持打开登录窗口"}, status=400)

    def _api_logout(self, query) -> None:
        db = self.ctx.db
        db.set_setting("cookie_header", None)
        db.set_setting("cookie_valid", "0")
        db.set_setting("user_name", None)
        db.set_setting("plan_id", None)
        self.ctx.reload_credentials()
        self._send_json({"ok": True})

    def _api_verify(self, query) -> None:
        """校验两个通道的凭据有效性。"""
        ctx = self.ctx
        ctx.reload_credentials()
        cookie_ok = ctx.client.validate_cookie() if ctx.has_cookie() else False
        api_key_ok = ctx.client.validate_api_key() if ctx.has_api_key() else False
        ctx.db.set_setting("cookie_valid", "1" if cookie_ok else "0")
        self._send_json({"ok": True, "cookie_valid": cookie_ok, "api_key_valid": api_key_ok})


def _first(query: dict, key: str) -> Optional[str]:
    values = query.get(key)
    return values[0] if values else None


def _window_view(window: Optional[dict]) -> Optional[dict]:
    """窗口限制视图（used/cap/剩余比例/重置时间）。"""
    if not window:
        return None
    used = float(window.get("used") or 0)
    cap = float(window.get("cap") or 0)
    return {
        "used": used,
        "cap": cap,
        "remaining": max(cap - used, 0),
        "percent": (min(used / cap * 100, 100) if cap > 0 else 0),
        "exceeded": bool(window.get("exceeded")),
        "reset_at": window.get("resetAt"),
    }


_ROUTES = {
    ("GET", "/api/status"): "_api_status",
    ("GET", "/api/overview"): "_api_overview",
    ("GET", "/api/series"): "_api_series",
    ("GET", "/api/models"): "_api_models",
    ("GET", "/api/modes"): "_api_modes",
    ("GET", "/api/daily-models"): "_api_daily_models",
    ("GET", "/api/records"): "_api_records",
    ("GET", "/api/models-list"): "_api_models_list",
    ("GET", "/api/quota"): "_api_quota",
    ("GET", "/api/rate"): "_api_rate",
    ("GET", "/api/settings"): "_api_settings_get",
    ("GET", "/api/verify"): "_api_verify",
    ("POST", "/api/settings"): "_api_settings_set",
    ("POST", "/api/sync"): "_api_sync",
    ("POST", "/api/sync/wait"): "_api_sync_wait",
    ("POST", "/api/quota/refresh"): "_api_quota_refresh",
    ("POST", "/api/login"): "_api_login",
    ("POST", "/api/logout"): "_api_logout",
}


class Server:
    """HTTP 服务包装（启动/停止）。"""

    def __init__(self, ctx: AppContext, host: str = "127.0.0.1", port: int = 0) -> None:
        ApiHandler.ctx = ctx
        self.httpd = ThreadingHTTPServer((host, port), ApiHandler)
        self.host, self.port = self.httpd.server_address[0], self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:  # noqa: BLE001
            pass
