"""Public account applications that remain disabled until an administrator decides."""

import time
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.auth.service import auth_connection, normalize_email, password_hash
from app.core.exceptions import StorageError
from app.db.database import ensure_schema_current


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    organization: Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)] = ''
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ''

    @field_validator('email', 'display_name', 'organization', 'note')
    @classmethod
    def valid_text(cls, value, info):
        allowed_controls = '\n\r\t' if info.field_name == 'note' else ''
        if any((ord(char) < 32 or ord(char) == 127) and char not in allowed_controls for char in value):
            raise ValueError('注册信息包含无效字符。')
        return normalize_email(value) if info.field_name == 'email' else value


def submit_registration(application: RegisterInput, client_ip: str) -> None:
    with auth_connection(write=True) as db:
        ensure_schema_current(db)
        if not db.execute("SELECT 1 FROM users WHERE role='admin' AND active LIMIT 1").fetchone():
            raise StorageError('registration_unavailable', '注册尚未开放，请联系管理员。', 503)
        now = time.time()
        db.execute('DELETE FROM auth_registration_attempts WHERE attempted_at < %s', (now - 900,))
        count = db.execute('SELECT count(*) AS n FROM auth_registration_attempts WHERE client_ip=%s',
                           (client_ip,)).fetchone()['n']
        if count >= 10:
            raise StorageError('registration_rate_limited', '注册尝试过多，请稍后重试。', 429)
        db.execute('INSERT INTO auth_registration_attempts (client_ip,attempted_at) VALUES (%s,%s)', (client_ip, now))
        account = db.execute("""
            INSERT INTO users (id,email,password_hash,role,active,review_status,created_at,updated_at)
            VALUES (%s,%s,%s,NULL,false,'pending',%s,%s)
            ON CONFLICT (email) DO NOTHING RETURNING id
        """, (str(uuid4()), application.email, password_hash(application.password), now, now)).fetchone()
        if account:
            db.execute('''INSERT INTO account_registrations (user_id,display_name,organization,note)
                VALUES (%s,%s,%s,%s)''', (account['id'], application.display_name, application.organization, application.note))
