"""클리닉 시간 신청: 원장님이 매주 시간들을 열면 학생이 가능한 시간을 모두 고르고, 원장님이 학생마다 하나를 확정한다.

계산만 한다(DB 없음). main.py 의 /api/admin/clinic_poll* · /api/student/clinic_poll* 가 부른다.
"""
import re
from typing import Dict, Iterable, List, Optional

DAYS = ["월", "화", "수", "목", "금", "토", "일"]


def slot_id(weekday: int, time: str) -> str:
    return f"w{int(weekday) % 7}-{time.replace(':', '')}"


def normalize_slots(raw) -> List[dict]:
    """[{weekday, time}] → 겹치지 않게, 요일 · 시각 순. 시각은 HH:MM 만 받는다."""
    out, seen = [], set()
    for s in raw or []:
        if not isinstance(s, dict):
            continue
        try:
            wd = int(s.get("weekday")) % 7
        except (TypeError, ValueError):
            continue
        t = str(s.get("time") or "").strip()
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            continue
        t = f"{int(m.group(1)):02d}:{m.group(2)}"
        sid = slot_id(wd, t)
        if sid in seen:
            continue
        seen.add(sid)
        out.append({"id": sid, "weekday": wd, "time": t, "label": f"{DAYS[wd]} {t}"})
    out.sort(key=lambda x: (x["weekday"], x["time"]))
    return out


def clean_choice(slot_ids, slots: List[dict]) -> List[str]:
    """학생이 고른 시간 중 실제로 열린 것만, 열린 순서대로."""
    want = {str(x) for x in (slot_ids or [])}
    return [s["id"] for s in slots if s["id"] in want]


def summary(slots: List[dict], answers: Iterable[dict], audience: Iterable[str]) -> Dict:
    """원장님 화면: 시간마다 가능한 학생, 학생마다 고른 시간 · 확정, 아직 안 고른 학생."""
    by_slot = {s["id"]: [] for s in slots}
    students = []
    answered = set()
    for a in answers or []:
        name = str(a.get("student_name") or "").strip()
        if not name:
            continue
        answered.add(name)
        chosen = clean_choice(a.get("slot_ids"), slots)
        for sid in chosen:
            by_slot[sid].append(name)
        students.append({"name": name, "slot_ids": chosen, "memo": str(a.get("memo") or ""),
                         "confirmed": a.get("confirmed_slot") or "", "updated_at": str(a.get("updated_at") or "")})
    students.sort(key=lambda x: x["name"])
    confirmed = {}
    for st in students:
        if st["confirmed"]:
            confirmed.setdefault(st["confirmed"], []).append(st["name"])
    return {
        "slots": [{**s, "available": sorted(by_slot[s["id"]]), "confirmed": sorted(confirmed.get(s["id"], []))} for s in slots],
        "students": students,
        "missing": sorted(n for n in dict.fromkeys(audience or []) if n not in answered),
    }
