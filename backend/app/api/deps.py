"""Зависимости FastAPI: текущий пользователь и проверка прав.

Права проверяются на сервере, а не в интерфейсе: роль определяет и доступные
разделы витрины, и доступные экраны Пульта (раздел 3 ТЗ, РОЛ.1–РОЛ.3).
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.database import get_db
from app.models import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Карта «роль → права», редактируемая часть вынесена в настройки платформы.
ROLE_MATRIX: dict[str, dict] = {
    Role.EMPLOYEE.value: {
        "title": "Сотрудник",
        "description": "Полный доступ к витрине",
        "denied_sections": [],
        "only_sections": None,
        "pult": [],
    },
    Role.DECREE.value: {
        "title": "Декрет",
        "description": "Все разделы, кроме страховых программ",
        "denied_sections": ["health"],
        "only_sections": None,
        "pult": [],
    },
    Role.VIP.value: {
        "title": "ВИП",
        "description": "Только раздел общих предложений",
        "denied_sections": [],
        "only_sections": ["common"],
        "pult": [],
    },
    Role.HR.value: {
        "title": "HR",
        "description": "Каталог, бюджеты, начисления, заявки, обращения",
        "denied_sections": [],
        "only_sections": None,
        "pult": ["dash", "catalog", "budget", "points", "orders", "people", "promo", "surveys", "support", "export"],
    },
    Role.ADMIN.value: {
        "title": "Администратор",
        "description": "Полный доступ, интеграции, роли, аудит",
        "denied_sections": [],
        "only_sections": None,
        "pult": ["*"],
    },
    Role.EXCLUDED.value: {
        "title": "Exclusion",
        "description": "Доступ к Системе ограничен",
        "denied_sections": ["*"],
        "only_sections": None,
        "pult": [],
    },
}


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    email = decode_token(token)
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен")

    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден или отключён")
    return user


def get_active_user(user: User = Depends(get_current_user)) -> User:
    """Сотрудник со служебной ролью Exclusion к витрине не допускается."""
    if user.role == Role.EXCLUDED.value:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Служебная группа Exclusion: сотрудник исключён из целевой аудитории Системы",
        )
    return user


def require_pult(screen: str):
    """Проверка доступа к экрану Пульта."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        allowed = ROLE_MATRIX.get(user.role, {}).get("pult", [])
        if "*" in allowed or screen in allowed:
            return user
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Раздел Пульта недоступен для роли «{ROLE_MATRIX.get(user.role, {}).get('title', user.role)}»",
        )

    return dependency


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.ADMIN.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуются права администратора")
    return user


def visible_section_codes(user: User, all_codes: list[str]) -> list[str]:
    """Какие разделы витрины видит роль."""
    rules = ROLE_MATRIX.get(user.role, {})
    if "*" in rules.get("denied_sections", []):
        return []
    if rules.get("only_sections"):
        return [c for c in all_codes if c in rules["only_sections"]]
    return [c for c in all_codes if c not in rules.get("denied_sections", [])]
