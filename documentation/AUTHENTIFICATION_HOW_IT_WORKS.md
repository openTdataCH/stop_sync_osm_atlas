## Authentication in This Project: How It Works, Why It’s Secure, and How to Avoid Pitfalls

### Overview

This document is a comprehensive walkthrough of the authentication stack implemented in this repository. It explains the architecture, shows the exact code paths involved, highlights security properties and tradeoffs, and enumerates common mistakes to avoid. It also includes practical steps for debugging, verifying, and extending the system.

We document the current, authentication and authorization design, including:

- Email verification with signed, time‑limited links (optional for login by default; can be enforced in production)
- Two‑factor authentication (TOTP) and one‑time backup codes
- Robust CSRF protection for both forms and JSON APIs (double‑submit header pattern)
- Role‑based access control (RBAC) with server‑enforced admin privileges
- Persistent data attribution and auditability (author captured and preserved)
- Rate limiting and progressive lockout controls
- Session, cookie, and transport security aligned with best practices

We detail each component with code excerpts, threat modeling, and bypass analysis.

### Table of Contents

- Architecture: monolith today vs "Authentication as a Service"
- Technology stack at a glance
- Key files and where things live
- Database design and multi-bind configuration
- User model and password hashing (Argon2)
- Registration flow
- Login flow, rate limiting, and account lockout
- CAPTCHA (Cloudflare Turnstile)
- Two-factor authentication (TOTP) and backup codes
- Logout and session management
- CSRF protection
- Transport security, cookies, and headers
- Templates and forms
- Environment variables and configuration
- Database initialization and DataGrip connectivity
- Threat model and security rationale
- Common pitfalls and how to avoid them
- Operational guidance: logging, monitoring, rotation
- Extending the system (password reset, WebAuthn, SSO)
- Testing authentication
- Hardening checklist

---

### Architecture: monolith today vs "Authentication as a Service"

Today, this application runs as a single Flask service (monolith) that contains both the business domain (stops, reports, search, statistics) and the authentication stack (registration, login/logout, 2FA, backup codes, rate limiting). It persists domain data in `stops_db` and authentication data in `auth_db` via SQLAlchemy multi‑binds.

An alternative is to split authentication into a dedicated service. Conceptually:

```
┌─────────────────────┐    ┌──────────────────────┐
│   Auth Service      │    │   Main App Service   │
│   (Port 5000)       │    │   (Port 5001)        │
├───────────────────  │    ├──────────────────────│
│ • User registration │    │ • Stops management   │
│ • Login/logout      │    │ • Reports            │
│ • 2FA management    │    │ • Search             │
│ • JWT token issue   │    │ • Statistics         │
│ • Password reset    │    │                      │
├───────────────────  │    ├──────────────────────│
│ auth_db             │    │ stops_db             │
└─────────────────────┘    └──────────────────────┘
         │                            │
         └────── HTTP API calls ──────┘
```

How they would communicate:

1. User visits the app → Main App Service
2. Main App checks if user is logged in → calls Auth Service API: `GET /api/auth/verify-token`
3. Auth Service responds → `{ "valid": true, "user_id": 123, "roles": ["admin"] }`
4. Main App serves content based on the auth response

Main application responsibilities shift to:
- Redirect users to the Auth Service for login
- Receive JWT tokens back (via redirect/callback)
- Validate tokens, either locally (via Auth Service JWKS) or by calling `GET /api/auth/verify-token`

What we would need to change to make it happen:

- Service split and ownership
  - Extract everything under `backend/blueprints/auth.py` and `backend/auth_models.py` into a new Flask service (Auth Service) with its own application factory and `db` bind pointing only to `auth_db`.
  - Keep the current service (Main App) focused on domain endpoints and `stops_db` only; remove auth routes and the `auth` SQLAlchemy bind from it.

- Identity model and propagation
  - Issue signed JWT access tokens in the Auth Service with claims like `sub` (user_id), `email`, `roles`.
  - Publish a JWKS endpoint (e.g., `GET /.well-known/jwks.json`) so the Main App can validate JWTs locally, or provide an introspection endpoint (`GET /api/auth/verify-token`) for remote validation.
  - Replace `flask_login`‑backed server sessions in the Main App with a request middleware that reads `Authorization: Bearer <JWT>` and sets the request identity from claims.

- Login/Logout/2FA flows
  - Update templates (e.g., `templates/layouts/base.html`, `templates/auth/*.html`) so "Login" links redirect to the Auth Service (e.g., `/auth/login?redirect_uri=https://app/callback`).
  - Implement a callback endpoint in the Main App to receive either a short‑lived authorization code (then exchange for JWT via Auth API) or the JWT directly; store only the JWT (no plaintext secrets) and its refresh token if used.
  - Keep TOTP setup, backup codes, password reset, and email verification fully inside the Auth Service.

