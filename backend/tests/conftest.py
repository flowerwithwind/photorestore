"""pytest 全局夹具：临时数据目录 + 清库测试客户端。"""
from __future__ import annotations

import os
import tempfile

os.environ["PHOTORESTORE_DATA_DIR"] = tempfile.mkdtemp(prefix="photorestore-test-")
os.environ["PHOTORESTORE_MODELS_DIR"] = tempfile.mkdtemp(prefix="photorestore-models-test-")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import db


@pytest.fixture()
def client():
    with TestClient(app) as c:
        db.wipe_data()
        yield c

@pytest.fixture(autouse=True)
def clean_artifact_dirs():
    """每个测试前清空 outputs/ 与 tmp/（产物与中间文件，保证 hermetic）。"""
    from app import config

    for directory in (config.OUTPUTS_DIR, config.TMP_DIR):
        if directory.is_dir():
            for child in directory.iterdir():
                if child.is_file():
                    child.unlink(missing_ok=True)
        else:
            directory.mkdir(parents=True, exist_ok=True)
    yield
