"""API request validation models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import uuid4
from urllib.parse import urlsplit
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def validate_image_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    try:
        url = urlsplit(value)
        # Accessing port also validates malformed ports.
        url.port
        if url.scheme in ("http", "https") and url.hostname and not url.username and not url.password:
            if any(char.isspace() for char in value) or "\\" in value:
                raise ValueError("Invalid photo URL")
            return value
    except ValueError:
        pass
    if (re.fullmatch(r"/dashboard/images/dumpsters/[A-Za-z0-9_./-]+\.(?:jpg|jpeg|png|webp|avif|gif)", value, re.IGNORECASE)
            and all(part not in (".", "..", "") for part in value.split("/")[1:])):
        return value
    raise ValueError("Use an HTTP(S) image URL or /dashboard/images/dumpsters/photo.jpg")


class DumpsterImageUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    image_url: Annotated[str | None, Field(max_length=2048)]
    validate_photo = field_validator("image_url")(validate_image_url)


class DumpsterCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    address: Annotated[str | None, Field(min_length=5, max_length=300)] = None
    latitude: Annotated[float | None, Field(ge=-90, le=90)] = None
    longitude: Annotated[float | None, Field(ge=-180, le=180)] = None
    empty_distance_cm: Annotated[float, Field(gt=0, le=400)]
    full_distance_cm: Annotated[float, Field(gt=0, le=400)]
    fill_threshold_percent: Annotated[float | None, Field(ge=0, le=100)] = None
    daily_fill_rate_percent: Annotated[float, Field(ge=0, le=100)] = 0.0
    baseline_order: Annotated[int, Field(ge=0, le=100000)] = 0
    image_url: Annotated[str | None, Field(max_length=2048)] = None
    validate_photo = field_validator("image_url")(validate_image_url)

    @model_validator(mode="after")
    def location_and_calibration_are_valid(self) -> "DumpsterCreate":
        has_both_coordinates = self.latitude is not None and self.longitude is not None
        has_partial_coordinates = (self.latitude is None) != (self.longitude is None)
        if self.address and (has_both_coordinates or has_partial_coordinates):
            raise ValueError("Provide either a street address or coordinates, not both")
        if not self.address and not has_both_coordinates:
            raise ValueError("Provide a street address or both latitude and longitude")
        if self.empty_distance_cm <= self.full_distance_cm:
            raise ValueError("empty_distance_cm must be greater than full_distance_cm")
        return self


class MeasurementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measurement_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=80)
    dumpster_id: Annotated[str, Field(min_length=1, max_length=64)]
    device_id: Annotated[str | None, Field(max_length=80)] = None
    distance_cm: Annotated[float, Field(gt=0, le=400)]
    raw_distance_cm: Annotated[float | None, Field(gt=0, le=400)] = None
    fill_percentage: Annotated[float | None, Field(ge=0, le=100)] = None
    measured_at: datetime

    @field_validator("measured_at")
    @classmethod
    def timestamp_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("measured_at must include a timezone offset")
        return value


class RoutePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_date: date | None = None
    depot_latitude: Annotated[float, Field(ge=-90, le=90)] = -22.017
    depot_longitude: Annotated[float, Field(ge=-180, le=180)] = -47.895
