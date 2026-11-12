"""해설 영상: 내용에 맞춘 도표 장면들.

AI 가 해설 글을 읽고 '장면 설계도(storyboard)'를 만들면, 장면마다 내용에 맞는 화면으로 그린다.
    title     영상 첫 화면 — 주제와 한 줄 요약
    keyword   핵심 개념 하나를 크게
    list      근거 · 특징 · 단계 여러 개
    timeline  사건 순서 · 문단 흐름 · 시간 변화
    compare   두 대상 · 두 입장 · 전후 비교
    relation  인물 관계 · 개념 사이 관계
    quote     원문(지문 · 시구)에 형광펜
    caption   위 어디에도 안 맞는 설명 (문장을 크게)
항목들은 선생님이 그 항목을 설명하는 문장을 읽기 시작할 때 하나씩 화면에 나타난다.

💡 설계도는 AI 를 한 번만 부르면 나온다(글자만 주고받으므로 한 편에 몇 원).
   AI 답이 엉망이면 parse_storyboard 가 걸러내고, 남는 게 없으면 예전처럼 문장만 크게 보여준다.
"""
import json
import math
import re

from PIL import ImageDraw

import explain_video as ev
from explain_video import (W, MARGIN, CONTENT_TOP, CONTENT_BOTTOM, CARD, CARD_FOCUS, TEXT, SOFT,
                           ACCENT, BG_TOP, BG_BOTTOM, font, wrap, fit_wrap, draw_lines,
                           lerp, quant, ease, draw_badge)

LEFT_COLOR = (125, 200, 255)     # 비교: 왼쪽
RIGHT_COLOR = (255, 160, 122)    # 비교: 오른쪽
NODE_COLORS = [(125, 200, 255), (255, 160, 122), (110, 231, 150), (196, 176, 255), (250, 204, 21)]

KINDS = ("title", "keyword", "list", "timeline", "compare", "relation", "quote", "caption")


# ─────────────────────────────────────────────────────────
# AI 에게 줄 지시문 · AI 답 정리
# ─────────────────────────────────────────────────────────
STORYBOARD_GUIDE = """[화면 모양] — 장면마다 내용에 가장 잘 맞는 것 하나
- title: 영상 첫 장면. {"type":"title","title":"15자 이내 주제","subtitle":"25자 이내 한 줄 요약","lines":[...]}
- keyword: 핵심 개념 하나를 크게. {"type":"keyword","keyword":"12자 이내","desc":"40자 이내 뜻풀이","lines":[...]}
- list: 근거 · 특징 · 단계 여러 개. {"type":"list","heading":"20자 이내","items":["30자 이내", ...최대 5개],"lines":[...]}
- timeline: 사건 순서 · 문단 흐름 · 시간 변화. {"type":"timeline","heading":"20자 이내","events":[{"label":"8자 이내(예: 1문단, 과거)","text":"30자 이내"}, ...최대 5개],"lines":[...]}
- compare: 두 대상 · 두 입장 · 전후 비교. {"type":"compare","heading":"20자 이내","left":{"title":"10자 이내","points":["20자 이내", ...최대 4개]},"right":{"title":"10자 이내","points":[...]},"lines":[...]}
- relation: 인물 관계 · 개념 사이 관계. {"type":"relation","heading":"20자 이내","nodes":["8자 이내", ...최대 5개],"edges":[{"from":"nodes 에 있는 이름","to":"nodes 에 있는 이름","label":"8자 이내"}, ...최대 6개],"lines":[...]}
- quote: 원문(지문 · 시구)을 직접 보여줄 때. 원문을 한 글자도 바꾸지 말 것. {"type":"quote","source":"15자 이내(예: 2연)","text":"150자 이내 원문","highlight":"text 안에서 강조할 부분 그대로","lines":[...]}
- caption: 위 어디에도 안 맞는 설명. {"type":"caption","lines":[...]}

[공통 규칙]
- lines: 그 장면에서 선생님이 소리 내어 읽을 자연스러운 구어체 문장들. 한 문장 20~60자.
- list · timeline · compare · relation 은 항목을 화면에 적힌 순서대로 설명하는 문장을 lines 에 같은 순서로 넣어줘. 그 문장을 읽을 때 항목이 하나씩 나타난다.
- 화면 글자는 짧게 요약하고, 자세한 설명은 lines 로.
- 마크다운이나 *, #, <, > 같은 기호 금지."""


