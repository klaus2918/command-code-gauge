# -*- coding: utf-8 -*-
"""server 单元测试：范围解析、窗口视图、计划信息、同步规划。"""
import json
import time
import urllib.request
from datetime import datetime, timezone

import pytest

from app.cc_api import UsageRecord, decode_cursor
from app.server import (
    AppContext,
    Server,
    _window_view,
    local_tz_offset_sec,
    normalize_number_unit,
    plan_info,
)
from app.db import Database


def make_record(record_id, ts_offset_sec=0):
    ts = datetime.fromtimestamp(time.time() + ts_offset_sec, tz=timezone.utc)
    return UsageRecord(
        id=record_id,
        created_at=ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        tokens_in=10, tokens_out=1, duration_ms=100,
        status="completed", mode="agent", type="api", model="m",
        cost_total=0.001, cost_input=0.0005, cost_output=0.0004, cost_cache=0.0001,
        trace_id="t", created_ts=ts, raw={},
    )


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr("app.server.read_cli_api_key", lambda: "")  # 测试不得触达真实凭据
    db = Database(str(tmp_path / "ctx.db"))
    context = AppContext(db)
    yield context
    db.close()


class TestPlanInfo:
    def test_known_plans(self):
        assert plan_info("individual-goat") == {"plan_id": "individual-goat", "name": "GOAT", "monthly_credits": 70}
        assert plan_info("individual-max")["monthly_credits"] == 150

    def test_unknown_plan_derives_name(self):
        info = plan_info("individual-super")
        assert info["name"] == "Super"
        assert info["monthly_credits"] is None

    def test_empty(self):
        assert plan_info(None) == {"plan_id": None, "name": None, "monthly_credits": None}


class TestWindowView:
    def test_full_window(self):
        view = _window_view({"used": 7, "cap": 14, "exceeded": False, "resetAt": 1789270632270})
        assert view["remaining"] == 7
        assert view["percent"] == pytest.approx(50.0)
        assert view["reset_at"] == 1789270632270

    def test_over_cap_clamped(self):
        view = _window_view({"used": 20, "cap": 10})
        assert view["percent"] == 100
        assert view["remaining"] == 0

    def test_zero_cap(self):
        assert _window_view({"used": 0, "cap": 0})["percent"] == 0

    def test_none(self):
        assert _window_view(None) is None


class TestResolveRange:
    def test_today_starts_at_midnight(self, ctx):
        start, end = ctx.resolve_range("today")
        local = time.localtime(start)
        assert local.tm_hour == 0 and local.tm_min == 0
        assert end > start

    def test_24h(self, ctx):
        start, end = ctx.resolve_range("24h")
        assert end - start == pytest.approx(86401, abs=2)

    def test_days(self, ctx):
        start, end = ctx.resolve_range("7d")
        assert end - start == pytest.approx(7 * 86400 + 1, abs=2)

    def test_all_returns_none(self, ctx):
        assert ctx.resolve_range("all") == (None, None)

    def test_unknown_falls_back_to_24h(self, ctx):
        start, end = ctx.resolve_range("bogus")
        assert end - start == pytest.approx(86401, abs=2)

    def test_billing_without_snapshot(self, ctx):
        assert ctx.resolve_range("billing") == (None, None)

    def test_billing_with_snapshot(self, ctx):
        ctx.db.save_quota_snapshot({
            "subscription": {"data": {"currentPeriodStart": "2026-09-12T22:15:48.000Z"}},
        })
        start, end = ctx.resolve_range("billing")
        assert start is not None and end > start


class TestTimezone:
    def test_offset_nonzero_on_cn_machine(self):
        # 本机为东八区；仅校验返回整数秒且能被 900 整除（15 分钟粒度）
        offset = local_tz_offset_sec()
        assert isinstance(offset, int)
        assert offset % 900 == 0


class TestCredentials:
    def test_has_flags(self, ctx):
        assert ctx.has_cookie() is False
        ctx.db.set_setting("cookie_header", "a=b")
        assert ctx.has_cookie() is True

    def test_reload_credentials(self, ctx):
        ctx.db.set_setting("cookie_header", "x=y")
        ctx.db.set_setting("api_key", "key123")
        ctx.reload_credentials()
        assert ctx.client.cookie_header == "x=y"
        assert ctx.client.api_key == "key123"

    def test_sync_without_cookie_fails(self, ctx):
        result = ctx.run_sync("incremental")
        assert result["ok"] is False
        assert "未登录" in result["error"]


