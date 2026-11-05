"""Photos, overlays, renders and GLBs, on S3-compatible object storage: Cloudflare R2, or MinIO locally. Graph state holds only their keys.

boto3 blocks: from async code, call these through `asyncio.to_thread` (or FastAPI's `run_in_threadpool`).
"""

import io
import os
from pathlib import PurePosixPath

import boto3
import pillow_heif
from botocore.config import Config
from PIL import Image

pillow_heif.register_heif_opener()


def to_jpeg(heic: bytes) -> bytes:
    """A HEIC photo (what iPhones take) as a JPEG, which browsers and OpenCV read; its EXIF (the camera's focal length) is kept."""
    image = Image.open(io.BytesIO(heic))
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=90, exif=image.getexif(), icc_profile=image.info.get("icc_profile"))
    return out.getvalue()


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
        if pillow_heif.is_supported(data):
            data, content_type, key = to_jpeg(data), "image/jpeg", str(PurePosixPath(key).with_suffix(".jpg"))
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
