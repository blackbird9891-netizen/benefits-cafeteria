"""Модели данных системы «Кафетерий льгот».

Структура повторяет предметную область ТЗ: сотрудники и роли, балльные лоты
со сроками сгорания, каталог с разделами, заказы с маршрутом согласования,
кампании (окна выбора), журналы аудита и аномалий, обращения в поддержку.
"""

from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(str, Enum):
    """Роли из раздела 3 ТЗ."""

    EMPLOYEE = "employee"
    DECREE = "decree"
    VIP = "vip"
    HR = "hr"
    ADMIN = "admin"
    EXCLUDED = "excluded"


class OrderStatus(str, Enum):
    NEW = "new"
    APPROVE = "approve"
    WORK = "work"
    DONE = "done"
    CANCEL = "cancel"


class ItemType(str, Enum):
    """Типы позиций из ФТ-КАТ.5 — ФТ-КАТ.8."""

    GIFT = "gift"
    CARD = "card"
    PHYSICAL = "phys"
    DOCUMENT = "doc"
    DMS = "dms"
    DMS_FAMILY = "dms-family"
    SLOT = "slot"
    STAY = "stay"
    EDUCATION = "edu"
    VACATION = "vac"
    FLEX = "flex"


# Периоды лимита. Один источник для схемы ввода и для расчёта в витрине:
# разойдутся — и неизвестный период молча отменит ограничение.
LIMIT_PERIODS: dict[str, int] = {
    "день": 1, "неделя": 7, "месяц": 30, "квартал": 92, "год": 365,
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[str] = mapped_column(String(255), default="")
    grade: Mapped[str] = mapped_column(String(16), default="")
    department: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(32), default=Role.EMPLOYEE.value)
    hired_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    city: Mapped[str] = mapped_column(String(128), default="")
    sex: Mapped[str] = mapped_column(String(8), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    chief: Mapped[str] = mapped_column(String(255), default="")
    vacation_left: Mapped[int] = mapped_column(Integer, default=0)
    budget: Mapped[int] = mapped_column(Integer, default=0)
    points_frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    lots: Mapped[list["PointLot"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    orders: Mapped[list["Order"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class PointLot(Base):
    """Балльный лот. Сгораемые и несгораемые баллы — ФТ-БАЛ.1–ФТ-БАЛ.4."""

    __tablename__ = "point_lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    remaining: Mapped[int] = mapped_column(Integer)
    burnable: Mapped[bool] = mapped_column(Boolean, default=True)
    granted_at: Mapped[date] = mapped_column(Date, default=date.today)
    burn_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str] = mapped_column(String(255))
    granted_by: Mapped[str] = mapped_column(String(255), default="Система")

    user: Mapped["User"] = relationship(back_populates="lots")


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    icon: Mapped[str] = mapped_column(String(8), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    items: Mapped[list["CatalogItem"]] = relationship(back_populates="section")


class CatalogItem(Base):
    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), index=True)
    category: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(255))
    price: Mapped[int] = mapped_column(Integer, default=0)
    item_type: Mapped[str] = mapped_column(String(32), default=ItemType.GIFT.value)
    supplier: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(8), default="")

    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    low_at: Mapped[int] = mapped_column(Integer, default=5)
    seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cap_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)

    limit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    limit_period: Mapped[str | None] = mapped_column(String(32), nullable=True)

    needs_doc: Mapped[bool] = mapped_column(Boolean, default=False)
    has_slots: Mapped[bool] = mapped_column(Boolean, default=False)
    approvals: Mapped[list | None] = mapped_column(JSON, nullable=True)
    files: Mapped[list | None] = mapped_column(JSON, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    section: Mapped["Section"] = relationship(back_populates="items")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), index=True)
    price: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.NEW.value, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    user: Mapped["User"] = relationship(back_populates="orders")
    item: Mapped["CatalogItem"] = relationship()
    approvals_chain: Mapped[list["OrderApproval"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderApproval(Base):
    """Маршрут согласования — ФТ-ЗАК.3, ФТ-ЗАК.4."""

    __tablename__ = "order_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    approver: Mapped[str] = mapped_column(String(128))
    result: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    order: Mapped["Order"] = relationship(back_populates="approvals_chain")


class Campaign(Base):
    """Окно выбора — раздел 4.6 ТЗ."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    segments: Mapped[list | None] = mapped_column(JSON, nullable=True)


class PlatformSetting(Base):
    """Настройки без доработки кода — раздел 4.15 ТЗ."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
    value_type: Mapped[str] = mapped_column(String(16), default="int")
    title: Mapped[str] = mapped_column(String(255), default="")


class AuditLog(Base):
    """Журнал аудита — ФТ-АУД.1."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(128), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class Anomaly(Base):
    """Журнал аномалий — ФТ-АУД.2, ФТ-АУД.3."""

    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    rule: Mapped[str] = mapped_column(String(255))
    actor: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="open")


class Ticket(Base):
    """Обращения в поддержку — раздел 4.13 ТЗ."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), default="open")
    answer: Mapped[str] = mapped_column(Text, default="")
    attachment: Mapped[str] = mapped_column(String(255), default="")

    user: Mapped["User"] = relationship()


class PromoBatch(Base):
    """Партии промокодов — раздел 4.8 ТЗ."""

    __tablename__ = "promo_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    item: Mapped["CatalogItem"] = relationship()


class DmsPolicy(Base):
    """Полис ДМС сотрудника — раздел 4.3 ТЗ."""

    __tablename__ = "dms_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    base_program: Mapped[str] = mapped_column(String(255), default="")
    policy_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="Действует")
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    extensions: Mapped[list | None] = mapped_column(JSON, nullable=True)

    user: Mapped["User"] = relationship()


class FamilyMember(Base):
    """Члены семьи в ДМС — ФТ-ДМС.4, ФТ-ДМС.5."""

    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    birth_date: Mapped[date] = mapped_column(Date)
    relation: Mapped[str] = mapped_column(String(64))
    sex: Mapped[str] = mapped_column(String(8), default="")
    price: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(64), default="На оформлении")

    user: Mapped["User"] = relationship()


class NewsPost(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)


class NewsComment(Base):
    __tablename__ = "news_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("news.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    approved: Mapped[bool] = mapped_column(Boolean, default=True)


class Survey(Base):
    __tablename__ = "surveys"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    question: Mapped[str] = mapped_column(String(255))
    options: Mapped[list] = mapped_column(JSON)
    votes: Mapped[list] = mapped_column(JSON)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)


class SurveyVote(Base):
    __tablename__ = "survey_votes"

    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    choice: Mapped[int] = mapped_column(Integer)


class Transfer(Base):
    """Переводы баллов между сотрудниками — ФТ-СОЦ.1."""

    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    fee: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CharityDonation(Base):
    """Благотворительность с софинансированием — ФТ-СОЦ.4, ФТ-СОЦ.5."""

    __tablename__ = "charity_donations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    fund: Mapped[str] = mapped_column(String(255))
    amount: Mapped[int] = mapped_column(Integer)
    matched: Mapped[int] = mapped_column(Integer)
    certificate: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
