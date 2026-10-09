"""Витрина сотрудника: профиль, каталог, корзина, заказы, ДМС, баллы."""

import random
import string
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas
from app.api.deps import (
    ROLE_MATRIX,
    denied_item_types,
    get_active_user,
    visible_section_codes,
)
from app.core import points as pts
from app.database import get_db
from app.models import (
    Anomaly,
    Campaign,
    CatalogItem,
    CharityDonation,
    DmsPolicy,
    FamilyMember,
    ItemType,
    NewsComment,
    NewsPost,
    Order,
    OrderApproval,
    OrderStatus,
    PointLot,
    PlatformSetting,
    PromoBatch,
    Section,
    Survey,
    SurveyVote,
    Ticket,
    Transfer,
    User,
)

router = APIRouter()

AGE_MIN, AGE_MAX = 1, 65


# ---------- вспомогательное ----------

def setting(db: Session, key: str, default: int = 0) -> int:
    row = db.get(PlatformSetting, key)
    return int(row.value) if row else default


def current_campaign(db: Session) -> Campaign | None:
    return db.scalar(select(Campaign).order_by(Campaign.id.desc()))


def window_is_open(db: Session) -> bool:
    camp = current_campaign(db)
    if not camp:
        return True
    today = date.today()
    return camp.is_open and camp.date_from <= today <= camp.date_to


def window_block(db: Session) -> str | None:
    """Возвращает текст блокировки, если окно закрыто и режим ограничивающий."""
    if window_is_open(db):
        return None
    row = db.get(PlatformSetting, "window_mode")
    mode = row.value if row else "restrict"
    if mode == "inform":
        return None
    return "Окно выбора закрыто. Оформление и отмена заблокированы, требуется заявка в HR на исключение."


def bought_count(db: Session, user_id: int, item_id: int, period: str | None) -> int:
    from datetime import timedelta

    deltas = {
        "день": timedelta(days=1),
        "неделя": timedelta(days=7),
        "месяц": timedelta(days=30),
        "квартал": timedelta(days=92),
        "год": timedelta(days=365),
    }
    since = datetime.now() - deltas.get(period or "", timedelta(days=36500))
    rows = db.scalars(
        select(Order).where(
            Order.user_id == user_id,
            Order.item_id == item_id,
            Order.status != OrderStatus.CANCEL.value,
            Order.created_at >= since,
        )
    ).all()
    return len(rows)


def available_stock(db: Session, item: CatalogItem) -> int | None:
    if item.item_type == ItemType.GIFT.value:
        batch = db.scalar(select(PromoBatch).where(PromoBatch.item_id == item.id))
        if batch:
            return batch.total - batch.used
    if item.stock is not None:
        return item.stock
    if item.seats is not None:
        return item.seats
    return None


def family_price(birth: date) -> int:
    today = date.today()
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    if age < AGE_MIN or age > AGE_MAX:
        return 0
    if age < 18:
        return 5200
    if age < 45:
        return 6800
    if age < 60:
        return 8900
    return 11500


def item_out(db: Session, item: CatalogItem, user: User) -> schemas.ItemOut:
    data = schemas.ItemOut.model_validate(item)
    data.available_stock = available_stock(db, item)
    if item.limit_count:
        n = bought_count(db, user.id, item.id, item.limit_period)
        data.limit_reached = n >= item.limit_count
        if data.limit_reached:
            data.blocked_reason = f"Лимит исчерпан: не более {item.limit_count} за {item.limit_period}"
    if data.blocked_reason is None and data.available_stock is not None and data.available_stock <= 0:
        data.blocked_reason = "Позиция временно отсутствует"
    return data


def order_out(order: Order) -> schemas.OrderOut:
    data = schemas.OrderOut.model_validate(order)
    data.item_title = order.item.title if order.item else ""
    data.item_type = order.item.item_type if order.item else ""
    data.user_name = order.user.full_name if order.user else ""
    return data


