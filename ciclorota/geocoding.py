"""Google Maps Platform address lookup with persistent result caching."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import google_api_key_status
from .db import Database

logger = logging.getLogger("ciclorota.geocoding")


@dataclass(frozen=True)
class GeocodedAddress:
    latitude: float
    longitude: float
    display_name: str


class AddressNotFound(Exception):
    """No provider result matched the submitted street address."""


class GeocodingError(Exception):
    """The provider could not return a valid address result."""


class GoogleMapsGeocoder:
    """Resolve submitted addresses with the Google Geocoding API.

    Successful lookups are cached in SQLite so restarting the API does not
    repeat provider requests. The API key is only used by this backend class
    and is never returned in API responses or included in application logs.
    """

    DEFAULT_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"

    def __init__(
        self,
        database: Database,
        api_key: str,
        timeout_seconds: float = 5.0,
        endpoint: str = DEFAULT_ENDPOINT,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("Google Geocoding API endpoint must use HTTPS")
        if timeout_seconds <= 0:
            raise ValueError("Geocoder timeout must be positive")
        self.database = database
        self.api_key = api_key.strip() if google_api_key_status(api_key) == "provided" else ""
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def geocode(self, address: str) -> GeocodedAddress:
        query = " ".join(address.split())
        if not query:
            raise AddressNotFound("Enter a street address to geocode")

        cache_key = hashlib.sha256(
            (self.endpoint + "\0" + query.casefold()).encode("utf-8")
        ).hexdigest()
        cached = self.database.get_geocoding_cache(cache_key)
        if cached is not None:
            return GeocodedAddress(
                cached["latitude"], cached["longitude"], cached["display_name"]
            )
        if not self.api_key:
            raise GeocodingError("Google Geocoding API key is not configured")

        query_string = urlencode({"address": query, "key": self.api_key})
        request = Request(
            self.endpoint + "?" + query_string,
            headers={
                "Accept": "application/json",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                result: Any = json.loads(response.read().decode("utf-8"))
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            # Do not log the URL: it contains both the address and server key.
            logger.warning("Google address lookup failed (%s)", type(error).__name__)
            raise GeocodingError("Google address lookup service is unavailable") from error

        if not isinstance(result, dict):
            raise GeocodingError("Google address lookup returned an invalid response")
        status = result.get("status")
        if status == "ZERO_RESULTS":
            raise AddressNotFound("No map location matched that street address")
        if status != "OK":
            # Google's error_message can include request details; keep responses
            # generic so the API key and submitted address stay private.
            logger.warning("Google Geocoding API returned status %s", status or "unknown")
            raise GeocodingError("Google address lookup service could not resolve the address")

        results = result.get("results")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            raise GeocodingError("Google address lookup returned an invalid location")

        try:
            location = results[0]["geometry"]["location"]
            latitude = float(location["lat"])
            longitude = float(location["lng"])
            display_name = str(results[0].get("formatted_address") or query).strip()
        except (KeyError, TypeError, ValueError) as error:
            raise GeocodingError("Google address lookup returned an invalid location") from error

        if (
            not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
            or not display_name
        ):
            raise GeocodingError("Google address lookup returned an invalid location")

        self.database.store_geocoding_cache(
            cache_key, latitude, longitude, display_name
        )
        return GeocodedAddress(latitude, longitude, display_name)
