# pi_client.py - Enhanced with Hardware Support
# Raspberry Pi Zero 2 W with Camera Module 3, I2C LCD, and LEDs

import cv2 
import base64
import time
import socketio
from threading import Event
from aes_utils import load_key, encrypt_bytes, b64_encode_bytes
from picamera2 import Picamera2 
import os

# === HARDWARE IMPORTS ===
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    print("[WARN] RPi.GPIO not available - LED control disabled")
    GPIO_AVAILABLE = False

try:
    from RPLCD.i2c import CharLCD
    LCD_AVAILABLE = True
except ImportError:
    print("[WARN] RPLCD not available - LCD control disabled")
    LCD_AVAILABLE = False

# === CONFIGURATION ===
SERVER_URL = "http://192.168.100.203:5000"  # REPLACE WITH YOUR SERVER IP
CAMERA_ID = "pi_zero_2"
FPS = 2  # frames per second to send
AES_KEY_PATH = "aes_key.bin"

# GPIO Pin Configuration
GREEN_LED_PIN = 17  # BCM pin for Green LED (recognized)
RED_LED_PIN = 27    # BCM pin for Red LED (unknown/no face)

# LCD Configuration (I2C 1602)
LCD_I2C_ADDRESS = 0x27  # Common address, use `i2cdetect -y 1` to verify
LCD_I2C_PORT = 1        # I2C port (usually 1 on Pi Zero 2 W)

# === SOCKETIO SETUP ===
sio = socketio.Client()
last_result = None
result_event = Event()
picam2_instance = None  # Will be set in main() for capture mode access
preview_active = False  # Preview mode for registration

# === FACE DETECTION (for preview green rectangles) ===
face_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
face_cascade = cv2.CascadeClassifier(face_cascade_path)
print(f"[OK] Face cascade loaded: {face_cascade_path}")

# === HARDWARE INITIALIZATION ===
lcd = None  # Will be initialized in main()

if GPIO_AVAILABLE:
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(GREEN_LED_PIN, GPIO.OUT)
        GPIO.setup(RED_LED_PIN, GPIO.OUT)
        # Turn both LEDs off initially
        GPIO.output(GREEN_LED_PIN, GPIO.LOW)
        GPIO.output(RED_LED_PIN, GPIO.LOW)
        print("[OK] GPIO Initialized")

        # === LED QUICK TEST ===
        GPIO.output(GREEN_LED_PIN, GPIO.HIGH)
        time.sleep(1)
        GPIO.output(GREEN_LED_PIN, GPIO.LOW)

        GPIO.output(RED_LED_PIN, GPIO.HIGH)
        time.sleep(1)
        GPIO.output(RED_LED_PIN, GPIO.LOW)
        # === END TEST ===

    except Exception as e:
        print(f"[ERROR] GPIO Init Failed: {e}")

# === AES KEY ===
try:
    AES_KEY = load_key(AES_KEY_PATH)
    print(f"[OK] Loaded AES key from {AES_KEY_PATH}")
except Exception as e:
    print(f"[ERROR] Failed to load AES key: {e}")
    AES_KEY = None

# === LCD FUNCTIONS ===
def lcd_display(line1, line2=""):
    """Display text on LCD (16x2)"""
    if lcd is None:
        return
    try:
        lcd.clear()
        # Truncate to 16 chars per line
        lcd.cursor_pos = (0, 0)
        lcd.write_string(line1[:16].center(16))
        lcd.cursor_pos = (1, 0)
        lcd.write_string(line2[:16].center(16))
    except Exception as e:
        print(f"[LCD Error] {e}")

# === LED FUNCTIONS ===
def set_leds(recognized=False):
    """
    Control LEDs based on recognition result
    - recognized=True: Green ON, Red OFF
    - recognized=False: Green OFF, Red ON
    """
    if not GPIO_AVAILABLE:
        return
    try:
        if recognized:
            GPIO.output(GREEN_LED_PIN, GPIO.HIGH)
            GPIO.output(RED_LED_PIN, GPIO.LOW)
        else:
            GPIO.output(GREEN_LED_PIN, GPIO.LOW)
            GPIO.output(RED_LED_PIN, GPIO.HIGH)
    except Exception as e:
        print(f"[LED Error] {e}")

def leds_off():
    """Turn both LEDs off"""
    if not GPIO_AVAILABLE:
        return
    try:
        GPIO.output(GREEN_LED_PIN, GPIO.LOW)
        GPIO.output(RED_LED_PIN, GPIO.LOW)
    except:
        pass

# === SOCKET.IO EVENTS ===
@sio.event
def connect():
    print("[SOCKET] Connected to server")
    lcd_display("Hi! Facial", "Recognition Sys")
    time.sleep(1.5)
    # Register as RPi client so server can send capture requests
    sio.emit('rpi_register', {'camera_id': CAMERA_ID})

@sio.event
def disconnect():
    print("[SOCKET] Disconnected from server")
    lcd_display("Disconnected", "Check Network")
    leds_off()

