"""AI에게 줄 말(프롬프트)과, AI 답을 확인 · 다듬는 부분."""

import json
import re
from datetime import datetime

from . import catalog
from .ai import AIError


class GenerationError(Exception):
    pass


# ─────────────────────────────────────────────────────────
# 입력 정리
# ─────────────────────────────────────────────────────────
def merge_profile(profile) -> dict:
    out = dict(catalog.DEFAULT_PROFILE)
    for k, v in (profile or {}).items():
        if k in out and v is not None:
            out[k] = str(v).strip()
    if out["theme"] not in catalog.THEMES:
        out["theme"] = catalog.DEFAULT_PROFILE["theme"]
    return out


def normalize_request(req: dict) -> dict:
    req = req or {}
    channels = [c for c in (req.get("channels") or []) if c in catalog.CHANNELS]
    channels = list(dict.fromkeys(channels))
    if not channels:
        raise GenerationError("인스타그램이나 블로그 중 하나는 골라주세요.")
    topic = str(req.get("topic") or "").strip()
    if not topic:
        raise GenerationError("무엇에 대한 글인지 주제를 적어주세요.")
    kind = req.get("kind") if req.get("kind") in catalog.KINDS else "tip"
    tone = req.get("tone") if req.get("tone") in catalog.TONES else "friendly"
    audience = req.get("audience") if req.get("audience") in catalog.AUDIENCES else "both"
    length = req.get("blog_length") if req.get("blog_length") in catalog.BLOG_LENGTHS else "normal"
    try:
        slides = int(req.get("slide_count") or 6)
    except (TypeError, ValueError):
        slides = 6
    return {
        "channels": channels, "kind": kind, "topic": topic[:300],
        "details": str(req.get("details") or "").strip()[:4000],
        "tone": tone, "audience": audience, "blog_length": length,
        "slide_count": max(1, min(catalog.MAX_SLIDES, slides)),
        "reel": bool(req.get("reel")),
    }


# ─────────────────────────────────────────────────────────
# 프롬프트
# ─────────────────────────────────────────────────────────
COMMON_RULES = """[꼭 지킬 것]
1. 학원 정보와 '자세한 내용'에 적힌 사실만 쓰세요. 날짜 · 숫자 · 합격 실적 · 성적 · 강사 경력을 지어내지 마세요.
   필요한데 모르는 정보는 [개강일], [전화번호]처럼 대괄호 빈칸으로 남기세요.
2. 과장 광고가 되는 말을 쓰지 마세요: '합격 보장', '성적 보장', '100%', '무조건', '1등/1위/최고 학원', '유일', '최초' 같은 말.
   다른 학원을 깎아내리지 마세요.
3. 학생 이름 · 학교 이름 · 얼굴이 드러나는 내용은 쓰지 마세요. 후기는 '고2 ○○ 학생'처럼 가리세요.
4. 맞춤법을 지키고, 번역투나 딱딱한 광고 문구 대신 사람이 직접 쓴 듯한 자연스러운 한국어로 쓰세요.
5. 답은 JSON 하나로만 주세요. 다른 말은 쓰지 마세요."""


def _profile_block(p: dict) -> str:
    rows = [("학원 이름", p["name"]), ("지역", p["region"]), ("과목", p["subjects"]), ("대상 학년", p["grades"]),
            ("강점", p["strengths"]), ("상담 연락처", p["contact"]), ("주소", p["address"])]
    lines = [f"- {k}: {v}" for k, v in rows if v]
    if p["avoid"]:
        lines.append(f"- 쓰지 말아야 할 말: {p['avoid']}")
    text = "\n".join(lines) or "- (적힌 정보 없음 — 학원 이름은 '저희 학원'으로 쓰세요)"
    if p["sample"]:
        text += f"\n\n[이 학원이 예전에 쓴 글 — 말투와 분위기를 따라 쓰세요. 내용은 베끼지 마세요]\n{p['sample'][:1500]}"
    return text


