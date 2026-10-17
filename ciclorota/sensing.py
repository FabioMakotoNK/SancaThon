"""Validated distance processing and per-dumpster fill calibration."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class Calibration:
    empty_distance_cm: float
    full_distance_cm: float

    def __post_init__(self) -> None:
        if not (0 < self.full_distance_cm < self.empty_distance_cm <= 400):
            raise ValueError("Calibration requires 0 < full distance < empty distance <= 400 cm")


def estimate_fill_percent(distance_cm: float, calibration: Calibration) -> float:
    if not math.isfinite(distance_cm) or distance_cm <= 0:
        raise ValueError("Distance must be a finite positive number")
    fill = 100.0 * (calibration.empty_distance_cm - distance_cm) / (
        calibration.empty_distance_cm - calibration.full_distance_cm
    )
    return round(min(100.0, max(0.0, fill)), 2)


class Kalman1D:
    """Small scalar Kalman filter suitable for slowly changing distance readings."""

    def __init__(self, process_noise: float = 0.08, measurement_noise: float = 4.0) -> None:
        if process_noise <= 0 or measurement_noise <= 0:
            raise ValueError("Kalman noise values must be positive")
        self.process_noise = process_noise
        self.measurement_noise = measurement_noise
        self.estimate: float | None = None
        self.error_estimate = 1.0

    def reset(self, measurement: float) -> float:
        self.estimate = measurement
        self.error_estimate = 1.0
        return measurement

    def update(self, measurement: float) -> float:
        if self.estimate is None:
            return self.reset(measurement)
        predicted_error = self.error_estimate + self.process_noise
        gain = predicted_error / (predicted_error + self.measurement_noise)
        self.estimate += gain * (measurement - self.estimate)
        self.error_estimate = (1.0 - gain) * predicted_error
        return self.estimate


@dataclass(frozen=True)
class ProcessedReading:
    raw_distance_cm: float
    filtered_distance_cm: float
    fill_percentage: float
    discontinuity_reset: bool = False


class SensorProcessor:
    """Reject invalid readings/spikes, smooth accepted distance, and apply calibration."""

    def __init__(
        self,
        calibration: Calibration,
        *,
        min_distance_cm: float = 2.0,
        max_distance_cm: float = 400.0,
        median_window: int = 3,
        discontinuity_cm: float = 30.0,
        confirmation_tolerance_cm: float = 10.0,
        confirmation_samples: int = 3,
    ) -> None:
        if median_window < 1 or confirmation_samples < 2:
            raise ValueError("Median window must be positive and discontinuity needs at least two samples")
        self.calibration = calibration
        self.min_distance_cm = min_distance_cm
        self.max_distance_cm = max_distance_cm
        self._samples: deque[float] = deque(maxlen=median_window)
        self._kalman = Kalman1D()
        self.discontinuity_cm = discontinuity_cm
        self.confirmation_tolerance_cm = confirmation_tolerance_cm
        self.confirmation_samples = confirmation_samples
        self._candidate: list[float] = []

    @property
    def filtered_distance_cm(self) -> float | None:
        return self._kalman.estimate

    def process(self, raw_distance_cm: float | None) -> ProcessedReading | None:
        if (
            raw_distance_cm is None
            or not math.isfinite(raw_distance_cm)
            or not self.min_distance_cm <= raw_distance_cm <= self.max_distance_cm
        ):
            return None
        self._samples.append(raw_distance_cm)
        measurement = float(median(self._samples))
        current = self._kalman.estimate
        reset = False
        if current is not None and abs(measurement - current) > self.discontinuity_cm:
            if not self._candidate or abs(measurement - median(self._candidate)) > self.confirmation_tolerance_cm:
                self._candidate = [measurement]
                return None
            self._candidate.append(measurement)
            if len(self._candidate) < self.confirmation_samples:
                return None
            measurement = float(median(self._candidate))
            self._kalman.reset(measurement)
            self._candidate.clear()
            reset = True
        else:
            self._candidate.clear()
            measurement = self._kalman.update(measurement)
        return ProcessedReading(
            raw_distance_cm=float(raw_distance_cm),
            filtered_distance_cm=round(measurement, 2),
            fill_percentage=estimate_fill_percent(measurement, self.calibration),
            discontinuity_reset=reset,
        )
