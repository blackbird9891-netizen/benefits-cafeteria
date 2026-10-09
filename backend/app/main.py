"""Точка входа приложения «Кафетерий льгот»."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import DataError, IntegrityError

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

# Спецификация запрещает сочетание подстановочного origin с учётными данными:
# браузер отвергнет такой ответ. Токен передаётся заголовком, cookie не используются.
_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials="*" not in _origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ограничения СУБД не должны долетать до клиента пятисотой ошибкой.
# Схемы ввода проверяют длины и диапазоны, но уникальные индексы и
# внешние ключи остаются за базой: SQLite часть из них пропускает молча,
# PostgreSQL отклоняет. Обработчик переводит такие отказы в 400 и не
# показывает наружу текст запроса — в нём могут быть чужие данные.
@app.exception_handler(IntegrityError)
@app.exception_handler(DataError)
async def db_constraint_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=400,
        content={"detail": "Данные не прошли проверку базы: "
                           "возможно, значение слишком длинное или уже занято."},
    )


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(shop.router, prefix="/api", tags=["shop"])
app.include_router(pult.router, prefix="/api/pult", tags=["pult"])


@app.get("/api/health", tags=["service"])
def health():
    return {"status": "ok"}


# Раздача клиентской части тем же сервисом.
# В контуре с docker-compose фронт отдаёт nginx, здесь — запасной путь
# для одиночного развёртывания (один контейнер вместо трёх).
# В контейнере код лежит в /app/app, клиентская часть в /app/frontend.
# При локальном запуске — backend/app и frontend рядом с backend.
_ROOT = Path(__file__).resolve()
FRONTEND = next(
    (p for p in (_ROOT.parents[1] / "frontend" / "index.html",
                 _ROOT.parents[2] / "frontend" / "index.html")
     if p.exists()),
    None,
)


@app.get("/", include_in_schema=False)
def index():
    if FRONTEND:
        return FileResponse(FRONTEND, media_type="text/html; charset=utf-8")
    return {"detail": "Клиентская часть не найдена. API доступен по /api/docs"}
