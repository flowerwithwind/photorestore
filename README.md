# PhotoRestore · AI 影像修复工作台

> 纯本地视觉处理：老照片去噪去模糊 / 黑白上色 / 超分辨率，模型不出本机。
> 求职作品集项目 4/4 ｜ 开发中 v1.0.0-dev ｜ 演示模式示例图随 D6 提供

![CI](https://github.com/flowerwithwind/photorestore/actions/workflows/ci.yml/badge.svg)

## 能力一览

| 能力 | 说明 | 引擎 |
|---|---|---|
| 修复 | 老照片去噪、去模糊 | OpenCV 经典算法保底 + Real-ESRGAN ONNX 可选 |
| 上色 | 黑白照片自动上色 | DDColor ONNX（或等价替代） |
| 超分 | ×2 / ×4 分辨率增强 | Real-ESRGAN ONNX |
| 对比画廊 | before/after 滑动对比、按类型筛选、下载 | 前端组件 |
| 实时进度 | SSE 进度 + 阶段时间线 + 断线重连 | FastAPI + EventSource |
| 隐私本地 | 图像与模型均不离开本机 | 无任何外部 API |

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
- 质量：pytest + ruff + vitest + build（CI 执行，暂不自动部署）
