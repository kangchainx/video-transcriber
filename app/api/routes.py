"""REST API 定义。"""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session, session_scope
from ..models import VideoTSTask
from ..schemas import CreateTaskRequest, TaskDetailResponse, TaskResponse
from ..services.task_manager import task_manager
from ..services.downloader import is_youtube  # 内部工具，用于自动判断来源
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(payload: CreateTaskRequest) -> TaskResponse:
    """创建转写任务，立即入库并异步处理。"""

    # 先入库再调度，任何异常直接返回 500
    try:
        async with session_scope() as session:
            task = VideoTSTask(
                video_source=payload.video_source or ("youtube" if is_youtube(str(payload.video_url)) else "url"),
                video_source_url=str(payload.video_url),
                user_id=payload.user_id,
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
async def get_task(task_id: uuid.UUID) -> TaskResponse:
    """查询单个任务状态。"""

    result = await task_manager.fetch_task_with_details(task_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    task, details = result
    return TaskResponse(
        task_id=task.id,
        status=task.status,  # type: ignore[arg-type]
        progress=float(task.progress or 0),
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
        details=[TaskDetailResponse.model_validate(d) for d in details],
    )


@router.get("/tasks/{task_id}/stream")
async def stream_task(task_id: uuid.UUID):
    """SSE 接口，推送后续进度。"""

    # 先确认任务存在
    exists = await task_manager.fetch_task_with_details(task_id)
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    async def event_generator():
        async for chunk in task_manager.sse_stream(task_id):
            yield chunk

    return StreamingResponse(event_generator(), media_type="text/event-stream")
