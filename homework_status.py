"""알림장(logyedu.com 관리자 → 알림장)에 넣을 '학생별 과제 제출 여부'.

원장님이 알림장을 쓸 때 학생 카드의 '지난 과제'를 손으로 고르던 것을, 앱에 낸 기록으로
자동으로 채우기 위해 홈페이지 서버가 /api/notice/homework_status 로 묻는다.
여기에는 DB 없이 돌아가는 계산만 둔다(그래서 따로 시험할 수 있다).

학생마다 상태:
  submitted  마감 안에 냄 (마감이 없으면 낸 것)
  late       마감 뒤에 냄 ('기한 후 제출')
  missing    안 냄 — 마감이 지났거나 마감이 없는 과제
  pending    아직 안 냈지만 마감 전 (알림장에서는 건드리지 않는다)
"""
from datetime import date, datetime, timedelta
from typing import Callable, Dict, Iterable, List, Optional

MAX_HOMEWORKS = 12
DAYS_BEFORE = 14      # 수업일 기준 이만큼 앞 마감까지
DAYS_AFTER = 7        # 수업일 기준 이만큼 뒤 마감까지
NO_DEADLINE_DAYS = 21  # 마감이 없는 과제는 이만큼 앞에 만든 것까지


def parse_day(value) -> Optional[date]:
    t = str(value or "").strip().replace("T", " ")[:10]
    try:
        return datetime.strptime(t, "%Y-%m-%d").date()
    except ValueError:
        return None


def pick_homeworks(homeworks: Iterable[dict], class_day: date) -> List[dict]:
    """수업일 즈음의 과제만 고른다. 수업일이 마감인 과제가 맨 앞."""
    picked = []
    for hw in homeworks:
        if not hw or hw.get("hidden") or not str(hw.get("title") or "").strip():
            continue
        due = parse_day(hw.get("deadline"))
        if due is not None:
            if class_day - timedelta(days=DAYS_BEFORE) <= due <= class_day + timedelta(days=DAYS_AFTER):
                picked.append(hw)
        else:
            made = parse_day(hw.get("created_at"))
            if made is not None and class_day - timedelta(days=NO_DEADLINE_DAYS) <= made <= class_day:
                picked.append(hw)

    def order(hw):
        due = parse_day(hw.get("deadline"))
        near = due or parse_day(hw.get("created_at")) or class_day
        # 수업일이 마감인 과제가 맨 앞, 그다음은 수업일에 가까운 순
        return (0 if due == class_day else 1, abs((near - class_day).days))

    picked.sort(key=order)
    return picked[:MAX_HOMEWORKS]


def latest_by_student(reports: Iterable[dict]) -> Dict[str, dict]:
    """한 학생이 여러 번 냈으면 가장 나중 기록."""
    out: Dict[str, dict] = {}
    for r in reports or []:
        who = str((r or {}).get("student_name") or "").strip()
        if not who:
            continue
        when = str(r.get("updated_at") or r.get("submitted_at") or "")
        prev = out.get(who)
        if prev is None or when >= str(prev.get("updated_at") or prev.get("submitted_at") or ""):
            out[who] = r
    return out


def student_status(report: Optional[dict], deadline_passed: bool, has_deadline: bool) -> dict:
    if report:
        row = {"status": "late" if report.get("late") else "submitted",
               "submitted_at": str(report.get("submitted_at") or "")}
        if report.get("percent") is not None:
            try:
                row["percent"] = round(float(report.get("percent")))
            except (TypeError, ValueError):
                pass
        return row
    if has_deadline and not deadline_passed:
        return {"status": "pending"}
    return {"status": "missing"}


def build(class_day: date,
          homeworks: Iterable[dict],
          reports_for: Callable[[str], Iterable[dict]],
          audience_for: Callable[[dict], Iterable[str]],
          deadline_passed: Callable[[str], bool]) -> List[dict]:
    """과제마다 {title, group, deadline, due_on_day, students: {이름: {status, ...}}}."""
    out = []
    for hw in pick_homeworks(homeworks, class_day):
        title = str(hw.get("title")).strip()
        deadline = str(hw.get("deadline") or "").strip()
        passed = bool(deadline) and deadline_passed(deadline)
        latest = latest_by_student(reports_for(title))
        names = list(dict.fromkeys([*(audience_for(hw) or []), *latest.keys()]))
        out.append({
            "title": title,
            "group": str(hw.get("group") or ""),
            "deadline": deadline,
            "due_on_day": parse_day(deadline) == class_day,
            "students": {n: student_status(latest.get(n), passed, bool(deadline)) for n in names},
        })
    return out


