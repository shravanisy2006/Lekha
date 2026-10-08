import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlmodel import Session

from database import get_session
from models import Role, User

# The secret that signs tokens. In real use, set the LEKHA_SECRET_KEY environment variable
# to a long random string; anyone who knows it can create valid tokens.
SECRET_KEY = os.environ.get("LEKHA_SECRET_KEY", "dev-only-secret-change-me-before-the-shop-uses-it")
ALGORITHM = "HS256"
TOKEN_HOURS = 8  # one shop day

password_hash = PasswordHash.recommended()  # Argon2, a slow hash built for passwords
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)

NOT_LOGGED_IN = HTTPException(
    status_code=401, detail="Not logged in, or the login has expired", headers={"WWW-Authenticate": "Bearer"}
)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user: User) -> str:
    expires = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    payload = {"sub": str(user.id), "exp": expires}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_optional_user(
    token: str | None = Depends(oauth2_scheme), session: Session = Depends(get_session)
) -> User | None:
    """The logged-in user, or None if no token was sent."""
    if token is None:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])  # also checks "exp"
    except jwt.InvalidTokenError:
        raise NOT_LOGGED_IN
    user = session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise NOT_LOGGED_IN
    return user


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    """Any logged-in user (owner or staff)."""
    if user is None:
        raise NOT_LOGGED_IN
    return user


def require_owner(user: User = Depends(get_current_user)) -> User:
    """Only the owner."""
    if user.role != Role.owner:
        raise HTTPException(status_code=403, detail="Only the owner can do this")
    return user