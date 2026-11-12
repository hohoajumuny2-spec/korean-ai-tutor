"""해설 영상 만들기 — 사람 같은 목소리 + 움직이는 화면.

main.py 의 /api/admin/generate_video(해설 영상 만들기)가 이 모듈을 부른다.

목소리
  1순위: 구글 Gemini 음성(TTS). 이미 쓰고 있는 GOOGLE_API_KEY(또는 GEMINI_API_KEY)를
         그대로 쓰므로 새로 가입하거나 키를 받을 필요가 없다.
         💡 요금: flash 음성 모델은 소리 1초에 약 32토큰, 100만 토큰에 10달러 안팎이라
            영상 1분에 30원 정도다. (해설 영상 하나가 보통 1~3분)
  2순위: 그게 안 되면(키 없음 · 한도 초과 등) 예전처럼 무료 gTTS 로 만든다.
         영상이 아예 안 나오는 것보다는 기계 목소리라도 나오는 편이 낫다.

  서버 환경변수로 바꿀 수 있다(안 넣으면 기본값).
    VIDEO_TTS_MODEL  쓸 음성 모델. 쉼표로 여러 개 = 앞에서부터 시도
    VIDEO_TTS_VOICE  목소리 이름 (기본 Charon — 차분하고 또렷한 설명조)
    VIDEO_TTS_STYLE  말투 지시문. 빈칸이면 지시 없이 읽는다

화면
  사진 한 장을 소리 길이만큼 띄우던 예전 방식 대신,
    - 읽는 글자를 따라 자막 색이 차오르고
    - 지문 근거 문장에 형광펜이 그어지고
    - 선지마다 해설이 그 선지를 말할 때 O / X 가 찍히고
    - 장면이 바뀔 때 부드럽게 넘어가고, 맨 위에 진행 막대가 찬다.
  💡 같은 그림이 이어지는 동안은 그림을 한 장만 저장하고 '몇 프레임 동안'만 적어 두므로,
     서버가 1초에 30장을 일일이 그리지 않는다(3분 영상도 그림은 몇백 장).
"""
import base64
import os
import re
import shutil
import subprocess
import tempfile
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FPS = 30
SAMPLE_RATE = 24000          # Gemini 음성이 주는 소리 형식(16비트 · 1채널 · 24kHz)
LINE_PAUSE = 0.3             # 문장 사이 쉬는 시간(초)
MAX_LINES = 25               # 한 영상에 읽을 문장 수 상한 (요금 · 시간 보호)
FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "NotoSansKR.ttf")
BRAND = "로지에듀"
TEACHER = "최준용 국어"

DEFAULT_TTS_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]
DEFAULT_TTS_VOICE = "Charon"
DEFAULT_TTS_STYLE = "Read this aloud in natural Korean, in a calm, clear and friendly teacher's voice:"
TTS_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# 색
BG_TOP, BG_BOTTOM = (22, 26, 41), (9, 11, 18)
CARD = (31, 36, 54)
CARD_FOCUS = (44, 50, 74)
TEXT = (240, 242, 248)
SOFT = (196, 200, 214)
DIM = (118, 124, 145)
ACCENT = (250, 204, 21)
HILITE_BG = (128, 98, 10)
HILITE_TEXT = (255, 244, 200)
GOOD = (110, 231, 150)
BAD = (248, 113, 113)
BAD_SOFT = (252, 170, 170)
BRAND_COLOR = (196, 176, 255)
TRACK = (44, 49, 68)

# 화면 칸
CONTENT_TOP = 250
SUB_TOP, SUB_BOTTOM = 1480, 1780       # 아래 자막 상자
CONTENT_BOTTOM = SUB_TOP - 50
MARGIN = 80

OPTION_MARKERS = "①②③④⑤"


class TTSError(Exception):
    pass


class VideoResult:
    def __init__(self, video: bytes, voice: str, seconds: float):
        self.video = video
        self.voice = voice          # "gemini" / "gtts" / "custom"
        self.seconds = seconds


# ─────────────────────────────────────────────────────────
# 목소리
# ─────────────────────────────────────────────────────────
def _api_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""
    return key.strip().replace('"', "").replace("'", "")


def _tts_models() -> list:
    raw = os.environ.get("VIDEO_TTS_MODEL", "")
    models = [m.strip() for m in raw.split(",") if m.strip()]
    return models or list(DEFAULT_TTS_MODELS)


