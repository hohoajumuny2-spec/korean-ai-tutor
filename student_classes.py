"""학생의 과목별 반(국어 · 수학 · 영어) 다루기.

학생 명단(students)에는 과목별 반이 class_names = {"korean": .., "math": .., "english": ..} 로,
예전부터 쓰던 반 한 칸이 class_name(국어) 으로 들어 있다.

💡 예전에는 관리자 화면 '선택 학생 반 배정'이 class_name 한 칸만 덮어써서, 국어반 학생을
   수학반에 넣으면 국어반에서 빠졌다 — 한 학생을 국어 · 수학 반에 동시에 둘 수 없었다(2026-10-25).
"""
SUBJECT_KEYS = ("korean", "math", "english")


def _subject(s) -> str:
    s = str(s or "korean").strip().lower()
    return s if s in SUBJECT_KEYS else "korean"


def guess_class_subject(class_name: str) -> str:
    """반 이름으로 과목을 짐작한다. '고2 수학 A반' → math, '영어 독해반' → english, 나머지 → korean."""
    n = str(class_name or "")
    if "수학" in n:
        return "math"
    if "영어" in n:
        return "english"
    return "korean"


def class_assignment_fields(data: dict, subject: str, target: str) -> dict:
    """한 과목의 반만 바꾸고 다른 과목 반은 그대로 둔다. 학생 문서에 merge 로 쓸 값을 돌려준다."""
    data = data or {}
    subject = _subject(subject)
    target = str(target or "").strip()
    names = dict(data.get("class_names") or {})
    # 과목별 반을 처음 쓰는 학생은 예전 한 칸(국어) 값을 국어반으로 옮겨 둔다
    if "korean" not in names and data.get("class_name"):
        names["korean"] = str(data.get("class_name") or "").strip()
    names[subject] = target
    out = {"class_names": names}
    if subject == "korean":
        out["class_name"] = target            # 예전 화면 · 기능이 읽는 칸도 맞춰 둔다
    if target:
        subs = list(data.get("subjects") or ["korean"])
        if subject not in subs:
            out["subjects"] = subs + [subject]  # 수학반에 넣으면 수학 과목도 듣는 것으로
    return out


def merge_added_student(data: dict, school: str, grade: str, class_name: str = "",
                        class_names: dict = None, subjects: list = None) -> dict:
    """'학생 추가'로 이미 있는 학생을 다시 넣을 때 쓸 값. 있던 과목 · 다른 과목 반을 지우지 않는다.

    💡 예전에는 국어반 학생(임지섭)을 수학반으로 한 번 더 추가하면 과목이 ['math'] 로,
       국어반 칸(class_name)이 수학반 이름으로 덮여 국어 정보가 사라졌다(2026-10-25)."""
    data = dict(data or {})
    out = {"school": school, "grade": grade}
    had = list(data.get("subjects") or (["korean"] if data else []))
    want = [_subject(s) for s in (subjects or [])] or (["korean"] if not had else [])
    subs = list(dict.fromkeys(had + want))
    if subs:
        out["subjects"] = subs
    merged = dict(data)
    merged["subjects"] = subs
    for k, v in (class_names or {}).items():
        if str(v or "").strip():
            got = class_assignment_fields(merged, k, v)
            merged.update(got)
            out.update(got)
    if str(class_name or "").strip():
        got = class_assignment_fields(merged, guess_class_subject(class_name), class_name)
        merged.update(got)
        out.update(got)
    if "class_name" not in out and not data.get("class_name"):
        out["class_name"] = ""              # 새 학생: 예전 칸도 만들어 둔다
    return out