# Префиксы промокодов должны быть латиницей: код уходит партнёру и
# вводится в чужих системах, кириллица там не принимается.
TRANSLIT = {
    "а": "A", "б": "B", "в": "V", "г": "G", "д": "D", "е": "E", "ё": "E",
    "ж": "ZH", "з": "Z", "и": "I", "й": "Y", "к": "K", "л": "L", "м": "M",
    "н": "N", "о": "O", "п": "P", "р": "R", "с": "S", "т": "T", "у": "U",
    "ф": "F", "х": "H", "ц": "C", "ч": "CH", "ш": "SH", "щ": "SCH",
    "ы": "Y", "э": "E", "ю": "YU", "я": "YA", "ъ": "", "ь": "",
}


def gen_code(item: CatalogItem) -> str:
    latin = "".join(TRANSLIT.get(ch, ch if ch.isascii() and ch.isalnum() else "")
                    for ch in item.title.lower())
    prefix = (latin[:3] or "GFT").upper()
    chunk = lambda: "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}-{chunk()}-{chunk()}"


def next_public_id(db: Session, prefix: str, model) -> str:
    """Последовательный номер. Случайная часть убрана: при оформлении
    нескольких позиций подряд она давала коллизии на уникальном поле."""
    last = db.scalar(select(func.max(model.id))) or 0
    return f"{prefix}-{100000 + last + 1}"


# ---------- профиль ----------

