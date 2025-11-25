"""数据库 ORM 模型，映射既有 Postgres 表结构。"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Numeric, String, Text, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """基础声明类。"""

    pass


class VideoTSTask(Base):
    """视频转写任务表，对应 video_ts_task。"""

    __tablename__ = "video_ts_task"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_source: Mapped[Optional[str]] = mapped_column(String(10))
    video_source_url: Mapped[Optional[str]] = mapped_column(String(500))
    # 仅存储 user_id，数据库已有外键约束到 users 表；此处不再声明以避免缺少 users 元数据时报错
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    progress: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now(), onupdate=func.now()
    )

    details: Mapped[list["VideoTSDetail"]] = relationship(
        "VideoTSDetail", back_populates="task", cascade="all, delete-orphan"
    )


class VideoTSDetail(Base):
    """视频转写结果文件表，对应 video_ts_detail。"""

    __tablename__ = "video_ts_detail"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("video_ts_task.id"))
    # 同上，保留 user_id 字段但不在 ORM 中声明外键
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    file_name: Mapped[str] = mapped_column(Text(), nullable=False)
    file_path: Mapped[str] = mapped_column(Text(), nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger)
    file_format: Mapped[Optional[str]] = mapped_column(String(50))
    detected_language: Mapped[Optional[str]] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now(), onupdate=func.now()
    )

    task: Mapped["VideoTSTask"] = relationship(
        "VideoTSTask", back_populates="details", primaryjoin="VideoTSDetail.task_id==VideoTSTask.id"
    )
