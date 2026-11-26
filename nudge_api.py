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
    out = {"enabled": False, "kakao": True, "key": "", "exclude": [], "memo": "", "memo_until": "", "penalty": ""}
    ref = _db().collection("settings").document("nudge_config")
    snap = ref.get()
    if snap.exists:
        v = snap.to_dict() or {}
        out.update({"enabled": bool(v.get("enabled")), "kakao": bool(v.get("kakao", True)),
                    "key": str(v.get("key") or ""), "exclude": [str(x) for x in (v.get("exclude") or [])],
                    "memo": str(v.get("memo") or ""), "memo_until": str(v.get("memo_until") or ""),
                    "penalty": str(v.get("penalty") or "")})
    if create_key and not out["key"]:
        out["key"] = secrets.token_urlsafe(18)
        ref.set({"key": out["key"]}, merge=True)
    return out


MEMO_MAX = 200


def active_memo(cfg: dict, today: date) -> str:
    """원장님 한마디: 적어 둔 것이 있고, 마지막 날(있으면)이 아직 안 지났을 때만."""
    memo = str((cfg or {}).get("memo") or "").strip()
    until = nd._d((cfg or {}).get("memo_until"))
    if not memo or (until and today > until):
        return ""
    return memo[:MEMO_MAX]


def push_body(m: dict, memo: str) -> str:
    """앱 알림 본문: 재촉 한 줄 + 원장님 한마디(있을 때만)."""
    return f"{m['body']}\n💬 {memo}" if memo else m["body"]


# ── 카톡: 이미 승인받은 '알림장' 틀로 보낸다 ─────────────────
#   💡 2026-11-25 원장님 요청: 재촉마다 새 템플릿을 검수받지 말고 쓰고 있는 알림장(SOLAPI_TEMPLATE_NOTICE)을 쓴다.
#      알림장 틀: #{학생} #{날짜} · ■ 오늘 수업 진도 #{진도} · ■ 다음 수업까지 과제 #{과제} · ■ … 기록 #{알림장}
#      → 진도 칸에 말머리, 과제 칸에 과제와 마감, 알림장 칸에 재촉 글(+ 원장님 한마디 · 불이익).
NOTICE_KIND = "알림장"
NOTICE_TOPIC = {"과제마감": "과제 마감 안내", "미제출": "과제 미제출 안내", "과제안내": "과제 제출 안내", "클리닉": "클리닉 일정 안내",
                "학습기록": "오늘의 학습 기록 안내"}
NONE = "별도 안내 없음"
PENALTY_MAX = 300


def penalty_lines(text: str) -> List[str]:
    import re as _re
    return [x.strip(" -–") for x in _re.split(r"\s*(?:\n|·|ㆍ|•)\s*", str(text or "")) if x.strip(" -–")]


def notice_text(head: str, body: str, memo: str = "", penalty: str = "") -> str:
    """알림장 칸에 들어갈 글."""
    text = f"{head}\n{body}".strip()
    pl = penalty_lines(penalty)
    if pl:
        text += "\n\n[ 지키지 않으면 ]\n" + "\n".join("- " + x for x in pl)
    if memo:
        text += f"\n\n💬 원장님 한마디\n{memo}"
    return text[:700]


def notice_vars(m: dict, memo: str = "", penalty: str = "") -> dict:
    """재촉 하나 → 알림장 틀 빈칸. 불이익은 과제 · 클리닉 재촉에만 붙인다."""
    k, v = m["kakao_kind"], m.get("kakao_vars") or {}
    if k in ("과제마감", "미제출"):
        hw = f"{v.get('과제', '')} ({v.get('마감', '')} 마감)".strip()
    elif k == "과제안내":
        hw = str(v.get("과제", "")).strip()
    else:
        hw = NONE
    return {"진도": NOTICE_TOPIC.get(k, "학습 안내"), "과제": hw or NONE,
            "알림장": notice_text(m["title"], m["body"], memo, penalty if k in ("과제마감", "미제출", "과제안내", "클리닉") else "")}


