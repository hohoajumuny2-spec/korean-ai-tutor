import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from sns_maker.ai import FakeAI
from sns_maker.app import create_app
from sns_maker.instagram import (API_VERSION, TOKEN_KEY, InstagramClient, InstagramError, build_caption,
                                 friendly_error)
from sns_maker.storage import Store


class FakeMeta:
    """메타 서버 흉내. 받은 요청을 적어 두고, 정해 둔 답을 준다."""

    def __init__(self, status_seq=("IN_PROGRESS", "FINISHED"), fail=None):
        self.calls = []
        self.hosts = set()
        self.status_seq = list(status_seq)
        self.polls = {}
        self.fail = fail          # (경로 일부, 오류 dict)
        self.n = 0

    def __call__(self, method, url, params):
        path = urlparse(url).path
        self.hosts.add(urlparse(url).netloc)
        self.calls.append((method, path, dict(params)))
        if self.fail and self.fail[0] in path:
            return 400, {"error": self.fail[1]}
        if path.endswith("/refresh_access_token"):
            return 200, {"access_token": "NEW-TOKEN", "expires_in": 5184000}
        if path.endswith("/me"):
            return 200, {"user_id": "1784", "username": "logyedu"}
        if path.endswith("/media") and method == "POST":
            self.n += 1
            return 200, {"id": f"c{self.n}"}
        if path.endswith("/media_publish"):
            return 200, {"id": "m1"}
        if path.endswith("/m1"):
            return 200, {"permalink": "https://www.instagram.com/p/abc/"}
        cid = path.rsplit("/", 1)[-1]
        i = self.polls.get(cid, 0)
        self.polls[cid] = i + 1
        return 200, {"status_code": self.status_seq[min(i, len(self.status_seq) - 1)]}

    def posts(self, suffix):
        return [p for m, path, p in self.calls if m == "POST" and path.endswith(suffix)]


def client(tmp_path, meta, **kw):
    return InstagramClient(Store(str(tmp_path / "ig.db")), "ENV-TOKEN", http=meta, sleep=lambda s: None, **kw)


def test_carousel_flow(tmp_path):
    meta = FakeMeta()
    c = client(tmp_path, meta)
    steps = []
    out = c.publish(["https://x/0.jpg", "https://x/1.jpg", "https://x/2.jpg"], "본문", steps.append)
    assert out == {"media_id": "m1", "permalink": "https://www.instagram.com/p/abc/"}
    media = meta.posts("/media")
    assert [m.get("is_carousel_item") for m in media[:3]] == ["true"] * 3
    assert media[3]["media_type"] == "CAROUSEL" and media[3]["children"] == "c1,c2,c3"
    assert media[3]["caption"] == "본문" and "caption" not in media[0]
    assert meta.posts("/media_publish") == [{"creation_id": "c4", "access_token": "ENV-TOKEN"}]
    assert all(f"/{API_VERSION}/" in path for _, path, _ in meta.calls if "refresh" not in path)
    assert meta.hosts == {"graph.instagram.com"}
    assert any("게시" in s for s in steps)


def test_single_image_flow_and_user_id_from_env(tmp_path):
    meta = FakeMeta(status_seq=("FINISHED",))
    c = client(tmp_path, meta, user_id="999")
    c.publish(["https://x/0.jpg"], "글")
    media = meta.posts("/media")
    assert len(media) == 1 and media[0]["image_url"] == "https://x/0.jpg" and media[0]["caption"] == "글"
    assert all("/999/" in path for m, path, _ in meta.calls if m == "POST")


def test_container_error_and_timeout(tmp_path):
    with pytest.raises(InstagramError, match="ERROR"):
        client(tmp_path, FakeMeta(status_seq=("ERROR",))).publish(["u"], "c")
    now = [0.0]

    def clock():
        now[0] += 50
        return now[0]
    c = InstagramClient(Store(str(tmp_path / "t.db")), "T", user_id="1", http=FakeMeta(status_seq=("IN_PROGRESS",)),
                        sleep=lambda s: None, clock=clock)
    with pytest.raises(InstagramError, match="오래"):
        c.publish(["u"], "c")


