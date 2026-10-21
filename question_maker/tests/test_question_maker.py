import random
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from question_maker.ai import FakeAI, parse_json_text
from question_maker.app import create_app, daily_due
from question_maker.generator import (GenerationError, balance_answers, generate_set, merge_style,
                                      normalize_question, normalize_recipe, passage_is_faithful,
                                      revise_set)
from question_maker.render import render_paper
from question_maker.storage import KST

PASSAGE = ("잃어버렸습니다.\n무얼 어디다 잃었는지 몰라\n두 손이 주머니를 더듬어\n길에 나아갑니다.\n\n"
           "돌과 돌과 돌이 끝없이 연달아\n길은 돌담을 끼고 갑니다.")

RECIPE = {"items": [{"kind": "mcq", "difficulty": "high", "count": 4},
                    {"kind": "ox", "difficulty": "low", "count": 2},
                    {"kind": "short", "difficulty": "mid", "count": 1},
                    {"kind": "blank", "difficulty": "mid", "count": 1}],
          "types": ["시어·소재의 의미", "표현상 특징"], "verify": True}


def test_parse_json_text_handles_fences():
    assert parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_text('여기 있습니다: {"a": 2} 끝') == {"a": 2}


def test_normalize_recipe_rejects_empty_and_too_many():
    with pytest.raises(GenerationError):
        normalize_recipe({"items": []})
    with pytest.raises(GenerationError):
        normalize_recipe({"items": [{"kind": "mcq", "difficulty": "mid", "count": 999}]})
    r = normalize_recipe({"items": [{"kind": "nope", "difficulty": "mid", "count": 1},
                                    {"kind": "ox", "difficulty": "low", "count": "2"}]})
    assert r["items"] == [{"kind": "ox", "difficulty": "low", "count": 2}]


def test_normalize_question_checks_shape():
    style = merge_style({})
    q = normalize_question({"kind": "mcq", "stem": "s", "choices": ["① 가", "② 나", "③ 다", "④ 라", "⑤ 마"],
                            "answer": "③"}, style)
    assert q["choices"][0] == "가" and q["answer"] == 3
    with pytest.raises(GenerationError):
        normalize_question({"kind": "mcq", "stem": "s", "choices": ["a", "b"], "answer": 1}, style)
    assert normalize_question({"kind": "ox", "stem": "s", "answer": "참"}, style)["answer"] == "O"
    with pytest.raises(GenerationError):
        normalize_question({"kind": "ox", "stem": "s", "answer": "모름"}, style)


def test_passage_faithfulness():
    marked = PASSAGE.replace("길에 나아갑니다", "㉠<u>길에 나아갑니다</u>").replace("돌과 돌과", "[B]\n돌과 돌과")
    assert passage_is_faithful(PASSAGE, marked)
    assert not passage_is_faithful(PASSAGE, "완전히 다른 글을 AI가 지어냈습니다. " * 3)


def test_balance_answers_spreads_and_keeps_notes_aligned():
    style = merge_style({})
    qs = []
    for i in range(10):
        qs.append(normalize_question({"kind": "mcq", "stem": f"q{i}", "answer": 1,
                                      "choices": ["정답", "b", "c", "d", "e"],
                                      "choice_notes": ["맞음", "x", "x", "x", "x"]}, style))
    balance_answers(qs, random.Random(1))
    answers = [q["answer"] for q in qs]
    assert len(set(answers)) == 5
    for q in qs:
        assert q["choices"][q["answer"] - 1] == "정답"
        assert q["choice_notes"][q["answer"] - 1] == "맞음"


def test_generate_set_with_fake_ai():
    data = generate_set(FakeAI(), source_text=PASSAGE, subject="국어", recipe=RECIPE,
                        style=merge_style({}), rng=random.Random(3))
    qs = data["questions"]
    assert len(qs) == 8
    assert [q["no"] for q in qs] == list(range(1, 9))
    assert [q["kind"] for q in qs] == ["mcq"] * 4 + ["short", "blank", "ox", "ox"]
    assert {q["type"] for q in qs} <= set(RECIPE["types"]) | {"사실적 이해(내용 일치)"}


def test_generate_set_large_is_split_into_batches():
    recipe = {"items": [{"kind": "mcq", "difficulty": "mid", "count": 30}], "verify": False}
    data = generate_set(FakeAI(), source_text=PASSAGE, subject="국어", recipe=recipe, style=merge_style({}))
    assert len(data["questions"]) == 30


def test_revise_set_with_fake_ai():
    style = merge_style({})
    data = generate_set(FakeAI(), source_text=PASSAGE, subject="국어", recipe=RECIPE, style=style)
    new, summary = revise_set(FakeAI(), source_text=PASSAGE, data=data, instruction="2번 더 어렵게",
                              targets=[2], style=style)
    assert new["questions"][1]["stem"].endswith("(고친 문항)")
    assert not new["questions"][0]["stem"].endswith("(고친 문항)")
    assert summary


