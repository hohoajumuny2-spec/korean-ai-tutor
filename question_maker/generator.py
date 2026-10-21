"""지문 → 문제 세트. 출제, 검수, 말로 고치기를 맡는다.

AI에게는 JSON으로 답하게 하고, 받은 답은 여기서 하나하나 확인·정리한다.
- 문항 수·종류·선지 개수·정답 형식이 맞는지
- 지문을 AI가 몰래 고쳐 쓰지 않았는지 (기호·밑줄만 넣었는지)
- 객관식 정답 번호가 한쪽으로 몰리거나 규칙적이지 않은지 (코드가 선지 자리를 바꿔 고르게 맞춘다)
"""

import difflib
import json
import random
import re

from .catalog import (DEFAULT_STYLE, DIFFICULTIES, KIND_RULES, KINDS, MAX_QUESTIONS,
                      QUESTIONS_PER_CALL)
from .ai import AIError

CIRCLED = "①②③④⑤⑥⑦"
MARKER_RE = re.compile(r"[㉠-㉭ⓐ-ⓩ㉮-㉻]|\[[A-H]\]|</?u>")


class GenerationError(Exception):
    pass


# ─────────────────────────────────────────────────────────
# 설정 정리
# ─────────────────────────────────────────────────────────
def merge_style(style_data) -> dict:
    style = dict(DEFAULT_STYLE)
    for k, v in (style_data or {}).items():
        if k in style and v is not None:
            style[k] = v
    try:
        style["choice_count"] = 4 if int(style["choice_count"]) == 4 else 5
    except (TypeError, ValueError):
        style["choice_count"] = 5
    try:
        style["negative_percent"] = max(0, min(100, int(style["negative_percent"])))
    except (TypeError, ValueError):
        style["negative_percent"] = 30
    try:
        style["columns"] = 1 if int(style["columns"]) == 1 else 2
    except (TypeError, ValueError):
        style["columns"] = 2
    try:
        style["font_size"] = max(8.0, min(16.0, float(style["font_size"])))
    except (TypeError, ValueError):
        style["font_size"] = 10.5
    if style["explanation"] not in ("short", "detailed"):
        style["explanation"] = "detailed"
    return style


def normalize_recipe(recipe) -> dict:
    recipe = recipe or {}
    items = []
    for it in recipe.get("items") or []:
        kind = str((it or {}).get("kind", "")).strip()
        diff = str((it or {}).get("difficulty", "")).strip()
        try:
            count = int((it or {}).get("count", 0))
        except (TypeError, ValueError):
            count = 0
        if kind in KINDS and diff in DIFFICULTIES and count > 0:
            items.append({"kind": kind, "difficulty": diff, "count": count})
    total = sum(i["count"] for i in items)
    if total <= 0:
        raise GenerationError("문항 수를 1개 이상 정해주세요.")
    if total > MAX_QUESTIONS:
        raise GenerationError(f"한 지문에 {MAX_QUESTIONS}문항까지 만들 수 있습니다. (지금 {total}문항)")
    types = [str(t).strip() for t in (recipe.get("types") or []) if str(t).strip()]
    style_id = recipe.get("style_id")
    try:
        style_id = int(style_id) if style_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        style_id = None
    return {
        "items": items,
        "types": types,
        "extra": str(recipe.get("extra") or "").strip(),
        "verify": bool(recipe.get("verify", True)),
        "style_id": style_id,
    }


def expand_items(recipe: dict, rng: random.Random) -> list:
    """'객관식 상 3개, OX 하 2개' 같은 설정을 문항 한 칸씩으로 펼친다.
    난이도가 순서대로 줄 서지 않게 섞고, 고른 유형은 골고루 나눠 맡긴다."""
    slots = []
    for it in recipe["items"]:
        slots += [{"kind": it["kind"], "difficulty": it["difficulty"]} for _ in range(it["count"])]
    rng.shuffle(slots)
    # 같은 종류끼리는 모아 둔다 (시험지에서 객관식 사이에 OX가 끼어 있으면 보기 어렵다)
    order = {k: i for i, k in enumerate(KINDS)}
    slots.sort(key=lambda s: order[s["kind"]])
    types = list(recipe["types"])
    if types:
        rng.shuffle(types)
        for i, s in enumerate(slots):
            s["type"] = types[i % len(types)]
    return slots


