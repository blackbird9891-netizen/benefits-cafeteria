"""Балльная механика — раздел 4.4 ТЗ.

Самая дорогая часть системы: ошибка в приоритете списания или в сроках
сгорания означает, что у сотрудника пропадут баллы, которые пропадать
не должны были. Тесты бьют по модулю напрямую, без HTTP.
"""

from datetime import date, timedelta

import pytest

from app.core import points as pts
from app.models import User


@pytest.fixture
def user(db_session):
    u = User(email="t@corp.example", hashed_password="x", full_name="Тестов Т. Т.")
    db_session.add(u)
    db_session.commit()
    return u


def test_balance_empty(db_session, user):
    b = pts.balance(db_session, user)
    assert (b.available, b.granted, b.spent, b.burned) == (0, 0, 0, 0)


def test_grant_splits_burnable_and_permanent(db_session, user):
    pts.grant(db_session, user, 1000, "сгораемые", burnable=True)
    pts.grant(db_session, user, 500, "несгораемые", burnable=False)
    db_session.commit()

    b = pts.balance(db_session, user)
    assert b.burnable == 1000
    assert b.permanent == 500
    assert b.available == 1500


def test_burnable_lot_gets_expiry_permanent_does_not(db_session, user):
    """ФТ-БАЛ.2: срок задаётся при начислении, по умолчанию год."""
    burnable = pts.grant(db_session, user, 100, "а", burnable=True)
    permanent = pts.grant(db_session, user, 100, "б", burnable=False)
    db_session.commit()

    assert burnable.burn_at == pts.add_months(burnable.granted_at, 12)
    assert permanent.burn_at is None


def test_spend_takes_burnable_first(db_session, user):
    """ФТ-БАЛ.4: в первую очередь списываются сгораемые."""
    pts.grant(db_session, user, 300, "несгораемые", burnable=False)
    pts.grant(db_session, user, 200, "сгораемые", burnable=True)
    db_session.commit()

    assert pts.spend(db_session, user, 250, "покупка")
    db_session.commit()

    b = pts.balance(db_session, user)
    assert b.burnable == 0, "сгораемые должны уйти полностью"
    assert b.permanent == 250, "несгораемых должно остаться 300 − 50"


def test_spend_takes_nearest_expiry_first(db_session, user):
    """Внутри сгораемых первым уходит лот с ближайшим сроком."""
    today = date.today()
    far = pts.grant(db_session, user, 100, "дальний", burnable=True,
                    granted_at=today, burn_at=today + timedelta(days=300))
    near = pts.grant(db_session, user, 100, "ближний", burnable=True,
                     granted_at=today, burn_at=today + timedelta(days=10))
    db_session.commit()

    pts.spend(db_session, user, 100, "покупка")
    db_session.commit()

    assert near.remaining == 0
    assert far.remaining == 100


def test_expired_lot_excluded_from_balance(db_session, user):
    """Сгоревшие баллы не доступны и учитываются отдельно."""
    today = date.today()
    pts.grant(db_session, user, 500, "просрочен", burnable=True,
              granted_at=today - timedelta(days=400), burn_at=today - timedelta(days=1))
    pts.grant(db_session, user, 200, "живой", burnable=True)
    db_session.commit()

    b = pts.balance(db_session, user)
    assert b.available == 200
    assert b.burned == 500


def test_spend_rejects_when_insufficient(db_session, user):
    pts.grant(db_session, user, 100, "мало")
    db_session.commit()

    assert pts.spend(db_session, user, 500, "дорого") is False
    assert pts.balance(db_session, user).available == 100, "баланс не должен измениться"


def test_frozen_points_are_unavailable(db_session, user):
    """ФТ-БАЛ.9: заморозка делает баллы недоступными к расходованию."""
    pts.grant(db_session, user, 1000, "есть")
    user.points_frozen = True
    db_session.commit()

    b = pts.balance(db_session, user)
    assert b.available == 0
    assert b.burnable == 1000, "сами баллы никуда не делись"
    assert pts.spend(db_session, user, 100, "попытка") is False


def test_refund_creates_new_lot(db_session, user):
    pts.grant(db_session, user, 500, "начало")
    pts.spend(db_session, user, 300, "трата")
    db_session.commit()

    pts.refund(db_session, user, 300, "отмена заказа")
    db_session.commit()

    b = pts.balance(db_session, user)
    assert b.available == 500


def test_spend_across_several_lots(db_session, user):
    pts.grant(db_session, user, 100, "первый")
    pts.grant(db_session, user, 100, "второй")
    pts.grant(db_session, user, 100, "третий")
    db_session.commit()

    assert pts.spend(db_session, user, 250, "крупная покупка")
    db_session.commit()
    assert pts.balance(db_session, user).available == 50


def test_audit_written_on_grant_and_spend(db_session, user):
    from app.models import AuditLog

    pts.grant(db_session, user, 100, "начисление")
    pts.spend(db_session, user, 50, "списание")
    db_session.commit()

    actions = [a.action for a in db_session.query(AuditLog).all()]
    assert "Начисление баллов" in actions
    assert "Списание баллов" in actions


@pytest.mark.parametrize("start,months,expected", [
    (date(2026, 1, 15), 12, date(2027, 1, 15)),
    (date(2026, 1, 31), 1, date(2026, 2, 28)),
    (date(2024, 1, 31), 1, date(2024, 2, 29)),
    (date(2026, 12, 5), 1, date(2027, 1, 5)),
])
def test_add_months_handles_month_ends(start, months, expected):
    """Конец месяца и високосный год — классический источник ошибок."""
    assert pts.add_months(start, months) == expected
