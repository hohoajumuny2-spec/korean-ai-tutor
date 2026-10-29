"""자료 저장. PC에서는 SQLite 파일 하나, 학원 서버에서는 Firestore(sns_ 컬렉션)."""

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, request TEXT, status TEXT, progress TEXT, error TEXT,
    data TEXT, prev TEXT, created_at TEXT, updated_at TEXT
);
"""

LIST_FIELDS = ("id", "title", "status", "error", "created_at", "updated_at")


def now_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def _loads(value, default=None):
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _summary(row: dict) -> dict:
    out = {k: row.get(k) for k in LIST_FIELDS}
    req = row.get("request") or {}
    out["channels"] = req.get("channels", [])
    out["kind"] = req.get("kind")
    return out


class Store:
    def __init__(self, path: str):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.execute("UPDATE posts SET status='error', error='프로그램이 다시 시작되어 끊겼습니다. 다시 만들어 주세요.' "
                               "WHERE status='working'")
            self._conn.commit()

    def _exec(self, sql, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _one(self, sql, args=()):
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
            return dict(row) if row else None

    def get_setting(self, key, default=None):
        row = self._one("SELECT value FROM settings WHERE key=?", (key,))
        return _loads(row["value"], default) if row else default

    def set_setting(self, key, value):
        self._exec("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value, ensure_ascii=False)))

    def _post(self, row):
        if row:
            for k in ("request", "data", "prev"):
                row[k] = _loads(row[k])
        return row

    def create_post(self, title, request) -> int:
        t = now_str()
        cur = self._exec("INSERT INTO posts(title, request, status, progress, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                         (title, json.dumps(request, ensure_ascii=False), "working", "AI가 글을 쓰는 중…", t, t))
        return cur.lastrowid

    def update_post(self, pid, **fields):
        if not fields:
            return
        fields["updated_at"] = now_str()
        for k in ("request", "data", "prev"):
            if k in fields:
                fields[k] = json.dumps(fields[k], ensure_ascii=False) if fields[k] is not None else None
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE posts SET {cols} WHERE id=?", (*fields.values(), pid))

    def get_post(self, pid):
        return self._post(self._one("SELECT * FROM posts WHERE id=?", (pid,)))

    def list_posts(self, limit=200):
        with self._lock:
            rows = [dict(r) for r in self._conn.execute(
                "SELECT id, title, status, error, created_at, updated_at, request FROM posts ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()]
        for r in rows:
            r["request"] = _loads(r["request"], {})
        return [_summary(r) for r in rows]

    def delete_post(self, pid):
        self._exec("DELETE FROM posts WHERE id=?", (pid,))


class FirestoreStore:
    P = "sns_"

    def __init__(self, client):
        self.db = client
        self._id_lock = threading.Lock()
        self._last_id = 0
        for doc in self._col("posts").where("status", "==", "working").stream():
            doc.reference.set({"status": "error", "updated_at": now_str(),
                               "error": "서버가 다시 시작되어 끊겼습니다. 다시 만들어 주세요."}, merge=True)

    def _col(self, name):
        return self.db.collection(self.P + name)

    def _new_id(self) -> int:
        with self._id_lock:
            nid = max(int(time.time() * 1000), self._last_id + 1)
            self._last_id = nid
            return nid

    def get_setting(self, key, default=None):
        doc = self._col("settings").document(str(key)).get()
        return doc.to_dict().get("value", default) if doc.exists else default

    def set_setting(self, key, value):
        self._col("settings").document(str(key)).set({"value": value})

    def create_post(self, title, request) -> int:
        pid, t = self._new_id(), now_str()
        self._col("posts").document(str(pid)).set({
            "id": pid, "title": title, "request": request, "status": "working", "progress": "AI가 글을 쓰는 중…",
            "error": None, "data": None, "prev": None, "created_at": t, "updated_at": t})
        return pid

    def update_post(self, pid, **fields):
        fields["updated_at"] = now_str()
        self._col("posts").document(str(pid)).set(fields, merge=True)

    def get_post(self, pid):
        doc = self._col("posts").document(str(pid)).get()
        return doc.to_dict() if doc.exists else None

    def list_posts(self, limit=200):
        rows = [d.to_dict() for d in self._col("posts").stream()]
        rows.sort(key=lambda r: r.get("id", 0), reverse=True)
        return [_summary(r) for r in rows[:limit]]

    def delete_post(self, pid):
        self._col("posts").document(str(pid)).delete()
