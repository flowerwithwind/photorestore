"""画廊 API 测试（D6）：列表/筛选、种子图片、原图下载、级联删除（hermetic）。"""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path

from PIL import Image

from app import config

_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "bmp": "BMP"}


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("等待条件超时")


def _image_bytes(fmt: str = "png", width: int = 24, height: int = 18) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (60, 90, 160)).save(buffer, format=_FORMATS[fmt])
    return buffer.getvalue()


def _create_image(client, name: str = "gallery.png", fmt: str = "png") -> int:
    data = _image_bytes(fmt)
    path = config.UPLOADS_DIR / name
    path.write_bytes(data)
    r = client.post(
        "/api/images",
        json={"filename": name, "size_bytes": len(data), "format": fmt, "path": str(path)},
    )
    assert r.status_code == 201
    return r.json()["id"]


def _wait_task(client, task_id: str | int):
    _wait_until(lambda: client.get(f"/api/tasks/{task_id}").json()["status"] in {
        "succeeded",
        "failed",
        "cancelled",
    })


def _task_output_path(client, task_id: int) -> Path:
    detail = client.get(f"/api/tasks/{task_id}").json()
    return Path(detail["result"]["outputs"][0]["path"])


def test_list_images_empty(client):
    body = client.get("/api/images").json()
    assert body == {"items": [], "total": 0}


def test_list_images_with_task_summaries_and_filters(client):
    image_a = _create_image(client, name="a.png")
    image_b = _create_image(client, name="b.png")
    task_a = client.post(
        "/api/tasks",
        json={"image_ids": [image_a], "task_type": "restore", "params": {}},
    ).json()["task_id"]
    task_b = client.post(
        "/api/tasks",
        json={"image_ids": [image_b], "task_type": "upscale", "params": {"scale": 2}},
    ).json()["task_id"]
    _wait_task(client, task_a)
    _wait_task(client, task_b)

    all_images = client.get("/api/images").json()
    assert all_images["total"] == 2
    by_id = {item["id"]: item for item in all_images["items"]}
    tasks_a = by_id[image_a]["tasks"]
    assert [t["id"] for t in tasks_a] == [task_a]
    assert tasks_a[0]["task_type"] == "restore"
    assert tasks_a[0]["status"] == "succeeded"
    assert tasks_a[0]["progress"] == 100
    assert tasks_a[0]["result"]["outputs"][0]["download_url"] == (
        f"/api/tasks/{task_a}/outputs/0/download"
    )
    assert by_id[image_b]["tasks"][0]["status"] == "failed"

    # 按任务类型筛选
    restore_only = client.get("/api/images", params={"task_type": "restore"}).json()
    assert [item["id"] for item in restore_only["items"]] == [image_a]
    # 按状态筛选（succeeded 只含 A；failed 只含 B）
    succeeded = client.get("/api/images", params={"status": "succeeded"}).json()
    assert [item["id"] for item in succeeded["items"]] == [image_a]
    failed = client.get("/api/images", params={"status": "failed"}).json()
    assert [item["id"] for item in failed["items"]] == [image_b]
    # 分页
    page = client.get("/api/images", params={"limit": 1, "offset": 0}).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1


