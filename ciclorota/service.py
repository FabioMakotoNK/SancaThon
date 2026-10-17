"""Collection policy, freshness classification, and route-plan construction."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo
from uuid import uuid4

from .config import Settings
from .db import Database
from .routing import Coordinate, build_travel_matrix, optimize_tsp


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Timestamp must be timezone aware")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def local_today(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def next_collection_date(after: date, weekdays: tuple[int, ...]) -> date:
    for offset in range(1, 8):
        candidate = after + timedelta(days=offset)
        if candidate.weekday() in weekdays:
            return candidate
    raise ValueError("No collection weekday configured")


def measurement_age_seconds(measured_at: str, now: datetime) -> float:
    stamp = datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
    return max(0.0, (now - stamp.astimezone(timezone.utc)).total_seconds())


def classify_freshness(measured_at: str | None, settings: Settings, now: datetime) -> tuple[str, float | None]:
    if measured_at is None:
        return "no_data", None
    age = measurement_age_seconds(measured_at, now)
    if age > settings.offline_after_seconds:
        return "offline", age
    if age > settings.stale_after_seconds:
        return "stale", age
    return "normal", age


def present_dumpster(row: dict[str, Any], settings: Settings, now: datetime) -> dict[str, Any]:
    status, age = classify_freshness(row.get("latest_measured_at"), settings, now)
    latest = None
    if row.get("latest_measurement_id") is not None:
        latest = {
            "measurement_id": row["latest_measurement_id"],
            "device_id": row["latest_device_id"],
            "raw_distance_cm": row["latest_raw_distance_cm"],
            "distance_cm": row["latest_distance_cm"],
            "fill_percentage": row["latest_fill_percentage"],
            "measured_at": row["latest_measured_at"],
            "received_at": row["latest_received_at"],
            "age_seconds": round(age or 0, 1),
        }
    return {
        "id": row["id"],
        "name": row["name"],
        "address": row.get("address"),
        "geocoded_label": row.get("geocoded_label"),
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "empty_distance_cm": row["empty_distance_cm"],
        "full_distance_cm": row["full_distance_cm"],
        "fill_threshold_percent": row["fill_threshold_percent"],
        "daily_fill_rate_percent": row["daily_fill_rate_percent"],
        "baseline_order": row["baseline_order"],
        "status": status,
        "last_seen_at": row["last_seen_at"],
        "latest": latest,
    }


def build_route_plan(
    database: Database,
    settings: Settings,
    *,
    collection_date: date,
    depot: Coordinate,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    rows = database.list_dumpsters()
    statuses = [present_dumpster(row, settings, now) for row in rows]
    horizon_days = max(0, (collection_date - now.astimezone(ZoneInfo(settings.timezone_name)).date()).days)
    decisions: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    baseline: list[dict[str, Any]] = []

    for item in statuses:
        latest = item["latest"]
        if latest is None:
            decisions.append({"dumpster_id": item["id"], "selected": False, "reason": "no valid measurement"})
            continue
        if item["status"] != "normal":
            decisions.append(
                {"dumpster_id": item["id"], "selected": False, "reason": f"{item['status']} measurement; manual review required"}
            )
            continue
        baseline.append(item)
        fill = float(latest["fill_percentage"])
        projected = min(100.0, fill + item["daily_fill_rate_percent"] * horizon_days)
        threshold = item["fill_threshold_percent"]
        if projected >= 100:
            reason = "projected overflow before the fixed collection date"
        elif fill >= threshold:
            reason = f"current fill {fill:.1f}% meets {threshold:.1f}% threshold"
        elif projected >= threshold:
            reason = f"projected fill {projected:.1f}% meets threshold by collection date"
        else:
            reason = f"projected fill {projected:.1f}% remains below {threshold:.1f}% threshold"
        selected = projected >= threshold
        decisions.append(
            {
                "dumpster_id": item["id"],
                "selected": selected,
                "reason": reason,
                "current_fill_percentage": fill,
                "projected_fill_percentage": round(projected, 2),
                "threshold_percent": threshold,
            }
        )
        if selected:
            eligible.append(item)

    all_locations = [depot] + [
        Coordinate(item["latitude"], item["longitude"]) for item in baseline
    ]
    matrix = build_travel_matrix(all_locations, settings)
    baseline_nodes = list(range(1, len(baseline) + 1))
    baseline_distance_m = _closed_route_distance(matrix.distances_m, baseline_nodes)
    baseline_duration_s = _closed_route_duration(matrix.durations_s, baseline_nodes)
    id_to_node = {item["id"]: index for index, item in enumerate(baseline, start=1)}
    selected_nodes = [id_to_node[item["id"]] for item in eligible]
    route_nodes, optimized_distance_m, algorithm = optimize_tsp(
        matrix.distances_m, selected_nodes, max_exact_stops=settings.max_exact_route_stops
    )
    optimized_duration_s = _closed_route_duration(matrix.durations_s, route_nodes)
    ordered = [baseline[node - 1] for node in route_nodes]
    optimized_km = optimized_distance_m / 1000
    baseline_km = baseline_distance_m / 1000

    def operating_metrics(km: float) -> dict[str, float]:
        liters = km * settings.fuel_liters_per_100km / 100
        return {
            "estimated_fuel_liters": round(liters, 2),
            "estimated_co2_kg": round(liters * settings.co2_kg_per_liter, 2),
            "estimated_fuel_cost_brl": round(liters * settings.fuel_cost_per_liter_brl, 2),
        }

    plan = {
        "route_id": str(uuid4()),
        "planned_at": iso_utc(now),
        "collection_date": collection_date.isoformat(),
        "fixed_collection_weekdays": settings.fixed_collection_weekdays,
        "schedule_changed": False,
        "depot": {"latitude": depot.latitude, "longitude": depot.longitude},
        "provider": matrix.provider,
        "provider_warning": matrix.warning,
        "algorithm": algorithm,
        "route": [
            {
                "sequence": index,
                "dumpster_id": item["id"],
                "name": item["name"],
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "fill_percentage": item["latest"]["fill_percentage"],
                "reason": next(d["reason"] for d in decisions if d["dumpster_id"] == item["id"]),
            }
            for index, item in enumerate(ordered, start=1)
        ],
        "decisions": decisions,
        "baseline": {
            "method": "all fresh dumpsters in configured baseline_order, returning to depot",
            "stop_count": len(baseline),
            "distance_km": round(baseline_km, 2),
            "duration_minutes": round(baseline_duration_s / 60, 1),
            **operating_metrics(baseline_km),
        },
        "optimized": {
            "stop_count": len(ordered),
            "distance_km": round(optimized_km, 2),
            "duration_minutes": round(optimized_duration_s / 60, 1),
            **operating_metrics(optimized_km),
        },
        "estimated_distance_saved_km": round(baseline_km - optimized_km, 2),
        "assumptions": {
            "fuel_liters_per_100km": settings.fuel_liters_per_100km,
            "fuel_cost_per_liter_brl": settings.fuel_cost_per_liter_brl,
            "co2_kg_per_liter": settings.co2_kg_per_liter,
            "fallback_road_factor": settings.fallback_road_factor,
            "average_speed_kmh_when_using_fallback": settings.average_speed_kmh,
            "environmental_and_cost_values_are_estimates": True,
        },
    }
    database.save_route_plan(plan["route_id"], plan["collection_date"], plan["planned_at"], plan)
    return plan


def _closed_route_distance(matrix: list[list[float]], nodes: list[int]) -> float:
    if not nodes:
        return 0.0
    return matrix[0][nodes[0]] + sum(matrix[nodes[i]][nodes[i + 1]] for i in range(len(nodes) - 1)) + matrix[nodes[-1]][0]


def _closed_route_duration(matrix: list[list[float]], nodes: list[int]) -> float:
    if not nodes:
        return 0.0
    return matrix[0][nodes[0]] + sum(matrix[nodes[i]][nodes[i + 1]] for i in range(len(nodes) - 1)) + matrix[nodes[-1]][0]
