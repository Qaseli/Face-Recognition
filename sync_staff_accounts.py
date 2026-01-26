# sync_staff_accounts.py
# Run this script ONCE to create login accounts for all existing staff members
# whose face images exist in the 'faces' folder but who don't have DB accounts.

import sqlite3
import os

DB_PATH = "attendance.db"
FACES_DIR = "faces"
DEFAULT_PASSWORD = "123456"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def sync_accounts():
    conn = get_db_connection()
    c = conn.cursor()
    
    if not os.path.exists(FACES_DIR):
        print("No 'faces' directory found!")
        return
    
    # Ensure leave_balance column exists
    try:
        c.execute("ALTER TABLE users ADD COLUMN leave_balance INTEGER DEFAULT 14")
    except:
        pass

    staff_names = [name for name in os.listdir(FACES_DIR) if os.path.isdir(os.path.join(FACES_DIR, name))]
    
    created = 0
    for name in staff_names:
        c.execute("SELECT * FROM users WHERE username=?", (name,))
        if not c.fetchone():
            c.execute("INSERT INTO users (username, password, role, leave_balance) VALUES (?, ?, 'staff', 14)", (name, DEFAULT_PASSWORD))
            print(f"  ✅ Created account: {name} / {DEFAULT_PASSWORD}")
            created += 1
        else:
            print(f"  ⏭️  Account exists: {name}")
    
    conn.commit()
    conn.close()
    print(f"\n🎉 Done! Created {created} new account(s).")

if __name__ == "__main__":
    print("🔄 Syncing staff face folders to database accounts...\n")
    sync_accounts()
