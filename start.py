"""项目启动脚本：预检依赖并启动 FastAPI 服务。

用法：
    python start.py --host 0.0.0.0 --port 8000 --reload
    python start.py --no-preflight   # 跳过预检
"""

import argparse
import asyncio
import logging
import shutil
import sys
from typing import Tuple

import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.services.storage import check_minio


logger = logging.getLogger("start")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _icon(ok: bool) -> str:
    """简单状态图标。"""

    return "✅" if ok else "❌"


def _check_binary(name: str, path: str) -> Tuple[bool, str]:
    """检查可执行程序是否存在于 PATH 或指定路径。"""

    resolved = shutil.which(path)
    if resolved:
        return True, f"{name} 可用，路径：{resolved}"
    return False, f"{name} 不可用，请确认已安装并在 PATH 中：{path}"


async def _check_db() -> Tuple[bool, str]:
    """检查数据库连通性。"""

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return True, "数据库连接正常"
    except Exception as exc:  # noqa: BLE001
        return False, f"数据库不可用：{exc}"
    finally:
        await engine.dispose()


async def preflight() -> None:
    """启动前预检：数据库、Minio、ffmpeg、yt-dlp、代理提示。"""

    settings = get_settings()

    db_ok, db_msg = await _check_db()
    if settings.FILE_STORAGE_STRATEGY.lower() == "minio":
        minio_ok, minio_msg = check_minio()
    else:
        minio_ok, minio_msg = True, "已跳过 Minio 检查（文件存储策略=local）"
    ffmpeg_ok, ffmpeg_msg = _check_binary("ffmpeg", settings.FFMPEG_BIN)
    ytdlp_ok, ytdlp_msg = _check_binary("yt-dlp", settings.YTDLP_BIN)
    proxy_ok = settings.PROXY_ENABLED and bool(settings.PROXY_URL)
    proxy_msg = (
        f"代理开启，URL={settings.PROXY_URL}"
        if proxy_ok
        else ("代理配置不完整（已开启但无 URL）" if settings.PROXY_ENABLED else "代理未开启")
    )

    logger.info("预检：数据库 %s %s", _icon(db_ok), db_msg)
    logger.info("预检：Minio %s %s", _icon(minio_ok), minio_msg)
    logger.info("预检：ffmpeg %s %s", _icon(ffmpeg_ok), ffmpeg_msg)
    logger.info("预检：yt-dlp %s %s", _icon(ytdlp_ok), ytdlp_msg)
    logger.info("预检：代理 %s %s", _icon(proxy_ok), proxy_msg)

    if not all([db_ok, ffmpeg_ok, ytdlp_ok, minio_ok]):
        logger.warning("预检存在异常，服务仍会尝试启动，请检查上方日志。")


def parse_args() -> argparse.Namespace:
    """解析启动参数。"""

    parser = argparse.ArgumentParser(description="启动 FastAPI 服务（含预检）")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用自动重载（开发模式）。未指定时将根据 APP_ENV=dev 自动开启。",
    )
    parser.add_argument(
        "--no-preflight",
        action="store_true",
        help="跳过预检（数据库/Minio/ffmpeg/yt-dlp/代理）。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()

    # 若未显式传 reload，且 APP_ENV=dev，则默认开启热重载
    reload_flag = args.reload or (str(getattr(settings, "APP_ENV", "")).lower() == "dev")

    if not args.no_preflight:
        asyncio.run(preflight())

    logger.info("启动服务 host=%s port=%s reload=%s", args.host, args.port, reload_flag)
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=reload_flag)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
