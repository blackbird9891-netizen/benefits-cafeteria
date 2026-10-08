"""Авторизация: вход по логину и паролю, имитация SSO, вход по приглашению."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.core.points import write_audit
from app.core.security import create_access_token, verify_password
from app.database import get_db
from app.models import User

router = APIRouter()

INVITE_CODE = "KL-2026-7788"

NOT_IN_HR = (
    "Сотрудник с такой почтой не найден в кадровом контуре. "
    "Возможна рассинхронизация данных с 1С:ЗУП — обратитесь в HR."
)


def _issue(db: Session, user: User) -> schemas.TokenResponse:
    write_audit(db, user.full_name, "Вход в систему", f"Роль: {user.role}")
    db.commit()
    return schemas.TokenResponse(access_token=create_access_token(user.email))


@router.post("/login", response_model=schemas.TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Совместим с OAuth2PasswordRequestForm, чтобы работала кнопка Authorize в /docs."""
    user = db.scalar(select(User).where(User.email == form.username.lower().strip()))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_IN_HR)
    if not verify_password(form.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Неверный пароль. Проверьте раскладку или войдите через корпоративный SSO")
    return _issue(db, user)


@router.post("/login-json", response_model=schemas.TokenResponse)
def login_json(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_IN_HR)
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Неверный пароль. Проверьте раскладку или войдите через корпоративный SSO")
    return _issue(db, user)


@router.post("/sso/{email}", response_model=schemas.TokenResponse)
def sso_login(email: str, db: Session = Depends(get_db)):
    """Имитация единого входа. В рабочей системе — редирект в службу каталога заказчика."""
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_IN_HR)
    return _issue(db, user)


@router.post("/invite", response_model=schemas.TokenResponse)
def invite_login(payload: schemas.InviteRequest, db: Session = Depends(get_db)):
    """ФТ-ОНБ.1: вход по коду приглашения из письма."""
    if payload.code.strip().upper() != INVITE_CODE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Код приглашения не найден или истёк. Запросите новое приглашение у HR")
    user = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_IN_HR)
    return _issue(db, user)


@router.get("/demo-accounts")
def demo_accounts(db: Session = Depends(get_db)):
    """Тестовые учётные записи демо-стенда — выводятся на экране входа."""
    from app.api.deps import ROLE_MATRIX

    rows = db.scalars(select(User).order_by(User.id)).all()
    passwords = {"hr": "hr1234", "admin": "admin1234"}
    return [
        {
            "email": u.email,
            "password": passwords.get(u.role, "demo1234"),
            "full_name": u.full_name,
            "role": u.role,
            "role_title": ROLE_MATRIX.get(u.role, {}).get("title", u.role),
            "hint": ROLE_MATRIX.get(u.role, {}).get("description", ""),
        }
        for u in rows
    ]
