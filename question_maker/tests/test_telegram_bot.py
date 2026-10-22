from datetime import datetime

from fastapi.testclient import TestClient

from question_maker.ai import FakeAI
from question_maker.app import create_app
from question_maker.storage import KST, FirestoreStore
from question_maker.telegram_bot import TelegramBot, format_set, parse_recipe
from question_maker.tests.fake_firestore import FakeFirestore

OWNER = "111"
PASSAGE = ("잃어버렸습니다. 무얼 어디다 잃었는지 몰라 두 손이 주머니를 더듬어 길에 나아갑니다. "
           "돌과 돌과 돌이 끝없이 연달아 길은 돌담을 끼고 갑니다. 담은 쇠문을 굳게 닫아 "
           "길 위에 긴 그림자를 드리우고 길은 아침에서 저녁으로 저녁에서 아침으로 통했습니다.")


class Resp:
    def __init__(self, body=None, content=b""):
        self._b, self.content = body or {"ok": True, "result": {}}, content

    def json(self):
        return self._b


class FakeHTTP:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, data=None, files=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, json or data or {}, files))
        if method == "getFile":
            return Resp({"ok": True, "result": {"file_path": "photos/a.jpg"}})
        return Resp()

    def get(self, url, timeout=None):
        return Resp(content=b"image-bytes")

    def texts(self):
        return [c[1].get("text", "") for c in self.calls if c[0] == "sendMessage"]

    def clear(self):
        self.calls.clear()


def make():
    http = FakeHTTP()
    bot = TelegramBot("TOKEN", OWNER, None, http=http)
    app = create_app(store=FirestoreStore(FakeFirestore()), ai=FakeAI(), start_scheduler=False,
                     telegram=bot, public_url="https://example.com/qm")
    return app, bot, http


def msg(text=None, chat=OWNER, uid=[0], **extra):
    uid[0] += 1
    m = {"chat": {"id": int(chat)}, **extra}
    if text is not None:
        m["text"] = text
    return {"update_id": uid[0], "message": m}


def button(data, uid=[1000]):
    uid[0] += 1
    return {"update_id": uid[0], "callback_query": {"id": "c", "data": data,
                                                    "message": {"chat": {"id": int(OWNER)}}}}


def test_parse_recipe():
    r = parse_recipe("객관식 상 2, 중 2, OX 하 3")
    assert r["items"] == [{"kind": "mcq", "difficulty": "high", "count": 2},
                          {"kind": "mcq", "difficulty": "mid", "count": 2},
                          {"kind": "ox", "difficulty": "low", "count": 3}]
    assert parse_recipe("킬러 1\n단답형 중 2")["items"][1] == {"kind": "short", "difficulty": "mid", "count": 2}
    assert parse_recipe("3번 더 어렵게") is None
    assert parse_recipe("안녕") is None


def test_format_set_splits_long_messages():
    data = {"intro": "", "passage": "가" * 9000, "questions": [
        {"no": 1, "kind": "ox", "difficulty": "low", "stem": "s", "answer": "O", "explanation": "e"}]}
    msgs = format_set("t", data)
    assert all(len(m) <= 4096 for m in msgs)
    assert "정답 및 해설" in msgs[-1]


def test_stranger_is_refused():
    app, bot, http = make()
    bot.handle(msg(PASSAGE, chat="999"))
    assert "원장님만" in http.texts()[0] and "999" in http.texts()[0]
    assert app.state.store.get_setting("tg_pending") is None


def test_full_conversation():
    app, bot, http = make()
    store = app.state.store

    bot.handle(msg(PASSAGE))
    assert store.get_setting("tg_pending")["text"] == PASSAGE
    assert "지문을 받았어요" in http.texts()[-1]

    http.clear()
    bot.handle(msg("객관식 상 2, OX 하 3"))
    sid = store.get_setting("tg_current_set")
    row = store.get_set(sid)
    assert row["status"] == "done" and len(row["data"]["questions"]) == 5
    joined = "\n".join(http.texts())
    assert "①" in joined and "정답 및 해설" in joined
    assert store.get_setting("tg_pending") is None

    # 같은 업데이트가 다시 와도 두 번 처리하지 않는다
    dup = msg("1번 더 어렵게")
    bot.handle(dup)
    bot.handle(dup)
    assert store.get_set(sid)["data"]["questions"][0]["stem"].endswith("(고친 문항)")
    assert len(store.list_revisions(sid)) == 1

    bot.handle(msg("/undo"))
    assert not store.get_set(sid)["data"]["questions"][0]["stem"].endswith("(고친 문항)")

    http.clear()
    bot.handle(button(f"file:{sid}"))
    docs = [c for c in http.calls if c[0] == "sendDocument"]
    assert docs and b"<html" in docs[0][2]["document"][1]

    http.clear()
    bot.handle(msg("/list"))
    assert f"/show {sid}" in http.texts()[0]


def test_photo_and_queue_and_daily():
    app, bot, http = make()
    store = app.state.store
    bot.handle(msg(photo=[{"file_id": "small"}, {"file_id": "big"}]))
    assert store.get_setting("tg_pending")  # 연습용 AI가 옮겨 적은 글이 지문이 된다
    bot.handle(button("queue"))
    assert len(store.next_waiting(10)) == 1
    assert store.get_setting("tg_pending") is None

    store.set_setting("daily", {"enabled": True, "time": "06:00", "per_day": 1, "weekdays": list(range(7)),
                                "recipe": {"items": [{"kind": "ox", "difficulty": "low", "count": 2}]}})
    http.clear()
    made = app.state.run_daily(datetime.now(KST))
    assert len(made) == 1
    assert any("오늘의 문제" in t for t in http.texts())


def test_webhook_route_checks_secret():
    app, bot, http = make()
    c = TestClient(app)
    assert c.post("/telegram/wrong", json={}).status_code == 404
    assert c.post(f"/telegram/{bot.secret}", json={}).status_code == 404   # 머리글 비밀값 없음
    r = c.post(f"/telegram/{bot.secret}", json={"update_id": 5, "message": {"chat": {"id": 1}, "text": "/help"}},
               headers={"X-Telegram-Bot-Api-Secret-Token": bot.secret})
    assert r.status_code == 200
    assert c.get("/api/meta").json()["telegram"] is True
