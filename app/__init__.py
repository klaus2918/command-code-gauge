"""CCGauge - Command Code 用量仪表盘（本地优先）。

模块划分：
- auth     登录窗口与凭据捕获
- cc_api   Command Code API 客户端（明细分页 / 配额 / 计划）
- db       SQLite 存储与聚合
- server   本地 HTTP 服务（前端 REST + 同步调度）
- main     pywebview 窗口 / 托盘 / 单实例
"""

__version__ = "1.1.0"
APP_NAME = "CCGauge"
APP_TITLE = "CCGauge - Command Code 用量仪表盘"
