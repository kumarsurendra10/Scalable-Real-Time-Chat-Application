import asyncio

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.core.redis_client as redis_client_module
from app.db.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_engine, monkeypatch):
    test_session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # the real lifespan calls init_models() against the production
    # Postgres URL; tests use SQLite via dependency override instead,
    # so skip that startup step entirely.
    async def _noop_init_models():
        return None

    monkeypatch.setattr("app.main.init_models", _noop_init_models)

    # the WebSocket route module talks to the DB directly via
    # AsyncSessionLocal (it isn't part of FastAPI's Depends() graph),
    # so redirect that name too, otherwise it would hit the real
    # Postgres URL during tests.
    monkeypatch.setattr("app.ws.routes.AsyncSessionLocal", test_session_factory)

    # swap real redis for an in-memory fake so tests don't need a server
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client_module, "_redis_pool", fake_redis)
    monkeypatch.setattr(redis_client_module, "get_redis", lambda: fake_redis)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
