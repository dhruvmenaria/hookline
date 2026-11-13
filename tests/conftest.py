import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hookline.config import settings
from hookline.db import Base, get_session
from hookline.main import app


@pytest_asyncio.fixture
async def client(tmp_path):
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    old_secret = settings.webhook_secret
    settings.webhook_secret = "test-webhook-secret"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
    settings.webhook_secret = old_secret
    await test_engine.dispose()


def signed_headers(body: bytes, key: str, secret: str = "test-webhook-secret") -> dict[str, str]:
    import hashlib
    import hmac

    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hookline-Signature": signature, "Idempotency-Key": key, "Content-Type": "application/json"}
