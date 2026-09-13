# -*- coding: utf-8 -*-
"""登录模块：WebView 登录窗口与凭据捕获。

实测要点（见 plan.md 附录 C1）：
- 登录页为站内表单（``https://commandcode.ai/signin``），登录成功后跳转站内页面
- 会话凭据为 HttpOnly cookie（``__Secure-commandcode_prod_.session_token`` 等）
- pywebview(WebView2) 的 ``window.get_cookies()`` 可读取 HttpOnly cookie
- 捕获后立即用 ``/internal/usage`` 校验，避免误存未完成的登录态

用法（主线程创建窗口，另起线程监听）：

    window = webview.create_window("登录", build_signin_url(), ...)
    watcher = LoginWatcher(window, on_success=lambda header, user: ...)
    watcher.start()
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from .cc_api import CommandCodeClient

SIGNIN_URL = "https://commandcode.ai/signin"
SITE_HOST = "commandcode.ai"
POLL_INTERVAL_SEC = 1.5
MAX_WAIT_SEC = 900
MAX_VALIDATE_ATTEMPTS = 8
SESSION_COOKIE_MARKER = "commandcode_prod"


def build_signin_url() -> str:
    """登录页地址。"""
    return SIGNIN_URL


def normalize_cookies(raw_cookies) -> list[dict]:
    """把 pywebview 返回的 SimpleCookie 列表规整为字典列表。"""
    result: list[dict] = []
    for raw in raw_cookies or []:
        try:
            names = list(raw.keys())
        except Exception:  # noqa: BLE001 兼容非预期类型
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
            except Exception:  # noqa: BLE001
                continue
    return result


def serialize_cookie_header(cookies: list[dict]) -> str:
    """序列化为 HTTP Cookie 头（全量保留，含 HttpOnly 会话凭据）。"""
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))


def has_session_cookie(cookies: list[dict]) -> bool:
    """是否包含会话凭据（按名称特征判断）。"""
    return any(SESSION_COOKIE_MARKER in (c.get("name") or "") for c in cookies)


def validate_cookie_header(cookie_header: str) -> bool:
    """用明细接口验证登录态是否真正生效。"""
    if not cookie_header:
        return False
    client = CommandCodeClient(cookie_header=cookie_header)
    return client.validate_cookie()


class LoginWatcher:
    """轮询登录窗口，捕获登录态并回调。

    Args:
        window: pywebview 窗口对象
        on_success: 成功回调 ``fn(cookie_header, cookie_count)``
        on_cancelled: 窗口关闭或超时回调
        validate: 是否用接口验证（默认 True；置 False 仅按 URL+cookie 判定）
    """

    def __init__(
        self,
        window,
        on_success: Callable[[str, int], None],
        on_cancelled: Optional[Callable[[], None]] = None,
        validate: bool = True,
    ) -> None:
        self.window = window
        self.on_success = on_success
        self.on_cancelled = on_cancelled
        self.validate = validate
        self.done = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="ccgauge-login")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        deadline = time.time() + MAX_WAIT_SEC
        attempts = 0
        while not self._stop.is_set() and time.time() < deadline:
            url = self._current_url()
            if url is None:
                break  # 窗口已关闭
            if SITE_HOST in url and "/signin" not in url and attempts < MAX_VALIDATE_ATTEMPTS:
                cookies = normalize_cookies(self._get_cookies())
                header = serialize_cookie_header(cookies)
                if header and (not self.validate or has_session_cookie(cookies)):
                    attempts += 1
                    if not self.validate or validate_cookie_header(header):
                        self.done = True
                        self._stop.set()
                        self.on_success(header, len(cookies))
                        return
            self._stop.wait(POLL_INTERVAL_SEC)
        if not self.done and self.on_cancelled:
            self.on_cancelled()

    def _current_url(self) -> Optional[str]:
        """当前 URL；窗口不可用时返回 None。"""
        try:
            return self.window.get_current_url() or ""
        except Exception:  # noqa: BLE001 窗口未就绪或已销毁
            return None if not self._window_alive() else ""

    def _window_alive(self) -> bool:
        try:
            import webview
            return self.window in webview.windows
        except Exception:  # noqa: BLE001
            return False

    def _get_cookies(self):
        try:
            return self.window.get_cookies()
        except Exception:  # noqa: BLE001
            return []