- Configuration and deployment
  - Compose two containers and a shared network. Example:
    ```yaml
    services:
      auth:
        build: .
        command: flask run --host=0.0.0.0 --port=5000 -m backend.auth_app:app
        environment:
          AUTH_DATABASE_URI: mysql+pymysql://stops_user:1234@db/auth_db
          SECRET_KEY: ${AUTH_SECRET_KEY}
          JWT_ISSUER: https://auth.local
          JWT_AUDIENCE: app
        ports: ["5000:5000"]
      app:
        build: .
        command: flask run --host=0.0.0.0 --port=5001 -m backend.app:app
        environment:
          DATABASE_URI: mysql+pymysql://stops_user:1234@db/stops_db
          AUTH_SERVICE_URL: http://auth:5000
          JWKS_URL: http://auth:5000/.well-known/jwks.json
        ports: ["5001:5001"]
    ```
  - Introduce `AUTH_SERVICE_URL`, `JWKS_URL`, `JWT_ISSUER`, `JWT_AUDIENCE` env vars.
  - Move email templates and outbound email for auth flows to the Auth Service.

- Data and RBAC
  - The Main App stops querying the `users` table directly; it trusts identity from JWT and stores author attribution as `user_id` (from `sub`) and optionally `email` claim.
  - Enforce roles/permissions in the Main App using role claims contained in the JWT.

Why we decided to keep a single service (for now):

- Scope and velocity: one codebase, one runtime, fewer moving parts to ship features quickly.
- Simpler local development: no cross‑service auth, fewer containers, no CORS complexity.
- SQLAlchemy multi‑binds let us keep `auth_db` and `stops_db` separate without network boundaries.
- Running an Auth Service implies token issuance, key rotation/JWKS, revocation policies, discovery endpoints, and an OAuth/OIDC‑like flow—valuable at scale, but heavier than needed for this project today.

This document retains the monolithic model as the authoritative reference. The section above outlines a clean migration path should we adopt an Auth‑as‑a‑Service design later.

---

### Technology stack at a glance:

This Flask application uses:

- Flask-Login for session-based authentication
- SQLAlchemy for ORM with multiple database binds
- Argon2 for secure password hashing
- TOTP-based two-factor authentication (pyotp)
- Backup codes hashed and stored similar to passwords
- Flask-WTF for CSRF protection on form endpoints
- Flask-Limiter for rate limiting
- Flask-Talisman for transport/security headers
- Cloudflare Turnstile for CAPTCHA on auth forms

Authentication is stateful via a secure session cookie. After a successful login (and 2FA if enabled), the server sets a session that identifies the user. The cookie is configured with security attributes like HttpOnly and SameSite, and in production should also be marked Secure with HTTPS enforced.

---

### Key files and where things live

- Application setup and configuration
  - `backend/app.py`
  - `backend/extensions.py`

- Authentication data model
  - `backend/auth_models.py`

- Authentication routes and forms
  - `backend/blueprints/auth.py`

- HTML templates for auth UI
  - `templates/auth/login.html`
  - `templates/auth/register.html`
  - `templates/auth/two_factor.html`
  - `templates/auth/enable_2fa.html`
  - `templates/auth/backup_codes.html`

- Email delivery
  - `backend/services/email.py`

- Email verification templates
  - `templates/emails/verify_email.html`
  - `templates/emails/verify_email.txt`
  - `templates/auth/verify_notice.html`
  - `templates/auth/resend_verification.html`
  - `templates/auth/email_verified.html`

- Databases and Docker
  - `docker-compose.yml` (exposes MySQL, configures environment)
  - `entrypoint.sh` (waits for DB and runs migrations)

---

### Database design, migrations, and multi-bind configuration

The project uses two MySQL schemas managed by Alembic migrations:

- `stops_db` for the main application data
- `auth_db` for authentication data (e.g., `users`)

Multiple binds are configured so that different models can live in different databases while sharing a single app and session.

Relevant configuration:

```python
# backend/app.py
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/stops_db')
app.config['SQLALCHEMY_BINDS'] = {
    'auth': os.getenv('AUTH_DATABASE_URI', 'mysql+pymysql://stops_user:1234@localhost:3306/auth_db'),
}
```

This  snippet cleanly splits the data world in two. Domain data in `stops_db` and sensitive auth data in `auth_db`. Models opt into the auth database via `__bind_key__ = 'auth'`, so we get isolation without extra code. It also unlocks practical wins: separate migrations, tighter DB privileges, and easier future moves toward an external Auth service if needed.

The `User` model specifies `__bind_key__ = 'auth'`, directing SQLAlchemy to place the `users` table in `auth_db`:

```python
# backend/auth_models.py (excerpt)
class User(UserMixin, db.Model):
    __bind_key__ = 'auth'
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    # Two-factor auth
    is_totp_enabled = db.Column(db.Boolean, default=False, nullable=False)
    totp_secret = db.Column(db.String(64), nullable=True)
    backup_codes_json = db.Column(db.Text, nullable=True)
    # Account hygiene
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    # Lockout
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
```

Schema is managed by versioned migrations. The application runs `flask db upgrade` on startup to apply any pending changes.

Links:
- Multi-bind configuration: `backend/app.py`
- User model and bind: `backend/auth_models.py`

---

### User model and password hashing (Argon2)

Passwords are never stored in plaintext. They are hashed with Argon2 using the `argon2-cffi` implementation. Argon2 is a modern, memory-hard password hashing function designed to resist GPU and ASIC cracking.

Relevant code:

```python
# backend/auth_models.py (excerpt)
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

_ARGON2_HASHER = PasswordHasher()

class User(UserMixin, db.Model):
    # ...
    def set_password(self, plaintext: str) -> None:
        self.password_hash = _ARGON2_HASHER.hash(plaintext)

    def verify_password(self, plaintext: str) -> bool:
        try:
            return _ARGON2_HASHER.verify(self.password_hash, plaintext)
        except (VerifyMismatchError, VerificationError, ValueError):
            return False
```

Security properties:

- Passwords are salted and hashed using parameters encapsulated by `PasswordHasher()`.
- Verification uses constant-time comparisons under the hood.
- On mismatch or any verification error, it returns `False` without throwing sensitive errors.
- You can tune Argon2 parameters (memory cost, time cost, parallelism) via `PasswordHasher` if needed in production hardening.


- We do not store plaintext passwords.
- We do not use fast hashes (SHA-256/MD5) for passwords.
- We never log or print password inputs or hashes.

What “memory-hard” means and why it matters:

- A memory-hard function deliberately requires a significant amount of RAM to compute each hash. This limits how many hashes an attacker can compute in parallel on GPUs/ASICs, where fast cores are abundant but fast memory per core is limited and expensive.
- Argon2 lets you tune three key parameters to fit your hardware and latency budget: memory cost (RAM used per hash), time cost (number of passes), and parallelism (lanes/threads). Increasing memory cost is the most effective defense against large-scale cracking rigs.

---

### Registration flow

Users can register with an email and password. The password must be at least 12 characters (configurable in form validation).

Routes and forms:

```python
# backend/blueprints/auth.py (excerpt)
class RegisterForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=12, max=128)])
    agree_tos = BooleanField('AgreeToS', validators=[DataRequired()])

@auth_bp.route('/auth/register', methods=['GET', 'POST'])
@limiter.limit("5/minute")
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if not _verify_turnstile():
            flash('Captcha verification failed. Please try again.', 'danger')
            return redirect(url_for('auth.register'))
        email = form.email.data.lower().strip()
        password = form.password.data
        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'danger')
            return redirect(url_for('auth.register'))
        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        try:
            _send_verification_email(user)  # optional; verification not required to login
        except Exception:
            pass
        flash('Account created. You can sign in now. We sent an optional verification email.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', form=form)
```

In plain terms: this route shows a registration form and, on submit, validates inputs, normalizes the email, rejects duplicates, hashes the password with Argon2 via `user.set_password`, saves the user, and sends an email verification link. Email verification is optional for login by default. If validation fails, it re-renders `templates/auth/register.html` with errors; requests are rate-limited to 5/minute and protected by CSRF.

Security controls:

Rate limiting details (practical implications):

- Limits are keyed per client IP via `get_remote_address` (see `backend/extensions.py`).
- GET and POST to `/auth/register` share the same limit (5/minute). The 6th request within a minute returns HTTP 429.
- When running behind a reverse proxy (Nginx, Traefik, Cloudflare), the app may otherwise only see the proxy’s IP. That makes all users share one quota. To apply limits per real client IP:
  - At the proxy: forward the client IP and scheme (see Appendix B’s Nginx example using `X-Forwarded-For` and `X-Forwarded-Proto`).
  - In the app: trust those headers so `get_remote_address` uses the forwarded IP. Example:

    ```python
    # backend/app.py (add during app setup)
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    ```


 - Email normalized to lowercase and trimmed.
 - Strong minimum password length enforced.
 - CSRF protection is provided by Flask-WTF on the form.

---

### Login flow, rate limiting, and account lockout

Login verifies the password using Argon2 and optionally proceeds to a second factor if enabled. The route enforces rate limiting and implements progressive account lockout.