@sio.on('rpi_registered')
def on_rpi_registered(data):
    print("[SOCKET] Registered as RPi client with server")
    lcd_display("System Ready", "Show your face")

@sio.on('result')
def on_result(data):
    global last_result
    last_result = data
    result_event.set()

@sio.on('start_preview')
def on_start_preview(data):
    """Admin wants to see live preview for registration"""
    global preview_active
    preview_active = True
    staff_name = data.get('staff_name', 'NewStaff')
    print(f"[PREVIEW] Starting preview mode for: {staff_name}")
    lcd_display("REGISTRATION", staff_name[:16])
    # Blink green LED to indicate preview mode
    if GPIO_AVAILABLE:
        for _ in range(3):
            GPIO.output(GREEN_LED_PIN, GPIO.HIGH)
            time.sleep(0.15)
            GPIO.output(GREEN_LED_PIN, GPIO.LOW)
            time.sleep(0.15)

@sio.on('stop_preview')
def on_stop_preview(data=None):
    """Admin stopped preview - resume normal scanning"""
    global preview_active
    preview_active = False
    print("[PREVIEW] Preview mode stopped")
    lcd_display("Welcome To", "Face Attendance")
    leds_off()

@sio.on('capture_now')
def on_capture_now(data):
    """Capture a single high-quality frame during preview"""
    global picam2_instance
    
    print("[CAPTURE] Taking photo...")
    lcd_display("Capturing...", "Hold Still!")
    
    try:
        frame = picam2_instance.capture_array()
        # Fix frame format: Picamera2 may return 4-channel XRGB
        if len(frame.shape) == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        # Convert to JPEG (high quality)
        ret, jpg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if ret:
            img_b64 = base64.b64encode(jpg.tobytes()).decode('utf-8')
            sio.emit('capture_response', {
                'status': 'ok',
                'images': [img_b64],
                'staff_name': data.get('staff_name', 'NewStaff')
            })
            print("[CAPTURE] Photo sent to server")
            lcd_display("Photo Taken!", "")
            # Flash green LED
            if GPIO_AVAILABLE:
                GPIO.output(GREEN_LED_PIN, GPIO.HIGH)
                time.sleep(0.5)
                GPIO.output(GREEN_LED_PIN, GPIO.LOW)
        else:
            sio.emit('capture_response', {'status': 'error', 'reason': 'encode_failed'})
    except Exception as e:
        print(f"[CAPTURE ERROR] {e}")
        sio.emit('capture_response', {'status': 'error', 'reason': str(e)})
    
    lcd_display("REGISTRATION", "Ready...")

# === UTILITY FUNCTIONS ===
def encrypt_and_send_jpeg(jpeg_bytes):
    if AES_KEY is None:
        print("[ERROR] No AES key loaded; cannot encrypt")
        return False
    enc = encrypt_bytes(jpeg_bytes, AES_KEY)
    b64 = b64_encode_bytes(enc)
    payload = {'camera_id': CAMERA_ID, 'image': b64}
    sio.emit('frame_encrypted', payload)
    return True

