"""REST API 定义。"""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session, session_scope
from ..models import VideoTSTask
from ..schemas import CreateTaskRequest, TaskDetailResponse, TaskResponse
from ..services.task_manager import task_manager
from ..services.downloader import is_youtube  # 内部工具，用于自动判断来源
from ..services import storage
from ..auth import verify_signature
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(payload: CreateTaskRequest, user_id: Optional[str] = Depends(verify_signature)) -> TaskResponse:
    """创建转写任务，立即入库并异步处理。"""

    actual_user_id: Optional[uuid.UUID] = payload.user_id or (uuid.UUID(user_id) if user_id else None)
    if not actual_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 userId")

    # 先入库再调度，任何异常直接返回 500
    try:
        async with session_scope() as session:
            task = VideoTSTask(
                video_source=payload.video_source or ("youtube" if is_youtube(str(payload.video_url)) else "url"),
                video_source_url=str(payload.video_url),
                user_id=actual_user_id,
                status="pending",
                progress=0,
            )
            session.add(task)
            await session.flush()
            await session.refresh(task)
        # 启动后台处理（如果调度失败，也要告知调用方）
        await task_manager.enqueue(task, payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    # 控制台打印创建成功，便于调试
    logger.info("创建任务成功 task_id=%s source=%s url=%s", task.id, task.video_source, task.video_source_url)

    return TaskResponse(
        task_id=task.id,
        status=task.status,  # type: ignore[arg-type]
        progress=float(task.progress or 0),
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
        details=[],
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: uuid.UUID, _: Optional[str] = Depends(verify_signature)) -> TaskResponse:
    """查询单个任务状态。"""

    result = await task_manager.fetch_task_with_details(task_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    task, details = result
    detail_models = []
    for d in details:
        mdl = TaskDetailResponse.model_validate(d)
        if storage.settings.FILE_STORAGE_STRATEGY.lower() == "minio":
            mdl.file_path = storage.resolve_file_url(mdl.file_path)
        detail_models.append(mdl)
    return TaskResponse(
        task_id=task.id,
        status=task.status,  # type: ignore[arg-type]
        progress=float(task.progress or 0),
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
        details=detail_models,
    )


@router.get("/tasks/{task_id}/stream")
async def stream_task(task_id: uuid.UUID, _: Optional[str] = Depends(verify_signature)):
    """SSE 接口，推送后续进度。"""

    # 先确认任务存在
    exists = await task_manager.fetch_task_with_details(task_id)
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    async def event_generator():
        async for chunk in task_manager.sse_stream(task_id):
            yield chunk

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/tasks/{task_id}/download")
async def download_task_file(task_id: uuid.UUID, _: Optional[str] = Depends(verify_signature)):
    """
    返回任务结果文件的临时签名下载地址。
    默认取该任务最新的一条结果记录。
    """

    result = await task_manager.fetch_task_with_details(task_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    task, details = result
    if not details:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务暂无结果文件")

    # 取最新一条文件记录
    detail = sorted(details, key=lambda d: d.created_at or task.created_at)[-1]
    if storage.settings.FILE_STORAGE_STRATEGY.lower() == "minio":
        signed_url = storage.presign_from_path(detail.file_path)
    else:
        signed_url = detail.file_path
    return {"task_id": str(task_id), "file_name": detail.file_name, "download_url": signed_url}
