# server.py
import os
os.environ["EVENTLET_NO_GREENDNS"] = "yes"

import base64
import io
import traceback
import cv2
import time
from PIL import Image
from flask import Flask, jsonify, request, send_from_directory, Response, session, redirect, make_response
from flask_socketio import SocketIO, emit
import csv
from config import Config
from utils import setup_logger, validate_date_format
from recognition import Recognizer
import db
from aes_utils import load_key, b64_decode_to_bytes, decrypt_bytes
import numpy as np
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, auth

# Initialize Firebase (Global Scope)
try:
    cred_path = Config.FIREBASE_CREDENTIALS # Now exists in Config
    if not os.path.exists(cred_path):
        # Fallback to absolute path check or warn
        # Try finding it in current dir
        if os.path.exists("firebase_credentials.json"):
            cred_path = "firebase_credentials.json"
            
    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        print(f"[INFO] Firebase Initialized from {cred_path}") # Print to stdout to be sure
    else:
        print(f"[WARNING] Firebase credentials not found at {cred_path}")
except Exception as e:
    print(f"[ERROR] Firebase Init Failed: {e}")

# Initialize Logger
logger = setup_logger("Server")

# Initialize Flask & SocketIO
app = Flask(__name__, static_folder='.', static_url_path='')
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# State
AES_KEY = None
recognizer = None
active_clients = set()
last_rpi_heartbeat = 0 # Unix timestamp of last received frame

# Capture Mode State (for staff registration via Pi camera)
capture_pending = False  # Is a capture request active?
capture_images = []  # Captured images from Pi
capture_staff_name = ""  # Name of staff being registered
capture_complete = False  # Has capture finished?
rpi_client_sid = None  # Socket ID of connected RPi client
latest_preview_frame = None  # Latest preview frame data for HTTP polling




def gen_frames():
    cap = cv2.VideoCapture(0)
    while True:
        success, frame = cap.read()
        if not success:
            break
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

def initialize_system():
    global AES_KEY, recognizer
    
    logger.info("Initializing Backend System...")
    
    # Load AES Key
    try:
        AES_KEY = load_key(Config.AES_KEY_PATH)
        logger.info(f"Loaded AES key from {Config.AES_KEY_PATH}")
    except Exception as e:
        logger.error(f"Failed to load AES key: {e}")

    except Exception as e:
        logger.error(f"Failed to load AES key: {e}")
        logger.critical(f"Failed to load AES key: {e}")
        AES_KEY = None

    # Load Recognizer
    try:
        recognizer = Recognizer(enc_file="encodings.pkl", tolerance=Config.RECOGNITION_TOLERANCE)
        logger.info(f"Recognizer initialized with tolerance {Config.RECOGNITION_TOLERANCE}")
    except Exception as e:
        logger.error(f"Failed to initialize recognizer: {e}")
        recognizer = None

    # Init DB
    db.init_db()
    logger.info("System Initialized Successfully")
    
    # Auto-generate daily reports for the last 7 days
    try:
        from datetime import timedelta
        for i in range(1, 8):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            generate_daily_report(date_str)
    except Exception as e:
        logger.warning(f"Daily report auto-generation skipped: {e}")

# --- Socket.IO Events ---

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    active_clients.add(sid)
    logger.info(f"Client connected: {sid} (Total: {len(active_clients)})")
    emit('server_msg', {'msg': 'welcome', 'config': {'tolerance': Config.RECOGNITION_TOLERANCE}})

@socketio.on('disconnect')
def handle_disconnect():
    global rpi_client_sid
    sid = request.sid
    if sid in active_clients:
        active_clients.remove(sid)
    # If the disconnected client was the RPi, clear the reference
    if sid == rpi_client_sid:
        rpi_client_sid = None
        logger.info("RPi client disconnected")
    logger.info(f"Client disconnected: {sid}")

@socketio.on('rpi_register')
def handle_rpi_register(data):
    """RPi client registers itself so server knows which SID to send capture requests to"""
    global rpi_client_sid
    rpi_client_sid = request.sid
    camera_id = data.get('camera_id', 'unknown')
    logger.info(f"RPi client registered: {rpi_client_sid} (Camera: {camera_id})")
    emit('rpi_registered', {'status': 'ok'})

@socketio.on('capture_response')
def handle_capture_response(data):
    """Pi sends captured images back to server"""
    global capture_images, capture_complete
    
    status = data.get('status', 'error')
    if status == 'ok':
        images = data.get('images', [])
        capture_images.extend(images)  # Append (single capture at a time)
        capture_complete = True
        logger.info(f"Received {len(images)} capture image(s) from RPi")
    else:
        reason = data.get('reason', 'unknown')
        logger.error(f"Capture failed: {reason}")
        capture_complete = True

@socketio.on('preview_frame')
def handle_preview_frame(data):
    """Store preview frame from Pi for HTTP polling by browser"""
    global latest_preview_frame
    latest_preview_frame = {
        'image': data.get('image'),
        'face_detected': data.get('face_detected', False),
        'num_faces': data.get('num_faces', 0)
    }

