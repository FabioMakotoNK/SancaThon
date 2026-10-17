"""Legacy TCP CSV console only; it is not connected to the CicloRota API or database."""

import socket

HOST = "0.0.0.0"  # Listen on all computer network interfaces
PORT = 5000

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()

    print(f"Legacy TCP CSV logger listening on port {PORT}; data is not persisted or sent to CicloRota")
    print("Waiting for ESP32...")

    while True:
        connection, address = server.accept()
        print(f"\nESP32 connected: {address}")

        try:
            with connection:
                with connection.makefile("r", encoding="utf-8") as messages:
                    for line in messages:
                        message = line.strip()
                        print(f"Received: {message}")

                        try:
                            ratio, filtered_cm, raw_cm = map(
                                float, message.split(",")
                            )
                            print(
                                f"Ratio: {ratio:.4f} | "
                                f"Filtered: {filtered_cm:.2f} cm | "
                                f"Raw: {raw_cm:.0f} cm"
                            )
                        except ValueError:
                            print("Expected: ratio,filtered_cm,raw_cm")

        except (OSError, UnicodeError) as error:
            print(f"Connection error: {error}")

        print("ESP32 disconnected. Waiting for reconnection...")
