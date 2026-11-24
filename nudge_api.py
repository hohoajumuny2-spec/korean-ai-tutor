"""재촉(듀오링고식) — 학생 앱 서버 연결 (2026-11-24, 원장님 요청).

계산은 nudge.py, 여기서는 DB 읽기 · 쓰기와 주소만 맡는다. main.py 끝에서 register(app, H)로 붙인다.

  · 공부 기록: 제출 기록이 생길 때마다(숙제 · 퀴즈 · 모의고사 · 매일 학습 · 클리닉) 오늘을 '공부한 날'로 적는다.
               키오스크 출석 · 클리닉 등원도 tick 때 홈페이지 출결을 읽어 적는다.
  · 리그:      경험치가 오를 때마다 이번 주 경험치(league_xp)에도 더한다.
  · tick:      /api/nudge/tick?key=… 를 cron-job.org 가 30분마다 부른다. 켜 두었을 때만 보낸다.

DB
  streaks/{이름}                   연속 기록 (nudge.new_streak 모양 + student_name)
  league_xp/{주}__{이름}           {week, student_name, xp}
  nudge_log/{날짜}__{이름}         {date, student_name, keys[], push, kakao, items[]}
  settings/nudge_config            {enabled, kakao, key, exclude[]}
"""
import os
import secrets
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import requests
from fastapi import Depends, HTTPException
from pydantic import BaseModel

import nudge as nd

H: Dict = {}
STREAKS = "streaks"
LEAGUE = "league_xp"
LOG = "nudge_log"


def _db():
    return H["db"]()


def _sid(v: str) -> str:
    return H["sanitize_doc_id"](v)


def _now() -> datetime:
    return H["now_kst"]()


# ── 설정 ────────────────────────────────────────────────
def load_config(create_key: bool = False) -> dict:
    out = {"enabled": False, "kakao": True, "key": "", "exclude": []}
    ref = _db().collection("settings").document("nudge_config")
    snap = ref.get()
    if snap.exists:
        v = snap.to_dict() or {}
        out.update({"enabled": bool(v.get("enabled")), "kakao": bool(v.get("kakao", True)),
                    "key": str(v.get("key") or ""), "exclude": [str(x) for x in (v.get("exclude") or [])]})
    if create_key and not out["key"]:
        out["key"] = secrets.token_urlsafe(18)
        ref.set({"key": out["key"]}, merge=True)
    return out


# ── 공부 기록 · 리그 ────────────────────────────────────
def record_activity(name: str, day: Optional[date] = None) -> tuple:
    """오늘(또는 day)을 공부한 날로 적는다. 이미 적혀 있으면 읽기만 한다."""
    name = str(name or "").strip()
    if not name or H["is_preview"](name):
        return None, 0, []
    day = day or _now().date()
    ref = _db().collection(STREAKS).document(_sid(name))
    snap = ref.get()
    doc = (snap.to_dict() or {}) if snap.exists else None
    if doc and doc.get("last_active") == day.isoformat():
        return doc, 0, []
    s, bonus, events = nd.mark_active(doc, day)
    s["student_name"] = name
    ref.set(s)
    if bonus:
        H["add_xp"](name, bonus)
    return s, bonus, events


def add_league_xp(name: str, amount: int, day: Optional[date] = None):
    name = str(name or "").strip()
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return
    if not name or amount <= 0 or H["is_preview"](name):
        return
    w = nd.week_id(day or _now().date())
    _db().collection(LEAGUE).document(_sid(f"{w}__{name}")).set(
        {"week": w, "student_name": name, "xp": H["increment"](amount)}, merge=True)


def _safe(fn):
    def run(*a, **k):
        try:
            fn(*a, **k)
        except Exception as e:  # 기록이 실패해도 제출 · 점수는 그대로 되어야 한다
            print("[재촉] 기록 실패:", repr(e))
    return run


# ── 모으기 (DB) ─────────────────────────────────────────
def fetch_attendance(day: date):
    """홈페이지(logyedu.com) 키오스크 출결. 실패하면 None."""
    secret = os.environ.get("NOTIFY_SECRET", "").strip()
    if not secret:
        return None
    base = (os.environ.get("LOGYEDU_SITE_URL", "").strip() or "https://logyedu.com").rstrip("/")
    try:
        r = requests.get(f"{base}/api/notify/attendance", params={"from": day.isoformat(), "to": day.isoformat()},
                         headers={"X-Notify-Secret": secret}, timeout=40)
        data = r.json()
    except Exception:
        return None
    if not data.get("ok"):
        return None
    return data.get("students") or []


