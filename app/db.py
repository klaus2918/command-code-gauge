# -*- coding: utf-8 -*-
"""SQLite 数据层：请求级明细、配额快照、同步状态与设置。

设计要点：
- 明细以服务端记录 ``id`` 为主键 UPSERT（幂等，重复同步不产生脏数据）
- ``created_ts`` 存 epoch 秒，便于范围过滤与分组聚合
- 时间统一存 UTC；日/小时分组按传入的本地时区偏移换算
- WAL 模式 + 线程锁，供 HTTP 服务与 pywebview 多线程访问
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Iterable, Optional

from .cc_api import UsageRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    created_ts    INTEGER NOT NULL,
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    status        TEXT,
    mode          TEXT,
    type          TEXT,
    model         TEXT,
    cost_total    REAL NOT NULL DEFAULT 0,
    cost_input    REAL NOT NULL DEFAULT 0,
    cost_output   REAL NOT NULL DEFAULT 0,
    cost_cache    REAL NOT NULL DEFAULT 0,
    trace_id      TEXT,
    raw_json      TEXT,
    synced_at     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_records_ts    ON usage_records(created_ts DESC);
CREATE INDEX IF NOT EXISTS idx_records_model ON usage_records(model);
CREATE INDEX IF NOT EXISTS idx_records_mode  ON usage_records(mode);

CREATE TABLE IF NOT EXISTS quota_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at  INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quota_captured ON quota_snapshots(captured_at DESC);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

SETTING_KEYS = (
    "cookie_header",       # 网页登录态（Cookie 头原文）
    "api_key",             # Command Code API Key
    "user_name",
    "plan_id",
    "sync_interval_min",   # 自动同步间隔（分钟）
    "sync_range_days",     # 历史范围（天）
    "theme",               # light | dark
    "lang",                # zh | en
    "last_sync_at",
    "last_sync_error",
    "cookie_valid",
)


class Database:
    """SQLite 封装（线程安全）。"""

    def __init__(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- 明细 ---------------------------------------------------------------

    def upsert_records(self, records: Iterable[UsageRecord]) -> int:
        """写入明细（按 id 忽略重复），返回新增条数。"""
        inserted = 0
        now = int(time.time())
        with self._lock:
            before = self._conn.total_changes
            self._conn.executemany(
                """INSERT OR IGNORE INTO usage_records
                   (id, created_at, created_ts, tokens_in, tokens_out, duration_ms,
                    status, mode, type, model, cost_total, cost_input, cost_output,
                    cost_cache, trace_id, raw_json, synced_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        r.id,
                        r.created_at,
                        int(r.created_ts.timestamp()) if r.created_ts else 0,
                        r.tokens_in,
                        r.tokens_out,
                        r.duration_ms,
                        r.status,
                        r.mode,
                        r.type,
                        r.model,
                        r.cost_total,
                        r.cost_input,
                        r.cost_output,
                        r.cost_cache,
                        r.trace_id,
                        json.dumps(r.raw, ensure_ascii=False),
                        now,
                    )
                    for r in records
                ],
            )
            inserted = self._conn.total_changes - before
            self._conn.commit()
        return inserted

    def has_record(self, record_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM usage_records WHERE id = ? LIMIT 1", (record_id,)
            ).fetchone()
        return row is not None

    def count_records(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM usage_records").fetchone()
        return int(row["c"]) if row else 0

    def data_range(self) -> dict:
        """数据范围（最早/最新记录时间与总条数）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT MIN(created_ts) AS min_ts, MAX(created_ts) AS max_ts, COUNT(*) AS c FROM usage_records"
            ).fetchone()
        return {
            "min_ts": row["min_ts"],
            "max_ts": row["max_ts"],
            "total": int(row["c"]) if row else 0,
        }

    def earliest_record(self) -> Optional[dict]:
        """最早一条记录（历史回填的续传锚点）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, created_at FROM usage_records ORDER BY created_ts ASC, id ASC LIMIT 1"
            ).fetchone()
        return {"id": row["id"], "created_at": row["created_at"]} if row else None

    def latest_record_ts(self) -> Optional[int]:
        """最新一条记录的时间戳（用于判断是否需要增量拉取）。"""
        with self._lock:
            row = self._conn.execute("SELECT MAX(created_ts) AS ts FROM usage_records").fetchone()
        return int(row["ts"]) if row and row["ts"] is not None else None

    def query_records(
        self,
        page: int = 1,
        page_size: int = 50,
        model: Optional[str] = None,
        mode: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> dict:
        """请求级明细分页查询（时间倒序）。"""
        where, params = self._range_where(start_ts, end_ts, model=model, mode=mode)
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 200))
        offset = (page - 1) * page_size
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) AS c FROM usage_records {where}", params
            ).fetchone()["c"]
            rows = self._conn.execute(
                f"""SELECT * FROM usage_records {where}
                    ORDER BY created_ts DESC, id DESC LIMIT ? OFFSET ?""",
                [*params, page_size, offset],
            ).fetchall()
        return {
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "items": [self._row_to_record(r) for r in rows],
        }

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "created_ts": row["created_ts"],
            "tokens_in": row["tokens_in"],
            "tokens_out": row["tokens_out"],
            "total_tokens": row["tokens_in"] + row["tokens_out"],
            "duration_ms": row["duration_ms"],
            "status": row["status"],
            "mode": row["mode"],
            "type": row["type"],
            "model": row["model"],
            "cost_total": row["cost_total"],
            "cost_input": row["cost_input"],
            "cost_output": row["cost_output"],
            "cost_cache": row["cost_cache"],
            "trace_id": row["trace_id"],
        }

    @staticmethod
    def _range_where(
        start_ts: Optional[int],
        end_ts: Optional[int],
        model: Optional[str] = None,
        mode: Optional[str] = None,
    ):
        clauses = []
        params: list = []
        if start_ts is not None:
            clauses.append("created_ts >= ?")
            params.append(int(start_ts))
        if end_ts is not None:
            clauses.append("created_ts < ?")
            params.append(int(end_ts))
        if model:
            clauses.append("model = ?")
            params.append(model)
        if mode:
            clauses.append("mode = ?")
            params.append(mode)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    # -- 聚合 ---------------------------------------------------------------

    def overview(self, start_ts: Optional[int] = None, end_ts: Optional[int] = None) -> dict:
        """用量概览（当前范围）。"""
        where, params = self._range_where(start_ts, end_ts)
        with self._lock:
            row = self._conn.execute(
                f"""SELECT COUNT(*)                          AS requests,
                           COALESCE(SUM(tokens_in), 0)        AS tokens_in,
                           COALESCE(SUM(tokens_out), 0)       AS tokens_out,
                           COALESCE(SUM(cost_total), 0)       AS cost_total,
                           COALESCE(SUM(cost_input), 0)       AS cost_input,
                           COALESCE(SUM(cost_output), 0)      AS cost_output,
                           COALESCE(SUM(cost_cache), 0)       AS cost_cache,
                           COALESCE(AVG(duration_ms), 0)      AS avg_duration_ms,
                           COUNT(DISTINCT model)              AS model_count
                    FROM usage_records {where}""",
                params,
            ).fetchone()
        tokens_in = int(row["tokens_in"])
        tokens_out = int(row["tokens_out"])
        cost_input = float(row["cost_input"])
        cost_cache = float(row["cost_cache"])
        cache_base = cost_input + cost_cache
        return {
            "requests": int(row["requests"]),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "total_tokens": tokens_in + tokens_out,
            "cost_total": float(row["cost_total"]),
            "cost_input": cost_input,
            "cost_output": float(row["cost_output"]),
            "cost_cache": cost_cache,
            "cache_cost_ratio": (cost_cache / cache_base) if cache_base > 0 else 0.0,
            "avg_duration_ms": float(row["avg_duration_ms"]),
            "model_count": int(row["model_count"]),
        }

    def series_hourly(
        self, start_ts: int, end_ts: int, tz_offset_sec: int = 0
    ) -> list[dict]:
        """按小时聚合（用于 24 小时趋势）。"""
        return self._series("hour", start_ts, end_ts, tz_offset_sec)

    def series_daily(
        self, start_ts: int, end_ts: int, tz_offset_sec: int = 0
    ) -> list[dict]:
        """按日聚合（用于多日趋势 / 按日视图）。"""
        return self._series("day", start_ts, end_ts, tz_offset_sec)

    def _series(self, kind: str, start_ts: int, end_ts: int, tz_offset_sec: int) -> list[dict]:
        fmt = "%Y-%m-%dT%H:00" if kind == "hour" else "%Y-%m-%d"
        where, params = self._range_where(start_ts, end_ts)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT strftime('{fmt}', created_ts + ?, 'unixepoch') AS bucket,
                           COUNT(*)                       AS requests,
                           COALESCE(SUM(tokens_in), 0)    AS tokens_in,
                           COALESCE(SUM(tokens_out), 0)   AS tokens_out,
                           COALESCE(SUM(cost_total), 0)   AS cost_total
                    FROM usage_records {where}
                    GROUP BY bucket ORDER BY bucket ASC""",
                [int(tz_offset_sec), *params],
            ).fetchall()
        return [
            {
                "bucket": r["bucket"],
                "requests": int(r["requests"]),
                "tokens_in": int(r["tokens_in"]),
                "tokens_out": int(r["tokens_out"]),
                "total_tokens": int(r["tokens_in"]) + int(r["tokens_out"]),
                "cost_total": float(r["cost_total"]),
            }
            for r in rows
        ]

    def model_breakdown(self, start_ts: Optional[int], end_ts: Optional[int]) -> list[dict]:
        """按模型聚合（用量统计 / 排行）。"""
        where, params = self._range_where(start_ts, end_ts)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT model,
                           COUNT(*)                       AS requests,
                           COALESCE(SUM(tokens_in), 0)    AS tokens_in,
                           COALESCE(SUM(tokens_out), 0)   AS tokens_out,
                           COALESCE(SUM(cost_total), 0)   AS cost_total
                    FROM usage_records {where}
                    GROUP BY model ORDER BY cost_total DESC""",
                params,
            ).fetchall()
        result = []
        for r in rows:
            result.append({
                "model": r["model"] or "(unknown)",
                "requests": int(r["requests"]),
                "tokens_in": int(r["tokens_in"]),
                "tokens_out": int(r["tokens_out"]),
                "total_tokens": int(r["tokens_in"]) + int(r["tokens_out"]),
                "cost_total": float(r["cost_total"]),
            })
        return result

    def mode_breakdown(self, start_ts: Optional[int], end_ts: Optional[int]) -> list[dict]:
        """按调用类型聚合（agent / title-gen / web-fetch 等）。"""
        where, params = self._range_where(start_ts, end_ts)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT mode,
                           COUNT(*)                       AS requests,
                           COALESCE(SUM(tokens_in), 0)    AS tokens_in,
                           COALESCE(SUM(tokens_out), 0)   AS tokens_out,
                           COALESCE(SUM(cost_total), 0)   AS cost_total
                    FROM usage_records {where}
                    GROUP BY mode ORDER BY requests DESC""",
                params,
            ).fetchall()
        return [
            {
                "mode": r["mode"] or "(unknown)",
                "requests": int(r["requests"]),
                "tokens_in": int(r["tokens_in"]),
                "tokens_out": int(r["tokens_out"]),
                "cost_total": float(r["cost_total"]),
            }
            for r in rows
        ]

    def daily_model_breakdown(
        self, start_ts: int, end_ts: int, tz_offset_sec: int = 0
    ) -> list[dict]:
        """按「日期 × 模型」聚合（会话历史降级视图，见 plan 附录 C4）。"""
        where, params = self._range_where(start_ts, end_ts)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT strftime('%Y-%m-%d', created_ts + ?, 'unixepoch') AS day,
                           model,
                           COUNT(*)                       AS requests,
                           COALESCE(SUM(tokens_in), 0)    AS tokens_in,
                           COALESCE(SUM(tokens_out), 0)   AS tokens_out,
                           COALESCE(SUM(cost_total), 0)   AS cost_total,
                           COALESCE(AVG(duration_ms), 0)  AS avg_duration_ms
                    FROM usage_records {where}
                    GROUP BY day, model ORDER BY day DESC, cost_total DESC""",
                [int(tz_offset_sec), *params],
            ).fetchall()
        return [
            {
                "day": r["day"],
                "model": r["model"] or "(unknown)",
                "requests": int(r["requests"]),
                "tokens_in": int(r["tokens_in"]),
                "tokens_out": int(r["tokens_out"]),
                "total_tokens": int(r["tokens_in"]) + int(r["tokens_out"]),
                "cost_total": float(r["cost_total"]),
                "avg_duration_ms": float(r["avg_duration_ms"]),
            }
            for r in rows
        ]

    def list_models(self) -> list[str]:
        """已入库的模型清单（用于筛选下拉）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT model FROM usage_records WHERE model IS NOT NULL AND model != '' ORDER BY model"
            ).fetchall()
        return [r["model"] for r in rows]

    # -- 配额快照 -----------------------------------------------------------

    def save_quota_snapshot(self, payload: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO quota_snapshots (captured_at, payload_json) VALUES (?, ?)",
                (int(time.time()), json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()

    def latest_quota_snapshot(self) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json, captured_at FROM quota_snapshots "
                "ORDER BY captured_at DESC, id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except ValueError:
            return None
        payload["_captured_at"] = row["captured_at"]
        return payload

    # -- 同步状态 -----------------------------------------------------------

    def get_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO sync_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
            self._conn.commit()

    def get_sync_state(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM sync_state").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # -- 设置 ---------------------------------------------------------------

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: Optional[str]) -> None:
        with self._lock:
            if value is None:
                self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                self._conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, str(value)),
                )
            self._conn.commit()

    def all_settings(self, mask_secrets: bool = True) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        result = {}
        for r in rows:
            key, value = r["key"], r["value"]
            if mask_secrets and key in ("cookie_header", "api_key") and value:
                result[key] = f"<已设置: {len(value)} 字符>"
            else:
                result[key] = value
        return result
