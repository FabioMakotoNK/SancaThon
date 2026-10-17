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

**Problem.** Industrial waste collection often uses fixed schedules and fixed routes, even when some dumpsters do not need emptying. This can cause unnecessary stops and travel, low truck utilization, wasted fuel, higher operating costs, and increased CO₂ emissions.

**Target users.** Industrial facilities that generate substantial waste (particularly food processing, metalworking, and manufacturing), logistics and sustainability managers, operations teams, and outsourced industrial waste-collection providers.

**Goal.** Create an IoT-assisted waste-collection system that measures estimated dumpster fill levels, sends the readings to a centralized Python service, selects necessary collection stops, and computes a more efficient route. A dashboard should make fill levels, recommended stops, routes, and operational/environmental indicators visible.

**Important operational rule (clarified by the team):** **Collection days/times remain fixed. Only which dumpsters are visited and the route/order of stops change dynamically** based on current measurements and collection constraints. Earlier project descriptions mention dynamically scheduling collections; interpret that as *dynamic stop and route selection within the fixed collection schedule*, not as rescheduling truck dispatch dates.

## 2. Confirmed design decisions

The team has described this intended end-to-end design:

1. Deploy **ESP32 microcontrollers** with **HC-SR04 ultrasonic sensors** at waste dumpsters.
2. Measure the distance from the sensor to the waste surface and derive an **estimated fill level**.
3. Apply a **Kalman filter** to reduce noise in ultrasonic measurements. The precise placement of the filter in the software has not yet been confirmed; ESP32-side filtering is a practical default.
4. Send measurements over **Wi-Fi using HTTP** to a **Python-based server**.
5. Aggregate readings from **multiple dumpsters** on the server; track their latest reported occupancy and data freshness.
6. Determine which dumpsters warrant collection on the next fixed collection run.
7. Calculate an efficient collection route using **mapping/routing algorithms** and the selected stops.
8. Present the relevant information in a **monitoring dashboard**.

**Not yet specified or verified:** server framework, database, HTTP endpoint paths, payload schema, map provider, optimization library, dashboard technology, upload frequency, sensor sampling frequency, threshold values, vehicle fleet configuration, container dimensions, deployment environment, and current implementation progress. Do not present suggestions below as decided facts.

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
│ Dumpster status · Stops · Optimized routes  │
│ Distance/cost/CO₂ metrics and comparisons   │
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
Raw readings → validity checks → outlier handling → Kalman estimate
             → calibrated estimated fill percentage → HTTP message
```

- Validate timeouts, non-echoes, physically impossible distances, and transient spikes **before** interpreting a reading.
- A one-dimensional Kalman filter is a reasonable smoothing approach; choose/tune process noise and measurement noise empirically. A median-based spike rejection stage can help with large outliers.
- Recognize genuine step changes (e.g., when a dumpster is emptied). A slow filter must not incorrectly mask a persistent real change. Consider resetting/reinitializing the estimate after a confirmed discontinuity.
- If feasible, retain a way to inspect raw and filtered measurements during testing; this is useful for filter tuning and debugging.

## 5. Connectivity and server ingestion

**Confirmed transport:** ESP32 → Wi-Fi → HTTP → Python server. Multiple ESP32 devices may report independently to the same service when network connectivity is available.

**Illustrative API contract — proposal only (not an implemented or agreed endpoint):**

```http
POST /api/measurements HTTP/1.1
Content-Type: application/json
```

```json
{
  "dumpster_id": "D001",
  "distance_cm": 42.5,
  "fill_percentage": 78.3,
  "measured_at": "2026-10-17T10:30:00-03:00"
}
```

Suggested additional metadata where useful: device ID, calibration/version, sensor quality/validity, raw reading, battery/power status, and unique measurement ID.

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

Potential model: **Traveling Salesperson Problem (TSP)** for one truck with fixed eligible stops; **Vehicle Routing Problem (VRP)** for multiple vehicles, capacity constraints, or richer dispatch requirements. **Google OR-Tools** is a possible solver; **OpenStreetMap + OSRM** are possible road-network sources. These are **technology recommendations, not a chosen stack**.

**Optimization objective:** Reduce unnecessary road travel, time, and cost *subject to* acceptable service quality, overflow prevention, and vehicle constraints. Minimizing distance alone is insufficient if it causes missed urgent collections.

**Scope note:** Fill level alone is a limited proxy for waste amount. If the model uses vehicle load, label estimates and assumptions explicitly. Do not assume all waste types have the same density.

## 7. Dashboard and intended outputs

The project calls for a dashboard showing, where data are available:

- Dumpsters, locations, latest estimated fill levels, and last-report timestamps.
- Device/measurement health (offline, stale, invalid, or normal).
- Which dumpsters were selected for the upcoming fixed collection run and why.
- The planned route, collection stops, distance, and estimated duration.
- Comparisons against fixed-route baseline: distance traveled, stop counts, estimated fuel use, estimated CO₂, operating cost, and potential ROI.

Avoid portraying unmeasured savings or emissions reductions as demonstrated facts. Document conversion factors and assumptions whenever estimating costs or emissions.

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
- End-to-end demo: change a physical dumpster level → ingest an updated estimate → observe changed stop selection/route on the dashboard.

## 9. MVP roadmap (planned work, not a completion report)

1. **Sensing:** Wire and calibrate HC-SR04 + ESP32; validate readings; implement and tune the Kalman filter.
2. **Transmission:** Join Wi-Fi and POST measurements to the Python service; test failures and retries.
3. **Storage and state:** Persist multiple dumpsters and expose current, timestamped readings.
4. **Stop-selection rules:** Implement configurable occupancy thresholds plus stale-data and urgency handling.
5. **Route optimization:** Add road-distance/time calculations, then a TSP/VRP approach as complexity requires.
6. **Dashboard:** Visualize dumpsters, route, stop decisions, and measurement quality.
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
7. **Favor an end-to-end working demo over premature complexity.** Establish reliable sensing → server ingestion → stop selection → route visualization first.
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
