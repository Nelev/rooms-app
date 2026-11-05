"""Photos, overlays, renders and GLBs, on S3-compatible object storage: Cloudflare R2, or MinIO locally. Graph state holds only their keys.

Without object storage (STORAGE_* unset), uploaded photos are kept in UPLOAD_DIR (default backend/.uploads/) under their key.

boto3 blocks: from async code, call these through `asyncio.to_thread` (or FastAPI's `run_in_threadpool`).
"""

import io
import mimetypes
import os
from pathlib import Path, PurePosixPath

import boto3
import pillow_heif
from botocore.config import Config
from PIL import Image

pillow_heif.register_heif_opener()

REPO = Path(__file__).resolve().parents[3]


def to_jpeg(heic: bytes) -> bytes:
    """A HEIC photo (what iPhones take) as a JPEG, which browsers and OpenCV read; its EXIF (the camera's focal length) is kept."""
    image = Image.open(io.BytesIO(heic))
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=90, exif=image.getexif(), icc_profile=image.info.get("icc_profile"))
    return out.getvalue()


def as_stored(key: str, data: bytes, content_type: str) -> tuple[str, bytes, str]:
    """A HEIC photo as a JPEG, its key ending in .jpg; anything else as it is."""
    if pillow_heif.is_supported(data):
        return str(PurePosixPath(key).with_suffix(".jpg")), to_jpeg(data), "image/jpeg"
    return key, data, content_type


def local_path(key: str) -> Path | None:
    """The local file of an image key: an uploads/ key in UPLOAD_DIR (photos uploaded without object storage), a fixtures/ key in
    fixtures/ (the stub runs' photos). None for any other key, one that is not a photo (an SVG is active content, not a photo) or one
    that leaves its directory."""
    mimetype = mimetypes.guess_type(key)[0] or ""
    if not mimetype.startswith("image/") or mimetype == "image/svg+xml" or "\0" in key:
        return None
    roots = {"uploads": Path(os.getenv("UPLOAD_DIR") or REPO / "backend" / ".uploads") / "uploads", "fixtures": REPO / "fixtures"}
    prefix, _, rest = key.partition("/")
    if not (root := roots.get(prefix)):
        return None
    path = (root / rest).resolve()
    return path if path.is_relative_to(root.resolve()) else None


def put_local(key: str, data: bytes, content_type: str) -> str:
    """Store an uploads/ photo in UPLOAD_DIR, as Storage.put would, and return the key it was stored at."""
    key, data, _ = as_stored(key, data, content_type)
    path = local_path(key)
    if not path:
        raise ValueError(f"not an uploads/ image key: {key}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


class Storage:
    """One bucket. The frontend reads objects through signed URLs, so the bucket stays private."""

    def __init__(self, endpoint_url: str, bucket: str, access_key_id: str, secret_access_key: str) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",  # what R2 expects; MinIO accepts any
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),  # path style: MinIO has no bucket subdomains
        )

    @classmethod
    def from_env(cls) -> "Storage":
        env = os.environ
        return cls(env["STORAGE_ENDPOINT_URL"], env["STORAGE_BUCKET"], env["STORAGE_ACCESS_KEY_ID"], env["STORAGE_SECRET_ACCESS_KEY"])

    def put(self, key: str, data: bytes, content_type: str) -> str:
        """Store `data` at `key` and return the key it was stored at: a HEIC photo is stored as a JPEG, its key ending in .jpg."""
        key, data, content_type = as_stored(key, data, content_type)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return key

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def url(self, key: str, expires_in: int = 3600) -> str:
        """A URL that reads the object for `expires_in` seconds, for the frontend."""
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in)

    def delete(self, key: str) -> None:
        """Delete the object; deleting a missing key is not an error."""
        self.client.delete_object(Bucket=self.bucket, Key=key)
