"""pytest 全局夹具：临时数据目录 + 清库测试客户端。"""
from __future__ import annotations

import os
import tempfile

os.environ["PHOTORESTORE_DATA_DIR"] = tempfile.mkdtemp(prefix="photorestore-test-")
os.environ["PHOTORESTORE_MODELS_DIR"] = tempfile.mkdtemp(prefix="photorestore-models-test-")

import pytest
from app.main import app
from app.storage import db
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    with TestClient(app) as c:
        db.wipe_data()
        yield c
