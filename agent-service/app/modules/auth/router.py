import asyncio
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.infra.database import AsyncSessionFactory

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])
bearer = HTTPBearer(auto_error=False)
passwords = PasswordHash((Argon2Hasher(), BcryptHasher()))


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=6, max_length=200)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("用户名不能为空")
        return value


class Register(Login):
    username: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=160)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if "@" not in value:
            raise ValueError("邮箱格式错误")
        return value.strip().lower()


def token(user_id: int, kind: str, lifetime: timedelta) -> str:
    return jwt.encode({"user_id": user_id, "kind": kind, "exp": datetime.now(timezone.utc) + lifetime}, settings.auth.secret, algorithm="HS256")


def decode(value: str, kind: str) -> int:
    try:
        claims = jwt.decode(value, settings.auth.secret, algorithms=["HS256"], options={"require": ["exp", "user_id", "kind"]})
        if claims["kind"] != kind:
            raise ValueError()
        return int(claims["user_id"])
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(401, "无效或已过期的 Token") from None


async def current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> int:
    if credentials is None:
        raise HTTPException(401, "Not authenticated")
    user_id = decode(credentials.credentials, "access")
    async with AsyncSessionFactory() as session:
        active = await session.scalar(text("SELECT id FROM users WHERE id=:id AND status='active'"), {"id": user_id})
    if active is None:
        raise HTTPException(401, "无效的认证凭据")
    return user_id


def session_response(user, response):
    response.set_cookie("refresh_token", token(user["id"], "refresh", timedelta(days=7)), httponly=True, samesite="lax", secure=settings.auth.secure_cookie, path="/api/v1/auth", max_age=604800)
    return {"access_token": token(user["id"], "access", timedelta(minutes=30)), "token_type": "Bearer", "user": {"id": user["id"], "username": user["username"], "email": user["email"], "displayName": user["display_name"]}}


@router.post("/register", status_code=201)
async def register(form: Register, response: Response):
    hashed = await asyncio.to_thread(passwords.hash, form.password)
    try:
        async with AsyncSessionFactory() as session, session.begin():
            user = (await session.execute(text("INSERT INTO users(username,email,password_hash,display_name) VALUES(:name,:email,:hash,:name) RETURNING *"), {"name": form.username.strip(), "email": form.email, "hash": hashed})).mappings().one()
    except IntegrityError:
        raise HTTPException(409, "用户名或邮箱已存在") from None
    return session_response(user, response)


@router.post("/login")
async def login(form: Login, response: Response):
    async with AsyncSessionFactory() as session:
        user = (await session.execute(text("SELECT * FROM users WHERE (username=:name OR email=:name) AND status='active'"), {"name": form.username.strip()})).mappings().one_or_none()
    valid = False
    if user:
        try:
            valid = await asyncio.to_thread(passwords.verify, form.password, user["password_hash"])
        except (ValueError, TypeError, UnknownHashError):
            pass
    if not valid:
        raise HTTPException(401, "用户名/邮箱或密码错误")
    return session_response(user, response)


@router.post("/refresh")
async def refresh(response: Response, refresh_token: str | None = Cookie(default=None)):
    user_id = decode(refresh_token or "", "refresh")
    async with AsyncSessionFactory() as session:
        user = (await session.execute(text("SELECT * FROM users WHERE id=:id AND status='active'"), {"id": user_id})).mappings().one_or_none()
    if user is None:
        raise HTTPException(401, "无效的认证凭据")
    return session_response(user, response)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    return {"ok": True}
