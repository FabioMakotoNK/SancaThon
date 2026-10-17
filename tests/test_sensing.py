import math

import pytest

from ciclorota.sensing import Calibration, Kalman1D, SensorProcessor, estimate_fill_percent


def test_calibration_formula_and_clamping():
    calibration = Calibration(empty_distance_cm=150, full_distance_cm=25)
    assert estimate_fill_percent(87.5, calibration) == 50.0
    assert estimate_fill_percent(200, calibration) == 0.0
    assert estimate_fill_percent(2, calibration) == 100.0


def test_bad_calibration_and_distance_are_rejected():
    with pytest.raises(ValueError):
        Calibration(empty_distance_cm=25, full_distance_cm=150)
    with pytest.raises(ValueError):
        estimate_fill_percent(math.nan, Calibration(150, 25))


def test_kalman_filter_smooths_measurement_noise():
    filter_ = Kalman1D()
    first = filter_.update(100)
    second = filter_.update(110)
    assert first == 100
    assert 100 < second < 110


def test_processor_rejects_timeout_and_invalid_ranges():
    processor = SensorProcessor(Calibration(150, 25))
    assert processor.process(None) is None
    assert processor.process(float("nan")) is None
    assert processor.process(1.0) is None
    assert processor.process(401.0) is None


def test_processor_rejects_single_echo_spike():
    processor = SensorProcessor(Calibration(150, 25))
    readings = [processor.process(value) for value in (100, 100, 100, 300, 100)]
    accepted = [reading for reading in readings if reading is not None]
    assert accepted
    assert abs(accepted[-1].filtered_distance_cm - 100) < 2


def test_sustained_step_resets_filter_after_confirmation():
    processor = SensorProcessor(Calibration(150, 25))
    for value in (100, 100, 100):
        processor.process(value)
    results = [processor.process(200) for _ in range(6)]
    confirmed = [reading for reading in results if reading is not None and reading.discontinuity_reset]
    assert confirmed
    assert confirmed[-1].filtered_distance_cm == pytest.approx(200)