class TestSyncPlanning:
    """同步规划：增量追新 / 历史回填（断点续传）不得重复拉取已有区间。"""

    @staticmethod
    def _patch_iter(ctx, pages):
        captured = {}

        def fake_iter(start_cursor=None, max_pages=None):
            captured["start_cursor"] = start_cursor
            captured["max_pages"] = max_pages
            for page in pages:
                yield page

        ctx.client.iter_usage = fake_iter
        return captured

    def test_should_sync_now_respects_interval(self, ctx):
        ctx.db.set_setting("sync_interval_min", "5")
        ctx.db.set_setting("last_sync_at", str(int(time.time()) - 60))
        assert ctx.should_sync_now() is False            # 1 分钟前刚同步过
        ctx.db.set_setting("last_sync_at", str(int(time.time()) - 600))
        assert ctx.should_sync_now() is True             # 10 分钟前，已超过 5 分钟间隔

    def test_incremental_starts_from_latest(self, ctx):
        ctx.db.set_setting("cookie_header", "a=b")
        ctx.db.upsert_records([make_record("old", -7200), make_record("new", -60)])
        captured = self._patch_iter(ctx, [])
        ctx.run_sync("incremental")
        assert captured["start_cursor"] is None          # 增量从最新开始，不带锚点

    def test_full_backfill_uses_earliest_anchor(self, ctx):
        ctx.db.set_setting("cookie_header", "a=b")
        ctx.db.upsert_records([make_record("old", -7200), make_record("new", -60)])
        captured = self._patch_iter(ctx, [])
        result = ctx.run_sync("full")
        assert result["ok"] is True
        cursor = captured["start_cursor"]
        assert cursor is not None                        # 回填从最早记录续传
        decoded = decode_cursor(cursor)
        assert decoded["id"] == "old"
        assert decoded["seen"] == 0

    def test_full_on_empty_db_starts_from_latest(self, ctx):
        ctx.db.set_setting("cookie_header", "a=b")
        captured = self._patch_iter(ctx, [])
        ctx.run_sync("full")
        assert captured["start_cursor"] is None          # 空库从最新翻到底

    def test_incremental_stops_when_page_fully_known(self, ctx):
        from app.cc_api import UsagePage

        ctx.db.set_setting("cookie_header", "a=b")
        known = make_record("known-1", -120)
        ctx.db.upsert_records([known])
        unknown = make_record("fresh-1", -30)

        pages = [
            UsagePage(records=[unknown], next_cursor="x", limit=100),
            UsagePage(records=[known], next_cursor="y", limit=100),   # 整页已知 → 停止
        ]
        self._patch_iter(ctx, pages)
        result = ctx.run_sync("incremental")
        assert result["ok"] is True
        assert result["inserted"] == 1                    # 仅新增 fresh-1
        assert result["pages"] == 2
        assert "追平" in result["stop_reason"]

    def test_full_stops_when_history_complete(self, ctx):
        from app.cc_api import UsagePage

        ctx.db.set_setting("cookie_header", "a=b")
        ctx.db.upsert_records([make_record("old", -7200)])
        pages = [
            UsagePage(records=[make_record("older", -10800)], next_cursor="z", limit=100),  # 新增更早记录
            UsagePage(records=[make_record("old", -7200)], next_cursor="w", limit=100),     # 已知 → 历史已完整
        ]
        self._patch_iter(ctx, pages)
        result = ctx.run_sync("full")
        assert result["inserted"] == 1
        assert "历史已完整" in result["stop_reason"]


