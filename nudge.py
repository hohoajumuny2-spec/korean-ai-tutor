"""재촉 엔진 — 듀오링고처럼 학생이 수업 · 클리닉 · 숙제 · 매일 학습을 빠뜨리지 않게 (2026-11-24, 원장님 요청).

DB 없이 계산만 한다(그래서 따로 시험할 수 있다). DB 읽기 · 보내기는 main.py 가 한다.

① 연속 기록 🔥
   매일 학습 · 숙제 제출 · 퀴즈 · 모의고사 · 클리닉 · 키오스크 출석 가운데 하나라도 하면 '공부한 날'.
   어제도 했으면 하루씩 늘고, 하루라도 비면 0부터. 방패가 있으면 빈 날 하나를 방패가 막는다.
   방패는 처음 1개, 7일 연속마다 1개(최대 2개). 7 · 30 · 50 · 100 · 200 · 365일에는 보너스 경험치.

② 재촉 시간표 (한국 시각)
   숙제     마감 24시간 전(부드럽게) → 3시간 전 → 1시간 전(단호하게 + 카톡) → 마감 뒤(단호하게 + 카톡)
   매일     19:00 → 21:30 → 23:00 (연속 기록이 있는데 오늘 아직 아무것도 안 했을 때) "연속이 1시간 뒤 꺼져요"(+ 카톡)
   클리닉   시작 2시간 전 → 시작 30분이 지나도 안 오면(+ 카톡)
   며칠째   이틀 넘게 아무것도 안 했으면 17:00에 한 번
   23:30 ~ 08:00 에는 보내지 않는다. 학생 한 명에게 하루 앱 알림 5번 · 카톡 2번까지.

③ 말투: 1단계는 장난스럽게, 2단계는 다그치게, 3단계는 단호하고 건조하게(원장님 요청: 섞어서).
"""
import hashlib
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

SHIELD_MAX = 2
SHIELD_EVERY = 7
MILESTONES = {7: 30, 30: 100, 50: 150, 100: 300, 200: 500, 365: 1000}   # 연속 일수 → 보너스 경험치

QUIET_START = (23, 30)   # 이때부터
QUIET_END = (8, 0)       # 이때까지는 보내지 않는다
MAX_PUSH_PER_DAY = 5
MAX_KAKAO_PER_DAY = 2

TWO_CHAR_SURNAMES = ("남궁", "황보", "제갈", "선우", "독고", "사공", "서문", "동방")


# ── 이름 부르기 ──────────────────────────────────────────
def call_name(name: str) -> str:
    """'박서연' → '서연아', '김지수' → '지수야'. 한글 이름이 아니면 그대로."""
    raw = re.sub(r"\(.*?\)|\[.*?\]", "", str(name or "")).strip()
    n = re.sub(r"[^가-힣]", "", raw)
    if len(n) < 2:
        return raw or "친구야"
    given = n[2:] if (len(n) >= 4 and n[:2] in TWO_CHAR_SURNAMES) else (n[1:] if len(n) >= 3 else n)
    last = given[-1]
    has_batchim = (ord(last) - 0xAC00) % 28 != 0
    return given + ("아" if has_batchim else "야")