def gather(now: datetime) -> dict:
    db = _db()
    today = now.date()
    ds = today.isoformat()
    studs = []
    for d in db.collection("students").stream():
        v = d.to_dict() or {}
        if v.get("withdrawn") or H["is_preview"](d.id):
            continue
        studs.append({"name": d.id, **v})
    since = (now - timedelta(days=21)).strftime("%Y-%m-%d")
    reports = [r.to_dict() or {} for r in db.collection("reports").where("submitted_at", ">=", since).stream()]
    lo, hi = (today - timedelta(days=7)).isoformat(), (today + timedelta(days=2)).isoformat()
    hws = []
    for d in db.collection("homeworks").stream():
        v = d.to_dict() or {}
        dl = str(v.get("deadline") or "").strip()
        if v.get("hidden") or not dl or not (lo <= dl[:10] <= hi):
            continue
        hws.append({"title": d.id, **v})
    streaks = {}
    for d in db.collection(STREAKS).stream():
        v = d.to_dict() or {}
        streaks[str(v.get("student_name") or d.id)] = v
    push_names = {str((d.to_dict() or {}).get("student_name") or "") for d in db.collection("push_subs").stream()}
    clinics = [d.to_dict() or {} for d in db.collection("clinics").stream()]
    logs = {}
    for d in db.collection(LOG).where("date", "==", ds).stream():
        v = d.to_dict() or {}
        logs[str(v.get("student_name"))] = v
    return {"now": now, "students": studs, "reports": reports, "homeworks": hws, "streaks": streaks,
            "push_names": push_names, "clinics": clinics, "logs": logs, "attendance": fetch_attendance(today)}


# ── 학생 한 명 상황 만들기 (DB 없이) ─────────────────────
def clinic_today(clinics: List[dict], name: str, today: date) -> Optional[str]:
    """오늘 그 학생 클리닉 시각(가장 이른 것). 없으면 None."""
    times = []
    for c in clinics or []:
        if str(c.get("student_name") or "").strip() != name or not c.get("time"):
            continue
        if str(c.get("kind") or "") == "once":
            if str(c.get("date") or "")[:10] == today.isoformat():
                times.append(str(c["time"]))
        else:
            try:
                if int(c.get("weekday", -1)) % 7 == today.weekday():
                    times.append(str(c["time"]))
            except (TypeError, ValueError):
                pass
    return min(times) if times else None


def attended_today(att_rows, name: str, today: date) -> Optional[dict]:
    """{'present': bool, 'clinic': bool} — 출결을 못 읽었으면 None."""
    if att_rows is None:
        return None
    ds = today.isoformat()
    key = name.replace(" ", "")
    for a in att_rows:
        if str(a.get("name") or "").replace(" ", "") == key:
            return {"present": ds in (a.get("presentDates") or []), "clinic": ds in (a.get("clinicDates") or [])}
    return {"present": False, "clinic": False}


def homework_for(g: dict, s: dict) -> List[dict]:
    """그 학생에게 보이는, 마감이 가까운(또는 막 지난) 숙제와 냈는지."""
    name = s["name"]
    info = H["targeting_info_from"](s)
    out = []
    for hw in g["homeworks"]:
        if not H["homework_visible_to_student"](hw, name, info=info):
            continue
        done = any(r.get("type") == "과제 제출" and str(r.get("task_name", "")).strip() == hw["title"]
                   and str(r.get("student_name", "")).strip() == name for r in g["reports"])
        out.append({"title": hw["title"], "deadline": str(hw.get("deadline") or ""), "submitted": done})
    return out


def context_for(g: dict, s: dict, streak: Optional[dict]) -> dict:
    now = g["now"]
    today = now.date()
    name = s["name"]
    view = nd.streak_view(streak, today)
    att = attended_today(g["attendance"], name, today)
    ctime = clinic_today(g["clinics"], name, today)
    return {
        "name": name, "call": nd.call_name(name), "streak": view["current"], "active_today": view["done_today"],
        "last_active": nd._d((streak or {}).get("last_active")),
        # '오늘의 유형 문제'는 학생 앱에서 내렸다(2026-11-09) → 매일 재촉은 연속 기록 기준만
        "practice": False, "practice_done": False,
        "homeworks": homework_for(g, s),
        # 출결을 못 읽었으면 왔다고 보고 '안 왔다' 재촉은 하지 않는다
        "clinic": {"time": ctime, "attended": att is None or att["present"] or att["clinic"]} if ctime else None,
    }