def group_kakao(items: List[tuple], memo: str = "", penalty: str = "") -> Dict[str, List[dict]]:
    """[(이름, 재촉)] → {'알림장': [{name, vars}]} — 모두 알림장 틀 하나로 보낸다."""
    return {NOTICE_KIND: [{"name": name, "vars": notice_vars(m, memo, penalty)} for name, m in items]} if items else {}


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
    lo, hi = (today - timedelta(days=7)).isoformat(), (today + timedelta(days=nd.HWD_DAYS)).isoformat()
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
    # 어제 보낸 '마감 지남' 안내는 오늘 또 보내지 않는다
    late_sent = {}
    for d in db.collection(LOG).where("date", "==", (today - timedelta(days=1)).isoformat()).stream():
        v = d.to_dict() or {}
        late_sent[str(v.get("student_name"))] = {k for k in (v.get("keys") or []) if str(k).startswith("hwlate:")}
    return {"now": now, "students": studs, "reports": reports, "homeworks": hws, "streaks": streaks,
            "push_names": push_names, "clinics": clinics, "logs": logs, "late_sent": late_sent, "attendance": fetch_attendance(today)}


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
    memo = active_memo(cfg, today)
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
        ctx = context_for(g, s, streak)
        # 클리닉 시간은 학생마다 자주 바뀌어서, 등록된 일정으로 자동 재촉하지 않는다(원장님이 골라서 보낸다, 2026-11-25)
        ctx["clinic"] = None
        msgs = nd.due_messages(ctx, now,
                               set(log.get("keys") or []) | g.get("late_sent", {}).get(name, set()))
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
                        if not H["send_push_to_student"](name, m["title"], push_body(m, memo), "/", "nudge-" + m["key"]):
                            row["via"].remove("push")
                    except Exception as e:
                        print("[재촉] 앱 알림 실패:", repr(e))
                        row["via"].remove("push")
                if "kakao" in m["via"]:
                    kakao_items.append((name, m))
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
        kakao = {k: H["kakao_message"](k, "student", items)
                 for k, items in group_kakao(kakao_items, memo, cfg.get("penalty", "")).items()}
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
def send_test(name: str, kind: str, push: bool, kakao: bool) -> dict:
    """시간 · 하루 한도와 상관없이 한 학생에게 예시 재촉을 바로 보낸다(기록 · 한도에는 넣지 않는다)."""
    name = str(name or "").strip()
    if not name:
        return {"success": False, "detail": "학생을 골라 주세요."}
    if kind not in nd.TEXTS:
        return {"success": False, "detail": "재촉 종류를 골라 주세요."}
    if not push and not kakao:
        return {"success": False, "detail": "앱 알림이나 카톡 중 하나는 골라 주세요."}
    snap = _db().collection(STREAKS).document(_sid(name)).get()
    cur = nd.streak_view((snap.to_dict() or {}) if snap.exists else None, _now().date())["current"]
    m = nd.sample_message(kind, name, _now(), cur or 5)
    cfg = load_config()
    memo = active_memo(cfg, _now().date())
    nv = notice_vars(m, memo, cfg.get("penalty", ""))
    out = {"success": True, "title": m["title"], "body": push_body(m, memo),
           "kakao_kind": NOTICE_KIND, "kakao_vars": nv, "push": None, "kakao": None}
    if push:
        try:
            out["push"] = int(H["send_push_to_student"](name, m["title"], out["body"], "/", "nudge-test"))
        except Exception as e:
            out["push"] = 0
            out["push_error"] = str(e)
    if kakao:
        out["kakao"] = H["kakao_message"](NOTICE_KIND, "student", [{"name": name, "vars": nv}])
    return out


# ── 클리닉 안내 카톡: 원장님이 눌러서 보낸다 ─────────────────
CLINIC_LOG = "clinic_notice_log"


