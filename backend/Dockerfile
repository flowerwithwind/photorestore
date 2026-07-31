# PhotoRestore 后端镜像：Python 3.12-slim + FastAPI/uvicorn（ONNX Runtime CPU + OpenCV）
# 布局保持 backend/ 层级，保证 app.config 的 PROJECT_ROOT 指向 /app（VERSION/models/data 解析正确）
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PHOTORESTORE_DATA_DIR=/app/data \
    PHOTORESTORE_MODELS_DIR=/app/models

WORKDIR /app

# OpenCV / onnxruntime 运行所需系统库
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/app /app/backend/app
COPY VERSION /app/VERSION
COPY scripts/download_models.py /app/scripts/download_models.py

EXPOSE 8030

CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8030"]
