# ─────────────────────────────────────────────────────────
# 키오스크 클리닉 (국어)
#
#   학생은 이름만 누르면 된다. 입구 키오스크와 교실 태블릿에 같은 화면(clinic-kiosk.html)을 띄운다.
#
#   ① 클리닉 등원 → 오늘의 클리닉 안내 → [1단계 문제 출력] → 복사기에서 원장님 문제지(PDF)가 나온다
#   ② 종이로 푼다 → 태블릿에서 이름 → 답 입력 → 점수·틀린 번호
#   ③ 틀린 문제마다 '왜 틀렸는지' 고르기 → 문제별 짧은 해설·주목할 점 → [해설지 출력]
#   ④ 해설지를 보고 다시 풀기 → 틀렸던 문제만 다시 답 입력
#   ⑤ 그래도 틀린 문제 → "이 문제는 잘 모르는구나!" → [국최 선생님께 질문하기]
#   ⑥ 1단계 점수(처음 푼 점수)가 기준 점수 이상이면 높은 레벨, 미만이면 낮은 레벨 문제지 출력
#      낮은 레벨을 통과하면 높은 레벨로. 각 문제지마다 ②~⑤를 똑같이 한다.
#
#   원장님이 준비하는 것: '클리닉 프로그램' 하나 = 안내문 + 기준 점수 + 문제지 세 개(1단계·낮은 레벨·높은 레벨)
#   각 문제지는 '문제지 만들기'로 만든 PDF(출력용) + 내보낸 .json(정답·해설을 읽음).
#
#   main.py가 register(app, helpers)로 필요한 함수(db, AI, 포인트, 저장 등)를 넘겨준다.
# ─────────────────────────────────────────────────────────
import os
import re
import json
import asyncio
import urllib.parse
from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, HTTPException, File, Form, UploadFile
from pydantic import BaseModel

H = {}

PROGRAMS_COLL = "clinic_programs"
RUNS_COLL = "clinic_runs"
JOBS_COLL = "clinic_print_jobs"
CONFIG_DOC = "clinic_config"

SET_KEYS = ("main", "low", "high")
SET_LABEL = {"main": "1단계 문제", "low": "2단계 · 기초 레벨", "high": "2단계 · 높은 레벨"}
REASONS = ["지문을 잘못 읽었어요", "선지를 잘못 읽었어요", "개념을 몰랐어요", "헷갈려서 찍었어요", "시간이 부족했어요", "실수했어요"]
CIRC = "①②③④⑤⑥⑦⑧⑨⑩"
FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "NotoSansKR.ttf")
XP_SET_DONE = 20

DEFAULT_CONFIG = {"kiosk_code": ""}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _db():
    return H["db"]()


def _s(v, n=None):
    t = str(v if v is not None else "").strip()
    return t[:n] if n else t


def load_config() -> dict:
    db = _db()
    out = dict(DEFAULT_CONFIG)
    if db is None:
        return out
    doc = db.collection("settings").document(CONFIG_DOC).get()
    if doc.exists:
        out["kiosk_code"] = _s((doc.to_dict() or {}).get("kiosk_code"), 40)
    return out


# ── '문제지 만들기'로 만든 문제지 읽기 ─────────────────
#   원장님은 '문제지 만들기'(브라우저에서 여는 파일)로 문제를 쓰고 PDF로 뽑는다.
#   클리닉에 올릴 때 그 PDF와 함께 '파일로 내보내기'(.json) 또는 입력칸 글을 같이 올리면,
#   여기서 그 글을 '문제지 만들기'와 같은 규칙으로 읽어 문항·정답·해설을 꺼낸다 (AI 안 씀, 0원).
#   규칙은 문제지 만들기의 parse()를 그대로 옮겼다:
#     [1~2] 묶음 머리 · 1. 문항 · [지문]…[/지문] · <보기>…[/보기] · ①~⑤ 선택지 · 정답: · 해설:
RE_Q = re.compile(r"^\s*(?:(?:문제|Q)\s*(\d{1,3})\s*[.．:)]?(?=\s|$)|(\d{1,3})\s*[.．](?![\d.．])|(\d{1,3})\s*번\s*[.．)]?(?=\s|$))\s*(.*)$")
RE_GROUP = re.compile(r"^\s*\[\s*(\d{1,3})\s*[~∼～\-–]\s*(\d{1,3})\s*\]\s*(.*)$")
RE_ANS = re.compile(r"^\s*(?:[\[【<〈(]\s*(?:정답|답)\s*[\]】>〉)]|(?:정답|답)\s*[:：]|정답(?=\s|[①-⑩\d]))\s*(.*)$")
RE_EXP = re.compile(r"^\s*(?:[\[【<〈(]\s*(?:해설|풀이)\s*[\]】>〉)]|(?:해설|풀이)\s*[:：]|해설(?=\s|$))\s*(.*)$")
RE_BOGI = re.compile(r"^\s*[<〈《＜\[【(]\s*보\s*기\s*[>〉》＞\]】)]\s*$")
RE_BOX = re.compile(r"^\s*\[(지문|박스|상자)\]\s*$")
RE_BOXEND = re.compile(r"^\s*\[/\s*(보기|지문|박스|상자|(?:지문\s*)?요약|핵심\s*정리)\s*\]\s*$")
RE_SUM = re.compile(r"^\s*[\[【]\s*(?:(?:지문\s*)?요약|핵심\s*정리)\s*[\]】]\s*$")
RE_SQ = re.compile(r"^\s*[\[<〈(【]?\s*(서술형|단답형)\s*(\d{1,3})\s*[\]>〉)】]?\s*[.．:)]?(?:\s+|$)(.*)$")
RE_CHOICE = re.compile(r"^\s*(?:[①-⑩]|\(\d{1,2}\)|[1-9]\)\s)")
RE_BACK = re.compile(r"^[ \t]*[\[【]\s*정답\s*모아\s*보기\s*[\]】][ \t]*$", re.M)
_CIRC10 = "①②③④⑤⑥⑦⑧⑨⑩"


def _maker_plain(t: str) -> str:
    t = re.sub(r"\[그림:[^\]]*\]", "[그림]", t or "")
    t = re.sub(r"__(.+?)__", r"<u>\1</u>", t)
    t = t.replace("**", "")
    t = re.sub(r"\^\{(.+?)\}", r"^\1", t)
    t = re.sub(r"_\{(.+?)\}", r"_\1", t)
    return t.strip()


def _split_choices(line: str) -> list:
    t = line.strip()
    if re.match(r"^[①-⑩]", t):
        return [x[1:].strip() for x in re.split(r"(?=[①-⑩])", t) if x]
    if re.match(r"^\(\d{1,2}\)", t):
        return [re.sub(r"^\(\d{1,2}\)\s*", "", x).strip() for x in re.split(r"(?=\(\d{1,2}\))", t) if x.strip()]
    return [re.sub(r"^[1-9]\)\s*", "", x).strip() for x in re.split(r"\s+(?=[1-9]\)\s)", t) if x.strip()]


