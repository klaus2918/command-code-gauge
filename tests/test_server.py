# -*- coding: utf-8 -*-
"""server 单元测试：范围解析、窗口视图、计划信息、同步规划。"""
import time
from datetime import datetime, timezone

import pytest

from app.cc_api import UsageRecord, decode_cursor
from app.server import (
    AppContext,
    _window_view,
    local_tz_offset_sec,
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
