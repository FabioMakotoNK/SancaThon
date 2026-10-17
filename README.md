# CicloRota — EcoTech

CicloRota is an IoT-assisted industrial waste collection MVP. ESP32 nodes report filtered ultrasonic distances; the Python service computes calibrated fill estimates. The server stores readings from multiple dumpsters, marks stale devices, selects stops for the next configured collection day, and computes a single-truck route. The collection schedule stays fixed; only stop selection and stop order change.

This repository began with project guidance only. The implementation choices below are now the working MVP architecture. Hardware operation and industrial performance remain unverified.

## Features

- ESP32 + HC-SR04 Arduino firmware with input validation, median spike rejection, scalar Kalman filtering, server-owned per-dumpster calibration, Wi-Fi reconnect, NTP timestamps, HTTP retries, and idempotency IDs.
- FastAPI REST API with SQLite persistence, multiple dumpsters, per-dumpster calibration/thresholds, timestamp ordering, duplicate handling, freshness health, and measurement history.
- Stop selection based on current/projected fill at the next fixed weekday. Stale and offline data are flagged and left for manual review.
- Optional OSRM distance/time matrices. A local haversine-based approximate road-distance fallback supports offline demos. The local solver uses exact Held-Karp TSP through 12 stops and nearest-neighbor plus 2-opt above that.
- Dashboard em português brasileiro com Google Maps Platform, marcadores avançados para cada ponto cadastrado, nível de enchimento e situação dos dispositivos, rota selecionada, ordem de coleta e comparação com a referência.
- Synthetic multi-site sensor simulator that sends through the same HTTP API as hardware.
- Native C++ tests for firmware measurement logic and Python tests for API, calibration, routing, and simulation definitions.

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

### Environment, maps, and routing

The Compose file passes the existing `CICLOROTA_*` settings from `.env` to the API container. The backend binds to `0.0.0.0:8000` inside Docker. Since the API also serves the dashboard, browser requests use the current page's origin; browser code does not use a Docker-only service hostname.

To enable the Google map and address registration, set `CICLOROTA_GOOGLE_MAPS_BROWSER_KEY` and `CICLOROTA_GOOGLE_GEOCODING_API_KEY` in `.env`, keeping them separate and restricted as described below. The browser key is necessarily returned to the browser and must be restricted to website referrers and the Maps JavaScript API. For access through the host LAN address, authorize that origin in Google Cloud as well. Keep `.env` private. After changing environment values, apply them by recreating the service:

    docker compose up -d --force-recreate ciclorota

Without Google credentials, the API and dashboard data table still work; the map shows setup guidance, and address geocoding cannot call Google. Coordinate-based API registration remains available.

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

### Google Maps Platform setup

The dashboard registration form accepts a physical street address. On submission, the FastAPI backend calls the Google Geocoding API, stores the submitted address, returned formatted address, and resolved coordinates in SQLite, then returns the new pin in dashboard data. Coordinate registration remains available to simulator and API clients. An address with no result returns HTTP 422; a provider or configuration failure returns HTTP 502 without creating the dumpster. Successful responses are cached in SQLite for the single-tenant MVP.

To enable maps and address registration:

1. Create a Google Cloud project with billing enabled, then enable **Maps JavaScript API** and **Geocoding API**.
2. Create a browser key restricted to **Maps JavaScript API** and authorized website referrers. For local development, allow `http://localhost:8000/*` and `http://127.0.0.1:8000/*`.
3. Create a separate server key restricted to **Geocoding API** and the backend's source IP. Keep this key secret.
4. Replace both example key values below with actual keys from your Google Cloud project. For Docker Compose, put these values in `.env`; when running Uvicorn directly, export the variables before starting the API. The literal `your-...` values are placeholders and cannot load a map or geocode an address:

       export CICLOROTA_GOOGLE_MAPS_BROWSER_KEY="your-referrer-restricted-browser-key"
       export CICLOROTA_GOOGLE_GEOCODING_API_KEY="your-server-only-geocoding-key"
       export CICLOROTA_GOOGLE_MAP_ID="DEMO_MAP_ID"

   `DEMO_MAP_ID` is for testing. Create and configure a production map ID for deployment.

The browser key is returned by `GET /api/config` so the dashboard can load Maps JavaScript; it is expected to be visible to browsers and must be website- and API-restricted. Example key values are withheld from the response, and `google_maps_key_status` reports `missing`, `placeholder`, or `provided`. This status only checks local configuration; Google validates the actual key. The Geocoding API key is read only by the backend and is never returned by the API. Google Maps may incur usage charges; set quotas and billing alerts in the Cloud project. See Google's [API key security guidance](https://developers.google.com/maps/api-security-best-practices) and [Advanced Markers setup](https://developers.google.com/maps/documentation/javascript/advanced-markers/start).