def clinic_rows(day: str) -> List[dict]:
    """그날 클리닉이 있는 학생(퇴원생 빼고), 시각 순. sent: 그날 안내 카톡을 보낸 시각(안 보냈으면 '')."""
    d = nd._d(day)
    if not d:
        return []
    db = _db()
    left = {x.id for x in db.collection("students").stream() if (x.to_dict() or {}).get("withdrawn")}
    names = {x.id for x in db.collection("students").stream()}
    times: Dict[str, str] = {}
    for c in (x.to_dict() or {} for x in db.collection("clinics").stream()):
        who = str(c.get("student_name") or "").strip()
        if not who or who in left or who not in names:
            continue
        t = clinic_today([c], who, d)
        if t and (who not in times or t < times[who]):
            times[who] = t
    out = []
    for who, t in sorted(times.items(), key=lambda kv: (kv[1], kv[0])):
        snap = db.collection(CLINIC_LOG).document(_sid(f"{d.isoformat()}__{who}")).get()
        out.append({"name": who, "time": t, "sent": ((snap.to_dict() or {}).get("at") or "") if snap.exists else ""})
    return out


def _clinic_hhmm(t: str) -> str:
    try:
        hh, mm = str(t).split(":")[:2]
        return nd._hhmm(datetime(2000, 1, 1, int(hh), int(mm)))
    except (ValueError, TypeError):
        return str(t)


def send_clinic_notice(items: List[dict], push: bool = False) -> dict:
    """원장님이 고른 학생에게 클리닉 일정 카톡(알림장 틀). 학생마다 날짜 · 시간을 따로 정할 수 있다
    (클리닉 시간이 학생마다 바뀌므로 등록된 일정에 없는 학생 · 시간도 보낸다). push 면 앱 알림도 같이."""
    names = {x.id for x in _db().collection("students").stream() if not (x.to_dict() or {}).get("withdrawn")}
    jobs, skipped, seen = [], [], set()
    for it in items or []:
        n = str((it or {}).get("name") or "").strip()
        d = nd._d((it or {}).get("date"))
        hm = str((it or {}).get("time") or "").strip()[:5]
        if not n or n in seen:
            continue
        seen.add(n)
        try:
            hh, mm = (int(x) for x in hm.split(":"))
            ok_time = 0 <= hh < 24 and 0 <= mm < 60
        except ValueError:
            ok_time = False
        if n not in names or not d or not ok_time:
            skipped.append(n)
            continue
        jobs.append({"name": n, "date": d, "time": f"{hh:02d}:{mm:02d}",
                     "vars": {"날짜": nd._day_label(d), "시각": _clinic_hhmm(f"{hh}:{mm}")}})
    if not jobs:
        return {"success": False, "detail": "학생 · 날짜 · 시간을 확인해 주세요.", "skipped": skipped}
    cfg = load_config()
    penalty = cfg.get("penalty", "")
    res = H["kakao_message"](NOTICE_KIND, "student", [{"name": j["name"], "vars": {
        "진도": NOTICE_TOPIC["클리닉"], "과제": NONE,
        "알림장": notice_text("🩺 클리닉 일정 안내",
                             f"📅 {j['vars']['날짜']} {j['vars']['시각']}\n"
                             f"{nd.call_name(j['name'])}, 잊지 말고 시간 맞춰 와! 오면 키오스크에서 '클리닉 등원'을 꼭 눌러 줘.",
                             "", penalty)}} for j in jobs])
    if not res.get("success"):
        return {"success": False, "detail": res.get("detail") or "보내지 못했습니다.", "skipped": skipped}
    bad = set(res.get("no_phone") or []) | set(res.get("unknown") or [])
    pushed = []
    if push:
        for j in jobs:
            try:
                body = f"{nd.call_name(j['name'])}, {j['vars']['날짜']} {j['vars']['시각']} 클리닉이야! 늦지 말고 와 😊"
                if H["send_push_to_student"](j["name"], "🩺 클리닉 일정 안내", body, "/", "clinic-" + j["date"].isoformat()):
                    pushed.append(j["name"])
            except Exception as e:
                print("[클리닉 안내] 앱 알림 실패:", repr(e))
    at = _now().strftime("%m/%d %H:%M")
    sent = []
    for j in jobs:
        if j["name"] in bad and j["name"] not in pushed:
            continue
        sent.append(j["name"])
        _db().collection(CLINIC_LOG).document(_sid(f"{j['date'].isoformat()}__{j['name']}")).set(
            {"date": j["date"].isoformat(), "student_name": j["name"], "time": j["time"], "at": at})
    return {"success": True, "sent": sent, "kakao_sent": [j["name"] for j in jobs if j["name"] not in bad],
            "pushed": pushed, "skipped": skipped,
            "no_phone": res.get("no_phone") or [], "unknown": res.get("unknown") or []}


