"""Оформление заказа и согласование — разделы 4.2, 4.5, 4.7 ТЗ.

Все проверки выполняются на сервере: интерфейс можно обойти прямым
запросом, поэтому каждое правило проверяется именно так.
"""

import pytest


def item_by_title(api, title):
    for i in api.get("/api/catalog").json():
        if title in i["title"]:
            return i
    raise AssertionError(f"позиция «{title}» не найдена в каталоге")


def balance(api):
    return api.get("/api/me").json()["balance"]


# ---------- успешное оформление ----------

def test_checkout_debits_points_and_creates_order(api):
    api.as_employee()
    before = balance(api)["available"]
    item = item_by_title(api, "Подарочная карта")

    r = api.post("/api/checkout", json={"lines": [{"item_id": item["id"], "options": {}}]})
    assert r.status_code == 200, r.text

    data = r.json()
    assert data["spent"] == item["price"]
    assert data["balance"]["available"] == before - item["price"]
    assert len(data["orders"]) == 1


def test_gift_order_issues_code_immediately(api):
    """ФТ-СЕР.2: код выдаётся в момент покупки."""
    api.as_employee()
    item = item_by_title(api, "Подарочная карта")
    order = api.post("/api/checkout",
                     json={"lines": [{"item_id": item["id"], "options": {}}]}).json()["orders"][0]

    assert order["code"], "промокод должен быть выдан"
    assert order["status"] == "done"


def test_promo_stock_decreases(api):
    api.as_employee()
    item = item_by_title(api, "Подарочная карта")
    before = item["available_stock"]

    api.post("/api/checkout", json={"lines": [{"item_id": item["id"], "options": {}}]})
    after = item_by_title(api, "Подарочная карта")["available_stock"]
    assert after == before - 1


def test_multiple_lines_in_one_checkout(api):
    """Коллизия публичных идентификаторов при оформлении подряд."""
    api.as_employee()
    first = item_by_title(api, "Подарочная карта")
    second = item_by_title(api, "Беспроводная гарнитура")

    r = api.post("/api/checkout", json={"lines": [
        {"item_id": first["id"], "options": {}},
        {"item_id": second["id"], "options": {}},
    ]})
    assert r.status_code == 200, r.text

    ids = [o["public_id"] for o in r.json()["orders"]]
    assert len(set(ids)) == 2, f"идентификаторы заказов совпали: {ids}"


# ---------- проверки, блокирующие оформление ----------

def test_budget_overrun_rejected(api):
    """ФТ-ОНБ.5: оформление блокируется при превышении бюджета."""
    api.as_employee()
    available = balance(api)["available"]
    expensive = next(i for i in api.get("/api/catalog").json() if i["price"] > available)

    r = api.post("/api/checkout", json={"lines": [{"item_id": expensive["id"], "options": {}}]})
    assert r.status_code == 409
    assert "Превышение бюджета" in r.json()["detail"]
    assert balance(api)["available"] == available, "баллы не должны списаться"


def test_slot_required(api):
    """ФТ-КАТ.6: позиция по записи требует выбранного слота."""
    api.as_employee()
    item = item_by_title(api, "Консультация психолога")

    r = api.post("/api/checkout", json={"lines": [{"item_id": item["id"], "options": {}}]})
    assert r.status_code == 400
    assert "дату и время" in r.json()["detail"]

    ok = api.post("/api/checkout",
                  json={"lines": [{"item_id": item["id"], "options": {"slot": "09.10, 15:30"}}]})
    assert ok.status_code == 200


def test_document_required(api):
    """ФТ-ЛГТ.8: позиция с подтверждающими документами без файла не проходит."""
    api.as_employee()
    item = item_by_title(api, "Компенсация рабочего места")

    r = api.post("/api/checkout", json={"lines": [{"item_id": item["id"], "options": {}}]})
    assert r.status_code == 400
    assert "документ" in r.json()["detail"]


def test_vacation_blocked_when_days_left(api):
    """ФТ-ЛГТ.4: дни отпуска недоступны при неотгулянном основном."""
    api.as_employee()
    item = item_by_title(api, "День дополнительного отпуска")

    r = api.post("/api/checkout",
                 json={"lines": [{"item_id": item["id"], "options": {"days": 1}}]})
    assert r.status_code == 409
    assert "отгулянном" in r.json()["detail"]


@pytest.mark.parametrize("birth,ok", [
    ("1990-05-12", True),
    ("2015-03-01", True),
    ("1950-01-01", False),
    ("2026-01-01", False),
])
def test_family_dms_age_validation(api, birth, ok):
    """ФТ-ДМС.5: возраст застрахованного от 1 до 65 лет."""
    api.as_employee()
    item = item_by_title(api, "ДМС для члена семьи")
    payload = {"lines": [{"item_id": item["id"], "options": {
        "fio": "Иванова М. П.", "bd": birth, "rel": "Супруга", "sex": "Ж"}}]}

    r = api.post("/api/checkout", json=payload)
    if ok:
        assert r.status_code == 200, r.text
    else:
        assert r.status_code == 400
        assert "вне условий программы" in r.json()["detail"]


def test_family_dms_requires_full_data(api):
    api.as_employee()
    item = item_by_title(api, "ДМС для члена семьи")
    r = api.post("/api/checkout",
                 json={"lines": [{"item_id": item["id"], "options": {"fio": "Иванова"}}]})
    assert r.status_code == 400


