"""SQLite persistence for drafts, vehicle types and saved shipment plans."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

DB_PATH = os.environ.get("RO_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "route_optimization.db"))

DRAFT_COLUMNS = [
    "do_number",
    "weight",
    "volume",
    "pickup_location_code",
    "pickup_latitude",
    "pickup_longitude",
    "delivery_location_code",
    "delivery_latitude",
    "delivery_longitude",
    "priority",
    "pickup_open_time",
    "pickup_close_time",
    "delivery_open_time",
    "delivery_close_time",
]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS route_optimization_draft (
    id TEXT PRIMARY KEY,
    import_batch_id TEXT NOT NULL,
    {", ".join(f"{c} {'REAL' if c in ('weight', 'volume') or c.endswith(('latitude', 'longitude')) else 'TEXT'}" for c in DRAFT_COLUMNS)},
    is_multi_pickup INTEGER NOT NULL DEFAULT 0,
    is_proceed INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_draft_mode ON route_optimization_draft (is_multi_pickup, is_deleted, is_proceed);

CREATE TABLE IF NOT EXISTS vehicle_type (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    max_weight REAL NOT NULL DEFAULT 0,
    max_volume REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS shipment_planning (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    import_batch_ids TEXT NOT NULL,
    plan_date TEXT,
    payload TEXT NOT NULL,
    proceeded_draft_ids TEXT NOT NULL
);
"""

SEED_VEHICLE_TYPES = [
    ("Van", 1.5, 8.0),
    ("Light Truck", 4.0, 20.0),
    ("Heavy Truck", 10.0, 45.0),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM vehicle_type").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO vehicle_type (id, name, max_weight, max_volume) VALUES (?, ?, ?, ?)",
                [(str(uuid.uuid4()), n, w, v) for n, w, v in SEED_VEHICLE_TYPES],
            )


# ---------------------------------------------------------------- drafts


def _draft_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["is_multi_pickup"] = bool(d["is_multi_pickup"])
    d["is_proceed"] = bool(d["is_proceed"])
    d.pop("is_deleted", None)
    return d


def save_drafts(rows: list[dict], import_batch_id: str, is_multi_pickup: bool) -> list[dict]:
    created = now_iso()
    out = []
    with connect() as conn:
        for r in rows:
            draft_id = str(uuid.uuid4())
            values = [r.get(c) for c in DRAFT_COLUMNS]
            conn.execute(
                f"INSERT INTO route_optimization_draft (id, import_batch_id, {', '.join(DRAFT_COLUMNS)}, is_multi_pickup, created_at) "
                f"VALUES (?, ?, {', '.join('?' for _ in DRAFT_COLUMNS)}, ?, ?)",
                [draft_id, import_batch_id, *values, int(is_multi_pickup), created],
            )
            out.append(draft_id)
        placeholders = ", ".join("?" for _ in out)
        fetched = conn.execute(
            f"SELECT * FROM route_optimization_draft WHERE id IN ({placeholders}) ORDER BY rowid", out
        ).fetchall() if out else []
    return [_draft_dict(r) for r in fetched]


def search_drafts(is_multi_pickup: bool, include_proceeded: bool) -> list[dict]:
    sql = "SELECT * FROM route_optimization_draft WHERE is_deleted = 0 AND is_multi_pickup = ?"
    if not include_proceeded:
        sql += " AND is_proceed = 0"
    with connect() as conn:
        rows = conn.execute(sql + " ORDER BY created_at DESC, rowid", [int(is_multi_pickup)]).fetchall()
    return [_draft_dict(r) for r in rows]


def delete_drafts(ids: list[str]) -> int:
    if not ids:
        return 0
    with connect() as conn:
        cur = conn.execute(
            f"UPDATE route_optimization_draft SET is_deleted = 1 WHERE is_deleted = 0 AND id IN ({', '.join('?' for _ in ids)})",
            ids,
        )
        return cur.rowcount


def mark_drafts_proceeded(conn: sqlite3.Connection, ids: list[str]) -> int:
    if not ids:
        return 0
    cur = conn.execute(
        f"UPDATE route_optimization_draft SET is_proceed = 1 WHERE is_deleted = 0 AND id IN ({', '.join('?' for _ in ids)})",
        ids,
    )
    return cur.rowcount


# ---------------------------------------------------------------- vehicle types


def list_vehicle_types() -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM vehicle_type ORDER BY max_weight, name").fetchall()]


def get_vehicle_types(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM vehicle_type WHERE id IN ({', '.join('?' for _ in ids)})", ids).fetchall()
    return {r["id"]: dict(r) for r in rows}


def create_vehicle_type(name: str, max_weight: float, max_volume: float) -> dict:
    vt = {"id": str(uuid.uuid4()), "name": name, "max_weight": max_weight, "max_volume": max_volume}
    with connect() as conn:
        conn.execute("INSERT INTO vehicle_type (id, name, max_weight, max_volume) VALUES (:id, :name, :max_weight, :max_volume)", vt)
    return vt


# ---------------------------------------------------------------- shipment planning


def save_shipment_planning(import_batch_ids: list[str], plan_date: str | None, payload: dict, draft_ids: list[str], mark: bool) -> dict:
    record = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "import_batch_ids": import_batch_ids,
        "plan_date": plan_date,
    }
    with connect() as conn:
        proceeded = draft_ids if mark else []
        mark_drafts_proceeded(conn, proceeded)
        conn.execute(
            "INSERT INTO shipment_planning (id, created_at, import_batch_ids, plan_date, payload, proceeded_draft_ids) VALUES (?, ?, ?, ?, ?, ?)",
            [record["id"], record["created_at"], json.dumps(import_batch_ids), plan_date, json.dumps(payload), json.dumps(proceeded)],
        )
    record["route_count"] = len(payload.get("routes", []))
    record["proceeded_draft_ids"] = proceeded
    return record


def list_shipment_plannings() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM shipment_planning ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        payload = json.loads(r["payload"])
        out.append(
            {
                "id": r["id"],
                "created_at": r["created_at"],
                "import_batch_ids": json.loads(r["import_batch_ids"]),
                "plan_date": r["plan_date"],
                "route_count": len(payload.get("routes", [])),
                "proceeded_draft_ids": json.loads(r["proceeded_draft_ids"]),
            }
        )
    return out
