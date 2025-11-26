"""简单的 Header 签名校验，防止未授权调用。"""

import hmac
import time
import uuid
from hashlib import sha256
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from .config import get_settings

settings = get_settings()


def _validate_uuid(val: str) -> None:
    """校验 UUID 形态。"""

    try:
        uuid.UUID(val)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="X-Auth-UserId 无效") from exc


async def verify_signature(
    x_auth_userid: Optional[str] = Header(default=None, alias="X-Auth-UserId", convert_underscores=False),
    x_auth_timestamp: Optional[str] = Header(default=None, alias="X-Auth-Timestamp", convert_underscores=False),
    x_auth_nonce: Optional[str] = Header(default=None, alias="X-Auth-Nonce", convert_underscores=False),
    x_auth_sign: Optional[str] = Header(default=None, alias="X-Auth-Sign", convert_underscores=False),
):
    """
    校验请求签名：
    - 必须包含 4 个 Header
    - 时间戳在可接受窗口内
    - HMAC_SHA256(secret, userId|ts|nonce) 匹配
    - userId 必须是 UUID
    """

    if not settings.AUTH_ENABLED:
        return None

    missing = [h for h, v in {
        "X-Auth-UserId": x_auth_userid,
        "X-Auth-Timestamp": x_auth_timestamp,
        "X-Auth-Nonce": x_auth_nonce,
        "X-Auth-Sign": x_auth_sign,
    }.items() if not v]
    if missing:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"缺少认证头: {', '.join(missing)}")

    _validate_uuid(x_auth_userid)

    try:
        ts_int = int(x_auth_timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="X-Auth-Timestamp 无效") from exc

    now = int(time.time())
    tolerance = settings.AUTH_TOLERANCE_SECONDS
    if abs(now - ts_int) > tolerance:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请求已过期或时间戳异常")

    secret = settings.AUTH_SHARED_SECRET or ""
    if not secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="服务端未配置认证密钥")

    payload = f"{x_auth_userid}|{x_auth_timestamp}|{x_auth_nonce}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    if not hmac.compare_digest(expected, x_auth_sign):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="签名校验失败")

    return x_auth_userid
