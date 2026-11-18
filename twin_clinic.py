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
        "hw": str(doc.get("hw") or "").strip()[:120],       # 클리닉 과제에서 들어온 경우 그 과제 이름
        "createdAt": str(doc.get("createdAt") or "").strip()[:40],
        "total": total, "right": right,
        "answers": _int_list(doc.get("answers"), 0, 5),
        "wrong": _int_list(doc.get("wrong"), 1, MAX_ITEMS),
        "retry": [{**r, "reason": str(r.get("reason") or "")[:60]} for r in rows("retry", ("no", "pick", "correct", "reason"))],
        "twins": rows("twins", ("vid", "no", "pick", "correct")),
        "ask": _int_list(doc.get("ask"), 1, MAX_ITEMS),
    }


# ── 원장님이 올리는 세트(원래 문제 + 유사 문제) ─────────────────────────
MAX_SET_BYTES = 900_000      # Firestore 문서 한 개(1MB) 안에 들도록
CIRCLED = "①②③④⑤"


def _txt(v, n):
    return str(v or "").strip()[:n]


def _question(q, passages, where):
    if not isinstance(q, dict):
        raise ValueError(f"{where}: 형식이 올바르지 않습니다.")
    choices = [_txt(c, 600) for c in (q.get("choices") or [])][:5]
    if len(choices) != 5 or not all(choices):
        raise ValueError(f"{where}: 선택지 ①~⑤ 다섯 개가 모두 있어야 합니다.")
    try:
        answer = int(q.get("answer"))
    except (TypeError, ValueError):
        answer = 0
    if not 1 <= answer <= 5:
        raise ValueError(f"{where}: 정답(1~5)이 없습니다.")
    pid = _txt(q.get("passage"), 40)
    if pid and pid not in passages:
        pid = ""
    return {"passage": pid, "stem": _txt(q.get("stem"), 1500),
            "box": [_txt(b, 1500) for b in (q.get("box") or [])][:30],
            "choices": choices, "answer": answer,
            "explain": _txt(q.get("explain"), 3000),
            "note": [_txt(b, 300) for b in (q.get("note") or [])][:5]}


def clean_set(bank) -> dict:
    """원장님이 만든 세트(문항은행 JSON)를 점검한다. 문항마다 유사 문제가 1개 이상 있어야 한다."""
    if not isinstance(bank, dict):
        raise ValueError("세트 형식이 올바르지 않습니다.")
    if len(json.dumps(bank, ensure_ascii=False).encode("utf-8")) > MAX_SET_BYTES:
        raise ValueError("세트가 너무 큽니다. 지문이나 문항을 나눠 두 세트로 올려 주세요.")
    title = _txt(bank.get("title"), 120)
    if not title:
        raise ValueError("세트 제목을 적어 주세요.")
    passages = {}
    out_p = []
    for i, p in enumerate((bank.get("passages") or [])[:30]):
        if not isinstance(p, dict):
            continue
        pid = _txt(p.get("id"), 40) or f"p{i + 1}"
        passages[pid] = True
        out_p.append({"id": pid, "title": _txt(p.get("title"), 120) or f"지문 {i + 1}",
                      "lead": _txt(p.get("lead"), 200), "text": _txt(p.get("text"), 20000)})
    items = []
    for it in (bank.get("items") or [])[:MAX_ITEMS]:
        try:
            no = int((it or {}).get("no"))
        except (TypeError, ValueError):
            raise ValueError("문항 번호가 올바르지 않습니다.")
        if it.get("twinOnly"):
            # 원래 문제는 종이로만 — 정답은 과제 정답표에 있다. 유사 문제만 점검한다
            pid = _txt(it.get("passage"), 40)
            q = {"passage": pid if pid in passages else "", "stem": "", "box": [], "choices": [], "answer": 0,
                 "explain": "", "note": [], "twinOnly": True}
        else:
            q = _question(it, passages, f"{no}번")
        q["no"] = no
        q["points"] = 3 if str(it.get("points")) == "3" else 2
        variants = []
        for j, v in enumerate((it.get("variants") or [])[:4]):
            vq = _question(v, passages, f"{no}번 유사 문제 {j + 1}")
            vq["vid"] = f"{no}-{'ABCD'[j]}"
            if not vq["passage"]:
                vq["passage"] = q["passage"]
            variants.append(vq)
        if not variants:
            raise ValueError(f"{no}번: 유사 문제가 없습니다. 문항마다 유사 문제를 1개 이상 넣어 주세요.")
        q["variants"] = variants
        items.append(q)
    if not items:
        raise ValueError("문항이 없습니다.")
    nos = [x["no"] for x in items]
    if len(set(nos)) != len(nos):
        raise ValueError("문항 번호가 겹칩니다.")
    items.sort(key=lambda x: x["no"])
    return {"title": title, "school": _txt(bank.get("school"), 60), "note": _txt(bank.get("note"), 200),
            "passages": out_p, "items": items, "twinOnly": all(i.get("twinOnly") for i in items)}