@socketio.on('frame_encrypted')
def handle_frame(data):
    """
    data: { 'camera_id': 'pi0', 'image': '<base64 of iv+ciphertext>' }
    """
    global last_rpi_heartbeat
    last_rpi_heartbeat = time.time()

    try:
        if AES_KEY is None:
            emit('result', {'status': 'error', 'reason': 'Server AES key not loaded'})
            return

        camera_id = data.get('camera_id', 'unknown')
        img_b64 = data.get('image')
        
        if not img_b64:
            emit('result', {'status': 'error', 'reason': 'no image'})
            return

        # 1. Decode & Decrypt
        try:
            enc_bytes = b64_decode_to_bytes(img_b64)
            img_bytes = decrypt_bytes(enc_bytes, AES_KEY)
        except Exception as e:
            logger.warning(f"Decryption failed from {camera_id}: {e}")
            emit('result', {'status': 'error', 'reason': 'decryption_failed'})
            return

        # 2. Convert to RGB
        try:
            img_pil = Image.open(io.BytesIO(img_bytes)).convert('RGB')
            rgb = np.array(img_pil)
        except Exception as e:
            logger.error(f"Image processing failed: {e}")
            emit('result', {'status': 'error', 'reason': 'bad_image_data'})
            return
        
        # 2.5 🔴 LIVE PREVIEW FRAME (send to frontend)
        try:
            frame_b64 = base64.b64encode(img_bytes).decode("utf-8")
            socketio.emit("live_frame", {
                "camera_id": camera_id,
                "image": frame_b64
            })
        except Exception as e:
            logger.warning(f"Failed to emit live frame: {e}")


        # 3. Recognition
        if recognizer:
            name, dist = recognizer.recognize(rgb)
            status = 'ok'
            
            if name not in ("NoFace", "Unknown"):
                # Check cooldown
                if db.is_duplicate_entry(name, Config.ATTENDANCE_COOLDOWN_SECONDS):
                    logger.info(f"Duplicate entry ignored for {name}")
                    status = 'ignored_duplicate'
                else:
                    confidence = max(0.0, 1.0 - dist)
                    db.add_record(name, camera_id, confidence=confidence)
                    logger.info(f"Face recognized: {name} ({dist:.2f})")
            
            result_data = {'status': status, 'name': name, 'distance': dist, 'camera_id': camera_id}
            emit('result', result_data)  # Send to RPi sender
            # Broadcast to ALL clients (admin dashboard Live Log)
            socketio.emit('recognition_event', result_data)
        else:
            emit('result', {'status': 'error', 'reason': 'recognizer_not_ready'})

    except Exception as e:
        logger.error(f"Error processing frame: {e}")
        traceback.print_exc()
        emit('result', {'status': 'error', 'reason': str(e)})

# --- Static File Serving ---

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

# --- REST API Endpoints ---

@app.route("/api/health")
def health_check():
    # Check if we heard from RPi in last 15 seconds
    is_rpi_online = (time.time() - last_rpi_heartbeat) < 15
    
    return jsonify({
        "status": "healthy",
        "clients": len(active_clients),
        "aes_loaded": AES_KEY is not None,
        "recognizer_ready": recognizer is not None,
        "db_path": Config.DB_PATH,
        "rpi_connected": is_rpi_online
    })

@app.route("/api/config")
def get_config():
    return jsonify({
        "server_port": Config.SERVER_PORT,
        "tolerance": Config.RECOGNITION_TOLERANCE,
        "cooldown": Config.ATTENDANCE_COOLDOWN_SECONDS,
        "debug": Config.DEBUG_MODE
    })

@app.route("/api/attendance/recent")
def recent_attendance():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        rows = db.get_recent_paginated(page, per_page)
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/attendance/by-date")
def attendance_by_date():
    start = request.args.get('start')
    end = request.args.get('end')
    
    if not start or not end:
        return jsonify({"error": "Missing start or end date"}), 400
    
    if not (validate_date_format(start) and validate_date_format(end)):
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    try:
        rows = db.get_by_date_range(start, end)
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/attendance/stats")
def attendance_stats():
    try:
        stats = db.get_stats_last_7_days()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/export/attendance")
def export_attendance_csv():
    try:
        # Export last 5000 records
        limit = 5000
        conn = db.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM attendance ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        
        # Generate CSV
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['ID', 'Name', 'Timestamp', 'Camera ID', 'Confidence']) # Header
        
        for row in rows:
            cw.writerow([row['id'], row['name'], row['timestamp'], row['camera_id'], row['confidence']])
            
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = "attachment; filename=attendance_export.csv"
        output.headers["Content-type"] = "text/csv"
        return output
    except Exception as e:
        logger.error(f"Export failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/attendance/today")
def attendance_today():
    """Return today's attendance for Live Recognition Log (all entries)"""
    try:
        from datetime import datetime, timedelta
        # Query last 24 hours to handle UTC vs local timezone differences
        now_utc = datetime.utcnow()
        start_utc = (now_utc - timedelta(hours=24)).isoformat()
        
        conn = db.get_db_connection()
        c = conn.cursor()
        c.execute("""SELECT name, timestamp, camera_id, confidence 
                     FROM attendance 
                     WHERE timestamp >= ? 
                     ORDER BY timestamp DESC""", (start_utc,))
        rows = c.fetchall()
        conn.close()
        
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        logger.error(f"Today attendance fetch failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/export/today")
def export_today_csv():
    """Download today's attendance as CSV"""
    try:
        from datetime import datetime, timedelta
        now_utc = datetime.utcnow()
        start_utc = (now_utc - timedelta(hours=24)).isoformat()
        today_local = datetime.now().strftime("%Y-%m-%d")
        
        conn = db.get_db_connection()
        c = conn.cursor()
        c.execute("""SELECT name, timestamp, camera_id, confidence 
                     FROM attendance 
                     WHERE timestamp >= ? 
                     ORDER BY timestamp DESC""", (start_utc,))
        rows = c.fetchall()
        conn.close()
        
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['Name', 'Timestamp', 'Camera ID', 'Confidence'])
        
        for row in rows:
            cw.writerow([row['name'], row['timestamp'], row['camera_id'], row['confidence']])
        
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = f"attachment; filename=attendance_{today_local}.csv"
        output.headers["Content-type"] = "text/csv"
        return output
    except Exception as e:
        logger.error(f"Today export failed: {e}")
        return jsonify({"error": str(e)}), 500

