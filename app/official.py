# -*- coding: utf-8 -*-
"""官方套餐与模型信息：抓取 commandcode.ai 公开文档页并解析为结构化数据。

数据来源（均为公开页面，无需登录，不发送任何本地数据）：
- ``/docs/plans/<slug>``：套餐内每模型月度额度上限、每模型 5h/周/月次数估算、每模型单价
- ``/docs/resources/pricing-limits``：全模型单价表、套餐月额度与 5h/周窗口上限

实现约束（详见 .op/changes/official-plan-info/research/findings.md）：
- 官方**没有** JSON 接口（``/api/models``、``/alpha/models`` 实测 404），数据内嵌在 HTML 与
  Next.js RSC flight 文本（``self.__next_f.push([1,"..."])``）中；
- 标签解析必须用 :class:`html.parser.HTMLParser` 状态机：属性值内可能含 ``>``
  （如 ``class="[&[role=checkbox]>svg]:..."``），正则按 ``<td[^>]*>`` 切会截断；
- 单元格含渲染噪声：``<!-- -->`` 注释、折叠标记 ``+1``、排序符号 ``↕``、
  优惠双值（原价 + 现价）、``Free``、``—``；
- 解析结果需按「表头语义」识别表类型，不依赖表顺序。
"""
from __future__ import annotations

import html as html_mod
import json
import re
import time
from html.parser import HTMLParser
from typing import Optional

import requests

DOCS_BASE = "https://commandcode.ai"
PLAN_PAGE_TMPL = DOCS_BASE + "/docs/plans/{slug}"
PRICING_LIMITS_URL = DOCS_BASE + "/docs/resources/pricing-limits"

HTTP_TIMEOUT_SEC = 30
USER_AGENT = "CCGauge/0.2 (+local usage panel)"

# 订阅 planId → 官方文档页 slug（实测可用的 slug：go / goat / pro / max）
PLAN_SLUGS = {
    "individual-go": "go",
    "individual-goat": "goat",
    "individual-pro": "pro",
    "individual-pro-v1": "pro",
    "individual-max": "max",
}

# 官方口径的「典型请求」结构（官方文档：~800 fresh input、~200 output、~50K cache read）
TYPICAL_SHAPE = {"input_tokens": 800, "output_tokens": 200, "cache_read_tokens": 50000}

# 非模型值（本地 usage 的 model 字段里可能混入工具名）
NON_MODEL_VALUES = {"web_fetch", "web_search", "(unknown)"}

_FLIGHT_RE = re.compile(r"self\.__next_f\.push\(\[1,(\"(?:[^\"\\]|\\.)*\")\]\)", re.S)
_MONEY_RE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?)")
_INT_RE = re.compile(r"([0-9][0-9,]*)")
_MULT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*([KM])", re.I)


class OfficialDataError(Exception):
    """官方数据抓取或解析失败。"""


# --------------------------------------------------------------------- HTTP


def fetch_page_text(url: str, timeout: int = HTTP_TIMEOUT_SEC) -> str:
    """抓取页面并返回「HTML + RSC flight 文本」拼接后的可解析文本。"""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    except requests.RequestException as exc:
        raise OfficialDataError(f"{url} 网络错误: {exc}") from exc
    if resp.status_code != 200:
        raise OfficialDataError(f"{url} 请求失败（HTTP {resp.status_code}）")
    return flatten_payload(resp.text)


def flatten_payload(raw_html: str) -> str:
    """把 Next.js flight 分片反转义后与原始 HTML 拼接，供表格解析使用。"""
    parts = [raw_html]
    for chunk in _FLIGHT_RE.findall(raw_html):
        try:
            parts.append(json.loads(chunk))
        except ValueError:
            parts.append(html_mod.unescape(chunk))
    return "\n".join(parts)


# ----------------------------------------------------------------- 表格解析


_BLOCK_TAGS = {"div", "p", "span", "li", "a", "b", "strong", "em", "code", "small", "svg"}
_MONEY_ONLY_RE = re.compile(r"^\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)$")


class Cell(str):
    """单元格文本（``str`` 子类）。

    额外保留：
    - ``lead``：首个非空片段（模型名等主信息）
    - ``note``：其余片段合并（倍率 / 优惠 / 时段等补充说明，常来自 title / sr-only）
    - ``money``：仅由「纯金额片段」解析出的数值列表，避免把说明文字里的价格当现值
    """

    lead: str = ""
    note: str = ""
    money: tuple = ()


