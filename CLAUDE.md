# CLAUDE.md — EcoTech / CicloRota

> Project context and working instructions for AI coding assistants.
> Event: **SancaThon 2026** · Team: **EcoTech** · Project: **CicloRota — Dynamic Reverse Logistics Management**
>
> **Status convention:** This file documents the proposed system and known architectural decisions. It does **not** prove that hardware, code, endpoints, algorithms, or integrations have already been implemented. Inspect the repository before making implementation claims.

## 1. Project identity and motivation

**Team members**
- Rodrigo Eidji Kurogi
- João Pedro Peressin Beduschi
- Fabio Makoto

**Problem.** Industrial waste collection often uses fixed schedules and fixed routes, even when some dumpsters do not need emptying. This can cause unnecessary stops and travel, low truck utilination, wasted fuel, higher operating costs, and increased CO₂ emissions.

**Target users.** Industrial facilities that generate substantial waste (particularly food processing, metalworking, and manufacturing), logistics and sustainability managers, operations teams, and outsourced industrial waste-collection providers.

**Goal.** Create an IoT-assisted waste-collection system that measures estimated dumpster fill levels, sends the readings to a centralized Python service, selects necessary collection stops, and computes a more efficient route. The current dashboard prioritizes fill levels, sensor measurements, freshness, and dumpster photographs. Backend route optimization remains available through the API and the restored Google map and planning control.

**Important operational rule (clarified by the team):** **Collection days/times remain fixed. Only which dumpsters are visited and the route/order of stops change dynamically** based on current measurements and collection constraints. Earlier project descriptions mention dynamically scheduling collections; interpret that as *dynamic stop and route selection within the fixed collection schedule*, not as rescheduling truck dispatch dates.

## 2. Confirmed design decisions

The team has described this intended end-to-end design:

1. Deploy **ESP32 microcontrollers** with **HC-SR04 ultrasonic sensors** at waste dumpsters.
2. Measure distance from the sensor to the waste surface. The Python backend derives estimated fill using the registered dumpster calibration.
3. The ESP32 validates readings, rejects spikes, and applies the shared median plus scalar Kalman pipeline before sending filtered distance.
4. Send measurements over **Wi-Fi using HTTP** to a **Python-based server**.
5. Aggregate readings from **multiple dumpsters** on the server; track their latest reported occupancy and data freshness.
6. Determine which dumpsters warrant collection on the next fixed collection run.
7. Calculate an efficient collection route using **mapping/routing algorithms** and the selected stops.
8. Present the relevant information in a **monitoring dashboard**.

**MVP implementation choices recorded in this repository:** FastAPI, SQLite, documented REST schemas, Google Geocoding for address registration, OSRM as an optional route-matrix service, and a static monitoring dashboard. See the README and section 13 for the current implementation. Site-specific calibration, operational thresholds, physical installation, and production deployment still require field validation.

## 3. Intended system architecture

```text
┌─────────────────────────────────────────────┐
│ Dumpster N                                  │
│ HC-SR04 → ESP32 → validation/filtering      │
│                   → fill-level estimation   │
└─────────────────────────┬───────────────────┘
                          │ Wi-Fi / HTTP
             (many dumpsters, independent IDs)
                          │
                          ▼
┌─────────────────────────────────────────────┐
│ Python server                               │
│ HTTP ingestion → validation → persistence  │
│                  → current dumpster status  │
│                  → collection-stop decision │
│                  → routing/optimization     │
└─────────────────────────┬───────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────┐
│ Dashboard                                   │
│ Dumpster status · Sensor readings · Photos  │
│ Measurement timestamps and sensor freshness   │
└─────────────────────────────────────────────┘
```

**Responsibility boundary:** The ESP32 should focus on sensing, signal processing, and communication. The server should own persistent state, fleet/stop constraints, and route computation. Do not compute full multi-dumpster routes on microcontrollers.

**Terminology:** Sensor readings can be periodic rather than continuous. Avoid calling them strictly *real-time* unless the acquisition/transmission cadence supports that claim; *near-real-time* or *latest available reading* may be more accurate.

## 4. Sensing and fill-level estimation

