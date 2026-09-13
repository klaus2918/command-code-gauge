# -*- coding: utf-8 -*-
"""应用壳：pywebview 窗口 + 系统托盘 + 单实例守卫 + js_api。

启动流程：
1. 单实例守卫（命名互斥体；已运行则激活旧窗口并退出）
2. 初始化数据目录与数据库（开发态 ``项目/data``；打包后 ``exe 同目录/data``）
3. 启动本地 HTTP 服务（127.0.0.1 随机端口）
4. 创建主窗口（加载本地前端）与隐藏登录窗口
5. 托盘图标（显示窗口 / 立即同步 / 退出）
6. 已登录时启动后台调度，并在数据为空时自动全量同步
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import sys
import threading
import time

import webview

from . import APP_TITLE, __version__
from .auth import LoginWatcher, build_signin_url
from .db import Database
from .server import DEFAULT_SYNC_INTERVAL_MIN, DEFAULT_SYNC_RANGE_DAYS, AppContext, Server

WINDOW_SIZE = (1280, 840)
WINDOW_MIN_SIZE = (1000, 640)
LOGIN_WINDOW_SIZE = (780, 700)
MUTEX_NAME = "CCGauge_SingleInstance_Mutex"
ERROR_ALREADY_EXISTS = 183

_quitting = False
_tray_ready = False
_watcher_ref: dict = {"watcher": None, "window": None}


def base_dir() -> str:
    """应用根目录（开发态为项目目录，打包后为 exe 目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    """数据目录（数据库与 WebView 存储）。"""
    path = os.path.join(base_dir(), "data")
    os.makedirs(path, exist_ok=True)
    return path


def diag_log(message: str) -> None:
    """诊断日志（打包后无控制台，落盘便于排查）。"""
    print(message, flush=True)
    try:
        with open(os.path.join(data_dir(), "app.log"), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + message + "\n")
    except OSError:
        pass


def asset_path(name: str) -> str:
    """资源文件路径（打包后走 _MEIPASS）。"""
    if getattr(sys, "frozen", False):
        root = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        candidate = os.path.join(root, "assets", name)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(base_dir(), "assets", name)


# -- 单实例 -----------------------------------------------------------------


