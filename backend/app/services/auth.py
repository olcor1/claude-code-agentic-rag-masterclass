from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.db.models import User
from app.db.session import bind_current_user_context, enable_auth_bypass_context, get_db


def register_user(db: Session, email: str, password: str) -> User:
    enable_auth_bypass_context(db)
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    return user


def authenticate_user(db: Session, email: str, password: str) -> str:
    enable_auth_bypass_context(db)
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return create_access_token(str(user.id))


def get_user_by_id(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token)
    except Exception as exc:  # pragma: no cover - invalid token path
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    bind_current_user_context(db, payload["sub"])
    return get_user_by_id(db, payload["sub"])
