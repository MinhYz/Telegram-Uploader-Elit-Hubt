import base64
from cryptography.fernet import Fernet
from config.settings import AES_SECRET_KEY
from utils.logger import logger

def _get_fernet() -> Fernet:
    key = AES_SECRET_KEY
    # Ensure key is valid Fernet 32 url-safe base64 bytes
    if isinstance(key, str):
        key = key.encode()
    try:
        return Fernet(key)
    except Exception:
        # Fallback to key derivation if raw string provided
        derived_key = base64.urlsafe_b64encode(key.ljust(32)[:32])
        return Fernet(derived_key)

_fernet = _get_fernet()

def encrypt_data(plain_text: str) -> str:
    """Encrypt plain text string into AES-256 Fernet ciphertext."""
    if not plain_text:
        return ""
    try:
        return _fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return plain_text

def decrypt_data(cipher_text: str) -> str:
    """Decrypt AES-256 Fernet ciphertext into plain text string."""
    if not cipher_text:
        return ""
    try:
        return _fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return cipher_text
