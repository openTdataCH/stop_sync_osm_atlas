from datetime import datetime, timedelta
import base64
import io
import os
import requests

import pyotp
import qrcode
import qrcode.image.svg as qrcode_svg
from flask import Blueprint, request, render_template, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from wtforms import StringField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Email, Length
from flask_wtf import FlaskForm
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from typing import Optional

from backend.extensions import db, limiter
from backend.auth_models import User
from backend.services.email import send_email


auth_bp = Blueprint('auth', __name__)


class RegisterForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=12, max=128)])
    agree_tos = BooleanField('AgreeToS', validators=[DataRequired()])


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember me')


class TwoFactorForm(FlaskForm):
    token = StringField('Token', validators=[DataRequired(), Length(min=6, max=10)])


def _is_account_locked(user: User) -> bool:
    return bool(user.locked_until and user.locked_until > datetime.utcnow())


def _verify_turnstile() -> bool:
    # Skip verification if not configured (useful in local development)
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


def _get_serializer() -> URLSafeTimedSerializer:
    # Use secret key with a dedicated salt to isolate verification purpose
    secret = os.getenv('SECRET_KEY', 'change-this-in-production')
    return URLSafeTimedSerializer(secret_key=secret, salt='email-verification')


def _generate_email_verification_token(user_id: int) -> str:
    s = _get_serializer()
    return s.dumps({'uid': user_id})


def _load_email_verification_token(token: str, max_age_seconds: int = 60 * 60 * 48) -> Optional[int]:
    s = _get_serializer()
    try:
        data = s.loads(token, max_age=max_age_seconds)
        return int(data.get('uid'))
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        return None


def _send_verification_email(user: User) -> None:
    # Respect basic throttle on per-user basis (server-side check)
    now = datetime.utcnow()
    if user.last_verification_sent_at and (now - user.last_verification_sent_at) < timedelta(minutes=1):
        return
    token = _generate_email_verification_token(user.id)
    verify_link = url_for('auth.verify_email', token=token, _external=True)
    app_name = os.getenv('APP_NAME', 'OSM-ATLAS Sync')
    support_email = os.getenv('SUPPORT_EMAIL', None)
    subject = f"Verify your email for {app_name}"
    # Render email bodies from templates
    html_body = render_template('emails/verify_email.html', user=user, verify_url=verify_link, app_name=app_name, support_email=support_email)
    text_body = render_template('emails/verify_email.txt', user=user, verify_url=verify_link, app_name=app_name, support_email=support_email)
    send_email(to_address=user.email, subject=subject, html_body=html_body, text_body=text_body)
    user.last_verification_sent_at = now
    db.session.commit()


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
        # Immediately send email verification
        try:
            _send_verification_email(user)
        except Exception:
            # Fail silently to avoid leaking internal errors
            pass
        return render_template('auth/verify_notice.html', email=email)
    return render_template('auth/register.html', form=form)


@auth_bp.route('/auth/login', methods=['GET', 'POST'])
@limiter.limit("10/minute")
def login():
    form = LoginForm()
    if form.validate_on_submit():
        if not _verify_turnstile():
            flash('Captcha verification failed. Please try again.', 'danger')
            return redirect(url_for('auth.login'))
        email = form.email.data.lower().strip()
        password = form.password.data
        remember = form.remember.data
        user = User.query.filter_by(email=email).first()
        if not user:
            flash('Invalid credentials.', 'danger')
            return redirect(url_for('auth.login'))
        if _is_account_locked(user):
            flash('Account temporarily locked due to failed attempts. Try again later.', 'danger')
            return redirect(url_for('auth.login'))
        if not user.verify_password(password):
            user.failed_login_attempts += 1
            # Exponential backoff lock: 5, 7, 11, ... minutes
            if user.failed_login_attempts >= 5:
                lock_minutes = min(60, 2 * user.failed_login_attempts + 5)
                user.locked_until = datetime.utcnow() + timedelta(minutes=lock_minutes)
            db.session.commit()
            flash('Invalid credentials.', 'danger')
            return redirect(url_for('auth.login'))
        # Password ok; reset counters
        user.failed_login_attempts = 0
        user.locked_until = None
        db.session.commit()
        # Require email verification before allowing login
        if not user.is_email_verified:
            try:
                _send_verification_email(user)
            except Exception:
                pass
            flash('Please verify your email address. We have sent a new verification email.', 'warning')
            return redirect(url_for('auth.verification_required', email=email))
        # If 2FA enabled, go to 2FA step
        if user.is_totp_enabled:
            # Store pending user id in session
            request.session = request.session if hasattr(request, 'session') else None
            # Use Flask session
            from flask import session as flask_session
            flask_session['pending_2fa_user_id'] = user.id
            flask_session['remember_me'] = bool(remember)
            return redirect(url_for('auth.two_factor'))
        # No 2FA, log in directly
        login_user(user, remember=remember, duration=timedelta(days=14))
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        flash('Logged in successfully.', 'success')
        return redirect(url_for('index'))
    return render_template('auth/login.html', form=form)


