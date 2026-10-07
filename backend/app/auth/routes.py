from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from app.core.errors import error_detail


class AuthRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    {
                        "detail": error_detail("invalid_request", "认证请求格式无效。")
                    },
                    status_code=422,
                    headers={"Cache-Control": "no-store"},
                )

        return safe_handler


from app.auth.service import authenticate, revoke_session, update_preferences
from app.auth.config import settings
from app.auth.middleware import COOKIE_NAME
from app.auth.passwords import change_password, recover_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"], route_class=AuthRoute)


class LoginInput(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class PreferencesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ui_language: Literal["zh-CN", "en"]


class ChangePasswordInput(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class ResetPasswordInput(BaseModel):
    recovery_code: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response):
    token, result = authenticate(
        body.email, body.password, request.client.host if request.client else "unknown"
    )
    config = settings()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=config.absolute_seconds,
        httponly=True,
        secure=config.secure,
        samesite="lax",
        path="/",
    )
    return result


@router.get("/me")
def me(request: Request):
    return {"user": request.state.user, "csrf_token": request.state.csrf_token}


@router.get("/preferences", response_model=PreferencesInput)
def preferences(request: Request):
    return {"ui_language": request.state.user["ui_language"]}


@router.patch("/preferences", response_model=PreferencesInput)
def save_preferences(body: PreferencesInput, request: Request):
    return update_preferences(request.cookies[COOKIE_NAME], request.headers.get("X-CSRF-Token", ""), body.ui_language)


@router.post("/logout", status_code=204)
def logout(request: Request):
    revoke_session(request.cookies[COOKIE_NAME])
    return cleared_session_response()


def cleared_session_response():
    response = Response(status_code=204)
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=settings().secure, httponly=True, samesite="lax"
    )
    return response


@router.post("/change-password", status_code=204)
def change_own_password(body: ChangePasswordInput, request: Request):
    change_password(
        request.cookies[COOKIE_NAME], request.headers.get("X-CSRF-Token", ""),
        body.current_password, body.new_password,
        request.client.host if request.client else "unknown",
    )
    return cleared_session_response()


@router.post("/reset-password", status_code=204)
def reset_with_recovery(body: ResetPasswordInput, request: Request):
    recover_password(body.recovery_code, body.new_password, request.client.host if request.client else "unknown")
    return cleared_session_response()