def parse_maker_text(src: str) -> dict:
    """→ {"questions": [{no, passage, q_text, bogi, options, answer, explanation, kind}], "total": 문항 수}"""
    src = (src or "").replace("\r\n", "\n").replace("\r", "\n")
    back = ""
    m = RE_BACK.search(src)
    if m:
        src, back = src[:m.start()], src[m.end():]
    lines = src.split("\n")
    numbered = any(RE_Q.match(l) or RE_SQ.match(l) for l in lines)
    items, cur, state, box, blank = [], None, "body", None, False

    def new_q(num):
        return {"type": "q", "num": num, "parts": [], "boxes": [], "choices": [], "answer": "", "explain": [], "kind": "choice"}

    def flush():
        nonlocal cur, state, box
        if cur:
            items.append(cur)
        cur, state, box = None, "body", None

    for raw in lines:
        line = raw.rstrip()
        empty = not line.strip()
        g = RE_GROUP.match(line)
        if g:
            flush()
            cur = {"type": "g", "from": int(g.group(1)), "to": int(g.group(2)), "title": g.group(3), "parts": [], "boxes": [], "choices": []}
            blank = False
            continue
        sq = RE_SQ.match(line) if numbered else None
        if sq and state != "box-x":
            flush()
            cur = new_q(sq.group(2)); cur["kind"] = "essay"
            if sq.group(3).strip():
                cur["parts"].append(sq.group(3))
            blank = False
            continue
        q = RE_Q.match(line) if numbered else None
        if q and state != "box-x":
            flush()
            cur = new_q(q.group(1) or q.group(2) or q.group(3))
            if q.group(4).strip():
                cur["parts"].append(q.group(4))
            blank = False
            continue
        if not empty and not numbered:
            pass
        blank = empty
        if not cur:
            if empty:
                continue
            cur = {"type": "g", "parts": [], "boxes": [], "choices": []}
        a = RE_ANS.match(line) if not empty else None
        if a:
            if cur["type"] == "q":
                cur["answer"] = a.group(1).strip()
            state = "after"
            continue
        e = RE_EXP.match(line) if not empty else None
        if e:
            state = "explain"
            if cur["type"] == "q" and e.group(1).strip():
                cur["explain"].append(e.group(1))
            continue
        if state == "explain":
            if cur["type"] == "q" and (cur["explain"] or not empty):
                cur["explain"].append(line)
            continue
        if RE_BOGI.match(line):
            box = {"label": "보기", "lines": []}; cur["boxes"].append(box); state = "box"; continue
        if RE_BOX.match(line):
            box = {"label": "지문", "lines": []}; cur["boxes"].append(box); state = "box-x"; continue
        if RE_SUM.match(line):
            box = {"label": "요약", "lines": []}; cur["boxes"].append(box); state = "box-x"; continue
        if RE_BOXEND.match(line):
            state, box = "body", None; continue
        if state != "box-x" and RE_CHOICE.match(line) and cur["type"] == "q":
            state, box = "body", None
            cur["choices"].extend(_split_choices(line))
            continue
        if state in ("box", "box-x"):
            if not empty:
                box["lines"].append(line)
            continue
        if empty:
            continue
        if cur["choices"]:
            cur["choices"][-1] += " " + line.strip()
            continue
        cur["parts"].append(line)
    flush()

    # 뒤쪽 [정답 모아 보기]: "1. ③" / "1) 3" / "1번 ③" 줄로 적힌 정답
    back_ans = {}
    for l in back.split("\n"):
        for mm in re.finditer(r"(\d{1,3})\s*(?:번|[.)])\s*([①-⑩]|\d{1,2})", l):
            back_ans[mm.group(1)] = mm.group(2)

    out, group = [], None
    for it in items:
        if it["type"] == "g":
            group = it
            continue
        no = str(it.get("num") or "")
        passage_parts = []
        if group and (not group.get("from") or (no.isdigit() and group["from"] <= int(no) <= group["to"])):
            passage_parts += ["\n".join(b["lines"]) for b in group["boxes"] if b["label"] == "지문"]
            if not passage_parts and group["parts"]:
                passage_parts.append("\n".join(group["parts"]))
        passage_parts += ["\n".join(b["lines"]) for b in it["boxes"] if b["label"] == "지문"]
        bogi = "\n".join("\n".join(b["lines"]) for b in it["boxes"] if b["label"] == "보기")
        ans_raw = it["answer"] or back_ans.get(no, "")
        ans = ""
        mm = re.match(r"^\s*([①-⑩])", ans_raw)
        if mm:
            ans = str(_CIRC10.index(mm.group(1)) + 1)
        else:
            mm = re.match(r"^\s*(\d{1,2})\s*(?:번)?\s*$", ans_raw)
            if mm:
                ans = mm.group(1)
        is_choice = it["kind"] == "choice" and len([c for c in it["choices"] if c]) >= 2
        out.append({
            "no": no, "kind": "choice" if is_choice else "written",
            "passage": _maker_plain("\n\n".join(p for p in passage_parts if p.strip())),
            "q_text": _maker_plain(" ".join(it["parts"])), "bogi": _maker_plain(bogi),
            "options": [_maker_plain(c) for c in it["choices"][:5]],
            "answer": ans if is_choice else "", "answer_text": _maker_plain(ans_raw),
            "explanation": _maker_plain("\n".join(it["explain"])),
        })
    return {"questions": out, "total": len(out)}




# ── AI: 다시 풀 때 볼 '주목할 점' ─────────────────────────
HINT_PROMPT = """아래는 국어 객관식 문항들입니다. 학생이 이 문항을 틀렸고, 곧 혼자 다시 풀어 봅니다.
문항마다 다시 풀 때 도움이 되는 '주목할 점'을 쓰세요.
- 1~2문장, 70자 이내. 학생에게 말하듯 쓰세요. (예: "2문단에서 냉매가 열을 '내주는' 곳이 어디인지 다시 확인해 봐.")
- 정답 번호나 정답 보기의 내용을 직접 말하지 마세요. 어디를, 무엇에 주의해서 볼지만 알려 주세요.
- 해설이 있으면 참고하되 정답을 드러내지 마세요.
오직 JSON 배열만 출력하세요: [{{"no": "1", "hint": "..."}}, ...]

[문항]
{content}"""


def ai_make_hints(questions: list) -> dict:
    """문제지 하나를 올릴 때 한 번만 부른다 (학생마다 부르지 않는다). → {no: hint}"""
    if not questions:
        return {}
    blocks = []
    for q in questions:
        opts = "\n".join(f"({i+1}) {o}" for i, o in enumerate(q.get("options") or []) if o)
        blocks.append(f"### {q['no']}번\n[지문 일부] {(q.get('passage') or '')[:1200]}\n[발문] {q.get('q_text','')}\n"
                      + (f"[보기] {q['bogi']}\n" if q.get("bogi") else "")
                      + f"{opts}\n[정답] {q.get('answer','')}번\n[해설] {q.get('explanation','')}")
    try:
        resp = H["safe_generate"]([HINT_PROMPT.format(content="\n\n".join(blocks)[:60000])], False, False)
        m = re.search(r"\[.*\]", getattr(resp, "text", "") or "", re.S)
        rows = json.loads(m.group(0)) if m else []
    except Exception as e:
        print("클리닉 주목할 점 만들기 실패:", e)
        return {}
    return {str(r.get("no")).strip(): _s(r.get("hint"), 200) for r in rows if isinstance(r, dict) and r.get("hint")}


