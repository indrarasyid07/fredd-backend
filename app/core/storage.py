"""Private file storage for chat media (roadmap 3.8; the final setup and signed-URL serving come
with roadmap 5.1).

`get_storage()` returns an S3-compatible bucket when `STORAGE_ENABLED=true` (MinIO, R2, S3) and a
local folder otherwise. Keys are relative; the configured prefix is added here, so callers never
see it. boto3 is synchronous: calls run in a thread so the event loop keeps serving.
"""

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from app.core.config import settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def signed_url(self, key: str, seconds: int) -> str | None: ...


class S3Storage:
    def __init__(self) -> None:
        import boto3  # imported here: the local setup does not need it loaded
        from botocore.config import Config

        self._client: S3Client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url or None,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            region_name=settings.storage_region,
            # SigV4 with bucket-in-path works on MinIO behind a proxy, R2 and S3 alike; the
            # defaults made MinIO refuse HEAD and signed links (checked against a real server).
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._bucket = settings.storage_bucket

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=settings.storage_key_prefix + key,
            Body=data,
            ContentType=content_type,
        )

    async def signed_url(self, key: str, seconds: int) -> str | None:
        """A GET link that works for `seconds` (the bucket itself stays private)."""
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": settings.storage_key_prefix + key},
            ExpiresIn=seconds,
        )


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = (self._root / settings.storage_key_prefix / key).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("storage key leaves the media folder")
        await asyncio.to_thread(_write, path, data)

    async def signed_url(self, key: str, seconds: int) -> str | None:
        return None  # local files are not served


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@lru_cache
def get_storage() -> Storage:
    """The process-wide storage. Tests replace it."""
    if settings.storage_enabled:
        return S3Storage()
    return LocalStorage(Path(settings.media_dir))
