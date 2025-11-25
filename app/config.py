"""全局配置加载，集中管理环境变量（含中文注释）。"""

from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from pydantic import AnyHttpUrl, Field, HttpUrl, constr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """项目配置，覆盖默认值时使用环境变量。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 数据库配置
    DATABASE_URL: str = Field(..., description="Postgres 连接串，如 postgresql+asyncpg://user:pass@host:5432/db")

    # Minio 存储配置
    MINIO_ENDPOINT: str = Field(..., description="Minio 地址，格式 host:port")
    MINIO_ACCESS_KEY: str = Field(..., description="Minio Access Key")
    MINIO_SECRET_KEY: str = Field(..., description="Minio Secret Key")
    MINIO_BUCKET: str = Field("yvap", description="Minio 桶名称")
    MINIO_REGION: Optional[str] = Field(None, description="Minio 区域名，可为空")
    MINIO_SECURE: bool = Field(False, description="是否使用 HTTPS 访问 Minio")
    MINIO_PREFIX: Optional[str] = Field(None, description="对象键前缀，可为空")
    MINIO_PUBLIC_BASE_URL: Optional[AnyHttpUrl] = Field(
        None, description="对外可访问的 Minio 网关或 CDN 域名，拼接文件下载地址"
    )

    # 代理配置
    PROXY_ENABLED: bool = Field(False, description="是否开启代理下载（用于中国大陆访问 YouTube 等）")
    PROXY_URL: Optional[str] = Field(None, description="代理地址，如 http://127.0.0.1:7890")
    PROXY_BYPASS: Optional[str] = Field(None, description="无需代理的域名，逗号分隔，可选")

    # 模型配置
    FASTER_WHISPER_MODEL: str = Field("tiny", description="faster-whisper 模型名称")
    FASTER_WHISPER_DEVICE: str = Field("cpu", description="推理设备：cpu/cuda")
    FASTER_WHISPER_COMPUTE_TYPE: str = Field("int8", description="计算精度：int8/float16 等")

    # OpenAI Whisper 备用配置（可不使用）
    OPENAI_API_KEY: Optional[str] = Field(None, description="OpenAI API Key")
    OPENAI_BASE_URL: Optional[HttpUrl] = Field(None, description="自定义 OpenAI Base URL，可选")

    # YouTube 下载细粒度配置
    YOUTUBE_PLAYER_CLIENT: str = Field(
        "default",
        description="yt-dlp 使用的 player_client，默认 default；如需 android 请配合 YOUTUBE_PO_TOKEN",
    )
    YOUTUBE_PO_TOKEN: Optional[str] = Field(
        None, description="若使用 android 客户端需提供 po_token，格式如 android.gvs+XXXX"
    )

    # 任务输出配置
    DEFAULT_OUTPUT_FORMAT: constr(pattern="^(txt|markdown)$") = Field(
        "txt", description="默认输出格式，支持 txt 或 markdown"
    )
    TEMP_DIR: Path = Field(default=Path("tmp"), description="临时文件目录（默认放在项目根目录 tmp 下）")

    # 可执行程序路径（若需要自定义）
    FFMPEG_BIN: str = Field("ffmpeg", description="ffmpeg 可执行命令名称或绝对路径")
    YTDLP_BIN: str = Field("yt-dlp", description="yt-dlp 可执行命令名称或绝对路径")
    YTDLP_COOKIES_FILE: Optional[str] = Field(
        None, description="yt-dlp cookies 文件路径（可选），用于访问需登录的视频"
    )

    def proxy_dict(self) -> Dict[str, str]:
        """构造 requests/yt-dlp/ffmpeg 可用的代理配置。"""
        if not (self.PROXY_ENABLED and self.PROXY_URL):
            return {}
        return {"http": self.PROXY_URL, "https": self.PROXY_URL}

    # --------- 校正空字符串输入 ---------
    @field_validator("OPENAI_BASE_URL", "PROXY_URL", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: Optional[str]):
        """允许 .env 中留空时解析为 None，避免校验报错。"""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("PROXY_URL")
    @classmethod
    def _validate_proxy_url(cls, v: Optional[str]):
        """避免误填 true/false 导致 yt-dlp 解析代理失败。"""
        if v and v.lower() in {"true", "false"}:
            raise ValueError("PROXY_URL 需填写形如 http://127.0.0.1:7890 的地址，或留空")
        return v

    @field_validator("YOUTUBE_PLAYER_CLIENT")
    @classmethod
    def _clean_player_client(cls, v: str) -> str:
        """清洗 player_client，避免空字符串。"""
        return v or "default"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """统一获取配置实例，避免重复解析环境变量。"""

    settings = Settings()
    settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return settings
