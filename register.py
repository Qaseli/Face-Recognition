#register.py
import cv2
import os
import pickle

DATA_DIR = "faces"

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

name = input("Enter person name: ")

user_dir = os.path.join(DATA_DIR, name)
os.makedirs(user_dir, exist_ok=True)

cap = cv2.VideoCapture(0)

count = 0
print("Look at camera. Press SPACE to capture. Capture 10 images.")

while True:
    ret, frame = cap.read()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

# Detect face
    faces = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
).detectMultiScale(gray, 1.3, 5)

# If no face → red warning box
    if len(faces) == 0:
        cv2.putText(frame, "No Face Detected",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 255),
                2)

# If face found → green box
    for (x, y, w, h) in faces:
        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)



    cv2.imshow("Register Face", frame)
    if cv2.waitKey(1) & 0xFF == 32:
        count += 1
        cv2.imwrite(f"{user_dir}/{count}.jpg", gray)
        print(f"Captured {count}/10")

    if count >= 10:
        break

cap.release()
cv2.destroyAllWindows()

print("Training face model...")

import numpy as np
recognizer = cv2.face.LBPHFaceRecognizer_create()

faces = []
labels = []
label_map = {}
current_label = 0

for person in os.listdir(DATA_DIR):
    label_map[current_label] = person
    person_path = os.path.join(DATA_DIR, person)

    for img_name in os.listdir(person_path):
        img = cv2.imread(os.path.join(person_path, img_name), cv2.IMREAD_GRAYSCALE)
        faces.append(img)
        labels.append(current_label)

    current_label += 1

recognizer.train(faces, np.array(labels))
recognizer.save("face_model.yml")


with open("labels.pkl", "wb") as f:
    pickle.dump(label_map, f)

print(f"{name} registered successfully!")
