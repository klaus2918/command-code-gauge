# CCGauge — Command Code 用量面板

**本地优先的 Command Code 用量统计面板**：配额窗口、Token 构成、模型排行、按日聚合与使用记录，打开即见。

[🌐 English](./README_en.md)

---

## ✨ 功能

- **配额窗口实时监控**：5 小时 / 每周滚动窗口（进度条 + 已用金额 + 重置倒计时）+ 月度信用余额与计费周期剩余天数
- **用量概览**：请求数 / 总 Token（输入+输出）/ 费用 / 缓存成本占比 / 平均耗时 / 模型数，支持今天、24 小时、7 天、30 天、计费周期、全部六档范围
- **今日趋势**：24 小时输入 / 输出柱状图
- **用量统计**：Token 构成、成本构成（输入 / 输出 / 缓存）、模型用量环形图与排行、趋势主图（费用 / 请求数 / Token 三指标切换，含本范围合计；Token 用堆叠面积呈现输入输出）
- **按日聚合**：日期 × 模型粒度的请求数 / Token / 费用 / 平均耗时
- **使用记录**：请求级明细分页浏览，支持模型筛选
- **模型性价比（官方套餐信息）**：新增「模型」页，抓取官方文档的**每模型月度额度上限**、**5 小时 / 每周 / 每月请求次数估算**与每百万 token 单价，与本机实测（请求数、平均每请求成本、额度消耗进度、额度内可跑次数）并排对照，默认按「可跑次数」排序，便于快速比较各模型性价比
- **内置 WebView 登录**：独立登录窗口打开官方登录页，自动捕获会话凭据，无需手动复制 Cookie
- **自动同步（增量优先）**：日常只拉取新增记录（通常 1~2 次请求即追平）；首次使用或点按「回填历史」时才向过去补全，且**从本地最早的记录断点续传**——不会重复拉取已有区间。同步间隔 1 / 5 / 15 / 30 分钟可调，同步范围（30 / 60 / 90 / 180 天 / 全部）可配；配额数据独立按 5 分钟节流刷新
- **URL 直达**：支持 `?page=stats&metric=tokens` 形式的地址参数，切换页面/指标会同步到地址栏，刷新或加书签均保持
- **双主题 + 中英双语**：亮色 / 深色一键切换，界面中英切换
- **Token 数字单位可切**：中文单位（`2.48亿`、`97.83万`；不足一万显示原数 `7719`）/ 英文单位（`247.51M`）/ 原始数字（`247,506,388`）三种表述；未显式设置时随界面语言派生，紧凑数字悬停可读完整值
- **系统托盘**：关闭窗口最小化到托盘，托盘菜单可显示窗口 / 立即同步 / 退出
- **单实例**：重复启动时激活已有窗口

## 🖥 快速开始

### 直接使用（Windows）

下载 Release 中的 `CCGauge.exe`（单文件，无需安装）：

1. 双击运行，欢迎页点击「立即登录」
2. 在弹出的登录窗口完成 commandcode.ai 登录（邮箱密码 / Google / GitHub / Discord）
3. 自动进入面板并执行首次全量同步

> 需要 Windows 10/11（自带 WebView2 Runtime）。数据保存在 exe 同目录 `data/` 文件夹。

### 源码运行

```bash
git clone https://github.com/klaus2918/command-code-gauge.git
cd command-code-gauge
pip install -r requirements.txt
python entry.py
```

### 打包

```bat
build.bat
```

输出 `dist\CCGauge.exe`（单文件，含图标与托盘支持）。

### 测试

```bash
pip install -r requirements-dev.txt
pytest tests/ -v                      # 后端（Python）
node --test "tests/js/*.test.mjs"     # 前端数字单位格式化（Node 内置 test runner，无需 npm install）
```

## 📊 数据说明

