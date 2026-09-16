import io
import os
import re
import json
import time
import uuid
import random
import requests
import threading
import mimetypes
import urllib.parse
import asyncio
from collections import defaultdict
from fastapi import (
    FastAPI, HTTPException, UploadFile, File, Form, WebSocket,
    WebSocketDisconnect, Response, Request, Header, Depends
)
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import firebase_admin
from firebase_admin import credentials, firestore, storage
import google.generativeai as genai
from datetime import datetime
import fitz

# ─────────────────────────────────────────────────────────
# 디렉토리 생성
# ─────────────────────────────────────────────────────────
for folder in ["exams", "homeworks", "board", "chat", "profiles"]:
    os.makedirs(f"uploads/{folder}", exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Global Error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "detail": "서버 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."},
        headers={"Access-Control-Allow-Origin": "*"},
    )


XP_REWARD_LOGIN = 20
XP_REWARD_HOMEWORK = 60
XP_REWARD_ESSAY = 70
XP_REWARD_PROFILE = 80
XP_REWARD_CHAT = 8
XP_REWARD_CHAT_DAILY_MAX_COUNT = 5  # 하루 최대 5회까지만 질문 포인트 인정
XP_REWARD_QUIZ_BASE = 30
XP_REWARD_EXAM_BASE = 50

# ─────────────────────────────────────────────────────────
# 🌱 성장 레벨 시스템 ("씨앗의 여정") — 학생 xp 누적치로 10단계 레벨 계산
# ─────────────────────────────────────────────────────────
LEVELS = [
    {"level": 1, "name": "씨앗", "icon": "🌰", "threshold": 0, "unlock_item": None},
    {"level": 2, "name": "새싹", "icon": "🌱", "threshold": 300, "unlock_item": {"id": "sprout", "emoji": "🌱", "label": "새싹 배지"}},
    {"level": 3, "name": "떡잎", "icon": "🌿", "threshold": 700, "unlock_item": {"id": "clover", "emoji": "🍀", "label": "네잎클로버"}},
    {"level": 4, "name": "줄기", "icon": "🪴", "threshold": 1200, "unlock_item": {"id": "bamboo", "emoji": "🎍", "label": "대나무 장식"}},
    {"level": 5, "name": "봉오리", "icon": "🌸", "threshold": 1800, "unlock_item": {"id": "flowerpin", "emoji": "🌸", "label": "꽃 머리핀"}},
    {"level": 6, "name": "꽃", "icon": "🌼", "threshold": 2600, "unlock_item": {"id": "wreath", "emoji": "🌻", "label": "화관"}},
    {"level": 7, "name": "열매", "icon": "🍏", "threshold": 3600, "unlock_item": {"id": "grapes", "emoji": "🍇", "label": "열매 목걸이"}},
    {"level": 8, "name": "잘 익은 열매", "icon": "🍎", "threshold": 4800, "unlock_item": {"id": "crown", "emoji": "👑", "label": "작은 왕관"}},
    {"level": 9, "name": "빛나는 열매", "icon": "🍎", "threshold": 6400, "unlock_item": {"id": "sparkle", "emoji": "✨", "label": "반짝이는 오라"}},
    {"level": 10, "name": "황금 열매", "icon": "🏆", "threshold": 8400, "unlock_item": {"id": "trophy", "emoji": "🏆", "label": "황금 트로피"}},
]


# ── 아바타 꾸미기 ──────────────────────────────────────
#   레벨마다 배지 하나씩만 주던 것을 여러 갈래로 늘렸다.
#   갈래(slot)마다 따로 고를 수 있어 조합이 많아진다.
#   level은 그 항목이 열리는 레벨. 1이면 처음부터 쓸 수 있다.
AVATAR_SLOTS = [
    {"key": "face",   "name": "캐릭터",  "icon": "🙂"},
    {"key": "color",  "name": "색깔",    "icon": "🎨"},
    {"key": "hat",    "name": "머리",    "icon": "🎩"},
    {"key": "pet",    "name": "친구",    "icon": "🐾"},
    {"key": "badge",  "name": "배지",    "icon": "🏅"},
    {"key": "effect", "name": "효과",    "icon": "✨"},
]

# 내 사진을 아바타로 쓸 수 있게 되는 레벨
PHOTO_UNLOCK_LEVEL = 3

AVATAR_ITEMS = {
    "face": [
        {"id": "boy",      "emoji": "👦", "label": "남학생",   "level": 1},
        {"id": "girl",     "emoji": "👧", "label": "여학생",   "level": 1},
        {"id": "student",  "emoji": "🧑‍🎓", "label": "졸업생",  "level": 2},
        {"id": "nerd",     "emoji": "🤓", "label": "안경",     "level": 2},
        {"id": "cool",     "emoji": "😎", "label": "선글라스", "level": 4},
        {"id": "star",     "emoji": "🤩", "label": "반짝눈",   "level": 5},
        {"id": "ninja",    "emoji": "🥷", "label": "닌자",     "level": 6},
        {"id": "wizard",   "emoji": "🧙", "label": "마법사",   "level": 7},
        {"id": "astro",    "emoji": "🧑‍🚀", "label": "우주인",  "level": 8},
        {"id": "hero",     "emoji": "🦸", "label": "영웅",     "level": 9},
        {"id": "dragon",   "emoji": "🐉", "label": "용",       "level": 10},
    ],
    "color": [
        {"id": "blue",    "label": "바다",     "css": "linear-gradient(135deg,#1e3a8a,#2563eb)", "ring": "#3b82f6", "level": 1},
        {"id": "green",   "label": "새싹",     "css": "linear-gradient(135deg,#14532d,#16a34a)", "ring": "#22c55e", "level": 1},
        {"id": "pink",    "label": "벚꽃",     "css": "linear-gradient(135deg,#831843,#db2777)", "ring": "#ec4899", "level": 2},
        {"id": "purple",  "label": "포도",     "css": "linear-gradient(135deg,#4c1d95,#7c3aed)", "ring": "#8b5cf6", "level": 3},
        {"id": "orange",  "label": "노을",     "css": "linear-gradient(135deg,#7c2d12,#ea580c)", "ring": "#f97316", "level": 4},
        {"id": "teal",    "label": "민트",     "css": "linear-gradient(135deg,#134e4a,#0d9488)", "ring": "#14b8a6", "level": 5},
        {"id": "red",     "label": "불꽃",     "css": "linear-gradient(135deg,#7f1d1d,#dc2626)", "ring": "#ef4444", "level": 6},
        {"id": "night",   "label": "밤하늘",   "css": "linear-gradient(135deg,#0f172a,#334155)", "ring": "#64748b", "level": 7},
        {"id": "candy",   "label": "솜사탕",   "css": "linear-gradient(135deg,#db2777,#38bdf8)", "ring": "#f472b6", "level": 8},
        {"id": "aurora",  "label": "오로라",   "css": "linear-gradient(135deg,#059669,#7c3aed,#0ea5e9)", "ring": "#a78bfa", "level": 9},
        {"id": "gold",    "label": "황금",     "css": "linear-gradient(135deg,#78350f,#f59e0b,#fde68a)", "ring": "#fbbf24", "level": 10},
    ],
    "hat": [
        {"id": "none",     "emoji": "",   "label": "없음",       "level": 1},
        {"id": "cap",      "emoji": "🧢", "label": "야구모자",   "level": 3},
        {"id": "ribbon",   "emoji": "🎀", "label": "리본",       "level": 4},
        {"id": "headband", "emoji": "🎧", "label": "헤드폰",     "level": 5},
        {"id": "gradcap",  "emoji": "🎓", "label": "학사모",     "level": 6},
        {"id": "tophat",   "emoji": "🎩", "label": "중절모",     "level": 7},
        {"id": "crown",    "emoji": "👑", "label": "왕관",       "level": 8},
        {"id": "halo",     "emoji": "😇", "label": "천사 고리",  "level": 10},
    ],
    "pet": [
        {"id": "none",   "emoji": "",   "label": "없음",     "level": 1},
        {"id": "chick",  "emoji": "🐣", "label": "병아리",   "level": 3},
        {"id": "cat",    "emoji": "🐱", "label": "고양이",   "level": 4},
        {"id": "dog",    "emoji": "🐶", "label": "강아지",   "level": 5},
        {"id": "rabbit", "emoji": "🐰", "label": "토끼",     "level": 6},
        {"id": "fox",    "emoji": "🦊", "label": "여우",     "level": 7},
        {"id": "owl",    "emoji": "🦉", "label": "부엉이",   "level": 8},
        {"id": "unicorn","emoji": "🦄", "label": "유니콘",   "level": 9},
        {"id": "phoenix","emoji": "🔥", "label": "불사조",   "level": 10},
    ],
    # 예전에 레벨마다 하나씩 주던 아이템들 — id를 그대로 두어 이미 고른 학생 것이 유지된다
    "badge": [
        {"id": "none",      "emoji": "",   "label": "없음",           "level": 1},
        {"id": "sprout",    "emoji": "🌱", "label": "새싹 배지",      "level": 2},
        {"id": "clover",    "emoji": "🍀", "label": "네잎클로버",     "level": 3},
        {"id": "bamboo",    "emoji": "🎍", "label": "대나무 장식",    "level": 4},
        {"id": "flowerpin", "emoji": "🌸", "label": "꽃 머리핀",      "level": 5},
        {"id": "wreath",    "emoji": "🌻", "label": "화관",           "level": 6},
        {"id": "grapes",    "emoji": "🍇", "label": "열매 목걸이",    "level": 7},
        {"id": "crown",     "emoji": "👑", "label": "작은 왕관",      "level": 8},
        {"id": "sparkle",   "emoji": "✨", "label": "반짝이는 오라",  "level": 9},
        {"id": "trophy",    "emoji": "🏆", "label": "황금 트로피",    "level": 10},
    ],
    "effect": [
        {"id": "none",    "emoji": "",   "label": "없음",       "level": 1},
        {"id": "twinkle", "emoji": "✨", "label": "반짝임",     "level": 4},
        {"id": "hearts",  "emoji": "💖", "label": "하트",       "level": 5},
        {"id": "stars",   "emoji": "🌟", "label": "별빛",       "level": 6},
        {"id": "comet",   "emoji": "💫", "label": "혜성",       "level": 7},
        {"id": "flame",   "emoji": "🔥", "label": "불꽃",       "level": 8},
        {"id": "rainbow", "emoji": "🌈", "label": "무지개",     "level": 9},
        {"id": "galaxy",  "emoji": "🌌", "label": "은하",       "level": 10},
    ],
}

AVATAR_DEFAULTS = {"face": "boy", "color": "blue", "hat": "none",
                   "pet": "none", "badge": "none", "effect": "none"}


def avatar_unlocks(level: int) -> dict:
    """그 레벨에서 쓸 수 있는 항목 id 목록을 갈래별로."""
    return {slot: [it["id"] for it in items if it["level"] <= level]
            for slot, items in AVATAR_ITEMS.items()}


def new_items_at_level(level: int) -> list:
    """이번 레벨에서 새로 열린 것들 (레벨업 축하 화면용)."""
    out = []
    for slot, items in AVATAR_ITEMS.items():
        name = next((s["name"] for s in AVATAR_SLOTS if s["key"] == slot), slot)
        for it in items:
            if it["level"] == level:
                out.append({"slot": slot, "slot_name": name,
                            "emoji": it.get("emoji", "🎨"), "label": it["label"]})
    if level == PHOTO_UNLOCK_LEVEL:
        out.append({"slot": "photo", "slot_name": "내 사진", "emoji": "📷",
                    "label": "내 사진을 아바타로 쓰기"})
    return out


def sanitize_avatar(raw: dict, level: int) -> dict:
    """학생이 보낸 꾸미기 값을 레벨에 맞게 걸러낸다. 아직 못 여는 것은 기본값으로."""
    raw = raw or {}
    unlocked = avatar_unlocks(level)
    out = {}
    for slot, default in AVATAR_DEFAULTS.items():
        want = str(raw.get(slot, "") or "").strip()
        out[slot] = want if want in unlocked.get(slot, []) else default
    out["use_photo"] = bool(raw.get("use_photo")) and level >= PHOTO_UNLOCK_LEVEL
    return out


@app.get("/api/student/avatar_catalog")
def get_avatar_catalog():
    """꾸미기 항목 전체 목록 — 어느 레벨에 열리는지 함께."""
    return {"success": True, "slots": AVATAR_SLOTS, "items": AVATAR_ITEMS,
            "defaults": AVATAR_DEFAULTS, "photo_level": PHOTO_UNLOCK_LEVEL}


def compute_level_info(xp) -> dict:
    """누적 xp로 현재 레벨/다음 레벨까지 필요한 양/지금까지 잠금해제된 꾸미기 아이템을 계산한다."""
    try:
        xp = max(0, int(xp or 0))
    except (TypeError, ValueError):
        xp = 0

    current = LEVELS[0]
    idx = 0
    for i, lv in enumerate(LEVELS):
        if xp >= lv["threshold"]:
            current = lv
            idx = i
        else:
            break

    next_lv = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    unlocked_items = [lv["unlock_item"] for lv in LEVELS[: idx + 1] if lv["unlock_item"]]
    lv_num = current["level"]

    return {
        "level": current["level"],
        "name": current["name"],
        "icon": current["icon"],
        "xp": xp,
        "current_threshold": current["threshold"],
        "next_threshold": next_lv["threshold"] if next_lv else None,
        "next_name": next_lv["name"] if next_lv else None,
        "is_max": next_lv is None,
        "unlocked_items": unlocked_items,
        "unlocked": avatar_unlocks(lv_num),
        "new_at_this_level": new_items_at_level(lv_num),
        "photo_unlocked": lv_num >= PHOTO_UNLOCK_LEVEL,
        "photo_level": PHOTO_UNLOCK_LEVEL,
    }


def level_up_info(old_xp, delta):
    """xp가 old_xp에서 old_xp+delta로 늘어날 때 레벨이 오르면 축하 화면에 쓸 정보를 반환, 아니면 None."""
    if not delta:
        return None
    old_lv = compute_level_info(old_xp)
    new_lv = compute_level_info((old_xp or 0) + delta)
    if new_lv["level"] > old_lv["level"]:
        # 건너뛴 레벨이 있을 수 있으니 그 사이에 열린 것을 모두 모은다
        gained = []
        for lv in range(old_lv["level"] + 1, new_lv["level"] + 1):
            gained += new_items_at_level(lv)
        return {"from": old_lv["level"], "to": new_lv["level"], "name": new_lv["name"],
                "icon": new_lv["icon"], "unlocked": gained}
    return None

# 💡 해결: 파일 업로드 제한을 25MB에서 100MB로 대폭 상향 조정
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".hwp", ".doc", ".docx",
    ".txt", ".ppt", ".pptx", ".mp4", ".mov",
}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100MB

# ─────────────────────────────────────────────────────────
# Firebase 초기화
# ─────────────────────────────────────────────────────────
firebase_key_str = os.environ.get("FIREBASE_KEY")
db = None
bucket = None
if firebase_key_str:
    try:
        cred_dict = json.loads(firebase_key_str)
        cred = credentials.Certificate(cred_dict)
        project_id = cred_dict.get("project_id")
        bucket_name = os.environ.get("FIREBASE_BUCKET", f"{project_id}.appspot.com").replace("gs://", "").strip("/")

        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})
        db = firestore.client()
        bucket = storage.bucket()
    except Exception as e:
        print("Firebase Init Error:", e)


# ─────────────────────────────────────────────────────────
# 관리자 인증
# ─────────────────────────────────────────────────────────
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
_admin_tokens = set()
STUDENT_SIGNUP_CODE = os.environ.get("STUDENT_SIGNUP_CODE", "logyedu2024")

def issue_admin_token() -> str:
    token = uuid.uuid4().hex
    _admin_tokens.add(token)
    return token


def verify_admin(x_admin_token: Optional[str] = Header(None)):
    if not x_admin_token or x_admin_token not in _admin_tokens:
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    return True


# ─────────────────────────────────────────────────────────
# 파일 저장 (경로 조작 방지 + 확장자/용량 검증)
# ─────────────────────────────────────────────────────────
def get_safe_filename(filename: str) -> str:
    if not filename:
        return "unnamed_file"
    return os.path.basename(filename).replace(" ", "_")


def validate_upload(filename: str, file_bytes: bytes):
    safe_name = get_safe_filename(filename)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"허용되지 않는 파일 형식입니다: {ext}")
    # 💡 100MB 초과 시 에러 메시지
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="파일 용량이 100MB를 초과했습니다. 더 작은 파일로 분할해 주세요.")


def save_bytes(file_bytes: bytes, filename: str, folder: str, content_type: str) -> str:
    safe_name = get_safe_filename(filename)
    validate_upload(filename, file_bytes)
    unique_name = f"{uuid.uuid4()}_{safe_name}"
    filepath = f"uploads/{folder}/{unique_name}"

    if bucket:
        try:
            blob = bucket.blob(filepath)
            mt, _ = mimetypes.guess_type(safe_name)
            blob.upload_from_string(file_bytes, content_type=mt or content_type or "application/octet-stream")
            return f"/{filepath}"
        except Exception as e:
            print("Storage Upload Error:", e)
            # 💡 영구 저장소(Firebase Storage) 업로드가 실패해 임시 저장소로 대체되면 즉시 알림
            # (서버 재배포 시 임시 저장소의 파일은 사라질 수 있어 확인이 필요함)
            send_telegram_message(f"⚠️ [저장소 경고]\n'{safe_name}' 파일을 영구 저장소에 올리지 못해 임시 저장소에 저장했습니다.\n서버가 재배포되면 이 파일은 사라질 수 있습니다. 확인이 필요합니다.\n오류: {e}")

    with open(filepath, "wb") as buffer:
        buffer.write(file_bytes)
    return f"/{filepath}"


def sanitize_doc_id(value: str, fallback: str = "unnamed") -> str:
    if not value or not value.strip():
        return fallback
    cleaned = value.strip().replace("/", "_").replace("\\", "_")
    if cleaned in (".", ".."):
        return fallback
    return cleaned[:200]


def normalize_grade(value: str) -> str:
    """'고1', '1학년', '1' 처럼 표기가 달라도 같은 학년으로 인식하도록 숫자만 추출해서 비교용으로 씀."""
    if not value:
        return ""
    m = re.search(r"\d+", value)
    return m.group(0) if m else value.strip()


@app.get("/uploads/{folder}/{filename}")
def get_upload_file(folder: str, filename: str):
    safe_filename = get_safe_filename(filename)
    safe_folder = get_safe_filename(folder)
    filepath = f"uploads/{safe_folder}/{safe_filename}"

    mt, _ = mimetypes.guess_type(safe_filename)
    encoded_filename = urllib.parse.quote(safe_filename.encode("utf-8"))
    is_inline = mt in ["application/pdf", "image/jpeg", "image/png", "image/gif"]
    disposition = "inline" if is_inline else "attachment"

    if bucket:
        try:
            blob = bucket.blob(filepath)
            if blob.exists():
                return Response(
                    content=blob.download_as_bytes(),
                    media_type=mt or "application/octet-stream",
                    headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_filename}"},
                )
        except Exception:
            pass

    if os.path.exists(filepath):
        return FileResponse(
            filepath,
            media_type=mt or "application/octet-stream",
            headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_filename}"},
        )
    raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")


def send_telegram_message(text: str):
    # 💡 Render에는 TELEGRAM_TOKEN이라는 이름으로 저장돼 있는데 코드는 TELEGRAM_BOT_TOKEN을
    # 찾고 있어서, 값이 설정돼 있어도 계속 못 찾아 알림이 전혀 안 가던 문제. 두 이름 다 확인.
    token = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram 알림 건너뜀: TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID 환경변수가 설정되지 않았습니다.")
        return

    def _send():
        try:
            res = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=5,
            )
            if not res.ok:
                print(f"Telegram 알림 전송 실패: [{res.status_code}] {res.text}")
        except Exception as e:
            print(f"Telegram 알림 전송 오류: {e}")

    threading.Thread(target=_send).start()


# ─────────────────────────────────────────────────────────
# AI 모델 (캐싱 유지)
# ─────────────────────────────────────────────────────────
_cached_model = None
_cached_quality_model = None

# 💡 채팅처럼 빈도가 높고 속도가 중요한 기능은 빠른 모델(flash)을,
# 문제 출제/논술 첨삭/해설자료처럼 결과물의 품질이 곧 산출물인 기능은
# 더 똑똑한 모델(pro)을 우선 사용하도록 분리. (예전엔 flash가 pro보다
# 먼저 선택되게 되어 있어, 출제되는 문제의 질이 낮다는 피드백이 있었음)
# 💡 원래 gemini-3.6-flash가 최우선이었는데, FAST/QUALITY로 목록을 나누며 실수로
# 빠뜨렸었음 — list_models()에 이 이름이 없으면 available[0]로 대체되는데, 그게
# 하필 단종된 gemini-2.5-flash였어서 "AI 응답 실패" 오류로 이어졌음. 복구.
FAST_MODEL_PREFERENCE = ["gemini-3.6-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"]
# 💡 gemini-2.5-pro가 이 계정에서 단종되어 "This model ... is no longer available to
# new users. ... use models/gemini-3.1-pro-preview" 오류가 발생했음 — 구글이 안내한
# 대체 모델을 최우선으로, 혹시 이후 이것도 바뀔 경우를 대비해 기존 후보들도 순서대로 남겨둠
QUALITY_MODEL_PREFERENCE = ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-1.5-pro-latest", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-pro"]


def get_best_model(prefer_quality: bool = False):
    global _cached_model, _cached_quality_model
    if prefer_quality and _cached_quality_model:
        return _cached_quality_model
    if not prefer_quality and _cached_model:
        return _cached_model

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise Exception("API 키가 설정되지 않았습니다.")
    genai.configure(api_key=api_key.strip().replace('"', "").replace("'", ""))

    try:
        models = genai.list_models()
        available = [m.name.replace("models/", "") for m in models if "generateContent" in m.supported_generation_methods]
        preference = QUALITY_MODEL_PREFERENCE if prefer_quality else FAST_MODEL_PREFERENCE
        target_model = next(
            (m for m in preference if m in available),
            available[0] if available else None,
        )
        if not target_model:
            raise Exception("사용 가능한 구글 AI 모델이 없습니다.")

        model = genai.GenerativeModel(target_model)
        if prefer_quality:
            _cached_quality_model = model
        else:
            _cached_model = model
        return model
    except Exception as e:
        raise Exception(f"AI 모델 초기화 실패: {str(e)}")


def safe_generate(contents, stream=False, prefer_quality=False):
    model = get_best_model(prefer_quality=prefer_quality)
    return model.generate_content(contents, stream=stream)


# ─────────────────────────────────────────────────────────
# 간단한 요청 속도 제한 (AI 호출은 비용이 들기 때문에, 로그인 없이도 호출
# 가능한 /api/chat, /api/essay/grade를 무제한으로 외부에서 두들기지 못하게 막는 용도)
# ─────────────────────────────────────────────────────────
_rate_limit_hits: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = threading.Lock()


def check_rate_limit(request: Request, bucket: str, max_calls: int, window_seconds: int):
    client_ip = request.client.host if request.client else "unknown"
    key = f"{bucket}:{client_ip}"
    now = time.time()
    cutoff = now - window_seconds
    with _rate_limit_lock:
        hits = _rate_limit_hits[key]
        while hits and hits[0] < cutoff:
            hits.pop(0)
        if len(hits) >= max_calls:
            raise HTTPException(
                status_code=429,
                detail=f"요청이 너무 잦습니다. {window_seconds}초 후 다시 시도해주세요.",
            )
        hits.append(now)


# ─────────────────────────────────────────────────────────
# WebSocket
# ─────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, ws: WebSocket, room: str):
        await ws.accept()
        self.active_connections.setdefault(room, []).append(ws)

    def disconnect(self, ws: WebSocket, room: str):
        if room in self.active_connections and ws in self.active_connections[room]:
            self.active_connections[room].remove(ws)

    async def broadcast(self, message: str, room: str, sender: WebSocket):
        for c in self.active_connections.get(room, []):
            if c != sender:
                try:
                    await c.send_text(message)
                except Exception:
                    pass

manager = ConnectionManager()

@app.websocket("/ws/exam/{room}")
async def websocket_endpoint(websocket: WebSocket, room: str):
    await manager.connect(websocket, room)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(data, room, sender=websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket, room)


# ─────────────────────────────────────────────────────────
# 인증
# ─────────────────────────────────────────────────────────
class AuthRequest(BaseModel):
    school: str = ""
    grade: str = ""
    student_name: str
    admin_password: str = ""


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/auth")
async def authenticate(req: AuthRequest):
    if req.admin_password:
        if req.admin_password == ADMIN_PASSWORD:
            token = issue_admin_token()
            return {"success": True, "is_admin": True, "admin_token": token}
        return {"success": False, "detail": "관리자 비밀번호가 올바르지 않습니다."}

    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}

    student_name = req.student_name.strip()
    school = req.school.strip()
    grade = req.grade.strip()

    doc = await asyncio.to_thread(lambda: db.collection("students").document(student_name).get())
    if doc.exists:
        data = doc.to_dict()
        if str(data.get("school", "")).strip() == school and normalize_grade(str(data.get("grade", ""))) == normalize_grade(grade):
            today = datetime.now().strftime("%Y-%m-%d")
            lvl_up = None
            if data.get("last_login", "") != today:
                lvl_up = level_up_info(data.get("xp", 0), XP_REWARD_LOGIN)
                await asyncio.to_thread(
                    lambda: db.collection("students").document(student_name).set(
                        {"last_login": today, "xp": firestore.Increment(XP_REWARD_LOGIN)}, merge=True
                    )
                )
            # 💡 로그인 자체는 reports 컬렉션에 전혀 기록되지 않아, 관리자 화면의
            # "로그인 이력"이 항상 비어있던 버그 수정 — 매 로그인마다 기록을 남김
            await asyncio.to_thread(
                lambda: db.collection("reports").add(
                    {
                        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "student_name": student_name,
                        "school": school,
                        "grade": grade,
                        "task_name": "로그인",
                        "type": "로그인",
                        "score": "",
                    }
                )
            )
            send_telegram_message(f"🔔 [접속 알림]\n{school} {grade}학년 {student_name} 학생이 스마트 학습실에 로그인했습니다.")
            return {"success": True, "is_admin": False, "level_up": lvl_up}
    return {"success": False, "detail": "명부에 이름이 없거나 정보가 틀립니다."}


