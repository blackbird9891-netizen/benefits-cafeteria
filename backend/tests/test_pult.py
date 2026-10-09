"""Административная панель — разделы 4.5, 4.6, 4.8, 4.14, 4.16, 4.17 ТЗ."""


def test_dashboard_aggregates(api):
    d = api.as_admin().get("/api/pult/dashboard").json()

    assert d["totals"]["granted"] > 0
    assert 0 <= d["usage_pct"] <= 100
    assert d["by_department"], "подразделения должны быть сгруппированы"
    assert sum(d["orders_by_month"]) == d["orders_total"]
    assert d["data_note"], "ФТ-АНЛ.5: неполнота данных должна отмечаться"


def test_dashboard_lists_pending_work(api):
    """Открытые заявки, обращения и аномалии попадают в «требует действия»."""
    types = {n["type"] for n in api.as_admin().get("/api/pult/dashboard").json()["needs_action"]}
    assert "order" in types
    assert "ticket" in types
    assert "anomaly" in types


# ---------- бюджеты ----------

def test_mass_budget_preview_lists_exclusions(api):
    """ФТ-БЮД.3: сотрудники без грейда и служебные роли попадают в исключения."""
    d = api.as_hr().post("/api/pult/budgets/preview").json()

    assert d["rows"], "должны быть строки к пересчёту"
    reasons = {e["reason"] for e in d["excluded"]}
    assert "грейд не указан" in reasons or "служебная группа Exclusion" in reasons


def test_mass_budget_apply_changes_values(api):
    api.as_hr()
    preview = api.post("/api/pult/budgets/preview").json()
    applied = api.post("/api/pult/budgets/apply").json()

    assert applied["applied"] == len(preview["rows"])

    rows = {r["user_id"]: r["budget"] for r in api.get("/api/pult/budgets").json()["rows"]}
    for r in preview["rows"]:
        assert rows[r["user_id"]] == r["will"]


# ---------- каталог ----------

def test_archive_hides_item_from_catalog(api):
    """ФТ-КАТ.4: архивная позиция исчезает из витрины."""
    api.as_hr()
    item = api.get("/api/pult/catalog").json()[0]
    api.post(f"/api/pult/catalog/{item['id']}/archive", json={"value": True})

    api.as_employee()
    assert item["id"] not in [i["id"] for i in api.get("/api/catalog").json()]


def test_delete_blocked_when_orders_exist(api):
    """ФТ-КАТ.4: удаление позиции с активными заказами запрещено."""
    api.as_employee()
    item = next(i for i in api.get("/api/catalog").json() if "Подарочная карта" in i["title"])
    api.post("/api/checkout", json={"lines": [{"item_id": item["id"], "options": {}}]})

    api.as_hr()
    r = api.delete(f"/api/pult/catalog/{item['id']}")
    assert r.status_code == 409
    assert "заказах" in r.json()["detail"]


def test_delete_allowed_without_orders(api):
    api.as_hr()
    created = api.post("/api/pult/catalog", json={
        "section_id": 1, "title": "Временная позиция", "category": "Тест", "price": 100,
    }).json()
    assert api.delete(f"/api/pult/catalog/{created['id']}").status_code == 204


def test_create_item_validates_section(api):
    api.as_hr()
    r = api.post("/api/pult/catalog", json={
        "section_id": 999, "title": "Позиция в несуществующем разделе", "price": 100,
    })
    assert r.status_code == 400


# ---------- начисления ----------

def test_manual_grant_requires_reason(api):
    """ФТ-БАЛ.8: комментарий обязателен."""
    api.as_hr()
    r = api.post("/api/pult/points/grant",
                 json={"user_id": 1, "amount": 500, "reason": ""})
    assert r.status_code == 422


def test_manual_grant_above_cap_raises_anomaly(api):
    """ФТ-АУД.2: превышение потолка попадает в журнал аномалий."""
    api.as_admin()
    before = len(api.get("/api/pult/anomalies").json())

    api.post("/api/pult/points/grant",
             json={"user_id": 1, "amount": 50000, "reason": "крупное начисление"})

    anomalies = api.get("/api/pult/anomalies").json()
    assert len(anomalies) == before + 1
    assert "потолка" in anomalies[0]["rule"]


def test_manual_spend_rejects_when_insufficient(api):
    api.as_hr()
    r = api.post("/api/pult/points/spend",
                 json={"user_id": 1, "amount": 10 ** 9, "reason": "слишком много"})
    assert r.status_code == 409


def test_anomaly_can_be_marked_legit(api):
    """ФТ-АУД.3."""
    api.as_admin()
    anomaly = api.get("/api/pult/anomalies").json()[0]
    r = api.post(f"/api/pult/anomalies/{anomaly['id']}/legit")
    assert r.status_code == 200
    assert r.json()["status"] == "legit"


# ---------- окна выбора ----------

