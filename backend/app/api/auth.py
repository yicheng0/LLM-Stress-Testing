from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.core.auth import AuthUser, authenticate_user, create_guest_user, current_user, issue_token
from backend.app.models.schemas import LoginOut, LoginRequest, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: AuthUser) -> UserOut:
    return UserOut(username=user.username, role=user.role)


@router.post("/login", response_model=LoginOut)
async def login(payload: LoginRequest) -> LoginOut:
    username = payload.username.strip()
    if username == "guest":
        user = create_guest_user()
        return LoginOut(token=issue_token(user), user=_user_out(user))

    user = authenticate_user(username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return LoginOut(token=issue_token(user), user=_user_out(user))


@router.get("/me", response_model=UserOut)
async def me(user: AuthUser = Depends(current_user)) -> UserOut:
    return _user_out(user)
