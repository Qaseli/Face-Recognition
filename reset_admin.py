# reset_admin.py
import sqlite3

DB_PATH = "attendance.db"

def reset_admin():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Force Reset Admin
    print("Resetting Admin credentials...")
    c.execute("UPDATE users SET password='admin123', role='admin' WHERE username='admin'")
    
    # Verify
    c.execute("SELECT * FROM users WHERE username='admin'")
    row = c.fetchone()
    print(f"Admin Status: {dict(zip([c[0] for c in c.description], row))}")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    reset_admin()
