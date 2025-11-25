"""调用 faster-whisper 完成音频转写，输出 txt / markdown。"""

import logging
from pathlib import Path
from typing import Optional, Tuple

from faster_whisper import WhisperModel

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# 模型懒加载，避免多次初始化
_model_cache: dict[str, WhisperModel] = {}


def _get_model(model_name: str, device: str, compute_type: str) -> WhisperModel:
    """按需加载或复用 faster-whisper 模型。"""

    cache_key = f"{model_name}-{device}-{compute_type}"
    if cache_key in _model_cache:
        return _model_cache[cache_key]
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    _model_cache[cache_key] = model
    return model


def _get_model_with_fallback(model_name: str, device: str, compute_type: str) -> Tuple[WhisperModel, str, str]:
    """
    获取模型，如 CUDA 不可用自动回退到 CPU。
    返回：模型实例、实际设备、实际 compute_type。
    """

    try:
        model = _get_model(model_name, device, compute_type)
        return model, device, compute_type
    except RuntimeError as exc:
        if device.lower() == "cuda":
            logger.warning("CUDA 模式加载失败，自动回退 CPU：%s", exc)
            fallback_device = "cpu"
            fallback_compute = "int8"
            model = _get_model(model_name, fallback_device, fallback_compute)
            return model, fallback_device, fallback_compute
        raise


def transcribe_audio(
    audio_path: Path,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
    language: Optional[str] = None,
) -> Tuple[str, str]:
    """
    对音频进行转写。
    返回：文本结果、检测到的语言。
    """

    model_name = model_name or settings.FASTER_WHISPER_MODEL
    device = device or settings.FASTER_WHISPER_DEVICE
    compute_type = compute_type or settings.FASTER_WHISPER_COMPUTE_TYPE

    model, actual_device, actual_compute = _get_model_with_fallback(model_name, device, compute_type)
    segments, info = model.transcribe(str(audio_path), language=language)

    # 拼接纯文本
    lines = []
    for segment in segments:
        lines.append(segment.text.strip())
    text = "\n".join(lines).strip()
    detected_lang = info.language

    # 仅在回退时提示一次
    if actual_device != device:
        logger.info("已回退到设备=%s compute_type=%s 进行转写", actual_device, actual_compute)

    return text, detected_lang


def render_output(text: str, output_format: str) -> str:
    """根据目标格式渲染内容。"""

    if output_format == "markdown":
        return f"## 转写结果\n\n{text}"
    return text
