import time
import uuid
import os
import oss2
from config import settings


def _get_bucket() -> oss2.Bucket:
    auth = oss2.Auth(settings.access_key_id, settings.access_key_secret)
    return oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket_name)


def _build_object_key(original_filename: str) -> str:
    ext = os.path.splitext(original_filename)[1] or ".wav"
    unique = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    return f"{settings.oss_prefix}{unique}{ext}"


def upload_file(file_bytes: bytes, original_filename: str) -> tuple[str, str]:
    """上传文件到 OSS，返回 (签名 URL, object_key)。"""
    bucket = _get_bucket()
    object_key = _build_object_key(original_filename)
    bucket.put_object(object_key, file_bytes)
    url = bucket.sign_url("GET", object_key, settings.oss_expire_seconds)
    return url, object_key


def delete_file(object_key: str) -> None:
    """删除 OSS 上的临时文件。"""
    bucket = _get_bucket()
    bucket.delete_object(object_key)