def storyboard_prompt(text: str, max_lines: int) -> str:
    return f"""아래 해설 글을 학생들이 볼 세로형 해설 영상의 '장면 설계도'로 바꿔줘.
원문의 내용과 의미는 절대 바꾸지 말고, 내용을 한눈에 정리해 주는 화면을 골라줘.

{STORYBOARD_GUIDE}
- 장면은 3~8개, 모든 장면의 lines 를 합쳐 {max_lines}개 이하. 첫 장면은 title.
- 다른 설명 없이 {{"scenes":[...]}} JSON 하나만 출력해.

[원문]
{text}"""


def parse_json_reply(raw: str):
    """AI 답에서 JSON 을 꺼낸다. ```json 울타리 · 앞뒤 군말 · 끝 쉼표를 견딘다."""
    s = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    start = min([i for i in (s.find("{"), s.find("[")) if i != -1], default=-1)
    if start == -1:
        return None
    s = s[start:]
    end = max(s.rfind("}"), s.rfind("]"))
    s = s[:end + 1]
    s = re.sub(r",\s*([}\]])", r"\1", s)
    try:
        return json.loads(s)
    except Exception:
        return None


def _s(v, limit: int) -> str:
    txt = re.sub(r"[*#`<>]", "", str(v or "")).strip()
    txt = re.sub(r"\s+", " ", txt)
    return txt if len(txt) <= limit else txt[:limit - 1].rstrip() + "…"


def _lines(v) -> list:
    if isinstance(v, str):
        v = [v]
    return [_s(x, 120) for x in (v or []) if _s(x, 120)]


def clean_scene(sc) -> dict:
    """장면 하나를 검사해 그릴 수 있는 모양으로 다듬는다. 못 쓰면 None."""
    if not isinstance(sc, dict):
        return None
    kind = str(sc.get("type", "")).strip().lower()
    lines = _lines(sc.get("lines"))
    out = {"type": kind, "lines": lines}
    if kind == "title":
        out.update(title=_s(sc.get("title"), 24), subtitle=_s(sc.get("subtitle"), 40))
        if not out["title"]:
            return None
    elif kind == "keyword":
        out.update(keyword=_s(sc.get("keyword"), 16), desc=_s(sc.get("desc"), 60))
        if not out["keyword"]:
            return None
    elif kind == "list":
        items = [_s(x, 44) for x in (sc.get("items") or []) if _s(x, 44)][:5]
        if not items:
            return None
        out.update(heading=_s(sc.get("heading"), 26), items=items)
    elif kind == "timeline":
        events = []
        for e in (sc.get("events") or [])[:5]:
            if isinstance(e, dict) and _s(e.get("text"), 44):
                events.append({"label": _s(e.get("label"), 10), "text": _s(e.get("text"), 44)})
            elif isinstance(e, str) and _s(e, 44):
                events.append({"label": "", "text": _s(e, 44)})
        if len(events) < 2:
            return None
        out.update(heading=_s(sc.get("heading"), 26), events=events)
    elif kind == "compare":
        sides = []
        for key in ("left", "right"):
            side = sc.get(key) if isinstance(sc.get(key), dict) else {}
            pts = [_s(x, 30) for x in (side.get("points") or []) if _s(x, 30)][:4]
            sides.append({"title": _s(side.get("title"), 12), "points": pts})
        if not (sides[0]["title"] and sides[1]["title"]):
            return None
        out.update(heading=_s(sc.get("heading"), 26), left=sides[0], right=sides[1])
    elif kind == "relation":
        nodes = []
        for n in (sc.get("nodes") or []):
            name = _s(n, 10)
            if name and name not in nodes:
                nodes.append(name)
        nodes = nodes[:5]
        edges = []
        for e in (sc.get("edges") or []):
            if not isinstance(e, dict):
                continue
            a, b = _s(e.get("from"), 10), _s(e.get("to"), 10)
            if a in nodes and b in nodes and a != b:
                edges.append({"from": a, "to": b, "label": _s(e.get("label"), 10)})
        if len(nodes) < 2 or not edges:
            return None
        out.update(heading=_s(sc.get("heading"), 26), nodes=nodes, edges=edges[:6])
    elif kind == "quote":
        text = str(sc.get("text") or "").strip()[:220]
        if not text:
            return None
        hl = str(sc.get("highlight") or "").strip()
        out.update(source=_s(sc.get("source"), 18), text=text, highlight=hl if hl and hl in text else "")
    elif kind == "caption":
        pass
    else:
        if not lines:
            return None
        out = {"type": "caption", "lines": lines}
    if not out["lines"]:
        # 읽을 문장이 없으면 화면 글자를 대신 읽는다
        guess = out.get("title") or out.get("keyword") or out.get("heading") or ""
        if not guess:
            return None
        out["lines"] = [guess]
    return out


