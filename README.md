# 视频转写服务 · FastAPI + faster-whisper

将在线视频/音频转写为文本的异步服务，内置下载、抽音、转码、推理与结果分发。支持轮询与 SSE 进度、可选签名认证，可直接对接网关或任务系统。

*如果这个项目对您有帮助，请给个 star 🌟，你的支持将是我源源不断的动力。*

## 为什么用它
- 端到端链路：yt-dlp/HTTP 下载 → ffmpeg 抽音 → faster-whisper 推理 → txt/markdown 渲染与存储。
- 多来源输入：普通 URL 与 YouTube 自动识别，支持代理与 cookies 访问受限视频。
- 实时可观测：REST 查询 + SSE 流式进度，失败信息直达调用方。
- 结果可托管：Minio/本地存储二选一，提供签名下载 URL，文件路径写入数据库。
- 可控资源：自选模型、设备与 compute type，按需清理临时文件。
- 安全可选：HMAC 请求签名开关，时间戳容忍窗口可配置。

## 项目结构
```
app/
  api/routes.py        # 创建任务、状态查询、SSE、下载
  services/
    downloader.py      # HTTP/YouTube 下载与抽音（代理、cookies、player_client）
    transcription.py   # faster-whisper 推理与格式化
    storage.py         # Minio / 本地存储与签名 URL
    task_manager.py    # 异步队列、状态推进、SSE 推送
  auth.py              # 可选 HMAC 校验
  config.py            # Pydantic 配置加载
  db.py                # PostgreSQL 异步会话
  models.py            # video_ts_task / video_ts_detail 映射
  schemas.py           # Pydantic 请求 / 响应模型
  main.py              # FastAPI 入口
.env.example           # 环境变量示例
requirements.txt       # 依赖列表
```

## 快速开始
1) 准备依赖：Python 3.11+、PostgreSQL、`ffmpeg`、`yt-dlp`（YouTube 需代理时请准备可用代理）。  
2) 创建虚拟环境并安装依赖：
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
3) 配置环境变量：
```bash
cp .env.example .env
# 填写 DATABASE_URL、Minio 或 local 存储配置、代理/模型/认证等
```
4) 启动开发服务：
```bash
uvicorn app.main:app --reload
# 默认 http://127.0.0.1:8000
```
5) 创建任务示例：
```bash
curl -X POST http://127.0.0.1:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"videoUrl":"https://...","userId":"<uuid>","output_format":"txt"}'
```
随后可调用 `GET /api/tasks/{task_id}` 或 `curl -N /api/tasks/{task_id}/stream` 查看进度。

## 配置说明（.env）
- 必填
  - `DATABASE_URL`：PostgreSQL 连接串。
  - 存储：`FILE_STORAGE_STRATEGY=minio|local`。使用 Minio 时需 `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MINIO_BUCKET`，可选 `MINIO_PREFIX`、`MINIO_REGION`、`MINIO_PUBLIC_BASE_URL`、`MINIO_SECURE`。
- 模型与推理
  - `FASTER_WHISPER_MODEL`（默认 tiny）、`FASTER_WHISPER_DEVICE`（cpu/cuda）、`FASTER_WHISPER_COMPUTE_TYPE`（int8/float16 等）、`DEFAULT_OUTPUT_FORMAT`（txt/markdown）。
- 下载与代理
  - `PROXY_ENABLED` + `PROXY_URL` + `PROXY_BYPASS`；`YTDLP_COOKIES_FILE` 支持 cookies 登录。
  - YouTube 细节：`YOUTUBE_PLAYER_CLIENT`（default/android）、`YOUTUBE_PO_TOKEN`（android.gvs+XXXX）。
- 运行与路径
  - `TEMP_DIR`（默认 ./tmp）、`CLEAN_TMP_FILE`、`FFMPEG_BIN`、`YTDLP_BIN`。
- 认证（可选）
  - `AUTH_ENABLED`、`AUTH_SHARED_SECRET`、`AUTH_TOLERANCE_SECONDS`。开启后需带以下请求头：`X-Auth-UserId`、`X-Auth-Timestamp`、`X-Auth-Nonce`、`X-Auth-Sign`（HMAC_SHA256(secret, userId|ts|nonce)）。
- OpenAI 备用
  - `OPENAI_API_KEY`、`OPENAI_BASE_URL`（留空不影响本地 faster-whisper）。

## 接口速览
- `GET /health`：健康检查。
- `POST /api/tasks`：创建任务。请求字段：`videoUrl`、`userId`（UUID，必填）、可选 `videoSource`、`model`、`language`、`output_format`(txt|markdown)、`device`、`compute_type`。
- `GET /api/tasks/{task_id}`：查询状态与结果文件列表。
- `GET /api/tasks/{task_id}/stream`：SSE 推送进度与最终结果。
- `GET /api/tasks/{task_id}/download`：返回最新结果文件的签名下载地址（Minio）或本地路径。

## 处理流程
1. 创建任务并写入 `video_ts_task`，立即返回 task_id。
2. downloader 根据来源决定 HTTP 或 yt-dlp 下载，支持代理、cookies 与 YouTube player_client。
3. ffmpeg 抽取音频并转码为 wav。
4. faster-whisper 推理，按请求格式渲染为 txt/markdown。
5. 结果上传到 Minio 或写入本地存储，记录到 `video_ts_detail`，返回签名 URL。
6. task_manager 持续更新进度，REST/SSE 均可获取最新状态。

## 数据库表（既有）
- `video_ts_task`：任务状态、进度、错误信息。
- `video_ts_detail`：结果文件名/路径/格式/大小/检测语言等。

## 注意事项
- `.env` 中留空项会被自动解析为 None，减少校验报错。
- YouTube 需代理时请提前验证 `PROXY_URL`；如设 `YOUTUBE_PLAYER_CLIENT=android` 建议同时提供 `YOUTUBE_PO_TOKEN`。
- 生产部署请关闭 `--reload`，确保 ffmpeg/yt-dlp 可用、Minio 桶存在或本地存储目录可写。

## Docker 构建与运行
### 仅构建镜像
在项目根目录执行：
```bash
docker build -t video-transcriber:latest .
```
代理环境可改为（将地址替换为你的代理）：
```bash
docker build \
  --build-arg HTTP_PROXY=http://127.0.0.1:7890 \
  --build-arg HTTPS_PROXY=http://127.0.0.1:7890 \
  -t video-transcriber:latest .
```

### 直接运行（需要自备 Postgres/Minio）
```bash
docker run --rm -p 8000:8000 --env-file .env video-transcriber:latest
```
注意：`.env` 里的 `DATABASE_URL`、`MINIO_ENDPOINT` 等如果写的是 `localhost`，容器内通常不可用；请改成真实可达地址或使用下方 compose。

### 用 docker compose 一键启动（推荐）
项目已提供 `docker-compose.yml`（含 Postgres + Minio + app）：
```bash
docker compose up --build
```
- 代理环境：先在当前 shell 导出 `HTTP_PROXY/HTTPS_PROXY/NO_PROXY`，compose 会自动透传到 build 与运行时环境
- 服务：API `http://127.0.0.1:8000`，Minio `http://127.0.0.1:9000`，Minio Console `http://127.0.0.1:9001`
- 首次使用请在 Minio Console 创建桶 `yvap`（或修改 compose 里的 `MINIO_BUCKET`）
