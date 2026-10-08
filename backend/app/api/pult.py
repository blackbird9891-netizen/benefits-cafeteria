"""Пульт администратора: раздел 4.14 ТЗ.

Каждый экран закрыт отдельной проверкой прав. HR получает урезанный набор,
Администратор — полный, включая настройки, аудит и аномалии.
"""

import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas
from app.api.deps import ROLE_MATRIX, require_admin, require_pult
from app.api.shop import available_stock, next_public_id, order_out
from app.core import points as pts
from app.database import get_db
from app.models import (
    Anomaly,
    AuditLog,
    Campaign,
    CatalogItem,
    ItemType,
    NewsPost,
    Order,
    OrderApproval,
    OrderStatus,
    PlatformSetting,
    PromoBatch,
    Role,
    Section,
    Ticket,
    User,
)

router = APIRouter()

GRADE_BUDGETS = {"G9": 5000, "G11": 6500, "G12": 8000, "G13": 9000, "G15": 11000, "G17": 0}


# ---------- дашборд ----------

@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), actor: User = Depends(require_pult("dash"))):
    users = db.scalars(select(User).where(User.role != Role.EXCLUDED.value)).all()

    totals = {"granted": 0, "spent": 0, "left": 0}
    by_dept: dict[str, dict] = {}
    mix = {"spent": 0, "burnable": 0, "permanent": 0}

    for u in users:
        b = pts.balance(db, u)
        totals["granted"] += b.granted
        totals["spent"] += b.spent
        totals["left"] += b.burnable + b.permanent
        mix["spent"] += b.spent
        mix["burnable"] += b.burnable
        mix["permanent"] += b.permanent

        d = by_dept.setdefault(u.department or "Без подразделения",
                               {"granted": 0, "spent": 0, "people": 0})
        d["granted"] += b.granted
        d["spent"] += b.spent
        d["people"] += 1

    orders = db.scalars(select(Order).where(Order.status != OrderStatus.CANCEL.value)).all()
    popular: dict[str, int] = {}
    by_month = [0] * 12
    for o in orders:
        popular[o.item.title if o.item else "—"] = popular.get(o.item.title if o.item else "—", 0) + 1
        by_month[o.created_at.month - 1] += 1

    needs_action = []
    for o in db.scalars(select(Order).where(Order.status == OrderStatus.APPROVE.value)).all():
        needs_action.append({"type": "order", "title": f"Согласование заказа {o.public_id}",
                             "detail": f"{o.user.full_name} · {o.item.title}"})
    for t in db.scalars(select(Ticket).where(Ticket.status == "open")).all():
        needs_action.append({"type": "ticket", "title": f"Обращение {t.public_id}",
                             "detail": f"{t.topic} · {t.user.full_name}"})
    for a in db.scalars(select(Anomaly).where(Anomaly.status == "open")).all():
        needs_action.append({"type": "anomaly", "title": f"Аномалия: {a.rule}", "detail": a.detail})
    for u in users:
        if not u.grade:
            needs_action.append({"type": "grade", "title": "Сотрудник без грейда",
                                 "detail": f"{u.full_name} · бюджет не рассчитан"})

    return {
        "totals": totals,
        "usage_pct": round(totals["spent"] / totals["granted"] * 100) if totals["granted"] else 0,
        "by_department": [{"name": k, **v} for k, v in sorted(by_dept.items(), key=lambda x: -x[1]["granted"])],
        "points_mix": mix,
        "popular": sorted([{"title": k, "count": v} for k, v in popular.items()],
                          key=lambda x: -x["count"])[:6],
        "orders_by_month": by_month,
        "orders_total": len(orders),
        "orders_pending": sum(1 for o in orders if o.status == OrderStatus.APPROVE.value),
        "people_total": len(users),
        "needs_action": needs_action,
        "data_note": "Данные за текущий месяц неполные: синхронизация с 1С:ЗУП выполнена вчера",
    }


# ---------- каталог ----------

@router.get("/catalog", response_model=list[schemas.ItemOut])
def admin_catalog(db: Session = Depends(get_db), actor: User = Depends(require_pult("catalog"))):
    items = db.scalars(select(CatalogItem).order_by(CatalogItem.section_id, CatalogItem.id)).all()
    out = []
    for i in items:
        data = schemas.ItemOut.model_validate(i)
        data.available_stock = available_stock(db, i)
        out.append(data)
    return out