# ── ① 연속 기록 ─────────────────────────────────────────
def _d(v) -> Optional[date]:
    try:
        return datetime.strptime(str(v or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def new_streak() -> dict:
    return {"current": 0, "best": 0, "last_active": "", "shields": 1, "shield_used": [], "milestones": [], "days": []}


def mark_active(doc: Optional[dict], today: date) -> tuple:
    """오늘 공부했다고 적는다. (새 기록, 보너스 경험치, 이번에 일어난 일 목록)을 돌려준다.
    이미 오늘 적었으면 그대로."""
    s = {**new_streak(), **(doc or {})}
    s["shield_used"] = list(s.get("shield_used") or [])
    s["milestones"] = list(s.get("milestones") or [])
    s["days"] = list(s.get("days") or [])
    last = _d(s.get("last_active"))
    events = []
    if last == today:
        return s, 0, events
    if last is None or last > today:
        s["current"] = 1
    else:
        gap = (today - last).days - 1          # 빈 날 수
        if gap == 0:
            s["current"] = int(s.get("current") or 0) + 1
        elif gap <= int(s.get("shields") or 0):
            s["shields"] = int(s["shields"]) - gap
            for k in range(gap):
                s["shield_used"].append((last + timedelta(days=k + 1)).isoformat())
            s["shield_used"] = s["shield_used"][-30:]
            s["current"] = int(s.get("current") or 0) + 1
            events.append(f"shield:{gap}")
        else:
            if int(s.get("current") or 0) > 0:
                events.append(f"broken:{s.get('current')}")
            s["current"] = 1
    s["last_active"] = today.isoformat()
    s["best"] = max(int(s.get("best") or 0), s["current"])
    s["days"] = (s["days"] + [today.isoformat()])[-60:]
    bonus = 0
    if s["current"] % SHIELD_EVERY == 0 and int(s.get("shields") or 0) < SHIELD_MAX:
        s["shields"] = int(s.get("shields") or 0) + 1
        events.append("shield_earned")
    if s["current"] in MILESTONES and s["current"] not in s["milestones"]:
        bonus = MILESTONES[s["current"]]
        s["milestones"].append(s["current"])
        events.append(f"milestone:{s['current']}")
    return s, bonus, events


def streak_view(doc: Optional[dict], today: date) -> dict:
    """지금 보이는 연속 기록: 오늘 · 어제 했으면 그대로, 빈 날을 방패로 막을 수 있으면 그대로, 아니면 끊김(0)."""
    s = {**new_streak(), **(doc or {})}
    last = _d(s.get("last_active"))
    cur = int(s.get("current") or 0)
    done_today = last == today
    if last is None:
        alive = 0
    elif last >= today - timedelta(days=1):
        alive = cur
    else:
        gap = (today - last).days - 1                       # 오늘을 빼고 빈 날
        alive = cur if gap <= int(s.get("shields") or 0) else 0
    week = []
    days = set(s.get("days") or [])
    used = set(s.get("shield_used") or [])
    for k in range(6, -1, -1):
        d = (today - timedelta(days=k)).isoformat()
        week.append({"day": d, "mark": "done" if d in days else "shield" if d in used else ""})
    return {"current": alive, "best": int(s.get("best") or 0), "shields": int(s.get("shields") or 0),
            "done_today": done_today, "at_risk": alive > 0 and not done_today, "week": week}


# ── ② 재촉 고르기 ───────────────────────────────────────
def parse_deadline(v) -> Optional[datetime]:
    """'2026-11-25T22:00' · '2026-11-25 22:00' · '2026-11-25'(그날 23:59)."""
    t = str(v or "").strip().replace("T", " ")
    for fmt, whole_day in (("%Y-%m-%d %H:%M:%S", False), ("%Y-%m-%d %H:%M", False), ("%Y-%m-%d", True)):
        try:
            dt = datetime.strptime(t, fmt)
            return dt.replace(hour=23, minute=59) if whole_day else dt
        except ValueError:
            continue
    return None


def quiet(now: datetime) -> bool:
    hm = (now.hour, now.minute)
    return hm >= QUIET_START or hm < QUIET_END


def _hhmm(dt: datetime) -> str:
    return f"{dt.hour}시" + (f" {dt.minute}분" if dt.minute else "")


def _when(dl: datetime, now: datetime) -> str:
    if dl.date() == now.date():
        return f"오늘 {_hhmm(dl)}"
    if dl.date() == now.date() + timedelta(days=1):
        return f"내일 {_hhmm(dl)}"
    return f"{dl.month}월 {dl.day}일 {_hhmm(dl)}"


def _pick(options: List[str], seed: str) -> str:
    h = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16)
    return options[h % len(options)]


# 말투 — {who}: '서연아' · {n}: 연속 일수 · {t}: 과제 이름 · {when}: 마감 · {left}: 남은 시간 · {time}: 클리닉 시각
TEXTS = {
    "hw24": (1, "📚 숙제 잊지 않았지?", [
        "{who}, '{t}' 마감이 {when}이야. 오늘 미리 해 두면 내일이 편해! 🙌",
        "{who}! '{t}' 아직이네? 마감 {when}. 지금 10분만 시작해 보자 ✏️",
        "국최 선생님이 '{t}' 기다리는 중… {when}까지야 👀",
    ]),
    "hw3": (2, "⏰ 숙제 마감 3시간 전", [
        "{who}, '{t}' 마감까지 {left} 남았어. 지금 시작해야 해!",
        "'{t}' 아직 안 냈어. 마감 {when}. 미루면 진짜 큰일 나!",
        "{who}! 3시간 남았다. '{t}' 지금 펴자. 🔥",
    ]),
    "hw1": (3, "⛔ 숙제 마감 1시간 전", [
        "'{t}' 마감 1시간 전입니다. 아직 제출하지 않았습니다.",
        "{who}, '{t}' 미제출. 마감 {when}. 지금 바로 제출하세요.",
    ]),
    "hwlate": (3, "❗ 숙제 미제출", [
        "'{t}' 마감({when})이 지났습니다. 아직 제출하지 않았습니다. 오늘 안에 제출하세요.",
        "{who}, '{t}' 미제출 상태입니다. 늦어도 오늘 꼭 내세요.",
    ]),
    "pr19": (1, "🔥 오늘 공부 기다리는 중", [
        "{who}, 오늘 하나만 하면 🔥 {n}일 연속! 과제 · 퀴즈 · 단어 시험 뭐든 좋아",
        "국최 선생님이 기다리는 중 😊 {n}일째 불꽃 지켜야지?",
        "{who}! 하루 하나, 오늘 것만 하면 돼. 지금 어때? ✨",
    ]),
    "pr2130": (2, "🔥 아직 오늘 공부 안 했어", [
        "{who}, 오늘 공부를 아직 안 했어. 🔥 {n}일 연속이 위험해!",
        "잠깐! {n}일 연속 기록이 오늘 밤에 끊길 수 있어. 5분만 하자 😥",
        "{who}… 선생님 기다리다 지쳤어 🥺 오늘 공부 아직이야",
    ]),
    "pr23": (3, "⚠️ 1시간 뒤 연속 기록이 꺼집니다", [
        "{n}일 연속 기록이 1시간 뒤 끊깁니다. 지금 학생 앱에서 하나라도 하세요.",
        "{who}, 오늘 공부 기록이 없습니다. 자정 전에 하나라도 하세요.",
    ]),
    "cl2h": (1, "🩺 오늘 클리닉 있어", [
        "{who}, 오늘 {time} 클리닉이야! 늦지 말고 와 😊",
        "오늘 {time} 클리닉 잊지 않았지? 키오스크에서 클리닉 등원 누르는 것도 잊지 마 🙌",
    ]),
    "cl30": (3, "❗ 클리닉 시간이 지났습니다", [
        "오늘 {time} 클리닉 시간이 30분 지났습니다. 아직 등원하지 않았습니다.",
        "{who}, 클리닉({time})에 오지 않았습니다. 지금 오거나 선생님께 연락하세요.",
    ]),
    "idle": (1, "🥺 보고 싶어", [
        "{who}, 이틀째 소식이 없네… 학생 앱에서 하나만 풀고 가 🙏",
        "국최 선생님이 {who}를 찾고 있어 👀 오늘 5분만!",
    ]),
}


def _msg(key: str, kind: str, ctx: dict, seed: str, extra: dict) -> dict:
    level, title, options = TEXTS[kind]
    vals = {"who": ctx.get("call") or call_name(ctx.get("name", "")), "n": max(1, int(ctx.get("streak") or 0)), **extra}
    body = _pick(options, seed + key).format(**vals)
    return {"key": key, "kind": kind, "level": level, "title": title, "body": body}


def due_messages(ctx: dict, now: datetime, sent_keys: set) -> List[dict]:
    """지금 보낼 재촉(아직 안 보낸 것만). ctx:
        name, call, streak(지금 연속), active_today(bool), last_active(date|None)
        practice(bool: 매일 학습을 쓰는 학생), practice_done(bool)
        homeworks: [{title, deadline, submitted}]   clinic: {time:'18:00', attended:bool} | None
    """
    if quiet(now):
        return []
    today = now.date()
    out = []

    def want(key, kind, extra=None):
        if key not in sent_keys:
            out.append(_msg(key, kind, ctx, ctx.get("name", "") + today.isoformat(), extra or {}))

    # 숙제: 마감이 가까운 것부터, 한 번에 하나만(같은 단계는 과제마다 따로 센다)
    for hw in sorted(ctx.get("homeworks") or [], key=lambda h: str(h.get("deadline") or "")):
        if hw.get("submitted"):
            continue
        dl = parse_deadline(hw.get("deadline"))
        if not dl:
            continue
        t = str(hw.get("title") or "숙제")
        left = dl - now
        extra = {"t": t, "when": _when(dl, now), "left": f"{max(1, int(left.total_seconds() // 3600))}시간"}
        if timedelta(0) < left <= timedelta(hours=1):
            want(f"hw1:{t}", "hw1", extra)
        elif timedelta(hours=1) < left <= timedelta(hours=3):
            want(f"hw3:{t}", "hw3", extra)
        elif timedelta(hours=3) < left <= timedelta(hours=24):
            want(f"hw24:{t}", "hw24", extra)
        elif timedelta(hours=-36) <= left <= timedelta(0) and now.hour >= 8:
            want(f"hwlate:{t}", "hwlate", extra)

    # 클리닉
    cl = ctx.get("clinic") or None
    if cl and cl.get("time") and not cl.get("attended"):
        m = re.match(r"^(\d{1,2}):(\d{2})", str(cl["time"]))
        if m:
            start = datetime.combine(today, datetime.min.time()).replace(hour=int(m.group(1)), minute=int(m.group(2)))
            extra = {"time": _hhmm(start)}
            if start - timedelta(hours=2) <= now < start:
                want("cl2h", "cl2h", extra)
            elif start + timedelta(minutes=30) <= now < start + timedelta(hours=3):
                want("cl30", "cl30", extra)

    # 매일 학습 · 연속 기록 (오늘 아무것도 안 했을 때)
    if not ctx.get("active_today"):
        hm = (now.hour, now.minute)
        # 연속 기록이 살아 있는 학생(또는 매일 문제를 받는 학생)이 오늘 아직 아무것도 안 했으면
        if int(ctx.get("streak") or 0) > 0 or (ctx.get("practice") and not ctx.get("practice_done")):
            if hm >= (23, 0):
                want("pr23", "pr23")
            elif hm >= (21, 30):
                want("pr2130", "pr2130")
            elif hm >= (19, 0):
                want("pr19", "pr19")
        last = ctx.get("last_active")
        if last and (today - last).days >= 2 and hm >= (17, 0) and not out:
            want("idle", "idle")
    return out


def route(msgs: List[dict], has_push: bool, pushed_today: int, kakao_today: int, kakao_on: bool) -> List[dict]:
    """보낼 길 정하기: 앱 알림은 하루 MAX_PUSH_PER_DAY, 카톡은 3단계(또는 앱 알림이 없는 학생의 2단계 이상)만 하루 MAX_KAKAO_PER_DAY."""
    out = []
    for m in sorted(msgs, key=lambda x: -x["level"]):
        via = []
        if has_push and pushed_today < MAX_PUSH_PER_DAY:
            via.append("push")
            pushed_today += 1
        if kakao_on and kakao_today < MAX_KAKAO_PER_DAY and (m["level"] >= 3 or (not has_push and m["level"] >= 2)):
            via.append("kakao")
            kakao_today += 1
        out.append({**m, "via": via})
    return out


# ── ③ 반별 주간 리그 ─────────────────────────────────────
def week_id(d: date) -> str:
    """월요일에 바뀌는 주 이름: '2026-W48'."""
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def league(rows: List[dict], me: str, top: int = 10) -> dict:
    """rows: [{name, xp}] (같은 반). 이번 주 경험치 순위와 내 자리."""
    ranked = sorted([r for r in rows if int(r.get("xp") or 0) > 0], key=lambda r: (-int(r["xp"]), r["name"]))
    mine = next((i + 1 for i, r in enumerate(ranked) if r["name"] == me), None)
    my_xp = next((int(r["xp"]) for r in ranked if r["name"] == me), 0)
    return {"top": [{"rank": i + 1, "name": r["name"], "xp": int(r["xp"])} for i, r in enumerate(ranked[:top])],
            "my_rank": mine, "my_xp": my_xp, "size": len(ranked)}
