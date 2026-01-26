# server.py
import os
os.environ["EVENTLET_NO_GREENDNS"] = "yes"

import base64
import io
import traceback
import cv2
import time
from PIL import Image
from flask import Flask, jsonify, request, send_from_directory, Response, session, redirect
from flask_socketio import SocketIO, emit
from config import Config
from utils import setup_logger, validate_date_format
from recognition import Recognizer
import db
from aes_utils import load_key, b64_decode_to_bytes, decrypt_bytes

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

# --- Socket.IO Events ---

@socketio.on('connect')
def handle_connect():
    sid = request.sid
    active_clients.add(sid)
    logger.info(f"Client connected: {sid} (Total: {len(active_clients)})")
    emit('server_msg', {'msg': 'welcome', 'config': {'tolerance': Config.RECOGNITION_TOLERANCE}})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in active_clients:
        active_clients.remove(sid)
    logger.info(f"Client disconnected: {sid}")

@socketio.on('frame_encrypted')
def handle_frame(data):
    """
    data: { 'camera_id': 'pi0', 'image': '<base64 of iv+ciphertext>' }
    """
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
            
            emit('result', {'status': status, 'name': name, 'distance': dist})
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
    return jsonify({
        "status": "healthy",
        "clients": len(active_clients),
        "aes_loaded": AES_KEY is not None,
        "recognizer_ready": recognizer is not None,
        "db_path": Config.DB_PATH
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
        actual_name = user_dict.get('full_name', name)
        
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
            "username": name,    # Login ID / Folder Name
            "images": img_count,
            "thumbnail": thumbnail,
            "details": user_dict
        })
    return jsonify(staff_list)

@app.route("/api/staff", methods=["POST"])
def add_staff():
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401

    full_name = request.form.get("name") # "name" form field is now Full Name
    if not full_name:
        return jsonify({"error": "Name required"}), 400
        
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
        is_first_login=1
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
        data.get('department')
    )
    return jsonify({"status": "ok"})

@app.route("/api/staff/<name>", methods=["DELETE"])
def delete_staff(name):
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    
    # Delete from DB
    db.delete_user(name)

    # Delete from File System
    faces_dir = "faces"
    user_dir = os.path.join(faces_dir, name)
    
    if os.path.exists(user_dir):
        import shutil
        shutil.rmtree(user_dir)
        
        try:
            import subprocess
            subprocess.run(["python", "encode.py"], check=True)
            global recognizer
            recognizer = Recognizer(enc_file="encodings.pkl", tolerance=Config.RECOGNITION_TOLERANCE)
        except Exception as e:
             logger.error(f"Re-encoding failed after delete: {e}")

    return jsonify({"status": "ok"})

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


@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    initialize_system()
    port = Config.SERVER_PORT
    logger.info(f"Starting Server on 0.0.0.0:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=Config.DEBUG_MODE)