def parse_storyboard(data, max_lines: int = ev.MAX_LINES) -> list:
    """AI 답(JSON 문자열이나 이미 읽은 값)을 그릴 수 있는 장면 목록으로. 못 쓰면 []."""
    if isinstance(data, str):
        data = parse_json_reply(data)
    if isinstance(data, dict):
        data = data.get("scenes")
    if not isinstance(data, list):
        return []
    # 💡 그냥 문장(옛 형식 ["문장", ...], 또는 원장님이 장면 사이에 써 넣은 문장)은
    #    문장을 크게 보여주는 장면으로 — 이어진 문장끼리는 한 장면으로 묶는다
    merged = []
    for x in data:
        if isinstance(x, str):
            if merged and merged[-1].get("_from_text"):
                merged[-1]["lines"].append(x)
            else:
                merged.append({"type": "caption", "lines": [x], "_from_text": True})
        else:
            merged.append(x)
    data = merged
    out, used = [], 0
    for sc in data:
        sc = clean_scene(sc)
        if not sc:
            continue
        room = max_lines - used
        if room <= 0:
            break
        sc["lines"] = sc["lines"][:room]
        used += len(sc["lines"])
        out.append(sc)
    return out


# ─────────────────────────────────────────────────────────
# 항목이 나타나는 때 맞추기
# ─────────────────────────────────────────────────────────
def _bigrams(s: str) -> set:
    s = re.sub(r"[^\w가-힣]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def align_items(items: list, lines: list) -> list:
    """항목마다 '그 항목을 설명하는 문장 번호'를 고른다.
    글자 두 개씩 겹치는 정도로 가장 닮은 문장을 찾되, 순서는 거꾸로 가지 않게.
    닮은 문장이 없으면 끝에서부터 맞춘다(앞 문장은 보통 '세 가지가 있어요' 같은 도입)."""
    ni, nl = len(items), len(lines)
    if nl == 0:
        return [0] * ni
    grams = [_bigrams(l) for l in lines]
    out, prev = [], 0
    for k, item in enumerate(items):
        ig = _bigrams(item)
        best, best_score = None, 1
        for j in range(prev, nl):
            score = len(ig & grams[j])
            if score > best_score:
                best, best_score = j, score
        if best is None:
            best = max(prev, min(nl - 1, nl - ni + k)) if nl >= ni else max(prev, int(k * nl / ni))
        out.append(best)
        prev = best
    return out


class DiagramScene(ev.Scene):
    """항목들이 하나씩 나타나는 장면의 공통 부분."""
    APPEAR = 0.4      # 나타나는 데 걸리는 시간(초)
    STEPS = 8

    def item_texts(self) -> list:
        return []

    def prepare(self):
        items = self.item_texts()
        idx = align_items(items, self.lines)
        self.reveal = []
        for k, j in enumerate(idx):
            same = [kk for kk, jj in enumerate(idx) if jj == j]
            st, dur = self.times[j] if j < len(self.times) else (0.0, 0.0)
            # 한 문장에 항목이 여럿이면 그 문장 안에서 나눠서 나타낸다
            self.reveal.append(st + 0.15 + dur * 0.8 * same.index(k) / len(same))
        self.layout()

    def layout(self):
        pass

    def state(self, t):
        steps = tuple(quant((t - r) / self.APPEAR, self.STEPS) if t >= r else -1 for r in self.reveal)
        shown = [k for k, s in enumerate(steps) if s >= 0]
        return steps + (shown[-1] if shown else -1,)

    def amount(self, st, k) -> float:
        """k 번째 항목이 얼마나 나타났는지 0~1 (아직이면 -1)."""
        s = st[k]
        return -1 if s < 0 else ease(s / self.STEPS)

    def heading(self, d, text):
        if text:
            f, lines, lh = fit_wrap(text, W - 2 * MARGIN, 140, (56, 50, 44), bold=True, spacing=1.3)
            draw_lines(d, lines, f, MARGIN, CONTENT_TOP - 10, lh, TEXT)
            return CONTENT_TOP - 10 + lh * len(lines) + 40
        return CONTENT_TOP


# ─────────────────────────────────────────────────────────
# 장면 모양들
# ─────────────────────────────────────────────────────────
class TitleScene(ev.Scene):
    def __init__(self, lines, title, subtitle):
        super().__init__(lines)
        self.title, self.subtitle = title, subtitle

    def state(self, t):
        return (quant(t / 0.6, 12), quant((t - 0.4) / 0.6, 12))

    def draw(self, img, st, t):
        d = ImageDraw.Draw(img)
        a, b = ease(st[0] / 12), ease(st[1] / 12)
        inner = W - 2 * MARGIN
        tf, tl, tlh = fit_wrap(self.title, inner, 360, (104, 92, 80, 68, 58), bold=True, spacing=1.25)
        y = 640 - tlh * len(tl) / 2 + (1 - a) * 50
        draw_lines(d, tl, tf, MARGIN, y, tlh, lerp(BG_TOP, TEXT, a), center_w=inner)
        y_line = 640 + tlh * len(tl) / 2 + 40
        half = 140 * b
        if half > 2:
            d.rounded_rectangle([W / 2 - half, y_line, W / 2 + half, y_line + 10], radius=5, fill=ACCENT)
        if self.subtitle:
            sf, sl, slh = fit_wrap(self.subtitle, inner, 220, (46, 42, 38), spacing=1.35)
            draw_lines(d, sl, sf, MARGIN, y_line + 60 + (1 - b) * 30, slh, lerp(BG_TOP, SOFT, b), center_w=inner)


class KeywordScene(ev.Scene):
    def __init__(self, lines, keyword, desc):
        super().__init__(lines)
        self.keyword, self.desc = keyword, desc

    def state(self, t):
        desc_at = self.times[1][0] if len(self.times) > 1 else 0.9
        return (quant(t / 0.45, 9), quant((t - desc_at) / 0.4, 8) if t >= desc_at else -1)

    def draw(self, img, st, t):
        d = ImageDraw.Draw(img)
        draw_badge(d, "핵심 개념")
        k = st[0] / 9
        scale = (0.7 + 0.3 * ease(k) + 0.06 * math.sin(math.pi * k)) if k < 1 else 1.0
        inner = W - 2 * MARGIN - 80
        kf, kl, klh = fit_wrap(self.keyword, inner, 300, (110, 96, 84, 72, 60), bold=True, spacing=1.25)
        kf = font(max(24, int(kf.size * scale)), True)
        kl = wrap(self.keyword, kf, inner + 40)
        klh = int(kf.size * 1.25)
        box_h = klh * len(kl) + 90
        cy = 700
        top = cy - box_h / 2
        d.rounded_rectangle([MARGIN - 10, top, W - MARGIN + 10, top + box_h], radius=40,
                            fill=lerp(BG_TOP, CARD, ease(k)), outline=lerp(BG_TOP, ACCENT, ease(k)), width=5)
        draw_lines(d, kl, kf, MARGIN, top + 40, klh, lerp(BG_TOP, ACCENT, ease(k)), center_w=W - 2 * MARGIN)
        if self.desc and st[1] >= 0:
            b = ease(st[1] / 8)
            df, dl, dlh = fit_wrap(self.desc, W - 2 * MARGIN, 400, (50, 46, 42, 38), spacing=1.4)
            draw_lines(d, dl, df, MARGIN, top + box_h + 70 + (1 - b) * 30, dlh, lerp(BG_TOP, TEXT, b),
                       center_w=W - 2 * MARGIN)


class ListScene(DiagramScene):
    def __init__(self, lines, heading, items):
        super().__init__(lines)
        self.head = heading
        # 💡 '⑤ 가설 검정…'처럼 선지 번호로 시작하는 항목은 동그라미에 그 번호를 쓰고
        #    글에서는 뺀다 — 안 그러면 ⑤ 옆에 '4'가 붙어 헷갈린다(오답 정리 화면)
        marks = [it[0] if it[:1] and it[0] in ev.OPTION_MARKERS else "" for it in items]
        if all(marks):
            self.nums = [str(ev.OPTION_MARKERS.index(m) + 1) for m in marks]
            self.items = [it[1:].strip() for it in items]
        else:
            self.nums = [str(k + 1) for k in range(len(items))]
            self.items = items
        self.speech_items = items     # 문장 맞추기는 번호까지 넣어서 ('1번은…')

    def item_texts(self):
        return self.speech_items

    def layout(self):
        avail = CONTENT_BOTTOM - (CONTENT_TOP + 150)
        for size in (62, 56, 50, 46, 42, 38, 34, 30):
            f = font(size, True)
            rows = [wrap(it, f, W - 2 * MARGIN - size * 2.4) for it in self.items]
            heights = [len(r) * int(size * 1.35) + 56 for r in rows]
            if sum(heights) + 26 * (len(rows) - 1) <= avail:
                break
        self.f, self.rows, self.heights = f, rows, heights

    def draw(self, img, st, t):
        d = ImageDraw.Draw(img)
        y = self.heading(d, self.head)
        total = sum(self.heights) + 26 * (len(self.rows) - 1)
        y = max(y, (y + CONTENT_BOTTOM - total) / 2)
        focus = st[-1]
        for k, (rows, h) in enumerate(zip(self.rows, self.heights)):
            a = self.amount(st, k)
            if a < 0:
                # 자리만 흐리게 잡아 둔다 — 몇 개가 나올지 미리 보이게
                d.rounded_rectangle([MARGIN, y, W - MARGIN, y + h], radius=28, outline=(38, 43, 62), width=3)
            else:
                dx = (1 - a) * 120
                fill = CARD_FOCUS if k == focus else CARD
                d.rounded_rectangle([MARGIN + dx, y, W - MARGIN + dx, y + h], radius=28, fill=lerp(BG_TOP, fill, a))
                r = int(self.f.size * 0.75)
                cx, cy = MARGIN + 60 + dx, y + h / 2
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=lerp(BG_TOP, ACCENT, a))
                nf = font(int(self.f.size * 0.8), True)
                num = self.nums[k]
                d.text((cx - nf.getlength(num) / 2, cy - nf.size * 0.68), num, font=nf, fill=BG_BOTTOM)
                ty = y + (h - len(rows) * int(self.f.size * 1.35)) / 2 - 4
                draw_lines(d, rows, self.f, MARGIN + 60 + r * 2 + 10 + dx, ty, int(self.f.size * 1.35), lerp(BG_TOP, TEXT, a))
            y += h + 26


