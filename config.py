import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, use defaults

class Config:
    # Server Settings
    SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(os.getenv("SERVER_PORT", 5000))
    DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() in ("true", "1", "yes")
    SECRET_KEY = os.getenv("SECRET_KEY", "secret!")

    # Database
    DB_PATH = os.getenv("DB_PATH", "attendance.db")

    # Security
    AES_KEY_PATH = os.getenv("AES_KEY_PATH", "aes_key.bin")

    # Recognition Settings
    # Lower tolerance = stricter matching, Higher = looser
    RECOGNITION_TOLERANCE = float(os.getenv("RECOGNITION_TOLERANCE", 0.5))

    # Attendance Logic
    # Minimum seconds between attendance records for the same person
    ATTENDANCE_COOLDOWN_SECONDS = int(os.getenv("ATTENDANCE_COOLDOWN_SECONDS", 60))

    # File Uploads
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
