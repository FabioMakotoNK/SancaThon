"""Optional browser checks: pip install playwright; playwright install chromium.

Runs against temporary SQLite records, never the running deployment database.
Uses the installed Edge browser on Windows, or Playwright Chromium elsewhere.
The tiny colored PNGs are test fixtures, not dumpster photographs.
"""
import os
from pathlib import Path
import socket
import struct
import threading
import time
import zlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
import uvicorn

from ciclorota.api import create_app
from ciclorota.config import Settings

playwright_api = pytest.importorskip("playwright.sync_api", reason="Install playwright for browser checks")


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        options = {"headless": True}
        edge = Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe"
        if os.name == "nt" and edge.is_file():
            options["channel"] = "msedge"
        try:
            instance = p.chromium.launch(**options)
        except playwright_api.Error as error:
            pytest.skip(f"Browser not installed: {error}")
        yield instance
        instance.close()


def pixel_png(rgb):
    def chunk(kind, data):
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0" + bytes(rgb))) + chunk(b"IEND", b""))


@pytest.fixture
def live_dashboard(tmp_path, request):
    app = create_app(Settings(database_path=tmp_path / "browser.sqlite3"))
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "fixture-a.png").write_bytes(pixel_png((35, 115, 80)))
    (photos / "fixture-b.png").write_bytes(pixel_png((70, 100, 160)))
    # Exercise the same static URL prefix using isolated image files.
    app.router.routes.insert(0, Mount("/dashboard/images/dumpsters", StaticFiles(directory=photos)))
    api = TestClient(app)
    if getattr(request, "param", True):
        stamp = (datetime.now(timezone.utc) - timedelta(seconds=2)).replace(microsecond=0)
        records = [("A", "fixture-a.png", 80, stamp), ("B", "fixture-b.png", 0, stamp),
                   ("BROKEN", "missing.jpg", 50, stamp - timedelta(days=2)), ("EMPTY", None, None, None)]
        for id_, photo, fill, measured_at in records:
            response = api.post("/api/dumpsters", json={
                "id": id_, "name": "Test <yard> & " + id_, "latitude": -22, "longitude": -47,
                "empty_distance_cm": 150, "full_distance_cm": 25,
                "image_url": "/dashboard/images/dumpsters/" + photo if photo else None,
            })
            assert response.status_code == 201
            if fill is not None:
                response = api.post("/api/measurements", json={
                    "measurement_id": "fixture-" + id_, "dumpster_id": id_, "device_id": "test-device",
                    "distance_cm": 150 - fill / 100 * 125, "raw_distance_cm": 150 - fill / 100 * 125,
                    "measured_at": measured_at.isoformat(),
                })
                assert response.status_code == 200
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}", api
    server.should_exit = True
    thread.join(timeout=10)
    listener.close()


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}, {"width": 320, "height": 800}])
def test_gallery_matches_live_api_and_responsive_layout(browser, live_dashboard, viewport):
    url, api = live_dashboard
    page = browser.new_page(viewport=viewport)
    errors, requests = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: requests.append(request.url))
    try:
        page.goto(url)
        page.wait_for_selector(".dumpster-card")
        assert page.locator(".dumpster-card").count() == 4
        assert page.locator("#route-map, #plan-button").count() == 2
        assert page.locator("#metrics").count() == 0
        assert "Google Maps não está configurado" in page.locator("#route-map").inner_text()
        assert not any("maps.googleapis.com" in request for request in requests)
        records = {record["id"]: record for record in api.get("/api/dumpsters").json()}
        for id_ in ("A", "B"):
            card = page.locator(f'[data-dumpster-id="{id_}"]')
            assert card.locator("h4").inner_text() == records[id_]["name"]
            assert card.locator("img").get_attribute("src").split("?")[0].endswith("fixture-" + id_.lower() + ".png")
            card.locator("img").scroll_into_view_if_needed()
            page.wait_for_function("img => img.complete && img.naturalWidth > 0", arg=card.locator("img").element_handle())
            assert float(card.locator("progress").get_attribute("value")) == records[id_]["latest"]["fill_percentage"]
            assert card.locator("time").get_attribute("datetime") == records[id_]["latest"]["measured_at"]
        empty = page.locator('[data-dumpster-id="EMPTY"]')
        assert empty.locator("progress").count() == 0
        assert "Sem leitura" in empty.inner_text()
        assert "Sem fotografia" in empty.inner_text()
        broken = page.locator('[data-dumpster-id="BROKEN"]')
        broken.scroll_into_view_if_needed()
        page.wait_for_function("() => document.querySelector('[data-dumpster-id=\"BROKEN\"] img').src.endsWith('photo-placeholder.svg')")
        assert "Off-line estimado" in broken.inner_text()
        assert "Último valor conhecido" in broken.inner_text()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        cards = page.locator(".dumpster-card")
        boxes = [cards.nth(i).bounding_box() for i in range(2)]
        assert (abs(boxes[0]["x"] - boxes[1]["x"]) < 1) == (viewport["width"] < 600)
        assert not errors
        if viewport["width"] in (1440, 390):
            Path("build").mkdir(exist_ok=True)
            page.screenshot(path=f'build/gallery-{viewport["width"]}.png', full_page=True)
    finally:
        page.close()


