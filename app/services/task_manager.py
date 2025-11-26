"""任务执行与进度推送管理。"""

import asyncio
import logging
import shutil
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session, session_scope
from ..models import VideoTSDetail, VideoTSTask
from ..schemas import CreateTaskRequest, SSEMessage, TaskDetailResponse
from . import downloader, storage, transcription

logger = logging.getLogger(__name__)

settings = get_settings()


def _now() -> datetime:
    """UTC 时间戳，便于写入 updated_at。"""

    return datetime.now(timezone.utc)


class TaskManager:
    """负责后台跑任务和 SSE 通知。"""

    def __init__(self) -> None:
        # task_id -> 订阅的队列列表
        self._subscribers: Dict[uuid.UUID, List[asyncio.Queue[SSEMessage]]] = defaultdict(list)
        # 本地存储策略下的临时结果（不入库）
        self._local_results: Dict[uuid.UUID, TaskDetailResponse] = {}
        # 记录上一次日志状态，避免重复打印
        self._last_log_state: Dict[uuid.UUID, tuple] = {}

    def subscribe(self, task_id: uuid.UUID) -> asyncio.Queue[SSEMessage]:
        """创建一个新的 SSE 订阅队列。"""

        queue: asyncio.Queue[SSEMessage] = asyncio.Queue()
        self._subscribers[task_id].append(queue)
        return queue

    def _publish(self, task_id: uuid.UUID, message: SSEMessage) -> None:
        """将消息推送给所有订阅者。"""

        for queue in self._subscribers.get(task_id, []):
            queue.put_nowait(message)

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """简单清洗文件名，避免特殊字符导致路径问题。"""

        invalid = r'\\/:*?"<>|'
        cleaned = "".join("_" if ch in invalid else ch for ch in name)
        cleaned = cleaned.strip().replace(" ", "_")
        return cleaned or "transcript"

    def _cleanup_subscribers(self, task_id: uuid.UUID) -> None:
        """任务结束后清理订阅队列，避免内存泄漏。"""

        if task_id in self._subscribers:
            del self._subscribers[task_id]

    async def enqueue(self, task: VideoTSTask, req: CreateTaskRequest) -> None:
        """启动异步任务执行。"""

        asyncio.create_task(self._process_task(task, req))

    async def _process_task(self, task: VideoTSTask, req: CreateTaskRequest) -> None:
        """实际执行转写流程，分阶段更新进度。"""

        task_id = task.id
        temp_root = settings.TEMP_DIR / str(task_id)
        loop = asyncio.get_running_loop()

        last_bucket = -1

        def _notify(message: str, progress: Optional[float] = None) -> None:
            """在线程中调用，转到事件循环更新状态（此处仅下载阶段触发一次）。"""

            nonlocal last_bucket
            if progress is not None:
                # 仅在第一次有进度时推送，避免频繁
                if last_bucket != -1:
                    return
                last_bucket = 0
            try:
                asyncio.run_coroutine_threadsafe(
                    self._update_status(task_id, progress=progress, message=message), loop
                )
            except Exception:
                logger.exception("任务 %s 进度通知失败", task_id)

        try:
            await self._update_status(task_id, status="processing", progress=5, message="开始处理")

            # 1) 下载媒体
            download_path, media_title = await asyncio.to_thread(
                downloader.download_media, str(task.video_source_url), temp_root, task.video_source, _notify
            )
            logger.info("任务 %s 下载完成，源标题：%s", task_id, media_title)
            await self._update_status(task_id, progress=25, message="下载完成，开始抽取音频")

            # 2) 抽取音频
            audio_path, file_size = await asyncio.to_thread(
                downloader.extract_audio_to_wav, download_path, temp_root
            )
            await self._update_status(task_id, progress=50, message="音频准备完成，开始转写")

            # 3) 转写
            text, detected_lang = await asyncio.to_thread(
                transcription.transcribe_audio,
                audio_path,
                req.model,
                req.device,
                req.compute_type,
                req.language,
            )
            await self._update_status(task_id, progress=80, message="转写完成，开始上传结果")

            # 4) 渲染并上传
            output_format = req.output_format or settings.DEFAULT_OUTPUT_FORMAT
            rendered = transcription.render_output(text, output_format)
            base_name = self._sanitize_filename(media_title)
            filename = f"{base_name}.{ 'md' if output_format == 'markdown' else 'txt' }"
            output_path = temp_root / filename
            output_path.write_text(rendered, encoding="utf-8")

            if settings.FILE_STORAGE_STRATEGY.lower() == "local":
                # 仅保存在本地，不上传、不入库
                local_detail = TaskDetailResponse(
                    file_name=filename,
                    file_path=str(output_path),
                    file_size=output_path.stat().st_size,
                    file_format=output_format,
                    detected_language=detected_lang,
                )
                self._local_results[task_id] = local_detail
            else:
                object_key = await asyncio.to_thread(
                    storage.upload_result_file, str(output_path), str(task_id), filename
                )
                public_url = storage.build_public_url(object_key)

                # 5) 写入文件记录
                await self._insert_detail(
                    task_id=task.id,
                    user_id=task.user_id,
                    file_name=filename,
                    file_path=public_url or object_key,
                    file_size=output_path.stat().st_size,
                    file_format=output_format,
                    detected_language=detected_lang,
                )

            await self._update_status(task_id, status="completed", progress=100, message="任务完成")
        except Exception as exc:  # noqa: BLE001
            await self._update_status(task_id, status="failed", message=str(exc))
        finally:
            # 清理临时目录
            if settings.CLEAN_TMP_FILE and temp_root.exists():
                shutil.rmtree(temp_root, ignore_errors=True)
            self._cleanup_subscribers(task_id)

    async def _update_status(
        self,
        task_id: uuid.UUID,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
    ) -> None:
        """更新任务状态并通知订阅者。"""

        async with session_scope() as session:
            stmt = select(VideoTSTask).where(VideoTSTask.id == task_id)
            result = await session.execute(stmt)
            db_task = result.scalar_one_or_none()
            if not db_task:
                return

            if status:
                db_task.status = status
            if progress is not None:
                db_task.progress = float(progress)
            if status == "failed" and message:
                db_task.error_message = message
            db_task.updated_at = _now()
            await session.flush()
            await session.refresh(db_task)
            details = await self._fetch_details(session, db_task.id)

        # 若失败且 message 为空，回填数据库中的 error_message 便于前端获取原因
        msg_message = message
        if status == "failed" and not msg_message:
            msg_message = db_task.error_message

        result_files = None
        if details:
            result_files = []
            for d in details:
                mdl = TaskDetailResponse.model_validate(d)
                # minio 存储才需要转换为可访问地址
                if settings.FILE_STORAGE_STRATEGY.lower() == "minio":
                    mdl.file_path = storage.resolve_file_url(mdl.file_path)
                result_files.append(mdl)
        # 若使用本地存储且已生成结果，则附加
        if settings.FILE_STORAGE_STRATEGY.lower() == "local" and task_id in self._local_results:
            result_files = result_files or []
            result_files.append(self._local_results[task_id])

        msg = SSEMessage(
            task_id=db_task.id,
            status=db_task.status,  # type: ignore[arg-type]
            progress=float(db_task.progress or 0),
            message=msg_message,
            result_files=result_files,
        )
        # 控制台打印，便于调试
        log_state = (db_task.status, float(db_task.progress or 0), msg_message)
        if self._last_log_state.get(task_id) != log_state:
            self._last_log_state[task_id] = log_state
            logger.info(
                "任务状态更新 task_id=%s status=%s progress=%.1f message=%s",
                task_id,
                db_task.status,
                float(db_task.progress or 0),
                msg_message,
            )
        self._publish(task_id, msg)

    async def _insert_detail(
        self,
        task_id: uuid.UUID,
        user_id: uuid.UUID,
        file_name: str,
        file_path: str,
        file_size: Optional[int],
        file_format: str,
        detected_language: Optional[str],
    ) -> None:
        """写入 video_ts_detail 记录。"""

        async with session_scope() as session:
            detail = VideoTSDetail(
                task_id=task_id,
                user_id=user_id,
                file_name=file_name,
                file_path=file_path,
                file_size=file_size,
                file_format=file_format,
                detected_language=detected_language,
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(detail)
            await session.flush()

    async def _fetch_details(self, session: AsyncSession, task_id: uuid.UUID) -> List[VideoTSDetail]:
        """查询结果文件列表（不新建事务）。"""

        stmt = select(VideoTSDetail).where(VideoTSDetail.task_id == task_id)
        result = await session.execute(stmt)
        details = list(result.scalars().all())
        # 本地存储时，附加内存中的结果
        if settings.FILE_STORAGE_STRATEGY.lower() == "local" and task_id in self._local_results:
            details.append(self._local_results[task_id])  # type: ignore[list-item]
        return details

    async def fetch_task_with_details(self, task_id: uuid.UUID) -> Optional[Tuple[VideoTSTask, List[VideoTSDetail]]]:
        """供接口查询任务和文件信息。"""

        async with session_scope() as session:
            stmt = select(VideoTSTask).where(VideoTSTask.id == task_id)
            result = await session.execute(stmt)
            db_task = result.scalar_one_or_none()
            if not db_task:
                return None
            details = await self._fetch_details(session, db_task.id)
            return db_task, details

    async def sse_stream(self, task_id: uuid.UUID) -> AsyncGenerator[str, None]:
        """SSE 生成器，持续从队列读取并按 SSE 协议输出。"""

        queue = self.subscribe(task_id)
        # 首次立即推送当前状态，方便后加入的订阅者
        current = await self.fetch_task_with_details(task_id)
        if current:
            task, details = current
            init_files = None
            if details:
                init_files = []
                for d in details:
                    mdl = TaskDetailResponse.model_validate(d)
                    mdl.file_path = storage.resolve_file_url(mdl.file_path)
                    init_files.append(mdl)

            init_msg = task.error_message if task.status == "failed" else "当前状态"
            init_event = SSEMessage(
                task_id=task.id,
                status=task.status,  # type: ignore[arg-type]
                progress=float(task.progress or 0),
                message=init_msg,
                result_files=init_files,
            )
            yield f"data: {init_event.model_dump_json()}\n\n"
            if task.status in {"completed", "failed"}:
                self._cleanup_subscribers(task_id)
                return

        try:
            while True:
                msg: SSEMessage = await queue.get()
                data_str = msg.model_dump_json()
                yield f"data: {data_str}\n\n"
                if msg.status in {"completed", "failed"}:
                    break
        finally:
            # 确保流结束时也清理
            self._cleanup_subscribers(task_id)


task_manager = TaskManager()
