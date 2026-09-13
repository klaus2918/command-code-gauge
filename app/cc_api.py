# -*- coding: utf-8 -*-
"""Command Code API 客户端（双通道认证）。

通道（实测结论，见 plan.md 附录 C）：
- Cookie 通道（网页登录态，auth.py 捕获）：``/internal/usage`` 请求级明细
- API Key 通道（``~/.commandcode/auth.json`` 的 apiKey）：``/alpha/billing/*``、``/alpha/whoami``、``/alpha/usage/summary``

实现约束：
- 必须携带 ``User-Agent: cli``（Python 默认 UA 被 Cloudflare 拒绝，错误码 1010）
- ``/internal/usage`` 的 limit 上限 100；cursor 为 keyset 锚点 ``{createdAt,id,since,seen}``
- ``tokensIn`` / ``tokensOut`` / ``durationTotal`` 为字符串数字，需转换
- 锚点翻页可无限回溯：以每批最早记录的 createdAt 构造下一个 cursor
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterator, Optional

import requests

API_BASE_URL = "https://api.commandcode.ai"
USAGE_LIMIT_MAX = 100
REQUEST_TIMEOUT_SEC = 30
RETRY_BACKOFF_SEC = (0.5, 1.5, 3.0)
CLI_VERSION = "1.53.1"
PAGE_TERMINATE_GUARD = 200

BASE_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "cli",
    "x-command-code-version": CLI_VERSION,
    "x-cli-environment": "production",
}


class CommandCodeAPIError(Exception):
    """API 调用失败（网络/服务端/协议）。"""


class AuthError(CommandCodeAPIError):
    """认证失败（401）：cookie 过期或 apiKey 无效。"""


class RateLimitError(CommandCodeAPIError):
    """限流（429）。"""


def _to_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_iso_utc(value: str) -> Optional[datetime]:
    """解析 ISO 8601（含 Z 后缀）为 UTC datetime。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def encode_cursor(created_at: str, record_id: str, since: str, seen: int = 0) -> str:
    """构造 keyset 锚点 cursor（base64url，无填充）。"""
    payload = {"createdAt": created_at, "id": record_id, "since": since, "seen": seen}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict:
    """解码 cursor；失败返回空 dict。"""
    if not cursor:
        return {}
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


@dataclass
class UsageRecord:
    """归一化后的请求级用量记录。"""

    id: str
    created_at: str            # 原始 ISO 字符串（UTC）
    tokens_in: int
    tokens_out: int
    duration_ms: int
    status: str
    mode: str
    type: str
    model: str
    cost_total: float
    cost_input: float
    cost_output: float
    cost_cache: float
    trace_id: str
    created_ts: Optional[datetime] = None
    raw: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        """总 Token 口径：输入（含缓存命中）+ 输出。"""
        return self.tokens_in + self.tokens_out

    @classmethod
    def from_api(cls, item: dict) -> "UsageRecord":
        meta = item.get("meta") or {}
        created_at = str(item.get("createdAt") or "")
        return cls(
            id=str(item.get("id") or ""),
            created_at=created_at,
            tokens_in=_to_int(item.get("tokensIn")),
            tokens_out=_to_int(item.get("tokensOut")),
            duration_ms=_to_int(item.get("durationTotal")),
            status=str(item.get("status") or ""),
            mode=str(item.get("mode") or ""),
            type=str(item.get("type") or ""),
            model=str(meta.get("model") or ""),
            cost_total=_to_float(meta.get("totalCost")),
            cost_input=_to_float(meta.get("inputCost")),
            cost_output=_to_float(meta.get("outputCost")),
            cost_cache=_to_float(meta.get("cacheCost")),
            trace_id=str(meta.get("traceId") or ""),
            created_ts=parse_iso_utc(created_at),
            raw=item,
        )


@dataclass
class UsagePage:
    """一页明细响应。"""

    records: list[UsageRecord]
    next_cursor: Optional[str]
    limit: int
    window: dict = field(default_factory=dict)
    period_basis: str = ""

    @property
    def earliest(self) -> Optional[UsageRecord]:
        """本批最早（时间最小）的记录，用于构造下一个锚点。"""
        if not self.records:
            return None
        return min(self.records, key=lambda r: (r.created_at, r.id))


