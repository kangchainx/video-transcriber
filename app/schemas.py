"""Pydantic 数据模型，定义请求与响应体（含中文注释）。"""

import uuid
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, ConfigDict


class CreateTaskRequest(BaseModel):
    """创建转写任务的请求体。"""

    video_url: HttpUrl = Field(..., alias="videoUrl", description="视频/音频下载地址")
    video_source: Optional[str] = Field(None, alias="videoSource", description="来源标识，如 youtube/url")
    model: Optional[str] = Field(None, description="模型名称，可选，默认 tiny")
    language: Optional[str] = Field(None, description="语言提示，可选")
    output_format: Optional[Literal["txt", "markdown"]] = Field(
        None, alias="output_format", description="输出格式，默认 txt"
    )
    device: Optional[str] = Field(None, description="推理设备，默认 cpu")
    compute_type: Optional[str] = Field(None, description="计算精度，默认 int8")
    user_id: Optional[uuid.UUID] = Field(None, alias="userId", description="由网关传入的用户 ID（或从签名头获取）")

    model_config = ConfigDict(populate_by_name=True)


class TaskDetailResponse(BaseModel):
    """单个结果文件描述。"""

    file_name: str
    file_path: str
    file_size: Optional[int]
    file_format: Optional[str]
    detected_language: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class TaskResponse(BaseModel):
    """任务状态响应。"""

    task_id: uuid.UUID
    status: Literal["pending", "processing", "completed", "failed"]
    progress: float = 0
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    details: List[TaskDetailResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SSEMessage(BaseModel):
    """SSE 推送的数据结构。"""

    task_id: uuid.UUID
    status: Literal["pending", "processing", "completed", "failed"]
    progress: float
    message: Optional[str] = None
    result_files: Optional[List[TaskDetailResponse]] = None