# ─────────────────────────────────────────────────────────
# 프롬프트
# ─────────────────────────────────────────────────────────
JSON_SHAPE = """{
  "intro": "※ 다음 글을 읽고 물음에 답하시오.",
  "passage": "기호와 밑줄을 넣은 지문 전체",
  "source_note": "- 윤동주, 「길」 (문학 작품일 때만. 비문학이면 빈 문자열)",
  "questions": [
    {
      "no": 1,
      "kind": "mcq | short | blank | ox",
      "difficulty": "killer | semi | high | mid | low",
      "type": "문제 유형",
      "stem": "발문",
      "box": "[보기] 안에 들어갈 내용 (필요할 때만, 없으면 빈 문자열)",
      "choices": ["선지1", "선지2", "..."],
      "answer": "객관식은 정답 선지의 번호(1부터 시작하는 정수), OX는 \\"O\\" 또는 \\"X\\", 단답형·빈칸은 정답 글",
      "accept": ["단답형에서 함께 정답으로 인정할 표현 (없으면 빈 배열)"],
      "keep_order": false,
      "explanation": "정답의 근거 (객관식은 선지 번호를 쓰지 말고 근거만)",
      "choice_notes": ["객관식만: 선지마다 맞고 틀린 이유를 한 문장씩, choices와 같은 순서"]
    }
  ]
}"""


def style_block(style: dict) -> str:
    lines = [f"- 객관식 선지는 {style['choice_count']}개입니다. 선지 앞에 번호(①, 1) 등)를 붙이지 마세요. 번호는 프로그램이 붙입니다."]
    neg = style["negative_percent"]
    if neg <= 0:
        lines.append("- 발문은 모두 긍정 발문(가장 적절한 것은?)으로 쓰세요.")
    else:
        lines.append(f"- 객관식 가운데 약 {neg}%는 '적절하지 않은 것은?' 같은 부정 발문으로 쓰세요.")
    if style["use_markers"]:
        lines.append("- 지문의 특정 구절을 물을 때는 지문 그 자리에 ㉠㉡㉢(구절) 또는 ⓐⓑⓒ(어휘) 기호를 넣고, 기호 바로 뒤 "
                     "물을 범위를 <u>…</u>로 감싸 밑줄을 그으세요. 예: ㉠<u>길에 나아갑니다</u>. "
                     "부분별로 묻는 문항이 있으면 문단(시는 연) 앞에 [A] [B] [C]를 넣으세요. 발문에서 쓰지 않는 기호는 넣지 마세요.")
    else:
        lines.append("- 지문에 ㉠ⓐ[A] 같은 기호나 밑줄을 넣지 마세요. 필요하면 발문에 구절을 직접 인용하세요.")
    if style["explanation"] == "short":
        lines.append("- 해설은 정답 근거만 1~2문장으로 짧게 쓰세요. choice_notes도 아주 짧게 쓰세요.")
    else:
        lines.append("- 해설은 지문의 구체적인 부분을 근거로 정답 이유를 분명히 쓰고, choice_notes에 선지마다 맞고 틀린 이유를 쓰세요.")
    if style.get("stem_examples", "").strip():
        lines.append("- 발문은 아래 예시와 같은 말투·형식을 따르세요:\n" + style["stem_examples"].strip())
    if style.get("extra_rules", "").strip():
        lines.append("- 원장님 지침 (반드시 따를 것):\n" + style["extra_rules"].strip())
    return "\n".join(lines)


def items_block(items: list, start_no: int) -> str:
    out = []
    for i, it in enumerate(items):
        label = f"{start_no + i}번: {KINDS[it['kind']]}, 난이도 {DIFFICULTIES[it['difficulty']][0]}"
        if it.get("type"):
            label += f", 유형 '{it['type']}'"
        out.append("- " + label)
    used = []
    for it in items:
        if it["difficulty"] not in used:
            used.append(it["difficulty"])
    rules = "\n".join(f"- {DIFFICULTIES[d][0]}: {DIFFICULTIES[d][1]}" for d in used)
    return "\n".join(out) + "\n\n[난이도별 출제 원칙]\n" + rules