def generate_daily_report(date_str=None):
    """Generate a daily CSV report file in the reports/ folder"""
    from datetime import datetime, timedelta
    if date_str is None:
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    
    filepath = os.path.join(reports_dir, f"attendance_{date_str}.csv")
    
    # Skip if already generated
    if os.path.exists(filepath):
        return filepath
    
    try:
        rows = db.get_by_date_range(date_str, date_str)
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            cw = csv.writer(f)
            cw.writerow(['Name', 'Timestamp', 'Camera ID', 'Confidence'])
            for row in rows:
                cw.writerow([row['name'], row['timestamp'], row['camera_id'], row['confidence']])
        
        logger.info(f"Daily report generated: {filepath} ({len(rows)} records)")
        return filepath
    except Exception as e:
        logger.error(f"Failed to generate report for {date_str}: {e}")
        return None

@app.route("/api/reports/generate_daily", methods=["POST"])
def trigger_daily_report():
    """Admin: Manually trigger daily report generation"""
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    
    from datetime import datetime, timedelta
    # Generate for the last 7 days (fills any gaps)
    generated = []
    for i in range(7):
        date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        result = generate_daily_report(date_str)
        if result:
            generated.append(date_str)
    
    return jsonify({"status": "ok", "generated": generated})



# --- Auth APIs ---

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    
    user = db.verify_user(username, password)
    if user:
        # Check if first login required
        if user.get('is_first_login') or user.get('status') == 'Inactive':
             # If status is Inactive, we only allow if verify_user succeeded (which checks temp_pass)
             return jsonify({
                 "status": "first_login_required",
                 "user": username
             })
             
        session["user"] = username
        session["role"] = user["role"]
        return jsonify({
            "status": "ok", 
            "user": username, 
            "role": user["role"],
            "leave_balance": user.get("leave_balance", 0),
            "full_name": user.get("full_name", username)
        })
    return jsonify({"status": "error", "message": "Invalid credentials or account inactive"}), 401

@app.route("/api/login/google", methods=["POST"])
def google_login():
    data = request.json
    id_token = data.get('id_token')
    
    if not id_token:
        return jsonify({"error": "No token provided"}), 400
    try:
        # 1. Verify Token with Firebase
        decoded_token = auth.verify_id_token(id_token)
        email = decoded_token['email']
        
        # 2. Check Database
        user = db.get_user_by_email(email)
        
        if not user:
            return jsonify({"error": "Email not registered in system"}), 401
            
        if user['status'] == 'Inactive':
             # Auto-Activate user on successful Google Login
             logger.info(f"Auto-activating user {user['username']} via Google Login")
             # Use a dummy password for the 'change' function or direct SQL? 
             # Better: Creating a specific activation function is cleaner, but reusing change_password is valid if we don't care about setting a specific password.
             # Actually, for Google users we don't need a password. 
             # Let's just update the status directly here or via a db helper.
             # Ideally we should add a `db.activate_user(username)` helper.
             # But to keep it simple and safe within existing tools:
             db.activation_via_google(user['username'])
             user['status'] = 'Active' # Update local dict for session

        # 3. Create Session
        session["user"] = user["username"]
        session["role"] = user["role"]
        
        return jsonify({
            "status": "ok", 
            "user": user["username"], 
            "role": user["role"],
            "full_name": user.get('full_name', user["username"])
        })
        
    except Exception as e:
        logger.error(f"Google Login Error: {e}")
        return jsonify({"error": "Invalid token"}), 401
        
@app.route("/api/change_password", methods=["POST"])
def change_password_route():
    data = request.json
    username = data.get("username")
    temp_pass = data.get("temp_password")
    new_pass = data.get("new_password")
    
    # Verify temp pass again for security
    user = db.verify_user(username, temp_pass)
    if not user:
         return jsonify({"error": "Invalid temporary password"}), 400
         
    if db.change_password(username, new_pass):
        return jsonify({"status": "ok"})
    else:
        return jsonify({"error": "Failed to update password"}), 500

@app.route("/api/user/update_password", methods=["POST"])
def update_password_session():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    username = session["user"]
    data = request.json
    current_pass = data.get("current_password")
    new_pass = data.get("new_password")
    
    # Check if user has a password set currently
    # We need a db helper for this, or verify_user. 
    # For now, let's try verify_user if current_pass is provided.
    
    conn = db.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT password FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    
    # Check if they have a REAL password (ignore the placeholder set by add_staff)
    has_password = row and row['password'] and row['password'] != 'legacy_placeholder'
    
    if has_password and not current_pass:
        return jsonify({"error": "Current password required"}), 400
        
    if has_password:
        # Verify it
        if row['password'] != current_pass:
             return jsonify({"error": "Incorrect current password"}), 400
             
    # Set new password
    if db.change_password(username, new_pass):
        return jsonify({"status": "ok"})
    return jsonify({"error": "Failed to update"}), 500

