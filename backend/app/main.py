"""Точка входа приложения «Кафетерий льгот»."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, pult, shop
from app.config import settings
from app.database import Base, engine

DESCRIPTION = """
Многофункциональная система управления материальными и нематериальными
поощрениями сотрудников.

**Разделы API**

* `auth` — вход по логину, через SSO или по коду приглашения
* `shop` — витрина сотрудника: каталог, корзина, заказы, ДМС, баллы, поддержка
* `pult` — административная панель: каталог, бюджеты, начисления, согласования,
  выгрузка в бухгалтерию, журнал аудита, настройки платформы

Права проверяются на сервере: роль определяет и доступные разделы витрины,
и доступные экраны Пульта.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="Кафетерий льгот",
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(shop.router, prefix="/api", tags=["shop"])
app.include_router(pult.router, prefix="/api/pult", tags=["pult"])


@app.get("/api/health", tags=["service"])
def health():
    return {"status": "ok"}
