"""설문조사: 원장님이 질문을 만들어 학생(반 · 학생 지정)에게 보내고, 학생이 답하면 모아 본다.

계산만 한다(DB 없음). main.py 의 /api/admin/survey* · /api/student/survey* 가 부른다.
질문 종류
  single  하나 고르기       multi  여러 개 고르기
  scale   1~5 점수          text   글로 쓰기
"""
import re
import uuid
from typing import Dict, Iterable, List

KINDS = {"single": "하나 고르기", "multi": "여러 개 고르기", "scale": "1~5 점수", "text": "글로 쓰기"}
MAX_QUESTIONS = 30
MAX_OPTIONS = 12


def normalize_questions(raw) -> List[dict]:
    """[{id?, kind, text, options, required}] → 깨끗한 질문 목록. 질문 글이 없거나 고르기인데 보기가 2개 미만이면 뺀다."""
    out, seen = [], set()
    for q in (raw or [])[:MAX_QUESTIONS]:
        if not isinstance(q, dict):
            continue
        text = re.sub(r"\s+", " ", str(q.get("text") or "")).strip()[:300]
        kind = q.get("kind") if q.get("kind") in KINDS else "single"
        if not text:
            continue
        opts = []
        if kind in ("single", "multi"):
            for o in q.get("options") or []:
                o = re.sub(r"\s+", " ", str(o or "")).strip()[:100]
                if o and o not in opts:
                    opts.append(o)
            opts = opts[:MAX_OPTIONS]
            if len(opts) < 2:
                continue
        qid = str(q.get("id") or "").strip()
        if not re.fullmatch(r"[a-z0-9]{4,16}", qid) or qid in seen:
            qid = uuid.uuid4().hex[:8]
        seen.add(qid)
        out.append({"id": qid, "kind": kind, "text": text, "options": opts, "required": bool(q.get("required", True))})
    return out


def clean_answers(questions: List[dict], raw) -> Dict[str, object]:
    """학생이 보낸 답 → 질문에 맞는 것만. 고르기는 보기 번호(0부터), 점수는 1~5, 글은 500자."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for q in questions:
        v = raw.get(q["id"])
        if q["kind"] == "single":
            try:
                i = int(v)
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(q["options"]):
                out[q["id"]] = i
        elif q["kind"] == "multi":
            vals = v if isinstance(v, list) else []
            picked = sorted({int(x) for x in vals if str(x).lstrip("-").isdigit() and 0 <= int(x) < len(q["options"])})
            if picked:
                out[q["id"]] = picked
        elif q["kind"] == "scale":
            try:
                i = int(v)
            except (TypeError, ValueError):
                continue
            if 1 <= i <= 5:
                out[q["id"]] = i
        else:
            t = str(v or "").strip()[:500]
            if t:
                out[q["id"]] = t
    return out


def missing_required(questions: List[dict], answers: Dict[str, object]) -> List[int]:
    """답하지 않은 필수 질문 번호(1부터)."""
    return [i + 1 for i, q in enumerate(questions) if q.get("required") and q["id"] not in answers]


def summary(questions: List[dict], rows: Iterable[dict], audience: Iterable[str], anonymous: bool = False) -> Dict:
    """원장님 화면: 질문마다 보기별 수 · 점수 평균 · 글 답, 답한 학생, 아직 안 한 학생."""
    rows = [r for r in rows or [] if str(r.get("student_name") or "").strip()]
    per = []
    for q in questions:
        item = {"id": q["id"], "kind": q["kind"], "text": q["text"], "options": q["options"], "count": 0}
        if q["kind"] in ("single", "multi"):
            counts = [0] * len(q["options"])
            who = [[] for _ in q["options"]]
            for r in rows:
                v = (r.get("answers") or {}).get(q["id"])
                picks = v if isinstance(v, list) else ([v] if isinstance(v, int) else [])
                if picks:
                    item["count"] += 1
                for i in picks:
                    if isinstance(i, int) and 0 <= i < len(counts):
                        counts[i] += 1
                        who[i].append(r["student_name"])
            item["counts"] = counts
            if not anonymous:
                item["who"] = who
        elif q["kind"] == "scale":
            dist = [0] * 5
            for r in rows:
                v = (r.get("answers") or {}).get(q["id"])
                if isinstance(v, int) and 1 <= v <= 5:
                    dist[v - 1] += 1
            n = sum(dist)
            item["count"] = n
            item["dist"] = dist
            item["avg"] = round(sum((i + 1) * c for i, c in enumerate(dist)) / n, 2) if n else None
        else:
            texts = []
            for r in rows:
                v = (r.get("answers") or {}).get(q["id"])
                if isinstance(v, str) and v.strip():
                    texts.append({"name": "" if anonymous else r["student_name"], "text": v})
            item["count"] = len(texts)
            item["texts"] = texts
        per.append(item)
    answered = sorted({r["student_name"] for r in rows})
    aud = sorted(set(audience or []))
    return {"questions": per, "answered": [] if anonymous else answered, "answered_count": len(answered),
            "missing": [n for n in aud if n not in set(answered)], "audience_count": len(aud)}
