"""학생별 약점 분석 (2026-11-26 원장님 요청).

채점 기록(reports) + 문항 유형(qmeta)으로 학생이 어느 유형에 약한지 본다. DB 없이 계산만 한다.

  · 유형별: 푼 문항 수 · 틀린 수 · 정답률 · 틀린 이유(찍음 · 둘 중 고민 · 잘못 봄 · 모름) · 최근 흐름 · 틀린 문항 예
  · 약점 순위: study_extras.weak_tags 와 같은 무게(최근 · '찍음'일수록 무겁게) + 정답률
  · 유형이 안 붙은 오답: 어느 자료인지 알려 줘서 원장님이 [AI로 유형 붙이기]를 누를 수 있게
"""
from datetime import date, datetime
from typing import Callable, Dict, Iterable, List, Optional

import study_extras

KINDS = {"과제 제출", "타임어택 퀴즈", "모의고사", "출제 문제"}
RECENT_DAYS = 21          # '최근'으로 보는 기간(이 안 · 밖의 정답률을 견줘 흐름을 본다)
REASON_LABEL = {"guess": "찍음", "two": "둘 중 고민", "misread": "잘못 봄", "unsure": "모름"}


def _num(v) -> Optional[int]:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _day(v) -> Optional[date]:
    try:
        return datetime.strptime(str(v or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def latest_reports(rows: Iterable[dict]) -> List[dict]:
    """같은 자료를 여러 번 냈으면 가장 나중 것만(최근 순)."""
    best: Dict[tuple, dict] = {}
    for r in rows or []:
        if str(r.get("type", "")) not in KINDS:
            continue
        key = (r.get("type"), str(r.get("task_name", "")))
        if key not in best or str(r.get("submitted_at", "")) > str(best[key].get("submitted_at", "")):
            best[key] = r
    return sorted(best.values(), key=lambda r: str(r.get("submitted_at", "")), reverse=True)


def wrong_set(r: dict) -> set:
    """이 기록에서 아직 틀린 것으로 보는 문항(다시 풀어 고친 것은 빼되, '찍음'으로 고른 것은 남긴다 — student_misses 와 같다)."""
    reasons = r.get("reasons") or {}
    wrongs = {w for w in (_num(x) for x in (r.get("wrongs") or [])) if w}
    retry = r.get("retry") if isinstance(r.get("retry"), dict) else {}
    if retry.get("count") and retry.get("wrongs") is not None:
        keep = {w for w in (_num(x) for x in retry.get("wrongs") or []) if w}
        wrongs = {w for w in wrongs if w in keep or reasons.get(str(w)) == "guess"}
    return wrongs


def trend(recent: dict, before: dict) -> str:
    """최근 3주와 그 전의 정답률 비교 → 'up'(나아짐) · 'down'(나빠짐) · 'same' · 'new'(최근에 처음) · ''(판단 어려움)."""
    if recent["n"] >= 2 and before["n"] >= 2:
        a = 1 - recent["w"] / recent["n"]
        b = 1 - before["w"] / before["n"]
        if a - b >= 0.15:
            return "up"
        if b - a >= 0.15:
            return "down"
        return "same"
    if recent["n"] >= 2 and before["n"] == 0:
        return "new"
    return ""


def analyze(rows: Iterable[dict], meta_for: Callable[[str, str], dict], today: Optional[date] = None,
            top: int = 5) -> dict:
    """rows: 그 학생의 reports, meta_for(kind, title) → {"1": {"tag": ...}}."""
    today = today or date.today()
    tags: Dict[str, dict] = {}
    misses: List[dict] = []
    untagged: Dict[tuple, int] = {}
    reasons_total: Dict[str, int] = {}
    wrong_total = tasks = 0
    for r in latest_reports(rows):
        kind, title = r.get("type", ""), str(r.get("task_name", ""))
        at = str(r.get("submitted_at", ""))[:10]
        d = _day(at)
        recent = d is not None and (today - d).days <= RECENT_DAYS
        meta = meta_for(kind, title) or {}
        reasons = r.get("reasons") or {}
        unsure = {u for u in (_num(x) for x in (r.get("unsure") or [])) if u}
        wrongs = wrong_set(r)
        tasks += 1
        wrong_total += len(wrongs)
        for no_s, m in meta.items():
            tag = study_extras.clean_tag((m or {}).get("tag"))
            no = _num(no_s)
            if not tag or not no:
                continue
            t = tags.setdefault(tag, {"tag": tag, "n": 0, "wrong": 0, "reasons": {}, "examples": [],
                                      "recent": {"n": 0, "w": 0}, "before": {"n": 0, "w": 0}, "last_wrong": ""})
            t["n"] += 1
            (t["recent"] if recent else t["before"])["n"] += 1
            if no in wrongs:
                t["wrong"] += 1
                (t["recent"] if recent else t["before"])["w"] += 1
                why = reasons.get(str(no)) or ("unsure" if no in unsure else "")
                if why:
                    t["reasons"][why] = t["reasons"].get(why, 0) + 1
                if len(t["examples"]) < 4:
                    t["examples"].append({"kind": kind, "title": title, "no": no, "at": at, "reason": why})
                t["last_wrong"] = max(t["last_wrong"], at)
                misses.append({"tag": tag, "reason": reasons.get(str(no), ""), "unsure": no in unsure, "at": at})
        for no in wrongs:
            if not study_extras.clean_tag((meta.get(str(no)) or {}).get("tag")):
                untagged[(kind, title)] = untagged.get((kind, title), 0) + 1
        for no in wrongs:
            why = reasons.get(str(no)) or ("unsure" if no in unsure else "")
            if why:
                reasons_total[why] = reasons_total.get(why, 0) + 1

    weight = {w["tag"]: w["score"] for w in study_extras.weak_tags(misses, None, today)}
    rows_out = []
    for t in tags.values():
        rate = round(100 * (t["n"] - t["wrong"]) / t["n"]) if t["n"] else None
        rows_out.append({
            "tag": t["tag"], "solved": t["n"], "wrong": t["wrong"], "correct_rate": rate,
            "score": round(weight.get(t["tag"], 0.0), 2), "reasons": t["reasons"],
            "trend": trend(t["recent"], t["before"]), "last_wrong": t["last_wrong"], "examples": t["examples"],
        })
    # 약점 순위: 무게(최근 · 찍음) 먼저, 같으면 정답률 낮은 순 — 틀린 적이 없는 유형은 '잘하는 유형'으로
    weak = sorted([x for x in rows_out if x["wrong"]], key=lambda x: (-x["score"], x["correct_rate"] or 0, -x["wrong"]))
    strong = sorted([x for x in rows_out if not x["wrong"] and x["solved"] >= 3], key=lambda x: -x["solved"])
    tagged_wrong = sum(x["wrong"] for x in rows_out)
    return {
        "weak": weak[:top], "all": sorted(rows_out, key=lambda x: (x["correct_rate"] if x["correct_rate"] is not None else 101, x["tag"])),
        "strong": strong[:5],
        "reasons": {REASON_LABEL.get(k, k): v for k, v in sorted(reasons_total.items(), key=lambda kv: -kv[1])},
        "tasks": tasks, "wrong_total": wrong_total, "tagged_wrong": tagged_wrong,
        "untagged_wrong": sum(untagged.values()),
        "untagged_tasks": [{"kind": k, "title": t, "wrong": n} for (k, t), n in sorted(untagged.items(), key=lambda kv: -kv[1])][:12],
    }


def summary_line(res: dict, name: str = "") -> str:
    """원장님이 알림장 · 상담에 그대로 쓸 수 있는 한 줄."""
    w = res.get("weak") or []
    if not w:
        return f"{name} 학생은 아직 약점으로 볼 만한 유형이 없습니다." if name else "아직 약점으로 볼 만한 유형이 없습니다."
    parts = [f"'{x['tag']}'({x['solved']}문항 중 {x['wrong']}개 틀림)" for x in w[:3]]
    who = f"{name} 학생은 " if name else ""
    return f"{who}최근 {', '.join(parts)}에서 약합니다."
