"""Регрессии на дефекты, найденные при ревью и первом прогоне тестов.

Каждый тест закрывает конкретную ошибку, которая уже была в коде.
"""

from datetime import date

import pytest

from app.core import points as pts
from app.models import Order, User


def test_spend_sees_grant_in_same_transaction(db_session):
    """Дефект: autoflush был выключен, и списание не видело начисление,
    сделанное в той же транзакции до коммита. Операция молча отвечала
    «недостаточно средств», а баллы оставались нетронутыми."""
    user = User(email="r1@corp.example", hashed_password="x", full_name="Регресс Р. Р.")
    db_session.add(user)
    db_session.flush()

    pts.grant(db_session, user, 1000, "начисление")
    assert pts.spend(db_session, user, 400, "списание сразу после начисления") is True
    assert pts.balance(db_session, user).available == 600


def test_decree_cannot_buy_family_dms(api):
    """Дефект: ограничение роли «Декрет» работало только по разделам витрины.
    Позиция «ДМС для члена семьи» лежит в разделе «Семья и дети» и оставалась
    доступной, хотя ТЗ закрывает для этой роли страховые программы (РОЛ.3)."""
    api.as_admin()
    family_dms = next(i for i in api.get("/api/pult/catalog").json()
                      if i["item_type"] == "dms-family")

    api.as_decree()
    titles = [i["title"] for i in api.get("/api/catalog").json()]
    assert family_dms["title"] not in titles, "позиция не должна быть в каталоге"

    assert api.get(f"/api/catalog/{family_dms['id']}").status_code == 403

    r = api.post("/api/checkout", json={"lines": [{"item_id": family_dms["id"], "options": {
        "fio": "Иванов И. И.", "bd": "1990-01-01", "rel": "Супруг"}}]})
    assert r.status_code == 403, "прямой запрос в обход интерфейса тоже должен отклоняться"


def test_order_ids_unique_in_bulk_checkout(api, db_session):
    """Дефект: публичный номер собирался из максимального id плюс случайное
    число, и при оформлении нескольких позиций подряд номера совпадали —
    второй заказ падал на уникальном индексе."""
    api.as_admin()
    api.post("/api/pult/points/grant",
             json={"user_id": 1, "amount": 30000, "reason": "под тест", "burnable": True})

    api.as_employee()
    cheap = [i for i in api.get("/api/catalog").json()
             if i["price"] and i["price"] < 5000 and not i["needs_doc"]
             and not i["has_slots"] and i["item_type"] not in ("dms-family", "vac", "stay")][:3]
    assert len(cheap) >= 2

    r = api.post("/api/checkout",
                 json={"lines": [{"item_id": i["id"], "options": {}} for i in cheap]})
    assert r.status_code == 200, r.text

    ids = [o["public_id"] for o in r.json()["orders"]]
    assert len(ids) == len(set(ids)), f"номера заказов повторились: {ids}"

    all_ids = [o.public_id for o in db_session.query(Order).all()]
    assert len(all_ids) == len(set(all_ids)), "в базе есть дубли публичных номеров"


def test_gift_cancel_message_is_specific(api):
    """Дефект: проверка статуса стояла раньше проверки типа, и при попытке
    отменить промокод возвращалось расплывчатое «не тот статус» вместо
    объяснения, что код выдан и не возвращается."""
    api.as_employee()
    item = next(i for i in api.get("/api/catalog").json() if i["item_type"] == "gift")
    order = api.post("/api/checkout",
                     json={"lines": [{"item_id": item["id"], "options": {}}]}).json()["orders"][0]

    detail = api.post(f"/api/orders/{order['id']}/cancel").json()["detail"]
    assert "ротацию" in detail, f"сообщение должно объяснять причину, получено: {detail}"


def test_failed_checkout_leaves_no_trace(api):
    """Откат транзакции: неудачное оформление не должно оставлять
    ни заказа, ни списания, ни изменённого остатка."""
    api.as_employee()
    before_balance = api.get("/api/me").json()["balance"]["available"]
    before_orders = len(api.get("/api/orders").json())

    item = next(i for i in api.get("/api/catalog").json() if i["has_slots"])
    good = next(i for i in api.get("/api/catalog").json() if i["item_type"] == "gift")

    # Вторая строка корзины невалидна: слот не выбран.
    r = api.post("/api/checkout", json={"lines": [
        {"item_id": good["id"], "options": {}},
        {"item_id": item["id"], "options": {}},
    ]})
    assert r.status_code == 400

    assert api.get("/api/me").json()["balance"]["available"] == before_balance
    assert len(api.get("/api/orders").json()) == before_orders
    stock_after = next(i for i in api.get("/api/catalog").json()
                       if i["id"] == good["id"])["available_stock"]
    assert stock_after == good["available_stock"], "остаток промокодов не должен измениться"


@pytest.mark.parametrize("start,months,expected", [
    (date(2026, 8, 31), 1, date(2026, 9, 30)),
    (date(2026, 3, 31), 1, date(2026, 4, 30)),
    (date(2026, 12, 31), 2, date(2027, 2, 28)),
])
def test_burn_date_never_overflows_month(start, months, expected):
    """Срок сгорания, посчитанный от конца месяца, не должен уезжать
    в следующий месяц: 31 августа плюс месяц — это 30 сентября."""
    assert pts.add_months(start, months) == expected