```python
# backend/blueprints/auth.py (excerpt)
class LoginForm(FlaskForm):  # [1] Form fields and validation
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember me')

def _is_account_locked(user: User) -> bool:  # [2] Helper: progressive lockout check
    return bool(user.locked_until and user.locked_until > datetime.utcnow())

@auth_bp.route('/auth/login', methods=['GET', 'POST'])  # [3] Route
@limiter.limit("10/minute")  # [4] Rate limiting
def login():  # [5]
    form = LoginForm()  # [6]
    if form.validate_on_submit():  # [7]
        email = form.email.data.lower().strip()  # [8] Normalize
        password = form.password.data  # [9]
        remember = form.remember.data  # [9]
        user = User.query.filter_by(email=email).first()  # [10]
        if not user:  # [11] Generic error to avoid enumeration
            flash('Invalid credentials.', 'danger')
            return redirect(url_for('auth.login'))
        if _is_account_locked(user):  # [12]
            flash('Account temporarily locked due to failed attempts. Try again later.', 'danger')
            return redirect(url_for('auth.login'))
        if not user.verify_password(password):  # [13]
            user.failed_login_attempts += 1  # [14]
            # Exponential backoff lock: 5, 7, 11, ... minutes
            if user.failed_login_attempts >= 5:  # [15]
                lock_minutes = min(60, 2 * user.failed_login_attempts + 5)
                user.locked_until = datetime.utcnow() + timedelta(minutes=lock_minutes)
            db.session.commit()  # [16]
            flash('Invalid credentials.', 'danger')  # [17]
            return redirect(url_for('auth.login'))
        # Password ok; reset counters
        user.failed_login_attempts = 0  # [18]
        user.locked_until = None  # [18]
        db.session.commit()  # [19]
        # If email not verified, send reminder but allow login to proceed
        if not user.is_email_verified:
            try:
                _send_verification_email(user)
            except Exception:
                pass
            flash('Your email is not verified yet. You can continue; we sent a verification email.', 'warning')
        # If 2FA enabled, go to 2FA step
        if user.is_totp_enabled:  # [20]
            from flask import session as flask_session
            flask_session['pending_2fa_user_id'] = user.id  # [20]
            flask_session['remember_me'] = bool(remember)  # [20]
            return redirect(url_for('auth.two_factor'))  # [21]
        # No 2FA, log in directly
        login_user(user, remember=remember, duration=timedelta(days=14))  # [22]
        user.last_login_at = datetime.utcnow()  # [23]
        db.session.commit()  # [24]
        flash('Logged in successfully.', 'success')  # [25]
        return redirect(url_for('index'))  # [25]
    return render_template('auth/login.html', form=form)  # [26]
```

#### Walkthrough (by marker)

- [1] Form definition and validation rules
- [2] Helper to determine if the account is currently locked
- [3] Route declaration; [4] applies per-IP rate limiting
- [5] View function start; [6] create form
- [7] Only proceed on valid POST; [8]-[9] normalize and read inputs
- [10] Lookup user by email
- [11] Return generic error for nonexistent user (prevents enumeration)
- [12] Enforce temporary lockout windows
- [13]-[17] Wrong password path: increment counter, compute lockout, persist, return generic error
- [18]-[19] Successful password: reset counters and persist
- [20]-[21] If 2FA enabled: stash pending user and remember flag in session, redirect to 2FA
- [22]-[25] If no 2FA: create session, update last login, persist, and redirect with success
- [26] GET or invalid form submission renders the login page

Security controls (with references):

- **Rate limiting**: 10/minute on login [4].
- **Progressive lockout**: starts after 5 failures, up to 60 minutes [14]-[16].
- **Counter reset on success**: failed attempts cleared [18]-[19].
- **No user enumeration**: generic error for missing user and wrong password [11], [17].
- **2FA gating**: session created only after TOTP step if enabled [20]-[22].
- **Email verification**: optional for login by default; a signed 48h link is sent on registration and when an unverified user logs in.

---

### CAPTCHA (Cloudflare Turnstile)

Humans are great. Bots, not so much. CAPTCHA adds a tiny “prove you’re human” step that is easy for people and hard for automated scripts. We use Cloudflare Turnstile because it’s free, privacy‑friendly, and low‑friction.

How it works at a glance:

- The browser renders a Turnstile widget inside the form.
- On submit, the widget adds a token named `cf-turnstile-response` to the form.
- The server posts that token to Cloudflare’s verify API with our secret key.
- If the API says “success,” we continue processing; otherwise, we reject.

Where we added it:

- Registration (`/auth/register`)
- Login (`/auth/login`)

Environment variables (optional for local dev):

- `TURNSTILE_SITE_KEY` – public key to render the widget
- `TURNSTILE_SECRET_KEY` – server key to verify tokens

Server‑side verification helper:

