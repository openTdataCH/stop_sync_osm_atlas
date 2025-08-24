## Authentication: How It Works (Concise)

This is a high‑signal overview of how authentication is implemented in this project, with links to the exact files. For full details and code excerpts, see the deep dive document.

- Deep dive: [documentation/AUTHENTIFICATION_DEEP_DIVE.md](./AUTHENTIFICATION_DEEP_DIVE.md)

### What you get

- Email/password accounts stored in a dedicated auth database
- Optional email verification via signed, time‑limited links
- Two‑factor authentication (TOTP) with one‑time backup codes
- Session‑based auth using secure cookies (remember‑me supported)
- Strong CSRF protection for forms and standard header for AJAX
- Per‑route rate limits and progressive account lockout
- Security headers via Talisman and HTTPS enforcement toggle

## Key pieces (where things live)

- App setup, security config, CSRF exemptions, Talisman, blueprints: [backend/app.py](../backend/app.py)
- Extensions (SQLAlchemy, Flask‑Login, CSRF, Limiter, Talisman): [backend/extensions.py](../backend/extensions.py)
- User model, Argon2 hashing, 2FA fields, lockout fields: [backend/auth_models.py](../backend/auth_models.py)
- Auth routes (register, login, 2FA, verify email, logout): [backend/blueprints/auth.py](../backend/blueprints/auth.py)
- Email sending (SES): [backend/services/email.py](../backend/services/email.py)
- TOTP secret at‑rest encryption helpers (Fernet): [backend/services/crypto.py](../backend/services/crypto.py)
- Auth UI templates: [templates/auth/](../templates/auth/)
- Verification email templates: [templates/emails/](../templates/emails/)
- Main layout that injects CSRF token and AJAX header: [templates/layouts/base.html](../templates/layouts/base.html)

## Data model (auth_db)

- `User` lives in the `auth` bind; see `__bind_key__ = 'auth'` in [backend/auth_models.py](../backend/auth_models.py).
- Passwords are hashed with Argon2 (`argon2‑cffi`).
- Email verification fields: `is_email_verified`, `email_verified_at`.
- 2FA fields: `is_totp_enabled`, `totp_secret` (encrypted at rest), `backup_codes_json` (Argon2‑hashed codes).
- Lockout fields: `failed_login_attempts`, `locked_until`.

## Flows

### Registration

1) User submits email + password on `/auth/register`.
2) Cloudflare Turnstile is validated (skipped if keys unset).
3) Email is normalized; if the email already exists, the response is neutral (no enumeration) and, if unverified, a verification email may be resent.
4) Otherwise a new account is created (password Argon2‑hashed) and a verification email is sent.
5) In both cases, user is directed to a verification notice page.

Files: [auth blueprint](../backend/blueprints/auth.py), templates in [templates/auth/register.html](../templates/auth/register.html), email in [templates/emails/](../templates/emails/).

### Login (+ lockout)

1) User submits credentials on `/auth/login` (Turnstile validated).
2) Wrong password increments `failed_login_attempts`; after 5, temporary locks apply with exponential backoff (capped).
3) On success, counters reset. If email unverified, a reminder is sent but login can proceed.
4) If 2FA is enabled, proceed to the 2FA step; otherwise a session is created.

Files: [auth blueprint](../backend/blueprints/auth.py), [User model](../backend/auth_models.py).

### Two‑factor (TOTP + backup codes)

- Enabling: `/auth/enable_2fa` generates a secret, shows QR, verifies a code, enables 2FA, and shows one‑time backup codes (stored as Argon2 hashes).
- Login step: `/auth/2fa` accepts either a valid TOTP or a single‑use backup code; on success, the user session is created.
- Disabling: `/auth/disable_2fa` requires re‑auth via password.

Files: [auth blueprint](../backend/blueprints/auth.py), templates in [templates/auth/](../templates/auth/), crypto in [backend/services/crypto.py](../backend/services/crypto.py).

### Email verification

- Verification links are signed and time‑limited (`itsdangerous`).
- Routes: view, resend, and notice pages are handled in the auth blueprint.

Files: [auth blueprint](../backend/blueprints/auth.py), templates in [templates/auth/](../templates/auth/), emails in [templates/emails/](../templates/emails/).

### Logout

- `/auth/logout` clears the session via Flask‑Login and redirects home.

Files: [auth blueprint](../backend/blueprints/auth.py).

## Security controls (at a glance)

- Sessions and cookies: configured in [backend/app.py](../backend/app.py) (HttpOnly, SameSite=Lax, optional Secure; 14‑day remember cookie).
- CSRF: Flask‑WTF protects forms; AJAX sends `X‑CSRFToken` from meta tag in [templates/layouts/base.html](../templates/layouts/base.html). JSON blueprints `data`, `reports`, `search`, `stats` are currently exempt; others (like `problems`) are protected.
- Rate limiting: per‑route limits on auth endpoints, global defaults in [backend/extensions.py](../backend/extensions.py). Turn on proper proxy headers when behind a reverse proxy.
- CAPTCHA: Cloudflare Turnstile on register/login; site key injected via context processor.
- 2FA secrets encryption: TOTP secrets are encrypted at rest when a Fernet key is configured; see [backend/services/crypto.py](../backend/services/crypto.py) and related usage in the auth blueprint.
- Security headers: Flask‑Talisman is initialized in [backend/app.py](../backend/app.py); enable HTTPS with `FORCE_HTTPS=true` and set `SESSION_COOKIE_SECURE=true` in production.

## Configuration (env)

- Databases: `DATABASE_URI`, `AUTH_DATABASE_URI`
- Secrets: `SECRET_KEY` (mandatory), `TOTP_SECRET_ENC_KEY` or `FERNET_KEY` for 2FA secret encryption
- HTTPS: `FORCE_HTTPS`, `SESSION_COOKIE_SECURE`
- CAPTCHA: `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`
- Email (SES): `AWS_REGION`, `SES_FROM_EMAIL`, optional `SES_CONFIGURATION_SET`

See: [docker-compose.yml](../docker-compose.yml) and [entrypoint.sh](../entrypoint.sh).

## Admin and authorization

- Admin is a DB flag (`users.is_admin`). Admin‑only actions can use a decorator (see `admin_required` in [backend/blueprints/problems.py](../backend/blueprints/problems.py)).

## Notes and tips

- Email verification is optional by default; you can enforce verified‑only login by changing the login flow in [auth.py](../backend/blueprints/auth.py).
- If running behind a reverse proxy, forward client IPs and consider enabling proxy trust (e.g., Werkzeug `ProxyFix`) so rate limits key correctly.
- Keep server time in sync (NTP) for TOTP to work reliably.

For extended rationale, threat model, and implementation details, see the deep dive: [documentation/AUTHENTIFICATION_DEEP_DIVE.md](./AUTHENTIFICATION_DEEP_DIVE.md).


