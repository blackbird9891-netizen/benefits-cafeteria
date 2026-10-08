from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
# autoflush=True обязателен: балльная механика начисляет и списывает в одной
# транзакции, и без автоматического сброса запрос не видит несохранённые лоты —
# списание молча отвечает «недостаточно средств».
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=True)


class Base(DeclarativeBase):
    pass


def get_db():
    """Сессия на запрос. При исключении откатывается, чтобы частичные
    изменения не утекли в следующий запрос через то же соединение."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
