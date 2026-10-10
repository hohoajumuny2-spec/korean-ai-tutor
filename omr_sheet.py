"""종이 OMR 답안지 — 인쇄할 답안지(PDF)를 만들고, 칠한 답안지 사진을 읽는다.

💡 학생이 화면 OMR에 답을 누르는 대신, 종이 답안지에 칠하고 원장님이 폰으로 찍거나
   복합기로 스캔해 올리면 채점한다. 답안지는 여기서 직접 만들기 때문에 칸의 자리를
   정확히 안다. 그래서 인공지능에 '읽어 달라'고 맡기지 않고 자리마다 얼마나
   까만지를 재서 읽는다(비용이 들지 않고, 같은 사진은 언제나 같은 답으로 읽힌다).

답안지 생김새 (A4 세로, 단위 pt):
  · 네 모서리에 까만 네모 — 사진이 비뚤게 찍혀도 이 넷을 찾아 반듯하게 편다.
  · 위쪽 가운데 까만 막대 — 거꾸로 찍힌 사진을 바로 세운다(아래쪽 같은 자리는 비워 둔다).
  · 답안지 번호 칸 24개 — 누구 답안지인지(학생 · 시험)를 까만 칸/흰 칸으로 적어 둔다.
  · 답 칸: 4줄 × 25문항 = 최대 100문항, 문항마다 ①~⑤.
"""
import io
import os

import numpy as np

PAGE_W, PAGE_H = 595.28, 841.89          # A4
MARK = 18.0                               # 모서리 네모 한 변
MARK_C = [(30.0, 30.0), (PAGE_W - 30.0, 30.0), (PAGE_W - 30.0, PAGE_H - 30.0), (30.0, PAGE_H - 30.0)]  # TL TR BR BL
BAR = (PAGE_W / 2 - 48, 24.0, PAGE_W / 2 + 48, 36.0)   # 방향 막대
BAR_MIRROR = (PAGE_W - BAR[2], PAGE_H - BAR[3], PAGE_W - BAR[0], PAGE_H - BAR[1])

CODE_BITS = 24                            # 앞 20칸 = 번호, 뒤 4칸 = 검산
CODE_CELL, CODE_GAP = 9.0, 4.0
CODE_X, CODE_Y = 150.0, 152.0

COLS, ROWS = 4, 25
MAX_Q = COLS * ROWS
GRID_X, GRID_Y = 22.0, 196.0
COL_W = (PAGE_W - 2 * GRID_X) / COLS
ROW_H = (790.0 - GRID_Y) / ROWS
BUBBLE_R = 7.0
BUBBLE_DX = 20.0
BUBBLE_X0 = 42.0                          # 줄 왼쪽 끝에서 ① 가운데까지

SCALE = 2.0                               # 읽을 때 펴는 크기: 1pt = 2px

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "NotoSansKR.ttf")


class OmrError(Exception):
    """사진에서 답안지를 찾지 못했을 때. 원장님께 그대로 보여 줄 문구를 담는다."""


# ─────────────────────────────────────────────────────────
# 자리 계산 — 인쇄와 읽기가 같은 함수를 쓴다
# ─────────────────────────────────────────────────────────
def bubble_center(q_index: int, choice: int):
    """q_index(0부터) 문항의 choice(1~5)번 동그라미 가운데."""
    col, row = divmod(q_index, ROWS)
    x = GRID_X + col * COL_W + BUBBLE_X0 + (choice - 1) * BUBBLE_DX
    y = GRID_Y + row * ROW_H + ROW_H / 2
    return x, y


def code_cell(i: int):
    x = CODE_X + i * (CODE_CELL + CODE_GAP)
    return (x, CODE_Y, x + CODE_CELL, CODE_Y + CODE_CELL)


