"""Thin wrapper around the MinIO client: upload/download raw bytes for one
bucket. Used by the ingestion upload endpoint (store the original file
untouched) and by the ingestion worker (read it back to parse).

The MinIO SDK is synchronous. It is only ever called from two places where
that is fine: a Celery task (already a separate sync process), and the
upload endpoint (one small-to-medium file, well under the request timeout —
not the multi-second GIS/tabular parsing work that actually needs a worker).
"""

from __future__ import annotations

import io
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.errors import AppError

_client: Minio | None = None


def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    return _client


def ensure_bucket() -> None:
    """Idempotent: create the bucket if it does not exist yet. Called once
    at API startup (see app/main.py) so the first real upload never race
    against bucket creation."""
    client = get_client()
    try:
        if not client.bucket_exists(settings.minio_bucket):
            client.make_bucket(settings.minio_bucket)
    except S3Error as exc:
        raise AppError("STORAGE_UNAVAILABLE", f"Object storage unreachable: {exc}", 503) from exc


def put_object(key: str, data: bytes, content_type: str) -> None:
    """Store `data` at `key`. Raises AppError(STORAGE_UNAVAILABLE) rather than
    letting a raw connection error bubble up — EXT-04: if this fails, the
    caller must not create a dataset_uploads row pointing at a file that was
    never actually written."""
    client = get_client()
    try:
        client.put_object(
            settings.minio_bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
    except S3Error as exc:
        raise AppError("STORAGE_UNAVAILABLE", f"Object storage unreachable: {exc}", 503) from exc


def get_presigned_url(key: str, expires_seconds: int) -> str:
    """A time-limited download URL (design's own words for reports.expires_at
    / EXT-04's "time-limited download URL") — the caller never gets a raw
    bucket path, only a signed link that stops working after `expires_seconds`."""
    client = get_client()
    try:
        return client.presigned_get_object(settings.minio_bucket, key, expires=timedelta(seconds=expires_seconds))
    except S3Error as exc:
        raise AppError("STORAGE_UNAVAILABLE", f"Object storage unreachable: {exc}", 503) from exc


def get_object(key: str) -> bytes:
    client = get_client()
    try:
        response = client.get_object(settings.minio_bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
    except S3Error as exc:
        raise AppError("STORAGE_UNAVAILABLE", f"Object storage unreachable: {exc}", 503) from exc
