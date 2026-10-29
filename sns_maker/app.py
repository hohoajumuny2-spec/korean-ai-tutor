"""홍보글 공장 — 학원 인스타그램 · 블로그 글을 만들어 주는 프로그램.

켜는 법:  python -m sns_maker   (자세한 내용은 sns_maker/README.md)
"""

import asyncio
import hashlib
import hmac
import io
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
from question_maker.login import install_login

from .ai import make_ai
from .cards import render_card, render_zip
from .generator import (GenerationError, check_post, generate_post, merge_profile, normalize_request,
                        revise_post, suggest_ideas)
from .instagram import InstagramError, build_caption, make_client
from .storage import KST, Store, now_str

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
    subject: str = ""


class PublishReq(BaseModel):
    theme: str = ""
    force: bool = False   # 이미 올린 글을 한 번 더 올릴 때


def _title(req: dict) -> str:
    return req["topic"][:60]


def create_app(db_path: Optional[str] = None, ai="auto", store=None,
               check_login: Optional[Callable[[str, str], bool]] = None,
               check_token: Optional[Callable[[str], bool]] = None,
               public_url: Optional[str] = None, instagram="auto") -> FastAPI:
    """store: 저장소(없으면 SQLite 파일). check_login(이름, 비밀번호): 학원 서버에 붙일 때
    관리자 계정으로 들어오게 하는 함수. 없으면 SNS_PASSWORD 환경 변수로 막는다.
    public_url: 인스타그램이 카드 그림을 가져갈 이 프로그램의 https 주소 (예: https://학원서버/sns).
    instagram: 인스타그램 올리기 (기본은 INSTAGRAM_ACCESS_TOKEN 환경 변수로 만든다)."""
    if store is None:
        store = Store(db_path or os.environ.get("SNS_DB", str(Path.cwd() / "sns_maker.db")))
    if ai == "auto":
        ai = make_ai()
    password = os.environ.get("SNS_PASSWORD", "").strip()
    jobs_sem = threading.Semaphore(2)
    public_url = (public_url or os.environ.get("SNS_PUBLIC_URL", "")).strip().rstrip("/")
    refresher = instagram == "auto"
    if instagram == "auto":
        instagram = make_client(store)

    app = FastAPI(title="홍보글 공장")
    app.state.store = store
    app.state.ai = ai
    app.state.instagram = instagram

    # 인터넷에 올려 쓸 때는 비밀번호를 꼭 정한다. 아무나 들어와 AI 사용료를 쓰지 못하게.
    # 카드 그림 공개 주소는 인스타그램이 가져가야 하므로 막지 않는다 (서명이 맞아야만 열린다).
    install_login(app, realm="sns-maker", password=password, check_login=check_login, check_token=check_token,
                  open_parts=("/public/cards/",))

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

    # ── 인스타그램에 올리기 ───────────────────────────
    def card_secret() -> bytes:
        key = store.get_setting("card_secret")
        if not key:
            key = secrets.token_hex(32)
            store.set_setting("card_secret", key)
        return key.encode()

    def card_sig(pid: int, n: int, theme: str) -> str:
        return hmac.new(card_secret(), f"{pid}:{n}:{theme}".encode(), hashlib.sha256).hexdigest()

    def ig_state(row: dict) -> dict:
        ig = dict(row.get("instagram") or {})
        # 올리는 도중 서버가 다시 켜졌다면 '올리는 중'이 영영 끝나지 않는다
        if ig.get("status") == "working" and time.time() - ig.get("started", 0) > 600:
            ig.update(status="error", error="올리는 도중 끊겼습니다. 인스타그램에 올라갔는지 확인한 뒤 다시 올려 주세요.")
        return ig

    def run_publish(pid: int, theme: str):
        row = store.get_post(pid)
        ig = row["data"]["instagram"]
        state = {"status": "working", "started": time.time(), "at": now_str(), "progress": ""}

        def progress(msg):
            state["progress"] = msg
            store.update_post(pid, instagram=dict(state))
        try:
            urls = [f"{public_url}/public/cards/{pid}/{n}.jpg?theme={theme}&sig={card_sig(pid, n, theme)}"
                    for n in range(len(ig["slides"]))]
            done = app.state.instagram.publish(urls, build_caption(ig), progress)
            store.update_post(pid, instagram={"status": "done", "at": now_str(), "theme": theme, **done})
        except InstagramError as e:
            store.update_post(pid, instagram={"status": "error", "at": now_str(), "error": str(e)})
        except Exception as e:
            traceback.print_exc()
            store.update_post(pid, instagram={"status": "error", "at": now_str(), "error": f"알 수 없는 오류: {e}"})

    if refresher and instagram:
        # 접속 키는 60일이 지나면 끊긴다. 하루 한 번 살펴 일주일마다 새로 받는다.
        def keep_token_fresh():
            while True:
                try:
                    instagram.maybe_refresh()
                except Exception:
                    pass
                time.sleep(86400)
        threading.Thread(target=keep_token_fresh, daemon=True).start()

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
            "instagram": bool(app.state.instagram and app.state.instagram.configured),
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
        row = need_post(pid)
        row["instagram"] = ig_state(row)
        return {"post": row}

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
    def slides_of(pid: int):
        """카드 목록과, 카드 아래에 적을 이름(학원 이름 · 과목)."""
        row = need_post(pid)
        slides = ((row.get("data") or {}).get("instagram") or {}).get("slides") or []
        if not slides:
            raise HTTPException(404, "카드뉴스가 없습니다.")
        subject = (row.get("request") or {}).get("subject", "")
        label = " · ".join(x for x in (profile()["name"], subject) if x)
        return slides, label

    def theme_of(theme: str) -> str:
        return theme if theme in catalog.THEMES else profile()["theme"]

    @app.get("/api/posts/{pid}/cards/{n}.png")
    def card_png(pid: int, n: int, theme: str = ""):
        slides, label = slides_of(pid)
        if not 0 <= n < len(slides):
            raise HTTPException(404, "그런 장이 없습니다.")
        png = render_card(slides[n], n, len(slides), label, theme_of(theme))
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/posts/{pid}/cards.zip")
    def cards_zip(pid: int, theme: str = ""):
        slides, label = slides_of(pid)
        z = render_zip(slides, label, theme_of(theme))
        return Response(z, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="cardnews_{pid}.zip"'})

    @app.get("/public/cards/{pid}/{n}.jpg")
    def card_public_jpg(pid: int, n: int, sig: str = "", theme: str = ""):
        """인스타그램이 가져갈 카드 그림. 로그인 없이 열리므로 서명이 맞을 때만 준다."""
        if not hmac.compare_digest(sig, card_sig(pid, n, theme)):
            raise HTTPException(403, "주소가 맞지 않습니다.")
        slides, label = slides_of(pid)
        if not 0 <= n < len(slides):
            raise HTTPException(404, "그런 장이 없습니다.")
        png = render_card(slides[n], n, len(slides), label, theme_of(theme))
        from PIL import Image   # 인스타그램은 JPEG만 받는다
        buf = io.BytesIO()
        Image.open(io.BytesIO(png)).convert("RGB").save(buf, "JPEG", quality=92)
        return Response(buf.getvalue(), media_type="image/jpeg")

    @app.get("/api/instagram")
    async def instagram_info():
        """인스타그램 연결 상태. 접속 키는 절대 돌려주지 않는다."""
        ig = app.state.instagram
        if not (ig and ig.configured):
            return {"configured": False}
        try:
            acc = await asyncio.to_thread(ig.account)
            return {"configured": True, "username": acc.get("username", "")}
        except InstagramError as e:
            return {"configured": True, "error": str(e)}

    @app.post("/api/posts/{pid}/instagram/publish")
    def publish_instagram(pid: int, body: PublishReq):
        if not (app.state.instagram and app.state.instagram.configured):
            raise HTTPException(400, "학원 서버에 INSTAGRAM_ACCESS_TOKEN을 넣어야 올릴 수 있습니다.")
        if not public_url:
            raise HTTPException(400, "이 프로그램의 공개 주소(SNS_PUBLIC_URL)를 몰라 인스타그램이 그림을 가져갈 수 없습니다.")
        row = need_post(pid)
        if row["status"] == "working":
            raise HTTPException(409, "AI가 아직 쓰는 중입니다.")
        ig = (row.get("data") or {}).get("instagram")
        if not ig or not ig.get("slides"):
            raise HTTPException(400, "인스타그램 카드뉴스가 없는 글입니다.")
        state = ig_state(row)
        if state.get("status") == "working":
            raise HTTPException(409, "지금 올리는 중입니다.")
        if state.get("status") == "done" and not body.force:
            raise HTTPException(409, "이미 인스타그램에 올린 글입니다.")
        theme = theme_of(body.theme)
        store.update_post(pid, instagram={"status": "working", "started": time.time(), "at": now_str(),
                                          "progress": "올릴 준비 중…"})
        start(run_publish, pid, theme)
        return {"ok": True}

    # ── 올릴 거리 추천 ────────────────────────────────
    @app.post("/api/ideas")
    async def ideas(body: IdeasReq):
        recent = [p["title"] for p in store.list_posts(30)]
        try:
            items = await asyncio.to_thread(suggest_ideas, app.state.ai, profile(), datetime.now(KST),
                                            recent, max(3, min(15, body.count)), body.subject)
        except GenerationError as e:
            raise HTTPException(400, str(e))
        return {"ideas": items}

    @app.exception_handler(Exception)
    async def on_error(request: Request, exc: Exception):
        traceback.print_exc()
        return JSONResponse({"detail": f"서버 오류: {exc}"}, status_code=500)

    return app
