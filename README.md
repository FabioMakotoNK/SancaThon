# CicloRota — EcoTech

CicloRota is an IoT-assisted industrial waste collection MVP. ESP32 nodes report calibrated ultrasonic fill estimates to a Python service. The server stores readings from multiple dumpsters, marks stale devices, selects stops for the next configured collection day, and computes a single-truck route. The collection schedule stays fixed; only stop selection and stop order change.

This repository began with project guidance only. The implementation choices below are now the working MVP architecture. Hardware operation and industrial performance remain unverified.

## Features

- ESP32 + HC-SR04 Arduino firmware with input validation, median spike rejection, scalar Kalman filtering, per-device calibration, Wi-Fi reconnect, NTP timestamps, HTTP retries, and idempotency IDs.
- FastAPI REST API with SQLite persistence, multiple dumpsters, per-dumpster calibration/thresholds, timestamp ordering, duplicate handling, freshness health, and measurement history.
- Stop selection based on current/projected fill at the next fixed weekday. Stale and offline data are flagged and left for manual review.
- Optional OSRM distance/time matrices. A local haversine-based approximate road-distance fallback supports offline demos. The local solver uses exact Held-Karp TSP through 12 stops and nearest-neighbor plus 2-opt above that.
- Dashboard with dumpster health/fill, route order, baseline comparison, estimated duration/fuel/CO2/fuel cost, and a schematic route plot.
- Synthetic multi-site sensor simulator that sends through the same HTTP API as hardware.
- Native C++ tests for firmware measurement logic and Python tests for API, calibration, routing, and simulation definitions.

## Run locally

Python 3.11 or newer is required.

    python3 -m venv .venv
    .venv/bin/python -m pip install -e '.[dev]'
    .venv/bin/uvicorn ciclorota.api:app --reload

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
| CICLOROTA_OSRM_URL | empty | Optional OSRM-compatible base URL, for example http://localhost:5000 |
| CICLOROTA_OSRM_TIMEOUT | 2 | OSRM request timeout in seconds |
| CICLOROTA_AVERAGE_SPEED_KMH | 30 | Duration assumption for fallback distances |
| CICLOROTA_FALLBACK_ROAD_FACTOR | 1.25 | Multiplier applied to straight-line distance in fallback mode |
| CICLOROTA_MAX_EXACT_STOPS | 12 | Stop count limit for exact TSP before heuristic routing |
| CICLOROTA_FUEL_L_PER_100KM | 18 | Estimated truck fuel use |
| CICLOROTA_FUEL_COST_BRL_PER_L | 6.20 | Estimated fuel price |
| CICLOROTA_CO2_KG_PER_L | 2.68 | CO2 conversion per liter of fuel |

Configure the host to use the same local time zone as the collection operations. A supplied collection date must be on one of the configured weekdays; planning does not alter the dispatch schedule.

OSRM mode calls its table service for a full distance/duration matrix. The MVP does not download map data or start OSRM itself; configure an already-running OSRM-compatible service. If the service is unreachable or returns incomplete routes, a warning is returned and the local approximation is used. The dashboard draws a schematic route between site coordinates; the route distance and duration come from the selected matrix provider.

## API

- GET /api/health — service/database health.
- GET /api/config — fixed weekdays, next collection date, freshness policy, and routing configuration.
- POST /api/dumpsters — register a site and its coordinates, empty/full calibration, fill threshold, daily fill-rate estimate, and fixed baseline order.
- GET /api/dumpsters — current latest valid measurement plus normal/stale/offline/no-data health.
- POST /api/measurements — ingest an ESP32 or simulated observation. The backend recomputes fill percentage from filtered distance and that dumpster's calibration; a supplied fill percentage must agree within five points.
- GET /api/measurements/{dumpster_id}?limit=100 — measurement history.
- POST /api/routes/plan — plan a route for the next fixed day, or a caller-supplied date that matches a fixed weekday. Depot defaults are illustrative São Carlos coordinates.
- GET /api/routes/latest — most recently persisted plan.
- GET / and /dashboard — monitoring UI.

Measurements require a timezone-aware measured_at timestamp, valid distance, and a registered dumpster ID. Repeated measurement IDs are idempotent. An older delayed observation is retained in history but does not replace the latest measurement.

## Sensor calibration and wiring

For each dumpster, measure sensor-to-surface distance when empty and at the defined maximum usable fill. Require empty distance greater than full distance. The estimated fill is:

    100 * (empty_distance_cm - filtered_distance_cm) / (empty_distance_cm - full_distance_cm)

The result is clamped to 0–100%. This is an estimated level, not certified volume or mass. A single top-mounted ultrasonic sensor can be biased by irregular piles, reflections, moisture, and obstructions. The MVP assumes a linear level-to-fill relationship; calibrate each geometry independently.

The standard HC-SR04 commonly uses 5 V and may return a 5 V ECHO signal. Use an appropriate divider or level shifter before the ESP32's 3.3 V input. Check the exact board/module specifications before wiring.

Firmware details and PlatformIO commands are in firmware/README.md. Copy firmware/include/secrets.h.example to firmware/include/secrets.h and set Wi-Fi, endpoint, device/dumpster IDs, pin mapping, and calibration. The secrets header is git-ignored. Firmware sends plain HTTP and uses public NTP servers, suitable only for a trusted development network. Production requires HTTPS/device authentication and managed credentials/time.

## Tests

    .venv/bin/pytest

The Python suite covers fill math, calibration errors, Kalman smoothing, invalid/outlier samples, discontinuity resets, API schema/duplicate/timestamp handling, stale-state behavior, fixed-weekday enforcement, route optimization, local-distance fallback, and demo fixture structure.

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
