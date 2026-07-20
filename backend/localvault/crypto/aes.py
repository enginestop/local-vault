from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .csprng import new_nonce


def aes_gcm_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """Encrypt with AES-256-GCM. Returns ciphertext+tag (16 bytes tag, SEC-009)."""
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")
    if len(nonce) != 12:
        raise ValueError("nonce must be 12 bytes")
    aes = AESGCM(key)
    return aes.encrypt(nonce, plaintext, aad)


def aes_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    """Decrypt + authenticate. Raises cryptography.exceptions.InvalidTag on failure (SEC-008)."""
    if len(key) != 32:
        raise ValueError("key must be 32 bytes")
    if len(nonce) != 12:
        raise ValueError("nonce must be 12 bytes")
    aes = AESGCM(key)
    return aes.decrypt(nonce, ciphertext, aad)