def test_campaign_rejects_reversed_dates(api):
    """ФТ-ОКН.5: дата окончания не может быть раньше начала."""
    r = api.as_admin().post("/api/pult/campaigns", json={
        "title": "Некорректная", "date_from": "2026-12-01", "date_to": "2026-11-01",
    })
    assert r.status_code == 400


def test_closed_window_blocks_checkout(api):
    """ФТ-ОКН.4, режим restrict: вне окна оформление заблокировано."""
    api.as_admin()
    campaign = api.get("/api/pult/campaigns").json()[0]
    api.post(f"/api/pult/campaigns/{campaign['id']}/toggle")

    api.as_employee()
    item = next(i for i in api.get("/api/catalog").json() if "Подарочная карта" in i["title"])
    r = api.post("/api/checkout", json={"lines": [{"item_id": item["id"], "options": {}}]})
    assert r.status_code == 409
    assert "Окно выбора закрыто" in r.json()["detail"]


def test_inform_mode_allows_checkout_outside_window(api):
    """ФТ-ОКН.4, режим inform: изменения разрешены."""
    api.as_admin()
    campaign = api.get("/api/pult/campaigns").json()[0]
    api.post(f"/api/pult/campaigns/{campaign['id']}/toggle")
    api.put("/api/pult/settings/window_mode", json={"value": "inform"})

    api.as_employee()
    item = next(i for i in api.get("/api/catalog").json() if "Подарочная карта" in i["title"])
    assert api.post("/api/checkout",
                    json={"lines": [{"item_id": item["id"], "options": {}}]}).status_code == 200


# ---------- промокоды ----------

def test_promo_batch_load_increases_total(api):
    api.as_hr()
    batch = api.get("/api/pult/promo").json()["batches"][0]
    r = api.post(f"/api/pult/promo/{batch['item_id']}/load", json={"count": 50})
    assert r.json()["total"] == batch["total"] + 50


def test_low_stock_flagged(api):
    """ФТ-СЕР.3: остаток ниже порога отмечается."""
    batches = api.as_hr().get("/api/pult/promo").json()["batches"]
    flagged = [b for b in batches if b["below_threshold"]]
    assert flagged, "в демо-данных есть партия с остатком ниже порога"


# ---------- выгрузка ----------

def test_export_has_all_required_columns(api):
    """ФТ-АНЛ.6: пятнадцать полей из ТЗ."""
    d = api.as_hr().get("/api/pult/export").json()

    assert len(d["columns"]) == 15
    for required in ("ID заказа", "ФИО", "Пол", "Дата рождения", "Телефон",
                     "Наименование лота", "Email", "Сумма заказа, ₽", "Адрес доставки"):
        assert required in d["columns"], required


def test_export_excludes_cancelled(api):
    api.as_employee()
    item = next(i for i in api.get("/api/catalog").json() if "Консультация психолога" in i["title"])
    order = api.post("/api/checkout", json={"lines": [
        {"item_id": item["id"], "options": {"slot": "09.10, 15:30"}}]}).json()["orders"][0]

    api.as_hr()
    before = len(api.get("/api/pult/export").json()["rows"])

    api.as_employee()
    api.post(f"/api/orders/{order['id']}/cancel")

    api.as_hr()
    assert len(api.get("/api/pult/export").json()["rows"]) == before - 1


def test_export_csv_downloads(api):
    r = api.as_hr().get("/api/pult/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    assert "ID заказа" in r.text


# ---------- настройки ----------

def test_setting_change_affects_behaviour(api):
    """Раздел 4.15: параметры меняются без доработки кода."""
    api.as_admin()
    api.put("/api/pult/settings/transfer_min", json={"value": "9000"})

    api.as_employee()
    r = api.post("/api/transfer", json={"to_user_id": 3, "amount": 1000})
    assert r.status_code == 400
    assert "9000" in r.json()["detail"]


def test_setting_change_is_audited(api):
    api.as_admin()
    api.put("/api/pult/settings/transfer_fee", json={"value": "30"})
    details = [r["detail"] for r in api.get("/api/pult/audit").json()]
    assert any("transfer_fee" in d for d in details)


def test_unknown_setting_404(api):
    assert api.as_admin().put("/api/pult/settings/nope", json={"value": "1"}).status_code == 404


# ---------- обращения ----------

def test_ticket_lifecycle(api):
    """Раздел 4.13: обращение создаётся сотрудником и закрывается поддержкой."""
    api.as_employee()
    created = api.post("/api/tickets", json={
        "topic": "Вопрос по баллам", "body": "Когда сгорят баллы за август?",
    }).json()
    assert created["status"] == "open"
    assert created["public_id"].startswith("SUP-")

    api.as_hr()
    answered = api.post(
        f"/api/pult/tickets/{created['id']}/answer",
                    json={"answer": "Ответ направлен"}).json()
    assert answered["status"] == "closed"
    assert answered["answer"]

    api.as_employee()
    mine = api.get("/api/tickets").json()
    assert any(t["id"] == created["id"] and t["status"] == "closed" for t in mine)
