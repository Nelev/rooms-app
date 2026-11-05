import asyncio
import mimetypes
from pathlib import PurePath
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.api.models import Upload
from app.storage import Storage, local_path, put_local

router = APIRouter(tags=["uploads"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post(
    "/uploads",
    responses={413: {"description": "The file is over 20 MB"}, 415: {"description": "The file is not an image"}},
)
async def upload(file: UploadFile, request: Request) -> Upload:
    """Store a room photo (a HEIC one as a JPEG) and return its key: in object storage, or in UPLOAD_DIR without it (STORAGE_* unset)."""
    content_type = file.content_type or ""
    suffix = PurePath(file.filename or "").suffix.lower() or mimetypes.guess_extension(content_type) or ""
    key = f"uploads/{uuid4().hex}{suffix}"  # never the client's path
    if not content_type.startswith("image/") or not local_path(key):  # local_path: a photo's extension, so GET /uploads serves it
        raise HTTPException(415, "Upload an image")
    if (file.size or 0) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is over 20 MB")
    storage: Storage | None = request.app.state.storage
    put = storage.put if storage else put_local
    return Upload(key=await asyncio.to_thread(put, key, await file.read(), content_type))


@router.get(
    "/uploads/{key:path}",
    response_class=FileResponse,
    responses={
        200: {"content": {"image/*": {}}, "description": "The photo"},
        307: {"description": "With object storage, a redirect to a signed URL of the photo"},
        404: {"description": "No such photo, or the key is not an uploads/ or fixtures/ image"},
    },
)
async def photo(key: str, request: Request) -> Response:
    """A room photo by its key: an uploaded one (uploads/...) or a fixture's (fixtures/..., the stub runs' photos)."""
    path = local_path(key)
    if not path:
        raise HTTPException(404, "No such photo")
    storage: Storage | None = request.app.state.storage
    if storage and key.startswith("uploads/"):
        return RedirectResponse(await asyncio.to_thread(storage.url, key))
    if not path.is_file():
        raise HTTPException(404, "No such photo")
    return FileResponse(path)