def _fallback_hint(q: dict) -> str:
    """AI가 실패했을 때: 해설 첫 문장에서 정답 번호 표시를 지우고 쓴다."""
    t = re.sub(r"정답\s*(은|은요|:)?\s*[①-⑩\d]+\s*(번)?(이다|입니다)?[.]?", "", q.get("explanation", "") or "")
    t = re.sub(r"[①-⑩]", "", t).strip()
    first = re.split(r"(?<=[.!?다])\s+", t)[0] if t else ""
    return _s(first, 120) or "지문으로 돌아가 발문이 묻는 것과 각 보기를 한 줄씩 다시 대조해 보세요."


# ── 문제지 하나 읽기 ─────────────────────────────────────
def build_set(text: str, hint_mode: str) -> dict:
    parsed = parse_maker_text(text) if (text or "").strip() else {"questions": [], "total": 0}
    graded = [q for q in parsed["questions"] if q["kind"] == "choice" and q["answer"]]
    hints = ai_make_hints(graded) if (graded and hint_mode != "explain") else {}
    qs = []
    for q in graded:
        if hint_mode == "explain":
            hint = _s(q.get("explanation"), 400) or _fallback_hint(q)
        else:
            hint = hints.get(str(q["no"])) or _fallback_hint(q)
        qs.append({"no": str(q["no"]), "answer": q["answer"], "q_text": _s(q["q_text"], 600), "bogi": _s(q["bogi"], 800),
                   "options": [_s(o, 300) for o in q["options"]], "explanation": _s(q["explanation"], 800), "hint": hint})
    return {"questions": qs, "total": parsed["total"],
            "written": [q["no"] for q in parsed["questions"] if q["kind"] != "choice"],
            "no_answer": [q["no"] for q in parsed["questions"] if q["kind"] == "choice" and not q["answer"]]}


def _text_from_json(raw: bytes) -> tuple:
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return "", ""
    d = d.get("data", d) if isinstance(d, dict) else {}
    return _s(d.get("text")), _s((d.get("opt") or {}).get("title"))


# ── 학생·프로그램 찾기 ───────────────────────────────────
def student_info(name: str) -> Optional[dict]:
    db = _db()
    doc = db.collection("students").document(name).get()
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    info = H["student_targeting_info"](name) or {"subjects": ["korean"], "classes": {}, "all_classes": []}
    return {"school": _s(data.get("school")), "grade": _s(data.get("grade")),
            "class_name": (info.get("classes") or {}).get("korean", "") or "",
            "korean": "korean" in (info.get("subjects") or ["korean"])}


def _target_ok(p: dict, name: str, class_name: str) -> bool:
    studs, classes = p.get("student_names") or [], p.get("class_names") or []
    if not studs and not classes:
        return True
    return name in studs or (bool(class_name) and class_name in classes)


def find_program_for(name: str, class_name: str) -> Optional[tuple]:
    """이 학생이 오늘 받을 클리닉 프로그램: 대상·기간이 맞고, 아직 끝내지 않은 것 중 먼저 올린 것."""
    db = _db()
    today = _today()
    finished = {(d.to_dict() or {}).get("program_id") for d in
                db.collection(RUNS_COLL).where("student_name", "==", name).stream() if (d.to_dict() or {}).get("finished_at")}
    cands = []
    for d in db.collection(PROGRAMS_COLL).stream():
        p = d.to_dict() or {}
        if not p.get("active", True) or d.id in finished or not (p.get("sets") or {}).get("main"):
            continue
        if p.get("start_date") and p["start_date"] > today:
            continue
        if p.get("end_date") and p["end_date"] < today:
            continue
        if not _target_ok(p, name, class_name):
            continue
        cands.append((d.id, p))
    if not cands:
        return None
    cands.sort(key=lambda x: (0 if name in (x[1].get("student_names") or []) else 1, x[1].get("created_at", "")))
    return cands[0]


def open_run(name: str) -> Optional[tuple]:
    """끝내지 않은 클리닉이 있으면 그것 (날짜가 바뀌어도 이어서 한다)."""
    db = _db()
    rows = [(d.id, d.to_dict() or {}) for d in db.collection(RUNS_COLL).where("student_name", "==", name).stream()]
    rows = [r for r in rows if not r[1].get("finished_at")]
    rows.sort(key=lambda r: r[1].get("started_at", ""), reverse=True)
    return rows[0] if rows else None


def _program(pid: str) -> dict:
    d = _db().collection(PROGRAMS_COLL).document(pid).get()
    return (d.to_dict() or {}) if d.exists else {}


# ── 다음 단계 정하기 ─────────────────────────────────────
def decide_next(run: dict, prog: dict) -> tuple:
    """(다음 문제지 키 또는 "", 학생에게 보여 줄 설명)"""
    cur = run.get("cur", "main")
    sets = prog.get("sets") or {}
    score = ((run.get("sets") or {}).get(cur) or {}).get("first", {}).get("score", 0)
    path = run.get("path") or []
    if cur == "main":
        base = int(prog.get("pass_score", 70))
        if score >= base:
            nxt, why = "high", f"1단계 점수 {score}점 — 기준 {base}점을 넘었어요! 높은 레벨 문제에 도전해요."
        else:
            nxt, why = "low", f"1단계 점수 {score}점 — 기준 {base}점보다 조금 낮아요. 기초 레벨 문제로 실력을 다져요."
    elif cur == "low":
        base = int(prog.get("low_pass_score", 70))
        if score >= base:
            nxt, why = "high", f"기초 레벨 {score}점 — 통과! 이제 높은 레벨 문제에 도전해요."
        else:
            nxt, why = "", f"기초 레벨 {score}점 — 통과 기준 {base}점에 아직 못 미쳐요. 오늘은 여기까지! 다음 클리닉에서 다시 도전해요."
    else:
        nxt, why = "", f"높은 레벨 {score}점 — 오늘 클리닉을 모두 마쳤어요!"
    if nxt and (nxt in path or not sets.get(nxt)):
        if not sets.get(nxt):
            why += " (오늘은 준비된 다음 문제지가 없어 여기서 마쳐요.)"
        nxt = ""
    return nxt, why


