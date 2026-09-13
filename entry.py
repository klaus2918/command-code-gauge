"""CCGauge 入口（开发 / 打包通用）。

打包后（PyInstaller）双击 exe 即运行本入口：
启动本地 HTTP 服务 → 创建主窗口（未登录时显示欢迎页引导登录）。
"""
import multiprocessing

from app.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
