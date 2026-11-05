import asyncio
from pathlib import PurePath
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile

from app.api.models import Upload
from app.storage import Storage

router = APIRouter(tags=["uploads"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post(
    "/uploads",
    responses={413: {"description": "The file is over 20 MB"}, 415: {"description": "The file is not an image"}},
)
async def upload(file: UploadFile, request: Request) -> Upload:
    """Store a room photo (a HEIC one as a JPEG) and return its key. Without object storage (STORAGE_* unset), check it and drop it."""
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(415, "Upload an image")
    if (file.size or 0) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is over 20 MB")
    key = f"uploads/{uuid4().hex}{PurePath(file.filename or '').suffix.lower()}"  # never the client's path
    storage: Storage | None = request.app.state.storage
    if storage:
        key = await asyncio.to_thread(storage.put, key, await file.read(), file.content_type or "")
    return Upload(key=key)
