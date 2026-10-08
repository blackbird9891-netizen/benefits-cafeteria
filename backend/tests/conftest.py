"""Общие фикстуры.

Каждый тест получает чистую базу в памяти и клиент с подменённой сессией.
Реальная база не используется: тесты не зависят от порядка запуска и
не оставляют следов.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def client(db_session):
    def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def seeded(db_session):
    """База с демонстрационными данными."""
    from app import seed as seed_module

    original = seed_module.SessionLocal
    seed_module.SessionLocal = lambda: db_session
    try:
        seed_module.run_seed(force=True)
    finally:
        seed_module.SessionLocal = original
    return db_session


@pytest.fixture
def api(client, seeded):
    """Клиент с наполненной базой и помощником для входа."""

    class Api:
        def __init__(self, c):
            self.c = c
            self.token = None

        def login(self, email: str, password: str):
            r = self.c.post("/api/auth/login-json", json={"email": email, "password": password})
            assert r.status_code == 200, r.text
            self.token = r.json()["access_token"]
            return self

        def as_employee(self):
            return self.login("a.drozdiuk@corp.example", "demo1234")

        def as_decree(self):
            return self.login("e.nazarova@corp.example", "demo1234")

        def as_vip(self):
            return self.login("v.orlov@corp.example", "demo1234")

        def as_hr(self):
            return self.login("i.sokolova@corp.example", "hr1234")

        def as_admin(self):
            return self.login("s.belov@corp.example", "admin1234")

        def as_excluded(self):
            return self.login("p.gavrilov@corp.example", "demo1234")

        @property
        def headers(self):
            return {"Authorization": f"Bearer {self.token}"} if self.token else {}

        def get(self, path, **kw):
            return self.c.get(path, headers=self.headers, **kw)

        def post(self, path, **kw):
            return self.c.post(path, headers=self.headers, **kw)

        def put(self, path, **kw):
            return self.c.put(path, headers=self.headers, **kw)

        def delete(self, path, **kw):
            return self.c.delete(path, headers=self.headers, **kw)

    return Api(client)