def _activate_existing_instance() -> bool:
    """激活已运行实例的主窗口（按标题枚举）。"""
    user32 = ctypes.windll.user32
    found = {"hwnd": None}

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _on_window(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if "CCGauge" in buf.value and "Login" not in buf.value:
            found["hwnd"] = hwnd
            return False
        return True

    user32.EnumWindows(_on_window, 0)
    hwnd = found["hwnd"]
    if not hwnd:
        return False
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        else:
            user32.ShowWindow(hwnd, 5)   # SW_SHOW
        user32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass
    return True


def ensure_single_instance():
    """命名互斥体守卫；已有实例时激活其窗口并退出当前进程。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        if handle:
            kernel32.CloseHandle(handle)
        for _ in range(20):
            if _activate_existing_instance():
                break
            time.sleep(0.5)
        sys.exit(0)
    return handle


# -- 托盘 -------------------------------------------------------------------


class TrayIcon:
    """系统托盘图标（pystray）。"""

    def __init__(self, icon_path: str, on_show, on_quit, on_sync) -> None:
        self.icon_path = icon_path
        self.on_show = on_show
        self.on_quit = on_quit
        self.on_sync = on_sync
        self._icon = None

    def start(self) -> bool:
        global _tray_ready
        try:
            from PIL import Image, ImageDraw
            import pystray

            if self.icon_path and os.path.isfile(self.icon_path):
                image = Image.open(self.icon_path).convert("RGBA")
            else:
                image = self._fallback_image()
            menu = pystray.Menu(
                pystray.MenuItem("显示窗口", self._show, default=True),
                pystray.MenuItem("立即同步", self._sync),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit),
            )
            self._icon = pystray.Icon("CCGauge", image, "CCGauge - Command Code 用量面板", menu)
            threading.Thread(target=self._icon.run, daemon=True).start()
            _tray_ready = True
            return True
        except Exception as exc:  # noqa: BLE001
            diag_log(f"[tray] 托盘启动失败: {exc}")
            _tray_ready = False
            return False

    @staticmethod
    def _fallback_image():
        """无图标文件时生成占位图标。"""
        from PIL import Image, ImageDraw
        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((4, 4, size - 4, size - 4), fill=(59, 130, 246, 255))
        draw.rectangle((20, 26, 44, 34), fill=(255, 255, 255, 255))
        return image

    def stop(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:  # noqa: BLE001
                pass

    def _show(self, icon=None, item=None) -> None:
        self.on_show()

    def _sync(self, icon=None, item=None) -> None:
        self.on_sync()

    def _quit(self, icon=None, item=None) -> None:
        global _quitting
        _quitting = True
        self.stop()
        self.on_quit()


# -- 前端桥接 ---------------------------------------------------------------


class WindowApi:
    """暴露给前端的窗口控制接口（``window.pywebview.api.*``）。"""

    def __init__(self) -> None:
        self._window = None
        self.on_open_login = None

    def bind(self, window) -> None:
        self._window = window

    def open_login(self) -> bool:
        if self.on_open_login:
            self.on_open_login()
        return True

    def minimize(self) -> bool:
        if self._window:
            try:
                self._window.minimize()
            except Exception:  # noqa: BLE001
                pass
        return True

    def close(self) -> bool:
        """关闭按钮：托盘可用时隐藏到托盘，否则真正退出。"""
        global _quitting
        if not self._window:
            return True
        if _quitting or not _tray_ready:
            try:
                self._window.destroy()
            except Exception:  # noqa: BLE001
                pass
        else:
            try:
                self._window.hide()
            except Exception:  # noqa: BLE001
                pass
        return True

    def quit(self) -> bool:
        global _quitting
        _quitting = True
        for win in list(webview.windows):
            try:
                win.destroy()
            except Exception:  # noqa: BLE001
                pass
        return True

    def sync_now(self) -> bool:
        ctx = APP_CTX.get("ctx")
        if ctx:
            ctx.run_sync_async("incremental")
        return True


APP_CTX: dict = {"ctx": None, "server": None, "main_window": None}


# -- 主流程 -----------------------------------------------------------------


def main() -> None:
    global _quitting

    ensure_single_instance()

    db = Database(os.path.join(data_dir(), "ccgauge.db"))
    _migrate_legacy_credentials(db)

    ctx = AppContext(db)
    APP_CTX["ctx"] = ctx

    server = Server(ctx)
    APP_CTX["server"] = server
    dashboard_url = server.base_url
    diag_log(f"[app] 本地服务 {dashboard_url}（数据目录 {data_dir()}）")

    api = WindowApi()

    main_window = webview.create_window(
        APP_TITLE,
        dashboard_url,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=WINDOW_MIN_SIZE,
        js_api=api,
    )
    api.bind(main_window)
    APP_CTX["main_window"] = main_window

    # 隐藏登录窗口（点击登录时显示并加载登录页）
    login_window = webview.create_window(
        "CCGauge - 登录 Command Code",
        "about:blank",
        width=LOGIN_WINDOW_SIZE[0],
        height=LOGIN_WINDOW_SIZE[1],
        hidden=True,
    )
    _watcher_ref["window"] = login_window

    def notify_frontend() -> None:
        try:
            main_window.evaluate_js("window.ccgaugeOnDataChanged && window.ccgaugeOnDataChanged();")
        except Exception:  # noqa: BLE001
            pass

    def on_login_success(cookie_header: str, cookie_count: int) -> None:
        db.set_setting("cookie_header", cookie_header)
        db.set_setting("cookie_valid", "1")
        ctx.reload_credentials()
        try:
            login_window.hide()
        except Exception:  # noqa: BLE001
            pass
        notify_frontend()
        # 空库首次登录才做历史回填；已有数据仅增量追新（避免重复拉取）
        ctx.run_sync_async("full" if db.count_records() == 0 else "incremental")

    def open_login() -> None:
        """显示登录窗口并启动监听（单飞守卫）。"""
        watcher = _watcher_ref.get("watcher")
        if isinstance(watcher, LoginWatcher) and watcher._thread and watcher._thread.is_alive() and not watcher.done:
            try:
                login_window.show()
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            login_window.show()
            login_window.load_url(build_signin_url())
        except Exception:  # noqa: BLE001
            pass
        new_watcher = LoginWatcher(login_window, on_login_success,
                                   on_cancelled=lambda: notify_frontend())
        _watcher_ref["watcher"] = new_watcher
        new_watcher.start()

    api.on_open_login = open_login
    ctx.on_login_request = open_login  # HTTP 兜底通道（浏览器/桥未就绪时）

    def on_window_closed() -> None:
        watcher = _watcher_ref.get("watcher")
        if isinstance(watcher, LoginWatcher):
            watcher.stop()

    main_window.events.closed += on_window_closed

    tray = TrayIcon(
        asset_path("CCGauge.ico"),
        on_show=lambda: (main_window.show(), main_window.restore()),
        on_quit=lambda: [w.destroy() for w in list(webview.windows)],
        on_sync=lambda: ctx.run_sync_async("incremental"),
    )
    tray.start()

    # 已登录：启动调度；空库做历史回填，否则仅在超过同步间隔时做一次轻量增量
    if ctx.has_cookie():
        ctx.start_scheduler()
        if db.count_records() == 0:
            diag_log("[sync] 空库 → 启动历史回填")
            ctx.run_sync_async("full")
        elif ctx.should_sync_now():
            diag_log("[sync] 启动增量追新")
            ctx.run_sync_async("incremental")
        else:
            diag_log("[sync] 距上次同步未到间隔，跳过启动同步")
    if ctx.has_api_key():
        threading.Thread(target=ctx.refresh_quota, daemon=True).start()

    def _bridge_diagnostics() -> None:
        """启动自检：确认 JS 桥与前端页面已就绪（输出到日志便于排查）。"""
        time.sleep(3)
        try:
            result = main_window.evaluate_js(
                "JSON.stringify({bridge: typeof window.pywebview, "
                "api: !!(window.pywebview && window.pywebview.api), "
                "nav: (document.querySelector('.nav-item.active') || {}).textContent || null})"
            )
            diag_log(f"[diag] frontend: {result}")
        except Exception as exc:  # noqa: BLE001
            diag_log(f"[diag] frontend check failed: {exc}")

    icon = asset_path("CCGauge.ico")
    webview.start(
        func=lambda: threading.Thread(target=_bridge_diagnostics, daemon=True).start(),
        icon=icon if os.path.isfile(icon) else None,
    )

    if not _quitting:
        tray.stop()
    ctx.stop_scheduler()
    server.stop()
    db.close()


def _migrate_legacy_credentials(db: Database) -> None:
    """首次运行时从探测产物迁移凭据（开发便利；正式使用走登录窗口）。"""
    if db.get_setting("cookie_header"):
        return
    probe = os.path.join(data_dir(), "probe", "cookies.json")
    if not os.path.isfile(probe):
        return
    try:
        import json
        with open(probe, encoding="utf-8") as fh:
            cookies = json.load(fh)
        header = "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name"))
        if header:
            db.set_setting("cookie_header", header)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
