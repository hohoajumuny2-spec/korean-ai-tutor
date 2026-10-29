"""문제 공장 · 홍보글 공장이 함께 쓰는 로그인 확인.

들어오는 길은 세 가지다.
1. 학원 앱 관리자 화면의 버튼: 이미 로그인한 관리자 토큰을 POST /login 으로 보내면
   쿠키에 담아 두고 바로 들여보낸다. 비밀번호를 다시 칠 필요가 없다.
2. 브라우저 로그인 창(Basic 인증): 관리자 이름 · 비밀번호 (check_login) 또는 환경 변수 비밀번호.
3. 막지 않는 주소(open_paths): 매일 출제 깨우기처럼 정해진 일만 하는 곳.
"""

import asyncio
import base64
import hashlib
import secrets
import time
from typing import Callable, Iterable, Optional
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

COOKIE = "admin_session"
COOKIE_DAYS = 30


def install_login(app: FastAPI, *, realm: str, password: str = "",
                  check_login: Optional[Callable[[str, str], bool]] = None,
                  check_token: Optional[Callable[[str], bool]] = None,
                  open_paths: Iterable[str] = (), open_parts: Iterable[str] = ()):
    open_paths, open_parts = tuple(open_paths), tuple(open_parts)
    cache = {}   # 같은 사람이 요청마다 DB를 거치지 않게 10분간 기억

    async def remembered(key: str, check, *args) -> bool:
        if cache.get(key, 0) > time.time():
            return True
        ok = bool(await asyncio.to_thread(check, *args))
        if ok:
            cache[key] = time.time() + 600
        return ok

    async def token_ok(token: str) -> bool:
        if not (check_token and token):
            return False
        return await remembered("t:" + hashlib.sha256(token.encode()).hexdigest(), check_token, token)

    @app.middleware("http")
    async def check_password(request: Request, call_next):
        path = request.url.path
        if path.endswith(open_paths) or any(p in path for p in open_parts):
            return await call_next(request)
        if not (password or check_login or check_token):
            return await call_next(request)

        # 학원 앱에서 버튼으로 넘어올 때
        if request.method == "POST" and path.rstrip("/").endswith("/login"):
            body = (await request.body()).decode("utf-8", "replace")
            token = (parse_qs(body).get("token") or [""])[0].strip()
            if not await token_ok(token):
                return HTMLResponse("<meta charset='utf-8'><p style='font:16px sans-serif;padding:24px'>"
                                    "로그인 정보가 만료되었습니다. 학원 앱에서 관리자로 다시 로그인한 뒤 버튼을 눌러 주세요.</p>",
                                    status_code=401)
            resp = RedirectResponse("./", status_code=303)
            https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
            resp.set_cookie(COOKIE, token, max_age=COOKIE_DAYS * 86400, path="/", httponly=True,
                            secure=https, samesite="lax")
            return resp

        if await token_ok(request.cookies.get(COOKIE, "")):
            return await call_next(request)

        ok = False
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                user, _, given = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
                if check_login:
                    key = "p:" + hashlib.sha256(f"{user}\0{given}".encode()).hexdigest()
                    ok = await remembered(key, check_login, user.strip(), given.strip())
                elif password:
                    ok = secrets.compare_digest(given, password)
            except Exception:
                ok = False
        if not ok:
            return Response("비밀번호가 필요합니다. 학원 앱 관리자 화면의 버튼으로 들어오면 비밀번호 없이 열립니다.",
                            status_code=401, media_type="text/plain; charset=utf-8",
                            headers={"WWW-Authenticate": f'Basic realm="{realm}", charset="UTF-8"'})
        return await call_next(request)