def test_friendly_errors(tmp_path):
    assert "만료" in friendly_error({"code": 190, "message": "Error validating access token"})
    assert "권한" in friendly_error({"code": 10, "message": "Application does not have permission"})
    assert "횟수" in friendly_error({"code": 9, "error_subcode": 2207042, "message": "limit"})
    assert "그림을 가져가지" in friendly_error({"code": 9004, "error_subcode": 2207052, "message": "Media download has failed"})
    assert "모르는" not in friendly_error({"message": "뭔가 이상함"})
    meta = FakeMeta(fail=("/media", {"code": 190, "message": "Error validating access token"}))
    with pytest.raises(InstagramError, match="만료"):
        client(tmp_path, meta).publish(["u"], "c")


def test_token_refresh_is_saved_and_new_env_token_wins(tmp_path):
    store = Store(str(tmp_path / "r.db"))
    meta = FakeMeta()
    now = [1000.0]
    c = InstagramClient(store, "ENV-TOKEN", user_id="1", http=meta, sleep=lambda s: None, clock=lambda: now[0])
    assert c.maybe_refresh() is False                  # 처음 본 키: 시각만 적어 둔다
    assert store.get_setting(TOKEN_KEY)["token"] == "ENV-TOKEN"
    now[0] += 3 * 86400
    assert c.maybe_refresh() is False                  # 일주일이 안 됐다
    now[0] += 5 * 86400
    assert c.maybe_refresh() is True and c.token() == "NEW-TOKEN"
    refresh = [p for m, path, p in meta.calls if path.endswith("/refresh_access_token")]
    assert refresh == [{"grant_type": "ig_refresh_token", "access_token": "ENV-TOKEN"}]
    # 원장님이 서버에 새 키를 넣으면 저장해 둔 키 대신 그 키를 쓴다
    c2 = InstagramClient(store, "OTHER-ENV", user_id="1", http=meta)
    assert c2.token() == "OTHER-ENV"


def test_facebook_host(tmp_path):
    meta = FakeMeta(status_seq=("FINISHED",))
    store = Store(str(tmp_path / "f.db"))
    with pytest.raises(InstagramError, match="INSTAGRAM_USER_ID"):
        InstagramClient(store, "PAGE", http=meta, host="graph.facebook.com").account()
    c = InstagramClient(store, "PAGE", user_id="1784", http=meta, sleep=lambda s: None, host="graph.facebook.com")
    assert c.maybe_refresh(force=True) is False        # 페이스북 길에는 새로 받기가 없다
    c.publish(["u"], "c")
    assert meta.hosts == {"graph.facebook.com"}
    assert not any(path.endswith("/me") or "refresh" in path for _, path, _ in meta.calls)


def test_build_caption_limits():
    cap = build_caption({"caption": "가" * 3000, "hashtags": [f"#t{i}" for i in range(40)]})
    assert len(cap) <= 2200 and cap.endswith("#t29") and "#t30" not in cap
    assert build_caption({"caption": "글", "hashtags": []}) == "글"


# ── 학원 서버에 붙은 모습으로 ──────────────────────────
class FakeIG:
    configured = True

    def __init__(self, fail=None):
        self.fail, self.got = fail, None

    def account(self):
        return {"user_id": "1", "username": "logyedu"}

    def publish(self, urls, caption, progress=lambda m: None):
        self.got = (urls, caption)
        progress("게시하는 중…")
        if self.fail:
            raise InstagramError(self.fail)
        return {"media_id": "m1", "permalink": "https://www.instagram.com/p/abc/"}


def wait_ig(c, pid):
    end = time.time() + 5
    while time.time() < end:
        post = c.get(f"/api/posts/{pid}").json()["post"]
        if post["instagram"].get("status") != "working":
            return post
        time.sleep(0.05)
    raise AssertionError("끝나지 않음")


def make_post(c):
    pid = c.post("/api/posts", json={"request": {"channels": ["instagram"], "topic": "오답 노트", "slide_count": 3}}).json()["id"]
    end = time.time() + 5
    while c.get(f"/api/posts/{pid}").json()["post"]["status"] == "working" and time.time() < end:
        time.sleep(0.05)
    return pid


