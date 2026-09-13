# -*- coding: utf-8 -*-
"""official 模块与官方数据接口测试（全部离线：解析用夹具，抓取用 monkeypatch）。"""
import json
import os
import time
import urllib.request

import pytest

from app import official
from app.db import Database
from app.server import AppContext, Server

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def plan_page() -> dict:
    return official.parse_plan_page(
        official.flatten_payload(load_fixture("official_plan_goat.html")), "goat"
    )


@pytest.fixture(scope="module")
def pricing() -> dict:
    return official.parse_pricing_limits(
        official.flatten_payload(load_fixture("official_pricing_limits.html"))
    )


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr("app.server.read_cli_api_key", lambda: "")
    db = Database(str(tmp_path / "official.db"))
    context = AppContext(db)
    yield context
    db.close()


class TestFlattenPayload:
    def test_flight_chunks_are_unescaped(self):
        text = official.flatten_payload(load_fixture("official_flight_sample.html"))
        # 原始 HTML 与 flight 分片里的 Content-Type 表都应在展开结果中出现
        assert text.count("Requests / 5 hours") >= 1
        assert "Monthly credits" in text
        assert len(official.parse_tables(text)) == 2

    def test_attribute_containing_gt_does_not_break_cells(self):
        text = official.flatten_payload(load_fixture("official_flight_sample.html"))
        tables = official.parse_tables(text)
        allowance_row = [row for row in tables[1] if row[0].startswith("Tiny")][0]
        # 单元格属性里含 `[&[role=checkbox]>svg]`，正则切标签会截断；状态机解析应拿到完整主信息
        assert allowance_row[0].lead == "Tiny Model"
        assert official.parse_money(allowance_row[5]) == (None, 20.0)
        assert official.parse_rate(allowance_row[1])[0] == 1.0


class TestNameNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("DeepSeek V4.1 Flash", "deepseekv41flash"),
        ("deepseek/deepseek-v4.1-flash", "deepseekv41flash"),
        ("DeepSeek V4 Flash (latest)", "deepseekv4flash"),
        ("deepseek/deepseek-v4-flash", "deepseekv4flash"),
        ("GPT-5.6 Sol", "gpt56sol"),
        ("", ""),
    ])
    def test_normalize(self, raw, expected):
        assert official.normalize_model_key(raw) == expected

    def test_non_model_values_excluded(self):
        assert official.is_model_value("deepseek/deepseek-v4-pro")
        assert not official.is_model_value("web_fetch")
        assert not official.is_model_value("")


class TestValueParsing:
    def test_double_price_returns_was_and_now(self):
        assert official.parse_money("$0.60$0.30") == (0.60, 0.30)

    def test_note_prices_are_ignored(self):
        cell = official._make_cell(["$0.15", "peak $0.30 / $1.20 01-04 UTC"])
        assert cell.lead == "$0.15"
        assert official.parse_money(cell) == (None, 0.15)

    def test_free_and_dash(self):
        assert official.parse_money("Free") == (None, None)
        assert official.parse_money("—") == (None, None)

    def test_counts(self):
        assert official.parse_int("30,800") == 30800
        assert official.parse_int("~75K") == 75000
        assert official.parse_int("1.1M") == 1100000
        assert official.parse_int("—") is None

    def test_context(self):
        assert official.parse_context("1M") == "1M"
        assert official.parse_context("256K") == "256K"
        assert official.parse_context(None) is None