```python
# backend/blueprints/auth.py (excerpt)
import requests

def _verify_turnstile() -> bool:
    # If keys aren’t configured (e.g., local dev), skip verification gracefully
    secret = os.getenv('TURNSTILE_SECRET_KEY', '')
    if not secret:
        return True
    token = request.form.get('cf-turnstile-response', '')
    if not token:
        return False
    try:
        remoteip = request.headers.get('X-Forwarded-For', request.remote_addr)
        r = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={'secret': secret, 'response': token, 'remoteip': remoteip},
            timeout=5
        )
        data = r.json()
        return bool(data.get('success'))
    except Exception:
        return False
```

Enforced on submit (registration and login):

```python
# backend/blueprints/auth.py (excerpt)
@auth_bp.route('/auth/register', methods=['GET', 'POST'])
@limiter.limit("5/minute")
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if not _verify_turnstile():
            flash('Captcha verification failed. Please try again.', 'danger')
            return redirect(url_for('auth.register'))
        # ... create user, send verification email

@auth_bp.route('/auth/login', methods=['GET', 'POST'])
@limiter.limit("10/minute")
def login():
    form = LoginForm()
    if form.validate_on_submit():
        if not _verify_turnstile():
            flash('Captcha verification failed. Please try again.', 'danger')
            return redirect(url_for('auth.login'))
        # ... existing password/lockout/2FA flow
```

Making the site key available to templates:

```python
# backend/app.py (excerpt)
@app.context_processor
def inject_turnstile():
    return {'TURNSTILE_SITE_KEY': os.getenv('TURNSTILE_SITE_KEY', '')}
```

Rendering the widget in forms:

```html
<!-- templates/auth/login.html (excerpt) -->
{% if TURNSTILE_SITE_KEY %}
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
<div class="cf-turnstile my-3" data-sitekey="{{ TURNSTILE_SITE_KEY }}"></div>
{% endif %}
```

Docker environment wiring (optional):

```yaml
# docker-compose.yml (excerpt)
environment:
  # ... other settings ...
  TURNSTILE_SITE_KEY: "${TURNSTILE_SITE_KEY:-}"
  TURNSTILE_SECRET_KEY: "${TURNSTILE_SECRET_KEY:-}"
```

Why Turnstile?

- Free tier and privacy‑friendly
- Minimal friction for users compared to classic CAPTCHAs
- Complements our CSRF, rate limiting, lockout, and 2FA

Tips and gotchas

- Keys not set? The widget won’t render and verification is skipped (useful locally).
- Behind a proxy? Ensure `X-Forwarded-For` is forwarded so we can pass the client IP.
- If verification starts failing, double‑check secrets and outbound connectivity.

---

### Two-factor authentication (TOTP) and backup codes

The system supports TOTP-based 2FA (e.g., Google Authenticator, Authy). Once enabled, users must enter a 6‑digit TOTP or a valid single‑use backup code to finish logging in.

Enabling 2FA (setup):

```python
# backend/blueprints/auth.py (excerpt)
@auth_bp.route('/auth/enable_2fa', methods=['GET', 'POST'])  # [1] Route
@login_required  # [2] Only for logged-in users
def enable_2fa():  # [3]
    user = current_user  # [4]
    if request.method == 'POST':  # [5]
        token = request.form.get('token', '').strip().replace(' ', '')  # [6]
        if not user.totp_secret:  # [7]
            flash('No 2FA setup in progress.', 'danger')
            return redirect(url_for('auth.enable_2fa'))
        totp = pyotp.TOTP(user.totp_secret)  # [8]
        if totp.verify(token, valid_window=1):  # [9]
            user.is_totp_enabled = True  # [10]
            backup_codes = User.generate_backup_codes()  # [11]
            user.set_backup_codes(backup_codes)  # [12]
            db.session.commit()  # [13]
            return render_template('auth/backup_codes.html', backup_codes=backup_codes)  # [14]
        else:  # [15]
            flash('Invalid verification code.', 'danger')
            return redirect(url_for('auth.enable_2fa'))
    # Start setup: generate secret and QR
    if not user.totp_secret:  # [16]
        user.totp_secret = pyotp.random_base32()  # [17]
        db.session.commit()  # [18]
    issuer = os.getenv('AUTH_ISSUER', 'OSM-ATLAS Sync')  # [19]
    totp_uri = pyotp.totp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name=issuer)  # [20]
    # Render QR as inline SVG data URL (omitted here)  # [21]
    return render_template('auth/enable_2fa.html', qr_data_url=data_url, secret=user.totp_secret)  # [22]
```

Walkthrough (setup):

- [1]-[3] Route protected by login; user initiates setup
- [6]-[9] On POST, read code and verify against the secret (±1 window)
- [10]-[14] Enable 2FA, generate and store backup codes, persist, then show codes once
- [16]-[22] On first visit, create a secret, persist, build provisioning URI, render QR

Backup codes (generate, store, consume):

