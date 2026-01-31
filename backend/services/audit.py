from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from flask import request

from backend.extensions import db
from backend.auth_models import AuthEvent, User


logger = logging.getLogger(__name__)


def _get_ip_address() -> Optional[str]:
    try:
        # Prefer X-Forwarded-For if behind a proxy; take first IP
        forwarded_for = request.headers.get('X-Forwarded-For', '')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return request.remote_addr
    except Exception:
        return None


def record_auth_event(
    *,
    event_type: str,
    user: Optional[User] = None,
    email_attempted: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist and also emit a structured log for an authentication-related event.

    This helper is intentionally resilient: failures to record should not break the auth flow.
    """
    try:
        ip_address = _get_ip_address()
        user_agent = None
        try:
            user_agent = request.headers.get('User-Agent')
        except Exception:
            user_agent = None

        event = AuthEvent(
            user_id=user.id if user else None,
            email_attempted=email_attempted,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_json=json.dumps(metadata) if metadata else None,
            occurred_at=datetime.utcnow(),
        )
        db.session.add(event)
        db.session.commit()
    except Exception as exc:
        # Do not raise; just log a warning
        logger.warning("Failed to record auth event %s: %s", event_type, exc)

    # Also emit to application logs in structured form (best-effort)
    try:
        payload = {
            'type': 'auth_event',
            'event_type': event_type,
            'user_id': getattr(user, 'id', None),
            'email_attempted': email_attempted,
            'ip_address': _get_ip_address(),
            'user_agent': request.headers.get('User-Agent') if request else None,
            'metadata': metadata or {},
        }
        logger.info(json.dumps(payload))
    except Exception:
        # Swallow logging errors silently
        pass


