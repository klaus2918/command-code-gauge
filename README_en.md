# CCGauge — Command Code Usage Panel

**Local-first usage dashboard for Command Code**: quota windows, token breakdown, model ranking, daily aggregation and request records — all at a glance.

[🌐 中文](./README.md)

---

## ✨ Features

- **Live quota windows**: 5-hour / weekly rolling windows (progress bar + spent amount + reset countdown), monthly credit balance and days left in the billing period
- **Usage overview**: requests / total tokens (in+out) / cost / cache cost ratio / average duration / model count, with six ranges — today, 24h, 7d, 30d, billing period, all
- **Today trend**: 24-hour input/output bar chart
- **Usage statistics**: token breakdown, cost breakdown (input / output / cache), model doughnut chart and ranking, trend chart with metric switcher (cost / requests / tokens) and range totals
- **Daily aggregation**: per-day × model requests / tokens / cost / average duration
- **Request records**: paginated request-level details with model filter
- **Built-in WebView login**: a dedicated login window opens the official sign-in page and captures the session credentials automatically — no manual cookie copying
- **Auto sync (incremental-first)**: routine syncs only fetch new records (usually 1–2 requests); the first run or the “Backfill history” button walks backwards and **resumes from the earliest locally stored record**, so already-fetched ranges are never re-requested. Interval 1 / 5 / 15 / 30 min and range (30 / 60 / 90 / 180 days / all) are configurable; quota data refreshes on a separate 5-minute throttle
- **Dual theme + bilingual**: light / dark themes, Chinese / English UI
- **System tray**: close-to-tray, with show window / sync now / quit menu
- **Single instance**: launching again focuses the existing window

## 🖥 Quick start

### Use the binary (Windows)

Download `CCGauge.exe` from Releases (single file, no install):

1. Double-click and click “Sign in” on the welcome page
2. Complete the commandcode.ai login (email, Google, GitHub or Discord)
3. The dashboard opens and runs its first full sync

> Requires Windows 10/11 (WebView2 Runtime included). Data lives in the `data/` folder next to the exe.

### Run from source

```bash
pip install -r requirements.txt
python entry.py
```

### Build

```bat
build.bat
```

Produces `dist\CCGauge.exe` (single file, with icon and tray support).

### Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## 📊 Data

- **Details**: Command Code request-record endpoint (`/internal/usage`, web session auth) — timestamp, model, input/output tokens, duration, cost breakdown (input / output / cache)
- **Quota**: `/alpha/billing/credits` (5-hour / weekly windows + credits), `/alpha/billing/subscriptions` (plan and billing period), `/alpha/usage/summary` (server aggregates)
- **Total tokens** = input + output
- **Cache cost ratio** = cache cost / (input cost + cache cost)
- Costs are raw USD; the panel supports **USD / CNY / both** display modes (switchable in Settings), with CNY converted at the live [open.er-api.com](https://open.er-api.com) rate (24-hour cache, gracefully falls back to USD only)
- Records are deduplicated by server record id; incremental sync is idempotent

## 🔒 Privacy

- Session credentials and API key stay in the local `data/ccgauge.db` — never uploaded
- All usage data is stored locally; the app contains no telemetry
- The panel serves only on a random `127.0.0.1` port and is not exposed to the network

## 🛠 Tech stack

Python · pywebview (WebView2) · SQLite · Chart.js · pystray · PyInstaller

## 📄 License

MIT © CCGauge

---

## Credits

UI and interaction inspired by [opencode-go-gauge](https://github.com/yphyphyph/opencode-go-gauge) (OpenCode Go usage panel); data source and implementation are built specifically for Command Code.