def build_generate_prompt(*, source_text, subject, items, start_no, style, recipe,
                          need_passage, marked_passage="", total=0) -> str:
    kinds_used = []
    for it in items:
        if it["kind"] not in kinds_used:
            kinds_used.append(it["kind"])
    kind_rules = "\n".join(f"- {KINDS[k]}: {KIND_RULES[k].format(choice_count=style['choice_count'])}"
                           for k in kinds_used)
    if need_passage:
        passage_rule = (
            "- passage에는 아래 원본 지문을 한 글자도 바꾸거나 빼지 말고 그대로 옮기되, 출제에 필요한 기호·밑줄·구획 표시만 넣으세요. "
            "맞춤법이 틀려 보여도 고치지 마세요.\n"
            f"- 이 지문으로는 모두 {total}문항을 낼 예정이고, 이번에는 그중 {len(items)}문항을 만듭니다.")
        passage_text = f"[원본 지문]\n{source_text}"
    else:
        passage_rule = ("- 지문은 앞에서 이미 확정됐습니다. intro, passage, source_note는 쓰지 말고 questions만 쓰세요. "
                        "지문에 이미 있는 기호만 가리킬 수 있습니다(새 기호를 만들지 마세요).\n"
                        "- 앞에서 이미 낸 문항과 같은 내용을 다시 묻지 마세요.")
        passage_text = f"[확정된 지문 (기호 표시 포함)]\n{marked_passage}"
    extra = f"\n[이번 출제에 대한 추가 요청]\n{recipe['extra']}\n" if recipe.get("extra") else ""

    return f"""당신은 학교 시험과 수능 출제 경험이 많은 {subject} 교사입니다. 아래 지문으로 문제를 출제하세요.

[만들 문항 - 번호, 종류, 난이도, 유형을 정확히 지킬 것]
{items_block(items, start_no)}

[문제 종류별 규칙]
{kind_rules}

[공통 규칙]
- 모든 정답은 지문만으로 확정되어야 하고, 객관식 정답은 하나뿐이어야 합니다.
- 오답 선지는 지문 내용을 살짝 비틀어 그럴듯하게 만드세요. 지문과 무관하거나 상식으로 바로 걸러지는 오답은 쓰지 마세요.
- 정답 선지만 유독 길거나 자세하지 않게, 선지들의 길이와 문장 구조를 비슷하게 맞추세요.
- [보기]는 다른 자료·사례·작품과 견주어야 하는 문항에만 쓰세요.
- 선지에 자연스러운 순서가 있으면(예: ㄱ, ㄴ / ㄱ, ㄷ 조합, 숫자 순) keep_order를 true로 하세요.
- 마크다운(**, #)을 쓰지 마세요. 밑줄 <u>…</u> 말고는 꺾쇠(< >)를 쓰지 마세요.
{passage_rule}

[스타일]
{style_block(style)}
{extra}
[답 형식]
설명 없이 아래 모양의 JSON 하나만 답하세요.
{JSON_SHAPE}

{passage_text}
"""


def build_verify_prompt(*, source_text, data, style) -> str:
    return f"""아래는 방금 만든 문제 세트입니다. 원본 지문과 한 문항씩 대조해 검수하고, 문제가 있으면 직접 고친 최종본을 주세요.

[검수 기준]
1. 정답이 지문과 정확히 맞는지. 틀렸으면 answer와 해설을 바로잡으세요.
2. 객관식에 정답이 둘 이상이거나 없는 문항이 없는지. 있으면 선지를 고치세요.
3. 정답 선지만 티가 나게 길거나 자세하지 않은지. 그렇다면 선지 길이·구조를 맞추세요(정답 여부는 그대로).
4. 지문과 무관하거나 너무 뻔한 오답이 있으면 지문을 살짝 비튼 그럴듯한 오답으로 바꾸세요.
5. 발문이 가리키는 기호(㉠, ⓐ, [A])가 지문에 실제로 있는지. 없으면 발문을 고치세요.
6. 오탈자.
문항 수, 번호, 종류(kind), 난이도는 바꾸지 마세요. 객관식 선지는 {style['choice_count']}개를 유지하세요.
고칠 것이 없으면 그대로 두세요.

[답 형식]
설명 없이 JSON 하나만: {{"questions": [... 받은 것과 같은 모양의 문항들 ...], "notes": ["고친 내용을 한 줄씩. 없으면 빈 배열"]}}

[원본 지문]
{source_text}

[문제 세트]
{json.dumps({"passage": data.get("passage", ""), "questions": data["questions"]}, ensure_ascii=False, indent=1)}
"""