class TestParsePlanPage:
    def test_model_rates_allowance_and_estimates(self, plan_page):
        models = {m["key"]: m for m in plan_page["models"]}
        deepseek = models["deepseekv41flash"]
        assert deepseek["name"] == "DeepSeek V4.1 Flash"
        assert deepseek["context"] == "1M"
        assert deepseek["rates"] == {"input": 0.15, "output": 0.6, "cache_read": 0.003,
                                     "cache_write": None}
        assert deepseek["allowance"] == 60.0
        assert deepseek["requests"] == {"five_hour": 30800, "weekly": 76900, "monthly": 154000}
        assert deepseek["free"] is False

    def test_discounted_model_uses_current_price(self, plan_page):
        minimax = [m for m in plan_page["models"] if m["key"] == "minimaxm3"][0]
        assert minimax["rates"]["input"] == 0.3      # 现价，而非划线原价 0.6
        assert "→" in minimax["rates_raw"]["input"]
        assert minimax["allowance"] == 47.0

    def test_allowance_only_models_are_kept(self, plan_page):
        # 额度表里有、目录表未保留的模型也要出现在结果中（rates 允许为空）
        keys = {m["key"] for m in plan_page["models"]}
        assert "qwen38max0902" in keys


class TestParsePricingLimits:
    def test_plan_windows(self, pricing):
        goat = pricing["plans"]["GOAT"]
        assert goat["monthly_credits"] == 70.0
        assert goat["five_hour"] == 14.0
        assert goat["weekly"] == 35.0
        assert pricing["plans"]["Max 10\u00d7"]["monthly_credits"] == 150.0


class TestModelMatching:
    def test_one_to_one_prefix_matching(self):
        official_keys = ["deepseekv4flash", "deepseekv4flashfast", "deepseekv41flash"]
        local = {"deepseekv4flash": {"requests": 1}}
        mapping = official.match_local_usage(official_keys, local)
        # 精确命中优先，不得把 deepseekv4flash 也匹配到 deepseekv4flashfast
        assert mapping == {"deepseekv4flash": "deepseekv4flash"}

    def test_prefix_fallback_picks_closest(self):
        official_keys = ["deepseekv4flash", "deepseekv4flashfast"]
        local = {"deepseekv4flashlatest": {"requests": 1}}
        mapping = official.match_local_usage(official_keys, local)
        assert mapping == {"deepseekv4flashlatest": "deepseekv4flash"}

    def test_unmatched_local_reported(self):
        rows = official.build_model_rows(
            [{"name": "A", "key": "a", "rates": {}, "allowance": None, "requests": None}],
            {"web_fetch_thing": {"model": "web_fetch_thing", "requests": 1}},
        )
        assert rows["local_only"] == [{"key": "web_fetch_thing", "name": "web_fetch_thing"}]
        assert rows["official_only"] == ["A"]


class TestValueMetrics:
    MODEL = {"name": "DeepSeek V4.1 Flash", "key": "deepseekv41flash",
             "rates": {"input": 0.15, "output": 0.6, "cache_read": 0.003, "cache_write": None},
             "allowance": 60.0, "requests": {"five_hour": 30800, "weekly": 76900,
                                             "monthly": 154000}}

    def test_typical_basis_for_unused_model(self):
        result = official.build_model_rows([dict(self.MODEL)], {})
        row = result["rows"][0]
        assert row["used"] is False
        assert row["basis"] == "typical"
        # 官方典型请求：800 输入 + 200 输出 + 50K 缓存读
        assert row["typical_cost_per_request"] == pytest.approx(0.00039)
        assert row["value"] == pytest.approx(60 / 0.00039, rel=1e-6)
        assert row["vs_estimate_ratio"] == pytest.approx(row["value"] / 154000)

    def test_measured_basis_uses_local_costs(self):
        local = {
            "deepseekv41flash": {
                "model": "deepseek/deepseek-v4.1-flash",
                "requests": 1000, "tokens_in": 250_000_000, "tokens_out": 1_000_000,
                "cost_total": 1.84, "cost_input": 0.375, "cost_output": 0.637,
                "cost_cache": 0.826, "_key": "deepseekv41flash",
            }
        }
        row = official.build_model_rows([dict(self.MODEL)], local)["rows"][0]
        assert row["used"] is True
        assert row["basis"] == "measured"
        assert row["cost_per_request"] == pytest.approx(0.00184)
        assert row["value"] == pytest.approx(60 / 0.00184, rel=1e-6)
        assert row["remaining_requests"] == pytest.approx((60 - 1.84) / 0.00184, rel=1e-6)
        measured = row["measured"]
        assert measured["allowance_used_pct"] == pytest.approx(1.84 / 60 * 100)
        assert measured["cache_read_tokens_est"] == pytest.approx(0.826 / (0.003 / 1e6))
        assert measured["cache_share"] == pytest.approx(0.826 / 1.84)

    def test_zero_requests_do_not_crash(self):
        local = {"a": {"model": "a", "requests": 0, "tokens_in": 0, "tokens_out": 0,
                       "cost_total": 0.0, "cost_input": 0.0, "cost_output": 0.0,
                       "cost_cache": 0.0, "_key": "a"}}
        row = official.build_model_rows(
            [{"name": "A", "key": "a", "rates": {"input": 1.0}, "allowance": 10.0,
              "requests": {}}], local)["rows"][0]
        assert row["cost_per_request"] is None
        assert row["value"] is None
        assert row["remaining_requests"] is None

    def test_free_model_has_no_typical_cost(self):
        row = official.build_model_rows(
            [{"name": "F", "key": "f", "rates": {"input": None, "output": None,
                                                 "cache_read": None}, "allowance": None,
              "requests": None}], {})["rows"][0]
        assert row["typical_cost_per_request"] is None
        assert row["value"] is None