def encode_code(n: int) -> list:
    """번호(1 ~ 2^20-1) → 칸 24개(1=칠함). 뒤 4칸은 앞 다섯 묶음을 더한 검산."""
    if not 0 <= n < (1 << 20):
        raise ValueError("답안지 번호가 범위를 벗어났습니다")
    check = sum((n >> (4 * k)) & 15 for k in range(5)) % 16
    v = (n << 4) | check
    return [(v >> (CODE_BITS - 1 - i)) & 1 for i in range(CODE_BITS)]


def decode_code(bits: list):
    """칸 24개 → 번호. 0이면 이름 없는 빈 답안지, 검산이 틀리면 None."""
    v = 0
    for b in bits:
        v = (v << 1) | (1 if b else 0)
    n, check = v >> 4, v & 15
    if sum((n >> (4 * k)) & 15 for k in range(5)) % 16 != check:
        return None
    return n


# ─────────────────────────────────────────────────────────
# 인쇄용 답안지
# ─────────────────────────────────────────────────────────
_FIXED_TEXT = ("OMR 답안지 이름 컴퓨터용 사인펜이나 진한 연필로 동그라미 안을 꽉 채워 칠하세요. "
               "고칠 때는 지우개로 깨끗이 지우세요. 답안지 번호 ← 칠하지 마세요 답 없음 (안 칠해요) "
               "단답형 · 답안지에 따로 써요 개 접거나 구기지 말고 선생님께 내세요. 0123456789")


def _sheet_text(sheets, title, academy) -> str:
    return _FIXED_TEXT + (title or "") + (academy or "") + "".join(
        f"{s.get('name') or ''}{s.get('info') or ''}" for s in sheets)


def _font_for(text: str):
    """한글 글꼴(10MB)을 통째로 넣으면 답안지 PDF가 수 MB가 된다. 실제로 쓰는 글자만 남긴다.
    글자 줄이기 도구(fonttools)가 없으면 통째로 넣는다(커도 인쇄는 된다)."""
    if not os.path.exists(FONT_PATH):
        return None
    try:
        from fontTools import subset, ttLib
        font = ttLib.TTFont(FONT_PATH)
        opts = subset.Options()
        opts.layout_features = []
        opts.name_IDs = ["*"]
        sub = subset.Subsetter(options=opts)
        sub.populate(text=text)
        sub.subset(font)
        if "fvar" in font:          # 굵기를 고를 수 있는 글꼴은 기본이 아주 가는 굵기다 → 보통 굵기로 고정
            from fontTools.varLib import instancer
            font = instancer.instantiateVariableFont(font, {"wght": 500})
        buf = io.BytesIO()
        font.save(buf)
        return buf.getvalue()
    except Exception:
        return open(FONT_PATH, "rb").read()


