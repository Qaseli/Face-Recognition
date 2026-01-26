# db.py
import sqlite3
from datetime import datetime, timedelta
from config import Config
from utils import setup_logger

logger = setup_logger("DB")

def get_db_connection():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    timestamp TEXT,
                    camera_id TEXT,
                    confidence REAL
                )""")
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    password TEXT,
                    role TEXT DEFAULT 'staff',
                    leave_balance INTEGER DEFAULT 14
                )""")
    
    # Try adding column if not exists (migratiom)
    try:
        c.execute("ALTER TABLE users ADD COLUMN leave_balance INTEGER DEFAULT 14")
    except Exception:
        pass
    
    c.execute("""CREATE TABLE IF NOT EXISTS leave_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    type TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    reason TEXT,
                    status TEXT DEFAULT 'Pending',
                    created_at TEXT,
                    attachment_path TEXT
                )""")
    
    # Migrations
    try:
        c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'staff'")
    except Exception: pass
    
    try:
        c.execute("ALTER TABLE users ADD COLUMN staff_id TEXT")
    except Exception: pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN email TEXT")
    except Exception: pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN phone TEXT")
    except Exception: pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN age INTEGER")
    except Exception: pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN position TEXT")
    except Exception: pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN department TEXT")
    except Exception: pass

    try:
        c.execute("ALTER TABLE leave_requests ADD COLUMN attachment_path TEXT")
    except Exception: pass

    try:
        c.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'Active'")
    except Exception: pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN temp_password TEXT")
    except Exception: pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN is_first_login INTEGER DEFAULT 0")
    except Exception: pass
    try:
        c.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
    except Exception: pass

    c.execute("SELECT * FROM users WHERE username=?", ("admin",))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (username, password, role, leave_balance) VALUES (?, ?, ?, ?)", ("admin", "admin123", "admin", 0))
    else:
        # Always reset admin credentials for development
        c.execute("UPDATE users SET password='admin123', role='admin' WHERE username='admin'")

    conn.commit()
    # Add index for faster timestamp queries (safe for existing databases)
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON attendance(timestamp)")
    except Exception:
        pass  # Index already exists or column doesn't exist yet
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {Config.DB_PATH}")

def generate_next_staff_id():
    """Generates the next available Staff ID in format STF-XXX"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE username LIKE 'STF-%'")
    rows = c.fetchall()
    conn.close()
    
    max_id = 0
    import re
    for r in rows:
        match = re.search(r'STF-(\d+)', r['username'])
        if match:
            num = int(match.group(1))
            if num > max_id:
                max_id = num
    
    return f"STF-{max_id + 1:03d}"

def add_record(name, camera_id="pi0", confidence=0.0):
    conn = get_db_connection()
    c = conn.cursor()
    ts = datetime.utcnow().isoformat()
    c.execute("INSERT INTO attendance (name, timestamp, camera_id, confidence) VALUES (?, ?, ?, ?)",
              (name, ts, camera_id, confidence))
    conn.commit()
    conn.close()
    logger.info(f"Recorded attendance for {name} (cam: {camera_id}, conf: {confidence:.2f})")

def is_duplicate_entry(name, cooldown_seconds):
    """Checks if the person has a recent entry within the cooldown period."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Calculate cutoff time
    cutoff = (datetime.utcnow() - timedelta(seconds=cooldown_seconds)).isoformat()
    
    c.execute("SELECT id FROM attendance WHERE name = ? AND timestamp > ? ORDER BY timestamp DESC LIMIT 1",
              (name, cutoff))
    result = c.fetchone()
    conn.close()
    return result is not None

def get_recent_paginated(page=1, per_page=50):
    conn = get_db_connection()
    c = conn.cursor()
    offset = (page - 1) * per_page
    
    c.execute("SELECT name, timestamp, camera_id, confidence FROM attendance ORDER BY id DESC LIMIT ? OFFSET ?", 
              (per_page, offset))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_by_date_range(start_date, end_date):
    """
    start_date, end_date: strings in 'YYYY-MM-DD' format
    returns entries between start_date 00:00:00 and end_date 23:59:59
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    # Add time components to cover the full day
    start_ts = f"{start_date}T00:00:00"
    end_ts = f"{end_date}T23:59:59"
    
    c.execute("""SELECT name, timestamp, camera_id, confidence 
                 FROM attendance 
                 WHERE timestamp BETWEEN ? AND ? 
                 ORDER BY timestamp DESC""", 
              (start_ts, end_ts))
    
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_stats_last_7_days():
    """Returns daily counts for the last 7 days"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # SQLite doesn't have great date functions, but ISO format allows string comparison/substr
    # We want to group by day. substr(timestamp, 1, 10) gives YYYY-MM-DD
    
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    
    c.execute("""
        SELECT substr(timestamp, 1, 10) as day, COUNT(*) as count 
        FROM attendance 
        WHERE timestamp > ? 
        GROUP BY day 
        ORDER BY day ASC
    """, (cutoff,))
    
    rows = c.fetchall()
    conn.close()
    return {row['day']: row['count'] for row in rows}

def verify_user(username, password):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    
    if row:
        # Check active status first
        if row['status'] == 'Inactive':
            # Allow login ONLY if temp_password matches
            if row['temp_password'] == password:
                return dict(row)
            return None 
            
        # Active
        if row['password'] == password:
            return dict(row)
            
    return None