class TestSnapshotResponse:
    def test_missing_snapshot(self):
        payload = official.build_snapshot_response(None, {}, stale=True, error="抓取失败")
        assert payload["ok"] is False
        assert payload["stale"] is True
        assert payload["error"] == "抓取失败"
        assert payload["models"] == []

    def test_snapshot_payload_shape(self):
        snapshot = {
            "plan_slug": "goat", "plan_name": "GOAT", "fallback": False,
            "plan_limits": {"monthly_credits": 70.0, "five_hour": 14.0, "weekly": 35.0},
            "models": [{"name": "DeepSeek V4.1 Flash", "key": "deepseekv41flash",
                        "rates": {"input": 0.15}, "allowance": 60.0,
                        "requests": {"monthly": 154000}, "in_plan": True}],
            "sources": {"plan_page": "u"}, "fetched_at": 1700000000,
        }
        payload = official.build_snapshot_response(snapshot, {})
        assert payload["ok"] is True and payload["stale"] is False
        assert payload["plan"]["slug"] == "goat"
        assert payload["plan"]["limits"]["weekly"] == 35.0
        assert payload["models"][0]["name"] == "DeepSeek V4.1 Flash"
        assert payload["unmatched"]["official_only"] == ["DeepSeek V4.1 Flash"]


class TestDatabaseOfficialSnapshot:
    def test_save_and_latest_roundtrip(self, tmp_path):
        db = Database(str(tmp_path / "snap.db"))
        try:
            assert db.latest_official_snapshot("official") is None
            stamp = db.save_official_snapshot("official", {"plan_slug": "goat", "models": []}, 1700000000)
            assert stamp == 1700000000
            cached = db.latest_official_snapshot("official")
            assert cached["plan_slug"] == "goat"
            assert cached["_fetched_at"] == 1700000000
            db.save_official_snapshot("official", {"plan_slug": "pro", "models": []}, 1700000001)
            assert db.latest_official_snapshot("official")["plan_slug"] == "pro"
        finally:
            db.close()