def render_sheets_pdf(sheets: list, kinds: list, title: str, academy: str = "LOGYEDU") -> bytes:
    """답안지 PDF. sheets: [{"code": 번호(0=빈 답안지), "name": 학생 이름, "info": "학교 학년"}]
    kinds: 문항마다 choice / multiN / short / none (main.slot_kind)."""
    import fitz

    n = min(len(kinds), MAX_Q)
    doc = fitz.open()
    font_buf = _font_for(_sheet_text(sheets, title, academy))
    gray, light, black = (0.45, 0.45, 0.45), (0.62, 0.62, 0.62), (0, 0, 0)
    for sheet in sheets:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        fn = "helv"
        if font_buf:
            page.insert_font(fontname="kr", fontbuffer=font_buf)
            fn = "kr"
        # 💡 page.insert_text / draw_* 를 한 번 부를 때마다 쪽 내용이 새로 쓰여 느리다.
        #    한 장을 다 그린 뒤 한 번에 붙인다.
        sh = page.new_shape()

        def text(x, y, s, size=10, color=black):
            sh.insert_text((x, y), s, fontname=fn, fontsize=size, color=color)

        def box(rect, fill=None, color=black, width=0.8):
            sh.draw_rect(fitz.Rect(*rect))
            sh.finish(color=color, fill=fill, width=width)

        for cx, cy in MARK_C:
            box((cx - MARK / 2, cy - MARK / 2, cx + MARK / 2, cy + MARK / 2), fill=black)
        box(BAR, fill=black)

        text(48, 66, f"{academy}  OMR 답안지", 10, gray)
        text(48, 92, (title or "")[:40], 17)
        name = (sheet.get("name") or "").strip()
        box((48, 104, 330, 136), color=gray)
        if name:
            text(56, 126, f"이름  {name}", 15)
            if sheet.get("info"):
                text(220, 126, str(sheet["info"])[:16], 10, gray)
        else:
            text(56, 126, "이름", 13, gray)
        text(345, 110, "· 컴퓨터용 사인펜이나 진한 연필로", 8, gray)
        text(345, 120, "  동그라미 안을 꽉 채워 칠하세요.", 8, gray)
        text(345, 130, "· 고칠 때는 지우개로 깨끗이 지우세요.", 8, gray)
        text(345, 140, "· 접거나 구기지 말고 선생님께 내세요.", 8, gray)

        text(48, CODE_Y + 8, "답안지 번호", 8, gray)
        for i, b in enumerate(encode_code(int(sheet.get("code") or 0))):
            if b:
                box(code_cell(i), fill=black)
            else:
                box(code_cell(i), color=light, width=0.5)
        text(CODE_X + CODE_BITS * (CODE_CELL + CODE_GAP) + 6, CODE_Y + 8, "← 칠하지 마세요", 8, gray)

        def line(p, q, width):
            sh.draw_line(p, q)
            sh.finish(color=light, width=width)

        for c in range(COLS):
            x0 = GRID_X + c * COL_W
            if c * ROWS < n:
                line((x0 + 2, GRID_Y - 4), (x0 + COL_W - 4, GRID_Y - 4), 0.6)
        for i in range(n):
            col, row = divmod(i, ROWS)
            x0 = GRID_X + col * COL_W
            yc = GRID_Y + row * ROW_H + ROW_H / 2
            if row % 5 == 4 and i != n - 1:
                line((x0 + 2, yc + ROW_H / 2), (x0 + COL_W - 4, yc + ROW_H / 2), 0.4)
            text(x0 + (8 if i + 1 < 10 else 4 if i + 1 < 100 else 0), yc + 4, str(i + 1), 10.5)
            kind = kinds[i]
            if kind == "none":
                text(x0 + BUBBLE_X0 - 6, yc + 3.5, "답 없음 (안 칠해요)", 8, light)
                continue
            if kind == "short":
                text(x0 + BUBBLE_X0 - 6, yc + 3.5, "단답형 · 답안지에 따로 써요", 8, light)
                continue
            for k in range(1, 6):
                bx, by = bubble_center(i, k)
                sh.draw_circle((bx, by), BUBBLE_R)
                sh.finish(color=light, width=0.8)
                text(bx - 2.6, by + 3, str(k), 7.5, light)
            if kind.startswith("multi"):
                text(x0 + BUBBLE_X0 + 4 * BUBBLE_DX + 10, yc + 3, f"{kind[5:]}개", 7, gray)
        sh.commit()
    out = doc.tobytes(garbage=4, deflate=True)   # garbage=4: 쪽마다 넣은 같은 글꼴을 하나로 합친다
    doc.close()
    return out


# ─────────────────────────────────────────────────────────
# 사진 읽기
# ─────────────────────────────────────────────────────────
def load_images(data: bytes, filename: str = "") -> list:
    """올린 파일 하나 → 회색 사진 목록. PDF(스캔본)는 쪽마다 한 장."""
    import cv2

    head = data[:5]
    if head == b"%PDF-" or filename.lower().endswith(".pdf"):
        import fitz
        out = []
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=200, colorspace=fitz.csGRAY)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, 0].copy()
                out.append(img)
        return out
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise OmrError("사진을 열지 못했습니다. JPG나 PNG, PDF로 올려 주세요(아이폰 HEIC는 '가장 호환성 높은' 형식으로 찍어 주세요).")
    return [img]