# ── 학생 화면용 모양 (정답은 절대 보내지 않는다) ────────────
def run_view(rid: str, run: dict, prog: dict) -> dict:
    cur = run.get("cur", "main")
    sset = (prog.get("sets") or {}).get(cur) or {}
    qmap = {q["no"]: q for q in sset.get("questions", [])}
    st = (run.get("sets") or {}).get(cur) or {}
    step = run.get("step", "solve")
    first, second = st.get("first") or {}, st.get("second") or {}
    wrong = first.get("wrong", [])
    show_hint = step in ("hint", "ask", "next", "done")

    def qbrief(no, with_hint=False):
        q = qmap.get(no, {})
        o = {"no": no, "q_text": q.get("q_text", ""), "bogi": q.get("bogi", ""), "options": q.get("options", []),
             "reason": (st.get("reasons") or {}).get(no, "")}
        if with_hint:
            o["hint"] = q.get("hint", "")
        return o

    out = {"id": rid, "program_title": run.get("program_title", ""), "intro": prog.get("intro", ""),
           "cur": cur, "cur_label": SET_LABEL[cur], "step": step, "path": run.get("path", []),
           "numbers": [q["no"] for q in sset.get("questions", [])], "written": sset.get("written", []),
           "first": {k: first.get(k) for k in ("score", "correct", "total", "wrong")} if first else None,
           "wrong_items": [qbrief(n, show_hint) for n in wrong],
           "second": {k: second.get(k) for k in ("fixed", "still")} if second else None,
           "still_items": [qbrief(n, True) for n in (second.get("still") or [])],
           "asked": st.get("asked", []), "printed": bool(st.get("printed_at")), "hint_printed": bool(st.get("hint_printed_at")),
           "reasons_list": REASONS, "finished": bool(run.get("finished_at")), "summary": run.get("summary", ""),
           "history": [{"set": k, "label": SET_LABEL[k], "score": (((run.get("sets") or {}).get(k) or {}).get("first") or {}).get("score")}
                       for k in run.get("path", [])]}
    if step == "next":
        nxt, why = decide_next(run, prog)
        out["next_set"], out["next_label"], out["next_why"] = nxt, (SET_LABEL[nxt] if nxt else ""), why
    return out


def program_card(pid: str, p: dict) -> dict:
    sets = p.get("sets") or {}
    return {"id": pid, "title": p.get("title", ""), "intro": p.get("intro", ""), "pass_score": p.get("pass_score", 70),
            "low_pass_score": p.get("low_pass_score", 70),
            "sets": {k: {"label": SET_LABEL[k], "count": len((sets.get(k) or {}).get("questions", []))} for k in SET_KEYS if sets.get(k)}}


# ── 해설지 PDF ───────────────────────────────────────────
def _plain(t: str) -> str:
    return re.sub(r"</?u>", "", t or "")


def hint_lines(run: dict, prog: dict, set_key: str) -> list:
    """해설지에 들어갈 줄들: [(글, 크기, 색, 들여쓰기, 아래 여백)]"""
    sset = (prog.get("sets") or {}).get(set_key) or {}
    qmap = {q["no"]: q for q in sset.get("questions", [])}
    rs = ((run.get("sets") or {}).get(set_key)) or {}
    out = [(f"로지에듀 클리닉 · {SET_LABEL[set_key]} 해설지", 16, (0, 0, 0), 0, 2),
           (f"{run.get('student_name','')}   ·   {prog.get('title','')}   ·   {_today()}", 10, (0.3, 0.3, 0.3), 0, 6),
           ("지문은 처음 받은 문제지를 보세요. 아래 '주목할 점'을 읽고 틀린 문제를 다시 풀어 본 뒤, 태블릿에 답을 입력하세요.", 9.5, (0.3, 0.3, 0.3), 0, 12)]
    for no in (rs.get("first") or {}).get("wrong", []):
        q = qmap.get(no)
        if not q:
            continue
        reason = (rs.get("reasons") or {}).get(no, "")
        out.append((f"{no}번" + (f"   (내가 고른 이유: {reason})" if reason else ""), 12, (0, 0, 0), 0, 3))
        out.append((_plain(q.get("q_text", "")), 10.5, (0, 0, 0), 0, 3))
        if q.get("bogi"):
            out.append(("<보기> " + _plain(q["bogi"]), 9.8, (0, 0, 0), 10, 3))
        opts = [f"{CIRC[i]} {_plain(o)}" for i, o in enumerate(q.get("options") or []) if o]
        if opts:
            out.append(("\n".join(opts), 10, (0, 0, 0), 10, 5))
        out.append(("▶ 주목할 점: " + (q.get("hint") or ""), 10.5, (0.05, 0.3, 0.6), 4, 6))
        out.append(("다시 고른 답:  ①   ②   ③   ④   ⑤", 10.5, (0, 0, 0), 4, 16))
    return out


