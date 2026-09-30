from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse


class AuthRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    {
                        "detail": {
                            "code": "invalid_request",
                            "message": "登录请求格式无效。",
                        }
                    },
                    status_code=422,
                    headers={"Cache-Control": "no-store"},
                )

        return safe_handler


from .service import authenticate, revoke_session
from .config import settings
from .middleware import COOKIE_NAME

router = APIRouter(prefix="/api/v1/auth", tags=["auth"], route_class=AuthRoute)


class LoginInput(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


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


@router.post("/logout", status_code=204)
def logout(request: Request):
    revoke_session(request.cookies[COOKIE_NAME])
    response = Response(status_code=204)
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=settings().secure, httponly=True, samesite="lax"
    )
    return response