@app.get("/api/student/profile/{student_name}")
def get_student_profile(student_name: str):
    if db is None:
        return {"success": False}
    doc = db.collection("students").document(student_name).get()
    if not doc.exists:
        return {"success": False}
    reports = [
        r.to_dict()
        for r in db.collection("reports")
        .where("student_name", "==", student_name)
        .order_by("submitted_at", direction=firestore.Query.DESCENDING)
        .limit(100)
        .stream()
    ]
    profile = doc.to_dict()
    return {"success": True, "profile": profile, "reports": reports, "level_info": compute_level_info(profile.get("xp"))}


class AvatarSaveRequest(BaseModel):
    student_name: str
    gender: str = ""          # 예전 방식 (boy/girl) — 넘어오면 face로 옮긴다
    item: str = ""            # 예전 방식 (배지 하나)
    avatar: dict = None       # 새 방식 {face,color,hat,pet,badge,effect,use_photo}


@app.post("/api/student/avatar")
async def save_avatar(req: AvatarSaveRequest):
    if db is None:
        return {"success": False}

    s_ref = db.collection("students").document(sanitize_doc_id(req.student_name))
    doc = await asyncio.to_thread(s_ref.get)
    if not doc.exists:
        return {"success": False, "detail": "학생 정보를 찾을 수 없습니다."}

    data = doc.to_dict() or {}
    info = compute_level_info(data.get("xp"))

    raw = dict(req.avatar or {})
    # 예전 화면에서 온 요청도 받아준다
    if not raw:
        if req.gender in ("boy", "girl"):
            raw["face"] = req.gender
        if req.item:
            raw["badge"] = req.item
        prev = data.get("avatar_look") or {}
        for k, v in prev.items():
            raw.setdefault(k, v)

    look = sanitize_avatar(raw, info["level"])
    await asyncio.to_thread(lambda: s_ref.set({
        "avatar_look": look,
        # 예전 화면이 읽던 항목도 함께 맞춰 둔다
        "avatar_gender": look["face"] if look["face"] in ("boy", "girl") else data.get("avatar_gender", "boy"),
        "avatar_item": look["badge"],
    }, merge=True))
    return {"success": True, "avatar": look, "level_info": info}


# ── 관리자 아바타 ──────────────────────────────────────
#   원장님은 학생 명단에 없어 xp가 쌓이지 않는다. 늘 최고 레벨로 두어
#   모든 꾸미기를 직접 보고 학생에게 보여줄 수 있게 한다.
MAX_LEVEL_XP = LEVELS[-1]["threshold"]


@app.get("/api/admin/avatar", dependencies=[Depends(verify_admin)])
def get_admin_avatar():
    info = compute_level_info(MAX_LEVEL_XP)
    look = dict(AVATAR_DEFAULTS)
    look["use_photo"] = False
    image = ""
    if db is not None:
        doc = db.collection("settings").document("admin_avatar").get()
        if doc.exists:
            data = doc.to_dict() or {}
            look.update(data.get("look") or {})
            image = data.get("profile_image", "")
    return {"success": True, "avatar": sanitize_avatar(look, info["level"]),
            "level_info": info, "profile_image": image}


class AdminAvatarReq(BaseModel):
    avatar: dict = None


