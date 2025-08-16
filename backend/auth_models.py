from datetime import datetime, timedelta
import json
import os
import secrets
from typing import List

from flask_login import UserMixin
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from backend.extensions import db


_ARGON2_HASHER = PasswordHasher()


class User(UserMixin, db.Model):
    __bind_key__ = 'auth'
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)

    # Roles
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    # Email verification
    is_email_verified = db.Column(db.Boolean, default=False, nullable=False)
    email_verified_at = db.Column(db.DateTime, nullable=True)
    last_verification_sent_at = db.Column(db.DateTime, nullable=True)

    # Two-factor auth
    is_totp_enabled = db.Column(db.Boolean, default=False, nullable=False)
    totp_secret = db.Column(db.String(64), nullable=True)  # base32 secret when enabled
    backup_codes_json = db.Column(db.Text, nullable=True)  # JSON array of hashed codes

    # Account hygiene
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # Lockout/attempt tracking
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)

    def get_id(self):
        return str(self.id)

    # Password management
    def set_password(self, plaintext: str) -> None:
        self.password_hash = _ARGON2_HASHER.hash(plaintext)

    def verify_password(self, plaintext: str) -> bool:
        try:
            return _ARGON2_HASHER.verify(self.password_hash, plaintext)
        except (VerifyMismatchError, VerificationError, ValueError):
            return False

    # Backup codes management
    def set_backup_codes(self, codes_plain: List[str]) -> None:
        hashed = []
        for code in codes_plain:
            hashed.append(_ARGON2_HASHER.hash(code))
        self.backup_codes_json = json.dumps(hashed)

    def verify_and_consume_backup_code(self, code_plain: str) -> bool:
        if not self.backup_codes_json:
            return False
        try:
            hashes = json.loads(self.backup_codes_json)
        except Exception:
            hashes = []
        remaining = []
        matched = False
        for h in hashes:
            try:
                if _ARGON2_HASHER.verify(h, code_plain):
                    matched = True
                    # Do not append consumed code
                else:
                    remaining.append(h)
            except Exception:
                remaining.append(h)
        if matched:
            self.backup_codes_json = json.dumps(remaining)
        return matched

    @staticmethod
    def generate_backup_codes(num_codes: int = 10) -> List[str]:
        codes = []
        for _ in range(num_codes):
            # 10 bytes -> 20 hex chars; display groups for readability
            raw = secrets.token_hex(10)
            formatted = f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}"
            codes.append(formatted)
        return codes


class AuthEvent(db.Model):
    __bind_key__ = 'auth'
    __tablename__ = 'auth_events'
    
    id = db.Column(db.Integer, primary_key=True)
    # Optional linkage to a known user
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    # For failed login attempts where user is unknown or to capture the attempted identity
    email_attempted = db.Column(db.String(255), nullable=True, index=True)
    
    # Event classification (e.g. login_success, login_failure, login_locked, logout, 2fa_success, 2fa_failure, email_verified, 2fa_enabled, 2fa_disabled)
    event_type = db.Column(db.String(50), nullable=False, index=True)
    
    # Request context
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4/IPv6 max textual length
    user_agent = db.Column(db.Text, nullable=True)
    
    # Free-form JSON metadata as text
    metadata_json = db.Column(db.Text, nullable=True)
    
    # Timestamp
    occurred_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
