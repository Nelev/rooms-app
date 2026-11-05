from pathlib import PurePath
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile

from app.api.models import Upload

router = APIRouter(tags=["uploads"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post(
    "/uploads",
    responses={413: {"description": "The file is over 20 MB"}, 415: {"description": "The file is not an image"}},
)
async def upload(file: UploadFile) -> Upload:
    """Store a room photo. Stub: checks it, returns a key and drops the file."""
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(415, "Upload an image")
    if (file.size or 0) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is over 20 MB")
    return Upload(key=f"uploads/{uuid4().hex}{PurePath(file.filename or '').suffix.lower()}")  # never the client's path