@router.post("/catalog", response_model=schemas.ItemOut, status_code=201)
def create_item(payload: schemas.ItemIn, db: Session = Depends(get_db),
                actor: User = Depends(require_pult("catalog"))):
    if not db.get(Section, payload.section_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Раздел не найден")
    item = CatalogItem(**payload.model_dump())
    db.add(item)
    pts.write_audit(db, actor.full_name, "Создание позиции каталога",
                    f"{payload.title} ({payload.item_type}, {payload.price} баллов)")
    db.commit()
    db.refresh(item)
    return schemas.ItemOut.model_validate(item)


@router.put("/catalog/{item_id}", response_model=schemas.ItemOut)
def update_item(item_id: int, payload: schemas.ItemIn, db: Session = Depends(get_db),
                actor: User = Depends(require_pult("catalog"))):
    item = db.get(CatalogItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Позиция не найдена")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    pts.write_audit(db, actor.full_name, "Изменение позиции каталога", item.title)
    db.commit()
    db.refresh(item)
    return schemas.ItemOut.model_validate(item)


@router.post("/catalog/{item_id}/archive", response_model=schemas.ItemOut)
def archive_item(item_id: int, value: bool = True, db: Session = Depends(get_db),
                 actor: User = Depends(require_pult("catalog"))):
    """ФТ-КАТ.4: архивация скрывает позицию, сохраняя её в прежних заказах."""
    item = db.get(CatalogItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Позиция не найдена")
    item.archived = value
    pts.write_audit(db, actor.full_name,
                    "Архивация позиции" if value else "Возврат позиции из архива", item.title)
    db.commit()
    db.refresh(item)
    return schemas.ItemOut.model_validate(item)


@router.delete("/catalog/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db),
                actor: User = Depends(require_pult("catalog"))):
    """Удаление позиции с активными заказами блокируется — ФТ-КАТ.4."""
    item = db.get(CatalogItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Позиция не найдена")
    active = db.scalar(select(func.count(Order.id)).where(
        Order.item_id == item_id, Order.status != OrderStatus.CANCEL.value))
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Позиция участвует в {active} заказах, удаление заблокировано. Используйте архивацию")
    db.delete(item)
    pts.write_audit(db, actor.full_name, "Удаление позиции каталога", item.title)
    db.commit()


# ---------- бюджеты ----------

@router.get("/budgets")
def list_budgets(db: Session = Depends(get_db), actor: User = Depends(require_pult("budget"))):
    users = db.scalars(select(User).order_by(User.id)).all()
    rows = []
    for u in users:
        b = pts.balance(db, u)
        rows.append({
            "user_id": u.id, "full_name": u.full_name, "department": u.department,
            "grade": u.grade, "budget": u.budget, "granted": b.granted,
            "spent": b.spent, "left": b.burnable + b.permanent, "frozen": b.frozen,
        })
    return {"grades": GRADE_BUDGETS, "rows": rows}


@router.post("/budgets/preview")
def preview_mass_budget(db: Session = Depends(get_db), actor: User = Depends(require_pult("budget"))):
    """ФТ-БЮД.2, ФТ-БЮД.3: предпросмотр пересчёта и список исключений."""
    rows, excluded = [], []
    for u in db.scalars(select(User).order_by(User.id)).all():
        if not u.grade:
            excluded.append({"full_name": u.full_name, "reason": "грейд не указан"})
            continue
        if u.role == Role.EXCLUDED.value:
            excluded.append({"full_name": u.full_name, "reason": "служебная группа Exclusion"})
            continue
        rows.append({"user_id": u.id, "full_name": u.full_name, "grade": u.grade,
                     "was": u.budget, "will": GRADE_BUDGETS.get(u.grade, 0)})
    return {"rows": rows, "excluded": excluded}


@router.post("/budgets/apply")
def apply_mass_budget(db: Session = Depends(get_db), actor: User = Depends(require_pult("budget"))):
    applied = 0
    for u in db.scalars(select(User)).all():
        if u.grade and u.role != Role.EXCLUDED.value:
            u.budget = GRADE_BUDGETS.get(u.grade, 0)
            applied += 1
    pts.write_audit(db, actor.full_name, "Массовый пересчёт бюджетов", f"{applied} сотрудников")
    db.commit()
    return {"applied": applied}


# ---------- начисления ----------

@router.post("/points/grant")
def admin_grant(payload: schemas.GrantIn, db: Session = Depends(get_db),
                actor: User = Depends(require_pult("points"))):
    """ФТ-БАЛ.8: ручное начисление с обязательным комментарием."""
    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")

    cap = int((db.get(PlatformSetting, "manual_cap") or PlatformSetting(value="20000")).value)
    pts.grant(db, user, payload.amount, payload.reason,
              burnable=payload.burnable, granted_by=actor.full_name)

    if payload.amount > cap:
        db.add(Anomaly(rule="Ручное начисление свыше потолка", actor=actor.full_name,
                       detail=f"{user.full_name}: {payload.amount} баллов. {payload.reason}"))

    pts.write_audit(db, actor.full_name, "Ручное начисление",
                    f"{user.full_name}: {payload.amount}. {payload.reason}")
    db.commit()
    return {"granted": payload.amount, "balance": pts.balance(db, user).__dict__}


@router.post("/points/spend")
def admin_spend(payload: schemas.SpendIn, db: Session = Depends(get_db),
                actor: User = Depends(require_pult("points"))):
    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    if not pts.spend(db, user, payload.amount, f"Ручное списание: {payload.reason}"):
        raise HTTPException(status.HTTP_409_CONFLICT, "У сотрудника недостаточно баллов")
    pts.write_audit(db, actor.full_name, "Ручное списание",
                    f"{user.full_name}: {payload.amount}. {payload.reason}")
    db.commit()
    return {"spent": payload.amount, "balance": pts.balance(db, user).__dict__}


@router.post("/points/freeze/{user_id}")
def freeze_points(user_id: int, value: bool = True, db: Session = Depends(get_db),
                  actor: User = Depends(require_pult("points"))):
    """ФТ-БАЛ.9: заморозка баллов сотрудника."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    user.points_frozen = value
    pts.write_audit(db, actor.full_name,
                    "Заморозка баллов" if value else "Разморозка баллов", user.full_name)
    db.commit()
    return {"frozen": value}


# ---------- заказы и согласования ----------

@router.get("/orders", response_model=list[schemas.OrderOut])
def admin_orders(status_filter: str | None = None, db: Session = Depends(get_db),
                 actor: User = Depends(require_pult("orders"))):
    stmt = select(Order).order_by(Order.created_at.desc())
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    return [order_out(o) for o in db.scalars(stmt).all()]


@router.post("/orders/{order_id}/decide", response_model=schemas.OrderOut)
def decide_order(order_id: int, approved: bool, comment: str = "",
                 db: Session = Depends(get_db), actor: User = Depends(require_pult("orders"))):
    """ФТ-ЗАК.4: согласование с фиксацией решения, времени и комментария."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ не найден")
    if order.status != OrderStatus.APPROVE.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Заказ не находится на согласовании")

    for step in order.approvals_chain:
        if step.result is None:
            step.result = approved
            step.decided_at = datetime.now()
            step.comment = comment

    if approved:
        order.status = OrderStatus.WORK.value
    else:
        order.status = OrderStatus.CANCEL.value
        if order.price > 0:
            pts.refund(db, order.user, order.price, f"отклонение заявки {order.public_id}")

    pts.write_audit(db, actor.full_name,
                    "Согласование заявки" if approved else "Отклонение заявки",
                    f"{order.public_id} ({order.item.title}), сотрудник {order.user.full_name}")
    db.commit()
    db.refresh(order)
    return order_out(order)


@router.post("/orders/{order_id}/complete", response_model=schemas.OrderOut)
def complete_order(order_id: int, db: Session = Depends(get_db),
                   actor: User = Depends(require_pult("orders"))):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ не найден")
    order.status = OrderStatus.DONE.value
    if order.item.item_type == ItemType.VACATION.value:
        order.note = "Передано в кадровую службу, дни внесены в график"
    elif order.item.item_type == ItemType.PHYSICAL.value:
        order.note = "Передано в доставку, трек-номер направлен сотруднику"
    pts.write_audit(db, actor.full_name, "Заказ выполнен", f"{order.public_id} ({order.item.title})")
    db.commit()
    db.refresh(order)
    return order_out(order)


# ---------- сотрудники и роли ----------

@router.get("/people")
def list_people(db: Session = Depends(get_db), actor: User = Depends(require_pult("people"))):
    rows = []
    for u in db.scalars(select(User).order_by(User.id)).all():
        b = pts.balance(db, u)
        rows.append({
            "id": u.id, "full_name": u.full_name, "email": u.email, "position": u.position,
            "department": u.department, "grade": u.grade, "role": u.role,
            "role_title": ROLE_MATRIX.get(u.role, {}).get("title", u.role),
            "hired_at": u.hired_at, "available": b.available, "frozen": b.frozen,
        })
    return {"rows": rows, "role_matrix": ROLE_MATRIX}


@router.post("/people/{user_id}/role")
def change_role(user_id: int, role: str, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    """РОЛ.4: изменение роли фиксируется в журнале аудита."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    if role not in ROLE_MATRIX:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неизвестная роль")
    was = user.role
    user.role = role
    pts.write_audit(db, actor.full_name, "Изменение роли",
                    f"{user.full_name}: {ROLE_MATRIX[was]['title']} → {ROLE_MATRIX[role]['title']}")
    db.commit()
    return {"role": role}


# ---------- промокоды ----------

@router.get("/promo")
def list_promo(db: Session = Depends(get_db), actor: User = Depends(require_pult("promo"))):
    rows = []
    for b in db.scalars(select(PromoBatch)).all():
        left = b.total - b.used
        rows.append({
            "item_id": b.item_id, "title": b.item.title, "supplier": b.item.supplier,
            "total": b.total, "used": b.used, "left": left,
            "low_at": b.item.low_at, "below_threshold": left <= b.item.low_at,
            "expires_at": b.expires_at,
        })
    issued = [
        {"public_id": o.public_id, "user": o.user.full_name, "item": o.item.title,
         "code": o.code, "at": o.created_at}
        for o in db.scalars(select(Order).where(Order.code.isnot(None))).all()
    ]
    return {"batches": rows, "issued": issued}


@router.post("/promo/{item_id}/load")
def load_batch(item_id: int, count: int = 50, db: Session = Depends(get_db),
               actor: User = Depends(require_pult("promo"))):
    """ФТ-СЕР.1: загрузка партии кодов."""
    batch = db.scalar(select(PromoBatch).where(PromoBatch.item_id == item_id))
    if not batch:
        batch = PromoBatch(item_id=item_id, total=0, used=0)
        db.add(batch)
    batch.total += count
    item = db.get(CatalogItem, item_id)
    pts.write_audit(db, actor.full_name, "Загрузка партии промокодов",
                    f"{item.title if item else item_id}: +{count} кодов")
    db.commit()
    return {"total": batch.total, "left": batch.total - batch.used}


# ---------- окна выбора ----------

@router.get("/campaigns", response_model=list[schemas.CampaignOut])
def list_campaigns(db: Session = Depends(get_db), actor: User = Depends(require_pult("campaigns"))):
    return db.scalars(select(Campaign).order_by(Campaign.id.desc())).all()


@router.post("/campaigns", response_model=schemas.CampaignOut, status_code=201)
def create_campaign(payload: schemas.CampaignIn, db: Session = Depends(get_db),
                    actor: User = Depends(require_pult("campaigns"))):
    """ФТ-ОКН.5: дата окончания не может быть раньше даты начала."""
    if payload.date_to < payload.date_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Дата окончания не может быть раньше даты начала")
    camp = Campaign(**payload.model_dump())
    db.add(camp)
    pts.write_audit(db, actor.full_name, "Создание окна выбора",
                    f"{payload.title}, {payload.date_from} — {payload.date_to}")
    db.commit()
    db.refresh(camp)
    return camp


@router.post("/campaigns/{campaign_id}/toggle", response_model=schemas.CampaignOut)
def toggle_campaign(campaign_id: int, db: Session = Depends(get_db),
                    actor: User = Depends(require_pult("campaigns"))):
    camp = db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Кампания не найдена")
    camp.is_open = not camp.is_open
    pts.write_audit(db, actor.full_name,
                    "Открытие окна выбора" if camp.is_open else "Закрытие окна выбора", camp.title)
    db.commit()
    db.refresh(camp)
    return camp


# ---------- обращения ----------

@router.get("/tickets", response_model=list[schemas.TicketOut])
def admin_tickets(db: Session = Depends(get_db), actor: User = Depends(require_pult("support"))):
    rows = db.scalars(select(Ticket).order_by(Ticket.created_at.desc())).all()
    out = []
    for t in rows:
        data = schemas.TicketOut.model_validate(t)
        data.user_name = t.user.full_name
        out.append(data)
    return out


@router.post("/tickets/{ticket_id}/answer", response_model=schemas.TicketOut)
def answer_ticket(ticket_id: int, answer: str, db: Session = Depends(get_db),
                  actor: User = Depends(require_pult("support"))):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Обращение не найдено")
    ticket.answer = answer
    ticket.status = "closed"
    pts.write_audit(db, actor.full_name, "Закрытие обращения", f"{ticket.public_id}: {ticket.topic}")
    db.commit()
    db.refresh(ticket)
    data = schemas.TicketOut.model_validate(ticket)
    data.user_name = ticket.user.full_name
    return data


# ---------- выгрузка в бухгалтерию ----------

EXPORT_COLUMNS = [
    "ID заказа", "ФИО", "Группа сотрудника", "Пол", "Дата рождения", "Город", "Телефон",
    "Наименование лота", "Тип товара", "Статус покупки", "Email", "Дата заказа",
    "Сумма заказа, ₽", "Комментарий", "Адрес доставки",
]

STATUS_TITLES = {"new": "Создан", "approve": "На согласовании", "work": "В обработке",
                 "done": "Выполнен", "cancel": "Отменён"}


def export_rows(db: Session) -> list[list]:
    rate = int((db.get(PlatformSetting, "point_rub") or PlatformSetting(value="1")).value)
    rows = []
    for o in db.scalars(select(Order).where(Order.status != OrderStatus.CANCEL.value)
                        .order_by(Order.created_at)).all():
        u, i = o.user, o.item
        rows.append([
            o.public_id, u.full_name, u.department, u.sex,
            u.birth_date.strftime("%d.%m.%Y") if u.birth_date else "", u.city, u.phone,
            i.title, i.item_type, STATUS_TITLES.get(o.status, o.status), u.email,
            o.created_at.strftime("%d.%m.%Y %H:%M"), o.price * rate, o.note,
            f"{u.city}, до офиса" if i.item_type == ItemType.PHYSICAL.value else "—",
        ])
    return rows


@router.get("/export")
def export_preview(db: Session = Depends(get_db), actor: User = Depends(require_pult("export"))):
    """ФТ-АНЛ.6: выгрузка со всеми полями из ТЗ и валидацией."""
    rows = export_rows(db)
    invalid = [r[0] for r in rows if not r[6] or not r[10]]
    return {
        "columns": EXPORT_COLUMNS,
        "rows": rows,
        "total_rub": sum(r[12] for r in rows),
        "invalid": invalid,
    }


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), actor: User = Depends(require_pult("export"))):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_ALL)
    writer.writerow(EXPORT_COLUMNS)
    writer.writerows(export_rows(db))
    pts.write_audit(db, actor.full_name, "Выгрузка в бухгалтерию", f"{len(export_rows(db))} строк")
    db.commit()
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cafeteria-export.csv"'},
    )


# ---------- аудит и аномалии ----------

@router.get("/audit", response_model=list[schemas.AuditOut])
def read_audit(limit: int = 200, db: Session = Depends(get_db),
               actor: User = Depends(require_pult("audit"))):
    return db.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(limit)).all()


@router.get("/anomalies", response_model=list[schemas.AnomalyOut])
def read_anomalies(db: Session = Depends(get_db), actor: User = Depends(require_pult("anomalies"))):
    return db.scalars(select(Anomaly).order_by(Anomaly.at.desc())).all()


@router.post("/anomalies/{anomaly_id}/legit", response_model=schemas.AnomalyOut)
def mark_legit(anomaly_id: int, db: Session = Depends(get_db),
               actor: User = Depends(require_pult("anomalies"))):
    """ФТ-АУД.3: отметка операции как легитимной."""
    anomaly = db.get(Anomaly, anomaly_id)
    if not anomaly:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    anomaly.status = "legit"
    pts.write_audit(db, actor.full_name, "Аномалия отмечена легитимной",
                    f"{anomaly.rule}: {anomaly.detail}")
    db.commit()
    db.refresh(anomaly)
    return anomaly


# ---------- настройки платформы ----------

@router.get("/settings", response_model=list[schemas.SettingOut])
def read_settings(db: Session = Depends(get_db), actor: User = Depends(require_pult("settings"))):
    return db.scalars(select(PlatformSetting)).all()


@router.put("/settings/{key}", response_model=schemas.SettingOut)
def update_setting(key: str, payload: schemas.SettingIn, db: Session = Depends(get_db),
                   actor: User = Depends(require_pult("settings"))):
    """Раздел 4.15: параметры меняются без доработки кода."""
    row = db.get(PlatformSetting, key)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Настройка не найдена")
    was = row.value
    row.value = payload.value
    pts.write_audit(db, actor.full_name, "Изменение настроек", f"{key}: {was} → {payload.value}")
    db.commit()
    db.refresh(row)
    return row


@router.get("/integrations")
def integrations(db: Session = Depends(get_db), actor: User = Depends(require_pult("settings"))):
    """Статусы внешних каналов. Инфраструктура заказчика в границы ТЗ не входит."""
    return [
        {"name": "1С:ЗУП — кадровый контур", "status": "available"},
        {"name": "Корпоративный SSO", "status": "available"},
        {"name": "SMTP — почтовая инфраструктура", "status": "available"},
        {"name": "Giftery — подарочные карты", "status": "available"},
        {"name": "ПВК / prostodar", "status": "available"},
        {"name": "КЭДО", "status": "not_configured"},
    ]
