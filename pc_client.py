import cv2
import socketio
import base64
from aes_utils import encrypt_bytes

SERVER_URL = "http://192.168.100.203:5000"

sio = socketio.Client()

@sio.event
def connect():
    print("Connected to server")

@sio.event
def disconnect():
    print("Disconnected")

def main():
    sio.connect(SERVER_URL)

    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Camera not found")
        return

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        _, buffer = cv2.imencode(".jpg", frame)
        encrypted = encrypt_bytes(buffer.tobytes())
        encoded = base64.b64encode(encrypted).decode("utf-8")

        sio.emit("frame", encoded)

        cv2.imshow("PC Client Camera", frame)
        if cv2.waitKey(1) == 27:
            break

    cap.release()
    cv2.destroyAllWindows()
    sio.disconnect()

if __name__ == "__main__":
    main()
