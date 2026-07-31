"""模型一键下载脚本（URL 配置 + SHA256 校验 + 失败可重跑）。

用法：
  python scripts/download_models.py            # 下载全部模型
  python scripts/download_models.py --only upscale
  python scripts/download_models.py --check    # 仅校验已下载文件
  python scripts/download_models.py --force    # 覆盖已存在文件

说明：D1 阶段 URL 为占位配置，D3 定稿模型文件与哈希后可直接使用；
sha256 为空时跳过校验并打印警告。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"

# key -> 模型文件清单（D3 细化；sha256 为空 = 占位，暂不校验）
MODELS: dict[str, dict] = {
    "restore": {
        "name": "去噪去模糊",
        "files": [
            {
                "name": "realesrgan-x4.onnx",
                "url": "https://example.com/models/realesrgan-x4.onnx",
                "sha256": "",
            }
        ],
    },
    "upscale": {
        "name": "超分辨率",
        "files": [
            {
                "name": "realesrgan-x2.onnx",
                "url": "https://example.com/models/realesrgan-x2.onnx",
                "sha256": "",
            },
            {
                "name": "realesrgan-x4.onnx",
                "url": "https://example.com/models/realesrgan-x4.onnx",
                "sha256": "",
            },
        ],
    },
    "colorize": {
        "name": "黑白上色",
        "files": [
            {
                "name": "ddcolor.onnx",
                "url": "https://example.com/models/ddcolor.onnx",
                "sha256": "",
            }
        ],
    },
}


class ChecksumError(RuntimeError):
    """SHA256 校验失败。"""


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path, expected_sha256: str = "", chunk_size: int = 1024 * 1024) -> Path:
    """下载文件到 dest；指定 expected_sha256 时校验，不匹配抛 ChecksumError。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)
    if expected_sha256:
        actual = sha256_file(dest)
        if actual.lower() != expected_sha256.lower():
            dest.unlink(missing_ok=True)
            raise ChecksumError(f"{dest.name} SHA256 不匹配: 期望 {expected_sha256}，实际 {actual}")
    return dest


def collect_targets(only: list[str] | None) -> list[dict]:
    keys = list(MODELS) if not only else only
    targets = []
    for key in keys:
        if key not in MODELS:
            raise SystemExit(f"未知模型组: {key}（可选: {', '.join(MODELS)}）")
        for f in MODELS[key]["files"]:
            targets.append({**f, "group": key})
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description="PhotoRestore 模型下载器")
    parser.add_argument("--only", nargs="*", help="仅下载指定模型组: restore/upscale/colorize")
    parser.add_argument("--check", action="store_true", help="仅校验已下载文件")
    parser.add_argument("--force", action="store_true", help="覆盖已存在文件")
    args = parser.parse_args()

    targets = collect_targets(args.only)
    failed = 0
    for t in targets:
        dest = MODELS_DIR / t["name"]
        if args.check:
            if dest.exists():
                if t["sha256"]:
                    ok = sha256_file(dest) == t["sha256"].lower()
                    print(f"[check] {t['name']}: {'OK' if ok else 'MISMATCH'}")
                    failed += 0 if ok else 1
                else:
                    print(f"[check] {t['name']}: 存在（占位配置，跳过校验）")
            else:
                print(f"[check] {t['name']}: 缺失")
                failed += 1
            continue
        if dest.exists() and not args.force:
            print(f"[skip] {t['name']} 已存在（--force 覆盖）")
            continue
        if not t["url"].startswith(("https://", "http://")):
            print(f"[warn] {t['name']} URL 为占位配置，跳过: {t['url']}")
            continue
        print(f"[download] {t['name']} <- {t['url']}")
        try:
            download_file(t["url"], dest, t["sha256"])
        except Exception as exc:  # noqa: BLE001 - 脚本需逐个失败继续
            print(f"[error] {t['name']}: {exc}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
