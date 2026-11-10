"""문제 공장에서 만든 문제 세트를 학생 앱(logyedu.co.kr) 과제 · 클리닉으로 낼 때 쓰는 변환 (2026-11-10).

학생 앱 과제는 정답표(answers)와 문항별 해설(explanations)만 있으면 학생이 OMR로 답을 내고
그 자리에서 채점받는다. 문제 글은 따로 '문제지'로 보여 준다(정답은 빼고).
"""
from typing import Dict, List, Tuple


def _clean(v) -> str:
    return " ".join(str(v if v is not None else "").split())


def homework_answers(data: dict) -> Tuple[List[str], Dict[str, str]]:
    """세트 data → (정답표, {문항 번호: 해설}).

    객관식은 정답 번호, OX는 O/X, 단답형 · 빈칸은 정답 글. 함께 인정하는 답(accept)이 있으면
    '정답|다른 답' 으로 이어 '둘 중 하나면 맞음'이 되게 한다(학생 앱 채점 규칙)."""
    answers, expl = [], {}
    for i, q in enumerate((data or {}).get("questions") or []):
        no = i + 1
        kind = q.get("kind")
        a = q.get("answer")
        if kind == "mcq":
            try:
                ans = str(int(a))
            except (TypeError, ValueError):
                ans = _clean(a)
        elif kind == "ox":
            ans = _clean(a).upper().replace("○", "O").replace("×", "X")
        else:
            alts = [_clean(a)] + [_clean(x) for x in (q.get("accept") or [])]
            seen, keep = set(), []
            for x in alts:
                if x and x not in seen:
                    seen.add(x)
                    keep.append(x.replace("|", "/"))
            ans = "|".join(keep)
        answers.append(ans or "-")
        e = str(q.get("explanation") or "").strip()
        if e:
            expl[str(no)] = e
    return answers, expl


def unique_title(title: str, exists) -> str:
    """같은 이름의 과제가 있으면 ' (2)', ' (3)' … 을 붙인다."""
    base = " ".join(str(title or "").split())[:60] or "문제 공장 과제"
    if not exists(base):
        return base
    n = 2
    while exists(f"{base} ({n})") and n < 100:
        n += 1
    return f"{base} ({n})"
