"""SQLite repository for dumpsters, observations, and generated collection plans."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)

    def initialize(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS dumpsters (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    empty_distance_cm REAL NOT NULL,
                    full_distance_cm REAL NOT NULL,
                    fill_threshold_percent REAL NOT NULL,
                    daily_fill_rate_percent REAL NOT NULL DEFAULT 0,
                    baseline_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    address TEXT,
                    geocoded_label TEXT,
                    image_url TEXT
                );
                CREATE TABLE IF NOT EXISTS measurements (
                    measurement_id TEXT PRIMARY KEY,
                    dumpster_id TEXT NOT NULL REFERENCES dumpsters(id) ON DELETE CASCADE,
                    device_id TEXT,
                    raw_distance_cm REAL,
                    distance_cm REAL NOT NULL,
                    fill_percentage REAL NOT NULL,
                    measured_at TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_measurements_latest
                    ON measurements(dumpster_id, measured_at DESC, received_at DESC);
                CREATE TABLE IF NOT EXISTS route_plans (
                    route_id TEXT PRIMARY KEY,
                    collection_date TEXT NOT NULL,
                    planned_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS geocoding_cache (
                    cache_key TEXT PRIMARY KEY,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    display_name TEXT NOT NULL,
                    cached_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(dumpsters)").fetchall()}
            if "address" not in columns:
                conn.execute("ALTER TABLE dumpsters ADD COLUMN address TEXT")
            if "geocoded_label" not in columns:
                conn.execute("ALTER TABLE dumpsters ADD COLUMN geocoded_label TEXT")
            if "image_url" not in columns:
                conn.execute("ALTER TABLE dumpsters ADD COLUMN image_url TEXT")
            conn.commit()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_dumpster(self, item: dict[str, Any], created_at: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO dumpsters
                   (id, name, latitude, longitude, empty_distance_cm, full_distance_cm,
                    fill_threshold_percent, daily_fill_rate_percent, baseline_order, created_at, address, geocoded_label, image_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["id"], item["name"], item["latitude"], item["longitude"],
                    item["empty_distance_cm"], item["full_distance_cm"],
                    item["fill_threshold_percent"], item["daily_fill_rate_percent"],
                    item["baseline_order"], created_at, item.get("address"), item.get("geocoded_label"), item.get("image_url"),
                ),
            )

    def update_dumpster_image(self, dumpster_id: str, image_url: str | None) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE dumpsters SET image_url = ? WHERE id = ?", (image_url, dumpster_id)
            )
            return cursor.rowcount == 1

    def get_dumpster(self, dumpster_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM dumpsters WHERE id = ?", (dumpster_id,)).fetchone()
            return dict(row) if row else None

    def list_dumpsters(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT d.*,
                       m.measurement_id AS latest_measurement_id,
                       m.device_id AS latest_device_id,
                       m.raw_distance_cm AS latest_raw_distance_cm,
                       m.distance_cm AS latest_distance_cm,
                       m.fill_percentage AS latest_fill_percentage,
                       m.measured_at AS latest_measured_at,
                       m.received_at AS latest_received_at,
                       (SELECT MAX(allm.received_at) FROM measurements allm
                        WHERE allm.dumpster_id = d.id) AS last_seen_at
                FROM dumpsters d
                LEFT JOIN measurements m ON m.measurement_id = (
                    SELECT mm.measurement_id FROM measurements mm
                    WHERE mm.dumpster_id = d.id
                    ORDER BY mm.measured_at DESC, mm.received_at DESC LIMIT 1
                )
                ORDER BY d.baseline_order, d.id
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_geocoding_cache(self, cache_key: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT latitude, longitude, display_name FROM geocoding_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            return dict(row) if row else None

    def store_geocoding_cache(self, cache_key: str, latitude: float, longitude: float, display_name: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO geocoding_cache
                   (cache_key, latitude, longitude, display_name, cached_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (cache_key, latitude, longitude, display_name),
            )

    def insert_measurement(self, item: dict[str, Any]) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO measurements
                   (measurement_id, dumpster_id, device_id, raw_distance_cm, distance_cm,
                    fill_percentage, measured_at, received_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["measurement_id"], item["dumpster_id"], item.get("device_id"),
                    item.get("raw_distance_cm"), item["distance_cm"], item["fill_percentage"],
                    item["measured_at"], item["received_at"],
                ),
            )
            return cursor.rowcount == 1

    def get_measurement(self, measurement_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM measurements WHERE measurement_id = ?", (measurement_id,)
            ).fetchone()
            return dict(row) if row else None

    def measurement_history(self, dumpster_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM measurements WHERE dumpster_id = ?
                   ORDER BY measured_at DESC, received_at DESC LIMIT ?""",
                (dumpster_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def save_route_plan(self, route_id: str, collection_date: str, planned_at: str, payload: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO route_plans(route_id, collection_date, planned_at, payload_json)
                   VALUES (?, ?, ?, ?)""",
                (route_id, collection_date, planned_at, json.dumps(payload, separators=(",", ":"))),
            )

    def latest_route_plan(self) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT payload_json FROM route_plans ORDER BY planned_at DESC LIMIT 1"
            ).fetchone()
            return json.loads(row["payload_json"]) if row else None
