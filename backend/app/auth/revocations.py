"""Audited deletions; callers own the write transaction and schema check."""


def revoke_sessions(db, *, reason, source, revoked_at, user_id=None, token_hash=None):
    if (user_id is None) == (token_hash is None):
        raise ValueError("Specify exactly one session selector.")
    selector, value = ("user_id", user_id) if user_id is not None else ("token_hash", token_hash)
    # Only rows actually removed produce records. An audit failure rolls back
    # both this deletion and the caller's account/recovery changes.
    db.execute(
        f"""WITH removed AS (DELETE FROM sessions WHERE {selector} = %s RETURNING token_hash,user_id)
        INSERT INTO session_revocations (token_hash,user_id,reason,revoked_at,source)
        SELECT token_hash,user_id,%s,%s,%s FROM removed""",
        (value, reason, revoked_at, source),
    )


def invalidate_recovery_codes(db, user_id, timestamp):
    db.execute(
        "UPDATE password_recovery_codes SET revoked_at = %s WHERE user_id = %s AND used_at IS NULL AND revoked_at IS NULL",
        (timestamp, user_id),
    )


def session_expiry_reason(row, timestamp, idle_seconds):
    if not row["active"]:
        return "account_disabled"
    if row["expires_at"] <= timestamp:
        return "absolute_expired"
    if row["last_seen_at"] + idle_seconds <= timestamp:
        return "idle_expired"
    return None