# ── 숙제 카톡: 원장님이 과제를 골라 안 낸 학생에게 눌러서 보낸다 (2026-11-27) ──
HW_LOG = "hw_notice_log"
HW_RANGE_BEFORE, HW_RANGE_AFTER = 14, 21      # 마감이 2주 전 ~ 3주 뒤인 과제
HW_NODL_DAYS = 30                             # 마감일 없는 과제는 30일 안에 낸 것만


def homework_rows(now: Optional[datetime] = None) -> List[dict]:
    """최근 과제와 학생별 제출 여부 · 오늘 보낸 시각.
    순서: 마감 전(가까운 순) → 마감일 없음(최근에 낸 순) → 마감 지남(최근에 지난 순)."""
    now = now or _now()
    today = now.date()
    db = _db()
    lo, hi = (today - timedelta(days=HW_RANGE_BEFORE)).isoformat(), (today + timedelta(days=HW_RANGE_AFTER)).isoformat()
    since = (today - timedelta(days=HW_NODL_DAYS)).isoformat()
    hws = []
    for d in db.collection("homeworks").stream():
        v = d.to_dict() or {}
        if v.get("hidden"):
            continue
        dl = str(v.get("deadline") or "").strip()
        if nd.parse_deadline(dl):
            if lo <= dl[:10] <= hi:
                hws.append({"title": d.id, **v})
        elif str(v.get("created_at") or "")[:10] >= since:
            hws.append({"title": d.id, **v})
    if not hws:
        return []
    studs = []
    for d in db.collection("students").stream():
        v = d.to_dict() or {}
        if v.get("withdrawn") or H["is_preview"](d.id):
            continue
        studs.append({"name": d.id, **v})
    sent = {}
    for d in db.collection(HW_LOG).where("date", "==", today.isoformat()).stream():
        v = d.to_dict() or {}
        sent[(str(v.get("title")), str(v.get("student_name")))] = str(v.get("at") or "")
    out = []
    for hw in hws:
        t = hw["title"]
        done = {str(r.get("student_name", "")).strip() for r in
                (x.to_dict() or {} for x in db.collection("reports").where("task_name", "==", t).stream())
                if r.get("type") == "과제 제출"}
        rows = []
        for s in studs:
            if not H["homework_visible_to_student"](hw, s["name"], info=H["targeting_info_from"](s)):
                continue
            rows.append({"name": s["name"], "class_name": class_of(s), "submitted": s["name"] in done,
                         "sent": sent.get((t, s["name"]), "")})
        if not rows:
            continue
        dl = nd.parse_deadline(hw.get("deadline"))
        rows.sort(key=lambda r: (r["submitted"], r["class_name"] or "~", r["name"]))
        status = "none" if not dl else ("passed" if dl <= now else "open")
        out.append({"title": t, "deadline": str(hw.get("deadline") or ""), "kind": "clinic" if hw.get("kind") == "clinic" else "class",
                    "status": status, "passed": status == "passed",
                    "dleft": nd._dleft(dl.date(), today) if dl else "", "due": nd._due(dl) if dl else "",
                    "created": str(hw.get("created_at") or "")[:10],
                    "missing": sum(not r["submitted"] for r in rows), "total": len(rows), "students": rows})
    order = {"open": 0, "none": 1, "passed": 2}
    out.sort(key=lambda h: str(h["deadline"]) if h["status"] == "open" else "")
    out.sort(key=lambda h: h["created"] if h["status"] == "none" else (str(h["deadline"]) if h["status"] == "passed" else ""), reverse=True)
    out.sort(key=lambda h: order[h["status"]])
    return out


