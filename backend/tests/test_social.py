"""ДМС, переводы, благотворительность, опросы — разделы 4.3, 4.11, 4.12 ТЗ."""

import pytest


# ---------- ДМС ----------

def test_policy_returned(api):
    """ФТ-ДМС.1, ФТ-ДМС.6: полис и его статус."""
    d = api.as_employee().get("/api/dms").json()
    assert d["base_program"]
    assert d["status"] == "Действует"
    assert d["refused"] is False


def test_refuse_keeps_points(api):
    """ФТ-ДМС.8: при отказе от базового ДМС баллы остаются у сотрудника."""
    api.as_employee()
    before = api.get("/api/me").json()["balance"]["available"]

    r = api.post("/api/dms/refuse?value=true")
    assert r.json()["refused"] is True
    assert api.get("/api/me").json()["balance"]["available"] == before

    assert api.post("/api/dms/refuse?value=false").json()["refused"] is False


def test_extension_lands_in_policy(api):
    """ФТ-ДМС.3: купленное расширение появляется в полисе."""
    api.as_employee()
    ext = next(i for i in api.get("/api/catalog").json() if i["item_type"] == "dms")
    api.post("/api/checkout", json={"lines": [{"item_id": ext["id"], "options": {}}]})

    assert ext["id"] in api.get("/api/dms").json()["extensions"]


def test_family_member_added_after_purchase(api):
    """ФТ-ДМС.4: член семьи появляется в списке после оформления."""
    api.as_employee()
    item = next(i for i in api.get("/api/catalog").json() if i["item_type"] == "dms-family")

    api.post("/api/checkout", json={"lines": [{"item_id": item["id"], "options": {
        "fio": "Иванова Мария Петровна", "bd": "1991-07-20", "rel": "Супруга", "sex": "Ж"}}]})

    family = api.get("/api/dms/family").json()
    assert len(family) == 1
    assert family[0]["full_name"] == "Иванова Мария Петровна"
    assert family[0]["price"] > 0, "стоимость считается по возрастной группе"


@pytest.mark.parametrize("birth,expected", [
    ("2015-01-01", 5200),
    ("1991-01-01", 6800),
    ("1975-01-01", 8900),
    ("1965-01-01", 11500),
])
def test_family_price_by_age_group(birth, expected):
    """Стоимость ДМС для члена семьи зависит от возраста."""
    from datetime import date

    from app.api.shop import family_price

    assert family_price(date.fromisoformat(birth)) == expected


# ---------- переводы ----------

def test_transfer_applies_commission(api):
    """ФТ-СОЦ.1: комиссия удерживается при переводе."""
    api.as_employee()
    sender_before = api.get("/api/me").json()["balance"]["available"]

    r = api.post("/api/transfer", json={"to_user_id": 3, "amount": 1000})
    assert r.status_code == 200

    data = r.json()
    assert data["fee"] == 250, "ставка по умолчанию 25%"
    assert data["received"] == 750
    assert api.get("/api/me").json()["balance"]["available"] == sender_before - 1000


def test_transfer_credits_recipient(api):
    api.as_employee()
    api.post("/api/transfer", json={"to_user_id": 3, "amount": 1000})

    api.login("d.kim@corp.example", "demo1234")
    lots = api.get("/api/me/points").json()
    assert any("Перевод от" in l["reason"] and l["amount"] == 750 for l in lots)


def test_transfer_below_minimum_rejected(api):
    """ФТ-СОЦ.2, ФТ-СОЦ.6."""
    r = api.as_employee().post("/api/transfer", json={"to_user_id": 3, "amount": 100})
    assert r.status_code == 400
    assert "Минимальная сумма" in r.json()["detail"]


def test_transfer_to_self_rejected(api):
    r = api.as_employee().post("/api/transfer", json={"to_user_id": 1, "amount": 1000})
    assert r.status_code == 400


def test_transfer_beyond_balance_rejected(api):
    r = api.as_employee().post("/api/transfer", json={"to_user_id": 3, "amount": 10 ** 7})
    assert r.status_code == 409


# ---------- благотворительность ----------

def test_charity_matches_company_contribution(api):
    """ФТ-СОЦ.4, ФТ-СОЦ.5: сертификат и софинансирование."""
    api.as_employee()
    r = api.post("/api/charity", json={"fund": "Фонд «Вера»", "amount": 1000})
    assert r.status_code == 200

    data = r.json()
    assert data["certificate"].startswith("CRT-")
    assert data["fund_receives"] == 2000, "множитель по умолчанию ×2"


def test_charity_below_minimum_rejected(api):
    r = api.as_employee().post("/api/charity", json={"fund": "Фонд «Вера»", "amount": 10})
    assert r.status_code == 400


# ---------- опросы и новости ----------

def test_survey_vote_counted_once(api):
    """ФТ-ГЕЙ.1: повторное голосование отклоняется."""
    api.as_employee()
    survey = api.get("/api/surveys").json()[0]
    before = survey["votes"][0]

    assert api.post(f"/api/surveys/{survey['id']}/vote?choice=0").status_code == 200

    after = api.get("/api/surveys").json()[0]
    assert after["votes"][0] == before + 1
    assert after["my_vote"] == 0

    assert api.post(f"/api/surveys/{survey['id']}/vote?choice=1").status_code == 409


def test_survey_rejects_invalid_choice(api):
    api.as_employee()
    survey = api.get("/api/surveys").json()[0]
    assert api.post(f"/api/surveys/{survey['id']}/vote?choice=99").status_code == 400


def test_comment_goes_to_moderation(api):
    """ФТ-КОМ.1: комментарии проходят модерацию."""
    api.as_employee()
    post = api.get("/api/news").json()[0]
    before = len(post["comments"])

    r = api.post(f"/api/news/{post['id']}/comment", json={"body": "Вопрос по срокам"})
    assert r.status_code == 201

    after = next(n for n in api.get("/api/news").json() if n["id"] == post["id"])
    assert len(after["comments"]) == before, "до модерации комментарий не публикуется"


def test_empty_comment_rejected(api):
    api.as_employee()
    post = api.get("/api/news").json()[0]
    assert api.post(f"/api/news/{post['id']}/comment", json={"body": ""}).status_code == 422