- **明细数据**：Command Code 服务端请求记录接口（`/internal/usage`，网页会话凭据认证），字段含请求时间、模型、输入 / 输出 Token、耗时、成本（输入 / 输出 / 缓存分解）
- **配额数据**：`/alpha/billing/credits`（5 小时 / 每周窗口 + 信用余额）、`/alpha/billing/subscriptions`（计划与计费周期）、`/alpha/usage/summary`（服务端汇总）
- **总 Token** = 输入 + 输出
- **缓存成本占比** = 缓存成本 /（输入成本 + 缓存成本）
- **官方套餐与模型数据**：来自 `commandcode.ai` 公开文档页（`/docs/plans/<套餐>`、`/docs/resources/pricing-limits`），无需登录、不携带任何凭据；官方未提供 JSON 接口，故以解析页面表格实现，结果本地缓存 24 小时，抓取或解析失败时沿用上次快照并在「模型」页标注数据时间
- **估算口径**：「模型」页的缓存读 token 由「缓存成本 ÷ 官方缓存单价」反推（本机明细不含缓存读计数），界面标注为估算；「额度可跑次数」= 该模型月度额度 ÷ 你的实测平均每请求成本，括号内为与官方次数估算的比值
- 费用为 USD 原始值；支持 **USD / CNY / 双显** 三种口径（设置页切换），人民币按 [open.er-api.com](https://open.er-api.com) 实时汇率换算（24 小时缓存，获取失败时自动降级为仅显示美元）
- **Token 显示口径**：**中文单位**（亿 / 万，不足一万显示原数，如 `2.48亿`、`120万`、`7719`）、**英文单位**（`247.51M`）、**原始数字**（`247,506,388`）三种（设置页切换）；未显式设置时随界面语言派生（中文界面 → 中文单位，English → 英文单位）
- 明细按服务端记录 ID 去重入库，增量同步幂等可重复执行

### 同步机制

| 模式 | 触发时机 | 行为 | 典型请求量 |
|------|---------|------|-----------|
| 增量追新 | 定时调度、启动（超过间隔）、登录（库非空）、「立即同步」 | 从最新向前翻，某页整页已存在即停 | 1~2 次 |
| 历史回填 | 空库首次启动/登录、「回填历史」 | 库非空时从**最早记录**锚点继续向更早补；空库时从最新翻到底 | 首次若干次，之后通常 1 次 |

两种模式都以服务端记录 ID 幂等去重，重复执行安全。

## 🔒 隐私

- 登录凭据（会话 Cookie）与 API Key 仅保存在本机 `data/ccgauge.db`，绝不外传
- 用量数据全部本地存储，应用不含任何遥测
- 面板仅在 `127.0.0.1` 随机端口提供本地页面，不对外监听

## 🛠 技术栈

Python · pywebview (WebView2) · SQLite · Chart.js · pystray · PyInstaller

## 📁 目录结构

```
entry.py                 入口（开发/打包通用）
app/
├─ auth.py               登录窗口与凭据捕获
├─ cc_api.py             Command Code API 客户端（双通道认证 + 锚点分页）
├─ official.py           官方套餐 / 模型信息抓取与解析（公开文档页，无新依赖）
├─ db.py                 SQLite 存储与聚合
├─ server.py             本地 HTTP 服务 + 同步引擎 + 定时调度
├─ main.py               窗口 / 托盘 / 单实例 / 前端桥接
└─ web/                  前端（原生 JS + Chart.js）
   ├─ units.js           数字单位格式化（纯函数，Node 测试覆盖）
   └─ app.js             页面渲染与交互
scripts/
├─ build_icon.py         生成应用图标
└─ probe_login.py        登录原型（接口联调工具）
tests/                   pytest 单元测试（含 tests/fixtures 官方页面离线夹具）+ tests/js（Node）数字单位格式化测试
build.bat                PyInstaller 打包脚本
```

## 📄 License

[MIT](./LICENSE) © CCGauge

---

## 参考与致谢

- 界面与交互参考 [opencode-go-gauge](https://github.com/yphyphyph/opencode-go-gauge)（OpenCode Go 用量面板，MIT 许可，Copyright (c) 2026 GoGauge (yphyphyph)）；本项目数据源与实现完全针对 Command Code 构建。
- 图表库 [Chart.js](https://www.chartjs.org/)（MIT 许可，见 `app/web/chart.umd.min.js`）。
