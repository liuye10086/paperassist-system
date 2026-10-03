"""Accounts and revocable opaque sessions backed exclusively by PostgreSQL."""

import hashlib
import re
import secrets
import time
from uuid import uuid4
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from app.storage import _storage_connection, StorageError
from contextlib import contextmanager
from app.database import ensure_schema_current
from .config import settings
from .revocations import invalidate_recovery_codes, revoke_sessions, session_expiry_reason


class AccountValidationError(ValueError):
    pass


@contextmanager
def auth_connection(write=False):
    try:
        with _storage_connection(write=write) as db:
            yield db
    except StorageError as exc:
        if isinstance(exc.__cause__, AccountValidationError):
            raise ValueError(str(exc.__cause__)) from None
        raise


hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
_dummy_hash = hasher.hash(secrets.token_urlsafe(32))


def normalize_email(email):
    value = email.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value):
        raise ValueError("请输入有效邮箱。")
    return value


def validate_password(password):
    if not 12 <= len(password) <= 128:
        raise ValueError("密码须为12至128个字符。")


def password_hash(password):
    validate_password(password)
    return hasher.hash(password)


def public_user(row):
    return {key: row[key] for key in ("id", "email", "role")}


def _create(email, password, role, bootstrap):
    email = normalize_email(email)
    if role not in ("user", "admin"):
        raise ValueError("无效账号角色。")
    hashed = password_hash(password)
    result = dict(id=str(uuid4()), email=email, role=role)
    with auth_connection(write=True) as db:
        ensure_schema_current(db)
        if bootstrap and db.execute("SELECT id FROM users LIMIT 1").fetchone():
            raise AccountValidationError("初始化仅允许首个账号。")
        if db.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone():
            raise AccountValidationError("邮箱已存在。")
        now = time.time()
        db.execute(
            "INSERT INTO users (id,email,password_hash,role,active,created_at,updated_at) VALUES (%s,%s,%s,%s,true,%s,%s)",
            (result["id"], email, hashed, role, now, now),
        )
        if bootstrap:
            ids = [
                row["id"]
                for row in db.execute(
                    "UPDATE projects SET owner_id = %s WHERE owner_id IS NULL RETURNING id",
                    (result["id"],),
                )
            ]
            result.update(
                claimed_project_ids=sorted(ids), claimed_project_count=len(ids)
            )
    return result


def create_user(email, password, role="user", claim_legacy=False):
    if claim_legacy:
        raise ValueError("历史项目只能通过 bootstrap_admin 认领。")
    return _create(email, password, role, False)


def bootstrap_admin(email, password):
    return _create(email, password, "admin", True)


def _change(email, field, value, reason):
    email = normalize_email(email)
    with auth_connection(write=True) as db:
        ensure_schema_current(db)
        row = db.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if not row:
            raise AccountValidationError("账号不存在。")
        now = time.time()
        db.execute(
            f"UPDATE users SET {field} = %s, updated_at = %s WHERE id = %s",
            (value, now, row["id"]),
        )
        invalidate_recovery_codes(db, row["id"], now)
        revoke_sessions(db, user_id=row["id"], reason=reason, source="cli", revoked_at=now)


def reset_password(email, password):
    _change(email, "password_hash", password_hash(password), "admin_password_reset")


def set_user_active(email, active):
    _change(email, "active", bool(active), "account_enabled" if active else "account_disabled")


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(email, password, ip):
    try:
        email = normalize_email(email)
    except ValueError:
        email = email.strip().lower()[:254]
    now = time.time()
    limited = False
    result = None
    with auth_connection(write=True) as db:
        ensure_schema_current(db)
        db.execute(
            "DELETE FROM auth_login_attempts WHERE attempted_at < %s", (now - 900,)
        )
        count = db.execute(
            "SELECT count(*) FILTER (WHERE email = %s) AS emails, count(*) FILTER (WHERE client_ip = %s) AS ips FROM auth_login_attempts",
            (email, ip),
        ).fetchone()
        if count["emails"] >= 5 or count["ips"] >= 30:
            limited = True
        else:
            row = db.execute(
                "SELECT * FROM users WHERE email = %s", (email,)
            ).fetchone()
            try:
                valid = hasher.verify(
                    row["password_hash"] if row else _dummy_hash, password
                )
            except (VerificationError, InvalidHashError):
                valid = False
            if not row or not row["active"] or not valid:
                db.execute(
                    "INSERT INTO auth_login_attempts (email,client_ip,attempted_at) VALUES (%s,%s,%s)",
                    (email, ip, now),
                )
            else:
                config = settings()
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.execute(
                    "INSERT INTO sessions (token_hash,user_id,csrf_token,created_at,last_seen_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        digest(token),
                        row["id"],
                        csrf,
                        now,
                        now,
                        now + config.absolute_seconds,
                    ),
                )
                if hasher.check_needs_rehash(row["password_hash"]):
                    db.execute(
                        "UPDATE users SET password_hash = %s WHERE id = %s",
                        (hasher.hash(password), row["id"]),
                    )
                result = (token, {"user": public_user(row), "csrf_token": csrf})
    if limited:
        raise StorageError("login_rate_limited", "登录尝试过多，请稍后重试。", 429)
    if result is None:
        raise StorageError("invalid_credentials", "账号或密码错误。", 401)
    return result


def resolve_session(token):
    with auth_connection(write=True) as db:
        ensure_schema_current(db)
        now = time.time()
        row = db.execute(
            "SELECT users.id,users.email,users.role,users.active,sessions.csrf_token,sessions.last_seen_at,sessions.expires_at FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash = %s",
            (digest(token),),
        ).fetchone()
        if row is None:
            return None
        reason = session_expiry_reason(row, now, settings().idle_seconds)
        if reason:
            revoke_sessions(db, token_hash=digest(token), reason=reason, source="session", revoked_at=now)
            return None
        db.execute(
            "UPDATE sessions SET last_seen_at = %s WHERE token_hash = %s",
            (now, digest(token)),
        )
        return {"user": public_user(row), "csrf_token": row["csrf_token"]}


def revoke_session(token):
    with auth_connection(write=True) as db:
        ensure_schema_current(db)
        revoke_sessions(db, token_hash=digest(token), reason="logout", source="web", revoked_at=time.time())
