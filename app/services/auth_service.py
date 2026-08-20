"""
Authentication service using JWT tokens stored in HTTP-only cookies.
Password hashing with bcrypt via passlib.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.models.user import User

# ─── Configuration ───────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "abhinav-procurement-secret-key-change-in-production-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("AUTH_TOKEN_EXPIRE_MINUTES", "480"))  # 8 hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ─── Password utilities ───────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ─── Token utilities ──────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# ─── User utilities ───────────────────────────────────────────────────────────

def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username, User.is_active == True).first()


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_default_admin(db: Session):
    """Create default admin user if no users exist."""
    if db.query(User).count() == 0:
        admin = User(
            username="admin",
            full_name="Abhinav Group Admin",
            hashed_password=hash_password("admin123"),
            role="ADMIN",
            is_active=True
        )
        db.add(admin)
        db.commit()
        print("[AUTH] Created default admin user: admin / admin123")
        print("[AUTH] IMPORTANT: Please change the password after first login!")