@app.route("/api/user/update_profile", methods=["POST"])
def update_own_profile():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    username = session["user"]
    data = request.json
    
    email = data.get("email")
    phone = data.get("phone")
    position = data.get("position")
    department = data.get("department")
    
    # Update DB
    conn = db.get_db_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET email=?, phone=?, position=?, department=? WHERE username=?", (email, phone, position, department, username))
        conn.commit()
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Profile update failed: {e}")
        return jsonify({"error": "Update failed"}), 500
    finally:
        conn.close()

@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("user", None)
    session.pop("role", None)
    return jsonify({"status": "ok"})

@app.route("/api/check_auth")
def check_auth():
    if "user" in session:
        # Fetch fresh user data
        conn = db.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=?", (session["user"],))
        row = c.fetchone()
        conn.close()
        
        if row:
            user_data = dict(row)
            # Remove password
            user_data.pop('password', None)
            user_data.pop('temp_password', None)
            
            return jsonify({
                "authenticated": True, 
                "user": session["user"], 
                "role": user_data['role'],
                "leave_balance": user_data['leave_balance'],
                "full_name": user_data.get('full_name', user_data['username']),
                "details": user_data
            })
    return jsonify({"authenticated": False}), 401

# --- Staff Management APIs ---

@app.route("/api/staff", methods=["GET"])
def get_staff():
    # Return list of staff from DB (enriched with face count)
    conn = db.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE role!='admin'")
    users = c.fetchall()
    conn.close()
    
    staff_list = []
    faces_dir = "faces"
    
    for u in users:
        user_dict = dict(u)
        user_dict.pop('password', None)
        user_dict.pop('temp_password', None)
        
        # Username is now the Staff ID (e.g., STF-001) in new items
        name = user_dict['username'] # This is the folder name too
        actual_name = user_dict.get('display_name') or user_dict.get('full_name') or name
        
        img_count = 0
        thumbnail = None
        
        user_path = os.path.join(faces_dir, name)
        if os.path.exists(user_path):
             images = [f for f in os.listdir(user_path) if f.endswith(('.jpg', '.png'))]
             img_count = len(images)
             if images:
                 thumbnail = f"faces/{name}/{images[0]}"
        
        staff_list.append({
            "name": actual_name, # Display Name
            "full_name": user_dict.get('full_name') or name,
            "display_name": user_dict.get('display_name') or '',
            "username": name,    # Login ID / Folder Name
            "images": img_count,
            "thumbnail": thumbnail,
            "details": user_dict
        })
    return jsonify(staff_list)

@app.route("/api/staff/detail/<username>")
def get_staff_detail(username):
    """Get single staff member details including leave balance."""
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = db.get_db_connection()
    c = conn.cursor()
    row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "Staff not found"}), 404
    
    info = dict(row)
    info.pop('password', None)
    info.pop('temp_password', None)
    return jsonify(info)

@app.route("/api/staff/start_preview", methods=["POST"])
def start_preview():
    """Start live preview from Pi camera for registration"""
    global capture_images
    
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    
    if rpi_client_sid is None:
        return jsonify({"error": "RPi camera not connected"}), 503
    
    data = request.json or {}
    staff_name = data.get("name", "NewStaff")
    
    # Reset capture state
    capture_images = []
    
    # Tell Pi to start preview mode
    socketio.emit('start_preview', {
        'staff_name': staff_name
    }, room=rpi_client_sid)
    
    logger.info(f"Preview started for: {staff_name}")
    return jsonify({"status": "ok"})

@app.route("/api/staff/preview_frame")
def get_preview_frame():
    """Return latest preview frame for HTTP polling"""
    if latest_preview_frame:
        return jsonify(latest_preview_frame)
    return jsonify({'image': None, 'face_detected': False, 'num_faces': 0})

@app.route("/api/staff/stop_preview", methods=["POST"])
def stop_preview():
    """Stop live preview and resume normal scanning"""
    global latest_preview_frame
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    
    if rpi_client_sid:
        socketio.emit('stop_preview', {}, room=rpi_client_sid)
    
    latest_preview_frame = None
    logger.info("Preview stopped")
    return jsonify({"status": "ok"})

@app.route("/api/staff/capture_now", methods=["POST"])
def capture_now():
    """Capture a single frame during preview mode"""
    global capture_complete
    
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    
    if rpi_client_sid is None:
        return jsonify({"error": "RPi camera not connected"}), 503
    
    data = request.json or {}
    staff_name = data.get("name", "NewStaff")
    
    capture_complete = False
    
    socketio.emit('capture_now', {
        'staff_name': staff_name
    }, room=rpi_client_sid)
    
    # Wait for capture response
    import eventlet
    timeout = 10
    start_time = time.time()
    while not capture_complete and (time.time() - start_time) < timeout:
        eventlet.sleep(0.3)
    
    if not capture_complete:
        return jsonify({"error": "Capture timeout"}), 504
    
    if not capture_images:
        return jsonify({"error": "No image captured"}), 500
    
    # Return the latest captured image
    return jsonify({
        "status": "ok",
        "image": capture_images[-1],
        "total_captured": len(capture_images)
    })