def build_revise_prompt(*, source_text, data, instruction, targets, style) -> str:
    target_line = (f"고칠 대상 문항: {', '.join(str(t) for t in targets)}번. 다른 문항은 그대로 두세요."
                   if targets else "고칠 대상: 요청에서 말한 부분 (특정 번호를 말하지 않았으면 요청에 맞게 판단)")
    current = {k: data.get(k) for k in ("intro", "passage", "source_note", "questions")}
    return f"""아래 문제 세트를 원장님 요청대로 고쳐 주세요.

[원장님 요청]
{instruction}

[범위]
{target_line}
- 문항을 더하거나 빼라는 요청이면 그렇게 하세요. 번호는 1번부터 다시 차례대로 매기세요.
- 지문 원문 내용은 바꾸지 마세요. 기호·밑줄만 더하거나 뺄 수 있습니다.
- 정답이 지문만으로 확정되어야 한다는 원칙은 그대로 지키세요.

[스타일]
{style_block(style)}

[답 형식]
설명 없이 JSON 하나만 답하세요. 받은 세트와 같은 모양(intro, passage, source_note, questions)에
"summary": "무엇을 어떻게 고쳤는지 한두 문장" 을 더해 주세요.

[원본 지문]
{source_text}

[지금 문제 세트]
{json.dumps(current, ensure_ascii=False, indent=1)}
"""


# ─────────────────────────────────────────────────────────
# AI 답 확인·정리
# ─────────────────────────────────────────────────────────
def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "\n".join(_text(x) for x in v)
    return str(v).strip()


def _strip_number_prefix(choice: str) -> str:
    return re.sub(r"^\s*(?:[①-⑩]|\(?\d{1,2}[\).]|[가-마][\).])\s*", "", choice).strip()


def parse_mcq_answer(value, n: int):
    s = _text(value)
    if not s:
        return None
    if s[0] in CIRCLED:
        idx = CIRCLED.index(s[0]) + 1
    else:
        m = re.search(r"\d+", s)
        if not m:
            return None
        idx = int(m.group())
    return idx if 1 <= idx <= n else None


def normalize_question(raw: dict, style: dict) -> dict:
    """AI가 준 문항 하나를 정해진 모양으로 다듬는다. 쓸 수 없으면 GenerationError."""
    if not isinstance(raw, dict):
        raise GenerationError("문항 형식이 잘못됐습니다.")
    kind = _text(raw.get("kind")).lower()
    if kind not in KINDS:
        kind = "mcq" if raw.get("choices") else "short"
    q = {
        "no": raw.get("no"),
        "kind": kind,
        "difficulty": _text(raw.get("difficulty")) if _text(raw.get("difficulty")) in DIFFICULTIES else "mid",
        "type": _text(raw.get("type")),
        "stem": _text(raw.get("stem")),
        "box": _text(raw.get("box")),
        "choices": [],
        "answer": "",
        "accept": [],
        "keep_order": bool(raw.get("keep_order", False)),
        "explanation": _text(raw.get("explanation")),
        "choice_notes": [],
    }
    if not q["stem"]:
        raise GenerationError("발문이 비어 있는 문항이 있습니다.")
    if kind == "mcq":
        choices = [_strip_number_prefix(_text(c)) for c in (raw.get("choices") or [])]
        choices = [c for c in choices if c]
        n = style["choice_count"]
        if len(choices) != n:
            raise GenerationError(f"선지가 {n}개가 아닌 객관식 문항이 있습니다({len(choices)}개).")
        answer = parse_mcq_answer(raw.get("answer"), n)
        if answer is None:
            raise GenerationError("정답 번호를 알 수 없는 객관식 문항이 있습니다.")
        notes = [_text(x) for x in (raw.get("choice_notes") or [])]
        q.update(choices=choices, answer=answer, choice_notes=notes if len(notes) == n else [])
    elif kind == "ox":
        a = _text(raw.get("answer")).upper().replace("○", "O").replace("×", "X")
        if a in ("TRUE", "참", "맞음"):
            a = "O"
        if a in ("FALSE", "거짓", "틀림"):
            a = "X"
        if a not in ("O", "X"):
            raise GenerationError("OX 문항의 정답이 O나 X가 아닙니다.")
        q["answer"] = a
    else:
        a = _text(raw.get("answer"))
        if not a:
            raise GenerationError("정답이 비어 있는 문항이 있습니다.")
        q["answer"] = a
        q["accept"] = [_text(x) for x in (raw.get("accept") or []) if _text(x)]
    return q