class CommandCodeClient:
    """Command Code API 客户端。

    Args:
        cookie_header: 网页登录态 cookie 头（``name=value; name2=value2``）
        api_key: ``~/.commandcode/auth.json`` 中的 apiKey
        base_url: API 基址
        timeout: 单请求超时（秒）
    """

    def __init__(
        self,
        cookie_header: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: str = API_BASE_URL,
        timeout: int = REQUEST_TIMEOUT_SEC,
    ) -> None:
        self.cookie_header = cookie_header or ""
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    # -- 内部 ---------------------------------------------------------------

    def _headers(self, channel: str) -> dict:
        """构造请求头。channel: ``cookie`` | ``apikey``。"""
        headers = dict(BASE_HEADERS)
        if channel == "cookie":
            if not self.cookie_header:
                raise AuthError("未配置网页登录态 cookie")
            headers["Cookie"] = self.cookie_header
        elif channel == "apikey":
            if not self.api_key:
                raise AuthError("未配置 API Key")
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            raise ValueError(f"未知认证通道: {channel}")
        return headers

    def _get(self, path: str, params: Optional[dict], channel: str) -> dict:
        """带重试的 GET；返回解析后的 JSON。"""
        url = self.base_url + path
        headers = self._headers(channel)
        last_error: Optional[Exception] = None
        for attempt in range(len(RETRY_BACKOFF_SEC) + 1):
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = CommandCodeAPIError(f"{path} 网络错误: {exc}")
                if attempt < len(RETRY_BACKOFF_SEC):
                    time.sleep(RETRY_BACKOFF_SEC[attempt])
                    continue
                raise last_error from exc

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise CommandCodeAPIError(f"{path} 响应非 JSON: {resp.text[:200]}") from exc
            if resp.status_code in (401, 403):
                raise AuthError(f"{path} 认证失败（HTTP {resp.status_code}）")
            if resp.status_code == 429:
                if attempt < len(RETRY_BACKOFF_SEC):
                    time.sleep(RETRY_BACKOFF_SEC[attempt])
                    continue
                raise RateLimitError(f"{path} 触发限流（HTTP 429）")
            if 500 <= resp.status_code < 600 and attempt < len(RETRY_BACKOFF_SEC):
                time.sleep(RETRY_BACKOFF_SEC[attempt])
                continue
            raise CommandCodeAPIError(f"{path} 请求失败（HTTP {resp.status_code}）: {resp.text[:200]}")
        raise last_error or CommandCodeAPIError(f"{path} 请求失败")

    # -- 明细（cookie 通道） ------------------------------------------------

    def fetch_usage_page(self, limit: int = USAGE_LIMIT_MAX, cursor: Optional[str] = None) -> UsagePage:
        """拉取一页请求级明细。"""
        limit = max(1, min(int(limit), USAGE_LIMIT_MAX))
        params: dict = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        body = self._get("/internal/usage", params, "cookie")
        records = [UsageRecord.from_api(item) for item in (body.get("usages") or [])]
        return UsagePage(
            records=records,
            next_cursor=body.get("nextCursor"),
            limit=_to_int(body.get("limit"), limit),
            window=body.get("window") or {},
            period_basis=str(body.get("periodBasis") or ""),
        )

    def iter_usage(
        self,
        start_cursor: Optional[str] = None,
        anchor_since: Optional[str] = None,
        on_page: Optional[Callable[[UsagePage, int], None]] = None,
        max_pages: int = PAGE_TERMINATE_GUARD,
        stop_when: Optional[Callable[[UsageRecord], bool]] = None,
    ) -> Iterator[UsagePage]:
        """按锚点持续翻页（可回溯全部历史）。

        翻页规则（实测）：下一批锚点 = 本批最早记录的 ``createdAt``，``seen=0``；
        返回空批即终止。``stop_when`` 用于增量模式（遇到已知记录即停）。

        Args:
            start_cursor: 起始 cursor；缺省从最新开始
            anchor_since: 锚点中的 since 字段（窗口起点，服务端仅回显）
            on_page: 每页回调（page, index）
            max_pages: 最大页数保护
            stop_when: 记录级停止条件（返回 True 则结束迭代）
        """
        cursor = start_cursor
        for index in range(max_pages):
            page = self.fetch_usage_page(USAGE_LIMIT_MAX, cursor)
            if not page.records:
                return
            yield page
            if on_page:
                on_page(page, index)
            if stop_when and any(stop_when(r) for r in page.records):
                return
            earliest = page.earliest
            if earliest is None:
                return
            cursor = encode_cursor(earliest.created_at, earliest.id, anchor_since or "", 0)
            if index + 1 >= max_pages:
                return

    def validate_cookie(self) -> bool:
        """校验 cookie 通道是否有效（拉 1 条明细）。"""
        try:
            page = self.fetch_usage_page(limit=1)
            return True
        except CommandCodeAPIError:
            return False

    # -- 配额与计划（apiKey 通道） -----------------------------------------

    def _with_org(self, params: Optional[dict], org_id: Optional[str]) -> Optional[dict]:
        params = dict(params or {})
        if org_id:
            params["orgId"] = org_id
        return params or None

    def fetch_whoami(self) -> dict:
        """用户信息（含 org 与 spend limits）。"""
        return self._get("/alpha/whoami", {"limits": "1"}, "apikey")

    def fetch_credits(self, org_id: Optional[str] = None) -> dict:
        """信用余额 + 窗口限制（5 小时 / 每周）。"""
        return self._get("/alpha/billing/credits", self._with_org(None, org_id), "apikey")

    def fetch_subscription(self, org_id: Optional[str] = None) -> dict:
        """订阅与计费周期。"""
        return self._get("/alpha/billing/subscriptions", self._with_org(None, org_id), "apikey")

    def fetch_summary(self, org_id: Optional[str] = None, since: Optional[str] = None) -> dict:
        """服务端汇总（请求数 / 成本 / token 进出 / 成功率）。"""
        return self._get("/alpha/usage/summary", self._with_org({"since": since}, org_id), "apikey")

    def fetch_quota_bundle(self) -> dict:
        """一次性拉取配额三件套（whoami → credits/subscription → summary）。"""
        whoami = self.fetch_whoami()
        org_id = ((whoami.get("org") or {}).get("id")) or None
        credits = self.fetch_credits(org_id)
        subscription = self.fetch_subscription(org_id)
        period_start = ((subscription.get("data") or {}).get("currentPeriodStart")) or None
        summary = self.fetch_summary(org_id, period_start)
        return {
            "whoami": whoami,
            "credits": credits,
            "subscription": subscription,
            "summary": summary,
            "org_id": org_id,
        }

    def validate_api_key(self) -> bool:
        """校验 apiKey 通道是否有效。"""
        try:
            self.fetch_whoami()
            return True
        except CommandCodeAPIError:
            return False
