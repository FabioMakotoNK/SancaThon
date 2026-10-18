
import cv2
import time
import os
import socket

stream = cv2.VideoCapture(0)
if not stream.isOpened():
    print("no stream")
    exit()

os.makedirs("ciclorota/data", exist_ok=True)

interval = 5  # Take a picture every 5 seconds
last_photo = time.monotonic() - interval
count = 0

while(True):
    ret, frame = stream.read()
    if not ret:
        print("no")
        break

    # Check if enough time has passed
    if time.monotonic() - last_photo >= interval:
        filename = f"ciclorota/data/photo_{count}.jpg"

        cv2.imwrite(filename, frame)
        print(f"Saved: {filename}")

        last_photo = time.monotonic()
        count += 1

    cv2.imshow("webcam", frame)

    if cv2.waitKey(1) == ord('q'):
        break

stream.release()
cv2.destroyAllWindows()
