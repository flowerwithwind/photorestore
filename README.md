# PhotoRestore · AI 影像修复工作台

> 纯本地视觉处理：老照片去噪去模糊 / 黑白上色 / 超分辨率，模型不出本机。
> 求职作品集项目 4/4 ｜ 开发中 v1.0.0-dev

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

## 快速开始

```bash
# 1. 环境（Python 3.12）
conda env create -f environment.yml
conda activate photorestore

# 2. 安装依赖
pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# 3. 下载模型（可选：无模型时自动使用经典算法保底）
python scripts/download_models.py

# 4. 启动后端
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8030
```

- 健康检查：http://127.0.0.1:8030/api/health
- API 文档：http://127.0.0.1:8030/docs
- 前端开发端口：5175（D5 里程碑提供）

## 模型说明

模型放于 `models/`（Docker 部署时挂载数据卷），由 `scripts/download_models.py` 一键下载并做 SHA256 校验，失败可重跑。
D1 阶段模型 URL 为占位配置；模型缺失时后端自动降级为 OpenCV 经典算法，保证演示链路完整。

## 工程基线

- 后端：FastAPI + SQLite + ONNX Runtime（CPU）+ OpenCV
- 前端：React + Vite + ECharts（D5 起）
- 质量：pytest + ruff + vitest + build（CI 执行，暂不自动部署）
