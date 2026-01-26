import requests
import json

BASE_URL = "http://127.0.0.1:5000/api"

def test_flow():
    s = requests.Session()
    
    # 1. Login Admin
    print("[1] Logging in as Admin...")
    r = s.post(f"{BASE_URL}/login", json={"username": "admin", "password": "admin123"})
    if r.status_code != 200:
        return print("Admin Login Failed")
    print("Admin OK")
    
    # 2. Add Staff
    print("[2] Creating Staff 'API Test User'...")
    # Need multipart for image, mocking it
    files = {'image': ('test.jpg', b'fake_image_bytes', 'image/jpeg')}
    data = {
        'name': 'API Test User',
        'email': 'api@test.com',
        'department': 'IT'
    }
    r = s.post(f"{BASE_URL}/staff", data=data, files=files)
    if r.status_code != 200:
        return print(f"Add Staff Failed: {r.text}")
    
    creds = r.json().get('credentials')
    staff_id = creds['staff_id']
    temp_pass = creds['temp_password']
    print(f"Staff Created: {staff_id} / {temp_pass}")
    
    # 3. Login with Temp Pass
    print(f"[3] Attempting First Login as {staff_id}...")
    s2 = requests.Session() # New session
    r = s2.post(f"{BASE_URL}/login", json={"username": staff_id, "password": temp_pass})
    
    print(f"Login Response: {r.json()}")
    if r.json().get('status') != 'first_login_required':
        return print("FAIL: Did not get 'first_login_required'")
    print("SUCCESS: Got 'first_login_required'")
    
    # 4. Change Password
    print("[4] Changing Password...")
    r = s2.post(f"{BASE_URL}/change_password", json={
        "username": staff_id,
        "temp_password": temp_pass,
        "new_password": "newpassword123"
    })
    if r.status_code != 200:
        return print(f"Change Password Failed: {r.text}")
    print("Password Changed OK")
    
    # 5. Final Login
    print("[5] Logging in with New Password...")
    s3 = requests.Session()
    r = s3.post(f"{BASE_URL}/login", json={"username": staff_id, "password": "newpassword123"})
    if r.status_code != 200:
        return print(f"Final Login Failed: {r.text}")
    
    # Check if active
    r_check = s3.get(f"{BASE_URL}/check_auth")
    if r_check.json().get('authenticated'):
        print(f"FINAL SUCCESS: Authenticated as {r_check.json()['user']}")
    else:
        print("Final Auth Check Failed")

if __name__ == "__main__":
    try:
        test_flow()
    except Exception as e:
        print(e)
