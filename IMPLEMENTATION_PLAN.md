# CicloRota MVP implementation plan

The repository started with project guidance only. This plan records the implementation sequence and completion evidence.

1. [x] Inspect the repository and record the chosen MVP architecture.
2. [x] Implement reusable sensing logic: range validation, outlier rejection, Kalman filtering, and per-dumpster fill calibration.
3. [x] Implement ESP32/HC-SR04 firmware with Wi-Fi recovery, timestamped HTTP posts, bounded retries, and configurable credentials/pins.
4. [x] Implement the Python API, SQLite persistence, multiple-dumpster state, freshness reporting, and validation.
5. [x] Implement fixed-weekday collection planning, overflow-aware stop selection, OSRM integration with a local fallback, and route/cost estimates.
6. [x] Implement the monitoring dashboard and realistic HTTP simulator.
7. [x] Add automated unit, API, routing, and firmware-logic tests; run them and fix failures.
8. [x] Document setup, configuration, operation, test results, and hardware/external-service validation still required.

## Architecture choices

- Python 3.11+, FastAPI, Pydantic, SQLite, and a static HTML/CSS/JavaScript dashboard.
- PlatformIO with Arduino framework for ESP32 firmware. Credentials and deployment settings live in an untracked secrets header.
- One ESP32-side distance Kalman filter; the server recomputes the calibrated fill estimate from the reported filtered distance and stores both the estimate and raw distance.
- Collection days default to Monday and Thursday and are configurable. Planning accepts only those weekdays and never changes a dispatch date.
- OSRM is optional. When unavailable, the backend uses a documented, approximate haversine road-distance model so local demonstrations remain self-contained.
- A deterministic local TSP solver provides routing without an optimization service or dependency. Google Maps Platform supplies the dashboard map and address geocoding; optional OSRM supplies road-network distances. Fuel, emissions, and cost are estimates controlled by configuration.

9. [x] Replace dashboard coordinate fields with street-address entry and geocode each user-submitted address server-side.
10. [x] Store entered and matched addresses with resolved coordinates; cache successful geocodes and migrate existing SQLite databases.
11. [x] Replace the schematic dashboard plot with an interactive Google Map of all dumpster locations, fill/health markers, route overlay, and 15-second data refresh.
12. [x] Add tests for address registration, Google Geocoding API success/cache/failure, database migration, and map dashboard assets.
13. [x] Replace the previous geocoding and map providers with Google Maps Platform; keep browser and server API keys separate; use Advanced Markers and a configurable map ID; document key restrictions, billing, and deployment requirements.
14. [x] Diagnose local Google Maps key errors, reject documented placeholder keys, return a normal empty latest-route response, add a favicon, and verify the running local API plus automated tests.
15. [x] Localize the complete dashboard in Brazilian Portuguese, including dynamic status/route/error messages, number and date formatting, accessibility text, and Google Maps language/region settings.


## ESP32 integration follow-up (2026-10-17)

16. [x] Compare the pull with repository history and trace the pulled CSV/TCP sketch against API, SQLite, and dashboard behavior. The pull is `be6b84d` on `a121b80`.
17. [x] Preserve the pulled sensor library call and GPIO 4/5 configuration; replace TCP CSV with timestamped HTTP JSON to the existing FastAPI endpoint and shared Kalman pipeline.
18. [x] Align both firmware targets on the same distance-based request. Leave fill calculation to the backend using that dumpster calibration; add API persistence, retrieval, validation, and firmware-contract tests.
19. [x] Document Arduino and PlatformIO setup, LAN endpoint configuration, protocol fields, legacy TCP logger status, and physical validation limits in the root README, component guides, and CLAUDE.md.
20. [ ] Execute the full automated suite and firmware toolchain build. Python source compilation passed. pytest and native g++ invocations failed before process launch with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. Arduino CLI, PlatformIO, and physical hardware are unavailable.
