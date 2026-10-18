"""Photo associations preserve real measurement and route API behavior."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from ciclorota.api import create_app
from ciclorota.config import Settings
from ciclorota.db import Database


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(Settings(database_path=tmp_path / "photos.sqlite3")))


def register(client, id_, image_url=None):
    return client.post("/api/dumpsters", json={
        "id": id_, "name": "Test " + id_, "latitude": -22.0, "longitude": -47.9,
        "empty_distance_cm": 150, "full_distance_cm": 25, "image_url": image_url,
    })


def test_optional_photos_match_records_and_latest_sensor_values(client):
    assert register(client, "PHOTO-A", "/dashboard/images/dumpsters/a.jpg").status_code == 201
    assert register(client, "PHOTO-B", "https://example.org/b.jpg").status_code == 201
    assert register(client, "NO-PHOTO").status_code == 201
    measured_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).replace(microsecond=0).isoformat()
    payload = {"measurement_id": "test-reading", "dumpster_id": "PHOTO-A", "device_id": "esp32-test",
               "distance_cm": 50, "raw_distance_cm": 52, "measured_at": measured_at}
    assert client.post("/api/measurements", json=payload).status_code == 200
    records = {item["id"]: item for item in client.get("/api/dumpsters").json()}
    assert records["PHOTO-A"]["image_url"] == "/dashboard/images/dumpsters/a.jpg"
    assert records["PHOTO-A"]["latest"]["fill_percentage"] == 80
    assert records["PHOTO-A"]["latest"]["distance_cm"] == 50
    assert records["PHOTO-A"]["latest"]["raw_distance_cm"] == 52
    assert records["PHOTO-A"]["latest"]["measured_at"] == measured_at
    assert records["PHOTO-A"]["status"] == "normal"
    assert records["PHOTO-B"]["image_url"] == "https://example.org/b.jpg"
    assert records["PHOTO-B"]["latest"] is None
    assert records["NO-PHOTO"]["image_url"] is None
    assert records["NO-PHOTO"]["status"] == "no_data"


def test_update_and_clear_photo_without_changing_measurements(client):
    register(client, "EXISTING")
    assert client.patch("/api/dumpsters/EXISTING/photo", json={
        "image_url": "/dashboard/images/dumpsters/existing.webp"
    }).status_code == 200
    assert client.get("/api/dumpsters").json()[0]["image_url"].endswith("existing.webp")
    assert client.patch("/api/dumpsters/EXISTING/photo", json={"image_url": None}).status_code == 200
    assert client.get("/api/dumpsters").json()[0]["image_url"] is None
    assert client.patch("/api/dumpsters/MISSING/photo", json={"image_url": None}).status_code == 404
    assert client.patch("/api/dumpsters/EXISTING/photo", json={}).status_code == 422
    assert client.patch("/api/dumpsters/EXISTING/photo", json={"image_url": None, "name": "changed"}).status_code == 422
    assert client.get("/api/measurements/EXISTING").json() == []


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:image/png;base64,abc", "file:///C:/private.jpg",
    "//example.org/photo.jpg", "/dashboard/images/dumpsters/../private.jpg",
    "/dashboard/images/dumpsters/%2e%2e/private.jpg", "/dashboard/images/dumpsters/a.svg",
    "http://user:password@example.org/a.jpg", "http://example.org:invalid/a.jpg",
    "https://example.org/invalid photo.jpg", "C:\\Users\\private.jpg",
])
def test_reject_invalid_photo_urls_on_create_and_update(client, url):
    assert register(client, "BAD", url).status_code == 422
    register(client, "EXISTING")
    assert client.patch("/api/dumpsters/EXISTING/photo", json={"image_url": url}).status_code == 422


@pytest.mark.parametrize("url", [None, "", "  ", "/dashboard/images/dumpsters/a.JPG",
                                     "/dashboard/images/dumpsters/yard/a.webp", "https://example.org/a.jpg?v=2"])
def test_accept_optional_and_supported_photo_urls(client, url):
    assert register(client, "VALID", url).status_code == 201


def test_old_database_gets_nullable_image_column_without_losing_records(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE dumpsters (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
            empty_distance_cm REAL NOT NULL, full_distance_cm REAL NOT NULL, fill_threshold_percent REAL NOT NULL,
            daily_fill_rate_percent REAL NOT NULL DEFAULT 0, baseline_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, address TEXT, geocoded_label TEXT)""")
        conn.execute("INSERT INTO dumpsters VALUES ('OLD', 'Existing site', 0, 0, 150, 25, 75, 0, 0, ?, NULL, NULL)",
                     (datetime.now(timezone.utc).isoformat(),))
    database = Database(path)
    database.initialize()
    database.initialize()  # Startup migration is idempotent.
    assert database.get_dumpster("OLD")["image_url"] is None
    assert database.get_dumpster("OLD")["name"] == "Existing site"
    assert database.update_dumpster_image("OLD", "/dashboard/images/dumpsters/old.png")
    assert database.get_dumpster("OLD")["image_url"].endswith("old.png")