"""문제 공장 — 지문을 주면 원하는 난이도·종류·유형·스타일로 문제를 만들어 두는 프로그램.

켜는 법:  python -m question_maker   (자세한 내용은 question_maker/README.md)
"""

import base64
import os
import random
import secrets
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from . import catalog
from .ai import AIError, make_ai
from .generator import (GenerationError, generate_set, merge_style, normalize_question,
                        normalize_recipe, renumber, revise_set)
from .render import render_paper
from .storage import KST, Store

STATIC = Path(__file__).parent / "static"

DAILY_DEFAULT = {
    "enabled": False,
    "time": "07:00",
    "per_day": 1,
    "weekdays": [0, 1, 2, 3, 4, 5, 6],   # 0=월요일
    "recipe": catalog.DEFAULT_RECIPE,
}


def daily_due(settings: dict, now: datetime, last_run: str) -> bool:
    """오늘 매일 출제를 돌릴 차례인지."""
    if not settings.get("enabled"):
        return False
    today = now.strftime("%Y-%m-%d")
    if last_run == today:
        return False
    if now.weekday() not in (settings.get("weekdays") or []):
        return False
    try:
        hh, mm = [int(x) for x in str(settings.get("time", "07:00")).split(":")[:2]]
    except ValueError:
        hh, mm = 7, 0
    return (now.hour, now.minute) >= (hh, mm)


# ─────────────────────────────────────────────────────────
# 요청 모양
# ─────────────────────────────────────────────────────────
class PassageReq(BaseModel):
    title: str = ""
    text: str
    subject: str = "국어"
    recipe: Optional[dict] = None


class PassageUpdateReq(BaseModel):
    title: Optional[str] = None
    text: Optional[str] = None
    subject: Optional[str] = None
    recipe: Optional[dict] = None
    clear_recipe: bool = False
    status: Optional[str] = None


class MoveReq(BaseModel):
    direction: int


class NewSetReq(BaseModel):
    title: str = ""
    text: str
    subject: str = "국어"
    recipe: dict
    save_passage: bool = False


class SetUpdateReq(BaseModel):
    title: Optional[str] = None
    data: Optional[dict] = None
    style_id: Optional[int] = None


class ReviseReq(BaseModel):
    instruction: str
    targets: List[int] = []


class StyleReq(BaseModel):
    data: dict


class DailyReq(BaseModel):
    enabled: bool
    time: str = "07:00"
    per_day: int = 1
    weekdays: List[int] = [0, 1, 2, 3, 4, 5, 6]
    recipe: dict