```python
# backend/auth_models.py (excerpt)
def set_backup_codes(self, codes_plain: List[str]) -> None:  # [23]
    hashed = []  # [24]
    for code in codes_plain:  # [25]
        hashed.append(_ARGON2_HASHER.hash(code))  # [26]
    self.backup_codes_json = json.dumps(hashed)  # [27]

def verify_and_consume_backup_code(self, code_plain: str) -> bool:  # [28]
    if not self.backup_codes_json:  # [29]
        return False
    try:
        hashes = json.loads(self.backup_codes_json)  # [30]
    except Exception:
        hashes = []
    remaining = []  # [31]
    matched = False  # [32]
    for h in hashes:  # [33]
        try:
            if _ARGON2_HASHER.verify(h, code_plain):  # [34]
                matched = True  # [35]
                # consumed; not re-added
            else:
                remaining.append(h)
        except Exception:
            remaining.append(h)
    if matched:  # [36]
        self.backup_codes_json = json.dumps(remaining)
    return matched  # [37]

@staticmethod
def generate_backup_codes(num_codes: int = 10) -> List[str]:  # [38]
    codes = []
    for _ in range(num_codes):  # [39]
        raw = secrets.token_hex(10)  # 20 hex chars  # [40]
        formatted = f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}"  # [41]
        codes.append(formatted)
    return codes  # [42]
```

Walkthrough (backup codes):

- [23]-[27] Store only Argon2 hashes of codes
- [28]-[37] Verify against hashes and consume matched code atomically
- [38]-[42] Generate 10 random codes, formatted for readability

Two‑factor login step:

```python
# backend/blueprints/auth.py (excerpt)
@auth_bp.route('/auth/2fa', methods=['GET', 'POST'])  # [43]
@limiter.limit("15/minute")  # [44]
def two_factor():  # [45]
    from flask import session as flask_session
    pending_user_id = flask_session.get('pending_2fa_user_id')  # [46]
    if not pending_user_id:  # [47]
        return redirect(url_for('auth.login'))
    user = db.session.get(User, pending_user_id)  # [48]
    if not user or not user.is_totp_enabled or not user.totp_secret:  # [49]
        return redirect(url_for('auth.login'))
    form = TwoFactorForm()  # [50]
    if form.validate_on_submit():  # [51]
        token = form.token.data.strip().replace(' ', '')  # [52]
        totp = pyotp.TOTP(user.totp_secret)  # [53]
        if totp.verify(token, valid_window=1) or user.verify_and_consume_backup_code(token):  # [54]
            remember = bool(flask_session.pop('remember_me', False))  # [55]
            flask_session.pop('pending_2fa_user_id', None)  # [56]
            login_user(user, remember=remember, duration=timedelta(days=14))  # [57]
            user.last_login_at = datetime.utcnow()  # [58]
            db.session.commit()  # [59]
            flash('2FA successful. Logged in.', 'success')  # [60]
            return redirect(url_for('index'))  # [61]
        else:  # [62]
            flash('Invalid 2FA token or backup code.', 'danger')
    return render_template('auth/two_factor.html', form=form)  # [63]
```

Walkthrough (2FA step):

- [46]-[49] Only users who passed password step and have 2FA enabled proceed
- [52]-[54] Accept either a valid TOTP or a single‑use backup code
- [55]-[61] On success: apply remember flag, clear pending state, create session, persist, redirect
- [62]-[63] On failure: show error and re‑render form

Security properties (with references):

- **Secret generation**: random TOTP secret created once during setup [16]-[18]
- **Provisioning**: standard otpauth URI for authenticator apps [19]-[22]
- **Verification window**: ±30–60s tolerance (`valid_window=1`) [9], [54]
- **Backup codes**: Argon2‑hashed at rest; single‑use consumption [23]-[37]
- **Session safety**: remember flag applied only after successful 2FA [55]-[57]

Gotchas:

- Keep server time in sync (NTP) to avoid TOTP drift
- Show backup codes once; store them offline like passwords
- Don’t log secrets, TOTPs, or backup codes


Disabling 2FA:

```python
# backend/blueprints/auth.py (excerpt)
@auth_bp.route('/auth/disable_2fa', methods=['POST'])
@login_required
def disable_2fa():
    user = current_user
    user.is_totp_enabled = False
    user.totp_secret = None
    user.backup_codes_json = None
    db.session.commit()
    flash('2FA disabled.', 'success')
    return redirect(url_for('index'))
```

---

### Logout and session management

The server uses Flask-Login to manage sessions. Logout clears the user’s session association server-side.

```python
# backend/blueprints/auth.py (excerpt)
@auth_bp.route('/auth/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'success')
    return redirect(url_for('index'))
```

Session configuration lives in `backend/app.py`:

```python
# backend/app.py (excerpt)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-in-production')
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=14)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
```

Security notes:

- Use a long, random `SECRET_KEY` in production; keep it stable across restarts.
- Set `SESSION_COOKIE_SECURE=true` and serve over HTTPS in production.
- Consider `SameSite=Strict` if your app doesn’t require cross-site requests (tradeoffs apply).
- Keep `HttpOnly` to prevent JavaScript access to session cookies.

---

### CSRF protection (forms and JSON)

Flask‑WTF (`CSRFProtect`) protects classic forms. For JSON write endpoints we require CSRF via a standard header.

```python
# backend/app.py (relevant excerpts)
csrf.init_app(app)
csrf.exempt(data_bp)
csrf.exempt(reports_bp)
csrf.exempt(search_bp)
csrf.exempt(stats_bp)

@login_manager.unauthorized_handler
def unauthorized():
    ...  # Returns JSON 401 for AJAX
```

Frontend automatically attaches `X‑CSRFToken` to AJAX calls:

```html
<!-- templates/layouts/base.html -->
<meta name="csrf-token" content="{{ csrf_token() }}">
<script>
  (function() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && window.jQuery) {
      $.ajaxSetup({ headers: { 'X-CSRFToken': meta.getAttribute('content') } });
    }
  })();
</script>
```

Pitfalls:

- Missing `{{ form.hidden_tag() }}` breaks CSRF on forms.
- Omitting `X‑CSRFToken` for AJAX writes will fail CSRF.
- Never use `GET` for mutating actions.

---

#### CSRF in practice: the friendly tour

- **What it is (in this app)**: Think of CSRF as a secret handshake between the browser and the server. The handshake is a per‑session token derived from `SECRET_KEY`. Only pages we render can know it.
- **Where it lives**:
  - Forms: Flask‑WTF drops it in a hidden input via `{{ form.hidden_tag() }}` (used in `login`, `register`, `two_factor`, etc.).
  - AJAX: We expose it in a meta tag and auto‑attach it as a header for jQuery requests.

  ```html
  <!-- templates/layouts/base.html (excerpt) -->
  <meta name="csrf-token" content="{{ csrf_token() }}">
  <script>
    (function() {
      var meta = document.querySelector('meta[name="csrf-token"]');
      if (meta && window.jQuery) {
        $.ajaxSetup({ headers: { 'X-CSRFToken': meta.getAttribute('content') } });
      }
    })();
  </script>
  ```

- **When it’s sent**:
  - Forms: automatically, as soon as the user submits the form.
  - jQuery AJAX: automatically, on every request, via the `X‑CSRFToken` header.
  - `fetch()`/non‑jQuery: add the header yourself using the meta tag value.

- **How validation works**: `CSRFProtect` intercepts unsafe HTTP methods (POST/PUT/PATCH/DELETE) and checks that the token in the form field or `X‑CSRFToken` header matches the session. Mismatch or missing? The request is rejected with a 400.

- **What’s protected vs. exempt right now**:
  - Protected: Auth forms and any routes not listed as exempt (notably, `problems_bp`).
  - Exempt: `data_bp`, `reports_bp`, `search_bp`, `stats_bp` (see `backend/app.py`). If an exempt JSON endpoint mutates data, keep it authenticated and consider removing the exemption.

##### If we didn’t have CSRF: how an attack would play out

Imagine Alice is logged into our site in one tab. In another tab, she visits attacker‑site.example.

1. The attacker page silently auto‑submits a form to our app:
   ```html
   <form action="https://our-app.example/protected/action" method="POST" id="x">
     <input type="hidden" name="make_admin" value="1">
   </form>
   <script>document.getElementById('x').submit()</script>
   ```
2. Because browsers send cookies automatically, Alice’s valid session cookie goes along for the ride.
3. Without CSRF, our server would see a legitimate cookie and a plausible POST and might perform the action—no user intent required.
4. With CSRF, the request is missing the secret token (the attacker can’t read it due to same‑origin policy), so the server rejects it.

That’s the entire value proposition: even if the attacker can make Alice’s browser send a request, they can’t forge the secret handshake.


### Transport security, cookies, and headers

The app uses Flask-Talisman for security headers and optional HTTPS enforcement.

```python
# backend/app.py (excerpt)
from backend.extensions import talisman

talisman.init_app(
    app,
    content_security_policy=None,  # relaxed CSP due to CDN-heavy frontend for now
    force_https=os.getenv('FORCE_HTTPS', 'false').lower() == 'true'
)
```

Notes:

- In production, enable `FORCE_HTTPS=true` and configure a CSP suited to your frontend to mitigate XSS.
- Enable HSTS and OCSP stapling at the reverse proxy; set `SESSION_COOKIE_SECURE=true`.
- Prefer `SameSite=Strict` if your app is not embedded cross-site; otherwise keep `Lax`.

---

### Templates and forms


Example snippet (login):