class TestServerOfficialApi:
    @pytest.fixture()
    def api(self, ctx, monkeypatch):
        calls = {"count": 0}

        def fake_fetch(slug, timeout=30):
            calls["count"] += 1
            return {
                "plan_slug": slug, "plan_name": "GOAT", "fallback": False,
                "plan_limits": {"monthly_credits": 70.0, "five_hour": 14.0, "weekly": 35.0},
                "models": [{"name": "DeepSeek V4.1 Flash", "key": "deepseekv41flash",
                            "context": "1M", "rates": {"input": 0.15, "output": 0.6,
                                                        "cache_read": 0.003},
                            "allowance": 60.0,
                            "requests": {"five_hour": 30800, "weekly": 76900,
                                         "monthly": 154000},
                            "in_plan": True}],
                "sources": {"plan_page": "fixture"}, "fetched_at": int(time.time()),
            }

        monkeypatch.setattr("app.official.fetch_official_snapshot", fake_fetch)
        ctx.db.set_setting("plan_id", "individual-goat")
        server = Server(ctx)
        server.calls = calls
        yield server
        server.stop()

    @staticmethod
    def _request(server, method, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            server.base_url.rstrip("/") + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(request, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_plan_slug_mapping(self, ctx):
        ctx.db.set_setting("plan_id", "individual-goat")
        assert ctx.plan_slug() == "goat"
        ctx.db.set_setting("plan_id", "individual-pro-v1")
        assert ctx.plan_slug() == "pro"
        ctx.db.set_setting("plan_id", "teams-pro")
        assert ctx.plan_slug() is None

    def test_api_returns_plan_and_models(self, api):
        payload = self._request(api, "GET", "/api/official-models")
        assert payload["ok"] is True
        assert payload["plan"]["slug"] == "goat"
        assert payload["plan"]["limits"]["five_hour"] == 14.0
        assert payload["models"][0]["requests"]["monthly"] == 154000
        assert payload["fetched_at"] > 0
        assert api.calls["count"] == 1

    def test_second_call_uses_cache(self, api):
        self._request(api, "GET", "/api/official-models")
        self._request(api, "GET", "/api/official-models")
        assert api.calls["count"] == 1

    def test_force_refresh_bypasses_cache(self, api):
        self._request(api, "GET", "/api/official-models")
        payload = self._request(api, "POST", "/api/official/refresh")
        assert payload["ok"] is True
        assert api.calls["count"] == 2

    def test_failure_degrades_to_cached_snapshot(self, api, monkeypatch):
        first = self._request(api, "GET", "/api/official-models")
        assert first["stale"] is False

        def boom(slug, timeout=30):
            raise official.OfficialDataError("模拟抓取失败")

        monkeypatch.setattr("app.official.fetch_official_snapshot", boom)
        payload = self._request(api, "POST", "/api/official/refresh")
        assert payload["ok"] is True
        assert payload["stale"] is True
        assert "模拟抓取失败" in (payload["error"] or "")
        assert payload["plan"]["slug"] == "goat"

    def test_failure_without_cache(self, api, monkeypatch):
        def boom(slug, timeout=30):
            raise official.OfficialDataError("网络不可用")

        monkeypatch.setattr("app.official.fetch_official_snapshot", boom)
        payload = self._request(api, "GET", "/api/official-models")
        assert payload["ok"] is False
        assert payload["stale"] is True
        assert payload["models"] == []

    def test_local_usage_uses_billing_period_and_skips_non_models(self, api, ctx):
        from tests.test_server import make_record

        ctx.db.upsert_records([
            make_record("r1"), make_record("r2"),
        ])
        ctx.db._conn.execute("UPDATE usage_records SET model = ?", ("deepseek/deepseek-v4.1-flash",))
        ctx.db._conn.execute("UPDATE usage_records SET cost_total = 0.5, cost_cache = 0.2 WHERE id = 'r1'")
        ctx.db._conn.commit()
        ctx.db.upsert_records([make_record("r3")])
        ctx.db._conn.execute("UPDATE usage_records SET model = 'web_fetch' WHERE id = 'r3'")
        ctx.db._conn.commit()

        usage = ctx.official_local_usage()
        assert "deepseekv41flash" in usage
        assert all("web_fetch" not in key for key in usage)

        payload = self._request(api, "POST", "/api/official/refresh")
        row = payload["models"][0]
        assert row["used"] is True
        assert row["measured"]["requests"] == 2
        # r1 覆盖为 $0.5，r2 保持 $0.001 → 每请求 (0.5 + 0.001) / 2
        assert row["cost_per_request"] == pytest.approx(0.2505)
