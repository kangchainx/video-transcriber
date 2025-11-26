"""Minio 封装：上传转写结果文件并返回路径/URL。"""

from datetime import timedelta
from typing import Optional, Tuple
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from ..config import get_settings

settings = get_settings()


def _build_client() -> Minio:
    """创建 Minio 客户端（全部使用关键字参数以兼容新版本 SDK 的关键字限定签名）。"""

    return Minio(
        endpoint=settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
        region=settings.MINIO_REGION,
    )


_client = _build_client()


def _ensure_bucket_exists() -> None:
    """确保桶存在，不存在则创建（幂等）。"""

    if not _client.bucket_exists(bucket_name=settings.MINIO_BUCKET):
        _client.make_bucket(settings.MINIO_BUCKET)


def upload_result_file(local_path: str, task_id: str, filename: str) -> str:
    """
    上传文件到 Minio。
    返回对象键（或带前缀的路径），不负责删除本地文件。
    """

    _ensure_bucket_exists()
    # 对象键格式：translation-result/<task_id>/<filename>，可选前缀
    object_key = f"translation-result/{task_id}/{filename}"
    if settings.MINIO_PREFIX:
        object_key = f"{settings.MINIO_PREFIX.rstrip('/')}/{object_key}"

    _client.fput_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=object_key,
        file_path=local_path,
    )
    return object_key


def build_public_url(object_key: str) -> Optional[str]:
    """若配置了外部访问域名，拼接公开 URL。"""

    if not settings.MINIO_PUBLIC_BASE_URL:
        return None
    base = str(settings.MINIO_PUBLIC_BASE_URL)
    return f"{base.rstrip('/')}/{object_key}"


def presign_url(object_key: str, expires_seconds: int = 3600) -> str:
    """生成带时效的下载地址。"""

    return _client.presigned_get_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=object_key,
        expires=timedelta(seconds=expires_seconds),
    )


def presign_from_path(stored_path: str, expires_seconds: int = 3600) -> str:
    """
    强制对存储路径生成临时签名 URL。
    - 若是 http(s) 链接，尝试解析出 object_key 后签名；解析失败则直接使用路径部分
    - 若是对象键，直接签名
    """

    object_key = stored_path
    if stored_path.startswith(("http://", "https://")):
        parsed = urlparse(stored_path)
        path = parsed.path.lstrip("/")
        bucket_prefix = settings.MINIO_BUCKET.rstrip("/") + "/"
        if path.startswith(bucket_prefix):
            object_key = path[len(bucket_prefix) :]
        else:
            object_key = path
    return presign_url(object_key, expires_seconds)


def resolve_file_url(stored_path: str, expires_seconds: int = 3600) -> str:
    """
    根据存储路径返回可直接下载的 URL。
    - 若已是 http(s) 开头，直接返回
    - 若配置了公共域名，返回拼接 URL
    - 否则生成临时签名 URL
    """

    if stored_path.startswith("http://") or stored_path.startswith("https://"):
        return stored_path
    public = build_public_url(stored_path)
    if public:
        return public
    return presign_url(stored_path, expires_seconds)


def check_minio() -> Tuple[bool, str]:
    """健康检查：尝试 bucket_exists，不创建。"""

    try:
        exists = _client.bucket_exists(bucket_name=settings.MINIO_BUCKET)
        if exists:
            return True, f"Minio 可访问，桶 {settings.MINIO_BUCKET} 存在"
        return True, f"Minio 可访问，桶 {settings.MINIO_BUCKET} 不存在"
    except S3Error as exc:
        return False, f"Minio 访问异常：{exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Minio 未就绪：{exc}"