def speech_text(text: str) -> str:
    """화면에 보이는 글을 소리 내어 읽기 좋게 바꾼다. ③ → '3번', 마크다운 기호 제거."""
    out = text
    for i, mk in enumerate(OPTION_MARKERS, start=1):
        out = out.replace(mk, f" {i}번 ")
    out = re.sub(r"[*#`>_~|]", " ", out)
    return re.sub(r"\s+", " ", out).strip()


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        path = shutil.which("ffmpeg")
        if not path:
            raise RuntimeError("ffmpeg 를 찾지 못했습니다.")
        return path


def _run(args: list, data: bytes = None) -> bytes:
    r = subprocess.run(args, input=data, capture_output=True)
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(err[-1500:] or "ffmpeg 처리 중 알 수 없는 오류")
    return r.stdout


def _to_pcm(args_in: list, data: bytes = None) -> bytes:
    """ffmpeg 로 아무 소리나 → 16비트 · 1채널 · 24kHz 날 PCM."""
    return _run([_ffmpeg(), "-v", "error", *args_in,
                 "-f", "s16le", "-acodec", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-"], data)


def pcm_from_gemini_response(data: dict) -> bytes:
    """Gemini 답에서 소리 부분만 꺼내 24kHz PCM 으로 돌려준다. 소리가 없으면 b""."""
    chunks = []
    rate = SAMPLE_RATE
    for cand in (data or {}).get("candidates") or []:
        for part in ((cand.get("content") or {}).get("parts") or []):
            inline = part.get("inlineData") or part.get("inline_data") or {}
            if not inline.get("data"):
                continue
            chunks.append(base64.b64decode(inline["data"]))
            mime = inline.get("mimeType") or inline.get("mime_type") or ""
            m = re.search(r"rate=(\d+)", mime)
            if m:
                rate = int(m.group(1))
        if chunks:
            break
    raw = b"".join(chunks)
    if raw and rate != SAMPLE_RATE:
        raw = _to_pcm(["-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "-"], raw)
    return raw


def gemini_tts(text: str) -> bytes:
    key = _api_key()
    if not key:
        raise TTSError("구글 API 키가 설정되지 않았습니다.")
    style = os.environ.get("VIDEO_TTS_STYLE", DEFAULT_TTS_STYLE).strip()
    voice = os.environ.get("VIDEO_TTS_VOICE", DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE
    body = {
        "contents": [{"parts": [{"text": f"{style} {text}" if style else text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    last = ""
    for model in _tts_models():
        for attempt in range(4):
            try:
                r = requests.post(TTS_URL.format(model=model), json=body, timeout=120,
                                  headers={"x-goog-api-key": key})
            except requests.RequestException as e:
                last = str(e)
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 404:
                last = f"{model}: 모델을 찾지 못함"
                break                                   # 다음 모델로
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"{model}: {r.status_code} {r.text[:200]}"
                time.sleep(min(30, 3 * 2 ** attempt))   # 잠깐 쉬었다 다시
                continue
            if r.status_code != 200:
                last = f"{model}: {r.status_code} {r.text[:300]}"
                break
            pcm = pcm_from_gemini_response(r.json())
            if pcm:
                return pcm
            last = f"{model}: 소리가 비어 있음"
    raise TTSError(last or "음성 생성 실패")


def gtts_tts(text: str) -> bytes:
    from gtts import gTTS
    with tempfile.TemporaryDirectory(prefix="tts_") as d:
        mp3 = os.path.join(d, "a.mp3")
        gTTS(text, lang="ko").save(mp3)
        return _to_pcm(["-i", mp3])


def _voice_all(texts: list, tts=None):
    """문장들을 모두 소리로 바꾼다. 돌려주는 값: (PCM 목록, 쓴 목소리 이름).
    💡 Gemini 가 한 문장이라도 실패하면 전부 gTTS 로 다시 만든다 — 한 영상 안에서
       목소리가 바뀌면 듣기 어색하기 때문."""
    spoken = [speech_text(t) or "." for t in texts]
    if not spoken:
        return [], "none"
    if tts is not None:
        return [tts(t) for t in spoken], "custom"
    try:
        with ThreadPoolExecutor(max_workers=3) as ex:
            return list(ex.map(gemini_tts, spoken)), "gemini"
    except Exception as e:
        print(f"[해설영상] Gemini 음성 실패 → gTTS 로 대신합니다: {e}")
    with ThreadPoolExecutor(max_workers=3) as ex:
        return list(ex.map(gtts_tts, spoken)), "gtts"


def _silence(sec: float) -> bytes:
    return b"\x00\x00" * int(round(sec * SAMPLE_RATE))


def _pcm_seconds(pcm: bytes) -> float:
    return len(pcm) / (2 * SAMPLE_RATE)


# ─────────────────────────────────────────────────────────
# 글자 · 그리기 도구
# ─────────────────────────────────────────────────────────
_font_cache = {}


def font(size: int, bold: bool = False):
    key = (size, bold)
    f = _font_cache.get(key)
    if f is None:
        f = ImageFont.truetype(FONT_PATH, size)
        if bold:
            try:
                f.set_variation_by_axes([700])
            except Exception:
                pass
        _font_cache[key] = f
    return f


def wrap(text: str, fnt, max_w: float) -> list:
    """어절 단위로 줄을 나누고, 한 어절이 너무 길면 글자 단위로 자른다.
    돌려주는 값: [(줄 글자, 원문에서 그 줄이 시작하는 위치), ...]
    — 위치를 같이 들고 다녀야 자막 색 채우기와 형광펜을 줄마다 정확히 그릴 수 있다."""
    measure = fnt.getlength
    out = []
    pos = 0
    for para in text.split("\n"):
        cur, line_start = "", pos
        for m in re.finditer(r"\S+\s*|\s+", para):
            tok, tok_start = m.group(0), pos + m.start()
            if not cur:
                line_start = tok_start
            if measure((cur + tok).rstrip()) <= max_w:
                cur += tok
                continue
            if cur.strip():
                out.append((cur.rstrip(), line_start))
            cur, line_start = "", tok_start
            if measure(tok.rstrip()) <= max_w:
                cur = tok
                continue
            piece, piece_start = "", tok_start
            for j, ch in enumerate(tok):
                if piece and measure(piece + ch) > max_w:
                    out.append((piece, piece_start))
                    piece, piece_start = "", tok_start + j
                piece += ch
            cur, line_start = piece, piece_start
        out.append((cur.rstrip(), line_start))
        pos += len(para) + 1
    return out


def fit_wrap(text: str, max_w: float, max_h: float, sizes, bold=False, spacing=1.45):
    """정해진 칸에 다 들어가는 가장 큰 글자 크기를 고른다."""
    for size in sizes:
        f = font(size, bold)
        lines = wrap(text, f, max_w)
        if len(lines) * size * spacing <= max_h:
            return f, lines, int(size * spacing)
    f = font(sizes[-1], bold)
    lines = wrap(text, f, max_w)
    keep = max(1, int(max_h // (sizes[-1] * spacing)))
    return f, lines[:keep], int(sizes[-1] * spacing)


def draw_lines(d, lines, fnt, x, y, line_h, fill, *, spoken=None, spoken_fill=TEXT,
               highlight=None, hi_bg=HILITE_BG, hi_fill=HILITE_TEXT, center_w=None):
    """여러 줄을 그린다.
    spoken: 원문 기준 앞에서부터 이만큼은 '읽은 글자'로 밝게 (자막 색 채우기)
    highlight: (시작, 끝) 원문 기준 형광펜 범위
    center_w: 주면 그 폭 안에서 가운데 맞춤"""
    for txt, start in lines:
        lx = x
        if center_w is not None:
            lx = x + (center_w - fnt.getlength(txt)) / 2
        cuts = {0, len(txt)}
        for c in ([spoken] if spoken is not None else []) + (list(highlight) if highlight else []):
            if c is not None and 0 < c - start < len(txt):
                cuts.add(c - start)
        cuts = sorted(cuts)
        segs = []
        for a, b in zip(cuts, cuts[1:]):
            gi = start + a
            hi = bool(highlight and highlight[0] <= gi < highlight[1])
            color = fill
            if spoken is not None and gi < spoken:
                color = spoken_fill
            if hi:
                color = hi_fill
            segs.append((a, b, color, hi))
        for a, b, _, hi in segs:
            if hi:
                x0 = lx + fnt.getlength(txt[:a])
                x1 = lx + fnt.getlength(txt[:b])
                d.rounded_rectangle([x0 - 3, y - 2, x1 + 3, y + fnt.size * 1.3], radius=6, fill=hi_bg)
        for a, b, color, _ in segs:
            d.text((lx + fnt.getlength(txt[:a]), y), txt[a:b], font=fnt, fill=color)
        y += line_h
    return y


def lerp(c1, c2, a: float):
    a = max(0.0, min(1.0, a))
    return tuple(int(round(p + (q - p) * a)) for p, q in zip(c1, c2))


def quant(x: float, steps: int) -> int:
    """0~1 사이 진행도를 몇 단계로 끊는다. 단계가 같으면 같은 그림을 다시 쓴다."""
    return max(0, min(steps, int(x * steps)))


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


_bg_cache = {}


def background(chip: str) -> Image.Image:
    """그라데이션 바탕 + 맨 위 상표 + 오른쪽 위 꼬리표(문항 번호 · 제목)."""
    if chip in _bg_cache:
        return _bg_cache[chip].copy()
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for yy in range(H):
        d.line([(0, yy), (W, yy)], fill=lerp(BG_TOP, BG_BOTTOM, yy / H))
    d.text((MARGIN, 92), BRAND, font=font(36, True), fill=BRAND_COLOR)
    d.text((MARGIN + font(36, True).getlength(BRAND) + 18, 96), TEACHER, font=font(32), fill=DIM)
    if chip:
        cf = font(30, True)
        chip_txt = chip if cf.getlength(chip) < 420 else chip[:14] + "…"
        cw = cf.getlength(chip_txt)
        d.rounded_rectangle([W - MARGIN - cw - 40, 86, W - MARGIN, 142], radius=28, outline=ACCENT, width=3)
        d.text((W - MARGIN - cw - 20, 92), chip_txt, font=cf, fill=ACCENT)
    if len(_bg_cache) > 8:
        _bg_cache.clear()
    _bg_cache[chip] = img.copy()
    return img


def draw_progress(img: Image.Image, frac: float):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([MARGIN, 40, W - MARGIN, 50], radius=5, fill=TRACK)
    x1 = MARGIN + (W - 2 * MARGIN) * max(0.0, min(1.0, frac))
    if x1 > MARGIN + 10:
        d.rounded_rectangle([MARGIN, 40, x1, 50], radius=5, fill=ACCENT)


def draw_badge(d, label: str, y: int = CONTENT_TOP - 70):
    d.rounded_rectangle([MARGIN, y + 8, MARGIN + 14, y + 44], radius=4, fill=ACCENT)
    d.text((MARGIN + 30, y), label, font=font(40, True), fill=ACCENT)


def draw_subtitle(d, text: str, spoken: int):
    """아래 자막 상자. 읽은 글자까지 하얗게 차오른다."""
    if not text:
        return
    d.rounded_rectangle([MARGIN - 20, SUB_TOP, W - MARGIN + 20, SUB_BOTTOM], radius=36, fill=CARD)
    inner_w = W - 2 * MARGIN - 20
    fnt, lines, lh = fit_wrap(text, inner_w, SUB_BOTTOM - SUB_TOP - 60, (46, 42, 38, 34, 30), bold=True, spacing=1.42)
    y = SUB_TOP + (SUB_BOTTOM - SUB_TOP - lh * len(lines)) / 2 + 4
    draw_lines(d, lines, fnt, MARGIN - 10, y, lh, DIM, spoken=spoken, spoken_fill=TEXT, center_w=inner_w + 20)


# ─────────────────────────────────────────────────────────
# 장면
# ─────────────────────────────────────────────────────────
class Scene:
    """한 장면. lines 는 이 장면에서 읽을 문장들(없으면 fixed 초 동안 조용히 보여준다)."""
    subtitles = True
    fade = True

    def __init__(self, lines=None, fixed: float = 0.0):
        self.lines = [s for s in (lines or []) if s.strip()][:MAX_LINES]
        self.fixed = fixed
        self.times = []        # [(시작, 길이), ...] 문장마다 — 장면 안 기준 초
        self.duration = fixed

    def setup(self, times: list, duration: float):
        self.times = times
        self.duration = duration
        self.prepare()

    def prepare(self):
        pass

    def current(self, t: float):
        """지금 읽는 문장 번호와, 그 문장에서 몇 글자째까지 읽었는지."""
        idx = -1
        for i, (st, _) in enumerate(self.times):
            if t >= st:
                idx = i
        if idx < 0:
            return -1, 0
        st, dur = self.times[idx]
        p = (t - st) / dur if dur > 0 else 1
        return idx, int(round(len(self.lines[idx]) * max(0.0, min(1.0, p))))

    def line_start(self, i: int) -> float:
        return self.times[i][0] if 0 <= i < len(self.times) else 0.0

    def state(self, t: float):
        return ()

    def draw(self, img: Image.Image, st, t: float):
        pass

    def frame_key(self, t: float):
        """이 순간 화면을 결정하는 값들. 앞 프레임과 같으면 그림을 새로 그리지 않는다."""
        cur = self.current(t) if self.subtitles else (-1, 0)
        return (self.state(t), cur)

    def paint(self, base: Image.Image, key, t: float) -> Image.Image:
        st, (idx, spoken) = key
        img = base
        self.draw(img, st, t)
        if self.subtitles and idx >= 0:
            draw_subtitle(ImageDraw.Draw(img), self.lines[idx], spoken)
        return img


class IntroScene(Scene):
    """상표가 떠오르고, 둘째 문장에서 'N번 문항 해설' 딱지가 튀어나온다."""
    def __init__(self, lines, pill: str, fixed: float = 0.0):
        super().__init__(lines, fixed)
        self.pill = pill

    def state(self, t):
        a = quant(t / 0.7, 14)
        b = quant((t - 0.3) / 0.7, 14)
        pill_at = self.line_start(1) if len(self.times) > 1 else (0.6 if not self.lines else self.line_start(0) + 0.6)
        c = quant((t - pill_at) / 0.35, 7) if t >= pill_at else -1
        return (a, b, c)

    def draw(self, img, st, t):
        a, b, c = st
        d = ImageDraw.Draw(img)
        cy = 700
        ea, eb = ease(a / 14), ease(b / 14)
        bf, tf = font(132, True), font(60, True)
        d.text(((W - bf.getlength(BRAND)) / 2, cy - 160 + (1 - ea) * 60), BRAND, font=bf,
               fill=lerp(BG_TOP, TEXT, ea))
        d.text(((W - tf.getlength(TEACHER)) / 2, cy + 30 + (1 - eb) * 50), TEACHER, font=tf,
               fill=lerp(BG_TOP, BRAND_COLOR, eb))
        half = 160 * eb
        if half > 2:
            d.rounded_rectangle([W / 2 - half, cy + 140, W / 2 + half, cy + 150], radius=5, fill=ACCENT)
        if c >= 0 and self.pill:
            k = c / 7
            scale = 0.6 + 0.4 * ease(k) + 0.08 * (1 - abs(2 * k - 1)) if k < 1 else 1.0
            pf = font(max(20, int(58 * scale)), True)
            pw = pf.getlength(self.pill)
            ph = pf.size * 1.7
            py = cy + 300
            d.rounded_rectangle([W / 2 - pw / 2 - 44, py, W / 2 + pw / 2 + 44, py + ph], radius=int(ph / 2), fill=ACCENT)
            d.text((W / 2 - pw / 2, py + ph * 0.18), self.pill, font=pf, fill=BG_BOTTOM)


class PassageScene(Scene):
    """지문 발췌를 보여주고, 근거 문장에 형광펜을 왼쪽부터 쭉 긋는다."""
    SWEEP = 28

    def __init__(self, lines, excerpt: str, span):
        super().__init__(lines)
        self.excerpt = excerpt
        self.span = span

    def prepare(self):
        self.box = (MARGIN - 20, CONTENT_TOP, W - MARGIN + 20, CONTENT_BOTTOM)
        self.fnt, self.wrapped, self.lh = fit_wrap(
            self.excerpt, W - 2 * MARGIN - 40, CONTENT_BOTTOM - CONTENT_TOP - 100,
            (48, 46, 44, 42, 40, 38, 36, 34, 32, 30))
        # 형광펜은 첫 문장을 읽기 시작하고 조금 뒤에 긋는다
        self.sweep_from = 0.6
        self.sweep_len = 1.6

    def state(self, t):
        if not self.span:
            return (0,)
        return (quant((t - self.sweep_from) / self.sweep_len, self.SWEEP),)

    def draw(self, img, st, t):
        d = ImageDraw.Draw(img)
        draw_badge(d, "지문 근거")
        d.rounded_rectangle(self.box, radius=32, fill=CARD)
        hi = None
        if self.span and st[0] > 0:
            a, b = self.span
            hi = (a, a + int(round((b - a) * st[0] / self.SWEEP)))
        text_h = self.lh * len(self.wrapped)
        y = CONTENT_TOP + max(50, (CONTENT_BOTTOM - CONTENT_TOP - text_h) / 2)
        draw_lines(d, self.wrapped, self.fnt, MARGIN + 10, y, self.lh, SOFT, highlight=hi)


_OPT_REF_RES = [re.compile(rf"(?:{OPTION_MARKERS[i - 1]}|(?<![\d.]){i}\s*번(?!\s*(?:문항|문제)))") for i in range(1, 6)]


def option_refs(line: str) -> list:
    """해설 문장이 몇 번 선지를 말하는지. '③은', '3번 선지는' 둘 다 잡는다."""
    return [i for i in range(1, 6) if _OPT_REF_RES[i - 1].search(line)]


class OptionsScene(Scene):
    """선지 5개. 해설이 그 선지를 말하는 순간 O / X 가 찍히고 이유가 나타난다."""
    POP = 6

    def __init__(self, lines, stem: str, options: list, correct: int, reasons: dict):
        super().__init__(lines)
        self.stem = stem
        self.options = [re.sub(rf"^[{OPTION_MARKERS}]\s*", "", o).strip() for o in options]
        self.correct = correct
        self.reasons = {int(k): v for k, v in (reasons or {}).items() if str(k).isdigit() and v}

    def prepare(self):
        n = len(self.options)
        reveal = {}
        for li, line in enumerate(self.lines):
            for o in option_refs(line):
                if o <= n and o not in reveal:
                    reveal[o] = self.line_start(li) + 0.2
        dur = self.duration or 1.0
        if self.correct and self.correct not in reveal:
            reveal[self.correct] = min(dur * 0.1, 1.0)
        rest = [o for o in range(1, n + 1) if o not in reveal]
        for k, o in enumerate(rest):
            reveal[o] = dur * (0.3 + 0.6 * (k / max(1, len(rest))))
        self.reveal = reveal

        # 글자 크기: 이유 줄 자리까지 미리 비워 둔 상태로 칸에 들어가는 가장 큰 크기
        avail = CONTENT_BOTTOM - CONTENT_TOP - 10
        for size in (42, 40, 38, 36, 34, 32, 30, 28):
            layout = self._layout(size)
            if layout[-1] <= avail:
                break
        self.rows = layout[0]          # self._fonts 도 이 크기로 맞춰져 있다

    def _layout(self, size):
        of, rf, sf = font(size, True), font(int(size * 0.76)), font(int(size * 0.86))
        text_x = MARGIN + int(size * 1.6)
        y = 0
        stem_lines = wrap(self.stem, sf, W - 2 * MARGIN) if self.stem else []
        stem_h = len(stem_lines) * int(sf.size * 1.4) + (24 if stem_lines else 0)
        y += stem_h
        rows = []
        for i, opt in enumerate(self.options, start=1):
            ol = wrap(opt, of, W - MARGIN - text_x)
            reason = self.reasons.get(i) if i != self.correct else ""
            rl = wrap(f"→ {reason}", rf, W - MARGIN - text_x - 20) if reason else []
            h = len(ol) * int(of.size * 1.38) + len(rl) * int(rf.size * 1.4) + 22
            rows.append((i, y, h, ol, rl))
            y += h + 8
        self._fonts = (of, rf, sf, text_x, stem_lines)
        return rows, stem_h, y

    def state(self, t):
        pops = tuple(quant((t - self.reveal[i]) / 0.3, self.POP) if t >= self.reveal[i] else -1
                     for i in range(1, len(self.options) + 1))
        shown = [(self.reveal[i], i) for i in range(1, len(self.options) + 1) if t >= self.reveal[i]]
        focus = max(shown)[1] if shown else 0
        return pops + (focus,)

    def draw(self, img, st, t):
        d = ImageDraw.Draw(img)
        draw_badge(d, "선택지 분석")
        of, rf, sf, text_x, stem_lines = self._fonts
        top = CONTENT_TOP
        y = top
        for line, _ in stem_lines:
            d.text((MARGIN, y), line, font=sf, fill=SOFT)
            y += int(sf.size * 1.4)
        focus = st[-1]
        for i, ry, h, ol, rl in self.rows:
            y0 = top + ry
            pop = st[i - 1]
            shown = pop >= 0
            is_ok = i == self.correct
            color = (GOOD if is_ok else BAD) if shown else DIM
            if shown and i == focus:
                d.rounded_rectangle([MARGIN - 24, y0 - 12, W - MARGIN + 24, y0 + h - 6], radius=22, fill=CARD_FOCUS)
            # 동그라미 표시 — 체크/엑스는 글꼴에 없어 직접 그린다
            r = of.size * 0.48
            if shown:
                k = pop / self.POP
                r *= 0.5 + 0.5 * ease(k) + 0.15 * (1 - abs(2 * k - 1)) if k < 1 else 1.0
            cx, cy = MARGIN + of.size * 0.55, y0 + of.size * 0.68
            if shown:
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
                w = max(3, int(r * 0.22))
                if is_ok:
                    d.line([cx - r * .5, cy + r * .02, cx - r * .12, cy + r * .42, cx + r * .55, cy - r * .4],
                           fill=BG_BOTTOM, width=w, joint="curve")
                else:
                    d.line([cx - r * .42, cy - r * .42, cx + r * .42, cy + r * .42], fill=BG_BOTTOM, width=w)
                    d.line([cx - r * .42, cy + r * .42, cx + r * .42, cy - r * .42], fill=BG_BOTTOM, width=w)
            else:
                d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=DIM, width=3)
                nf = font(int(of.size * 0.62), True)
                num = str(i)
                d.text((cx - nf.getlength(num) / 2, cy - nf.size * 0.72), num, font=nf, fill=DIM)
            yy = y0
            txt_color = TEXT if (shown and is_ok) else (SOFT if shown else DIM)
            for line, _ in ol:
                d.text((text_x, yy), line, font=of, fill=txt_color)
                yy += int(of.size * 1.38)
            if shown and rl:
                for line, _ in rl:
                    d.text((text_x + 20, yy), line, font=rf, fill=BAD_SOFT)
                    yy += int(rf.size * 1.4)


class CaptionScene(Scene):
    """일반 해설: 지금 읽는 문장을 크게, 바로 앞 문장은 위에 흐리게."""
    subtitles = False

    def state(self, t):
        idx, spoken = self.current(t)
        enter = quant((t - self.line_start(idx)) / 0.35, 7) if idx >= 0 else 0
        return (idx, spoken, enter)

    def draw(self, img, st, t):
        idx, spoken, enter = st
        if idx < 0:
            return
        d = ImageDraw.Draw(img)
        n = len(self.lines)
        draw_badge(d, f"{idx + 1} / {n}")
        e = ease(enter / 7)
        inner = W - 2 * MARGIN
        cur_f, cur_l, cur_lh = fit_wrap(self.lines[idx], inner, 900, (66, 62, 58, 54, 50, 46, 42), bold=True)
        block_h = cur_lh * len(cur_l)
        y = 900 - block_h / 2 + (1 - e) * 60
        if idx > 0:
            pf, pl, plh = fit_wrap(self.lines[idx - 1], inner, 420, (40, 36, 32))
            py = max(CONTENT_TOP + 20, y - 80 - plh * len(pl))
            draw_lines(d, pl, pf, MARGIN, py, plh, lerp(SOFT, DIM, e), center_w=inner)
        draw_lines(d, cur_l, cur_f, MARGIN, y, cur_lh, lerp(BG_TOP, DIM, e),
                   spoken=spoken, spoken_fill=lerp(BG_TOP, TEXT, e), center_w=inner)


class OutroScene(Scene):
    subtitles = False

    def draw(self, img, st, t):
        d = ImageDraw.Draw(img)
        bf, tf = font(110, True), font(54, True)
        d.text(((W - bf.getlength(BRAND)) / 2, 760), BRAND, font=bf, fill=TEXT)
        d.text(((W - tf.getlength(TEACHER)) / 2, 920), TEACHER, font=tf, fill=BRAND_COLOR)


# ─────────────────────────────────────────────────────────
# 장면들 → 영상
# ─────────────────────────────────────────────────────────
FADE_STEPS = 8
FADE_SEC = 0.3


def build_video(scenes: list, chip: str = "", tts=None) -> VideoResult:
    """장면 목록을 받아 mp4 를 만든다. (블로킹 — asyncio.to_thread 로 부를 것)"""
    texts = [ln for sc in scenes for ln in sc.lines]
    pcms, voice = _voice_all(texts, tts)

    audio = bytearray()
    starts = []
    k = 0
    for sc in scenes:
        starts.append(_pcm_seconds(audio))
        times, local = [], 0.0
        for _ in sc.lines:
            pcm = pcms[k]
            k += 1
            dur = _pcm_seconds(pcm)
            times.append((local, dur))
            audio += pcm + _silence(LINE_PAUSE)
            local += dur + LINE_PAUSE
        if not sc.lines:
            audio += _silence(sc.fixed)
            local = sc.fixed
        sc.setup(times, local)
    total = _pcm_seconds(audio)
    total_frames = max(1, int(round(total * FPS)))
    scene_frames = [int(round(s * FPS)) for s in starts] + [total_frames]

    with tempfile.TemporaryDirectory(prefix="explain_video_") as work:
        wav_path = os.path.join(work, "audio.wav")
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(bytes(audio))

        entries = []          # [그림 파일, 프레임 수]
        prev_key = None
        prev_last = None       # 앞 장면의 마지막 그림 (넘어갈 때 섞는 용)
        last_img = None
        for si, sc in enumerate(scenes):
            f0, f1 = scene_frames[si], scene_frames[si + 1]
            for fi in range(f0, f1):
                t = (fi - f0) / FPS
                fade = quant(t / FADE_SEC, FADE_STEPS) if (sc.fade and prev_last is not None) else FADE_STEPS
                key = (si, sc.frame_key(t), fade, quant(fi / total_frames, 240))
                if key == prev_key:
                    entries[-1][1] += 1
                    continue
                img = sc.paint(background(chip), key[1], t)
                if fade < FADE_STEPS:
                    img = Image.blend(prev_last, img, ease(fade / FADE_STEPS))
                draw_progress(img, fi / total_frames)
                path = os.path.join(work, f"f{len(entries):05d}.jpg")
                img.save(path, quality=92)
                entries.append([path, 1])
                prev_key = key
                last_img = img
            if last_img is not None:
                prev_last = last_img

        list_path = os.path.join(work, "frames.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            f.write("ffconcat version 1.0\n")
            for path, n in entries:
                f.write(f"file '{path}'\nduration {n / FPS:.6f}\n")
            f.write(f"file '{entries[-1][0]}'\n")   # 마지막 그림 길이가 무시되지 않게 한 번 더

        out_path = os.path.join(work, "final.mp4")
        _run([_ffmpeg(), "-y", "-v", "error",
              "-f", "concat", "-safe", "0", "-i", list_path, "-i", wav_path,
              "-map", "0:v", "-map", "1:a",
              "-vf", f"fps={FPS},format=yuv420p",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
              "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", out_path])
        with open(out_path, "rb") as f:
            return VideoResult(f.read(), voice, total)


def render_question_video(question_no: int, excerpt: str, span, stem: str, options: list,
                          correct: int, wrong_reasons: dict, passage_lines: list, option_lines: list,
                          tts=None) -> VideoResult:
    """문항 하나: 인트로 → 지문 근거(형광펜) → 선택지 분석(O/X) → 끝 화면."""
    scenes = [IntroScene([f"안녕하세요. {BRAND} {TEACHER}입니다.", f"{question_no}번 문항 해설입니다."],
                         pill=f"{question_no}번 문항 해설")]
    scenes.append(PassageScene(passage_lines or ["지문에서 근거를 먼저 확인해봅시다."], excerpt, span))
    if options:
        scenes.append(OptionsScene(option_lines or ["선택지를 하나씩 살펴보겠습니다."],
                                   stem, options, correct, wrong_reasons))
    elif option_lines:
        scenes.append(CaptionScene(option_lines))
    scenes.append(OutroScene(fixed=1.5))
    return build_video(scenes, chip=f"{question_no}번", tts=tts)


def render_caption_video(lines: list, title: str = "", tts=None) -> VideoResult:
    """일반 해설: (제목 화면) → 문장마다 크게 → 끝 화면."""
    scenes = []
    if title:
        scenes.append(IntroScene([], pill=title[:20], fixed=1.8))
    scenes.append(CaptionScene(lines))
    scenes.append(OutroScene(fixed=1.5))
    return build_video(scenes, chip=title[:14] if title else "", tts=tts)
