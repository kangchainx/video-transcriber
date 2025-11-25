# 视频转写服务

基于 FastAPI + faster-whisper 的语音转文字后台服务，支持创建任务、轮询查询与 SSE 实时进度，结果上传至 Minio 并记录数据库。

## 技术栈
- Python 3.11+
- FastAPI / Uvicorn
- SQLAlchemy Async + asyncpg（数据库：PostgreSQL，使用既有表 `video_ts_task`、`video_ts_detail`）
- faster-whisper（本地推理）
- Minio 存储
- yt-dlp + ffmpeg（媒体下载与抽音）

## 功能概览
- 创建转写任务：提交视频/音频 URL，后台异步处理，立即返回任务 ID。
- 进度查询：支持普通查询接口和 SSE 流式进度。
- 媒体处理：支持普通 HTTP/HTTPS 下载，自动识别 YouTube 链接可用 yt-dlp 抽音；ffmpeg 转码为 wav。
- 转写输出：faster-whisper 转写，输出 txt 或 markdown，结果上传 Minio `translation-result/<task_id>/...`，写入 `video_ts_detail`。
- 代理可选：需外网访问（如 YouTube）时可通过本地代理。

## 项目结构
```
app/
  api/
    routes.py        # REST 接口定义（创建/查询/SSE）
  services/
    downloader.py    # 下载与抽音（支持代理/YouTube）
    transcription.py # faster-whisper 转写与格式渲染
    storage.py       # Minio 上传与 URL 拼装
    task_manager.py  # 后台任务调度与进度推送
  config.py          # 配置加载（.env）
  db.py              # 数据库引擎与会话
  models.py          # ORM 映射到 video_ts_task / video_ts_detail
  schemas.py         # Pydantic 请求/响应模型
  main.py            # FastAPI 入口与路由挂载
.env.example         # 环境变量示例
requirements.txt     # Python 依赖
```

## 接口列表
- `GET /health`：健康检查。
- `POST /api/tasks`：创建任务。
  - 参数（JSON）：`videoUrl`、`videoSource`(可选)、`model`(默认 tiny)、`language`(可选)、`output_format`(txt|markdown，默认 txt)、`device`(默认 cpu)、`compute_type`(默认 int8)、`userId`(网关传入)。
  - 返回：`task_id`、`status`、`progress`。
- `GET /api/tasks/{task_id}`：查询任务状态与结果文件列表。
- `GET /api/tasks/{task_id}/stream`：SSE 推送进度及最终结果。

## 开发与使用
1. 准备环境
   - 安装 Python 3.11+，建议使用虚拟环境（virtualenv/venv）。
   - 本机安装 `ffmpeg` 与 `yt-dlp`（YouTube 需要代理时可用）。
   - 创建并激活虚拟环境（示例）：
     ```bash
     python -m venv .venv
     source .venv/bin/activate  # Windows: .venv\Scripts\activate
     ```
   - 安装 ffmpeg（macOS 示例）：`brew install ffmpeg`；其他平台请参考官方文档或包管理器。
2. 安装依赖
   ```bash
   pip install -r requirements.txt
   ```
3. 配置环境变量
   - 复制 `.env.example` 为 `.env`，按实际填充。
   - 核心项：`DATABASE_URL`（Postgres）、Minio 访问配置、代理开关 `PROXY_ENABLED` + `PROXY_URL`（如 `http://127.0.0.1:7890`，默认 false）、模型参数。
   - 可执行/下载配置：`FFMPEG_BIN`、`YTDLP_BIN`、可选 `YTDLP_COOKIES_FILE`（指向 cookies.txt，访问需登录的视频时使用）。
   - YouTube 细粒度：`YOUTUBE_PLAYER_CLIENT`（default/android），如设 android 建议配 `YOUTUBE_PO_TOKEN=android.gvs+XXXX`。
4. 启动开发服务
   ```bash
   uvicorn app.main:app --reload
   ```
   默认监听 `http://127.0.0.1:8000`。
5. 调用示例
   - 创建任务：
     ```bash
     curl -X POST http://127.0.0.1:8000/api/tasks \
       -H "Content-Type: application/json" \
       -d '{"videoUrl":"https://...","userId":"<uuid>","output_format":"txt"}'
     ```
   - 查询任务：`GET /api/tasks/<task_id>`
   - SSE 进度：`curl -N http://127.0.0.1:8000/api/tasks/<task_id>/stream`

## 数据库表（既有）
- `video_ts_task`：任务状态、进度、错误信息等。
- `video_ts_detail`：结果文件记录（文件名/路径/大小/格式/检测语言等）。

## 注意事项
- OpenAI 配置为可选，留空不影响启动。
-,env 中留空项会自动解析为 None，避免校验报错。
- 生产环境请关闭 `--reload`，并确保 ffmpeg/yt-dlp 可用、Minio 桶存在或具备创建权限。