# ─────────────────────────────────────────────────────────
# 학부모 전용 화면(logyedu.com/p/코드): 한 학생의 최근 과제와 제출 여부
# ─────────────────────────────────────────────────────────
STUDENT_DAYS = 45      # 이만큼 앞까지 마감(마감이 없으면 만든 날)인 과제
STUDENT_MAX = 12


def for_student(today: date,
                homeworks: Iterable[dict],
                my_reports: Iterable[dict],
                visible: Callable[[dict], bool],
                deadline_passed: Callable[[str], bool]) -> List[dict]:
    """한 학생에게 나간 최근 과제 → [{title, deadline, status, submitted_at, percent?}] 최근 것부터.

    my_reports: 그 학생의 '과제 제출' 기록(과제 이름 = task_name)."""
    mine: Dict[str, dict] = {}
    for r in my_reports or []:
        t = str((r or {}).get("task_name") or "").strip()
        if not t:
            continue
        when = str(r.get("updated_at") or r.get("submitted_at") or "")
        prev = mine.get(t)
        if prev is None or when >= str(prev.get("updated_at") or prev.get("submitted_at") or ""):
            mine[t] = r
    rows = []
    for hw in homeworks or []:
        title = str((hw or {}).get("title") or "").strip()
        if not title or hw.get("hidden") or not visible(hw):
            continue
        due = parse_day(hw.get("deadline"))
        made = parse_day(hw.get("created_at"))
        anchor = due or made
        # 지난 45일 안 과제와, 마감이 아직 안 온 과제(멀리 있어도)를 넣는다
        if anchor is None or anchor < today - timedelta(days=STUDENT_DAYS):
            continue
        deadline = str(hw.get("deadline") or "").strip()
        row = student_status(mine.get(title), bool(deadline) and deadline_passed(deadline), bool(deadline))
        row.update({"title": title, "deadline": deadline.replace("T", " ")[:16], "_anchor": anchor.isoformat()})
        rows.append(row)
    rows.sort(key=lambda r: r["_anchor"], reverse=True)
    for r in rows:
        r.pop("_anchor", None)
    return rows[:STUDENT_MAX]


def class_grid(today: date, homeworks: Iterable[dict], names: List[str],
               reports_by_title: Dict[str, Iterable[dict]],
               visible_to_class: Callable[[dict], bool],
               deadline_passed: Callable[[str], bool], limit: int = 10) -> Dict:
    """반별 과제 제출표: 그 반에 나간 최근 과제(열) × 학생(줄). 칸마다 submitted · late · missing · pending."""
    cols = []
    for hw in homeworks or []:
        title = str((hw or {}).get("title") or "").strip()
        if not title or hw.get("hidden") or not visible_to_class(hw):
            continue
        anchor = parse_day(hw.get("deadline")) or parse_day(hw.get("created_at"))
        # 지난 45일 안 과제와, 마감이 아직 안 온 과제(멀리 있어도)를 넣는다
        if anchor is None or anchor < today - timedelta(days=STUDENT_DAYS):
            continue
        cols.append((anchor, hw))
    cols.sort(key=lambda x: x[0], reverse=True)
    cols = [hw for _, hw in cols[:limit]]
    out_cols, cells = [], {n: {} for n in names}
    for hw in cols:
        title = str(hw.get("title")).strip()
        deadline = str(hw.get("deadline") or "").strip()
        passed = bool(deadline) and deadline_passed(deadline)
        latest = latest_by_student(reports_by_title.get(title, []))
        counts = {"submitted": 0, "late": 0, "missing": 0, "pending": 0}
        for n in names:
            st = student_status(latest.get(n), passed, bool(deadline))
            cells[n][title] = st
            counts[st["status"]] += 1
        out_cols.append({"title": title, "deadline": deadline.replace("T", " ")[:16], "counts": counts})
    rows = [{"name": n, "cells": [cells[n][c["title"]] for c in out_cols],
             "missing": sum(1 for c in out_cols if cells[n][c["title"]]["status"] == "missing")} for n in names]
    return {"homeworks": out_cols, "rows": rows}