def create_app(db_path: Optional[str] = None, ai="auto", start_scheduler: bool = True) -> FastAPI:
    db_path = db_path or os.environ.get("QM_DB", str(Path.cwd() / "question_maker.db"))
    store = Store(db_path)
    if ai == "auto":
        ai = make_ai()
    password = os.environ.get("QM_PASSWORD", "").strip()
    jobs_sem = threading.Semaphore(2)   # AI에 동시에 너무 많이 보내지 않게

    app = FastAPI(title="문제 공장")
    app.state.store = store
    app.state.ai = ai

    # 인터넷에 올려 쓸 때는 QM_PASSWORD를 꼭 정한다. 아무나 들어와 AI 사용료를 쓰지 못하게.
    @app.middleware("http")
    async def check_password(request: Request, call_next):
        if password:
            ok = False
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("basic "):
                try:
                    _, _, given = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
                    ok = secrets.compare_digest(given, password)
                except Exception:
                    ok = False
            if not ok:
                return Response("비밀번호가 필요합니다.", status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="question-maker", charset="UTF-8"'})
        return await call_next(request)

    def style_for(style_id) -> dict:
        row = store.get_style(style_id) if style_id else None
        return merge_style(row["data"] if row else None)

    # ── 출제 작업 ──────────────────────────────────────
    def run_set(set_id: int):
        row = store.get_set(set_id)
        if not row:
            return
        with jobs_sem:
            try:
                style = style_for(row["style_id"])
                data = generate_set(
                    app.state.ai, source_text=row["source_text"], subject=row["subject"],
                    recipe=row["recipe"], style=style,
                    progress=lambda msg: store.update_set(set_id, progress=msg),
                    rng=random.Random())
                store.update_set(set_id, data=data, status="done", progress="완성", error="")
                if row["passage_id"]:
                    store.update_passage(row["passage_id"], status="done", error="", set_id=set_id)
            except (GenerationError, AIError) as e:
                store.update_set(set_id, status="error", progress="실패", error=str(e))
                if row["passage_id"]:
                    store.update_passage(row["passage_id"], status="error", error=str(e))
            except Exception as e:
                traceback.print_exc()
                store.update_set(set_id, status="error", progress="실패", error=f"예상하지 못한 오류: {e}")
                if row["passage_id"]:
                    store.update_passage(row["passage_id"], status="error", error=str(e))

    def start_from_passage(passage: dict, origin: str, wait: bool = False) -> int:
        recipe = passage.get("recipe") or (store.get_setting("daily", DAILY_DEFAULT) or DAILY_DEFAULT)["recipe"]
        recipe = normalize_recipe(recipe)
        stamp = datetime.now(KST).strftime("%m/%d")
        set_id = store.create_set(f"{passage['title']} ({stamp})", passage["subject"], passage["text"],
                                  recipe, recipe.get("style_id"), passage["id"], origin)
        store.update_passage(passage["id"], status="working", error="", set_id=set_id,
                             used_at=datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"))
        if wait:
            run_set(set_id)
        else:
            threading.Thread(target=run_set, args=(set_id,), daemon=True).start()
        return set_id

    def run_daily(now: datetime) -> list:
        settings = store.get_setting("daily", DAILY_DEFAULT) or DAILY_DEFAULT
        if not app.state.ai:
            return []   # 키가 없으면 지문을 꺼내지 않는다 (실패로 소모되지 않게)
        store.set_setting("daily_last_run", now.strftime("%Y-%m-%d"))
        made = []
        for p in store.next_waiting(max(1, int(settings.get("per_day", 1)))):
            try:
                made.append(start_from_passage(p, "daily", wait=True))
            except GenerationError as e:
                store.update_passage(p["id"], status="error", error=str(e))
        return made

    app.state.run_daily = run_daily

    def scheduler_loop():
        while True:
            try:
                now = datetime.now(KST)
                settings = store.get_setting("daily", DAILY_DEFAULT) or DAILY_DEFAULT
                if daily_due(settings, now, store.get_setting("daily_last_run", "")):
                    run_daily(now)
            except Exception:
                traceback.print_exc()
            time.sleep(30)

    if start_scheduler:
        threading.Thread(target=scheduler_loop, daemon=True).start()

    # ── 화면 ──────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/meta")
    def meta():
        return {
            "kinds": catalog.KINDS,
            "difficulties": {k: v[0] for k, v in catalog.DIFFICULTIES.items()},
            "difficulty_rules": {k: v[1] for k, v in catalog.DIFFICULTIES.items()},
            "types": catalog.QUESTION_TYPES,
            "default_style": catalog.DEFAULT_STYLE,
            "default_recipe": catalog.DEFAULT_RECIPE,
            "max_questions": catalog.MAX_QUESTIONS,
            "ai": app.state.ai.name if app.state.ai else None,
            "now": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        }

    # ── 지문 보관함 ───────────────────────────────────
    @app.get("/api/passages")
    def list_passages():
        return {"passages": store.list_passages()}

    @app.post("/api/passages")
    def add_passage(req: PassageReq):
        text = req.text.strip()
        if len(text) < 20:
            raise HTTPException(400, "지문이 너무 짧습니다.")
        try:
            recipe = normalize_recipe(req.recipe) if req.recipe else None
        except GenerationError as e:
            raise HTTPException(400, str(e))
        title = req.title.strip() or " ".join(text.split())[:20]
        return {"id": store.add_passage(title, text, req.subject.strip() or "국어", recipe)}

    @app.put("/api/passages/{pid}")
    def update_passage(pid: int, req: PassageUpdateReq):
        if not store.get_passage(pid):
            raise HTTPException(404, "없는 지문입니다.")
        fields = {k: v for k, v in req.model_dump().items()
                  if k in ("title", "text", "subject") and v is not None}
        if req.recipe is not None:
            try:
                fields["recipe"] = normalize_recipe(req.recipe)
            except GenerationError as e:
                raise HTTPException(400, str(e))
        if req.clear_recipe:
            fields["recipe"] = None
        if req.status == "waiting":
            fields.update(status="waiting", error="")
        store.update_passage(pid, **fields)
        return {"ok": True}

    @app.delete("/api/passages/{pid}")
    def delete_passage(pid: int):
        store.delete_passage(pid)
        return {"ok": True}

    @app.post("/api/passages/{pid}/move")
    def move_passage(pid: int, req: MoveReq):
        store.move_passage(pid, req.direction)
        return {"ok": True}

    @app.post("/api/passages/{pid}/generate")
    def generate_passage_now(pid: int):
        p = store.get_passage(pid)
        if not p:
            raise HTTPException(404, "없는 지문입니다.")
        if p["status"] == "working":
            raise HTTPException(409, "이미 출제 중입니다.")
        if not app.state.ai:
            raise HTTPException(400, "AI 키가 없습니다. README의 'AI 키 넣기'를 따라 해주세요.")
        try:
            return {"set_id": start_from_passage(p, "manual")}
        except GenerationError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/extract")
    async def extract_text(files: List[UploadFile] = File(...)):
        """txt·pdf·사진에서 글을 꺼낸다. 꺼낸 글은 저장하기 전에 화면에서 확인·수정한다."""
        texts = []
        for f in files:
            data = await f.read()
            name = (f.filename or "").lower()
            ctype = f.content_type or ""
            if name.endswith(".txt"):
                for enc in ("utf-8", "cp949"):
                    try:
                        texts.append(data.decode(enc))
                        break
                    except UnicodeDecodeError:
                        continue
            elif name.endswith(".pdf"):
                text = ""
                try:
                    import fitz
                    doc = fitz.open(stream=data, filetype="pdf")
                    text = "\n".join(page.get_text() for page in doc)
                    doc.close()
                except ImportError:
                    pass
                if len(text.strip()) < 50 and app.state.ai:
                    text = app.state.ai.transcribe(data, "application/pdf")
                texts.append(text)
            elif ctype.startswith("image/"):
                if not app.state.ai:
                    raise HTTPException(400, "사진에서 글을 읽으려면 AI 키가 필요합니다.")
                texts.append(app.state.ai.transcribe(data, ctype))
            else:
                raise HTTPException(400, f"{f.filename}: txt, pdf, 사진 파일만 읽을 수 있습니다.")
        return {"text": "\n\n".join(t.strip() for t in texts if t and t.strip())}

    # ── 문제 세트 ─────────────────────────────────────
    @app.post("/api/sets")
    def new_set(req: NewSetReq):
        text = req.text.strip()
        if len(text) < 20:
            raise HTTPException(400, "지문이 너무 짧습니다.")
        if not app.state.ai:
            raise HTTPException(400, "AI 키가 없습니다. README의 'AI 키 넣기'를 따라 해주세요.")
        try:
            recipe = normalize_recipe(req.recipe)
        except GenerationError as e:
            raise HTTPException(400, str(e))
        title = req.title.strip() or " ".join(text.split())[:20]
        subject = req.subject.strip() or "국어"
        pid = None
        if req.save_passage:
            pid = store.add_passage(title, text, subject, recipe)
            store.update_passage(pid, status="working")
        set_id = store.create_set(title, subject, text, recipe, recipe.get("style_id"), pid, "manual")
        threading.Thread(target=run_set, args=(set_id,), daemon=True).start()
        return {"set_id": set_id}

    @app.get("/api/sets")
    def list_sets():
        return {"sets": store.list_sets()}

    @app.get("/api/sets/{set_id}")
    def get_set(set_id: int):
        row = store.get_set(set_id)
        if not row:
            raise HTTPException(404, "없는 문제 세트입니다.")
        row["revisions"] = store.list_revisions(set_id)
        return row

    @app.put("/api/sets/{set_id}")
    def update_set(set_id: int, req: SetUpdateReq):
        row = store.get_set(set_id)
        if not row:
            raise HTTPException(404, "없는 문제 세트입니다.")
        fields = {}
        if req.title is not None and req.title.strip():
            fields["title"] = req.title.strip()
        if req.style_id is not None:
            fields["style_id"] = req.style_id or None
        if req.data is not None:
            if row["status"] != "done":
                raise HTTPException(409, "출제가 끝난 뒤에 고칠 수 있습니다.")
            style = style_for(fields.get("style_id", row["style_id"]))
            try:
                qs = [normalize_question(q, style) for q in req.data.get("questions") or []]
            except GenerationError as e:
                raise HTTPException(400, str(e))
            if not qs:
                raise HTTPException(400, "문항이 하나도 없습니다.")
            renumber(qs)
            new = dict(row["data"] or {})
            for k in ("intro", "passage", "source_note"):
                if k in req.data:
                    new[k] = str(req.data[k] or "")
            new["questions"] = qs
            store.push_revision(set_id, row["data"], "직접 고치기 전")
            fields["data"] = new
        if fields:
            store.update_set(set_id, **fields)
        return {"ok": True}

    @app.post("/api/sets/{set_id}/revise")
    def revise(set_id: int, req: ReviseReq):
        row = store.get_set(set_id)
        if not row:
            raise HTTPException(404, "없는 문제 세트입니다.")
        if row["status"] != "done" or not row["data"]:
            raise HTTPException(409, "출제가 끝난 뒤에 고칠 수 있습니다.")
        try:
            new, summary = revise_set(app.state.ai, source_text=row["source_text"], data=row["data"],
                                      instruction=req.instruction, targets=req.targets,
                                      style=style_for(row["style_id"]))
        except (GenerationError, AIError) as e:
            raise HTTPException(400, str(e))
        store.push_revision(set_id, row["data"], f"'{req.instruction.strip()[:40]}' 고치기 전")
        store.update_set(set_id, data=new)
        return {"ok": True, "summary": summary}

    @app.post("/api/sets/{set_id}/undo")
    def undo(set_id: int):
        prev = store.pop_revision(set_id)
        if not prev:
            raise HTTPException(400, "되돌릴 기록이 없습니다.")
        store.update_set(set_id, data=prev["data"])
        return {"ok": True, "note": prev["note"]}

    @app.post("/api/sets/{set_id}/regenerate")
    def regenerate(set_id: int):
        row = store.get_set(set_id)
        if not row:
            raise HTTPException(404, "없는 문제 세트입니다.")
        if row["status"] == "working":
            raise HTTPException(409, "이미 출제 중입니다.")
        if row["data"]:
            store.push_revision(set_id, row["data"], "다시 출제하기 전")
        store.update_set(set_id, status="working", progress="다시 출제합니다...", error="")
        threading.Thread(target=run_set, args=(set_id,), daemon=True).start()
        return {"ok": True}

    @app.delete("/api/sets/{set_id}")
    def delete_set(set_id: int):
        store.delete_set(set_id)
        return {"ok": True}

    @app.get("/print", response_class=HTMLResponse)
    def print_view(ids: str, mode: str = "both", style_id: Optional[int] = None):
        sets = []
        for part in ids.split(","):
            if part.strip().isdigit():
                row = store.get_set(int(part))
                if row and row["data"]:
                    sets.append(row)
        if not sets:
            raise HTTPException(404, "인쇄할 문제 세트가 없습니다.")
        style = style_for(style_id if style_id is not None else sets[0]["style_id"])
        if mode not in ("paper", "answers", "both"):
            mode = "both"
        return HTMLResponse(render_paper(sets, style, mode))

    # ── 스타일 ───────────────────────────────────────
    @app.get("/api/styles")
    def list_styles():
        return {"styles": store.list_styles()}

    @app.post("/api/styles")
    def add_style(req: StyleReq):
        return {"id": store.save_style(merge_style(req.data) | {"name": req.data.get("name") or "새 스타일"})}

    @app.put("/api/styles/{sid}")
    def update_style(sid: int, req: StyleReq):
        if not store.get_style(sid):
            raise HTTPException(404, "없는 스타일입니다.")
        store.save_style(merge_style(req.data) | {"name": req.data.get("name") or "이름 없는 스타일"}, sid)
        return {"ok": True}

    @app.delete("/api/styles/{sid}")
    def delete_style(sid: int):
        store.delete_style(sid)
        return {"ok": True}

    # ── 매일 출제 ─────────────────────────────────────
    @app.get("/api/daily")
    def get_daily():
        settings = store.get_setting("daily", DAILY_DEFAULT) or DAILY_DEFAULT
        return {"settings": settings, "last_run": store.get_setting("daily_last_run", ""),
                "waiting": len(store.next_waiting(10000))}

    @app.put("/api/daily")
    def save_daily(req: DailyReq):
        try:
            hh, mm = [int(x) for x in req.time.split(":")[:2]]
            assert 0 <= hh < 24 and 0 <= mm < 60
        except (ValueError, AssertionError):
            raise HTTPException(400, "시각은 07:30 처럼 적어주세요.")
        try:
            recipe = normalize_recipe(req.recipe)
        except GenerationError as e:
            raise HTTPException(400, str(e))
        settings = {
            "enabled": req.enabled, "time": f"{hh:02d}:{mm:02d}",
            "per_day": max(1, min(20, req.per_day)),
            "weekdays": sorted({d for d in req.weekdays if 0 <= d <= 6}),
            "recipe": recipe,
        }
        store.set_setting("daily", settings)
        return {"ok": True, "settings": settings}

    @app.post("/api/daily/run-now")
    def daily_run_now():
        settings = store.get_setting("daily", DAILY_DEFAULT) or DAILY_DEFAULT
        if not app.state.ai:
            raise HTTPException(400, "AI 키가 없습니다. README의 'AI 키 넣기'를 따라 해주세요.")
        made = []
        for p in store.next_waiting(max(1, int(settings.get("per_day", 1)))):
            try:
                made.append(start_from_passage(p, "daily"))
            except GenerationError as e:
                store.update_passage(p["id"], status="error", error=str(e))
        if not made:
            raise HTTPException(400, "대기 중인 지문이 없습니다.")
        return {"set_ids": made}

    @app.exception_handler(Exception)
    async def on_error(request: Request, exc: Exception):
        traceback.print_exc()
        return JSONResponse({"detail": f"서버 오류: {exc}"}, status_code=500)

    return app
