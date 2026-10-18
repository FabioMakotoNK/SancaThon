"""Camera integration tests never access a physical camera or the live database."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ciclorota import camera
from ciclorota.api import create_app
from ciclorota.config import Settings


@pytest.fixture
def capture_setup(tmp_path, monkeypatch):
    client = TestClient(create_app(Settings(database_path=tmp_path / "camera.sqlite3")))
    for id_ in ("CAM-A", "CAM-B"):
        assert client.post("/api/dumpsters", json={
            "id": id_, "name": id_, "latitude": -22, "longitude": -47,
            "empty_distance_cm": 150, "full_distance_cm": 25,
        }).status_code == 201

    def api(base, path, *, payload=None, method="GET"):
        response = client.request(method, path, json=payload)
        if response.status_code >= 400:
            raise camera.CameraError("API error")
        return response.json()

    monkeypatch.setattr(camera, "api_json", api)

    class Stream:
        released = False
        def isOpened(self):
            return True
        def read(self):
            return True, object()
        def release(self):
            self.released = True

    stream = Stream()
    opens = []
    def open_stream(source):
        opens.append(source)
        return stream
    cv = SimpleNamespace(VideoCapture=open_stream, IMWRITE_JPEG_QUALITY=1,
                         imencode=lambda *args: (True, SimpleNamespace(tobytes=lambda: b"test-jpeg-bytes")))
    monkeypatch.setattr(camera, "load_opencv", lambda: cv)
    return client, stream, cv, opens


def test_capture_links_only_selected_dumpster_and_leaves_sensor_data_untouched(tmp_path, capture_setup):
    client, stream, cv, opens = capture_setup
    assert camera.main(["--dumpster-id", "CAM-A", "--once", "--output-dir", str(tmp_path)]) == 0
    filename = camera.photo_filename("CAM-A")
    assert (tmp_path / filename).read_bytes() == b"test-jpeg-bytes"
    records = {item["id"]: item for item in client.get("/api/dumpsters").json()}
    assert records["CAM-A"]["image_url"] == "/dashboard/images/dumpsters/" + filename
    assert records["CAM-B"]["image_url"] is None
    assert all(item["latest"] is None for item in records.values())
    assert opens == [0]
    assert stream.released
    assert not list(tmp_path.glob(".capture-*.tmp"))


def test_unknown_id_and_list_do_not_open_camera(capture_setup):
    client, stream, cv, opens = capture_setup
    assert camera.main(["--dumpster-id", "UNKNOWN"]) == 1
    assert camera.main(["--list"]) == 0
    assert opens == []


def test_failed_capture_releases_camera_without_linking_photo(tmp_path, capture_setup):
    client, stream, cv, opens = capture_setup
    stream.read = lambda: (False, None)
    assert camera.main(["--dumpster-id", "CAM-A", "--once", "--output-dir", str(tmp_path)]) == 1
    assert stream.released
    assert all(item["image_url"] is None for item in client.get("/api/dumpsters").json())
    assert not list(tmp_path.glob("camera-*.jpg"))


def test_failed_encoding_preserves_previous_photo(tmp_path, capture_setup):
    client, stream, cv, opens = capture_setup
    filename = tmp_path / camera.photo_filename("CAM-A")
    filename.write_bytes(b"previous-photo")
    cv.imencode = lambda *args: (False, None)
    assert camera.main(["--dumpster-id", "CAM-A", "--once", "--output-dir", str(tmp_path)]) == 1
    assert filename.read_bytes() == b"previous-photo"
    assert stream.released


def test_atomic_replace_and_filename_safety(tmp_path):
    path = tmp_path / camera.photo_filename("ID")
    camera.atomic_write_photo(path, b"first")
    camera.atomic_write_photo(path, b"second")
    assert path.read_bytes() == b"second"
    with pytest.raises(camera.CameraError):
        camera.atomic_write_photo(path, b"")
    assert path.read_bytes() == b"second"
    assert not list(tmp_path.glob(".capture-*.tmp"))
    with pytest.raises(camera.CameraError):
        camera.photo_filename("../../private")
    assert camera.photo_filename("Id").lower() != camera.photo_filename("ID").lower()


@pytest.mark.parametrize("interval", ["0", "-1", "nan", "inf"])
def test_invalid_interval_rejected_before_camera_access(interval):
    with pytest.raises(SystemExit) as error:
        camera.main(["--dumpster-id", "CAM-A", "--interval", interval])
    assert error.value.code == 2