# CicloRota — EcoTech

CicloRota is an IoT-assisted industrial waste collection MVP. ESP32 nodes report filtered ultrasonic distances; the Python service computes calibrated fill estimates. The server stores readings from multiple dumpsters, marks stale devices, selects stops for the next configured collection day, and computes a single-truck route. The collection schedule stays fixed; only stop selection and stop order change.

This repository began with project guidance only. The implementation choices below are now the working MVP architecture. Hardware operation and industrial performance remain unverified.

## Features

- ESP32 + HC-SR04 Arduino firmware with input validation, median spike rejection, scalar Kalman filtering, server-owned per-dumpster calibration, Wi-Fi reconnect, NTP timestamps, HTTP retries, and idempotency IDs.
- FastAPI REST API with SQLite persistence, multiple dumpsters, per-dumpster calibration/thresholds, timestamp ordering, duplicate handling, freshness health, and measurement history.
- Stop selection based on current/projected fill at the next fixed weekday. Stale and offline data are flagged and left for manual review.
- Optional OSRM distance/time matrices. A local haversine-based approximate road-distance fallback supports offline demos. The local solver uses exact Held-Karp TSP through 12 stops and nearest-neighbor plus 2-opt above that.
- Responsive Portuguese monitoring dashboard with a **Dumpster Photo Gallery**, sensor-derived fill levels, raw/filtered distances, measurement timestamps, and freshness-based sensor health. The Google map, dumpster markers, saved route overlay, and route-planning button are restored above the gallery; routing APIs, algorithms, and route history remain available.
- Synthetic multi-site sensor simulator that sends through the same HTTP API as hardware.
- Native C++ tests for firmware measurement logic and Python tests for API, calibration, routing, and simulation definitions.

## Dumpster Photo Gallery

The dashboard prioritizes dumpster monitoring and visual inspection. Each registered dumpster has a card with its photograph (or a clearly labeled placeholder), ID/name, estimated fill, raw and filtered distances, latest measurement timestamp, and sensor freshness status. Data comes from `GET /api/dumpsters` and refreshes every 15 seconds. Times are shown in the browser's local time zone; the original timezone-aware timestamp is retained in the HTML `time` element. Off-line/stale states reflect measurement age, not a verified live Wi-Fi connection. Empty, loading, API failure, and broken-image states are supported. Failed refreshes retain the last successful data with a warning.

The Google map, route overlay, route stop list, and planning button are present alongside the gallery. The route comparison charts remain omitted. Route optimization, fixed collection schedules, `/api/routes/plan`, `/api/routes/latest`, and route-plan storage are preserved. Photographs are for identification only: fill continues to come exclusively from ultrasonic distance and the backend's per-dumpster calibration.

### Store and associate photographs

No identified dumpster photos were found. Existing untracked `ciclorota/data/photo_*.jpg` webcam captures have no dumpster association and are left unchanged; they are not exposed or copied into the image. No photographs are generated.

Place actual dumpster photographs in this directory (filenames may include letters, digits, underscores, dots, and hyphens):

```text
ciclorota/dashboard/images/
  photo-placeholder.svg          # Generic missing-image icon, not a photograph
  dumpsters/
    <your-photo>.jpg             # Add real local images here
```

Supported local image types: JPG/JPEG, PNG, WebP, AVIF, and GIF. Files are served as `/dashboard/images/dumpsters/<your-photo>.jpg`; optional subdirectories are supported. Do not enter a Windows filesystem path. Alternatively, use an accessible absolute HTTP(S) image URL. On an HTTPS deployment, use HTTPS images to avoid mixed-content blocking.

The nullable `image_url` field links the photo to a real dumpster record. Existing records automatically receive `NULL` through an idempotent additive SQLite column migration; no existing records, measurements, or routes are removed. Creating a dumpster still works without `image_url`.

For an existing record, expand **Associar ou alterar uma fotografia**, select its actual ID, enter the path/URL, and save. The registration form also supports an optional photograph URL. These controls save links only; there is no file upload endpoint. API clients may set `image_url` on `POST /api/dumpsters`, or update an existing association:

```http
PATCH /api/dumpsters/<registered-id>/photo
Content-Type: application/json

{"image_url": "/dashboard/images/dumpsters/your-photo.jpg"}
```