```html
<form method="POST">
  {{ form.hidden_tag() }}
  {{ form.email.label }} {{ form.email }}
  {{ form.password.label }} {{ form.password }}
  {{ form.remember.label }} {{ form.remember }}
  <button type="submit">Login</button>
</form>
```

Common mistakes:

- Missing `form.hidden_tag()` breaks CSRF.
- Not escaping user-controlled fields in custom templates.

---

### Environment variables and configuration

Key environment variables (see `docker-compose.yml`):

```yaml
services:
  app:
    environment:
      FLASK_APP: backend/app.py
      FLASK_ENV: development
      FLASK_DEBUG: 1
      DATABASE_URI: mysql+pymysql://stops_user:1234@db/stops_db
      AUTH_DATABASE_URI: mysql+pymysql://stops_user:1234@db/auth_db
      SECRET_KEY: ${SECRET_KEY:-dev-insecure}
      FORCE_HTTPS: "false"
      SESSION_COOKIE_SECURE: "false"
```

Production tips:

- Use strong values for `SECRET_KEY` and store them securely (e.g., Docker secrets, parameter store).
- Set `FORCE_HTTPS=true` and `SESSION_COOKIE_SECURE=true`.
- Disable `FLASK_DEBUG`.
- Review rate limits in `backend/extensions.py` and per-route decorators.

Email delivery (SES):

- `AWS_REGION` (e.g., `eu-west-1`)
- `SES_FROM_EMAIL` (verified identity in SES)
- Optional: `SES_CONFIGURATION_SET`

---


### Common pitfalls and how to avoid them

- Weak or rotating `SECRET_KEY`: breaks sessions/CSRF and can allow cookie forgery. Use a long, random, stable key per environment.
- Running without HTTPS in production: exposes session cookies. Always enable TLS and set `SESSION_COOKIE_SECURE=true`.
- Logging sensitive data: never log passwords, TOTP tokens, or backup codes.
- Lack of time sync: TOTP fails; enable NTP on servers.
- Improper error messages: avoid user enumeration; keep generic errors on login.
- Rate limits too permissive: tune route-level limits according to your security needs.
- Migrations not applied: ensure the app has run and executed `flask db upgrade` (done automatically on start).
- Failing to hash backup codes: in this app, they are hashed. Keep it that way.
- Exposing TOTP secret after setup: only show once; do not redisplay.
- Leaving CSP disabled in production: re-enable CSP to mitigate XSS.

---

### Operational guidance: logging, monitoring, rotation

- Monitor login failures, lockouts, and 2FA failures; alert on spikes.
- Rotate `SECRET_KEY` carefully; it invalidates sessions. Coordinate during maintenance.
- Backup and secure the `auth_db`. Treat it as sensitive even with hashing.
- Apply database least privilege where possible (in development, broader grants are used for convenience).

---

### Extending the system

Password reset flow (recommended):

- Implement a signed, single-use, short-lived reset token sent via email.
- Token should be stored server-side (or signed with a secret) and invalidated on use.
- Enforce password strength on reset.


Admin management:

- Admin assignment is a server‑side DB flag (`users.is_admin`).
- Admin‑only endpoints are protected by `@admin_required` in addition to `@login_required` and CSRF.

---

### Testing authentication

Unit tests and functional tests should cover:

- Registration success and failure cases (duplicate email, weak password).
- Login success, wrong password, nonexistent email (generic error), lockout progression, unlock after timeout.
- 2FA setup: generating secret, QR rendering, verification with a valid TOTP, failure with an invalid code.
- Backup code consumption: valid once, removed afterward.
- CSRF: posting without CSRF token should fail on form routes.
- Rate limiting: simulate exceeding limits and ensure proper responses.
- Email verification: registration triggers email; unverified login is allowed and triggers resend; verification link marks the account verified; invalid/expired tokens are rejected.

Example TOTP test snippet:

```python
import pyotp

def test_totp_verification(client, db_session, user_with_totp):
    # user_with_totp has user.totp_secret set up already
    totp = pyotp.TOTP(user_with_totp.totp_secret)
    valid = totp.now()
    assert totp.verify(valid, valid_window=1)
```

---

### Hardening checklist

- [ ] Use strong, random `SECRET_KEY` in all environments
- [ ] Enforce HTTPS end-to-end (reverse proxy + app)
- [ ] Set `FORCE_HTTPS=true` and `SESSION_COOKIE_SECURE=true`
- [ ] Re-enable and tune CSP via Flask-Talisman
- [ ] Tune Argon2 parameters 
- [ ] Add password reset flow
- [ ] Consider WebAuthn for stronger MFA
- [ ] Ensure NTP time sync on servers
- [ ] Monitor auth metrics and alert on anomalies
- [ ] Add Alembic migrations for `auth_db` schema evolution
- [ ] Review database privileges; consider separate accounts per schema

---




