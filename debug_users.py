import sqlite3
from config import Config

def list_users():
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, username, full_name, email, role, status FROM users")
    rows = c.fetchall()
    conn.close()
    
    print(f"{'ID':<5} {'Username':<15} {'Full Name':<20} {'Email':<25} {'Role':<10} {'Status':<10}")
    print("-" * 90)
    for r in rows:
        print(f"{r['id']:<5} {r['username']:<15} {r['full_name'] or '':<20} {r['email'] or 'None':<25} {r['role']:<10} {r['status'] or '':<10}")

if __name__ == "__main__":
    list_users()