Send `{"image_url": null}` to clear it. Unsupported URL schemes, filesystem paths, and local directory traversal are rejected. A valid but unavailable image displays the placeholder; it does not affect sensor measurements.

### Docker photo assets

Local assets under `ciclorota/dashboard/images/` are included by `.dockerignore`, Python package-data rules, and the existing Dockerfile's package copy. No new service, absolute path, or network setting is needed; the existing database volume is preserved and a read-only photo-directory bind mount is added. Compose mounts this host directory read-only into the API container, so added or replaced photos are visible immediately after the dashboard refresh. Rebuild with `docker compose up --build -d` after application code changes. Database associations persist in the existing SQLite volume. With the development bind mount, new local files are available without rebuilding.

## Host camera connected to the gallery

`ciclorota/camera.py` runs on the computer with the webcam, outside Docker. It verifies the selected ID against actual `/api/dumpsters` records before opening the camera, saves the latest complete JPEG into the local photo directory, and links that file through `PATCH /api/dumpsters/{id}/photo`. It never creates a dumpster, posts a sensor measurement, or infers fill from an image. Importing the module does not open a camera.

From the repository root on Windows:

```powershell
# Install the optional camera dependency in the host virtual environment.
.\.venv\Scripts\python.exe -m pip install -e ".[camera]"

# List actual registered dumpster IDs (does not open the camera).
.\.venv\Scripts\python.exe -m ciclorota.camera --list

# Replace YOUR_REGISTERED_ID with the actual container this camera monitors.
.\.venv\Scripts\python.exe -m ciclorota.camera --dumpster-id YOUR_REGISTERED_ID
```

If no IDs are listed, register the real dumpster and its calibration/location in the dashboard or `/docs` first. The script refuses unknown IDs. To select another webcam, add `--source 1`. `--interval 5` is the default capture interval. `--once` saves and links one image, then exits; `--preview` optionally displays a camera window (q exits). Without preview, use Ctrl+C to stop. `--base-url http://localhost:8000` selects the API; the default assumes camera and Docker run on this computer. A video file or camera stream URL may also be supplied as `--source`.

Captured files are named `camera-<id>-<digest>.jpg` under `ciclorota/dashboard/images/dumpsters/`. The suffix distinguishes IDs that differ only in letter case on Windows. Only the selected dumpster's photo link is changed, after a complete first image is saved. Every five seconds the script atomically replaces that file, so readers do not receive a partly written JPEG. It keeps one latest photo per ID rather than an unbounded archive. Camera read/encode errors preserve the previous photo and release the device.

Compose mounts `./ciclorota/dashboard/images/dumpsters` at `/app/ciclorota/dashboard/images/dumpsters:ro`. Capture runs on the host, which can write; the container can only read. Default Docker startup is unchanged:

```powershell
docker compose up --build -d
```

The gallery refreshes every 15 seconds and adds a changing `_photo_v` query parameter to same-origin local photograph URLs. This retrieves updated camera bytes even though the filename is unchanged. External/signed image URLs are left untouched. Sensor measurement timestamps still describe the sensor reading, not the photo capture time. The camera prints its own capture timestamp in UTC; photo timestamps are not stored in the database.

Generated `camera-*.jpg` and temporary `.capture-*.tmp` files are excluded from Git and Docker image builds; they remain available through the directory mount. Existing unassigned webcam captures in `ciclorota/data` are neither imported nor deleted. There is no upload endpoint or automatic dumpster recognition. Run one explicitly configured capture process per camera/dumpster association. To run the camera on another machine, the photograph directory must also be shared/synchronized with the API host; changing `--base-url` alone does not transfer image bytes.

## Run with Docker Compose

Docker Engine with the Docker Compose plugin (Compose v2) is required; Docker Desktop supplies both on Windows and macOS. A first build needs internet access to pull the Python image and install the project dependencies. The application dependencies, Python runtime, and SQLite are supplied by the image; a local Python or Node.js installation is not needed. ESP32 firmware remains on the physical device.

From a fresh checkout, the complete app starts with:

    docker compose up --build -d

No `.env` file is required for the first start. To customize keys or settings, copy `.env.example` to `.env` and edit it before starting. The example contains no credentials. Compose reads `.env` automatically, and Git ignores it.