- Install the HC-SR04 so that it measures downward from a known reference position at or near the top of each dumpster.
- For a simple container with approximately constant cross-sectional area, estimate the fill percentage as:

  ```text
  fill_percent = 100 × (D_empty - D_measured) / (D_empty - D_full)
  ```

  Where `D_empty` is the calibrated sensor-to-surface distance when empty, `D_full` is the distance at the defined maximum usable fill level, and `D_measured` is the validated/filtered reading. Require `D_empty > D_full` and clamp a valid result to `[0, 100]`.
- **A single ultrasonic sensor measures distance, not true volume or mass.** Irregular heaps, objects directly below the sensor, tilted dumpsters, moisture, acoustic reflections, and occlusions can bias the estimate. Describe the output as *estimated fill percentage* rather than certified volume.
- Track calibration information **per dumpster**; do not assume all container geometries are equal. For non-uniform container cross-sections, a linear fill-to-volume conversion may be wrong.
- If volume estimates are required, combine the estimated level with known container geometry or an empirically calibrated mapping. Truck **mass** capacity cannot be determined reliably from measured fill volume without waste-density assumptions or weighing.
- Standard HC-SR04 modules commonly use 5 V and can output a 5 V ECHO signal. **Protect 3.3 V ESP32 GPIO** with an appropriate level shifter or voltage divider. Verify the exact sensor/module specifications and power wiring.
- Industrial deployment adds dust, humidity, vibration, corrosion, impact, and metal-dumpster Wi-Fi attenuation. The HC-SR04 is acceptable for a controlled MVP; consider an industrial-rated or waterproof sensor and antenna placement for field use.

### Measurement-processing guidance

```text
Raw readings → range validation → median spike rejection → Kalman estimate
             → HTTP distance report → server per-dumpster calibration → estimated fill
```

- Validate timeouts, non-echoes, physically impossible distances, and transient spikes **before** interpreting a reading.
- A one-dimensional Kalman filter is a reasonable smoothing approach; choose/tune process noise and measurement noise empirically. A median-based spike rejection stage can help with large outliers.
- Recognize genuine step changes (e.g., when a dumpster is emptied). A slow filter must not incorrectly mask a persistent real change. Consider resetting/reinitializing the estimate after a confirmed discontinuity.
- If feasible, retain a way to inspect raw and filtered measurements during testing; this is useful for filter tuning and debugging.

## 5. Connectivity and server ingestion

**Confirmed transport:** ESP32 → Wi-Fi → HTTP → Python server. Multiple ESP32 devices may report independently to the same service when network connectivity is available.

**Implemented firmware ingestion contract: FastAPI `POST /api/measurements`.**

```http
POST /api/measurements HTTP/1.1
Content-Type: application/json
```

```json
{
  "measurement_id": "esp32-D001-unique-id",
  "dumpster_id": "D001",
  "device_id": "esp32-D001",
  "raw_distance_cm": 43.1,
  "distance_cm": 42.5,
  "measured_at": "2026-10-17T13:30:00Z"
}
```

The firmware sends measurement ID, dumpster ID, device ID, raw distance in centimeters, filtered distance in centimeters, and a timezone-aware measured_at timestamp. The current ESP32 targets omit fill_percentage so server-side per-dumpster calibration is authoritative. The schema accepts an optional fill_percentage from other clients and checks it against the same calibration.

**Recommended ingestion behaviors:**
- Identify every physical dumpster/device consistently; prevent accidental mixing of readings.
- Validate schema, timestamps, units, percentages, and plausible ranges.
- Store measurement history and the latest *valid* observation per dumpster.
- Record freshness/last-seen state; never assume a stale value is current.
- Handle ESP32 disconnects and HTTP errors using bounded retries, automatic Wi-Fi reconnection, and appropriate timeouts. If data must survive outages, buffer readings within available device storage constraints.
- Design for duplicate or delayed requests (e.g., idempotent measurement IDs or timestamp-based handling).
- For deployments beyond a trusted lab network, use HTTPS, device authentication, and sensible secret management. Do not hard-code credentials or commit them to source control.

## 6. Route planning and collection policy

**Hard constraint:** Departure/collection days remain fixed. Optimization occurs when preparing each run and may be recomputed when useful based on fresh data. Changing the route is **not** equivalent to changing the collection schedule.

