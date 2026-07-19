
# crypto_utils.py — เข้ารหัส/ถอดรหัสข้อมูลอ่อนไหว (Groq API key ฯลฯ)
import os 
from cryptography.fernet import Fernet 


_key = os.environ.get("ENCRYPTION_KEY")

if not _key :
   raise RuntimeError(
        "ไม่พบ ENCRYPTION_KEY ใน environment variables — "
        "ต้องตั้งค่าก่อนรันระบบ (generate ด้วย: "
        "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")"
    ) 

_fernet = Fernet(_key.encode() if isinstance(_key, str ) else _key )
def encrypt_value(plain:str) -> str : 
   """เข้ารหัส string ธรรมดา → คืนค่าเป็น string (base64) เก็บลง database ได้ตรงๆ"""
   if not plain: return ""
   return _fernet.encrypt(plain.encode()).decode()

def decrypt_value(encryptted: str) -> str:
    """ถอดรหัส string ที่เข้ารหัสด้วย encrypt_value — คืนค่าดั้งเดิม
    ถ้าถอดรหัสไม่ได้ (key ผิด/ข้อมูลเสีย) คืนค่าว่างแทนที่จะทำให้ทั้งระบบ crash"""

    if not encrypted:
       return ""
    try: 
       return fernet.decrypt(encrypted.encode()).decode()
    except Exception:
       return ""

