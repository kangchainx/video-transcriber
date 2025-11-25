"""FastAPI 应用入口。"""

import asyncio
import logging
import shutil
from typing import Dict, Tuple

import uvicorn
from fastapi import FastAPI
from sqlalchemy import text

from .api.routes import router as api_router
from .config import get_settings
from .db import engine
from .services.storage import check_minio

settings = get_settings()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("video-transcriber")

app = FastAPI(title="Video Transcriber", version="0.1.0")
app.include_router(api_router)


async def _check_db() -> Tuple[bool, str]:
    """检查数据库连接是否可用。"""

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return True, "数据库连接正常"
    except Exception as exc:  # noqa: BLE001
        return False, f"数据库不可用：{exc}"


def _check_binary(name: str, path: str) -> Tuple[bool, str]:
    """检查可执行程序是否存在于 PATH 或指定路径。"""

    resolved = shutil.which(path)
    if resolved:
        return True, f"{name} 可用，路径：{resolved}"
    return False, f"{name} 不可用，请确认已安装并在 PATH 中：{path}"


async def log_component_status() -> None:
    """启动时打印关键组件状态。"""

    db_ok, db_msg = await _check_db()
    minio_ok, minio_msg = check_minio()
    ffmpeg_ok, ffmpeg_msg = _check_binary("ffmpeg", settings.FFMPEG_BIN)
    ytdlp_ok, ytdlp_msg = _check_binary("yt-dlp", settings.YTDLP_BIN)
    proxy_msg = (
        f"代理开启，URL={settings.PROXY_URL}"
        if settings.PROXY_ENABLED and settings.PROXY_URL
        else ("代理配置不完整（已开启但无 URL）" if settings.PROXY_ENABLED else "代理未开启")
    )

    icon = lambda ok: "✅" if ok else "❌"  # 简单状态图标

    logger.info("组件检测：数据库：%s %s", icon(db_ok), db_msg)
    logger.info("组件检测：Minio：%s %s", icon(minio_ok), minio_msg)
    logger.info("组件检测：ffmpeg：%s %s", icon(ffmpeg_ok), ffmpeg_msg)
    logger.info("组件检测：yt-dlp：%s %s", icon(ytdlp_ok), ytdlp_msg)
    logger.info("组件检测：代理：%s %s", icon(settings.PROXY_ENABLED and bool(settings.PROXY_URL)), proxy_msg)


@app.on_event("startup")
async def on_startup():
    """应用启动时进行必要组件检查。"""

    await log_component_status()


@app.get("/health")
async def health():
    """健康检查。"""

    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
