# -*- coding: utf-8 -*-
"""打印 ``app/__init__.py`` 中的 ``__version__``（版本号单一来源）。

用法::

    py scripts/read_version.py     # → 1.1.3

供 ``build.bat`` 读取后注入 Inno Setup：``iscc /DMyAppVersion=<ver> CCGauge.iss``。
单独运行也会在找不到定义时以非 0 退出，避免构建脚本拿到空版本号继续跑。
"""
from __future__ import annotations

import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT_PATH = os.path.join(BASE_DIR, "app", "__init__.py")
PATTERN = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def read_version(path: str = INIT_PATH) -> str:
    """从指定文件读取 ``__version__``；缺失时抛 ``SystemExit(1)``。"""
    with open(path, encoding="utf-8") as handle:
        match = PATTERN.search(handle.read())
    if not match:
        raise SystemExit(f"未在 {path} 找到 __version__ 定义")
    return match.group(1)


def main() -> None:
    version = read_version()
    sys.stdout.write(version + "\n")


if __name__ == "__main__":
    main()