Useful commands:

    docker compose ps
    docker compose logs -f
    docker compose logs -f ciclorota
    docker compose up --build -d
    docker compose down

For source editing, an optional development override bind-mounts the Python/dashboard package and enables Uvicorn reload. The normal Compose command remains the default:

    docker compose -f compose.yaml -f compose.dev.yaml up --build -d

Stop that development stack with:

    docker compose -f compose.yaml -f compose.dev.yaml down

The service is named `ciclorota`. Its health check calls `/api/health`. Both the Portuguese dashboard and API are served by that service on the same origin:

- Dashboard: http://localhost:8000/
- API health: http://localhost:8000/api/health
- Interactive API docs: http://localhost:8000/docs

Compose publishes host TCP port 8000 by default on `0.0.0.0`, so another device on the same LAN can reach it. Set `CICLOROTA_PORT` in `.env` if port 8000 is occupied; then use that port in the browser and firmware configuration. Set `CICLOROTA_BIND_ADDRESS=127.0.0.1` to restrict access to the local computer, but ESP32 devices will not be able to connect in that mode. On a trusted LAN, allow the selected TCP port through the host firewall and disable Wi-Fi client isolation. This MVP has no device authentication, so do not expose it to the public internet.

### ESP32 on the Docker host's LAN

Find the host computer's current LAN IP address and configure the selected firmware endpoint as:

    http://<HOST-LAN-IP>:8000/api/measurements

For example, if the host currently has address `192.168.1.20`, use `http://192.168.1.20:8000/api/measurements`. Update the endpoint after the host's DHCP address changes, or reserve a stable address in the router. Do not use `localhost`, `127.0.0.1`, or the Compose service name in firmware: those refer to the device itself or Docker's private network. The host firewall and Wi-Fi network must allow the ESP32 to reach the published port.

Register the dumpster ID in CicloRota before configuring the same ID in firmware. The HTTP payload remains the existing JSON contract documented in the ESP32 measurement protocol section. Ingested observations are persisted in the SQLite volume and appear on the dashboard at its next refresh.

### Environment, address lookup, and backend routing

The Compose file passes the existing `CICLOROTA_*` settings from `.env` to the API container. The backend binds to `0.0.0.0:8000` inside Docker. Since the API also serves the dashboard, browser requests use the current page's origin; browser code does not use a Docker-only service hostname.

Address-based registration still uses the backend Google Geocoding API. Set `CICLOROTA_GOOGLE_GEOCODING_API_KEY` in `.env` if needed. Without it, coordinate-based API registration, monitoring, and the photo gallery still work. The map uses the existing browser Maps key and map ID. Configure `CICLOROTA_GOOGLE_MAPS_BROWSER_KEY` and `CICLOROTA_GOOGLE_MAP_ID` for map rendering. No Google key is needed for photo viewing.

After changing environment values, recreate the service:

    docker compose up -d --force-recreate ciclorota

OSRM is still an optional external service; no map data or OSRM container is downloaded. Leave `CICLOROTA_OSRM_URL` blank to use the local approximate-distance fallback. If an OSRM service is running on the Docker host, use `http://host.docker.internal:5000` on Docker Desktop. On Linux, use an address reachable from the container (for example, the Docker host gateway) or attach the service to the Compose network and use its service DNS name. A route failure continues to fall back to the local approximation.

### SQLite persistence and safe reset

SQLite is stored at `/app/data/ciclorota.sqlite3` inside the container and mounted on the named `ciclorota-data` volume. The database is initialized and existing schema migrations run when the API starts. `docker compose down` removes the app container and network but preserves this volume. Rebuilding the image also preserves measurements and route history.

To reset a development database, first stop the app and make a backup, then remove only the database file from the volume and restart the service:

    docker compose stop ciclorota
    docker compose cp ciclorota:/app/data/ciclorota.sqlite3 ./ciclorota-backup.sqlite3
    docker compose run --rm --no-deps --entrypoint python ciclorota -c "from pathlib import Path; Path('/app/data/ciclorota.sqlite3').unlink(missing_ok=True)"
    docker compose start ciclorota

The API recreates an empty schema on startup. This reset removes dumpsters, measurements, route plans, and the geocoding cache; keep the backup if the data may be needed. Do not add `-v` to `docker compose down` unless you intentionally want to delete the persistent volume and all its data.

