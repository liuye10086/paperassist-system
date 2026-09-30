"""Authentication settings, evaluated from project-local configuration."""

from dataclasses import dataclass
from app.config import local_config


@dataclass(frozen=True)
class AuthSettings:
    absolute_seconds: int
    idle_seconds: int
    secure: bool
    origins: frozenset[str]


def settings():
    values = local_config()
    production = values.get("PAPERASSIST_ENV", "development") == "production"
    origins = values.get("PAPERASSIST_AUTH_TRUSTED_ORIGINS", "")
    if production and not origins.strip():
        raise ValueError("Production requires PAPERASSIST_AUTH_TRUSTED_ORIGINS.")
    if not origins:
        origins = ",".join(
            f"http://{host}:{port}"
            for host in ("localhost", "127.0.0.1")
            for port in (5173, 8000)
        )
        if values.get("PAPERASSIST_ENV") == "test":
            origins += ",http://testserver"
    absolute = int(values.get("PAPERASSIST_AUTH_ABSOLUTE_SECONDS", "604800"))
    idle = int(values.get("PAPERASSIST_AUTH_IDLE_SECONDS", "1800"))
    if absolute <= 0 or idle <= 0:
        raise ValueError("Authentication expiry must be positive.")
    return AuthSettings(
        absolute,
        idle,
        production,
        frozenset(s.strip().rstrip("/") for s in origins.split(",") if s.strip()),
    )