def test_item_limit_enforced(api):
    """ФТ-БЮД.6: лимит покупок по позиции считается по фактическим заказам."""
    api.as_employee()
    item = item_by_title(api, "Подарочная карта")
    assert item["limit_count"] == 2

    for _ in range(2):
        assert api.post("/api/checkout",
                        json={"lines": [{"item_id": item["id"], "options": {}}]}).status_code == 200

    third = api.post("/api/checkout", json={"lines": [{"item_id": item["id"], "options": {}}]})
    assert third.status_code == 409
    assert "лимит" in third.json()["detail"].lower()


def test_frozen_points_block_checkout(api):
    """ФТ-БАЛ.9: при заморозке оформление невозможно."""
    api.as_admin()
    api.post("/api/pult/points/freeze/1", json={"value": True})

    api.as_employee()
    item = item_by_title(api, "Подарочная карта")
    r = api.post("/api/checkout", json={"lines": [{"item_id": item["id"], "options": {}}]})
    assert r.status_code == 409


def test_empty_cart_rejected(api):
    api.as_employee()
    assert api.post("/api/checkout", json={"lines": []}).status_code == 400


# ---------- отмена ----------

def test_cancel_refunds_points(api):
    """ФТ-ЗАК.5: отмена возвращает баллы."""
    api.as_employee()
    before = balance(api)["available"]
    item = item_by_title(api, "Консультация психолога")

    order = api.post("/api/checkout", json={"lines": [
        {"item_id": item["id"], "options": {"slot": "09.10, 15:30"}}]}).json()["orders"][0]
    assert balance(api)["available"] == before - item["price"]

    r = api.post(f"/api/orders/{order['id']}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancel"
    assert balance(api)["available"] == before, "баллы должны вернуться полностью"


def test_gift_order_cannot_be_cancelled(api):
    """ФТ-ЗАК.6: промокод в ротацию не возвращается."""
    api.as_employee()
    item = item_by_title(api, "Подарочная карта")
    order = api.post("/api/checkout",
                     json={"lines": [{"item_id": item["id"], "options": {}}]}).json()["orders"][0]

    r = api.post(f"/api/orders/{order['id']}/cancel")
    assert r.status_code == 409
    assert "отмена невозможна" in r.json()["detail"]


def test_cannot_cancel_foreign_order(api):
    api.as_employee()
    item = item_by_title(api, "Консультация психолога")
    order = api.post("/api/checkout", json={"lines": [
        {"item_id": item["id"], "options": {"slot": "09.10, 15:30"}}]}).json()["orders"][0]

    api.as_decree()
    assert api.post(f"/api/orders/{order['id']}/cancel").status_code == 404


# ---------- согласование ----------

def test_order_with_approvals_goes_to_approval(api):
    """ФТ-ЗАК.3: позиция с согласующими попадает в статус «на согласовании»."""
    api.as_employee()
    item = item_by_title(api, "Гибкий график")
    assert item["approvals"] == ["Руководитель"]

    order = api.post("/api/checkout",
                     json={"lines": [{"item_id": item["id"], "options": {}}]}).json()["orders"][0]
    assert order["status"] == "approve"
    assert [a["approver"] for a in order["approvals_chain"]] == ["Руководитель"]


def test_approval_releases_order(api):
    api.as_employee()
    item = item_by_title(api, "Гибкий график")
    order = api.post("/api/checkout",
                     json={"lines": [{"item_id": item["id"], "options": {}}]}).json()["orders"][0]

    api.as_hr()
    r = api.post(f"/api/pult/orders/{order['id']}/decide",
                 json={"approved": True})
    assert r.status_code == 200
    assert r.json()["status"] == "work"
    assert r.json()["approvals_chain"][0]["result"] is True


def test_rejection_refunds_points(api):
    """При отклонении заявки списанные баллы возвращаются сотруднику."""
    api.as_admin()
    api.post("/api/pult/points/grant",
             json={"user_id": 1, "amount": 10000, "reason": "под тест", "burnable": True})

    api.as_employee()
    before = balance(api)["available"]
    item = item_by_title(api, "Участие в отраслевой конференции")

    order = api.post("/api/checkout", json={"lines": [
        {"item_id": item["id"], "options": {"doc": "программа.pdf"}}]}).json()["orders"][0]
    assert balance(api)["available"] == before - item["price"]

    api.as_hr()
    api.post(f"/api/pult/orders/{order['id']}/decide",
                 json={"approved": False, "comment": "бюджет подразделения исчерпан"})

    api.as_employee()
    assert balance(api)["available"] == before, "при отклонении баллы возвращаются"


def test_cannot_approve_own_request(api):
    """Согласовать собственную заявку нельзя ни при какой роли."""
    api.as_hr()
    item = item_by_title(api, "Гибкий график")
    order = api.post("/api/checkout",
                     json={"lines": [{"item_id": item["id"], "options": {}}]}).json()["orders"][0]

    r = api.post(f"/api/pult/orders/{order['id']}/decide",
                 json={"approved": True})
    assert r.status_code == 403
    assert "собственную" in r.json()["detail"]


def test_decide_rejects_wrong_status(api):
    api.as_employee()
    item = item_by_title(api, "Подарочная карта")
    order = api.post("/api/checkout",
                     json={"lines": [{"item_id": item["id"], "options": {}}]}).json()["orders"][0]

    api.as_hr()
    r = api.post(f"/api/pult/orders/{order['id']}/decide",
                 json={"approved": True})
    assert r.status_code == 409