class TimelineScene(DiagramScene):
    def __init__(self, lines, heading, events):
        super().__init__(lines)
        self.head, self.events = heading, events

    def item_texts(self):
        return [f"{e['label']} {e['text']}" for e in self.events]

    def layout(self):
        avail = CONTENT_BOTTOM - (CONTENT_TOP + 150)
        x_text = MARGIN + 110
        for size in (56, 50, 46, 42, 38, 34, 30):
            f, lf = font(size, True), font(int(size * 0.8), True)
            rows = [wrap(e["text"], f, W - MARGIN - x_text) for e in self.events]
            heights = [(int(lf.size * 1.4) if e["label"] else 0) + len(r) * int(size * 1.35) + 40
                       for e, r in zip(self.events, rows)]
            if sum(heights) <= avail:
                break
        self.f, self.lf, self.rows, self.heights, self.x_text = f, lf, rows, heights, x_text

    def draw(self, img, st, t):
        d = ImageDraw.Draw(img)
        y0 = self.heading(d, self.head)
        y0 = max(y0, (y0 + CONTENT_BOTTOM - sum(self.heights)) / 2)
        lx = MARGIN + 40
        ys, y = [], y0
        for h in self.heights:
            ys.append(y)
            y += h
        # 세로 줄: 바탕은 흐리게, 나타난 마지막 점까지는 노랗게 자란다
        d.rounded_rectangle([lx - 4, ys[0] + 20, lx + 4, ys[-1] + 20], radius=4, fill=(40, 45, 64))
        shown = [k for k in range(len(self.events)) if st[k] >= 0]
        if shown:
            last = shown[-1]
            a = self.amount(st, last)
            prev_y = ys[last - 1] + 20 if last > 0 else ys[0] + 20
            end_y = prev_y + (ys[last] + 20 - prev_y) * a
            d.rounded_rectangle([lx - 4, ys[0] + 20, lx + 4, max(ys[0] + 28, end_y)], radius=4, fill=ACCENT)
        for k, ev_ in enumerate(self.events):
            a = self.amount(st, k)
            cy = ys[k] + 20
            if a < 0:
                d.ellipse([lx - 14, cy - 14, lx + 14, cy + 14], outline=(60, 66, 88), width=4, fill=BG_TOP)
                continue
            r = 14 + 8 * a
            d.ellipse([lx - r, cy - r, lx + r, cy + r], fill=ACCENT)
            yy = ys[k] + (1 - a) * 30
            if ev_["label"]:
                d.text((self.x_text, yy - 6), ev_["label"], font=self.lf, fill=lerp(BG_TOP, ACCENT, a))
                yy += int(self.lf.size * 1.4)
            draw_lines(d, self.rows[k], self.f, self.x_text, yy, int(self.f.size * 1.35),
                       lerp(BG_TOP, TEXT if k == st[-1] else SOFT, a))


