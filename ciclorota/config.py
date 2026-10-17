"""Environment-backed configuration for the local MVP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


_WEEKDAYS = {
    "MONDAY": 0,
    "TUESDAY": 1,
    "WEDNESDAY": 2,
    "THURSDAY": 3,
    "FRIDAY": 4,
    "SATURDAY": 5,
    "SUNDAY": 6,
}


def parse_weekdays(value: str) -> tuple[int, ...]:
    names = [part.strip().upper() for part in value.split(",") if part.strip()]
    if not names:
        raise ValueError("At least one fixed collection weekday is required")
    unknown = [name for name in names if name not in _WEEKDAYS]
    if unknown:
        raise ValueError(f"Unknown collection weekday(s): {', '.join(unknown)}")
    return tuple(sorted({_WEEKDAYS[name] for name in names}))


def weekday_names(days: tuple[int, ...]) -> list[str]:
    inverse = {number: name.title() for name, number in _WEEKDAYS.items()}
    return [inverse[day] for day in days]


def google_api_key_status(value: str) -> str:
    """Recognize example values without claiming to validate a Google key."""
    key = value.strip()
    if not key:
        return "missing"
    if key.lower().startswith("your-") or key.upper() == "YOUR_API_KEY" or key == "AIza...":
        return "placeholder"
    return "provided"


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path("data/ciclorota.sqlite3")
    fixed_collection_weekdays: tuple[int, ...] = (0, 3)
    stale_after_seconds: int = 6 * 60 * 60
    offline_after_seconds: int = 24 * 60 * 60
    timezone_name: str = "America/Sao_Paulo"
    default_fill_threshold_percent: float = 75.0
    osrm_base_url: str = ""
    osrm_timeout_seconds: float = 2.0
    average_speed_kmh: float = 30.0
    fallback_road_factor: float = 1.25
    fuel_liters_per_100km: float = 18.0
    fuel_cost_per_liter_brl: float = 6.20
    co2_kg_per_liter: float = 2.68
    max_exact_route_stops: int = 12
    google_maps_browser_key: str = ""
    google_geocoding_api_key: str = ""
    google_maps_map_id: str = "DEMO_MAP_ID"
    geocoder_timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "Settings":
        weekdays = parse_weekdays(os.getenv("CICLOROTA_FIXED_DAYS", "MONDAY,THURSDAY"))
        settings = cls(
            database_path=Path(os.getenv("CICLOROTA_DB_PATH", "data/ciclorota.sqlite3")),
            fixed_collection_weekdays=weekdays,
            stale_after_seconds=int(os.getenv("CICLOROTA_STALE_SECONDS", str(6 * 60 * 60))),
            offline_after_seconds=int(os.getenv("CICLOROTA_OFFLINE_SECONDS", str(24 * 60 * 60))),
            timezone_name=os.getenv("CICLOROTA_TIMEZONE", "America/Sao_Paulo"),
            default_fill_threshold_percent=float(os.getenv("CICLOROTA_FILL_THRESHOLD", "75")),
            osrm_base_url=os.getenv("CICLOROTA_OSRM_URL", "").rstrip("/"),
            osrm_timeout_seconds=float(os.getenv("CICLOROTA_OSRM_TIMEOUT", "2")),
            average_speed_kmh=float(os.getenv("CICLOROTA_AVERAGE_SPEED_KMH", "30")),
            fallback_road_factor=float(os.getenv("CICLOROTA_FALLBACK_ROAD_FACTOR", "1.25")),
            fuel_liters_per_100km=float(os.getenv("CICLOROTA_FUEL_L_PER_100KM", "18")),
            fuel_cost_per_liter_brl=float(os.getenv("CICLOROTA_FUEL_COST_BRL_PER_L", "6.20")),
            co2_kg_per_liter=float(os.getenv("CICLOROTA_CO2_KG_PER_L", "2.68")),
            max_exact_route_stops=int(os.getenv("CICLOROTA_MAX_EXACT_STOPS", "12")),
            google_maps_browser_key=os.getenv("CICLOROTA_GOOGLE_MAPS_BROWSER_KEY", "").strip(),
            google_geocoding_api_key=os.getenv("CICLOROTA_GOOGLE_GEOCODING_API_KEY", "").strip(),
            google_maps_map_id=os.getenv("CICLOROTA_GOOGLE_MAP_ID", "DEMO_MAP_ID").strip(),
            geocoder_timeout_seconds=float(os.getenv("CICLOROTA_GEOCODER_TIMEOUT", "5")),
        )
        if settings.stale_after_seconds <= 0 or settings.offline_after_seconds < settings.stale_after_seconds:
            raise ValueError("Offline age must be greater than or equal to a positive stale age")
        if not 0 <= settings.default_fill_threshold_percent <= 100:
            raise ValueError("Default fill threshold must be between 0 and 100")
        try:
            ZoneInfo(settings.timezone_name)
        except Exception as error:
            raise ValueError(f"Unknown timezone: {settings.timezone_name}") from error
        if settings.average_speed_kmh <= 0 or settings.fallback_road_factor < 1:
            raise ValueError("Routing speed must be positive and road factor must be at least one")
        if settings.geocoder_timeout_seconds <= 0:
            raise ValueError("Geocoder timeout must be positive")
        if not settings.google_maps_map_id:
            raise ValueError("Google Maps map ID cannot be empty")
        return settings
