"""模型下载脚本测试（file:// 本地 URL，无网络依赖）。"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from download_models import ChecksumError, download_file, sha256_file


@pytest.fixture()
def source_file(tmp_path: Path) -> tuple[Path, str]:
    src = tmp_path / "model.onnx"
    src.write_bytes(b"fake-onnx-bytes-0123456789")
    return src, hashlib.sha256(src.read_bytes()).hexdigest()


def test_download_ok(tmp_path: Path, source_file: tuple[Path, str]):
    src, sha = source_file
    dest = tmp_path / "out" / "model.onnx"
    download_file(src.as_uri(), dest, sha)
    assert dest.read_bytes() == src.read_bytes()


def test_download_checksum_mismatch(tmp_path: Path, source_file: tuple[Path, str]):
    src, _ = source_file
    dest = tmp_path / "out" / "model.onnx"
    with pytest.raises(ChecksumError):
        download_file(src.as_uri(), dest, "0" * 64)
    assert not dest.exists()


def test_sha256_file(tmp_path: Path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    assert sha256_file(f) == hashlib.sha256(b"hello").hexdigest()
