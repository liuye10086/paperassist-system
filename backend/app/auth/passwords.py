"""Local recovery issuance and transaction-safe sensitive password operations."""
import hmac
import secrets
import time
from argon2.exceptions import VerificationError, InvalidHashError

from app.database import ensure_schema_current
from app.storage import StorageError
from .config import settings
from .service import (
    AccountValidationError, auth_connection, digest, hasher, normalize_email,
    password_hash, validate_password,
)
from .revocations import invalidate_recovery_codes, revoke_sessions, session_expiry_reason

WINDOW_SECONDS = 900


def now():
    return time.time()


def issue_recovery_code(email):
    email = normalize_email(email)
    code = secrets.token_urlsafe(32)
    with auth_connection(write=True) as db:
        ensure_schema_current(db)
        row = db.execute("SELECT id,active FROM users WHERE email = %s", (email,)).fetchone()
        if row is None or not row["active"]:
            raise AccountValidationError("账号不存在或已停用。")
        timestamp = now()
        invalidate_recovery_codes(db, row["id"], timestamp)
        db.execute(
            "INSERT INTO password_recovery_codes (code_hash,user_id,created_at,expires_at) VALUES (%s,%s,%s,%s)",
            (digest(code), row["id"], timestamp, timestamp + WINDOW_SECONDS),
        )
    return code


def _rate_limited(db, user_id, code_hash, ip, timestamp):
    db.execute("DELETE FROM auth_password_attempts WHERE attempted_at <= %s", (timestamp - WINDOW_SECONDS,))
    counts = db.execute(
        """SELECT count(*) FILTER (WHERE user_id = %s) AS users,
        count(*) FILTER (WHERE code_hash = %s) AS codes,
        count(*) FILTER (WHERE client_ip = %s) AS ips FROM auth_password_attempts""",
        (user_id, code_hash, ip),
    ).fetchone()
    return counts["users"] >= 5 or counts["codes"] >= 5 or counts["ips"] >= 30


def _failure(db, user_id, code_hash, ip, timestamp):
    db.execute(
        "INSERT INTO auth_password_attempts (user_id,code_hash,client_ip,attempted_at) VALUES (%s,%s,%s,%s)",
        (user_id, code_hash, ip, timestamp),
    )


def _limited_error():
    return StorageError("password_rate_limited", "密码操作尝试过多，请15分钟后重试。", 429)


def _update_password(db, user_id, hashed, timestamp, reason):
    db.execute("UPDATE users SET password_hash = %s, updated_at = %s WHERE id = %s", (hashed, timestamp, user_id))
    invalidate_recovery_codes(db, user_id, timestamp)
    revoke_sessions(db, user_id=user_id, reason=reason, source="web", revoked_at=timestamp)


def change_password(token, csrf_token, current_password, new_password, ip):
    validate_password(new_password)
    error = None
    with auth_connection(write=True) as db:
        ensure_schema_current(db)
        timestamp = now()
        token_hash = digest(token)
        row = db.execute(
            """SELECT users.id,users.active,users.password_hash,sessions.csrf_token,sessions.last_seen_at,sessions.expires_at
            FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash = %s""", (token_hash,),
        ).fetchone()
        reason = session_expiry_reason(row, timestamp, settings().idle_seconds) if row else None
        if row is None or reason:
            if row:
                revoke_sessions(db, token_hash=token_hash, reason=reason, source="session", revoked_at=timestamp)
            error = StorageError("authentication_required", "请登录后继续。", 401)
        elif not hmac.compare_digest(csrf_token.encode("utf-8"), row["csrf_token"].encode("ascii")):
            error = StorageError("csrf_invalid", "请求安全凭据无效，请重新登录。", 403)
        elif _rate_limited(db, row["id"], None, ip, timestamp):
            error = _limited_error()
        else:
            try:
                valid = hasher.verify(row["password_hash"], current_password)
            except (VerificationError, InvalidHashError):
                valid = False
            if not valid:
                _failure(db, row["id"], None, ip, timestamp)
                error = StorageError("invalid_current_password", "当前密码错误。", 400)
            else:
                _update_password(db, row["id"], password_hash(new_password), timestamp, "password_changed")
    # Errors are raised after committing failure counters (never inside the
    # transaction where an exception would silently roll them back).
    if error:
        raise error


def recover_password(code, new_password, ip):
    validate_password(new_password)
    code_hash = digest(code)
    error = None
    with auth_connection(write=True) as db:
        ensure_schema_current(db)
        timestamp = now()
        row = db.execute(
            """SELECT password_recovery_codes.*,users.active FROM password_recovery_codes
            JOIN users ON users.id=password_recovery_codes.user_id WHERE code_hash = %s""", (code_hash,),
        ).fetchone()
        user_id = row["user_id"] if row else None
        if _rate_limited(db, user_id, code_hash, ip, timestamp):
            error = _limited_error()
        elif (
            row is None or not row["active"] or row["expires_at"] <= timestamp
            or row["used_at"] is not None or row["revoked_at"] is not None
        ):
            _failure(db, user_id, code_hash, ip, timestamp)
            error = StorageError("invalid_recovery_code", "恢复码无效或已过期，请联系管理员重新核验。", 400)
        else:
            db.execute("UPDATE password_recovery_codes SET used_at = %s WHERE code_hash = %s", (timestamp, code_hash))
            _update_password(db, user_id, password_hash(new_password), timestamp, "password_recovered")
    if error:
        raise error