def capture_jpeg_from_cv_frame(frame_bgr, quality=70):
    ret, jpg = cv2.imencode('.jpg', frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ret:
        return None
    return jpg.tobytes()

# === RESULT HANDLER ===
display_until = 0  # timestamp until which we should keep current LCD/LED state

def handle_result(result):
    """
    Process recognition result and update LCD + LEDs
    """
    global display_until
    
    name = result.get('name', 'Error')
    status = result.get('status', '')
    
    print(f"[RESULT] {name} | status={status}")
    
    # If we're still showing a previous result, skip NoFace updates
    if name == 'NoFace' and time.time() < display_until:
        return
    
    if status == 'error':
        reason = result.get('reason', 'Unknown')
        lcd_display("Error", reason[:16])
        set_leds(recognized=False)
        display_until = time.time() + 3
        
    elif name == 'NoFace':
        # Only reaches here if cooldown expired
        lcd_display("Welcome To", "Face Attendance")
        leds_off()
        
    elif name == 'Unknown':
        lcd_display("Access Denied", "Not Registered")
        set_leds(recognized=False)  # RED LED ON
        display_until = time.time() + 3
        
    elif status == 'ignored_duplicate':
        # Already recorded today
        lcd_display(f"Hai {name[:12]}", "Already Logged")
        set_leds(recognized=True)  # GREEN LED ON
        display_until = time.time() + 3
        
    else:
        # NEW attendance recorded!
        lcd_display(f"Hai {name[:12]}", "Access Granted!")
        set_leds(recognized=True)  # GREEN LED ON
        display_until = time.time() + 4

# === MAIN LOOP ===
def main():
    print("=" * 50)
    print("  Facial Recognition Client - Raspberry Pi")
    print("=" * 50)
    print(f"Server: {SERVER_URL}")
    print(f"Camera: Picamera2 (Camera Module 3)")
    print(f"FPS: {FPS}")
    print("=" * 50)
    
    # === LCD INITIALIZATION (after GPIO is ready) ===
    global lcd
    if LCD_AVAILABLE and lcd is None:
        for attempt in range(3):
            try:
                time.sleep(1)
                lcd = CharLCD(
                    i2c_expander='PCF8574',
                    address=LCD_I2C_ADDRESS,
                    port=LCD_I2C_PORT,
                    cols=16,
                    rows=2,
                    charmap='A00'
                )
                lcd.clear()
                lcd.write_string("System Starting")
                print("[OK] LCD Initialized")
                break
            except Exception as e:
                print(f"[WARN] LCD attempt {attempt+1}/3: {e}")
                lcd = None
                if attempt < 2:
                    time.sleep(2)
        if lcd is None:
            print("[ERROR] LCD Failed - continuing without display")
    
    lcd_display("Connecting...", SERVER_URL.split("//")[1][:16])
    
    try:
        sio.connect(SERVER_URL)
    except Exception as e:
        print(f"[ERROR] Cannot connect to server: {e}")
        lcd_display("Conn Failed", "Check Server")
        return

    # === CAMERA SETUP ===
    global picam2_instance
    picam2 = Picamera2()
    picam2.configure(
        picam2.create_video_configuration(
            main={"size": (640, 480)},
        controls={
            "AwbEnable": True,
            "AeEnable": True
        }
        )
    )
    picam2.start()
    picam2_instance = picam2  # Allow capture handler to access camera
    print("[OK] Camera started")
    
    lcd_display("Welcome To", "Face Attendance")

    try:
        while True:
            start = time.time()

            # Capture frame
            frame = picam2.capture_array()
            # Fix color: Picamera2 outputs XRGB (4-channel), convert to BGR for OpenCV
            if len(frame.shape) == 3 and frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            frame_small = cv2.resize(frame, (320, 240))

            if preview_active:
                # === PREVIEW MODE: stream with face detection ===
                try:
                    # Fix frame format: Picamera2 may return 4-channel XRGB
                    if len(frame_small.shape) == 3 and frame_small.shape[2] == 4:
                        frame_bgr = cv2.cvtColor(frame_small, cv2.COLOR_BGRA2BGR)
                    else:
                        frame_bgr = frame_small
                    
                    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=3, minSize=(30, 30))
                    
                    # Draw green rectangles around detected faces
                    preview_frame = frame_bgr.copy()
                    face_detected = len(faces) > 0
                    for (x, y, w, h) in faces:
                        cv2.rectangle(preview_frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                        cv2.putText(preview_frame, 'Face OK', (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    
                    # Send preview frame to server (unencrypted, for speed)
                    ret, jpg = cv2.imencode('.jpg', preview_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
                    if ret:
                        img_b64 = base64.b64encode(jpg.tobytes()).decode('utf-8')
                        sio.emit('preview_frame', {
                            'image': img_b64,
                            'face_detected': face_detected,
                            'num_faces': len(faces)
                        })
                        print(f"[PREVIEW] Frame sent | faces={len(faces)}")
                    
                    # LED feedback during preview
                    if face_detected and GPIO_AVAILABLE:
                        GPIO.output(GREEN_LED_PIN, GPIO.HIGH)
                        GPIO.output(RED_LED_PIN, GPIO.LOW)
                    elif GPIO_AVAILABLE:
                        GPIO.output(GREEN_LED_PIN, GPIO.LOW)
                        GPIO.output(RED_LED_PIN, GPIO.HIGH)
                
                except Exception as e:
                    print(f"[PREVIEW ERROR] {e}")
                
                # Preview at ~5 FPS
                elapsed = time.time() - start
                time.sleep(max(0, 0.2 - elapsed))
            else:
                # === NORMAL MODE: recognition ===
                jpeg_bytes = capture_jpeg_from_cv_frame(frame_small, quality=85)

                if jpeg_bytes is None:
                    print("[ERROR] JPEG encode failed")
                    continue

                # Send encrypted frame
                sent = encrypt_and_send_jpeg(jpeg_bytes)
                
                if sent:
                    result_event.clear()
                    if result_event.wait(timeout=5.0):
                        handle_result(last_result)
                        
                        # If we just showed a recognition result, wait before next frame
                        if time.time() < display_until:
                            remaining = display_until - time.time()
                            time.sleep(max(0, remaining))
                            leds_off()
                    else:
                        print("[WARN] No response from server")

                # Maintain FPS
                elapsed = time.time() - start
                time.sleep(max(0, 1.0 / FPS - elapsed))

    except KeyboardInterrupt:
        print("\n[INFO] Stopping client...")

    finally:
        lcd_display("System", "Shutting Down")
        time.sleep(1)
        if lcd:
            lcd.clear()
        leds_off()
        if GPIO_AVAILABLE:
            GPIO.cleanup()
        picam2.stop()
        sio.disconnect()
        print("[OK] Cleanup complete")


if __name__ == "__main__":
    main()

