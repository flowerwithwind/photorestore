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



def list_images_with_tasks(
    *,
    task_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """画廊视图（D6）：按图像列表返回，并附带每张图像关联的任务。

    返回 {"items": [...], "total": N}；可选按任务类型/状态过滤（EXISTS 子查询）。
    """
    conditions: list[str] = []
    params: list[Any] = []
    if task_type is not None:
        conditions.append(
            "EXISTS (SELECT 1 FROM task_images ti JOIN tasks t ON t.id = ti.task_id"
            " WHERE ti.image_id = images.id AND t.task_type = ?)"
        )
        params.append(task_type)
    if status is not None:
        conditions.append(
            "EXISTS (SELECT 1 FROM task_images ti JOIN tasks t ON t.id = ti.task_id"
            " WHERE ti.image_id = images.id AND t.status = ?)"
        )
        params.append(status)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM images{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT id, filename, size_bytes, format, path, created_at"
            f" FROM images{where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        items = [dict(r) for r in rows]
        image_ids = [item["id"] for item in items]
        by_image: dict[int, list[int]] = {}
        if image_ids:
            placeholders = ",".join("?" * len(image_ids))
            link_rows = conn.execute(
                f"SELECT task_id, image_id FROM task_images"
                f" WHERE image_id IN ({placeholders}) ORDER BY task_id",
                image_ids,
            ).fetchall()
            for r in link_rows:
                by_image.setdefault(r["image_id"], []).append(r["task_id"])
            task_ids = sorted({tid for tids in by_image.values() for tid in tids})
            tasks_by_id: dict[int, dict] = {}
            if task_ids:
                t_placeholders = ",".join("?" * len(task_ids))
                task_rows = conn.execute(
                    f"SELECT * FROM tasks WHERE id IN ({t_placeholders})", task_ids
                ).fetchall()
                tasks_by_id = {t["id"]: _row_to_task(t) for t in task_rows}
        for item in items:
            item["tasks"] = [
                tasks_by_id[tid] for tid in by_image.get(item["id"], []) if tid in tasks_by_id
            ]
        return {"items": items, "total": int(total)}


def get_image_tasks(image_id: int) -> list[dict]:
    """按图像查询其全部关联任务（按 id 倒序，含状态/参数/结果）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT t.* FROM tasks t JOIN task_images ti ON ti.task_id = t.id"
            " WHERE ti.image_id = ? ORDER BY t.id DESC",
            (image_id,),
        ).fetchall()
        return [_row_to_task(r) for r in rows]


def delete_image_cascade(image_id: int) -> dict | None:
    """删除图片及其关联任务（级联 task_images/task_phase_logs），返回待清理文件信息。

    返回 {"image_path": str, "task_ids": [...], "output_paths": [...]}；
    图片不存在时返回 None。文件系统清理由调用方负责。
    """
    with get_conn() as conn:
        image = conn.execute("SELECT path FROM images WHERE id=?", (image_id,)).fetchone()
        if image is None:
            return None
        rows = conn.execute(
            "SELECT task_id FROM task_images WHERE image_id=? ORDER BY task_id", (image_id,)
        ).fetchall()
        task_ids = [int(r["task_id"]) for r in rows]
        output_paths: list[str] = []
        for task_id in task_ids:
            task = conn.execute(
                "SELECT result_json FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            result = jloads(task["result_json"], {}) if task and task["result_json"] else {}
            if isinstance(result, dict):
                for out in result.get("outputs") or []:
                    if isinstance(out, dict) and out.get("path"):
                        output_paths.append(out["path"])
            conn.execute("DELETE FROM task_phase_logs WHERE task_id=?", (task_id,))
            conn.execute("DELETE FROM task_images WHERE task_id=?", (task_id,))
            conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.execute("DELETE FROM task_images WHERE image_id=?", (image_id,))
        conn.execute("DELETE FROM images WHERE id=?", (image_id,))
        return {"image_path": image["path"], "task_ids": task_ids, "output_paths": output_paths}


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

def create_tasks_batch(
    *,
    task_type: str,
    status: str,
    params: dict[str, Any],
    params_hash: str,
    image_ids: list[int],
    created_at: str | None = None,
) -> list[int]:
    """原子批量创建任务（D7）：每张图像一个任务，单事务写入全部 tasks + task_images。

    任一插入失败（含外键约束）时整体回滚，不留任何残留记录；
    返回按输入顺序的 task_id 列表。
    """
    ts = created_at or now_iso()
    task_ids: list[int] = []
    with get_conn() as conn:
        for image_id in image_ids:
            cur = conn.execute(
                "INSERT INTO tasks(task_type, status, progress, phase, params_json, params_hash, created_at)"
                " VALUES(?,?,0,NULL,?,?,?)",
                (task_type, status, jdumps(params), params_hash, ts),
            )
            task_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO task_images(task_id, image_id) VALUES(?,?)",
                (task_id, image_id),
            )
            task_ids.append(task_id)
        return task_ids



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
