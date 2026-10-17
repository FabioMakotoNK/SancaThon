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
- A deterministic local TSP solver provides routing without an optimization service or dependency. Fuel, emissions, and cost are estimates controlled by configuration.
