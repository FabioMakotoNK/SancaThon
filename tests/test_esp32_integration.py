from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_hardware_sketch_preserves_sensor_and_emits_backend_http_contract():
    sketch = (ROOT / "hardware/sketch_oct17b/sketch_oct17b.ino").read_text()
    assert "Ultrasonic sensor(TRIG_PIN, ECHO_PIN, ECHO_TIMEOUT_US)" in sketch
    assert "sensor.read(CM)" in sketch
    assert "constexpr uint8_t TRIG_PIN = 4" in sketch
    assert "constexpr uint8_t ECHO_PIN = 5" in sketch
    assert "constexpr unsigned long ECHO_TIMEOUT_US = 30000UL" in sketch
    assert "constexpr unsigned long SAMPLE_INTERVAL_MS = 500UL" in sketch
    assert "ciclorota::MeasurementPipeline pipeline" in sketch
    assert "HTTPClient http" in sketch
    assert "http.POST(" in sketch
    for field in (
        "measurement_id", "dumpster_id", "device_id",
        "raw_distance_cm", "distance_cm", "measured_at",
    ):
        escaped_json_key = chr(92) + chr(34) + field + chr(92) + chr(34)
        assert escaped_json_key in sketch
    assert "fill_percentage" not in sketch


def test_platformio_firmware_uses_same_server_owned_fill_contract():
    firmware = (ROOT / "firmware/src/main.cpp").read_text()
    payload = firmware.split("char payload[512];", 1)[1].split("for (int attempt", 1)[0]
    for field in (
        "measurement_id", "dumpster_id", "device_id",
        "raw_distance_cm", "distance_cm", "measured_at",
    ):
        escaped_json_key = chr(92) + chr(34) + field + chr(92) + chr(34)
        assert escaped_json_key in payload
    assert "fill_percentage" not in payload