def _find_marks(gray):
    """모서리 네모 네 개의 가운데(사진 좌표) — TL, TR, BR, BL 순."""
    import cv2

    h, w = gray.shape
    big = max(h, w)
    block = int(big / 15) | 1
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    th = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, 12)
    contours, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cands = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < (big * 0.008) ** 2 or area > (big * 0.09) ** 2:
            continue
        (cx, cy), (rw, rh), _ = cv2.minAreaRect(c)
        if rw <= 0 or rh <= 0 or not 0.6 < rw / rh < 1.66 or area / (rw * rh) < 0.86:
            continue
        approx = cv2.approxPolyDP(c, 0.06 * cv2.arcLength(c, True), True)
        if len(approx) != 4:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        mask = np.zeros((bh, bw), np.uint8)
        cv2.drawContours(mask, [c - [x, y]], -1, 255, -1)
        inside = th[y:y + bh, x:x + bw][mask > 0]
        if inside.size == 0 or inside.mean() < 0.8 * 255:      # 속이 빈 네모(칸 테두리)는 뺀다
            continue
        cands.append((area, cx, cy))
    if len(cands) < 4:
        raise OmrError("답안지 네 모서리의 까만 네모를 찾지 못했습니다. 답안지 전체가 나오게, 밝은 곳에서 다시 찍어 주세요.")
    cands.sort(reverse=True)
    floor = cands[3][0] * 0.5
    pts = np.array([(x, y) for a, x, y in cands if a >= floor], dtype=np.float32)
    s, d = pts.sum(axis=1), pts[:, 0] - pts[:, 1]
    tl, br, tr, bl = pts[s.argmin()], pts[s.argmax()], pts[d.argmax()], pts[d.argmin()]
    quad = np.array([tl, tr, br, bl], dtype=np.float32)
    if len({tuple(p) for p in quad.tolist()}) < 4:
        raise OmrError("답안지 모서리를 제대로 찾지 못했습니다. 답안지를 똑바로 놓고 다시 찍어 주세요.")
    # 세로 답안지인데 가로가 더 길게 잡혔으면 옆으로 누운 사진이다 → 한 칸 돌려 이름을 다시 붙인다
    top = np.linalg.norm(quad[1] - quad[0])
    left = np.linalg.norm(quad[3] - quad[0])
    if top > left:
        quad = np.array([quad[3], quad[0], quad[1], quad[2]], dtype=np.float32)
        top, left = left, top
    want = (MARK_C[1][0] - MARK_C[0][0]) / (MARK_C[3][1] - MARK_C[0][1])
    if not 0.75 * want < top / max(left, 1) < 1.3 * want:
        raise OmrError("답안지 모서리가 이상하게 잡혔습니다. 답안지 한 장만, 전체가 나오게 찍어 주세요.")
    return quad


def _warp(gray, quad):
    import cv2

    dst = np.array([(x * SCALE, y * SCALE) for x, y in MARK_C], dtype=np.float32)
    m = cv2.getPerspectiveTransform(quad, dst)
    size = (int(PAGE_W * SCALE), int(PAGE_H * SCALE))
    return cv2.warpPerspective(gray, m, size, flags=cv2.INTER_LINEAR, borderValue=255)


def _dark(th, rect):
    x0, y0, x1, y1 = (int(round(v * SCALE)) for v in rect)
    roi = th[y0:y1, x0:x1]
    return float(roi.mean()) / 255 if roi.size else 0.0


