import pytest
from fastapi import HTTPException

from app.auth import require_api_key
from app.config import Settings


def _settings() -> Settings:
    return Settings(ingestion_valid_api_keys="key-one,key-two")


@pytest.mark.asyncio
async def test_accepts_valid_key() -> None:
    result = await require_api_key(x_ingestion_key="key-one", settings=_settings())
    assert result == "key-one"


@pytest.mark.asyncio
async def test_rejects_missing_key() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_api_key(x_ingestion_key=None, settings=_settings())
    assert exc_info.value.status_code == 401
    assert "Missing" in exc_info.value.detail


@pytest.mark.asyncio
async def test_rejects_invalid_key() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_api_key(x_ingestion_key="not-a-real-key", settings=_settings())
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid API key"


@pytest.mark.asyncio
async def test_key_list_parses_and_trims_whitespace() -> None:
    settings = Settings(ingestion_valid_api_keys=" key-one , key-two ,")
    assert settings.valid_api_keys == {"key-one", "key-two"}
    result = await require_api_key(x_ingestion_key="key-two", settings=settings)
    assert result == "key-two"