# ── 한 번 돌기 ──────────────────────────────────────────
def run_tick(dry: bool = False, cfg: Optional[dict] = None) -> dict:
    cfg = cfg or load_config()
    now = _now()
    today = now.date()
    g = gather(now)
    exclude = set(cfg.get("exclude") or [])
    planned, kakao_items, marked = [], [], []
    for s in g["students"]:
        name = s["name"]
        streak = g["streaks"].get(name)
        att = attended_today(g["attendance"], name, today)
        if att and (att["present"] or att["clinic"]) and (streak or {}).get("last_active") != today.isoformat():
            marked.append(name)
            if not dry:
                streak, _, _ = record_activity(name, today)
            else:
                streak, _, _ = nd.mark_active(streak, today)
        if name in exclude:
            continue
        log = g["logs"].get(name) or {}
        msgs = nd.due_messages(context_for(g, s, streak), now, set(log.get("keys") or []))
        if not msgs:
            continue
        routed = nd.route(msgs, name in g["push_names"], int(log.get("push") or 0),
                          int(log.get("kakao") or 0), bool(cfg.get("kakao")))
        sent_rows = []
        for m in routed:
            row = {"at": now.strftime("%H:%M"), "key": m["key"], "level": m["level"], "title": m["title"],
                   "body": m["body"], "via": list(m["via"])}
            if not dry:
                if "push" in m["via"]:
                    try:
                        if not H["send_push_to_student"](name, m["title"], m["body"], "/", "nudge-" + m["key"]):
                            row["via"].remove("push")
                    except Exception as e:
                        print("[재촉] 앱 알림 실패:", repr(e))
                        row["via"].remove("push")
                if "kakao" in m["via"]:
                    kakao_items.append({"name": name, "vars": {"내용": f"{m['title']}\n{m['body']}"[:600]}})
            sent_rows.append(row)
        planned.append({"name": name, "items": sent_rows})
        if not dry:
            _db().collection(LOG).document(_sid(f"{today.isoformat()}__{name}")).set({
                "date": today.isoformat(), "student_name": name,
                "keys": list(dict.fromkeys(list(log.get("keys") or []) + [m["key"] for m in routed])),
                "push": int(log.get("push") or 0) + sum("push" in r["via"] for r in sent_rows),
                "kakao": int(log.get("kakao") or 0) + sum("kakao" in r["via"] for r in sent_rows),
                "items": (list(log.get("items") or []) + sent_rows)[-30:],
            }, merge=True)
    kakao = None
    if kakao_items and not dry:
        kakao = H["kakao_message"]("안내", "student", kakao_items)
    return {"success": True, "dry": dry, "at": now.strftime("%Y-%m-%d %H:%M"), "quiet": nd.quiet(now),
            "students": len(g["students"]), "attendance_ok": g["attendance"] is not None,
            "marked_from_kiosk": marked, "planned": planned, "kakao": kakao}


# ── 원장님 한눈에 보기 ───────────────────────────────────
def overview_rows(g: dict) -> List[dict]:
    from overview import student_class_label
    now = g["now"]
    today = now.date()
    rows = []
    for s in g["students"]:
        name = s["name"]
        streak = g["streaks"].get(name)
        view = nd.streak_view(streak, today)
        c = context_for(g, s, streak)
        last = c["last_active"]
        att = attended_today(g["attendance"], name, today)
        overdue = [h["title"] for h in c["homeworks"] if not h["submitted"]
                   and (nd.parse_deadline(h["deadline"]) or now) < now]
        soon = [h["title"] for h in c["homeworks"] if not h["submitted"]
                and now <= (nd.parse_deadline(h["deadline"]) or now) <= now + timedelta(hours=24)]
        log = g["logs"].get(name) or {}
        idle = (today - last).days if last else None
        clinic_missed = bool(c["clinic"]) and att is not None and not c["clinic"]["attended"]
        flags = []
        if overdue:
            flags.append("숙제 미제출")
        if clinic_missed:
            flags.append("클리닉 미등원")
        if idle is None:
            flags.append("기록 없음")
        elif idle >= 2:
            flags.append(f"{idle}일째 안 함")
        elif view["at_risk"]:
            flags.append("오늘 아직")
        rows.append({
            "name": name, "class_name": student_class_label(s), "streak": view["current"], "best": view["best"],
            "shields": view["shields"], "done_today": view["done_today"], "week": view["week"],
            "last_active": last.isoformat() if last else "", "idle_days": idle,
            "overdue": overdue, "due_soon": soon,
            "clinic": ({"time": c["clinic"]["time"], "attended": None if att is None else c["clinic"]["attended"]}
                       if c["clinic"] else None),
            "has_push": name in g["push_names"], "sent_today": log.get("items") or [],
            "flags": flags,
        })
    weight = {"숙제 미제출": 0, "클리닉 미등원": 1}
    rows.sort(key=lambda r: (min([weight.get(f, 2 if "일째" in f or f == "기록 없음" else 3) for f in r["flags"]] or [9]),
                             -(r["idle_days"] or 0), r["name"]))
    return rows


def class_of(s: dict) -> str:
    info = H["targeting_info_from"](s)
    return (info.get("classes") or {}).get("korean") or (info.get("all_classes") or [""])[0]