**Initial MVP logic (suggested; not yet confirmed):**
1. Obtain the latest valid, sufficiently recent fill estimate for each dumpster.
2. Mark candidate dumpsters whose fill level exceeds a configurable threshold.
3. Account for known operational rules and any risk of overflow before the **next** fixed collection date; below-threshold dumpsters may still require collection.
4. Build a travel distance/time matrix for selected sites using a real road network (not just straight-line distances).
5. Optimize the sequence of stops; for multiple trucks, include depot locations, vehicle capacities, and other routing constraints where known.
6. Publish selected stops, omitted stops, reasons/priority, and resulting route to the dashboard.

Potential model: **Traveling Salesperson Problem (TSP)** for one truck with fixed eligible stops; **Vehicle Routing Problem (VRP)** for multiple vehicles, capacity constraints, or richer dispatch requirements. This MVP uses a deterministic local TSP solver, Google Maps Platform for the dashboard map and address geocoding, and optional OSRM road-network matrices.

**Optimization objective:** Reduce unnecessary road travel, time, and cost *subject to* acceptable service quality, overflow prevention, and vehicle constraints. Minimizing distance alone is insufficient if it causes missed urgent collections.

**Scope note:** Fill level alone is a limited proxy for waste amount. If the model uses vehicle load, label estimates and assumptions explicitly. Do not assume all waste types have the same density.

## 7. Current dashboard and retained routing scope

The dashboard displays registered dumpster identification, optional photographs, sensor-derived fill estimates, raw/filtered distance, measurement timestamps, and freshness-based sensor health. The responsive **Dumpster Photo Gallery** and measurement table refresh from the real backend every 15 seconds. Missing or broken photographs show a clearly labeled generic placeholder. Photographs never determine occupancy.

The user explicitly requested the map back after the photo-gallery update. Google Maps, live dumpster markers, saved route overlay, route stop list, map navigation, and route planning control are restored alongside the gallery. Comparison charts remain omitted. Route optimization algorithms, APIs, fixed collection schedules, estimated operating metrics, and route database history remain part of EcoTech.

## 8. Validation plan

**Current evidence described in the original project submission:** Conceptual only. Planned validation includes realistic synthetic-data simulations, prototype development, and eventually testing with an industrial partner. There is no confirmed field-performance result in the available project description.

Use an apples-to-apples comparison:

| Baseline: conventional service | EcoTech approach |
| --- | --- |
| Fixed collection days | Same fixed collection days |
| Fixed or all preselected stops | Stops selected using occupancy/urgency |
| Conventional fixed sequence | Road-aware optimized sequence |
| Reference travel/cost data | Travel/cost derived under matching assumptions |

Measure distance, stops, travel time, estimated fuel use/CO₂, capacity utilization (if estimable), and overflows or missed required collections. Test **multiple collection cycles** and varying fill patterns; don't extrapolate from one favorable example.

Suggested technical tests:
- Sensor calibration against known fill heights and different waste-surface geometries.
- Noise/outlier handling and detection of sudden emptying events.
- Loss of Wi-Fi, HTTP failures, duplicate and out-of-order messages.
- Multiple simultaneous reporting dumpsters and stale-device behavior.
- Route determinism/validity, vehicle capacity constraints, and overflow policy.
- End-to-end demo: change a physical dumpster level → ingest an updated estimate → observe sensor-derived fill and timestamp updates on the dashboard; verify routing separately through its API.

## 9. MVP roadmap (planned work, not a completion report)

1. **Sensing:** Wire and calibrate HC-SR04 + ESP32; validate readings; implement and tune the Kalman filter.
2. **Transmission:** Join Wi-Fi and POST measurements to the Python service; test failures and retries.
3. **Storage and state:** Persist multiple dumpsters and expose current, timestamped readings.
4. **Stop-selection rules:** Implement configurable occupancy thresholds plus stale-data and urgency handling.
5. **Route optimization:** Add road-distance/time calculations, then a TSP/VRP approach as complexity requires.
6. **Dashboard:** Display dumpster monitoring, sensor measurements, and the photo gallery; route visualization is intentionally out of scope.
7. **Evaluation:** Compare the conventional baseline with EcoTech using realistic scenarios, report assumptions and outcomes.
8. **Field validation (future):** Test with a potential industrial partner, assess hardware durability, operating costs, and scalability.

**Do not mark roadmap items complete without inspecting code, tests, hardware reports, or evidence provided by the team.**

## 10. Guidance for AI contributors