@app.route("/api/staff/save_captures", methods=["POST"])
def save_captures():
    """Save captured images from Pi to staff folder"""
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    staff_id = data.get("staff_id")
    images = data.get("images", [])
    
    if not staff_id or not images:
        return jsonify({"error": "Missing staff_id or images"}), 400
    
    # Save images to faces folder
    faces_dir = "faces"
    user_dir = os.path.join(faces_dir, staff_id)
    os.makedirs(user_dir, exist_ok=True)
    
    existing = len([f for f in os.listdir(user_dir) if f.endswith('.jpg')])
    saved_count = 0
    
    for i, img_b64 in enumerate(images):
        try:
            img_data = base64.b64decode(img_b64)
            filename = f"{existing + i + 1}.jpg"
            filepath = os.path.join(user_dir, filename)
            with open(filepath, 'wb') as f:
                f.write(img_data)
            saved_count += 1
        except Exception as e:
            logger.error(f"Failed to save capture {i}: {e}")
    
    logger.info(f"Saved {saved_count} captures for {staff_id}")
    
    # Auto-encode faces and reload recognizer after saving
    if saved_count > 0:
        try:
            import subprocess, sys
            result = subprocess.run(
                [sys.executable, "encode.py"], 
                check=True, capture_output=True, text=True, timeout=120
            )
            logger.info(f"Re-encoding after capture: {result.stdout.strip()}")
            
            global recognizer
            recognizer = Recognizer(enc_file="encodings.pkl", tolerance=Config.RECOGNITION_TOLERANCE)
            logger.info(f"Recognizer reloaded after saving captures for '{staff_id}'")
        except Exception as e:
            logger.error(f"Auto-encode after capture failed: {e}")
            # Fallback: inline encoding
            try:
                import face_recognition
                import pickle
                
                encodings_list = []
                names_list = []
                for person in os.listdir(faces_dir):
                    person_dir = os.path.join(faces_dir, person)
                    if not os.path.isdir(person_dir):
                        continue
                    for img_name in os.listdir(person_dir):
                        img_path = os.path.join(person_dir, img_name)
                        try:
                            image = face_recognition.load_image_file(img_path)
                            boxes = face_recognition.face_locations(image, model="hog")
                            if len(boxes) == 0:
                                continue
                            enc = face_recognition.face_encodings(image, boxes)[0]
                            encodings_list.append(enc)
                            names_list.append(person)
                        except Exception:
                            pass
                
                data_pkl = {"encodings": encodings_list, "names": names_list}
                with open("encodings.pkl", "wb") as f:
                    pickle.dump(data_pkl, f)
                
                recognizer = Recognizer(enc_file="encodings.pkl", tolerance=Config.RECOGNITION_TOLERANCE)
                logger.info(f"Inline re-encoding done: {len(encodings_list)} faces, recognizer reloaded")
            except Exception as e2:
                logger.error(f"Inline re-encoding also failed: {e2}")
    
    return jsonify({"status": "ok", "saved": saved_count})

@app.route("/api/rpi/status")
def rpi_status():
    """Check if RPi is connected and ready for capture"""
    is_connected = rpi_client_sid is not None
    is_rpi_online = (time.time() - last_rpi_heartbeat) < 15
    
    return jsonify({
        "connected": is_connected,
        "online": is_rpi_online,
        "sid": rpi_client_sid if is_connected else None
    })