The optional simulator can populate and exercise the same API from inside the running service:

    docker compose exec ciclorota ciclorota-simulate --cycles 4 --base-url http://127.0.0.1:8000


## Run locally (without Docker)

Python 3.11 or newer is required.

    python3 -m venv .venv
    .venv/bin/python -m pip install -e '.[dev]'
    .venv/bin/uvicorn ciclorota.api:app --reload --host 0.0.0.0 --port 8000

Open http://127.0.0.1:8000 for the dashboard. API documentation is at http://127.0.0.1:8000/docs.

In another terminal, populate four sample sites with repeatable noisy readings and plan a route:

    .venv/bin/python -m ciclorota.simulation --cycles 4

The simulator creates demo dumpsters only when their IDs are absent, posts multiple timestamped sensor measurements per site, and asks the API to plan the next fixed-day run. Re-running it appends new measurement history. To target another server, pass --base-url http://host:8000. Use --seed to repeat the synthetic noise pattern and --interval N to pause between simulated collection cycles.

The default SQLite file is data/ciclorota.sqlite3. Set CICLOROTA_DB_PATH to change it. To reset a demo, stop the server and remove that database file.

## Configuration

All settings are read from environment variables when the API starts.

| Variable | Default | Purpose |
| --- | --- | --- |
| CICLOROTA_DB_PATH | data/ciclorota.sqlite3 | SQLite database file |
| CICLOROTA_FIXED_DAYS | MONDAY,THURSDAY | Fixed dispatch weekdays; comma-separated weekday names |
| CICLOROTA_TIMEZONE | America/Sao_Paulo | Time zone used to calculate the next run and projection horizon |
| CICLOROTA_FILL_THRESHOLD | 75 | Default per-dumpster selection threshold, percent |
| CICLOROTA_STALE_SECONDS | 21600 | Latest reading age after which the device is stale |
| CICLOROTA_OFFLINE_SECONDS | 86400 | Latest reading age after which the device is offline |
| CICLOROTA_GOOGLE_MAPS_BROWSER_KEY | empty | Website-restricted key for Maps JavaScript API; visible to browsers |
| CICLOROTA_GOOGLE_GEOCODING_API_KEY | empty | Secret backend key restricted to Geocoding API |
| CICLOROTA_GOOGLE_MAP_ID | DEMO_MAP_ID | Google Maps map ID; create a project map ID for deployment |
| CICLOROTA_GEOCODER_TIMEOUT | 5 | Google Geocoding API timeout in seconds |
| CICLOROTA_OSRM_URL | empty | Optional OSRM URL; use host.docker.internal:5000 for a host service in Docker Desktop, or localhost:5000 outside Docker |
| CICLOROTA_OSRM_TIMEOUT | 2 | OSRM request timeout in seconds |
| CICLOROTA_AVERAGE_SPEED_KMH | 30 | Duration assumption for fallback distances |
| CICLOROTA_FALLBACK_ROAD_FACTOR | 1.25 | Multiplier applied to straight-line distance in fallback mode |
| CICLOROTA_MAX_EXACT_STOPS | 12 | Stop count limit for exact TSP before heuristic routing |
| CICLOROTA_FUEL_L_PER_100KM | 18 | Estimated truck fuel use |
| CICLOROTA_FUEL_COST_BRL_PER_L | 6.20 | Estimated fuel price |
| CICLOROTA_CO2_KG_PER_L | 2.68 | CO2 conversion per liter of fuel |

Configure the host to use the same local time zone as the collection operations. A supplied collection date must be on one of the configured weekdays; planning does not alter the dispatch schedule.

### Address lookup and retained route APIs

The dashboard registration form accepts a physical street address. FastAPI resolves it with the Google Geocoding API, stores the address and coordinates, and caches successful lookups in SQLite. Configure a secret server key restricted to Geocoding API using `CICLOROTA_GOOGLE_GEOCODING_API_KEY`. A missing address result returns HTTP 422; unavailable configuration/provider returns HTTP 502 without creating a dumpster. Coordinate registration remains available to API clients without a key. Address input is sent to Google; use operational site addresses. Review the provider's policies before public deployment.

