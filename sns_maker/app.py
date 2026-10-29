"""홍보글 공장 — 학원 인스타그램 · 블로그 글을 만들어 주는 프로그램.

켜는 법:  python -m sns_maker   (자세한 내용은 sns_maker/README.md)
"""

import asyncio
import base64
import hashlib
import os
import secrets
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import catalog
from .ai import make_ai
from .cards import render_card, render_zip
from .generator import (GenerationError, check_post, generate_post, merge_profile, normalize_request,
                        revise_post, suggest_ideas)
from .storage import KST, Store

STATIC = Path(__file__).parent / "static"


class PostReq(BaseModel):
    request: dict


class ReviseReq(BaseModel):
    instruction: str


class DataReq(BaseModel):
    data: dict


class ProfileReq(BaseModel):
    profile: dict


class IdeasReq(BaseModel):
    count: int = 8


def _title(req: dict) -> str:
    return req["topic"][:60]


def create_app(db_path: Optional[str] = None, ai="auto", store=None,
               check_login: Optional[Callable[[str, str], bool]] = None) -> FastAPI:
    """store: 저장소(없으면 SQLite 파일). check_login(이름, 비밀번호): 학원 서버에 붙일 때
    관리자 계정으로 들어오게 하는 함수. 없으면 SNS_PASSWORD 환경 변수로 막는다."""
    if store is None:
        store = Store(db_path or os.environ.get("SNS_DB", str(Path.cwd() / "sns_maker.db")))
    if ai == "auto":
        ai = make_ai()
    password = os.environ.get("SNS_PASSWORD", "").strip()
    login_cache = {}
    jobs_sem = threading.Semaphore(2)

    app = FastAPI(title="홍보글 공장")
    app.state.store = store
    app.state.ai = ai

    # 인터넷에 올려 쓸 때는 비밀번호를 꼭 정한다. 아무나 들어와 AI 사용료를 쓰지 못하게.
    @app.middleware("http")
    async def check_password(request: Request, call_next):
        if password or check_login:
            ok = False
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("basic "):
                try:
                    user, _, given = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
                    if check_login:
                        key = hashlib.sha256(f"{user}\0{given}".encode()).hexdigest()
                        if login_cache.get(key, 0) > time.time():
                            ok = True
                        else:
                            ok = bool(await asyncio.to_thread(check_login, user.strip(), given))
                            if ok:
                                login_cache[key] = time.time() + 600
                    else:
                        ok = secrets.compare_digest(given, password)
                except Exception:
                    ok = False
            if not ok:
                return Response("비밀번호가 필요합니다.", status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="sns-maker", charset="UTF-8"'})
        return await call_next(request)

    def profile() -> dict:
        return merge_profile(store.get_setting("profile", {}))

    def today() -> str:
        return datetime.now(KST).strftime("%Y-%m-%d (%a)")

    def need_post(pid: int) -> dict:
        row = store.get_post(pid)
        if not row:
            raise HTTPException(404, "글을 찾을 수 없습니다.")
        return row

    # ── 글 쓰기 작업 (뒤에서 돌림) ─────────────────────
    def run_generate(pid: int, req: dict, prev=None):
        with jobs_sem:
            try:
                data = generate_post(app.state.ai, req, profile(), today())
                store.update_post(pid, status="done", data=data, prev=prev, error=None, progress="")
            except GenerationError as e:
                store.update_post(pid, status="error" if prev is None else "done", error=str(e), progress="")
            except Exception as e:
                traceback.print_exc()
                store.update_post(pid, status="error" if prev is None else "done", error=f"알 수 없는 오류: {e}",
                                  progress="")

    def run_revise(pid: int, instruction: str):
        row = store.get_post(pid)
        with jobs_sem:
            try:
                data = revise_post(app.state.ai, row["data"], instruction, row["request"], profile())
                store.update_post(pid, status="done", data=data, prev=row["data"], error=None, progress="")
            except Exception as e:
                if not isinstance(e, GenerationError):
                    traceback.print_exc()
                store.update_post(pid, status="done", error=str(e), progress="")

    def start(target, *args):
        threading.Thread(target=target, args=args, daemon=True).start()

    # ── 화면 ──────────────────────────────────────────
    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/meta")
    def meta():
        return {
            "channels": catalog.CHANNELS,
            "kinds": {k: {"name": v[0], "promo": v[2]} for k, v in catalog.KINDS.items()},
            "tones": {k: v[0] for k, v in catalog.TONES.items()},
            "audiences": catalog.AUDIENCES,
            "blog_lengths": {k: v[0] for k, v in catalog.BLOG_LENGTHS.items()},
            "themes": {k: {"name": catalog.THEME_NAMES[k], "colors": v} for k, v in catalog.THEMES.items()},
            "max_slides": catalog.MAX_SLIDES,
            "month_hint": catalog.MONTH_HINTS[datetime.now(KST).month],
            "ai": app.state.ai.name if app.state.ai else None,
        }

    # ── 학원 정보 ─────────────────────────────────────
    @app.get("/api/profile")
    def get_profile():
        return {"profile": profile()}

    @app.put("/api/profile")
    def put_profile(body: ProfileReq):
        p = merge_profile(body.profile)
        store.set_setting("profile", p)
        return {"profile": p}

    # ── 글 ────────────────────────────────────────────
    @app.post("/api/posts")
    def create_post(body: PostReq):
        if app.state.ai is None:
            raise HTTPException(400, "AI 키(GOOGLE_API_KEY)가 없습니다. 키를 넣고 다시 켜 주세요.")
        try:
            req = normalize_request(body.request)
        except GenerationError as e:
            raise HTTPException(400, str(e))
        pid = store.create_post(_title(req), req)
        start(run_generate, pid, req)
        return {"id": pid}

    @app.get("/api/posts")
    def list_posts():
        return {"posts": store.list_posts()}

    @app.get("/api/posts/{pid}")
    def get_post(pid: int):
        return {"post": need_post(pid)}

    @app.put("/api/posts/{pid}")
    def save_post(pid: int, body: DataReq):
        """손으로 고친 글을 저장한다. 살펴볼 점도 다시 단다."""
        row = need_post(pid)
        if row["status"] == "working":
            raise HTTPException(409, "AI가 아직 쓰는 중입니다.")
        data = {k: body.data[k] for k in ("instagram", "blog") if k in body.data}
        data["notes"] = check_post(data, row["request"], profile())
        store.update_post(pid, data=data, prev=row["data"], error=None)
        return {"post": store.get_post(pid)}

    @app.post("/api/posts/{pid}/revise")
    def revise(pid: int, body: ReviseReq):
        row = need_post(pid)
        if row["status"] != "done" or not row.get("data"):
            raise HTTPException(409, "다 만들어진 글만 고칠 수 있습니다.")
        if not body.instruction.strip():
            raise HTTPException(400, "어떻게 고칠지 적어주세요.")
        store.update_post(pid, status="working", progress="AI가 고치는 중…", error=None)
        start(run_revise, pid, body.instruction.strip())
        return {"ok": True}

    @app.post("/api/posts/{pid}/regenerate")
    def regenerate(pid: int):
        row = need_post(pid)
        if row["status"] == "working":
            raise HTTPException(409, "AI가 아직 쓰는 중입니다.")
        store.update_post(pid, status="working", progress="AI가 새로 쓰는 중…", error=None)
        start(run_generate, pid, row["request"], row.get("data"))
        return {"ok": True}

    @app.post("/api/posts/{pid}/undo")
    def undo(pid: int):
        row = need_post(pid)
        if not row.get("prev"):
            raise HTTPException(400, "되돌릴 것이 없습니다.")
        store.update_post(pid, data=row["prev"], prev=row["data"], error=None)
        return {"post": store.get_post(pid)}

    @app.delete("/api/posts/{pid}")
    def delete_post(pid: int):
        store.delete_post(pid)
        return {"ok": True}

    # ── 카드뉴스 그림 ─────────────────────────────────
    def slides_of(pid: int) -> list:
        row = need_post(pid)
        slides = ((row.get("data") or {}).get("instagram") or {}).get("slides") or []
        if not slides:
            raise HTTPException(404, "카드뉴스가 없습니다.")
        return slides

    def theme_of(theme: str) -> str:
        return theme if theme in catalog.THEMES else profile()["theme"]

    @app.get("/api/posts/{pid}/cards/{n}.png")
    def card_png(pid: int, n: int, theme: str = ""):
        slides = slides_of(pid)
        if not 0 <= n < len(slides):
            raise HTTPException(404, "그런 장이 없습니다.")
        png = render_card(slides[n], n, len(slides), profile()["name"], theme_of(theme))
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/posts/{pid}/cards.zip")
    def cards_zip(pid: int, theme: str = ""):
        z = render_zip(slides_of(pid), profile()["name"], theme_of(theme))
        return Response(z, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="cardnews_{pid}.zip"'})

    # ── 올릴 거리 추천 ────────────────────────────────
    @app.post("/api/ideas")
    async def ideas(body: IdeasReq):
        recent = [p["title"] for p in store.list_posts(30)]
        try:
            items = await asyncio.to_thread(suggest_ideas, app.state.ai, profile(), datetime.now(KST),
                                            recent, max(3, min(15, body.count)))
        except GenerationError as e:
            raise HTTPException(400, str(e))
        return {"ideas": items}

    @app.exception_handler(Exception)
    async def on_error(request: Request, exc: Exception):
        traceback.print_exc()
        return JSONResponse({"detail": f"서버 오류: {exc}"}, status_code=500)

    return app
