"""학생 한눈에 보기 — 학생 앱 성적 + 홈페이지(logyedu.com) 키오스크 출결을 한 줄로 모은다.

계산만 한다(DB · 네트워크 없음). main.py 의 /api/admin/overview 가 부른다.
"""
import re
from typing import Dict, Iterable, List, Optional

SCORED_TYPES = ("모의고사", "타임어택 퀴즈", "과제 제출", "영어 단어 시험")


def name_key(name) -> str:
    """'박서연(고2)', ' 박 서연 ' 처럼 적혀도 같은 학생으로 맞춘다."""
    n = re.sub(r"\(.*?\)|\[.*?\]", "", str(name or ""))
    return re.sub(r"\s+", "", n)


def _num(v) -> Optional[float]:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def score_pct(r: dict) -> Optional[float]:
    got, total = _num(r.get("score")), _num(r.get("total_score"))
    if got is None or not total:
        return None
    return max(0.0, min(100.0, got / total * 100))


def score_text(r: dict) -> str:
    got, total = _num(r.get("score")), _num(r.get("total_score"))
    if got is None:
        return str(r.get("score", "")).strip() or "-"
    fmt = lambda x: str(int(x)) if float(x).is_integer() else str(round(float(x), 1))
    return f"{fmt(got)}/{fmt(total)}" if total else f"{fmt(got)}점"


def build(students: Iterable[dict], reports: Iterable[dict], attendance: Optional[List[dict]]) -> Dict:
    """students: [{name, school, grade, class_name, withdrawn}], reports: 그 달 제출 기록,
    attendance: 홈페이지가 준 학생별 출결(없으면 None)."""
    att = {}
    for a in attendance or []:
        k = name_key(a.get("name"))
        if k:
            att[k] = a

    # 같은 시험을 다시 낸 경우 마지막 것만 센다
    latest = {}
    for r in reports or []:
        if r.get("type") not in SCORED_TYPES:
            continue
        key = (name_key(r.get("student_name")), r.get("type"), str(r.get("task_name", "")))
        if not key[0]:
            continue
        if key not in latest or str(r.get("submitted_at", "")) > str(latest[key].get("submitted_at", "")):
            latest[key] = r
    by_student: Dict[str, List[dict]] = {}
    for (k, _t, _n), r in latest.items():
        by_student.setdefault(k, []).append(r)

    rows, matched = [], set()
    for s in students or []:
        if s.get("withdrawn"):
            continue
        name = str(s.get("name") or s.get("student_name") or "").strip()
        k = name_key(name)
        if not k:
            continue
        reps = sorted(by_student.get(k, []), key=lambda r: str(r.get("submitted_at", "")), reverse=True)
        pcts = [p for p in (score_pct(r) for r in reps) if p is not None]
        a = att.get(k)
        if a:
            matched.add(k)
        rows.append({
            "name": name,
            "school": s.get("school", "") or "",
            "grade": s.get("grade", "") or "",
            "class_name": s.get("class_name", "") or "",
            "tests": len(reps),
            "avg": round(sum(pcts) / len(pcts), 1) if pcts else None,
            "recent": [{"title": str(r.get("task_name", "")), "type": r.get("type", ""), "score": score_text(r),
                        "pct": None if score_pct(r) is None else round(score_pct(r)),
                        "date": str(r.get("submitted_at", ""))[:10]} for r in reps[:4]],
            "attendance": a,
        })
    rows.sort(key=lambda r: (r["class_name"] or "힣", r["name"]))
    kiosk_only = sorted(a.get("name", "") for k, a in att.items() if k not in matched)
    return {"rows": rows, "kiosk_only": kiosk_only}