def read_sheet(gray, kinds) -> dict:
    """회색 사진 한 장 → {"code": 번호|0|None, "answers": [...], "flags": {번호: 이유}, "fills": [...]}

    kinds 는 문항마다 choice / multiN / short / none (main.slot_kind). 숫자를 주면 모두 choice.
    answers 는 문항마다 '' / '3' / '2+4'(여러 개 칠함). 동그라미가 없는 문항(short · none)은 ''.
    flags 는 원장님이 눈으로 확인해야 하는 문항: 흐림(지운 자국 · 살짝 칠함), 여러 개."""
    import cv2

    if max(gray.shape) > 2600:                       # 폰 사진은 너무 크다 — 줄여도 충분히 읽힌다
        f = 2600 / max(gray.shape)
        gray = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    quad = _find_marks(gray)
    page = _warp(gray, quad)
    th = cv2.adaptiveThreshold(cv2.GaussianBlur(page, (3, 3), 0), 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 61, 14)
    # 위쪽 막대가 아래에 있으면 거꾸로 찍힌 것 → 뒤집는다
    if _dark(th, BAR_MIRROR) > _dark(th, BAR):
        page, th = cv2.rotate(page, cv2.ROTATE_180), cv2.rotate(th, cv2.ROTATE_180)
    if _dark(th, BAR) < 0.5:
        raise OmrError("우리 학원 OMR 답안지가 아닌 것 같습니다. 이 화면에서 인쇄한 답안지를 찍어 주세요.")

    bits = []
    for i in range(CODE_BITS):
        x0, y0, x1, y1 = code_cell(i)
        pad = CODE_CELL * 0.2
        bits.append(1 if _dark(th, (x0 + pad, y0 + pad, x1 - pad, y1 - pad)) > 0.5 else 0)
    code = decode_code(bits)

    if isinstance(kinds, int):
        kinds = ["choice"] * kinds
    kinds = list(kinds)[:MAX_Q]
    n = len(kinds)
    # 💡 칸이 얼마나 까만지를 '흑/백'으로만 나누면 지우개로 지운 연한 자국도 칠한 것처럼 읽힌다.
    #    주변 종이 밝기에 견줘 얼마나 어두운지(0~1)를 잰다 — 그림자가 진 사진에서도 같은 기준이 된다.
    paper = cv2.GaussianBlur(cv2.dilate(page, np.ones((31, 31), np.uint8)), (0, 0), 12).astype(np.float32)
    dark = np.clip(1.0 - page.astype(np.float32) / np.maximum(paper, 1.0), 0.0, 1.0)
    r = int(BUBBLE_R * SCALE * 0.72)
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    disk = (xx ** 2 + yy ** 2) <= r * r
    fills = []
    for i in range(n):
        row = []
        if kinds[i] in ("short", "none"):       # 동그라미를 그리지 않은 줄
            fills.append(None)
            continue
        for k in range(1, 6):
            cx, cy = (int(round(v * SCALE)) for v in bubble_center(i, k))
            roi = dark[cy - r:cy + r + 1, cx - r:cx + r + 1]
            row.append(round(float(roi[disk].mean()), 3) if roi.shape == disk.shape else 0.0)
        fills.append(row)
    # 빈 동그라미도 테두리 · 숫자 때문에 조금은 까맣다. 그 바탕을 답안지마다 재서 뺀다.
    flat = sorted(v for row in fills if row for v in row)
    base = flat[len(flat) // 2] if flat else 0.0
    answers, flags = [], {}
    for i, row in enumerate(fills):
        if row is None:
            answers.append("")
            continue
        want = int(kinds[i][5:]) if kinds[i].startswith("multi") else 1
        # 칠한 칸: 바탕보다 확실히 어둡고, 그 줄에서 가장 진한 칸에 견줘도 진하다.
        # 지운 자국은 바탕보다는 어둡지만 칠한 칸보다 한참 옅다 → '흐림'으로 원장님께 보인다.
        top = max(row)
        strong = [k + 1 for k, v in enumerate(row) if v - base >= 0.20 and v >= 0.6 * top]
        faint = [k + 1 for k, v in enumerate(row) if v - base >= 0.10 and k + 1 not in strong]
        answers.append("+".join(str(k) for k in strong))
        if faint:
            flags[i + 1] = "흐림"
        elif len(strong) > want:
            flags[i + 1] = "여러 개"
    return {"code": code, "answers": answers, "flags": flags, "fills": fills}