The dashboard again loads Maps JavaScript and visualizes dumpster locations and the saved route, following the user’s map restoration request. Existing `CICLOROTA_GOOGLE_MAPS_BROWSER_KEY`, `CICLOROTA_GOOGLE_MAP_ID`, and `/api/config` fields remain for backward compatibility. The secret geocoding key is never returned to browsers.

Backend routing remains operational through the API. OSRM can supply a road-distance/duration matrix; an unavailable service falls back to the configured local approximation. Route algorithms, fixed collection dates, saved route plans, and estimated operating metrics are unchanged and available through `/docs`, through the API as well as the dashboard map and planning control.

## API

- GET /api/health — service/database health.
- GET /api/config — fixed weekdays, next collection date, freshness policy, routing configuration, public Maps JavaScript key and its local configuration status, and map ID. Example keys are withheld; the server geocoding key is never included.
- POST /api/dumpsters — register a site by street address (automatically geocoded) or coordinates for programmatic clients, plus calibration, fill threshold, daily fill-rate estimate, and baseline order.
- GET /api/dumpsters — optional `image_url`, current latest valid measurement, and normal/stale/offline/no-data health.
- PATCH /api/dumpsters/{dumpster_id}/photo — update or clear a photograph association without changing sensor data.
- POST /api/measurements — ingest an ESP32 or simulated observation. The backend recomputes fill percentage from filtered distance and that dumpster's calibration; a supplied fill percentage must agree within five points.
- GET /api/measurements/{dumpster_id}?limit=100 — measurement history.
- POST /api/routes/plan — plan a route for the next fixed day, or a caller-supplied date that matches a fixed weekday. Depot defaults are illustrative São Carlos coordinates.
- GET /api/routes/latest — most recently persisted plan, or JSON `null` with HTTP 200 before a route is planned.
- GET / and /dashboard — monitoring UI.

Measurements require a timezone-aware measured_at timestamp, valid distance, and a registered dumpster ID. Repeated measurement IDs are idempotent. An older delayed observation is retained in history but does not replace the latest measurement.

## Sensor calibration and wiring

For each dumpster, measure sensor-to-surface distance when empty and at the defined maximum usable fill. Require empty distance greater than full distance. The estimated fill is:

    100 * (empty_distance_cm - filtered_distance_cm) / (empty_distance_cm - full_distance_cm)

The result is clamped to 0–100%. This is an estimated level, not certified volume or mass. A single top-mounted ultrasonic sensor can be biased by irregular piles, reflections, moisture, and obstructions. The MVP assumes a linear level-to-fill relationship; calibrate each geometry independently.

The standard HC-SR04 commonly uses 5 V and may return a 5 V ECHO signal. Use an appropriate divider or level shifter before the ESP32's 3.3 V input. Check the exact board/module specifications before wiring.

Two ESP32 targets are available; setup details are in hardware/README.md and firmware/README.md. The pulled Arduino sketch at hardware/sketch_oct17b preserves the working Ultrasonic.read(CM) sensor path, GPIO 4/5, 30 ms echo timeout, 75 cm diagnostic ratio, and 500 ms sampling. It now uses the shared median/Kalman pipeline and posts measurements directly to CicloRota over HTTP. The PlatformIO firmware in firmware/ provides the alternate pulseIn reader and uses the same API and filtering pipeline. The PlatformIO example uses GPIO 4/5 to match the confirmed sketch pins; ignored local secrets files are not overwritten.

Copy the appropriate secrets.h.example file to secrets.h for the selected firmware. Configure Wi-Fi, the full API endpoint, and a dumpster ID already registered in CicloRota. The Arduino sketch configuration is in hardware/sketch_oct17b/secrets.h; PlatformIO configuration is in firmware/include/secrets.h. Both send raw and filtered distance in centimeters and omit fill_percentage so the backend calculates fill from the calibration saved for that dumpster. The PlatformIO calibration constants remain available for local serial diagnostics only.

The ESP32 must use the server computer LAN address, for example http://192.168.1.20:8000/api/measurements, not 127.0.0.1. Run Uvicorn bound to 0.0.0.0 on a trusted local network and allow the port through the host firewall. Firmware uses plain HTTP and public NTP servers; production requires HTTPS, device authentication, and managed credentials/time.

### ESP32 measurement protocol

The device sends `Content-Type: application/json` to `POST /api/measurements`:

