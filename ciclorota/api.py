"""FastAPI application for measurements, dumpster state, and collection routes."""

from __future__ import annotations

import logging
from datetime import timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, google_api_key_status, weekday_names
from .db import Database
from .geocoding import AddressNotFound, GeocodingError, GoogleMapsGeocoder
from .routing import Coordinate
from .schemas import DumpsterCreate, DumpsterImageUpdate, MeasurementCreate, RoutePlanRequest
from .service import build_route_plan, iso_utc, local_today, next_collection_date, present_dumpster, utc_now

logger = logging.getLogger("ciclorota")


def create_app(
    settings: Settings | None = None,
    geocoder: GoogleMapsGeocoder | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_path)
    database.initialize()
    app = FastAPI(title="CicloRota API", version="0.1.0")
    app.state.settings = settings
    app.state.database = database
    app.state.geocoder = geocoder or GoogleMapsGeocoder(
        database,
        api_key=settings.google_geocoding_api_key,
        timeout_seconds=settings.geocoder_timeout_seconds,
    )
    dashboard_dir = Path(__file__).parent / "dashboard"

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "ciclorota", "database": "connected"}

    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        browser_key_status = google_api_key_status(settings.google_maps_browser_key)
        return {
            "fixed_collection_weekdays": weekday_names(settings.fixed_collection_weekdays),
            "default_fill_threshold_percent": settings.default_fill_threshold_percent,
            "next_collection_date": next_collection_date(local_today(settings.timezone_name), settings.fixed_collection_weekdays).isoformat(),
            "stale_after_seconds": settings.stale_after_seconds,
            "offline_after_seconds": settings.offline_after_seconds,
            "osrm_configured": bool(settings.osrm_base_url),
            "google_maps_browser_key": (
                settings.google_maps_browser_key if browser_key_status == "provided" else ""
            ),
            "google_maps_key_status": browser_key_status,
            "google_maps_map_id": settings.google_maps_map_id,
        }

    @app.post("/api/dumpsters", status_code=201)
    def create_dumpster(payload: DumpsterCreate) -> dict[str, Any]:
        item = payload.model_dump()
        if database.get_dumpster(item["id"]):
            raise HTTPException(status_code=409, detail="Dumpster ID already exists")
        if item["address"]:
            try:
                location = app.state.geocoder.geocode(item["address"])
            except AddressNotFound as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            except GeocodingError as error:
                logger.warning("Could not geocode dumpster %s: %s", item["id"], error)
                raise HTTPException(status_code=502, detail=str(error)) from error
            item["latitude"] = location.latitude
            item["longitude"] = location.longitude
            item["geocoded_label"] = location.display_name
        else:
            item["geocoded_label"] = None
        if item["fill_threshold_percent"] is None:
            item["fill_threshold_percent"] = settings.default_fill_threshold_percent
        try:
            database.create_dumpster(item, iso_utc(utc_now()))
        except Exception:
            logger.exception("Could not create dumpster %s", item["id"])
            raise HTTPException(status_code=409, detail="Could not create dumpster")
        logger.info("Registered dumpster %s at %.6f, %.6f", item["id"], item["latitude"], item["longitude"])
        return {"status": "created", "dumpster": item}

    @app.get("/api/dumpsters")
    def list_dumpsters() -> list[dict[str, Any]]:
        now = utc_now()
        return [present_dumpster(row, settings, now) for row in database.list_dumpsters()]

    @app.patch("/api/dumpsters/{dumpster_id}/photo")
    def update_dumpster_photo(dumpster_id: str, payload: DumpsterImageUpdate) -> dict[str, Any]:
        if not database.update_dumpster_image(dumpster_id, payload.image_url):
            raise HTTPException(status_code=404, detail="Unknown dumpster_id")
        return {"id": dumpster_id, "image_url": payload.image_url}

    @app.post("/api/measurements")
    def ingest_measurement(payload: MeasurementCreate) -> dict[str, Any]:
        if payload.measured_at.astimezone(timezone.utc).timestamp() > utc_now().timestamp() + 300:
            raise HTTPException(status_code=422, detail="measured_at cannot be more than five minutes in the future")
        dumpster = database.get_dumpster(payload.dumpster_id)
        if dumpster is None:
            raise HTTPException(status_code=404, detail="Unknown dumpster_id")
        from .sensing import Calibration, estimate_fill_percent

        fill = estimate_fill_percent(
            payload.distance_cm,
            Calibration(dumpster["empty_distance_cm"], dumpster["full_distance_cm"]),
        )
        if payload.fill_percentage is not None and abs(payload.fill_percentage - fill) > 5.0:
            raise HTTPException(status_code=422, detail="fill_percentage does not match dumpster calibration")
        item = {
            "measurement_id": payload.measurement_id,
            "dumpster_id": payload.dumpster_id,
            "device_id": payload.device_id,
            "raw_distance_cm": payload.raw_distance_cm,
            "distance_cm": payload.distance_cm,
            "fill_percentage": fill,
            "measured_at": iso_utc(payload.measured_at),
            "received_at": iso_utc(utc_now()),
        }
        inserted = database.insert_measurement(item)
        stored = database.get_measurement(item["measurement_id"])
        if not inserted:
            return {
                "status": "duplicate",
                "measurement_id": item["measurement_id"],
                "fill_percentage": stored["fill_percentage"] if stored else fill,
            }
        return {
            "status": "accepted",
            "measurement_id": item["measurement_id"],
            "fill_percentage": fill,
            "measured_at": item["measured_at"],
        }

    @app.get("/api/measurements/{dumpster_id}")
    def measurement_history(
        dumpster_id: str, limit: int = Query(default=100, ge=1, le=500)
    ) -> list[dict[str, Any]]:
        if database.get_dumpster(dumpster_id) is None:
            raise HTTPException(status_code=404, detail="Unknown dumpster_id")
        return database.measurement_history(dumpster_id, limit)

    @app.post("/api/routes/plan")
    def plan_route(payload: RoutePlanRequest) -> dict[str, Any]:
        run_date = payload.collection_date or next_collection_date(
            local_today(settings.timezone_name), settings.fixed_collection_weekdays
        )
        if run_date < local_today(settings.timezone_name):
            raise HTTPException(status_code=422, detail="Cannot plan a route for a past collection date")
        if run_date.weekday() not in settings.fixed_collection_weekdays:
            raise HTTPException(
                status_code=422,
                detail=f"Collection date must follow the fixed weekday schedule: {weekday_names(settings.fixed_collection_weekdays)}",
            )
        try:
            return build_route_plan(
                database,
                settings,
                collection_date=run_date,
                depot=Coordinate(payload.depot_latitude, payload.depot_longitude),
            )
        except Exception as error:
            logger.exception("Route planning failed")
            raise HTTPException(status_code=500, detail=f"Route planning failed: {error}") from error

    @app.get("/api/routes/latest")
    def latest_route() -> dict[str, Any] | None:
        return database.latest_route_plan()

    @app.get("/")
    def dashboard() -> FileResponse:
        return FileResponse(dashboard_dir / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> RedirectResponse:
        return RedirectResponse(url="/dashboard/favicon.svg", status_code=307)

    app.mount("/dashboard", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")
    return app


app = create_app()
