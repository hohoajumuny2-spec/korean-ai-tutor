import io
import time
import zipfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from question_maker.tests.fake_firestore import FakeFirestore
from sns_maker import catalog
from sns_maker.ai import FakeAI
from sns_maker.app import create_app
from sns_maker.cards import H, W, render_card, render_zip
from sns_maker.generator import (GenerationError, build_generate_prompt, check_post, clean_hashtags, finish,
                                 generate_post, merge_profile, normalize_request, revise_post, suggest_ideas)
from sns_maker.storage import KST, FirestoreStore, Store

PROFILE = {"name": "바른국어학원", "region": "대치동", "contact": "02-000-0000",
           "reg_no": "제1234호", "fee_note": "교습비: 고1 월 30만원", "base_hashtags": "#바른국어 #대치동국어학원"}


def wait_done(client, pid, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        post = client.get(f"/api/posts/{pid}").json()["post"]
        if post["status"] != "working":
            return post
        time.sleep(0.05)
    raise AssertionError("끝나지 않음")


def test_normalize_request_checks_input():
    with pytest.raises(GenerationError):
        normalize_request({"channels": [], "topic": "x"})
    with pytest.raises(GenerationError):
        normalize_request({"channels": ["blog"], "topic": "  "})
    r = normalize_request({"channels": ["blog", "blog", "tiktok"], "topic": "주제", "kind": "nope",
                           "slide_count": 99, "tone": "?"})
    assert r["channels"] == ["blog"] and r["kind"] == "tip" and r["slide_count"] == catalog.MAX_SLIDES
    assert r["tone"] == "friendly"


def test_prompt_contains_profile_and_rules():
    req = normalize_request({"channels": ["instagram", "blog"], "topic": "중간고사 대비", "details": "11/3 개강",
                             "reel": True})
    p = build_generate_prompt(req, merge_profile(PROFILE), "2026-10-29")
    for word in ("바른국어학원", "대치동", "11/3 개강", "합격 보장", "reel_script", "titles", "카드뉴스 6장"):
        assert word in p


def test_clean_hashtags():
    tags = clean_hashtags(["대치동 국어", "#공부팁", "#공부팁", "#BAD!tag"], "#바른국어 바른국어")
    assert tags[0] == "#바른국어" and tags.count("#공부팁") == 1
    assert "#대치동" in tags and "#국어" in tags and "#BADtag" in tags
    assert len(clean_hashtags([f"#t{i}" for i in range(50)])) == 30


def test_finish_adds_footer_and_notes_for_promo():
    req = normalize_request({"channels": ["instagram", "blog"], "topic": "고1 모집", "kind": "recruit"})
    raw = FakeAI().generate_json("", dict(req, mode="generate", profile=PROFILE))
    raw["instagram"]["caption"] += "\n합격 보장! [개강일] 시작 #a #b #c"
    data = finish(raw, req, merge_profile(PROFILE))
    ig = data["instagram"]
    assert "제1234호" in ig["caption"] and "교습비" in data["blog"]["outro"]
    assert "#a" not in ig["caption"] and "#a" in ig["hashtags"]   # 본문 끝 태그는 따로 옮김
    assert ig["hashtags"][:2] == ["#바른국어", "#대치동국어학원"]
    notes = " ".join(data["notes"])
    assert "합격 보장" in notes and "[개강일]" in notes
    assert "등록번호" not in notes   # 정보가 다 있으니 안내하지 않음


def test_notes_warn_missing_reg_no_only_for_promo():
    p = merge_profile({"name": "학원"})
    promo = normalize_request({"channels": ["blog"], "topic": "모집", "kind": "recruit"})
    tip = normalize_request({"channels": ["blog"], "topic": "팁", "kind": "tip"})
    raw = FakeAI().generate_json("", dict(promo, mode="generate", profile=p))
    assert any("등록번호" in n for n in finish(raw, promo, p)["notes"])
    assert not any("등록번호" in n for n in finish(raw, tip, p)["notes"])
    data = finish(raw, promo, merge_profile({"avoid": "족집게"}))
    data["blog"]["intro"] = "족집게 강의"
    assert any("족집게" in n for n in check_post(data, promo, merge_profile({"avoid": "족집게"})))


def test_finish_rejects_broken_answer():
    req = normalize_request({"channels": ["instagram"], "topic": "x"})
    with pytest.raises(GenerationError):
        finish({"instagram": {"caption": ""}}, req, merge_profile({}))
    with pytest.raises(GenerationError):
        finish({}, req, merge_profile({}))


class FlakyAI(FakeAI):
    def __init__(self):
        self.calls = 0

    def generate_json(self, prompt, task, quality=True):
        self.calls += 1
        if self.calls == 1:
            return {"instagram": {"caption": ""}}
        return super().generate_json(prompt, task, quality)


def test_generate_retries_once_and_needs_ai():
    ai = FlakyAI()
    data = generate_post(ai, {"channels": ["instagram"], "topic": "공부 팁"}, PROFILE, "오늘")
    assert ai.calls == 2 and data["instagram"]["slides"]
    with pytest.raises(GenerationError):
        generate_post(None, {"channels": ["blog"], "topic": "x"}, {}, "오늘")


def test_revise_and_ideas():
    req = {"channels": ["blog"], "topic": "팁"}
    data = generate_post(FakeAI(), req, PROFILE, "오늘")
    out = revise_post(FakeAI(), data, "더 짧게", req, PROFILE)
    assert "고친 글" in out["blog"]["intro"] and out["summary"]
    with pytest.raises(GenerationError):
        revise_post(FakeAI(), data, " ", req, PROFILE)
    ideas = suggest_ideas(FakeAI(), PROFILE, datetime(2026, 10, 29, tzinfo=KST), [], 5)
    assert len(ideas) == 5 and all(i["kind"] in catalog.KINDS for i in ideas)


def test_cards_render():
    slides = [{"title": "중간고사 2주 전, 국어 이렇게 준비하세요", "body": "부제"},
              {"title": "1. 교과서 본문 다시 읽기", "body": "선생님이 수업 시간에 강조한 부분을 표시하며 " * 6}]
    png = render_card(slides[1], 1, 2, "바른국어학원", "white")
    assert Image.open(io.BytesIO(png)).size == (W, H)
    z = zipfile.ZipFile(io.BytesIO(render_zip(slides, "학원", "nope")))
    assert z.namelist() == ["card_01.png", "card_02.png"]


@pytest.mark.parametrize("make_store", [lambda tmp: Store(str(tmp / "s.db")),
                                        lambda tmp: FirestoreStore(FakeFirestore())])
def test_app_flow(tmp_path, make_store):
    client = TestClient(create_app(ai=FakeAI(), store=make_store(tmp_path)))
    assert client.get("/").status_code == 200
    assert client.get("/api/meta").json()["ai"]
    assert client.put("/api/profile", json={"profile": PROFILE}).json()["profile"]["name"] == "바른국어학원"

    assert client.post("/api/posts", json={"request": {"channels": [], "topic": "x"}}).status_code == 400
    pid = client.post("/api/posts", json={"request": {"channels": ["instagram", "blog"], "topic": "고1 모집",
                                                      "kind": "recruit", "slide_count": 3}}).json()["id"]
    post = wait_done(client, pid)
    assert post["status"] == "done" and len(post["data"]["instagram"]["slides"]) == 3
    assert "제1234호" in post["data"]["instagram"]["caption"]
    listed = client.get("/api/posts").json()["posts"]
    assert listed[0]["id"] == pid and listed[0]["channels"] == ["instagram", "blog"]

    r = client.get(f"/api/posts/{pid}/cards/0.png?theme=pink")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get(f"/api/posts/{pid}/cards/9.png").status_code == 404
    assert client.get(f"/api/posts/{pid}/cards.zip").status_code == 200

    client.post(f"/api/posts/{pid}/revise", json={"instruction": "더 짧게"})
    post = wait_done(client, pid)
    assert "고친 글" in post["data"]["instagram"]["caption"] and post["prev"]

    edited = post["data"]
    edited["blog"]["intro"] = "직접 고친 첫 문단 합격 보장"
    post = client.put(f"/api/posts/{pid}", json={"data": edited}).json()["post"]
    assert post["data"]["blog"]["intro"].startswith("직접 고친") and any("합격 보장" in n for n in post["data"]["notes"])

    post = client.post(f"/api/posts/{pid}/undo").json()["post"]
    assert "고친 글" in post["data"]["blog"]["intro"]

    assert len(client.post("/api/ideas", json={"count": 4}).json()["ideas"]) == 4
    client.delete(f"/api/posts/{pid}")
    assert client.get(f"/api/posts/{pid}").status_code == 404


def test_app_without_ai_and_with_login(tmp_path):
    client = TestClient(create_app(ai=None, store=Store(str(tmp_path / "a.db"))))
    assert client.post("/api/posts", json={"request": {"channels": ["blog"], "topic": "x"}}).status_code == 400

    locked = TestClient(create_app(ai=FakeAI(), store=Store(str(tmp_path / "b.db")),
                                   check_login=lambda u, p: p == "pw"))
    assert locked.get("/api/meta").status_code == 401
    assert locked.get("/api/meta", auth=("원장님", "pw")).status_code == 200


def test_login_with_admin_token_from_academy_app(tmp_path):
    """학원 앱 버튼: 관리자 토큰을 POST /sns/login 으로 보내면 쿠키를 받고 비밀번호 없이 들어간다."""
    from fastapi import FastAPI
    parent = FastAPI()
    parent.mount("/sns", create_app(ai=FakeAI(), store=Store(str(tmp_path / "t.db")),
                                    check_login=lambda u, p: False, check_token=lambda t: t == "good"))
    client = TestClient(parent)
    assert client.get("/sns/api/meta").status_code == 401
    assert client.post("/sns/login", data={"token": "bad"}, follow_redirects=False).status_code == 401
    r = client.post("/sns/login", data={"token": "good"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "./"
    assert client.cookies.get("admin_session") == "good"
    assert client.get("/sns/api/meta").status_code == 200
    assert client.get("/sns/").status_code == 200
