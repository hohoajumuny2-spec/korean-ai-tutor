"""오답 쌍둥이 클리닉 결과 정리.

학생이 시험지 답을 넣고 → 틀린 문항을 다시 풀고 → 틀린 문항마다 쌍둥이 2문제를 푼 결과(doc)를
그대로 받아 저장한다. 화면(rosyedu-web/twin-clinic)이 통계를 다시 계산하므로 문서 모양은 바꾸지 않고,
크기 · 칸만 점검한다.
"""
import json

MAX_DOC_BYTES = 60_000       # 24문항 + 쌍둥이 48문항 결과가 수 KB — 넉넉히
MAX_ITEMS = 200


def _int_list(v, lo=0, hi=999):
    out = []
    for x in (v if isinstance(v, list) else [])[:MAX_ITEMS]:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if lo <= n <= hi:
            out.append(n)
    return out


def clean_result(doc) -> dict:
    """화면이 보낸 결과 문서를 점검해 저장할 모양으로. 이상하면 ValueError."""
    if not isinstance(doc, dict):
        raise ValueError("결과 형식이 올바르지 않습니다.")
    if len(json.dumps(doc, ensure_ascii=False).encode("utf-8")) > MAX_DOC_BYTES:
        raise ValueError("결과가 너무 큽니다.")
    set_id = str(doc.get("setId") or "").strip()[:80]
    student = str(doc.get("student") or "").strip()[:40]
    if not set_id or not student:
        raise ValueError("세트 또는 학생 이름이 없습니다.")
    try:
        total = int(doc.get("total") or 0)
        right = int(doc.get("right") or 0)
    except (TypeError, ValueError):
        raise ValueError("점수 형식이 올바르지 않습니다.")
    if not (0 < total <= MAX_ITEMS) or not (0 <= right <= total):
        raise ValueError("점수 형식이 올바르지 않습니다.")

    def rows(key, fields):
        out = []
        for r in (doc.get(key) if isinstance(doc.get(key), list) else [])[:MAX_ITEMS]:
            if isinstance(r, dict):
                out.append({k: r.get(k) for k in fields if k in r})
        return out

    return {
        "setId": set_id,
        "setTitle": str(doc.get("setTitle") or "").strip()[:120],
        "student": student,
        "studentId": str(doc.get("studentId") or "").strip()[:60] or None,
        "school": str(doc.get("school") or "").strip()[:40],
        "grade": str(doc.get("grade") or "").strip()[:20],
        "createdAt": str(doc.get("createdAt") or "").strip()[:40],
        "total": total, "right": right,
        "answers": _int_list(doc.get("answers"), 0, 5),
        "wrong": _int_list(doc.get("wrong"), 1, MAX_ITEMS),
        "retry": [{**r, "reason": str(r.get("reason") or "")[:60]} for r in rows("retry", ("no", "pick", "correct", "reason"))],
        "twins": rows("twins", ("vid", "no", "pick", "correct")),
        "ask": _int_list(doc.get("ask"), 1, MAX_ITEMS),
    }