def build_generate_prompt(req: dict, profile: dict, today: str) -> str:
    kind_name, kind_rule, _ = catalog.KINDS[req["kind"]]
    tone_name, tone_rule = catalog.TONES[req["tone"]]
    parts = [
        "당신은 한국 입시 학원의 SNS 홍보를 10년 넘게 맡아 온 마케터이자 카피라이터입니다.",
        f"오늘은 {today}입니다.",
        f"\n[학원 정보]\n{_profile_block(profile)}",
        f"\n[이번 글]\n- 글 종류: {kind_name} — {kind_rule}\n- 주제: {req['topic']}"
        f"\n- 읽을 사람: {catalog.AUDIENCES[req['audience']]}\n- 말투: {tone_name} — {tone_rule}",
    ]
    if req["details"]:
        parts.append(f"\n[자세한 내용 · 원장님 메모 — 이 사실을 꼭 살려 쓰세요]\n{req['details']}")
    shape = {}
    if "instagram" in req["channels"]:
        n = req["slide_count"]
        parts.append(f"""
[인스타그램 게시물]
- caption: 본문. 첫 줄은 스크롤을 멈추게 하는 한 줄(질문 · 공감 · 숫자). 짧은 문단과 줄 바꿈, 이모지를 알맞게.
  400~900자. 끝에 상담 · 문의로 이어지는 한두 줄. 해시태그는 caption에 넣지 말고 hashtags에 따로.
- hashtags: 15~25개. '#' 붙여서. 지역+과목(예: #대치동국어학원), 학년, 주제, 일반 공부 태그를 섞되 주제와 무관한 태그는 빼세요.
- slides: 카드뉴스 {n}장. 1장은 표지(title에 눈길을 끄는 제목 15자 안팎, body에 부제 한 줄).
  나머지는 장마다 title 20자 이내, body 2~4줄 70자 이내. 한 장에 한 가지 메시지. 마지막 장은 정리나 상담 안내.
- image_ideas: 함께 올리면 좋을 사진 · 그림 아이디어 2~4개 (학생 얼굴이 나오지 않는 것으로).""")
        shape["instagram"] = {"caption": "...", "hashtags": ["#..."], "slides": [{"title": "...", "body": "..."}],
                              "image_ideas": ["..."]}
        if req["reel"]:
            parts.append("- reel_script: 30초 안팎 릴스 대본. (0~3초) 같은 시간 표시와 화면 글씨 · 말할 내용을 함께.")
            shape["instagram"]["reel_script"] = "..."
    if "blog" in req["channels"]:
        _, chars = catalog.BLOG_LENGTHS[req["blog_length"]]
        parts.append(f"""
[블로그 글 (네이버 블로그)]
- titles: 제목 후보 3개. 검색될 말(지역 · 과목 · 학년 · 주제)을 앞쪽에 넣고 30자 안팎.
- keywords: 사람들이 검색창에 칠 만한 핵심 검색어 3~6개. 본문에 자연스럽게 2~3번씩 녹이세요(억지로 반복하지 말 것).
- intro: 첫 인사와 이 글을 읽어야 하는 이유 (3~5문장).
- sections: 소제목 3~6개. 각각 heading(소제목), body(문단. 줄 바꿈으로 문단 나눔), photo(그 자리에 넣을 사진 설명, 없으면 빈 글자).
- outro: 정리와 상담 안내.
- tags: 블로그 태그 10개 안팎 ('#' 없이).
- intro · sections · outro를 합쳐 {chars}자 안팎.""")
        shape["blog"] = {"titles": ["..."], "keywords": ["..."], "intro": "...",
                         "sections": [{"heading": "...", "body": "...", "photo": "..."}], "outro": "...", "tags": ["..."]}
    parts.append("\n" + COMMON_RULES)
    parts.append("\n[답 모양]\n" + json.dumps(shape, ensure_ascii=False))
    return "\n".join(parts)