def test_publish_endpoint_lifecycle(tmp_path):
    ig = FakeIG()
    app = create_app(ai=FakeAI(), store=Store(str(tmp_path / "a.db")), public_url="https://school.example/sns",
                     instagram=ig)
    c = TestClient(app)
    assert c.get("/api/meta").json()["instagram"] is True
    assert c.get("/api/instagram").json() == {"configured": True, "username": "logyedu"}
    pid = make_post(c)
    assert c.post(f"/api/posts/{pid}/instagram/publish", json={"theme": "pink"}).status_code == 200
    post = wait_ig(c, pid)
    assert post["instagram"]["status"] == "done" and post["instagram"]["permalink"].endswith("/abc/")
    urls, caption = ig.got
    assert len(urls) == 3 and all(u.startswith(f"https://school.example/sns/public/cards/{pid}/") for u in urls)
    assert "theme=pink" in urls[0] and "#" in caption
    assert c.get("/api/posts").json()["posts"][0]["instagram"] == "done"
    # 이미 올린 글은 force 없이 다시 안 올린다
    assert c.post(f"/api/posts/{pid}/instagram/publish", json={}).status_code == 409
    assert c.post(f"/api/posts/{pid}/instagram/publish", json={"force": True}).status_code == 200
    wait_ig(c, pid)

    # 공개 그림 주소: 서명이 맞아야 JPEG를 준다
    path = urlparse(urls[1])
    r = c.get(path.path.replace("/sns", "", 1) + "?" + path.query)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    bad = parse_qs(path.query)
    assert c.get(path.path.replace("/sns", "", 1) + f"?theme={bad['theme'][0]}&sig=00").status_code == 403
    assert c.get(path.path.replace("/sns", "", 1).replace("/1.jpg", "/2.jpg") + "?" + path.query).status_code == 403


def test_publish_errors_and_not_configured(tmp_path):
    c = TestClient(create_app(ai=FakeAI(), store=Store(str(tmp_path / "b.db")), public_url="https://s/sns",
                              instagram=FakeIG(fail="인스타그램이 정한 횟수를 넘었습니다")))
    pid = make_post(c)
    c.post(f"/api/posts/{pid}/instagram/publish", json={})
    post = wait_ig(c, pid)
    assert post["instagram"]["status"] == "error" and "횟수" in post["instagram"]["error"]

    off = TestClient(create_app(ai=FakeAI(), store=Store(str(tmp_path / "c.db")), instagram=None))
    assert off.get("/api/meta").json()["instagram"] is False
    assert off.get("/api/instagram").json() == {"configured": False}
    pid = make_post(off)
    assert off.post(f"/api/posts/{pid}/instagram/publish", json={}).status_code == 400

    blog_only = TestClient(create_app(ai=FakeAI(), store=Store(str(tmp_path / "d.db")), public_url="https://s/sns",
                                      instagram=FakeIG()))
    pid = blog_only.post("/api/posts", json={"request": {"channels": ["blog"], "topic": "x"}}).json()["id"]
    time.sleep(0.3)
    assert blog_only.post(f"/api/posts/{pid}/instagram/publish", json={}).status_code == 400


def test_public_cards_open_without_login_but_api_locked(tmp_path):
    from fastapi import FastAPI
    ig = FakeIG()
    inner = create_app(ai=FakeAI(), store=Store(str(tmp_path / "e.db")), public_url="https://s/sns", instagram=ig,
                       check_login=lambda u, p: p == "pw", check_token=lambda t: False)
    parent = FastAPI()
    parent.mount("/sns", inner)
    c = TestClient(parent)
    auth = ("원장님", "pw")
    pid = c.post("/sns/api/posts", auth=auth,
                 json={"request": {"channels": ["instagram"], "topic": "x", "slide_count": 2}}).json()["id"]
    end = time.time() + 5
    while c.get(f"/sns/api/posts/{pid}", auth=auth).json()["post"]["status"] == "working" and time.time() < end:
        time.sleep(0.05)
    c.post(f"/sns/api/posts/{pid}/instagram/publish", auth=auth, json={})
    end = time.time() + 5
    while ig.got is None and time.time() < end:
        time.sleep(0.05)
    u = urlparse(ig.got[0][0])
    assert c.get(f"{u.path}?{u.query}").status_code == 200            # 로그인 없이 (인스타그램이 가져감)
    assert c.get(f"/sns/api/posts/{pid}").status_code == 401           # 다른 곳은 여전히 잠김
    assert c.get(f"/sns/api/posts/{pid}/cards/0.png").status_code == 401
