# recognition.py
import pickle
import face_recognition
import numpy as np
from typing import Tuple

ENC_FILE = "encodings.pkl"

class Recognizer:
    def __init__(self, enc_file=ENC_FILE, tolerance=0.5):
        print("[DEBUG] Opening encodings file:", enc_file)

        # open encodings.pkl
        with open(enc_file, "rb") as f:
            data = pickle.load(f)
        print("[DEBUG] Encodings file loaded")

        print("[DEBUG] Parsing encoding data structure...")
        self.known_encodings = data.get("encodings", [])
        self.known_names = data.get("names", [])
        print("[DEBUG] Encodings initialized")
        print(f"[DEBUG] Faces loaded: {len(self.known_names)}")

        self.tolerance = tolerance
        print("[DEBUG] Recognizer ready\n")

    def recognize(self, rgb_image) -> Tuple[str, float]:
        """
        Input: rgb_image (numpy array)
        Return: (name, best_distance). If unknown, name = "Unknown"
        """
        boxes = face_recognition.face_locations(rgb_image, model="hog")
        if not boxes:
            return ("NoFace", 1.0)
        encodings = face_recognition.face_encodings(rgb_image, boxes)
        # For simplicity handle first face
        face_enc = encodings[0]
        dists = face_recognition.face_distance(self.known_encodings, face_enc)
        if len(dists) == 0:
            return ("Unknown", 1.0)
        best_idx = np.argmin(dists)
        best_dist = float(dists[best_idx])
        if best_dist <= self.tolerance:
            return (self.known_names[best_idx], best_dist)
        else:
            return ("Unknown", best_dist)
