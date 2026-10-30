"""홈페이지(logyedu.com/guide)의 과목별 안내를 읽어 홍보글의 '학원 소개' 재료로 쓴다.

상담용 안내 화면(/guide)은 과목 · 프로그램 내용을 <script id="page-data"> JSON 으로 담고 있다.
홈페이지에서 과목 안내를 고치면 홍보글에도 그대로 반영된다(1시간마다 새로 읽음).
"""
import json
import os
import re
import threading
import time
from typing import Callable, Optional

GUIDE_URL = "https://logyedu.com/guide"
CACHE_SEC = 3600
_lock = threading.Lock()
_cache = {"at": 0.0, "subjects": None, "error": ""}


def parse_guide(html: str) -> list:
    """안내 화면 HTML → 과목 목록([{name, lead, programs: [...]}, ...]). 못 읽으면 빈 목록."""
    m = re.search(r'<script[^>]*id="page-data"[^>]*>(.*?)</script>', html or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return []
    subs = data.get("subjects") if isinstance(data, dict) else None
    return [s for s in subs or [] if isinstance(s, dict) and s.get("name")]


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def subject_text(sub: dict, full: bool = True, limit: int = 2200) -> str:
    """한 과목 안내를 AI에게 줄 몇 줄로. full=False 면 한 줄 요약 + 프로그램 이름만."""
    name = _clean(sub.get("name"))
    lines = [f"■ {name}: {_clean(sub.get('lead'))}"]
    for p in sub.get("programs") or []:
        if not isinstance(p, dict):
            continue
        head = f"- {_clean(p.get('name'))}" + (f" ({_clean(p.get('target'))})" if p.get("target") else "")
        if not full:
            lines.append(head)
            continue
        lines.append(head + (f": {_clean(p.get('goal'))}" if p.get("goal") else ""))
        pts = [_clean(x) for x in (p.get("points") or []) if _clean(x)]
        if pts:
            lines.append("  · 특징: " + " / ".join(pts))
        if p.get("outcome"):
            lines.append("  · 목표 상태: " + _clean(p.get("outcome")))
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def notes_for(subjects: list, subject: str = "") -> str:
    """과목을 고르면 그 과목 자세히, '학원 전체'면 과목마다 짧게. 같은 과목이 없으면 빈 글자."""
    if not subjects:
        return ""
    if subject:
        want = subject.strip()
        hit = [s for s in subjects if _clean(s.get("name")) == want or want in _clean(s.get("name"))]
        # 국어 글이면 국어 DIDIM 1단계인 문해력 과정도 함께 본다
        if want == "국어":
            hit += [s for s in subjects if _clean(s.get("name")) == "문해력" and s not in hit]
        return "\n\n".join(subject_text(s, full=True) for s in hit)
    return "\n\n".join(subject_text(s, full=False, limit=700) for s in subjects)


def _fetch(url: str) -> str:
    import requests
    r = requests.get(url, timeout=15, headers={"User-Agent": "logyedu-sns-maker"})
    r.raise_for_status()
    return r.text


def load(fetch: Optional[Callable[[str], str]] = None, now: Optional[float] = None) -> tuple:
    """(과목 목록, 오류 글자). 1시간 동안은 한 번 읽은 것을 쓴다. 못 읽어도 예전 것이 있으면 그것을 쓴다."""
    now = time.time() if now is None else now
    url = (os.environ.get("LOGYEDU_GUIDE_URL", "").strip() or GUIDE_URL)
    with _lock:
        if _cache["subjects"] is not None and now - _cache["at"] < CACHE_SEC:
            return _cache["subjects"], _cache["error"]
    try:
        subs = parse_guide((fetch or _fetch)(url))
        err = "" if subs else "홈페이지 안내에서 과목 내용을 찾지 못했습니다."
    except Exception as e:  # 홈페이지가 잠깐 안 열려도 글쓰기는 된다
        subs, err = None, f"홈페이지를 열지 못했습니다({type(e).__name__})."
    with _lock:
        if subs:
            _cache.update(at=now, subjects=subs, error="")
            return subs, ""
        old = _cache["subjects"] or []
        _cache.update(at=now, subjects=old, error=err)
        return old, err


def reset_cache():
    with _lock:
        _cache.update(at=0.0, subjects=None, error="")
