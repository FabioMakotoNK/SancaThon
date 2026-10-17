"""Road-distance providers and deterministic single-truck TSP optimization."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen

from .config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Coordinate:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class TravelMatrix:
    distances_m: list[list[float]]
    durations_s: list[list[float]]
    provider: str
    warning: str | None = None


def haversine_m(a: Coordinate, b: Coordinate) -> float:
    radius = 6_371_000.0
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(b.longitude - a.longitude)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(value)))


def fallback_matrix(locations: list[Coordinate], settings: Settings, warning: str | None = None) -> TravelMatrix:
    n = len(locations)
    distances = [[0.0] * n for _ in range(n)]
    durations = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            road_distance = haversine_m(locations[i], locations[j]) * settings.fallback_road_factor
            distances[i][j] = road_distance
            durations[i][j] = road_distance / (settings.average_speed_kmh * 1000 / 3600)
    return TravelMatrix(distances, durations, "haversine_road_approximation", warning)


def osrm_matrix(locations: list[Coordinate], settings: Settings) -> TravelMatrix:
    if not settings.osrm_base_url:
        raise ValueError("OSRM URL is not configured")
    coordinates = ";".join(f"{p.longitude:.6f},{p.latitude:.6f}" for p in locations)
    url = f"{settings.osrm_base_url}/table/v1/driving/{coordinates}?annotations=distance,duration"
    with urlopen(url, timeout=settings.osrm_timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))
    if body.get("code") != "Ok":
        raise ValueError(f"OSRM returned status {body.get('code', 'unknown')}")
    distances = body.get("distances")
    durations = body.get("durations")
    expected = len(locations)
    if not isinstance(distances, list) or not isinstance(durations, list):
        raise ValueError("OSRM response did not include distance and duration matrices")
    if len(distances) != expected or len(durations) != expected:
        raise ValueError("OSRM matrix dimensions do not match the requested locations")
    if any(len(row) != expected or any(v is None for v in row) for row in distances + durations):
        raise ValueError("OSRM returned unreachable or incomplete location pairs")
    return TravelMatrix(distances, durations, "OSRM")


def build_travel_matrix(locations: list[Coordinate], settings: Settings) -> TravelMatrix:
    if settings.osrm_base_url and len(locations) > 1:
        try:
            return osrm_matrix(locations, settings)
        except (OSError, ValueError, URLError, TimeoutError) as error:
            logger.warning("OSRM unavailable; using local distance approximation: %s", error)
            return fallback_matrix(locations, settings, f"OSRM unavailable ({error}); approximate distances used")
    return fallback_matrix(locations, settings)


def _path_cost(matrix: list[list[float]], path: tuple[int, ...]) -> float:
    if not path:
        return 0.0
    return matrix[0][path[0]] + sum(matrix[path[i]][path[i + 1]] for i in range(len(path) - 1)) + matrix[path[-1]][0]


def optimize_tsp(
    distances_m: list[list[float]],
    stop_indices: list[int],
    *,
    max_exact_stops: int = 12,
) -> tuple[list[int], float, str]:
    """Return an optimal order for up to max_exact_stops, then nearest-neighbor plus 2-opt."""
    stops = list(dict.fromkeys(stop_indices))
    if any(index <= 0 or index >= len(distances_m) for index in stops):
        raise ValueError("Stop indices must refer to non-depot matrix entries")
    if not stops:
        return [], 0.0, "empty"
    if len(stops) <= max_exact_stops:
        costs: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {}
        for offset, node in enumerate(stops):
            costs[(1 << offset, offset)] = (distances_m[0][node], (node,))
        for mask in range(1, 1 << len(stops)):
            for last in range(len(stops)):
                state = costs.get((mask, last))
                if state is None:
                    continue
                cost, path = state
                for nxt, node in enumerate(stops):
                    if mask & (1 << nxt):
                        continue
                    key = (mask | (1 << nxt), nxt)
                    candidate = (cost + distances_m[stops[last]][node], path + (node,))
                    existing = costs.get(key)
                    if existing is None or candidate < existing:
                        costs[key] = candidate
        full = (1 << len(stops)) - 1
        best = min(
            (cost + distances_m[stops[last]][0], path)
            for (mask, last), (cost, path) in costs.items()
            if mask == full
        )
        return list(best[1]), best[0], "held_karp_exact"

    remaining = set(stops)
    path: list[int] = []
    current = 0
    while remaining:
        next_node = min(remaining, key=lambda node: (distances_m[current][node], node))
        path.append(next_node)
        remaining.remove(next_node)
        current = next_node
    improved = True
    while improved:
        improved = False
        for left in range(len(path) - 1):
            for right in range(left + 1, len(path)):
                candidate = path[:left] + list(reversed(path[left : right + 1])) + path[right + 1 :]
                if _path_cost(distances_m, tuple(candidate)) + 1e-9 < _path_cost(distances_m, tuple(path)):
                    path = candidate
                    improved = True
                    break
            if improved:
                break
    return path, _path_cost(distances_m, tuple(path)), "nearest_neighbor_2opt"
