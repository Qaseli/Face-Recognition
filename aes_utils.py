# aes_utils.py
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import os
import base64

KEY_FILE = "aes_key.bin"

def load_key(path=KEY_FILE):
    with open(path, "rb") as f:
        key = f.read()
    if len(key) != 32:
        raise ValueError("Key must be 32 bytes for AES-256")
    return key

def encrypt_bytes(plaintext_bytes, key):
    """
    plaintext_bytes: bytes to encrypt
    key: 32-byte key
    returns: bytes(iv + ciphertext)
    """
    iv = os.urandom(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ct = cipher.encrypt(pad(plaintext_bytes, AES.block_size))
    return iv + ct

def decrypt_bytes(iv_and_ciphertext, key):
    """
    iv_and_ciphertext: bytes starting with 16-byte IV
    returns: plaintext bytes
    """
    if len(iv_and_ciphertext) < 16:
        raise ValueError("Ciphertext too short")
    iv = iv_and_ciphertext[:16]
    ct = iv_and_ciphertext[16:]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    pt = unpad(cipher.decrypt(ct), AES.block_size)
    return pt

def b64_encode_bytes(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")

def b64_decode_to_bytes(s: str) -> bytes:
    return base64.b64decode(s)
