"""SQLite 存储层：连接管理、建表、DAO。

设计约定：
- 每次操作独立连接（WAL 模式），简单可靠；
- 时间统一 ISO 8601 字符串（本地时间）；
- JSON 字段以 TEXT 存储。
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any

from app.config import DB_PATH
from app.models import now_iso

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS images (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filename TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  format TEXT NOT NULL,
  path TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_type TEXT NOT NULL,
  status TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0,
  phase TEXT,
  params_json TEXT NOT NULL DEFAULT '{}',
  params_hash TEXT NOT NULL,
  error TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS task_images (
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  image_id INTEGER NOT NULL REFERENCES images(id),
  PRIMARY KEY (task_id, image_id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_task_images_image ON task_images(image_id);

CREATE TABLE IF NOT EXISTS task_phase_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  phase TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  duration_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_task_phase_logs_task ON task_phase_logs(task_id);
"""


def jdumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def jloads(raw: str | None, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_conn() -> Iterable[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)


def wipe_data() -> None:
    """清空全部业务数据（测试与演示数据管理用）。"""
    with get_conn() as conn:
        conn.executescript(
            "DELETE FROM task_phase_logs; DELETE FROM task_images; DELETE FROM tasks; DELETE FROM images; DELETE FROM settings;"
        )


# ---------------------------------------------------------------------------
# settings DAO
# ---------------------------------------------------------------------------


def get_setting(key: str, default: Any = None) -> Any:
    with get_conn() as conn:
        row = conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        return jloads(row["value_json"], default) if row else default


def set_setting(key: str, value: Any) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, jdumps(value)),
        )


def get_all_settings() -> dict[str, Any]:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
        return {r["key"]: jloads(r["value_json"]) for r in rows}


# ---------------------------------------------------------------------------
# images DAO
# ---------------------------------------------------------------------------


def create_image(
    *,
    filename: str,
    size_bytes: int,
    format_: str,
    path: str,
    created_at: str | None = None,
) -> int:
    """登记一张原图元数据，返回自增 id。"""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO images(filename, size_bytes, format, path, created_at) VALUES(?,?,?,?,?)",
            (filename, size_bytes, format_, path, created_at or now_iso()),
        )
        return int(cur.lastrowid)


def get_image(image_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, filename, size_bytes, format, path, created_at FROM images WHERE id=?",
            (image_id,),
        ).fetchone()
        return dict(row) if row else None


def list_images() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, filename, size_bytes, format, path, created_at FROM images ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# tasks DAO
# ---------------------------------------------------------------------------


def _row_to_task(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "task_type": row["task_type"],
        "status": row["status"],
        "progress": row["progress"],
        "phase": row["phase"],
        "params": jloads(row["params_json"], {}),
        "params_hash": row["params_hash"],
        "error": row["error"],
        "result": jloads(row["result_json"]),
        "image_ids": [],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def create_task(
    *,
    task_type: str,
    status: str,
    params: dict[str, Any],
    params_hash: str,
    image_ids: list[int],
    created_at: str | None = None,
) -> int:
    """创建任务（初始 status 通常为 queued）并绑定图像，返回自增 id。"""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO tasks(task_type, status, progress, phase, params_json, params_hash, created_at)"
            " VALUES(?,?,0,NULL,?,?,?)",
            (task_type, status, jdumps(params), params_hash, created_at or now_iso()),
        )
        task_id = int(cur.lastrowid)
        conn.executemany(
            "INSERT INTO task_images(task_id, image_id) VALUES(?,?)",
            [(task_id, image_id) for image_id in image_ids],
        )
        return task_id


def get_task(task_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            return None
        task = _row_to_task(row)
        rows = conn.execute(
            "SELECT image_id FROM task_images WHERE task_id=? ORDER BY image_id", (task_id,)
        ).fetchall()
        task["image_ids"] = [r["image_id"] for r in rows]
        return task


def list_tasks(status: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
    sql = "SELECT * FROM tasks"
    params: list[Any] = []
    if status is not None:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        tasks = [_row_to_task(r) for r in rows]
        ids = [t["id"] for t in tasks]
        if ids:
            placeholders = ",".join("?" * len(ids))
            img_rows = conn.execute(
                f"SELECT task_id, image_id FROM task_images WHERE task_id IN ({placeholders}) ORDER BY image_id",
                ids,
            ).fetchall()
            by_task: dict[int, list[int]] = {}
            for r in img_rows:
                by_task.setdefault(r["task_id"], []).append(r["image_id"])
            for task in tasks:
                task["image_ids"] = by_task.get(task["id"], [])
        return tasks


def update_task_status(
    task_id: int,
    status: str,
    *,
    started_at: str | None = None,
    finished_at: str | None = None,
    progress: int | None = None,
    phase: str | None = None,
    error: str | None = None,
    result: Any = None,
    expected_status: str | None = None,
) -> bool:
    """更新任务状态及可选字段（状态机守卫由 service 层负责）。

    传入 expected_status 时按条件更新（WHERE status=expected_status），
    用于并发场景下防止覆盖其它线程刚写入的状态（如 queued 取消竞态）。
    """
    sets = ["status=?"]
    params: list[Any] = [status]
    if started_at is not None:
        sets.append("started_at=?")
        params.append(started_at)
    if finished_at is not None:
        sets.append("finished_at=?")
        params.append(finished_at)
    if progress is not None:
        sets.append("progress=?")
        params.append(progress)
    if phase is not None:
        sets.append("phase=?")
        params.append(phase)
    if error is not None:
        sets.append("error=?")
        params.append(error)
    if result is not None:
        sets.append("result_json=?")
        params.append(jdumps(result))
    params.append(task_id)
    sql = f"UPDATE tasks SET {', '.join(sets)} WHERE id=?"
    if expected_status is not None:
        sql += " AND status=?"
        params.append(expected_status)
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount > 0


def update_task_progress(task_id: int, progress: int, phase: str) -> bool:
    """进度与阶段实时落库（单调性由 executor 的 ProgressReporter 保证）。"""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE tasks SET progress=?, phase=? WHERE id=?", (progress, phase, task_id)
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# task phase logs DAO（D4：阶段时间线）
# ---------------------------------------------------------------------------


def log_phase_start(task_id: int, phase: str, started_at: str) -> int:
    """记录一个阶段的开始，返回日志 id。"""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO task_phase_logs(task_id, phase, started_at) VALUES(?,?,?)",
            (task_id, phase, started_at),
        )
        return int(cur.lastrowid)


def log_phase_finish(log_id: int, finished_at: str, duration_ms: int) -> bool:
    """记录阶段结束时间与耗时（毫秒）。"""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE task_phase_logs SET finished_at=?, duration_ms=? WHERE id=?",
            (finished_at, duration_ms, log_id),
        )
        return cur.rowcount > 0


def get_phase_logs(task_id: int) -> list[dict]:
    """按开始顺序返回某任务的全部阶段日志。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, phase, started_at, finished_at, duration_ms"
            " FROM task_phase_logs WHERE task_id=? ORDER BY id",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]
