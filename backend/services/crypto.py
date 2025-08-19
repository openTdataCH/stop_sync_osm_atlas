import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


_ENC_PREFIX = "enc:"
_PLAIN_PREFIX = "plain:"


def _get_fernet() -> Optional[Fernet]:
    key = os.getenv("TOTP_SECRET_ENC_KEY") or os.getenv("FERNET_KEY")
    if not key:
        return None
    try:
        return Fernet(key)
    except Exception:
        return None


def encrypt_for_db(plaintext: str) -> str:
    if plaintext is None:
        return None  # type: ignore[return-value]
    fernet = _get_fernet()
    if not fernet:
        # Store with explicit marker that it's plaintext (for future migrations)
        return f"{_PLAIN_PREFIX}{plaintext}"
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return f"{_ENC_PREFIX}{token.decode('utf-8')}"


def decrypt_from_db(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if value.startswith(_ENC_PREFIX):
        token = value[len(_ENC_PREFIX) :].encode("utf-8")
        fernet = _get_fernet()
        if not fernet:
            # Cannot decrypt without a key
            raise RuntimeError("Encryption key not configured; cannot decrypt TOTP secret.")
        try:
            return fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Failed to decrypt TOTP secret: invalid key or token.") from exc
    if value.startswith(_PLAIN_PREFIX):
        return value[len(_PLAIN_PREFIX) :]
    # Backward-compat: previously stored as raw base32 in DB without prefix
    return value


def encryption_available() -> bool:
    return _get_fernet() is not None


def encrypt_if_possible(plaintext: str) -> str:
    """Encrypt without adding plain: prefix when key unavailable.

    Useful for opportunistic migrations of legacy unprefixed values.
    """
    fernet = _get_fernet()
    if not fernet:
        return plaintext
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return f"{_ENC_PREFIX}{token.decode('utf-8')}"


