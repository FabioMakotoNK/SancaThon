# ESP32 firmware

The PlatformIO project uses Arduino on an ESP32 DevKit board and a top-mounted HC-SR04. Copy include/secrets.h.example to include/secrets.h, then configure Wi-Fi, endpoint, device/dumpster IDs, GPIO pins, and the local diagnostic calibration. The secrets.h file is git-ignored. GPIO example defaults are TRIG 4 and ECHO 5 to match the pulled working Arduino sketch; do not connect a 5 V ECHO output directly to the ESP32.


## Wiring

- HC-SR04 VCC to the module's required supply (commonly 5 V) and GND to ESP32 GND.
- TRIG to the configured ESP32 output (default GPIO 4).
- ECHO must pass through a 5 V-to-3.3 V level shifter or resistor divider before the configured ESP32 input (default GPIO 5). Never connect a 5 V ECHO signal directly to an ESP32 GPIO.
- Keep the sensor face at a calibrated, known height above the usable fill range. Configure empty and full distances separately for each dumpster.

## Build and flash

From this directory, install PlatformIO Core, copy the example secrets header, then run:

    pio run
    pio run --target upload
    pio device monitor

The PlatformIO firmware samples five ultrasonic pulses, rejects missing/out-of-range measurements and transient spikes, applies the shared median plus one-dimensional Kalman pipeline, and resets after three consistent samples confirm a large step such as emptying. Its local calibration is used for a serial diagnostic only. The JSON HTTP request sends measurement ID, dumpster/device IDs, raw and filtered distances in centimeters, and a timezone-aware UTC timestamp; it omits fill_percentage so the backend uses the dumpster calibration stored in SQLite. Wi-Fi reconnect and HTTP retries are bounded, and one measurement ID is reused during all retries.

The integrated Arduino IDE sketch that arrived in the latest pull is hardware/sketch_oct17b/sketch_oct17b.ino. It retains the Ultrasonic library reader and GPIO 4/5 and uses the same sensor_pipeline.h, HTTP contract, and secrets described in hardware/README.md.

The development firmware uses plain HTTP and public NTP servers; both require a trusted network and internet access. Production deployments should use authenticated HTTPS and managed time synchronization. No physical ESP32 or HC-SR04 was available during software verification.
