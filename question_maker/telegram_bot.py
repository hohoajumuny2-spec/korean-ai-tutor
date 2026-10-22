"""텔레그램으로 문제 공장을 쓰는 봇.

원장님이 봇에게
  - 지문(글, 사진, PDF, txt)을 보내면 → 바로 출제하거나 매일 출제 보관함에 넣는다.
  - "객관식 상 2, 중 2, OX 하 3" 처럼 보내면 → 그 구성으로 출제한다.
  - 만든 문제를 받은 뒤 "3번 더 어렵게" 처럼 보내면 → 그대로 고쳐 다시 보내 준다.
매일 출제가 끝나면 만든 문제를 봇이 보내 준다.

등록된 원장님 대화방(TELEGRAM_CHAT_ID)에서 온 말만 듣는다.
"""

import hashlib
import html
import re
import threading
import traceback

import requests

from .catalog import DIFFICULTIES, KINDS

CIRCLED = "①②③④⑤⑥⑦"
LIMIT = 3800          # 텔레그램 메시지 한 통 한도(4096자)보다 조금 작게
PASSAGE_MIN = 150     # 이보다 긴 글은 지문으로 본다

KIND_WORDS = [("객관식", "mcq"), ("오지선다", "mcq"), ("선다", "mcq"), ("단답형", "short"), ("단답", "short"),
              ("서술", "short"), ("빈칸", "blank"), ("o/x", "ox"), ("ox", "ox"), ("오엑스", "ox")]
DIFF_RE = re.compile(r"(?<![가-힣])(준킬러|킬러|최상|상|중|하)(?![가-힣])")
DIFF_WORDS = {"준킬러": "semi", "킬러": "killer", "최상": "killer", "상": "high", "중": "mid", "하": "low"}


def parse_recipe(text: str):
    """'객관식 상 2, 중 2, OX 하 3' → 출제 설정. 종류나 난이도 말이 하나도 없으면 None."""
    items, kind, seen_word = [], None, False
    for seg in re.split(r"[,\n/·]+|그리고", text.lower()):
        seg = seg.strip()
        if not seg:
            continue
        for word, k in KIND_WORDS:
            if word in seg:
                kind, seen_word = k, True
                break
        dm = DIFF_RE.search(seg)
        if dm:
            seen_word = True
        nm = re.search(r"(\d{1,2})", seg)
        if nm:
            items.append({"kind": kind or "mcq", "difficulty": DIFF_WORDS[dm.group(1)] if dm else "mid",
                          "count": int(nm.group(1))})
    if not items or not seen_word:
        return None
    return {"items": items}


def recipe_text(recipe: dict) -> str:
    return ", ".join(f"{KINDS[i['kind']]} {DIFFICULTIES[i['difficulty']][0]} {i['count']}"
                     for i in recipe.get("items", []))


def _h(text: str) -> str:
    """텔레그램 HTML로 안전하게. 밑줄 <u>만 살린다."""
    s = html.escape(text or "", quote=False)
    s = s.replace("&lt;u&gt;", "<u>").replace("&lt;/u&gt;", "</u>")
    if s.count("<u>") > s.count("</u>"):
        s += "</u>" * (s.count("<u>") - s.count("</u>"))
    return s


def _answer(q: dict) -> str:
    if q["kind"] == "mcq":
        try:
            return CIRCLED[int(q["answer"]) - 1]
        except (ValueError, IndexError, TypeError):
            return str(q["answer"])
    return str(q["answer"])


def format_set(title: str, data: dict) -> list:
    """문제 세트를 텔레그램 메시지 여러 통으로 나눈다. [문제들..., 정답·해설...]"""
    pieces = [f"📝 <b>{_h(title)}</b>"]
    passage = f"<b>{_h(data.get('intro') or '※ 다음 글을 읽고 물음에 답하시오.')}</b>\n\n{_h(data.get('passage', ''))}"
    if data.get("source_note"):
        passage += f"\n{_h(data['source_note'])}"
    pieces.append(passage)
    for q in data.get("questions", []):
        p = f"<b>{q['no']}.</b> {_h(q['stem'])}"
        if q.get("box"):
            p += f"\n<blockquote>&lt;보기&gt;\n{_h(q['box'])}</blockquote>"
        if q["kind"] == "mcq":
            p += "\n" + "\n".join(f"{CIRCLED[i]} {_h(c)}" for i, c in enumerate(q["choices"]))
        elif q["kind"] == "ox":
            p += "\n( O / X )"
        pieces.append(p)
    answers = ["✅ <b>정답 및 해설</b>"]
    for q in data.get("questions", []):
        tag = f"{KINDS.get(q['kind'], '')}·{DIFFICULTIES.get(q['difficulty'], ('',))[0]}"
        answers.append(f"<b>{q['no']}. {_h(_answer(q))}</b> <i>({tag})</i>\n{_h(q.get('explanation', ''))}")
    return _pack(pieces) + _pack(answers)


