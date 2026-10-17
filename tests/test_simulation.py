from ciclorota.simulation import DEMO_SITES


def test_demo_sites_have_distinct_calibration_and_fixed_baseline_order():
    assert len(DEMO_SITES) >= 3
    assert len({site["id"] for site in DEMO_SITES}) == len(DEMO_SITES)
    assert [site["baseline_order"] for site in DEMO_SITES] == list(range(1, len(DEMO_SITES) + 1))
    assert len({site["empty_distance_cm"] for site in DEMO_SITES}) > 1