def _make_cell(fragments: list[str]) -> Cell:
    parts = [p for p in (_clean_cell(f) for f in fragments) if p]
    cell = Cell(_clean_cell("".join(fragments)))
    cell.lead = parts[0] if parts else ""
    cell.note = " ".join(parts[1:]) if len(parts) > 1 else ""
    values = []
    for part in parts:
        match = _MONEY_ONLY_RE.match(part)
        if match:
            values.append(float(match.group(1).replace(",", "")))
    cell.money = tuple(values)
    return cell


def primary(cell) -> str:
    """取单元格主信息（有 ``lead`` 时用它，否则用全文）。"""
    lead = getattr(cell, "lead", "")
    return lead or str(cell)


class _TableCollector(HTMLParser):
    """按标签状态机收集 ``<table>`` 单元格（对含 ``>`` 的属性值免疫）。

    每个单元格按内部块级/行内标签切成若干片段：首片段是模型名等主信息，
    其余片段是该单元格里的补充说明（如倍率备注、优惠说明），分别保留。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list["Cell"]]] = []
        self._rows: Optional[list[list[Cell]]] = None
        self._row: Optional[list[Cell]] = None
        self._frags: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: D102
        if tag == "table":
            self._rows = []
        elif tag == "tr" and self._rows is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._frags = [""]
        elif tag == "br" and self._frags is not None:
            self._frags.append(" ")
        elif self._frags is not None and tag in _BLOCK_TAGS:
            self._frags.append("")

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: D102
        if tag == "br" and self._frags is not None:
            self._frags.append(" ")

    def handle_data(self, data: str) -> None:  # noqa: D102
        if self._frags is not None:
            self._frags[-1] += data

    def handle_endtag(self, tag: str) -> None:  # noqa: D102
        if tag in ("td", "th") and self._frags is not None and self._row is not None:
            self._row.append(_make_cell(self._frags))
            self._frags = None
        elif tag == "tr" and self._row is not None and self._rows is not None:
            if any(str(c) for c in self._row):
                self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._rows is not None:
            if self._rows:
                self.tables.append(self._rows)
            self._rows = None


def _clean_cell(text: str) -> str:
    """单元格文本清洗：去注释残留、排序符号、折叠标记，压缩空白。"""
    text = text.replace("<!-- -->", "")
    text = text.replace("\u2195", " ").replace("\u21c5", " ").replace("\u2190", " ")
    text = re.sub(r"\+\d+\s*$", "", text.strip())          # 折叠标记 +1
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_tables(text: str) -> list[list[list[str]]]:
    """解析出所有表格（表格 → 行 → 单元格）。"""
    collector = _TableCollector()
    collector.feed(text)
    collector.close()
    return collector.tables


def _header_of(table: list[list[str]]) -> list[str]:
    return [c.lower() for c in table[0]] if table else []


def _is_catalog(header: list[str]) -> bool:
    return bool(header) and header[0].startswith("model") and "context" in header


def _is_estimates(header: list[str]) -> bool:
    return bool(header) and header[0].startswith("model") and any("requests / " in h for h in header)


def _is_allowances(header: list[str]) -> bool:
    return bool(header) and header[0].startswith("model") and any("monthly credits" in h for h in header)


def _is_windows(header: list[str]) -> bool:
    return bool(header) and header[0].startswith("plan") and any("5-hour limit" in h for h in header)


def _is_plans(header: list[str]) -> bool:
    return bool(header) and header[0].startswith("plan") and any(h.startswith("credits/mo") for h in header)


# --------------------------------------------------------------- 值解析辅助

def parse_money(text) -> tuple[Optional[float], Optional[float]]:
    """解析金额单元格，返回 ``(was, now)``。

    优惠单元格形如 ``$0.60$0.30``（原价 + 现价）→ ``(0.60, 0.30)``；
    单值单元格 → ``(None, 值)``；``Free`` / ``—`` → ``(None, None)``。
    带 ``title`` / ``sr-only`` 说明的单元格只用「纯金额片段」，避免把说明文字里的
    峰时价格当成本行现价。
    """
    values = list(getattr(text, "money", ()) or ())
    if not values:
        raw = str(text or "")
        if not raw or raw.strip() in ("—", "-", "–", "Free", "FREE", "免费"):
            return (None, None)
        values = [float(v.replace(",", "")) for v in _MONEY_RE.findall(raw)]
    if not values:
        return (None, None)
    if len(values) == 1:
        return (None, values[0])
    return (values[0], values[-1])


def parse_int(text) -> Optional[int]:
    """解析计数单元格（``30,800`` / ``~75K`` / ``1.1M``）；只看单元格主信息。"""
    body = primary(text).strip().replace(",", "")
    if not body:
        return None
    match = _MULT_RE.search(body)
    if match:
        value = float(match.group(1)) * (1000 if match.group(2).upper() == "K" else 1000000)
        return int(round(value))
    match = _INT_RE.search(body)
    if match:
        return int(match.group(1))
    return None


def parse_context(text) -> Optional[str]:
    """解析上下文长度（``1M`` / ``256K`` / ``1.1M``）。"""
    match = _MULT_RE.search(primary(text).strip())
    return f"{match.group(1)}{match.group(2).upper()}" if match else None


def parse_rate(text: str) -> tuple[Optional[float], Optional[str]]:
    """解析单价单元格，返回 ``(现值, 原始文本)``。"""
    was, now = parse_money(text)
    if now is None and was is None:
        return (None, text.strip())
    return (now, text.strip())


def is_free_cell(text: str) -> bool:
    return (text or "").strip().lower() in ("free", "免费", "$0", "$0.00", "$0.000")


def _rate_display(cell) -> Optional[str]:
    """单价单元格的展示文本（保留优惠的原价 → 现价），空白 / ``—`` 返回 None。"""
    raw = str(cell or "").strip()
    if not raw or raw in ("—", "-", "–"):
        return None
    if is_free_cell(raw) or is_free_cell(getattr(cell, "lead", "")):
        return "Free"
    was, now = parse_money(cell)
    if now is not None and was is not None and abs(was - now) > 1e-9:
        return f"${was:g} → ${now:g}"
    if now is not None:
        return f"${now:g}"
    return raw


# ------------------------------------------------------------- 名称规范化

def normalize_model_key(name: str) -> str:
    """模型名规范化：去厂商前缀与括号后缀，仅保留字母数字，便于与本地 slug 对齐。

    ``DeepSeek V4.1 Flash`` → ``deepseekv41flash``；
    ``deepseek/deepseek-v4.1-flash`` → ``deepseekv41flash``。
    """
    text = str(name or "").strip()
    if "/" in text:
        head, _, tail = text.partition("/")
        # 仅在“厂商前缀”形态下剥离（前缀不含空格且与主体不同）
        if head and " " not in head and tail:
            text = tail
    text = re.sub(r"\([^)]*\)", "", text)      # 去括号后缀，如 (latest)、(exp)
    text = re.sub(r"[^0-9a-zA-Z]+", "", text)
    return text.lower()


def is_model_value(name: str) -> bool:
    """判断本地 ``model`` 字段是否是真实模型名（排除 ``web_fetch`` 等工具值）。"""
    value = str(name or "").strip()
    return bool(value) and value.lower() not in NON_MODEL_VALUES


# ------------------------------------------------------------- 页面 → 快照

def parse_plan_page(text: str, slug: str) -> dict:
    """解析套餐文档页：每模型单价 / 额度上限 / 次数估算 + 套餐窗口额度。"""
    catalog: dict[str, dict] = {}
    allowances: dict[str, float] = {}
    estimates: dict[str, dict] = {}
    plan_limits: dict = {}

    for table in parse_tables(text):
        header = _header_of(table)
        if _is_catalog(header):
            for row in table[1:]:
                if len(row) < 4 or not row[0]:
                    continue
                name = primary(row[0]).strip()
                key = normalize_model_key(name)
                if not key:
                    continue
                entry = catalog.setdefault(key, {"name": name, "rates_raw": {}, "note": None})
                entry["name"] = name
                if getattr(row[0], "note", ""):
                    entry["note"] = row[0].note
                entry["context"] = parse_context(row[1])
                cells = row[4:] if len(row) >= 8 else row[2:]
                labels = ["input", "output", "cache_read", "cache_write"]
                for label, cell in zip(labels, cells):
                    display = _rate_display(cell)
                    if display is not None:
                        entry["rates_raw"][label] = display
        elif _is_estimates(header):
            for row in table[1:]:
                if len(row) < 4 or not row[0]:
                    continue
                estimates[normalize_model_key(primary(row[0]))] = {
                    "five_hour": parse_int(row[1]),
                    "weekly": parse_int(row[2]),
                    "monthly": parse_int(row[3]),
                }
        elif _is_allowances(header):
            for row in table[1:]:
                if len(row) < 6 or not row[0]:
                    continue
                _, now = parse_money(row[5])
                if now is not None:
                    name = primary(row[0]).strip()
                    allowances[normalize_model_key(name)] = {"name": name, "amount": now}
        elif _is_windows(header):
            for row in table[1:]:
                if len(row) < 5 or not row[0]:
                    continue
                _, monthly = parse_money(row[2])
                _, five_hour = parse_money(row[3])
                _, weekly = parse_money(row[4])
                plan_limits[row[0].strip().lower()] = {
                    "monthly_credits": monthly,
                    "five_hour": five_hour,
                    "weekly": weekly,
                }

    models = []
    for key, entry in catalog.items():
        rates: dict[str, Optional[float]] = {}
        for label in ("input", "output", "cache_read", "cache_write"):
            raw = entry["rates_raw"].get(label)
            rates[label] = parse_rate(raw)[0] if raw is not None else None
        free_cells = [
            entry["rates_raw"].get(label, "")
            for label in ("input", "output", "cache_read")
        ]
        free = bool([c for c in free_cells if c]) and all(is_free_cell(c) for c in free_cells if c)
        allowance = allowances.get(key) or {}
        models.append({
            "name": entry["name"],
            "key": key,
            "context": entry.get("context"),
            "rates": rates,
            "rates_raw": entry["rates_raw"],
            "free": free,
            "note": entry.get("note"),
            "allowance": allowance.get("amount"),
            "requests": estimates.get(key),
            "in_plan": True,
        })

    # 额度表里出现但目录表未收录的模型（例如目录表折叠）也补进来
    known = {m["key"] for m in models}
    for key, allowance in allowances.items():
        if key in known:
            continue
        models.append({
            "name": allowance.get("name") or key,
            "key": key,
            "context": None,
            "rates": {"input": None, "output": None, "cache_read": None, "cache_write": None},
            "rates_raw": {},
            "free": False,
            "note": None,
            "allowance": allowance.get("amount"),
            "requests": estimates.get(key),
            "in_plan": True,
        })

    return {
        "plan_slug": slug,
        "plan_name": None,
        "plan_limits": plan_limits,
        "models": models,
    }


def parse_pricing_limits(text: str) -> dict:
    """解析 pricing-limits 页：套餐概览（月额度 / 5h / 周窗口）+ 全模型单价目录。"""
    plans: dict[str, dict] = {}
    windows: dict[str, dict] = {}

    for table in parse_tables(text):
        header = _header_of(table)
        if _is_plans(header):
            for row in table[1:]:
                if len(row) < 3 or not row[0]:
                    continue
                _, price = parse_money(row[1])
                _, credits = parse_money(row[2])
                plans[row[0].strip()] = {"price": price, "monthly_credits": credits}
        elif _is_windows(header):
            for row in table[1:]:
                if len(row) < 5 or not row[0]:
                    continue
                _, cost = parse_money(row[1])
                _, monthly = parse_money(row[2])
                _, five_hour = parse_money(row[3])
                _, weekly = parse_money(row[4])
                windows[row[0].strip()] = {
                    "cost": cost,
                    "monthly_credits": monthly,
                    "five_hour": five_hour,
                    "weekly": weekly,
                }

    for name, window in windows.items():
        plans.setdefault(name, {})
        plans[name].update(window)
    return {"plans": plans, "windows": windows}


def fetch_official_snapshot(slug: Optional[str], timeout: int = HTTP_TIMEOUT_SEC) -> dict:
    """抓取并合并官方数据，返回可直接落库的快照。

    Args:
        slug: 套餐文档页 slug（``goat`` / ``pro`` / ``go`` / ``max``）；``None`` 时只抓
            pricing-limits，模型列表不含套餐额度。
    """
    pricing = parse_pricing_limits(fetch_page_text(PRICING_LIMITS_URL, timeout))
    snapshot: dict = {
        "plan_slug": slug,
        "plan_name": None,
        "plan_limits": {},
        "models": [],
        "plans": pricing["plans"],
        "fallback": slug is None,
        "sources": {"pricing": PRICING_LIMITS_URL, "plan_page": None},
        "fetched_at": int(time.time()),
    }
    if not slug:
        return snapshot

    plan_url = PLAN_PAGE_TMPL.format(slug=slug)
    page = parse_plan_page(fetch_page_text(plan_url, timeout), slug)
    snapshot["sources"]["plan_page"] = plan_url
    snapshot["models"] = page["models"]
    snapshot["plan_name"] = _plan_display_name(slug, pricing["plans"])
    window = _find_plan_window(slug, pricing["plans"])
    snapshot["plan_limits"] = {
        "monthly_credits": window.get("monthly_credits"),
        "five_hour": window.get("five_hour"),
        "weekly": window.get("weekly"),
        "price": window.get("price") or window.get("cost"),
    }
    return snapshot


def _plan_display_name(slug: str, plans: dict) -> Optional[str]:
    for name in plans:
        if name.strip().lower().replace(" ", "") == slug:
            return name.strip()
    return {"go": "Go", "goat": "GOAT", "pro": "Pro", "max": "Max"}.get(slug, slug.upper())


def _find_plan_window(slug: str, plans: dict) -> dict:
    for name, data in plans.items():
        compact = name.strip().lower().replace(" ", "")
        if compact == slug or compact.startswith(slug):
            return data
    return {}


# ------------------------------------------------------------------ 性价比

def implied_cache_read_tokens(cost_component: float, rate: Optional[float]) -> Optional[float]:
    """由某项成本 ÷ 对应官方单价反推 token 数（本地库未存缓存读计数，故为估算值）。"""
    if not rate or cost_component <= 0:
        return None
    return cost_component / (rate / 1e6)


def typical_cost_per_request(rates: dict) -> Optional[float]:
    """按官方「典型请求」结构（800 输入 / 200 输出 / 50K 缓存读）算每请求成本。

    官方文档的「次数估算」正是用这一结构推算；本地未用过的模型也用它估算可跑次数。
    """
    if rates.get("input") is None and rates.get("output") is None and rates.get("cache_read") is None:
        return None
    total = (
        (rates.get("input") or 0.0) * TYPICAL_SHAPE["input_tokens"] / 1e6
        + (rates.get("output") or 0.0) * TYPICAL_SHAPE["output_tokens"] / 1e6
        + (rates.get("cache_read") or 0.0) * TYPICAL_SHAPE["cache_read_tokens"] / 1e6
    )
    return total or None


def _merge_row(model: dict, local: Optional[dict]) -> dict:
    """官方模型记录 + 本地实测用量 → 页面行（含额度进度与可跑次数）。"""
    rates = model.get("rates") or {}
    allowance = model.get("allowance")
    estimates = model.get("requests") or {}
    typical = typical_cost_per_request(rates)
    row = {
        "name": model["name"],
        "key": model["key"],
        "context": model.get("context"),
        "rates": rates,
        "rates_raw": model.get("rates_raw") or {},
        "free": bool(model.get("free")),
        "note": model.get("note"),
        "allowance": allowance,
        "requests": estimates,
        "in_plan": model.get("in_plan", True),
        "used": local is not None,
        "typical_cost_per_request": typical,
        "measured": None,
        "cost_per_request": typical,
        "basis": "typical",
        "value": (allowance / typical) if allowance and typical else None,
        "remaining_requests": None,
        "vs_estimate_ratio": None,
    }
    if local is None:
        monthly = estimates.get("monthly")
        if monthly and row["value"]:
            row["vs_estimate_ratio"] = row["value"] / monthly
        return row

    requests = int(local.get("requests") or 0)
    tokens_in = int(local.get("tokens_in") or 0)
    tokens_out = int(local.get("tokens_out") or 0)
    cost_total = float(local.get("cost_total") or 0.0)
    cost_cache = float(local.get("cost_cache") or 0.0)
    cost_input = float(local.get("cost_input") or 0.0)
    cost_output = float(local.get("cost_output") or 0.0)
    cost_per_request = (cost_total / requests) if requests else None
    # 本地库不存缓存读 token 计数：由缓存成本 ÷ 官方缓存单价反推（估算值）
    cache_tokens = implied_cache_read_tokens(cost_cache, rates.get("cache_read"))
    fresh_tokens = implied_cache_read_tokens(cost_input, rates.get("input"))

    row.update({
        "basis": "measured",
        "cost_per_request": cost_per_request,
        "value": (allowance / cost_per_request) if allowance and cost_per_request else None,
        "remaining_requests": (
            (max(0.0, allowance - cost_total) / cost_per_request)
            if allowance and cost_per_request else None
        ),
        "measured": {
            "requests": requests,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_in_avg": (tokens_in / requests) if requests else None,
            "tokens_out_avg": (tokens_out / requests) if requests else None,
            "fresh_input_tokens_est": fresh_tokens,
            "cache_read_tokens_est": cache_tokens,
            "cost_total": cost_total,
            "cost_input": cost_input,
            "cost_output": cost_output,
            "cost_cache": cost_cache,
            "cache_share": (cost_cache / cost_total) if cost_total else None,
            "cost_per_request": cost_per_request,
            "cost_per_mtok": (cost_total / ((tokens_in + tokens_out) / 1e6)) if (tokens_in + tokens_out) else None,
            "allowance_used_pct": (cost_total / allowance * 100.0) if allowance else None,
            "remaining_credits": (max(0.0, allowance - cost_total) if allowance else None),
            "cost_ratio_vs_typical": (cost_per_request / typical) if cost_per_request and typical else None,
        },
    })
    monthly = estimates.get("monthly")
    if monthly and row["value"]:
        row["vs_estimate_ratio"] = row["value"] / monthly
    return row


def match_local_usage(official_keys: list[str], local_usage: dict[str, dict]) -> dict[str, str]:
    """把本地用量键映射到官方模型键（一对一，避免一个本地模型命中多个官方模型）。

    规则：先精确匹配；剩余项做前缀包含匹配，取「长度差最小」的官方键，
    已被占用的官方键不再复用。
    """
    mapping: dict[str, str] = {}
    taken: set[str] = set()
    official_set = set(official_keys)

    for key in local_usage:
        if key in official_set:
            mapping[key] = key
            taken.add(key)

    for key in local_usage:
        if key in mapping or not key:
            continue
        candidates = [
            ok for ok in official_keys
            if ok not in taken and (ok.startswith(key) or key.startswith(ok))
        ]
        if not candidates:
            continue
        best = min(candidates, key=lambda ok: (abs(len(ok) - len(key)), ok))
        mapping[key] = best
        taken.add(best)
    return mapping


def build_model_rows(
    official_models: list[dict],
    local_usage: dict[str, dict],
    plan_limits: Optional[dict] = None,
) -> dict:
    """把官方模型目录与本地用量合并为页面行，并计算性价比指标。

    Args:
        official_models: 官方模型记录（含 ``rates`` / ``allowance`` / ``requests``）
        local_usage: ``{规范化模型键: {requests, tokens_in, tokens_out, cost_total, cost_cache}}``
        plan_limits: 套餐窗口额度（仅用于响应上下文，不参与单模型计算）

    Returns:
        ``{"rows": [...], "matched": [...], "official_only": [...], "local_only": [...]}``
    """
    mapping = match_local_usage([m["key"] for m in official_models], local_usage)
    by_official: dict[str, dict] = {}
    for local_key, official_key in mapping.items():
        by_official[official_key] = local_usage[local_key]

    rows: list[dict] = []
    matched: list[str] = []
    official_only: list[str] = []

    for model in official_models:
        local = by_official.get(model["key"])
        if local is not None:
            matched.append(model["name"])
        else:
            official_only.append(model["name"])
        rows.append(_merge_row(model, local))

    local_only = [
        {"key": key, "name": usage.get("model") or key}
        for key, usage in sorted(local_usage.items())
        if key not in mapping
    ]
    return {"rows": rows, "matched": matched, "official_only": official_only, "local_only": local_only}


def build_snapshot_response(
    snapshot: Optional[dict],
    local_usage: dict[str, dict],
    stale: bool = False,
    error: Optional[str] = None,
) -> dict:
    """把落库快照 + 本地用量整理为 ``/api/official-models`` 的返回体。"""
    if not snapshot:
        return {
            "ok": False,
            "stale": True,
            "error": error or "暂无官方数据",
            "models": [],
            "unmatched": {"official_only": [], "local_only": []},
        }
    models = snapshot.get("models") or []
    merged = build_model_rows(models, local_usage, snapshot.get("plan_limits"))
    return {
        "ok": True,
        "stale": stale,
        "error": error,
        "fetched_at": snapshot.get("fetched_at"),
        "plan": {
            "slug": snapshot.get("plan_slug"),
            "name": snapshot.get("plan_name"),
            "fallback": bool(snapshot.get("fallback")),
            "limits": snapshot.get("plan_limits") or {},
        },
        "sources": snapshot.get("sources") or {},
        "models": merged["rows"],
        "unmatched": {
            "official_only": merged["official_only"],
            "local_only": merged["local_only"],
        },
    }