When working on this project:

1. **Preserve the product constraint:** Fixed collection schedule; variable collection stops and travel route.
2. **Use the existing repository as the source of truth for implementation details.** This document states project intent, not necessarily current code state.
3. **Distinguish fact from recommendation.** ESP32, HC-SR04, Kalman filtering, Wi-Fi/HTTP, Python server, multiple dumpsters, and dynamic route/stop selection are team-described design elements. FastAPI, SQLite, OR-Tools, OSRM, Streamlit, thresholds, sampling cadence, and suggested API shapes are options until adopted.
4. **Don't overclaim accuracy.** A top-mounted ultrasonic sensor estimates a distance/level; true volume and weight require additional information.
5. **Do not silently discard errors.** Distinguish bad measurements, stale devices, network failures, and genuine low fill levels.
6. **Keep components modular.** Separate sensor I/O, filtering, fill conversion, HTTP client, backend validation/storage, stop selection, routing, and UI so each can be tested independently.
7. **Favor an end-to-end working demo over premature complexity.** Establish reliable sensing → server ingestion → dashboard monitoring first; validate backend routing independently.
8. **When introducing a new technology or design change**, state whether it is a recommendation or a confirmed team decision and update this document once the choice is made.
9. **Report outcomes with evidence.** Label synthetic examples, simulations, calibration results, and production observations separately.
10. **Avoid inventing repository structure, libraries, device pin assignments, or working endpoints.** Inspect actual files before writing code or instructions that depend on them.

## 11. Original project scope (English summary of the partial submission)

1. **Problem:** Fixed waste-collection routes and times generate unnecessary journeys, underutilized trucks, fuel waste, costs, and CO₂ emissions.
2. **Target audience:** Waste-intensive industries, especially food processing, metalworking, and manufacturing; logistics, sustainability, operations, and waste-hauling providers.
3. **Proposed solution:** An intelligent reverse-logistics platform that monitors container filling and automatically optimizes collection routes.
4. **Operation:** IoT sensors send occupancy information to an online platform; an algorithm considers collection need, distance, truck capacity, and urgency; a dashboard displays operational and environmental indicators.
5. **Differentiation:** Data-informed collection rather than exclusively fixed routes, combining IoT, routing, and financial/environmental indicators including ROI.
6. **Initial validation:** Conceptual; planned comparison of traditional and intelligent routes with realistic synthetic data.
7. **Next steps:** ESP32-based sensor MVP, database, monitoring platform, routing algorithm, dashboard, simulations, potential industrial-partner validation, and economic/scalability analysis.

*Clarification applicable throughout:* The team subsequently specified **fixed collection schedules with dynamically selected stops and routes**, which takes precedence over less precise language in the original submission.


## 12. MVP implementation decisions and software status (2026-10-17)

The following choices were made to produce a runnable MVP. They are implementation choices, not additional team-confirmed requirements:

- The backend uses FastAPI, Pydantic, SQLite, and a static browser dashboard.
- Firmware targets PlatformIO/Arduino on an ESP32. The device validates and filters distance before posting; the backend recomputes the estimated fill percentage using that dumpster's registered calibration.
- The default fixed collection weekdays are Monday and Thursday in the America/Sao_Paulo time zone. Both are configurable. Route planning rejects dates outside the configured weekdays and never changes a dispatch date.
- The MVP models one truck and one depot. OSRM is optional. Without it, a configurable haversine detour approximation supports local demonstrations. Exact Held-Karp TSP is used through 12 stops, followed by nearest-neighbor plus 2-opt for larger runs.
- Fuel use, fuel price, average speed, road detour, and CO2 conversion factors are configurable estimates. A monetary fuel comparison is shown; ROI/payback is not computed because capital and non-fuel operating costs are not available.
- Demo coordinates and fill histories are synthetic. The simulator posts through the real HTTP API and does not validate physical sensing or industrial performance.

Software verification recorded for this implementation:

- Python API, database, policy, routing, sensing, simulator fixture, and native firmware logic suite: 19 tests passed.
- The portable C++ sensor pipeline compiled with g++ and its executable test passed.
- Dashboard JavaScript passed Node syntax checking.
- A local Uvicorn server accepted simulated readings for four dumpsters and returned a route using the local distance fallback.

Still unverified:

