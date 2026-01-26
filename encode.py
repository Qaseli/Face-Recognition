# encode_faces.py
import os
import face_recognition
import pickle

KNOWN_DIR = "faces"
OUTPUT = "encodings.pkl"

encodings = []
names = []

for person in os.listdir(KNOWN_DIR):
    person_dir = os.path.join(KNOWN_DIR, person)
    if not os.path.isdir(person_dir):
        continue
    for img_name in os.listdir(person_dir):
        img_path = os.path.join(person_dir, img_name)
        try:
            image = face_recognition.load_image_file(img_path)
            boxes = face_recognition.face_locations(image, model="hog")
            if len(boxes) == 0:
                print(f"No face found in {img_path}, skipping")
                continue
            enc = face_recognition.face_encodings(image, boxes)[0]
            encodings.append(enc)
            names.append(person)
            print(f"Encoded {img_path} as {person}")
        except Exception as e:
            print("Error", img_path, e)

data = {"encodings": encodings, "names": names}
with open(OUTPUT, "wb") as f:
    pickle.dump(data, f)
print("Saved encodings to", OUTPUT)
