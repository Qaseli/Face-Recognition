#reconize_live.py
import sqlite3
from datetime import datetime

conn = sqlite3.connect("attendance.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    date TEXT,
    time TEXT
)
""")
conn.commit()

last_seen = {}


import cv2
import pickle

# Load trained model
recognizer = cv2.face.LBPHFaceRecognizer_create()
recognizer.read("face_model.yml")

# Load labels
with open("labels.pkl", "rb") as f:
    labels = pickle.load(f)
id_to_name = labels

# Load face detector
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

cap = cv2.VideoCapture(0)

print("Recognition started. Press ESC to quit.")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.3, 5)

    for (x, y, w, h) in faces:
        roi = gray[y:y+h, x:x+w]

        id_, conf = recognizer.predict(roi)

        if conf < 55:
            name = id_to_name.get(id_, "Unknown")
            color = (0, 255, 0)

            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            time = now.strftime("%H:%M:%S")

            if name not in last_seen or (now - last_seen[name]).seconds > 10:
                cur.execute(
                    "INSERT INTO attendance (name, date, time) VALUES (?, ?, ?)",
                    (name, today, time)
                )
                conn.commit()
                print(f"[ATTENDANCE] {name} recorded at {time}")
                last_seen[name] = now
        else:
            name = "Unknown"
            color = (0, 0, 255)

        cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
        cv2.putText(frame, f"{name} {round(conf,1)}",
                    (x, y-10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    color,
                    2)

    cv2.imshow("Live Recognition", frame)

    if cv2.waitKey(1) == 27:
        break


cap.release()
cv2.destroyAllWindows()
