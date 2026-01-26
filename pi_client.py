# pi_client.py
import cv2 
import base64
import time
import socketio
from threading import Event
from aes_utils import load_key, encrypt_bytes, b64_encode_bytes
from picamera2 import Picamera2 
import os

# Edit this to your server IP (http)
SERVER_URL = "http://192.168.100.203:5000"  # REPLACE <SERVER_IP>
CAMERA_ID = "pi_zero_2"
FPS = 2  # frames per second to send
AES_KEY_PATH = "aes_key.bin"  # copy this file from server

sio = socketio.Client()
last_result = None
result_event = Event()

# load AES key
try:
    AES_KEY = load_key(AES_KEY_PATH)
    print("Loaded AES key from", AES_KEY_PATH)
except Exception as e:
    print("Failed to load AES key:", e)
    AES_KEY = None

@sio.event
def connect():
    print("Connected to server")

@sio.event
def disconnect():
    print("Disconnected from server")

@sio.on('result')
def on_result(data):
    global last_result
    last_result = data
    result_event.set()

def encrypt_and_send_jpeg(jpeg_bytes):
    if AES_KEY is None:
        print("No AES key loaded; cannot encrypt")
        return False
    enc = encrypt_bytes(jpeg_bytes, AES_KEY)  # iv + ciphertext
    b64 = b64_encode_bytes(enc)
    payload = {'camera_id': CAMERA_ID, 'image': b64}
    sio.emit('frame_encrypted', payload)
    return True

def capture_jpeg_from_cv_frame(frame_bgr, quality=70):
    # encode to JPEG bytes
    ret, jpg = cv2.imencode('.jpg', frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ret:
        return None
    return jpg.tobytes()

def main():
    print("Starting client. Connecting to", SERVER_URL)
    sio.connect(SERVER_URL)

    # === Pi Camera (Picamera2) SETUP ===
    picam2 = Picamera2()
    picam2.configure(
        picam2.create_video_configuration(
            main={"size": (640, 480)}
        )
    )
    picam2.start()

    try:
        while True:
            start = time.time()

            # CAPTURE FRAME (NO cap variable anymore)
            frame = picam2.capture_array()

            frame_small = cv2.resize(frame, (320, 240))
            jpeg_bytes = capture_jpeg_from_cv_frame(frame_small, quality=60)

            if jpeg_bytes is None:
                print("JPEG encode failed")
                continue

            sent = encrypt_and_send_jpeg(jpeg_bytes)
            if sent:
                result_event.clear()
                if result_event.wait(timeout=5.0):
                    res = last_result
                    name = res.get('name', 'Error')
                    status = res.get('status', '')
                    overlay = frame.copy()

                    if status == 'ok':
                        text = f"{name}"
                    else:
                        text = f"Err:{res.get('reason','')}"

                    cv2.putText(
                        overlay, text, (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.0, (0, 255, 0), 2
                    )
                    #cv2.imshow("Pi Display", overlay)
                    #cv2.waitKey(1)
                    print(f"[RESULT] {name} | status={status}")

                else:
                    print("No response from server")

            elapsed = time.time() - start
            time.sleep(max(0, 1.0 / FPS - elapsed))

    except KeyboardInterrupt:
        print("Stopping client")

    finally:
        #cv2.destroyAllWindows()
        sio.disconnect()


if __name__ == "__main__":
    main()
