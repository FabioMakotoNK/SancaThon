import json
from urllib.parse import parse_qs, urlparse

import pytest

import ciclorota.geocoding as geocoding
from ciclorota.db import Database
from ciclorota.geocoding import AddressNotFound, GeocodingError, GoogleMapsGeocoder


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.body).encode("utf-8")


def make_database(path):
    database = Database(path)
    database.initialize()
    return database


def google_result(lat=-22.01, lng=-47.89, address="Rua Central, São Carlos"):
    return {
        "status": "OK",
        "results": [{
            "formatted_address": address,
            "place_id": "google-place-id",
            "geometry": {"location": {"lat": lat, "lng": lng}},
        }],
    }


def test_geocoder_uses_google_api_and_persists_case_insensitive_cache(tmp_path, monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response(google_result(address="Rua Central, São Carlos, SP"))

    monkeypatch.setattr(geocoding, "urlopen", fake_urlopen)
    database = make_database(tmp_path / "geo.sqlite3")
    service = GoogleMapsGeocoder(database, "server-secret", timeout_seconds=2.5)
    first = service.geocode("  Rua Central, São Carlos  ")
    restarted_service = GoogleMapsGeocoder(database, "server-secret")
    second = restarted_service.geocode("rua central, são carlos")
    assert first == second
    assert first.latitude == -22.01
    assert first.longitude == -47.89
    assert first.display_name == "Rua Central, São Carlos, SP"
    assert len(requests) == 1
    request, timeout = requests[0]
    query = parse_qs(urlparse(request.full_url).query)
    assert query == {"address": ["Rua Central, São Carlos"], "key": ["server-secret"]}
    assert request.get_header("Accept") == "application/json"
    assert timeout == 2.5


def test_geocoder_maps_zero_results_and_provider_failures(tmp_path, monkeypatch, caplog):
    database = make_database(tmp_path / "geo.sqlite3")
    service = GoogleMapsGeocoder(database, "server-secret")

    monkeypatch.setattr(geocoding, "urlopen", lambda *args, **kwargs: Response({
        "status": "ZERO_RESULTS", "results": []
    }))
    with pytest.raises(AddressNotFound):
        service.geocode("Rua sem resultado, São Carlos")

    monkeypatch.setattr(geocoding, "urlopen", lambda *args, **kwargs: Response({
        "status": "REQUEST_DENIED",
        "error_message": "server-secret Rua privada",
        "results": [],
    }))
    with pytest.raises(GeocodingError) as error:
        service.geocode("Rua privada")
    assert "server-secret" not in str(error.value)
    assert "Rua privada" not in str(error.value)
    assert "server-secret" not in caplog.text


def test_geocoder_requires_key_and_rejects_invalid_location(tmp_path, monkeypatch):
    database = make_database(tmp_path / "geo.sqlite3")
    missing_key = GoogleMapsGeocoder(database, "")
    with pytest.raises(GeocodingError, match="key is not configured"):
        missing_key.geocode("Rua Central, São Carlos")

    monkeypatch.setattr(geocoding, "urlopen", lambda *args, **kwargs: Response(
        google_result(lat=200, lng=0)
    ))
    invalid = GoogleMapsGeocoder(database, "server-secret")
    with pytest.raises(GeocodingError):
        invalid.geocode("Rua inválida, São Carlos")


def test_geocoder_rejects_invalid_endpoint_and_timeout(tmp_path):
    database = make_database(tmp_path / "geo.sqlite3")
    with pytest.raises(ValueError, match="HTTPS"):
        GoogleMapsGeocoder(database, "server-secret", endpoint="http://example.test/geocode")
    with pytest.raises(ValueError, match="timeout"):
        GoogleMapsGeocoder(database, "server-secret", timeout_seconds=0)


def test_existing_database_receives_address_columns_and_cache_table(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE dumpsters (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
        empty_distance_cm REAL NOT NULL, full_distance_cm REAL NOT NULL,
        fill_threshold_percent REAL NOT NULL, daily_fill_rate_percent REAL NOT NULL DEFAULT 0,
        baseline_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""")
    conn.commit()
    conn.close()

    database = Database(path)
    database.initialize()
    with database.connection() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(dumpsters)")}
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"address", "geocoded_label"} <= columns
    assert "geocoding_cache" in tables
