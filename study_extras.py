"""문항별 유형 · 요약 해설 · 해설 영상, 오답 원인 점검, 매일 유형 문제.

DB 없이 돌아가는 계산만 둔다(따로 시험할 수 있게). DB 읽기 · 쓰기는 main.py 가 한다.

① 문항 정보(qmeta): {"1": {"tag": "추론", "summary": "한 줄 요약", "video": "https://..."}}
   - tag      문항 유형. 매일 유형 문제를 고를 때 쓴다.
   - summary  요약 해설(짧게). 자세한 해설은 예전부터 있던 explanation 칸이 맡는다.
   - video    해설 영상 주소(유튜브 · 동영상 링크).
② 오답 원인(reason): 학생이 틀린 문항마다 고른다.
   guess   하나도 몰라서 찍었다       → 개념부터. 같은 유형을 많이 다시 푼다.
   two     둘 중 하나에서 고민했다     → 두 선택지의 차이를 짚는다. 같은 유형을 조금 더.
   misread 문제를 잘못 봤다          → 실력보다 습관. 발문 · 조건 읽기 점검. 유형 문제는 적게.
③ 매일 유형 문제: 틀린 유형(원인으로 무게를 둔다)에서 하루 몇 문제씩만 낸다.
"""
import hashlib
import re
import json
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

TAG_MAX = 30
SUMMARY_MAX = 400
VIDEO_MAX = 300

REASONS = {
    "guess": "하나도 몰라서 찍었어요",
    "two": "둘 중에서 고민하다 틀렸어요",
    "misread": "문제를 잘못 봤어요",
}
# 원인별로 그 유형을 얼마나 더 풀게 할지(약점 무게)
REASON_WEIGHT = {"guess": 3.0, "two": 2.0, "misread": 0.5}
DEFAULT_WRONG_WEIGHT = 1.5      # 원인을 아직 안 고른 오답
UNSURE_WEIGHT = 2.5             # '모름'으로 낸 문항(=사실상 찍기 전 단계)

DAILY_DEFAULT = 3
DAILY_MAX = 10

# 유형 칸에 띄워 줄 보기(자유롭게 적어도 된다). 국어는 출제기(question_maker)의 유형 목록과 맞춘다.
TAG_SUGGESTIONS = {
    "korean": ["사실적 이해", "중심 내용·주제", "구조·전개", "추론", "비판", "적용([보기])", "개념 비교", "어휘·문맥",
               "화자·서술자", "시어·소재", "표현상 특징", "정서·태도", "인물·서사", "외적 준거", "작품 비교",
               "문법-음운", "문법-형태", "문법-통사", "문법-의미·담화", "화법", "작문"],
    "math": ["계산", "식의 변형", "방정식·부등식", "함수와 그래프", "도형", "경우의 수·확률", "통계", "수열",
             "지수·로그", "삼각함수", "극한·연속", "미분", "적분", "개념 이해", "서술형 풀이"],
    "english": ["어휘", "어법", "주제·요지", "제목", "빈칸 추론", "순서 배열", "문장 삽입", "무관한 문장",
                "내용 일치", "요약문", "지칭 추론", "심경·분위기", "장문 독해"],
}


def clean_tag(v) -> str:
    t = re.sub(r"\s+", " ", str(v or "")).strip()
    return t[:TAG_MAX]


def clean_video(v) -> str:
    """해설 영상 주소: http(s) 로 시작하는 것만 받는다."""
    t = str(v or "").strip()
    if not t:
        return ""
    if not re.match(r"^https?://", t, re.I):
        t = "https://" + t if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", t, re.I) else ""
    return t[:VIDEO_MAX]


def youtube_id(url: str) -> str:
    """유튜브 주소면 영상 id(11자), 아니면 빈 글자."""
    t = str(url or "").strip()
    m = re.search(r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/))([A-Za-z0-9_-]{11})", t)
    return m.group(1) if m else ""


