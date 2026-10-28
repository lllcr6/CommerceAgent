"""Opaque, revocable server-side sessions. No identity supplied by the browser is trusted."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete
import app.db.base as db
from app.db.service_models import Account, LoginSession

router = APIRouter(prefix="/api/auth")
COOKIE = "commerce_session"

def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + digest

def verify_password(password, stored):
    return hmac.compare_digest(password_hash(password, stored.split(":")[0]), stored)

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

async def current_user(request: Request) -> Account:
    token = request.cookies.get(COOKIE, "")
    async with db.async_session() as s:
        session = await s.get(LoginSession, token_hash(token))
        if not session or session.expires_at <= datetime.utcnow():
            raise HTTPException(401, "Please sign in.")
        user = await s.get(Account, session.user_id)
        if not user:
            raise HTTPException(401, "Your sign-in session has expired.")
        request.state.user = user
        return user

async def customer(user=Depends(current_user)):
    if user.role != "user":
        raise HTTPException(403, "Customer access required")
    return user

async def staff(user=Depends(current_user)):
    if user.role != "support":
        raise HTTPException(403, "Support access required.")
    return user

async def administrator(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required.")
    return user

class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)

@router.post("/register")
async def register(req: Credentials):
    from sqlalchemy.exc import IntegrityError
    from app.business_store import seed_orders
    async with db.async_session() as s:
        s.add(Account(id=req.username, password_hash=password_hash(req.password), role="user"))
        try:
            await s.flush()
            await seed_orders(s, req.username)
            await s.commit()
        except IntegrityError:
            raise HTTPException(409, "That username is already taken.")
    return {"username": req.username, "role": "user"}

@router.post("/login")
async def login(req: Credentials, response: Response, request: Request):
    async with db.async_session() as s:
        user = await s.get(Account, req.username)
        if not user or not verify_password(req.password, user.password_hash):
            raise HTTPException(401, "Incorrect username or password.")
        old = request.cookies.get(COOKIE)
        if old:
            await s.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(old)))
        token = secrets.token_urlsafe(32)
        s.add(LoginSession(token_hash=token_hash(token), user_id=user.id,
                           expires_at=datetime.utcnow() + timedelta(hours=12)))
        await s.commit()
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=43200,
                        secure=request.url.scheme == "https")
    return {"username": user.id, "role": user.role}

@router.get("/me")
async def me(user=Depends(current_user)):
    return {"username": user.id, "role": user.role}

@router.post("/logout")
async def logout(request: Request, response: Response):
    async with db.async_session() as s:
        await s.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(request.cookies.get(COOKIE, ""))))
        await s.commit()
    response.delete_cookie(COOKIE)
    return {"ok": True}