def test_promo_code_prefix_is_latin(api):
    """Дефект, найденный только в Docker: префикс промокода брался из первых
    трёх символов названия позиции, и для русского названия код выходил
    кириллическим — «ПОД-5ICV-NEJE». Такой код не примет ни одна партнёрская
    система: он уходит наружу и вводится в чужих интерфейсах."""
    api.as_employee()
    item = next(i for i in api.get("/api/catalog").json() if i["item_type"] == "gift")
    order = api.post("/api/checkout",
                     json={"lines": [{"item_id": item["id"], "options": {}}]}).json()["orders"][0]

    code = order["code"]
    assert code, "промокод должен быть выдан сразу"
    assert code.isascii(), f"промокод содержит не-ASCII символы: {code}"
    assert all(ch.isalnum() or ch == "-" for ch in code), code


@pytest.mark.parametrize("field,length", [
    ("title", 300),
    ("supplier", 300),
    ("category", 200),
])
def test_long_strings_rejected_with_422(api, field, length):
    """Дефект, найденный только в Docker: схема позиции не ограничивала длину
    строк, а модель объявляет String(255). SQLite писал молча, PostgreSQL
    отклонял на уровне СУБД — пользователь получал 500 вместо внятного отказа."""
    api.as_admin()
    section_id = api.get("/api/sections").json()[0]["id"]
    payload = {"section_id": section_id, "title": "Позиция", "price": 100,
               "item_type": "gift", field: "я" * length}

    r = api.post("/api/pult/catalog", json=payload)
    assert r.status_code == 422, f"ожидался отказ валидации, получено {r.status_code}: {r.text}"


def test_valid_item_still_passes(api):
    """Контроль: ограничения не должны ломать обычное создание позиции."""
    api.as_admin()
    section_id = api.get("/api/sections").json()[0]["id"]
    r = api.post("/api/pult/catalog", json={
        "section_id": section_id, "title": "Сертификат в книжный магазин",
        "price": 2500, "item_type": "gift", "supplier": "ООО «Книги»",
        "description": "Электронный сертификат, срок действия год.",
    })
    assert r.status_code == 201, r.text


def test_decision_comment_goes_in_body_not_query(api):
    """Дефект: решение по заявке принималось строкой запроса
    (`?approved=false&comment=...`). Комментарий согласующего — это текст
    о конкретном человеке, а строка запроса пишется в логи сервера,
    обратного прокси и хостинга, откуда её никто не удаляет."""
    api.as_admin()
    api.post("/api/pult/points/grant",
             json={"user_id": 1, "amount": 30000, "reason": "под тест", "burnable": True})

    api.as_employee()
    item = next(i for i in api.get("/api/catalog").json()
                if i.get("approvals") and not i["needs_doc"] and not i["has_slots"]
                and i["item_type"] not in ("vac", "dms-family"))
    order = api.post("/api/checkout",
                     json={"lines": [{"item_id": item["id"], "options": {}}]}).json()["orders"][0]

    api.as_hr()
    # Старый способ больше не работает: тело обязательно.
    assert api.post(f"/api/pult/orders/{order['id']}/decide?approved=false").status_code == 422

    reason = "отказано: сотрудник на испытательном сроке"
    r = api.post(f"/api/pult/orders/{order['id']}/decide",
                 json={"approved": False, "comment": reason})
    assert r.status_code == 200, r.text
    assert r.json()["approvals_chain"][0]["comment"] == reason, "комментарий должен сохраниться"

    api.as_admin()   # журнал аудита HR закрыт по матрице прав
    audit = api.get("/api/pult/audit").json()
    assert any(reason in (a["detail"] or "") for a in audit), "решение должно попасть в аудит"


def test_decision_comment_length_is_limited(api):
    """Комментарий пишется в текстовое поле модели — длину ограничивает схема,
    иначе PostgreSQL отдаст 500 там, где нужен внятный отказ."""
    api.as_admin()
    api.post("/api/pult/points/grant",
             json={"user_id": 1, "amount": 30000, "reason": "под тест", "burnable": True})

    api.as_employee()
    item = next(i for i in api.get("/api/catalog").json()
                if i.get("approvals") and not i["needs_doc"] and not i["has_slots"]
                and i["item_type"] not in ("vac", "dms-family"))
    order = api.post("/api/checkout",
                     json={"lines": [{"item_id": item["id"], "options": {}}]}).json()["orders"][0]

    api.as_hr()
    r = api.post(f"/api/pult/orders/{order['id']}/decide",
                 json={"approved": True, "comment": "я" * 3000})
    assert r.status_code == 422, f"ожидался отказ валидации, получено {r.status_code}"

    # заявка должна остаться нерешённой
    assert api.get("/api/pult/orders").json(), "список заказов должен быть доступен"
    chain = next(o for o in api.get("/api/pult/orders").json()
                 if o["id"] == order["id"])["approvals_chain"]
    assert chain[0]["result"] is None, "отклонённая валидация не должна менять заявку"