def clean_meta_entry(e) -> dict:
    if not isinstance(e, dict):
        return {}
    out = {}
    tag = clean_tag(e.get("tag"))
    summary = str(e.get("summary") or "").strip()[:SUMMARY_MAX]
    video = clean_video(e.get("video"))
    if tag:
        out["tag"] = tag
    if summary:
        out["summary"] = summary
    if video:
        out["video"] = video
    return out


def parse_meta_map(raw) -> Dict[str, dict]:
    """{"1": {...}} 꼴로 맞춘다. 번호가 아니거나 빈 항목은 버린다."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        try:
            n = int(str(k).strip())
        except ValueError:
            continue
        if n < 1:
            continue
        e = clean_meta_entry(v)
        if e:
            out[str(n)] = e
    return out


def merge_meta(old: Dict[str, dict], incoming_raw, replace: bool = False) -> Dict[str, dict]:
    """관리자가 보낸 문항 정보를 얹는다. 보낸 칸이 빈 글자면 그 칸을 지운다."""
    merged = {} if replace else {k: dict(v) for k, v in (old or {}).items()}
    if not isinstance(incoming_raw, dict):
        return merged
    for k, v in incoming_raw.items():
        try:
            n = int(str(k).strip())
        except ValueError:
            continue
        if n < 1 or not isinstance(v, dict):
            continue
        cur = merged.get(str(n), {})
        cleaned = clean_meta_entry(v)
        for field in ("tag", "summary", "video"):
            if field in v:                       # 보낸 칸만 바꾼다
                if cleaned.get(field):
                    cur[field] = cleaned[field]
                else:
                    cur.pop(field, None)
        if cur:
            merged[str(n)] = cur
        else:
            merged.pop(str(n), None)
    return merged


def quiz_question_meta(q: dict) -> dict:
    """퀴즈 문항 안에 들어 있는 유형 · 요약 · 영상."""
    return clean_meta_entry({"tag": q.get("tag"), "summary": q.get("summary"), "video": q.get("video")})


# ── 오답 원인 ──────────────────────────────────────────────

def reason_feedback(reason: str, tag: str = "", subject: str = "") -> dict:
    """원인에 따라 다른 피드백. {title, tips[], practice}."""
    t = f"'{tag}' 유형" if tag else "이 유형"
    if reason == "guess":
        tips = ["해설을 '자세한 해설'까지 끝까지 읽고, 정답의 근거를 한 줄로 직접 써 보세요.",
                f"{t}의 개념을 먼저 다시 잡아야 해요. 모르는 낱말 · 개념은 AI 국최에게 바로 물어보세요.",
                f"오늘부터 {t} 문제를 조금씩 매일 풀게 됩니다."]
        if subject == "math":
            tips[0] = "해설의 풀이를 그대로 따라 쓰며, 어떤 공식 · 개념을 썼는지 표시해 보세요."
        return {"title": "개념부터 다시 잡아요", "tips": tips, "practice": "많이"}
    if reason == "two":
        tips = ["내가 고른 답과 정답을 나란히 놓고, 어디서 갈렸는지 한 문장으로 적어 보세요.",
                "오답 선택지가 '왜 틀렸는지' 근거를 찾는 연습이 필요해요. 요약 해설을 먼저 보세요.",
                f"{t} 문제를 며칠 동안 조금씩 더 풀게 됩니다."]
        if subject == "math":
            tips[0] = "두 풀이 방법 중 어디서 틀렸는지, 조건 하나하나를 다시 대입해 확인해 보세요."
        return {"title": "거의 다 왔어요. 마지막 한 끗!", "tips": tips, "practice": "조금"}
    if reason == "misread":
        tips = ["발문의 '옳은 것 / 옳지 않은 것', '모두 / 하나'에 동그라미를 치고 푸는 습관을 들여요.",
                "답을 고르기 전에 문제가 묻는 것을 한 번 더 읽어요(3초 점검).",
                "실력보다는 습관 문제예요. 유형 문제는 조금만 더 풀게 됩니다."]
        if subject == "math":
            tips[0] = "조건(정수, 양수, 범위 등)과 구하는 것에 밑줄을 긋고, 답을 낸 뒤 조건을 다시 확인해요."
        if subject == "english":
            tips[0] = "글의 흐름 · 지시어 · 'NOT/true' 같은 발문 표현에 표시를 하고 풀어요."
        return {"title": "실수 방지 습관을 만들어요", "tips": tips, "practice": "적게"}
    return {"title": "", "tips": [], "practice": ""}


# ── 약한 유형 계산 ─────────────────────────────────────────

def _days_ago(when: str, today: date) -> int:
    try:
        d = datetime.strptime(str(when or "")[:10], "%Y-%m-%d").date()
        return max(0, (today - d).days)
    except ValueError:
        return 30


def weak_tags(misses: Iterable[dict], practice_stats: Optional[Dict[str, dict]] = None,
              today: Optional[date] = None) -> List[dict]:
    """틀린 기록 → 약한 유형 순위.

    misses: [{tag, reason?, unsure?, at:'YYYY-MM-DD', subject?}]
    practice_stats: {tag: {right, wrong}} — 매일 문제에서 맞히면 무게가 줄고 틀리면 는다.
    돌려주는 값: [{tag, score, count, reasons:{guess:n,...}, subject}] (점수 높은 순, 0 이하는 뺀다)
    """
    today = today or date.today()
    acc: Dict[str, dict] = {}
    for m in misses or []:
        tag = clean_tag(m.get("tag"))
        if not tag:
            continue
        reason = m.get("reason") or ""
        w = REASON_WEIGHT.get(reason, UNSURE_WEIGHT if m.get("unsure") else DEFAULT_WRONG_WEIGHT)
        age = _days_ago(m.get("at"), today)
        w *= 0.5 ** (age / 21.0)       # 3주마다 절반으로(오래된 오답은 덜 중요)
        a = acc.setdefault(tag, {"tag": tag, "score": 0.0, "count": 0, "reasons": {}, "subject": ""})
        a["score"] += w
        a["count"] += 1
        if reason:
            a["reasons"][reason] = a["reasons"].get(reason, 0) + 1
        if not a["subject"] and m.get("subject"):
            a["subject"] = m["subject"]
    for tag, st in (practice_stats or {}).items():
        if tag in acc:
            right, wrong = int(st.get("right", 0) or 0), int(st.get("wrong", 0) or 0)
            acc[tag]["score"] += 0.8 * wrong - 0.6 * right
    out = [a for a in acc.values() if a["score"] > 0.05]
    for a in out:
        a["score"] = round(a["score"], 2)
    out.sort(key=lambda a: (-a["score"], a["tag"]))
    return out


def pick_daily(weak: List[dict], pool: List[dict], count: int, seed: str,
               solved_right: Iterable[str] = (), avoid: Iterable[str] = ()) -> List[dict]:
    """약한 유형에서 오늘 풀 문제를 고른다.

    pool: [{qid, tag, ...}] (유형이 있는 연습 가능 문항)
    - 약한 유형 순서대로 돌아가며 한 문제씩(한 유형에 몰리지 않게, 점수 높은 유형이 먼저).
    - 매일 문제에서 이미 맞힌 문항은 되도록 빼고(solved_right), 원래 틀렸던 그 문항(avoid)은 마지막에.
    - 같은 날 다시 불러도 같은 문제가 나오게 seed(학생+날짜)로 섞는다.
    """
    count = max(0, min(DAILY_MAX, int(count or 0)))
    if not count or not weak or not pool:
        return []
    right, avoid = set(solved_right or ()), set(avoid or ())

    def order(item):
        h = hashlib.sha1(f"{seed}|{item['qid']}".encode()).hexdigest()
        # 처음 보는 문항 → 원래 틀렸던 문항 → 이미 맞힌 문항 순
        return (item["qid"] in right, item["qid"] in avoid, h)

    by_tag: Dict[str, List[dict]] = {}
    for it in pool:
        by_tag.setdefault(it.get("tag", ""), []).append(it)
    queues = []
    for w in weak:
        cands = sorted(by_tag.get(w["tag"], []), key=order)
        if cands:
            queues.append(cands)
    picked, seen = [], set()
    while len(picked) < count and any(queues):
        for q in queues:
            while q and q[0]["qid"] in seen:
                q.pop(0)
            if q and len(picked) < count:
                it = q.pop(0)
                picked.append(it)
                seen.add(it["qid"])
    return picked


# ─────────────────────────────────────────────────────────
# ④ 유형 자동 붙이기: AI가 문항 글 · 해설을 읽고 정해 둔 유형 목록에서 하나씩 고른다.
#    AI 답은 '보기'일 뿐 — 화면에 채워 두고 원장님이 확인한 뒤 저장한다.
#    목록 밖의 이름은 버린다(같은 유형이 이름만 달라 따로 세지지 않게).
# ─────────────────────────────────────────────────────────
AUTO_TAG_MAX_ITEMS = 80
AUTO_TAG_TEXT_MAX = 900


def _squash(t: str) -> str:
    return re.sub(r"[\s·・ㆍ\-_()\[\]]", "", str(t or "")).lower()


def tag_prompt(subject_label: str, allowed: List[str], items: List[dict], has_file: bool = False) -> str:
    """items: [{no, text, options, answer, explanation}] → AI에게 보낼 글."""
    lines = []
    for it in items[:AUTO_TAG_MAX_ITEMS]:
        part = [f"[{it['no']}번]"]
        if it.get("text"):
            part.append("문제: " + str(it["text"])[:AUTO_TAG_TEXT_MAX])
        opts = [str(o) for o in (it.get("options") or []) if str(o).strip()]
        if opts:
            part.append("보기: " + " / ".join(f"{i + 1}) {o[:120]}" for i, o in enumerate(opts)))
        if it.get("answer"):
            part.append("정답: " + str(it["answer"])[:60])
        if it.get("explanation"):
            part.append("해설: " + str(it["explanation"])[:AUTO_TAG_TEXT_MAX])
        lines.append("\n".join(part))
    file_note = "\n첨부한 그림은 이 자료의 해설지(또는 문제지)입니다. 번호를 맞춰 함께 보세요." if has_file else ""
    return f"""당신은 {subject_label} 교사입니다. 아래 문항마다 '어떤 유형의 문제인지'를 고르세요.

