from typing import AsyncGenerator

import httpx
import pytest_asyncio

from main import app


@pytest_asyncio.fixture(scope="session")
async def fast_api_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    Получить клиент FastAPI
    """

    async with httpx.AsyncClient(
        app=app,
        base_url="http://localhost:7777",
        follow_redirects=True
    ) as client:
        try:
            yield client
        finally:
            await client.aclose()
