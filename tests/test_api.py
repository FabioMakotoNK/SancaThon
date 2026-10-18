from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from ciclorota.api import create_app
from ciclorota.geocoding import GeocodedAddress
from ciclorota.config import Settings
from ciclorota.service import local_today, next_collection_date


def make_client(path, geocoder=None):
    settings = Settings(
        database_path=path, fixed_collection_weekdays=(0, 3),
        stale_after_seconds=3600, offline_after_seconds=86400,
        default_fill_threshold_percent=75, osrm_base_url="",
        average_speed_kmh=30, fallback_road_factor=1.25,
        google_maps_browser_key="browser-restricted-key",
        google_geocoding_api_key="server-only-secret",
        google_maps_map_id="test-map-id",
    )
    return TestClient(create_app(settings, geocoder=geocoder))


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


def test_google_maps_settings_load_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOROTA_DB_PATH", str(tmp_path / "env.sqlite3"))
    monkeypatch.setenv("CICLOROTA_GOOGLE_MAPS_BROWSER_KEY", "browser-key")
    monkeypatch.setenv("CICLOROTA_GOOGLE_GEOCODING_API_KEY", "server-key")
    monkeypatch.setenv("CICLOROTA_GOOGLE_MAP_ID", "production-map-id")
    settings = Settings.from_env()
    assert settings.google_maps_browser_key == "browser-key"
    assert settings.google_geocoding_api_key == "server-key"
    assert settings.google_maps_map_id == "production-map-id"


def test_unplanned_route_and_favicon_are_available_without_404(tmp_path):
    client = make_client(tmp_path / "empty.sqlite3")
    latest = client.get("/api/routes/latest")
    assert latest.status_code == 200
    assert latest.json() is None
    icon_redirect = client.get("/favicon.ico", follow_redirects=False)
    assert icon_redirect.status_code == 307
    assert icon_redirect.headers["location"] == "/dashboard/favicon.svg"
    icon = client.get("/dashboard/favicon.svg")
    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/svg+xml")


def test_example_google_keys_are_not_sent_to_google(tmp_path):
    settings = Settings(
        database_path=tmp_path / "placeholders.sqlite3",
        google_maps_browser_key="your-referrer-restricted-browser-key",
        google_geocoding_api_key="your-server-only-geocoding-key",
    )
    client = TestClient(create_app(settings))
    config = client.get("/api/config").json()
    assert config["google_maps_browser_key"] == ""
    assert config["google_maps_key_status"] == "placeholder"
    response = client.post("/api/dumpsters", json={
        "id": "D-EXAMPLE", "name": "Example", "address": "Rua Central 1, São Carlos",
        "empty_distance_cm": 150, "full_distance_cm": 25,
    })
    assert response.status_code == 502
    assert response.json()["detail"] == "Google Geocoding API key is not configured"


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
    page = client.get("/").text
    assert "CicloRota" in page
    assert 'name="address"' in page
    assert 'name="image_url"' in page
    assert "Dumpster Photo Gallery" in page
    assert 'id="photo-gallery"' in page
    assert 'id="route-map"' in page
    assert 'id="plan-button"' in page
    assert 'id="metrics"' not in page
    app_js = client.get("/dashboard/app.js").text
    assert 'api("/api/dumpsters")' in app_js
    assert '/api/routes/latest' in app_js
    assert "maps.googleapis.com" in app_js
    assert "AdvancedMarkerElement" in app_js
    assert "window.setInterval(refresh, 15000)" in app_js
    assert client.get("/dashboard/style.css").status_code == 200
    placeholder = client.get("/dashboard/images/photo-placeholder.svg")
    assert placeholder.status_code == 200
    assert placeholder.headers["content-type"].startswith("image/svg+xml")
    config = client.get("/api/config").json()
    # Retain compatibility for API consumers and keep backend secrets private.
    assert config["google_maps_browser_key"] == "browser-restricted-key"
    assert "google_geocoding_api_key" not in config
    assert "server-only-secret" not in str(config)