@app.route("/api/encode", methods=["POST"])
def trigger_encode():
    """Trigger face encoding after new staff is registered"""
    global recognizer
    
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        import subprocess
        result = subprocess.run(["python", "encode.py"], capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            # Reload recognizer with new encodings
            recognizer = Recognizer(enc_file="encodings.pkl", tolerance=Config.RECOGNITION_TOLERANCE)
            logger.info("Face encodings updated and recognizer reloaded")
            return jsonify({"status": "ok", "message": "Encodings updated"})
        else:
            logger.error(f"Encode failed: {result.stderr}")
            return jsonify({"error": "Encoding failed", "details": result.stderr}), 500
            
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Encoding timeout"}), 504
    except Exception as e:
        logger.error(f"Encode error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/staff", methods=["POST"])
def add_staff():
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    full_name = request.form.get("name") # "name" form field is now Full Name
    if not full_name:
        return jsonify({"error": "Name required"}), 400
    
    display_name = request.form.get("display_name") # Short display name
        
    # Auto-Generators
    staff_id = db.generate_next_staff_id() # Logic to get STF-XXX
    import secrets
    temp_password = secrets.token_hex(4) # 8 char random hex
    
    # Extra Fields
    email = request.form.get('email')
    phone = request.form.get('phone')
    age = request.form.get('age')
    position = request.form.get('position')
    department = request.form.get('department')
    
    # Create User in DB
    # Username = Staff ID
    success = db.create_user(
        username=staff_id, 
        password="legacy_placeholder", # Won't be used if status is Inactive
        role="staff", 
        staff_id=staff_id, 
        email=email, 
        phone=phone, 
        age=age, 
        position=position, 
        department=department,
        full_name=full_name,
        status='Inactive',
        temp_password=temp_password,
        is_first_login=1,
        display_name=display_name
    )

    if success:
        if "image" in request.files:
            file = request.files["image"]
            if file.filename != '':
                # Save Image using STAFF ID as folder name
                faces_dir = "faces"
                user_dir = os.path.join(faces_dir, staff_id)
                os.makedirs(user_dir, exist_ok=True)
                
                existing = len([f for f in os.listdir(user_dir) if f.endswith('.jpg')])
                filename = f"{existing + 1}.jpg"
                file.save(os.path.join(user_dir, filename))
                
                # Trigger Training
                try:
                    import subprocess
                    subprocess.run(["python", "encode.py"], check=True)
                    global recognizer
                    recognizer = Recognizer(enc_file="encodings.pkl", tolerance=Config.RECOGNITION_TOLERANCE)
                except: pass

        return jsonify({
            "status": "ok", 
            "message": f"Staff created successfully.",
            "credentials": {
                "staff_id": staff_id,
                "temp_password": temp_password
            }
        })
    else:
        return jsonify({"error": "Failed to create user DB record"}), 500

@app.route("/api/staff/<username>", methods=["PUT"])
def update_staff(username):
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    db.update_user_details(
        username,
        data.get('staff_id'),
        data.get('email'),
        data.get('phone'),
        data.get('age'),
        data.get('position'),
        data.get('department'),
        data.get('name'), # 'name' field from form corresponds to Full Name
        data.get('display_name')
    )
    return jsonify({"status": "ok"})

@app.route("/api/staff/<name>", methods=["DELETE"])
def delete_staff(name):
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    
    # Delete from DB
    db.delete_user(name)
    logger.info(f"Deleted staff '{name}' from database")

    # Cascading delete: clean up all related records
    try:
        conn = db.get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM leave_requests WHERE username=?", (name,))
        c.execute("DELETE FROM attendance WHERE name=?", (name,))
        c.execute("DELETE FROM warnings WHERE username=?", (name,))
        c.execute("DELETE FROM late_appeals WHERE username=?", (name,))
        conn.commit()
        conn.close()
        logger.info(f"Cleaned up all related records for '{name}' (leaves, attendance, warnings, appeals)")
    except Exception as e:
        logger.error(f"Error cleaning up related records for '{name}': {e}")

    # Delete from File System
    faces_dir = "faces"
    user_dir = os.path.join(faces_dir, name)
    
    if os.path.exists(user_dir):
        import shutil
        shutil.rmtree(user_dir)
        logger.info(f"Deleted face images folder: {user_dir}")
    else:
        logger.warning(f"Face folder not found for '{name}' at {user_dir}")
    
    # Re-encode faces and reload recognizer
    encode_ok = False
    try:
        import sys
        import subprocess
        result = subprocess.run(
            [sys.executable, "encode.py"], 
            check=True, capture_output=True, text=True, timeout=120
        )
        logger.info(f"Re-encoding completed: {result.stdout.strip()}")
        if result.stderr:
            logger.warning(f"Re-encoding stderr: {result.stderr.strip()}")
        
        global recognizer
        recognizer = Recognizer(enc_file="encodings.pkl", tolerance=Config.RECOGNITION_TOLERANCE)
        logger.info(f"Recognizer reloaded after deleting '{name}'")
        encode_ok = True
    except Exception as e:
        logger.error(f"Subprocess re-encoding failed: {e}, trying inline re-encode...")
        # Fallback: re-encode inline without subprocess
        try:
            import face_recognition
            import pickle
            
            encodings_list = []
            names_list = []
            for person in os.listdir(faces_dir):
                person_dir = os.path.join(faces_dir, person)
                if not os.path.isdir(person_dir):
                    continue
                for img_name in os.listdir(person_dir):
                    img_path = os.path.join(person_dir, img_name)
                    try:
                        image = face_recognition.load_image_file(img_path)
                        boxes = face_recognition.face_locations(image, model="hog")
                        if len(boxes) == 0:
                            continue
                        enc = face_recognition.face_encodings(image, boxes)[0]
                        encodings_list.append(enc)
                        names_list.append(person)
                    except Exception:
                        pass
            
            data = {"encodings": encodings_list, "names": names_list}
            with open("encodings.pkl", "wb") as f:
                pickle.dump(data, f)
            
            recognizer = Recognizer(enc_file="encodings.pkl", tolerance=Config.RECOGNITION_TOLERANCE)
            logger.info(f"Inline re-encoding completed: {len(encodings_list)} faces, recognizer reloaded")
            encode_ok = True
        except Exception as e2:
            logger.error(f"Inline re-encoding also failed: {e2}")

    return jsonify({"status": "ok", "encoded": encode_ok})

@app.route("/api/staff/<name>/images", methods=["GET"])
def get_staff_images(name):
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
        
    faces_dir = "faces"
    user_path = os.path.join(faces_dir, name)
    
    if not os.path.exists(user_path):
        return jsonify([])
        
    images = [f"faces/{name}/{f}" for f in os.listdir(user_path) if f.endswith(('.jpg', '.png'))]
    return jsonify(images)

# --- Leave Management APIs ---

@app.route("/api/leave", methods=["GET"])
def get_leave():
    user = session.get("user")
    role = session.get("role")
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
        
    # Admin sees all, Staff sees own
    requests = db.get_leave_requests(None if role == 'admin' else user)
    return jsonify(requests)

 

# RE-DEFINING THE FUNCTIONS CLEANLY BELOW

@app.route("/api/leave", methods=["POST"])
def apply_leave():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    
    leave_type = request.form.get('type')
    start = request.form.get('start')
    end = request.form.get('end')
    reason = request.form.get('reason')
    
    # 1. File Upload
    attachment_path = None
    if 'attachment' in request.files:
        file = request.files['attachment']
        if file and file.filename != '':
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
            filename = f"{int(time.time())}_{file.filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            attachment_path = filename

    # 2. Validation
    # Overlap
    if db.check_overlap(user, start, end):
         return jsonify({"error": "Dates overlap with an existing request."}), 400

    # Medical Proof
    if leave_type == 'Medical' and not attachment_path:
        return jsonify({"error": "Medical leave requires a valid attachment (Proof)."}), 400

    # Annual Balance
    if leave_type == 'Annual':
        conn = db.get_db_connection()
        u = conn.execute("SELECT leave_balance FROM users WHERE username=?", (user,)).fetchone()
        conn.close()
        
        from datetime import datetime
        try:
             if not start or not end:
                 return jsonify({"error": "Start and End dates are required."}), 400
                 
             d1 = datetime.strptime(start, "%Y-%m-%d")
             d2 = datetime.strptime(end, "%Y-%m-%d")
             days = abs((d2 - d1).days) + 1
             
             if u and u['leave_balance'] < days:
                 return jsonify({"error": f"Insufficient leave balance. You have {u['leave_balance']} days left, but requested {days} days."}), 400
        except Exception as e:
             logger.error(f"Date parsing error: {e}")
             return jsonify({"error": f"Invalid date format: {e}"}), 400

    db.add_leave_request(user, leave_type, start, end, reason, attachment_path)
    return jsonify({"status": "ok"})

@app.route('/api/attendance/staff/<username>')
def get_staff_attendance(username):
    # Get last 50 logs for this user from RAM or DB
    # Currently we rely on DB `attendance` table
    conn = db.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM attendance WHERE name=? ORDER BY timestamp DESC LIMIT 50", (username,))
    rows = c.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/leave/<id>/status", methods=["POST"])
def update_leave_status_route(id):
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
        
    status = request.json.get("status")
    result = db.update_leave_status(id, status)
    
    if result == "Insufficient balance":
        return jsonify({"error": "Cannot approve: Staff has insufficient leave balance."}), 400
    
    if not result:
        return jsonify({"error": "Failed to update status."}), 500
        
    return jsonify({"status": "ok"})

@app.route("/api/leave/<id>", methods=["POST"])
def update_leave_details_route(id):
    user = session.get("user")
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Check ownership and fetch existing
    conn = db.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM leave_requests WHERE id=?", (id,))
    req = c.fetchone()
    conn.close()
    
    if not req:
        return jsonify({"error": "Not found"}), 404
        
    if req['username'] != user and session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
        
    if req['status'] != 'Pending' and session.get("role") != "admin":
        return jsonify({"error": "Cannot edit non-pending requests"}), 400

    # Data
    l_type = request.form.get('type')
    start = request.form.get('start')
    end = request.form.get('end')
    reason = request.form.get('reason')
    
    # 1. File Upload
    attachment_path = req['attachment_path'] # Default to existing
    if 'attachment' in request.files:
        file = request.files['attachment']
        if file and file.filename != '':
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
            filename = f"{int(time.time())}_{file.filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            attachment_path = filename

    # 2. Validation
    # Overlap (Exclude self)
    if db.check_overlap(req['username'], start, end, exclude_id=id):
         return jsonify({"error": "Dates overlap with an existing request."}), 400

    # Medical Proof
    if l_type == 'Medical' and not attachment_path:
        return jsonify({"error": "Medical leave requires a valid attachment (Proof)."}), 400

    # Annual Balance
    if l_type == 'Annual':
        conn = db.get_db_connection()
        u = conn.execute("SELECT leave_balance FROM users WHERE username=?", (req['username'],)).fetchone()
        conn.close()
        try:
             d1 = datetime.strptime(start, "%Y-%m-%d")
             d2 = datetime.strptime(end, "%Y-%m-%d")
             days = abs((d2 - d1).days) + 1
             if u and u['leave_balance'] < days:
                 return jsonify({"error": f"Insufficient leave balance. You have {u['leave_balance']} days left."}), 400
        except ValueError:
             return jsonify({"error": "Invalid date format"}), 400

    db.update_leave_request_details(id, l_type, start, end, reason, attachment_path)
    return jsonify({"status": "ok"})


@app.route("/api/leave/<int:id>", methods=["DELETE"])
def delete_leave_request(id):
    """Staff can cancel their own pending leave request, admin can cancel any."""
    user = session.get("user")
    role = session.get("role")
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    
    conn = db.get_db_connection()
    c = conn.cursor()
    try:
        req = c.execute("SELECT * FROM leave_requests WHERE id=?", (id,)).fetchone()
        if not req:
            conn.close()
            return jsonify({"error": "Leave request not found"}), 404
        
        # Staff can only delete their own pending requests
        if role != "admin":
            if req['username'] != user:
                conn.close()
                return jsonify({"error": "You can only cancel your own requests"}), 403
            if req['status'] != 'Pending':
                conn.close()
                return jsonify({"error": "Only pending requests can be cancelled"}), 400
        
        c.execute("DELETE FROM leave_requests WHERE id=?", (id,))
        conn.commit()
        logger.info(f"Leave request {id} deleted by {user}")
        return jsonify({"status": "ok", "message": "Leave request cancelled"})
    except Exception as e:
        logger.error(f"Error deleting leave request: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# --- Late Appeal & Warning APIs ---

@app.route("/api/late-appeal", methods=["POST"])
def submit_late_appeal():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    date = request.form.get('date')
    arrival_time = request.form.get('arrival_time')
    reason = request.form.get('reason')

    if not date or not reason:
        return jsonify({"error": "Date and reason are required"}), 400

    # Handle proof file upload
    attachment_path = None
    if 'attachment' in request.files:
        file = request.files['attachment']
        if file and file.filename != '':
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])
            filename = f"{int(time.time())}_{file.filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            attachment_path = filename

    result = db.add_late_appeal(user, date, arrival_time, reason, attachment_path)
    if result:
        return jsonify({"status": "ok"})
    return jsonify({"error": "Failed to submit appeal"}), 500


