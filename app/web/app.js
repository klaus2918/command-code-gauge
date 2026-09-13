/* CCGauge 前端逻辑：状态管理 / 数据获取 / 渲染 / 图表 / 中英双语 */
(() => {
  'use strict';

  // ---------------------------------------------------------------- i18n
  const I18N = {
    zh: {
      'nav.home': '首页', 'nav.stats': '用量统计', 'nav.records': '使用记录',
      'nav.settings': '设置', 'nav.about': '关于',
      'action.sync': '同步', 'action.refresh': '刷新', 'action.prev': '上一页', 'action.next': '下一页',
      'welcome.title': '欢迎使用 CCGauge',
      'welcome.desc': '本地优先的 Command Code 用量面板：配额窗口、Token 构成、模型排行与使用记录，打开即见。',
      'welcome.login': '立即登录', 'welcome.quit': '退出',
      'welcome.hint': '登录窗口会打开 commandcode.ai 官方登录页，完成后自动捕获会话凭据（仅保存在本机）。',
      'home.quota': '配额窗口', 'home.overview': '用量概览', 'home.todayTrend': '今日趋势（24 小时）',
      'quota.fiveHour': '5 小时窗口', 'quota.weekly': '每周窗口', 'quota.credits': '月度信用',
      'quota.remaining': '剩余', 'quota.resetsIn': '重置于', 'quota.periodEnds': '周期剩余 {d} 天',
      'range.today': '今天', 'range.24h': '24 小时', 'range.7d': '7 天', 'range.30d': '30 天',
      'range.billing': '计费周期', 'range.all': '全部',
      'metric.requests': '请求数', 'metric.totalTokens': '总 Token', 'metric.cost': '费用',
      'metric.cacheRatio': '缓存成本占比', 'metric.avgDuration': '平均耗时', 'metric.models': '模型数',
      'stats.title': '用量统计', 'stats.tokenBreakdown': 'Token 构成', 'stats.modelShare': '模型用量占比',
      'stats.modelRank': '模型排行', 'stats.trend': '趋势',
      'stats.trendCost': '费用', 'stats.trendRequests': '请求数', 'stats.trendTokens': 'Token',
      'stats.sumCost': '本范围合计 {v}', 'stats.sumRequests': '本范围合计 {v} 次请求',
      'stats.sumTokens': '本范围合计 {v} tokens',
      'stats.sparseHint': '数据点较少：应用常驻运行会按同步间隔持续积累，趋势将逐步完整。',
      'token.in': '输入', 'token.out': '输出',
      'cost.input': '输入成本', 'cost.output': '输出成本', 'cost.cache': '缓存成本', 'cost.total': '总成本',
      'records.dailyTitle': '按日聚合', 'records.detailTitle': '请求明细',
      'table.day': '日期', 'table.model': '模型', 'table.requests': '请求数', 'table.tokensIn': '输入',
      'table.tokensOut': '输出', 'table.totalTokens': '总 Token', 'table.cost': '费用',
      'table.avgDuration': '平均耗时', 'table.time': '时间', 'table.mode': '类型', 'table.duration': '耗时',
      'settings.title': '设置', 'settings.sync': '同步', 'settings.interval': '自动同步间隔',
      'settings.range': '同步范围', 'settings.syncNow': '立即同步', 'settings.syncFull': '回填历史',
      'settings.syncHint': '「立即同步」只拉取新增；「回填历史」从最早记录继续向前补历史，均不会重复拉取已有区间。',
      'settings.account': '账户', 'settings.user': '用户', 'settings.plan': '计划', 'settings.credential': '登录态',
      'settings.relogin': '重新登录', 'settings.logout': '退出登录',
      'settings.appearance': '外观', 'settings.theme': '主题', 'settings.light': '亮色', 'settings.dark': '深色',
      'settings.lang': '语言', 'settings.currency': '货币显示',
      'settings.rateInfo': '汇率 1 USD ≈ ¥{r}（24 小时缓存，open.er-api.com）',
      'settings.rateFailed': '汇率暂不可用，当前仅显示美元',
      'about.title': '关于',
      'about.desc': 'Command Code 用量面板：配额窗口、Token 构成、模型排行、按日聚合与自动同步。数据默认保存在本机 SQLite；登录凭据仅保存在本机，不会上传到任何第三方。',
      'about.source': '数据来源', 'about.storage': '数据存储',
      'status.loggedIn': '已登录', 'status.notLoggedIn': '未登录', 'status.syncing': '同步中…',
      'status.cookieInvalid': '登录态已失效，请重新登录',
      'toast.syncStarted': '同步已开始', 'toast.syncDone': '同步完成：新增 {n} 条',
      'toast.settingsSaved': '设置已保存', 'toast.loggedOut': '已退出登录',
      'toast.loginOpened': '登录窗口已打开', 'toast.loginUnavailable': '当前环境无法打开登录窗口',
      'toast.noData': '暂无数据，请先同步',
      'empty.records': '暂无记录', 'empty.models': '暂无模型数据',
      'page.info': '第 {p} / {t} 页 · 共 {n} 条', 'page.none': '暂无数据',
      'sync.never': '尚未同步', 'sync.last': '上次同步 {t}', 'sync.failed': '同步失败：{e}',
      'sync.records': '{n} 条记录', 'sync.span': '数据范围 {a} ~ {b}',
      'plan.monthly': '月额度 ${c}',
    },
    en: {
      'nav.home': 'Home', 'nav.stats': 'Statistics', 'nav.records': 'Records',
      'nav.settings': 'Settings', 'nav.about': 'About',
      'action.sync': 'Sync', 'action.refresh': 'Refresh', 'action.prev': 'Prev', 'action.next': 'Next',
      'welcome.title': 'Welcome to CCGauge',
      'welcome.desc': 'Local-first Command Code usage panel: quota windows, token breakdown, model ranking and request records.',
      'welcome.login': 'Sign in', 'welcome.quit': 'Quit',
      'welcome.hint': 'The login window opens the official commandcode.ai sign-in page; credentials are captured automatically and stay on this machine.',
      'home.quota': 'Quota windows', 'home.overview': 'Usage overview', 'home.todayTrend': 'Today (24h)',
      'quota.fiveHour': '5-hour window', 'quota.weekly': 'Weekly window', 'quota.credits': 'Monthly credits',
      'quota.remaining': 'remaining', 'quota.resetsIn': 'resets in', 'quota.periodEnds': '{d} days left in period',
      'range.today': 'Today', 'range.24h': '24h', 'range.7d': '7d', 'range.30d': '30d',
      'range.billing': 'Billing', 'range.all': 'All',
      'metric.requests': 'Requests', 'metric.totalTokens': 'Total tokens', 'metric.cost': 'Cost',
      'metric.cacheRatio': 'Cache cost ratio', 'metric.avgDuration': 'Avg duration', 'metric.models': 'Models',
      'stats.title': 'Usage statistics', 'stats.tokenBreakdown': 'Token breakdown', 'stats.modelShare': 'Model share',
      'stats.modelRank': 'Model ranking', 'stats.trend': 'Trends',
      'stats.trendCost': 'Cost', 'stats.trendRequests': 'Requests', 'stats.trendTokens': 'Tokens',
      'stats.sumCost': 'Range total {v}', 'stats.sumRequests': 'Range total {v} requests',
      'stats.sumTokens': 'Range total {v} tokens',
      'stats.sparseHint': 'Few data points so far — keep the app running and the trend fills in as history accumulates.',
      'token.in': 'Input', 'token.out': 'Output',
      'cost.input': 'Input cost', 'cost.output': 'Output cost', 'cost.cache': 'Cache cost', 'cost.total': 'Total cost',
      'records.dailyTitle': 'Daily aggregation', 'records.detailTitle': 'Request details',
      'table.day': 'Date', 'table.model': 'Model', 'table.requests': 'Requests', 'table.tokensIn': 'Input',
      'table.tokensOut': 'Output', 'table.totalTokens': 'Total tokens', 'table.cost': 'Cost',
      'table.avgDuration': 'Avg duration', 'table.time': 'Time', 'table.mode': 'Mode', 'table.duration': 'Duration',
      'settings.title': 'Settings', 'settings.sync': 'Sync', 'settings.interval': 'Auto sync interval',
      'settings.range': 'Sync range', 'settings.syncNow': 'Sync now', 'settings.syncFull': 'Backfill history',
      'settings.syncHint': '"Sync now" pulls only new records; "Backfill history" continues backwards from the earliest stored record. Neither re-fetches what is already stored.',
      'settings.account': 'Account', 'settings.user': 'User', 'settings.plan': 'Plan', 'settings.credential': 'Session',
      'settings.relogin': 'Re-login', 'settings.logout': 'Sign out',
      'settings.appearance': 'Appearance', 'settings.theme': 'Theme', 'settings.light': 'Light', 'settings.dark': 'Dark',
      'settings.lang': 'Language', 'settings.currency': 'Currency',
      'settings.rateInfo': 'Rate 1 USD ≈ ¥{r} (24h cache, open.er-api.com)',
      'settings.rateFailed': 'Exchange rate unavailable — showing USD only',
      'about.title': 'About',
      'about.desc': 'Command Code usage panel: quota windows, token breakdown, model ranking, daily aggregation and auto sync. Data is stored locally in SQLite; credentials never leave this machine.',
      'about.source': 'Data source', 'about.storage': 'Storage',
      'status.loggedIn': 'Signed in', 'status.notLoggedIn': 'Not signed in', 'status.syncing': 'Syncing…',
      'status.cookieInvalid': 'Session expired, please sign in again',
      'toast.syncStarted': 'Sync started', 'toast.syncDone': 'Sync finished: {n} new',
      'toast.settingsSaved': 'Settings saved', 'toast.loggedOut': 'Signed out',
      'toast.loginOpened': 'Login window opened', 'toast.loginUnavailable': 'Login window unavailable here',
      'toast.noData': 'No data yet, please sync first',
      'empty.records': 'No records', 'empty.models': 'No model data',
      'page.info': 'Page {p} / {t} · {n} items', 'page.none': 'No data',
      'sync.never': 'Never synced', 'sync.last': 'Last sync {t}', 'sync.failed': 'Sync failed: {e}',
      'sync.records': '{n} records', 'sync.span': 'span {a} ~ {b}',
      'plan.monthly': 'Monthly ${c}',
    },
  };

  const t = (key, vars) => {
    let text = (I18N[state.lang] && I18N[state.lang][key]) || I18N.zh[key] || key;
    if (vars) Object.keys(vars).forEach((k) => { text = text.replace(`{${k}}`, vars[k]); });
    return text;
  };

  // ---------------------------------------------------------------- state
  const state = {
    lang: localStorage.getItem('ccgauge.lang') || 'zh',
    theme: localStorage.getItem('ccgauge.theme') || 'light',
    page: 'home',
    homeRange: 'today',
    statsRange: '7d',
    recordPage: 1,
    recordPageSize: 50,
    recordModel: '',
    trendMetric: 'cost',
    trendSeries: [],
    trendLabels: [],
    rate: 0,                 // USD→CNY 汇率（0 表示未获取，仅显示美元）
    currencyMode: 'both',    // usd | cny | both
    status: null,
    charts: {},
    pollTimer: null,
    quotaRefreshing: false,
  };

  const $ = (id) => document.getElementById(id);
  const tzOffsetSec = () => -new Date().getTimezoneOffset() * 60;

  // ---------------------------------------------------------------- utils
  function fmtInt(value) {
    const n = Number(value) || 0;
    return n.toLocaleString('en-US');
  }

  function fmtCompact(value) {
    const n = Number(value) || 0;
    if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n);
  }

  /** 金额格式化：按货币模式输出美元 / 人民币 / 双显（汇率未就绪时仅美元）。 */
  function fmtCost(value) {
    const usd = Number(value) || 0;
    const rate = state.rate;
    const mode = rate > 0 ? state.currencyMode : 'usd';
    if (usd === 0) {
      if (mode === 'cny') return '¥0';
      if (mode === 'both') return '$0（¥0）';
      return '$0';
    }
    let usdText;
    if (usd < 0.01) usdText = usd.toFixed(6);
    else if (usd < 1) usdText = usd.toFixed(4);
    else usdText = usd.toFixed(2);
    const cnyText = (usd * rate).toFixed(2);
    if (mode === 'cny') return '¥' + cnyText;
    if (mode === 'both') return '$' + usdText + '（¥' + cnyText + '）';
    return '$' + usdText;
  }

  /** 图表轴用紧凑金额（双显会超出轴宽，仅取当前主口径）。 */
  function fmtCostAxis(value) {
    const usd = Number(value) || 0;
    if (state.rate > 0 && state.currencyMode === 'cny') {
      return '¥' + (usd * state.rate).toFixed(2);
    }
    return '$' + usd.toFixed(2);
  }

  function fmtDuration(ms) {
    const n = Number(ms) || 0;
    if (n >= 60000) return (n / 60000).toFixed(1) + ' min';
    if (n >= 1000) return (n / 1000).toFixed(1) + ' s';
    return Math.round(n) + ' ms';
  }

  function fmtTime(ts) {
    if (!ts) return '--';
    const d = new Date(ts * 1000);
    const pad = (x) => String(x).padStart(2, '0');
    return `${d.getMonth() + 1}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function fmtDate(ts) {
    if (!ts) return '--';
    const d = new Date(ts * 1000);
    const pad = (x) => String(x).padStart(2, '0');
    return `${d.getMonth() + 1}/${pad(d.getDate())}`;
  }

  function fmtCountdown(resetAt) {
    if (!resetAt) return '';
    const diff = Math.max(0, Math.floor((Number(resetAt) - Date.now()) / 1000));
    const h = Math.floor(diff / 3600);
    const m = Math.floor((diff % 3600) / 60);
    if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  function toast(message, ok = true) {
    const el = $('toast');
    el.textContent = message;
    el.classList.remove('hidden');
    el.classList.add('show');
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.classList.add('hidden'), 220); }, 2600);
  }

  // ---------------------------------------------------------------- api
  async function api(path, options) {
    const resp = await fetch(path, options);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  const get = (path, params) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return api(path + qs);
  };

  const post = (path, payload) => api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });

  // ---------------------------------------------------------------- 主题 / 语言
  function applyTheme(theme) {
    state.theme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('ccgauge.theme', theme);
    document.querySelectorAll('#themeSeg button').forEach((b) => {
      b.classList.toggle('active', b.dataset.themeValue === theme);
    });
    Object.values(state.charts).forEach((c) => { try { c.destroy(); } catch (_) {} });
    state.charts = {};
    if (state.status) renderAll();
  }

  function applyLang(lang) {
    state.lang = lang;
    localStorage.setItem('ccgauge.lang', lang);
    document.documentElement.setAttribute('lang', lang === 'zh' ? 'zh-CN' : 'en');
    document.querySelectorAll('[data-i18n]').forEach((el) => {
      el.textContent = t(el.dataset.i18n);
    });
    $('langBtn').textContent = lang === 'zh' ? 'EN' : '中';
    document.querySelectorAll('#langSeg button').forEach((b) => {
      b.classList.toggle('active', b.dataset.langValue === lang);
    });
    if (state.status) renderAll();
  }

  // ---------------------------------------------------------------- 页面切换
  const PAGE_KEYS = ['home', 'stats', 'records', 'settings', 'about'];

  function switchPage(page) {
    state.page = page;
    // 同步 URL（刷新/书签可保持当前页；home 不写入 query）
    try {
      const params = new URLSearchParams(location.search);
      if (page === 'home') {
        params.delete('page');
      } else {
        params.set('page', page);
      }
      const query = params.toString();
      history.replaceState(null, '', query ? `?${query}` : location.pathname);
    } catch (_) { /* 非浏览器环境忽略 */ }
    document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
    const loggedIn = state.status && state.status.logged_in;
    ['home', 'stats', 'records', 'settings', 'about'].forEach((p) => {
      $(`page-${p}`).classList.toggle('hidden', p !== page);
    });
    $('page-welcome').classList.toggle('hidden', !(!loggedIn && page === 'home'));
    if (loggedIn && page === 'home') $('page-welcome').classList.add('hidden');
    if (!loggedIn && page !== 'home') {
      // 未登录时始终回欢迎页
      $('page-welcome').classList.remove('hidden');
      ['home', 'stats', 'records', 'settings', 'about'].forEach((p) => $(`page-${p}`).classList.add('hidden'));
      if (page === 'settings') { $(`page-settings`).classList.remove('hidden'); $('page-welcome').classList.add('hidden'); }
    }
    loadPage(page);
  }

  function loadPage(page) {
    if (page === 'home') { loadQuota(); loadOverview(state.homeRange); loadTodayChart(); }
    else if (page === 'stats') { loadStats(state.statsRange); }
    else if (page === 'records') { loadDailyRecords(); loadRecordPage(1); }
    else if (page === 'settings') { loadSettings(); }
  }

  // ---------------------------------------------------------------- 状态
  async function loadStatus() {
    const status = await get('/api/status');
    state.status = status;
    const dot = $('statusDot');
    if (!status.logged_in) { dot.className = 'status-dot warn'; dot.title = t('status.notLoggedIn'); }
    else if (status.cookie_valid === false) { dot.className = 'status-dot err'; dot.title = t('status.cookieInvalid'); }
    else { dot.className = 'status-dot ok'; dot.title = t('status.loggedIn'); }
    $('syncBtn').disabled = !!status.syncing || !status.logged_in;
    $('syncBtn').textContent = status.syncing ? t('status.syncing') : t('action.sync');

    const badge = $('planBadge');
    if (status.plan && status.plan.name) {
      badge.hidden = false;
      badge.textContent = status.plan.name;
    } else { badge.hidden = true; }

    $('aboutVersion').textContent = 'v' + (status.version || '--');
    const syncEl = $('syncStatus');
    if (status.sync && status.sync.last_error) {
      syncEl.textContent = t('sync.failed', { e: status.sync.last_error });
    } else {
      const parts = [];
      if (status.sync && status.sync.last_sync_at) {
        parts.push(t('sync.last', { t: fmtTime(status.sync.last_sync_at) }));
      }
      if (status.data && status.data.total) {
        parts.push(t('sync.records', { n: fmtInt(status.data.total) }));
      }
      if (status.data && status.data.min_ts) {
        parts.push(t('sync.span', { a: fmtDate(status.data.min_ts), b: fmtDate(status.data.max_ts) }));
      }
      syncEl.textContent = parts.length ? parts.join(' · ') : t('sync.never');
    }
    if (!state.status.logged_in) switchPage('home');
    else if (state.page === 'home') $('page-welcome').classList.add('hidden');
    return status;
  }

  // ---------------------------------------------------------------- 配额
  async function loadQuota() {
    const data = await get('/api/quota');
    renderQuota(data);
    // 快照过期（>5 分钟）时后台触发一次节流刷新，保持数据新鲜
    const staleSec = data.captured_at ? (Date.now() / 1000 - data.captured_at) : 1e9;
    if (staleSec > 300 && !state.quotaRefreshing) {
      state.quotaRefreshing = true;
      try {
        await post('/api/quota/refresh');
        renderQuota(await get('/api/quota'));
      } catch (_) { /* 刷新失败保留旧快照 */ } finally {
        state.quotaRefreshing = false;
      }
    }
  }

  function renderQuota(data) {
    const w = data.windows || {};
    renderWindow($('fiveHourUsed'), $('fiveHourCap'), $('fiveHourBar'), $('fiveHourReset'), w.five_hour);
    renderWindow($('weeklyUsed'), $('weeklyCap'), $('weeklyBar'), $('weeklyReset'), w.weekly);

    const credits = data.credits || {};
    const total = (Number(credits.monthly) || 0) + (Number(credits.purchased) || 0) + (Number(credits.free) || 0);
    const monthlyQuota = (data.plan && data.plan.monthly_credits) || total || 1;
    $('creditRemaining').textContent = fmtCost(total);
    const bar = $('creditBar');
    const usedPct = Math.min(100, Math.max(0, (1 - total / monthlyQuota) * 100));
    bar.style.width = usedPct.toFixed(1) + '%';
    bar.className = 'progress-fill' + (usedPct > 90 ? ' danger' : usedPct > 70 ? ' warn' : '');
    const sub = data.subscription || {};
    let meta = '';
    if (sub.current_period_end) {
      const days = Math.max(0, Math.ceil((new Date(sub.current_period_end).getTime() - Date.now()) / 86400000));
      meta = t('quota.periodEnds', { d: days });
    }
    if (data.plan && data.plan.monthly_credits) meta += (meta ? ' · ' : '') + t('plan.monthly', { c: data.plan.monthly_credits });
    $('creditMeta').textContent = meta;
    $('quotaCapturedAt').textContent = data.captured_at ? t('sync.last', { t: fmtTime(data.captured_at) }) : '';
  }

  function renderWindow(usedEl, capEl, barEl, resetEl, windowData) {
    if (!windowData) {
      usedEl.textContent = '--';
      capEl.textContent = '';
      resetEl.textContent = '';
      barEl.style.width = '0%';
      return;
    }
    usedEl.textContent = fmtCost(windowData.used);
    capEl.textContent = '/ ' + fmtCost(windowData.cap);
    const pct = Math.min(100, Number(windowData.percent) || 0);
    barEl.style.width = pct.toFixed(1) + '%';
    barEl.className = 'progress-fill' + (pct > 90 ? ' danger' : pct > 70 ? ' warn' : '');
    const countdown = fmtCountdown(windowData.reset_at);
    resetEl.textContent = countdown ? `${t('quota.resetsIn')} ${countdown}` : '';
  }

  // ---------------------------------------------------------------- 概览
  async function loadOverview(range) {
    const data = await get('/api/overview', { range });
    const o = data.overview || {};
    $('ovRequests').textContent = fmtInt(o.requests);
    $('ovTokens').textContent = fmtCompact(o.total_tokens);
    $('ovTokensSub').textContent = `↑${fmtCompact(o.tokens_in)} ↓${fmtCompact(o.tokens_out)}`;
    $('ovCost').textContent = fmtCost(o.cost_total);
    $('ovCostSub').textContent = `${t('cost.cache')} ${fmtCost(o.cost_cache)}`;
    $('ovCache').textContent = ((o.cache_cost_ratio || 0) * 100).toFixed(1) + '%';
    $('ovCacheSub').textContent = `${t('cost.input')} ${fmtCost(o.cost_input)}`;
    $('ovDuration').textContent = fmtDuration(o.avg_duration_ms);
    $('ovModels').textContent = fmtInt(o.model_count);
  }

  // ---------------------------------------------------------------- 图表工具
  function chartColors() {
    const dark = state.theme === 'dark';
    return {
      text: dark ? '#9aa1ad' : '#6b7280',
      grid: dark ? 'rgba(255,255,255,.06)' : 'rgba(0,0,0,.06)',
      in: dark ? '#60a5fa' : '#3b82f6',
      out: dark ? '#a78bfa' : '#8b5cf6',
      cost: dark ? '#fbbf24' : '#d97706',
      requests: dark ? '#4ade80' : '#16a34a',
      palette: dark
        ? ['#60a5fa', '#a78bfa', '#4ade80', '#fbbf24', '#f87171', '#22d3ee', '#f472b6', '#a3e635']
        : ['#3b82f6', '#8b5cf6', '#16a34a', '#d97706', '#dc2626', '#0891b2', '#db2777', '#65a30d'],
    };
  }

  function destroyChart(key) {
    if (state.charts[key]) { try { state.charts[key].destroy(); } catch (_) {} delete state.charts[key]; }
  }

  async function loadTodayChart() {
    const data = await get('/api/series', { kind: 'hour', range: '24h', tz: tzOffsetSec() });
    const series = data.series || [];
    const c = chartColors();
    destroyChart('today');
    state.charts.today = new Chart($('chartToday'), {
      type: 'bar',
      data: {
        labels: series.map((s) => s.bucket.slice(11, 16)),
        datasets: [
          { label: t('token.in'), data: series.map((s) => s.tokens_in), backgroundColor: c.in, borderRadius: 3, yAxisID: 'y' },
          { label: t('token.out'), data: series.map((s) => s.tokens_out), backgroundColor: c.out, borderRadius: 3, yAxisID: 'y1' },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: c.text, boxWidth: 10, boxHeight: 10, usePointStyle: true } },
          tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${fmtInt(item.parsed.y)}` } },
        },
        scales: {
          x: { ticks: { color: c.text, maxRotation: 0, autoSkip: true }, grid: { display: false } },
          // 输入（百万级）与输出（千级）量级差异大，分列左右轴保证两者可见
          y: {
            position: 'left', beginAtZero: true,
            ticks: { color: c.text, callback: (v) => fmtCompact(v) }, grid: { color: c.grid },
          },
          y1: {
            position: 'right', beginAtZero: true,
            ticks: { color: c.text, callback: (v) => fmtCompact(v) }, grid: { display: false },
          },
        },
      },
    });
  }

  // ---------------------------------------------------------------- 统计
  async function loadStats(range) {
    range = resolveStatsRange(range);
    loadSeriesStats(range);
    loadModelStats(range);
    loadTrend(range);
  }

  /** 数据跨度不足所选范围时回退到「全部」，避免出现几乎空白的图表。 */
  function resolveStatsRange(range) {
    const data = state.status && state.status.data;
    if (!data || !data.min_ts || !data.max_ts) return range;
    const spanDays = (data.max_ts - data.min_ts) / 86400;
    const needsFallback = (range === '7d' && spanDays < 6)
      || (range === '30d' && spanDays < 25)
      || (range === 'billing' && spanDays < 6);
    if (!needsFallback) return range;
    state.statsRange = 'all';
    const btn = document.querySelector('#statsRange .tab[data-range="all"]');
    if (btn) toggleTabs('statsRange', btn);
    return 'all';
  }

  async function loadSeriesStats(range) {
    const [ovData, seriesData] = await Promise.all([
      get('/api/overview', { range }),
      get('/api/series', { kind: 'day', range, tz: tzOffsetSec() }),
    ]);
    const o = ovData.overview || {};
    const total = (o.tokens_in || 0) + (o.tokens_out || 0);
    const inPct = total > 0 ? (o.tokens_in / total) * 100 : 50;
    $('segIn').style.width = inPct.toFixed(1) + '%';
    $('segOut').style.width = (100 - inPct).toFixed(1) + '%';
    $('tokenInVal').textContent = fmtCompact(o.tokens_in);
    $('tokenOutVal').textContent = fmtCompact(o.tokens_out);

    $('costRows').innerHTML = [
      [t('cost.input'), fmtCost(o.cost_input)],
      [t('cost.output'), fmtCost(o.cost_output)],
      [t('cost.cache'), fmtCost(o.cost_cache)],
      [t('cost.total'), fmtCost(o.cost_total)],
    ].map(([k, v]) => `<div class="row"><span class="muted">${k}</span><b>${v}</b></div>`).join('');
    void seriesData;
  }

  async function loadModelStats(range) {
    const data = await get('/api/models', { range });
    const models = data.models || [];
    const c = chartColors();

    const tbody = $('modelTable').querySelector('tbody');
    tbody.innerHTML = models.length
      ? models.map((m) => `<tr>
          <td>${escapeHtml(m.model)}</td>
          <td class="num">${fmtInt(m.requests)}</td>
          <td class="num">${fmtCompact(m.tokens_in)}</td>
          <td class="num">${fmtCompact(m.tokens_out)}</td>
          <td class="num">${fmtCompact(m.total_tokens)}</td>
          <td class="num">${fmtCost(m.cost_total)}</td>
        </tr>`).join('')
      : `<tr><td colspan="6" class="empty">${t('empty.models')}</td></tr>`;

    destroyChart('models');
    if (models.length) {
      state.charts.models = new Chart($('chartModels'), {
        type: 'doughnut',
        data: {
          labels: models.map((m) => shortModelName(m.model)),
          datasets: [{
            data: models.map((m) => m.cost_total),
            backgroundColor: c.palette,
            borderWidth: 0,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '60%',
          plugins: {
            legend: {
              position: 'right',
              labels: { color: c.text, boxWidth: 10, usePointStyle: true, font: { size: 11 } },
            },
            tooltip: { callbacks: { label: (item) => `${item.label}: ${fmtCost(item.parsed)}` } },
          },
        },
      });
    }
  }

  /** 模型短名：`deepseek/deepseek-v4.1-flash` → `deepseek-v4.1-flash`（图例用）。 */
  function shortModelName(name) {
    const text = String(name || '');
    const parts = text.split('/');
    return parts.length > 1 ? parts.slice(1).join('/') : text;
  }

  async function loadTrend(range) {
    const kind = ['24h', 'today'].includes(range) ? 'hour' : 'day';
    const data = await get('/api/series', { kind, range, tz: tzOffsetSec() });
    state.trendSeries = data.series || [];
    state.trendLabels = state.trendSeries.map((s) => (kind === 'hour' ? s.bucket.slice(11, 16) : s.bucket.slice(5)));
    renderTrend();
  }

  /** 渲染趋势主图：单图 + 指标切换（费用 / 请求数 / Token），固定画布高度。 */
  function renderTrend() {
    const series = state.trendSeries;
    const labels = state.trendLabels;
    const c = chartColors();
    destroyChart('trend');
    updateTrendMeta(series);
    if (!series || !series.length) return;

    let config;
    if (state.trendMetric === 'requests') {
      config = {
        type: 'bar',
        data: {
          labels,
          datasets: [{
            label: t('table.requests'),
            data: series.map((s) => s.requests),
            backgroundColor: c.requests,
            borderRadius: 3,
            maxBarThickness: 26,
          }],
        },
        options: trendOptions(c, fmtInt),
      };
    } else if (state.trendMetric === 'tokens') {
      // 输入（百万级）与输出（千级）用堆叠面积呈现，两者都可见
      config = {
        type: 'line',
        data: {
          labels,
          datasets: [
            {
              label: t('token.in'), data: series.map((s) => s.tokens_in),
              borderColor: c.in, backgroundColor: c.in + 'cc',
              fill: true, tension: .3, borderWidth: 1.5,
              pointRadius: series.length > 40 ? 0 : 2, stack: 'tok',
            },
            {
              label: t('token.out'), data: series.map((s) => s.tokens_out),
              borderColor: c.out, backgroundColor: c.out + 'cc',
              fill: true, tension: .3, borderWidth: 1.5,
              pointRadius: series.length > 40 ? 0 : 2, stack: 'tok',
            },
          ],
        },
        options: trendOptions(c, fmtCompact, { stacked: true, legend: true }),
      };
    } else {
      config = {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: t('table.cost'),
            data: series.map((s) => s.cost_total),
            borderColor: c.cost,
            backgroundColor: c.cost + '33',
            fill: true, tension: .3, borderWidth: 2,
            pointRadius: series.length > 40 ? 0 : 3,
          }],
        },
        options: trendOptions(c, fmtCost, { axisFormatter: fmtCostAxis }),
      };
    }
    state.charts.trend = new Chart($('chartTrend'), config);
  }

  /** 更新趋势卡的「本范围合计」与稀疏数据提示。 */
  function updateTrendMeta(series) {
    const list = series || [];
    const sum = (key) => list.reduce((acc, item) => acc + (item[key] || 0), 0);
    const summaryMap = {
      cost: t('stats.sumCost', { v: fmtCost(sum('cost_total')) }),
      requests: t('stats.sumRequests', { v: fmtInt(sum('requests')) }),
      tokens: t('stats.sumTokens', { v: fmtCompact(sum('total_tokens')) }),
    };
    const summaryEl = $('trendSummary');
    if (summaryEl) summaryEl.textContent = list.length ? (summaryMap[state.trendMetric] || '') : '';
    const hintEl = $('trendHint');
    if (hintEl) hintEl.textContent = (list.length && list.length < 4) ? t('stats.sparseHint') : '';
  }

  /** 趋势图通用配置：单一 Y 轴（每图一个量纲），固定高度容器。 */
  function trendOptions(c, formatter, extra) {
    const opts = extra || {};
    const axisFormatter = opts.axisFormatter || formatter;
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: !!opts.legend,
          labels: { color: c.text, boxWidth: 10, usePointStyle: true },
        },
        tooltip: {
          callbacks: {
            label: (item) => {
              const name = item.dataset.label ? `${item.dataset.label}: ` : '';
              return `${name}${formatter(item.parsed.y)}`;
            },
          },
        },
      },
      scales: {
        x: {
          stacked: !!opts.stacked,
          ticks: { color: c.text, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 },
          grid: { display: false },
        },
        y: {
          stacked: !!opts.stacked,
          beginAtZero: true,
          ticks: { color: c.text, maxTicksLimit: 6, callback: (value) => axisFormatter(value) },
          grid: { color: c.grid },
        },
      },
    };
  }

  // ---------------------------------------------------------------- 记录
  async function loadDailyRecords() {
    const data = await get('/api/daily-models', { range: '30d', tz: tzOffsetSec() });
    const rows = data.rows || [];
    const tbody = $('dailyTable').querySelector('tbody');
    tbody.innerHTML = rows.length
      ? rows.slice(0, 60).map((r) => `<tr>
          <td>${r.day}</td>
          <td>${escapeHtml(r.model)}</td>
          <td class="num">${fmtInt(r.requests)}</td>
          <td class="num">${fmtCompact(r.tokens_in)}</td>
          <td class="num">${fmtCompact(r.tokens_out)}</td>
          <td class="num">${fmtCost(r.cost_total)}</td>
          <td class="num">${fmtDuration(r.avg_duration_ms)}</td>
        </tr>`).join('')
      : `<tr><td colspan="7" class="empty">${t('empty.records')}</td></tr>`;
  }

  async function loadRecordPage(page) {
    state.recordPage = page;
    const params = { page, page_size: state.recordPageSize, range: 'all' };
    if (state.recordModel) params.model = state.recordModel;
    const data = await get('/api/records', params);
    const items = data.items || [];
    const tbody = $('recordTable').querySelector('tbody');
    tbody.innerHTML = items.length
      ? items.map((r) => `<tr>
          <td class="mono">${fmtTime(r.created_ts)}</td>
          <td>${escapeHtml(r.model)}</td>
          <td>${escapeHtml(r.mode || '')}</td>
          <td class="num">${fmtCompact(r.tokens_in)}</td>
          <td class="num">${fmtCompact(r.tokens_out)}</td>
          <td class="num">${fmtCompact(r.total_tokens)}</td>
          <td class="num">${fmtDuration(r.duration_ms)}</td>
          <td class="num">${fmtCost(r.cost_total)}</td>
        </tr>`).join('')
      : `<tr><td colspan="8" class="empty">${t('empty.records')}</td></tr>`;
    const totalPages = Math.max(1, Math.ceil((data.total || 0) / state.recordPageSize));
    $('pageInfo').textContent = data.total ? t('page.info', { p: page, t: totalPages, n: fmtInt(data.total) }) : t('page.none');
    $('prevPage').disabled = page <= 1;
    $('nextPage').disabled = page >= totalPages;
  }

  async function loadRecordModels() {
    const data = await get('/api/models-list');
    const select = $('recordModelFilter');
    const current = state.recordModel;
    select.innerHTML = `<option value="">${state.lang === 'zh' ? '全部模型' : 'All models'}</option>` +
      (data.models || []).map((m) => `<option value="${escapeAttr(m)}">${escapeHtml(m)}</option>`).join('');
    select.value = current;
  }

  // ---------------------------------------------------------------- 设置
  async function loadSettings() {
    const data = await get('/api/settings');
    const s = data.settings || {};
    if (s.sync_interval_min) $('setInterval').value = s.sync_interval_min;
    if (s.sync_range_days !== undefined) $('setRange').value = s.sync_range_days;
    if (s.currency_mode) state.currencyMode = s.currency_mode;
    toggleSeg('currencySeg', 'currencyValue', state.currencyMode);
    updateRateInfo();
    $('setUserName').textContent = s.user_name || '--';
    const plan = state.status && state.status.plan;
    $('setPlan').textContent = plan && plan.name ? plan.name : '--';
    $('setCredential').textContent = s.cookie_header ? '✓' : '--';
    $('btnLogout').disabled = !s.cookie_header;
  }

  /** 汇率信息行（设置页）。 */
  function updateRateInfo() {
    const el = $('rateInfo');
    if (!el) return;
    el.textContent = state.rate > 0
      ? t('settings.rateInfo', { r: Number(state.rate).toFixed(4) })
      : t('settings.rateFailed');
  }

  // ---------------------------------------------------------------- 工具
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  const escapeAttr = escapeHtml;

  // ---------------------------------------------------------------- 登录/退出
  async function doLogin() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_login) {
      await window.pywebview.api.open_login();
      toast(t('toast.loginOpened'));
      return;
    }
    const res = await post('/api/login');
    toast(res.ok ? t('toast.loginOpened') : t('toast.loginUnavailable'), res.ok);
  }

  async function doQuit() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.quit) {
      await window.pywebview.api.quit();
      return;
    }
    toast(state.lang === 'zh' ? '请通过系统托盘图标退出应用' : 'Use the tray icon to quit', false);
  }

  async function doSync(mode) {
    const res = await post('/api/sync', { mode: mode || 'incremental' });
    if (res.ok) {
      toast(t('toast.syncStarted'));
      setTimeout(refreshAll, 1500);
    } else {
      toast(res.error || 'sync failed', false);
    }
  }

  // ---------------------------------------------------------------- 刷新
  async function refreshAll() {
    const status = await loadStatus();
    if (!status.logged_in) return status;
    renderAll();
    return status;
  }

  function renderAll() {
    loadPage(state.page);
  }

  // ---------------------------------------------------------------- 事件绑定
  function bindEvents() {
    $('nav').addEventListener('click', (e) => {
      const btn = e.target.closest('.nav-item');
      if (btn) switchPage(btn.dataset.page);
    });

    $('themeBtn').addEventListener('click', () => applyTheme(state.theme === 'light' ? 'dark' : 'light'));
    $('langBtn').addEventListener('click', () => applyLang(state.lang === 'zh' ? 'en' : 'zh'));

    $('themeSeg').addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (btn) { applyTheme(btn.dataset.themeValue); persistSetting('theme', btn.dataset.themeValue); }
    });
    $('langSeg').addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (btn) { applyLang(btn.dataset.langValue); persistSetting('lang', btn.dataset.langValue); }
    });

    $('syncBtn').addEventListener('click', () => doSync('incremental'));
    $('welcomeLoginBtn').addEventListener('click', doLogin);
    $('welcomeQuitBtn').addEventListener('click', doQuit);
    $('btnRelogin').addEventListener('click', doLogin);
    $('btnLogout').addEventListener('click', async () => {
      await post('/api/logout');
      toast(t('toast.loggedOut'));
      refreshAll();
    });
    $('btnSyncIncremental').addEventListener('click', () => doSync('incremental'));
    $('btnSyncFull').addEventListener('click', () => doSync('full'));

    $('setInterval').addEventListener('change', (e) => persistSetting('sync_interval_min', e.target.value));
    $('setRange').addEventListener('change', (e) => persistSetting('sync_range_days', e.target.value));

    $('currencySeg').addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      state.currencyMode = btn.dataset.currencyValue;
      toggleSeg('currencySeg', 'currencyValue', state.currencyMode);
      persistSetting('currency_mode', state.currencyMode);
      renderAll();          // 金额全部重绘
    });

    $('homeRange').addEventListener('click', (e) => {
      const btn = e.target.closest('.tab');
      if (!btn) return;
      state.homeRange = btn.dataset.range;
      toggleTabs('homeRange', btn);
      loadOverview(state.homeRange);
      loadTodayChart();
    });

    $('statsRange').addEventListener('click', (e) => {
      const btn = e.target.closest('.tab');
      if (!btn) return;
      state.statsRange = btn.dataset.range;
      toggleTabs('statsRange', btn);
      loadStats(state.statsRange);
    });

    $('trendMetric').addEventListener('click', (e) => {
      const btn = e.target.closest('.tab');
      if (!btn) return;
      state.trendMetric = btn.dataset.metric;
      toggleTabs('trendMetric', btn);
      try {
        history.replaceState(null, '', `?page=stats&metric=${state.trendMetric}`);
      } catch (_) { /* 非浏览器环境忽略 */ }
      renderTrend();   // 用缓存序列直接重绘，不重新请求
    });

    $('prevPage').addEventListener('click', () => loadRecordPage(Math.max(1, state.recordPage - 1)));
    $('nextPage').addEventListener('click', () => loadRecordPage(state.recordPage + 1));
    $('recordsRefresh').addEventListener('click', () => { loadDailyRecords(); loadRecordPage(state.recordPage); });
    $('recordModelFilter').addEventListener('change', (e) => { state.recordModel = e.target.value; loadRecordPage(1); });

    window.addEventListener('resize', () => {
      Object.values(state.charts).forEach((c) => { try { c.resize(); } catch (_) {} });
    });
  }

  function toggleTabs(groupId, activeBtn) {
    $(groupId).querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b === activeBtn));
  }

  /** 分段按钮通用切换（按 dataset 键匹配）。 */
  function toggleSeg(groupId, dataKey, value) {
    $(groupId).querySelectorAll('button').forEach((b) => {
      b.classList.toggle('active', b.dataset[dataKey] === value);
    });
  }

  async function persistSetting(key, value) {
    try {
      await post('/api/settings', { [key]: value });
      toast(t('toast.settingsSaved'));
    } catch (err) {
      toast(String(err), false);
    }
  }

  // pywebview 登录成功回调
  window.ccgaugeOnDataChanged = () => { refreshAll(); };
  window.ccgaugeOnLoginSuccess = () => { refreshAll(); };

  // ---------------------------------------------------------------- 初始化
  async function init() {
    // 首次运行时（无本地缓存）采用服务端保存的主题 / 语言
    try {
      const remote = await get('/api/settings');
      const saved = remote.settings || {};
      if (!localStorage.getItem('ccgauge.theme') && saved.theme) {
        state.theme = saved.theme;
      }
      if (!localStorage.getItem('ccgauge.lang') && saved.lang) {
        state.lang = saved.lang;
      }
      if (saved.currency_mode) {
        state.currencyMode = saved.currency_mode;
      }
    } catch (_) { /* 服务端不可用时使用本地默认 */ }
    // 汇率（USD→CNY，24 小时缓存；获取失败则仅显示美元）
    try {
      const rateInfo = await get('/api/rate');
      state.rate = Number(rateInfo.rate) || 0;
      if (rateInfo.mode) state.currencyMode = rateInfo.mode;
    } catch (_) { /* 保持仅美元 */ }
    applyTheme(state.theme);
    applyLang(state.lang);
    bindEvents();
    // 支持 ?page=stats 直达（刷新保持当前页）
    const urlPage = new URLSearchParams(location.search).get('page');
    const urlMetric = new URLSearchParams(location.search).get('metric');
    if (urlMetric && ['cost', 'requests', 'tokens'].includes(urlMetric)) {
      state.trendMetric = urlMetric;
      const metricBtn = document.querySelector(`#trendMetric .tab[data-metric="${urlMetric}"]`);
      if (metricBtn) toggleTabs('trendMetric', metricBtn);
    }
    try {
      const status = await refreshAll();
      if (status && status.logged_in && urlPage && PAGE_KEYS.includes(urlPage) && urlPage !== 'home') {
        switchPage(urlPage);
      }
    } catch (err) {
      toast(String(err), false);
    }
    // 同步中状态轮询
    state.pollTimer = setInterval(async () => {
      try {
        const status = await get('/api/status');
        const wasSyncing = state.status && state.status.syncing;
        state.status = status;
        if (wasSyncing && !status.syncing) { toast(t('toast.syncDone', { n: status.sync.inserted || 0 })); renderAll(); }
        loadStatus();
      } catch (_) { /* 忽略轮询错误 */ }
    }, 5000);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
