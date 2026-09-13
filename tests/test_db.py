# -*- coding: utf-8 -*-
"""db 单元测试：UPSERT 幂等、范围过滤、聚合口径、设置脱敏。"""
import os
import time
from datetime import datetime, timezone

import pytest

from app.cc_api import UsageRecord
from app.db import Database

LOCAL_TZ = 8 * 3600


def make_record(record_id, ts_offset_sec=0, model="m1", mode="agent", tokens_in=100, tokens_out=10,
                cost_input=0.01, cost_output=0.02, cost_cache=0.03, duration_ms=1000):
    ts = datetime.fromtimestamp(time.time() + ts_offset_sec, tz=timezone.utc)
    return UsageRecord(
        id=record_id,
        created_at=ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_ms=duration_ms,
        status="completed",
        mode=mode,
        type="api",
        model=model,
        cost_total=cost_input + cost_output + cost_cache,
        cost_input=cost_input,
        cost_output=cost_output,
        cost_cache=cost_cache,
        trace_id="t-" + record_id,
        created_ts=ts,
        raw={"id": record_id},
    )


@pytest.fixture()
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    yield database
    database.close()


class TestUpsert:
    def test_insert_and_idempotent(self, db):
        records = [make_record("a"), make_record("b")]
        assert db.upsert_records(records) == 2
        assert db.upsert_records(records) == 0
        assert db.count_records() == 2

    def test_has_record(self, db):
        db.upsert_records([make_record("a")])
        assert db.has_record("a") is True
        assert db.has_record("missing") is False

    def test_empty_batch(self, db):
        assert db.upsert_records([]) == 0
        assert db.count_records() == 0


class TestOverview:
    def test_totals_and_cache_ratio(self, db):
        db.upsert_records([
            make_record("a", tokens_in=1000, tokens_out=100, cost_input=1.0, cost_output=2.0, cost_cache=3.0),
            make_record("b", tokens_in=500, tokens_out=50, cost_input=0.5, cost_output=1.0, cost_cache=1.5),
        ])
        ov = db.overview()
        assert ov["requests"] == 2
        assert ov["tokens_in"] == 1500
        assert ov["tokens_out"] == 150
        assert ov["total_tokens"] == 1650
        assert ov["cost_total"] == pytest.approx(9.0)
        # 缓存成本占比 = cache / (input + cache) = 4.5 / 6.0
        assert ov["cache_cost_ratio"] == pytest.approx(0.75)

    def test_empty_db(self, db):
        ov = db.overview()
        assert ov["requests"] == 0
        assert ov["cache_cost_ratio"] == 0.0

    def test_range_filter(self, db):
        db.upsert_records([
            make_record("old", ts_offset_sec=-7200),
            make_record("new", ts_offset_sec=-60),
        ])
        recent = db.overview(start_ts=int(time.time()) - 3600)
        assert recent["requests"] == 1


class TestSeries:
    def test_hourly_buckets(self, db):
        now = int(time.time())
        db.upsert_records([make_record("a", tokens_in=100, tokens_out=10)])
        series = db.series_hourly(now - 3600, now + 3600, LOCAL_TZ)
        assert len(series) >= 1
        assert series[-1]["tokens_in"] == 100
        assert series[-1]["total_tokens"] == 110

    def test_daily_buckets(self, db):
        now = int(time.time())
        db.upsert_records([make_record("a"), make_record("b")])
        series = db.series_daily(now - 86400, now + 3600, LOCAL_TZ)
        assert sum(s["requests"] for s in series) == 2


class TestBreakdowns:
    def test_model_and_mode(self, db):
        db.upsert_records([
            make_record("a", model="m1", mode="agent", cost_input=1, cost_output=0, cost_cache=0),
            make_record("b", model="m2", mode="agent", cost_input=0.1, cost_output=0, cost_cache=0),
            make_record("c", model="web_fetch", mode="web-fetch", cost_input=0.001, cost_output=0, cost_cache=0),
        ])
        models = db.model_breakdown(None, None)
        assert models[0]["model"] == "m1"          # 按成本倒序
        assert len(models) == 3
        modes = {m["mode"] for m in db.mode_breakdown(None, None)}
        assert modes == {"agent", "web-fetch"}
        assert db.list_models() == ["m1", "m2", "web_fetch"]

    def test_daily_model_breakdown(self, db):
        db.upsert_records([make_record("a", model="m1"), make_record("b", model="m1")])
        rows = db.daily_model_breakdown(int(time.time()) - 86400, int(time.time()) + 3600, LOCAL_TZ)
        assert len(rows) == 1
        assert rows[0]["requests"] == 2
        assert rows[0]["model"] == "m1"


class TestRecords:
    def test_pagination_and_filter(self, db):
        db.upsert_records([make_record("r%d" % i, ts_offset_sec=-i, model="m%d" % (i % 2)) for i in range(10)])
        page1 = db.query_records(page=1, page_size=4)
        assert page1["total"] == 10
        assert len(page1["items"]) == 4
        page3 = db.query_records(page=3, page_size=4)
        assert len(page3["items"]) == 2

        filtered = db.query_records(page=1, page_size=50, model="m0")
        assert filtered["total"] == 5
        assert all(item["model"] == "m0" for item in filtered["items"])

    def test_page_size_clamped(self, db):
        db.upsert_records([make_record("r%d" % i) for i in range(5)])
        result = db.query_records(page=1, page_size=9999)
        assert result["page_size"] == 200


class TestSettingsAndState:
    def test_settings_masking(self, db):
        db.set_setting("cookie_header", "a" * 100)
        db.set_setting("api_key", "k" * 50)
        db.set_setting("theme", "dark")
        masked = db.all_settings(mask_secrets=True)
        assert "已设置" in masked["cookie_header"]
        assert "已设置" in masked["api_key"]
        assert masked["theme"] == "dark"
        raw = db.all_settings(mask_secrets=False)
        assert raw["cookie_header"] == "a" * 100

    def test_setting_delete(self, db):
        db.set_setting("theme", "dark")
        db.set_setting("theme", None)
        assert db.get_setting("theme") is None

    def test_sync_state(self, db):
        db.set_state("last_sync_at", 123)
        assert db.get_state("last_sync_at") == "123"
        db.set_state("last_sync_at", 456)
        assert db.get_sync_state()["last_sync_at"] == "456"

    def test_quota_snapshot(self, db):
        db.save_quota_snapshot({"credits": {"monthlyCredits": 10}})
        db.save_quota_snapshot({"credits": {"monthlyCredits": 9}})
        latest = db.latest_quota_snapshot()
        assert latest["credits"]["monthlyCredits"] == 9
        assert "_captured_at" in latest