@app.route("/api/late-appeals", methods=["GET"])
def get_late_appeals():
    user = session.get("user")
    role = session.get("role")
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    if role == "admin":
        appeals = db.get_late_appeals()
        # Enrich with display names
        conn = db.get_db_connection()
        for appeal in appeals:
            u = conn.execute("SELECT display_name, full_name FROM users WHERE username=?", (appeal['username'],)).fetchone()
            if u:
                appeal['display_name'] = u['display_name'] or u['full_name'] or appeal['username']
        conn.close()
    else:
        appeals = db.get_late_appeals(username=user)

    return jsonify(appeals)


@app.route("/api/late-appeal/<int:id>", methods=["PUT"])
def update_late_appeal(id):
    role = session.get("role")
    if role != "admin":
        return jsonify({"error": "Admin only"}), 403

    data = request.json
    status = data.get("status")
    admin_note = data.get("admin_note", "")

    if status not in ["Approved", "Rejected"]:
        return jsonify({"error": "Invalid status"}), 400

    result = db.update_late_appeal_status(id, status, admin_note)
    if result:
        return jsonify({"status": "ok"})
    return jsonify({"error": "Failed to update appeal"}), 500


@app.route("/api/attendance-flags", methods=["GET"])
def get_attendance_flags():
    """Get staff members with high late/absent counts this month."""
    role = session.get("role")
    if role != "admin":
        return jsonify({"error": "Admin only"}), 403

    current_month = datetime.now().strftime('%Y-%m')

    # Get all staff users
    conn = db.get_db_connection()
    staff = conn.execute("SELECT username, display_name, full_name, staff_id FROM users WHERE role='staff' AND status='Active'").fetchall()
    conn.close()

    flags = []
    for s in staff:
        username = s['username']
        summary = db.get_monthly_attendance_summary(username, current_month)

        # Flag if 2+ unexcused lates (warn before threshold)
        if summary['unexcused_late'] >= 2 or summary['late'] >= 2:
            # Check existing warnings this month
            warnings = db.get_warnings(username)
            month_warnings = [w for w in warnings if w['month'] == current_month]
            current_level = max([w['level'] for w in month_warnings], default=0)

            flags.append({
                'username': username,
                'display_name': s['display_name'] or s['full_name'] or username,
                'staff_id': s['staff_id'],
                'on_time': summary['on_time'],
                'late': summary['late'],
                'excused': summary['excused'],
                'unexcused_late': summary['unexcused_late'],
                'current_warning_level': current_level,
                'month': current_month
            })

    return jsonify(flags)