def _pack(pieces: list) -> list:
    out, cur = [], ""
    for p in pieces:
        while len(p) > LIMIT:   # 아주 긴 지문은 밑줄 표시를 빼고 잘라 보낸다
            plain = re.sub(r"</?u>", "", p)
            if cur:
                out.append(cur)
                cur = ""
            out.append(plain[:LIMIT])
            p = plain[LIMIT:]
        if cur and len(cur) + len(p) + 2 > LIMIT:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out


HELP = """📝 <b>문제 공장 봇</b>

<b>1. 지문 보내기</b>
지문을 붙여 넣거나, 사진·PDF·txt 파일로 보내세요.
→ [바로 출제] 또는 [매일 출제 보관함에 넣기]를 고르면 됩니다.

<b>2. 문항 구성 정하기</b> (지문을 보낸 뒤)
예) <code>객관식 상 2, 중 2, OX 하 3</code>
예) <code>킬러 1, 상 3, 단답형 중 2</code>
난이도: 킬러·준킬러·상·중·하 / 종류: 객관식·단답형·빈칸·OX

<b>3. 말로 고치기</b> (문제를 받은 뒤)
예) <code>3번 더 어렵게</code>, <code>5번 선지 ④를 더 헷갈리게</code>, <code>OX 2개 더</code>

<b>명령</b>
/list 최근 문제 세트 · /show 번호 그 세트 다시 받기
/undo 방금 고친 것 되돌리기 · /queue 보관함 · /help 도움말"""


