# generate_key.py
import os

KEY_FILE = "aes_key.bin"

def gen_key():
    key = os.urandom(32)  # 256-bit key
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    print(f"Generated key and wrote to {KEY_FILE} (32 bytes).")
    print("Copy this file to your Raspberry Pi (keep it secret).")

if __name__ == "__main__":
    gen_key()

    # Run on Server
    # python generate_key.py 

    # Then securely copy aes_key.bin to Pi (example):
    # scp aes_key.bin pi@<PI_IP>:/home/pi/
    
