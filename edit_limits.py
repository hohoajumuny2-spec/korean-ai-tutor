"""문항마다 답을 고칠 수 있는 횟수 (2026-11-10).

학생이 제출한 뒤 틀린 문항을 끝없이 고쳐 내며 정답을 맞혀 가는 것을 막는다.
처음 낸 뒤로 한 문항은 MAX_EDITS 번까지만 고칠 수 있고, 그 뒤로는 수업이나
질문 게시판에서 해결한다. 두 길이 같은 횟수를 나눠 쓴다:
  · 과제 OMR 을 다시 내며 답을 바꾼 문항
  · '틀린 문항 다시 풀기'에서 다시 낸 문항

기록은 reports 문서의 q_edits 에 {"3": 2, "7": 1} 처럼 남긴다(문항 번호 → 고친 횟수).
"""
from typing import Dict, List, Tuple

MAX_EDITS = 2
LOCKED_MESSAGE = "이 문항은 이미 2번 고쳤어요. 더 고칠 수 없으니 수업 시간이나 질문 게시판에서 선생님께 물어보세요."


def load_counts(rep: dict) -> Dict[int, int]:
    """reports 문서의 q_edits 를 {문항 번호: 횟수} 로 읽는다. 잘못된 값은 버린다."""
    out: Dict[int, int] = {}
    for k, v in ((rep or {}).get("q_edits") or {}).items():
        try:
            no, n = int(k), int(v)
        except (TypeError, ValueError):
            continue
        if no >= 1 and n > 0:
            out[no] = n
    return out


def dump_counts(counts: Dict[int, int]) -> Dict[str, int]:
    return {str(k): int(v) for k, v in sorted(counts.items()) if v > 0}


def is_locked(counts: Dict[int, int], no: int, limit: int = MAX_EDITS) -> bool:
    return counts.get(no, 0) >= limit


def locked_list(counts: Dict[int, int], limit: int = MAX_EDITS) -> List[int]:
    return sorted(no for no, n in counts.items() if n >= limit)


def _norm(v) -> str:
    return "" if v is None else str(v).strip()


def apply_resubmit(prev_mine: list, new_mine: list, counts: Dict[int, int],
                   limit: int = MAX_EDITS) -> Tuple[list, Dict[int, int], List[int], List[int]]:
    """OMR 을 다시 낼 때: 바뀐 문항만 횟수를 센다.

    이미 다 고친 문항을 또 바꾸려 하면 바꾸지 않고 앞의 답을 그대로 둔다.
    돌려주는 것: (채점할 답, 새 횟수, 이번에 고친 문항, 막혀서 그대로 둔 문항)."""
    counts = dict(counts)
    size = max(len(prev_mine or []), len(new_mine or []))
    final, changed, blocked = [], [], []
    for i in range(size):
        old = _norm(prev_mine[i]) if i < len(prev_mine or []) else ""
        new = _norm(new_mine[i]) if i < len(new_mine or []) else ""
        no = i + 1
        if new == old:
            final.append(new)
        elif counts.get(no, 0) >= limit:
            final.append(old)
            blocked.append(no)
        else:
            counts[no] = counts.get(no, 0) + 1
            final.append(new)
            changed.append(no)
    return final, counts, changed, blocked


def take_retry(nos: List[int], counts: Dict[int, int],
               limit: int = MAX_EDITS) -> Tuple[List[int], Dict[int, int], List[int]]:
    """'틀린 문항 다시 풀기'로 낸 문항마다 한 번씩 센다.

    돌려주는 것: (채점할 문항, 새 횟수, 막혀서 채점하지 않은 문항)."""
    counts = dict(counts)
    allowed, blocked = [], []
    for no in nos:
        if counts.get(no, 0) >= limit:
            blocked.append(no)
        else:
            counts[no] = counts.get(no, 0) + 1
            allowed.append(no)
    return allowed, counts, blocked
