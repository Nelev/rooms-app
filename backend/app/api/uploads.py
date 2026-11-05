from pathlib import PurePath
from uuid import uuid4

from fastapi import APIRouter, UploadFile

from app.api.models import Upload

router = APIRouter(tags=["uploads"])


@router.post("/uploads")
async def upload(file: UploadFile) -> Upload:
    """Store a photo. Stub: returns a key and drops the file."""
    return Upload(key=f"uploads/{uuid4().hex}{PurePath(file.filename or '').suffix.lower()}")  # never the client's path