@app.post("/api/admin/avatar", dependencies=[Depends(verify_admin)])
def save_admin_avatar(req: AdminAvatarReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    info = compute_level_info(MAX_LEVEL_XP)
    look = sanitize_avatar(req.avatar or {}, info["level"])
    db.collection("settings").document("admin_avatar").set({"look": look}, merge=True)
    return {"success": True, "avatar": look, "level_info": info}


@app.post("/api/admin/avatar/photo", dependencies=[Depends(verify_admin)])
async def upload_admin_photo(file: UploadFile = File(...)):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    if not file or not file.filename:
        return {"success": False, "detail": "파일이 없습니다."}
    raw = await file.read()
    if not raw:
        return {"success": False, "detail": "빈 파일입니다."}
    if not (file.content_type or "").lower().startswith("image/"):
        return {"success": False, "detail": "그림 파일만 올릴 수 있습니다."}
    try:
        url = save_bytes(raw, file.filename, "profiles", file.content_type)
    except HTTPException as e:
        return {"success": False, "detail": str(e.detail)}
    db.collection("settings").document("admin_avatar").set({"profile_image": url}, merge=True)
    return {"success": True, "url": url}


@app.post("/api/student/profile_update")
async def update_profile(
    student_name: str = Form(...),
    motto: str = Form(""),
    avatar: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    if db is None:
        return {"success": False}
    s_ref = db.collection("students").document(student_name)
    doc = await asyncio.to_thread(s_ref.get)
    if not doc.exists:
        return {"success": False}

    update_data = {"motto": motto, "avatar": avatar}
    if not doc.to_dict().get("profile_setup_done"):
        update_data["xp"] = firestore.Increment(XP_REWARD_PROFILE)
        update_data["profile_setup_done"] = True

    if file and file.filename:
        file_bytes = await file.read()
        update_data["profile_image"] = save_bytes(file_bytes, file.filename, "profiles", file.content_type)
        update_data["avatar"] = ""

    await asyncio.to_thread(lambda: s_ref.set(update_data, merge=True))
    return {"success": True}


@app.get("/api/classes")
def get_classes():
    """로그인 화면 자동완성용 — 등록된 학교/학년 조합만 공개 (이름 등 개인정보 제외)."""
    if db is None:
        return {"success": False, "classes": []}
    seen = set()
    classes = []
    for d in db.collection("students").stream():
        data = d.to_dict()
        school, grade = str(data.get("school", "")).strip(), str(data.get("grade", "")).strip()
        if not school and not grade:
            continue
        key = (school, grade)
        if key in seen:
            continue
        seen.add(key)
        classes.append({"school": school, "grade": grade})
    return {"success": True, "classes": classes}


class StudentRegisterRequest(BaseModel):
    school: str
    grade: str
    name: str
    code: str


@app.post("/api/student/register")
async def register_student(req: StudentRegisterRequest):
    """학생 자가 회원가입 — 가입 코드(STUDENT_SIGNUP_CODE)를 아는 사람만 스스로 명단에 등록할 수 있음."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}

    if req.code.strip() != STUDENT_SIGNUP_CODE:
        return {"success": False, "detail": "가입 코드가 올바르지 않습니다. 원장님께 문의해주세요."}

    school = req.school.strip()
    grade = req.grade.strip()
    name = req.name.strip()
    if not school or not grade or not name:
        return {"success": False, "detail": "학교, 학년, 이름을 모두 입력해주세요."}

    doc_id = sanitize_doc_id(name)
    s_ref = db.collection("students").document(doc_id)
    doc = await asyncio.to_thread(s_ref.get)
    if doc.exists:
        data = doc.to_dict()
        existing_school = str(data.get("school", "")).strip()
        existing_grade = normalize_grade(str(data.get("grade", "")))
        if existing_school == school and existing_grade == normalize_grade(grade):
            # 이미 동일 인물(같은 학교/학년)로 등록되어 있음 — 데이터를 덮어쓰지 않고 그대로 로그인 가능
            return {"success": True, "already_existed": True}
        return {"success": False, "detail": "이미 등록된 이름입니다. 동명이인이거나 정보가 다르다면 원장님께 문의해주세요."}

    await asyncio.to_thread(lambda: s_ref.set({"school": school, "grade": grade}, merge=True))
    send_telegram_message(f"🆕 [학생 자가 회원가입]\n{school} {grade} {name} 학생이 스스로 회원가입했습니다.")
    return {"success": True, "already_existed": False}


# ─────────────────────────────────────────────────────────
# 관리자 - 학생 관리
# ─────────────────────────────────────────────────────────
@app.get("/api/admin/students")
def get_students(_: bool = Depends(verify_admin)):
    if db is None:
        return {"success": False, "students": []}
    return {"success": True, "students": [{"id": d.id, "student_name": d.id, **d.to_dict()} for d in db.collection("students").stream()]}

class SingleStudentRequest(BaseModel):
    school: str
    grade: str
    name: str
    class_name: str = ""

@app.post("/api/admin/student")
def add_single_student(req: SingleStudentRequest, _: bool = Depends(verify_admin)):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    db.collection("students").document(sanitize_doc_id(req.name)).set(
        {"school": req.school, "grade": req.grade, "class_name": (req.class_name or "").strip()}, merge=True
    )
    return {"success": True}

class BulkDeleteReq(BaseModel):
    ids: list = None

@app.post("/api/admin/student/delete_bulk")
def delete_students_bulk(req: BulkDeleteReq, _: bool = Depends(verify_admin)):
    if db and req.ids:
        for t in req.ids: db.collection("students").document(t).delete()
    return {"success": True}

class StudentUpdateReq(BaseModel):
    old_id: str
    new_name: str
    school: str
    grade: str
    class_name: str = None

@app.post("/api/admin/student/update")
def update_student(req: StudentUpdateReq, _: bool = Depends(verify_admin)):
    if db is None: return {"success": False}
    doc_ref = db.collection("students").document(req.old_id)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        data['school'] = req.school; data['grade'] = req.grade
        if req.class_name is not None:
            data['class_name'] = req.class_name.strip()
        if req.old_id != req.new_name:
            db.collection("students").document(req.new_name).set(data)
            doc_ref.delete()
        else: doc_ref.set(data, merge=True)
    return {"success": True}

# ─────────────────────────────────────────────────────────
# 관리자 - 반(班) 관리
#   학생 명단을 반별로 묶고, 반마다 수업 요일/시간을 기록한다.
#   로그인 방식(학교+학년+이름)과는 완전히 분리되어 있어서,
#   반을 만들거나 바꿔도 학생 로그인에는 아무 영향이 없다.
# ─────────────────────────────────────────────────────────
DAY_ORDER = ["월", "화", "수", "목", "금", "토", "일"]


def _class_doc(d) -> dict:
    data = d.to_dict() or {}
    return {
        "id": d.id,
        "name": str(data.get("name") or d.id),
        "days": str(data.get("days") or ""),
        "start_time": str(data.get("start_time") or ""),
        "end_time": str(data.get("end_time") or ""),
        "memo": str(data.get("memo") or ""),
    }


def _class_sort_key(c: dict):
    """요일(월→일) → 시작 시각 → 이름 순으로 시간표처럼 정렬."""
    days = [x.strip() for x in c.get("days", "").split(",") if x.strip()]
    first_day = min((DAY_ORDER.index(x) for x in days if x in DAY_ORDER), default=99)
    return (first_day, c.get("start_time") or "99:99", c.get("name", ""))


@app.get("/api/admin/classes")
def get_admin_classes(_: bool = Depends(verify_admin)):
    if db is None:
        return {"success": False, "classes": []}
    classes = [_class_doc(d) for d in db.collection("classes").stream()]
    classes.sort(key=_class_sort_key)
    return {"success": True, "classes": classes}


class ClassUpsertReq(BaseModel):
    old_name: str = ""
    name: str
    days: str = ""
    start_time: str = ""
    end_time: str = ""
    memo: str = ""


@app.post("/api/admin/class")
def upsert_class(req: ClassUpsertReq, _: bool = Depends(verify_admin)):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.name.strip()
    if not name:
        return {"success": False, "detail": "반 이름을 입력해주세요."}

    old_name = (req.old_name or "").strip()
    payload = {
        "name": name,
        "days": req.days.strip(),
        "start_time": req.start_time.strip(),
        "end_time": req.end_time.strip(),
        "memo": req.memo.strip(),
    }
    db.collection("classes").document(sanitize_doc_id(name)).set(payload, merge=True)

    # 반 이름을 바꾼 경우 — 예전 반 문서를 지우고, 그 반에 속한 학생들도 새 이름으로 옮겨준다
    if old_name and old_name != name:
        db.collection("classes").document(sanitize_doc_id(old_name)).delete()
        for d in db.collection("students").where("class_name", "==", old_name).stream():
            d.reference.set({"class_name": name}, merge=True)
    return {"success": True}


class ClassDeleteReq(BaseModel):
    name: str


@app.post("/api/admin/class/delete")
def delete_class(req: ClassDeleteReq, _: bool = Depends(verify_admin)):
    """반만 삭제한다. 학생은 절대 지우지 않고 '미배정'으로 돌려놓을 뿐이다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.name.strip()
    if not name:
        return {"success": False, "detail": "반 이름이 비어 있습니다."}
    db.collection("classes").document(sanitize_doc_id(name)).delete()
    moved = 0
    for d in db.collection("students").where("class_name", "==", name).stream():
        d.reference.set({"class_name": ""}, merge=True)
        moved += 1
    return {"success": True, "unassigned": moved}


class AssignClassReq(BaseModel):
    ids: list = None
    class_name: str = ""


@app.post("/api/admin/student/assign_class")
def assign_class(req: AssignClassReq, _: bool = Depends(verify_admin)):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    target = (req.class_name or "").strip()
    count = 0
    for sid in (req.ids or []):
        db.collection("students").document(sid).set({"class_name": target}, merge=True)
        count += 1
    return {"success": True, "updated": count}


@app.get("/api/admin/reports")
def get_reports(_: bool = Depends(verify_admin)):
    if db is None:
        return {"success": False, "reports": []}
    docs = db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(300).stream()
    return {"success": True, "reports": [{"id": d.id, **d.to_dict()} for d in docs]}


# ─────────────────────────────────────────────────────────
# 챗봇 — 답변 자율성 부여 (족쇄 해제)
# ─────────────────────────────────────────────────────────
def build_safe_knowledge_context() -> str:
    """학생 챗봇에 노출해도 안전한 자료만 모은다 (정답/해설 필드 제외)."""
    if db is None:
        return ""
    kb_docs = db.collection("knowledge").order_by("created_at", direction=firestore.Query.DESCENDING).limit(50).stream()
    knowledge_base = "\n".join([f"[{d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in kb_docs])
    return knowledge_base


def get_ai_guidelines() -> str:
    """원장님이 설정한 'AI 답변 원칙'(수업 방식/설명 스타일 지침)을 가져온다."""
    if db is None:
        return ""
    doc = db.collection("settings").document("ai_guidelines").get()
    return doc.to_dict().get("text", "") if doc.exists else ""


def grant_chat_xp(student_name: str):
    """AI 질문 1회당 소량의 성장 포인트를 지급한다 (하루 최대 XP_REWARD_CHAT_DAILY_MAX_COUNT회). 레벨업 시 정보를 반환."""
    s_ref = db.collection("students").document(student_name)
    doc = s_ref.get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    today = datetime.now().strftime("%Y-%m-%d")
    old_xp = data.get("xp", 0)
    if data.get("chat_xp_date") != today:
        s_ref.set({"chat_xp_date": today, "chat_xp_count": 1, "xp": firestore.Increment(XP_REWARD_CHAT)}, merge=True)
        return level_up_info(old_xp, XP_REWARD_CHAT)
    elif data.get("chat_xp_count", 0) < XP_REWARD_CHAT_DAILY_MAX_COUNT:
        s_ref.set({"chat_xp_count": firestore.Increment(1), "xp": firestore.Increment(XP_REWARD_CHAT)}, merge=True)
        return level_up_info(old_xp, XP_REWARD_CHAT)
    return None


@app.post("/api/chat")
async def chat_with_ai(
    request: Request,
    prompt: str = Form(...),
    school: str = Form("미상"),
    grade: str = Form("미상"),
    student_name: str = Form("미상"),
    files: Optional[List[UploadFile]] = File(None),
):
    check_rate_limit(request, "chat", max_calls=15, window_seconds=60)
    send_telegram_message(f"💬 [질문 알림]\n{student_name} 학생이 국최에게 질문을 남겼습니다.\n\nQ: {prompt}")

    knowledge_base = await asyncio.to_thread(build_safe_knowledge_context)
    ai_guidelines = await asyncio.to_thread(get_ai_guidelines)

    system_prompt = f"""당신은 로지에듀 국어학원 AI 튜터 '국최'입니다.
아래 [원장님 답변 원칙]이 있다면 그 방식과 관점을 최우선으로 따라서 설명하세요.
그 다음으로 [학원 누적 자료]를 참고하여 다정하고 명쾌하게 답변하세요.
만약 학생이 묻는 내용이 자료에 없더라도, 국어 전문가로서의 지식을 활용해 국어 개념(문법, 표현법 등)을 친절하게 설명해 주세요. "자료에 없어서 모른다"는 말은 절대 하지 마세요.
단, 모의고사나 퀴즈의 정답을 직접적으로 물어볼 때는 정답 대신 힌트만 제공하세요.

[원장님 답변 원칙]
{ai_guidelines or "(설정된 원칙 없음 - 일반적인 국어 교육 원칙에 따라 설명)"}

[학원 누적 자료]
{knowledge_base}

[학생 질문]
{prompt}"""

    contents = [system_prompt]
    if files:
        for f in files:
            if f.filename:
                file_bytes = await f.read()
                contents.append({"mime_type": f.content_type or "application/octet-stream", "data": file_bytes})
    try:
        response = await asyncio.to_thread(safe_generate, contents, False)
        lvl_up = None
        if db is not None and student_name and student_name != "미상":
            try:
                lvl_up = await asyncio.to_thread(grant_chat_xp, student_name)
            except Exception:
                pass
        return {"success": True, "reply": response.text, "level_up": lvl_up}
    except Exception as e:
        # 💡 예전엔 무슨 오류든 "AI 응답 지연"으로만 뭉뚱그려서 원인 파악이 불가능했음.
        # 실제 예외 메시지(모델 단종, 레이트리밋 등)를 그대로 보여주도록 수정.
        return {"success": False, "reply": f"AI 응답 실패: {e}"}


@app.post("/api/essay/grade")
async def grade_essay(
    request: Request,
    school: str = Form(""),
    grade: str = Form(""),
    student_name: str = Form(""),
    topic: str = Form(...),
    file: UploadFile = File(...),
):
    check_rate_limit(request, "essay_grade", max_calls=8, window_seconds=60)
    send_telegram_message(f"✍️ [논술 제출 알림]\n{student_name} 학생이 '{topic}' 논술을 제출했습니다.")
    file_bytes = await file.read()
    ai_guidelines = await asyncio.to_thread(get_ai_guidelines)
    prompt = f"""다음은 학생이 작성한 논술/요약문입니다. 논제: {topic}
이 글을 분석하고, 빨간펜 선생님처럼 다정하지만 예리하게 칭찬과 개선점, 첨삭 피드백을 HTML 형식으로 작성해주세요.

[원장님 답변/채점 원칙 - 최우선으로 반영]
{ai_guidelines or "(설정된 원칙 없음 - 일반적인 논술 첨삭 기준에 따라 평가)"}"""

    try:
        # 💡 비용 절감: 논술 첨삭도 빠른(저렴한) 모델 사용. pro 모델은 '문제 출제'에만 적용
        response = await asyncio.to_thread(safe_generate, [prompt, {"mime_type": file.content_type, "data": file_bytes}], False)
        lvl_up = None
        if db is not None:
            file_url = await asyncio.to_thread(save_bytes, file_bytes, file.filename, "homeworks", file.content_type)
            await asyncio.to_thread(
                lambda: db.collection("reports").add(
                    {
                        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "student_name": student_name,
                        "school": school,
                        "grade": grade,
                        "task_name": topic,
                        "type": "논술 첨삭",
                        "score": "완료",
                        "file_url": file_url,
                    }
                )
            )
            s_ref = db.collection("students").document(student_name)
            s_doc = await asyncio.to_thread(s_ref.get)
            old_xp = s_doc.to_dict().get("xp", 0) if s_doc.exists else 0
            lvl_up = level_up_info(old_xp, XP_REWARD_ESSAY)
            await asyncio.to_thread(
                lambda: s_ref.set({"xp": firestore.Increment(XP_REWARD_ESSAY)}, merge=True)
            )
        return {"success": True, "feedback": response.text, "level_up": lvl_up}
    except Exception as e:
        return {"success": False, "detail": f"첨삭 처리 중 오류 발생: {e}"}


# ─────────────────────────────────────────────────────────
# 관리자 - 시험
# ─────────────────────────────────────────────────────────
@app.post("/api/admin/exam")
async def create_exam(
    title: str = Form(...),
    objective: str = Form(""),
    exam_data: str = Form(...),
    video_url: str = Form(""),
    explanation_text: str = Form(""),
    file: Optional[UploadFile] = File(None),
    ans_file: Optional[UploadFile] = File(None),
    _: bool = Depends(verify_admin),
):
    if db is None:
        return {"success": False, "detail": "DB 오류"}

    try:
        json.loads(exam_data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="exam_data 형식이 올바르지 않습니다.")

    pdf_url, ans_pdf_url = "", ""
    if file and file.filename:
        pdf_url = await asyncio.to_thread(save_bytes, await file.read(), file.filename, "exams", file.content_type)
    if ans_file and ans_file.filename:
        ans_pdf_url = await asyncio.to_thread(save_bytes, await ans_file.read(), ans_file.filename, "exams", ans_file.content_type)

    safe_title = sanitize_doc_id(title)
    await asyncio.to_thread(
        lambda: db.collection("exams").document(safe_title).set(
            {
                "title": title,
                "objective": objective,
                "exam_data": exam_data,
                "pdf_url": pdf_url,
                "ans_pdf_url": ans_pdf_url,
                "video_url": video_url,
                "explanation_text": explanation_text,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    )
    return {"success": True}


@app.get("/api/exams")
def get_exams():
    if db is None:
        return {"success": False, "exams": []}
    return {"success": True, "exams": [{"id": d.id, **d.to_dict()} for d in db.collection("exams").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}


@app.delete("/api/admin/exam/{title}")
def delete_exam(title: str, _: bool = Depends(verify_admin)):
    if db:
        db.collection("exams").document(title).delete()
    return {"success": True}


class ExamSubmitRequest(BaseModel):
    school: str
    grade: str
    student_name: str
    title: str
    answers: list


@app.post("/api/admin/extract_quiz", dependencies=[Depends(verify_admin)])
async def extract_quiz(files: List[UploadFile] = File(...)):
    """문제지를 찍거나 캡처한 이미지, 또는 PDF에서 객관식 문항을 읽어낸다.
    퀴즈를 낼 때 문제와 보기를 하나하나 타이핑하지 않아도 되도록 추가."""
    parts = []
    for f in files:
        if not f.filename:
            continue
        raw = await f.read()
        if not raw:
            continue
        name = f.filename.lower()
        if name.endswith(".pdf"):
            # PDF는 페이지를 그림으로 바꿔 넘긴다 (표·기호가 많아 글자만 뽑으면 어긋난다)
            try:
                doc = fitz.open(stream=raw, filetype="pdf")
                for page in doc[:8]:
                    pix = page.get_pixmap(dpi=150)
                    parts.append({"mime_type": "image/png", "data": pix.tobytes("png")})
                doc.close()
            except Exception as e:
                return {"success": False, "detail": f"PDF를 읽지 못했습니다: {e}"}
        else:
            parts.append({"mime_type": f.content_type or "image/png", "data": raw})

    if not parts:
        return {"success": False, "detail": "읽을 수 있는 파일이 없습니다. 이미지나 PDF를 올려주세요."}

    prompt = """첨부된 자료는 객관식 문제지입니다. 여기 실린 문항을 모두 읽어내세요.

[반드시 지킬 것]
- 오직 JSON만 출력하세요. 설명, 인사말, 코드블록 표시(```)를 절대 붙이지 마세요.
- 형식:
{"questions":[{"q_text":"문제 내용","bogi":"<보기> 상자 안의 글","options":["선택지1","선택지2","선택지3","선택지4","선택지5"],"answer":3,"score":2}]}
- q_text에는 문항 번호를 빼고 발문만 적으세요.
- bogi에는 그 문항에 딸린 <보기> 상자 안의 내용을 그대로 옮기세요. 상자가 없으면 빈 문자열("")로 두세요. <보기>라는 글자 자체는 빼고 안의 내용만 담습니다.
- options는 보기를 순서대로 담되, ①②③④⑤ 같은 번호 기호는 빼고 내용만 적으세요.
- 보기가 5개보다 적으면 있는 만큼만 담고, 빈 칸을 지어내지 마세요.
- answer는 정답 보기의 번호(1~5)입니다. 자료에 정답이 표시되어 있지 않으면 null로 두세요. 절대 추측하지 마세요.
- score는 배점입니다. 자료에 배점이 적혀 있으면 그 숫자를, 없으면 2를 쓰세요.
- 서술형·주관식 문항은 건너뛰세요. 객관식만 담습니다.
- 자료가 여러 장이면 모두 합쳐 하나의 JSON으로 만드세요. 같은 문항이 두 번 들어가지 않게 하세요."""

    try:
        resp = await asyncio.to_thread(lambda: safe_generate([prompt] + parts))
        text = (resp.text or "").strip()
    except Exception as e:
        return {"success": False, "detail": f"문제를 읽지 못했습니다: {str(e)}"}

    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"success": False, "detail": "문항을 찾지 못했습니다. 문제와 보기가 또렷하게 보이는 자료인지 확인해주세요."}
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return {"success": False, "detail": "읽어낸 내용을 정리하지 못했습니다. 조금 더 선명한 자료로 다시 시도해주세요."}

    questions, no_answer = [], 0
    for q in (parsed.get("questions") or []):
        q_text = str(q.get("q_text", "") or "").strip()
        if not q_text:
            continue
        opts = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
        if len(opts) < 2:
            continue
        opts = (opts + ["", "", "", "", ""])[:5]

        ans = q.get("answer")
        try:
            ans = int(ans)
            if not (1 <= ans <= 5) or not opts[ans - 1]:
                ans = None
        except (TypeError, ValueError):
            ans = None
        if ans is None:
            no_answer += 1

        try:
            score = int(q.get("score", 2))
        except (TypeError, ValueError):
            score = 2

        questions.append({"q_text": q_text[:500],
                          "bogi": str(q.get("bogi", "") or "").strip()[:2000],
                          "options": opts,
                          "answer": ans, "score": max(1, min(100, score))})
        if len(questions) >= 60:
            break

    if not questions:
        return {"success": False, "detail": "객관식 문항을 찾지 못했습니다. 문제와 보기가 함께 보이는 자료여야 합니다."}

    return {"success": True, "questions": questions, "count": len(questions),
            "no_answer": no_answer, "pages": len(parts)}


@app.post("/api/admin/extract_answers_image", dependencies=[Depends(verify_admin)])
async def extract_answers_image(files: List[UploadFile] = File(...)):
    """정답표를 찍거나 캡처한 이미지에서 문항별 정답을 읽어낸다.
    해답지를 PDF로 만들어 올리는 것이 번거롭다는 요청으로 추가 — 화면을 캡처해
    그대로 붙여넣으면 된다. 여러 장을 한 번에 올려도 합쳐서 읽는다."""
    parts = []
    for f in files:
        if not f.filename:
            continue
        raw = await f.read()
        if raw:
            parts.append({"mime_type": f.content_type or "image/png", "data": raw})
    if not parts:
        return {"success": False, "detail": "이미지를 찾지 못했습니다."}

    prompt = """첨부된 이미지는 시험의 정답표(또는 해설지의 정답 부분)입니다.
문항 번호와 그 문항의 정답을 모두 읽어내세요.

[반드시 지킬 것]
- 오직 JSON만 출력하세요. 설명, 인사말, 코드블록 표시(```)를 절대 붙이지 마세요.
- 형식: {"answers": {"1": 3, "2": 5, "3": 1}}
- 키는 문항 번호를 큰따옴표로 감싼 문자열, 값은 1~5 사이의 정수입니다.
- ①②③④⑤ 같은 원문자는 1,2,3,4,5로 바꿔서 적으세요.
- 이미지에 보이지 않는 문항은 아예 넣지 마세요. 추측해서 채우지 마세요.
- 주관식이거나 번호로 읽을 수 없는 문항은 건너뛰세요.
- 이미지가 여러 장이면 모두 합쳐서 하나의 JSON으로 만드세요."""

    try:
        resp = await asyncio.to_thread(lambda: safe_generate([prompt] + parts))
        text = (resp.text or "").strip()
    except Exception as e:
        return {"success": False, "detail": f"이미지 분석 실패: {str(e)}"}

    # 코드블록이나 앞뒤 군말이 섞여 와도 JSON 덩어리만 뽑아낸다
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"success": False, "detail": "정답을 읽지 못했습니다. 번호와 정답이 또렷하게 보이는 이미지인지 확인해주세요."}

    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return {"success": False, "detail": "정답을 읽지 못했습니다. 조금 더 선명한 이미지로 다시 시도해주세요."}

    raw_answers = parsed.get("answers", parsed) or {}
    answers = {}
    for k, v in raw_answers.items():
        try:
            num = int(str(k).strip())
            val = int(str(v).strip())
        except (TypeError, ValueError):
            continue
        if num >= 1 and 1 <= val <= 5:
            answers[str(num)] = val

    if not answers:
        return {"success": False, "detail": "이미지에서 문항 번호와 정답을 찾지 못했습니다."}

    return {"success": True, "answers": answers, "count": len(answers),
            "max_no": max(int(k) for k in answers)}


@app.post("/api/exam/submit")
async def submit_exam(req: ExamSubmitRequest):
    if db is None:
        return {"success": False}

    existing = await asyncio.to_thread(
        lambda: list(
            db.collection("reports")
            .where("student_name", "==", req.student_name)
            .where("task_name", "==", req.title)
            .where("type", "==", "모의고사")
            .limit(1)
            .stream()
        )
    )
    if existing:
        return {"success": False, "detail": "이미 제출한 시험입니다."}

    doc = await asyncio.to_thread(lambda: db.collection("exams").document(req.title).get())
    data = doc.to_dict() if doc.exists else {}
    actual_score = 0
    wrongs = []

    details = []
    total_possible = 0
    if data:
        exam_data = json.loads(data.get("exam_data", "{}"))
        for i, q in enumerate(exam_data.get("questions", [])):
            student_ans = str(req.answers[i]).strip() if i < len(req.answers) else ""
            correct_ans = str(q.get("ans", "")).strip()
            point = int(q.get("score", 0) or 0)
            total_possible += point
            is_ok = bool(student_ans) and student_ans == correct_ans
            if is_ok:
                actual_score += point
            else:
                wrongs.append(i + 1)
            # 💡 학생이 제출 직후 "몇 점인지, 무엇을 틀렸는지"를 바로 보려면
            #    문항별 내 답/정답/배점이 필요해서 함께 돌려준다.
            details.append({
                "no": i + 1,
                "my": student_ans,
                "ans": correct_ans,
                "score": point,
                "ok": is_ok,
                "blank": not student_ans,
                "tier": str(q.get("tier", "") or ""),
            })

    await asyncio.to_thread(
        lambda: db.collection("reports").add(
            {
                "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "student_name": req.student_name,
                "school": req.school,
                "grade": req.grade,
                "task_name": req.title,
                "type": "모의고사",
                "score": actual_score,
                "wrongs": wrongs,
                "total_score": total_possible,
                "question_count": len(details),
                "correct_count": sum(1 for d in details if d["ok"]),
            }
        )
    )
    exam_xp = XP_REWARD_EXAM_BASE + actual_score // 2  # 💡 고득점자가 지나치게 빨리 레벨업하지 않도록 점수 반영 비중을 절반으로 축소
    s_ref = db.collection("students").document(req.student_name)
    s_doc = await asyncio.to_thread(s_ref.get)
    old_xp = s_doc.to_dict().get("xp", 0) if s_doc.exists else 0
    lvl_up = level_up_info(old_xp, exam_xp)
    await asyncio.to_thread(
        lambda: s_ref.set({"xp": firestore.Increment(exam_xp)}, merge=True)
    )
    return {
        "success": True,
        "score": actual_score,
        "total_score": total_possible,
        "wrongs": wrongs,
        "details": details,
        "correct_count": sum(1 for d in details if d["ok"]),
        "question_count": len(details),
        "video_url": data.get("video_url", ""),
        "explanation_text": data.get("explanation_text", ""),
        "level_up": lvl_up,
    }


# ─────────────────────────────────────────────────────────
# 관리자 - 학생별 모의고사 성적 분석
# (틀린 문제 / 난이도별 정답률 / 직전 시험 대비 변화)
# ─────────────────────────────────────────────────────────
# 문항 난이도(diff)는 실제 응시자 기준 정답률 구간으로 정의된다.
# a: 정답률 80~100 (하) — b: 65~79 (중) — c: 45~64 (상) — d: 20~44 (준킬러) — e: 0~19 (킬러)
DIFFICULTY_TIER_LABELS = {"a": "하", "b": "중", "c": "상", "d": "준킬러", "e": "킬러"}


def correct_rate_to_tier(correct_rate: float) -> str:
    """정답률(%)을 문항 난이도(a~e) 구간으로 변환."""
    if correct_rate >= 80:
        return "a"
    if correct_rate >= 65:
        return "b"
    if correct_rate >= 45:
        return "c"
    if correct_rate >= 20:
        return "d"
    return "e"


@app.get("/api/admin/exam_report/{student_name}")
def get_student_exam_report(student_name: str, _: bool = Depends(verify_admin)):
    if db is None:
        return {"success": False, "exams": []}

    try:
        # 💡 where() 두 개 + order_by()를 Firestore에 같이 요청하면 복합 색인이 없어
        # 쿼리가 실패한다. 정렬은 대신 아래에서 Python으로 처리해 색인 없이도 동작하게 함.
        report_docs = list(
            db.collection("reports")
            .where("student_name", "==", student_name)
            .where("type", "==", "모의고사")
            .stream()
        )
    except Exception as e:
        return {"success": False, "detail": f"성적 조회 실패: {e}", "exams": []}

    report_docs.sort(key=lambda r: r.to_dict().get("submitted_at") or "")

    def _safe_int(v, default=0):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    exam_cache: dict = {}

    def get_exam(title: str):
        if title not in exam_cache:
            doc = db.collection("exams").document(sanitize_doc_id(title)).get()
            exam_cache[title] = doc.to_dict() if doc.exists else None
        return exam_cache[title]

    results = []
    for r in report_docs:
        try:
            data = r.to_dict() or {}
            title = data.get("task_name") or ""
            wrongs = {_safe_int(w) for w in (data.get("wrongs") or [])}

            breakdown = {
                key: {"label": label, "total": 0, "correct": 0, "possible_score": 0, "wrong_nums": []}
                for key, label in DIFFICULTY_TIER_LABELS.items()
            }
            total_possible = 0

            exam = get_exam(title)
            if exam:
                try:
                    questions = json.loads(exam.get("exam_data") or "{}").get("questions", [])
                except Exception:
                    questions = []
                for i, q in enumerate(questions):
                    if not isinstance(q, dict):
                        continue
                    tier = q.get("diff", "a")
                    if tier not in breakdown:
                        tier = "a"
                    q_score = _safe_int(q.get("score"), 0)
                    breakdown[tier]["total"] += 1
                    breakdown[tier]["possible_score"] += q_score
                    total_possible += q_score
                    if (i + 1) in wrongs:
                        breakdown[tier]["wrong_nums"].append(i + 1)
                    else:
                        breakdown[tier]["correct"] += 1

            results.append({
                "title": title,
                "submitted_at": data.get("submitted_at") or "",
                "score": _safe_int(data.get("score"), 0),
                "total_possible": total_possible,
                "wrongs": sorted(wrongs),
                "breakdown": breakdown,
            })
        except Exception as e:
            print(f"exam_report: skip malformed report {r.id}: {e}")
            continue

    return {"success": True, "exams": results}


@app.post("/api/admin/exam/{title}/auto_difficulty")
async def auto_difficulty_from_photo(
    title: str,
    file: UploadFile = File(...),
    _: bool = Depends(verify_admin),
):
    """EBS 등에서 제공하는 오답률표 사진을 AI로 읽어, 해당 문항들의 난이도(diff)를
    실제 정답률 구간(a~e)으로 자동 반영한다. 사진에 없는 나머지 문항은 'a'(하)로 둔다."""
    if db is None:
        return {"success": False, "detail": "DB 오류"}

    safe_title = sanitize_doc_id(title)
    doc = await asyncio.to_thread(lambda: db.collection("exams").document(safe_title).get())
    if not doc.exists:
        return {"success": False, "detail": "해당 시험을 찾을 수 없습니다."}

    exam = doc.to_dict()
    try:
        exam_data = json.loads(exam.get("exam_data", "{}"))
    except Exception:
        return {"success": False, "detail": "시험 데이터 형식이 올바르지 않습니다."}

    questions = exam_data.get("questions", [])
    if not questions:
        return {"success": False, "detail": "이 시험에는 등록된 문항이 없습니다."}

    file_bytes = await file.read()
    prompt = """이 이미지는 모의고사/문제집의 오답률(정답률) 통계표입니다.
표에 나온 문항 번호와 오답률(%)을 정확히 읽어서, 다른 설명 없이 아래 형식의 JSON 배열만 출력하세요.

[{"number": 문항번호(정수), "wrong_rate": 오답률(0~100 사이 숫자, % 기호 없이)}, ...]

표에 나오지 않은 문항은 포함하지 마세요."""

    try:
        response = await asyncio.to_thread(
            safe_generate, [prompt, {"mime_type": file.content_type or "image/jpeg", "data": file_bytes}], False
        )
        raw = re.sub(r"^```(?:json)?|```$", "", response.text.strip(), flags=re.MULTILINE).strip()
        extracted = json.loads(raw)
        if not isinstance(extracted, list):
            raise ValueError("응답이 목록 형식이 아닙니다.")
    except Exception as e:
        return {"success": False, "detail": f"사진 분석에 실패했습니다: {e}"}

    applied = []
    for entry in extracted:
        try:
            num = int(entry.get("number"))
            wrong_rate = float(entry.get("wrong_rate"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not (1 <= num <= len(questions)):
            continue
        correct_rate = max(0.0, min(100.0, 100.0 - wrong_rate))
        tier = correct_rate_to_tier(correct_rate)
        questions[num - 1]["diff"] = tier
        applied.append({"number": num, "wrong_rate": wrong_rate, "tier": tier, "tier_label": DIFFICULTY_TIER_LABELS[tier]})

    # 표에 없는 나머지 문항은 기본값 'a'(하)로 설정
    applied_nums = {a["number"] for a in applied}
    for i, q in enumerate(questions):
        if (i + 1) not in applied_nums:
            q["diff"] = "a"

    exam_data["questions"] = questions
    await asyncio.to_thread(
        lambda: db.collection("exams").document(safe_title).set(
            {"exam_data": json.dumps(exam_data, ensure_ascii=False)}, merge=True
        )
    )

    return {
        "success": True,
        "total_questions": len(questions),
        "applied": sorted(applied, key=lambda x: x["number"]),
        "default_count": len(questions) - len(applied),
    }


# ─────────────────────────────────────────────────────────
# 관리자 - 퀴즈
# ─────────────────────────────────────────────────────────
@app.post("/api/admin/quiz")
async def create_quiz(request: Request, _: bool = Depends(verify_admin)):
    if db is None:
        return {"success": False, "detail": "DB 오류"}
    req = await request.json()
    title = req.get("title")
    if not title or not str(title).strip():
        raise HTTPException(status_code=400, detail="퀴즈 제목은 필수입니다.")

    safe_title = sanitize_doc_id(title)

    # 💡 수정하면서 제목을 바꾼 경우, 예전 이름의 퀴즈가 남아 둘 다 배포되어 버린다.
    #    old_title이 오면 그 문서를 지운다.
    old_title = str(req.get("old_title", "") or "").strip()
    if old_title and sanitize_doc_id(old_title) != safe_title:
        await asyncio.to_thread(lambda: db.collection("quizzes").document(sanitize_doc_id(old_title)).delete())

    # 고치는 경우에는 처음 만든 날짜를 그대로 둔다
    prev = await asyncio.to_thread(lambda: db.collection("quizzes").document(safe_title).get())
    created_at = (prev.to_dict() or {}).get("created_at") if prev.exists else None
    created_at = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    await asyncio.to_thread(
        lambda: db.collection("quizzes").document(safe_title).set(
            {
                "title": title,
                "deadline": req.get("deadline"),
                "time_limit": int(req.get("time_limit", 0)),
                "questions": req.get("questions", []),
                "created_at": created_at,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    )
    return {"success": True}


@app.post("/api/admin/quiz/image", dependencies=[Depends(verify_admin)])
async def upload_quiz_image(file: UploadFile = File(...)):
    """퀴즈 문항 하나에 붙일 그림(지문 캡처·도표 등)을 올린다."""
    if not file or not file.filename:
        return {"success": False, "detail": "파일이 없습니다."}
    raw = await file.read()
    if not raw:
        return {"success": False, "detail": "빈 파일입니다."}
    ctype = (file.content_type or "").lower()
    if not ctype.startswith("image/"):
        return {"success": False, "detail": "그림 파일만 붙일 수 있습니다."}
    try:
        url = save_bytes(raw, file.filename, "quiz", ctype)
    except HTTPException as e:
        return {"success": False, "detail": str(e.detail)}
    except Exception as e:
        return {"success": False, "detail": f"올리지 못했습니다: {e}"}
    return {"success": True, "url": url}


@app.get("/api/quizzes")
def get_quizzes():
    if db is None:
        return {"success": False, "quizzes": []}
    return {"success": True, "quizzes": [{"id": d.id, **d.to_dict()} for d in db.collection("quizzes").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}


@app.delete("/api/admin/quiz/{title}")
def delete_quiz(title: str, _: bool = Depends(verify_admin)):
    if db:
        db.collection("quizzes").document(title).delete()
    return {"success": True}


class QuizSubmitReq(BaseModel):
    school: str
    grade: str
    student_name: str
    title: str
    answers: list


@app.post("/api/quiz/submit")
async def submit_quiz(req: QuizSubmitReq):
    if db is None:
        return {"success": False}

    existing = await asyncio.to_thread(
        lambda: list(
            db.collection("reports")
            .where("student_name", "==", req.student_name)
            .where("task_name", "==", req.title)
            .where("type", "==", "타임어택 퀴즈")
            .limit(1)
            .stream()
        )
    )
    if existing:
        return {"success": False, "detail": "이미 완료한 퀴즈입니다."}

    doc = await asyncio.to_thread(lambda: db.collection("quizzes").document(req.title).get())
    actual_score = 0
    total_possible = 0
    details = []
    if doc.exists:
        for i, q in enumerate(doc.to_dict().get("questions", [])):
            raw = req.answers[i] if i < len(req.answers) else None
            # 0이나 빈 값은 '고르지 않음'으로 본다 (퀴즈는 0으로 초기화되어 있음)
            my_ans = "" if raw in (None, "", 0, "0") else str(raw).strip()
            correct_ans = str(q.get("answer", "")).strip()
            point = int(q.get("score", 0) or 0)
            total_possible += point
            is_ok = bool(my_ans) and my_ans == correct_ans
            if is_ok:
                actual_score += point
            options = [str(o) for o in (q.get("options") or [])]

            def pick(n):
                try:
                    idx = int(n) - 1
                except (TypeError, ValueError):
                    return ""
                return options[idx] if 0 <= idx < len(options) else ""

            # 💡 퀴즈를 내고 나면 점수도 오답도 볼 수 없다는 요청 — 문항 내용과
            #    내가 고른 보기·정답 보기를 그대로 실어 보낸다.
            details.append({
                "no": i + 1,
                "q_text": str(q.get("q_text", "")),
                "bogi": str(q.get("bogi", "") or ""),
                "image": str(q.get("image", "") or ""),
                "my": my_ans,
                "my_text": pick(my_ans),
                "ans": correct_ans,
                "ans_text": pick(correct_ans),
                "score": point,
                "ok": is_ok,
                "blank": not my_ans,
            })

    await asyncio.to_thread(
        lambda: db.collection("reports").add(
            {
                "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "student_name": req.student_name,
                "school": req.school,
                "grade": req.grade,
                "task_name": req.title,
                "type": "타임어택 퀴즈",
                "score": actual_score,
                "total_score": total_possible,
                "question_count": len(details),
                "correct_count": sum(1 for d in details if d["ok"]),
                "wrongs": [d["no"] for d in details if not d["ok"]],
            }
        )
    )
    quiz_xp = XP_REWARD_QUIZ_BASE + actual_score // 2  # 💡 고득점자가 지나치게 빨리 레벨업하지 않도록 점수 반영 비중을 절반으로 축소
    s_ref = db.collection("students").document(req.student_name)
    s_doc = await asyncio.to_thread(s_ref.get)
    old_xp = s_doc.to_dict().get("xp", 0) if s_doc.exists else 0
    lvl_up = level_up_info(old_xp, quiz_xp)
    await asyncio.to_thread(
        lambda: s_ref.set({"xp": firestore.Increment(quiz_xp)}, merge=True)
    )
    send_telegram_message(f"⏱️ [퀴즈 완료]\n{req.student_name} 학생이 '{req.title}' 퀴즈를 완료했습니다. (점수: {actual_score}점)")
    return {
        "success": True,
        "score": actual_score,
        "total_score": total_possible,
        "details": details,
        "correct_count": sum(1 for d in details if d["ok"]),
        "question_count": len(details),
        "wrongs": [d["no"] for d in details if not d["ok"]],
        "level_up": lvl_up,
    }


# ─────────────────────────────────────────────────────────
# 난이도별 출제 원칙 (원장님 지정)
# ─────────────────────────────────────────────────────────
DIFFICULTY_PRINCIPLES = {
    "killer": (
        "킬러 문항 (최상위권 변별)",
        "지문의 정보를 고도로 비틀고 외부 사례를 결합하여 완벽한 논리적 이해를 요구합니다.\n"
        "- 순서 및 인과 도치: 지문에 제시된 인과, 순서, 목적과 방법 등의 내용을 교묘하게 순서를 바꾸어 오답 선지를 설계합니다.\n"
        "- 대조되는 정보의 교차 함정: 두 개 이상의 대상에 대한 공통점과 차이점을 묻는 문제로, 대조되는 정보들의 차이점 중 하나를 섞어서 문제를 내거나 숨겨진 공통점을 찾도록 유도합니다.\n"
        "- 심층적 추론과 해석: 지문에 직접적으로 명시되지 않은 정보라도 주어진 명제와 전제들을 결합하여 논리적으로 타당하게 이끌어 낼 수 있는 생략된 정보를 묻습니다.\n"
        "- 적용적, 비판적 이해: 지문에서 파악한 원리를 구체적인 사례(도표, 그래프, 예시 등)에 대입하여 문제를 해결하게 하거나, 특정 관점에서 다른 관점의 논리적 타당성을 비판하고 평가하도록 출제합니다.",
    ),
    "semi": (
        "준킬러 문항 (상위권 변별)",
        "킬러 문항과 동일한 출제 원리를 적용하되, 정답을 도출하기 위한 단서를 조금 더 명시적으로 제공합니다.\n"
        "- 킬러 문항처럼 순서/인과 도치, 대조 정보 분석, 심층적 추론, 비판적 이해의 원리를 바탕으로 문제를 출제합니다.\n"
        "- 킬러 문항보다는 매력적인 오답(함정)의 개수를 줄이거나 보기(예시)의 복잡도를 낮추어 체감 난이도를 조절합니다.",
    ),
    "high": (
        "난이도 상 (핵심 구조 및 재구성 파악)",
        "지문의 뼈대를 이해하고, 다른 표현으로 바뀐 정보를 정확히 찾아내는 능력을 평가합니다.\n"
        "- 고급 사실적 이해: 지문에 명시된 정보의 일치·불일치를 확인하되, 지문의 정보를 다른 어휘나 문장 구조로 재구성(Paraphrasing)하여 선지의 참·거짓을 판별하게 합니다.\n"
        "- 거시적 구조 파악: 문단별 핵심어, 글 전체의 중심 내용, 표제 및 부제, 글의 전개 방식(서술 방식) 등 지문의 뼈대와 숲을 보는 능력을 묻는 문항으로 설계합니다.",
    ),
    "mid": (
        "난이도 중 (표준 이해력 평가)",
        "상 난이도와 동일한 평가 요소를 가지나, 지문의 문장을 덜 꼬아내어 직관적인 정답 찾기가 가능하도록 출제합니다.\n"
        "- 일반적 사실적 이해: 지문 내용의 일치·불일치를 확인하는 가장 기본적인 문항을 출제합니다.\n"
        "- 주제 및 요지 파악: 글 전체의 중심 내용이나 문단의 요지를 찾는 문제를 평이한 수준의 선지로 구성합니다.",
    ),
    "low": (
        "난이도 하 (기본 내용 확인)",
        "글을 끝까지 읽었는지 확인하는 수준의 가장 기본적인 문항입니다.\n"
        "- 지문의 내용을 단순하게 사실적으로 묻는 문제로 출제합니다.\n"
        "- 복잡한 추론이나 어휘의 변형 없이, 지문에 있는 표현을 거의 그대로 선지에 활용하여 정답을 직관적으로 고를 수 있도록 구성합니다.",
    ),
}


# ─────────────────────────────────────────────────────────
# 관리자 - 문제 생성 스트리밍
# ─────────────────────────────────────────────────────────
@app.post("/api/admin/generate_stream")
async def generate_stream(
    q_mode: str = Form(...),
    q_types: str = Form(...),
    cnt_killer: int = Form(0),
    cnt_semi: int = Form(0),
    cnt_high: int = Form(0),
    cnt_mid: int = Form(0),
    cnt_low: int = Form(0),
    q_text: str = Form(""),
    q_texts: str = Form(""),
    q_principle: str = Form(""),
    start_num: int = Form(1),
    source_counts: str = Form(""),
    files: Optional[List[UploadFile]] = File(None),
    _: bool = Depends(verify_admin),
):
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
    start_num = max(1, start_num)

    # 💡 한 번에 너무 많은 문항을 요청하면 응답이 길어져 품질이 떨어지고 실패/비용 부담도 커져서,
    # 20문항씩 나눠 여러 번 요청한 뒤 결과를 합친다.
    QUESTIONS_PER_BATCH = 20

    # 난이도를 미리 섞어둔다 — 자료마다 난이도가 골고루 섞이고,
    # 문항이 난이도 순서대로 줄 서는 것도 자연히 방지된다.
    tier_pool = (
        ["killer"] * cnt_killer + ["semi"] * cnt_semi + ["high"] * cnt_high
        + ["mid"] * cnt_mid + ["low"] * cnt_low
    )
    random.shuffle(tier_pool)

    def build_difficulty_block(tiers):
        """이번 배치에 실제로 포함된 난이도만 원칙과 함께 프롬프트에 싣는다."""
        if q_mode != "신규" or not tiers:
            return ""
        sections = []
        for key in ("killer", "semi", "high", "mid", "low"):
            cnt = tiers.count(key)
            if cnt > 0:
                sections.append(f"■ {DIFFICULTY_PRINCIPLES[key][0]} — {cnt}문항\n{DIFFICULTY_PRINCIPLES[key][1]}")
        return "\n\n[난이도별 출제 원칙 - 지정된 문항 수와 출제 기준을 반드시 지켜서 출제하세요]\n" + "\n\n".join(sections)

    types_block = ""
    if q_mode == "신규" and q_types.strip():
        types_block = f"\n\n[문제 유형]\n다음 유형으로만 문제를 구성하세요: {q_types}"

    principle_block = ""
    if q_principle.strip():
        principle_block = f"""
[출제 원칙 - 원장님이 지정한 지침이므로 아래 형식 규칙 다음으로 최우선 반영]
{q_principle.strip()}
"""

    option_quality_block = """
[선지 품질 기준 - 반드시 지켜야 함]
- 선택지 번호는 반드시 원문자 ①②③④⑤만 사용하세요. "1)", "2)", "1.", "가." 등 다른 번호 형식은 절대 쓰지 마세요.
- 5개 선지는 길이와 문장 구조, 서술 수준을 서로 비슷하게 맞추세요. 정답만 유독 길거나 자세해서 티가 나면 안 됩니다.
- 각 문항의 정답은 지문 내용과 명확하게 일치/도출되는 단 하나여야 합니다. 정답이 여러 개로 해석되거나 애매한 문항은 만들지 마세요.
- 오답 선지도 그럴듯하게 구성하세요: 지문의 다른 부분과 살짝 뒤바꾸거나, 그럴듯하지만 틀린 인과관계를 넣거나, 지문 내용을 미묘하게 왜곡해서 만드세요. 지문과 전혀 무관하거나 상식적으로 말이 안 되는 오답은 넣지 마세요.
- 정답은 반드시 지문 내용만으로 판단해서 정하세요. 절대로 "①②③④⑤①②③④⑤..."처럼 번호를 순서대로 반복하거나, 오름차순/내림차순 등 예측 가능한 규칙으로 정답 번호를 미리 정해두지 마세요. 정답 번호가 문항마다 규칙적인 패턴을 이루면 학생이 지문을 읽지 않고도 정답을 맞힐 수 있으므로 절대 금지입니다. (특정 번호가 한쪽으로 심하게 몰리는 것도 피해야 하지만, 그보다 "패턴이 생기지 않는 것"이 훨씬 중요합니다.)
- [정답 및 해설]에서는 정답 근거와 함께, 왜 나머지 선지들이 틀렸는지도 지문의 구체적인 부분을 근거로 짧게 설명하세요.
- [보기] 박스는 그 문항을 풀기 위해 실제로 별도 참고자료(도표, 추가 지문, 통계 등)가 꼭 필요한 경우에만 사용하세요. 대부분의 문항에는 [보기]가 필요 없으니 억지로 만들지 마세요. 해설·정답표 등 다른 어떤 곳에도 [보기]나 박스형 서식을 쓰지 마세요.
- 문항은 난이도 순서(킬러→준킬러→...→하 또는 그 반대)대로 배치하지 말고, 지정된 난이도별 문항 수는 정확히 지키되 문항이 나오는 순서는 섞어서 배치하세요. 예를 들어 1번이 쉬운 문제, 2번이 어려운 문제, 3번이 중간 난이도인 식으로 난이도를 예측할 수 없게 구성하세요."""

    exam_style_block = """
[시험지 형식 - 실제 학교 시험지/주간지 형식을 그대로 따르세요]
- 지문 앞에는 반드시 "※ 다음 글을 읽고 물음에 답하시오." 같은 안내 발문을 붙이세요. (시(詩)나 짧은 글이면 "※ 다음을 읽고 물음에 답하시오."도 가능)
- 문학 작품(시, 소설, 수필 등)이라면 지문 끝에 반드시 출처를 표기하세요. 형식은 "- 윤동주, 「길」" 처럼 낫표(「 」)를 사용합니다. 비문학 지문은 출처를 쓰지 않습니다.
- 지문 안의 특정 구절이나 단어를 묻는 문항을 낼 때는, 지문의 해당 위치에 ㉠ ㉡ ㉢ (구절/단어용) 또는 ⓐ ⓑ ⓒ (어휘·표현용) 기호를 직접 표시해 넣고, 발문에서 그 기호를 가리키세요. 예: "㉠에 대한 이해로 가장 적절한 것은?", "문맥상 ⓐ와 바꿔 쓰기에 가장 적절한 것은?"
- 지문을 여러 덩어리로 나눠 묻는 문항(구성/전개 방식, 부분별 이해)을 낼 때는, 지문의 각 구획 앞에 [A] [B] [C] [D] [E] 표시를 넣고 발문에서 "[A]~[E]에 대한 이해로 적절하지 않은 것은?" 처럼 가리키세요. 시(詩)는 연 단위, 산문은 문단 단위로 나눕니다.
- 발문은 실제 시험지 문체를 쓰세요: "~에 대한 이해로 가장 적절한 것은?", "~에 대한 설명으로 적절하지 않은 것은?", "윗글과 [보기]를 비교한 내용으로 가장 적절한 것은?", "밑줄 친 시어들 중, 시적 의미와 기능이 ㉠과 가장 유사한 것은?" 등.
- 전체 문항 중 일부는 "적절하지 않은 것은?" 형태의 부정 발문으로 내세요. 모든 문항을 긍정 발문으로만 구성하지 마세요.
- [보기]를 쓰는 문항은 주로 '다른 작품/자료를 제시하고 윗글과 비교'하는 유형입니다. 이때 [보기] 안의 인용 작품에도 "- 김소월, 「나의 집」" 처럼 출처를 표기하세요."""

    example_block = """
[좋은 문항 예시 - 아래와 같은 형식/수준으로 출제하세요. 내용과 문항 번호(1번)는 예시일 뿐이며, 실제로는 주어진 지문 내용과 지정된 시작 번호를 따르세요]
[지문]
※ 다음 글을 읽고 물음에 답하시오.

[A]
잃어버렸습니다.
무얼 어디다 잃었는지 몰라
두 손이 주머니를 더듬어
㉠길에 나아갑니다.

[B]
돌과 돌과 돌이 끝없이 연달아
길은 돌담을 끼고 갑니다.

[C]
풀 한 포기 없는 이 길을 걷는 것은
담 저 쪽에 ⓐ내가 남아 있는 까닭이고

- 윤동주, 「길」

(※ 실제로는 주어진 지문 전체를 한 글자도 바꾸지 말고 그대로 싣고, 위처럼 구획 표시와 기호를 넣습니다. 비문학 지문이면 출처 표기는 생략합니다.)

1. [A]~[C]에 대한 이해로 적절하지 않은 것은?
① [A]에서 화자는 잃어버린 대상을 알지 못한 상태로 그것을 찾기 위한 태도를 보이고 있군.
② [B]에서 길은 공간적으로 연속되지만 돌담으로 인해 단절감을 함께 자아내고 있군.
③ [C]에서 화자는 길을 걷는 행위의 이유를 담 저쪽의 존재와 연결 짓고 있군.
④ [A]와 [C]는 모두 화자가 상실을 인식하고 있음을 드러내고 있군.
⑤ [B]에서 화자는 길을 걷기를 포기하고 돌담 안쪽으로 돌아서고 있군.

2. 문맥을 고려할 때 ㉠의 의미로 가장 적절한 것은?
① 화자가 잃어버린 대상을 되찾기 위해 나아가는 삶의 여정
② 화자가 타인과의 관계를 회복하기 위해 마련한 만남의 장소
③ 화자가 과거의 기억을 지우기 위해 선택한 도피의 통로
④ 화자가 자연과 하나 되기 위해 찾아낸 안식의 공간
⑤ 화자가 현실의 고통을 잊기 위해 상상해 낸 관념의 세계

[정답 및 해설]
1. 정답 ⑤
[B]는 길이 돌담을 끼고 끝없이 이어지는 모습을 제시할 뿐, 화자가 길 걷기를 포기하거나 돌아선다는 내용은 나타나 있지 않으므로 ⑤가 적절하지 않다. ①은 [A]의 "무얼 어디다 잃었는지 몰라"와 "길에 나아갑니다"에서 확인된다. ②는 돌담이 길을 따라 이어지며 경계를 이루는 데서 알 수 있다. ③은 [C]의 "담 저 쪽에 내가 남아 있는 까닭"에서 드러난다. ④는 [A]의 "잃어버렸습니다"와 [C]의 "잃은 것"이라는 인식에서 확인된다.

2. 정답 ①
㉠'길'은 화자가 잃어버린 것을 찾기 위해 걸어 나가는 공간이며, 시 전체에서 삶의 여정을 상징하므로 ①이 적절하다. ② 타인과의 만남을 위한 장소라는 근거는 없다. ③ 기억을 지우려는 도피와는 반대로 잃은 것을 찾으려는 태도가 나타난다. ④ 자연과의 합일을 지향하는 모습은 드러나지 않는다. ⑤ 관념적 상상 공간이 아니라 화자가 실제로 걸어 나가는 공간으로 형상화되어 있다.

[정답표]
1번 ⑤
2번 ①"""

    def build_prompt(tiers, batch_start, include_passage, source=None, multi=False):
        n = len(tiers) if tiers else total
        batch_end = batch_start + n - 1
        source = source or {"label": "", "text": q_text}
        if include_passage:
            order_rule = "- 반드시 다음 순서로, 각 섹션을 정확히 한 번씩만 출력하세요: [지문] (문제 출제에 사용한 지문 전체를 한 글자도 바꾸거나 생략하지 말고 그대로 먼저 제시) → 문항들(①②③④⑤ 선지 포함) → [정답 및 해설] → [정답표]. [지문]이 없으면 학생이 무엇을 보고 푸는지 알 수 없으니 절대 빠뜨리지 마세요."
        else:
            order_rule = "- 지문은 앞 회차에서 이미 제시했으므로 [지문] 섹션을 절대 다시 출력하지 마세요. 곧바로 문항부터 시작해서 문항들 → [정답 및 해설] → [정답표] 순서로만 출력하세요. 단, 지문에 표시했던 ㉠ ⓐ [A] 등의 기호는 앞 회차와 동일한 위치를 가리키도록 일관되게 사용하세요."
        # 자료를 여러 개 올린 경우, 이번 회차에는 그중 하나만 첨부해서 보낸다.
        # 그래도 "다른 자료를 기웃거리지 말라"고 못 박아 둬야 결과가 안정적이다.
        source_block = ""
        if multi:
            if source["parts"]:
                where = "지금 첨부된 이 자료"
                spread = f"\n- 이 자료에 지문이 여러 편 담겨 있다면, {n}문항이 그 지문들에 고르게 걸치도록 배분하세요."
            else:
                where = "아래에 주어진 이 지문"
                spread = ""
            source_block = f"""
[이번 회차에 사용할 자료 - 반드시 지킬 것]
- 이번에 출제할 대상은 '{source["label"]}' 하나뿐입니다. {where}의 내용만으로 {n}문항을 모두 출제하세요.{spread}
- 여기에 없는 다른 작품이나 글을 끌어와서 출제하지 마세요. 앞 회차에서 다룬 지문도 다시 쓰지 마세요.
"""

        return f"""다음 지문을 바탕으로 {n}문항의 객관식 문제를 출제해줘.

[출력 형식 규칙 - 반드시 지켜야 함]
- 마크다운 문법을 절대 사용하지 마세요. 굵게 표시하는 ** 기호, 제목에 쓰는 # 또는 ## 기호를 쓰지 마세요.
- 부등호/꺾쇠 기호 <, >는 절대 사용하지 마세요.
- 순수한 일반 텍스트로만 작성하세요. 강조가 필요하면 기호 없이 줄바꿈이나 문장으로 구분하세요.
{order_rule}
- 문항 번호는 1번이 아니라 반드시 {batch_start}번부터 시작해서 {batch_end}번까지 순서대로 매기세요 (예: {batch_start}. ... {batch_start + 1}. ... 식으로). [정답 및 해설]과 [정답표]에서도 같은 번호를 그대로 사용하세요.
{exam_style_block}
{option_quality_block}
{example_block}
{build_difficulty_block(tiers)}{types_block}
{principle_block}{source_block}
{source["text"]}"""

    # 💡 자료를 '출제 원천' 단위로 나눈다.
    #    예전에는 여러 파일을 한 번에 통째로 붙여서 보냈는데, 그러면 AI가 그중
    #    한 파일만 붙잡고 전 문항을 뽑아버렸다. 이제는 자료 하나당 따로 요청을 보내고,
    #    그 자료에서 몇 문항을 낼지도 원장님이 정한 수를 그대로 따른다.
    # 붙여넣은 지문들 — 한 덩어리로 합치지 않고 지문마다 따로 출제한다.
    passages = []
    if q_texts.strip():
        try:
            parsed = json.loads(q_texts)
            if isinstance(parsed, list):
                passages = [str(t).strip() for t in parsed if str(t).strip()]
        except (ValueError, TypeError):
            passages = []
    if not passages and q_text.strip():
        passages = [q_text.strip()]

    sources = []
    for i, text in enumerate(passages):
        head = " ".join(text.split())[:24]
        label = f"지문 {i + 1}" + (f" — {head}…" if head else "")
        sources.append({"label": label, "text": text, "parts": []})
    if files:
        for f in files:
            if f.filename:
                file_bytes = await f.read()
                sources.append({
                    "label": f.filename,
                    "text": "",
                    "parts": [{"mime_type": f.content_type or "application/octet-stream", "data": file_bytes}],
                })
    if not sources:
        sources = [{"label": "", "text": q_text, "parts": []}]
    # 지문 하나 + 파일 없음 = 예전과 똑같은 상황이므로 자료 구분 문구를 붙이지 않는다
    if len(sources) == 1 and not sources[0]["parts"]:
        sources[0]["label"] = ""

    def split_evenly(amount: int, n: int) -> list:
        """20문항을 6개 자료에 나누면 4,4,3,3,3,3 처럼 최대한 고르게 쪼갠다."""
        if n <= 0:
            return []
        base, rem = divmod(max(0, amount), n)
        return [base + (1 if i < rem else 0) for i in range(n)]

    # 원장님이 자료별 문항 수를 정해 보냈으면 그대로 쓰고, 아니면 고르게 나눈다.
    counts = None
    if source_counts.strip():
        try:
            parsed = json.loads(source_counts)
            if (isinstance(parsed, list) and len(parsed) == len(sources)
                    and all(isinstance(x, int) and x >= 0 for x in parsed)
                    and sum(parsed) == total):
                counts = parsed
        except (ValueError, TypeError):
            counts = None
    if counts is None:
        counts = split_evenly(total, len(sources))
    for s, c in zip(sources, counts):
        s["count"] = c

    def split_sections(text: str):
        """AI 출력에서 (지문+문항) / [정답 및 해설] / [정답표] 세 부분을 분리한다."""
        body, expl, table = text, "", ""
        if "[정답표]" in body:
            body, table = body.rsplit("[정답표]", 1)
        if "[정답 및 해설]" in body:
            body, expl = body.split("[정답 및 해설]", 1)
        return body.strip(), expl.strip(), table.strip()

    async def iter_batches():
        try:
            model = get_best_model(prefer_quality=True)
        except Exception as e:
            yield f"❌ AI 생성 실패: {e}"
            return

        explanations, answer_tables = [], []
        cursor = start_num
        tier_cursor = 0
        active = [s for s in sources if s["count"] > 0] or sources[:1]
        multi = len(active) > 1

        for src_idx, source in enumerate(active):
            n_src = source["count"] if source["count"] > 0 else total
            src_tiers = tier_pool[tier_cursor:tier_cursor + n_src]
            tier_cursor += n_src

            # 한 자료에서 20문항이 넘으면 그 자료 안에서 다시 나눠 요청한다
            sub_batches = [src_tiers[i:i + QUESTIONS_PER_BATCH]
                           for i in range(0, len(src_tiers), QUESTIONS_PER_BATCH)] or [[]]

            if multi:
                yield f"\n※ [{source['label']}] 자료에서 {n_src}문항\n\n"

            for b_idx, tiers in enumerate(sub_batches):
                prompt = build_prompt(tiers, cursor, include_passage=(b_idx == 0),
                                      source=source, multi=multi)
                try:
                    resp = await asyncio.to_thread(model.generate_content, [prompt] + source["parts"])
                    text = resp.text
                except Exception as e:
                    yield f"\n\n❌ {cursor}번부터 출제하는 중 오류가 발생했습니다: {e}"
                    return

                body, expl, table = split_sections(text)
                if body:
                    yield body + "\n\n"
                if expl:
                    explanations.append(expl)
                if table:
                    answer_tables.append(table)
                cursor += len(tiers) if tiers else total

        if explanations:
            yield "[정답 및 해설]\n" + "\n\n".join(explanations) + "\n\n"
        if answer_tables:
            yield "[정답표]\n" + "\n".join(answer_tables) + "\n"

    return StreamingResponse(iter_batches(), media_type="text/plain")


@app.post("/api/admin/generate_explainer")
async def generate_explainer(
    q_text: str = Form(""),
    files: Optional[List[UploadFile]] = File(None),
    _: bool = Depends(verify_admin),
):
    """학생에게 그대로 배포할 수 있는 지문 해설 자료 생성.
    (원문 지문 / 쉬운 설명 / 꼭 알아야 할 내용 / 출제 포인트 / 헷갈리기 쉬운 내용)"""
    source_text = q_text.strip()
    file_parts = []
    if files:
        for f in files:
            if not f.filename:
                continue
            file_bytes = await f.read()
            extracted = ""
            if f.filename.lower().endswith(".pdf"):
                try:
                    doc = fitz.open(stream=file_bytes, filetype="pdf")
                    extracted = "".join(page.get_text() for page in doc)
                except Exception:
                    extracted = ""
            if extracted.strip():
                source_text = (source_text + "\n\n" + extracted).strip() if source_text else extracted.strip()
            else:
                # PDF 텍스트 추출이 안 됐거나(스캔본 등) 이미지 파일이면 원본을 그대로 AI에게 보여준다
                file_parts.append({"mime_type": f.content_type or "application/octet-stream", "data": file_bytes})

    if not source_text.strip() and not file_parts:
        def empty_response():
            yield "❌ 지문 내용을 입력하거나 자료 파일을 먼저 업로드해주세요."

        return StreamingResponse(empty_response(), media_type="text/plain")

    prompt = f"""아래 지문을 학생들에게 그대로 나눠줄 수 있는 해설 자료로 정리해줘.

[출력 형식 규칙 - 반드시 지켜야 함]
- 마크다운 문법을 절대 사용하지 마세요. 굵게 표시하는 ** 기호, 제목에 쓰는 # 또는 ## 기호를 쓰지 마세요.
- 부등호/꺾쇠 기호 <, >는 절대 사용하지 마세요.
- 순수한 일반 텍스트로만 작성하고, 아래 5개 섹션을 반드시 이 순서대로, 각 제목을 대괄호로 표시해서 작성하세요.

[원문 지문]
아래 [지문]에 주어진 내용을 한 글자도 바꾸거나 요약하지 말고 그대로 옮기세요. 파일에서 추출되어 줄바꿈이나 띄어쓰기가 어색한 부분이 있다면 문단 구분만 자연스럽게 정리하고, 문장 내용 자체는 절대 고치지 마세요.

[쉬운 설명]
지문의 핵심 내용과 전체 흐름을 학생 눈높이에 맞춰 쉬운 말로 풀어서 설명하세요. 어려운 개념이나 용어가 있으면 비유나 구체적인 예시를 들어 이해를 도와주세요.

[꼭 알아야 할 내용]
이 지문에서 학생이 반드시 이해하고 넘어가야 하는 핵심 포인트를 항목별로 정리하세요.

[출제 포인트]
이 지문으로 실제 시험(내신/모의고사)을 낸다면 주로 어떤 부분이, 어떤 방식으로 출제되는지 구체적으로 설명하세요.

[헷갈리기 쉬운 내용]
학생들이 이 지문에서 자주 착각하거나 헷갈려하는 지점을 짚어주고, 왜 헷갈리는지와 정확한 이해를 함께 제시하세요.

[지문]
{source_text}"""

    contents = [prompt] + file_parts
    try:
        # 💡 비용 절감: 해설자료는 빠른(저렴한) 모델 사용. 품질이 가장 중요한 '문제 출제'에만 pro 모델을 씀
        model = get_best_model()
        response = model.generate_content(contents, stream=True)

        def iter_response():
            try:
                for chunk in response:
                    if chunk.text:
                        yield chunk.text
            except Exception as stream_err:
                # 💡 스트리밍 도중(레이트리밋, 세이프티 차단 등) 실패도 화면에 실제 사유가 보이게 함
                yield f"\n\n❌ AI 생성 중 오류가 발생했습니다: {stream_err}"

        return StreamingResponse(iter_response(), media_type="text/plain")
    except Exception as e:
        # 💡 이전엔 무슨 오류든 똑같은 안내문만 보여줘서 원인 파악이 불가능했음.
        # 실제 예외 메시지(모델 이름 오류, 429 레이트리밋, 세이프티 차단 등)를 그대로 노출.
        err_msg = str(e)

        def err_response():
            yield f"❌ AI 생성 실패: {err_msg}"

        return StreamingResponse(err_response(), media_type="text/plain")


# ─────────────────────────────────────────────────────────
# 관리자 - 숙제 및 기타
# ─────────────────────────────────────────────────────────
@app.get("/api/homeworks")
def get_homeworks():
    if db is None:
        return {"success": False, "homeworks": []}
    return {"success": True, "homeworks": [{"id": d.id, **d.to_dict()} for d in db.collection("homeworks").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}


@app.post("/api/admin/homework")
async def create_homework(
    title: str = Form(...),
    desc: str = Form(""),
    answer_text: str = Form(""),
    answer_file: Optional[UploadFile] = File(None),
    _: bool = Depends(verify_admin),
):
    if db is None:
        return {"success": False}
    ans_url = ""
    if answer_file and answer_file.filename:
        ans_url = await asyncio.to_thread(save_bytes, await answer_file.read(), answer_file.filename, "homeworks", answer_file.content_type)

    safe_title = sanitize_doc_id(title)
    await asyncio.to_thread(
        lambda: db.collection("homeworks").document(safe_title).set(
            {
                "title": title,
                "desc": desc,
                "answer_text": answer_text,
                "answer_file": ans_url,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    )
    return {"success": True}


@app.delete("/api/admin/homework/{title}")
def delete_homework(title: str, _: bool = Depends(verify_admin)):
    if db:
        db.collection("homeworks").document(title).delete()
    return {"success": True}


@app.post("/api/homework/submit")
async def submit_homework(
    school: str = Form(...),
    grade: str = Form(...),
    student_name: str = Form(...),
    title: str = Form(...),
    files: List[UploadFile] = File(...),
):
    if db is None:
        return {"success": False}

    existing = await asyncio.to_thread(
        lambda: list(
            db.collection("reports")
            .where("student_name", "==", student_name)
            .where("task_name", "==", title)
            .where("type", "==", "과제 제출")
            .limit(1)
            .stream()
        )
    )

    file_urls = []
    for f in files:
        if f.filename:
            file_bytes = await f.read()
            file_urls.append(await asyncio.to_thread(save_bytes, file_bytes, f.filename, "homeworks", f.content_type))

    await asyncio.to_thread(
        lambda: db.collection("reports").add(
            {
                "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "student_name": student_name,
                "school": school,
                "grade": grade,
                "task_name": title,
                "type": "과제 제출",
                "score": "제출완료",
                "file_url": ",".join(file_urls),
            }
        )
    )

    lvl_up = None
    if not existing:
        s_ref = db.collection("students").document(student_name)
        s_doc = await asyncio.to_thread(s_ref.get)
        old_xp = s_doc.to_dict().get("xp", 0) if s_doc.exists else 0
        lvl_up = level_up_info(old_xp, XP_REWARD_HOMEWORK)
        await asyncio.to_thread(
            lambda: s_ref.set({"xp": firestore.Increment(XP_REWARD_HOMEWORK)}, merge=True)
        )

    doc = await asyncio.to_thread(lambda: db.collection("homeworks").document(title).get())
    return {"success": True, "answer_file": doc.to_dict().get("answer_file", "") if doc.exists else "", "level_up": lvl_up}

@app.get("/api/board")
def get_board():
    if db is None: return {"success": False, "posts": []}
    return {"success": True, "posts": [{"id": d.id, **d.to_dict()} for d in db.collection("board").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

@app.post("/api/admin/board", dependencies=[Depends(verify_admin)])
async def create_board_post_admin(title: str = Form(...), desc: str = Form(""), file: Optional[UploadFile] = File(None)):
    if db is None: return {"success": False}
    file_url = ""
    if file and file.filename: file_url = await asyncio.to_thread(save_bytes, await file.read(), file.filename, "board", file.content_type)
    await asyncio.to_thread(lambda: db.collection("board").add({"title": title, "desc": desc, "file_url": file_url, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}))
    return {"success": True}

@app.delete("/api/admin/board/{post_id}", dependencies=[Depends(verify_admin)])
def delete_board_post_admin(post_id: str):
    if db: db.collection("board").document(post_id).delete()
    return {"success": True}

@app.get("/api/lectures")
def get_lectures():
    if db is None: return {"success": False, "lectures": []}
    return {"success": True, "lectures": [{"id": d.id, **d.to_dict()} for d in db.collection("lectures").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

class LectureRequest(BaseModel): title: str; desc: str; video_url: str
@app.post("/api/admin/lecture", dependencies=[Depends(verify_admin)])
def create_lecture_admin(req: LectureRequest):
    if db: db.collection("lectures").add({"title": req.title, "desc": req.desc, "video_url": req.video_url, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.delete("/api/admin/lecture/{lecture_id}", dependencies=[Depends(verify_admin)])
def delete_lecture_admin(lecture_id: str):
    if db: db.collection("lectures").document(lecture_id).delete()
    return {"success": True}

@app.get("/api/knowledge")
def get_knowledge():
    if db is None: return {"success": False, "knowledge": []}
    return {"success": True, "knowledge": [{"id": d.id, **d.to_dict()} for d in db.collection("knowledge").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}


@app.get("/api/admin/ai_guidelines", dependencies=[Depends(verify_admin)])
def get_ai_guidelines_admin():
    return {"success": True, "text": get_ai_guidelines()}


class AIGuidelinesRequest(BaseModel):
    text: str


@app.post("/api/admin/ai_guidelines", dependencies=[Depends(verify_admin)])
async def save_ai_guidelines(req: AIGuidelinesRequest):
    if db is None:
        return {"success": False}
    await asyncio.to_thread(lambda: db.collection("settings").document("ai_guidelines").set({"text": req.text.strip()}))
    return {"success": True}

@app.post("/api/admin/knowledge", dependencies=[Depends(verify_admin)])
async def add_knowledge_admin(title: str = Form(...), content: str = Form(""), files: Optional[List[UploadFile]] = File(None)):
    if db is None: return {"success": False}
    final_content = content
    if files:
        for file in files:
            if file.filename:
                try:
                    res = await asyncio.to_thread(safe_generate, ["이 문서의 핵심 지식을 요약해줘.", {"mime_type": file.content_type, "data": await file.read()}], False)
                    final_content += f"\n\n[{file.filename} 분석]\n{res.text}"
                except: pass
    await asyncio.to_thread(lambda: db.collection("knowledge").add({"title": title, "content": final_content, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}))
    return {"success": True}

@app.post("/api/admin/knowledge/bulk", dependencies=[Depends(verify_admin)])
async def add_knowledge_bulk_admin(files: List[UploadFile] = File(...)):
    if db is None: return {"success": False}
    processed = 0
    for file in files:
        if file.filename:
            try:
                file_bytes = await file.read()
                title = file.filename.rsplit('.', 1)[0]
                extracted_text = ""
                if file.filename.lower().endswith(".pdf"):
                    doc = fitz.open(stream=file_bytes, filetype="pdf")
                    for page in doc: extracted_text += page.get_text()
                else: extracted_text = file_bytes.decode('utf-8', errors='ignore')
                res = await asyncio.to_thread(safe_generate, [f"다음 문서의 핵심을 요약해줘.\n{extracted_text[:100000]}"], False)
                await asyncio.to_thread(lambda: db.collection("knowledge").add({"title": title, "content": f"[{title} 요약]\n{res.text}", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}))
                processed += 1
            except: pass
    return {"success": True, "count": processed}

class KnowledgeUpdateReq(BaseModel):
    id: str
    title: str
    content: str


@app.post("/api/admin/knowledge/update", dependencies=[Depends(verify_admin)])
def update_knowledge_admin(req: KnowledgeUpdateReq):
    """이미 올려둔 자료의 제목·내용을 고친다.
    예전에는 수정이 없어서 지우고 다시 올려야 했고, 그때마다 등록일이 바뀌어
    목록 순서가 뒤엉켰다. 여기서는 등록일을 건드리지 않고 내용만 갈아끼운다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    title = req.title.strip()
    content = req.content.strip()
    if not title:
        return {"success": False, "detail": "자료 제목을 입력해주세요."}
    if not content:
        return {"success": False, "detail": "자료 내용이 비어 있습니다."}

    ref = db.collection("knowledge").document(req.id)
    if not ref.get().exists:
        return {"success": False, "detail": "이미 삭제된 자료입니다."}

    ref.set({
        "title": title,
        "content": content,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }, merge=True)
    return {"success": True}


@app.delete("/api/admin/knowledge/{k_id}", dependencies=[Depends(verify_admin)])
def delete_knowledge_admin(k_id: str):
    if db: db.collection("knowledge").document(k_id).delete()
    return {"success": True}

@app.get("/api/inquiries")
def get_inquiries():
    if db is None: return {"success": False, "inquiries": []}
    return {"success": True, "inquiries": [{"id": d.id, **d.to_dict()} for d in db.collection("inquiries").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

@app.post("/api/inquiry")
def create_inquiry(content: str = Form(...), school: str = Form(""), grade: str = Form(""), student_name: str = Form("")):
    if db: db.collection("inquiries").add({"content": content, "school": school, "grade": grade, "student_name": student_name, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.delete("/api/admin/inquiry/{i_id}", dependencies=[Depends(verify_admin)])
def delete_inquiry_admin(i_id: str):
    if db: db.collection("inquiries").document(i_id).delete()
    return {"success": True}

class QuestionSaveReq(BaseModel):
    title: str
    content: str
    id: str = ""          # 있으면 그 출제본을 고친다


@app.post("/api/admin/questions", dependencies=[Depends(verify_admin)])
def save_question_admin(req: QuestionSaveReq):
    """출제본을 저장한다. id가 오면 새로 만들지 않고 그 출제본을 고친다.
    (자동 저장이 돌 때마다 사본이 쌓이지 않도록)"""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = req.title.strip() or "제목 없음"

    if req.id.strip():
        ref = db.collection("questions").document(req.id.strip())
        if ref.get().exists:
            ref.set({"title": title, "content": req.content, "updated_at": now}, merge=True)
            return {"success": True, "id": req.id.strip(), "updated": True}

    _, ref = db.collection("questions").add(
        {"title": title, "content": req.content, "created_at": now}
    )
    return {"success": True, "id": ref.id, "updated": False}

@app.get("/api/admin/questions", dependencies=[Depends(verify_admin)])
def get_questions_admin():
    if db is None: return {"success": False, "questions": []}
    return {"success": True, "questions": [{"id": d.id, **d.to_dict()} for d in db.collection("questions").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

@app.delete("/api/admin/questions/{q_id}", dependencies=[Depends(verify_admin)])
def delete_question_admin(q_id: str):
    if db: db.collection("questions").document(q_id).delete()
    return {"success": True}


# ═════════════════════════════════════════════════════════
# 상담 프로그램 (통합)
#   1) 성적 분석  → 수시/정시 비중 + 가능 대학 라인 + 맞춤 학습 프로그램
#   2) 학습 성향 검사 → 문제점 / 발전 가능성 / 개선점
#   3) 학생부 정성 평가
#   4) 개인별 학습 기록·점수 누적
#   네 가지가 학생 한 명의 '상담 카드' 하나에 모두 쌓인다.
# ═════════════════════════════════════════════════════════

# ── 학습 성향 검사 문항 ──────────────────────────────────
# 국어 학원 맥락에 맞춰 7개 축 × 4문항 = 28문항. 5점 척도(1 전혀 아니다 ~ 5 매우 그렇다).
# reverse=True인 문항은 뒤집어서 채점한다(점수가 높을수록 좋은 상태가 되도록).
# ── 학습 성향 검사 ─────────────────────────────────────
#   과목마다 공부하는 방식이 달라서 한 벌로는 잡히지 않는다.
#   국어·수학·영어는 6개 공통 축(동기·계획·집중·메타인지·오답·시험태도)에
#   과목 특화 축 하나를 더해 축끼리 견줄 수 있게 맞췄고,
#   학습 태도 점검은 과목과 무관한 별도 축으로 짰다.
#   모두 7축 × 4문항 = 28문항, 5점 척도. reverse는 뒤집어 채점한다.

_COMMON_AXES = [
    ("motive",  "학습 동기",      "공부할 이유가 스스로 분명한가"),
    ("plan",    "계획·시간관리",  "계획을 세우고 지켜내는가"),
    ("focus",   "집중 지속력",    "한 번에 얼마나 오래 몰입하는가"),
    ("meta",    "메타인지",       "아는 것과 모르는 것을 구분하는가"),
    ("review",  "오답·피드백",    "틀린 것을 되짚고 지적을 받아들이는가"),
    ("emotion", "시험 태도",      "긴장과 시간 압박을 다스리는가"),
]


def _axes(extra_key, extra_name, extra_desc):
    return [{"key": k, "name": n, "desc": d} for k, n, d in _COMMON_AXES] + \
           [{"key": extra_key, "name": extra_name, "desc": extra_desc}]


def _q(items):
    """(축, 문항, 역채점여부) 목록에 번호를 매긴다."""
    out = []
    for i, it in enumerate(items):
        axis, text = it[0], it[1]
        rev = len(it) > 2 and it[2]
        d = {"id": i + 1, "axis": axis, "text": text}
        if rev:
            d["reverse"] = True
        out.append(d)
    return out


TENDENCY_SETS = {
    "korean": {
        "key": "korean", "name": "국어 학습 성향", "icon": "📖",
        "desc": "국어를 공부하는 방식과 읽기 습관을 봅니다",
        "axes": _axes("reading", "국어 독해 습관", "글을 구조와 근거로 읽는가"),
        "questions": _q([
            ("motive", "국어 공부를 할 때 '왜 이걸 배우는지' 스스로 납득이 되어야 집중이 된다."),
            ("motive", "성적과 상관없이 새로운 글을 읽고 이해하는 일 자체가 재미있다."),
            ("motive", "부모님이나 선생님이 시키지 않아도 스스로 공부를 시작한다."),
            ("motive", "목표하는 대학이나 진로가 뚜렷해서 공부할 이유가 분명하다."),
            ("plan", "하루 또는 일주일 단위로 공부 계획을 세우고 기록한다."),
            ("plan", "계획을 세우면 대체로 그대로 지키는 편이다."),
            ("plan", "시험 2~3주 전부터 과목별 일정을 나눠서 준비한다."),
            ("plan", "미루다가 마감 직전에 몰아서 하는 편이다.", True),
            ("focus", "한번 앉으면 50분 이상 흐름이 끊기지 않고 공부한다."),
            ("focus", "공부 중 휴대폰 알림이 오면 바로 확인하게 된다.", True),
            ("focus", "긴 지문을 읽을 때 중간에 딴생각이 자주 든다.", True),
            ("focus", "주변이 조금 시끄러워도 할 일에 몰입할 수 있다."),
            ("meta", "문제를 풀고 나면 내가 무엇을 알고 무엇을 모르는지 구분할 수 있다."),
            ("meta", "답을 맞혔어도 '왜' 맞았는지 설명할 수 있는지 스스로 확인한다."),
            ("meta", "공부한 내용을 누군가에게 설명하듯 정리해 본다."),
            ("meta", "시험 점수가 나오면 그 원인을 구체적으로 짚어낼 수 있다."),
            ("review", "틀린 문제는 반드시 다시 풀어보고 넘어간다."),
            ("review", "오답 노트나 그에 준하는 기록을 꾸준히 남긴다."),
            ("review", "선생님의 지적을 들으면 기분이 상해 받아들이기 어렵다.", True),
            ("review", "같은 유형에서 반복해 틀리는 부분이 무엇인지 알고 있다."),
            ("emotion", "시험 때 아는 문제도 긴장해서 틀린 적이 많다.", True),
            ("emotion", "시간이 부족할 것 같으면 마음이 급해져 실수가 늘어난다.", True),
            ("emotion", "어려운 문제를 만나면 일단 넘기고 뒤를 먼저 푼다."),
            ("emotion", "시험이 끝나면 결과와 상관없이 감정을 빨리 추스른다."),
            ("reading", "글을 읽을 때 문단별 중심 내용을 표시하거나 정리한다."),
            ("reading", "모르는 어휘가 나오면 확인하지 않고 그냥 넘어간다.", True),
            ("reading", "선택지를 지문의 근거와 일일이 대조하며 지운다."),
            ("reading", "비문학 지문의 글 구조(대조·인과·분류 등)를 의식하며 읽는다."),
        ]),
    },

    "math": {
        "key": "math", "name": "수학 학습 성향", "icon": "🔢",
        "desc": "수학을 푸는 방식과 풀이 습관을 봅니다",
        "axes": _axes("solving", "수학 풀이 습관", "과정을 적고 조건을 정리하며 푸는가"),
        "questions": _q([
            ("motive", "수학을 '왜 배우는지' 스스로 납득이 되어야 집중이 된다."),
            ("motive", "어려운 문제를 끝내 풀어냈을 때의 성취감이 크다."),
            ("motive", "시키지 않아도 스스로 수학 공부를 시작한다."),
            ("motive", "목표하는 대학이나 전공 때문에 수학이 꼭 필요하다고 느낀다."),
            ("plan", "하루에 풀 문제 수나 진도를 정해두고 공부한다."),
            ("plan", "정해둔 분량을 대체로 끝내는 편이다."),
            ("plan", "시험 전에 단원별로 복습 일정을 나눠 둔다."),
            ("plan", "미루다가 시험 직전에 몰아서 하는 편이다.", True),
            ("focus", "한 문제를 붙잡고 20분 이상 고민할 수 있다."),
            ("focus", "잘 안 풀리면 금방 해설을 펴 본다.", True),
            ("focus", "문제를 풀다가 딴생각이 자주 든다.", True),
            ("focus", "주변이 조금 시끄러워도 계산에 집중할 수 있다."),
            ("meta", "공식을 외우기 전에 왜 그렇게 되는지 따져본다."),
            ("meta", "맞힌 문제도 다른 풀이가 있는지 생각해 본다."),
            ("meta", "배운 개념을 친구에게 설명할 수 있다."),
            ("meta", "틀렸을 때 '계산 실수'인지 '몰라서'인지 구분할 수 있다."),
            ("review", "틀린 문제는 해설을 덮고 스스로 다시 풀어본다."),
            ("review", "오답 노트나 그에 준하는 기록을 꾸준히 남긴다."),
            ("review", "해설을 보고 이해하면 그걸로 다 됐다고 여긴다.", True),
            ("review", "반복해서 틀리는 단원이 무엇인지 알고 있다."),
            ("emotion", "시험 때 아는 문제도 긴장해서 틀린 적이 많다.", True),
            ("emotion", "시간이 부족할 것 같으면 급해져 계산 실수가 늘어난다.", True),
            ("emotion", "어려운 문제는 일단 넘기고 뒤를 먼저 푼다."),
            ("emotion", "검산할 시간을 남겨 두고 푸는 편이다."),
            ("solving", "풀이 과정을 식으로 또박또박 적으면서 푼다."),
            ("solving", "암산으로 넘기다가 계산을 틀리는 일이 잦다.", True),
            ("solving", "문제를 읽고 무엇을 구하는 것인지 먼저 정리한다."),
            ("solving", "그림이나 표를 그려 조건을 정리해 본다."),
        ]),
    },

    "english": {
        "key": "english", "name": "영어 학습 성향", "icon": "🔤",
        "desc": "영어 공부 방식과 어휘·구문 습관을 봅니다",
        "axes": _axes("reading_en", "영어 학습 습관", "어휘와 문장 구조를 어떻게 다루는가"),
        "questions": _q([
            ("motive", "영어를 '왜 배우는지' 스스로 납득이 되어야 집중이 된다."),
            ("motive", "성적과 상관없이 영어로 된 글이나 영상을 보는 것이 재미있다."),
            ("motive", "시키지 않아도 스스로 영어 공부를 시작한다."),
            ("motive", "목표하는 대학이나 전공 때문에 영어가 꼭 필요하다고 느낀다."),
            ("plan", "하루에 외울 단어 수나 읽을 지문 수를 정해두고 공부한다."),
            ("plan", "정해둔 분량을 대체로 끝내는 편이다."),
            ("plan", "시험 전에 범위를 나눠 복습 일정을 잡는다."),
            ("plan", "미루다가 시험 직전에 몰아서 하는 편이다.", True),
            ("focus", "한번 앉으면 50분 이상 흐름이 끊기지 않고 공부한다."),
            ("focus", "공부 중 휴대폰 알림이 오면 바로 확인하게 된다.", True),
            ("focus", "긴 지문을 읽을 때 중간에 딴생각이 자주 든다.", True),
            ("focus", "듣기 문제를 풀 때 끝까지 집중해서 듣는다."),
            ("meta", "지문을 읽고 나서 무엇을 이해했고 무엇을 못 했는지 구분할 수 있다."),
            ("meta", "답을 맞혔어도 근거가 된 문장을 짚을 수 있는지 확인한다."),
            ("meta", "배운 표현을 내 문장으로 바꿔 써 본다."),
            ("meta", "점수가 나오면 어휘·구문·독해 중 무엇이 문제였는지 짚어낼 수 있다."),
            ("review", "틀린 문제는 반드시 다시 풀어보고 넘어간다."),
            ("review", "모르는 단어와 표현을 따로 모아 관리한다."),
            ("review", "선생님의 지적을 들으면 기분이 상해 받아들이기 어렵다.", True),
            ("review", "반복해서 틀리는 유형이 무엇인지 알고 있다."),
            ("emotion", "시험 때 아는 문제도 긴장해서 틀린 적이 많다.", True),
            ("emotion", "시간이 부족할 것 같으면 마음이 급해져 실수가 늘어난다.", True),
            ("emotion", "어려운 지문은 일단 넘기고 뒤를 먼저 푼다."),
            ("emotion", "시험이 끝나면 결과와 상관없이 감정을 빨리 추스른다."),
            ("reading_en", "단어를 외울 때 예문이나 쓰임과 함께 익힌다."),
            ("reading_en", "모르는 단어가 나오면 확인하지 않고 그냥 넘어간다.", True),
            ("reading_en", "긴 문장은 주어와 동사를 먼저 찾아 구조를 파악한다."),
            ("reading_en", "지문의 흐름(대조·예시·인과)을 의식하며 읽는다."),
        ]),
    },

    "attitude": {
        "key": "attitude", "name": "학습 태도 점검", "icon": "🧭",
        "desc": "과목과 무관하게 공부하는 태도 전반을 봅니다",
        "axes": [
            {"key": "diligence", "name": "성실성",       "desc": "출결과 준비를 챙기는가"},
            {"key": "classroom", "name": "수업 태도",    "desc": "수업 시간을 어떻게 쓰는가"},
            {"key": "homework",  "name": "과제 수행",    "desc": "과제를 제때 제대로 하는가"},
            {"key": "selfdrive", "name": "자기주도성",   "desc": "스스로 정하고 해결하는가"},
            {"key": "environ",   "name": "환경 관리",    "desc": "공부할 여건을 스스로 만드는가"},
            {"key": "grit",      "name": "끈기",         "desc": "잘 안 될 때도 계속하는가"},
            {"key": "honesty",   "name": "정직성·자기점검", "desc": "자신을 속이지 않고 돌아보는가"},
        ],
        "questions": _q([
            ("diligence", "수업에 늦지 않게 도착한다."),
            ("diligence", "준비물과 교재를 빠뜨리지 않고 챙긴다."),
            ("diligence", "몸이 조금 안 좋아도 수업에는 나온다."),
            ("diligence", "결석하면 빠진 내용을 스스로 메운다."),
            ("classroom", "수업 중 선생님 설명을 눈을 맞추며 듣는다."),
            ("classroom", "이해가 안 되면 그 자리에서 질문한다."),
            ("classroom", "수업 중 딴짓을 하거나 조는 때가 있다.", True),
            ("classroom", "중요한 내용을 스스로 판단해 적어 둔다."),
            ("homework", "과제를 기한 안에 낸다."),
            ("homework", "과제를 대충 채워서 내는 일이 있다.", True),
            ("homework", "과제를 하다 막히면 스스로 찾아보거나 물어본다."),
            ("homework", "돌려받은 과제의 지적을 다음에 반영한다."),
            ("selfdrive", "오늘 무엇을 공부할지 스스로 정한다."),
            ("selfdrive", "시키는 것만 하는 편이다.", True),
            ("selfdrive", "모르는 것이 생기면 그날 안에 해결하려 한다."),
            ("selfdrive", "공부 방법이 안 맞는다 싶으면 스스로 바꿔 본다."),
            ("environ", "공부할 때 휴대폰을 손이 닿지 않는 곳에 둔다."),
            ("environ", "책상 위를 정리하고 시작한다."),
            ("environ", "잠자는 시간이 들쭉날쭉하다.", True),
            ("environ", "공부가 잘 되는 시간대를 알고 그때 어려운 것을 한다."),
            ("grit", "성적이 안 나와도 방법을 바꿔가며 계속한다."),
            ("grit", "어렵다 싶으면 금방 포기한다.", True),
            ("grit", "오래 걸리는 목표도 꾸준히 밀고 간다."),
            ("grit", "하루 계획이 어긋나도 다음 날 다시 잡는다."),
            ("honesty", "모르면서 아는 척하지 않는다."),
            ("honesty", "답을 미리 보고 맞힌 것처럼 넘어간 적이 있다.", True),
            ("honesty", "공부한 시간을 부풀리지 않고 그대로 센다."),
            ("honesty", "스스로 얼마나 했는지 돌아보는 시간을 갖는다."),
        ]),
    },
}

DEFAULT_TENDENCY_SET = "korean"


def get_tendency_set(key: str) -> dict:
    return TENDENCY_SETS.get(str(key or "").strip(), TENDENCY_SETS[DEFAULT_TENDENCY_SET])


# 예전 코드가 쓰던 이름 — 국어 검사지를 가리킨다
TENDENCY_AXES = TENDENCY_SETS["korean"]["axes"]
TENDENCY_QUESTIONS = TENDENCY_SETS["korean"]["questions"]


def score_tendency(answers: dict, set_key: str = DEFAULT_TENDENCY_SET) -> list:
    """문항 응답(1~5)을 축별 0~100점으로 환산."""
    tset = get_tendency_set(set_key)
    axes, questions = tset["axes"], tset["questions"]
    buckets = {a["key"]: [] for a in axes}
    for q in questions:
        raw = answers.get(str(q["id"]), answers.get(q["id"]))
        try:
            v = int(raw)
        except (TypeError, ValueError):
            continue
        v = max(1, min(5, v))
        if q.get("reverse"):
            v = 6 - v
        buckets[q["axis"]].append(v)

    out = []
    for axis in axes:
        vals = buckets[axis["key"]]
        pct = round((sum(vals) / len(vals) - 1) / 4 * 100) if vals else 0
        out.append({**axis, "score": pct, "answered": len(vals)})
    return out


# ── 대학 라인 기준표 ────────────────────────────────────
# 실제 입결은 해마다 바뀌므로 AI에게 지어내게 하지 않고, 원장님이 직접
# 고치는 기준표를 근거로 삼는다. 아래는 초기값일 뿐이며 관리자 화면에서 수정 가능.
DEFAULT_ADMISSION_TABLE = {
    "susi": [
        {"upto": 1.3, "tier": "최상위권", "examples": "서울대 · 연세대 · 고려대"},
        {"upto": 1.8, "tier": "상위권",   "examples": "서강대 · 성균관대 · 한양대 · 중앙대 · 경희대"},
        {"upto": 2.4, "tier": "중상위권", "examples": "한국외대 · 서울시립대 · 건국대 · 동국대 · 홍익대"},
        {"upto": 3.0, "tier": "중위권",   "examples": "숙명여대 · 국민대 · 숭실대 · 세종대 · 인하대 · 아주대"},
        {"upto": 4.0, "tier": "중하위권", "examples": "광운대 · 명지대 · 가천대 · 단국대 · 경기권 대학"},
        {"upto": 5.0, "tier": "하위권",   "examples": "경기·인천권 대학 · 지방 거점 국립대"},
        {"upto": 9.0, "tier": "기초 재정비 구간", "examples": "지방 사립대 · 전문대 (성적 향상이 최우선)"},
    ],
    "jeongsi": [
        {"from_pct": 96, "tier": "최상위권", "examples": "서울대 · 연세대 · 고려대"},
        {"from_pct": 92, "tier": "상위권",   "examples": "서강대 · 성균관대 · 한양대 · 중앙대 · 경희대"},
        {"from_pct": 86, "tier": "중상위권", "examples": "한국외대 · 서울시립대 · 건국대 · 동국대 · 홍익대"},
        {"from_pct": 78, "tier": "중위권",   "examples": "숭실대 · 국민대 · 세종대 · 인하대 · 아주대"},
        {"from_pct": 65, "tier": "중하위권", "examples": "광운대 · 명지대 · 가천대 · 단국대 · 경기권 대학"},
        {"from_pct": 50, "tier": "하위권",   "examples": "경기·인천권 대학 · 지방 거점 국립대"},
        {"from_pct": 0,  "tier": "기초 재정비 구간", "examples": "지방 사립대 · 전문대 (성적 향상이 최우선)"},
    ],
    "scale": "9",
    "note": "학원 자체 기준표입니다. 실제 입시 결과에 맞게 원장님이 직접 수정해 사용하세요.",
}


def load_admission_table() -> dict:
    if db is None:
        return DEFAULT_ADMISSION_TABLE
    try:
        doc = db.collection("settings").document("admission_table").get()
        if doc.exists:
            data = doc.to_dict() or {}
            if data.get("susi") and data.get("jeongsi"):
                data["scale"] = normalize_scale(data.get("scale") or "9")
                return data
    except Exception:
        pass
    return DEFAULT_ADMISSION_TABLE


# ── 내신 9등급제 ↔ 5등급제 환산 ───────────────────────
# 2025학년도 고1부터 내신이 5등급제로 바뀌어, 학년마다 등급 체계가 다르다.
# 두 체계는 '누적 비율'이 달라서 등급 숫자를 그대로 비교할 수 없다.
#   9등급제 누적: 4 / 11 / 23 / 40 / 60 / 77 / 89 / 96 / 100 (%)
#   5등급제 누적: 10 / 34 / 66 / 90 / 100 (%)
# 그래서 등급을 '그 등급 구간의 한가운데 백분율'로 바꾼 뒤,
# 상대 체계에서 같은 백분율이 몇 등급인지 되짚는 방식으로 환산한다.
GRADE_CUTS = {
    "9": [4, 11, 23, 40, 60, 77, 89, 96, 100],
    "5": [10, 34, 66, 90, 100],
}


def _band_midpoints(cuts):
    mids, prev = [], 0
    for c in cuts:
        mids.append((prev + c) / 2)
        prev = c
    return mids


GRADE_MIDS = {k: _band_midpoints(v) for k, v in GRADE_CUTS.items()}


def normalize_scale(value) -> str:
    """'9', 9, '9등급제' 무엇이 와도 '9' 또는 '5'로 정리한다. 기본은 9등급제."""
    s = str(value or "").strip()
    return "5" if s.startswith("5") else "9"


def _grade_to_pct(grade: float, scale: str) -> float:
    """등급(소수 가능) → 누적 백분율. 등급 사이는 직선으로 잇는다."""
    mids = GRADE_MIDS[scale]
    g = max(1.0, min(float(len(mids)), float(grade)))
    lo = int(g) - 1
    if lo >= len(mids) - 1:
        return mids[-1]
    frac = g - int(g)
    return mids[lo] + frac * (mids[lo + 1] - mids[lo])


def _pct_to_grade(pct: float, scale: str) -> float:
    """누적 백분율 → 등급(소수). _grade_to_pct의 역방향."""
    mids = GRADE_MIDS[scale]
    if pct <= mids[0]:
        return 1.0
    if pct >= mids[-1]:
        return float(len(mids))
    for i in range(len(mids) - 1):
        if mids[i] <= pct <= mids[i + 1]:
            span = mids[i + 1] - mids[i]
            frac = 0 if span == 0 else (pct - mids[i]) / span
            return round((i + 1) + frac, 2)
    return float(len(mids))


def pct_to_band(pct, scale: str):
    """석차백분율(상위 몇 %)을 등급으로. 등급 구간이 누적 비율로 정해져 있어
    이 변환은 근사가 아니라 정확하다.
    예) 상위 7.2% → 9등급제 2등급(4~11%), 5등급제 1등급(0~10%)"""
    v = _num(pct)
    if v is None:
        return None
    scale = normalize_scale(scale)
    v = max(0.0, min(100.0, v))
    for i, c in enumerate(GRADE_CUTS[scale]):
        if v <= c:
            return i + 1
    return len(GRADE_CUTS[scale])


def pct_to_grade_exact(pct, scale: str):
    """평균 석차백분율을 등급으로 바꾼다. 소수 등급이 나오도록 구간 안에서 비례 배분."""
    v = _num(pct)
    if v is None:
        return None
    scale = normalize_scale(scale)
    cuts = GRADE_CUTS[scale]
    v = max(0.0, min(100.0, v))
    # 등급 한가운데를 그 등급의 대표값으로 보고, 구간 안에서는 직선으로 잇는다.
    # 그래야 평균 백분율 4%가 1등급, 11%가 2등급처럼 자연스럽게 이어진다.
    mids = GRADE_MIDS[scale]
    if v <= mids[0]:
        return 1.0
    if v >= mids[-1]:
        return float(len(mids))
    for i in range(len(mids) - 1):
        if mids[i] <= v <= mids[i + 1]:
            span = mids[i + 1] - mids[i]
            frac = 0.0 if span <= 0 else (v - mids[i]) / span
            return round((i + 1) + frac, 2)
    return float(len(mids))


def convert_grade_scale(grade, frm, to):
    """등급 하나를 다른 체계로 환산한다. 같은 체계면 그대로 돌려준다."""
    g = _num(grade)
    if g is None:
        return None
    frm, to = normalize_scale(frm), normalize_scale(to)
    if frm == to:
        return round(g, 2)
    return round(_pct_to_grade(_grade_to_pct(g, frm), to), 2)


def convert_grade_band(grade, frm, to):
    """과목 하나의 정수 등급은 '몇~몇 등급'처럼 폭으로 보는 것이 정확하다.
    예) 9등급제 2등급(상위 4~11%)은 5등급제로 1~2등급에 걸친다."""
    g = _num(grade)
    if g is None:
        return None
    frm, to = normalize_scale(frm), normalize_scale(to)
    if frm == to:
        return {"low": int(g), "high": int(g), "text": f"{int(g)}등급"}

    idx = max(1, min(len(GRADE_CUTS[frm]), int(round(g))))
    lo_pct = 0 if idx == 1 else GRADE_CUTS[frm][idx - 2]
    hi_pct = GRADE_CUTS[frm][idx - 1]

    def band_of(pct):
        for i, c in enumerate(GRADE_CUTS[to]):
            if pct <= c:
                return i + 1
        return len(GRADE_CUTS[to])

    low = band_of(lo_pct + 0.01)
    high = band_of(max(lo_pct + 0.01, hi_pct - 0.01))
    text = f"{low}등급" if low == high else f"{low}~{high}등급"
    return {"low": low, "high": high, "text": text}


MAIN_SUBJECT_KEYWORDS = ("국어", "영어", "수학", "사회", "과학", "한국사", "문학", "독서", "화법", "언어", "미적분", "확률", "기하", "물리", "화학", "생명", "지구", "통합")


def _num(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def summarize_naesin(rows: list, scale: str = "9") -> dict:
    """단위수 가중 평균 등급을 낸다. 단위수가 없으면 1로 본다."""
    scale = normalize_scale(scale)
    other = "5" if scale == "9" else "9"
    tot_w = tot_wg = 0.0
    main_w = main_wg = 0.0
    pct_w = pct_wp = 0.0
    pct_count = 0
    by_term = {}
    for r in rows or []:
        # 💡 석차백분율이 적혀 있으면 그것으로 등급을 구한다.
        #    백분율은 두 등급 체계의 누적 비율에 그대로 대응하므로
        #    9등급제↔5등급제 환산이 근사가 아니라 정확해진다.
        p = _num(r.get("pct"))
        g = pct_to_band(p, scale) if p is not None else _num(r.get("grade"))
        if g is None:
            continue
        w = _num(r.get("unit"), 1) or 1
        if p is not None:
            pct_w += w
            pct_wp += p * w
            pct_count += 1
        tot_w += w; tot_wg += g * w
        name = str(r.get("subject", ""))
        if any(k in name for k in MAIN_SUBJECT_KEYWORDS):
            main_w += w; main_wg += g * w
        term = str(r.get("term", "")).strip() or "기타"
        t = by_term.setdefault(term, {"w": 0.0, "wg": 0.0})
        t["w"] += w; t["wg"] += g * w

    terms = []
    for k, v in sorted(by_term.items()):
        if not v["w"]:
            continue
        a = round(v["wg"] / v["w"], 2)
        terms.append({"term": k, "avg": a, "avg_other": convert_grade_scale(a, scale, other)})

    avg = round(tot_wg / tot_w, 2) if tot_w else None
    main_avg = round(main_wg / main_w, 2) if main_w else None

    # 백분율이 적힌 과목이 있으면 가중 평균 백분율을 내고,
    # 그 백분율로 두 체계의 등급을 각각 정확히 산출한다.
    pct_avg = round(pct_wp / pct_w, 2) if pct_w else None
    avg9 = pct_to_grade_exact(pct_avg, "9") if pct_avg is not None else None
    avg5 = pct_to_grade_exact(pct_avg, "5") if pct_avg is not None else None
    all_by_pct = pct_count > 0 and pct_count == len([r for r in (rows or [])
                                                     if _num(r.get("pct")) is not None or _num(r.get("grade")) is not None])

    return {
        "avg": avg,
        "main_avg": main_avg,
        "pct_avg": pct_avg,
        "pct_count": pct_count,
        "avg_by_pct_9": avg9,
        "avg_by_pct_5": avg5,
        "exact": bool(all_by_pct),
        # 💡 2025학년도부터 내신이 5등급제로 바뀌어 학년마다 체계가 다르다.
        #    입력한 체계와 반대쪽 체계의 환산값을 항상 함께 내놓는다.
        "scale": scale,
        "other_scale": other,
        "avg_other": (avg5 if other == "5" else avg9) if all_by_pct else convert_grade_scale(avg, scale, other),
        "main_avg_other": convert_grade_scale(main_avg, scale, other),
        "total_units": round(tot_w, 1),
        "count": len([r for r in (rows or []) if _num(r.get("grade")) is not None]),
        "by_term": terms,
    }


# 수능·모의고사에서 절대평가로 치르는 과목 — 백분위가 나오지 않고 등급만 나온다.
ABSOLUTE_SUBJECTS = ("영어", "한국사", "제2외국어", "한문", "아랍어", "일본어", "중국어",
                     "독일어", "프랑스어", "스페인어", "러시아어", "베트남어")


def is_absolute_subject(name: str) -> bool:
    n = str(name or "").strip()
    return any(k in n for k in ABSOLUTE_SUBJECTS)


# ── 시험별 등급컷 ──────────────────────────────────────
#   모의고사는 회차마다 난이도가 달라 같은 원점수라도 등급이 다르다.
#   그래서 원장님이 회차별로 등급컷을 직접 넣고, 원점수를 그 컷에 비춰
#   등급을 뽑는다. 영어·한국사는 절대평가라 컷이 고정이다.
ABSOLUTE_DEFAULT_CUTS = [90, 80, 70, 60, 50, 40, 30, 20]   # 1~8등급컷, 나머지 9등급

# 탐구 과목 목록 — 2028 대입 개편으로 탐구가 통합사회·통합과학으로 바뀌므로
# 그 둘을 맨 앞에 두고, 현행 선택과목도 함께 남겨 둔다(재수생·기존 학년 대비).
EXAM_SUBJECTS = {
    "공통": ["국어", "수학", "영어", "한국사"],
    "사회탐구": ["통합사회", "생활과 윤리", "윤리와 사상", "한국지리", "세계지리",
                "동아시아사", "세계사", "경제", "정치와 법", "사회·문화"],
    "과학탐구": ["통합과학", "물리학I", "물리학II", "화학I", "화학II",
                "생명과학I", "생명과학II", "지구과학I", "지구과학II"],
    "기타": ["제2외국어/한문", "직업탐구"],
}

# 학생 계열 — 예체능 포함
TRACK_OPTIONS = ["미정", "인문", "자연", "예체능"]


@app.get("/api/admin/exam_subjects", dependencies=[Depends(verify_admin)])
def get_exam_subjects():
    return {"success": True, "groups": EXAM_SUBJECTS, "tracks": TRACK_OPTIONS,
            "absolute_default": ABSOLUTE_DEFAULT_CUTS}




def raw_to_grade(raw, cuts):
    """원점수를 등급컷에 비춰 등급으로 바꾼다. cuts는 1등급컷부터 내림차순."""
    v = _num(raw)
    if v is None or not cuts:
        return None
    clean = [c for c in (_num(x) for x in cuts) if c is not None]
    if not clean:
        return None
    for i, c in enumerate(clean):
        if v >= c:
            return i + 1
    return len(clean) + 1


def load_grade_cuts() -> list:
    if db is None:
        return []
    out = []
    for d in db.collection("grade_cuts").stream():
        out.append({"id": d.id, **(d.to_dict() or {})})
    out.sort(key=lambda x: str(x.get("date", "")), reverse=True)
    return out


def find_cut_set(exam_date: str):
    """모의고사 시행월(예 '2026-09')에 해당하는 등급컷 묶음을 찾는다."""
    key = str(exam_date or "").strip()
    if not key:
        return None
    for s in load_grade_cuts():
        if str(s.get("date", "")).strip() == key:
            return s
    return None


@app.get("/api/admin/grade_cuts", dependencies=[Depends(verify_admin)])
def get_grade_cuts():
    return {"success": True, "sets": load_grade_cuts(),
            "absolute_default": ABSOLUTE_DEFAULT_CUTS}


class GradeCutReq(BaseModel):
    id: str = ""
    name: str
    date: str
    subjects: list = None


@app.post("/api/admin/grade_cuts", dependencies=[Depends(verify_admin)])
def save_grade_cuts(req: GradeCutReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.name.strip()
    date = req.date.strip()
    if not name or not date:
        return {"success": False, "detail": "시험 이름과 시행월을 모두 입력해주세요."}

    subjects = []
    for s in (req.subjects or []):
        subj = str(s.get("subject", "")).strip()
        if not subj:
            continue
        cuts = [c for c in (_num(x) for x in (s.get("cuts") or [])) if c is not None]
        subjects.append({"subject": subj[:20], "cuts": cuts[:8],
                         "absolute": bool(is_absolute_subject(subj))})
    if not subjects:
        return {"success": False, "detail": "과목을 하나 이상 넣어주세요."}

    doc_id = sanitize_doc_id(req.id.strip() or date + "_" + name)
    db.collection("grade_cuts").document(doc_id).set({
        "name": name[:60], "date": date[:20], "subjects": subjects,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    return {"success": True, "id": doc_id, "sets": load_grade_cuts()}


class GradeCutDeleteReq(BaseModel):
    id: str


@app.post("/api/admin/grade_cuts/delete", dependencies=[Depends(verify_admin)])
def delete_grade_cuts(req: GradeCutDeleteReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    db.collection("grade_cuts").document(req.id).delete()
    return {"success": True, "sets": load_grade_cuts()}


def summarize_mock(rows: list) -> dict:
    """가장 최근 시행월의 성적을 정리한다.
    💡 영어·한국사는 절대평가라 백분위가 없고 등급만 나온다. 이 과목들을
       상대평가 과목(국어·수학·탐구)과 섞어 평균을 내면 정시 판단이 어긋나므로,
       평균은 상대평가 과목만으로 내고 절대평가 과목은 등급을 따로 보여준다."""
    valid = [r for r in (rows or [])
             if _num(r.get("grade")) is not None or _num(r.get("percentile")) is not None
             or _num(r.get("raw")) is not None]
    if not valid:
        return {"avg": None, "pct_avg": None, "latest": None, "count": 0,
                "by_date": [], "absolute": [], "abs_text": "", "raw_sum": None, "raw_text": ""}

    by_date = {}
    for r in valid:
        d = str(r.get("date", "")).strip() or "미상"
        by_date.setdefault(d, []).append(r)

    def block(rows_):
        rel = [x for x in rows_ if not is_absolute_subject(x.get("subject"))]
        absolute = [x for x in rows_ if is_absolute_subject(x.get("subject"))]
        gs = [_num(x.get("grade")) for x in rel if _num(x.get("grade")) is not None]
        ps = [_num(x.get("percentile")) for x in rel if _num(x.get("percentile")) is not None]
        # 💡 비상교육 자료처럼 '국수탐 원점수 합'으로 지원 가능선을 주는 자료가 있어
        #    상대평가 과목의 원점수 합계도 함께 낸다.
        raws = [_num(x.get("raw")) for x in rel if _num(x.get("raw")) is not None]
        abs_list = [{"subject": str(x.get("subject", "")).strip(),
                     "grade": _num(x.get("grade")), "raw": _num(x.get("raw"))}
                    for x in absolute if _num(x.get("grade")) is not None or _num(x.get("raw")) is not None]
        return {
            "avg": round(sum(gs) / len(gs), 2) if gs else None,
            "pct_avg": round(sum(ps) / len(ps), 1) if ps else None,
            "raw_sum": round(sum(raws), 1) if raws else None,
            "raw_count": len(raws),
            "rel_count": len(rel),
            "absolute": abs_list,
        }

    dates = sorted(by_date.keys())
    trend = [{"date": d, **block(by_date[d])} for d in dates]
    latest = trend[-1] if trend else None
    absolute = latest["absolute"] if latest else []
    abs_text = " · ".join(f"{a['subject']} {int(a['grade']) if float(a['grade']).is_integer() else a['grade']}등급"
                          for a in absolute)
    raw_sum = latest["raw_sum"] if latest else None
    raw_text = (f"국·수·탐 원점수 합 {raw_sum}점 ({latest['raw_count']}과목)"
                if latest and raw_sum is not None else "")
    return {
        "avg": latest["avg"] if latest else None,
        "pct_avg": latest["pct_avg"] if latest else None,
        "raw_sum": raw_sum,
        "raw_text": raw_text,
        "latest": latest["date"] if latest else None,
        "count": len(valid),
        "by_date": trend,
        "absolute": absolute,
        "abs_text": abs_text,
    }


def pick_tier(table: dict, naesin_avg, pct_avg, naesin_scale: str = "9") -> dict:
    """기준표는 9등급제나 5등급제 중 하나로 적혀 있다. 학생 내신이 다른 체계로
    입력되어 있으면 기준표 쪽 체계로 바꿔서 대본다.
    (그러지 않으면 5등급제 2.0등급이 9등급제 2.0등급 자리에 걸려 라인이 부풀려진다)"""
    out = {"susi": None, "jeongsi": None, "converted": None}
    table_scale = normalize_scale(table.get("scale") or "9")
    mine = naesin_avg
    if mine is not None and normalize_scale(naesin_scale) != table_scale:
        mine = convert_grade_scale(mine, naesin_scale, table_scale)
        out["converted"] = {"from": normalize_scale(naesin_scale), "to": table_scale, "value": mine}
    out["table_scale"] = table_scale
    if mine is not None:
        for row in table.get("susi", []):
            if mine <= _num(row.get("upto"), 99):
                out["susi"] = row
                break
    if pct_avg is not None:
        for row in table.get("jeongsi", []):
            if pct_avg >= _num(row.get("from_pct"), 0):
                out["jeongsi"] = row
                break
    return out


def judge_track(naesin_avg, mock_avg) -> dict:
    """내신과 모의고사 중 어느 쪽이 유리한지 숫자로 먼저 가른다."""
    if naesin_avg is None and mock_avg is None:
        return {"verdict": "판단 보류", "gap": None, "susi_weight": 50, "jeongsi_weight": 50,
                "reason": "내신과 모의고사 성적이 아직 입력되지 않았습니다."}
    if mock_avg is None:
        return {"verdict": "수시 우선(모의고사 미입력)", "gap": None, "susi_weight": 70, "jeongsi_weight": 30,
                "reason": "모의고사 성적이 없어 내신만으로 판단했습니다. 정시 판단을 위해 모의고사 성적을 입력해주세요."}
    if naesin_avg is None:
        return {"verdict": "정시 우선(내신 미입력)", "gap": None, "susi_weight": 30, "jeongsi_weight": 70,
                "reason": "내신 성적이 없어 모의고사만으로 판단했습니다. 수시 판단을 위해 내신 성적을 입력해주세요."}

    gap = round(naesin_avg - mock_avg, 2)   # 음수면 내신이 더 좋다(등급은 낮을수록 우수)
    if gap <= -1.0:
        v, sw = "수시 중심", 75
        reason = f"내신 평균({naesin_avg})이 모의고사 평균({mock_avg})보다 {abs(gap)}등급 앞섭니다. 학생부 기반 수시가 뚜렷하게 유리합니다."
    elif gap <= -0.4:
        v, sw = "수시 우세", 65
        reason = f"내신({naesin_avg})이 모의고사({mock_avg})보다 {abs(gap)}등급 좋습니다. 수시를 주력으로 두되 정시도 함께 준비해야 합니다."
    elif gap < 0.4:
        v, sw = "수시·정시 병행", 50
        reason = f"내신({naesin_avg})과 모의고사({mock_avg})의 차이가 {abs(gap)}등급으로 크지 않습니다. 어느 쪽도 버릴 수 없는 구간입니다."
    elif gap < 1.0:
        v, sw = "정시 우세", 35
        reason = f"모의고사({mock_avg})가 내신({naesin_avg})보다 {gap}등급 좋습니다. 정시를 주력으로 두되 수시 카드도 확보해야 합니다."
    else:
        v, sw = "정시 중심", 25
        reason = f"모의고사({mock_avg})가 내신({naesin_avg})보다 {gap}등급 앞섭니다. 수능 위주 정시가 뚜렷하게 유리합니다."
    return {"verdict": v, "gap": gap, "susi_weight": sw, "jeongsi_weight": 100 - sw, "reason": reason}


def counsel_ref(student_name: str):
    return db.collection("counsel").document(sanitize_doc_id(student_name))


def load_counsel(student_name: str) -> dict:
    if db is None:
        return {}
    doc = counsel_ref(student_name).get()
    return doc.to_dict() if doc.exists else {}


def _collect_tendencies(data: dict) -> dict:
    """검사지별 결과를 모은다. 예전에 저장된 국어 검사도 끌어온다."""
    out = dict(data.get("tendencies") or {})
    legacy = data.get("tendency")
    if legacy and "korean" not in out:
        legacy = dict(legacy)
        legacy.setdefault("set", "korean")
        legacy.setdefault("set_name", TENDENCY_SETS["korean"]["name"])
        out["korean"] = legacy
    return out


def build_counsel_view(student_name: str) -> dict:
    """상담 카드 한 장에 필요한 모든 계산을 끝낸 형태로 돌려준다."""
    data = load_counsel(student_name)
    scale = normalize_scale(data.get("naesin_scale"))
    naesin = summarize_naesin(data.get("naesin", []), scale)
    mock = summarize_mock(data.get("mock", []))
    table = load_admission_table()
    track = judge_track(naesin["avg"], mock["avg"])
    tiers = pick_tier(table, naesin["avg"], mock["pct_avg"], scale)

    logs = data.get("logs", [])
    scored = [l for l in logs if _num(l.get("score")) is not None and _num(l.get("max_score")) not in (None, 0)]
    log_avg = round(sum(_num(l["score"]) / _num(l["max_score"]) * 100 for l in scored) / len(scored), 1) if scored else None

    # 과목 하나하나에도 반대 체계 환산을 달아준다
    other = "5" if scale == "9" else "9"
    naesin_rows = []
    for r in data.get("naesin", []):
        row = dict(r)
        p = _num(r.get("pct"))
        if p is not None:
            # 백분율이 있으면 두 체계 모두 정확한 정수 등급이 나온다
            row["grade_from_pct"] = pct_to_band(p, scale)
            row["grade_other"] = f"{pct_to_band(p, other)}등급"
            row["exact"] = True
        else:
            band = convert_grade_band(r.get("grade"), scale, other)
            row["grade_other"] = band["text"] if band else ""
            row["exact"] = False
        naesin_rows.append(row)

    result = {
        "student_name": student_name,
        "profile": data.get("profile", {}),
        "naesin_scale": scale,
        "naesin_rows": naesin_rows,
        "mock_rows": data.get("mock", []),
        "naesin": naesin,
        "mock": mock,
        "track": track,
        "tiers": tiers,
        "table_note": table.get("note", ""),
        "tendency": data.get("tendency"),
        "tendencies": _collect_tendencies(data),
        "record_text": data.get("record_text", ""),
        "record_eval": data.get("record_eval", ""),
        "record_eval_at": data.get("record_eval_at", ""),
        "analysis": data.get("analysis"),
        "summary": data.get("summary"),
        "logs": logs,
        "log_avg": log_avg,
        "memos": data.get("memos", []),
        "updated_at": data.get("updated_at", ""),
    }
    result["target_gap"] = build_target_gap(result)
    return result


def fmt_grade_block(view: dict) -> str:
    n, m, t = view["naesin"], view["mock"], view["track"]
    scale_txt = f"{n.get('scale', '9')}등급제"
    other_txt = f"{n.get('other_scale', '5')}등급제"
    conv = ""
    if n.get("avg") is not None and n.get("avg_other") is not None:
        how = "석차백분율로 정확히 환산" if n.get("exact") else "등급 구간의 중앙값으로 환산(근사)"
        conv = f" / {other_txt} 환산 {n['avg_other']}등급 ({how})"
    if n.get("pct_avg") is not None:
        conv += f" / 평균 석차백분율 상위 {n['pct_avg']}%"
    lines = [
        f"- 내신 등급 체계: {scale_txt} (2025학년도 고1부터 5등급제로 바뀌어 학년마다 체계가 다름)",
        f"- 내신 평균 등급: {n['avg'] if n['avg'] is not None else '미입력'}{conv} (주요과목 {n['main_avg'] if n['main_avg'] is not None else '-'}, 반영 {n['count']}과목)",
        f"- 학기별 내신: " + (", ".join(f"{x['term']} {x['avg']}등급" for x in n["by_term"]) or "미입력"),
        f"- 모의고사 최근({m['latest'] or '-'}) 상대평가 과목(국어·수학·탐구) 평균 등급: {m['avg'] if m['avg'] is not None else '미입력'}, 평균 백분위: {m['pct_avg'] if m['pct_avg'] is not None else '-'}",
        f"- 절대평가 과목(영어·한국사 등): {m.get('abs_text') or '미입력'} (백분위가 없고 등급만 나오는 과목이므로 위 평균에는 넣지 않았음)",
        f"- 원점수: {m.get('raw_text') or '미입력'}",
        f"- 모의고사 추이: " + (", ".join(f"{x['date']} {x['avg']}등급" for x in m["by_date"] if x["avg"] is not None) or "미입력"),
        f"- 내신·모의 격차 판정: {t['verdict']} ({t['reason']})",
    ]
    susi, jeongsi = view["tiers"]["susi"], view["tiers"]["jeongsi"]
    conv = view["tiers"].get("converted")
    if susi:
        base = f" (기준표는 {view['tiers'].get('table_scale', '9')}등급제 기준"
        base += f", 학생 내신을 {conv['value']}등급으로 환산해 대조)" if conv else ")"
        lines.append(f"- 학원 기준표상 수시 라인: {susi['tier']} / {susi['examples']}{base}")
    if jeongsi:
        lines.append(f"- 학원 기준표상 정시 라인: {jeongsi['tier']} / {jeongsi['examples']}")
    return "\n".join(lines)


def fmt_profile_block(view: dict) -> str:
    p = view.get("profile") or {}
    labels = [
        ("target_univ", "희망 대학"), ("target_major", "희망 학과"), ("track", "계열"),
        ("enrolled_at", "학원 등록일"), ("prev_academy", "이전 학습 이력"),
        ("strength", "강점"), ("weakness", "약점"), ("note", "특이사항"),
    ]
    lines = [f"- {label}: {p[key]}" for key, label in labels if p.get(key)]
    return "\n".join(lines) if lines else "- 인적사항 미입력"


def fmt_memo_block(view: dict) -> str:
    memos = view.get("memos") or []
    if not memos:
        return "- 상담 메모 없음"
    return "\n".join(f"- ({m.get('at', '')}) {m.get('text', '')}" for m in memos[:25])


def fmt_tendency_block(view: dict) -> str:
    sets = view.get("tendencies") or {}
    if not sets:
        return "- 학습 성향 검사 미실시"
    out = []
    for key, t in sets.items():
        axes = t.get("axes") or []
        if not axes:
            continue
        name = t.get("set_name") or get_tendency_set(key)["name"]
        out.append(f"[{name}] ({t.get('submitted_at', '')})")
        out += [f"  - {a['name']}: {a['score']}점 / 100 ({a['desc']})" for a in axes]
        if t.get("analysis"):
            out.append(f"  해석: {t['analysis'][:600]}")
    return "\n".join(out) if out else "- 학습 성향 검사 미실시"


def fmt_log_block(view: dict) -> str:
    logs = view.get("logs", [])[:15]
    if not logs:
        return "- 원내 학습 기록 없음"
    out = []
    for l in logs:
        s = ""
        if _num(l.get("score")) is not None:
            s = f" — {l.get('score')}/{l.get('max_score', '?')}점"
        out.append(f"- {l.get('date', '')} {l.get('title', '')}{s} {l.get('memo', '')}".rstrip())
    return "\n".join(out)


# ── 조회 ────────────────────────────────────────────────
@app.get("/api/counsel/tendency_sets")
def get_tendency_sets():
    """어떤 검사지가 있는지 목록만 (문항은 빼고)."""
    return {"success": True, "sets": [
        {"key": s["key"], "name": s["name"], "icon": s["icon"], "desc": s["desc"],
         "count": len(s["questions"]), "axes": [a["name"] for a in s["axes"]]}
        for s in TENDENCY_SETS.values()
    ]}


@app.get("/api/counsel/tendency_questions")
def get_tendency_questions(set: str = DEFAULT_TENDENCY_SET):
    """학습 성향 검사 문항 — 학생이 직접 응시하므로 로그인 없이도 문항만은 볼 수 있다."""
    t = get_tendency_set(set)
    return {"success": True, "key": t["key"], "name": t["name"], "icon": t["icon"],
            "desc": t["desc"], "axes": t["axes"], "questions": t["questions"]}


class TendencySubmitReq(BaseModel):
    student_name: str
    answers: dict
    set: str = DEFAULT_TENDENCY_SET


@app.post("/api/counsel/tendency_submit")
async def submit_tendency(req: TendencySubmitReq):
    """학생 본인이 검사를 제출한다. 채점은 서버에서만 한다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.student_name.strip()
    if not name:
        return {"success": False, "detail": "학생 정보가 없습니다."}

    s_doc = await asyncio.to_thread(lambda: db.collection("students").document(sanitize_doc_id(name)).get())
    if not s_doc.exists:
        return {"success": False, "detail": "등록된 학생이 아닙니다."}

    tset = get_tendency_set(req.set)
    axes = score_tendency(req.answers or {}, tset["key"])
    if sum(a["answered"] for a in axes) < len(tset["questions"]):
        return {"success": False, "detail": "모든 문항에 답해주세요."}

    payload = {
        "set": tset["key"], "set_name": tset["name"],
        "answers": {str(k): v for k, v in (req.answers or {}).items()},
        "axes": axes,
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "analysis": "",
    }
    data = load_counsel(name)
    tendencies = data.get("tendencies") or {}
    # 예전에 국어 검사만 있던 시절 자료를 이어받는다
    if not tendencies and data.get("tendency"):
        legacy = dict(data["tendency"])
        legacy.setdefault("set", "korean")
        legacy.setdefault("set_name", TENDENCY_SETS["korean"]["name"])
        tendencies["korean"] = legacy
    tendencies[tset["key"]] = payload

    update = {"student_name": name, "tendencies": tendencies,
              "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if tset["key"] == "korean":
        update["tendency"] = payload          # 예전 화면과의 호환
    await asyncio.to_thread(lambda: counsel_ref(name).set(update, merge=True))
    send_telegram_message(f"🧭 [{tset['name']}]\n{name} 학생이 검사를 마쳤습니다.")
    return {"success": True, "axes": axes, "set": tset["key"], "set_name": tset["name"]}


@app.get("/api/counsel/me/{student_name}")
def get_my_counsel(student_name: str):
    """학생 본인이 보는 상담 카드 — 원장님만 보는 항목(학생부 원문 등)은 빼고 준다."""
    if db is None:
        return {"success": False}
    v = build_counsel_view(urllib.parse.unquote(student_name))
    return {"success": True, "counsel": {
        "naesin": v["naesin"], "mock": v["mock"], "track": v["track"], "tiers": v["tiers"],
        "table_note": v["table_note"],
        "tendency": v["tendency"], "tendencies": v["tendencies"],
        "analysis": v["analysis"], "summary": v["summary"],
        "logs": v["logs"], "log_avg": v["log_avg"],
    }}


# ── 1) 성적 입력 & 분석 ─────────────────────────────────
class GradeSaveReq(BaseModel):
    student_name: str
    naesin: list = None
    mock: list = None
    naesin_scale: str = ""


@app.post("/api/admin/counsel/grades", dependencies=[Depends(verify_admin)])
def save_grades(req: GradeSaveReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.student_name.strip()
    if not name:
        return {"success": False, "detail": "학생을 먼저 선택해주세요."}
    payload = {"student_name": name, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    if req.naesin_scale:
        payload["naesin_scale"] = normalize_scale(req.naesin_scale)
    if req.naesin is not None:
        payload["naesin"] = req.naesin[:200]
    if req.mock is not None:
        # 💡 원점수를 넣었는데 등급이 비어 있으면, 그 회차 등급컷으로 등급을 채워준다.
        #    원장님이 직접 적어 넣은 등급이 있으면 건드리지 않는다.
        mock_rows = req.mock[:200]
        cut_cache = {}
        for r in mock_rows:
            if _num(r.get("grade")) is not None or _num(r.get("raw")) is None:
                continue
            date = str(r.get("date", "")).strip()
            if date not in cut_cache:
                cut_cache[date] = find_cut_set(date)
            cset = cut_cache[date]
            subj = str(r.get("subject", "")).strip()
            cuts = None
            if cset:
                for s in (cset.get("subjects") or []):
                    if str(s.get("subject", "")).strip() == subj:
                        cuts = s.get("cuts")
                        break
            if cuts is None and is_absolute_subject(subj):
                cuts = ABSOLUTE_DEFAULT_CUTS
            g = raw_to_grade(r.get("raw"), cuts)
            if g is not None:
                r["grade"] = g
                r["grade_auto"] = True
        payload["mock"] = mock_rows
    counsel_ref(name).set(payload, merge=True)
    return {"success": True, "counsel": build_counsel_view(name)}


# ── 학생 인적사항 (상담 기초 자료) ─────────────────────
PROFILE_FIELDS = [
    "phone", "parent_phone", "parent_relation", "birth", "enrolled_at",
    "prev_academy", "target_univ", "target_major", "track",
    "strength", "weakness", "note",
]


class ProfileSaveReq(BaseModel):
    student_name: str
    school: str = ""
    grade: str = ""
    class_name: str = ""
    profile: dict = None
    create: bool = False


@app.post("/api/admin/counsel/profile", dependencies=[Depends(verify_admin)])
def save_counsel_profile(req: ProfileSaveReq):
    """상담 카드의 학생 인적사항을 저장한다.
    create=True면 명단에 없는 학생도 새로 등록하면서 인적사항을 함께 넣는다.
    (새 학생이 들어오면 상담 자료부터 만들어 두고 싶다는 요청)"""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.student_name.strip()
    if not name:
        return {"success": False, "detail": "학생 이름을 입력해주세요."}

    s_ref = db.collection("students").document(sanitize_doc_id(name))
    exists = s_ref.get().exists
    if req.create and exists:
        return {"success": False, "detail": "이미 명단에 있는 이름입니다. 동명이인이면 이름 뒤에 구분을 붙여주세요."}
    if not req.create and not exists:
        return {"success": False, "detail": "명단에 없는 학생입니다."}

    student_patch = {}
    if req.school.strip():
        student_patch["school"] = req.school.strip()
    if req.grade.strip():
        student_patch["grade"] = req.grade.strip()
    if req.create or req.class_name:
        student_patch["class_name"] = req.class_name.strip()
    if student_patch or req.create:
        s_ref.set(student_patch, merge=True)

    # 상담 카드에는 알려진 항목만 담는다 (엉뚱한 값이 섞이지 않도록)
    incoming = req.profile or {}
    clean = {k: str(incoming.get(k, "") or "").strip() for k in PROFILE_FIELDS}
    counsel_ref(name).set({
        "student_name": name,
        "profile": clean,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }, merge=True)

    if req.create:
        send_telegram_message(f"🆕 [신규 학생 등록]\n{req.school.strip()} {req.grade.strip()} {name} 학생이 명단에 추가되었습니다.")
    return {"success": True, "counsel": build_counsel_view(name)}


class CounselNameReq(BaseModel):
    student_name: str


@app.post("/api/admin/counsel/analyze", dependencies=[Depends(verify_admin)])
async def analyze_counsel(req: CounselNameReq):
    """성적 → 수시/정시 비중, 가능 대학 라인, 맞춤 학습 프로그램."""
    name = req.student_name.strip()
    view = build_counsel_view(name)
    # 💡 정시만 준비하는 학생은 내신을 넣지 않고, 고1은 모의고사가 없을 수 있다.
    #    둘 중 하나만 있어도 분석하고, 없는 쪽은 '미입력'으로 두고 넘어간다.
    has_naesin = view["naesin"]["avg"] is not None
    has_mock = view["mock"]["avg"] is not None or bool(view["mock"].get("absolute"))
    if not has_naesin and not has_mock:
        return {"success": False, "detail": "내신이나 모의고사 중 한 가지는 입력해주세요. 둘 다 채우실 필요는 없습니다."}

    prompt = f"""당신은 20년 경력의 대입 진학 상담 전문가입니다. 아래 학생의 성적 자료를 보고 상담문을 작성하세요.

[학생] {name}

[학생 기본 정보]
{fmt_profile_block(view)}

[원장님 상담 메모]
{fmt_memo_block(view)}

[성적 및 사전 판정]
{fmt_grade_block(view)}

[목표 대학까지의 거리 — 학원이 보유한 입결 자료 기준]
{fmt_target_block(view)}

[학습 성향 검사]
{fmt_tendency_block(view)}

[원내 학습 기록]
{fmt_log_block(view)}

[반드시 지킬 것]
1. 위에 적힌 '학원 기준표상 라인'은 이 학원이 관리하는 기준표에서 계산된 것입니다. 그 라인을 벗어난 다른 대학 이름을 새로 지어내지 마세요. 대학 이름은 위에 적힌 것만 사용합니다.
2. 구체적인 입시 경쟁률·컷·환산점수 같은 수치를 지어내지 마세요. 확인되지 않은 수치는 절대 쓰지 않습니다.
3. 수시와 정시는 '둘 다 준비한다'가 전제입니다. 어느 쪽을 버리라고 말하지 말고, 비중을 어떻게 나눌지로 설명하세요.
4. 학생과 학부모가 함께 읽는 문서입니다. 단정적으로 겁주지 말고, 근거를 들어 차분하게 쓰세요.
5. 내신이나 모의고사 중 한쪽이 '미입력'이면, 그 부분은 "아직 자료가 없어 판단을 미룬다"고만 적고 넘어가세요. 없는 성적을 추정해서 쓰지 마세요. 정시만 준비하는 학생은 내신이 없을 수 있고, 고1은 모의고사가 없을 수 있습니다.
6. 영어와 한국사는 절대평가라 백분위가 없습니다. 이 과목은 등급만 가지고 이야기하고, 다른 과목 평균과 섞지 마세요.

[출력 형식 — 아래 제목을 그대로 쓰고 순서도 지킬 것]
## 1. 현재 성적 진단
(내신과 모의고사를 각각 한 문단으로. 강한 쪽과 약한 쪽을 분명히 짚을 것)

## 2. 수시 · 정시 비중
(위 판정과 비중 퍼센트를 근거와 함께 설명. 왜 그 비중인지 성적 숫자로 설명할 것)

## 3. 현재 지원 가능 라인과 목표까지의 거리
(수시 라인과 정시 라인을 각각 설명. 위에 주어진 대학 이름만 사용.
 지금 성적을 유지했을 때와, 한 등급 올렸을 때 어디까지 달라지는지도 함께 적을 것.
 [목표 대학까지의 거리]에 자료가 있으면, 목표까지 몇 등급/몇 백분위가 더 필요한지
 그 숫자를 그대로 인용해 알려주고, 그 차이를 메우려면 무엇을 해야 하는지 적을 것.
 자료가 없다고 적혀 있으면 그 사실만 밝히고 수치를 지어내지 마세요.)

## 4. 맞춤 학습 프로그램
(국어 과목을 중심으로, 지금 당장 해야 할 것을 4~6개 항목으로.
 각 항목은 '무엇을 / 얼마나 자주 / 어떻게 확인할지'가 들어가야 함.
 학습 성향 검사 결과가 있다면 그 약점을 반영할 것)

## 5. 앞으로 3개월 로드맵
(1개월 / 2개월 / 3개월 차에 각각 무엇을 달성해야 하는지)
"""
    try:
        res = await asyncio.to_thread(lambda: safe_generate(prompt))
        text = (res.text or "").strip()
    except Exception as e:
        return {"success": False, "detail": f"AI 분석 실패: {str(e)}"}

    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    counsel_ref(name).set({"analysis": {"text": text, "at": at}, "updated_at": at}, merge=True)
    return {"success": True, "analysis": {"text": text, "at": at}}


# ── 2) 학습 성향 분석 ───────────────────────────────────
class TendencyAnalyzeReq(BaseModel):
    student_name: str
    set: str = DEFAULT_TENDENCY_SET


@app.post("/api/admin/counsel/tendency_analyze", dependencies=[Depends(verify_admin)])
async def analyze_tendency(req: TendencyAnalyzeReq):
    name = req.student_name.strip()
    view = build_counsel_view(name)
    tset = get_tendency_set(req.set)
    t = (view.get("tendencies") or {}).get(tset["key"]) or {}
    if not t.get("axes"):
        return {"success": False, "detail": f"학생이 아직 '{tset['name']}' 검사를 하지 않았습니다."}

    answered = []
    for q in tset["questions"]:
        v = (t.get("answers") or {}).get(str(q["id"]))
        if v is not None:
            answered.append(f"- ({q['axis']}) {q['text']} → {v}점")

    axes_text = "\n".join(f"- {a['name']}: {a['score']}점 / 100 ({a['desc']})" for a in t["axes"])
    subject_hint = {
        "korean": "국어", "math": "수학", "english": "영어",
    }.get(tset["key"], "")
    prompt = f"""당신은 학습 코칭 전문가입니다. 아래 '{tset['name']}' 검사 결과를 해석해 주세요.

[학생] {name}
[검사지] {tset['name']} — {tset['desc']}
[척도] 각 축은 0~100점이며, 점수가 높을수록 그 영역이 잘 갖춰진 상태입니다.

[축별 점수]
{axes_text}

[문항별 응답] (5점 척도, 역채점 문항은 이미 뒤집어 계산됨)
{chr(10).join(answered)}

[성적 참고]
{fmt_grade_block(view)}

[반드시 지킬 것]
1. 성격을 단정하거나 낙인찍지 마세요. '지금의 습관'에 대한 이야기로 쓰세요.
2. 점수가 낮은 축을 지적할 때는 반드시 바꿀 방법을 함께 제시하세요.
3. 학생이 직접 읽습니다. 존중하는 어조로 쓰되, 문제는 분명히 짚으세요.
4. {"이 검사는 " + subject_hint + " 과목에 대한 것이므로, " + subject_hint + " 공부와 연결지어 구체적으로 쓰세요." if subject_hint else "이 검사는 특정 과목이 아니라 공부하는 태도 전반에 대한 것입니다. 과목을 특정하지 말고 생활 습관과 태도에 초점을 맞춰 쓰세요."}

[출력 형식 — 제목을 그대로 쓸 것]
## 1. 한눈에 보는 학습 성향
(가장 높은 축 2개와 가장 낮은 축 2개를 근거로 3~4문장 요약)

## 2. 지금 가장 큰 문제점
(낮은 축 중심으로 2~3가지. 각각 '이 습관이 시험장에서 어떤 결과로 나타나는지'까지 적을 것)

## 3. 발전 가능성
(높은 축을 지렛대 삼아 어디까지 좋아질 수 있는지. 근거 있는 기대치로)

## 4. 개선해야 할 점 — 실행 목록
(4~6개. 각 항목은 '이번 주부터 할 수 있는 행동' 수준으로 아주 구체적으로.
 예: '지문 읽기 전 발문 먼저 읽기' 같은 식)

## 5. 원장님께 드리는 지도 제안
(이 학생을 가르칠 때 어떤 점을 신경 써야 하는지 3가지)
"""
    try:
        res = await asyncio.to_thread(lambda: safe_generate(prompt))
        text = (res.text or "").strip()
    except Exception as e:
        return {"success": False, "detail": f"AI 분석 실패: {str(e)}"}

    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    t["analysis"] = text
    t["analyzed_at"] = at
    data = load_counsel(name)
    tendencies = _collect_tendencies(data)
    tendencies[tset["key"]] = t
    update = {"tendencies": tendencies, "updated_at": at}
    if tset["key"] == "korean":
        update["tendency"] = t
    counsel_ref(name).set(update, merge=True)
    return {"success": True, "analysis": text, "at": at, "set": tset["key"]}


# ── 3) 학생부 정성 평가 ─────────────────────────────────
DEFAULT_RECORD_CRITERIA = """[평가 영역과 기준]

■ 학업 역량 — 교과 학습의 깊이, 지적 호기심이 실제 탐구 활동으로 이어졌는가
  A: 교과 내용을 넘어선 심화 탐구가 있고, 그 과정과 결과가 구체적으로 적혀 있다
  B: 교과 관련 탐구가 있으나 깊이가 얕거나 결과 서술이 빈약하다
  C: 수업 참여는 성실하나 스스로 파고든 흔적이 드러나지 않는다
  D: 학업에 대한 태도나 역량을 읽어낼 근거가 거의 없다

■ 진로 역량 — 희망 전공과 활동의 연결성, 탐구의 일관성과 심화 정도
  A: 학년이 올라가며 전공 관련 활동이 이어지고 점점 깊어진다
  B: 전공 관련 활동이 있으나 단발적이거나 연결이 느슨하다
  C: 활동은 많으나 전공과의 관련성이 잘 드러나지 않는다
  D: 진로 방향을 읽어낼 근거가 거의 없다

■ 공동체 역량 — 협업·나눔·성실성이 구체적 장면으로 드러나는가
  A: 구체적 상황과 행동이 적혀 있어 인성이 장면으로 보인다
  B: 긍정적 평가는 있으나 추상적 칭찬에 가깝다
  C: 형식적인 문구 위주다
  D: 관련 서술이 거의 없다

■ 서술의 구체성 — 추상적 칭찬이 아니라 '무엇을 어떻게 했는지'가 적혀 있는가
  A: 활동의 동기·과정·결과·변화가 모두 드러난다
  B: 활동 내용은 있으나 과정이나 변화가 빠져 있다
  C: 결과만 나열되어 있다
  D: 무엇을 했는지조차 파악하기 어렵다

[추가 지침]
- 위 기준에 없는 잣대를 새로 만들어 쓰지 마세요.
"""


def get_record_criteria() -> str:
    if db is None:
        return DEFAULT_RECORD_CRITERIA
    try:
        doc = db.collection("settings").document("record_criteria").get()
        if doc.exists:
            t = str((doc.to_dict() or {}).get("text", "")).strip()
            if t:
                return t
    except Exception:
        pass
    return DEFAULT_RECORD_CRITERIA


@app.get("/api/admin/counsel/record_criteria", dependencies=[Depends(verify_admin)])
def get_record_criteria_admin():
    return {"success": True, "text": get_record_criteria(), "default": DEFAULT_RECORD_CRITERIA}


class RecordCriteriaReq(BaseModel):
    text: str


@app.post("/api/admin/counsel/record_criteria", dependencies=[Depends(verify_admin)])
def save_record_criteria(req: RecordCriteriaReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    db.collection("settings").document("record_criteria").set({"text": req.text.strip()})
    return {"success": True}


class RecordEvalReq(BaseModel):
    student_name: str
    record_text: str
    target_major: str = ""


@app.post("/api/admin/counsel/record_eval", dependencies=[Depends(verify_admin)])
async def eval_record(req: RecordEvalReq):
    name = req.student_name.strip()
    body = (req.record_text or "").strip()
    if len(body) < 50:
        return {"success": False, "detail": "학생부 내용을 조금 더 붙여넣어 주세요. (최소 50자)"}

    view = build_counsel_view(name)
    major = req.target_major.strip() or (view.get("profile") or {}).get("target_major") or "미정"
    criteria = get_record_criteria()
    prompt = f"""당신은 대학 학생부종합전형 서류평가 경험이 있는 평가자입니다.
아래 학생부 기록을 실제 서류평가 관점에서 정성적으로 평가하세요.

[학생] {name}
[희망 전공] {major}

[성적 참고]
{fmt_grade_block(view)}

[학생부 원문]
{body[:12000]}

[평가 기준 — 이 학원의 기준입니다. 반드시 이 기준만 사용하세요]
{criteria}

[반드시 지킬 것]
0. 위 [평가 기준]에 적힌 영역과 등급 잣대만 사용하세요. 기준에 없는 영역을 새로 만들거나, 기준과 다른 잣대로 등급을 매기지 마세요.
1. 반드시 원문에 실제로 적힌 문장을 근거로 인용하며 평가하세요. 원문에 없는 활동을 지어내지 마세요.
2. 합격/불합격이나 합격 확률을 단정하지 마세요.
3. 좋은 점만 나열하지 말고, 평가자 눈에 약해 보이는 지점을 분명히 지적하세요.

[출력 형식 — 제목을 그대로 쓸 것]
## 1. 총평
(3~4문장. 이 학생부가 남기는 전체 인상)

## 2. 영역별 평가
(위 [평가 기준]에 적힌 영역을 하나도 빠짐없이, 각각: 등급 / 근거가 된 원문 대목 / 평가 사유를 적을 것)

## 3. 강점 — 이 기록의 무기
(2~3가지. 어느 대목이 왜 강한지)

## 4. 약점 — 평가자가 걸릴 지점
(2~3가지. 구체적으로)

## 5. 남은 학기 보완 전략
(앞으로 어떤 활동·탐구를 채워야 하는지 4~5개. 실행 가능한 수준으로)
"""
    try:
        res = await asyncio.to_thread(lambda: safe_generate(prompt))
        text = (res.text or "").strip()
    except Exception as e:
        return {"success": False, "detail": f"AI 평가 실패: {str(e)}"}

    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    counsel_ref(name).set({
        "student_name": name, "record_text": body, "target_major": major,
        "record_eval": text, "record_eval_at": at, "updated_at": at,
    }, merge=True)
    return {"success": True, "record_eval": text, "at": at}


# ── 4) 학습 기록 누적 ───────────────────────────────────
class CounselLogReq(BaseModel):
    student_name: str
    date: str = ""
    title: str
    content: str = ""
    score: str = ""
    max_score: str = ""
    memo: str = ""


@app.post("/api/admin/counsel/log", dependencies=[Depends(verify_admin)])
def add_counsel_log(req: CounselLogReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.student_name.strip()
    if not name or not req.title.strip():
        return {"success": False, "detail": "학생과 제목을 입력해주세요."}

    entry = {
        "id": uuid.uuid4().hex[:12],
        "date": req.date.strip() or datetime.now().strftime("%Y-%m-%d"),
        "title": req.title.strip(),
        "content": req.content.strip(),
        "score": req.score.strip(),
        "max_score": req.max_score.strip(),
        "memo": req.memo.strip(),
    }
    data = load_counsel(name)
    logs = data.get("logs", [])
    logs.insert(0, entry)
    counsel_ref(name).set({
        "student_name": name, "logs": logs[:300],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }, merge=True)
    return {"success": True, "counsel": build_counsel_view(name)}


class CounselLogDeleteReq(BaseModel):
    student_name: str
    log_id: str


@app.post("/api/admin/counsel/log/delete", dependencies=[Depends(verify_admin)])
def delete_counsel_log(req: CounselLogDeleteReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.student_name.strip()
    data = load_counsel(name)
    logs = [l for l in data.get("logs", []) if l.get("id") != req.log_id]
    counsel_ref(name).set({"logs": logs, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}, merge=True)
    return {"success": True, "counsel": build_counsel_view(name)}


# ── 상담 메모 ──────────────────────────────────────────
#   상담하면서 그때그때 적어 둔 메모. 종합 소견서를 쓸 때 함께 읽는다.
class CounselMemoReq(BaseModel):
    student_name: str
    text: str


@app.post("/api/admin/counsel/memo", dependencies=[Depends(verify_admin)])
def add_counsel_memo(req: CounselMemoReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.student_name.strip()
    text = req.text.strip()
    if not name:
        return {"success": False, "detail": "학생을 먼저 선택해주세요."}
    if not text:
        return {"success": False, "detail": "메모 내용을 입력해주세요."}

    entry = {
        "id": uuid.uuid4().hex[:12],
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "text": text[:4000],
    }
    data = load_counsel(name)
    memos = data.get("memos", [])
    memos.insert(0, entry)
    counsel_ref(name).set({
        "student_name": name, "memos": memos[:300],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }, merge=True)
    return {"success": True, "counsel": build_counsel_view(name)}


class CounselMemoDeleteReq(BaseModel):
    student_name: str
    memo_id: str


@app.post("/api/admin/counsel/memo/delete", dependencies=[Depends(verify_admin)])
def delete_counsel_memo(req: CounselMemoDeleteReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.student_name.strip()
    data = load_counsel(name)
    memos = [m for m in data.get("memos", []) if m.get("id") != req.memo_id]
    counsel_ref(name).set({"memos": memos, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}, merge=True)
    return {"success": True, "counsel": build_counsel_view(name)}


# ── 통합 종합 소견 ──────────────────────────────────────
@app.post("/api/admin/counsel/summary", dependencies=[Depends(verify_admin)])
async def make_summary(req: CounselNameReq):
    """1~4번을 한 장으로 묶어 학부모 상담에 그대로 쓸 수 있는 소견서를 만든다."""
    name = req.student_name.strip()
    view = build_counsel_view(name)

    has = []
    if view["naesin"]["avg"] is not None or view["mock"]["avg"] is not None: has.append("성적")
    for k, t in (view.get("tendencies") or {}).items():
        if t.get("axes"):
            has.append(t.get("set_name") or get_tendency_set(k)["name"])
    if view.get("record_eval"): has.append("학생부평가")
    if view.get("logs"): has.append("학습기록")
    if view.get("memos"): has.append("상담메모")
    if not has:
        return {"success": False, "detail": "성적·성향검사·학생부·학습기록 중 아무거나 하나만 채우시면 소견서를 만들 수 있습니다."}

    prompt = f"""당신은 학원 원장님을 대신해 학부모 상담 소견서를 쓰는 진학 상담 전문가입니다.
아래 자료를 종합해 학부모님께 그대로 전달할 수 있는 한 장짜리 소견서를 작성하세요.

[학생] {name}
[확보된 자료] {', '.join(has)}

[학생 기본 정보]
{fmt_profile_block(view)}

[성적]
{fmt_grade_block(view)}

[학습 성향]
{fmt_tendency_block(view)}


[학생부 정성 평가]
{view.get('record_eval', '') or '평가 전'}

[원내 학습 기록]
{fmt_log_block(view)}
{f"(기록된 점수 평균 {view['log_avg']}%)" if view.get('log_avg') is not None else ''}

[원장님 상담 메모 — 직접 보고 적으신 내용입니다. 다른 어떤 자료보다 우선해서 반영하세요]
{fmt_memo_block(view)}

[반드시 지킬 것]
1. 위 자료에 없는 사실을 지어내지 마세요. 빠진 자료는 '아직 확보되지 않았다'고 적으세요.
1-1. [원장님 상담 메모]는 원장님이 학생을 직접 보고 적으신 것입니다. 숫자로 드러나지 않는 사정(가정 형편, 건강, 태도 변화, 진로 고민 등)이 담겨 있으니, 소견서 곳곳에 자연스럽게 녹여 반영하세요. 메모 내용과 다른 자료가 어긋나면 메모를 따르세요.
2. 대학 이름은 위 성적 항목에 적힌 라인의 대학만 쓰세요.
3. 학부모님이 읽습니다. 전문 용어는 풀어 쓰고, 아이를 깎아내리지 마세요.
4. 전체 분량은 A4 한 장 정도로 압축하세요.

[출력 형식 — 제목을 그대로 쓸 것]
## 한 줄 요약
(이 학생을 한 문장으로)

## 지금 어디에 서 있는가
(성적과 학습 태도를 묶어 4~6문장)

## 수시 · 정시 전략
(비중과 이유, 현재 가능 라인을 3~5문장으로)

## 이 아이의 가장 큰 강점
(2가지)

## 반드시 고쳐야 할 것
(2가지. 무엇을 어떻게 바꿀지까지)

## 앞으로 학원에서 할 지도
(4가지. 원장님이 실제로 실행할 항목으로)

## 가정에서 도와주실 일
(2~3가지)
"""
    try:
        res = await asyncio.to_thread(lambda: safe_generate(prompt))
        text = (res.text or "").strip()
    except Exception as e:
        return {"success": False, "detail": f"AI 소견 작성 실패: {str(e)}"}

    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    counsel_ref(name).set({"summary": {"text": text, "at": at}, "updated_at": at}, merge=True)
    return {"success": True, "summary": {"text": text, "at": at}}


# ── 입결 자료 (엑셀 업로드) ─────────────────────────────
#   원장님이 이미 엑셀로 관리하시는 입결 자료를 그대로 올려 쓴다.
#   파일마다 열 구성이 달라서, 먼저 열 이름을 읽어 보여주고
#   "이 열이 대학, 이 열이 등급" 하고 짝지어 받은 뒤에 저장한다.
UNIV_CHUNK_SIZE = 700          # Firestore 문서 하나에 담을 행 수
UNIV_MAX_ROWS = 30000


def _sheet_names(raw: bytes, filename: str):
    if (filename or "").lower().endswith(".csv"):
        return ["(csv)"]
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    names = list(wb.sheetnames)
    wb.close()
    return names


def _read_sheet(raw: bytes, filename: str, sheet: str = "", max_rows: int = 0):
    """엑셀(.xlsx) 또는 CSV를 읽어 [[셀,...], ...] 로 돌려준다.
    💡 실제 입결 파일은 시트가 여러 개이고 첫 시트가 표지인 경우가 많아
       시트를 고를 수 있어야 한다."""
    name = (filename or "").lower()
    if name.endswith(".csv"):
        for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("CSV 파일의 글자 인코딩을 읽지 못했습니다.")
        import csv as _csv
        return [row for row in _csv.reader(io.StringIO(text))]

    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ValueError("서버에 엑셀 읽기 기능이 준비되지 않았습니다. 잠시 후 다시 시도해주세요.")
    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    target = sheet if sheet and sheet in wb.sheetnames else wb.sheetnames[0]
    ws = wb[target]
    cap = max_rows or (UNIV_MAX_ROWS + 40)
    rows = []
    for r in ws.iter_rows(values_only=True):
        rows.append(["" if c is None else str(c).strip().replace("\n", " ") for c in r])
        if len(rows) >= cap:
            break
    wb.close()
    return rows


def _is_dummy_row(row) -> bool:
    """'*' 나 '-' 만 늘어놓은 안내용 더미 줄인지."""
    vals = [c for c in row if str(c).strip()]
    return bool(vals) and all(str(c).strip() in ("*", "-", "·", "–") for c in vals)


def _merge_header(rows, header_idx: int, span: int = 1):
    """헤더가 두 줄로 나뉜 파일이 많다. 윗줄과 아랫줄을 합쳐 하나로 만든다.
    예) 윗줄 '최종등록자 대학별환산' + 아랫줄 '70% cut' → '최종등록자 대학별환산 70% cut'"""
    if header_idx >= len(rows):
        return []
    width = max((len(r) for r in rows[header_idx:header_idx + span + 6]), default=0)

    def at(ri, ci):
        if ri >= len(rows):
            return ""
        r = rows[ri]
        return r[ci] if ci < len(r) else ""

    out = []
    for c in range(width):
        parts = []
        # 병합 셀 때문에 윗줄이 비어 있으면 왼쪽에서 이어받는다
        top = at(header_idx, c)
        if not top:
            for back in range(c - 1, -1, -1):
                prev = at(header_idx, back)
                if prev:
                    # 바로 왼쪽 칸이 비어 있던 구간만 이어받는다
                    if all(not at(header_idx, k) for k in range(back + 1, c + 1)):
                        top = prev
                    break
        if top:
            parts.append(top)
        for s in range(1, span + 1):
            sub = at(header_idx + s, c)
            if sub and sub not in parts:
                parts.append(sub)
        label = " ".join(parts).strip()
        out.append(label or f"(이름 없는 {c + 1}번째 열)")
    return out


def _guess_header_row(rows) -> int:
    """값이 가장 많이 채워진 앞쪽 줄을 헤더로 본다."""
    best, best_score = 0, -1
    for i, r in enumerate(rows[:25]):
        filled = sum(1 for c in r if str(c).strip())
        # 숫자만 잔뜩 있는 줄은 데이터일 가능성이 높으니 점수를 깎는다
        numeric = sum(1 for c in r if _num(c) is not None)
        score = filled - numeric * 2
        if score > best_score:
            best, best_score = i, score
    return best


@app.post("/api/admin/univ_table/preview", dependencies=[Depends(verify_admin)])
async def preview_univ_table(file: UploadFile = File(...), sheet: str = Form(""),
                             header_row: int = Form(-1), header_span: int = Form(1)):
    """올린 파일의 시트 목록·열 이름·앞부분 몇 줄을 돌려준다 (짝짓기 화면용)."""
    raw = await file.read()
    if not raw:
        return {"success": False, "detail": "빈 파일입니다."}
    try:
        sheets = _sheet_names(raw, file.filename)
        rows = _read_sheet(raw, file.filename, sheet, max_rows=80)
    except Exception as e:
        return {"success": False, "detail": f"파일을 읽지 못했습니다: {e}"}
    if not rows:
        return {"success": False, "detail": "내용이 없는 시트입니다."}

    hidx = header_row if header_row >= 0 else _guess_header_row(rows)
    hidx = max(0, min(hidx, len(rows) - 1))
    span = max(0, min(int(header_span or 0), 3))
    columns = _merge_header(rows, hidx, span)

    # 헤더 아래 실제 데이터 줄
    body = [r for r in rows[hidx + span + 1:] if any(str(c).strip() for c in r) and not _is_dummy_row(r)]
    width = len(columns)
    sample = [[(r[i] if i < len(r) else "") for i in range(width)] for r in body[:5]]

    # 전체 줄 수는 따로 세어 본다 (미리보기는 80줄만 읽었으므로)
    try:
        all_rows = _read_sheet(raw, file.filename, sheet, max_rows=UNIV_MAX_ROWS + 40)
        total = len([r for r in all_rows[hidx + span + 1:]
                     if any(str(c).strip() for c in r) and not _is_dummy_row(r)])
    except Exception:
        total = len(body)

    # 헤더를 고르기 쉽도록 앞 15줄을 그대로 보여준다
    head_preview = [[(r[i] if i < len(r) else "") for i in range(min(width or 12, 14))] for r in rows[:15]]

    return {"success": True, "sheets": sheets, "sheet": sheet or (sheets[0] if sheets else ""),
            "header_row": hidx, "header_span": span, "columns": columns, "sample": sample,
            "row_count": total, "filename": file.filename, "head_preview": head_preview}


@app.post("/api/admin/univ_table/import", dependencies=[Depends(verify_admin)])
async def import_univ_table(
    file: UploadFile = File(...),
    mapping: str = Form(...),
    label: str = Form(""),
    sheet: str = Form(""),
    header_row: int = Form(-1),
    header_span: int = Form(1),
    append: bool = Form(False),
    kind: str = Form("susi"),
):
    """짝지어 준 열 구성대로 입결 자료를 저장한다.
    kind는 이 자료가 수시용인지 정시용인지 — 견줄 성적이 달라진다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    try:
        m = json.loads(mapping)
    except ValueError:
        return {"success": False, "detail": "열 짝짓기 정보를 읽지 못했습니다."}

    raw = await file.read()
    try:
        rows = _read_sheet(raw, file.filename, sheet, max_rows=UNIV_MAX_ROWS + 40)
    except Exception as e:
        return {"success": False, "detail": f"파일을 읽지 못했습니다: {e}"}

    hidx = header_row if header_row >= 0 else _guess_header_row(rows)
    span = max(0, min(int(header_span or 0), 3))
    body = [r for r in rows[hidx + span + 1:]
            if any(str(c).strip() for c in r) and not _is_dummy_row(r)]
    if not body:
        return {"success": False, "detail": "저장할 내용이 없습니다. 헤더 줄을 제대로 골랐는지 확인해주세요."}

    def cell(r, key):
        idx = m.get(key)
        if idx is None or idx == "" or int(idx) < 0:
            return ""
        idx = int(idx)
        return str(r[idx]).strip() if idx < len(r) else ""

    fixed_metric = str(m.get("metric", "grade"))
    if fixed_metric not in ("grade", "percentile", "score", "eng_grade"):
        fixed_metric = "grade"
    kind = "jeongsi" if str(kind).strip().startswith("정") or str(kind).strip() == "jeongsi" else "susi"

    def metric_of(r):
        # 점수 종류가 행마다 다른 파일(예: '점수구분' 열에 백분위/환산점수)을 위해
        raw_txt = cell(r, "metric_col")
        if not raw_txt:
            return fixed_metric
        t = raw_txt.replace(" ", "")
        if "백분위" in t:
            return "percentile"
        if "등급" in t:
            return "grade"
        if "점수" in t or "환산" in t or "표준" in t or "원점" in t:
            return "score"
        return fixed_metric

    entries, skipped = [], 0
    for r in body:
        univ = cell(r, "univ")
        cut = _num(cell(r, "cut"))
        if not univ or cut is None:
            skipped += 1
            continue
        e = {
            "univ": univ[:60],
            "major": cell(r, "major")[:80],
            "track": cell(r, "track")[:20],
            "type": cell(r, "type")[:40],
            "cut": round(cut, 3),
            "metric": metric_of(r),
            "kind": kind,
            "note": cell(r, "note")[:120],
        }
        year = cell(r, "year")
        if year:
            e["year"] = year[:10]
        region = cell(r, "region")
        if region:
            e["region"] = region[:20]
        eng = _num(cell(r, "eng"))
        if eng is not None:
            e["eng"] = round(eng, 2)
        entries.append(e)
        if len(entries) >= UNIV_MAX_ROWS:
            break

    if not entries:
        return {"success": False, "detail": "대학 이름과 기준 점수를 모두 읽어낸 줄이 하나도 없습니다. 헤더 줄과 열 짝짓기를 확인해주세요."}

    existing = []
    if append:
        existing = load_univ_table()
    for d in list(db.collection("univ_table").stream()):
        d.reference.delete()

    merged = (existing + entries)[:UNIV_MAX_ROWS]
    for i in range(0, len(merged), UNIV_CHUNK_SIZE):
        db.collection("univ_table").document(f"chunk_{i // UNIV_CHUNK_SIZE:04d}").set(
            {"rows": merged[i:i + UNIV_CHUNK_SIZE]}
        )
    meta_prev = load_univ_meta() if append else {}
    labels = [x for x in [meta_prev.get("label", ""), (label or file.filename or "").strip()] if x]
    kinds = {}
    for e in merged:
        k = e.get("kind", "susi")
        kinds[k] = kinds.get(k, 0) + 1
    db.collection("settings").document("univ_table_meta").set({
        "label": " + ".join(dict.fromkeys(labels))[:160] or "입결 자료",
        "count": len(merged),
        "metric": fixed_metric,
        "susi_count": kinds.get("susi", 0),
        "jeongsi_count": kinds.get("jeongsi", 0),
        "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })

    total_rows = len(body)
    warning = ""
    if skipped > len(entries):
        warning = (f"전체 {total_rows}줄 중 {len(entries)}줄만 읽었고 {skipped}줄은 건너뛰었습니다. "
                   f"헤더 줄과 '대학'·'기준 점수' 열을 다시 확인해주세요.")
    elif len(entries) >= UNIV_MAX_ROWS:
        warning = f"자료가 너무 많아 앞에서부터 {UNIV_MAX_ROWS:,}줄까지만 저장했습니다."
    elif skipped:
        warning = f"{skipped}줄은 대학 이름이나 기준 점수가 비어 있어 건너뛰었습니다."
    return {"success": True, "count": len(entries), "stored": len(merged), "skipped": skipped,
            "total_rows": total_rows, "metric": fixed_metric, "warning": warning}


def load_univ_table() -> list:
    if db is None:
        return []
    out = []
    for d in db.collection("univ_table").stream():
        out.extend((d.to_dict() or {}).get("rows", []))
    return out


def load_univ_meta() -> dict:
    if db is None:
        return {}
    doc = db.collection("settings").document("univ_table_meta").get()
    return doc.to_dict() if doc.exists else {}


@app.get("/api/admin/univ_table", dependencies=[Depends(verify_admin)])
def get_univ_table(q: str = "", limit: int = 50):
    meta = load_univ_meta()
    rows = load_univ_table()
    key = q.strip()
    if key:
        rows = [r for r in rows if key in r.get("univ", "") or key in r.get("major", "")]
    return {"success": True, "meta": meta, "count": len(rows), "rows": rows[:max(1, min(500, limit))]}


@app.post("/api/admin/univ_table/clear", dependencies=[Depends(verify_admin)])
def clear_univ_table():
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    for d in db.collection("univ_table").stream():
        d.reference.delete()
    db.collection("settings").document("univ_table_meta").delete()
    return {"success": True}


def match_univ_rows(rows: list, univ: str, major: str = "") -> list:
    """목표 대학·학과에 해당하는 줄을 고른다. 학과가 비면 그 대학 전체."""
    u, mj = univ.strip(), major.strip()
    if not u:
        return []
    hit = [r for r in rows if u in r.get("univ", "") or r.get("univ", "") in u]
    if mj:
        narrowed = [r for r in hit if mj in r.get("major", "") or (r.get("major", "") and r.get("major", "") in mj)]
        if narrowed:
            return narrowed
    return hit


def student_scores(view: dict) -> dict:
    """입결 자료와 견줄 학생 성적을 한자리에 모은다."""
    eng = None
    for a in (view["mock"].get("absolute") or []):
        if "영어" in str(a.get("subject", "")):
            eng = _num(a.get("grade"))
            break
    return {
        "grade": view["naesin"]["avg"],
        "percentile": view["mock"]["pct_avg"],
        "score": view["mock"].get("raw_sum"),
        "eng_grade": eng,
    }


def compare_univ_row(r: dict, mine_all: dict):
    """입결 한 줄을 학생 성적과 견준다. 점수 종류마다 좋고 나쁨의 방향이 다르다."""
    metric = r.get("metric", "grade")
    cut = _num(r.get("cut"))
    if cut is None:
        return None
    if metric == "grade":
        mine, unit, lower_is_better = mine_all["grade"], "등급", True
    elif metric == "percentile":
        mine, unit, lower_is_better = mine_all["percentile"], "백분위", False
    elif metric == "eng_grade":
        mine, unit, lower_is_better = mine_all["eng_grade"], "영어 등급", True
    else:   # score — 원점수·표준점수·대학별 환산점수
        mine, unit, lower_is_better = mine_all["score"], "점", False
    gap = None if mine is None else round((mine - cut) if lower_is_better else (cut - mine), 2)
    return {
        "univ": r.get("univ", ""), "major": r.get("major", ""),
        "track": r.get("track", ""), "type": r.get("type", ""),
        "year": r.get("year", ""), "kind": r.get("kind", "susi"),
        "cut": cut, "metric": metric, "unit": unit,
        "mine": mine, "gap": gap,
        "reach": None if gap is None else gap <= 0,
        "eng_cut": r.get("eng"), "note": r.get("note", ""),
    }


def build_target_gap(view: dict) -> dict:
    """지금 성적으로 목표 대학까지 얼마나 모자란지 수시·정시로 갈라 계산한다."""
    profile = view.get("profile") or {}
    univ = str(profile.get("target_univ", "")).strip()
    major = str(profile.get("target_major", "")).strip()
    if not univ:
        return {"status": "no_target", "message": "학생 정보에 희망 대학을 적으면 목표까지 얼마나 남았는지 계산합니다."}

    rows = load_univ_table()
    if not rows:
        return {"status": "no_table", "univ": univ, "major": major,
                "message": "입결 자료가 아직 올라오지 않았습니다. 엑셀을 올리면 목표까지의 거리를 계산합니다."}

    hits = match_univ_rows(rows, univ, major)
    if not hits:
        return {"status": "not_found", "univ": univ, "major": major,
                "message": f"입결 자료에서 '{univ}{(' ' + major) if major else ''}'을(를) 찾지 못했습니다. 대학 이름이 자료와 같은지 확인해주세요."}

    mine_all = student_scores(view)
    groups = {"susi": [], "jeongsi": []}
    for r in hits[:200]:
        item = compare_univ_row(r, mine_all)
        if item:
            groups[item["kind"] if item["kind"] in groups else "susi"].append(item)

    out = {"status": "ok", "univ": univ, "major": major}
    for k in ("susi", "jeongsi"):
        items = groups[k]
        scored = sorted([i for i in items if i["gap"] is not None], key=lambda x: x["gap"])
        out[k] = {
            "items": items[:20],
            "closest": scored[0] if scored else None,
            "reachable": sum(1 for i in scored if i["reach"]),
            "total": len(scored),
            "count": len(items),
        }
    if not out["susi"]["count"] and not out["jeongsi"]["count"]:
        return {"status": "not_found", "univ": univ, "major": major,
                "message": "찾은 줄에 기준 점수가 비어 있습니다."}
    return out


class UnivMajorsReq(BaseModel):
    student_name: str
    univ: str
    kind: str = ""
    only_reachable: bool = False


@app.post("/api/admin/univ_table/majors", dependencies=[Depends(verify_admin)])
def get_univ_majors(req: UnivMajorsReq):
    """대학 하나를 골라, 그 대학에서 지금 성적으로 가능한 학과를 찾아준다.
    지원 가능 라인에 뜬 대학을 눌렀을 때 쓴다."""
    univ = req.univ.strip()
    if not univ:
        return {"success": False, "detail": "대학 이름이 비어 있습니다."}

    rows = load_univ_table()
    if not rows:
        return {"success": False, "detail": "입결 자료가 아직 올라오지 않았습니다. 왼쪽 '입결 자료(엑셀) 관리'에서 먼저 올려주세요."}

    hits = match_univ_rows(rows, univ, "")
    if not hits:
        return {"success": False,
                "detail": f"입결 자료에서 '{univ}'을(를) 찾지 못했습니다.\n'경기권 대학'처럼 묶어 부르는 이름은 찾을 수 없습니다. 기준표에 실제 대학 이름을 적어주세요."}

    view = build_counsel_view(req.student_name.strip()) if req.student_name.strip() else None
    mine_all = student_scores(view) if view else {"grade": None, "percentile": None, "score": None, "eng_grade": None}

    groups = {"susi": [], "jeongsi": []}
    for r in hits[:600]:
        item = compare_univ_row(r, mine_all)
        if not item:
            continue
        k = item["kind"] if item["kind"] in groups else "susi"
        if req.kind and req.kind in groups and k != req.kind:
            continue
        if req.only_reachable and item["reach"] is not True:
            continue
        groups[k].append(item)

    out = {"success": True, "univ": univ, "mine": mine_all}
    for k in ("susi", "jeongsi"):
        items = groups[k]
        # 도달한 것을 먼저, 그 안에서는 기준이 높은(=좋은) 학과부터
        reached = sorted([i for i in items if i["reach"] is True],
                         key=lambda x: x["gap"])
        near = sorted([i for i in items if i["reach"] is False], key=lambda x: x["gap"])
        unknown = [i for i in items if i["reach"] is None]
        out[k] = {
            "reached": reached[:80],
            "near": near[:80],
            "unknown": unknown[:80],
            "count": len(items),
            "reach_count": len(reached),
        }
    return out


def fmt_target_block(view: dict) -> str:
    g = view.get("target_gap") or {}
    if g.get("status") != "ok":
        return f"- {g.get('message', '목표 대학 정보 없음')}"
    lines = [f"- 목표: {g['univ']} {g.get('major', '')}".rstrip()]
    for key, title in (("susi", "수시"), ("jeongsi", "정시")):
        blk = g.get(key) or {}
        if not blk.get("count"):
            lines.append(f"- [{title}] 이 대학의 {title} 자료가 없습니다.")
            continue
        c = blk.get("closest")
        if not c:
            lines.append(f"- [{title}] 자료는 {blk['count']}건 있으나 학생 성적이 없어 비교하지 못했습니다.")
        elif c["reach"]:
            lines.append(f"- [{title}] 가장 가까운 기준({c['univ']} {c['major']} {c['type']}): 기준 {c['cut']}{c['unit']}, 현재 {c['mine']}{c['unit']} — 이미 넘었습니다.")
        else:
            lines.append(f"- [{title}] 가장 가까운 기준({c['univ']} {c['major']} {c['type']}): 기준 {c['cut']}{c['unit']}, 현재 {c['mine']}{c['unit']} — {abs(c['gap'])}{c['unit']} 모자랍니다.")
        lines.append(f"  자료 {blk['total']}건 중 현재 성적으로 기준을 넘은 것: {blk['reachable']}건")
        for i in blk["items"][:6]:
            if i["gap"] is None:
                continue
            state = "도달" if i["reach"] else f"{abs(i['gap'])}{i['unit']} 부족"
            eng = f", 영어 {i['eng_cut']}등급 필요" if i.get("eng_cut") is not None else ""
            lines.append(f"  · {i['univ']} {i['major']} ({i['type']}) 기준 {i['cut']}{i['unit']}{eng} → {state}")
    return "\n".join(lines)


# ── 대학 라인 기준표 관리 ───────────────────────────────
@app.get("/api/admin/counsel/admission_table", dependencies=[Depends(verify_admin)])
def get_admission_table():
    return {"success": True, "table": load_admission_table(), "default": DEFAULT_ADMISSION_TABLE}


class AdmissionTableReq(BaseModel):
    susi: list
    jeongsi: list
    note: str = ""
    scale: str = "9"


@app.post("/api/admin/counsel/admission_table", dependencies=[Depends(verify_admin)])
def save_admission_table(req: AdmissionTableReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    db.collection("settings").document("admission_table").set({
        "susi": req.susi, "jeongsi": req.jeongsi,
        "scale": normalize_scale(req.scale),
        "note": req.note.strip() or DEFAULT_ADMISSION_TABLE["note"],
    })
    return {"success": True, "table": load_admission_table()}


# ⚠️ 이 라우트는 반드시 파일에서 가장 마지막에 등록되어야 한다.
#    FastAPI는 먼저 등록된 경로부터 맞춰보기 때문에, 이 {student_name} 라우트가
#    위에 있으면 /api/admin/counsel/admission_table 까지 학생 이름으로 삼켜버린다.
@app.get("/api/admin/counsel/{student_name}", dependencies=[Depends(verify_admin)])
def get_counsel_admin(student_name: str):
    if db is None:
        return {"success": False}
    return {"success": True, "counsel": build_counsel_view(urllib.parse.unquote(student_name))}