def test_render_paper_escapes_but_keeps_underline():
    data = {"intro": "※ 다음 글을 읽고 물음에 답하시오.", "passage": "㉠<u>길</u> <script>x</script>",
            "source_note": "- 윤동주, 「길」",
            "questions": [{"no": 1, "kind": "mcq", "difficulty": "mid", "type": "", "stem": "㉠의 의미는?",
                           "box": "", "choices": list("abcde"), "answer": 2, "accept": [],
                           "explanation": "근거", "choice_notes": []}]}
    out = render_paper([{"title": "t", "data": data}], merge_style({"paper_title": "중간고사"}), "both")
    assert "<u>길</u>" in out and "<script>x" not in out
    assert "정답 및 해설" in out and "②" in out and "중간고사" in out


def test_daily_due():
    s = {"enabled": True, "time": "07:00", "weekdays": [0, 1, 2, 3, 4, 5, 6]}
    morning = datetime(2026, 10, 21, 7, 5, tzinfo=KST)
    assert daily_due(s, morning, "")
    assert not daily_due(s, morning, "2026-10-21")
    assert not daily_due(s, datetime(2026, 10, 21, 6, 59, tzinfo=KST), "")
    assert not daily_due(dict(s, enabled=False), morning, "")
    assert not daily_due(dict(s, weekdays=[5, 6]), morning, "")   # 수요일


def wait_done(client, set_id):
    for _ in range(100):
        s = client.get(f"/api/sets/{set_id}").json()
        if s["status"] != "working":
            return s
        time.sleep(0.05)
    raise AssertionError("출제가 끝나지 않음")


def test_api_end_to_end(tmp_path):
    app = create_app(str(tmp_path / "t.db"), ai=FakeAI(), start_scheduler=False)
    c = TestClient(app)
    assert c.get("/").status_code == 200
    assert c.get("/api/meta").json()["ai"]

    sid = c.post("/api/styles", json={"data": {"name": "모의고사형", "choice_count": 4, "columns": 1}}).json()["id"]
    recipe = dict(RECIPE, style_id=sid)
    set_id = c.post("/api/sets", json={"title": "길", "text": PASSAGE, "recipe": recipe}).json()["set_id"]
    s = wait_done(c, set_id)
    assert s["status"] == "done", s["error"]
    assert all(len(q["choices"]) == 4 for q in s["data"]["questions"] if q["kind"] == "mcq")

    # 말로 고치기 → 되돌리기
    r = c.post(f"/api/sets/{set_id}/revise", json={"instruction": "1번 쉽게", "targets": [1]})
    assert r.status_code == 200
    assert c.get(f"/api/sets/{set_id}").json()["data"]["questions"][0]["stem"].endswith("(고친 문항)")
    assert c.post(f"/api/sets/{set_id}/undo").status_code == 200
    assert not c.get(f"/api/sets/{set_id}").json()["data"]["questions"][0]["stem"].endswith("(고친 문항)")

    # 직접 고치기: 문항 하나 빼기
    data = c.get(f"/api/sets/{set_id}").json()["data"]
    data["questions"] = data["questions"][1:]
    assert c.put(f"/api/sets/{set_id}", json={"data": data}).status_code == 200
    assert c.get(f"/api/sets/{set_id}").json()["data"]["questions"][0]["no"] == 1

    page = c.get(f"/print?ids={set_id}&mode=both")
    assert page.status_code == 200 and "정답 및 해설" in page.text

    # 보관함 + 매일 출제
    p1 = c.post("/api/passages", json={"title": "첫째", "text": PASSAGE}).json()["id"]
    p2 = c.post("/api/passages", json={"title": "둘째", "text": PASSAGE + "\n끝."}).json()["id"]
    c.post(f"/api/passages/{p2}/move", json={"direction": -1})
    daily = {"enabled": True, "time": "06:00", "per_day": 1, "weekdays": list(range(7)), "recipe": RECIPE}
    assert c.put("/api/daily", json=daily).status_code == 200
    made = app.state.run_daily(datetime.now(KST))
    assert len(made) == 1
    done = c.get(f"/api/sets/{made[0]}").json()
    assert done["status"] == "done" and done["origin"] == "daily" and done["passage_id"] == p2
    statuses = {p["id"]: p["status"] for p in c.get("/api/passages").json()["passages"]}
    assert statuses == {p1: "waiting", p2: "done"}
    assert c.get("/api/daily").json()["last_run"] == datetime.now(KST).strftime("%Y-%m-%d")


def test_api_without_ai(tmp_path):
    c = TestClient(create_app(str(tmp_path / "t.db"), ai=None, start_scheduler=False))
    r = c.post("/api/sets", json={"text": PASSAGE, "recipe": RECIPE})
    assert r.status_code == 400 and "키" in r.json()["detail"]


def test_password(tmp_path, monkeypatch):
    monkeypatch.setenv("QM_PASSWORD", "abc")
    c = TestClient(create_app(str(tmp_path / "t.db"), ai=FakeAI(), start_scheduler=False))
    assert c.get("/api/meta").status_code == 401
    assert c.get("/api/meta", auth=("x", "abc")).status_code == 200