class TestExchangeRate:
    """USD→CNY 汇率：24h 缓存、失败沿用旧值、解析与异常处理。"""

    def test_fetch_rate_parses_response(self, monkeypatch):
        from app import server

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"result": "success", "rates": {"USD": 1, "CNY": 7.1834}}

        monkeypatch.setattr(server.requests, "get", lambda *a, **k: FakeResponse())
        assert server.fetch_usd_cny_rate() == pytest.approx(7.1834)

    def test_fetch_rate_handles_network_error(self, monkeypatch):
        from app import server

        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(server.requests, "get", boom)
        assert server.fetch_usd_cny_rate() is None

    def test_fetch_rate_rejects_non_200(self, monkeypatch):
        from app import server

        class FakeResponse:
            status_code = 502
            text = "bad gateway"

            @staticmethod
            def json():
                return {}

        monkeypatch.setattr(server.requests, "get", lambda *a, **k: FakeResponse())
        assert server.fetch_usd_cny_rate() is None

    def test_refresh_rate_uses_cache_within_24h(self, ctx, monkeypatch):
        ctx.db.set_setting("usd_cny_rate", "7.1234")
        ctx.db.set_setting("usd_cny_rate_at", str(int(time.time())))
        calls = {"n": 0}

        def fake_fetch(*a, **k):
            calls["n"] += 1
            return 8.0

        monkeypatch.setattr("app.server.fetch_usd_cny_rate", fake_fetch)
        result = ctx.refresh_rate()
        assert result["cached"] is True
        assert result["rate"] == pytest.approx(7.1234)
        assert calls["n"] == 0                     # 命中缓存，不发起网络请求

    def test_refresh_rate_fetches_and_persists(self, ctx, monkeypatch):
        monkeypatch.setattr("app.server.fetch_usd_cny_rate", lambda *a, **k: 7.25)
        result = ctx.refresh_rate()
        assert result["ok"] is True
        assert result["rate"] == pytest.approx(7.25)
        assert result["cached"] is False
        assert ctx.db.get_setting("usd_cny_rate") == "7.25"

    def test_refresh_rate_falls_back_to_stale_value(self, ctx, monkeypatch):
        ctx.db.set_setting("usd_cny_rate", "6.9")
        ctx.db.set_setting("usd_cny_rate_at", str(int(time.time()) - 90000))  # 超过 24h
        monkeypatch.setattr("app.server.fetch_usd_cny_rate", lambda *a, **k: None)
        result = ctx.refresh_rate()
        assert result["ok"] is True
        assert result["rate"] == pytest.approx(6.9)
        assert result.get("stale") is True

    def test_refresh_rate_no_cache_and_failure(self, ctx, monkeypatch):
        monkeypatch.setattr("app.server.fetch_usd_cny_rate", lambda *a, **k: None)
        result = ctx.refresh_rate()
        assert result["ok"] is False
        assert result["rate"] is None
        assert "error" in result


class TestNumberUnitSetting:
    """数字单位：校验助手 + 设置接口读写（通过真实 HTTP 服务验证白名单行为）。"""

    @pytest.fixture()
    def api(self, ctx):
        server = Server(ctx)
        yield server
        server.stop()

    @staticmethod
    def _request(server, method, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            server.base_url.rstrip("/") + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(request, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_normalize_accepts_valid_modes(self):
        for mode in ("cn", "en", "plain"):
            assert normalize_number_unit(mode) == mode

    def test_normalize_trims_case_and_whitespace(self):
        assert normalize_number_unit(" CN ") == "cn"
        assert normalize_number_unit("Plain") == "plain"

    def test_normalize_rejects_invalid_and_empty(self):
        for bad in ("", " ", None, "bogus", "zh", 0, [], "cn-us"):
            assert normalize_number_unit(bad) is None

    def test_settings_expose_modes_and_empty_default(self, api):
        data = self._request(api, "GET", "/api/settings")
        assert data["ok"] is True
        # 未显式设置时返回空串，由前端按界面语言派生生效值（不预写默认值）
        assert data["settings"]["number_unit"] == ""
        assert data["options"]["number_unit"] == ["cn", "en", "plain"]

    def test_set_number_unit_persists(self, api, ctx):
        res = self._request(api, "POST", "/api/settings", {"number_unit": "plain"})
        assert res["ok"] is True
        assert "number_unit" in res["updated"]
        assert ctx.db.get_setting("number_unit") == "plain"
        assert self._request(api, "GET", "/api/settings")["settings"]["number_unit"] == "plain"

    def test_set_number_unit_normalizes_input(self, api, ctx):
        self._request(api, "POST", "/api/settings", {"number_unit": " CN "})
        assert ctx.db.get_setting("number_unit") == "cn"

    def test_invalid_number_unit_rejected_without_write(self, api, ctx):
        res = self._request(api, "POST", "/api/settings", {"number_unit": "bogus"})
        assert res["updated"] == []
        assert ctx.db.get_setting("number_unit") is None

    def test_unknown_setting_key_ignored(self, api, ctx):
        res = self._request(api, "POST", "/api/settings", {"bogus_key": "x"})
        assert res["updated"] == []
        assert ctx.db.get_setting("bogus_key") is None