def create_user(username, password, role='staff', staff_id=None, email=None, phone=None, age=None, position=None, department=None, full_name=None, status='Active', temp_password=None, is_first_login=0):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""INSERT INTO users 
                     (username, password, role, leave_balance, staff_id, email, phone, age, position, department, full_name, status, temp_password, is_first_login) 
                     VALUES (?, ?, ?, 14, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                  (username, password, role, staff_id, email, phone, age, position, department, full_name, status, temp_password, is_first_login))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to create user {username}: {e}")
        return False
    finally:
        conn.close()

def update_user_details(username, staff_id, email, phone, age, position, department):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""UPDATE users 
                     SET staff_id=?, email=?, phone=?, age=?, position=?, department=? 
                     WHERE username=?""", 
                  (staff_id, email, phone, age, position, department, username))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to update user {username}: {e}")
        return False
    finally:
        conn.close()

def add_leave_request(username, type, start, end, reason, attachment_path=None):
    conn = get_db_connection()
    c = conn.cursor()
    created_at = datetime.utcnow().isoformat()
    c.execute("INSERT INTO leave_requests (username, type, start_date, end_date, reason, created_at, attachment_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (username, type, start, end, reason, created_at, attachment_path))
    conn.commit()
    conn.close()

def get_leave_requests(username=None):
    conn = get_db_connection()
    c = conn.cursor()
    if username and username != 'admin': 
        c.execute("SELECT * FROM leave_requests WHERE username=? ORDER BY created_at DESC", (username,))
    else:
        c.execute("SELECT * FROM leave_requests ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_user(username):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM users WHERE username=?", (username,))
        # Optional: Delete attendance records too?
        # c.execute("DELETE FROM attendance WHERE name=?", (username,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to delete user {username} from DB: {e}")
        return False
    finally:
        conn.close()

def change_password(username, new_password):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""UPDATE users 
                     SET password=?, temp_password=NULL, status='Active', is_first_login=0 
                     WHERE username=?""", 
                  (new_password, username))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to change password for {username}: {e}")
        return False
    finally:
        conn.close()

def check_overlap(username, start_date, end_date, exclude_id=None):
    """
    Returns True if the new dates overlap with any existing (non-Rejected) request.
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    query = """
        SELECT id FROM leave_requests 
        WHERE username = ? 
        AND status != 'Rejected'
        AND start_date <= ? 
        AND end_date >= ?
    """
    params = [username, end_date, start_date]

    if exclude_id:
        query += " AND id != ?"
        params.append(exclude_id)
        
    c.execute(query, tuple(params))
    row = c.fetchone()
    conn.close()
    return row is not None

def update_leave_status(id, status):
    """
    Update status. If status is Approved and type is Annual, deduct balance.
    PREVENT negative balance.
    """
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        c.execute("SELECT * FROM leave_requests WHERE id=?", (id,))
        req = c.fetchone()
        
        if not req:
            return False

        current_status = req['status']
        leave_type = req['type']
        username = req['username']

        # DEDUCTION LOGIC (Only on transition to Approved)
        if status == 'Approved' and current_status != 'Approved':
            if leave_type == 'Annual':
                # Calculate Duration
                d1 = datetime.strptime(req['start_date'], "%Y-%m-%d")
                d2 = datetime.strptime(req['end_date'], "%Y-%m-%d")
                days = abs((d2 - d1).days) + 1
                
                # Check Balance
                c.execute("SELECT leave_balance FROM users WHERE username=?", (username,))
                user_row = c.fetchone()
                if not user_row: 
                    return False
                
                current_balance = user_row['leave_balance']
                
                if current_balance < days:
                    # REJECT approval if insufficient balance
                    logger.warning(f"Prevented approval for {username}: Insufficient balance ({current_balance} < {days})")
                    return "Insufficient balance" # Special return value to signal caller
                
                # Deduct
                c.execute("UPDATE users SET leave_balance = leave_balance - ? WHERE username=?", (days, username))

        # RESTORATION LOGIC (If un-approving? Or rejecting previously approved? 
        # PROMPT says: "Rejected leave requests must not affect leave balance".
        # But if we Approve then Reject later? Usually prompts imply simple flow. 
        # For safety: If we transition FROM Approved TO Rejected, we should refund.
        if current_status == 'Approved' and status != 'Approved':
             if leave_type == 'Annual':
                d1 = datetime.strptime(req['start_date'], "%Y-%m-%d")
                d2 = datetime.strptime(req['end_date'], "%Y-%m-%d")
                days = abs((d2 - d1).days) + 1
                c.execute("UPDATE users SET leave_balance = leave_balance + ? WHERE username=?", (days, username))

        c.execute("UPDATE leave_requests SET status=? WHERE id=?", (status, id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating leave status {id}: {e}")
        return False
    finally:
        conn.close()

def update_leave_request_details(id, type, start, end, reason, attachment_path=None):
    conn = get_db_connection()
    c = conn.cursor()
    if attachment_path:
        c.execute("UPDATE leave_requests SET type=?, start_date=?, end_date=?, reason=?, attachment_path=?, status='Pending' WHERE id=?",
                  (type, start, end, reason, attachment_path, id))
    else:
         c.execute("UPDATE leave_requests SET type=?, start_date=?, end_date=?, reason=?, status='Pending' WHERE id=?",
                  (type, start, end, reason, id))
    conn.commit()
    conn.close()