def build_revise_prompt(data: dict, instruction: str, profile: dict) -> str:
    keep = {k: data[k] for k in ("instagram", "blog") if k in data}
    return f"""당신은 학원 SNS 글을 다듬는 카피라이터입니다. 아래 글을 원장님 요청대로 고쳐 주세요.

[학원 정보]
{_profile_block(profile)}

[원장님 요청]
{instruction}

[지금 글]
{json.dumps(keep, ensure_ascii=False)}

요청과 관계없는 부분은 그대로 두세요. 모양(키 이름)은 바꾸지 마세요.
고친 글 전체와, 무엇을 고쳤는지 한두 문장(summary)을 함께 주세요.

{COMMON_RULES}

[답 모양]
{{"instagram": ..., "blog": ..., "summary": "..."}}  (지금 글에 있는 것만)"""


def build_ideas_prompt(profile: dict, now: datetime, count: int, kinds: list, recent: list) -> str:
    month = now.month
    nxt = month % 12 + 1
    kind_lines = "\n".join(f"- {k}: {catalog.KINDS[k][0]}" for k in kinds)
    recent_text = "\n".join(f"- {t}" for t in recent[:20]) or "- (없음)"
    return f"""당신은 한국 입시 학원의 SNS 홍보 담당자입니다. 앞으로 2~3주 동안 올릴 글감을 {count}개 추천해 주세요.

오늘: {now.strftime('%Y-%m-%d')}
이번 달 학원가 일: {catalog.MONTH_HINTS[month]}
다음 달 학원가 일: {catalog.MONTH_HINTS[nxt]}

[학원 정보]
{_profile_block(profile)}

[최근에 올린 글 — 겹치지 않게]
{recent_text}

[고를 수 있는 글 종류 (kind)]
{kind_lines}

- 학부모와 학생이 실제로 궁금해하고 저장 · 공유하고 싶어 할 주제로.
- 공부 팁 · 정보 글과 홍보 글을 고루 섞으세요 (홍보 글은 3분의 1 이하).
- topic은 그대로 글 주제로 쓸 수 있게 구체적으로 (30자 안팎). why는 지금 올리면 좋은 이유 한 문장.
- channel은 더 어울리는 곳: "instagram" 또는 "blog".
- 확실하지 않은 날짜 · 숫자는 쓰지 마세요.

[답 모양]
{{"ideas": [{{"kind": "tip", "topic": "...", "why": "...", "channel": "instagram"}}]}}"""


# ─────────────────────────────────────────────────────────
# AI 답 다듬기
# ─────────────────────────────────────────────────────────
def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _str_list(v, limit=50) -> list:
    if isinstance(v, str):
        v = re.split(r"[\n,]+", v)
    out = []
    for x in v or []:
        x = _s(x)
        if x and x not in out:
            out.append(x)
    return out[:limit]


def clean_hashtags(tags, base: str = "") -> list:
    """'#' 붙이고, 띄어쓰기 · 겹침 없애고, 늘 붙이는 태그를 앞에 둔다. 인스타는 30개까지만 받는다."""
    out = []
    for raw in _str_list(base.replace(",", " ").split(), 30) + _str_list(tags, 60):
        for piece in raw.split():
            tag = "#" + re.sub(r"[^\w가-힣]", "", piece.lstrip("#"))
            if len(tag) > 1 and tag.lower() not in [t.lower() for t in out]:
                out.append(tag)
    return out[:30]


def normalize_instagram(d: dict, profile: dict) -> dict:
    if not isinstance(d, dict):
        raise GenerationError("AI가 인스타그램 글을 주지 않았습니다. 다시 시도해주세요.")
    caption = _s(d.get("caption"))
    if not caption:
        raise GenerationError("AI가 인스타그램 본문을 비워 두었습니다. 다시 시도해주세요.")
    # 본문에 섞여 온 해시태그는 떼어 hashtags로 옮긴다
    stray = re.findall(r"#[\w가-힣]+", caption)
    if stray and len(stray) >= 3:
        caption = re.sub(r"(\s*#[\w가-힣]+)+\s*$", "", caption).strip()
    slides = []
    for s in d.get("slides") or []:
        if isinstance(s, dict):
            title, body = _s(s.get("title")), _s(s.get("body"))
        else:
            title, body = _s(s), ""
        if title or body:
            slides.append({"title": title, "body": body})
    out = {
        "caption": caption,
        "hashtags": clean_hashtags(list(d.get("hashtags") or []) + stray, profile.get("base_hashtags", "")),
        "slides": slides[:catalog.MAX_SLIDES],
        "image_ideas": _str_list(d.get("image_ideas"), 6),
    }
    if _s(d.get("reel_script")):
        out["reel_script"] = _s(d.get("reel_script"))
    return out