def test_list_images_unsupported_task_type_400(client):
    r = client.get("/api/images", params={"task_type": "mystery"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_task_type"


def test_seed_image_registers_file(client):
    data = _image_bytes("png")
    r = client.post(
        "/api/images/seed",
        json={"filename": "demo_sunset.png", "data_base64": base64.b64encode(data).decode()},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["format"] == "png"
    assert body["size_bytes"] > 0
    stored = Path(body["path"])
    assert stored.is_file()
    assert stored.read_bytes().startswith(b"\x89PNG")
    assert stored.parent == config.UPLOADS_DIR
    # 登记后可查询
    assert client.get(f"/api/images/{body['id']}").json()["filename"] == body["filename"]


def test_seed_image_jpeg_normalized(client):
    data = _image_bytes("jpg")
    r = client.post(
        "/api/images/seed",
        json={"filename": "demo.jpg", "data_base64": base64.b64encode(data).decode()},
    )
    assert r.status_code == 201
    assert r.json()["format"] == "jpeg"


def test_seed_image_invalid_base64(client):
    r = client.post("/api/images/seed", json={"filename": "x.png", "data_base64": "!!!not-base64!!!"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_base64"


def test_seed_image_empty(client):
    r = client.post("/api/images/seed", json={"filename": "x.png", "data_base64": ""})
    assert r.status_code == 422  # Field(min_length=1)


def test_seed_image_too_large(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 10)
    r = client.post(
        "/api/images/seed",
        json={"filename": "big.png", "data_base64": base64.b64encode(_image_bytes()).decode()},
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "image_too_large"


def test_seed_image_invalid_content(client):
    r = client.post(
        "/api/images/seed",
        json={"filename": "fake.png", "data_base64": base64.b64encode(b"not an image at all").decode()},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_image"


def test_download_original_image(client):
    image_id = _create_image(client, name="orig.png")
    r = client.get(f"/api/images/{image_id}/download")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == _image_bytes("png")
    assert "attachment" in r.headers.get("content-disposition", "")


def test_download_original_image_404(client):
    assert client.get("/api/images/999/download").status_code == 404
    # 文件缺失但记录存在 -> file_not_found
    image_id = _create_image(client, name="ghost.png")
    Path(client.get(f"/api/images/{image_id}").json()["path"]).unlink()
    r = client.get(f"/api/images/{image_id}/download")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "file_not_found"


def test_delete_image_404(client):
    r = client.delete("/api/images/12345")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "image_not_found"


def test_delete_image_cascades_tasks_and_files(client):
    image_id = _create_image(client, name="doomed.png")
    task_id = client.post(
        "/api/tasks",
        json={"image_ids": [image_id], "task_type": "restore", "params": {}},
    ).json()["task_id"]
    _wait_task(client, task_id)
    original = Path(client.get(f"/api/images/{image_id}").json()["path"])
    output = _task_output_path(client, task_id)
    assert original.is_file() and output.is_file()

    r = client.delete(f"/api/images/{image_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] is True
    assert body["deleted_task_ids"] == [task_id]
    assert str(original) in body["removed_files"]
    assert str(output) in body["removed_files"]

    assert client.get(f"/api/images/{image_id}").status_code == 404
    assert client.get(f"/api/tasks/{task_id}").status_code == 404
    assert not original.exists()
    assert not output.exists()
    # 相册列表同步收缩
    assert client.get("/api/images").json() == {"items": [], "total": 0}


def test_delete_image_keeps_other_images_and_files(client):
    doomed_id = _create_image(client, name="doomed.png")
    kept_id = _create_image(client, name="kept.png")
    doomed_task = client.post(
        "/api/tasks",
        json={"image_ids": [doomed_id], "task_type": "restore", "params": {}},
    ).json()["task_id"]
    kept_task = client.post(
        "/api/tasks",
        json={"image_ids": [kept_id], "task_type": "restore", "params": {"scale": 2}},
    ).json()["task_id"]
    _wait_task(client, doomed_task)
    _wait_task(client, kept_task)
    kept_original = Path(client.get(f"/api/images/{kept_id}").json()["path"])
    kept_output = _task_output_path(client, kept_task)

    client.delete(f"/api/images/{doomed_id}")

    assert client.get(f"/api/images/{kept_id}").status_code == 200
    assert client.get(f"/api/tasks/{kept_task}").status_code == 200
    assert kept_original.is_file()
    assert kept_output.is_file()
    remaining = client.get("/api/images").json()
    assert [item["id"] for item in remaining["items"]] == [kept_id]


def test_delete_image_without_tasks(client):
    image_id = _create_image(client, name="lonely.png")
    original = Path(client.get(f"/api/images/{image_id}").json()["path"])
    r = client.delete(f"/api/images/{image_id}")
    assert r.status_code == 200
    assert r.json()["deleted_task_ids"] == []
    assert not original.exists()
    assert client.get("/api/images").json() == {"items": [], "total": 0}