def leagues(students: List[dict], week: str, xp_rows: List[dict], top: int = 10) -> Dict[str, dict]:
    xp = {}
    for r in xp_rows:
        if r.get("week") == week:
            xp[str(r.get("student_name"))] = xp.get(str(r.get("student_name")), 0) + int(r.get("xp") or 0)
    by_class: Dict[str, List[dict]] = {}
    for s in students:
        c = class_of(s)
        if c:
            by_class.setdefault(c, []).append({"name": s["name"], "xp": xp.get(s["name"], 0)})
    return {c: nd.league(rows, "", top) for c, rows in by_class.items()}


# ── 주소 ────────────────────────────────────────────────
class NudgeConfigReq(BaseModel):
    enabled: bool = False
    kakao: bool = True
    exclude: list = []
    new_key: bool = False


def register(app, helpers: dict):
    H.update(helpers)
    verify_admin = H["verify_admin"]
    # 제출 기록 · 경험치가 생길 때마다 불리게 main.py 에 건다
    H["activity_hooks"].append(_safe(lambda name: record_activity(name)))
    H["xp_hooks"].append(_safe(lambda name, amount: add_league_xp(name, amount)))

    @app.get("/api/nudge/tick")
    def nudge_tick(key: str = ""):
        cfg = load_config()
        if not cfg["key"] or not secrets.compare_digest(str(key), cfg["key"]):
            raise HTTPException(status_code=403, detail="열쇠가 맞지 않습니다.")
        if not cfg["enabled"]:
            return {"success": True, "skipped": "꺼져 있음"}
        r = run_tick(False, cfg)
        return {"success": True, "at": r["at"], "sent": sum(len(p["items"]) for p in r["planned"]),
                "students": len(r["planned"]), "kiosk": len(r["marked_from_kiosk"])}

    @app.get("/api/student/streak")
    def student_streak(student_name: str = ""):
        name = str(student_name or "").strip()
        if not name:
            return {"success": False, "detail": "학생 이름이 없습니다."}
        db = _db()
        today = _now().date()
        snap = db.collection(STREAKS).document(_sid(name)).get()
        view = nd.streak_view((snap.to_dict() or {}) if snap.exists else None, today)
        sdoc = db.collection("students").document(name).get()
        me = {"name": name, **((sdoc.to_dict() or {}) if sdoc.exists else {})}
        cls = class_of(me) if sdoc.exists else ""
        league = None
        if cls:
            mates = []
            for d in db.collection("students").stream():
                v = d.to_dict() or {}
                if not v.get("withdrawn") and class_of({"name": d.id, **v}) == cls:
                    mates.append(d.id)
            w = nd.week_id(today)
            xp_rows = [d.to_dict() or {} for d in db.collection(LEAGUE).where("week", "==", w).stream()]
            xp = {str(r.get("student_name")): int(r.get("xp") or 0) for r in xp_rows}
            league = {"class_name": cls, "week": w, **nd.league([{"name": n, "xp": xp.get(n, 0)} for n in mates], name),
                      "days_left": 6 - today.weekday()}
        return {"success": True, **view, "next_milestone": next((m for m in sorted(nd.MILESTONES) if m > view["current"]), None),
                "league": league}

    @app.get("/api/admin/nudge/config", dependencies=[Depends(verify_admin)])
    def nudge_config_get():
        cfg = load_config(create_key=True)
        return {"success": True, **cfg}

    @app.post("/api/admin/nudge/config", dependencies=[Depends(verify_admin)])
    def nudge_config_set(req: NudgeConfigReq):
        data = {"enabled": bool(req.enabled), "kakao": bool(req.kakao),
                "exclude": [str(x).strip() for x in (req.exclude or []) if str(x).strip()][:300]}
        if req.new_key:
            data["key"] = secrets.token_urlsafe(18)
        _db().collection("settings").document("nudge_config").set(data, merge=True)
        return {"success": True, **load_config(create_key=True)}

    @app.get("/api/admin/nudge/overview", dependencies=[Depends(verify_admin)])
    def nudge_overview():
        g = gather(_now())
        rows = overview_rows(g)
        w = nd.week_id(g["now"].date())
        xp_rows = [d.to_dict() or {} for d in _db().collection(LEAGUE).where("week", "==", w).stream()]
        return {"success": True, "at": g["now"].strftime("%Y-%m-%d %H:%M"), "attendance_ok": g["attendance"] is not None,
                "rows": rows, "leagues": leagues(g["students"], w, xp_rows, top=5), "week": w,
                "config": {k: v for k, v in load_config().items() if k != "key"}}

    @app.post("/api/admin/nudge/run", dependencies=[Depends(verify_admin)])
    def nudge_run(dry: bool = True):
        return run_tick(bool(dry))
