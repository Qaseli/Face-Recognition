import sqlite3
import os

DB_PATH = 'attendance.db'

def migrate():
    print(f"Migrating {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Check existing columns
    c.execute("PRAGMA table_info(attendance)")
    columns = [info[1] for info in c.fetchall()]
    print(f"Current columns: {columns}")
    
    # 2. Add 'timestamp' if missing
    if 'timestamp' not in columns:
        print("Adding 'timestamp' column...")
        try:
            c.execute("ALTER TABLE attendance ADD COLUMN timestamp TEXT")
            # Populate it
            print("Populating 'timestamp' from date/time...")
            c.execute("UPDATE attendance SET timestamp = date || ' ' || time WHERE timestamp IS NULL")
            conn.commit()
        except Exception as e:
            print(f"Error adding timestamp: {e}")
            
    # 3. Add 'camera_id' if missing
    if 'camera_id' not in columns:
        print("Adding 'camera_id' column...")
        try:
            c.execute("ALTER TABLE attendance ADD COLUMN camera_id TEXT DEFAULT 'pi0'")
        except Exception as e:
            print(f"Error adding camera_id: {e}")

    # 4. Add 'confidence' if missing
    if 'confidence' not in columns:
        print("Adding 'confidence' column...")
        try:
            c.execute("ALTER TABLE attendance ADD COLUMN confidence REAL DEFAULT 0.0")
        except Exception as e:
            print(f"Error adding confidence: {e}")
            
    conn.commit()
    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    if os.path.exists(DB_PATH):
        migrate()
    else:
        print("Database not found.")
