# -*- coding: utf-8 -*-
"""cc_api 单元测试：cursor 编解码、字段映射、分页解析、错误处理。"""
import base64
import json
from datetime import timezone
from unittest.mock import MagicMock

import pytest

from app.cc_api import (
    AuthError,
    CommandCodeAPIError,
    CommandCodeClient,
    UsagePage,
    UsageRecord,
    decode_cursor,
    encode_cursor,
    parse_iso_utc,
)

SAMPLE_ITEM = {
    "id": "985cf514-cdbe-411b-89d7-d8d247b63e0a",
    "createdAt": "2026-09-13T00:31:39.997Z",
    "tokensIn": "182828",
    "tokensOut": "1236",
    "durationTotal": "6128",
    "status": "completed",
    "message": None,
    "meta": {
        "totalCost": 0.001353,
        "inputCost": 6.42e-05,
        "outputCost": 0.0007416,
        "cacheCost": 0.0005472,
        "model": "deepseek/deepseek-v4.1-flash",
        "traceId": "8cb0e20821277bcf84016a535193c9e9",
    },
    "type": "api",
    "mode": "agent",
}


class TestCursor:
    def test_encode_decode_roundtrip(self):
        raw = encode_cursor("2026-09-13T00:31:39.997Z", "abc-123", "2026-09-12T00:00:00Z", 7)
        assert "=" not in raw  # 无填充
        decoded = decode_cursor(raw)
        assert decoded == {
            "createdAt": "2026-09-13T00:31:39.997Z",
            "id": "abc-123",
            "since": "2026-09-12T00:00:00Z",
            "seen": 7,
        }

    def test_decode_invalid_returns_empty(self):
        assert decode_cursor("not-base64!!!") == {}
        assert decode_cursor("") == {}

    def test_decode_accepts_padded(self):
        payload = {"createdAt": "x", "id": "y", "since": "z", "seen": 1}
        padded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        assert decode_cursor(padded) == payload


class TestParseIso:
    def test_utc_z_suffix(self):
        dt = parse_iso_utc("2026-09-13T00:31:39.997Z")
        assert dt is not None and dt.tzinfo is not None
        assert dt.astimezone(timezone.utc).year == 2026

    def test_invalid(self):
        assert parse_iso_utc("") is None
        assert parse_iso_utc("garbage") is None


class TestUsageRecord:
    def test_from_api_normalizes_types(self):
        record = UsageRecord.from_api(SAMPLE_ITEM)
        assert isinstance(record.tokens_in, int) and record.tokens_in == 182828
        assert record.tokens_out == 1236
        assert record.duration_ms == 6128
        assert record.model == "deepseek/deepseek-v4.1-flash"
        assert record.cost_total == pytest.approx(0.001353)
        assert record.total_tokens == 182828 + 1236
        assert record.created_ts is not None

    def test_from_api_missing_fields(self):
        record = UsageRecord.from_api({"id": "x"})
        assert record.tokens_in == 0 and record.tokens_out == 0
        assert record.model == ""
        assert record.cost_total == 0.0
        assert record.created_ts is None

    def test_from_api_bad_numeric_strings(self):
        item = dict(SAMPLE_ITEM, tokensIn="NaN?", tokensOut=None)
        record = UsageRecord.from_api(item)
        assert record.tokens_in == 0
        assert record.tokens_out == 0


class TestUsagePage:
    def test_earliest_picks_min_created_at(self):
        items = [
            dict(SAMPLE_ITEM, id="b", createdAt="2026-09-13T00:31:39.997Z"),
            dict(SAMPLE_ITEM, id="a", createdAt="2026-09-12T23:00:00.000Z"),
            dict(SAMPLE_ITEM, id="c", createdAt="2026-09-13T01:00:00.000Z"),
        ]
        page = UsagePage(records=[UsageRecord.from_api(i) for i in items], next_cursor=None, limit=3)
        assert page.earliest.id == "a"

    def test_earliest_empty(self):
        assert UsagePage(records=[], next_cursor=None, limit=3).earliest is None