def normalize_blog(d: dict) -> dict:
    if not isinstance(d, dict):
        raise GenerationError("AI가 블로그 글을 주지 않았습니다. 다시 시도해주세요.")
    sections = []
    for s in d.get("sections") or []:
        if isinstance(s, dict) and (_s(s.get("heading")) or _s(s.get("body"))):
            sections.append({"heading": _s(s.get("heading")), "body": _s(s.get("body")), "photo": _s(s.get("photo"))})
    titles = _str_list(d.get("titles"), 5)
    if not titles or not sections:
        raise GenerationError("AI가 블로그 제목이나 본문을 비워 두었습니다. 다시 시도해주세요.")
    return {
        "titles": titles,
        "keywords": _str_list(d.get("keywords"), 8),
        "intro": _s(d.get("intro")),
        "sections": sections,
        "outro": _s(d.get("outro")),
        "tags": [t.lstrip("#") for t in _str_list(d.get("tags"), 30)],
    }


def ad_footer(profile: dict) -> str:
    """모집 · 홍보 글 끝에 붙이는 학원 정보 (등록번호 · 교습비 · 연락처)."""
    lines = []
    if profile.get("name") and profile.get("reg_no"):
        lines.append(f"{profile['name']} (학원 등록번호 {profile['reg_no']})")
    elif profile.get("reg_no"):
        lines.append(f"학원 등록번호 {profile['reg_no']}")
    if profile.get("fee_note"):
        lines.append(profile["fee_note"])
    if profile.get("address"):
        lines.append(f"📍 {profile['address']}")
    if profile.get("contact"):
        lines.append(f"☎ {profile['contact']}")
    return "\n".join(lines)


def check_post(data: dict, req: dict, profile: dict) -> list:
    """올리기 전에 살펴볼 점."""
    notes = []
    text = full_text(data)
    found = [p for p in catalog.RISKY_PHRASES if p in text]
    for word in [w.strip() for w in re.split(r"[,\n]", profile.get("avoid", "")) if w.strip()]:
        if word in text:
            found.append(word)
    if found:
        notes.append("과장 광고로 보일 수 있는 말이 있어요: " + ", ".join(dict.fromkeys(found))
                     + " → 고치거나 빼 주세요.")
    blanks = sorted(set(re.findall(r"\[[^\[\]\n]{1,15}\]", text)))
    if blanks:
        notes.append("채워 넣을 빈칸이 있어요: " + " ".join(blanks))
    if catalog.KINDS[req["kind"]][2] and not (profile.get("reg_no") and profile.get("fee_note")):
        notes.append("모집 · 홍보 글에는 학원 등록번호와 교습비를 함께 적어야 할 수 있어요. "
                     "'학원 정보'에 넣어 두면 글 끝에 자동으로 붙여요.")
    if "instagram" in data and len(data["instagram"]["caption"]) > 2200:
        notes.append("인스타그램 본문이 2,200자를 넘어 잘릴 수 있어요. '더 짧게'로 고쳐 보세요.")
    return notes


def full_text(data: dict) -> str:
    out = []
    ig = data.get("instagram")
    if ig:
        out.append(ig["caption"])
        out += [f"{s['title']}\n{s['body']}" for s in ig.get("slides", [])]
        out.append(ig.get("reel_script", ""))
    bl = data.get("blog")
    if bl:
        out += bl["titles"] + [bl["intro"], bl["outro"]]
        out += [f"{s['heading']}\n{s['body']}" for s in bl["sections"]]
    return "\n".join(out)