@app.route("/api/warning", methods=["POST"])
def issue_warning():
    role = session.get("role")
    admin_user = session.get("user")
    if role != "admin":
        return jsonify({"error": "Admin only"}), 403

    data = request.json
    username = data.get("username")
    level = data.get("level")
    reason = data.get("reason")
    month = data.get("month", datetime.now().strftime('%Y-%m'))

    if not username or not level or not reason:
        return jsonify({"error": "Username, level, and reason are required"}), 400

    result = db.add_warning(username, level, reason, month, admin_user)
    if result:
        return jsonify({"status": "ok"})
    return jsonify({"error": "Failed to issue warning"}), 500


@app.route("/api/warnings", methods=["GET"])
def get_warnings_route():
    user = session.get("user")
    role = session.get("role")
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    if role == "admin":
        username = request.args.get("username")
        warnings = db.get_warnings(username)
        # Enrich with display names
        conn = db.get_db_connection()
        for w in warnings:
            u = conn.execute("SELECT display_name, full_name FROM users WHERE username=?", (w['username'],)).fetchone()
            if u:
                w['display_name'] = u['display_name'] or u['full_name'] or w['username']
        conn.close()
    else:
        warnings = db.get_warnings(username=user)

    return jsonify(warnings)


@app.route("/api/attendance/summary/<username>", methods=["GET"])
def attendance_summary(username):
    user = session.get("user")
    role = session.get("role")
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    # Staff can only see their own summary
    if role != "admin" and user != username:
        return jsonify({"error": "Forbidden"}), 403

    month = request.args.get("month", datetime.now().strftime('%Y-%m'))
    summary = db.get_monthly_attendance_summary(username, month)
    return jsonify(summary)

@app.route("/api/staff-leave-balances")
def staff_leave_balances():
    """Admin endpoint: get all staff leave balance info."""
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    balances = db.get_all_staff_leave_balances()
    return jsonify({
        "staff": balances,
        "policy": {
            "annual_entitlement": db.ANNUAL_ENTITLEMENT,
            "max_carry_forward": db.MAX_CARRY_FORWARD,
            "carry_forward_expiry": f"March 31"
        }
    })

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    initialize_system()
    db.run_leave_maintenance()  # Auto-expire old leaves + annual balance reset
    port = Config.SERVER_PORT
    logger.info(f"Starting Server on 0.0.0.0:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=Config.DEBUG_MODE)