class TestClientParsing:
    def _client_with_response(self, payload, status=200):
        client = CommandCodeClient(cookie_header="a=b", api_key="k")
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = payload
        resp.text = json.dumps(payload)
        client.session.get = MagicMock(return_value=resp)
        return client

    def test_fetch_usage_page(self):
        payload = {
            "usages": [SAMPLE_ITEM],
            "nextCursor": "abc",
            "limit": 1,
            "window": {"days": 1, "entries": 100},
            "periodBasis": "plan-window",
        }
        client = self._client_with_response(payload)
        page = client.fetch_usage_page(limit=1)
        assert len(page.records) == 1
        assert page.next_cursor == "abc"
        assert page.window == {"days": 1, "entries": 100}
        assert page.period_basis == "plan-window"

    def test_limit_clamped_to_100(self):
        client = self._client_with_response({"usages": []})
        client.fetch_usage_page(limit=500)
        _, kwargs = client.session.get.call_args
        assert kwargs["params"]["limit"] == 100

    def test_auth_error_on_401(self):
        client = self._client_with_response({"error": "unauthorized"}, status=401)
        with pytest.raises(AuthError):
            client.fetch_usage_page(limit=1)

    def test_api_error_on_400(self):
        client = self._client_with_response({"error": "bad"}, status=400)
        with pytest.raises(CommandCodeAPIError):
            client.fetch_usage_page(limit=1)

    def test_iter_usage_advances_anchor(self):
        page1 = {
            "usages": [
                dict(SAMPLE_ITEM, id="r1", createdAt="2026-09-13T02:00:00.000Z"),
                dict(SAMPLE_ITEM, id="r2", createdAt="2026-09-13T01:00:00.000Z"),
            ],
            "nextCursor": None,
        }
        page2 = {"usages": [], "nextCursor": None}
        client = CommandCodeClient(cookie_header="a=b", api_key="k")
        client.session.get = MagicMock(side_effect=[
            self._mock_resp(page1),
            self._mock_resp(page2),
        ])
        pages = list(client.iter_usage(max_pages=5))
        assert len(pages) == 1
        assert len(pages[0].records) == 2
        # 第二次请求应带锚点 cursor（指向本批最早的 r2）
        second_params = client.session.get.call_args_list[1][1]["params"]
        assert "cursor" in second_params
        decoded = decode_cursor(second_params["cursor"])
        assert decoded["id"] == "r2"
        assert decoded["createdAt"] == "2026-09-13T01:00:00.000Z"

    def test_iter_usage_stop_when(self):
        payload = {"usages": [dict(SAMPLE_ITEM, id="known")], "nextCursor": "x"}
        client = CommandCodeClient(cookie_header="a=b", api_key="k")
        client.session.get = MagicMock(return_value=self._mock_resp(payload))
        pages = list(client.iter_usage(stop_when=lambda r: r.id == "known"))
        assert len(pages) == 1

    def test_validate_cookie_false_on_error(self):
        client = self._client_with_response({"error": "x"}, status=401)
        assert client.validate_cookie() is False

    @staticmethod
    def _mock_resp(payload, status=200):
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = payload
        resp.text = json.dumps(payload)
        return resp


class TestQuotaBundle:
    def test_fetch_quota_bundle_chains_org_id(self):
        client = CommandCodeClient(api_key="k")
        responses = {
            "/alpha/whoami": {"user": {"userName": "u"}, "org": {"id": "org_1"}},
            "/alpha/billing/credits": {"credits": {}},
            "/alpha/billing/subscriptions": {"data": {"currentPeriodStart": "2026-09-12T00:00:00.000Z"}},
            "/alpha/usage/summary": {"totalCount": 1},
        }

        def fake_get(url, params=None, headers=None, timeout=None):
            for path, payload in responses.items():
                if url.endswith(path):
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = payload
                    return resp
            raise AssertionError(f"unexpected url {url}")

        client.session.get = fake_get
        bundle = client.fetch_quota_bundle()
        assert bundle["org_id"] == "org_1"
        assert bundle["summary"]["totalCount"] == 1
        assert bundle["subscription"]["data"]["currentPeriodStart"] == "2026-09-12T00:00:00.000Z"