```json
{
  "measurement_id": "esp32-D1-unique-id",
  "dumpster_id": "D1",
  "device_id": "esp32-D1",
  "raw_distance_cm": 82.0,
  "distance_cm": 80.0,
  "measured_at": "2026-10-17T13:30:00Z"
}
```

`dumpster_id` must exactly match a registered dumpster. Both distances are centimeters; `distance_cm` is the filtered result. `measured_at` must include a timezone and firmware synchronizes it with NTP. The backend validates the payload, computes estimated fill with that dumpster calibration, stores the observation in SQLite, and exposes it through `GET /api/dumpsters` and `GET /api/measurements/{dumpster_id}`. Measurement IDs remain the same for bounded HTTP retries, making duplicate delivery idempotent. Invalid ranges and unknown dumpster IDs return HTTP 422 and 404 respectively. A successful reading appears on the dashboard at its next 15-second refresh. The simulator remains a separate API client for testing without sensor hardware.

## Tests

    .venv/bin/pytest

The Python suite covers optional photograph associations, safe image links, existing-database compatibility, preserved sensor/routing behavior, fill math, calibration errors, Kalman smoothing, invalid/outlier samples, discontinuity resets, API schema/duplicate/timestamp handling, address geocoding and cache, provider failures, database migration, stale-state behavior, fixed-weekday enforcement, route optimization, local-distance fallback, and demo fixture structure.

The portable firmware measurement pipeline has a standalone native test. With a C++17 compiler:

    g++ -std=c++17 -Ifirmware/include tests/firmware_pipeline_test.cpp -o /tmp/ciclorota-firmware-test
    /tmp/ciclorota-firmware-test

A PlatformIO/ESP32 toolchain and physical hardware are separate from these tests. Software simulation does not verify sensor mounting, electrical levels, radio performance, ESP32 timing, or actual collection results.

### Optional browser checks

Browser tests use temporary SQLite records and tiny PNG test fixtures; they never insert mock readings into the running dashboard database. To run desktop/mobile layout, correct image association, missing-image fallback, zero-fill, timestamps, photo editing, and API failure/recovery checks:

    .venv/bin/python -m pip install playwright
    .venv/bin/python -m playwright install chromium
    .venv/bin/python -m pytest tests/test_dashboard_browser.py -q

On Windows use `.venv\Scripts\python.exe`; tests can use an installed Microsoft Edge instead of downloading Chromium. Browser tests explicitly skip when the optional package/browser is unavailable. Test screenshots are written to ignored `build/`.

## MVP assumptions and limits

- One truck, one depot, and one route are modeled. The collection weekday is fixed; optimizing a route never moves a collection date.
- Conventional baseline means every fresh dumpster in its configured baseline order with a depot return. Optimized route visits only selected fresh sites. Comparisons use the same travel matrix.
- Stop thresholds and daily fill-rate estimates are configurable per dumpster. No measurement or stale input is silently treated as a low fill.
- Above 12 stops, route ordering is heuristic. The TSP objective minimizes travel distance; urgency is handled in eligibility/projection before routing.
- Fuel, CO2, distance-saved, duration, and fuel-cost values are estimates. The system does not infer truck mass capacity from fill percentages. ROI/payback is not calculated because deployment capital and non-fuel operating costs are not known.
- The fallback applies a configurable road detour factor to great-circle distance and assumes a constant average speed; it is not a road-network result. Use OSRM for road-aware estimates.
- No physical ESP32/HC-SR04 test or industrial field trial has been conducted.

### Gallery verification results

Executed locally: 58 tests passed, including five desktop/mobile browser checks
and the native C++ sensing test. JavaScript syntax checking passed. Docker
Compose built and started successfully; the container is healthy, and live
HTTP/browser smoke checks passed for the gallery and placeholder. The live
Docker database had no registered dumpsters; multi-dumpster/image behavior was
verified using isolated test records, without populating the live database.
Real photographs and real container calibration still need to be provided.


### Map restored alongside the gallery

At the user’s request, Google Maps, live dumpster markers, the saved route overlay, and the next-collection planning button are restored above the photo gallery. Navigation includes Mapa. Existing Maps environment settings are reused. Map errors are shown within the map panel without blocking measurements or photographs. Photo associations and sensor ingestion are unchanged.
