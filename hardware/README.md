# Arduino IDE ESP32 integration

The sketch at `sketch_oct17b/sketch_oct17b.ino` is the firmware added by the latest pull, adapted to CicloRota HTTP ingestion. It preserves the working `Ultrasonic.read(CM)` call, GPIO TRIG 4 / ECHO 5, the 30 ms echo timeout, the 75 cm diagnostic ratio, and the 500 ms sample interval. Accepted distances use the same median and Kalman pipeline tested by the PlatformIO firmware. The ratio is diagnostic only and is never sent as fill percent.

## Configure the server

1. Register the dumpster in the dashboard or API first. Its ID must exactly match `CICLOROTA_DUMPSTER_ID`; calibration is stored for that ID. The backend computes fill percent from filtered centimeters and the registered empty/full distances.
2. Install and run the API on the same LAN as the ESP32:

       .venv/bin/uvicorn ciclorota.api:app --host 0.0.0.0 --port 8000

3. Find the server computer LAN IPv4 address. Do not use `127.0.0.1` in firmware. Allow TCP port 8000 through the host firewall for the trusted LAN.

## Configure and upload

Install Arduino CLI, the Espressif ESP32 board core, and the `Ultrasonic` library used by the pulled sketch. For example:

    arduino-cli core update-index
    arduino-cli core install esp32:esp32
    arduino-cli lib install Ultrasonic

Copy `sketch_oct17b/secrets.h.example` to `sketch_oct17b/secrets.h`. Set the Wi-Fi name/password, a full endpoint such as `http://192.168.1.20:8000/api/measurements`, the registered dumpster ID, and a device ID. IDs are restricted to letters, digits, dot, underscore, and hyphen. The real `secrets.h` is git-ignored.

Compile from the repository root:

    arduino-cli compile --fqbn esp32:esp32:esp32 hardware/sketch_oct17b
    arduino-cli upload --fqbn esp32:esp32:esp32 -p PORT hardware/sketch_oct17b

Use the actual serial port in place of `PORT`. Open the serial monitor at 115200 baud. Check that Wi-Fi connects and that the log shows HTTP 2xx measurement acceptance. The firmware needs NTP time before it can send a timezone-aware timestamp.

## Data sent to CicloRota

The ESP32 posts JSON to `POST /api/measurements` with these fields:

```json
{
  "measurement_id": "esp32-D1-unique-id",
  "dumpster_id": "D1",
  "device_id": "esp32-D1",
  "raw_distance_cm": 82.0,
  "distance_cm": 80.0,
  "measured_at": "2026-10-17T13:30:00Z"
}
```

`distance_cm` is the accepted Kalman-filtered distance. `raw_distance_cm` is the latest valid echo, both in centimeters. `measurement_id` stays constant over retries so the backend can safely treat duplicates as idempotent. No `fill_percentage` is sent: the API calculates it with the per-dumpster calibration in SQLite. The latest accepted value is returned by `GET /api/dumpsters` and appears in the dashboard at its 15-second refresh. Sensor samples are sent every 500 ms; failed readings are not queued; the device resumes with a subsequent sample.

## Wiring and safety

- HC-SR04 VCC and GND must follow the exact module specification; connect grounds to ESP32 ground.
- TRIG is GPIO 4 and ECHO is GPIO 5, matching the working sketch. Put a suitable level shifter or resistor divider on a 5 V ECHO output before the ESP32 input.
- Check the board and sensor datasheets before powering the module. Simulation and API tests do not validate electrical compatibility or physical measurements.

## Legacy TCP logger

`server.py` is the standalone CSV logger included with the pulled firmware. It listens on port 5000, prints CSV, and does not call the CicloRota API or persist data. The integrated sketch no longer sends TCP CSV. Do not run this logger when validating dashboard ingestion; use the FastAPI service on port 8000. The Python simulator remains a separate no-hardware API test path.

Automated tests for the integrated API, database, dashboard response, and firmware contract are present. Python source compilation passed, but pytest and native g++ could not launch in the current command sandbox. No physical ESP32, HC-SR04, Wi-Fi, electrical, or field validation is claimed here.
