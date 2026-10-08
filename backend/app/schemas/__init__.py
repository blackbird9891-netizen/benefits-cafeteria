"""Схемы запросов и ответов."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- авторизация ---

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class InviteRequest(BaseModel):
    email: EmailStr
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    position: str
    grade: str
    department: str
    role: str
    role_title: str = ""
    city: str
    hired_at: date | None = None
    vacation_left: int
    budget: int
    chief: str


class BalanceOut(BaseModel):
    burnable: int
    permanent: int
    available: int
    burned: int
    granted: int
    spent: int
    frozen: bool


class MeOut(BaseModel):
    user: UserOut
    balance: BalanceOut
    sections: list[str]
    pult: list[str]


# --- каталог ---

class SectionOut(ORMModel):
    id: int
    code: str
    title: str
    icon: str


class ItemOut(ORMModel):
    id: int
    section_id: int
    category: str
    title: str
    price: int
    item_type: str
    supplier: str
    description: str
    conditions: str
    icon: str
    stock: int | None = None
    seats: int | None = None
    low_at: int
    cap_amount: int | None = None
    limit_count: int | None = None
    limit_period: str | None = None
    needs_doc: bool
    has_slots: bool
    approvals: list | None = None
    files: list | None = None
    archived: bool
    # вычисляемые поля
    available_stock: int | None = None
    limit_reached: bool = False
    blocked_reason: str | None = None


class ItemIn(BaseModel):
    section_id: int
    category: str = ""
    title: str
    price: int = 0
    item_type: str = "gift"
    supplier: str = ""
    description: str = ""
    conditions: str = ""
    icon: str = "▣"
    stock: int | None = None
    seats: int | None = None
    low_at: int = 5
    cap_amount: int | None = None
    limit_count: int | None = None
    limit_period: str | None = None
    needs_doc: bool = False
    has_slots: bool = False
    approvals: list | None = None
    files: list | None = None


# --- баллы ---

class LotOut(ORMModel):
    id: int
    amount: int
    remaining: int
    burnable: bool
    granted_at: date
    burn_at: date | None
    reason: str
    granted_by: str


class GrantIn(BaseModel):
    user_id: int
    amount: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=255)
    burnable: bool = True


class SpendIn(BaseModel):
    user_id: int
    amount: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=255)


# --- заказы ---

class ApprovalOut(ORMModel):
    approver: str
    result: bool | None
    comment: str


class OrderOut(ORMModel):
    id: int
    public_id: str
    user_id: int
    item_id: int
    price: int
    status: str
    created_at: datetime
    code: str | None
    note: str
    options: dict | None
    item_title: str = ""
    item_type: str = ""
    user_name: str = ""
    approvals_chain: list[ApprovalOut] = []


class CartLine(BaseModel):
    item_id: int
    options: dict = {}


class CheckoutIn(BaseModel):
    lines: list[CartLine]


class CheckoutResult(BaseModel):
    orders: list[OrderOut]
    spent: int
    balance: BalanceOut


# --- кампании ---

class CampaignOut(ORMModel):
    id: int
    title: str
    date_from: date
    date_to: date
    is_open: bool
    window_open: bool = False
    mode: str = "restrict"


class CampaignIn(BaseModel):
    title: str
    date_from: date
    date_to: date
    is_open: bool = True


# --- ДМС ---

class FamilyMemberIn(BaseModel):
    full_name: str
    birth_date: date
    relation: str
    sex: str = ""


class FamilyMemberOut(ORMModel):
    id: int
    full_name: str
    birth_date: date
    relation: str
    sex: str
    price: int
    status: str


class DmsOut(ORMModel):
    base_program: str
    policy_to: date | None
    status: str
    refused: bool
    extensions: list | None


# --- поддержка и коммуникации ---

class TicketIn(BaseModel):
    topic: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=4000)
    attachment: str = Field(default="", max_length=255)


class TicketOut(ORMModel):
    id: int
    public_id: str
    topic: str
    body: str
    created_at: datetime
    status: str
    answer: str
    attachment: str
    user_name: str = ""


class NewsOut(ORMModel):
    id: int
    title: str
    body: str
    created_at: datetime
    pinned: bool
    comments: list = []


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class SurveyOut(ORMModel):
    id: int
    title: str
    question: str
    options: list
    votes: list
    is_open: bool
    my_vote: int | None = None


# --- переводы и благотворительность ---

class TransferIn(BaseModel):
    to_user_id: int
    amount: int = Field(gt=0)


class CharityIn(BaseModel):
    fund: str = Field(min_length=1, max_length=255)
    amount: int = Field(gt=0)


# --- аудит, аномалии, настройки ---

class AuditOut(ORMModel):
    id: int
    at: datetime
    actor: str
    action: str
    detail: str


class AnomalyOut(ORMModel):
    id: int
    at: datetime
    rule: str
    actor: str
    detail: str
    status: str


class SettingOut(ORMModel):
    key: str
    value: str
    value_type: str
    title: str


class SettingIn(BaseModel):
    value: str = Field(max_length=255)
