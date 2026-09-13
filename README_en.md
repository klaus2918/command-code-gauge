# CCGauge — Command Code Usage Panel

**Local-first usage dashboard for Command Code**: quota windows, token breakdown, model ranking, daily aggregation and request records — all at a glance.

[🌐 中文](./README.md)

---

## ✨ Features

- **Live quota windows**: 5-hour / weekly rolling windows (progress bar + spent amount + reset countdown), monthly credit balance and days left in the billing period
- **Usage overview**: requests / total tokens (in+out) / cost / cache cost ratio / average duration / model count, with six ranges — today, 24h, 7d, 30d, billing period, all
- **Today trend**: 24-hour input/output bar chart
- **Usage statistics**: token breakdown, cost breakdown (input / output / cache), model doughnut chart and ranking, trend chart with metric switcher (cost / requests / tokens) and range totals
- **Daily aggregation**: per-day × model requests / tokens / cost / average duration, paged (stays complete as rows accumulate over time)
- **Request records**: paginated request-level details with model filter
- **Model value (official plan data)**: a new “Models” page fetches the official docs for **per-model monthly allowance**, **5-hour / weekly / monthly request estimates** and per-million-token rates, side by side with your local measurements (requests, average cost per request, allowance used, affordable requests) — sorted by affordable requests to compare models at a glance
- **Built-in WebView login**: a dedicated login window opens the official sign-in page and captures the session credentials automatically — no manual cookie copying
- **Auto sync (incremental-first)**: routine syncs only fetch new records (usually 1–2 requests); the first run or the “Backfill history” button walks backwards and **resumes from the earliest locally stored record**, so already-fetched ranges are never re-requested. Interval 1 / 5 / 15 / 30 min and range (30 / 60 / 90 / 180 days / all) are configurable; quota data refreshes on a separate 5-minute throttle
- **Dual theme + bilingual**: light / dark themes, Chinese / English UI
- **Switchable token units**: Chinese units (`2.48亿`, `97.83万`; values below 10,000 stay plain, e.g. `7719`) / English units (`247.51M`) / plain numbers (`247,506,388`); the default follows the UI language until you pick one explicitly, and compact values reveal the exact number on hover
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
git clone https://github.com/klaus2918/command-code-gauge.git
cd command-code-gauge
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
pytest tests/ -v                      # backend (Python)
node --test "tests/js/*.test.mjs"     # frontend token-unit formatting (Node's built-in test runner, no npm install)
```

## 📊 Data

- **Details**: Command Code request-record endpoint (`/internal/usage`, web session auth) — timestamp, model, input/output tokens, duration, cost breakdown (input / output / cache)
- **Quota**: `/alpha/billing/credits` (5-hour / weekly windows + credits), `/alpha/billing/subscriptions` (plan and billing period), `/alpha/usage/summary` (server aggregates)
- **Total tokens** = input + output
- **Cache cost ratio** = cache cost / (input cost + cache cost)
- **Official plan & model data**: from public `commandcode.ai` docs pages (`/docs/plans/<plan>`, `/docs/resources/pricing-limits`) — no login, no credentials attached. There is no official JSON API for these tables, so they are parsed from the page, cached locally for 24 hours, and fall back to the previous snapshot (with the fetch time shown on the Models page) when fetching or parsing fails
- **Estimates**: on the Models page, cache-read tokens are derived from cache cost ÷ official cache rate (the local DB does not store cache-read counts) and are labelled as estimates; “affordable requests” = model monthly allowance ÷ your measured average cost per request, with the ratio to the official estimate in brackets
- Costs are raw USD; the panel supports **USD / CNY / both** display modes (switchable in Settings), with CNY converted at the live [open.er-api.com](https://open.er-api.com) rate (24-hour cache, gracefully falls back to USD only)
- **Token unit modes**: **Chinese units** (亿 / 万; values below 10,000 stay plain — e.g. `2.48亿`, `120万`, `7719`), **English units** (`247.51M`) or **plain numbers** (`247,506,388`) — switchable in Settings; until you pick one, the mode follows the UI language (Chinese → Chinese units, English → English units)
- Records are deduplicated by server record id; incremental sync is idempotent

## 🔒 Privacy

- Session credentials and API key stay in the local `data/ccgauge.db` — never uploaded
- All usage data is stored locally; the app contains no telemetry
- The panel serves only on a random `127.0.0.1` port and is not exposed to the network

## 🛠 Tech stack

Python · pywebview (WebView2) · SQLite · Chart.js · pystray · PyInstaller

## 📄 License

[MIT](./LICENSE) © CCGauge

---

## Credits

- UI and interaction inspired by [opencode-go-gauge](https://github.com/yphyphyph/opencode-go-gauge) (OpenCode Go usage panel, MIT licensed, Copyright (c) 2026 GoGauge (yphyphyph)); the data source and implementation here are built specifically for Command Code.
- Charting by [Chart.js](https://www.chartjs.org/) (MIT licensed, bundled as `app/web/chart.umd.min.js`).
