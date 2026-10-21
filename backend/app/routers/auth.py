"""Auth routes: register / login / me / logout (stateless JWT)."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import create_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str
    password: str
    name: str = ""
    mode: str = "normal"


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    mode: str
    notifications_enabled: bool = True
    last_surah: int | None = None
    last_ayah: int | None = None


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, mode=u.mode,
                   notifications_enabled=u.notifications_enabled,
                   last_surah=u.last_surah, last_ayah=u.last_ayah)


class ProfilePatch(BaseModel):
    name: str | None = None
    mode: str | None = None
    notifications_enabled: bool | None = None


class ReadingPosition(BaseModel):
    surah: int
    ayah: int


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if "@" not in email or len(body.password) < 6:
        raise HTTPException(400, "Valid email and a password of 6+ characters are required")
    if body.mode not in ("normal", "hafiz"):
        raise HTTPException(400, "mode must be 'normal' or 'hafiz'")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Email already registered")
    user = User(email=email, password_hash=hash_password(body.password),
                name=body.name.strip(), mode=body.mode)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": create_token(user.id), "user": _user_out(user)}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.strip().lower()).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return {"token": create_token(user.id), "user": _user_out(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _user_out(user)


@router.post("/logout")
def logout(user: User = Depends(get_current_user)):
    # Stateless JWT: the client discards the token. Endpoint exists so
    # clients have a well-defined sign-out call (report FR-19).
    return {"detail": "Logged out"}


@router.patch("/me")
def update_profile(body: ProfilePatch, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    if body.mode is not None:
        if body.mode not in ("normal", "hafiz"):
            raise HTTPException(400, "mode must be 'normal' or 'hafiz'")
        user.mode = body.mode
    if body.name is not None:
        user.name = body.name.strip()
    if body.notifications_enabled is not None:
        user.notifications_enabled = body.notifications_enabled
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.put("/reading-position")
def set_reading_position(body: ReadingPosition,
                         user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    from ..ai.reference import load_reference
    ref = load_reference()
    if body.surah not in ref or body.ayah not in ref.get(body.surah, {}):
        raise HTTPException(400, "Unknown surah/ayah")
    user.last_surah, user.last_ayah = body.surah, body.ayah
    db.commit()
    return {"last_surah": user.last_surah, "last_ayah": user.last_ayah}
