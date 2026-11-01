"""학생 한눈에 보기 — 학생 앱 성적 + 홈페이지(logyedu.com) 키오스크 출결을 한 줄로 모은다.

계산만 한다(DB · 네트워크 없음). main.py 의 /api/admin/overview 가 부른다.
"""
import re
from datetime import date, timedelta
from typing import Callable, Dict, Iterable, List, Optional

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


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _day(value) -> Optional[date]:
    t = str(value or "").strip().replace("T", " ")[:10]
    try:
        return date.fromisoformat(t)
    except ValueError:
        return None


def homework_items(today: date, homeworks: Iterable[dict], reports: Iterable[dict], names: List[str],
                   visible: Callable[[dict, str], bool], deadline_passed: Callable[[str], bool],
                   start: date) -> Dict[str, List[dict]]:
    """학생마다 start 이후 숙제(과제)와 냈는지. 숙제는 마감일 주에 넣는다(마감이 없으면 낸 날,
    마감이 아직 멀면 이번 주). 이름은 name_key 로."""
    import homework_status as hs
    by_title: Dict[str, List[dict]] = {}
    for r in reports or []:
        if r.get("type") == "과제 제출":
            by_title.setdefault(str(r.get("task_name", "")).strip(), []).append(r)
    out: Dict[str, List[dict]] = {}
    for hw in homeworks or []:
        title = str((hw or {}).get("title") or "").strip()
        if not title or hw.get("hidden"):
            continue
        deadline = str(hw.get("deadline") or "").strip()
        anchor = _day(deadline) or _day(hw.get("created_at"))
        if anchor is None or anchor < start:
            continue
        anchor = min(anchor, today)
        passed = bool(deadline) and deadline_passed(deadline)
        latest = hs.latest_by_student(by_title.get(title, []))
        for n in names:
            if not visible(hw, n):
                continue
            st = hs.student_status(latest.get(n), passed, bool(deadline))
            out.setdefault(name_key(n), []).append({"title": title, "deadline": deadline.replace("T", " ")[:16],
                                                     "day": anchor.isoformat(), **st})
    for items in out.values():
        items.sort(key=lambda x: x["day"], reverse=True)
    return out


def weekly(today: date, n_weeks: int, att: Optional[dict], hw: List[dict]) -> List[dict]:
    """이번 주부터 n주 전까지 주마다 출석 · 지각 · 결석 · 클리닉 · 숙제. 맨 앞이 이번 주."""
    out = []
    has_dates = bool(att) and "presentDates" in att
    for i in range(max(1, n_weeks)):
        s = week_start(today) - timedelta(weeks=i)
        e = s + timedelta(days=6)
        lo, hi = s.isoformat(), e.isoformat()
        pick = lambda days: [d for d in (days or []) if lo <= str(d) <= hi]
        w = {"start": lo, "end": hi, "label": f"{s.month}/{s.day}~{e.month}/{e.day}", "this_week": i == 0}
        if att:
            w["absent_days"] = pick(att.get("absentDays"))
            w["absent"] = len(w["absent_days"])
            if has_dates:
                w["late_days"] = pick(att.get("lateDates"))
                w["present"] = len(pick(att.get("presentDates")))
                w["late"] = len(w["late_days"])
                w["clinic"] = len(pick(att.get("clinicDates")))
        items = [h for h in hw or [] if lo <= h["day"] <= hi]
        counts = {"submitted": 0, "late": 0, "missing": 0, "pending": 0}
        for h in items:
            counts[h["status"]] += 1
        w["homework"] = {"items": items, **counts, "total": len(items)}
        out.append(w)
    return out


def build(students: Iterable[dict], reports: Iterable[dict], attendance: Optional[List[dict]],
          today: Optional[date] = None, n_weeks: int = 0,
          homework: Optional[Dict[str, List[dict]]] = None) -> Dict:
    """students: [{name, school, grade, class_name, withdrawn}], reports: 그 기간 제출 기록,
    attendance: 홈페이지가 준 학생별 출결(없으면 None). n_weeks 를 주면 학생마다 주별(weeks)도 붙인다."""
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
        if n_weeks and today is not None:
            rows[-1]["weeks"] = weekly(today, n_weeks, a, (homework or {}).get(k, []))
    rows.sort(key=lambda r: (r["class_name"] or "힣", r["name"]))
    kiosk_only = sorted(a.get("name", "") for k, a in att.items() if k not in matched)
    return {"rows": rows, "kiosk_only": kiosk_only}


def recent_scores(reports: Iterable[dict], limit: int = 10) -> Dict:
    """한 학생의 기록 → 최근 성적 몇 개와 평균(같은 시험을 다시 냈으면 마지막 것만)."""
    latest = {}
    for r in reports or []:
        if r.get("type") not in SCORED_TYPES:
            continue
        key = (r.get("type"), str(r.get("task_name", "")))
        if key not in latest or str(r.get("submitted_at", "")) > str(latest[key].get("submitted_at", "")):
            latest[key] = r
    reps = sorted(latest.values(), key=lambda r: str(r.get("submitted_at", "")), reverse=True)[:limit]
    pcts = [p for p in (score_pct(r) for r in reps) if p is not None]
    return {
        "scores": [{"title": str(r.get("task_name", "")), "type": r.get("type", ""), "score": score_text(r),
                    "pct": None if score_pct(r) is None else round(score_pct(r)),
                    "date": str(r.get("submitted_at", ""))[:10]} for r in reps],
        "avg": round(sum(pcts) / len(pcts), 1) if pcts else None,
    }