def test_esp32_http_payload_persists_and_updates_dashboard_data(tmp_path):
    client = make_client(tmp_path / "esp32.sqlite3")
    assert create_dumpster(client, "D1").status_code == 201
    measured_at = datetime.now(timezone.utc).isoformat()
    # Matches the firmware JSON: IDs, raw and filtered centimeters, and UTC time.
    # Fill is omitted so the backend uses the calibration saved for D1.
    payload = {
        "measurement_id": "esp32-D1-00000001",
        "dumpster_id": "D1",
        "device_id": "esp32-D1",
        "raw_distance_cm": 52.0,
        "distance_cm": 50.0,
        "measured_at": measured_at,
    }
    accepted = client.post("/api/measurements", json=payload)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["fill_percentage"] == 80.0

    history = client.get("/api/measurements/D1").json()
    assert len(history) == 1
    assert history[0]["measurement_id"] == payload["measurement_id"]
    assert history[0]["raw_distance_cm"] == 52.0
    assert history[0]["distance_cm"] == 50.0
    assert history[0]["fill_percentage"] == 80.0

    registered = client.get("/api/dumpsters").json()[0]
    assert registered["id"] == "D1"
    latest = registered["latest"]
    assert latest["device_id"] == "esp32-D1"
    assert latest["raw_distance_cm"] == 52.0
    assert latest["distance_cm"] == 50.0
    assert latest["fill_percentage"] == 80.0
    assert datetime.fromisoformat(latest["measured_at"]) == datetime.fromisoformat(measured_at).replace(microsecond=0)
    run_day = next_collection_date(local_today("America/Sao_Paulo"), (0, 3))
    plan = client.post("/api/routes/plan", json={"collection_date": run_day.isoformat()})
    assert plan.status_code == 200, plan.text
    assert [stop["dumpster_id"] for stop in plan.json()["route"]] == ["D1"]
    assert client.get("/dashboard/app.js").status_code == 200


def test_esp32_measurement_rejects_invalid_missing_and_unknown_data(tmp_path):
    client = make_client(tmp_path / "esp32-validation.sqlite3")
    assert create_dumpster(client, "D1").status_code == 201
    payload = {
        "measurement_id": "esp32-D1-invalid-check",
        "dumpster_id": "D1",
        "device_id": "esp32-D1",
        "raw_distance_cm": 52.0,
        "distance_cm": 50.0,
        "measured_at": datetime.now(timezone.utc).isoformat(),
    }
    for bad_distance in (0, 401):
        response = client.post("/api/measurements", json=dict(payload, distance_cm=bad_distance))
        assert response.status_code == 422
    assert client.post("/api/measurements", json=dict(payload, raw_distance_cm=401)).status_code == 422
    assert client.post("/api/measurements", json={"dumpster_id": "D1", "distance_cm": 80}).status_code == 422
    assert client.post("/api/measurements", json=dict(payload, dumpster_id="UNKNOWN")).status_code == 404
    assert client.get("/api/measurements/D1").json() == []


class StubGeocoder:
    def __init__(self):
        self.addresses = []

    def geocode(self, address):
        self.addresses.append(address)
        return GeocodedAddress(-22.0145, -47.8912, "Avenida Brasil, São Carlos, SP")


def test_address_registration_geocodes_and_stores_location(tmp_path):
    geocoder = StubGeocoder()
    client = make_client(tmp_path / "address.sqlite3", geocoder)
    response = client.post("/api/dumpsters", json={
        "id": "D-ADDRESS", "name": "North yard",
        "address": "Avenida Brasil, São Carlos, SP",
        "empty_distance_cm": 150, "full_distance_cm": 25,
    })
    assert response.status_code == 201, response.text
    result = response.json()["dumpster"]
    assert result["latitude"] == -22.0145
    assert result["longitude"] == -47.8912
    assert result["geocoded_label"] == "Avenida Brasil, São Carlos, SP"
    assert geocoder.addresses == ["Avenida Brasil, São Carlos, SP"]
    stored = client.get("/api/dumpsters").json()[0]
    assert stored["address"] == "Avenida Brasil, São Carlos, SP"
    assert stored["latitude"] == -22.0145


def test_address_registration_maps_not_found_and_provider_errors(tmp_path):
    from ciclorota.geocoding import AddressNotFound, GeocodingError

    class MissingGeocoder:
        def geocode(self, address):
            raise AddressNotFound("No map location matched that street address")

    class FailedGeocoder:
        def geocode(self, address):
            raise GeocodingError("Address lookup service is unavailable")

    payload = {"id": "D-X", "name": "X", "address": "Rua das Flores 1, São Carlos",
               "empty_distance_cm": 150, "full_distance_cm": 25}
    not_found = make_client(tmp_path / "missing.sqlite3", MissingGeocoder()).post("/api/dumpsters", json=payload)
    failed = make_client(tmp_path / "failed.sqlite3", FailedGeocoder()).post("/api/dumpsters", json=payload)
    assert not_found.status_code == 422
    assert failed.status_code == 502
    assert make_client(tmp_path / "missing.sqlite3", MissingGeocoder()).get("/api/dumpsters").json() == []
    assert make_client(tmp_path / "failed.sqlite3", FailedGeocoder()).get("/api/dumpsters").json() == []
