# PhotoRestore · AI 影像修复工作台

> 纯本地视觉处理：老照片去噪去模糊 / 黑白上色 / 超分辨率，模型不出本机。
> 求职作品集项目 4/4 ｜ v1.0.0 正式发布 ｜ 演示模式示例图随 D6 提供

![CI](https://github.com/flowerwithwind/photorestore/actions/workflows/ci.yml/badge.svg)
![Version](https://img.shields.io/badge/version-v1.0.0-blue)

## 能力一览

| 能力 | 说明 | 引擎 |
|---|---|---|
| 修复 | 老照片去噪、去模糊 | OpenCV 经典算法保底 + Real-ESRGAN ONNX 可选 |
| 上色 | 黑白照片自动上色 | DDColor ONNX（或等价替代） |
| 超分 | ×2 / ×4 分辨率增强 | Real-ESRGAN ONNX |
| 对比画廊 | before/after 滑动对比、按类型筛选、下载 | 前端组件 |
| 实时进度 | SSE 进度 + 阶段时间线 + 断线重连 | FastAPI + EventSource |
| 隐私本地 | 图像与模型均不离开本机 | 无任何外部 API |

## 功能清单（D1 ~ D10）

| 里程碑 | 功能 |
|---|---|
| D1 | 项目骨架、环境与工程基线 |
| D2 | 数据模型与任务队列核心（tasks/images 表、状态机、线程池执行器、进度落库、重启恢复、磁盘统计与清理） |
| D3 | 图像管线与模型注册表（图像服务层、按任务类型路由、统一推理接口、缺模型明确报错） |
| D4 | 任务执行闭环（真实管线处理器、阶段时间线、协作式取消、SSE 进度推送、同图多版本产物） |
| D5 | 前端任务工作台（Vite+React、上传预检、任务列表、SSE 实时进度 + 轮询兜底、阶段时间线详情） |
| D6 | 对比画廊与下载（before/after 滑动对比、画廊筛选、级联删除、演示模式） |
| D7 | 参数面板与批量处理（批量原子入队、任务重跑、同图多版本展示） |
| D8 | 设置页与模型管理（模型元数据、并发配置、存储占用看板、模型下载指引） |
| D9 | 部署基础设施（Docker Compose + nginx 反代/SPA fallback + 数据卷 + 清理脚本） |
| D10 | v1.0.0 发布（真实字节上传链路、发布验收 e2e 测试、代码自审文档、版本统一与 GitHub Release） |

## 已知限制与已知问题（Known Issues）

1. **前端主包体积**：`vite build` 输出单入口 `index-*.js` 约 1.25 MB（gzip 约 413 kB），
   超过 Vite 500 kB 建议阈值——React + ECharts 等未做分包，后续按路由分包优化。
2. **JS 未分包**：第三方库全部打进同一 chunk，首次加载白屏时间较长。
3. **测试 act 警告**：vitest 运行时有 3 处 `not wrapped in act(...)` 警告（UploadView 异步状态更新），
   不影响断言正确性，后续用 `findBy*`/异步 `act` 消除。
4. **React Router future flag 警告**：v6 提示 v7 迁移（`v7_relativeSplatPath` 等），当前行为不受影响。
5. **Starlette 弃用警告**：`fastapi.testclient` 基于 `httpx`，提示未来迁移 `httpx2`，仅测试链路受影响。
6. **模型缺失行为**：restore 有经典算法保底；upscale/colorize 缺模型时任务会失败并提示
   运行 `scripts/download_models.py`（设置页有下载指引）。
7. **SSE 内存总线**：事件缓冲为进程内存（每任务 200 条），仅支持单实例部署；多实例需外置总线。
8. **上传限制**：单文件 ≤ 20MB、单边 ≤ 8000px（超限自动等比降采样后处理）；暂无分片/断点续传。
9. **SQLite 单写者**：默认并发 1；调高 `PHOTORESTORE_CONCURRENCY` 时受 SQLite 写锁约束。

详细设计、SSE/API 契约、安全性说明与后续建议见 [docs/code-review.md](docs/code-review.md)。
## 架构

```text
浏览器
  │  http://localhost:5175（静态页面 + React Router SPA fallback）
  ▼
frontend 容器（nginx）
  │  /api 反代（proxy_buffering off，SSE 友好；/healthz 容器健康检查）
  ▼
backend 容器（uvicorn :8030）
  │  FastAPI + SQLite + ONNX Runtime（CPU）
  ▼
挂载卷（宿主机持久化）
  ├─ models/  模型文件（download_models.py 下载）
  └─ data/    SQLite（photorestore.db）、uploads/、outputs/、tmp/
```

## 快速开始

### 方式一：Docker Compose（推荐，一键启动）

```bash
docker compose up -d --build
```

- 前端工作台：http://localhost:5175
- 后端健康检查：http://localhost:8030/api/health
- 前端反代健康检查：http://localhost:5175/api/health（验证 nginx → backend 链路）
- 前端容器健康检查：http://localhost:5175/healthz

### 方式二：本地开发

```bash
# 1. 环境（Python 3.12）
conda env create -f environment.yml
conda activate photorestore

# 2. 安装依赖
pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# 3. 下载模型（可选：无模型时自动使用经典算法保底）
python scripts/download_models.py

# 4. 启动后端（端口 8030）
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8030

# 5. 启动前端（端口 5175，/api 已代理到 8030，另开终端）
cd frontend
npm install
npm run dev
```

- 后端 API 文档：http://127.0.0.1:8030/docs

## 端口

| 服务 | 端口 | 说明 |
|---|---|---|
| backend | 8030 | FastAPI / uvicorn；/api/health 健康检查、/docs API 文档 |
| frontend | 5175 | nginx 静态托管 + SPA fallback；/api 反代到 backend，/healthz 容器健康检查 |

## 模型说明

模型放于 `models/`（Docker 部署时为挂载卷，容器重建不丢失），由 `scripts/download_models.py` 一键下载并做 SHA256 校验，失败可重跑。

- 本地：`python scripts/download_models.py`（`--check` 仅校验、`--only upscale` 按组下载、`--force` 覆盖）
- Docker：`docker compose exec backend python /app/scripts/download_models.py`
- 模型缺失时后端自动降级为 OpenCV 经典算法（restore 保底），保证演示链路完整。

## 数据管理

运行数据全部落在宿主机挂载卷（`data/` 与 `models/`），容器删除不丢数据。

| 操作 | 命令 |
|---|---|
| 下载模型 | `docker compose exec backend python /app/scripts/download_models.py` |
| 校验模型 | `docker compose exec backend python /app/scripts/download_models.py --check` |
| 清库/清产物（保留模型） | `bash scripts/docker_cleanup.sh` |
| 全部清理（含模型） | `bash scripts/docker_cleanup.sh --all` |
| 手动等价（Windows PowerShell） | `docker compose down` 后 `Remove-Item -Recurse -Force data\*` |

> 清库后重新 `docker compose up -d --build`，后端启动时自动重建空库与目录。

## 工程基线

- 后端：FastAPI + SQLite + ONNX Runtime（CPU）+ OpenCV
- 前端：React + Vite + ECharts（D5 起）
- 部署：Docker Compose（backend uvicorn :8030 + frontend nginx :5175，SSE 反代）
- 质量：pytest 158 passed + ruff 0 错误 + vitest 73 passed + build exit 0（CI 执行，暂不自动部署）