[유형 목록 — 반드시 이 안에서 하나만, 글자 그대로]
{chr(10).join('- ' + t for t in allowed)}

[규칙]
- 문제 글이 없으면 해설·정답·첨부 그림으로 짐작하세요.
- 어떤 유형인지 근거가 부족하면 빈 글자("")로 두세요. 억지로 고르지 마세요.
- 오직 JSON 하나만 출력하세요. 코드블록 표시나 설명을 붙이지 마세요.
- 모양: {{"1": "추론", "2": "어휘·문맥", "3": ""}}{file_note}

[문항]
{chr(10).join(lines)}
"""


def parse_tag_reply(text: str, allowed: List[str], nos: Iterable) -> Dict[str, str]:
    """AI 답(JSON 비슷한 글) → {"1": "추론"}. 목록에 없는 이름 · 없는 번호는 뺀다."""
    raw = str(text or "")
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {}
    body = m.group(0)
    import json as _json
    try:
        data = _json.loads(body)
    except ValueError:
        # "1": "추론" 꼴만 골라 읽는다(따옴표 · 쉼표가 조금 어긋나도)
        data = {k: v for k, v in re.findall(r'"?(\d+)"?\s*:\s*"([^"]*)"', body)}
    if not isinstance(data, dict):
        return {}
    by_key = {_squash(t): t for t in allowed}
    want = {str(n) for n in nos}
    out = {}
    for k, v in data.items():
        no = re.sub(r"\D", "", str(k))
        if no not in want:
            continue
        t = by_key.get(_squash(v))
        if t:
            out[no] = t
    return out


# ─────────────────────────────────────────────────────────
# 해설지 읽기 — 해설 창의 [해설지 사진 · 캡처 · 글로 채우기]
# ─────────────────────────────────────────────────────────
EXPLAIN_PROMPT = """첨부된 자료(사진 · 캡처 · PDF · 글)는 시험의 해설지입니다. 문항마다 해설을 읽어 정리하세요.

