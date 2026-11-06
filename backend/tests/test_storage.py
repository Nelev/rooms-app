"""Object storage, on a real MinIO: TEST_STORAGE_ENDPOINT_URL (CI starts one), else skipped. Each test gets a bucket of its own."""

import io
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pillow_heif
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.storage import Storage

PHOTO = Path(__file__).parents[2] / "fixtures" / "small-bedroom" / "photo-1.jpg"


@pytest.fixture
def storage() -> Iterator[Storage]:
    endpoint = os.getenv("TEST_STORAGE_ENDPOINT_URL") or pytest.skip("TEST_STORAGE_ENDPOINT_URL is not set")
    storage = Storage(endpoint, f"test-{uuid.uuid4().hex[:12]}", "minioadmin", "minioadmin")  # MinIO's default credentials
    storage.client.create_bucket(Bucket=storage.bucket)
    yield storage
    for page in storage.client.get_paginator("list_objects_v2").paginate(Bucket=storage.bucket):
        for item in page.get("Contents", []):
            storage.client.delete_object(Bucket=storage.bucket, Key=item["Key"])
    storage.client.delete_bucket(Bucket=storage.bucket)


def test_upload_and_signed_read(storage: Storage) -> None:
    data = PHOTO.read_bytes()
    key = storage.put("uploads/t1/photo-1.jpg", data, "image/jpeg")
    assert key == "uploads/t1/photo-1.jpg"
    assert storage.get(key) == data

    response = httpx.get(storage.url(key))
    assert response.status_code == 200
    assert (response.content, response.headers["content-type"]) == (data, "image/jpeg")
    assert httpx.get(storage.url(key).replace("Signature=", "Signature=0")).status_code == 403  # the signature is checked


def test_heic_upload_is_stored_as_jpeg(storage: Storage) -> None:
    heic = io.BytesIO()
    photo = Image.open(PHOTO)
    exif = photo.getexif()
    exif[0x010F] = "Apple"  # Make: the EXIF survives the conversion
    pillow_heif.from_pillow(photo).save(heic, quality=80, exif=exif.tobytes())

    key = storage.put("uploads/t1/IMG_0001.HEIC", heic.getvalue(), "image/heic")
    assert key == "uploads/t1/IMG_0001.jpg"
    response = httpx.get(storage.url(key))
    assert response.headers["content-type"] == "image/jpeg"
    jpeg = Image.open(io.BytesIO(response.content))
    assert (jpeg.format, jpeg.size) == ("JPEG", photo.size)
    assert jpeg.getexif()[0x010F] == "Apple"


def test_upload_endpoint_stores_the_photo(storage: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)  # the app starts in memory, never on the developer's database
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    env = {"ENDPOINT_URL": os.environ["TEST_STORAGE_ENDPOINT_URL"], "BUCKET": storage.bucket, "ACCESS_KEY_ID": "minioadmin"}
    for name, value in {**env, "SECRET_ACCESS_KEY": "minioadmin"}.items():
        monkeypatch.setenv(f"STORAGE_{name}", value)
    with TestClient(app) as client:
        key = client.post("/uploads", files={"file": ("room.JPG", PHOTO.read_bytes(), "image/jpeg")}).json()["key"]
        redirect = client.get(f"/uploads/{key}", follow_redirects=False)
    assert key.startswith("uploads/") and key.endswith(".jpg")
    assert storage.get(key) == PHOTO.read_bytes()
    assert redirect.status_code == 307  # to a signed URL of the photo
    assert httpx.get(redirect.headers["location"]).content == PHOTO.read_bytes()


def test_signed_urls_name_the_public_endpoint() -> None:
    """Offline: signing needs no connection. The browser gets the public endpoint, the API keeps its own (docker compose's MinIO)."""
    storage = Storage("http://minio:9000", "rooms", "minioadmin", "minioadmin", public_url="http://localhost:19000")
    assert storage.url("uploads/a.jpg").startswith("http://localhost:19000/rooms/uploads/a.jpg?")
    assert storage.client.meta.endpoint_url == "http://minio:9000"