- Building and flashing main.cpp with the ESP32 PlatformIO toolchain, because that toolchain and board were not available in this environment.
- HC-SR04 wiring, calibration against real containers, ESP32 Wi-Fi/HTTP behavior, and industrial field durability.
- OSRM against an actual configured road-network service. Its failure fallback is covered by a mocked test.
- Hardware buffering during long network outages; the current firmware retries a bounded number of times and resumes at its next measurement interval.


## 13. Historical address registration and coverage map (superseded by section 19 for dashboard UI)

The dashboard registers dumpsters using physical street addresses. The FastAPI backend resolves each submitted address with the Google Geocoding API and stores the entered address, formatted result, and coordinates. Coordinate-only registration remains available to API clients and the simulator. Existing SQLite databases are migrated to add address fields and a persistent lookup cache.

Google Maps Platform replaces the previous map and geocoding providers. Configure a referrer-restricted browser key for Maps JavaScript API, a separate secret backend key for Geocoding API, and a map ID. The backend exposes only the browser key through `GET /api/config`; it never returns the Geocoding API key. The map uses Google Maps JavaScript API and Advanced Markers, which require a map ID; `DEMO_MAP_ID` is a testing default. No key is committed to the repository. Missing credentials leave the API and dashboard data usable while the map displays setup guidance and address registration returns a provider error. Google's `gm_authFailure` callback also displays an actionable message when the browser key is rejected.

The dashboard renders all registered dumpster positions, fill and device-health status pins, marker popups with address/readings/route decisions, and a planned route overlay. Its status data refreshes every 15 seconds. A user's submitted address is sent to Google for geocoding. The current MVP is single-tenant; Google's Geocoding policies, key restrictions, public Terms/Privacy requirements, and location-data retention rules must be reviewed before public or multi-tenant deployment.

Verification for this provider migration: 29 Python tests passed, including Google Geocoding API response/status parsing, URL key usage, persistent-cache behavior, API key separation, address registration, database migration, and dashboard integration checks. JavaScript syntax and Python compilation passed. Live Google Maps display and geocoding were not tested because no Cloud project, keys, billing configuration, or deployed referrer restrictions are provided. The dashboard uses the documented demo map ID until a project-specific map ID is configured.

## 14. Historical Google Maps diagnostics (dashboard map removed in section 19)

The running local server was configured with the documented example browser key, which Google rejected with `InvalidKeyMapError`. The backend now classifies missing, placeholder, and provided browser keys. It withholds obvious example values from `GET /api/config`, and the dashboard displays an actionable setup message instead of loading Google Maps with those values. The server also treats an example Geocoding key as unconfigured. This local check does not validate real Google credentials; Google Cloud still must accept the supplied key, billing, API access, and referrer restrictions.

Before any route has been planned, `GET /api/routes/latest` now returns HTTP 200 with JSON `null`; the dashboard treats it as the normal empty state. A dashboard favicon and `/favicon.ico` redirect remove the unrelated missing-icon request. After Uvicorn reloaded, the live local server returned HTTP 200 and `null` for the latest route, HTTP 307 for the icon redirect, and a `placeholder` key status with no browser key sent. The 29 Python tests, JavaScript syntax check, and Python compilation passed. Rendering a live Google map still requires valid Cloud credentials and was not verified here.

## 15. Dashboard em português brasileiro (2026-10-17)

Todo o texto visível do dashboard está em português brasileiro: estrutura HTML, estados e erros, decisões de coleta, datas e números localizados, acessibilidade e textos dos marcadores. A Maps JavaScript API é carregada com `language=pt-BR` e `region=BR`; mensagens recebidas da API são convertidas para mensagens em português antes de aparecer na interface.


## 16. ESP32-to-dashboard integration review (2026-10-17)

The latest pull is identified from repository history as commit `be6b84d` on top of `a121b80`; it adds `hardware/sketch_oct17b/sketch_oct17b.ino` and `hardware/server.py`. The pulled sketch retained its HC-SR04 library read, GPIO TRIG 4 / ECHO 5, 30 ms echo timeout, 75 cm diagnostic ratio, and 500 ms acquisition interval. Its prior EMA and TCP CSV transport did not implement the project Kalman/HTTP/database path. The integrated sketch now applies the shared `firmware/include/sensor_pipeline.h` median/Kalman validation code and posts directly to `POST /api/measurements`.

