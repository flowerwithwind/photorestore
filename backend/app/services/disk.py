"""磁盘占用统计与清理策略（纯函数，便于 hermetic 测试）。

清理策略：按“保留最新、删除最旧”排序，当数量超过 max_count 或总体积
超过 max_bytes 时，从最旧的文件开始标记为可删项。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileEntry:
    path: Path
    size_bytes: int
    modified_at: float


def scan_directory(directory: Path) -> list[FileEntry]:
    """扫描目录下的普通文件（目录不存在时返回空列表）。"""
    if not directory.is_dir():
        return []
    entries: list[FileEntry] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append(FileEntry(path=path, size_bytes=stat.st_size, modified_at=stat.st_mtime))
    return entries


def compute_stats(entries: list[FileEntry]) -> dict[str, int]:
    """按数量与体积统计文件集合。"""
    return {"count": len(entries), "bytes": sum(entry.size_bytes for entry in entries)}


def get_storage_stats(uploads_dir: Path, outputs_dir: Path) -> dict:
    """统计原图目录与输出目录的数量/体积。"""
    uploads = scan_directory(uploads_dir)
    outputs = scan_directory(outputs_dir)
    return {
        "uploads": compute_stats(uploads),
        "outputs": compute_stats(outputs),
        "total": compute_stats(uploads + outputs),
    }


def plan_cleanup(
    entries: list[FileEntry],
    max_count: int | None = None,
    max_bytes: int | None = None,
) -> list[FileEntry]:
    """计算可删项：从最旧开始删，直到数量 <= max_count 且体积 <= max_bytes。

    - max_count / max_bytes 为 None 表示对应维度不限；
    - 两者都为 None 时无可删项；
    - 返回按旧到新排序的可删文件列表。
    """
    if max_count is not None and max_count < 0:
        raise ValueError("max_count 不能为负数")
    if max_bytes is not None and max_bytes < 0:
        raise ValueError("max_bytes 不能为负数")
    if max_count is None and max_bytes is None:
        return []
    ordered = sorted(entries, key=lambda entry: entry.modified_at)
    to_delete: list[FileEntry] = []
    remaining = list(ordered)
    while remaining:
        exceeds_count = max_count is not None and len(remaining) > max_count
        total_bytes = sum(entry.size_bytes for entry in remaining)
        exceeds_bytes = max_bytes is not None and total_bytes > max_bytes
        if not exceeds_count and not exceeds_bytes:
            break
        to_delete.append(remaining.pop(0))
    return to_delete