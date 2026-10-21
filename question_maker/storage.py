"""모든 자료를 파일 하나(SQLite)에 저장한다. 따로 DB 서버가 필요 없다."""

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

SCHEMA = """
CREATE TABLE IF NOT EXISTS passages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '국어',
    recipe TEXT,                -- 이 지문만의 출제 설정 (없으면 매일 출제 기본 설정)
    status TEXT NOT NULL DEFAULT 'waiting',   -- waiting | working | done | error
    error TEXT NOT NULL DEFAULT '',
    set_id INTEGER,
    position REAL NOT NULL,     -- 대기 순서 (작을수록 먼저)
    created_at TEXT NOT NULL,
    used_at TEXT
);
CREATE TABLE IF NOT EXISTS styles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '국어',
    passage_id INTEGER,
    source_text TEXT NOT NULL,
    recipe TEXT NOT NULL,
    style_id INTEGER,
    data TEXT,                  -- 지문(기호 표시) + 문항들
    status TEXT NOT NULL,       -- working | done | error
    progress TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'manual',   -- manual | daily
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id INTEGER NOT NULL,
    data TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def _loads(value, default=None):
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class Store:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            # 프로그램이 출제 도중 꺼졌다면 '만드는 중'으로 남은 것을 실패로 바꿔 둔다.
            self._conn.execute(
                "UPDATE question_sets SET status='error', error='프로그램이 다시 시작되어 출제가 끊겼습니다. 다시 출제해주세요.' "
                "WHERE status='working'")
            self._conn.execute("UPDATE passages SET status='waiting' WHERE status='working'")
            self._conn.commit()

    def _exec(self, sql, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _all(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        with self._lock:
            row = self._conn.execute(sql, args).fetchone()
            return dict(row) if row else None

    # ── 설정 ─────────────────────────────────────────
    def get_setting(self, key, default=None):
        row = self._one("SELECT value FROM settings WHERE key=?", (key,))
        return _loads(row["value"], default) if row else default

    def set_setting(self, key, value):
        self._exec("INSERT INTO settings(key, value) VALUES(?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value, ensure_ascii=False)))

    # ── 지문 보관함 ───────────────────────────────────
    def _passage(self, row):
        if row:
            row["recipe"] = _loads(row["recipe"])
        return row

    def add_passage(self, title, text, subject="국어", recipe=None) -> int:
        top = self._one("SELECT MAX(position) AS p FROM passages")
        pos = (top["p"] or 0) + 1
        cur = self._exec(
            "INSERT INTO passages(title, text, subject, recipe, position, created_at) VALUES(?,?,?,?,?,?)",
            (title, text, subject, json.dumps(recipe, ensure_ascii=False) if recipe else None, pos, now_str()))
        return cur.lastrowid

    def update_passage(self, pid, **fields):
        allowed = {"title", "text", "subject", "recipe", "status", "error", "set_id", "position", "used_at"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if "recipe" in fields:
            fields["recipe"] = json.dumps(fields["recipe"], ensure_ascii=False) if fields["recipe"] else None
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE passages SET {cols} WHERE id=?", (*fields.values(), pid))

    def get_passage(self, pid):
        return self._passage(self._one("SELECT * FROM passages WHERE id=?", (pid,)))

    def list_passages(self):
        rows = self._all("SELECT * FROM passages ORDER BY CASE status WHEN 'waiting' THEN 0 WHEN 'working' THEN 1 "
                         "WHEN 'error' THEN 2 ELSE 3 END, position, id DESC")
        return [self._passage(r) for r in rows]

    def next_waiting(self, limit):
        rows = self._all("SELECT * FROM passages WHERE status='waiting' ORDER BY position, id LIMIT ?", (limit,))
        return [self._passage(r) for r in rows]

    def move_passage(self, pid, direction):
        """대기 순서를 한 칸 올리거나(-1) 내린다(+1)."""
        waiting = self._all("SELECT id, position FROM passages WHERE status='waiting' ORDER BY position, id")
        ids = [r["id"] for r in waiting]
        if pid not in ids:
            return
        i = ids.index(pid)
        j = i + (1 if direction > 0 else -1)
        if not 0 <= j < len(ids):
            return
        a, b = waiting[i], waiting[j]
        with self._lock:
            self._conn.execute("UPDATE passages SET position=? WHERE id=?", (b["position"], a["id"]))
            self._conn.execute("UPDATE passages SET position=? WHERE id=?", (a["position"], b["id"]))
            self._conn.commit()

    def delete_passage(self, pid):
        self._exec("DELETE FROM passages WHERE id=?", (pid,))

    # ── 스타일 ───────────────────────────────────────
    def list_styles(self):
        rows = self._all("SELECT * FROM styles ORDER BY id")
        for r in rows:
            r["data"] = _loads(r["data"], {})
        return rows

    def get_style(self, sid):
        if not sid:
            return None
        row = self._one("SELECT * FROM styles WHERE id=?", (sid,))
        if row:
            row["data"] = _loads(row["data"], {})
        return row

    def save_style(self, data, sid=None) -> int:
        name = (data.get("name") or "이름 없는 스타일").strip()
        body = json.dumps(data, ensure_ascii=False)
        if sid and self.get_style(sid):
            self._exec("UPDATE styles SET name=?, data=?, updated_at=? WHERE id=?", (name, body, now_str(), sid))
            return sid
        cur = self._exec("INSERT INTO styles(name, data, created_at, updated_at) VALUES(?,?,?,?)",
                         (name, body, now_str(), now_str()))
        return cur.lastrowid

    def delete_style(self, sid):
        self._exec("DELETE FROM styles WHERE id=?", (sid,))

    # ── 문제 세트 ─────────────────────────────────────
    def _set(self, row):
        if row:
            row["recipe"] = _loads(row["recipe"], {})
            row["data"] = _loads(row["data"])
        return row

    def create_set(self, title, subject, source_text, recipe, style_id=None, passage_id=None, origin="manual") -> int:
        cur = self._exec(
            "INSERT INTO question_sets(title, subject, passage_id, source_text, recipe, style_id, status, progress, "
            "origin, created_at, updated_at) VALUES(?,?,?,?,?,?, 'working', '출제를 시작합니다...', ?, ?, ?)",
            (title, subject, passage_id, source_text, json.dumps(recipe, ensure_ascii=False), style_id,
             origin, now_str(), now_str()))
        return cur.lastrowid

    def update_set(self, set_id, **fields):
        allowed = {"title", "data", "status", "progress", "error", "style_id"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if "data" in fields:
            fields["data"] = json.dumps(fields["data"], ensure_ascii=False)
        fields["updated_at"] = now_str()
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE question_sets SET {cols} WHERE id=?", (*fields.values(), set_id))

    def get_set(self, set_id):
        return self._set(self._one("SELECT * FROM question_sets WHERE id=?", (set_id,)))

    def list_sets(self, limit=200):
        rows = self._all("SELECT id, title, subject, passage_id, recipe, style_id, status, progress, error, origin, "
                         "created_at, updated_at, data FROM question_sets ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            data = _loads(r.pop("data"))
            r["recipe"] = _loads(r["recipe"], {})
            r["question_count"] = len((data or {}).get("questions", []))
            out.append(r)
        return out

    def delete_set(self, set_id):
        self._exec("DELETE FROM revisions WHERE set_id=?", (set_id,))
        self._exec("DELETE FROM question_sets WHERE id=?", (set_id,))

    # ── 고치기 전 기록 (되돌리기용) ───────────────────
    def push_revision(self, set_id, data, note):
        self._exec("INSERT INTO revisions(set_id, data, note, created_at) VALUES(?,?,?,?)",
                   (set_id, json.dumps(data, ensure_ascii=False), note, now_str()))

    def list_revisions(self, set_id):
        return self._all("SELECT id, note, created_at FROM revisions WHERE set_id=? ORDER BY id DESC", (set_id,))

    def pop_revision(self, set_id):
        row = self._one("SELECT * FROM revisions WHERE set_id=? ORDER BY id DESC LIMIT 1", (set_id,))
        if not row:
            return None
        self._exec("DELETE FROM revisions WHERE id=?", (row["id"],))
        return {"data": _loads(row["data"]), "note": row["note"]}