The ESP32 request contract is `measurement_id`, registered `dumpster_id`, `device_id`, `raw_distance_cm`, filtered `distance_cm`, and timezone-aware UTC `measured_at`. Distances are centimeters. IDs use the same configured dumpster identifier as registration. Bounded HTTP retries reuse one measurement ID. The ESP32 omits `fill_percentage`: FastAPI validates the ID and distances, calculates fill with that dumpster calibration, and stores raw/filtered distance, fill, measurement time, and receive time in SQLite. The dashboard reads the API-backed latest value and refreshes every 15 seconds. The simulator remains a separate HTTP client for no-hardware demonstrations.

The PlatformIO target remains available and shares the same pipeline and HTTP field contract; its sample/default GPIO settings now match the working sketch at 4/5. Its included local calibration is used only for serial diagnostics, not as the source of dashboard fill values. Existing ignored local secrets are not replaced. Arduino sketch credentials and endpoint are separately configured in the ignored `hardware/sketch_oct17b/secrets.h` copied from its example.

`hardware/server.py` remains only as a legacy TCP CSV console and does not store data or update CicloRota. Do not use it for end-to-end validation. Run FastAPI on the server computer LAN interface and configure the ESP32 with that reachable address, port 8000, and `/api/measurements`; `127.0.0.1` is not reachable from a separate device. Plain HTTP is for a trusted development LAN only.

Two HTTP API integration tests and two firmware source-contract tests were added for this review, covering persistence, backend calibration, history/latest dashboard data, invalid/missing data, unknown IDs, pins, shared filtering, and JSON field names. `python3 -m py_compile` passed for the changed Python modules and tests. Attempts to launch `pytest -q`, `python3 -m pytest -q`, and the native `g++` test were stopped before command execution by the command sandbox error `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`; therefore no test pass is claimed for this review. PlatformIO and Arduino CLI are not installed. Software tests do not validate the Arduino build, physical GPIO, HC-SR04 timing/electrical levels, Wi-Fi, NTP, HTTP behavior on the device, or real container calibration. The full automated suite and device-bench checks remain pending.

## 17. Docker Compose deployment architecture (2026-10-17)

The software MVP runs in one Docker Compose service, `ciclorota`. A multi-stage Dockerfile builds the existing Python project into a Python 3.12 slim runtime image and runs Uvicorn as a non-root user, bound to `0.0.0.0:8000`. The API serves the static Portuguese dashboard from the same origin, so browser requests use the page host and do not depend on Docker DNS. The ESP32 is physical hardware and is not containerized.

SQLite remains the database. Compose mounts the named `ciclorota-data` volume at `/app/data`; the default `CICLOROTA_DB_PATH` is `/app/data/ciclorota.sqlite3`. SQLite schema initialization and additive migrations run on API startup. `docker compose down` preserves the data volume; removing it requires an explicit destructive volume removal.

Compose publishes host port 8000 on `0.0.0.0` by default to permit a same-LAN ESP32 to post to `http://<host-LAN-IP>:8000/api/measurements`. The host firewall and Wi-Fi network must permit that traffic. The dashboard and API use `http://localhost:8000` from the host. Set `CICLOROTA_BIND_ADDRESS` and `CICLOROTA_PORT` to change host publication. Docker service names are for container-to-container traffic only and must not be used in browser code or firmware.

No separate database, frontend, or OSRM container is needed by this implementation. OSRM remains optional and is configured with `CICLOROTA_OSRM_URL`; when unset or unreachable, the API uses its existing local approximate-distance route matrix. Existing Google-related environment variables are preserved. Only the backend Geocoding key is used for address lookup by the current dashboard; its gallery and monitoring do not load Maps JavaScript or need a browser key.

Configuration lives in the ignored `.env` file, copied from the secret-free `.env.example`. Compose supplies defaults when no `.env` exists, so `docker compose up --build -d` is the quick start. The container health check requests `/api/health`; restart policy is `unless-stopped`. See README.md for quick start, LAN/ESP32 setup, maps and routing configuration, logs, persistence, rebuilds, safe reset, and testing. The optional `compose.dev.yaml` override bind-mounts `ciclorota/` read-only and enables Uvicorn reload; start it with `docker compose -f compose.yaml -f compose.dev.yaml up --build -d`.

