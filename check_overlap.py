import sqlite3

try:
    conn = sqlite3.connect('attendance.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM leave_requests WHERE username='ZIA' AND start_date <= '2026-01-25' AND end_date >= '2026-01-25' AND status != 'Rejected'")
    rows = c.fetchall()
    print(f"Found {len(rows)} overlapping requests:")
    for row in rows:
        print(dict(row))
    conn.close()
except Exception as e:
    print(e)