class CompareScene(DiagramScene):
    def __init__(self, lines, heading, left, right):
        super().__init__(lines)
        self.head, self.left, self.right = heading, left, right
        # 왼쪽 첫 점, 오른쪽 첫 점, 왼쪽 둘째 점 ... 순서로 나타난다
        self.order = []
        for i in range(max(len(left["points"]), len(right["points"]))):
            if i < len(left["points"]):
                self.order.append(("L", i))
            if i < len(right["points"]):
                self.order.append(("R", i))

    def item_texts(self):
        # 제목 두 개가 먼저, 그다음 점들
        return [self.left["title"], self.right["title"]] + [
            (self.left if s == "L" else self.right)["points"][i] for s, i in self.order]

    def layout(self):
        self.col_w = (W - 2 * MARGIN - 40) / 2
        for size in (46, 42, 38, 34, 30, 28):
            f = font(size)
            ok = True
            self.cells = {}
            for side, data in (("L", self.left), ("R", self.right)):
                y = 0
                for i, p in enumerate(data["points"]):
                    rows = wrap(p, f, self.col_w - 60)
                    h = len(rows) * int(size * 1.35) + 36
                    self.cells[(side, i)] = (y, h, rows)
                    y += h + 18
                if y > CONTENT_BOTTOM - CONTENT_TOP - 330:
                    ok = False
            if ok:
                break
        self.f = f

    def draw(self, img, st, t):
        d = ImageDraw.Draw(img)
        y0 = self.heading(d, self.head)
        tf = font(52, True)
        for col, (side, data, color) in enumerate((("L", self.left, LEFT_COLOR), ("R", self.right, RIGHT_COLOR))):
            x0 = MARGIN + col * (self.col_w + 40)
            a = self.amount(st, col)
            if a < 0:
                continue
            d.rounded_rectangle([x0, y0 + (1 - a) * 30, x0 + self.col_w, y0 + 110 + (1 - a) * 30], radius=26,
                                fill=lerp(BG_TOP, color, a))
            tt = data["title"] if tf.getlength(data["title"]) < self.col_w - 30 else data["title"][:7] + "…"
            d.text((x0 + (self.col_w - tf.getlength(tt)) / 2, y0 + 22 + (1 - a) * 30), tt, font=tf, fill=BG_BOTTOM)
        # 가운데 VS
        if st[0] >= 0 and st[1] >= 0:
            vf = font(40, True)
            cx, cy, r = W / 2, y0 + 55, 44
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BG_BOTTOM, outline=ACCENT, width=4)
            d.text((cx - vf.getlength("VS") / 2, cy - vf.size * 0.68), "VS", font=vf, fill=ACCENT)
        focus = st[-1]
        for n, (side, i) in enumerate(self.order):
            k = n + 2
            a = self.amount(st, k)
            if a < 0:
                continue
            y, h, rows = self.cells[(side, i)]
            x0 = MARGIN + (0 if side == "L" else self.col_w + 40)
            yy = y0 + 150 + y + (1 - a) * 30
            color = LEFT_COLOR if side == "L" else RIGHT_COLOR
            fill = CARD_FOCUS if k == focus else CARD
            d.rounded_rectangle([x0, yy, x0 + self.col_w, yy + h], radius=22, fill=lerp(BG_TOP, fill, a))
            d.rounded_rectangle([x0, yy, x0 + 10, yy + h], radius=5, fill=lerp(BG_TOP, color, a))
            draw_lines(d, rows, self.f, x0 + 34, yy + 16, int(self.f.size * 1.35), lerp(BG_TOP, TEXT, a))