## 18. Docker integration verification status (2026-10-17)

Docker support was implemented with a root Compose file, a multi-stage Python image, a named SQLite data volume, a health check, a Compose bridge network, an environment example, and LAN setup documentation. Docker and Python runtime validation could not be executed in the current command sandbox: each attempt to launch `docker compose config --quiet`, `docker compose up --build -d`, `python3 -m pytest -q`, and `python3 -m py_compile ciclorota/*.py tests/*.py` was stopped before the command ran by `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. The Docker executable is present on the host, but these commands did not reach Docker or Python.

Consequently, image builds, Compose parsing, container health, HTTP API availability, SQLite persistence across container recreation, simulated measurement ingestion, route planning inside a container, and dashboard refresh from a container have not been verified here. The ESP32 remains physical hardware and was not validated through Docker or simulation. On a machine with a working Docker Engine and Compose plugin, run the documented quick start and API/simulator checks in README.md, then verify same-LAN device access and persistence across `docker compose down` followed by `docker compose up -d`.


## 19. Dumpster monitoring and Photo Gallery (implemented; map removal superseded by section 20)

At the user's explicit request, the static HTML/CSS/JavaScript dashboard now prioritizes sensor monitoring and visual inspection. The **Dumpster Photo Gallery** replaces the map, route overlay/stop list, impact comparison, route planning controls, and route-related UI requests. The page retains Portuguese navigation, responsive layouts, address registration, and 15-second measurement refresh. It displays real `/api/dumpsters` records with ID/name, optional photo, sensor-derived fill, raw/filtered centimeters, measurement timestamp, and freshness status. API failures retain the last successful snapshot with a warning; initial failure, loading, empty data, missing photo, and failed-image states are explicit. Status is inferred from measurement age, not a verified Wi-Fi connection.

Backend route algorithms, `/api/routes/plan`, `/api/routes/latest`, measurement ingestion/history, and route database tables are preserved. No ESP32 or HC-SR04 firmware changes are required. Photos are never used to estimate fill.

Photo storage is `ciclorota/dashboard/images/dumpsters/`; the static URL is `/dashboard/images/dumpsters/<filename>`. JPG/JPEG, PNG, WebP, AVIF, GIF, and absolute HTTP(S) image URLs are supported. A generic `dashboard/images/photo-placeholder.svg` is a missing-image icon, not a fake photograph. Existing untracked webcam images under `ciclorota/data/` have no confirmed dumpster association and remain untouched and unexposed.

A nullable `dumpsters.image_url` column is added idempotently at startup; older records remain valid with NULL. `POST /api/dumpsters` accepts the optional field, `GET /api/dumpsters` returns it, and `PATCH /api/dumpsters/{id}/photo` updates/clears it for an existing record. The gallery's association form and registration form save links only. No upload support is implemented. Image URL validation rejects unsafe schemes, local filesystem paths, and local traversal. The image field does not alter measurement ingestion, calibration, or timestamps.

Nested assets are included through `.dockerignore`, package-data configuration, and the existing Dockerfile. Compose networking, environment variables, services, port 8000, and the persistent SQLite volume are unchanged. Rebuild after adding local photos; the development bind mount serves them directly. Existing databases gain only the nullable image column; no destructive migration or separate migration system is introduced.

Implemented: gallery, photo association forms/API, additive schema support, static packaging, missing-image handling, and monitoring UI. Not implemented: uploads, automatic camera-to-dumpster association, computer vision, photo-derived fill, authentication, or photo capture timestamps. Field calibration and physical sensor validation remain separate from software checks. Historical map descriptions above document prior behavior, not the current UI.

### Verification of the gallery implementation

Executed on the local Windows environment: all **58 automated tests passed**,
including five Edge browser cases (1440 px desktop, 390 px and 320 px mobile,
photo association editing, measurement refresh, API failure/recovery, and empty
states) and the native C++ sensor pipeline test. JavaScript passed Node syntax
checking. Existing integration timestamp assertions were corrected to compare
the API's established second precision; the native test now uses relative
compiler paths and an executable suffix for Windows compatibility. Firmware
source and its measurement protocol were not modified.

`docker compose up --build -d` succeeded. The rebuilt service is healthy on
port 8000. Container checks verified the gallery, placeholder asset, image
storage directory, optional photo response field, and retained routing API.
Unassigned local webcam captures are explicitly excluded from the Docker build.
A headless browser also verified the running Docker dashboard without inserting
test data. At verification time the live database had zero registered dumpsters;
multi-dumpster/image cases ran against isolated temporary SQLite records and
explicitly labeled PNG test fixtures, not against the live deployment.

No real dumpster photo association or physical sensor measurement was validated
by these UI tests. Actual photographs must be supplied and linked to registered
IDs. The test environment emitted a non-failing Starlette/httpx deprecation
warning; optional browser tooling is used only for verification.


## 20. Map restored at explicit user request

The user reversed the previous map-removal instruction. The dashboard now includes the original Google Maps integration above the photo gallery, with live dumpster markers, reading/status popups, a saved route overlay, route stop labels, and the next-fixed-day route planning button. Existing Maps browser key/map ID and backend routing APIs are reused. The gallery, optional photograph associations, raw/filtered sensor measurements, and 15-second refresh remain intact. Map configuration/rendering errors do not block sensor or gallery updates. This supersedes statements above describing route/map visualization as absent; comparison charts remain omitted. No firmware, measurement protocol, database, or networking changes were made for this restoration.

Restoration verification: 58 tests passed; JavaScript syntax checking passed; Docker rebuild completed and service is healthy. A headless Edge browser verified the live Google Maps renderer on localhost with the gallery and planning button present.


## 21. Host camera-to-gallery integration (implemented)

At the user's request, `ciclorota/camera.py` is now a host-side CLI with explicit `--dumpster-id` (or `--list`), `--source`, `--interval`, `--once`, `--preview`, `--base-url`, and `--output-dir` options. OpenCV is an optional `[camera]` dependency, imported lazily. No webcam opens at import or during API startup. The CLI checks the selected ID against real API records before opening the capture device; unknown IDs are rejected without creating records or measurements.

The default output is `ciclorota/dashboard/images/dumpsters/camera-<id>-<digest>.jpg`. A complete JPEG is encoded, flushed to a temporary file, and atomically replaced. The first successful capture associates the URL with only the selected dumpster through the existing photo PATCH endpoint. Subsequent captures replace the latest file every five seconds by default. Camera errors and Ctrl+C release resources. Preview is optional, not required for dashboard display.

Compose retains the SQLite volume and adds a read-only host-directory bind mount for `/app/ciclorota/dashboard/images/dumpsters`. OpenCV and USB camera access remain on the host, not in the API container. The frontend adds `_photo_v` to same-origin local photo URLs at each 15-second refresh; external/signed URLs remain unchanged. The map, route controls, sensor measurements, filtering, ingestion, and fill computation are preserved. Capture timestamps are printed separately, not misrepresented as sensor timestamps. No additional database migration, photo upload, computer vision, or automated ID association is introduced.

Generated camera JPEGs and temporary files are excluded from Git and image builds. Unassigned `ciclorota/data` captures are preserved and remain unexposed. Captured photos represent whatever the explicitly selected camera sees; the software does not verify that it is aimed at the intended dumpster. Running on a different host requires sharing/synchronizing the image directory; the API photo link does not upload bytes. Physical camera validation requires a registered real dumpster and an appropriately aimed camera; automated tests use fake capture devices and temporary records instead of enabling a webcam.

Camera integration verification: 68 tests passed, including fake-device capture/cleanup, unknown-ID rejection, safe atomic replacement, photo association isolation, and a browser check that overwritten image pixels refresh while sensor fields remain unchanged. Docker rebuilt successfully; live checks confirmed the read-only photo bind mount serves host updates immediately and API health is OK. The physical webcam was not activated. OpenCV imports successfully on the host.

## 22. Camera demo for dumpster 1 (2026-10-18)

At the user's explicit request, the standalone webcam script was replaced with the integrated capture CLI again. A dumpster with ID 1 was created through the live API with clearly labeled random demo location/calibration settings. No sensor measurements were fabricated. A real 640x480 webcam JPEG was captured, linked to record 1, and confirmed in the live browser, including an automatic image refresh. Continuous host capture runs at the default five-second interval; the gallery refreshes every fifteen seconds. Ten focused camera/cache-refresh regression tests passed. Demo calibration and location must be replaced before interpreting real container occupancy.
