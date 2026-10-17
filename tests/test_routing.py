from ciclorota.config import Settings
from ciclorota.routing import Coordinate, build_travel_matrix, haversine_m, optimize_tsp


def test_haversine_distance_is_symmetric_and_zero_at_same_point():
    a = Coordinate(-22.0, -47.9)
    b = Coordinate(-22.01, -47.88)
    assert haversine_m(a, a) == 0
    assert haversine_m(a, b) == haversine_m(b, a)


def test_fallback_travel_matrix_is_local_and_nonzero():
    settings = Settings(osrm_base_url="", fallback_road_factor=1.25, average_speed_kmh=30)
    matrix = build_travel_matrix([Coordinate(0, 0), Coordinate(0, 0.01)], settings)
    assert matrix.provider == "haversine_road_approximation"
    assert matrix.distances_m[0][1] > 1000
    assert matrix.durations_s[0][1] > 0


def test_exact_tsp_returns_best_deterministic_order_and_closed_distance():
    distances = [
        [0, 2, 9, 8],
        [2, 0, 6, 4],
        [9, 6, 0, 3],
        [8, 4, 3, 0],
    ]
    order, cost, algorithm = optimize_tsp(distances, [1, 2, 3])
    assert order == [1, 3, 2]
    assert cost == 18
    assert algorithm == "held_karp_exact"


def test_empty_route_and_heuristic_branch():
    assert optimize_tsp([[0]], []) == ([], 0.0, "empty")
    size = 15
    matrix = [[0 if i == j else abs(i - j) + 1 for j in range(size)] for i in range(size)]
    order, cost, algorithm = optimize_tsp(matrix, list(range(1, size)), max_exact_stops=4)
    assert sorted(order) == list(range(1, size))
    assert cost > 0
    assert algorithm == "nearest_neighbor_2opt"


def test_osrm_failure_uses_documented_local_fallback(monkeypatch):
    import ciclorota.routing as routing

    def unavailable(*args, **kwargs):
        raise OSError("routing service unavailable")

    monkeypatch.setattr(routing, "urlopen", unavailable)
    settings = Settings(
        osrm_base_url="http://127.0.0.1:5000",
        osrm_timeout_seconds=0.01,
        fallback_road_factor=1.25,
        average_speed_kmh=30,
    )
    result = build_travel_matrix([Coordinate(-22, -47), Coordinate(-22.01, -47.01)], settings)
    assert result.provider == "haversine_road_approximation"
    assert "OSRM unavailable" in result.warning