def strip_markers(text: str) -> str:
    return re.sub(r"\s+", "", MARKER_RE.sub("", text or ""))


def passage_is_faithful(original: str, marked: str) -> bool:
    """AI가 기호·밑줄만 넣었는지, 지문 자체를 고쳐 썼는지 본다."""
    a, b = strip_markers(original), strip_markers(marked)
    if not a or not b:
        return False
    if a == b:
        return True
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.985


def balance_answers(questions: list, rng: random.Random) -> None:
    """객관식 정답 번호가 고르게, 규칙 없이 퍼지도록 정답 선지의 자리를 바꾼다.
    선지별 해설(choice_notes)도 함께 옮기므로 해설이 어긋나지 않는다."""
    movable = [q for q in questions if q["kind"] == "mcq" and not q.get("keep_order")]
    if not movable:
        return
    n = len(movable[0]["choices"])
    targets = []
    while len(targets) < len(movable):
        block = list(range(1, n + 1))
        rng.shuffle(block)
        if targets and block[0] == targets[-1]:
            block[0], block[-1] = block[-1], block[0]
        targets += block
    for q, target in zip(movable, targets):
        a = q["answer"]
        if a == target or len(q["choices"]) != n:
            continue
        c = q["choices"]
        c[a - 1], c[target - 1] = c[target - 1], c[a - 1]
        if len(q["choice_notes"]) == n:
            t = q["choice_notes"]
            t[a - 1], t[target - 1] = t[target - 1], t[a - 1]
        q["answer"] = target


def renumber(questions: list, start: int = 1) -> None:
    for i, q in enumerate(questions):
        q["no"] = start + i


# ─────────────────────────────────────────────────────────
# 출제
# ─────────────────────────────────────────────────────────
def generate_set(ai, *, source_text, subject, recipe, style, progress=lambda msg: None, rng=None) -> dict:
    if ai is None:
        raise GenerationError("AI 키가 없습니다. GOOGLE_API_KEY를 넣고 프로그램을 다시 켜주세요.")
    source_text = (source_text or "").strip()
    if len(source_text) < 20:
        raise GenerationError("지문이 너무 짧습니다.")
    rng = rng or random.Random()
    recipe = normalize_recipe(recipe)
    items = expand_items(recipe, rng)
    total = len(items)

    data = {"intro": "", "passage": source_text, "source_note": "", "questions": [], "notes": []}
    batches = [items[i:i + QUESTIONS_PER_CALL] for i in range(0, total, QUESTIONS_PER_CALL)]
    for b_idx, batch in enumerate(batches):
        start_no = len(data["questions"]) + 1
        need_passage = b_idx == 0
        progress(f"{start_no}~{start_no + len(batch) - 1}번 문항을 만드는 중... (전체 {total}문항)")
        made = []
        remaining = list(batch)
        for attempt in range(2):
            if not remaining:
                break
            prompt = build_generate_prompt(
                source_text=source_text, subject=subject, items=remaining,
                start_no=start_no + len(made), style=style, recipe=recipe,
                need_passage=need_passage and attempt == 0, marked_passage=data["passage"], total=total)
            task = {"mode": "generate", "items": remaining, "start_no": start_no + len(made),
                    "passage": source_text, "need_passage": need_passage and attempt == 0,
                    "choice_count": style["choice_count"]}
            raw = ai.generate_json(prompt, task, quality=True)
            if need_passage and attempt == 0:
                marked = _text(raw.get("passage"))
                if marked and passage_is_faithful(source_text, marked):
                    data["passage"] = marked
                elif marked:
                    data["notes"].append("AI가 지문 문장을 바꿔 써서, 원본 지문을 그대로 실었습니다. 기호(㉠ 등)를 가리키는 발문은 확인해주세요.")
                data["intro"] = _text(raw.get("intro")) or "※ 다음 글을 읽고 물음에 답하시오."
                data["source_note"] = _text(raw.get("source_note"))
            got = []
            for rq in (raw.get("questions") or []):
                try:
                    got.append(normalize_question(rq, style))
                except GenerationError as e:
                    data["notes"].append(f"형식이 맞지 않은 문항 하나를 버렸습니다: {e}")
            # 요청한 칸 순서대로 맞춰 넣는다 (종류가 같은 것끼리 짝지음)
            for slot in list(remaining):
                match = next((q for q in got if q["kind"] == slot["kind"]), None)
                if match:
                    got.remove(match)
                    match["difficulty"] = slot["difficulty"]
                    if slot.get("type") and not match["type"]:
                        match["type"] = slot["type"]
                    made.append(match)
                    remaining.remove(slot)
        if remaining:
            data["notes"].append(f"{len(remaining)}문항은 AI가 제대로 만들지 못해 빠졌습니다.")
        data["questions"] += made

    if not data["questions"]:
        raise GenerationError("AI가 쓸 수 있는 문항을 하나도 만들지 못했습니다. 다시 시도해주세요.")
    renumber(data["questions"])

    if recipe["verify"]:
        progress("만든 문제를 지문과 대조해 검수하는 중...")
        data = verify_set(ai, source_text=source_text, data=data, style=style)

    balance_answers(data["questions"], rng)
    progress("완성")
    return data