def send_homework_notice(titles, names: List[str], push: bool = False) -> dict:
    """고른 학생에게 숙제 카톡(알림장 틀). 숙제를 여러 개 고르면 학생마다 그중 안 낸 것만 모아 한 통으로 보낸다.
    하나면: 마감 전 '과제 마감 안내' · 마감일 없음 '과제 제출 안내' · 지남 '과제 미제출 안내'. 다 낸 학생은 건너뛴다."""
    if isinstance(titles, str):
        titles = [titles]
    db = _db()
    hws = []
    for t in dict.fromkeys(str(x or "").strip() for x in (titles or [])):
        snap = db.collection("homeworks").document(H["sanitize_doc_id"](t)).get() if t else None
        if snap and snap.exists:
            hws.append({"title": t, **(snap.to_dict() or {})})
    if not hws:
        return {"success": False, "detail": "그 과제를 찾지 못했습니다."}
    now = _now()
    studs = {}
    for x in db.collection("students").stream():
        v = x.to_dict() or {}
        if not v.get("withdrawn"):
            studs[x.id] = {"name": x.id, **v}
    picked, skipped = [], []
    for n in dict.fromkeys(str(x or "").strip() for x in (names or [])):
        if n:
            (picked if n in studs else skipped).append(n)
    if not picked:
        return {"success": False, "detail": "보낼 학생을 골라 주세요.", "skipped": skipped}
    done = {hw["title"]: {str(r.get("student_name", "")).strip() for r in
                          (x.to_dict() or {} for x in db.collection("reports").where("task_name", "==", hw["title"]).stream())
                          if r.get("type") == "과제 제출"} for hw in hws}
    missing, all_done = {}, []
    for n in picked:
        info = H["targeting_info_from"](studs[n])
        mine = [hw for hw in hws if n not in done[hw["title"]] and H["homework_visible_to_student"](hw, n, info=info)]
        if mine:
            missing[n] = mine
        else:
            all_done.append(n)
    if not missing:
        return {"success": False, "detail": "고른 학생은 고른 숙제를 모두 냈습니다.", "done": all_done, "skipped": skipped}
    cfg = load_config()
    memo, penalty = active_memo(cfg, now.date()), cfg.get("penalty", "")
    msgs = {n: nd.homework_bundle_message(n, [(hw["title"], hw.get("deadline")) for hw in mine], now)
            for n, mine in missing.items()}
    res = H["kakao_message"](NOTICE_KIND, "student", [{"name": n, "vars": notice_vars(m, memo, penalty)} for n, m in msgs.items()])
    if not res.get("success"):
        return {"success": False, "detail": res.get("detail") or "보내지 못했습니다.", "skipped": skipped}
    bad = set(res.get("no_phone") or []) | set(res.get("unknown") or [])
    pushed = []
    if push:
        for n, m in msgs.items():
            try:
                if H["send_push_to_student"](n, m["title"], push_body(m, memo), "/", "hw-" + m["key"][:60]):
                    pushed.append(n)
            except Exception as e:
                print("[숙제 카톡] 앱 알림 실패:", repr(e))
    at = now.strftime("%H:%M")
    sent = [n for n in missing if n not in bad or n in pushed]
    for n in sent:
        for hw in missing[n]:
            db.collection(HW_LOG).document(_sid(f"{now.date().isoformat()}__{hw['title']}__{n}")).set(
                {"date": now.date().isoformat(), "title": hw["title"], "student_name": n, "at": at})
    kinds = {m["kind"] for m in msgs.values()}
    kind = {"hwlate": "미제출", "hwd": "과제마감"}.get(next(iter(kinds)), "과제안내") if len(kinds) == 1 else "과제안내"
    return {"success": True, "sent": sent, "kakao_sent": [n for n in missing if n not in bad], "pushed": pushed,
            "skipped": skipped, "done": all_done, "no_phone": res.get("no_phone") or [], "unknown": res.get("unknown") or [],
            "sent_titles": {n: [hw["title"] for hw in missing[n]] for n in sent}, "kind": kind, "at": at}


