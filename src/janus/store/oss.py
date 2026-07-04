"""Alibaba Cloud OSS integration.

This module is Janus's audit and artifact archive, built on Alibaba Cloud Object
Storage Service via the official ``oss2`` SDK. Every action Janus performs is
archived here (``actions/``), and every codegen job stores its artifacts here
(``artifacts/``). Telegram approval cards link to presigned OSS URLs so the
maintainer can inspect full payloads from their phone.

Together with the ECS deployment (see ``deploy/``), this is the project's
Alibaba Cloud services integration for the Qwen Cloud Global AI Hackathon.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import oss2

from janus.settings import settings

logger = logging.getLogger(__name__)

DEV_STUB_DIR = Path(".oss-dev")


class OssArchive:
    def __init__(self) -> None:
        self._bucket: oss2.Bucket | None = None
        if settings.oss_access_key_id and settings.oss_bucket:
            auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
            self._bucket = oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket)
        elif settings.is_prod:
            raise RuntimeError("OSS credentials are required in prod")
        else:
            logger.warning("OSS credentials missing; using local dev stub at %s", DEV_STUB_DIR)

    async def put_action_detail(self, action_id: int, detail: dict) -> str:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"actions/{day}/{action_id}.json"
        await self._put(key, json.dumps(detail, indent=2, default=str).encode())
        return key

    async def put_artifact(self, job_id: str, filename: str, data: bytes) -> str:
        key = f"artifacts/{job_id}/{filename}"
        await self._put(key, data)
        return key

    async def presign(self, key: str, expires: int = 3600) -> str:
        if self._bucket is None:
            return f"file://{(DEV_STUB_DIR / key).resolve()}"
        return await asyncio.to_thread(self._bucket.sign_url, "GET", key, expires)

    async def _put(self, key: str, data: bytes) -> None:
        if self._bucket is None:
            path = DEV_STUB_DIR / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return
        await asyncio.to_thread(self._bucket.put_object, key, data)


@lru_cache(maxsize=1)
def archive() -> OssArchive:
    return OssArchive()


async def _selftest() -> None:
    logging.basicConfig(level=logging.INFO)
    key = await archive().put_action_detail(0, {"selftest": True, "at": str(datetime.now(UTC))})
    url = await archive().presign(key)
    print(f"put {key}\npresigned: {url}")


if __name__ == "__main__":
    asyncio.run(_selftest())