class RelationScene(DiagramScene):
    """이름들을 둥글게 놓고, 관계 화살표가 하나씩 그어진다."""
    def __init__(self, lines, heading, nodes, edges):
        super().__init__(lines)
        self.head, self.nodes, self.edges = heading, nodes, edges

    def item_texts(self):
        return [f"{e['from']} {e['to']} {e['label']}" for e in self.edges]

    def layout(self):
        n = len(self.nodes)
        cx, cy = W / 2, (CONTENT_TOP + 150 + CONTENT_BOTTOM) / 2
        rx, ry = 330, 380
        if n == 2:
            pos = [(cx, cy - ry * 0.75), (cx, cy + ry * 0.75)]
        else:
            pos = [(cx + rx * math.sin(2 * math.pi * k / n), cy - ry * math.cos(2 * math.pi * k / n))
                   for k in range(n)]
        self.pos = dict(zip(self.nodes, pos))
        self.nf = font(56 if n <= 3 else 48, True)

    def node_box(self, name):
        x, y = self.pos[name]
        w = self.nf.getlength(name) + 64
        h = self.nf.size * 1.9
        return x - w / 2, y - h / 2, x + w / 2, y + h / 2

    def _edge_end(self, a, b):
        """a 상자 가장자리에서 b 상자 가장자리까지 (상자를 뚫고 그리지 않게)."""
        (x1, y1), (x2, y2) = self.pos[a], self.pos[b]

        def clip(x, y, dx, dy, box):
            bx0, by0, bx1, by1 = box
            hw, hh = (bx1 - bx0) / 2 + 12, (by1 - by0) / 2 + 12
            s = min(hw / abs(dx) if dx else 1e9, hh / abs(dy) if dy else 1e9)
            return x + dx * s, y + dy * s

        dx, dy = x2 - x1, y2 - y1
        p1 = clip(x1, y1, dx, dy, self.node_box(a))
        p2 = clip(x2, y2, -dx, -dy, self.node_box(b))
        return p1, p2

    def draw(self, img, st, t):
        d = ImageDraw.Draw(img)
        self.heading(d, self.head)
        node_a = ease(st[-1] / 6)
        focus = st[-2]
        lf = font(40, True)
        # 화살표 먼저, 이름 상자는 그 위에
        for k, e in enumerate(self.edges):
            a = self.amount(st, k)
            if a < 0:
                continue
            (x1, y1), (x2, y2) = self._edge_end(e["from"], e["to"])
            ex, ey = x1 + (x2 - x1) * a, y1 + (y2 - y1) * a
            color = ACCENT if k == focus else SOFT
            d.line([(x1, y1), (ex, ey)], fill=color, width=7)
            if a > 0.95:
                ang = math.atan2(y2 - y1, x2 - x1)
                for s in (-1, 1):
                    d.line([(x2, y2), (x2 - 30 * math.cos(ang + s * 0.45), y2 - 30 * math.sin(ang + s * 0.45))],
                           fill=color, width=7)
                if e["label"]:
                    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                    w = lf.getlength(e["label"]) + 36
                    d.rounded_rectangle([mx - w / 2, my - 36, mx + w / 2, my + 36], radius=18,
                                        fill=BG_BOTTOM, outline=color, width=3)
                    d.text((mx - lf.getlength(e["label"]) / 2, my - 29), e["label"], font=lf, fill=color)
        for i, name in enumerate(self.nodes):
            color = NODE_COLORS[i % len(NODE_COLORS)]
            x0, y0, x1, y1 = self.node_box(name)
            d.rounded_rectangle([x0, y0, x1, y1], radius=int((y1 - y0) / 2), fill=lerp(BG_TOP, color, node_a))
            d.text((x0 + 32, y0 + (y1 - y0 - self.nf.size * 1.35) / 2), name, font=self.nf,
                   fill=lerp(BG_TOP, BG_BOTTOM, node_a))

    def state(self, t):
        # 맨 끝에 '이름 상자가 나타나는 정도'를 덧붙인다 → 초점은 st[-2]
        return super().state(t) + (quant(t / 0.5, 6),)


