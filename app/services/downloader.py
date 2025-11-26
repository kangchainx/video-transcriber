"""媒体下载与音频抽取工具，支持普通 HTTP 下载和 YouTube (yt-dlp)。"""

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Optional, Tuple

import requests
import yt_dlp

from ..config import get_settings

settings = get_settings()
ProgressCb = Callable[[str, Optional[float]], None]


def _build_proxy_env() -> dict:
    """生成代理相关的环境变量，用于 ffmpeg / yt-dlp。"""

    if not (settings.PROXY_ENABLED and settings.PROXY_URL):
        return {}
    # 简单校验，避免误填 true/false 等非法值
    if not settings.PROXY_URL.startswith(("http://", "https://", "socks5://", "socks5h://")):
        return {}
    env = {"http_proxy": settings.PROXY_URL, "https_proxy": settings.PROXY_URL}
    if settings.PROXY_BYPASS:
        env["no_proxy"] = settings.PROXY_BYPASS
    return env


def is_youtube(url: str) -> bool:
    """简单判断是否为 YouTube 链接。"""

    return bool(re.search(r"youtube\.com|youtu\.be", url, re.IGNORECASE))


def download_media(
    video_url: str,
    workdir: Path,
    video_source: Optional[str] = None,
    progress_cb: Optional[ProgressCb] = None,
) -> Tuple[Path, str]:
    """
    下载音/视频到临时目录。
    - 普通 URL：requests 流式下载
    - YouTube：yt-dlp 提取最佳音频
    返回 (本地文件路径, 标题/文件名基准)
    """

    workdir.mkdir(parents=True, exist_ok=True)
    is_yt = video_source == "youtube" or is_youtube(video_url)
    if is_yt:
        return _download_youtube(video_url, workdir, progress_cb)
    return _download_http(video_url, workdir, progress_cb)


def _download_http(url: str, workdir: Path, progress_cb: Optional[ProgressCb]) -> Tuple[Path, str]:
    """普通 HTTP/HTTPS 下载。"""

    local_path = workdir / f"{uuid.uuid4()}"
    proxies = settings.proxy_dict()
    with requests.get(url, stream=True, timeout=60, proxies=proxies) as resp:
        resp.raise_for_status()
        # 仅通知一次开始下载
        if progress_cb:
            progress_cb("正在下载媒体", 10.0)
        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    # 尝试用 URL basename 作为标题，缺失则用随机名
    title = Path(url.split("?")[0]).name or local_path.name
    return local_path, title


def _download_youtube(url: str, workdir: Path, progress_cb: Optional[ProgressCb]) -> Tuple[Path, str]:
    """
    使用 yt-dlp 抽取最佳音频到 wav。
    - 通过 yt_dlp Python API 便于传递代理与提取参数
    - 指定 player_client=android 可规避部分 SABR/JS 依赖问题
    """

    workdir.mkdir(parents=True, exist_ok=True)
    output_tpl = str(workdir / f"{uuid.uuid4()}.%(ext)s")

    proxy = None
    if settings.PROXY_ENABLED and settings.PROXY_URL and settings.PROXY_URL.startswith(
        ("http://", "https://", "socks5://", "socks5h://")
    ):
        proxy = settings.PROXY_URL

    player_client = settings.YOUTUBE_PLAYER_CLIENT or "default"
    po_token = settings.YOUTUBE_PO_TOKEN

    # 若选择 android 但没有 token，则自动回退 default，避免提示缺少 GVS PO Token
    if player_client.lower() == "android" and not po_token:
        player_client = "default"

    extractor_args = {"youtube": {"player_client": [player_client]}}
    if po_token:
        extractor_args["youtube"]["po_token"] = [po_token]

    cookies_file = None
    if settings.YTDLP_COOKIES_FILE:
        cf = Path(settings.YTDLP_COOKIES_FILE).expanduser()
        if not cf.exists():
            raise RuntimeError(f"指定的 cookies 文件不存在：{cf}")
        cookies_file = str(cf)

    def _hook(d):
        if progress_cb and d.get("status") == "downloading":
            progress_cb("正在下载媒体", 10.0)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_tpl,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            }
        ],
        # 强制单声道 + 16k 采样，便于后续转写
        "postprocessor_args": ["-ac", "1", "-ar", "16000"],
        "noplaylist": True,
        "quiet": True,
        "retries": 3,
        # 如果代理可用则透传
        "proxy": proxy,
        # 可配置的客户端与 po_token
        "extractor_args": extractor_args,
        # 可选 cookies
        "cookiefile": cookies_file,
        "progress_hooks": [_hook],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(f"yt-dlp 下载失败：{exc}") from exc

    # 取第一个 wav 结果
    wav_files = list(workdir.glob("*.wav"))
    if not wav_files:
        raise RuntimeError("yt-dlp 未生成音频文件，请检查链接、代理或 Cookie")
    title = info.get("title") or wav_files[0].stem
    return wav_files[0], title


def extract_audio_to_wav(input_path: Path, workdir: Path) -> Tuple[Path, Optional[int]]:
    """
    使用 ffmpeg 提取/转码为 wav，返回输出路径和文件大小。
    对已是 wav 的文件将直接复制。
    """

    workdir.mkdir(parents=True, exist_ok=True)
    output_path = workdir / f"{uuid.uuid4()}.wav"
    proxy_env = _build_proxy_env()

    if input_path.suffix.lower() == ".wav":
        shutil.copy(input_path, output_path)
    else:
        cmd = [
            settings.FFMPEG_BIN,
            "-y",
            "-i",
            str(input_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, env={**os.environ, **proxy_env})

    size = output_path.stat().st_size if output_path.exists() else None
    return output_path, size
