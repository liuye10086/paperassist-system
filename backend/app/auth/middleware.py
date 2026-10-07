"""Default-deny API authentication and browser write protection."""

import hmac
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import run_in_threadpool
from app.core.exceptions import StorageError
from app.core.errors import error_response as public_error_response, unexpected_error_response
from app.auth.config import settings
from app.auth.service import resolve_session

COOKIE_NAME = "paperassist_session"


def error_response(exc):
    headers = {"Cache-Control": "no-store"}
    if exc.status == 429:
        headers["Retry-After"] = "900"
    return public_error_response(exc.status, exc.code, exc.message, getattr(exc, 'params', None), headers)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        try:
            try:
                config = settings()
            except ValueError:
                raise StorageError('authentication_configuration', '认证配置无效，请检查受信源和会话期限。') from None
            public = request.url.path in ("/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/reset-password")
            session = None
            if not public:
                token = request.cookies.get(COOKIE_NAME)
                session = (
                    await run_in_threadpool(resolve_session, token) if token else None
                )
                if not session:
                    raise StorageError("authentication_required", "请登录后继续。", 401)
                request.state.user = session["user"]
                request.state.csrf_token = session["csrf_token"]
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                if request.headers.get("X-PaperAssist-Client") != "web":
                    raise StorageError("csrf_invalid", "请求缺少安全标头。", 403)
                origin = request.headers.get("Origin")
                if (
                    origin and origin.rstrip("/") not in config.origins
                ) or request.headers.get("Sec-Fetch-Site") == "cross-site":
                    raise StorageError("csrf_invalid", "请求来源不受信任。", 403)
                if session and not hmac.compare_digest(
                    request.headers.get("X-CSRF-Token", "").encode("utf-8"),
                    session["csrf_token"].encode("ascii"),
                ):
                    raise StorageError(
                        "csrf_invalid", "请求安全凭据无效，请重新登录。", 403
                    )
            response = await call_next(request)
        except StorageError as exc:
            response = error_response(exc)
        except Exception as exc:
            response = unexpected_error_response(exc)
        if response.status_code == 429:
            response.headers["Retry-After"] = "900"
        response.headers["Cache-Control"] = "no-store"
        return response
