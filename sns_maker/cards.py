"""카드뉴스 그림(PNG) 만들기. 인스타그램 세로 비율(4:5, 1080×1350)."""

import io
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import catalog

W, H = 1080, 1350
PAD = 96
FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "NotoSansKR.ttf"


def _font(size: int, weight: str = "Regular"):
    try:
        f = ImageFont.truetype(str(FONT_PATH), size)
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
        return f
    except OSError:
        return ImageFont.load_default()


def _wrap(draw, text: str, font, width: int) -> list:
    """한 글자씩 재어 가며 줄을 나눈다. 띄어쓰기에서 끊을 수 있으면 거기서 끊는다."""
    lines = []
    for para in (text or "").split("\n"):
        cur = ""
        for ch in para:
            if draw.textlength(cur + ch, font=font) <= width:
                cur += ch
                continue
            cut = cur.rfind(" ")
            if cut > len(cur) * 0.5:
                lines.append(cur[:cut])
                cur = cur[cut + 1:] + ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur.strip())
    return lines


def _fit(draw, text, weight, size, min_size, width, max_h, spacing=1.45):
    """정한 높이에 들어갈 때까지 글자를 줄인다."""
    while True:
        font = _font(size, weight)
        lines = _wrap(draw, text, font, width)
        line_h = int(size * spacing)
        if len(lines) * line_h <= max_h or size <= min_size:
            return font, lines, line_h
        size -= 4


def _rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def render_card(slide: dict, index: int, total: int, academy: str = "", theme: str = "navy") -> bytes:
    bg, fg, accent = (_rgb(c) for c in catalog.THEMES.get(theme, catalog.THEMES["navy"]))
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    inner = W - PAD * 2
    title, body = slide.get("title", ""), slide.get("body", "")

    if index == 0:   # 표지
        d.rectangle([PAD, 300, PAD + 120, 314], fill=accent)
        tf, tl, th = _fit(d, title, "Black", 104, 56, inner, 520, 1.3)
        y = 360
        for line in tl:
            d.text((PAD, y), line, font=tf, fill=fg)
            y += th
        if body:
            bf, bl, bh = _fit(d, body, "Medium", 46, 30, inner, 260)
            y += 40
            for line in bl:
                d.text((PAD, y), line, font=bf, fill=accent)
                y += bh
    else:
        num = _font(40, "Bold")
        tag = f"{index:02d}"
        d.rounded_rectangle([PAD, 150, PAD + 110, 220], radius=35, fill=accent)
        d.text((PAD + 55, 185), tag, font=num, fill=bg, anchor="mm")
        tf, tl, th = _fit(d, title, "Bold", 76, 48, inner, 330, 1.3)
        y = 290
        for line in tl:
            d.text((PAD, y), line, font=tf, fill=fg)
            y += th
        y += 30
        d.line([PAD, y, W - PAD, y], fill=accent, width=4)
        y += 60
        bf, bl, bh = _fit(d, body, "Regular", 50, 32, inner, H - y - 200, 1.6)
        for line in bl:
            d.text((PAD, y), line, font=bf, fill=fg)
            y += bh

    small = _font(30, "Medium")
    if academy:
        d.text((PAD, H - 110), academy, font=small, fill=fg)
    d.text((W - PAD, H - 110), f"{index + 1} / {total}", font=small, fill=fg, anchor="ra")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def render_zip(slides: list, academy: str = "", theme: str = "navy") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, s in enumerate(slides):
            z.writestr(f"card_{i + 1:02d}.png", render_card(s, i, len(slides), academy, theme))
    return buf.getvalue()
