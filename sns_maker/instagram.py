"""인스타그램에 올리기.

메타가 여는 길이 두 가지라 둘 다 받는다. 올리는 방법(컨테이너 → 게시)은 똑같다.
- Instagram 로그인 (기본): graph.instagram.com. 접속 키는 60일짜리라 일주일마다 새로 받아 둔다.
- Facebook 로그인: graph.facebook.com. 인스타 계정이 페이스북 페이지에 연결돼 있어야 하고,
  INSTAGRAM_USER_ID(인스타 비즈니스 계정 번호)를 꼭 넣는다. 오래 가는 페이지 접속 키는 끊기지 않는다.

준비: 학원 인스타 계정을 프로페셔널(비즈니스 · 크리에이터) 계정으로 바꾸고, 메타 앱에서 받은
접속 키를 INSTAGRAM_ACCESS_TOKEN 환경 변수에 넣는다 (자세한 순서는 README).

올리는 순서 (메타가 정한 방식):
1. 그림마다 '올릴 준비 상자(컨테이너)'를 만든다. 인스타그램이 그림 주소로 직접 가져간다.
2. 여러 장이면 그 상자들을 묶은 캐러셀 상자를 하나 더 만든다.
3. 상자가 준비될 때까지(FINISHED) 기다렸다가 게시한다.
"""

import hashlib
import os
import time

API_HOST = "https://graph.instagram.com"       # Instagram 로그인 (INSTAGRAM_API_HOST로 바꿀 수 있음)
FACEBOOK_HOST = "graph.facebook.com"
API_VERSION = "v23.0"          # 메타가 버전을 올리면 여기만 바꾼다
TOKEN_KEY = "instagram_token"  # 새로 받은 접속 키를 저장해 두는 설정 이름
REFRESH_EVERY = 7 * 86400      # 접속 키는 60일짜리다. 일주일마다 새로 받아 둔다
MAX_CAPTION = 2200
MAX_TAGS = 30
MAX_IMAGES = 10


class InstagramError(Exception):
    pass


def friendly_error(err: dict, status: int = 0) -> str:
    """메타가 준 오류를 원장님이 알아볼 말로."""
    err = err or {}
    code, sub = err.get("code"), err.get("error_subcode")
    msg = str(err.get("error_user_msg") or err.get("message") or "").strip()
    low = msg.lower()
    if code == 190 or "access token" in low or "session has expired" in low:
        head = "인스타그램 접속 키가 없거나 만료됐습니다. 메타 앱에서 접속 키를 새로 받아 INSTAGRAM_ACCESS_TOKEN에 넣어 주세요."
    elif code in (10, 200) or "permission" in low:
        head = "인스타그램에 글을 올릴 권한이 없습니다. 접속 키를 만들 때 '콘텐츠 게시(content_publish)' 권한을 허용했는지 확인해 주세요."
    elif code == 9 or sub == 2207042 or code in (4, 17, 32, 613) or status == 429:
        head = "인스타그램이 정한 횟수를 넘었습니다(하루 50개). 잠시 뒤에 다시 올려 주세요."
    elif sub in (2207052, 2207003, 2207020) or "download" in low or "fetch" in low:
        head = "인스타그램이 카드 그림을 가져가지 못했습니다. 학원 서버가 깨어 있는지 확인하고 다시 올려 주세요."
    elif "professional" in low or "business" in low:
        head = "학원 인스타 계정이 프로페셔널(비즈니스 · 크리에이터) 계정이어야 올릴 수 있습니다. 인스타 앱 설정에서 바꿔 주세요."
    elif sub == 2207009 or "aspect ratio" in low:
        head = "인스타그램이 받지 않는 그림 비율입니다."
    else:
        return "인스타그램에 올리지 못했습니다: " + (msg[:300] or f"알 수 없는 오류 ({status})")
    return head + (f"\n(인스타그램 오류: {msg[:200]})" if msg else "")