def build_hint_pdf_pil(lines: list, font_path: str = FONT_PATH) -> bytes:
    """예비 방법: 글을 그림(A4, 150dpi)으로 그려 PDF로 묶는다. 서버에 이미 있는 Pillow만 쓴다."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    scale = 150 / 72
    W, Hh, M = int(595 * scale), int(842 * scale), int(44 * scale)
    pages, cur = [], None
    y = M
    fonts = {}

    def font(sz):
        if sz not in fonts:
            fonts[sz] = ImageFont.truetype(font_path, int(sz * scale))
        return fonts[sz]

    def new_page():
        nonlocal cur, y
        cur = Image.new("RGB", (W, Hh), "white")
        pages.append(cur)
        y = M

    def wrap(text, f, width):
        out = []
        for para in text.split("\n"):
            line = ""
            for word in para.split(" "):
                cand = (line + " " + word) if line else word
                if f.getlength(cand) <= width:
                    line = cand
                    continue
                if line:
                    out.append(line)
                line = ""
                for ch in word:            # 한 낱말이 한 줄보다 길면 글자 단위로 자른다
                    if f.getlength(line + ch) > width and line:
                        out.append(line)
                        line = ""
                    line += ch
            out.append(line)
        return out

    new_page()
    for text, size, color, indent, gap in lines:
        f = font(size)
        lh = int(size * scale * 1.5)
        for ln in wrap(text, f, W - 2 * M - int(indent * scale)):
            if y + lh > Hh - M:
                new_page()
            ImageDraw.Draw(cur).text((M + int(indent * scale), y), ln, font=f, fill=tuple(int(c * 255) for c in color))
            y += lh
        y += int(gap * scale)
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=150)
    return buf.getvalue()


def build_hint_pdf(run: dict, prog: dict, set_key: str) -> bytes:
    """틀린 문제만 모아 '내가 고른 이유'와 '주목할 점'을 붙인 해설지. 정답은 싣지 않는다(다시 풀어야 하므로).
    글자가 선명한 PyMuPDF로 먼저 만들고, 혹시 실패하면 Pillow(그림) 방식으로 만든다."""
    try:
        return _build_hint_pdf_fitz(run, prog, set_key)
    except Exception as e:
        print("해설지 PDF(fitz) 실패 → 그림 방식으로:", e)
        return build_hint_pdf_pil(hint_lines(run, prog, set_key))


def _build_hint_pdf_fitz(run: dict, prog: dict, set_key: str) -> bytes:
    import fitz
    W, Hh, M = 595, 842, 44
    doc = fitz.open()
    st = {"page": None, "y": M}

    def new_page():
        p = doc.new_page(width=W, height=Hh)
        p.insert_font(fontname="kr", fontfile=FONT_PATH)
        st["page"], st["y"] = p, M
        return p

    def write(text, size=10.5, gap=4, indent=0, color=(0, 0, 0)):
        if not text:
            return
        for _ in range(3):
            p = st["page"] or new_page()
            rect = fitz.Rect(M + indent, st["y"], W - M, Hh - M)
            r = p.insert_textbox(rect, text, fontsize=size, fontname="kr", color=color)
            if r >= 0:
                st["y"] = Hh - M - r + gap
                return
            if st["y"] <= M + 1:
                text = text[: max(200, int(len(text) * 0.7))] + " …"
                continue
            new_page()

    new_page()
    for text, size, color, indent, gap in hint_lines(run, prog, set_key):
        write(text, size, gap=gap, indent=indent, color=color)
    # 한글 글꼴(10MB)을 통째로 넣으면 해설지 한 장이 10MB가 된다 — 쓴 글자만 남긴다
    try:
        doc.subset_fonts()
    except Exception as e:
        print("글꼴 줄이기 실패(그대로 출력):", e)
    return doc.tobytes(garbage=3, deflate=True)


# ── 질문 게시판에 올리기 ─────────────────────────────────
def post_question(run: dict, prog: dict, set_key: str, nos: list) -> str:
    db = _db()
    qmap = {q["no"]: q for q in ((prog.get("sets") or {}).get(set_key) or {}).get("questions", [])}
    rs = (run.get("sets") or {}).get(set_key) or {}
    lines = []
    for no in nos:
        q = qmap.get(no, {})
        my1 = ((rs.get("first") or {}).get("answers") or {}).get(no, "")
        my2 = ((rs.get("second") or {}).get("answers") or {}).get(no, "")
        lines.append(f"· {no}번 {_plain(q.get('q_text',''))[:70]}\n  처음 고른 답 {my1 or '-'} → 다시 고른 답 {my2 or '-'} / 틀린 이유: {(rs.get('reasons') or {}).get(no, '')}")
    text = (f"[클리닉 질문] {prog.get('title','')} · {SET_LABEL[set_key]}\n"
            f"해설지를 보고 다시 풀었는데도 잘 모르겠어요. 아래 문제를 알려 주세요.\n\n" + "\n".join(lines))
    ref = db.collection(H["qna_coll"]).document()
    ref.set({"author": run.get("student_name"), "is_admin": False, "school": run.get("school", ""), "grade": run.get("grade", ""),
             "subject": "korean", "text": text[:4000], "images": [], "solved": False, "answers": [], "created_at": _now(),
             "clinic_run": run.get("_id", "")})
    H["send_telegram_message"](f"❓ [클리닉 질문]\n{run.get('student_name')} — {SET_LABEL[set_key]} {', '.join(nos)}번을 모르겠대요.")
    return ref.id


def summarize(run: dict) -> str:
    parts = []
    for k in run.get("path", []):
        s = (run.get("sets") or {}).get(k) or {}
        f, sec = s.get("first") or {}, s.get("second") or {}
        if not f:
            continue
        t = f"{SET_LABEL[k]} {f.get('score', 0)}점"
        if f.get("wrong"):
            fixed, still = len(sec.get("fixed") or []), len(sec.get("still") or [])
            t += f"(틀린 {len(f['wrong'])}문제 중 다시 풀어 {fixed}문제 해결" + (f", {still}문제 질문" if still else "") + ")"
        parts.append(t)
    return " → ".join(parts)


def _queue_print(run_id: str, name: str, kind: str, set_key: str, pdf_path: str):
    _db().collection(JOBS_COLL).add({"run_id": run_id, "student_name": name, "kind": kind, "set": set_key,
                                     "pdf_path": pdf_path, "status": "pending", "created_at": _now()})


# ═══════════════════════════════════════════════════════
class KioskReq(BaseModel):
    code: str = ""
    student_name: str = ""
    answers: dict = {}
    reasons: dict = {}
    which: str = ""


class ProgUpdateReq(BaseModel):
    id: str
    title: Optional[str] = None
    intro: Optional[str] = None
    class_names: Optional[list] = None
    student_names: Optional[list] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    pass_score: Optional[int] = None
    low_pass_score: Optional[int] = None
    active: Optional[bool] = None
    questions: Optional[dict] = None    # {set: [{no, answer, hint}]}
    delete: bool = False


class ConfigReq(BaseModel):
    kiosk_code: str = ""


class RunReq(BaseModel):
    id: str
    delete: bool = False


class PrintDoneReq(BaseModel):
    code: str = ""
    ok: bool = True
    note: str = ""


def register(app, helpers: dict):
    H.update(helpers)
    verify_admin = H["verify_admin"]

    def kiosk_ok(code: str, x_admin_token: Optional[str]) -> bool:
        want = load_config().get("kiosk_code")
        if want and _s(code) == want:
            return True
        if x_admin_token:
            try:
                return bool(verify_admin(x_admin_token))
            except HTTPException:
                return False
        return False

    def need_kiosk(code, tok):
        if not kiosk_ok(code, tok):
            raise HTTPException(status_code=403, detail="키오스크 코드가 맞지 않습니다. 원장님께 말씀해주세요.")

    def load_run_for(name: str):
        r = open_run(name)
        if not r:
            raise HTTPException(status_code=400, detail="진행 중인 클리닉이 없어요. 처음부터 '클리닉 등원'을 눌러 주세요.")
        rid, run = r
        run["_id"] = rid
        return rid, run, _program(run["program_id"])

    def save_run(rid: str, run: dict):
        run["updated_at"] = _now()
        _db().collection(RUNS_COLL).document(rid).set({k: v for k, v in run.items() if k != "_id"})

    def finish_run(rid: str, run: dict, prog: dict):
        run["step"], run["finished_at"] = "done", _now()
        run["summary"] = summarize(run)
        if not H["is_preview"](run["student_name"]):
            first_main = (((run.get("sets") or {}).get("main") or {}).get("first") or {})
            H["save_report"]({"submitted_at": run["finished_at"], "student_name": run["student_name"],
                              "school": run.get("school", ""), "grade": run.get("grade", ""),
                              "task_name": f"클리닉 · {prog.get('title','')}", "type": "클리닉",
                              "score": first_main.get("score", 0), "total_score": 100,
                              "clinic_summary": run["summary"], "clinic_run": rid})
        H["send_telegram_message"](f"🩺 [클리닉 완료]\n{run['student_name']}: {run['summary']}")
        try:
            H["send_push_to_student"](run["student_name"], "클리닉 완료 🎉", run["summary"][:120], "/", "clinic")
        except Exception as e:
            print("클리닉 푸시 실패:", e)

    # ══════════ 키오스크 ══════════
    @app.get("/api/clinic/kiosk/today")
    def kiosk_today(code: str = "", x_admin_token: Optional[str] = Header(None)):
        need_kiosk(code, x_admin_token)
        db = _db()
        today, wd = _today(), datetime.now().weekday()
        sched = {}
        for d in db.collection("clinics").stream():
            r = d.to_dict() or {}
            n = _s(r.get("student_name"))
            if not n:
                continue
            kind = r.get("kind", "weekly")
            if (kind == "once" and _s(r.get("date")) == today) or (kind != "once" and r.get("weekday") is not None and int(r["weekday"]) % 7 == wd):
                sched.setdefault(n, _s(r.get("time")))
        status = {}
        for d in db.collection(RUNS_COLL).stream():
            r = d.to_dict() or {}
            n = r.get("student_name")
            if r.get("finished_at"):
                if r["finished_at"][:10] == today:
                    status[n] = "done"
            else:
                status.setdefault(n, f"{SET_LABEL.get(r.get('cur','main'),'')} 진행 중")
        rows = [{"student_name": n, "time": t, "status": status.get(n, "")} for n, t in sched.items()]
        for n, s in status.items():
            if n not in sched:
                rows.append({"student_name": n, "time": "", "status": s})
        rows.sort(key=lambda r: (r["time"] or "99", r["student_name"]))
        everyone = sorted(d.id for d in db.collection("students").stream())
        return {"success": True, "date": today, "rows": rows, "everyone": everyone}

    @app.post("/api/clinic/kiosk/state")
    async def kiosk_state(req: KioskReq, x_admin_token: Optional[str] = Header(None)):
        need_kiosk(req.code, x_admin_token)
        name = req.student_name.strip()
        info = await asyncio.to_thread(student_info, name)
        if not info:
            return {"success": False, "detail": "명단에 없는 이름이에요."}
        if not info["korean"]:
            return {"success": False, "detail": "클리닉은 국어 수강생만 할 수 있어요."}
        r = await asyncio.to_thread(open_run, name)
        if r:
            rid, run = r
            prog = await asyncio.to_thread(_program, run["program_id"])
            return {"success": True, "student_name": name, "run": run_view(rid, run, prog)}
        p = await asyncio.to_thread(find_program_for, name, info["class_name"])
        if not p:
            return {"success": True, "student_name": name, "run": None, "program": None}
        return {"success": True, "student_name": name, "run": None, "program": program_card(*p)}

    @app.post("/api/clinic/kiosk/start")
    async def kiosk_start(req: KioskReq, x_admin_token: Optional[str] = Header(None)):
        """[1단계 문제 출력] — 클리닉을 시작하고 1단계 문제지를 복사기로 보낸다."""
        need_kiosk(req.code, x_admin_token)
        name = req.student_name.strip()
        info = await asyncio.to_thread(student_info, name)
        if not info or not info["korean"]:
            return {"success": False, "detail": "클리닉을 시작할 수 없는 이름이에요."}
        if await asyncio.to_thread(open_run, name):
            return {"success": False, "detail": "이미 시작한 클리닉이 있어요. 이름을 다시 눌러 이어서 하세요."}
        p = await asyncio.to_thread(find_program_for, name, info["class_name"])
        if not p:
            return {"success": False, "detail": "오늘 준비된 클리닉이 없어요. 원장님께 말씀해주세요."}
        pid, prog = p
        db = _db()
        run = {"program_id": pid, "program_title": prog.get("title", ""), "student_name": name, "school": info["school"],
               "grade": info["grade"], "class_name": info["class_name"], "date": _today(), "started_at": _now(),
               "path": ["main"], "cur": "main", "step": "solve", "sets": {"main": {"printed_at": _now()}}, "finished_at": ""}
        _, ref = await asyncio.to_thread(lambda: db.collection(RUNS_COLL).add(run))
        await asyncio.to_thread(_queue_print, ref.id, name, "set", "main", prog["sets"]["main"]["pdf_url"])
        H["send_telegram_message"](f"🩺 [클리닉 등원]\n{name} — '{prog.get('title','')}' 1단계 문제지를 출력했습니다.")
        return {"success": True, "run": run_view(ref.id, run, prog)}

    @app.post("/api/clinic/kiosk/answer")
    async def kiosk_answer(req: KioskReq, x_admin_token: Optional[str] = Header(None)):
        """답 입력. 처음 풀이(step=solve)면 전체 채점, 다시 풀이(step=hint)면 틀렸던 문제만 채점."""
        need_kiosk(req.code, x_admin_token)
        rid, run, prog = await asyncio.to_thread(load_run_for, req.student_name.strip())
        cur = run["cur"]
        qs = ((prog.get("sets") or {}).get(cur) or {}).get("questions", [])
        st = run["sets"].setdefault(cur, {})
        ans = {str(k): _s(v, 4) for k, v in (req.answers or {}).items()}
        if run["step"] == "solve":
            if not qs:
                st["first"] = {"answers": {}, "wrong": [], "score": 0, "correct": 0, "total": 0, "at": _now()}
                run["step"] = "next"
            else:
                wrong = [q["no"] for q in qs if ans.get(q["no"], "") != q["answer"]]
                correct = len(qs) - len(wrong)
                st["first"] = {"answers": ans, "wrong": wrong, "correct": correct, "total": len(qs),
                               "score": round(correct / len(qs) * 100), "at": _now()}
                run["step"] = "reason" if wrong else "next"
        elif run["step"] == "hint":
            wrong = (st.get("first") or {}).get("wrong", [])
            amap = {q["no"]: q["answer"] for q in qs}
            fixed = [n for n in wrong if ans.get(n, "") == amap.get(n)]
            still = [n for n in wrong if n not in fixed]
            st["second"] = {"answers": ans, "fixed": fixed, "still": still, "at": _now()}
            run["step"] = "ask" if still else "next"
        else:
            return {"success": False, "detail": "지금은 답을 입력하는 단계가 아니에요."}
        await asyncio.to_thread(save_run, rid, run)
        return {"success": True, "run": run_view(rid, run, prog)}

    @app.post("/api/clinic/kiosk/reasons")
    async def kiosk_reasons(req: KioskReq, x_admin_token: Optional[str] = Header(None)):
        need_kiosk(req.code, x_admin_token)
        rid, run, prog = await asyncio.to_thread(load_run_for, req.student_name.strip())
        if run["step"] != "reason":
            return {"success": False, "detail": "지금은 이유를 고르는 단계가 아니에요."}
        st = run["sets"][run["cur"]]
        wrong = (st.get("first") or {}).get("wrong", [])
        reasons = {str(k): _s(v, 30) for k, v in (req.reasons or {}).items() if str(k) in wrong and _s(v) in REASONS}
        missing = [n for n in wrong if n not in reasons]
        if missing:
            return {"success": False, "detail": f"{', '.join(missing)}번 문제의 이유도 골라 주세요."}
        st["reasons"] = reasons
        run["step"] = "hint"
        await asyncio.to_thread(save_run, rid, run)
        return {"success": True, "run": run_view(rid, run, prog)}

    @app.post("/api/clinic/kiosk/print")
    async def kiosk_print(req: KioskReq, x_admin_token: Optional[str] = Header(None)):
        """which = hint(해설지) | set(지금 문제지 다시 출력)"""
        need_kiosk(req.code, x_admin_token)
        rid, run, prog = await asyncio.to_thread(load_run_for, req.student_name.strip())
        cur = run["cur"]
        st = run["sets"].setdefault(cur, {})
        if req.which == "hint":
            if run["step"] not in ("hint", "ask", "next"):
                return {"success": False, "detail": "해설지는 이유를 고른 다음에 출력할 수 있어요."}
            await asyncio.to_thread(_queue_print, rid, run["student_name"], "hint", cur, f"/api/clinic/run/{rid}/hint.pdf?set={cur}")
            st["hint_printed_at"] = _now()
        else:
            await asyncio.to_thread(_queue_print, rid, run["student_name"], "set", cur, prog["sets"][cur]["pdf_url"])
            st["printed_at"] = _now()
        await asyncio.to_thread(save_run, rid, run)
        return {"success": True, "run": run_view(rid, run, prog)}

    @app.post("/api/clinic/kiosk/ask")
    async def kiosk_ask(req: KioskReq, x_admin_token: Optional[str] = Header(None)):
        """다시 풀어도 틀린 문제 → 국최 선생님께 질문 (질문 게시판에 올라가고 원장님께 알림)."""
        need_kiosk(req.code, x_admin_token)
        rid, run, prog = await asyncio.to_thread(load_run_for, req.student_name.strip())
        if run["step"] != "ask":
            return {"success": False, "detail": "지금은 질문하는 단계가 아니에요."}
        st = run["sets"][run["cur"]]
        still = (st.get("second") or {}).get("still", [])
        if not H["is_preview"](run["student_name"]):
            st["question_id"] = await asyncio.to_thread(post_question, run, prog, run["cur"], still)
        st["asked"] = still
        run["step"] = "next"
        await asyncio.to_thread(save_run, rid, run)
        return {"success": True, "run": run_view(rid, run, prog)}

    @app.post("/api/clinic/kiosk/next")
    async def kiosk_next(req: KioskReq, x_admin_token: Optional[str] = Header(None)):
        """점수에 따라 다음 문제지(낮은/높은 레벨)를 출력하거나, 클리닉을 마친다."""
        need_kiosk(req.code, x_admin_token)
        rid, run, prog = await asyncio.to_thread(load_run_for, req.student_name.strip())
        if run["step"] != "next":
            return {"success": False, "detail": "아직 이번 문제지를 마치지 않았어요."}
        H["add_xp"](run["student_name"], XP_SET_DONE)
        nxt, _ = decide_next(run, prog)
        if not nxt:
            await asyncio.to_thread(finish_run, rid, run, prog)
            await asyncio.to_thread(save_run, rid, run)
            return {"success": True, "run": run_view(rid, run, prog), "finished": True}
        run["path"].append(nxt)
        run["cur"], run["step"] = nxt, "solve"
        run["sets"][nxt] = {"printed_at": _now()}
        await asyncio.to_thread(_queue_print, rid, run["student_name"], "set", nxt, prog["sets"][nxt]["pdf_url"])
        await asyncio.to_thread(save_run, rid, run)
        return {"success": True, "run": run_view(rid, run, prog)}

    @app.get("/api/clinic/run/{run_id}/hint.pdf")
    def hint_pdf(run_id: str, set: str = "main", code: str = "", x_admin_token: Optional[str] = Header(None)):
        from fastapi.responses import Response
        need_kiosk(code, x_admin_token)
        d = _db().collection(RUNS_COLL).document(run_id).get()
        if not d.exists or set not in SET_KEYS:
            raise HTTPException(status_code=404, detail="없는 기록입니다.")
        run = d.to_dict() or {}
        pdf = build_hint_pdf(run, _program(run["program_id"]), set)
        fname = urllib.parse.quote(f"해설지_{run.get('student_name','')}.pdf")
        return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename*=UTF-8''{fname}"})

    # ── 자동출력 프로그램용 ──
    @app.get("/api/clinic/print_jobs")
    def print_jobs(code: str = "", status: str = "pending", x_admin_token: Optional[str] = Header(None)):
        if not kiosk_ok(code, x_admin_token):
            return {"success": False, "jobs": []}
        rows = [{"id": d.id, **(d.to_dict() or {})} for d in _db().collection(JOBS_COLL).stream()]
        rows = [r for r in rows if not status or r.get("status") == status]
        rows.sort(key=lambda r: r.get("created_at", ""))
        return {"success": True, "jobs": rows[:50]}

    @app.post("/api/clinic/print_jobs/{job_id}/done")
    def print_job_done(job_id: str, req: PrintDoneReq, x_admin_token: Optional[str] = Header(None)):
        if not kiosk_ok(req.code, x_admin_token):
            return {"success": False}
        ref = _db().collection(JOBS_COLL).document(job_id)
        if not ref.get().exists:
            return {"success": False}
        ref.set({"status": "printed" if req.ok else "failed", "done_at": _now(), "note": _s(req.note, 200)}, merge=True)
        if not req.ok:
            H["send_telegram_message"](f"🖨 [클리닉 출력 실패]\n{(ref.get().to_dict() or {}).get('student_name','')}: {_s(req.note, 100)}")
        return {"success": True}

    # ══════════ 관리자 ══════════
    @app.post("/api/admin/clinic/programs", dependencies=[Depends(verify_admin)])
    async def admin_prog_save(id: str = Form(""), title: str = Form(""), intro: str = Form(""),
                              class_names: str = Form("[]"), student_names: str = Form("[]"),
                              start_date: str = Form(""), end_date: str = Form(""),
                              pass_score: int = Form(70), low_pass_score: int = Form(70), hint_mode: str = Form("focus"),
                              main_pdf: UploadFile = File(None), main_json: UploadFile = File(None), main_text: str = Form(""),
                              low_pdf: UploadFile = File(None), low_json: UploadFile = File(None), low_text: str = Form(""),
                              high_pdf: UploadFile = File(None), high_json: UploadFile = File(None), high_text: str = Form("")):
        """클리닉 프로그램 만들기(또는 고치기). 문제지마다 PDF(출력용) + .json 또는 글(정답·해설)."""
        db = _db()
        old = _program(id) if id else {}
        sets = dict(old.get("sets") or {})
        report = {}
        files = {"main": (main_pdf, main_json, main_text), "low": (low_pdf, low_json, low_text), "high": (high_pdf, high_json, high_text)}
        guess_title = ""
        for k, (pdf, js, text) in files.items():
            has_pdf = bool(pdf and pdf.filename)
            if not has_pdf and not (js and js.filename) and not text.strip():
                continue
            if not has_pdf and not sets.get(k):
                return {"success": False, "detail": f"{SET_LABEL[k]}의 PDF를 골라주세요."}
            entry = dict(sets.get(k) or {})
            if has_pdf:
                raw = await pdf.read()
                if not raw.startswith(b"%PDF"):
                    return {"success": False, "detail": f"{SET_LABEL[k]}: PDF 파일이 아닙니다."}
                entry["pdf_url"] = await asyncio.to_thread(H["save_bytes"], raw, pdf.filename, "clinic_sheets", "application/pdf")
                entry["pdf_name"] = pdf.filename
            if js and js.filename:
                t2, jt = _text_from_json(await js.read())
                text = text or t2
                guess_title = guess_title or (jt if k == "main" else "")
            if text.strip():
                built = await asyncio.to_thread(build_set, text, hint_mode)
                entry.update(built)
            entry.setdefault("questions", [])
            entry.setdefault("total", 0)
            entry.setdefault("written", [])
            entry.setdefault("no_answer", [])
            sets[k] = entry
            report[k] = {"graded": len(entry["questions"]), "total": entry["total"], "written": entry["written"], "no_answer": entry["no_answer"]}
        if not sets.get("main"):
            return {"success": False, "detail": "1단계 문제지(PDF)는 꼭 올려야 해요."}
        try:
            cls = [c for c in json.loads(class_names or "[]") if _s(c)]
            studs = [c for c in json.loads(student_names or "[]") if _s(c)]
        except Exception:
            cls, studs = [], []
        doc = {**old, "title": _s(title) or old.get("title") or guess_title or "클리닉", "intro": _s(intro, 1500),
               "class_names": cls, "student_names": studs, "start_date": _s(start_date) or old.get("start_date") or _today(),
               "end_date": _s(end_date), "pass_score": max(0, min(100, int(pass_score))),
               "low_pass_score": max(0, min(100, int(low_pass_score))), "hint_mode": "explain" if hint_mode == "explain" else "focus",
               "sets": sets, "active": old.get("active", True), "created_at": old.get("created_at") or _now(), "updated_at": _now()}
        if id and old:
            await asyncio.to_thread(lambda: db.collection(PROGRAMS_COLL).document(id).set(doc))
            pid = id
        else:
            _, ref = await asyncio.to_thread(lambda: db.collection(PROGRAMS_COLL).add(doc))
            pid = ref.id
        return {"success": True, "id": pid, "title": doc["title"], "report": report}

    @app.get("/api/admin/clinic/programs", dependencies=[Depends(verify_admin)])
    def admin_prog_list():
        db = _db()
        stats = {}
        for d in db.collection(RUNS_COLL).stream():
            r = d.to_dict() or {}
            s = stats.setdefault(r.get("program_id"), {"started": [], "done": []})
            s["started"].append(r.get("student_name"))
            if r.get("finished_at"):
                s["done"].append(r.get("student_name"))
        rows = []
        for d in db.collection(PROGRAMS_COLL).stream():
            p = d.to_dict() or {}
            sets = p.get("sets") or {}
            rows.append({"id": d.id, **{k: p.get(k) for k in ("title", "intro", "class_names", "student_names", "start_date", "end_date",
                                                                "pass_score", "low_pass_score", "hint_mode", "active", "created_at")},
                         "sets": {k: {"label": SET_LABEL[k], "pdf_url": v.get("pdf_url", ""), "pdf_name": v.get("pdf_name", ""),
                                      "graded": len(v.get("questions", [])), "total": v.get("total", 0), "written": v.get("written", []),
                                      "no_answer": v.get("no_answer", [])} for k, v in sets.items()},
                         **stats.get(d.id, {"started": [], "done": []})})
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return {"success": True, "rows": rows, "today": _today()}

    @app.get("/api/admin/clinic/program/{pid}", dependencies=[Depends(verify_admin)])
    def admin_prog_get(pid: str):
        p = _program(pid)
        if not p:
            return {"success": False, "detail": "없는 프로그램입니다."}
        return {"success": True, "program": {"id": pid, **p}}

    @app.post("/api/admin/clinic/programs/update", dependencies=[Depends(verify_admin)])
    def admin_prog_update(req: ProgUpdateReq):
        db = _db()
        ref = db.collection(PROGRAMS_COLL).document(req.id)
        doc = ref.get()
        if not doc.exists:
            return {"success": False, "detail": "없는 프로그램입니다."}
        if req.delete:
            ref.delete()
            return {"success": True}
        p = doc.to_dict() or {}
        for k in ("title", "intro", "class_names", "student_names", "start_date", "end_date", "pass_score", "low_pass_score", "active"):
            v = getattr(req, k)
            if v is not None:
                p[k] = v
        # 정답·주목할 점 고치기
        for sk, edits in (req.questions or {}).items():
            qs = ((p.get("sets") or {}).get(sk) or {}).get("questions", [])
            emap = {str(e.get("no")): e for e in edits or []}
            for q in qs:
                e = emap.get(q["no"])
                if e:
                    a = re.sub(r"[^1-5]", "", str(e.get("answer", q["answer"])))[:1]
                    q["answer"] = a or q["answer"]
                    q["hint"] = _s(e.get("hint", q.get("hint")), 400)
        p["updated_at"] = _now()
        ref.set(p)
        return {"success": True}

    @app.get("/api/admin/clinic/runs", dependencies=[Depends(verify_admin)])
    def admin_runs(date: str = ""):
        day = date.strip() or _today()
        rows = []
        for d in _db().collection(RUNS_COLL).stream():
            r = d.to_dict() or {}
            active_today = (r.get("updated_at") or r.get("started_at") or "")[:10] == day or r.get("date") == day
            if not active_today and not (not r.get("finished_at") and day == _today()):
                continue
            sets = []
            for k in r.get("path", []):
                s = (r.get("sets") or {}).get(k) or {}
                f, sec = s.get("first") or {}, s.get("second") or {}
                sets.append({"label": SET_LABEL[k], "score": f.get("score"), "wrong": f.get("wrong", []),
                             "reasons": s.get("reasons", {}), "fixed": sec.get("fixed", []), "still": sec.get("still", []),
                             "asked": s.get("asked", []), "printed": bool(s.get("printed_at")), "hint_printed": bool(s.get("hint_printed_at"))})
            rows.append({"id": d.id, "student_name": r.get("student_name"), "class_name": r.get("class_name", ""),
                         "program_title": r.get("program_title", ""), "cur_label": SET_LABEL.get(r.get("cur", "main")),
                         "step": r.get("step"), "started_at": r.get("started_at", ""), "finished_at": r.get("finished_at", ""),
                         "summary": r.get("summary", ""), "sets": sets})
        rows.sort(key=lambda x: (x["finished_at"] != "", x["started_at"]))
        return {"success": True, "date": day, "rows": rows}

    @app.post("/api/admin/clinic/runs/reset", dependencies=[Depends(verify_admin)])
    def admin_run_reset(req: RunReq):
        """학생의 진행 중인 클리닉을 지운다 (잘못 눌렀을 때 처음부터 다시)."""
        if req.delete:
            _db().collection(RUNS_COLL).document(req.id).delete()
        return {"success": True}

    @app.get("/api/admin/clinic/parent_lines", dependencies=[Depends(verify_admin)])
    def admin_parent_lines(date: str = ""):
        day = date.strip() or _today()
        lines = []
        for d in _db().collection(RUNS_COLL).stream():
            r = d.to_dict() or {}
            if (r.get("finished_at") or "")[:10] != day:
                continue
            lines.append({"student_name": r.get("student_name"), "class_name": r.get("class_name", ""),
                          "text": f"[로지에듀 클리닉] {r.get('student_name')} 학생 오늘 클리닉({r.get('program_title','')}): {r.get('summary','')}"})
        lines.sort(key=lambda x: (x["class_name"], x["student_name"]))
        return {"success": True, "date": day, "lines": lines}

    @app.get("/api/admin/clinic/config", dependencies=[Depends(verify_admin)])
    def admin_config_get():
        return {"success": True, "config": load_config(), "reasons": REASONS}

    @app.post("/api/admin/clinic/config", dependencies=[Depends(verify_admin)])
    def admin_config_set(req: ConfigReq):
        _db().collection("settings").document(CONFIG_DOC).set({"kiosk_code": _s(req.kiosk_code, 40)}, merge=True)
        return {"success": True, "config": load_config()}

    @app.get("/api/admin/clinic/preview_for", dependencies=[Depends(verify_admin)])
    def admin_preview_for(student_name: str):
        info = student_info(student_name)
        if not info:
            return {"success": False, "detail": "명단에 없는 이름입니다."}
        r = open_run(student_name)
        if r:
            return {"success": True, "text": f"진행 중: {r[1].get('program_title','')} · {SET_LABEL.get(r[1].get('cur','main'))}"}
        p = find_program_for(student_name, info["class_name"])
        return {"success": True, "text": f"지금 오면: {p[1].get('title','')}" if p else "지금 나갈 클리닉 프로그램이 없습니다."}
