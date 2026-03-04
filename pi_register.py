from picamera2 import Picamera2
import cv2
import os
import time

DATA_DIR = "faces"
os.makedirs(DATA_DIR, exist_ok=True)

name = input("Enter person name: ")
user_dir = os.path.join(DATA_DIR, name)
os.makedirs(user_dir, exist_ok=True)

print("Initializing Camera...")
picam2 = Picamera2()
picam2.configure(
    picam2.create_video_configuration(
        main={"size": (640, 480)}
    )
)
picam2.start()
time.sleep(2)

count = 0
print("Look at camera.")
print("Press ENTER to capture image (10 images total)")

while count < 10:
    input(f"Press ENTER for image {count+1}/10...")
    frame = picam2.capture_array()

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    filename = os.path.join(user_dir, f"{count+1}.jpg")
    cv2.imwrite(filename, gray)
    print("Saved", filename)

    count += 1

print("Finished capturing images.")

picam2.stop()
print(f"{name} registered successfully!")