@auth_bp.route('/auth/2fa', methods=['GET', 'POST'])
@limiter.limit("15/minute")
def two_factor():
    from flask import session as flask_session
    pending_user_id = flask_session.get('pending_2fa_user_id')
    if not pending_user_id:
        return redirect(url_for('auth.login'))
    user = db.session.get(User, pending_user_id)
    if not user or not user.is_totp_enabled or not user.totp_secret:
        return redirect(url_for('auth.login'))
    form = TwoFactorForm()
    if form.validate_on_submit():
        token = form.token.data.strip().replace(' ', '')
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(token, valid_window=1) or user.verify_and_consume_backup_code(token):
            remember = bool(flask_session.pop('remember_me', False))
            flask_session.pop('pending_2fa_user_id', None)
            login_user(user, remember=remember, duration=timedelta(days=14))
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            flash('2FA successful. Logged in.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid 2FA token or backup code.', 'danger')
    return render_template('auth/two_factor.html', form=form)


@auth_bp.route('/auth/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'success')
    return redirect(url_for('index'))


@auth_bp.route('/auth/enable_2fa', methods=['GET', 'POST'])
@login_required
def enable_2fa():
    user = current_user
    if request.method == 'POST':
        # Confirm code submitted by user to finalize enabling 2FA
        token = request.form.get('token', '').strip().replace(' ', '')
        if not user.totp_secret:
            flash('No 2FA setup in progress.', 'danger')
            return redirect(url_for('auth.enable_2fa'))
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(token, valid_window=1):
            user.is_totp_enabled = True
            # Generate backup codes and show once
            backup_codes = User.generate_backup_codes()
            user.set_backup_codes(backup_codes)
            db.session.commit()
            return render_template('auth/backup_codes.html', backup_codes=backup_codes)
        else:
            flash('Invalid verification code.', 'danger')
            return redirect(url_for('auth.enable_2fa'))
    # Start setup: generate secret and QR
    if not user.totp_secret:
        user.totp_secret = pyotp.random_base32()
        db.session.commit()
    issuer = os.getenv('AUTH_ISSUER', 'OSM-ATLAS Sync')
    totp_uri = pyotp.totp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name=issuer)
    # Generate QR as data URL
    qr = qrcode.QRCode(box_size=8, border=1)
    qr.add_data(totp_uri)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode_svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    data_url = f"data:image/svg+xml;base64,{base64.b64encode(buf.getvalue()).decode()}"
    return render_template('auth/enable_2fa.html', qr_data_url=data_url, secret=user.totp_secret)


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


@auth_bp.route('/auth/status', methods=['GET'])
def auth_status():
    if current_user.is_authenticated:
        return jsonify({
            'authenticated': True,
            'email': current_user.email,
            'is_totp_enabled': current_user.is_totp_enabled,
            'is_email_verified': current_user.is_email_verified,
            'is_admin': getattr(current_user, 'is_admin', False),
        })
    return jsonify({'authenticated': False})


# Email verification routes

@auth_bp.route('/auth/verify-email/<token>')
@limiter.limit("30/hour")
def verify_email(token: str):
    user_id = _load_email_verification_token(token)
    if not user_id:
        flash('This verification link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.login'))
    user = db.session.get(User, user_id)
    if not user:
        flash('Account not found.', 'danger')
        return redirect(url_for('auth.login'))
    if user.is_email_verified:
        flash('Your email is already verified. You can sign in.', 'info')
        return redirect(url_for('auth.login'))
    user.is_email_verified = True
    user.email_verified_at = datetime.utcnow()
    db.session.commit()
    return render_template('auth/email_verified.html')


@auth_bp.route('/auth/resend-verification', methods=['GET', 'POST'])
@limiter.limit("5/minute")
def resend_verification():
    if request.method == 'POST':
        email = (request.form.get('email') or '').lower().strip()
        user = User.query.filter_by(email=email).first()
        # Always respond the same to avoid account enumeration
        if user and not user.is_email_verified:
            try:
                _send_verification_email(user)
            except Exception:
                pass
        return render_template('auth/verify_notice.html', email=email)
    # If user is logged in and unverified, prefill
    prefill_email = current_user.email if getattr(current_user, 'is_authenticated', False) and not current_user.is_email_verified else ''
    return render_template('auth/resend_verification.html', email=prefill_email)


@auth_bp.route('/auth/verification-required')
def verification_required():
    # Informational page prompting user to check inbox or resend
    email = request.args.get('email', '')
    return render_template('auth/verify_notice.html', email=email)