[반드시 지킬 것]
- 오직 JSON만 출력하세요. 설명, 인사말, 코드블록 표시(```)를 절대 붙이지 마세요.
- 형식: {"items": {"1": {"answer": 3, "detail": "...", "summary": "...", "tag": "..."}, "2": {...}}}
- 키는 문항 번호(문자열). 자료에 없는 문항은 넣지 마세요. 추측해서 채우지 마세요.
- detail: 자료에 적힌 해설을 빠짐없이 그대로 옮겨 적으세요(줄바꿈 유지, 1200자 이내). ①②③④⑤ 같은 원문자와 <보기> 표기는 그대로 둡니다.
  선지별 풀이(①이 틀린 이유 등)가 있으면 줄을 바꿔 모두 적으세요. 해설이 없으면 빈 글자.
- summary: 학생이 가장 먼저 볼 한두 줄 요약(80자 이내). 정답의 근거를 한 문장으로. 자료에 해설이 없으면 빈 글자.
- answer: 자료에 정답이 보이면 1~5 정수, 안 보이면 넣지 마세요.
- tag: 그 문항이 묻는 유형을 짧게(예: 추론, 내용 일치, 표현상 특징, 어휘, 문법 - 음운 변동). {tags}
- 페이지가 여러 장이면 모두 합쳐 하나의 JSON으로 만드세요. 페이지 경계에서 이어지는 해설은 한 문항으로 합치세요."""


def explain_prompt(known_tags="") -> str:
    """해설지 읽기 지시문. 이미 쓰는 유형 이름이 있으면 그중에서 고르게 한다."""
    if isinstance(known_tags, (list, tuple)):
        raw = list(known_tags)
    else:
        raw = re.split(r"[,\n]", str(known_tags or ""))
    tags = []
    for t in raw:
        t = str(t).strip()
        if t and t not in tags:
            tags.append(t)
    hint = ("이미 쓰는 유형 이름이 있으면 그중에서 고르세요: " + ", ".join(tags[:60])) if tags else "모르면 빈 글자."
    return EXPLAIN_PROMPT.replace("{tags}", hint)


def _clip(v, n):
    t = str(v or "").strip()
    return t if len(t) <= n else t[:n].rstrip() + "…"


def parse_explain_reply(text) -> dict:
    """AI 답(JSON) → {"1": {"detail", "summary", "tag", "answer"?}}. 코드블록 · 군말 · 끝 쉼표가 섞여도 읽는다."""
    raw = str(text or "")
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {}
    blob = m.group(0)
    try:
        parsed = json.loads(blob)
    except ValueError:
        try:
            parsed = json.loads(re.sub(r",\s*([}\]])", r"\1", blob))
        except ValueError:
            return {}
    items = parsed.get("items", parsed) if isinstance(parsed, dict) else None
    if isinstance(items, list):
        items = {str(it.get("no", i + 1)): it for i, it in enumerate(items) if isinstance(it, dict)}
    if not isinstance(items, dict):
        return {}
    out = {}
    for k, v in items.items():
        num = re.search(r"\d+", str(k))
        if not num or not isinstance(v, dict):
            continue
        no = str(int(num.group(0)))
        if no == "0":
            continue
        row = {"detail": _clip(v.get("detail") or v.get("explanation"), 2000),
               "summary": _clip(v.get("summary"), 200), "tag": _clip(v.get("tag"), 30)}
        ans = str(v.get("answer", "")).strip()
        ans = {"①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5"}.get(ans, ans)
        if ans.isdigit() and 1 <= int(ans) <= 5:
            row["answer"] = int(ans)
        if row["detail"] or row["summary"] or row["tag"]:
            out[no] = row
    return out
