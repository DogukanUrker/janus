from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import jwt

from janus.settings import settings

API = "https://api.github.com"


def app_jwt() -> str:
    key = Path(settings.github_private_key_path).read_text()
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 540, "iss": settings.github_app_id}
    return jwt.encode(payload, key, algorithm="RS256")


@dataclass
class _CachedToken:
    token: str
    expires_at: float


_tokens: dict[int, _CachedToken] = {}
_lock = asyncio.Lock()


async def installation_token(installation_id: int) -> str:
    cached = _tokens.get(installation_id)
    if cached and cached.expires_at > time.time() + 300:
        return cached.token
    async with _lock:
        cached = _tokens.get(installation_id)
        if cached and cached.expires_at > time.time() + 300:
            return cached.token
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt()}",
                    "Accept": "application/vnd.github+json",
                },
            )
        resp.raise_for_status()
        token = resp.json()["token"]
        _tokens[installation_id] = _CachedToken(token=token, expires_at=time.time() + 3300)
        return token
