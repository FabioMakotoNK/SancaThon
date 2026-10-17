from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from ciclorota.api import create_app
from ciclorota.config import Settings
from ciclorota.service import local_today, next_collection_date


def make_client(path):
    settings = Settings(
        database_path=path, fixed_collection_weekdays=(0, 3),
        stale_after_seconds=3600, offline_after_seconds=86400,
        default_fill_threshold_percent=75, osrm_base_url="",
        average_speed_kmh=30, fallback_road_factor=1.25,
    )
    return TestClient(create_app(settings))


def create_dumpster(client, id_, order=0, threshold=75, rate=0):
    return client.post("/api/dumpsters", json={
        "id": id_, "name": "Site " + id_, "latitude": -22.0 - order * 0.005,
        "longitude": -47.9 + order * 0.005, "empty_distance_cm": 150,
        "full_distance_cm": 25, "fill_threshold_percent": threshold,
        "daily_fill_rate_percent": rate, "baseline_order": order,
    })


def post_fill(client, id_, measurement_id, fill, measured_at=None):
    distance = 150 - fill / 100 * 125
    return client.post("/api/measurements", json={
        "measurement_id": measurement_id, "dumpster_id": id_,
        "device_id": "device-" + id_, "distance_cm": distance,
        "raw_distance_cm": distance + 0.3, "fill_percentage": fill,
        "measured_at": (measured_at or datetime.now(timezone.utc)).isoformat(),
    })


def test_health_and_register_validation(tmp_path):
    client = make_client(tmp_path / "api.sqlite3")
    assert client.get("/api/health").json()["status"] == "ok"
    assert create_dumpster(client, "D1").status_code == 201
    assert create_dumpster(client, "D1").status_code == 409
    invalid = client.post("/api/dumpsters", json={
        "id": "D2", "name": "bad calibration", "latitude": 200, "longitude": 0,
        "empty_distance_cm": 25, "full_distance_cm": 150,
    })
    assert invalid.status_code == 422


def test_measurement_calibration_duplicate_and_out_of_order_latest(tmp_path):
    client = make_client(tmp_path / "api.sqlite3")
    assert create_dumpster(client, "D1").status_code == 201
    now = datetime.now(timezone.utc)
    newest, older = now - timedelta(minutes=1), now - timedelta(minutes=2)
    first = post_fill(client, "D1", "newest", 80, newest)
    assert first.status_code == 200
    duplicate = post_fill(client, "D1", "newest", 80, newest)
    assert duplicate.json()["status"] == "duplicate"
    assert post_fill(client, "D1", "older", 20, older).status_code == 200
    rows = client.get("/api/dumpsters").json()
    assert rows[0]["latest"]["measurement_id"] == "newest"
    assert rows[0]["latest"]["fill_percentage"] == 80

    mismatch = client.post("/api/measurements", json={
        "dumpster_id": "D1", "distance_cm": 100, "fill_percentage": 95,
        "measured_at": now.isoformat(),
    })
    assert mismatch.status_code == 422
    no_timezone = client.post("/api/measurements", json={
        "dumpster_id": "D1", "distance_cm": 100, "measured_at": "2026-10-17T10:00:00",
    })
    assert no_timezone.status_code == 422


def test_fixed_schedule_stop_selection_and_persisted_route(tmp_path):
    client = make_client(tmp_path / "api.sqlite3")
    create_dumpster(client, "D1", order=1, threshold=70)
    create_dumpster(client, "D2", order=2, threshold=70)
    post_fill(client, "D1", "m1", 90)
    post_fill(client, "D2", "m2", 30)
    run_day = next_collection_date(local_today("America/Sao_Paulo"), (0, 3))
    response = client.post("/api/routes/plan", json={
        "collection_date": run_day.isoformat(), "depot_latitude": -22.017, "depot_longitude": -47.895,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schedule_changed"] is False
    assert result["collection_date"] == run_day.isoformat()
    assert [stop["dumpster_id"] for stop in result["route"]] == ["D1"]
    assert result["optimized"]["stop_count"] == 1
    assert result["baseline"]["stop_count"] == 2
    assert result["provider"] == "haversine_road_approximation"
    assert client.get("/api/routes/latest").json()["route_id"] == result["route_id"]


def test_schedule_rejects_non_fixed_weekday_and_stale_measurement(tmp_path):
    client = make_client(tmp_path / "api.sqlite3")
    create_dumpster(client, "D1")
    post_fill(client, "D1", "old", 98, datetime.now(timezone.utc) - timedelta(hours=3))
    invalid_day = local_today("America/Sao_Paulo") + timedelta(days=1)
    if invalid_day.weekday() in (0, 3):
        invalid_day += timedelta(days=1)
    rejected = client.post("/api/routes/plan", json={"collection_date": invalid_day.isoformat()})
    assert rejected.status_code == 422
    run_day = next_collection_date(local_today("America/Sao_Paulo"), (0, 3))
    planned = client.post("/api/routes/plan", json={"collection_date": run_day.isoformat()}).json()
    assert planned["route"] == []
    assert planned["decisions"][0]["selected"] is False
    assert "stale" in planned["decisions"][0]["reason"]
    assert client.get("/api/measurements/D1").status_code == 200


def test_projection_prevents_overflow_before_fixed_run(tmp_path):
    client = make_client(tmp_path / "api.sqlite3")
    create_dumpster(client, "D1", threshold=95, rate=50)
    post_fill(client, "D1", "projected", 20)
    run_day = next_collection_date(local_today("America/Sao_Paulo"), (0, 3))
    plan = client.post("/api/routes/plan", json={"collection_date": run_day.isoformat()}).json()
    assert plan["route"][0]["dumpster_id"] == "D1"
    assert "projected overflow" in plan["decisions"][0]["reason"]


def test_dashboard_and_static_assets_are_served(tmp_path):
    client = make_client(tmp_path / "api.sqlite3")
    assert client.get("/").status_code == 200
    assert "CicloRota" in client.get("/").text
    assert client.get("/dashboard/app.js").status_code == 200