@router.get("/me", response_model=schemas.MeOut)
def read_me(db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    all_codes = [s.code for s in db.scalars(select(Section)).all()]
    rules = ROLE_MATRIX.get(user.role, {})
    out_user = schemas.UserOut.model_validate(user)
    out_user.role_title = rules.get("title", user.role)
    return schemas.MeOut(
        user=out_user,
        balance=schemas.BalanceOut(**pts.balance(db, user).__dict__),
        sections=visible_section_codes(user, all_codes),
        pult=rules.get("pult", []),
    )


@router.get("/me/points", response_model=list[schemas.LotOut])
def my_points(db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    lots = db.scalars(
        select(PointLot).where(PointLot.user_id == user.id).order_by(PointLot.granted_at.desc())
    ).all()
    return lots


# ---------- каталог ----------

@router.get("/sections", response_model=list[schemas.SectionOut])
def list_sections(db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    sections = db.scalars(select(Section).order_by(Section.sort_order)).all()
    allowed = visible_section_codes(user, [s.code for s in sections])
    return [s for s in sections if s.code in allowed]


@router.get("/catalog", response_model=list[schemas.ItemOut])
def list_catalog(
    section: str | None = None,
    q: str | None = None,
    item_type: str | None = None,
    max_price: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    sections = db.scalars(select(Section)).all()
    allowed_codes = visible_section_codes(user, [s.code for s in sections])
    allowed_ids = [s.id for s in sections if s.code in allowed_codes]

    stmt = select(CatalogItem).where(
        CatalogItem.section_id.in_(allowed_ids), CatalogItem.archived.is_(False)
    )
    if section:
        target = next((s.id for s in sections if s.code == section), None)
        stmt = stmt.where(CatalogItem.section_id == target)
    if item_type:
        stmt = stmt.where(CatalogItem.item_type == item_type)
    if max_price:
        stmt = stmt.where(CatalogItem.price <= max_price)

    denied = denied_item_types(user)
    if denied:
        stmt = stmt.where(CatalogItem.item_type.notin_(denied))

    items = db.scalars(stmt).all()
    if q:
        needle = q.lower()
        items = [i for i in items
                 if needle in i.title.lower() or needle in i.description.lower() or needle in i.category.lower()]

    return [item_out(db, i, user) for i in items]


@router.get("/catalog/{item_id}", response_model=schemas.ItemOut)
def read_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    item = db.get(CatalogItem, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Позиция не найдена")
    if item.item_type in denied_item_types(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Позиция недоступна для роли «{ROLE_MATRIX.get(user.role, {}).get('title', user.role)}»")
    return item_out(db, item, user)


# ---------- оформление заказа ----------

@router.post("/checkout", response_model=schemas.CheckoutResult)
def checkout(
    payload: schemas.CheckoutIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """Оформление корзины. Все проверки выполняются на сервере."""
    block = window_block(db)
    if block:
        raise HTTPException(status.HTTP_409_CONFLICT, block)
    if not payload.lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Корзина пуста")

    prepared: list[tuple[CatalogItem, dict, int]] = []
    total = 0

    for line in payload.lines:
        item = db.get(CatalogItem, line.item_id)
        if not item or item.archived:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Позиция {line.item_id} недоступна")
        if item.item_type in denied_item_types(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"«{item.title}»: позиция недоступна для вашей роли")

        opts = line.options or {}
        price = item.price

        if item.item_type == ItemType.DMS_FAMILY.value:
            if not all(opts.get(k) for k in ("fio", "bd", "rel")):
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "Заполните ФИО, дату рождения и степень родства застрахованного")
            price = family_price(date.fromisoformat(opts["bd"]))
            if price == 0:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"Возраст застрахованного вне условий программы ({AGE_MIN}–{AGE_MAX})")
        elif item.item_type == ItemType.VACATION.value:
            days = int(opts.get("days") or 1)
            if user.vacation_left > 0:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"Доступно только при отгулянном основном отпуске. Неотгулянных дней: {user.vacation_left}")
            price = item.price * days
        elif item.has_slots and not opts.get("slot"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"«{item.title}»: выберите дату и время")
        elif item.item_type == ItemType.STAY.value and not opts.get("from"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"«{item.title}»: укажите дату заезда")

        if item.needs_doc and not opts.get("doc"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"«{item.title}»: прикрепите подтверждающий документ")

        if item.cap_amount and price > item.cap_amount:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"«{item.title}»: превышен предел суммы {item.cap_amount}")

        if item.limit_count:
            n = bought_count(db, user.id, item.id, item.limit_period)
            if n >= item.limit_count:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"«{item.title}»: лимит не более {item.limit_count} за {item.limit_period}")

        stock = available_stock(db, item)
        if stock is not None and stock <= 0:
            raise HTTPException(status.HTTP_409_CONFLICT, f"«{item.title}»: нет в наличии")

        prepared.append((item, opts, price))
        total += price

    bal = pts.balance(db, user)
    if bal.frozen:
        raise HTTPException(status.HTTP_409_CONFLICT, "Баллы заморожены администратором")
    if total > bal.available:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Превышение бюджета на {total - bal.available} баллов. Доступно {bal.available}",
        )

    created: list[Order] = []
    for item, opts, price in prepared:
        needs_approval = bool(item.approvals)
        order = Order(
            public_id=next_public_id(db, "ORD", Order),
            user_id=user.id,
            item_id=item.id,
            price=price,
            status=OrderStatus.APPROVE.value if needs_approval
            else (OrderStatus.DONE.value if item.item_type == ItemType.GIFT.value else OrderStatus.WORK.value),
            options=opts,
        )

        if item.item_type == ItemType.GIFT.value:
            batch = db.scalar(select(PromoBatch).where(PromoBatch.item_id == item.id))
            if batch:
                batch.used += 1
                if batch.total - batch.used <= item.low_at:
                    db.add(Anomaly(
                        rule="Остаток промокодов ниже порога",
                        actor="Система",
                        detail=f"{item.title}: осталось {batch.total - batch.used}",
                    ))
            order.code = gen_code(item)

        if item.stock is not None:
            item.stock = max(0, item.stock - 1)
        if item.seats is not None:
            item.seats = max(0, item.seats - 1)

        if item.item_type == ItemType.DMS_FAMILY.value:
            db.add(FamilyMember(
                user_id=user.id,
                full_name=opts["fio"],
                birth_date=date.fromisoformat(opts["bd"]),
                relation=opts["rel"],
                sex=opts.get("sex", ""),
                price=price,
            ))
        if item.item_type == ItemType.DMS.value:
            policy = db.scalar(select(DmsPolicy).where(DmsPolicy.user_id == user.id))
            if policy:
                ext = list(policy.extensions or [])
                if item.id not in ext:
                    ext.append(item.id)
                policy.extensions = ext

        db.add(order)
        db.flush()

        for idx, approver in enumerate(item.approvals or []):
            db.add(OrderApproval(order_id=order.id, approver=approver, sort_order=idx))

        if price > 0:
            pts.spend(db, user, price, f"Заказ {order.public_id}")

        created.append(order)

    db.commit()
    for o in created:
        db.refresh(o)

    return schemas.CheckoutResult(
        orders=[order_out(o) for o in created],
        spent=total,
        balance=schemas.BalanceOut(**pts.balance(db, user).__dict__),
    )


@router.get("/orders", response_model=list[schemas.OrderOut])
def my_orders(db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    orders = db.scalars(
        select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc())
    ).all()
    return [order_out(o) for o in orders]


@router.post("/orders/{order_id}/cancel", response_model=schemas.OrderOut)
def cancel_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    order = db.get(Order, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Заказ не найден")
    # Порядок важен: для промокода причина отказа конкретнее, чем «не тот статус».
    if order.item.item_type == ItemType.GIFT.value:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Промокод выдан и в ротацию не возвращается, отмена невозможна")
    if order.status not in (OrderStatus.NEW.value, OrderStatus.APPROVE.value, OrderStatus.WORK.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "Заказ в этом статусе отмене не подлежит")

    block = window_block(db)
    if block:
        raise HTTPException(status.HTTP_409_CONFLICT, block)

    order.status = OrderStatus.CANCEL.value
    if order.price > 0:
        pts.refund(db, user, order.price, f"отмена заказа {order.public_id}")
    if order.item.stock is not None:
        order.item.stock += 1
    if order.item.seats is not None:
        order.item.seats += 1

    pts.write_audit(db, user.full_name, "Отмена заказа",
                    f"{order.public_id} ({order.item.title}), возврат {order.price}")
    db.commit()
    db.refresh(order)
    return order_out(order)


# ---------- ДМС ----------

@router.get("/dms", response_model=schemas.DmsOut)
def read_dms(db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    policy = db.scalar(select(DmsPolicy).where(DmsPolicy.user_id == user.id))
    if not policy:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Полис не найден")
    return policy


@router.post("/dms/refuse", response_model=schemas.DmsOut)
def refuse_dms(value: bool = True, db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    """ФТ-ДМС.8: при отказе неиспользованные баллы остаются у сотрудника."""
    policy = db.scalar(select(DmsPolicy).where(DmsPolicy.user_id == user.id))
    if not policy:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Полис не найден")
    policy.refused = value
    pts.write_audit(db, user.full_name,
                    "Отказ от базового ДМС" if value else "Возврат базового ДМС", "")
    db.commit()
    db.refresh(policy)
    return policy


@router.get("/dms/family", response_model=list[schemas.FamilyMemberOut])
def list_family(db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    return db.scalars(select(FamilyMember).where(FamilyMember.user_id == user.id)).all()


# ---------- переводы и благотворительность ----------

@router.post("/transfer")
def transfer_points(
    payload: schemas.TransferIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    fee_pct = setting(db, "transfer_fee", 25)
    minimum = setting(db, "transfer_min", 500)

    if payload.amount < minimum:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Минимальная сумма перевода {minimum} баллов")
    target = db.get(User, payload.to_user_id)
    if not target or target.id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Получатель не найден")

    fee = round(payload.amount * fee_pct / 100)
    if not pts.spend(db, user, payload.amount, f"Перевод сотруднику {target.full_name}"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Недостаточно баллов")

    pts.grant(db, target, payload.amount - fee, f"Перевод от {user.full_name}")
    db.add(Transfer(from_user_id=user.id, to_user_id=target.id, amount=payload.amount, fee=fee))
    pts.write_audit(db, user.full_name, "Перевод баллов",
                    f"{target.full_name}: {payload.amount - fee} (комиссия {fee})")
    db.commit()
    return {"sent": payload.amount, "fee": fee, "received": payload.amount - fee}


@router.post("/charity")
def donate(
    payload: schemas.CharityIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    multiplier = setting(db, "charity_match", 2)
    minimum = setting(db, "transfer_min", 500)
    if payload.amount < minimum:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Минимальная сумма {minimum} баллов")
    if not pts.spend(db, user, payload.amount, "Благотворительность"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Недостаточно баллов")

    cert = "CRT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    db.add(CharityDonation(
        user_id=user.id, fund=payload.fund, amount=payload.amount,
        matched=payload.amount * multiplier, certificate=cert,
    ))
    pts.write_audit(db, user.full_name, "Благотворительный донат",
                    f"{payload.fund}: {payload.amount}, софинансирование ×{multiplier}")
    db.commit()
    return {"certificate": cert, "donated": payload.amount, "fund_receives": payload.amount * multiplier}


# ---------- поддержка, новости, опросы ----------

@router.get("/tickets", response_model=list[schemas.TicketOut])
def my_tickets(db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    rows = db.scalars(
        select(Ticket).where(Ticket.user_id == user.id).order_by(Ticket.created_at.desc())
    ).all()
    return [schemas.TicketOut.model_validate(t) for t in rows]


@router.post("/tickets", response_model=schemas.TicketOut, status_code=201)
def create_ticket(
    payload: schemas.TicketIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    ticket = Ticket(
        public_id=next_public_id(db, "SUP", Ticket),
        user_id=user.id,
        topic=payload.topic,
        body=payload.body,
        attachment=payload.attachment,
    )
    db.add(ticket)
    pts.write_audit(db, user.full_name, "Создано обращение", f"{ticket.public_id}: {payload.topic}")
    db.commit()
    db.refresh(ticket)
    return schemas.TicketOut.model_validate(ticket)


@router.get("/news", response_model=list[schemas.NewsOut])
def list_news(db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    posts = db.scalars(select(NewsPost).order_by(NewsPost.pinned.desc(), NewsPost.created_at.desc())).all()
    result = []
    for p in posts:
        data = schemas.NewsOut.model_validate(p)
        comments = db.scalars(
            select(NewsComment).where(NewsComment.post_id == p.id, NewsComment.approved.is_(True))
        ).all()
        data.comments = [{"author": c.author, "body": c.body} for c in comments]
        result.append(data)
    return result


@router.post("/news/{post_id}/comment", status_code=201)
def add_comment(
    post_id: int,
    payload: schemas.CommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    if not db.get(NewsPost, post_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Публикация не найдена")
    db.add(NewsComment(post_id=post_id, author=user.full_name, body=payload.body, approved=False))
    db.commit()
    return {"status": "на модерации"}


@router.get("/surveys", response_model=list[schemas.SurveyOut])
def list_surveys(db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    rows = db.scalars(select(Survey)).all()
    result = []
    for s in rows:
        data = schemas.SurveyOut.model_validate(s)
        vote = db.scalar(select(SurveyVote).where(
            SurveyVote.survey_id == s.id, SurveyVote.user_id == user.id))
        data.my_vote = vote.choice if vote else None
        result.append(data)
    return result


@router.post("/surveys/{survey_id}/vote")
def vote(survey_id: int, choice: int, db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    survey = db.get(Survey, survey_id)
    if not survey or not survey.is_open:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Опрос недоступен")
    if db.scalar(select(SurveyVote).where(SurveyVote.survey_id == survey_id, SurveyVote.user_id == user.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Вы уже голосовали")
    if not 0 <= choice < len(survey.options):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Неверный вариант")

    votes = list(survey.votes)
    votes[choice] += 1
    survey.votes = votes
    db.add(SurveyVote(survey_id=survey_id, user_id=user.id, choice=choice))
    db.commit()
    return {"ok": True}


# ---------- кампания ----------

@router.get("/campaign", response_model=schemas.CampaignOut)
def read_campaign(db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    camp = current_campaign(db)
    if not camp:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Кампания не настроена")
    data = schemas.CampaignOut.model_validate(camp)
    data.window_open = window_is_open(db)
    row = db.get(PlatformSetting, "window_mode")
    data.mode = row.value if row else "restrict"
    return data


@router.get("/colleagues", response_model=list[schemas.UserOut])
def list_colleagues(db: Session = Depends(get_db), user: User = Depends(get_active_user)):
    """Список коллег для переводов баллов."""
    rows = db.scalars(select(User).where(User.id != user.id, User.is_active.is_(True))).all()
    out = []
    for u in rows:
        if u.role == "excluded":
            continue
        data = schemas.UserOut.model_validate(u)
        data.role_title = ROLE_MATRIX.get(u.role, {}).get("title", u.role)
        out.append(data)
    return out