The dashboard uses Google Maps JavaScript API with a configured map ID and Advanced Markers. It displays every registered dumpster using latest fill and device-health colors, shows site details and route decisions in click popups, overlays the planned route, and refreshes backend status every 15 seconds. If the browser key is not configured or the Google script cannot load, the dashboard explains the required configuration and the API/table remain usable. Google Maps provides its map attribution in the map UI. Address input is sent to Google for geocoding, so enter operational site addresses rather than confidential personal information. Review Google's [Geocoding policies and attribution requirements](https://developers.google.com/maps/documentation/geocoding/policies); the current MVP is single-tenant and the local project does not supply public Terms of Use or Privacy Policy pages required for a public deployment. Review storage and data isolation requirements before changing this into a multi-tenant service.

#### Troubleshooting `InvalidKeyMapError` / `InvalidKey`

These console messages mean Google does not recognize the key being sent to Maps JavaScript API. Set a valid browser API key in `CICLOROTA_GOOGLE_MAPS_BROWSER_KEY` (the separate Geocoding key does not replace it); do not use the example `your-...` value, a project number, or an OAuth client ID. The dashboard now detects example keys locally and displays setup guidance without loading Google's script. In Google Cloud Console, confirm the key belongs to an active project, Maps JavaScript API is enabled and allowed by that key's API restrictions, and the current site origin is allowed by its website referrer restriction. For Docker Compose, recreate the service with `docker compose up -d --force-recreate ciclorota`; when running Uvicorn directly, restart the server. Then hard-refresh the dashboard. Google documents `InvalidKeyMapError` as an unrecognized key and `InvalidKey` as a malformed or incorrect key; see its [error reference](https://developers.google.com/maps/documentation/javascript/error-messages#invalid-key-map-error). Billing and API activation errors have separate console codes.

OSRM mode calls its table service for a full distance/duration matrix. The MVP does not download map data or start OSRM itself; configure an already-running OSRM-compatible service. If the service is unreachable or returns incomplete routes, a warning is returned and the local approximation is used. The dashboard overlays the planned stop sequence on Google Maps. Route distance and duration come from the selected matrix provider; the fallback route line is illustrative, while OSRM distances use its road network.

## API

- GET /api/health — service/database health.
- GET /api/config — fixed weekdays, next collection date, freshness policy, routing configuration, public Maps JavaScript key and its local configuration status, and map ID. Example keys are withheld; the server geocoding key is never included.
- POST /api/dumpsters — register a site by street address (automatically geocoded) or coordinates for programmatic clients, plus calibration, fill threshold, daily fill-rate estimate, and baseline order.
- GET /api/dumpsters — current latest valid measurement plus normal/stale/offline/no-data health.
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

The Python suite covers fill math, calibration errors, Kalman smoothing, invalid/outlier samples, discontinuity resets, API schema/duplicate/timestamp handling, address geocoding and cache, provider failures, database migration, stale-state behavior, fixed-weekday enforcement, route optimization, local-distance fallback, and demo fixture structure.

The portable firmware measurement pipeline has a standalone native test. With a C++17 compiler:

    g++ -std=c++17 -Ifirmware/include tests/firmware_pipeline_test.cpp -o /tmp/ciclorota-firmware-test
    /tmp/ciclorota-firmware-test

A PlatformIO/ESP32 toolchain and physical hardware are separate from these tests. Software simulation does not verify sensor mounting, electrical levels, radio performance, ESP32 timing, or actual collection results.

## MVP assumptions and limits

- One truck, one depot, and one route are modeled. The collection weekday is fixed; optimizing a route never moves a collection date.
- Conventional baseline means every fresh dumpster in its configured baseline order with a depot return. Optimized route visits only selected fresh sites. Comparisons use the same travel matrix.
- Stop thresholds and daily fill-rate estimates are configurable per dumpster. No measurement or stale input is silently treated as a low fill.
- Above 12 stops, route ordering is heuristic. The TSP objective minimizes travel distance; urgency is handled in eligibility/projection before routing.
- Fuel, CO2, distance-saved, duration, and fuel-cost values are estimates. The system does not infer truck mass capacity from fill percentages. ROI/payback is not calculated because deployment capital and non-fuel operating costs are not known.
- The fallback applies a configurable road detour factor to great-circle distance and assumes a constant average speed; it is not a road-network result. Use OSRM for road-aware estimates.
- No physical ESP32/HC-SR04 test or industrial field trial has been conducted.