def verify_set(ai, *, source_text, data, style) -> dict:
    """검수에 실패하면(오류, 형식 깨짐, 문항 수 바뀜) 초안을 그대로 쓴다."""
    try:
        raw = ai.generate_json(build_verify_prompt(source_text=source_text, data=data, style=style),
                               {"mode": "verify", "draft": data}, quality=False)
        fixed = [normalize_question(q, style) for q in (raw.get("questions") or [])]
    except (AIError, GenerationError) as e:
        data["notes"].append(f"검수를 건너뛰었습니다: {e}")
        return data
    if len(fixed) != len(data["questions"]) or any(
            a["kind"] != b["kind"] for a, b in zip(fixed, data["questions"])):
        data["notes"].append("검수 결과의 문항 구성이 달라져 검수 전 문제를 그대로 썼습니다.")
        return data
    for a, b in zip(fixed, data["questions"]):
        a["difficulty"] = b["difficulty"]
        a["type"] = a["type"] or b["type"]
    renumber(fixed)
    notes = [_text(n) for n in (raw.get("notes") or []) if _text(n)]
    out = dict(data, questions=fixed)
    out["notes"] = data["notes"] + [f"검수: {n}" for n in notes]
    return out


def revise_set(ai, *, source_text, data, instruction, targets, style, rng=None):
    """말로 한 요청대로 고친다. (새 data, 고친 내용 요약)을 돌려준다."""
    if ai is None:
        raise GenerationError("AI 키가 없습니다.")
    instruction = (instruction or "").strip()
    if not instruction:
        raise GenerationError("어떻게 고칠지 적어주세요.")
    rng = rng or random.Random()
    targets = sorted({int(t) for t in (targets or [])})
    raw = ai.generate_json(
        build_revise_prompt(source_text=source_text, data=data, instruction=instruction,
                            targets=targets, style=style),
        {"mode": "revise", "data": data, "targets": targets, "instruction": instruction}, quality=True)
    questions = []
    for rq in raw.get("questions") or []:
        questions.append(normalize_question(rq, style))
    if not questions:
        raise GenerationError("고친 결과에 문항이 하나도 없습니다. 다시 시도해주세요.")
    renumber(questions)

    new = dict(data)
    new["questions"] = questions
    notes = list(data.get("notes") or [])
    passage = _text(raw.get("passage"))
    if passage and passage != data.get("passage"):
        if passage_is_faithful(source_text, passage):
            new["passage"] = passage
        else:
            notes.append("고치는 중 AI가 지문 문장을 바꾸려 해서, 지문은 고치기 전 그대로 두었습니다.")
    for key in ("intro", "source_note"):
        if _text(raw.get(key)):
            new[key] = _text(raw.get(key))
    # 고치지 않은 문항의 정답 자리는 그대로 두고, 새로 생기거나 고친 객관식만 다시 섞는다
    old_by_stem = {q["stem"]: q for q in data.get("questions", [])}
    changed = [q for q in questions if q["kind"] == "mcq" and
               (q["stem"] not in old_by_stem or old_by_stem[q["stem"]].get("choices") != q["choices"])]
    balance_answers(changed, rng)
    new["notes"] = notes
    summary = _text(raw.get("summary")) or "요청대로 고쳤습니다."
    return new, summary
