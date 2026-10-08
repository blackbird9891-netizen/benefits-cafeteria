"""Балльная механика: начисление, списание, сгорание, баланс.

Правила из раздела 4.4 ТЗ:
— баллы делятся на сгораемые и несгораемые (ФТ-БАЛ.1);
— срок сгорания задаётся при начислении, по умолчанию год (ФТ-БАЛ.2);
— при списании в первую очередь уходят сгораемые (ФТ-БАЛ.4);
— среди сгораемых первым списывается лот с ближайшим сроком.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, PointLot, User


@dataclass
class Balance:
    burnable: int
    permanent: int
    available: int
    burned: int
    granted: int
    spent: int
    frozen: bool


def add_months(start: date, months: int) -> date:
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    day = min(start.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def write_audit(db: Session, actor: str, action: str, detail: str = "") -> None:
    db.add(AuditLog(actor=actor, action=action, detail=detail))


def grant(
    db: Session,
    user: User,
    amount: int,
    reason: str,
    *,
    burnable: bool = True,
    burn_months: int = 12,
    granted_by: str = "Система",
    granted_at: date | None = None,
    burn_at: date | None = None,
) -> PointLot:
    """Начисление баллов отдельным лотом."""
    start = granted_at or date.today()
    lot = PointLot(
        user_id=user.id,
        amount=amount,
        remaining=amount,
        burnable=burnable,
        granted_at=start,
        burn_at=(burn_at or add_months(start, burn_months)) if burnable else None,
        reason=reason,
        granted_by=granted_by,
    )
    db.add(lot)
    write_audit(db, granted_by, "Начисление баллов", f"{user.full_name}: +{amount} ({reason})")
    return lot


def active_lots(db: Session, user_id: int) -> list[PointLot]:
    """Лоты с остатком, по которым ещё не наступил срок сгорания."""
    today = date.today()
    lots = db.scalars(select(PointLot).where(PointLot.user_id == user_id)).all()
    return [l for l in lots if l.remaining > 0 and (l.burn_at is None or l.burn_at > today)]


def balance(db: Session, user: User) -> Balance:
    today = date.today()
    all_lots = db.scalars(select(PointLot).where(PointLot.user_id == user.id)).all()

    burnable = sum(l.remaining for l in all_lots
                   if l.remaining > 0 and l.burnable and (l.burn_at is None or l.burn_at > today))
    permanent = sum(l.remaining for l in all_lots if l.remaining > 0 and not l.burnable)
    burned = sum(l.remaining for l in all_lots
                 if l.remaining > 0 and l.burn_at is not None and l.burn_at <= today)
    granted = sum(l.amount for l in all_lots)
    spent = granted - burnable - permanent - burned

    return Balance(
        burnable=burnable,
        permanent=permanent,
        available=0 if user.points_frozen else burnable + permanent,
        burned=burned,
        granted=granted,
        spent=spent,
        frozen=user.points_frozen,
    )


def spend(db: Session, user: User, amount: int, reason: str) -> bool:
    """Списание. Сначала сгораемые с ближайшим сроком, затем несгораемые."""
    if amount <= 0:
        return True

    bal = balance(db, user)
    if bal.available < amount:
        return False

    lots = sorted(
        active_lots(db, user.id),
        key=lambda l: (not l.burnable, l.burn_at or date(2099, 1, 1)),
    )

    need = amount
    for lot in lots:
        if need <= 0:
            break
        take = min(lot.remaining, need)
        lot.remaining -= take
        need -= take

    write_audit(db, "Система", "Списание баллов", f"{user.full_name}: −{amount} ({reason})")
    return need == 0


def refund(db: Session, user: User, amount: int, reason: str) -> PointLot:
    """Возврат баллов новым сгораемым лотом."""
    return grant(db, user, amount, f"Возврат: {reason}", burnable=True)