def finish(raw: dict, req: dict, profile: dict) -> dict:
    """AI 답을 확인하고, 학원 정보 꼬리말을 붙이고, 살펴볼 점을 단다."""
    if not isinstance(raw, dict):
        raise GenerationError("AI 답을 읽지 못했습니다. 다시 시도해주세요.")
    data = {}
    if "instagram" in req["channels"]:
        data["instagram"] = normalize_instagram(raw.get("instagram"), profile)
    if "blog" in req["channels"]:
        data["blog"] = normalize_blog(raw.get("blog"))
    apply_footer(data, req, profile)
    data["notes"] = check_post(data, req, profile)
    return data


def apply_footer(data: dict, req: dict, profile: dict):
    footer = ad_footer(profile) if catalog.KINDS[req["kind"]][2] else ""
    if not footer:
        return
    ig = data.get("instagram")
    if ig and footer not in ig["caption"]:
        ig["caption"] = ig["caption"].rstrip() + "\n\n" + footer
    bl = data.get("blog")
    if bl and footer not in bl["outro"]:
        bl["outro"] = (bl["outro"].rstrip() + "\n\n" + footer).strip()


# ─────────────────────────────────────────────────────────
# 하는 일
# ─────────────────────────────────────────────────────────
def generate_post(ai, req: dict, profile: dict, today: str) -> dict:
    if ai is None:
        raise GenerationError("AI 키(GOOGLE_API_KEY)가 없습니다. 키를 넣고 다시 켜 주세요.")
    req = normalize_request(req)
    profile = merge_profile(profile)
    prompt = build_generate_prompt(req, profile, today)
    task = dict(req, mode="generate", profile=profile)
    last = None
    for _ in range(2):   # 모양이 깨져 오면 한 번 더 부탁한다
        try:
            return finish(ai.generate_json(prompt, task), req, profile)
        except (GenerationError, AIError) as e:
            last = e
    raise GenerationError(str(last))


def revise_post(ai, data: dict, instruction: str, req: dict, profile: dict) -> dict:
    if ai is None:
        raise GenerationError("AI 키(GOOGLE_API_KEY)가 없습니다.")
    instruction = (instruction or "").strip()
    if not instruction:
        raise GenerationError("어떻게 고칠지 적어주세요.")
    req = normalize_request(req)
    profile = merge_profile(profile)
    task = {"mode": "revise", "data": data, "instruction": instruction, "profile": profile}
    try:
        raw = ai.generate_json(build_revise_prompt(data, instruction, profile), task)
    except AIError as e:
        raise GenerationError(str(e))
    out = finish({k: raw.get(k) for k in ("instagram", "blog")}, req, profile)
    out["summary"] = _s(raw.get("summary"))
    return out


def suggest_ideas(ai, profile: dict, now: datetime, recent: list, count: int = 8) -> list:
    if ai is None:
        raise GenerationError("AI 키(GOOGLE_API_KEY)가 없습니다.")
    profile = merge_profile(profile)
    kinds = list(catalog.KINDS)
    task = {"mode": "ideas", "count": count, "kinds": kinds, "profile": profile}
    try:
        raw = ai.generate_json(build_ideas_prompt(profile, now, count, kinds, recent), task, quality=False)
    except AIError as e:
        raise GenerationError(str(e))
    ideas = []
    for it in (raw or {}).get("ideas") or []:
        if not isinstance(it, dict) or not _s(it.get("topic")):
            continue
        ideas.append({"kind": it.get("kind") if it.get("kind") in catalog.KINDS else "tip",
                      "topic": _s(it.get("topic"))[:120], "why": _s(it.get("why"))[:200],
                      "channel": it.get("channel") if it.get("channel") in catalog.CHANNELS else "instagram"})
    if not ideas:
        raise GenerationError("AI가 추천을 주지 않았습니다. 다시 시도해주세요.")
    return ideas[:count]