def _requests_http(method: str, url: str, params: dict):
    """실제로 메타에 묻는 부분. (상태 번호, JSON)을 돌려준다."""
    import requests
    if method == "GET":
        r = requests.get(url, params=params, timeout=30)
    else:
        r = requests.post(url, data=params, timeout=60)
    try:
        body = r.json()
    except ValueError:
        body = {}
    return r.status_code, body


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


class InstagramClient:
    def __init__(self, store, env_token: str = "", user_id: str = "", http=None,
                 sleep=time.sleep, clock=time.time, host: str = API_HOST):
        self.store = store
        host = (host or API_HOST).strip().rstrip("/")
        self.host = host if host.startswith("http") else "https://" + host
        self.facebook = FACEBOOK_HOST in self.host
        self.env_token = (env_token or "").strip().strip('"').strip("'")
        self.user_id = (user_id or "").strip()
        self.username = ""
        self.http = http or _requests_http
        self.sleep, self.clock = sleep, clock

    # ── 접속 키 ───────────────────────────────────────
    def _saved(self) -> dict:
        saved = self.store.get_setting(TOKEN_KEY, {}) or {}
        # 원장님이 서버에 새 접속 키를 넣었다면 예전에 저장한 키 대신 새 키를 쓴다
        if saved.get("token") and saved.get("base") == _hash(self.env_token):
            return saved
        return {}

    def token(self) -> str:
        return self._saved().get("token") or self.env_token

    @property
    def configured(self) -> bool:
        return bool(self.token())

    def maybe_refresh(self, force: bool = False) -> bool:
        """일주일이 지났으면 접속 키를 새로 받아 저장한다. 실패해도 지금 키로 계속 쓴다."""
        if not self.env_token or self.facebook:   # 페이스북 길에는 이 새로 받기가 없다(페이지 키는 끊기지 않음)
            return False
        saved = self._saved()
        last = saved.get("refreshed_at", 0)
        if not saved:
            # 처음 보는 접속 키: 받은 때를 모르니 지금부터 센다 (받은 지 하루가 안 된 키는 새로 받을 수 없다)
            self.store.set_setting(TOKEN_KEY, {"token": self.env_token, "base": _hash(self.env_token),
                                               "refreshed_at": self.clock()})
            if not force:
                return False
            last = 0
        if not force and self.clock() - last < REFRESH_EVERY:
            return False
        status, body = self.http("GET", f"{self.host}/refresh_access_token",
                                 {"grant_type": "ig_refresh_token", "access_token": self.token()})
        new = (body or {}).get("access_token")
        if status != 200 or not new:
            return False
        self.store.set_setting(TOKEN_KEY, {"token": new, "base": _hash(self.env_token),
                                           "refreshed_at": self.clock(),
                                           "expires_in": (body or {}).get("expires_in")})
        return True

    # ── 메타에 묻기 ───────────────────────────────────
    def _call(self, method: str, path: str, **params) -> dict:
        token = self.token()
        if not token:
            raise InstagramError("인스타그램 접속 키가 없습니다. 학원 서버에 INSTAGRAM_ACCESS_TOKEN을 넣어 주세요.")
        try:
            status, body = self.http(method, f"{self.host}/{API_VERSION}/{path.lstrip('/')}",
                                     dict(params, access_token=token))
        except Exception as e:   # 연결 끊김 · 시간 초과
            raise InstagramError(f"인스타그램에 연결하지 못했습니다. 잠시 뒤 다시 해 주세요. ({type(e).__name__})")
        body = body or {}
        if status >= 400 or "error" in body:
            raise InstagramError(friendly_error(body.get("error"), status))
        return body

    def account(self) -> dict:
        """연결된 인스타 계정 (번호 · 아이디)."""
        if self.facebook:
            # 페이스북 길에서 'me'는 페이스북 사용자다. 인스타 계정 번호는 따로 받아야 한다
            if not self.user_id:
                raise InstagramError("페이스북 로그인 방식에서는 INSTAGRAM_USER_ID(인스타 비즈니스 계정 번호)를 넣어야 합니다.")
            if not self.username:
                self.username = self._call("GET", self.user_id, fields="username").get("username", "")
        elif not (self.user_id and self.username):
            me = self._call("GET", "me", fields="user_id,username")
            self.user_id = self.user_id or str(me.get("user_id") or me.get("id") or "")
            self.username = me.get("username", "")
        if not self.user_id:
            raise InstagramError("인스타 계정 번호를 알 수 없습니다. INSTAGRAM_USER_ID를 넣어 주세요.")
        return {"user_id": self.user_id, "username": self.username}

    def _wait(self, container_id: str, timeout: float = 120):
        end = self.clock() + timeout
        while True:
            st = self._call("GET", container_id, fields="status_code,status").get("status_code", "")
            if st in ("FINISHED", "PUBLISHED"):
                return
            if st in ("ERROR", "EXPIRED"):
                raise InstagramError("인스타그램이 카드 그림을 처리하지 못했습니다(" + st + "). 다시 올려 주세요.")
            if self.clock() >= end:
                raise InstagramError("인스타그램이 그림을 처리하는 데 너무 오래 걸립니다. 잠시 뒤 다시 올려 주세요.")
            self.sleep(3)

    # ── 올리기 ────────────────────────────────────────
    def publish(self, image_urls: list, caption: str, progress=lambda msg: None) -> dict:
        if not image_urls:
            raise InstagramError("올릴 카드뉴스 그림이 없습니다.")
        if len(image_urls) > MAX_IMAGES:
            raise InstagramError(f"인스타그램은 한 번에 {MAX_IMAGES}장까지만 올릴 수 있습니다.")
        self.maybe_refresh()
        uid = self.account()["user_id"]
        caption = caption[:MAX_CAPTION]
        if len(image_urls) == 1:
            progress("인스타그램이 그림을 가져가는 중…")
            container = self._call("POST", f"{uid}/media", image_url=image_urls[0], caption=caption)["id"]
        else:
            children = []
            for i, url in enumerate(image_urls):
                progress(f"인스타그램이 그림을 가져가는 중… ({i + 1}/{len(image_urls)})")
                cid = self._call("POST", f"{uid}/media", image_url=url, is_carousel_item="true")["id"]
                self._wait(cid)
                children.append(cid)
            progress("카드뉴스를 한 게시물로 묶는 중…")
            container = self._call("POST", f"{uid}/media", media_type="CAROUSEL",
                                   children=",".join(children), caption=caption)["id"]
        self._wait(container)
        progress("게시하는 중…")
        media_id = self._call("POST", f"{uid}/media_publish", creation_id=container)["id"]
        try:
            permalink = self._call("GET", media_id, fields="permalink").get("permalink", "")
        except InstagramError:
            permalink = ""   # 올리기는 끝났다. 주소만 못 받았을 뿐
        return {"media_id": media_id, "permalink": permalink}


def build_caption(ig: dict) -> str:
    """본문 + 해시태그(30개까지). 전체 2,200자를 넘으면 본문을 줄인다."""
    tags = " ".join((ig.get("hashtags") or [])[:MAX_TAGS])
    body = (ig.get("caption") or "").rstrip()
    room = MAX_CAPTION - (len(tags) + 2 if tags else 0)
    if len(body) > room:
        body = body[:max(0, room - 1)].rstrip() + "…"
    return body + ("\n\n" + tags if tags else "")


def make_client(store):
    """환경 변수로 만든다. 접속 키가 없으면 None."""
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not token:
        return None
    return InstagramClient(store, token, os.environ.get("INSTAGRAM_USER_ID", ""),
                           host=os.environ.get("INSTAGRAM_API_HOST", "") or API_HOST)
