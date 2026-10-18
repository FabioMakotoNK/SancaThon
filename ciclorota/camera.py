"""Capture a host camera's latest photo for a registered CicloRota dumpster.

Run from the repository: python -m ciclorota.camera --dumpster-id YOUR_ID
This program saves photographs only; it does not estimate fill or send measurements.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


DEFAULT_PHOTO_DIR = Path(__file__).resolve().parent / "dashboard" / "images" / "dumpsters"


class CameraError(RuntimeError):
    """An actionable camera or API configuration error."""


def api_json(base_url: str, path: str, *, payload: dict | None = None, method: str = "GET"):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(base_url.rstrip("/") + path, data=body, method=method,
                      headers={"Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        raise CameraError(f"API returned HTTP {error.code} for {path}. Check the registered dumpster and server.") from error
    except (URLError, TimeoutError, OSError, ValueError) as error:
        raise CameraError("Cannot reach/read the CicloRota API. Check --base-url and that the server is running.") from error


def photo_filename(dumpster_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", dumpster_id):
        raise CameraError("Dumpster ID must contain only letters, digits, dots, underscores or hyphens.")
    # Prefix prevents reserved Windows filenames. A short digest distinguishes
    # case-sensitive API IDs on case-insensitive host filesystems.
    import hashlib
    digest = hashlib.sha256(dumpster_id.encode("utf-8")).hexdigest()[:10]
    return f"camera-{dumpster_id}-{digest}.jpg"


def atomic_write_photo(destination: Path, jpeg: bytes) -> None:
    """Readers see either the previous complete JPEG or the next complete JPEG."""
    if not jpeg:
        raise CameraError("Camera produced an empty image; previous photograph was preserved.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".capture-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(jpeg)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_opencv():
    try:
        return importlib.import_module("cv2")
    except ImportError as error:
        raise CameraError('OpenCV is missing. Install the optional host dependency: python -m pip install -e ".[camera]"') from error


def capture_photos(args, filename: str) -> int:
    cv2 = load_opencv()
    source = int(args.source) if args.source.isdigit() else args.source
    stream = cv2.VideoCapture(source)
    destination = args.output_dir.resolve() / filename
    image_url = "/dashboard/images/dumpsters/" + quote(filename, safe="")
    linked = False
    next_capture = 0.0
    try:
        if not stream.isOpened():
            raise CameraError("Cannot open the camera. Check --source, camera permissions, and other camera applications.")
        print(f"Camera active for dumpster {args.dumpster_id}. Stop with Ctrl+C.", flush=True)
        while True:
            ok, frame = stream.read()
            if not ok:
                raise CameraError("Camera stopped providing frames. Check the camera connection.")
            if time.monotonic() >= next_capture:
                encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not encoded:
                    raise CameraError("Could not encode the photograph; previous image was preserved.")
                atomic_write_photo(destination, jpeg.tobytes())
                # Link only after the first complete image is available.
                if not linked:
                    api_json(args.base_url, "/api/dumpsters/" + quote(args.dumpster_id, safe="") + "/photo",
                             payload={"image_url": image_url}, method="PATCH")
                    linked = True
                    print(f"Dashboard photograph linked: {image_url}", flush=True)
                stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                print(f"{stamp} Saved latest photograph: {destination.name}", flush=True)
                if args.once:
                    return 0
                next_capture = time.monotonic() + args.interval
            if args.preview:
                cv2.imshow("CicloRota camera - press q to stop", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    return 0
            else:
                time.sleep(0.03)
    finally:
        stream.release()
        if args.preview:
            cv2.destroyAllWindows()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--dumpster-id", help="Actual ID already registered in the dashboard")
    target.add_argument("--list", action="store_true", help="List registered dumpsters without opening the camera")
    parser.add_argument("--base-url", default="http://localhost:8000", help="CicloRota API address")
    parser.add_argument("--source", default="0", help="OpenCV camera index, video file, or camera stream URL")
    parser.add_argument("--interval", type=float, default=5, help="Seconds between photographs (default: 5)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PHOTO_DIR,
                        help="Host directory mounted/served as /dashboard/images/dumpsters/")
    parser.add_argument("--once", action="store_true", help="Save and link one photograph, then stop")
    parser.add_argument("--preview", action="store_true", help="Show a camera window; q exits")
    args = parser.parse_args(argv)
    try:
        url = urlsplit(args.base_url)
        url.port
        if url.scheme not in ("http", "https") or not url.hostname or url.query or url.fragment or url.username or url.password:
            parser.error("--base-url must be an HTTP(S) server address without credentials, query or fragment")
    except ValueError:
        parser.error("Invalid --base-url")
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("--interval must be a positive finite number")
    try:
        filename = photo_filename(args.dumpster_id) if args.dumpster_id else None
        dumpsters = api_json(args.base_url, "/api/dumpsters")
        if not isinstance(dumpsters, list):
            raise CameraError("Unexpected dumpster response from API.")
        if args.list:
            for item in dumpsters:
                print(f"{item['id']}: {item['name']}")
            if not dumpsters:
                print("No registered dumpsters. Register a real container in the dashboard or /docs first.")
            return 0
        if not any(item.get("id") == args.dumpster_id for item in dumpsters):
            raise CameraError("That dumpster ID is not registered. Use --list or register it in the dashboard first. Camera was not opened.")
        return capture_photos(args, filename)
    except KeyboardInterrupt:
        print("\nCamera stopped.", flush=True)
        return 0
    except (CameraError, OSError) as error:
        print(f"Camera error: {error}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())