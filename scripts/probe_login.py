# -*- coding: utf-8 -*-
"""登录原型：捕获 Command Code 网页登录态并抓取 /internal/usage 真实响应。

任务目标（变更 command-code-gauge · 任务 1，验证阻塞项 B1/B2/B3）：
  1. 验证 pywebview(WebView2) 能读取 commandcode.ai 域全部 cookie（含 HttpOnly）
  2. 抓取 /internal/usage 首屏响应，确认字段结构与分页游标形态
  3. 验证同一 cookie 能否访问 /alpha/* 配额接口（决定认证通道设计）

用法：
    python scripts/probe_login.py
    弹出登录窗口 → 手动完成登录 → 自动捕获 cookie 并抓取接口 → 结果落盘 data/probe/
"""
from __future__ import annotations

import json
import os
import threading
import time

import requests
import webview

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE_DIR = os.path.join(BASE_DIR, "data", "probe")
WEBVIEW_DATA_DIR = os.path.join(BASE_DIR, "data", "webview")
SIGNIN_URL = "https://commandcode.ai/signin"
SITE_HOST = "commandcode.ai"
API_BASE = "https://api.commandcode.ai"
POLL_INTERVAL_SEC = 1.5
MAX_WAIT_SEC = 900
MAX_API_ATTEMPTS = 5

DONE = threading.Event()

API_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "cli",
    "x-command-code-version": "1.53.1",
    "x-cli-environment": "production",
}


def log(message: str) -> None:
    """输出进度（同时便于后台运行日志采集）。"""
    print(message, flush=True)


def normalize_cookies(raw_cookies) -> list[dict]:
    """pywebview 返回 SimpleCookie 列表，规整为 [{name, value, domain, path, ...}]。"""
    result: list[dict] = []
    for raw in raw_cookies or []:
        try:
            names = list(raw.keys())
        except Exception:
            continue
        for name in names:
            morsel = raw[name]
            try:
                result.append({
                    "name": name,
                    "value": morsel.value,
                    "domain": morsel["domain"],
                    "path": morsel["path"],
                    "httponly": bool(morsel["httponly"]),
                    "secure": bool(morsel["secure"]),
                })
            except Exception:
                continue
    return result


def build_cookie_header(cookies: list[dict]) -> str:
    """拼接为 HTTP Cookie 头。"""
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def save_json(name: str, payload) -> str:
    os.makedirs(PROBE_DIR, exist_ok=True)
    path = os.path.join(PROBE_DIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def _safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return resp.text[:2000]


def probe_api(cookies: list[dict]) -> dict:
    """用捕获的 cookie 依次请求明细与配额接口，返回结构化结果。"""
    headers = dict(API_HEADERS, Cookie=build_cookie_header(cookies))
    outcome: dict = {}

    try:
        resp = requests.get(
            f"{API_BASE}/internal/usage", params={"limit": 5}, headers=headers, timeout=30
        )
        outcome["internal_usage"] = {"status": resp.status_code, "body": _safe_json(resp)}
    except Exception as exc:  # noqa: BLE001
        outcome["internal_usage"] = {"error": repr(exc)}

    for label, path in (
        ("billing_credits", "/alpha/billing/credits"),
        ("billing_subscriptions", "/alpha/billing/subscriptions"),
        ("whoami", "/alpha/whoami?limits=1"),
    ):
        try:
            resp = requests.get(API_BASE + path, headers=headers, timeout=30)
            outcome[label] = {"status": resp.status_code, "body": _safe_json(resp)}
        except Exception as exc:  # noqa: BLE001
            outcome[label] = {"error": repr(exc)}
    return outcome


def report_usage_shape(outcome: dict) -> None:
    """打印 /internal/usage 响应结构摘要（字段名、条数、分页字段）。"""
    usage = outcome.get("internal_usage", {})
    log(f"[probe] /internal/usage → HTTP {usage.get('status')}")
    body = usage.get("body")
    if not isinstance(body, dict):
        log(f"[probe] 响应正文: {str(body)[:800]}")
        return
    log(f"[probe] 顶层字段: {sorted(body.keys())}")
    items = None
    for key in ("data", "items", "records", "usage"):
        value = body.get(key)
        if isinstance(value, list):
            items = value
            log(f"[probe] 记录数组字段名: {key}")
            break
    if items:
        log(f"[probe] 记录条数: {len(items)}；首条字段: {sorted(items[0].keys())}")
        log("[probe] 首条样例:")
        log(json.dumps(items[0], ensure_ascii=False, indent=2)[:2500])
    for key in ("nextCursor", "next_cursor", "cursor", "hasMore", "has_more", "page", "total"):
        if key in body:
            log(f"[probe] 分页/统计字段 {key} = {str(body[key])[:160]}")


def watch_login(window) -> None:
    """轮询登录窗口：URL 离开 /signin 后捕获 cookie 并立即验证接口。"""
    deadline = time.time() + MAX_WAIT_SEC
    attempts = 0
    while time.time() < deadline and not DONE.is_set():
        try:
            current_url = window.get_current_url() or ""
        except Exception:  # noqa: BLE001 窗口未就绪/已销毁
            time.sleep(POLL_INTERVAL_SEC)
            continue

        left_signin = SITE_HOST in current_url and "/signin" not in current_url
        if left_signin and attempts < MAX_API_ATTEMPTS:
            cookies = normalize_cookies(window.get_cookies())
            if cookies:
                attempts += 1
                log(f"[probe] 第 {attempts} 次尝试：捕获 {len(cookies)} 个 cookie（URL={current_url}）")
                for c in cookies:
                    log(f"  - {c['name']} (len={len(c['value'])}, domain={c['domain']}, "
                        f"httponly={c['httponly']})")
                outcome = probe_api(cookies)
                if outcome.get("internal_usage", {}).get("status") == 200:
                    save_json("cookies.json", cookies)
                    save_json("api_probe.json", outcome)
                    log("[probe] 登录态有效，结果已保存到 data/probe/")
                    report_usage_shape(outcome)
                    for label in ("billing_credits", "billing_subscriptions", "whoami"):
                        item = outcome.get(label, {})
                        log(f"[probe] {label} → HTTP {item.get('status')}")
                    log("[probe] === DONE ===")
                    DONE.set()
                    time.sleep(1.0)
                    try:
                        window.destroy()
                    except Exception:  # noqa: BLE001
                        pass
                    return
                log(f"[probe] 明细接口 HTTP {outcome.get('internal_usage', {}).get('status')}，继续等待登录完成")
        time.sleep(POLL_INTERVAL_SEC)

    if not DONE.is_set():
        log("[probe] 超时或窗口关闭：未捕获有效登录态")


def main() -> None:
    os.makedirs(WEBVIEW_DATA_DIR, exist_ok=True)
    window = webview.create_window(
        "CCGauge 登录原型 - 请完成登录",
        SIGNIN_URL,
        width=780,
        height=700,
    )
    threading.Thread(target=watch_login, args=(window,), daemon=True).start()
    webview.start(private_mode=False, storage_path=WEBVIEW_DATA_DIR)
    log("[probe] 窗口已关闭，进程退出")


if __name__ == "__main__":
    main()