def test_photo_edit_refresh_and_api_failure_preserve_measurements(browser, live_dashboard):
    url, api = live_dashboard
    page = browser.new_page()
    try:
        page.goto(url)
        page.wait_for_selector(".dumpster-card")
        page.locator(".photo-settings summary").click()
        page.select_option("#photo-dumpster", "EMPTY")
        page.fill("#photo-url", "/dashboard/images/dumpsters/fixture-b.png")
        page.locator("#photo-form button").click()
        page.wait_for_function("() => document.querySelector('[data-dumpster-id=\"EMPTY\"] img').src.split('?')[0].endsWith('fixture-b.png')")
        assert api.get("/api/dumpsters").json()[3]["id"] == "EMPTY"
        assert {item["id"]: item for item in api.get("/api/dumpsters").json()}["EMPTY"]["image_url"].endswith("fixture-b.png")
        measured = datetime.now(timezone.utc).replace(microsecond=0)
        assert api.post("/api/measurements", json={"dumpster_id": "A", "distance_cm": 125,
            "raw_distance_cm": 126, "measured_at": measured.isoformat()}).status_code == 200
        page.click("#refresh-button")
        page.wait_for_function("() => document.querySelector('[data-dumpster-id=\"A\"] progress').value === 20")
        page.route("**/api/dumpsters", lambda route: route.abort())
        page.click("#refresh-button")
        page.wait_for_selector("#notice.error")
        assert page.locator(".dumpster-card").count() == 4
        assert "desatualizados" in page.locator("#notice").inner_text()
        page.unroute("**/api/dumpsters")
        page.click("#refresh-button")
        page.wait_for_function("() => document.getElementById('notice').className === 'notice'")
    finally:
        page.close()


@pytest.mark.parametrize("live_dashboard", [False], indirect=True)
def test_empty_initial_failure_and_recovery(browser, live_dashboard):
    url, api = live_dashboard
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.route("**/api/dumpsters", lambda route: route.abort())
        page.goto(url)
        page.wait_for_selector("#notice.error")
        assert "Galeria indisponível" in page.locator("#photo-gallery").inner_text()
        page.unroute("**/api/dumpsters")
        page.click("#refresh-button")
        page.wait_for_selector("#register-link")
        assert "Nenhuma caçamba" in page.locator("#photo-gallery").inner_text()
        assert page.locator("#photo-dumpster").is_disabled()
        page.click("#register-link")
        assert page.locator("#registration").get_attribute("open") is not None
    finally:
        page.close()

def test_overwritten_camera_image_refreshes_without_changing_sensor_values(browser, live_dashboard):
    url, api = live_dashboard
    page = browser.new_page()
    try:
        page.goto(url)
        image = page.locator('[data-dumpster-id="A"] img')
        page.wait_for_selector('[data-dumpster-id="A"] img')
        image.scroll_into_view_if_needed()
        page.wait_for_function("img => img.complete && img.naturalWidth > 0", arg=image.element_handle())
        original_src = image.get_attribute("src")
        assert "_photo_v=" in original_src
        before = {item["id"]: item for item in api.get("/api/dumpsters").json()}["A"]["latest"]
        # Update the file served at the same URL, just as camera.py does.
        photos = next(route.app.directory for route in api.app.router.routes
                      if isinstance(route, Mount) and route.path == "/dashboard/images/dumpsters")
        from ciclorota.camera import atomic_write_photo
        atomic_write_photo(Path(photos) / "fixture-a.png", pixel_png((220, 70, 50)))
        page.click("#refresh-button")
        page.wait_for_function("old => document.querySelector('[data-dumpster-id=\"A\"] img').src !== old", arg=original_src)
        image = page.locator('[data-dumpster-id="A"] img')
        page.wait_for_function("img => img.complete && img.naturalWidth > 0", arg=image.element_handle())
        rgb = image.evaluate("img => { const c = document.createElement('canvas'); c.width = c.height = 1; const ctx = c.getContext('2d'); ctx.drawImage(img,0,0,1,1); return Array.from(ctx.getImageData(0,0,1,1).data).slice(0,3); }")
        assert rgb == [220, 70, 50]
        after = {item["id"]: item for item in api.get("/api/dumpsters").json()}["A"]["latest"]
        assert after["age_seconds"] >= before["age_seconds"]
        assert {k: v for k, v in after.items() if k != "age_seconds"} == {k: v for k, v in before.items() if k != "age_seconds"}
    finally:
        page.close()