class QuoteScene(ev.PassageScene):
    def __init__(self, lines, source, text, highlight):
        i = text.find(highlight) if highlight else -1
        super().__init__(lines, text, (i, i + len(highlight)) if i >= 0 else None)
        self.badge = source or "원문"

    SIZES = (64, 58, 52, 48, 44, 40, 36, 32)


def build_scene(sc: dict):
    kind, lines = sc["type"], sc["lines"]
    if kind == "title":
        return TitleScene(lines, sc["title"], sc.get("subtitle", ""))
    if kind == "keyword":
        return KeywordScene(lines, sc["keyword"], sc.get("desc", ""))
    if kind == "list":
        return ListScene(lines, sc.get("heading", ""), sc["items"])
    if kind == "timeline":
        return TimelineScene(lines, sc.get("heading", ""), sc["events"])
    if kind == "compare":
        return CompareScene(lines, sc.get("heading", ""), sc["left"], sc["right"])
    if kind == "relation":
        return RelationScene(lines, sc.get("heading", ""), sc["nodes"], sc["edges"])
    if kind == "quote":
        return QuoteScene(lines, sc.get("source", ""), sc["text"], sc.get("highlight", ""))
    return ev.CaptionScene(lines)


def render_storyboard_video(storyboard: list, title: str = "", tts=None) -> ev.VideoResult:
    """설계도 → 영상. 맨 끝에 상표 화면을 붙인다."""
    scenes = [build_scene(sc) for sc in storyboard]
    if not scenes or not isinstance(scenes[0], TitleScene):
        if title:
            scenes.insert(0, ev.IntroScene([], pill=title[:20], fixed=1.8))
    scenes.append(ev.OutroScene(fixed=1.5))
    return ev.build_video(scenes, chip=title[:14] if title else "", tts=tts)