def student_classes() -> dict:
    """클리닉 안내에서 학생을 반별로 찾게: students(이름 목록) + classes([{name, students}], 반 이름순, '반 없음'은 맨 뒤)."""
    names, by_class = [], {}
    for x in _db().collection("students").stream():
        v = x.to_dict() or {}
        if v.get("withdrawn") or H["is_preview"](x.id):
            continue
        names.append(x.id)
        cls = H["targeting_info_from"](v).get("all_classes") or []
        for c in (cls or ["반 없음"]):
            by_class.setdefault(c, []).append(x.id)
    order = sorted(by_class, key=lambda c: (c == "반 없음", c))
    return {"students": sorted(names), "classes": [{"name": c, "students": sorted(by_class[c])} for c in order]}


class ClinicSendReq(BaseModel):
    items: list = []          # [{name, date: 'YYYY-MM-DD', time: 'HH:MM'}]
    push: bool = False


class HomeworkSendReq(BaseModel):
    title: str = ""            # 예전 화면(숙제 하나)
    titles: list = []          # 숙제 여러 개(2026-11-27)
    names: list = []
    push: bool = False


class NudgeTestReq(BaseModel):
    student_name: str = ""
    kind: str = "pr19"
    push: bool = True
    kakao: bool = False


class NudgeConfigReq(BaseModel):
    enabled: bool = False
    kakao: bool = True
    exclude: list = []
    new_key: bool = False
    memo: Optional[str] = None          # 원장님 한마디(비우면 안 붙는다). None 이면 그대로 둔다
    memo_until: Optional[str] = None    # 이날까지만 붙인다(YYYY-MM-DD, 비우면 지울 때까지)
    penalty: Optional[str] = None       # 지키지 않으면(불이익): 과제 · 클리닉 카톡(알림장) 끝에 붙는다


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
                "memo": active_memo(load_config(), today),
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
        if req.memo is not None:
            data["memo"] = str(req.memo).strip()[:MEMO_MAX]
        if req.penalty is not None:
            data["penalty"] = str(req.penalty).strip()[:PENALTY_MAX]
        if req.memo_until is not None:
            mu = str(req.memo_until).strip()[:10]
            data["memo_until"] = mu if nd._d(mu) else ""
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

    @app.get("/api/admin/nudge/clinics", dependencies=[Depends(verify_admin)])
    def nudge_clinics(day: str = ""):
        d = nd._d(day) or _now().date()
        return {"success": True, "day": d.isoformat(), "label": nd._day_label(d), "rows": clinic_rows(d.isoformat()),
                **student_classes()}

    @app.post("/api/admin/nudge/clinic_send", dependencies=[Depends(verify_admin)])
    def nudge_clinic_send(req: ClinicSendReq):
        return send_clinic_notice(req.items, bool(req.push))

    @app.get("/api/admin/nudge/homeworks", dependencies=[Depends(verify_admin)])
    def nudge_homeworks():
        return {"success": True, "homeworks": homework_rows()}

    @app.post("/api/admin/nudge/homework_send", dependencies=[Depends(verify_admin)])
    def nudge_homework_send(req: HomeworkSendReq):
        return send_homework_notice(req.titles or [req.title], req.names, bool(req.push))

    @app.post("/api/admin/nudge/test", dependencies=[Depends(verify_admin)])
    def nudge_test(req: NudgeTestReq):
        return send_test(req.student_name, req.kind, bool(req.push), bool(req.kakao))

    @app.post("/api/admin/nudge/run", dependencies=[Depends(verify_admin)])
    def nudge_run(dry: bool = True):
        return run_tick(bool(dry))