class TelegramBot:
    def __init__(self, token: str, owner_chat_id: str, hooks, http=None):
        self.token = token.strip()
        self.owner = str(owner_chat_id).strip()
        self.h = hooks
        self.http = http or requests
        self.secret = hashlib.sha256(("qm-telegram:" + self.token).encode()).hexdigest()[:40]
        self._seen = []
        self._lock = threading.Lock()

    # ── 텔레그램 API ─────────────────────────────────
    def call(self, method, files=None, **params):
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        try:
            if files:
                r = self.http.post(url, data=params, files=files, timeout=60)
            else:
                r = self.http.post(url, json=params, timeout=60)
            body = r.json() if hasattr(r, "json") else {}
            if not body.get("ok", False):
                print(f"텔레그램 {method} 실패: {str(body)[:300]}")
            return body
        except Exception as e:
            print(f"텔레그램 {method} 오류: {e}")
            return {}

    def send(self, text, buttons=None, chat_id=None):
        params = {"chat_id": chat_id or self.owner, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row]
                                                          for row in buttons]}
        res = self.call("sendMessage", **params)
        if not res.get("ok") and "parse" in str(res.get("description", "")).lower():
            # HTML이 깨졌으면 글자만이라도 보낸다
            params["text"] = re.sub(r"<[^>]+>", "", text)
            params.pop("parse_mode")
            res = self.call("sendMessage", **params)
        return res

    def send_file(self, filename, data: bytes, caption=""):
        return self.call("sendDocument", files={"document": (filename, data, "text/html")},
                         chat_id=self.owner, caption=caption)

    def set_webhook(self, url):
        return self.call("setWebhook", url=url, secret_token=self.secret,
                         allowed_updates=["message", "callback_query"], drop_pending_updates=False)

    def download(self, file_id) -> bytes:
        info = self.call("getFile", file_id=file_id)
        path = (info.get("result") or {}).get("file_path")
        if not path:
            raise RuntimeError("텔레그램에서 파일을 받지 못했습니다.")
        r = self.http.get(f"https://api.telegram.org/file/bot{self.token}/{path}", timeout=120)
        return r.content

    # ── 받은 말 처리 ─────────────────────────────────
    def handle(self, update: dict):
        uid = update.get("update_id")
        with self._lock:
            if uid is not None:
                if uid in self._seen:
                    return     # 텔레그램이 같은 것을 다시 보낸 경우
                self._seen = (self._seen + [uid])[-200:]
        try:
            if "callback_query" in update:
                self._on_button(update["callback_query"])
            elif "message" in update:
                self._on_message(update["message"])
        except Exception as e:
            traceback.print_exc()
            self.send(f"⚠️ 처리하다 문제가 생겼어요: {_h(str(e))[:500]}")

    def _is_owner(self, chat_id) -> bool:
        return str(chat_id) == self.owner

    def _on_message(self, msg):
        chat_id = msg.get("chat", {}).get("id")
        if not self._is_owner(chat_id):
            self.send(f"이 봇은 등록된 원장님만 쓸 수 있어요.\n(이 대화방 번호: <code>{chat_id}</code>)", chat_id=chat_id)
            return
        text = (msg.get("text") or msg.get("caption") or "").strip()

        if msg.get("photo") or msg.get("document"):
            self.send("📄 파일에서 글을 읽는 중이에요...")
            if msg.get("photo"):
                data = self.download(msg["photo"][-1]["file_id"])
                extracted = self.h.extract("photo.jpg", "image/jpeg", data)
            else:
                doc = msg["document"]
                data = self.download(doc["file_id"])
                extracted = self.h.extract(doc.get("file_name", "file"), doc.get("mime_type", ""), data)
            if len(extracted.strip()) < 20:
                self.send("글을 거의 읽지 못했어요. 더 선명한 사진이나 글자로 된 파일을 보내 주세요.")
                return
            recipe = parse_recipe(text) if text else None
            self._got_passage(extracted.strip(), recipe)
            return

        if not text:
            return
        if text.startswith("/"):
            self._command(text)
            return
        pending = self.h.store.get_setting("tg_pending")
        current = self.h.store.get_setting("tg_current_set")
        lines = [l for l in text.splitlines() if l.strip()]
        # 긴 글, 여러 줄로 된 글(짧은 시 등), 고칠 문제가 아직 없을 때의 웬만한 글은 지문으로 본다
        if (len(text) >= PASSAGE_MIN or (len(lines) >= 3 and len(text) >= 40)
                or (not current and not pending and len(text) >= 40 and not parse_recipe(text))):
            self._got_passage(text, None)
            return
        if pending:
            recipe = parse_recipe(text)
            if recipe:
                self._generate(pending, recipe)
                return
            if text in ("출제", "바로 출제", "네", "응", "ㅇㅇ", "ok", "OK", "좋아"):
                self._generate(pending, None)
                return
        if current:
            self._revise(current, text)
            return
        self.send(HELP)

    def _command(self, text):
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        if cmd in ("/start", "/help"):
            self.send(HELP)
        elif cmd == "/list":
            rows = self.h.store.list_sets(limit=10)
            if not rows:
                self.send("아직 만든 문제가 없어요.")
                return
            label = {"working": "⏳", "done": "✅", "error": "❌"}
            lines = [f"{label.get(r['status'], '')} <code>/show {r['id']}</code> {_h(r['title'])} ({r['question_count']}문항)"
                     for r in rows]
            self.send("<b>최근 문제 세트</b>\n" + "\n".join(lines))
        elif cmd == "/show":
            if arg.strip().isdigit():
                self.send_set(int(arg.strip()))
            else:
                self.send("번호를 함께 보내 주세요. 예) /show 12  (번호는 /list 에서 볼 수 있어요)")
        elif cmd == "/undo":
            current = self.h.store.get_setting("tg_current_set")
            prev = self.h.store.pop_revision(current) if current else None
            if not prev:
                self.send("되돌릴 것이 없어요.")
                return
            self.h.store.update_set(current, data=prev["data"])
            self.send(f"↶ 되돌렸어요. ({_h(prev['note'])})")
            self.send_set(current)
        elif cmd == "/queue":
            waiting = self.h.store.next_waiting(100)
            daily = self.h.daily_settings()
            head = (f"⏰ 매일 출제: {'켜짐, ' + daily['time'] + '에 ' + str(daily['per_day']) + '개씩' if daily.get('enabled') else '꺼짐'}\n"
                    f"보관함 대기 지문 {len(waiting)}개")
            self.send(head + ("\n" + "\n".join(f"· {_h(p['title'])}" for p in waiting[:15]) if waiting else ""))
        else:
            self.send(HELP)

    def _got_passage(self, text, recipe):
        title = " ".join(text.split())[:20]
        pending = {"text": text, "title": title}
        if recipe:
            self._generate(pending, recipe)
            return
        self.h.store.set_setting("tg_pending", pending)
        default = self.h.default_recipe()
        self.send(f"📥 지문을 받았어요 ({len(text)}자)\n<i>{_h(text[:60])}…</i>\n\n"
                  f"기본 구성: {recipe_text(default)}\n"
                  f"다른 구성으로 내려면 이렇게 보내세요 → <code>객관식 상 2, OX 하 3</code>",
                  buttons=[[("✏️ 바로 출제", "gen")],
                           [("📥 매일 출제 보관함에 넣기", "queue"), ("취소", "cancel")]])

    def _on_button(self, cb):
        self.call("answerCallbackQuery", callback_query_id=cb.get("id"))
        if not self._is_owner(cb.get("message", {}).get("chat", {}).get("id")):
            return
        data = cb.get("data", "")
        pending = self.h.store.get_setting("tg_pending")
        if data in ("gen", "queue", "cancel") and not pending:
            self.send("이미 처리한 지문이에요. 지문을 다시 보내 주세요.")
            return
        if data == "gen":
            self._generate(pending, None)
        elif data == "queue":
            self.h.store.add_passage(pending["title"], pending["text"], "국어", None)
            self.h.store.set_setting("tg_pending", None)
            waiting = len(self.h.store.next_waiting(10000))
            daily = self.h.daily_settings()
            when = (f"매일 {daily['time']}에 {daily['per_day']}개씩 출제해서 보내 드려요."
                    if daily.get("enabled") else "매일 출제가 꺼져 있어요. 문제 공장 화면에서 켜 주세요.")
            self.send(f"📥 보관함에 넣었어요. (대기 {waiting}개)\n{when}")
        elif data == "cancel":
            self.h.store.set_setting("tg_pending", None)
            self.send("취소했어요.")
        elif data.startswith("file:"):
            self.send_paper(int(data[5:]))
        elif data.startswith("regen:"):
            sid = int(data[6:])
            self.send("🔁 같은 지문·구성으로 다시 출제하는 중이에요... (1~2분)")
            self.h.regenerate(sid)
            self.send_set(sid)

    def _generate(self, pending, recipe):
        self.h.store.set_setting("tg_pending", None)
        r = recipe or self.h.default_recipe()
        self.send(f"✏️ 출제하는 중이에요... ({recipe_text(r)})\n보통 1~2분 걸려요.")
        sid = self.h.create_set(pending["title"], pending["text"], recipe)
        self.send_set(sid)

    def _revise(self, set_id, instruction):
        targets = [int(n) for n in re.findall(r"(\d{1,2})\s*번", instruction)]
        self.send("🛠 고치는 중이에요... (30초~1분)")
        try:
            summary = self.h.revise(set_id, instruction, targets)
        except Exception as e:
            self.send(f"⚠️ 고치지 못했어요: {_h(str(e))}")
            return
        self.send(f"✅ {_h(summary)}\n(마음에 안 들면 /undo)")
        self.send_set(set_id)

    # ── 결과 보내기 ──────────────────────────────────
    def send_set(self, set_id, header=""):
        row = self.h.store.get_set(set_id)
        if not row:
            self.send("그 번호의 문제 세트가 없어요. /list 로 번호를 확인해 주세요.")
            return
        if row["status"] == "working":
            self.send("⏳ 아직 출제 중이에요. 잠시 뒤 /show " + str(set_id))
            return
        if row["status"] == "error" or not row.get("data"):
            self.send(f"❌ 출제에 실패했어요.\n{_h(row.get('error', ''))}",
                      buttons=[[("🔁 다시 출제", f"regen:{set_id}")]])
            return
        self.h.store.set_setting("tg_current_set", set_id)
        if header:
            self.send(header)
        msgs = format_set(row["title"], row["data"])
        for m in msgs:
            self.send(m)
        notes = row["data"].get("notes") or []
        tail = f"\n\n<i>{_h(' / '.join(notes)[:300])}</i>" if notes else ""
        self.send(f"이 문제를 고치려면 그냥 말로 보내세요. 예) <code>3번 더 어렵게</code>{tail}",
                  buttons=[[("🖨 시험지 파일 받기", f"file:{set_id}"), ("🔁 다시 출제", f"regen:{set_id}")]])

    def send_paper(self, set_id):
        html_text = self.h.render(set_id)
        if not html_text:
            self.send("시험지를 만들 수 없어요.")
            return
        row = self.h.store.get_set(set_id)
        name = re.sub(r"[\\/:*?\"<>|\s]+", "_", row["title"])[:40] or "시험지"
        self.send_file(f"{name}.html", html_text.encode("utf-8"),
                       caption="파일을 열면 시험지가 나와요. 맨 위 [인쇄 / PDF로 저장]을 누르세요.")
