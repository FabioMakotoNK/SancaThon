# ESP32 firmware

The PlatformIO project uses Arduino on an ESP32 DevKit board and a top-mounted HC-SR04. Configure the dumpster calibration, Wi-Fi, endpoint, device ID, and GPIO pins in include/secrets.h. Start from include/secrets.h.example; secrets.h is git-ignored.

## Wiring

- HC-SR04 VCC to the module's required supply (commonly 5 V) and GND to ESP32 GND.
- TRIG to the configured ESP32 output (default GPIO 5).
- ECHO must pass through a 5 V-to-3.3 V level shifter or resistor divider before the configured ESP32 input (default GPIO 18). Never connect a 5 V ECHO signal directly to an ESP32 GPIO.
- Keep the sensor face at a calibrated, known height above the usable fill range. Configure empty and full distances separately for each dumpster.

## Build and flash

From this directory, install PlatformIO Core, copy the example secrets header, then run:

    pio run
    pio run --target upload
    pio device monitor

Firmware samples five ultrasonic pulses, rejects missing/out-of-range measurements and transient large spikes, smooths accepted distances with a one-dimensional Kalman filter, and resets after three consistent readings confirm a large step such as emptying. It estimates fill percentage from the local calibration and posts JSON over Wi-Fi HTTP. Wi-Fi reconnect and HTTP retries are bounded. A generated measurement ID makes retries idempotent.

The development firmware uses plain HTTP and public NTP servers; both require a trusted network and internet access. Production deployments should use authenticated HTTPS and managed time synchronization. No physical ESP32 or HC-SR04 was available during software verification.
