"""Разграничение прав — раздел 3 ТЗ.

Проверяется на уровне API, в обход интерфейса: если роль не должна видеть
раздел, запрос к нему обязан вернуть отказ независимо от того, что
нарисовано на экране.
"""


def test_anonymous_is_rejected(api):
    assert api.get("/api/me").status_code == 401


def test_bad_password_rejected(api):
    r = api.c.post("/api/auth/login-json",
                   json={"email": "a.drozdiuk@corp.example", "password": "wrong"})
    assert r.status_code == 401


def test_unknown_email_reports_hr_desync(api):
    """ФТ-ОНБ.6: сотруднику, которого нет в кадровом контуре, объясняют причину."""
    r = api.c.post("/api/auth/login-json",
                   json={"email": "ghost@corp.example", "password": "demo1234"})
    assert r.status_code == 404
    assert "1С:ЗУП" in r.json()["detail"]


def test_invite_requires_valid_code(api):
    bad = api.c.post("/api/auth/invite",
                     json={"email": "a.drozdiuk@corp.example", "code": "WRONG"})
    assert bad.status_code == 400

    good = api.c.post("/api/auth/invite",
                      json={"email": "a.drozdiuk@corp.example", "code": "KL-2026-7788"})
    assert good.status_code == 200
    assert good.json()["access_token"]


def test_employee_sees_all_sections(api):
    data = api.as_employee().get("/api/me").json()
    assert set(data["sections"]) == {"common", "health", "learn", "rest", "family", "life"}
    assert data["pult"] == []


def test_decree_has_no_health_section(api):
    """Роль «Декрет»: доступны все разделы, кроме страховых программ."""
    data = api.as_decree().get("/api/me").json()
    assert "health" not in data["sections"]
    assert "common" in data["sections"]

    titles = [i["title"] for i in api.get("/api/catalog").json()]
    assert not any("ДМС" in t or "Стоматология" in t for t in titles), \
        "страховые позиции не должны попадать в каталог"


def test_vip_sees_only_common(api):
    data = api.as_vip().get("/api/me").json()
    assert data["sections"] == ["common"]


def test_excluded_is_denied_everywhere(api):
    """Служебная группа Exclusion: витрина закрыта целиком."""
    api.as_excluded()
    for path in ("/api/me", "/api/catalog", "/api/orders", "/api/sections"):
        assert api.get(path).status_code == 403, path


def test_hr_pult_is_limited(api):
    """HR получает Пульт без настроек, аудита и аномалий."""
    api.as_hr()
    assert api.get("/api/pult/dashboard").status_code == 200
    assert api.get("/api/pult/budgets").status_code == 200

    for path in ("/api/pult/audit", "/api/pult/anomalies", "/api/pult/settings"):
        assert api.get(path).status_code == 403, path


def test_admin_has_full_pult(api):
    api.as_admin()
    for path in ("/api/pult/dashboard", "/api/pult/audit",
                 "/api/pult/anomalies", "/api/pult/settings"):
        assert api.get(path).status_code == 200, path


def test_employee_cannot_reach_pult(api):
    api.as_employee()
    for path in ("/api/pult/dashboard", "/api/pult/people", "/api/pult/audit"):
        assert api.get(path).status_code == 403, path


def test_only_admin_changes_roles(api):
    """РОЛ.4: смена роли — операция администратора."""
    api.as_hr()
    assert api.post("/api/pult/people/1/role", json={"role": "admin"}).status_code == 403

    api.as_admin()
    assert api.post("/api/pult/people/3/role", json={"role": "vip"}).status_code == 200


def test_role_change_is_audited(api):
    api.as_admin()
    api.post("/api/pult/people/3/role", json={"role": "vip"})
    actions = [r["action"] for r in api.get("/api/pult/audit").json()]
    assert "Изменение роли" in actions


def test_demo_accounts_hidden_outside_demo_mode(api, monkeypatch):
    """Маршрут отдаёт пароли и существует только ради стенда."""
    from app.config import settings

    assert api.c.get("/api/auth/demo-accounts").status_code == 200

    monkeypatch.setattr(settings, "demo_mode", False)
    assert api.c.get("/api/auth/demo-accounts").status_code == 404
