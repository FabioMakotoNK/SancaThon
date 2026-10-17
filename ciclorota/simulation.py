"""Synthetic multi-dumpster sensor generator that posts through the real HTTP API."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .sensing import Calibration, SensorProcessor

DEMO_SITES = [
    {
        "id": "D001", "name": "Food processing", "latitude": -22.0000, "longitude": -47.9000,
        "empty_distance_cm": 150.0, "full_distance_cm": 25.0, "fill_threshold_percent": 70.0,
        "daily_fill_rate_percent": 8.0, "baseline_order": 1, "start_fill": 55.0, "growth": 7.0,
    },
    {
        "id": "D002", "name": "Metal workshop", "latitude": -22.0100, "longitude": -47.8750,
        "empty_distance_cm": 165.0, "full_distance_cm": 30.0, "fill_threshold_percent": 75.0,
        "daily_fill_rate_percent": 5.0, "baseline_order": 2, "start_fill": 50.0, "growth": 5.0,
    },
    {
        "id": "D003", "name": "Manufacturing plant", "latitude": -22.0320, "longitude": -47.8900,
        "empty_distance_cm": 140.0, "full_distance_cm": 20.0, "fill_threshold_percent": 80.0,
        "daily_fill_rate_percent": 3.0, "baseline_order": 3, "start_fill": 84.0, "growth": 2.0,
    },
    {
        "id": "D004", "name": "Food distribution", "latitude": -21.9870, "longitude": -47.8780,
        "empty_distance_cm": 155.0, "full_distance_cm": 25.0, "fill_threshold_percent": 70.0,
        "daily_fill_rate_percent": 12.0, "baseline_order": 4, "start_fill": 25.0, "growth": 10.0,
    },
]


def request_json(base_url: str, path: str, payload: dict | None = None) -> dict | list:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="GET" if body is None else "POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def populate_demo(base_url: str, *, cycles: int = 4, seed: int = 26, interval_seconds: float = 0.0) -> dict:
    """Create demo dumpsters if absent, send noisy sensor bursts, then plan a route."""
    existing = request_json(base_url, "/api/dumpsters")
    existing_ids = {row["id"] for row in existing}
    for site in DEMO_SITES:
        if site["id"] not in existing_ids:
            create = {key: value for key, value in site.items() if key not in {"start_fill", "growth"}}
            try:
                request_json(base_url, "/api/dumpsters", create)
            except HTTPError as error:
                if error.code != 409:
                    raise
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    for cycle in range(cycles):
        for site_index, site in enumerate(DEMO_SITES):
            fill = min(96.0, site["start_fill"] + cycle * site["growth"])
            calibration = Calibration(site["empty_distance_cm"], site["full_distance_cm"])
            true_distance = calibration.empty_distance_cm - (
                fill / 100.0 * (calibration.empty_distance_cm - calibration.full_distance_cm)
            )
            processor = SensorProcessor(calibration)
            last_reading = None
            last_raw = None
            for sample_index in range(5):
                raw = true_distance + rng.gauss(0.0, 1.5)
                if cycle == 1 and site_index == 0 and sample_index == 2:
                    raw += 45.0  # One transient echo, rejected by the median window.
                last_raw = max(2.0, min(400.0, raw))
                candidate = processor.process(last_raw)
                if candidate is not None:
                    last_reading = candidate
            if last_reading is None:
                continue
            measured_at = now - timedelta(days=(cycles - cycle - 1))
            request_json(
                base_url,
                "/api/measurements",
                {
                    "measurement_id": str(uuid4()),
                    "dumpster_id": site["id"],
                    "device_id": "sim-" + site["id"],
                    "raw_distance_cm": round(last_raw, 2),
                    "distance_cm": last_reading.filtered_distance_cm,
                    "fill_percentage": last_reading.fill_percentage,
                    "measured_at": measured_at.isoformat(),
                },
            )
        if interval_seconds > 0 and cycle + 1 < cycles:
            time.sleep(interval_seconds)
    route = request_json(base_url, "/api/routes/plan", {})
    return route


def main() -> None:
    parser = argparse.ArgumentParser(description="Send synthetic CicloRota measurements to a running API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--cycles", type=int, default=4, help="Number of simulated readings per dumpster")
    parser.add_argument("--seed", type=int, default=26, help="Random seed for repeatable sensor noise")
    parser.add_argument("--interval", type=float, default=0.0, help="Pause between simulated collection cycles")
    args = parser.parse_args()
    if args.cycles < 1 or args.cycles > 100:
        parser.error("--cycles must be between 1 and 100")
    if args.interval < 0:
        parser.error("--interval cannot be negative")
    try:
        route = populate_demo(args.base_url, cycles=args.cycles, seed=args.seed, interval_seconds=args.interval)
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        print(f"Simulation failed: {error}", file=sys.stderr)
        print("Start the API first: uvicorn ciclorota.api:app --reload", file=sys.stderr)
        raise SystemExit(1) from error
    print("Synthetic measurements posted; fixed collection date: " + route["collection_date"])
    print("Route provider: " + route["provider"])
    print("Selected stops: " + ", ".join(stop["dumpster_id"] for stop in route["route"]))
    print("Estimated optimized distance: %.2f km" % route["optimized"]["distance_km"])
    if route["provider_warning"]:
        print("Routing note: " + route["provider_warning"])


if __name__ == "__main__":
    main()
