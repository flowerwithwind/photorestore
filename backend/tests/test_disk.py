"""磁盘统计与清理策略测试（tmp_path 造文件，hermetic）。"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app import config
from app.services import disk


def _make_files(directory: Path, specs: list[tuple[str, int, int]]) -> list[Path]:
    """specs: [(文件名, 字节数, mtime 相对偏移秒数)]，mtime 越大越新。"""
    directory.mkdir(parents=True, exist_ok=True)
    base = time.time() - 1000
    paths = []
    for name, size, offset in specs:
        path = directory / name
        path.write_bytes(b"x" * size)
        os.utime(path, (base + offset, base + offset))
        paths.append(path)
    return paths


def test_scan_and_compute_stats(tmp_path: Path):
    _make_files(tmp_path, [("a.jpg", 100, 1), ("b.jpg", 200, 2), ("c.png", 300, 3)])
    entries = disk.scan_directory(tmp_path)
    assert len(entries) == 3
    assert disk.compute_stats(entries) == {"count": 3, "bytes": 600}
    assert disk.scan_directory(tmp_path / "missing") == []


def test_get_storage_stats(tmp_path: Path):
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    _make_files(uploads, [("a.jpg", 100, 1), ("b.jpg", 200, 2)])
    _make_files(outputs, [("o.png", 300, 1)])
    stats = disk.get_storage_stats(uploads, outputs)
    assert stats["uploads"] == {"count": 2, "bytes": 300}
    assert stats["outputs"] == {"count": 1, "bytes": 300}
    assert stats["total"] == {"count": 3, "bytes": 600}


def test_plan_cleanup_by_count(tmp_path: Path):
    paths = _make_files(tmp_path, [("a", 10, 1), ("b", 20, 2), ("c", 30, 3), ("d", 40, 4), ("e", 50, 5)])
    plan = disk.plan_cleanup(disk.scan_directory(tmp_path), max_count=2)
    assert [entry.path.name for entry in plan] == ["a", "b", "c"]
    # plan_cleanup 只计算可删项，不实际删除文件
    all_names = {p.name for p in paths}
    deleted_names = {entry.path.name for entry in plan}
    assert all_names - deleted_names == {"d", "e"}


def test_plan_cleanup_by_bytes(tmp_path: Path):
    _make_files(tmp_path, [("a", 100, 1), ("b", 200, 2), ("c", 300, 3), ("d", 400, 4)])
    plan = disk.plan_cleanup(disk.scan_directory(tmp_path), max_bytes=600)
    # 总 1000B：删 a(100) b(200) c(300) 后剩 400B <= 600B
    assert [entry.path.name for entry in plan] == ["a", "b", "c"]


def test_plan_cleanup_combined_limits(tmp_path: Path):
    _make_files(tmp_path, [("a", 100, 1), ("b", 200, 2), ("c", 300, 3)])
    plan = disk.plan_cleanup(disk.scan_directory(tmp_path), max_count=1, max_bytes=300)
    # 删 a 后 count=2>1；删 b 后 count=1 且体积=300 <= 300
    assert [entry.path.name for entry in plan] == ["a", "b"]


def test_plan_cleanup_no_limits_returns_empty(tmp_path: Path):
    _make_files(tmp_path, [("a", 100, 1), ("b", 200, 2)])
    entries = disk.scan_directory(tmp_path)
    assert disk.plan_cleanup(entries) == []
    assert disk.plan_cleanup(entries, max_count=10, max_bytes=10**9) == []


def test_plan_cleanup_zero_count_deletes_all(tmp_path: Path):
    _make_files(tmp_path, [("a", 100, 1), ("b", 200, 2)])
    plan = disk.plan_cleanup(disk.scan_directory(tmp_path), max_count=0)
    assert len(plan) == 2


def test_plan_cleanup_rejects_negative_limits(tmp_path: Path):
    entries = disk.scan_directory(tmp_path)
    with pytest.raises(ValueError):
        disk.plan_cleanup(entries, max_count=-1)
    with pytest.raises(ValueError):
        disk.plan_cleanup(entries, max_bytes=-1)


def test_storage_stats_api(client, tmp_path: Path, monkeypatch):
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    _make_files(uploads, [("a.jpg", 100, 1)])
    _make_files(outputs, [("o1.png", 100, 1), ("o2.png", 200, 2)])
    monkeypatch.setattr(config, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(config, "OUTPUTS_DIR", outputs)
    r = client.get("/api/storage/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["uploads"] == {"count": 1, "bytes": 100}
    assert body["outputs"] == {"count": 2, "bytes": 300}


def test_cleanup_api_dry_run_and_execute(client, tmp_path: Path, monkeypatch):
    outputs = tmp_path / "outputs"
    _make_files(outputs, [("o1.png", 100, 1), ("o2.png", 200, 2), ("o3.png", 300, 3)])
    monkeypatch.setattr(config, "OUTPUTS_DIR", outputs)

    r = client.post("/api/storage/cleanup", json={"scope": "outputs", "max_count": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["count"] == 2
    assert len(list(outputs.iterdir())) == 3

    r = client.post(
        "/api/storage/cleanup",
        json={"scope": "outputs", "max_count": 1, "dry_run": False},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2
    assert sorted(p.name for p in outputs.iterdir()) == ["o3.png"]


def test_cleanup_api_requires_limit(client):
    r = client.post("/api/storage/cleanup", json={"scope": "outputs"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "cleanup_requires_limit"