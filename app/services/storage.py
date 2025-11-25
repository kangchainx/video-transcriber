"""Minio 封装：上传转写结果文件并返回路径/URL。"""

import os
from typing import Optional, Tuple

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
