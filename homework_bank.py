"""과제 · 클리닉으로 올린 문제를 문제 보관함(questions)에도 남긴다 (2026-11-22).

원장님은 Claude에서 만든 문제 글을 붙여 넣어 정답 · 해설을 꺼낸 뒤(extract_from_bank)
과제 · 클리닉으로 올린다(create_homework). 예전에는 정답 · 해설만 과제에 남고 문제 글은
버려져 다시 쓸 수 없었다. 이제는

  1) 붙여 넣는 순간 그 글을 보관함에 '과제 연결 대기'로 넣고(같은 글이면 새로 만들지 않는다),
  2) 과제를 올리면 정답 · 해설이 맞는 대기 자료를 찾아 그 과제 이름 · 반 · 유형을 붙인다.

화면은 고치지 않아도 된다. 화면이 bank_id 를 함께 보내 주면 그것을 먼저 믿는다.
여기에는 DB를 만지지 않는 계산만 둔다(시험하기 쉽게).
"""
import hashlib
import re
from datetime import datetime, timedelta

ORIGIN = "homework_paste"
PENDING_HOURS = 6            # 붙여 넣고 이 시간 안에 올린 과제만 자동으로 잇는다
TITLE_MAX = 40
_FMT = "%Y-%m-%d %H:%M:%S"


def content_key(content: str) -> str:
    """같은 글인지 가리는 열쇠. 띄어쓰기 · 줄바꿈 차이는 무시한다."""
    norm = re.sub(r"\s+", " ", content or "").strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def guess_title(content: str, now: datetime) -> str:
    """과제와 잇기 전 임시 제목: 글의 첫 줄(안내 문구 · 머리표는 건너뜀)."""
    for line in (content or "").splitlines():
        s = re.sub(r"^[#\s※\-*>]+", "", line).strip()
        if not s or s.startswith("다음") or re.fullmatch(r"\[[^\]]*\]", s):
            continue
        return s[:TITLE_MAX]
    return f"과제 붙여넣기 {now.strftime('%m/%d %H:%M')}"


def _norm_answer(v) -> str:
    s = str(v if v is not None else "").strip()
    for i, ch in enumerate("①②③④⑤"):
        s = s.replace(ch, str(i + 1))
    return re.sub(r"\s+", "", s)


def _expl_head(v) -> str:
    return re.sub(r"\s+", "", str(v or ""))[:40]


def fingerprint(answer_list, explanations) -> dict:
    """과제와 견줄 때 쓰는 요약: 정답 목록 + 해설 앞부분."""
    return {
        "answers": [_norm_answer(a) for a in (answer_list or [])],
        "expl": {str(k): _expl_head(v) for k, v in (explanations or {}).items() if _expl_head(v)},
    }


def match_score(fp: dict, answer_list, explanations) -> float:
    """대기 자료(fp)와 지금 올리는 과제가 같은 문제인지 0~1 점수. 0이면 다른 문제."""
    a = [_norm_answer(x) for x in (answer_list or [])]
    b = list((fp or {}).get("answers") or [])
    if not a or len(a) != len(b):
        return 0.0
    filled = [i for i in range(len(a)) if a[i] and b[i]]
    ans = sum(a[i] == b[i] for i in filled) / len(filled) if filled else 0.0
    mine = {str(k): _expl_head(v) for k, v in (explanations or {}).items() if _expl_head(v)}
    theirs = (fp or {}).get("expl") or {}
    shared = [k for k in mine if k in theirs]
    if shared:
        exp = sum(mine[k] == theirs[k] for k in shared) / len(shared)
        if exp < 0.5:
            return 0.0
        return (ans + exp) / 2 if filled else exp
    return ans if ans >= 0.8 else 0.0


def is_fresh(pending_at: str, now: datetime) -> bool:
    try:
        t = datetime.strptime(str(pending_at or ""), _FMT)
    except ValueError:
        return False
    return timedelta(0) <= now - t <= timedelta(hours=PENDING_HOURS)


def pick_pending(rows, answer_list, explanations, now: datetime):
    """대기 중인 보관함 자료 [{id, pending_at, fp}] 가운데 이 과제와 맞는 것의 id (없으면 '')."""
    best, best_key = "", None
    for r in rows or []:
        if not is_fresh(r.get("pending_at"), now):
            continue
        score = match_score(r.get("fp") or {}, answer_list, explanations)
        if score <= 0:
            continue
        key = (score, str(r.get("pending_at") or ""))
        if best_key is None or key > best_key:
            best, best_key = str(r.get("id") or ""), key
    return best


def link_fields(prev: dict, hw_title: str, kind_label: str, target_classes, subject: str, tags, now: datetime,
                old_title: str = "") -> dict:
    """보관함 자료에 얹을 과제 정보. 한 글을 여러 과제(수업 · 클리닉)로 낼 수 있어 목록으로 쌓는다."""
    titles = [t for t in (prev.get("homework_titles") or []) if t and t != old_title]
    if hw_title not in titles:
        titles.append(hw_title)
    classes = list(dict.fromkeys(list(prev.get("target_classes") or []) + list(target_classes or [])))
    merged_tags = list(dict.fromkeys(list(prev.get("tags") or []) + [t for t in (tags or []) if t]))
    return {
        "title": f"[{kind_label}] {hw_title}"[:120],
        "subject": subject,
        "homework_titles": titles,
        "target_classes": classes,
        "tags": merged_tags,
        "pending_link": False,
        "linked_at": now.strftime(_FMT),
    }


def tags_from_qmeta(qmeta) -> list:
    """과제의 문항별 유형(qmeta {"1": {"tag": ...}})을 모은다."""
    out = []
    for v in (qmeta or {}).values():
        t = str((v or {}).get("tag") or "").strip() if isinstance(v, dict) else ""
        if t and t not in out:
            out.append(t)
    return out
