import io
import os
import re
import json
import time
import uuid
import hashlib
import secrets
import random
import requests
import threading
import mimetypes
import urllib.parse
import asyncio
import subprocess
import tempfile
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
from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS
import imageio_ffmpeg

# ─────────────────────────────────────────────────────────
# 디렉토리 생성
# ─────────────────────────────────────────────────────────
for folder in ["exams", "homeworks", "board", "chat", "profiles", "explain_videos"]:
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
        # 💡 2024년 10월 이후 새로 만든 Firebase 프로젝트는 기본 버킷 이름이
        # "프로젝트ID.appspot.com"이 아니라 "프로젝트ID.firebasestorage.app"이다.
        # FIREBASE_BUCKET 환경변수가 없을 때는(설정을 깜빡했을 때) 예전 방식 대신
        # 이 새 방식을 기본값으로 쓴다 — 실제 버킷 이름과 안 맞아 업로드가 전부
        # 임시 저장소로 빠지던 문제(logyedu24h 프로젝트에서 실제로 겪음)의 재발 방지.
        bucket_name = os.environ.get("FIREBASE_BUCKET", f"{project_id}.firebasestorage.app").replace("gs://", "").strip("/")

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
STUDENT_SIGNUP_CODE = os.environ.get("STUDENT_SIGNUP_CODE", "logyedu2024")

# 💡 관리자는 이제 한 명("원장님")이 아니라 여러 명일 수 있다. 각자 이름과 비밀번호로
# 로그인하고, 자기 비밀번호는 스스로 바꿀 수 있다. 다만 이 관리자 권한은 학습실 화면
# 안에서의 역할일 뿐이며, 서버 코드나 배포에는 전혀 접근할 수 없다.
_admin_tokens = {}   # token -> 관리자 이름


def _hash_password(raw: str, salt: str) -> str:
    return hashlib.sha256((salt + ":" + raw).encode("utf-8")).hexdigest()


def _new_salt() -> str:
    return secrets.token_hex(8)


def get_admin_doc(name: str):
    if db is None or not name:
        return None
    doc = db.collection("admins").document(name).get()
    return doc.to_dict() if doc.exists else None


def ensure_owner_admin():
    """처음 실행될 때, 환경변수 비밀번호로 '원장님' 계정을 DB에 만들어 둔다.
    이후로는 이 계정의 비밀번호도 DB에서 관리되며, 마이페이지에서 직접 바꿀 수 있다.
    (즉 한 번 만들어지고 나면 ADMIN_PASSWORD 환경변수를 바꿔도 반영되지 않는다 —
    비밀번호는 그때부터 원장님이 직접 관리하는 것이기 때문이다.)"""
    if db is None:
        return
    ref = db.collection("admins").document("원장님")
    if not ref.get().exists:
        salt = _new_salt()
        ref.set({
            "name": "원장님",
            "password_hash": _hash_password(ADMIN_PASSWORD, salt),
            "salt": salt,
            "is_owner": True,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })


def issue_admin_token(name: str) -> str:
    token = uuid.uuid4().hex
    _admin_tokens[token] = name
    # 💡 토큰을 메모리에만 두면, 코드를 배포할 때마다(서버 재시작) 로그인해 있던
    # 관리자가 전부 강제 로그아웃됐다 — 그것도 화면에 이유가 안 보이는 채로.
    # DB에도 함께 저장해 재시작 후에도 같은 토큰이 계속 통하게 한다.
    if db is not None:
        try:
            db.collection("admin_sessions").document(token).set({
                "name": name, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
        except Exception:
            pass
    return token


def _resolve_admin_token(token: str):
    """메모리 캐시에 먼저 있는지 보고, 없으면(막 재시작된 서버) DB에서 찾아 캐시를 채운다."""
    if token in _admin_tokens:
        return _admin_tokens[token]
    if db is None:
        return None
    try:
        doc = db.collection("admin_sessions").document(token).get()
    except Exception:
        return None
    if not doc.exists:
        return None
    name = (doc.to_dict() or {}).get("name")
    if name:
        _admin_tokens[token] = name
    return name


def verify_admin(x_admin_token: Optional[str] = Header(None)):
    if not x_admin_token or _resolve_admin_token(x_admin_token) is None:
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    return True


def current_admin_name(x_admin_token: Optional[str] = Header(None)) -> str:
    name = _resolve_admin_token(x_admin_token) if x_admin_token else None
    if not name:
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    return name


# ─────────────────────────────────────────────────────────
# 레벨업 룰렛
#   레벨업할 때마다 한 번, 그 레벨 전용 룰렛을 돌려 상품을 받는다.
#   상품 내용은 원장님이 직접 적고, 레벨이 높을수록 더 좋은 상품을 넣을 수 있다.
#   기본값은 꽝이 압도적으로 많고, 꽝 칸을 상품 칸 바로 옆에 둬서
#   "아깝게 꽝"이 되는 느낌을 자주 주도록 배치했다.
# ─────────────────────────────────────────────────────────
def _default_roulette_config():
    def miss():
        return {"label": "꽝", "is_miss": True}

    def prize(label):
        return {"label": label, "is_miss": False}

    def wheel(prizes):
        """꽝 6~7칸 사이사이에 상품을 끼워 넣는다 — 상품 옆은 항상 꽝이라
        '조금만 더 갔으면...' 하는 느낌이 나도록."""
        slices = [miss() for _ in range(7)]
        for i, p in enumerate(prizes):
            pos = 1 + i * 3
            slices.insert(min(pos, len(slices)), p)
        return slices

    return {
        "1": wheel([prize("칭찬 한마디 🌟")]),
        "2": wheel([prize("사탕 1개 🍬")]),
        "3": wheel([prize("칭찬 스티커 🏅")]),
        "4": wheel([prize("간식 교환권 🍪")]),
        "5": wheel([prize("숙제 힌트 카드 💡")]),
        "6": wheel([prize("간식 교환권 🍪"), prize("칭찬 상장 📜")]),
        "7": wheel([prize("작은 선물 🎁")]),
        "8": wheel([prize("작은 선물 🎁"), prize("특별 간식 🍰")]),
        "9": wheel([prize("특별 선물 🎁")]),
        "10": wheel([prize("원장님 특별 선물 🏆"), prize("깜짝 선물 🎉")]),
    }


def get_roulette_config():
    """레벨(1~10)별 룰렛 칸 구성. 원장님이 저장한 값이 있으면 그걸, 없는 레벨은 기본값으로 채운다."""
    defaults = _default_roulette_config()
    if db is None:
        return defaults
    doc = db.collection("settings").document("roulette_config").get()
    saved = (doc.to_dict() or {}).get("levels") if doc.exists else None
    levels = dict(defaults)
    if saved:
        for k, v in saved.items():
            if v:
                levels[str(k)] = v
    return levels


@app.get("/api/admin/roulette_config", dependencies=[Depends(verify_admin)])
def get_roulette_config_admin():
    return {"success": True, "levels": get_roulette_config()}


class RouletteConfigReq(BaseModel):
    level: int
    slices: list


@app.post("/api/admin/roulette_config", dependencies=[Depends(verify_admin)])
def save_roulette_config(req: RouletteConfigReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    if req.level < 1 or req.level > 10:
        return {"success": False, "detail": "레벨은 1~10 사이여야 합니다."}
    slices = []
    for s in (req.slices or []):
        label = str((s or {}).get("label", "")).strip()
        if not label:
            return {"success": False, "detail": "빈 칸 내용이 있습니다."}
        slices.append({"label": label, "is_miss": bool((s or {}).get("is_miss"))})
    if len(slices) < 2:
        return {"success": False, "detail": "룰렛 칸은 최소 2개 이상이어야 합니다."}
    levels = get_roulette_config()
    levels[str(req.level)] = slices
    db.collection("settings").document("roulette_config").set({"levels": levels}, merge=True)
    return {"success": True}


@app.get("/api/student/roulette_config")
def get_roulette_config_student(level: int = 1):
    levels = get_roulette_config()
    level = max(1, min(10, int(level or 1)))
    slices = levels.get(str(level)) or levels.get("1")
    return {"success": True, "level": level, "slices": slices}


@app.get("/api/student/roulette/eligible")
def roulette_eligible(student_name: str):
    """학습실에 들어왔을 때, 아직 안 돌린 룰렛이 있는지 조용히 확인한다."""
    if db is None:
        return {"success": True, "eligible": False}
    doc = db.collection("students").document(student_name.strip()).get()
    if not doc.exists:
        return {"success": True, "eligible": False}
    data = doc.to_dict()
    info = compute_level_info(data.get("xp"))
    last = _num(data.get("roulette_last_level")) or 0
    return {"success": True, "eligible": info["level"] > last, "level": info["level"]}


class RouletteSpinReq(BaseModel):
    student_name: str


@app.post("/api/student/roulette/spin")
async def spin_roulette(req: RouletteSpinReq):
    """당첨 여부는 반드시 서버가 정한다 — 학생이 보내는 레벨/결과 값은 신뢰하지 않고,
    학생 명단에 저장된 실제 경험치로 지금 레벨을 다시 계산한다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.student_name.strip()
    doc = await asyncio.to_thread(lambda: db.collection("students").document(name).get())
    if not doc.exists:
        return {"success": False, "detail": "학생 명단에서 찾을 수 없습니다."}
    data = doc.to_dict()
    info = compute_level_info(data.get("xp"))
    level = info["level"]
    last = _num(data.get("roulette_last_level")) or 0
    if level <= last:
        return {"success": False, "detail": "지금 레벨에서는 이미 룰렛을 돌렸습니다. 다음 레벨업을 기다려주세요."}

    levels = get_roulette_config()
    slices = levels.get(str(level)) or levels.get("1")
    idx = random.randrange(len(slices))
    won = slices[idx]

    await asyncio.to_thread(
        lambda: db.collection("students").document(name).set({"roulette_last_level": level}, merge=True)
    )
    await asyncio.to_thread(
        lambda: db.collection("reports").add({
            "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "student_name": name, "school": data.get("school", ""), "grade": data.get("grade", ""),
            "task_name": f"Lv.{level} 룰렛", "type": "룰렛", "score": won["label"],
        })
    )
    if not won["is_miss"]:
        send_telegram_message(f"🎰 [룰렛 당첨]\n{name} 학생이 Lv.{level} 룰렛에서 '{won['label']}'에 당첨됐습니다!")

    return {"success": True, "level": level, "index": idx, "slices": slices,
            "label": won["label"], "is_miss": won["is_miss"]}



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


def friendly_ai_error(err) -> str:
    """구글 AI가 돌려주는 영어 오류를 무슨 일인지 바로 알 수 있는 말로 바꾼다.
    💡 '429 Your prepayment credits are depleted...' 같은 문구가 그대로 화면에 떠서
       결제 문제인지 프로그램 문제인지 구분할 수 없던 적이 있다. 원문도 함께 남겨
       원인 추적은 그대로 되게 한다."""
    raw = str(err or "").strip()
    low = raw.lower()

    if "prepayment credits are depleted" in low or "billing" in low and "credit" in low:
        head = ("AI 사용 크레딧이 모두 떨어졌습니다. 프로그램 문제가 아니라 결제 문제입니다.\n"
                "Google AI Studio(https://ai.studio/projects)에서 크레딧을 충전하시거나 결제 수단을 연결해주세요.\n"
                "충전되면 출제·해설 영상·채점 등 AI 기능이 곧바로 다시 동작합니다.")
    elif "quota" in low or "resource_exhausted" in low or "rate limit" in low or low.startswith("429"):
        head = ("지금 AI 요청이 한도를 넘었습니다(하루 사용량 또는 분당 횟수 초과).\n"
                "잠시 뒤 다시 시도하시거나, Google AI Studio에서 사용 한도를 올려주세요.")
    elif "api key" in low or "permission" in low or "unauthenticated" in low or low.startswith("401") or low.startswith("403"):
        head = ("AI 열쇠(API 키)가 없거나 권한이 없습니다. 서버 설정의 GOOGLE_API_KEY를 확인해주세요.")
    elif "no longer available" in low or "not found" in low and "model" in low:
        head = ("쓰던 AI 모델이 더 이상 제공되지 않습니다. 잠시 뒤 다시 시도해주세요.\n"
                "계속 같은 오류가 나면 모델 목록을 손봐야 합니다.")
    elif "safety" in low or "blocked" in low:
        head = ("AI가 안전 정책을 이유로 이 자료에 대한 답을 막았습니다.\n"
                "자료의 표현을 조금 바꾸거나 일부를 덜어내고 다시 시도해주세요.")
    elif "deadline" in low or "timeout" in low or "timed out" in low:
        head = ("AI 응답이 제한 시간을 넘겼습니다. 자료를 조금 줄여서 다시 시도해주세요.")
    else:
        return raw

    return f"{head}\n\n(원래 오류: {raw[:300]})"


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
        if db is None:
            return {"success": False, "detail": "DB 연결 오류"}
        await asyncio.to_thread(ensure_owner_admin)
        # 이름 칸을 비워둔 채 비밀번호만 넣으면(예전 방식) 원장님 계정으로 시도한다.
        admin_name = req.student_name.strip()
        if admin_name in ("", "관리자"):
            admin_name = "원장님"
        adoc = await asyncio.to_thread(get_admin_doc, admin_name)
        # 💡 예전에는 이름 칸이 뭘 넣든 무시되고 비밀번호만 맞으면 원장님으로 로그인됐다.
        #    그 습관대로 아무 이름(예: 원장님 본명)을 넣는 분들이 있으니, 등록된 관리자
        #    이름이 아니더라도 비밀번호가 원장님 것과 같으면 원장님으로 로그인시킨다.
        if not adoc and admin_name != "원장님":
            owner_doc = await asyncio.to_thread(get_admin_doc, "원장님")
            if owner_doc and _hash_password(req.admin_password, owner_doc.get("salt", "")) == owner_doc.get("password_hash"):
                adoc, admin_name = owner_doc, "원장님"
        if adoc and _hash_password(req.admin_password, adoc.get("salt", "")) == adoc.get("password_hash"):
            token = issue_admin_token(admin_name)
            return {
                "success": True, "is_admin": True, "admin_token": token,
                "admin_name": admin_name, "is_owner": bool(adoc.get("is_owner")),
            }
        return {"success": False, "detail": "관리자 이름 또는 비밀번호가 올바르지 않습니다."}

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


# ─────────────────────────────────────────────────────────
# 관리자 계정 관리
#   - 목록/추가/삭제는 원장님(is_owner)만
#   - 비밀번호 변경은 로그인한 그 관리자 본인만, 현재 비밀번호를 확인한 뒤에
# ─────────────────────────────────────────────────────────
@app.get("/api/admin/admins", dependencies=[Depends(verify_admin)])
def list_admins():
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    rows = []
    for d in db.collection("admins").stream():
        a = d.to_dict() or {}
        rows.append({
            "name": a.get("name", d.id),
            "is_owner": bool(a.get("is_owner")),
            "created_at": a.get("created_at", ""),
        })
    rows.sort(key=lambda x: (not x["is_owner"], x["name"]))
    return {"success": True, "admins": rows}


class AdminCreateReq(BaseModel):
    name: str
    password: str


@app.post("/api/admin/admins")
def create_admin(req: AdminCreateReq, name: str = Depends(current_admin_name)):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    me = get_admin_doc(name)
    if not me or not me.get("is_owner"):
        return {"success": False, "detail": "원장님 계정만 관리자를 추가할 수 있습니다."}
    new_name = req.name.strip()
    if not new_name:
        return {"success": False, "detail": "이름을 입력해 주세요."}
    if len(req.password) < 4:
        return {"success": False, "detail": "비밀번호는 4자 이상이어야 합니다."}
    if get_admin_doc(new_name):
        return {"success": False, "detail": "이미 있는 관리자 이름입니다."}
    salt = _new_salt()
    db.collection("admins").document(new_name).set({
        "name": new_name,
        "password_hash": _hash_password(req.password, salt),
        "salt": salt,
        "is_owner": False,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    return {"success": True}


class AdminDeleteReq(BaseModel):
    name: str


@app.post("/api/admin/admins/delete")
def delete_admin(req: AdminDeleteReq, name: str = Depends(current_admin_name)):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    me = get_admin_doc(name)
    if not me or not me.get("is_owner"):
        return {"success": False, "detail": "원장님 계정만 관리자를 삭제할 수 있습니다."}
    target = req.name.strip()
    if target == "원장님":
        return {"success": False, "detail": "원장님 계정은 삭제할 수 없습니다."}
    db.collection("admins").document(target).delete()
    return {"success": True}


class AdminPasswordReq(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/admin/change_password")
def change_admin_password(req: AdminPasswordReq, name: str = Depends(current_admin_name)):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    me = get_admin_doc(name)
    if not me:
        return {"success": False, "detail": "계정 정보를 찾을 수 없습니다."}
    if _hash_password(req.current_password, me.get("salt", "")) != me.get("password_hash"):
        return {"success": False, "detail": "현재 비밀번호가 올바르지 않습니다."}
    if len(req.new_password) < 4:
        return {"success": False, "detail": "새 비밀번호는 4자 이상이어야 합니다."}
    salt = _new_salt()
    db.collection("admins").document(name).update({
        "password_hash": _hash_password(req.new_password, salt),
        "salt": salt,
    })
    return {"success": True}


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
    if not profile.get("subjects"):
        profile["subjects"] = ["korean"]   # 과목 등록 전 예전 학생은 국어만 듣던 학생들이었다
    return {"success": True, "profile": profile, "reports": reports, "level_info": compute_level_info(profile.get("xp"))}


EXPLANATION_MAX_CHARS = 1200      # 문항 하나당 해설 길이 상한


def parse_explanation_map(raw) -> dict:
    """문항 번호 -> 해설 글 묶음을 안전하게 정리한다.
    문자열(JSON), 딕셔너리, 목록 어느 형태로 와도 {"1": "...", "2": "..."} 로 맞춘다."""
    if not raw:
        return {}
    data = raw
    if isinstance(raw, str):
        txt = raw.strip()
        if not txt:
            return {}
        try:
            data = json.loads(txt)
        except Exception:
            return {}
    out = {}
    if isinstance(data, dict):
        pairs = data.items()
    elif isinstance(data, list):
        # [{"no":1,"text":"..."}] 또는 ["1번 해설", ...] 두 형태를 모두 받는다
        pairs = []
        for i, item in enumerate(data):
            if isinstance(item, dict):
                pairs.append((item.get("no", i + 1), item.get("text", item.get("explanation", ""))))
            else:
                pairs.append((i + 1, item))
    else:
        return {}
    for k, v in pairs:
        num = _num(k)
        text = str(v or "").strip()
        if num is None or not text:
            continue
        n = int(num)
        if n >= 1:
            out[str(n)] = text[:EXPLANATION_MAX_CHARS]
    return out


def explanations_for(kind: str, title: str) -> dict:
    """그 과제·시험·퀴즈에 저장해둔 문항별 해설을 꺼낸다. 없으면 빈 묶음."""
    if db is None or not title:
        return {}
    try:
        if kind in ("과제 제출", "homework"):
            d = db.collection("homeworks").document(sanitize_doc_id(title)).get()
            return parse_explanation_map((d.to_dict() or {}).get("explanations")) if d.exists else {}
        if kind in ("모의고사", "exam"):
            d = db.collection("exams").document(sanitize_doc_id(title)).get()
            return parse_explanation_map((d.to_dict() or {}).get("explanations")) if d.exists else {}
        if kind in ("출제 문제", "bank"):
            for d in db.collection("questions").stream():
                row = d.to_dict() or {}
                if str(row.get("title", "")).strip() != str(title).strip():
                    continue
                parsed = parse_question_bank_content(row.get("content", ""))
                return {str(n): str(t).strip()[:EXPLANATION_MAX_CHARS]
                        for n, t in parsed["explanations"].items() if str(t).strip()}
            return {}
        if kind in ("타임어택 퀴즈", "quiz"):
            d = db.collection("quizzes").document(sanitize_doc_id(title)).get()
            if not d.exists:
                return {}
            out = {}
            for i, q in enumerate((d.to_dict() or {}).get("questions") or []):
                txt = str(q.get("explanation", "") or "").strip()
                if txt:
                    out[str(i + 1)] = txt[:EXPLANATION_MAX_CHARS]
            return out
    except Exception as e:
        print("해설 불러오기 실패:", kind, title, e)
    return {}


@app.get("/api/student/wrong_questions/{student_name}")
def get_wrong_questions(student_name: str, limit: int = 30):
    """학생이 그동안 틀린 문항을 한자리에 모아 준다.
    💡 '몇 점'만 남으면 무엇을 틀렸는지 알 수 없어 복습이 안 된다. 그래서 채점 때 남겨둔
    틀린 문항 번호를 가지고, 원래 문제(퀴즈·모의고사·과제)를 되짚어 문제 내용과 정답까지 붙여준다."""
    if db is None:
        return {"success": False, "tasks": []}
    name = urllib.parse.unquote(student_name).strip()
    if not name:
        return {"success": False, "tasks": []}

    rows = [r.to_dict() for r in db.collection("reports")
            .where("student_name", "==", name)
            .order_by("submitted_at", direction=firestore.Query.DESCENDING)
            .limit(200).stream()]

    cache = {}

    def source_questions(kind: str, title: str) -> list:
        """그 과제·시험의 문항 목록을 [(문제글, 정답)] 로 꺼낸다. 못 찾으면 빈 목록."""
        key = (kind, title)
        if key in cache:
            return cache[key]
        out = []
        try:
            if kind == "타임어택 퀴즈":
                d = db.collection("quizzes").document(sanitize_doc_id(title)).get()
                for q in ((d.to_dict() or {}).get("questions") or []) if d.exists else []:
                    opts = q.get("options") or []
                    ans = q.get("answer", "")
                    idx = _num(ans)
                    label = opts[int(idx) - 1] if idx and 1 <= int(idx) <= len(opts) else str(ans)
                    out.append({"text": q.get("q_text", ""), "answer": str(ans), "answer_text": label,
                                "options": opts})
            elif kind == "모의고사":
                d = db.collection("exams").document(sanitize_doc_id(title)).get()
                if d.exists:
                    data = json.loads((d.to_dict() or {}).get("exam_data") or "{}")
                    for q in (data.get("questions") or []):
                        out.append({"text": "", "answer": str(q.get("ans", "")), "answer_text": "",
                                    "options": []})
            elif kind == "과제 제출":
                d = db.collection("homeworks").document(sanitize_doc_id(title)).get()
                for a in ((d.to_dict() or {}).get("answers") or []) if d.exists else []:
                    out.append({"text": "", "answer": str(a), "answer_text": "", "options": []})
        except Exception as e:
            print("틀린 문제 되짚기 실패:", title, e)
        cache[key] = out
        return out

    tasks, total_wrong = [], 0
    for r in rows:
        wrongs = [int(w) for w in (r.get("wrongs") or []) if _num(w) is not None]
        unsure = {int(u) for u in (r.get("unsure") or []) if _num(u) is not None}
        kind = r.get("type", "")
        title = r.get("task_name", "")
        # 💡 번호만 알려주면 왜 틀렸는지 알 수 없다. 저장해둔 문항별 해설을 같이 붙여
        #    학생이 눌러서 바로 확인할 수 있게 한다.
        expl = explanations_for(kind, title)
        # 💡 전부 맞힌 시험도 해설이 있으면 남겨 둔다 — 찍어서 맞힌 걸 되짚어 보려면
        #    다 맞은 시험이야말로 확인이 필요하다. 볼 것이 아무것도 없을 때만 건너뛴다.
        if not wrongs and not expl:
            continue
        qs = source_questions(kind, title)
        def make_item(no):
            q = qs[no - 1] if 0 < no <= len(qs) else {}
            return {"no": no, "text": q.get("text", ""),
                    "answer": q.get("answer", ""), "answer_text": q.get("answer_text", ""),
                    "options": q.get("options", []),
                    "explanation": expl.get(str(no), ""),
                    "is_wrong": no in wrongs,
                    "is_unsure": no in unsure}

        items = [make_item(no) for no in sorted(wrongs)]
        # 💡 맞힌 문제도 해설을 보고 싶다는 요청이 있었다. 찍어서 맞힌 것도 있으니
        #    전체 문항을 함께 내려주고, 화면에서 '틀린 것만/전체'로 골라 보게 한다.
        total_q = max(len(qs), max(wrongs) if wrongs else 0,
                      len(expl) and max(int(k) for k in expl))
        all_items = [make_item(no) for no in range(1, total_q + 1)]
        total_wrong += len(items)
        tasks.append({
            "title": title, "type": kind,
            "has_explanation": any(i["explanation"] for i in items),
            "unsure_count": len(unsure),
            "submitted_at": r.get("submitted_at", ""),
            "score": r.get("score", ""),
            "subject": r.get("subject", ""),
            "wrong_count": len(items), "items": items,
            "all_items": all_items, "question_count": len(all_items),
        })
        if len(tasks) >= max(1, min(100, limit)):
            break

    return {"success": True, "student": name, "tasks": tasks,
            "total_wrong": total_wrong, "task_count": len(tasks)}


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
    class_names: dict = None
    subjects: list = None

@app.post("/api/admin/student")
def add_single_student(req: SingleStudentRequest, _: bool = Depends(verify_admin)):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    subjects = [normalize_subject(s) for s in req.subjects] if req.subjects else ["korean"]
    payload = {"school": req.school, "grade": req.grade, "class_name": (req.class_name or "").strip(), "subjects": subjects}
    if req.class_names is not None:
        payload["class_names"] = {normalize_subject(k): str(v or "").strip() for k, v in req.class_names.items()}
    db.collection("students").document(sanitize_doc_id(req.name)).set(payload, merge=True)
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
    class_names: dict = None
    subjects: list = None

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
        if req.class_names is not None:
            # 💡 화면에서 국어반/수학반/영어반을 한 번에 같이 보내므로, 통째로 덮어쓰면
            # 안 되고 기존 값과 합쳐야 한다 — 안 그러면 다른 과목 칸을 그대로 뒀을 뿐인데
            # (빈 문자열로 넘어와) 이미 지정해둔 반이 지워져 버린다.
            merged = dict(data.get('class_names') or {})
            merged.update({normalize_subject(k): str(v or "").strip() for k, v in req.class_names.items()})
            data['class_names'] = merged
        if req.subjects is not None:
            data['subjects'] = [normalize_subject(s) for s in req.subjects] or ["korean"]
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


class AssignSubjectsReq(BaseModel):
    ids: list = None
    subjects: list = None


@app.post("/api/admin/student/assign_subjects")
def assign_subjects(req: AssignSubjectsReq, _: bool = Depends(verify_admin)):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    subjects = [normalize_subject(s) for s in (req.subjects or [])] or ["korean"]
    count = 0
    for sid in (req.ids or []):
        db.collection("students").document(sid).set({"subjects": subjects}, merge=True)
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
# ─────────────────────────────────────────────────────────
# 과목 — 24시간 AI 튜터를 국어뿐 아니라 수학·영어로 확장.
#   과목마다 자료학습(knowledge)과 AI 답변 원칙(ai_guidelines)을 완전히 분리해서
#   국어 지문 자료가 수학·영어 질문에 섞여 들어가지 않게 한다.
# ─────────────────────────────────────────────────────────
SUBJECTS = {
    "korean": {
        "label": "국어", "persona": "국최", "greeting_persona": "스마트 국최",
        "role": "국어학원", "expertise": "국어 개념(문법, 표현법 등)",
    },
    "math": {
        "label": "수학", "persona": "수박", "greeting_persona": "스마트 수박",
        "role": "수학학원", "expertise": "수학 개념(공식, 풀이 과정 등)",
    },
    "english": {
        "label": "영어", "persona": "재우T", "greeting_persona": "스마트 재우T",
        "role": "영어학원", "expertise": "영어 개념(문법, 어휘, 독해 등)",
    },
}


def normalize_subject(subject) -> str:
    s = str(subject or "korean").strip().lower()
    return s if s in SUBJECTS else "korean"


def student_subjects(student_name: str):
    """학생이 듣는 과목 목록을 학생 명단에서 가져온다.
    명단에 없는 이름(관리자 등)이면 None을 돌려줘 과목 제한 없이 통과시킨다.
    과목을 아직 등록하지 않은(예전부터 있던) 학생은 국어만 듣던 학생들이었으므로 국어로 간주한다."""
    if db is None or not student_name:
        return None
    doc = db.collection("students").document(student_name).get()
    if not doc.exists:
        return None
    subs = doc.to_dict().get("subjects")
    if not subs:
        return ["korean"]
    return [normalize_subject(s) for s in subs]


def get_student_class_for_subject(student_name: str, subject: str) -> str:
    """학생의 과목별 반을 가져온다. 과목별로 따로 지정한 반이 없으면(예전 방식으로
    반 하나만 쓰던 학생) 기존 단일 반 값을 그대로 대신 쓴다."""
    if db is None or not student_name:
        return ""
    doc = db.collection("students").document(student_name).get()
    if not doc.exists:
        return ""
    data = doc.to_dict()
    subj_key = normalize_subject(subject)
    class_names = data.get("class_names") or {}
    val = class_names.get(subj_key)
    if val:
        return str(val).strip()
    # 💡 예전에는 반이 하나뿐이었고, 그 학생들은 전부 국어만 듣던 학생들이었다
    # (student_subjects와 같은 전제). 그래서 국어만 그 값을 그대로 물려받고,
    # 수학·영어는 따로 지정하지 않았다면 "미배정"으로 본다.
    if subj_key == "korean":
        return str(data.get("class_name", "") or "").strip()
    return ""


def task_visible_to_student(subject: str, target_class: str, student_name: str) -> bool:
    """퀴즈/모의고사가 이 학생에게 보여도 되는지 — 그 과목을 듣지 않으면 안 되고,
    특정 반 대상으로 지정된 경우 그 반이 아니면 안 된다."""
    subs = student_subjects(student_name)
    if subs is not None and normalize_subject(subject) not in subs:
        return False
    target_class = (target_class or "").strip()
    if not target_class:
        return True
    return get_student_class_for_subject(student_name, subject) == target_class


def task_visibility_denied_reason(subject: str, target_class: str, student_name: str) -> str:
    """💡 예전에는 응시가 막힌 이유를 "응시할 수 없는 시험입니다"로만 뭉뚱그려서,
    과목 미등록 때문인지 반이 달라서인지 학생도 원장님도 알 수 없었다. 어느
    조건에서 막혔는지 구체적으로 짚어서 알려준다(task_visible_to_student와
    반드시 같은 판정 순서를 따라야 한다)."""
    subj_label = SUBJECTS[normalize_subject(subject)]["label"]
    subs = student_subjects(student_name)
    if subs is not None and normalize_subject(subject) not in subs:
        return f"'{student_name}' 학생은 {subj_label} 과목에 등록되어 있지 않아 응시할 수 없습니다. 학생 명단에서 {subj_label} 과목을 등록해주세요."
    target_class = (target_class or "").strip()
    if target_class:
        my_class = get_student_class_for_subject(student_name, subject) or "(반 미배정)"
        return f"'{target_class}' 반 학생만 응시할 수 있는 시험입니다. ('{student_name}' 학생의 {subj_label} 반: {my_class})"
    return "응시할 수 없는 시험입니다."


def with_subject_prefix(title: str, subject: str) -> str:
    """퀴즈/모의고사 제목 앞에 과목 표시를 붙인다. 이미 다른 과목 표시가 붙어 있으면
    (과목을 바꿔 수정한 경우) 떼어내고 새로 붙인다."""
    label = SUBJECTS[normalize_subject(subject)]["label"]
    t = (title or "").strip()
    for s in SUBJECTS.values():
        if t.startswith(f"[{s['label']}]"):
            t = t[len(f"[{s['label']}]"):].lstrip()
            break
    return f"[{label}] {t}"


def build_safe_knowledge_context(subject: str = "korean") -> str:
    """학생 챗봇에 노출해도 안전한 자료만, 그 과목 것만 모은다 (정답/해설 필드 제외)."""
    if db is None:
        return ""
    subject = normalize_subject(subject)
    rows = [d.to_dict() for d in db.collection("knowledge").stream()]
    # 과목 구분이 생기기 전에 올라간 예전 자료는 전부 국어 자료였다.
    rows = [r for r in rows if normalize_subject(r.get("subject")) == subject]
    # 💡 대부분 created_at을 문자열(strftime)로 저장하지만, 문서 하나라도 Firestore
    # 콘솔 등에서 직접 만들어져 실제 타임스탬프(DatetimeWithNanoseconds) 타입으로 들어가
    # 있으면 문자열과 비교할 수 없어("'<' not supported between instances of 'str' and
    # 'DatetimeWithNanoseconds'") 이 함수를 부르는 모든 채팅 질문이 그대로 실패했다.
    # 정렬 기준을 항상 문자열로 맞춰서 어떤 타입이 섞여 있어도 죽지 않게 한다.
    rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    knowledge_base = "\n".join([f"[{r.get('title')}] {r.get('content')}" for r in rows[:50]])
    return knowledge_base


def get_ai_guidelines(subject: str = "korean") -> str:
    """원장님이 설정한 'AI 답변 원칙'(수업 방식/설명 스타일 지침)을 과목별로 가져온다."""
    if db is None:
        return ""
    subject = normalize_subject(subject)
    doc = db.collection("settings").document(f"ai_guidelines_{subject}").get()
    if doc.exists:
        return doc.to_dict().get("text", "")
    if subject == "korean":
        # 과목 구분이 생기기 전에 적어둔 원칙은 국어 원칙으로 그대로 이어받는다.
        legacy = db.collection("settings").document("ai_guidelines").get()
        if legacy.exists:
            return legacy.to_dict().get("text", "")
    return ""


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
    subject: str = Form("korean"),
    school: str = Form("미상"),
    grade: str = Form("미상"),
    student_name: str = Form("미상"),
    files: Optional[List[UploadFile]] = File(None),
):
    subj_key = normalize_subject(subject)
    subj = SUBJECTS[subj_key]
    check_rate_limit(request, f"chat_{subj_key}", max_calls=15, window_seconds=60)

    # 💡 국어를 듣는 학생과 수학·영어를 듣는 학생은 구분되어야 한다.
    #    화면에서 숨겨도 요청을 직접 보내면 우회될 수 있으니, 서버에서 학생 명단의
    #    실제 수강 과목을 다시 확인한다(클라이언트가 보낸 값은 신뢰하지 않음).
    allowed = await asyncio.to_thread(student_subjects, student_name)
    if allowed is not None and subj_key not in allowed:
        return {
            "success": False,
            "reply": f"아직 {subj['label']} 수업에 등록되어 있지 않아 {subj['persona']}를 이용할 수 없어요. {subj['label']}에 등록하면 이 AI를 포함한 다양한 학습 프로그램을 이용할 수 있으니, 선생님께 등록을 문의해주세요!",
            "detail": "not_enrolled",
        }

    send_telegram_message(f"💬 [질문 알림]\n{student_name} 학생이 {subj['persona']}에게 질문을 남겼습니다.\n\nQ: {prompt}")

    # 💡 예전에는 아래 준비 과정(자료 조회, 프롬프트 조립, 파일 읽기)이 try 밖에
    # 있어서, 여기서 뭐가 하나라도 실패하면 전역 오류 처리기가 "서버 처리 중 오류가
    # 발생했습니다"라는 뭉뚱그린 500 오류로만 돌려줘 원인을 전혀 알 수 없었다.
    # 이제 이 함수의 준비 과정과 AI 호출을 통째로 하나의 try로 묶어서, 어디서
    # 실패하든 실제 원인이 화면에 그대로 나오게 한다.
    try:
        knowledge_base = await asyncio.to_thread(build_safe_knowledge_context, subject)
        ai_guidelines = await asyncio.to_thread(get_ai_guidelines, subject)

        has_images = bool(files) and any(f.filename for f in files)
        # 💡 수학은 사진 속 수식(분수, 지수, 루트, 그리스 문자, 손글씨 등)을 한 글자라도
        # 잘못 읽으면 완전히 다른 문제가 돼버린다. 이미지가 있을 때는 "먼저 보이는 대로
        # 정확히 옮겨 적고, 그다음에 풀라"고 못 박아서 대충 짐작해 답하는 것을 막는다.
        # 채팅창이 이제 KaTeX으로 LaTeX 수식을 실제로 그려주므로($...$는 줄 안에,
        # $$...$$는 독립된 줄에 쓰면 분수·제곱근·지수가 교과서처럼 그려진다),
        # 억지로 캐럿(^)이나 슬래시로 풀어쓰게 하지 않고 정식 LaTeX을 쓰게 한다.
        math_image_note = ""
        if subj_key == "math":
            math_image_note = """

[수식 표기 방법 — 반드시 지킬 것]
이 채팅창은 LaTeX 수식을 실제 기호(분수, 제곱근, 지수 등)로 그려줍니다.
수식은 반드시 LaTeX 문법으로 쓰고, 줄 안에 섞인 수식은 $...$ 로, 독립된 한 줄을
차지하는 수식(중요한 식이나 최종 답)은 $$...$$ 로 감싸세요.
예: 분수는 $\\frac{1}{4}$, 지수는 $9^{\\frac{1}{4}}$, 제곱근은 $\\sqrt{3}$,
곱셈은 $\\times$, 극한은 $\\lim_{h \\to 0}$, 시그마는 $\\sum_{k=1}^{4}$,
구간별 함수는 $$f(x) = \\begin{cases} 3x-2 & (x < 1) \\\\ x^2-3x+a & (x \\ge 1) \\end{cases}$$
처럼 정상적인 LaTeX 문법을 그대로 쓰면 됩니다. 수식이 아닌 설명 글은 평소처럼
자연스러운 한국어 문장으로 쓰세요.

[풀이가 여러 단계로 이어질 때 구성 방법]
- 풀이 과정이 두세 단계를 넘어가면, "1. OOO 구하기", "2. OOO의 관계" 처럼
  단계마다 짧은 소제목을 붙여 구간을 나누세요(소제목은 **굵게** 표시).
- 각 단계 안에서는 [식 제시] → [그 식이 왜 성립하는지 한두 줄 설명] → [다음 식]
  순서로, 계산 과정을 건너뛰지 말고 이어가세요.
- 마지막에 구한 핵심 결과(최종 답이나 그 문제의 핵심 식)는 $$\\boxed{...}$$ 로
  감싸서 한눈에 띄게 표시하세요."""
            if has_images:
                math_image_note += """

[사진이 첨부되었을 때 반드시 지킬 것]
1. 답을 하기 전에, 사진 속 수식과 숫자를 빠짐없이 정확하게(위 표기법으로) 옮겨 적으세요
   (분수는 분자/분모를 각각, 지수·아래첨자·루트·시그마·적분 기호·그리스 문자까지
   놓치지 말고, 읽은 그대로 먼저 옮겨 적으세요).
2. 글씨가 흐리거나 겹쳐서 확실하지 않은 부분이 있으면, 짐작해서 넘어가지 말고
   "이 부분이 OOO인지 XXX인지 확실하지 않다"고 먼저 말하고, 가장 그럴듯한 해석으로
   풀이하되 그 사실을 학생에게 알려주세요.
3. 사진에 문제가 여러 개 보이고 학생이 어떤 문제인지 말하지 않았다면, 모든 문제를
   한꺼번에 풀지 말고 먼저 "사진에 문제가 여러 개 있는데 몇 번 문제가 궁금해?"처럼
   되물어서 원하는 문제 하나에만 집중하세요. 학생이 이미 번호나 내용을 콕 짚었다면
   바로 그 문제만 풀어주세요.
4. 그 문제만 옮겨 적은 뒤, 풀이 과정을 단계별로 보여주고 답을 제시하세요."""

        system_prompt = f"""당신은 로지에듀 {subj['role']} AI 튜터 '{subj['persona']}'입니다.
아래 [원장님 답변 원칙]이 있다면 그 방식과 관점을 최우선으로 따라서 설명하세요.
그 다음으로 [학원 누적 자료]를 참고하여 다정하고 명쾌하게 답변하세요.
만약 학생이 묻는 내용이 자료에 없더라도, {subj['label']} 전문가로서의 지식을 활용해 {subj['expertise']}을 친절하게 설명해 주세요. "자료에 없어서 모른다"는 말은 절대 하지 마세요.
단, 모의고사나 퀴즈의 정답을 직접적으로 물어볼 때는 정답 대신 힌트만 제공하세요.
답변은 너무 길고 formal하게 늘어놓지 말고, 채팅으로 대화하듯 간결하고 이해하기 쉽게 답하세요.{math_image_note}

[원장님 답변 원칙]
{ai_guidelines or f"(설정된 원칙 없음 - 일반적인 {subj['label']} 교육 원칙에 따라 설명)"}

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

        # 💡 사진 속 수식을 읽어내는 건 빠른(저렴한) 모델이 자주 틀린다 — 수학 + 사진일 때만
        # 정밀한(비싼) 모델을 쓴다. 그 외(텍스트 질문, 국어·영어)는 기존처럼 빠른 모델 그대로.
        use_quality_model = subj_key == "math" and has_images
        response = await asyncio.to_thread(safe_generate, contents, False, use_quality_model)
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
        return {"success": False, "reply": f"AI 응답 실패\n{friendly_ai_error(e)}"}


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
    explanations: str = Form(""),
    subject: str = Form("korean"),
    target_class: str = Form(""),
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

    # 💡 문서 id는 화면/제출 요청이 그대로 쓰는 제목(과목 접두어 포함)과 같아야 한다.
    subj_key = normalize_subject(subject)
    title = with_subject_prefix(title, subj_key)
    safe_title = sanitize_doc_id(title)
    await asyncio.to_thread(
        lambda: db.collection("exams").document(safe_title).set(
            {
                "title": title,
                "subject": subj_key,
                "target_class": str(target_class or "").strip(),
                "objective": objective,
                "exam_data": exam_data,
                "pdf_url": pdf_url,
                "ans_pdf_url": ans_pdf_url,
                "video_url": video_url,
                "explanation_text": explanation_text,
                # 문항별 해설 — 학생이 채점 결과에서 번호를 눌러 바로 볼 수 있다
                "explanations": parse_explanation_map(explanations),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    )
    know_content = "\n\n".join(t for t in (objective, explanation_text) if t.strip())
    if know_content:
        await asyncio.to_thread(sync_knowledge_from_source, f"exam_{safe_title}", f"[모의고사] {title}", know_content, subj_key, "exam")
    return {"success": True, "title": title}


class ExamFileDeleteReq(BaseModel):
    title: str
    which: str = "pdf"       # pdf(시험지) | ans(해답지) | video(영상)


@app.post("/api/admin/exam/file/delete", dependencies=[Depends(verify_admin)])
def delete_exam_file(req: ExamFileDeleteReq):
    """모의고사에 붙여둔 파일을 떼어낸다 — 잘못 올렸을 때 시험 자체를 지우지 않고 파일만."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    field = {"pdf": "pdf_url", "ans": "ans_pdf_url", "video": "video_url"}.get(req.which)
    if not field:
        return {"success": False, "detail": "어떤 파일을 뗄지 알 수 없습니다."}
    ref = db.collection("exams").document(sanitize_doc_id(req.title))
    doc = ref.get()
    if not doc.exists:
        return {"success": False, "detail": "그런 모의고사가 없습니다."}
    if not (doc.to_dict() or {}).get(field):
        return {"success": False, "detail": "이미 비어 있습니다."}
    ref.set({field: ""}, merge=True)
    return {"success": True, "which": req.which}


@app.get("/api/exams")
def get_exams(student_name: str = ""):
    if db is None:
        return {"success": False, "exams": []}
    rows = [{"id": d.id, **d.to_dict()} for d in db.collection("exams").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]
    if student_name:
        rows = [e for e in rows if task_visible_to_student(e.get("subject", "korean"), e.get("target_class", ""), student_name)]
    return {"success": True, "exams": rows}


@app.delete("/api/admin/exam/{title}")
def delete_exam(title: str, _: bool = Depends(verify_admin)):
    if db:
        db.collection("exams").document(title).delete()
        delete_synced_knowledge(f"exam_{sanitize_doc_id(title)}")
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

    # 💡 해설도 '이 한 번의 호출'에서 같이 받아온다. 따로 부르면 사용료가 두 배가 된다.
    prompt = """첨부된 이미지는 시험의 정답표 또는 해설지입니다.
문항 번호와 그 문항의 정답을 모두 읽어내고, 해설이 적혀 있으면 해설도 함께 읽어내세요.

[반드시 지킬 것]
- 오직 JSON만 출력하세요. 설명, 인사말, 코드블록 표시(```)를 절대 붙이지 마세요.
- 형식: {"answers": {"1": 3, "2": 5}, "explanations": {"1": "...", "2": "..."}}
- answers 의 키는 문항 번호를 큰따옴표로 감싼 문자열, 값은 1~5 사이의 정수입니다.
- ①②③④⑤ 같은 원문자는 1,2,3,4,5로 바꿔서 적으세요.
- 이미지에 보이지 않는 문항은 아예 넣지 마세요. 추측해서 채우지 마세요.
- 주관식이거나 번호로 읽을 수 없는 문항은 answers 에서 건너뛰세요.
- explanations 에는 이미지에 실제로 적혀 있는 해설 문장을 그대로 옮겨 적으세요.
  해설이 없는 문항은 넣지 마세요. 없는 해설을 지어내지 마세요.
- 해설은 문항당 400자를 넘기지 말고, 넘치면 핵심만 간추리세요.
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

    explanations = parse_explanation_map(parsed.get("explanations"))

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

    if not await asyncio.to_thread(task_visible_to_student, data.get("subject", "korean"), data.get("target_class", ""), req.student_name):
        reason = await asyncio.to_thread(task_visibility_denied_reason, data.get("subject", "korean"), data.get("target_class", ""), req.student_name)
        return {"success": False, "detail": reason}

    actual_score = 0
    wrongs = []
    unsures = []

    details = []
    total_possible = 0
    if data:
        exam_data = json.loads(data.get("exam_data", "{}"))
        for i, q in enumerate(exam_data.get("questions", [])):
            student_ans = str(req.answers[i]).strip() if i < len(req.answers) else ""
            correct_ans = str(q.get("ans", "")).strip()
            point = int(q.get("score", 0) or 0)
            total_possible += point
            is_unsure = student_ans == UNSURE_MARK
            is_ok = bool(student_ans) and not is_unsure and student_ans == correct_ans
            if is_ok:
                actual_score += point
            else:
                wrongs.append(i + 1)
                if is_unsure:
                    unsures.append(i + 1)
            # 💡 학생이 제출 직후 "몇 점인지, 무엇을 틀렸는지"를 바로 보려면
            #    문항별 내 답/정답/배점이 필요해서 함께 돌려준다.
            details.append({
                "no": i + 1,
                "my": student_ans,
                "ans": correct_ans,
                "score": point,
                "ok": is_ok,
                "unsure": is_unsure,
                "blank": not student_ans and not is_unsure,
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
                "unsure": unsures,
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
        "unsure": unsures,
        # 💡 제출 직후가 가장 잘 기억나는 때다. 문항을 눌러 바로 해설을 볼 수 있게 함께 보낸다.
        "explanations": parse_explanation_map(data.get("explanations")),
        "details": details,
        "correct_count": sum(1 for d in details if d["ok"]),
        "question_count": len(details),
        "question_stats": (await asyncio.to_thread(
            lambda: compute_question_stats(req.title, "모의고사")))["questions"],
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

    report_docs.sort(key=lambda r: str(r.to_dict().get("submitted_at") or ""))

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

    # 💡 문서 id(=제출/시작 API가 그대로 조회 키로 쓰는 문자열)는 화면에 보이는
    # 제목(과목 접두어 포함)과 항상 같아야 한다 — 접두어를 붙이기 전 제목으로 id를
    # 만들면, 학생이 실제로 보내는 값(접두어 붙은 제목)과 어긋나 퀴즈를 찾지 못한다.
    subject = normalize_subject(req.get("subject", "korean"))
    title = with_subject_prefix(title, subject)
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

    questions = req.get("questions", [])
    await asyncio.to_thread(
        lambda: db.collection("quizzes").document(safe_title).set(
            {
                "title": title,
                "subject": subject,
                "target_class": str(req.get("target_class", "") or "").strip(),
                "deadline": req.get("deadline"),
                "time_limit": int(req.get("time_limit", 0)),
                "questions": questions,
                "created_at": created_at,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    )
    # 💡 AI가 '이 퀴즈 몇 번 문제 이해가 안 돼요' 같은 질문을 받을 수 있으려면 문항
    # 내용을 알아야 한다. 다만 정답을 그대로 실으면 학생이 그걸 캐낼 수 있으니
    # (기존 knowledge 업로드의 '정답 필드 제외' 원칙과 동일하게) 문제·보기만 싣는다.
    circles = ["①", "②", "③", "④", "⑤"]
    know_lines = []
    for i, q in enumerate(questions):
        opts = [o for o in (q.get("options") or []) if o]
        opt_text = " ".join(f"{circles[j] if j < len(circles) else j+1}{o}" for j, o in enumerate(opts))
        know_lines.append(f"{i + 1}. {q.get('q_text', '')}\n{opt_text}".strip())
    know_content = "\n\n".join(l for l in know_lines if l)
    if know_content:
        await asyncio.to_thread(sync_knowledge_from_source, f"quiz_{safe_title}", f"[퀴즈] {title}", know_content, subject, "quiz")
    return {"success": True, "title": title}


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
def get_quizzes(student_name: str = ""):
    if db is None:
        return {"success": False, "quizzes": []}
    rows = [{"id": d.id, **d.to_dict()} for d in db.collection("quizzes").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]
    # 💡 student_name이 오면(학생 화면) 그 학생이 듣는 과목이 아니거나, 특정 반 전용으로
    # 지정된 퀴즈인데 그 반이 아니면 목록에서 아예 뺀다. 관리자 화면은 student_name 없이
    # 부르므로 전체가 그대로 보인다.
    if student_name:
        rows = [q for q in rows if task_visible_to_student(q.get("subject", "korean"), q.get("target_class", ""), student_name)]
    return {"success": True, "quizzes": rows}


@app.delete("/api/admin/quiz/{title}")
def delete_quiz(title: str, _: bool = Depends(verify_admin)):
    if db:
        db.collection("quizzes").document(title).delete()
        delete_synced_knowledge(f"quiz_{sanitize_doc_id(title)}")
    return {"success": True}


class QuizStartReq(BaseModel):
    student_name: str
    title: str


@app.post("/api/quiz/start")
async def start_quiz(req: QuizStartReq):
    """💡 '타임어택' 퀴즈인데 예전에는 제한 시간이 브라우저 안의 카운트다운 하나뿐이었다.
    학생이 퀴즈방을 나갔다가 다시 들어오면 타이머가 매번 처음부터 다시 시작돼서,
    정해둔 제한 시간을 넘겨도 계속 풀 수 있는 구멍이 있었다. 이제 학생이 그 퀴즈를
    처음 시작한 시각을 서버에 기록해두고, 다시 들어와도 그 시각부터 남은 시간만
    돌려준다 — 재입장으로 타이머를 리셋할 수 없게 한다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}

    quiz_doc = await asyncio.to_thread(lambda: db.collection("quizzes").document(req.title).get())
    if not quiz_doc.exists:
        return {"success": False, "detail": "존재하지 않는 퀴즈입니다."}
    quiz_data = quiz_doc.to_dict()
    time_limit = int(quiz_data.get("time_limit", 0) or 0)

    if not await asyncio.to_thread(task_visible_to_student, quiz_data.get("subject", "korean"), quiz_data.get("target_class", ""), req.student_name):
        reason = await asyncio.to_thread(task_visibility_denied_reason, quiz_data.get("subject", "korean"), quiz_data.get("target_class", ""), req.student_name)
        return {"success": False, "detail": reason}

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

    attempt_id = sanitize_doc_id(f"{req.title}__{req.student_name}")
    a_ref = db.collection("quiz_attempts").document(attempt_id)
    a_doc = await asyncio.to_thread(a_ref.get)
    if a_doc.exists:
        started_at = a_doc.to_dict().get("started_at")
    else:
        started_at = datetime.now().timestamp()
        await asyncio.to_thread(
            lambda: a_ref.set({
                "student_name": req.student_name, "title": req.title, "started_at": started_at,
            })
        )
    return {"success": True, "started_at": started_at, "time_limit": time_limit}


class QuizSubmitReq(BaseModel):
    school: str
    grade: str
    student_name: str
    title: str
    answers: list


def compute_question_stats(task_name: str, kind: str, with_names: bool = False) -> dict:
    """문항마다 몇 명이 맞고 틀렸는지 센다.
    제출 기록에 남는 wrongs(틀린 문항 번호)를 뒤집어 정답자를 구한다."""
    if db is None:
        return {"questions": [], "submitted": 0}
    try:
        docs = list(
            db.collection("reports")
            .where("task_name", "==", task_name)
            .where("type", "==", kind)
            .stream()
        )
    except Exception:
        return {"questions": [], "submitted": 0}

    # 한 학생이 여러 번 냈으면 가장 나중 것만 본다
    latest = {}
    for d in docs:
        r = d.to_dict() or {}
        name = str(r.get("student_name", "")).strip()
        if not name:
            continue
        when = str(r.get("submitted_at", ""))
        if name not in latest or when >= latest[name][0]:
            latest[name] = (when, r)

    rows = [r for _, r in latest.values()]
    # 예전 기록에는 문항 수가 없을 수 있어 여러 곳에서 찾아본다
    q_count = 0
    for r in rows:
        n = _num(r.get("question_count"))
        if n:
            q_count = max(q_count, int(n))
        for w in (r.get("wrongs") or []):
            wn = _num(w)
            if wn:
                q_count = max(q_count, int(wn))
    if q_count <= 0:
        return {"questions": [], "submitted": len(rows)}

    stats = []
    for no in range(1, q_count + 1):
        correct = wrong = 0
        wrong_names = []
        for r in rows:
            # wrongs가 아예 없는 예전 기록은 셀 수 없으니 건너뛴다
            if "wrongs" not in r:
                continue
            if no in [int(x) for x in (r.get("wrongs") or []) if _num(x) is not None]:
                wrong += 1
                if with_names:
                    wrong_names.append(str(r.get("student_name", "")))
            else:
                correct += 1
        total = correct + wrong
        item = {
            "no": no, "correct": correct, "wrong": wrong, "total": total,
            "rate": round(correct / total * 100) if total else None,
        }
        if with_names:
            item["wrong_names"] = wrong_names[:60]
        stats.append(item)

    counted = sum(1 for r in rows if "wrongs" in r)
    return {"questions": stats, "submitted": counted, "students": len(rows)}


@app.get("/api/stats/questions")
def get_question_stats(title: str, kind: str = "타임어택 퀴즈"):
    """문항별 정답률 — 학생도 볼 수 있다. 이름은 나오지 않는다."""
    if kind not in ("타임어택 퀴즈", "모의고사"):
        return {"success": False, "detail": "알 수 없는 종류입니다."}
    return {"success": True, **compute_question_stats(urllib.parse.unquote(title), kind)}


@app.get("/api/admin/stats/questions", dependencies=[Depends(verify_admin)])
def get_question_stats_admin(title: str, kind: str = "타임어택 퀴즈"):
    """원장님용 — 어느 학생이 틀렸는지까지 함께."""
    if kind not in ("타임어택 퀴즈", "모의고사"):
        return {"success": False, "detail": "알 수 없는 종류입니다."}
    return {"success": True, **compute_question_stats(urllib.parse.unquote(title), kind, with_names=True)}


def compute_rank(task_name: str, kind: str, my_name: str, my_score) -> dict:
    """같은 퀴즈를 푼 학생들 사이에서 몇 등인지 센다.
    점수가 같으면 같은 등수를 주고, 그 다음 등수는 인원만큼 건너뛴다. (1, 2, 2, 4)"""
    if db is None:
        return {}
    try:
        docs = list(
            db.collection("reports")
            .where("task_name", "==", task_name)
            .where("type", "==", kind)
            .stream()
        )
    except Exception:
        return {}

    # 한 학생이 여러 번 들어가 있으면 가장 높은 점수만 센다
    best = {}
    for d in docs:
        r = d.to_dict() or {}
        name = str(r.get("student_name", "")).strip()
        sc = _num(r.get("score"))
        if not name or sc is None:
            continue
        if name not in best or sc > best[name]:
            best[name] = sc

    mine = _num(my_score)
    if mine is not None:
        # 방금 낸 점수가 아직 반영 안 됐을 수 있으니 직접 넣어 준다
        if my_name not in best or mine > best[my_name]:
            best[my_name] = mine

    total = len(best)
    if total == 0 or mine is None:
        return {}

    higher = sum(1 for s in best.values() if s > mine)
    same = sum(1 for s in best.values() if s == mine)
    rank = higher + 1

    if rank == 1 and same == 1:
        message = "🥇 1등입니다! 축하합니다!"
    elif rank == 1:
        message = f"🥇 공동 1등입니다! 축하합니다! ({same}명 공동)"
    elif rank == 2:
        message = "🥈 2등입니다! 아깝습니다, 잘했어요!"
    elif rank == 3:
        message = "🥉 3등입니다! 잘했어요!"
    elif total >= 4 and rank <= max(1, round(total * 0.3)):
        message = "👏 상위권입니다! 잘하고 있어요."
    elif rank == total and total > 1:
        message = "다음엔 더 잘할 수 있어요. 틀린 문제부터 다시 봅시다."
    else:
        message = "끝까지 푼 것만으로도 잘했습니다. 틀린 문제를 챙겨봅시다."

    return {
        "rank": rank,
        "total": total,
        "tied": same,
        "top_score": max(best.values()),
        "percentile": round((total - higher) / total * 100),
        "message": message,
        "text": f"지금까지 {total}명 중 {rank}등입니다" + (f" ({same}명 공동)" if same > 1 else ""),
    }


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
    doc_data = doc.to_dict() or {}

    if not await asyncio.to_thread(task_visible_to_student, doc_data.get("subject", "korean"), doc_data.get("target_class", ""), req.student_name):
        reason = await asyncio.to_thread(task_visibility_denied_reason, doc_data.get("subject", "korean"), doc_data.get("target_class", ""), req.student_name)
        return {"success": False, "detail": reason}

    # 💡 클라이언트 타이머는 재입장으로 우회될 수 있으니(퀴즈방을 나갔다 다시 들어오면
    # 카운트다운이 처음부터 다시 시작됨), 서버에 기록해둔 실제 시작 시각을 기준으로
    # 제한 시간을 넘겼는지 다시 한번 확인한다. 제출 요청이 오가는 시간을 감안해
    # 20초 정도는 너그럽게 봐준다.
    time_limit = int((doc.to_dict() or {}).get("time_limit", 0) or 0) if doc.exists else 0
    if time_limit > 0:
        attempt_id = sanitize_doc_id(f"{req.title}__{req.student_name}")
        a_doc = await asyncio.to_thread(lambda: db.collection("quiz_attempts").document(attempt_id).get())
        if a_doc.exists:
            started_at = a_doc.to_dict().get("started_at")
            if started_at and datetime.now().timestamp() - float(started_at) > time_limit * 60 + 20:
                return {"success": False, "detail": "제한 시간이 지나 제출할 수 없습니다."}

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
            # 💡 '모름'은 오답으로 채점하되 따로 표시해, 찍어서 맞힌 것과 구분한다
            is_unsure = my_ans == UNSURE_MARK
            is_ok = bool(my_ans) and not is_unsure and my_ans == correct_ans
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
                "unsure": is_unsure,
                # 문항에 적어둔 해설 — 학생이 결과에서 바로 읽을 수 있게 함께 보낸다
                "explanation": str(q.get("explanation", "") or "").strip()[:EXPLANATION_MAX_CHARS],
                "blank": not my_ans and not is_unsure,
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
                "unsure": [d["no"] for d in details if d.get("unsure")],
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
    rank = await asyncio.to_thread(
        lambda: compute_rank(req.title, "타임어택 퀴즈", req.student_name, actual_score)
    )
    return {
        "success": True,
        "score": actual_score,
        "total_score": total_possible,
        "details": details,
        "correct_count": sum(1 for d in details if d["ok"]),
        "question_count": len(details),
        "wrongs": [d["no"] for d in details if not d["ok"]],
        "unsure": [d["no"] for d in details if d.get("unsure")],
        "rank": rank,
        "question_stats": (await asyncio.to_thread(
            lambda: compute_question_stats(req.title, "타임어택 퀴즈")))["questions"],
        "level_up": lvl_up,
    }


# ─────────────────────────────────────────────────────────
# 영어 단어 시험 — 난이도별(상/중/하) 단어장을 여러 파일 올려두면,
# 원장님이 난이도별로 몇 개씩 뽑을지 정해서 무작위로 출제한다.
# 4가지 형태(단어→뜻, 뜻→단어, 스펠링 빈칸, 구절 해석)를 섞어 낸다.
# 채점은 객관적으로 판정 가능한 유형(뜻→단어, 스펠링)은 정확히 비교하고,
# 뜻을 써야 하는 유형(단어→뜻, 구절 해석)은 동의어도 맞게 봐야 하므로
# AI에게 한 번에 모아 채점을 맡긴다(문항마다 따로 부르지 않아 비용을 아낀다).
# ─────────────────────────────────────────────────────────
VOCAB_CHUNK_SIZE = 500
VOCAB_DIFFICULTIES = {"high": "상", "mid": "중", "low": "하"}


def normalize_vocab_difficulty(d) -> str:
    d = str(d or "mid").strip().lower()
    return d if d in VOCAB_DIFFICULTIES else "mid"


def vocab_difficulty_from_text(value) -> str:
    """'상'/'중'/'하' 또는 high/mid/low 로 적힌 난이도를 내부 키로 바꾼다.
    적혀 있지 않거나 알아볼 수 없으면 빈 문자열 — 그래야 '적히지 않음'과
    '중으로 적힘'을 구분할 수 있다."""
    t = str(value or "").strip().lower()
    if not t:
        return ""
    for key, label in VOCAB_DIFFICULTIES.items():
        if t == key or t == label or label in t:
            return key
    if t in ("high", "상급", "어려움", "hard"):
        return "high"
    if t in ("low", "초급", "쉬움", "easy"):
        return "low"
    if t in ("mid", "middle", "중급", "보통", "normal"):
        return "mid"
    return ""


VOCAB_EXTRACT_PROMPT = """첨부된 자료는 영어 단어장(단어 또는 구절과 그 뜻이 나열된 자료)입니다.
표 형식이든 사진이든 줄글이든 상관없이, 여기 실린 모든 단어(또는 숙어·구절)와 뜻을
정확하게, 빠짐없이 읽어내세요. 열 순서나 번호가 섞여 있어도 어느 것이 영어 단어이고
어느 것이 뜻인지 스스로 판단해서 올바르게 짝지으세요.

[반드시 지킬 것]
- 오직 JSON만 출력하세요. 설명, 인사말, 코드블록 표시(```)를 절대 붙이지 마세요.
- 형식: {"words":[{"word":"영어 단어 또는 구절","meaning":"뜻(한글)","difficulty":"상"}]}
- 단어의 철자를 정확히 옮기세요. 흐릿하거나 확실하지 않은 글자는 가장 가능성 높은 철자로
  적되, 절대 지어내지 마세요.
- 뜻은 자료에 적힌 그대로 옮기세요(여러 뜻이 있으면 '/'로 이어 붙이세요).
- 자료에 난이도(상/중/하)가 적혀 있으면 difficulty에 그대로 옮기세요.
  적혀 있지 않으면 difficulty 자체를 넣지 마세요(임의로 판단하지 마세요).
- 번호, 페이지 번호, 챕터/단원 제목처럼 단어장 내용이 아닌 것은 포함하지 마세요."""


# ── 영어 단어 입력용 표준 양식 ────────────────────────────
# 💡 사진·PDF·아무 엑셀이나 올려도 AI가 읽지만, 처음부터 이 틀에 맞춰 적으면
#    난이도까지 한 파일에 담을 수 있고 읽기도 가장 정확하다.
VOCAB_TEMPLATE_COLUMNS = [
    ("단어", "ubiquitous", "영어 단어 또는 숙어·구절. 예: give up, look forward to"),
    ("뜻", "어디에나 있는", "한글 뜻. 여러 뜻이면 '/'로 이어 적으세요. 예: 포기하다/그만두다"),
    ("난이도", "상", "상 · 중 · 하 중 하나. 비워두면 올릴 때 고른 난이도로 들어갑니다."),
]


def build_vocab_template_xlsx() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()
    ws = wb.active
    ws.title = "영어단어"
    head_fill = PatternFill("solid", fgColor="1F3864")
    req_fill = PatternFill("solid", fgColor="C00000")
    white_bold = Font(color="FFFFFF", bold=True, size=11)

    samples = [
        ["ubiquitous", "어디에나 있는", "상"],
        ["give up", "포기하다/그만두다", "중"],
        ["apple", "사과", "하"],
        ["look forward to", "~을 고대하다", ""],
    ]
    widths = [26, 34, 12]
    for i, (label, _ex, _desc) in enumerate(VOCAB_TEMPLATE_COLUMNS, start=1):
        required = label != "난이도"
        c = ws.cell(row=1, column=i, value=label + ("*" if required else ""))
        c.fill = req_fill if required else head_fill
        c.font = white_bold
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[c.column_letter].width = widths[i - 1]
    for r, row in enumerate(samples, start=2):
        for i, v in enumerate(row, start=1):
            ws.cell(row=r, column=i, value=v)
    ws.freeze_panes = "A2"

    guide = wb.create_sheet("작성안내")
    guide.column_dimensions["A"].width = 14
    guide.column_dimensions["B"].width = 22
    guide.column_dimensions["C"].width = 86
    for i, text in enumerate(["열 이름", "예시", "설명"], start=1):
        c = guide.cell(row=1, column=i, value=text)
        c.fill = head_fill
        c.font = white_bold
    for r, (label, example, desc) in enumerate(VOCAB_TEMPLATE_COLUMNS, start=2):
        guide.cell(row=r, column=1, value=label)
        guide.cell(row=r, column=2, value=example)
        guide.cell(row=r, column=3, value=desc)
    for r, line in enumerate([
        "● 첫 줄(열 이름)은 지우지 마세요. 2번째 줄부터 단어를 적으시면 됩니다.",
        "● 예시로 넣어둔 네 줄은 지우고 쓰시면 됩니다.",
        "● 난이도 칸을 비워두면, 파일을 올릴 때 고른 난이도(상·중·하)로 모두 들어갑니다.",
        "● 난이도를 칸마다 다르게 적으면 한 파일로 상·중·하를 한꺼번에 등록할 수 있습니다.",
        "● 띄어쓰기가 들어간 구절(give up 등)은 '구절 해석' 유형 문제로도 출제됩니다.",
        "● 이 양식이 아니어도 괜찮습니다. 쓰시던 엑셀·사진·PDF를 그대로 올리면 AI가 읽습니다.",
    ], start=len(VOCAB_TEMPLATE_COLUMNS) + 3):
        guide.cell(row=r, column=1, value=line)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@app.get("/api/admin/vocab/template", dependencies=[Depends(verify_admin)])
def download_vocab_template():
    try:
        data = build_vocab_template_xlsx()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"양식을 만들지 못했습니다: {e}")
    fname = urllib.parse.quote("영어단어_입력양식.xlsx".encode("utf-8"))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"},
    )

VOCAB_TABLE_ROWS_PER_BATCH = 200  # 표가 아주 크면 한 번에 다 넣지 않고 나눠서 시킨다


async def extract_vocab_words_via_ai(contents: list) -> tuple:
    """AI에게 무엇을 보여주든(표 텍스트/사진/PDF 페이지) 단어장을 읽어
    [{word, meaning, is_phrase}, ...]로 만든다. (단어 목록, 실패 사유) 를 돌려준다 —
    실패 사유가 있어야 "왜 0개가 나왔는지" 화면에서 바로 알 수 있다(예전엔
    무슨 이유든 뭉뚱그려 "단어를 찾지 못했습니다"만 보여줘서 원인 파악이 불가능했음)."""
    try:
        resp = await asyncio.to_thread(lambda: safe_generate(contents))
        text = (resp.text or "").strip()
    except Exception as e:
        return [], f"AI 호출 실패\n{friendly_ai_error(e)}"
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        preview = re.sub(r"\s+", " ", text)[:200]
        return [], f"AI가 단어장 형식으로 답하지 않았습니다" + (f": {preview}" if preview else " (빈 응답)")
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError) as e:
        return [], f"AI 응답을 해석하지 못했습니다: {e}"
    out = []
    for item in parsed.get("words", []) if isinstance(parsed, dict) else []:
        word = str((item or {}).get("word", "")).strip()
        meaning = str((item or {}).get("meaning", "")).strip()
        if word and meaning:
            row = {"word": word, "meaning": meaning, "is_phrase": " " in word}
            # 자료에 난이도가 적혀 있던 단어만 그 난이도를 따로 들고 간다
            diff = vocab_difficulty_from_text((item or {}).get("difficulty"))
            if diff:
                row["difficulty"] = diff
            out.append(row)
    if not out:
        return [], "AI가 이 자료에서 단어·뜻 쌍을 찾지 못했습니다. 단어와 뜻이 함께 뚜렷하게 보이는 자료인지 확인해주세요."
    return out, ""


@app.post("/api/admin/vocab/upload", dependencies=[Depends(verify_admin)])
async def upload_vocab_file(file: UploadFile = File(...), difficulty: str = Form("mid")):
    """💡 엑셀 열 순서를 규칙(1열=단어, 2열=뜻)으로 미리 짐작하다가, 순번 열이
    섞인 실제 파일에서 단어 대신 번호를 저장해버린 적이 있다 — "어떤 형태의 자료든
    상관없이" 되어야 한다는 요청에 따라, 엑셀/CSV도 규칙으로 추측하지 않고 표
    내용을 AI에게 그대로 보여주고 읽게 한다(사진·PDF와 동일한 방식)."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    diff = normalize_vocab_difficulty(difficulty)
    raw = await file.read()
    name = (file.filename or "").lower()

    if name.endswith((".xlsx", ".csv")):
        try:
            rows = await asyncio.to_thread(_read_sheet, raw, file.filename)
        except ValueError as e:
            return {"success": False, "detail": str(e)}
        data_rows = [[str(c or "").strip() for c in r] for r in rows if any(str(c or "").strip() for c in r)]
        if not data_rows:
            return {"success": False, "detail": "파일에서 읽을 내용이 없습니다."}
        words = []
        last_error = ""
        for i in range(0, len(data_rows), VOCAB_TABLE_ROWS_PER_BATCH):
            batch = data_rows[i:i + VOCAB_TABLE_ROWS_PER_BATCH]
            table_text = "\n".join(" | ".join(r) for r in batch)
            batch_words, err = await extract_vocab_words_via_ai([VOCAB_EXTRACT_PROMPT + "\n\n[표 데이터 — 줄마다 칸을 '|'로 구분]\n" + table_text])
            words += batch_words
            last_error = err or last_error
    else:
        parts = []
        if name.endswith(".pdf"):
            try:
                pdf_doc = fitz.open(stream=raw, filetype="pdf")
                for page in pdf_doc[:15]:
                    pix = page.get_pixmap(dpi=150)
                    parts.append({"mime_type": "image/png", "data": pix.tobytes("png")})
                pdf_doc.close()
            except Exception as e:
                return {"success": False, "detail": f"PDF를 읽지 못했습니다: {e}"}
        elif (file.content_type or "").startswith("image/"):
            parts.append({"mime_type": file.content_type, "data": raw})
        else:
            return {"success": False, "detail": "엑셀(.xlsx/.csv), 이미지, PDF 파일만 올릴 수 있습니다."}
        words, last_error = await extract_vocab_words_via_ai([VOCAB_EXTRACT_PROMPT] + parts)

    if not words:
        return {"success": False, "detail": last_error or "읽을 수 있는 단어를 찾지 못했습니다. 자료에 단어와 뜻이 함께 있는지 확인해주세요."}

    # 💡 표준 양식의 '난이도' 칸처럼 단어마다 난이도가 적혀 있으면 그것을 따르고,
    #    비어 있는 단어는 올릴 때 고른 난이도로 넣는다. 한 파일로 상·중·하를 한꺼번에.
    by_diff = {}
    for w in words:
        d = w.pop("difficulty", "") or diff
        by_diff.setdefault(normalize_vocab_difficulty(d), []).append(w)

    file_id = uuid.uuid4().hex[:12]
    counts = {k: len(v) for k, v in by_diff.items()}
    await asyncio.to_thread(
        lambda: db.collection("vocab_files").document(file_id).set({
            "label": file.filename, "difficulty": diff, "count": len(words),
            "counts": counts,
            "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    )
    seq = 0
    for d_key, group in by_diff.items():
        chunks = [group[i:i + VOCAB_CHUNK_SIZE] for i in range(0, len(group), VOCAB_CHUNK_SIZE)] or [[]]
        for chunk in chunks:
            await asyncio.to_thread(
                lambda seq=seq, chunk=chunk, d_key=d_key: db.collection("vocab_words").document(f"{file_id}_{seq:03d}").set({
                    "file_id": file_id, "difficulty": d_key, "words": chunk,
                })
            )
            seq += 1
    return {"success": True, "file_id": file_id, "count": len(words), "counts": counts}


@app.get("/api/admin/vocab/files", dependencies=[Depends(verify_admin)])
def list_vocab_files():
    if db is None:
        return {"success": False, "files": [], "counts": {}}
    rows = [{"id": d.id, **d.to_dict()} for d in db.collection("vocab_files").stream()]
    rows.sort(key=lambda r: str(r.get("uploaded_at", "")), reverse=True)
    counts = {"high": 0, "mid": 0, "low": 0}
    for r in rows:
        # 한 파일 안에 난이도가 섞여 있으면 그 내역대로, 없으면 파일 난이도로 센다
        per_file = r.get("counts") or {}
        if per_file:
            for k, v in per_file.items():
                counts[normalize_vocab_difficulty(k)] += int(v or 0)
        else:
            counts[normalize_vocab_difficulty(r.get("difficulty"))] += int(r.get("count", 0) or 0)
    return {"success": True, "files": rows, "counts": counts}


@app.delete("/api/admin/vocab/files/{file_id}", dependencies=[Depends(verify_admin)])
async def delete_vocab_file(file_id: str):
    if db is None:
        return {"success": False}
    await asyncio.to_thread(lambda: db.collection("vocab_files").document(file_id).delete())
    docs = await asyncio.to_thread(lambda: list(db.collection("vocab_words").where("file_id", "==", file_id).stream()))
    for d in docs:
        await asyncio.to_thread(d.reference.delete)
    return {"success": True}


def load_vocab_pool(difficulty: str) -> list:
    """그 난이도로 올라와 있는 모든 파일의 단어를 하나로 모은다."""
    if db is None:
        return []
    diff = normalize_vocab_difficulty(difficulty)
    pool = []
    for d in db.collection("vocab_words").where("difficulty", "==", diff).stream():
        pool.extend((d.to_dict() or {}).get("words", []))
    return pool


def blank_word(word: str) -> tuple:
    """단어의 일부 글자를 빈칸(_)으로 바꾼 표시용 문자열을 만든다."""
    letters = list(word)
    idxs = [i for i, c in enumerate(letters) if c.isalpha()]
    if not idxs:
        return word
    n_blank = max(1, min(len(idxs) - 1 if len(idxs) > 1 else 1, round(len(idxs) * 0.4)))
    blanks = set(random.sample(idxs, n_blank))
    return "".join("_" if i in blanks else c for i, c in enumerate(letters))


def build_vocab_question(entry: dict, qtype: int, no: int) -> dict:
    word, meaning, diff = entry["word"], entry["meaning"], entry["difficulty"]
    if qtype == 1:
        return {"no": no, "type": 1, "prompt": word, "answer": meaning, "difficulty": diff}
    if qtype == 2:
        return {"no": no, "type": 2, "prompt": meaning, "answer": word, "difficulty": diff}
    if qtype == 3:
        return {"no": no, "type": 3, "prompt": blank_word(word), "prompt_meaning": meaning, "answer": word, "difficulty": diff}
    return {"no": no, "type": 4, "prompt": word, "answer": meaning, "difficulty": diff}


def generate_vocab_questions(counts: dict) -> list:
    picked_all = []
    for diff_key, n in (counts or {}).items():
        diff_key = normalize_vocab_difficulty(diff_key)
        n = int(n or 0)
        if n <= 0:
            continue
        pool = load_vocab_pool(diff_key)
        if len(pool) < n:
            raise ValueError(f"{VOCAB_DIFFICULTIES[diff_key]} 난이도에 등록된 단어가 {len(pool)}개뿐이라 {n}개를 낼 수 없습니다.")
        for entry in random.sample(pool, n):
            entry = dict(entry)
            entry["difficulty"] = diff_key
            qtype = random.choice([1, 4]) if entry.get("is_phrase") else random.choice([1, 2, 3])
            picked_all.append((entry, qtype))
    random.shuffle(picked_all)
    return [build_vocab_question(entry, qtype, i + 1) for i, (entry, qtype) in enumerate(picked_all)]


class VocabTestCreateReq(BaseModel):
    title: str
    deadline: str = ""
    time_limit: int = 15
    target_class: str = ""
    counts: dict = {}
    manual_questions: list = None


@app.get("/api/admin/vocab/words", dependencies=[Depends(verify_admin)])
def list_vocab_words(difficulty: str = "mid"):
    """원장님이 무작위가 아니라 단어를 직접 골라 출제하고 싶을 때, 그 난이도에
    올라와 있는 단어를 목록으로 보여준다(파일 여러 개면 전부 합쳐서).
    difficulty='all'이면 난이도 구분 없이 전체를 한 번에 보여준다."""
    if str(difficulty).strip().lower() == "all":
        words = []
        for d in ("high", "mid", "low"):
            for w in load_vocab_pool(d):
                words.append({"word": w.get("word", ""), "meaning": w.get("meaning", ""), "is_phrase": bool(w.get("is_phrase")), "difficulty": d})
        return {"success": True, "difficulty": "all", "words": words}

    diff = normalize_vocab_difficulty(difficulty)
    pool = load_vocab_pool(diff)
    return {"success": True, "difficulty": diff, "words": [
        {"word": w.get("word", ""), "meaning": w.get("meaning", ""), "is_phrase": bool(w.get("is_phrase")), "difficulty": diff} for w in pool
    ]}


@app.post("/api/admin/vocab_test", dependencies=[Depends(verify_admin)])
async def create_vocab_test(req: VocabTestCreateReq):
    if db is None:
        return {"success": False, "detail": "DB 오류"}
    if not req.title.strip():
        return {"success": False, "detail": "시험 제목은 필수입니다."}

    if req.manual_questions:
        # 💡 무작위가 아니라 원장님이 직접 고른 단어·문제 유형 그대로 문항을 만든다.
        # 그래도 스펠링 빈칸(3번 유형)은 매번 새로 빈칸을 만들어야 하므로
        # build_vocab_question을 그대로 재사용한다.
        questions = []
        for item in req.manual_questions:
            word = str(item.get("word", "")).strip()
            meaning = str(item.get("meaning", "")).strip()
            if not word or not meaning:
                continue
            entry = {"word": word, "meaning": meaning, "difficulty": normalize_vocab_difficulty(item.get("difficulty"))}
            try:
                qtype = int(item.get("type", 1))
            except (TypeError, ValueError):
                qtype = 1
            if qtype not in (1, 2, 3, 4):
                qtype = 1
            questions.append(build_vocab_question(entry, qtype, len(questions) + 1))
        if not questions:
            return {"success": False, "detail": "선택한 문항이 없습니다."}
    else:
        try:
            questions = await asyncio.to_thread(generate_vocab_questions, req.counts)
        except ValueError as e:
            return {"success": False, "detail": str(e)}
        if not questions:
            return {"success": False, "detail": "출제할 단어 수를 1개 이상 입력하세요."}

    title = with_subject_prefix(req.title, "english")
    safe_title = sanitize_doc_id(title)
    await asyncio.to_thread(
        lambda: db.collection("vocab_tests").document(safe_title).set({
            "title": title, "subject": "english", "target_class": (req.target_class or "").strip(),
            "deadline": req.deadline, "time_limit": int(req.time_limit or 0),
            "questions": questions,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    )
    return {"success": True, "title": title}


def vocab_test_public(data: dict) -> dict:
    """학생에게 보여줄 때는 정답(answer)만 빼고 준다."""
    out = dict(data)
    out["questions"] = [{k: v for k, v in q.items() if k != "answer"} for q in (data.get("questions") or [])]
    out["question_count"] = len(data.get("questions") or [])
    return out


@app.get("/api/vocab_tests")
def get_vocab_tests(student_name: str = ""):
    if db is None:
        return {"success": False, "tests": []}
    rows = [{"id": d.id, **d.to_dict()} for d in db.collection("vocab_tests").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]
    if student_name:
        rows = [vocab_test_public(t) for t in rows if task_visible_to_student(t.get("subject", "english"), t.get("target_class", ""), student_name)]
    return {"success": True, "tests": rows}


@app.delete("/api/admin/vocab_test/{title}", dependencies=[Depends(verify_admin)])
def delete_vocab_test(title: str):
    if db:
        db.collection("vocab_tests").document(title).delete()
    return {"success": True}


class VocabTestStartReq(BaseModel):
    student_name: str
    title: str


@app.post("/api/vocab_test/start")
async def start_vocab_test(req: VocabTestStartReq):
    """💡 타임어택 퀴즈와 같은 이유로(재입장하면 타이머가 리셋되는 구멍을 막기 위해)
    시작 시각을 서버에 기록해두고, 다시 들어와도 그 시각부터 남은 시간만 돌려준다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}

    doc = await asyncio.to_thread(lambda: db.collection("vocab_tests").document(req.title).get())
    if not doc.exists:
        return {"success": False, "detail": "존재하지 않는 시험입니다."}
    data = doc.to_dict()
    time_limit = int(data.get("time_limit", 0) or 0)

    if not await asyncio.to_thread(task_visible_to_student, data.get("subject", "english"), data.get("target_class", ""), req.student_name):
        reason = await asyncio.to_thread(task_visibility_denied_reason, data.get("subject", "english"), data.get("target_class", ""), req.student_name)
        return {"success": False, "detail": reason}

    existing = await asyncio.to_thread(
        lambda: list(
            db.collection("reports")
            .where("student_name", "==", req.student_name)
            .where("task_name", "==", req.title)
            .where("type", "==", "영어 단어 시험")
            .limit(1)
            .stream()
        )
    )
    if existing:
        return {"success": False, "detail": "이미 완료한 시험입니다."}

    attempt_id = sanitize_doc_id(f"{req.title}__{req.student_name}")
    a_ref = db.collection("vocab_test_attempts").document(attempt_id)
    a_doc = await asyncio.to_thread(a_ref.get)
    if a_doc.exists:
        started_at = a_doc.to_dict().get("started_at")
    else:
        started_at = datetime.now().timestamp()
        await asyncio.to_thread(
            lambda: a_ref.set({"student_name": req.student_name, "title": req.title, "started_at": started_at})
        )
    return {"success": True, "started_at": started_at, "time_limit": time_limit, "test": vocab_test_public(data)}


def normalize_vocab_answer(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


async def ai_grade_vocab_meanings(items: list) -> dict:
    """뜻/해석형 문항(1,4번 유형)을 한 번의 AI 호출로 모아 채점한다.
    items: [{no, word, correct, student}] → {no: True/False}."""
    if not items:
        return {}
    lines = "\n".join(
        f'{{"no": {it["no"]}, "단어또는구절": "{it["word"]}", "모범답안": "{it["correct"]}", "학생답안": "{it["student"]}"}}'
        for it in items
    )
    prompt = f"""다음은 영어 단어/구절 뜻풀이 시험의 채점 대상입니다. 각 문항마다 학생 답안이 모범답안과
뜻이 통하면(동의어거나 표현이 달라도 의미가 같으면) 정답으로 채점하세요. 철자·띄어쓰기·조사가
달라도 의미가 같으면 정답입니다. 의미가 다르거나 답을 안 썼으면 오답입니다.

[채점 대상]
{lines}

[출력 형식 - 반드시 이 JSON 배열 형식으로만, 다른 말 없이 출력하세요]
[{{"no": 1, "ok": true}}, {{"no": 2, "ok": false}}]"""
    try:
        resp = await asyncio.to_thread(safe_generate, [prompt], False, False)
        text = (resp.text or "").strip()
        match = re.search(r"\[.*\]", text, re.S)
        if not match:
            return {}
        parsed = json.loads(match.group(0))
        return {int(p["no"]): bool(p.get("ok")) for p in parsed if "no" in p}
    except Exception:
        return {}


class VocabTestSubmitReq(BaseModel):
    school: str
    grade: str
    student_name: str
    title: str
    answers: list


@app.post("/api/vocab_test/submit")
async def submit_vocab_test(req: VocabTestSubmitReq):
    if db is None:
        return {"success": False}

    existing = await asyncio.to_thread(
        lambda: list(
            db.collection("reports")
            .where("student_name", "==", req.student_name)
            .where("task_name", "==", req.title)
            .where("type", "==", "영어 단어 시험")
            .limit(1)
            .stream()
        )
    )
    if existing:
        return {"success": False, "detail": "이미 완료한 시험입니다."}

    doc = await asyncio.to_thread(lambda: db.collection("vocab_tests").document(req.title).get())
    if not doc.exists:
        return {"success": False, "detail": "존재하지 않는 시험입니다."}
    data = doc.to_dict()

    if not await asyncio.to_thread(task_visible_to_student, data.get("subject", "english"), data.get("target_class", ""), req.student_name):
        reason = await asyncio.to_thread(task_visibility_denied_reason, data.get("subject", "english"), data.get("target_class", ""), req.student_name)
        return {"success": False, "detail": reason}

    time_limit = int(data.get("time_limit", 0) or 0)
    if time_limit > 0:
        attempt_id = sanitize_doc_id(f"{req.title}__{req.student_name}")
        a_doc = await asyncio.to_thread(lambda: db.collection("vocab_test_attempts").document(attempt_id).get())
        if a_doc.exists:
            started_at = a_doc.to_dict().get("started_at")
            if started_at and datetime.now().timestamp() - float(started_at) > time_limit * 60 + 20:
                return {"success": False, "detail": "제한 시간이 지나 제출할 수 없습니다."}

    questions = data.get("questions") or []
    ai_batch = []
    results = []
    for i, q in enumerate(questions):
        my = str(req.answers[i]).strip() if i < len(req.answers) and req.answers[i] is not None else ""
        results.append({
            "no": q["no"], "type": q["type"], "prompt": q["prompt"], "answer": q["answer"],
            "my": my, "difficulty": q.get("difficulty", "mid"), "ok": None,
        })
        if q["type"] in (1, 4):
            ai_batch.append({"no": q["no"], "word": q["prompt"], "correct": q["answer"], "student": my or "(빈칸)"})
        else:
            results[-1]["ok"] = bool(my) and normalize_vocab_answer(my) == normalize_vocab_answer(q["answer"])

    if ai_batch:
        ai_results = await ai_grade_vocab_meanings(ai_batch)
        for r in results:
            if r["ok"] is None:
                r["ok"] = ai_results.get(r["no"], normalize_vocab_answer(r["my"]) == normalize_vocab_answer(r["answer"]))

    correct_count = sum(1 for r in results if r["ok"])
    actual_score = round(correct_count / len(results) * 100) if results else 0

    diff_stats = {}
    for r in results:
        s = diff_stats.setdefault(r["difficulty"], {"total": 0, "correct": 0})
        s["total"] += 1
        if r["ok"]:
            s["correct"] += 1

    await asyncio.to_thread(
        lambda: db.collection("reports").add({
            "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "student_name": req.student_name, "school": req.school, "grade": req.grade,
            "task_name": req.title, "type": "영어 단어 시험",
            "score": actual_score, "question_count": len(results), "correct_count": correct_count,
            "wrongs": [r["no"] for r in results if not r["ok"]],
        })
    )

    vocab_xp = XP_REWARD_QUIZ_BASE + actual_score // 5
    s_ref = db.collection("students").document(req.student_name)
    s_doc = await asyncio.to_thread(s_ref.get)
    old_xp = s_doc.to_dict().get("xp", 0) if s_doc.exists else 0
    lvl_up = level_up_info(old_xp, vocab_xp)
    await asyncio.to_thread(lambda: s_ref.set({"xp": firestore.Increment(vocab_xp)}, merge=True))
    send_telegram_message(f"🔤 [영어 단어 시험 완료]\n{req.student_name} 학생이 '{req.title}' 시험을 완료했습니다. (점수: {actual_score}점)")

    return {
        "success": True, "score": actual_score, "correct_count": correct_count,
        "question_count": len(results), "details": results, "difficulty_stats": diff_stats,
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
# 관리자 - 오래 걸리는 일은 '작업'으로 맡겨두기
#   문제 출제나 해설 영상 만들기는 1~2분씩 걸린다. 예전에는 그동안 그 화면에
#   붙들려 있어야 했고, 다른 일을 하거나 페이지를 나가면 작업이 끊겼다.
#   이제는 서버에 일을 맡겨두고(작업 등록) 화면을 떠나도 서버가 계속 진행한다.
#   결과는 jobs 컬렉션에 쌓이므로, 나중에 아무 때나 돌아와서 받아 가면 된다.
# ─────────────────────────────────────────────────────────
JOB_STALE_MINUTES = 20      # 이만큼 소식이 없으면 서버가 재시작된 것으로 본다
PARTIAL_KEEP_CHARS = 60000  # 진행 중 보여줄 본문은 이만큼만 (문서 크기 한도 때문)


class MemUpload:
    """업로드된 파일을 메모리에 담아 두는 대역.
    요청이 끝나면 UploadFile은 닫히기 때문에, 작업으로 넘길 때는 미리 읽어 둬야 한다."""

    def __init__(self, filename: str, content_type: str, data: bytes):
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self) -> bytes:
        return self._data


def job_ref(job_id: str):
    return db.collection("jobs").document(job_id)


def create_job(kind: str, title: str, admin_name: str = "", meta: dict = None) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    job_id = uuid.uuid4().hex[:12]
    job_ref(job_id).set({
        "kind": kind, "title": title or "", "status": "running",
        "progress": "시작하는 중...", "result": "", "detail": "",
        "meta": meta or {}, "admin_name": admin_name,
        "created_at": now, "updated_at": now,
    })
    return job_id


def update_job(job_id: str, **fields):
    fields["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        job_ref(job_id).set(fields, merge=True)
    except Exception as e:
        print("작업 상태 저장 실패:", e)


def job_is_stale(row: dict) -> bool:
    if row.get("status") != "running":
        return False
    try:
        last = datetime.strptime(str(row.get("updated_at", "")), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return (datetime.now() - last).total_seconds() > JOB_STALE_MINUTES * 60


async def run_question_job(job_id: str, params: dict):
    """문제 출제를 백그라운드에서 돌린다. 화면은 이미 떠났을 수 있으므로
    진행 상황과 결과를 모두 jobs 문서에 적어 둔다."""
    def count_questions(text: str) -> int:
        # 💡 [정답 및 해설]에도 '1. 정답 ①'처럼 번호가 붙어 있어, 그대로 세면 두 번 센다.
        #    문항 본문 구간만 잘라서 센다.
        body = text.split("[정답 및 해설]")[0]
        return len(set(PROBLEM_NUM_RE.findall(body)))

    buf, last_saved = [], time.time()
    try:
        resp = await generate_stream(**{k: v for k, v in params.items() if k != "_job_meta"})
        async for chunk in resp.body_iterator:
            buf.append(chunk)
            # 💡 끝날 때만 저장하면 "지금 뭐가 만들어지고 있는지" 볼 방법이 없다.
            #    5초에 한 번씩 여기까지 만든 문제를 그대로 적어둬서, 원장님이 진행 중에도
            #    어떤 문제가 나오고 있는지 눈으로 확인할 수 있게 한다.
            if time.time() - last_saved >= 5:
                text = "".join(buf)
                update_job(job_id, progress=f"{count_questions(text)}문항까지 만들었습니다...",
                           partial=text[-PARTIAL_KEEP_CHARS:])
                last_saved = time.time()
        text = "".join(buf)
        if text.lstrip().startswith("❌"):
            update_job(job_id, status="error", detail=text.strip()[:500], progress="실패")
            return
        n = count_questions(text)
        # 💡 여러 개를 동시에 맡기면 화면은 하나밖에 못 따라간다. 화면이 보고 있든 아니든
        #    서버가 끝나는 즉시 보관함에 넣어, 어느 것도 잃어버리지 않게 한다.
        saved_id = ""
        try:
            meta = params.get("_job_meta") or {}
            saved_id = await asyncio.to_thread(
                store_question_bank, meta.get("title", ""), text, meta.get("subject", "korean"))
        except Exception as e:
            print("출제 결과 보관함 저장 실패:", e)
        update_job(job_id, status="done", result=text, partial="", progress=f"{n}문항 완성",
                   question_id=saved_id,
                   done_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        update_job(job_id, status="error", detail=friendly_ai_error(e)[:900], progress="실패")


async def run_video_job(job_id: str, params: dict):
    """해설 영상 만들기를 백그라운드에서 돌린다."""
    try:
        update_job(job_id, progress="장면을 나누는 중...")
        res = await generate_video(**params)
        if not res.get("success"):
            update_job(job_id, status="error", detail=res.get("detail", "")[:500], progress="실패")
            return
        update_job(job_id, status="done", progress=f"장면 {res.get('scene_count', 0)}개로 완성",
                   result=res.get("url", ""), meta={"title": res.get("title", ""), "video_id": res.get("id", "")},
                   done_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        update_job(job_id, status="error", detail=friendly_ai_error(e)[:900], progress="실패")


@app.post("/api/admin/jobs/questions")
async def start_question_job(
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
    verify: bool = Form(True),
    title: str = Form(""),
    subject: str = Form("korean"),
    files: Optional[List[UploadFile]] = File(None),
    name: str = Depends(current_admin_name),
):
    """문제 출제를 작업으로 맡긴다. 바로 작업 번호만 돌려주고, 출제는 서버가 이어서 한다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
    if total <= 0:
        return {"success": False, "detail": "문항 수를 1개 이상 지정해주세요."}

    # 요청이 끝나면 업로드 파일이 닫히므로 지금 다 읽어서 들고 간다
    mem_files = []
    for f in (files or []):
        if f.filename:
            mem_files.append(MemUpload(f.filename, f.content_type or "application/octet-stream", await f.read()))

    params = {
        "q_mode": q_mode, "q_types": q_types,
        "cnt_killer": cnt_killer, "cnt_semi": cnt_semi, "cnt_high": cnt_high,
        "cnt_mid": cnt_mid, "cnt_low": cnt_low,
        "q_text": q_text, "q_texts": q_texts, "q_principle": q_principle,
        "start_num": start_num, "source_counts": source_counts,
        "verify": verify, "subject": subject,
        "files": mem_files or None, "_": True,
    }
    job_title = title or "제목 없는 출제"
    subj = normalize_subject(subject)
    job_id = await asyncio.to_thread(
        create_job, "questions", job_title, name,
        {"total": total, "start_num": start_num, "subject": subj},
    )
    # generate_stream 에 넘길 인자와 섞이지 않게, 작업용 정보는 따로 담아 둔다
    params["_job_meta"] = {"title": job_title, "subject": subj}
    asyncio.create_task(run_question_job(job_id, params))
    return {"success": True, "job_id": job_id}


@app.post("/api/admin/jobs/video")
async def start_video_job(text: str = Form(...), title: str = Form(""), question_no: int = Form(0),
                          script: str = Form(""),
                          name: str = Depends(current_admin_name)):
    """해설 영상 만들기를 작업으로 맡긴다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    me = get_admin_doc(name)
    if not me or not me.get("is_owner"):
        return {"success": False, "detail": "이 기능은 원장님 계정만 사용할 수 있습니다."}
    if not text.strip():
        return {"success": False, "detail": "영상으로 만들 설명 내용을 입력해주세요."}

    label = (title.strip() or "해설영상") + (f" — {question_no}번" if question_no else "")
    job_id = await asyncio.to_thread(create_job, "video", label, name, {"question_no": question_no})
    asyncio.create_task(run_video_job(job_id, {
        "text": text, "title": title, "question_no": question_no, "script": script, "name": name,
    }))
    return {"success": True, "job_id": job_id}


@app.get("/api/admin/jobs", dependencies=[Depends(verify_admin)])
def list_jobs(limit: int = 20):
    """맡겨둔 작업들. 화면을 떠났다 돌아와도 여기서 결과를 찾아갈 수 있다."""
    if db is None:
        return {"success": False, "jobs": []}
    rows = [{"id": d.id, **d.to_dict()} for d in db.collection("jobs").stream()]
    rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    out = []
    for r in rows[:max(1, min(100, limit))]:
        if job_is_stale(r):
            r["status"] = "stalled"
            r["detail"] = r.get("detail") or "서버가 다시 시작되어 작업이 끊긴 것 같습니다. 다시 맡겨주세요."
        # 목록에서는 본문까지 실어 보내지 않는다(길다). 있다는 사실만 알려주고,
        # 실제 내용은 작업 하나를 열어볼 때 준다.
        out.append({k: v for k, v in r.items() if k not in ("result", "partial")}
                   | {"has_result": bool(r.get("result")), "has_partial": bool(r.get("partial"))})
    running = sum(1 for r in out if r["status"] == "running")
    return {"success": True, "jobs": out, "running": running}


@app.get("/api/admin/jobs/{job_id}", dependencies=[Depends(verify_admin)])
def get_job(job_id: str):
    if db is None:
        return {"success": False}
    doc = job_ref(job_id).get()
    if not doc.exists:
        return {"success": False, "detail": "이미 지워졌거나 없는 작업입니다."}
    row = {"id": doc.id, **doc.to_dict()}
    if job_is_stale(row):
        row["status"] = "stalled"
    return {"success": True, "job": row}


@app.delete("/api/admin/jobs/{job_id}", dependencies=[Depends(verify_admin)])
def delete_job(job_id: str):
    if db is not None:
        job_ref(job_id).delete()
    return {"success": True}


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
    verify: bool = Form(True),
    subject: str = Form("korean"),
    files: Optional[List[UploadFile]] = File(None),
    _: bool = Depends(verify_admin),
):
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
    start_num = max(1, start_num)
    subj_key = normalize_subject(subject)

    # 💡 한 번에 너무 많은 문항을 요청하면 응답이 길어져 품질이 떨어지고 실패/비용 부담도 커져서,
    # 20문항씩 나눠 여러 번 요청한 뒤 결과를 합친다.
    QUESTIONS_PER_BATCH = 20
    # 💡 글자로 된 PDF는 텍스트만 뽑아 보내면 원본을 통째로 올릴 때보다 AI에 보내는
    #    양이 크게 줄어 사용료가 절약된다. 이 글자 수에 못 미치면 스캔본(그림)으로
    #    보고 원본을 그대로 보여준다.
    PDF_TEXT_MIN_CHARS = 200

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
                # 💡 글자 PDF는 텍스트만 뽑아 보낸다 (사용료 절약). 다만 수학은 도형·그래프가
                #    문제의 일부라 글자만 뽑으면 문제가 어긋나므로 원본을 그대로 보여준다.
                extracted = ""
                if subj_key != "math" and f.filename.lower().endswith(".pdf"):
                    try:
                        doc = fitz.open(stream=file_bytes, filetype="pdf")
                        extracted = "".join(page.get_text() for page in doc)
                        doc.close()
                    except Exception:
                        extracted = ""
                if len(extracted.strip()) >= PDF_TEXT_MIN_CHARS:
                    sources.append({"label": f.filename, "text": extracted.strip(), "parts": []})
                else:
                    # 스캔본이거나 이미지 파일이면 원본을 그대로 보여줘야 한다
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

    async def verify_and_refine(draft_text: str, source: dict, model) -> str:
        """💡 정답이 실제 지문과 어긋나거나(오채점), 정답 선지만 유독 티가 나서 지문을
        안 읽어도 맞힐 수 있는 문항을 한 번 더 걸러내기 위한 자체 검수 단계.
        초안을 그대로 다시 넣고 AI 스스로 지문과 대조해 고치게 한 뒤, 고친 결과로 교체한다.
        검수 중 오류가 나면(타임아웃 등) 검수 없이 초안을 그대로 쓴다 — 품질 저하보다
        실패로 전체 출제가 끊기는 쪽이 더 나쁘기 때문."""
        verify_prompt = f"""아래는 방금 만든 문제/정답 및 해설/정답표 세트입니다. 첨부된(또는 아래 제시된) 원본 지문과 문항 하나하나를 다시 대조해서 스스로 검수하고, 문제가 있으면 직접 고쳐 최종본을 만드세요.

[검수 기준 - 문제가 있으면 반드시 고칠 것]
1. 정답표·해설에 적힌 정답 번호가 실제 지문 내용과 정확히 일치하는지 다시 확인하세요. 어긋나 있으면(오채점) 정답 번호를 바로잡고, 해설과 정답표도 함께 고치세요.
2. 정답 선지만 유독 길거나 자세하거나 서술 방식이 달라서 지문을 읽지 않고도 정답이 한눈에 티가 나는 문항이 있으면, 선지들의 길이와 문장 구조를 서로 비슷하게 다시 쓰세요. (선지의 참·거짓, 정답 여부 자체는 절대 바꾸지 마세요.)
3. 오답 선지가 지문과 무관하거나 너무 뻔하게 틀려서 소거법만으로 쉽게 답이 나오는 문항이 있으면, 지문 내용을 살짝 비튼 더 그럴듯한 오답으로 다시 쓰세요.
4. 문항들의 정답 번호가 규칙적인 패턴(오름차순·반복 등)을 이루고 있으면, 문항 내용과 정답 자체는 바꾸지 말고 선지 순서만 재배치해 패턴을 깨세요. 그에 맞춰 해설·정답표도 갱신하세요.
5. 오탈자, 원문자(①②③④⑤) 형식 오류, 마크다운 기호(**, # 등) 사용 여부도 함께 점검해 고치세요.

문제가 없는 부분은 그대로 두세요. 최종 결과는 초안과 동일한 순서([지문]이 포함돼 있었다면 지문 그대로 → 문항 → [정답 및 해설] → [정답표])로, 다른 설명이나 안내문 없이 그 형식 그대로만 출력하세요.

[방금 만든 초안]
{draft_text}"""
        if not source["parts"]:
            verify_prompt += f"""

[원본 지문]
{source["text"]}"""
        try:
            vresp = await asyncio.to_thread(model.generate_content, [verify_prompt] + source["parts"])
            vtext = (vresp.text or "").strip()
            return vtext if vtext else draft_text
        except Exception:
            return draft_text

    async def iter_batches():
        try:
            model = get_best_model(prefer_quality=True)
        except Exception as e:
            yield f"❌ AI 생성 실패\n{friendly_ai_error(e)}"
            return

        # 💡 검수는 '초안을 지문과 대조해 고치는' 확인 작업이라 빠른 모델로도 충분하다.
        #    출제와 같은 고급 모델로 검수까지 하면 사용료가 그대로 두 배가 되므로,
        #    검수만 빠른 모델로 돌려 품질은 지키면서 비용을 크게 줄인다.
        verify_model = model
        if verify:
            try:
                verify_model = get_best_model(prefer_quality=False)
            except Exception:
                verify_model = model

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
                    yield f"\n\n❌ {cursor}번부터 출제하는 중 오류가 발생했습니다.\n{friendly_ai_error(e)}"
                    return

                if verify:
                    text = await verify_and_refine(text, source, verify_model)
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
                yield f"\n\n❌ AI 생성 중 오류가 발생했습니다.\n{friendly_ai_error(stream_err)}"

        return StreamingResponse(iter_response(), media_type="text/plain")
    except Exception as e:
        # 💡 이전엔 무슨 오류든 똑같은 안내문만 보여줘서 원인 파악이 불가능했음.
        # 실제 예외 메시지(모델 이름 오류, 429 레이트리밋, 세이프티 차단 등)를 그대로 노출.
        err_msg = str(e)

        def err_response():
            yield f"❌ AI 생성 실패\n{friendly_ai_error(err_msg)}"

        return StreamingResponse(err_response(), media_type="text/plain")


# ─────────────────────────────────────────────────────────
# 관리자 - 해설 영상 자동 생성 (텍스트 → 세로형 쇼츠 영상)
#   해설 텍스트를 AI가 짧은 구어체 장면들로 나누면, 장면마다 자막 슬라이드 +
#   TTS 음성을 입힌 짧은 영상 클립을 만들어 이어붙인다. 원장님이 직접
#   촬영/편집하지 않아도, 방금 만든 해설 자료를 그대로 붙여넣기만 하면
#   학생에게 바로 배포할 수 있는 영상이 나온다.
# ─────────────────────────────────────────────────────────
VIDEO_FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "NotoSansKR.ttf")
VIDEO_W, VIDEO_H = 1080, 1920
VIDEO_MAX_SCENES = 25
_video_font_cache = {}


def _video_font(size: int, bold: bool = False):
    key = (size, bold)
    if key not in _video_font_cache:
        f = ImageFont.truetype(VIDEO_FONT_PATH, size)
        if bold:
            try:
                f.set_variation_by_axes([700])
            except Exception:
                pass
        _video_font_cache[key] = f
    return _video_font_cache[key]


def _video_wrap_lines(draw, text: str, font, max_width: int) -> list:
    """한글은 어절보다 글자 단위로 줄바꿈해야 슬라이드 폭에 안전하게 맞는다."""
    lines = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            test = cur + ch
            if draw.textbbox((0, 0), test, font=font)[2] > max_width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = test
        lines.append(cur)
    return lines


def _video_make_slide(text: str, out_path: str):
    img = Image.new("RGB", (VIDEO_W, VIDEO_H), (17, 20, 28))
    d = ImageDraw.Draw(img)
    font = _video_font(64, bold=True)
    lines = _video_wrap_lines(d, text, font, VIDEO_W - 160)
    line_h = font.size + 26
    total_h = line_h * len(lines)
    y = (VIDEO_H - total_h) // 2
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        d.text(((VIDEO_W - w) / 2, y), line, font=font, fill=(255, 255, 255))
        y += line_h
    brand_font = _video_font(34)
    brand = "로지에듀"
    bbox = d.textbbox((0, 0), brand, font=brand_font)
    d.text(((VIDEO_W - (bbox[2] - bbox[0])) / 2, VIDEO_H - 110), brand, font=brand_font, fill=(150, 155, 170))
    img.save(out_path)


def _video_make_intro_slide(out_path: str):
    """모든 문항별 영상 맨 앞에 붙는 브랜드 인트로 카드."""
    img = Image.new("RGB", (VIDEO_W, VIDEO_H), (12, 14, 22))
    d = ImageDraw.Draw(img)
    brand_font = _video_font(96, bold=True)
    sub_font = _video_font(54, bold=True)
    brand, sub = "로지에듀", "최준용 국어"
    bbox = d.textbbox((0, 0), brand, font=brand_font)
    d.text(((VIDEO_W - (bbox[2] - bbox[0])) / 2, VIDEO_H / 2 - 130), brand, font=brand_font, fill=(255, 255, 255))
    bbox2 = d.textbbox((0, 0), sub, font=sub_font)
    d.text(((VIDEO_W - (bbox2[2] - bbox2[0])) / 2, VIDEO_H / 2 + 10), sub, font=sub_font, fill=(196, 176, 255))
    img.save(out_path)


def _video_make_passage_slide(excerpt: str, highlight_span, out_path: str):
    """지문 발췌문을 보여주고, 정답의 근거가 되는 부분만 노란 형광펜처럼 강조한다."""
    img = Image.new("RGB", (VIDEO_W, VIDEO_H), (17, 20, 28))
    d = ImageDraw.Draw(img)
    # 💡 이모지(📖 등)는 Noto Sans KR에 글리프가 없어 네모 깨짐(tofu)으로 나온다 —
    # 직접 그린 네모 배지로 대신한다.
    d.rectangle([80, 96, 108, 124], fill=(250, 204, 21))
    d.text((124, 92), "지문 근거", font=_video_font(38, bold=True), fill=(250, 204, 21))

    body_font = _video_font(46)
    max_w = VIDEO_W - 160
    lines, cur, cur_w = [], [], 0
    for char_idx, ch in enumerate(excerpt):
        if ch == "\n":
            lines.append(cur); cur, cur_w = [], 0
            continue
        w = d.textlength(ch, font=body_font)
        if cur_w + w > max_w and cur:
            lines.append(cur); cur, cur_w = [], 0
        is_hi = bool(highlight_span and highlight_span[0] <= char_idx < highlight_span[1])
        cur.append((ch, is_hi)); cur_w += w
    if cur:
        lines.append(cur)

    line_h = body_font.size + 24
    total_h = line_h * len(lines)
    y = max(260, (VIDEO_H - total_h) // 2)
    for line in lines:
        text = "".join(c for c, _ in line)
        w = d.textbbox((0, 0), text, font=body_font)[2]
        x = (VIDEO_W - w) / 2
        cx = x
        for ch, is_hi in line:
            cw = d.textlength(ch, font=body_font)
            if is_hi:
                d.rectangle([cx - 2, y - 4, cx + cw + 2, y + body_font.size + 10], fill=(122, 95, 8))
            cx += cw
        cx = x
        for ch, is_hi in line:
            cw = d.textlength(ch, font=body_font)
            d.text((cx, y), ch, font=body_font, fill=(255, 241, 191) if is_hi else (220, 222, 230))
            cx += cw
        y += line_h
    img.save(out_path)


def _video_make_options_slide(stem: str, options: list, correct_idx: int, wrong_reasons: dict, out_path: str):
    """5개 선택지를 그대로 보여주면서, 정답은 초록 체크로, 오답은 빨간 X와 함께
    왜 틀렸는지 짧은 이유를 바로 아래에 덧붙여 보여준다."""
    img = Image.new("RGB", (VIDEO_W, VIDEO_H), (17, 20, 28))
    d = ImageDraw.Draw(img)
    d.rectangle([80, 86, 108, 114], fill=(250, 204, 21))
    d.text((124, 82), "선택지 분석", font=_video_font(38, bold=True), fill=(250, 204, 21))

    y = 180
    if stem:
        stem_font = _video_font(38)
        for line in _video_wrap_lines(d, stem, stem_font, VIDEO_W - 160):
            d.text((80, y), line, font=stem_font, fill=(180, 184, 200))
            y += stem_font.size + 14
        y += 24

    opt_font = _video_font(42, bold=True)
    reason_font = _video_font(30)
    for i, opt_text in enumerate(options, start=1):
        is_correct = (i == correct_idx)
        color = (110, 231, 150) if is_correct else (248, 113, 113)
        # 💡 체크/엑스 표시는 폰트 글리프(✔✘ 등)에 기대지 않고 직접 그린다 —
        # Noto Sans KR에 이 기호들의 글리프가 없어 네모 깨짐으로 나왔었다.
        r = opt_font.size * 0.34
        cx, cy = 80 + r, y + opt_font.size * 0.5
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=4)
        if is_correct:
            d.line([cx - r * 0.5, cy, cx - r * 0.1, cy + r * 0.45], fill=color, width=5)
            d.line([cx - r * 0.1, cy + r * 0.45, cx + r * 0.55, cy - r * 0.4], fill=color, width=5)
        else:
            d.line([cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5], fill=color, width=5)
            d.line([cx - r * 0.5, cy + r * 0.5, cx + r * 0.5, cy - r * 0.5], fill=color, width=5)
        lines = _video_wrap_lines(d, opt_text, opt_font, VIDEO_W - 220)
        for line in lines:
            d.text((140, y), line, font=opt_font, fill=(255, 255, 255) if is_correct else (215, 217, 225))
            y += opt_font.size + 12
        reason = wrong_reasons.get(str(i))
        if not is_correct and reason:
            for rline in _video_wrap_lines(d, f"→ {reason}", reason_font, VIDEO_W - 260):
                d.text((160, y), rline, font=reason_font, fill=(252, 165, 165))
                y += reason_font.size + 8
        y += 28
    img.save(out_path)


_OPTION_MARKERS = ["①", "②", "③", "④", "⑤"]


def _split_question_options(problem_text: str):
    """문항 텍스트에서 발문(stem)과 ①~⑤ 선지 5개를 분리한다. 형식이 원문자 5개를
    순서대로 갖추지 못했으면(서술형 등) 선지 없이 (전체 텍스트, [])를 돌려준다."""
    positions = []
    for mk in _OPTION_MARKERS:
        idx = problem_text.find(mk)
        if idx == -1:
            return problem_text.strip(), []
        positions.append(idx)
    if positions != sorted(positions):
        return problem_text.strip(), []
    stem = problem_text[:positions[0]].strip()
    stem = PROBLEM_NUM_RE.sub("", stem, count=1)
    options = []
    for i in range(5):
        start = positions[i]
        end = positions[i + 1] if i + 1 < 5 else len(problem_text)
        options.append(problem_text[start:end].strip())
    return stem, options


def _extract_option_number(answer_text: str) -> int:
    """정답표의 '③' 또는 '3번' 같은 표기에서 1~5 사이 정답 번호를 뽑는다."""
    for i, ch in enumerate(_OPTION_MARKERS):
        if ch in (answer_text or ""):
            return i + 1
    m = re.search(r"[1-5]", answer_text or "")
    return int(m.group(0)) if m else 0


def _evidence_excerpt(passage: str, quote: str, radius: int = 60):
    """근거 문장이 지문 안에서 실제로 발견되면 그 앞뒤 맥락을 살짝 포함한 짧은 발췌문과,
    그 발췌문 안에서 근거 문장이 시작·끝나는 글자 위치를 돌려준다. 못 찾으면(AI가 지문에
    없는 문장을 만들어낸 경우 등) 지문 앞부분만 강조 없이 보여준다."""
    quote = (quote or "").strip()
    idx = passage.find(quote) if quote else -1
    if idx == -1:
        return passage[:200].strip(), None
    start = max(0, idx - radius)
    end = min(len(passage), idx + len(quote) + radius)
    excerpt = passage[start:end].strip()
    rel_idx = excerpt.find(quote)
    return excerpt, (rel_idx, rel_idx + len(quote)) if rel_idx != -1 else None


async def analyze_question_for_video(preamble: str, problem_text: str, explanation_text: str) -> dict:
    """문항 하나를 영상으로 만들기 위해, AI에게 (1) 지문에서 그대로 가져온 근거 문장,
    (2) 오답 선지별 짧은 이유, (3) 구어체 내레이션 대본을 뽑아달라고 요청한다.
    실패하면 빈 값을 돌려주고, 호출부에서 안전하게 대체한다."""
    prompt = f"""아래는 지문형 문제 하나와 그 해설입니다. 이 문제를 설명하는 영상 자료를 만들기 위한 정보를 추출해줘.

[규칙]
- evidence_quote: 정답의 근거가 되는 부분을 아래 [지문]에서 한 글자도 바꾸지 말고 문장부호까지 정확히 그대로 옮겨줘. 통째로 길게 옮기지 말고, 핵심 문장 하나(또는 이어지는 두 문장) 정도로 짧게.
- wrong_reasons: 정답이 아닌 선택지 번호(1~5 중 정답 제외)마다, 왜 틀렸는지 12자 안팎으로 아주 짧게. 정답 선택지 번호는 넣지 마세요.
- narration: 학생에게 소리 내어 설명하듯 자연스러운 구어체 문장 4~6개로, 지문 근거 설명 → 정답인 이유 → 오답인 이유 순서로 짧게짧게 나눠줘. 한 문장은 20~50자 정도로.
- 다른 설명 없이 아래 형식의 JSON 객체 하나만 출력해: {{"evidence_quote": "...", "wrong_reasons": {{"1": "...", "2": "..."}}, "narration": ["...", "..."]}}

[지문]
{preamble}

[문제와 선택지]
{problem_text}

[해설]
{explanation_text}"""
    try:
        model = get_best_model()
        resp = await asyncio.to_thread(model.generate_content, prompt)
        raw = (resp.text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        return {
            "evidence_quote": str(data.get("evidence_quote", "")).strip(),
            "wrong_reasons": {str(k): str(v).strip() for k, v in (data.get("wrong_reasons") or {}).items()},
            "narration": [str(s).strip() for s in (data.get("narration") or []) if str(s).strip()],
        }
    except Exception:
        return {"evidence_quote": "", "wrong_reasons": {}, "narration": []}


def render_question_video(question_no: int, preamble: str, problem_text: str,
                           explanation_text: str, answer_text: str, analysis: dict) -> bytes:
    """블로킹 작업이므로 asyncio.to_thread로 감싸서 호출한다.
    인트로 → 문항 안내 → 지문 근거(하이라이트) → 선택지 분석, 4개 장면으로 구성된다."""
    stem, options = _split_question_options(problem_text)
    correct_idx = _extract_option_number(answer_text)
    excerpt, span = _evidence_excerpt(preamble, analysis.get("evidence_quote", ""))
    narration = analysis.get("narration") or _fallback_split_scenes(explanation_text or problem_text)
    wrong_reasons = analysis.get("wrong_reasons", {})
    half = max(1, len(narration) // 2) if narration else 0
    passage_narr = " ".join(narration[:half]) or "지문에서 근거를 먼저 확인해봅시다."
    options_narr = " ".join(narration[half:]) or "선택지를 하나씩 살펴보겠습니다."

    with tempfile.TemporaryDirectory(prefix="explain_video_") as workdir:
        clip_paths = []

        def add_clip(narr_text: str, slide_path: str):
            i = len(clip_paths)
            mp3_path = os.path.join(workdir, f"audio_{i}.mp3")
            clip_path = os.path.join(workdir, f"clip_{i}.mp4")
            gTTS(narr_text, lang="ko").save(mp3_path)
            _video_make_scene_clip(slide_path, mp3_path, clip_path)
            clip_paths.append(clip_path)

        intro_path = os.path.join(workdir, "intro.png")
        _video_make_intro_slide(intro_path)
        add_clip("안녕하세요. 로지에듀 최준용 국어입니다.", intro_path)

        title_path = os.path.join(workdir, "title.png")
        _video_make_slide(f"{question_no}번 문항 해설", title_path)
        add_clip(f"{question_no}번 문항 해설입니다.", title_path)

        passage_path = os.path.join(workdir, "passage.png")
        _video_make_passage_slide(excerpt, span, passage_path)
        add_clip(passage_narr, passage_path)

        options_path = os.path.join(workdir, "options.png")
        _video_make_options_slide(stem, options, correct_idx, wrong_reasons, options_path)
        add_clip(options_narr, options_path)

        final_path = os.path.join(workdir, "final.mp4")
        _video_concat_clips(clip_paths, final_path, workdir)
        with open(final_path, "rb") as f:
            return f.read()


def _video_run_ffmpeg(args: list):
    r = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "").strip()[-1500:] or "ffmpeg 처리 중 알 수 없는 오류")


def _video_make_scene_clip(image_path: str, audio_path: str, out_path: str):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    _video_run_ffmpeg([
        ffmpeg, "-y", "-loop", "1", "-i", image_path, "-i", audio_path,
        "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p", "-shortest", "-vf", f"scale={VIDEO_W}:{VIDEO_H}",
        out_path,
    ])


def _video_concat_clips(clip_paths: list, out_path: str, workdir: str):
    list_path = os.path.join(workdir, "concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    _video_run_ffmpeg([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path])


def render_explain_video(scenes: list) -> bytes:
    """블로킹 작업(TTS 네트워크 호출 + ffmpeg 렌더링)이므로 asyncio.to_thread로 감싸서 호출한다."""
    with tempfile.TemporaryDirectory(prefix="explain_video_") as workdir:
        clip_paths = []
        for i, scene_text in enumerate(scenes):
            img_path = os.path.join(workdir, f"slide_{i}.png")
            mp3_path = os.path.join(workdir, f"audio_{i}.mp3")
            clip_path = os.path.join(workdir, f"clip_{i}.mp4")
            _video_make_slide(scene_text, img_path)
            gTTS(scene_text, lang="ko").save(mp3_path)
            _video_make_scene_clip(img_path, mp3_path, clip_path)
            clip_paths.append(clip_path)
        final_path = os.path.join(workdir, "final.mp4")
        _video_concat_clips(clip_paths, final_path, workdir)
        with open(final_path, "rb") as f:
            return f.read()


def _fallback_split_scenes(text: str) -> list:
    """AI 장면 분리가 실패했을 때 쓰는 안전망 — 문장 부호 기준으로 기계적으로 쪼갠다."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。])\s+", text) if s.strip()]
    scenes, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) > 70:
            scenes.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        scenes.append(cur)
    return scenes[:VIDEO_MAX_SCENES] or [text[:200]]


async def split_video_scenes(text: str) -> list:
    """해설 텍스트를 AI가 짧은 구어체 장면들로 나눈다. 실패하면 기계적 분리로 대체한다."""
    prompt = f"""아래 해설/설명 글을 학생들이 짧은 세로형 영상(쇼츠)으로 보기 좋게, 성우가 소리 내어 읽을 자연스러운 구어체 대사로 나눠줘.

[규칙]
- 원문의 내용과 의미를 절대 바꾸지 말고, 말하듯이 자연스러운 문장으로 다듬어서 전달해.
- 한 장면은 대략 20~60자 정도로, 소리 내어 읽었을 때 4~8초 안팎이 되도록 짧게 끊어줘.
- 전체 장면 수는 {VIDEO_MAX_SCENES}개를 넘기지 마세요.
- 마크다운이나 *, #, <, > 같은 기호 없이 순수한 문장으로만 작성해.
- 다른 설명 없이, 장면 순서대로 문자열만 담은 JSON 배열로만 출력해. 예: ["첫 번째 장면입니다.", "두 번째 장면입니다."]

[원문]
{text}"""
    try:
        model = get_best_model()
        resp = await asyncio.to_thread(model.generate_content, prompt)
        raw = (resp.text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
        scenes = json.loads(raw.strip())
        scenes = [str(s).strip() for s in scenes if str(s).strip()]
        if scenes:
            return scenes[:VIDEO_MAX_SCENES]
    except Exception:
        pass
    return _fallback_split_scenes(text)


@app.post("/api/admin/ai_status")
async def ai_status(name: str = Depends(current_admin_name)):
    """AI가 지금 쓸 수 있는 상태인지 아주 짧은 호출 한 번으로 확인한다.

    💡 크레딧이 떨어진 줄 모르고 30분짜리 출제를 맡겼다가 뒤늦게 실패를 보는 일이
       있었다. 시작하기 전에 1초 만에 확인할 수 있게 한다. 호출 비용이 들므로
       원장님 계정만 쓸 수 있고, 답도 한 글자만 받도록 최소로 요청한다."""
    me = await asyncio.to_thread(get_admin_doc, name)
    if not me or not me.get("is_owner"):
        return {"success": False, "detail": "이 기능은 원장님 계정만 사용할 수 있습니다."}

    try:
        model_name = get_best_model().model_name
    except Exception:
        model_name = ""

    try:
        resp = await asyncio.to_thread(safe_generate, "1+1은? 숫자만 답해.")
        reply = (getattr(resp, "text", "") or "").strip()
        return {
            "success": True,
            "ok": True,
            "model": model_name,
            "reply": reply[:40],
            "message": "AI가 정상 동작합니다. 출제·해설 영상·채점 모두 바로 쓰실 수 있습니다.",
        }
    except Exception as e:
        return {
            "success": True,
            "ok": False,
            "model": model_name,
            "message": friendly_ai_error(e),
        }


def parse_manual_script(script: str, question_no: int) -> dict:
    """원장님이 손수 고친 대본(JSON)을 읽어들인다.
    💡 이 길로 들어오면 AI를 한 번도 부르지 않으므로 사용료가 들지 않는다.
       형식이 어긋나면 빈 값을 돌려주고, 호출부에서 AI 쪽으로 넘긴다."""
    raw = (script or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    if question_no > 0:
        narration = [str(x).strip() for x in (data.get("narration") or []) if str(x).strip()]
        reasons = {}
        for k, v in (data.get("wrong_reasons") or {}).items():
            txt = str(v).strip()
            if txt:
                reasons[str(k)] = txt[:40]
        out = {
            "evidence_quote": str(data.get("evidence_quote", "")).strip(),
            "wrong_reasons": reasons,
            "narration": narration[:VIDEO_MAX_SCENES],
        }
        # 하나라도 채워져 있어야 손수 만든 대본으로 인정한다
        return out if (out["evidence_quote"] or out["wrong_reasons"] or out["narration"]) else {}

    scenes = [str(x).strip() for x in (data.get("scenes") or []) if str(x).strip()]
    return {"scenes": scenes[:VIDEO_MAX_SCENES]} if scenes else {}


@app.post("/api/admin/video_draft")
async def video_draft(text: str = Form(...), question_no: int = Form(0),
                      name: str = Depends(current_admin_name)):
    """영상 대본 초안을 AI 없이 만들어 돌려준다.
    💡 원장님이 이 초안을 고쳐서 그대로 영상으로 만들면 AI 사용료가 한 푼도 들지 않는다.
       문장 부호를 기준으로 기계적으로 나누기만 하므로 공짜다."""
    me = await asyncio.to_thread(get_admin_doc, name)
    if not me or not me.get("is_owner"):
        return {"success": False, "detail": "이 기능은 원장님 계정만 사용할 수 있습니다."}
    source_text = (text or "").strip()
    if not source_text:
        return {"success": False, "detail": "영상으로 만들 설명 내용을 입력해주세요."}

    if question_no > 0:
        parsed = parse_question_bank_content(source_text)
        problem_text = parsed["problems"].get(question_no)
        if not problem_text:
            return {"success": False, "detail": f"{question_no}번 문항을 찾지 못했습니다. 문항 번호와 내용을 확인해주세요."}
        explanation_text = parsed["explanations"].get(question_no, "")
        answer_text = parsed["answers"].get(question_no, "")
        stem, options = _split_question_options(problem_text)
        correct = _extract_option_number(answer_text)
        return {
            "success": True,
            "question_no": question_no,
            "stem": stem,
            "options": options,
            "correct": correct,
            "preamble": parsed["preamble"][:4000],
            "evidence_quote": "",
            "wrong_reasons": {str(n): "" for n in range(1, len(options) + 1) if n != correct},
            "narration": _fallback_split_scenes(explanation_text or problem_text),
        }

    return {"success": True, "scenes": _fallback_split_scenes(source_text)}


@app.post("/api/admin/generate_video")
async def generate_video(text: str = Form(...), title: str = Form(""), question_no: int = Form(0),
                          script: str = Form(""),
                          name: str = Depends(current_admin_name)):
    # 💡 해설 영상 자동 생성은 서버 비용(AI 호출 + TTS + 렌더링)이 크게 드는 기능이라,
    # 다른 관리자 계정이 아니라 원장님(is_owner)만 쓸 수 있도록 제한한다.
    me = get_admin_doc(name)
    if not me or not me.get("is_owner"):
        return {"success": False, "detail": "이 기능은 원장님 계정만 사용할 수 있습니다."}
    source_text = text.strip()
    if not source_text:
        return {"success": False, "detail": "영상으로 만들 설명 내용을 입력해주세요."}

    if question_no > 0:
        # 💡 문항별 모드: 단순 자막이 아니라, 지문에서 근거가 되는 부분을 실제로
        # 강조해서 보여주고 선택지별로 정답/오답 이유까지 화면에 함께 띄운다.
        parsed = parse_question_bank_content(source_text)
        problem_text = parsed["problems"].get(question_no)
        if not problem_text:
            return {"success": False, "detail": f"{question_no}번 문항을 찾지 못했습니다. 문항 번호와 내용을 확인해주세요."}
        preamble = parsed["preamble"]
        explanation_text = parsed["explanations"].get(question_no, "")
        answer_text = parsed["answers"].get(question_no, "")
        # 💡 손수 고친 대본이 넘어왔으면 AI를 부르지 않는다 (사용료 0원).
        analysis = parse_manual_script(script, question_no)
        used_ai = not analysis
        if used_ai:
            analysis = await analyze_question_for_video(preamble, problem_text, explanation_text)
        try:
            video_bytes = await asyncio.to_thread(
                render_question_video, question_no, preamble, problem_text, explanation_text, answer_text, analysis,
            )
        except Exception as e:
            return {"success": False, "detail": f"영상 생성에 실패했습니다: {e}"}
        scene_count = 4
        safe_title = (title.strip() or f"{question_no}번 문항 해설영상")[:60]
    else:
        manual = parse_manual_script(script, 0)
        used_ai = not manual
        scenes = manual.get("scenes") if manual else await split_video_scenes(source_text)
        if not scenes:
            return {"success": False, "detail": "장면을 나누지 못했습니다. 내용을 조금 더 자세히 입력해주세요."}
        try:
            video_bytes = await asyncio.to_thread(render_explain_video, scenes)
        except Exception as e:
            return {"success": False, "detail": f"영상 생성에 실패했습니다: {e}"}
        scene_count = len(scenes)
        safe_title = (title.strip() or "해설영상")[:60]

    url = save_bytes(video_bytes, f"{safe_title}.mp4", "explain_videos", "video/mp4")

    doc_id = uuid.uuid4().hex
    if db is not None:
        await asyncio.to_thread(lambda: db.collection("explain_videos").document(doc_id).set({
            "title": safe_title, "url": url, "scene_count": scene_count, "question_no": question_no,
            "used_ai": used_ai,
            "source_text": source_text[:2000],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }))
    return {"success": True, "id": doc_id, "title": safe_title, "url": url,
            "scene_count": scene_count, "used_ai": used_ai}


UNSURE_REPORT_MAX_ROWS = 400      # 한 번에 훑어볼 제출 기록 수


# ─────────────────────────────────────────────────────────
# 원장님이 학생 대신 채점하기
#   💡 학생이 직접 낸 것과 기록이 똑같아야 한다. 그래서 채점 로직을 새로 짜지 않고
#      학생용 제출 함수를 그대로 부른다. 점수·오답·모름·경험치·알림까지 전부 같은 길.
# ─────────────────────────────────────────────────────────
GRADE_KINDS = {
    "homework": ("과제 제출", "과제"),
    "exam": ("모의고사", "모의고사"),
    "quiz": ("타임어택 퀴즈", "타임어택 퀴즈"),
    "vocab": ("영어 단어 시험", "영어 단어 시험"),
    "bank": ("출제 문제", "출제한 문제"),
}


def student_profile_for_grading(name: str) -> dict:
    """학생 명단에서 학교·학년을 가져온다. 제출 기록에 그대로 들어가는 값이라
    화면에서 입력받지 않고 명단을 그대로 따른다."""
    if db is None:
        return {}
    doc = db.collection("students").document(sanitize_doc_id(name)).get()
    if not doc.exists:
        doc = db.collection("students").document(name).get()
    return doc.to_dict() or {} if doc.exists else {}


def drop_previous_report(name: str, title: str, kind_label: str) -> int:
    """다시 채점할 수 있도록 예전 제출 기록을 지운다. 지운 개수를 돌려준다."""
    if db is None:
        return 0
    rows = list(db.collection("reports")
                .where("student_name", "==", name)
                .where("task_name", "==", title)
                .where("type", "==", kind_label)
                .limit(20).stream())
    for r in rows:
        db.collection("reports").document(r.id).delete()
    return len(rows)


def grade_question_bank(name: str, profile: dict, title: str, content: str, answers: list) -> dict:
    """출제한 문제(보관함)를 채점한다. 학생용 제출 경로가 따로 없는 유일한 종류라
    여기서 채점하되, 남기는 기록의 모양은 과제·시험과 똑같이 맞춘다."""
    parsed = parse_question_bank_content(content or "")
    nums = sorted(parsed["answers"].keys())
    if not nums:
        return {"success": False, "detail": "이 자료에서 정답표를 찾지 못했습니다."}

    key = []
    for i in range(1, max(nums) + 1):
        a = _extract_option_number(parsed["answers"].get(i, ""))
        key.append(str(a) if a else "")

    mine = parse_answer_slots(answers or [])
    wrongs, unsure, correct, scored = [], [], 0, 0
    for i, ans in enumerate(key):
        if not ans:                      # 정답을 못 읽은 문항은 채점에서 뺀다
            continue
        scored += 1
        got = mine[i] if i < len(mine) else ""
        if got == UNSURE_MARK:
            unsure.append(i + 1)
            wrongs.append(i + 1)
        elif got and got == ans:
            correct += 1
        else:
            wrongs.append(i + 1)

    percent = round(correct / scored * 100) if scored else 0
    db.collection("reports").add({
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "student_name": name,
        "school": profile.get("school", ""),
        "grade": profile.get("grade", ""),
        "task_name": title,
        "type": "출제 문제",
        "score": f"{correct}/{scored}",
        "percent": percent,
        "wrongs": wrongs,
        "unsure": unsure,
        "question_count": scored,
        "correct_count": correct,
    })
    return {"success": True, "correct": correct, "total": scored, "score": percent,
            "wrongs": wrongs, "unsure": unsure, "answers": key}


class GradeForStudentReq(BaseModel):
    kind: str                  # homework | exam | quiz | vocab | bank
    title: str
    student_name: str
    answers: list = []
    content: str = ""          # kind=bank 일 때 문제 자료 본문
    overwrite: bool = True     # 이미 낸 기록이 있으면 지우고 다시 채점


@app.post("/api/admin/grade_for_student", dependencies=[Depends(verify_admin)])
async def grade_for_student(req: GradeForStudentReq):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}

    kind = (req.kind or "").strip()
    if kind not in GRADE_KINDS:
        return {"success": False, "detail": "채점할 종류를 고르지 못했습니다."}
    name = (req.student_name or "").strip()
    title = (req.title or "").strip()
    if not name or not title:
        return {"success": False, "detail": "학생과 채점할 항목을 골라주세요."}

    profile = await asyncio.to_thread(student_profile_for_grading, name)
    if not profile:
        return {"success": False, "detail": f"'{name}' 학생을 명단에서 찾지 못했습니다."}

    kind_label = GRADE_KINDS[kind][0]
    replaced = 0
    if req.overwrite:
        replaced = await asyncio.to_thread(drop_previous_report, name, title, kind_label)

    payload = {
        "school": profile.get("school", ""),
        "grade": profile.get("grade", ""),
        "student_name": name,
        "title": title,
        "answers": list(req.answers or []),
    }

    # 💡 학생용 제출 함수를 그대로 부른다 — 기록·경험치·알림이 전부 같은 길로 간다.
    if kind == "homework":
        res = await submit_homework_omr(HomeworkOmrReq(**payload))
    elif kind == "exam":
        res = await submit_exam(ExamSubmitRequest(**payload))
    elif kind == "quiz":
        res = await submit_quiz(QuizSubmitReq(**payload))
    elif kind == "vocab":
        res = await submit_vocab_test(VocabTestSubmitReq(**payload))
    else:
        res = await asyncio.to_thread(
            grade_question_bank, name, profile, title, req.content, list(req.answers or []))

    if isinstance(res, dict):
        res = dict(res)
        res["graded_by_admin"] = True
        res["replaced"] = replaced
        res["kind_label"] = kind_label
    return res


@app.get("/api/admin/unsure_report", dependencies=[Depends(verify_admin)])
def unsure_report(student_name: str = "", subject: str = "", limit: int = 60):
    """학생들이 '모르겠다'고 눌러둔 문항을 모아 준다.

    💡 찍어서 맞힌 문항은 점수에 묻혀 보이지 않는다. 학생이 스스로 모른다고 표시한
       것만 따로 모으면, 무엇을 다시 가르쳐야 할지가 그대로 드러난다.
       · 학생 이름을 주면 그 학생이 모른다고 한 문항을 과제·시험별로 묶어 준다.
       · 이름을 주지 않으면 여러 학생이 함께 모른 문항(다시 다뤄야 할 것)을 추려 준다.
    """
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}

    name = (student_name or "").strip()
    want_subject = normalize_subject(subject) if subject else ""

    try:
        rows = [r.to_dict() for r in db.collection("reports")
                .order_by("submitted_at", direction=firestore.Query.DESCENDING)
                .limit(UNSURE_REPORT_MAX_ROWS).stream()]
    except Exception as e:
        print("모름 모아보기 실패:", e)
        return {"success": False, "detail": "기록을 불러오지 못했습니다."}

    expl_cache = {}

    def expl_of(kind, title):
        key = (kind, title)
        if key not in expl_cache:
            expl_cache[key] = explanations_for(kind, title)
        return expl_cache[key]

    # ── 한 학생만 보는 경우 ──────────────────────────────
    if name:
        tasks, total = [], 0
        for r in rows:
            if str(r.get("student_name", "")).strip() != name:
                continue
            unsure = [int(u) for u in (r.get("unsure") or []) if _num(u) is not None]
            if not unsure:
                continue
            kind = r.get("type", "")
            title = r.get("task_name", "")
            expl = expl_of(kind, title)
            items = [{"no": no, "explanation": expl.get(str(no), "")} for no in sorted(unsure)]
            total += len(items)
            tasks.append({
                "title": title, "type": kind,
                "submitted_at": r.get("submitted_at", ""),
                "score": r.get("score", ""),
                "count": len(items), "items": items,
            })
            if len(tasks) >= max(1, min(100, limit)):
                break
        return {"success": True, "mode": "student", "student": name,
                "tasks": tasks, "task_count": len(tasks), "total": total}

    # ── 전체를 보는 경우: 누가 몇 개인지 + 함께 모른 문항 ──
    per_student, spots = {}, {}
    for r in rows:
        unsure = [int(u) for u in (r.get("unsure") or []) if _num(u) is not None]
        if not unsure:
            continue
        who = str(r.get("student_name", "")).strip() or "(이름 없음)"
        kind = r.get("type", "")
        title = r.get("task_name", "")
        if want_subject and normalize_subject(r.get("subject", "korean")) != want_subject:
            continue
        per_student[who] = per_student.get(who, 0) + len(unsure)
        for no in unsure:
            key = (kind, title, no)
            spot = spots.setdefault(key, {"type": kind, "title": title, "no": no, "students": []})
            if who not in spot["students"]:
                spot["students"].append(who)

    students = [{"name": k, "count": v} for k, v in per_student.items()]
    students.sort(key=lambda x: (-x["count"], x["name"]))

    hot = []
    for (kind, title, no), spot in spots.items():
        if len(spot["students"]) < 2:      # 여러 학생이 함께 모른 것만 추린다
            continue
        hot.append({
            "type": kind, "title": title, "no": no,
            "count": len(spot["students"]),
            "students": sorted(spot["students"])[:12],
            "explanation": expl_of(kind, title).get(str(no), ""),
        })
    hot.sort(key=lambda x: (-x["count"], x["title"], x["no"]))

    return {"success": True, "mode": "all",
            "students": students[:max(1, min(200, limit))],
            "hotspots": hot[:40],
            "student_count": len(students), "hotspot_count": len(hot)}


@app.get("/api/admin/explain_videos")
def get_explain_videos(name: str = Depends(current_admin_name)):
    me = get_admin_doc(name)
    if not me or not me.get("is_owner"):
        return {"success": False, "detail": "이 기능은 원장님 계정만 사용할 수 있습니다.", "videos": []}
    if db is None:
        return {"success": False, "videos": []}
    docs = db.collection("explain_videos").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "videos": [{"id": d.id, **d.to_dict()} for d in docs]}


@app.delete("/api/admin/explain_video/{video_id}")
async def delete_explain_video(video_id: str, name: str = Depends(current_admin_name)):
    me = get_admin_doc(name)
    if not me or not me.get("is_owner"):
        return {"success": False, "detail": "이 기능은 원장님 계정만 사용할 수 있습니다."}
    if db is None:
        return {"success": False}
    await asyncio.to_thread(lambda: db.collection("explain_videos").document(video_id).delete())
    return {"success": True}


# ─────────────────────────────────────────────────────────
# 관리자 - 숙제 및 기타
# ─────────────────────────────────────────────────────────
@app.get("/api/homeworks")
def get_homeworks():
    if db is None:
        return {"success": False, "homeworks": []}
    return {"success": True, "homeworks": [{"id": d.id, **d.to_dict()} for d in db.collection("homeworks").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}


# 과제는 수업에서 내주는 것과 클리닉(보충)에서 내주는 것이 쓰임이 다르다.
HOMEWORK_KINDS = {"class": "수업 과제", "clinic": "클리닉 과제"}


def normalize_homework_kind(v) -> str:
    t = str(v or "").strip().lower()
    if t in ("clinic", "클리닉", "클리닉 과제"):
        return "clinic"
    return "class"


UNSURE_MARK = "?"      # 학생이 '모름'을 고른 문항


def parse_answer_slots(raw) -> list:
    """학생이 낸 답안을 '문항 순서 그대로' 읽는다.

    💡 정답표를 읽는 parse_answer_list 는 빈 칸을 버린다("1,,3" -> ["1","3"]).
       정답표에는 그게 맞지만 학생 답안에 쓰면 큰일 난다 — 한 문항만 비워도
       그 뒤 답이 전부 한 칸씩 밀려 엉뚱하게 채점된다. 그래서 자리를 지키는
       해석기를 따로 둔다. 빈 칸은 빈 칸으로, '모름'은 '?'로 남긴다."""
    if isinstance(raw, list):
        items = list(raw)
    else:
        text = str(raw or "").strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            items = parsed if isinstance(parsed, list) else re.split(r"[\n,]", text)
        except (ValueError, TypeError):
            items = re.split(r"[\n,]", text)

    circled = "①②③④⑤"
    out = []
    for it in items:
        v = str(it if it is not None else "").strip()
        if v in ("?", "모름", "몰라요", "잘 모르겠음", "잘모르겠음"):
            out.append(UNSURE_MARK)
            continue
        for i, ch in enumerate(circled):      # ③ -> 3
            v = v.replace(ch, str(i + 1))
        out.append(v[:20])                    # 빈 칸은 빈 칸 그대로 둔다
    return out


def parse_answer_list(raw) -> list:
    """정답표를 목록으로 만든다. '①②③' / '1,2,3' / 줄바꿈 — 어떻게 적어도 받는다."""
    if isinstance(raw, list):
        items = [str(x).strip() for x in raw]
    else:
        text = str(raw or "").strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = [str(x).strip() for x in parsed]
            else:
                raise ValueError
        except (ValueError, TypeError):
            # 줄바꿈/쉼표로 나누되, '1번 ③' 처럼 번호가 앞에 붙어 있으면 뒷부분만 쓴다
            items = []
            for line in re.split(r"[\n,]", text):
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"^\s*\d{1,3}\s*(?:번|[.)])\s*(.+)$", line)
                items.append((m.group(1) if m else line).strip())
    circled = "①②③④⑤"
    out = []
    for it in items:
        it = (it or "").strip()
        if not it:
            continue
        # 💡 '①②③'처럼 한 줄에 원문자만 죽 붙여 적는 경우가 많다 — 한 글자씩 갈라 받는다.
        if len(it) > 1 and all(ch in circled for ch in it.replace(" ", "")):
            out += [str(circled.index(ch) + 1) for ch in it if ch in circled]
            continue
        # '3 1 5'처럼 한 자리 숫자만 띄어 적은 경우도 갈라 받는다
        parts = it.split()
        if len(parts) > 1 and all(p in "12345" and len(p) == 1 for p in parts):
            out += parts
            continue
        for i, ch in enumerate(circled):      # ③ → 3
            it = it.replace(ch, str(i + 1))
        out.append(it.strip()[:20])
    return out


@app.post("/api/admin/extract_from_bank")
async def extract_from_bank(content: str = Form(...), _: bool = Depends(verify_admin)):
    """출제 탭에서 만든 문제 자료에서 문항별 정답과 해설을 그대로 꺼낸다.

    💡 출제본에는 이미 [정답 및 해설]과 [정답표]가 들어 있다. AI를 다시 부를 이유가
       없으므로 글을 읽어 가르기만 한다 — 사용료 0원."""
    text = (content or "").strip()
    if not text:
        return {"success": False, "detail": "문제 내용을 넣어주세요."}

    parsed = parse_question_bank_content(text)
    nums = sorted(set(list(parsed["problems"].keys()) + list(parsed["answers"].keys())))
    if not nums:
        return {"success": False, "detail": "문항을 찾지 못했습니다. 출제 탭에서 만든 자료인지 확인해주세요."}

    answers, explanations = {}, {}
    for n in nums:
        a = _extract_option_number(parsed["answers"].get(n, ""))
        if a:
            answers[str(n)] = int(a)
        expl = str(parsed["explanations"].get(n, "") or "").strip()
        if expl:
            explanations[str(n)] = expl[:EXPLANATION_MAX_CHARS]

    # OMR 채점에 쓰는 순서대로 늘어놓은 목록도 함께 준다 (빈 칸은 그대로 비워 둠)
    last = max(nums)
    answer_list = [answers.get(str(i), "") for i in range(1, last + 1)]

    return {
        "success": True,
        "question_count": len(nums),
        "answers": answers,
        "answer_list": answer_list,
        "explanations": explanations,
        "explanation_count": len(explanations),
    }


@app.post("/api/admin/homework")
async def create_homework(
    title: str = Form(...),
    desc: str = Form(""),
    answer_text: str = Form(""),
    kind: str = Form("class"),
    answers: str = Form(""),
    explanations: str = Form(""),
    answer_file: Optional[UploadFile] = File(None),
    _: bool = Depends(verify_admin),
):
    if db is None:
        return {"success": False}
    ans_url = ""
    if answer_file and answer_file.filename:
        ans_url = await asyncio.to_thread(save_bytes, await answer_file.read(), answer_file.filename, "homeworks", answer_file.content_type)

    answer_list = parse_answer_list(answers)
    safe_title = sanitize_doc_id(title)
    await asyncio.to_thread(
        lambda: db.collection("homeworks").document(safe_title).set(
            {
                "title": title,
                "desc": desc,
                "kind": normalize_homework_kind(kind),
                "answer_text": answer_text,
                "answer_file": ans_url,
                # 정답을 넣어두면 학생이 OMR로 답만 마킹해도 그 자리에서 채점된다
                "answers": answer_list,
                # 문항별 해설 — 학생이 채점 결과에서 번호를 눌러 바로 볼 수 있다
                "explanations": parse_explanation_map(explanations),
                "question_count": len(answer_list),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    )
    return {"success": True, "question_count": len(answer_list),
            "explanation_count": len(parse_explanation_map(explanations))}


class HomeworkFileDeleteReq(BaseModel):
    title: str


@app.post("/api/admin/homework/file/delete", dependencies=[Depends(verify_admin)])
def delete_homework_file(req: HomeworkFileDeleteReq):
    """과제에 붙여둔 해답 파일만 떼어낸다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    ref = db.collection("homeworks").document(sanitize_doc_id(req.title))
    doc = ref.get()
    if not doc.exists:
        return {"success": False, "detail": "그런 과제가 없습니다."}
    if not (doc.to_dict() or {}).get("answer_file"):
        return {"success": False, "detail": "붙어 있는 파일이 없습니다."}
    ref.set({"answer_file": ""}, merge=True)
    return {"success": True}


class HomeworkOmrReq(BaseModel):
    school: str = ""
    grade: str = ""
    student_name: str
    title: str
    answers: list = []


@app.post("/api/homework/omr_submit")
async def submit_homework_omr(req: HomeworkOmrReq):
    """수업·클리닉 과제를 OMR로 제출하면 그 자리에서 채점한다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.student_name.strip()
    if not name:
        return {"success": False, "detail": "학생 정보가 없습니다."}

    doc = await asyncio.to_thread(lambda: db.collection("homeworks").document(sanitize_doc_id(req.title)).get())
    if not doc.exists:
        return {"success": False, "detail": "그런 과제가 없습니다."}
    data = doc.to_dict() or {}
    key = parse_answer_list(data.get("answers") or [])
    if not key:
        return {"success": False, "detail": "이 과제에는 정답이 등록되어 있지 않아 자동 채점을 할 수 없습니다. 선생님께 알려주세요."}

    existing = await asyncio.to_thread(
        lambda: list(
            db.collection("reports")
            .where("student_name", "==", name)
            .where("task_name", "==", req.title)
            .where("type", "==", "과제 제출")
            .limit(1)
            .stream()
        )
    )
    if existing:
        return {"success": False, "detail": "이미 제출한 과제입니다."}

    # 💡 학생 답안은 자리(문항 번호)가 생명이라 parse_answer_slots 로 읽는다.
    #    예전에는 parse_answer_list 를 써서, 한 문항만 비워도 그 뒤가 전부 밀려
    #    엉뚱하게 채점됐다.
    mine = parse_answer_slots(req.answers or [])
    wrongs, unsure, correct = [], [], 0
    for i, ans in enumerate(key):
        got = mine[i] if i < len(mine) else ""
        if got == UNSURE_MARK:
            unsure.append(i + 1)
            wrongs.append(i + 1)
        elif got and got == ans:
            correct += 1
        else:
            wrongs.append(i + 1)

    total = len(key)
    score = round(correct / total * 100) if total else 0
    kind_label = HOMEWORK_KINDS.get(normalize_homework_kind(data.get("kind")), "수업 과제")
    await asyncio.to_thread(
        lambda: db.collection("reports").add({
            "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "student_name": name, "school": req.school, "grade": req.grade,
            "task_name": req.title, "type": "과제 제출",
            "homework_kind": data.get("kind", "class"),
            "score": f"{correct}/{total}",
            "percent": score, "wrongs": wrongs,
            # 찍어서 맞힌 것과 진짜 아는 것을 구분하려면 '모름'을 따로 남겨야 한다
            "unsure": unsure,
        })
    )
    send_telegram_message(f"📘 [{kind_label}]\n{name} 학생이 '{req.title}'을(를) 제출했습니다. ({correct}/{total})")
    # 💡 채점 직후가 가장 잘 기억나는 때다. 번호를 눌러 바로 해설을 볼 수 있게 함께 보낸다.
    return {"success": True, "correct": correct, "total": total, "score": score,
            "wrongs": wrongs, "unsure": unsure, "mine": mine,
            "answers": key, "kind": data.get("kind", "class"),
            "explanations": parse_explanation_map(data.get("explanations"))}


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
def get_knowledge(subject: str = "korean"):
    if db is None: return {"success": False, "knowledge": []}
    subject = normalize_subject(subject)
    rows = [{"id": d.id, **d.to_dict()} for d in db.collection("knowledge").stream()]
    rows = [r for r in rows if normalize_subject(r.get("subject")) == subject]
    rows.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return {"success": True, "knowledge": rows}


@app.get("/api/subjects")
def get_subjects():
    """국어/수학/영어 등 지금 운영 중인 과목 목록 — 화면에서 탭을 만들 때 쓴다."""
    return {"success": True, "subjects": [{"key": k, **v} for k, v in SUBJECTS.items()]}


@app.get("/api/admin/ai_guidelines", dependencies=[Depends(verify_admin)])
def get_ai_guidelines_admin(subject: str = "korean"):
    return {"success": True, "text": get_ai_guidelines(subject)}


class AIGuidelinesRequest(BaseModel):
    text: str
    subject: str = "korean"


@app.post("/api/admin/ai_guidelines", dependencies=[Depends(verify_admin)])
async def save_ai_guidelines(req: AIGuidelinesRequest):
    if db is None:
        return {"success": False}
    subject = normalize_subject(req.subject)
    await asyncio.to_thread(lambda: db.collection("settings").document(f"ai_guidelines_{subject}").set({"text": req.text.strip()}))
    return {"success": True}

@app.post("/api/admin/knowledge", dependencies=[Depends(verify_admin)])
async def add_knowledge_admin(title: str = Form(...), content: str = Form(""), subject: str = Form("korean"), files: Optional[List[UploadFile]] = File(None)):
    if db is None: return {"success": False}
    subject = normalize_subject(subject)
    final_content = content
    if files:
        for file in files:
            if file.filename:
                try:
                    res = await asyncio.to_thread(safe_generate, ["이 문서의 핵심 지식을 요약해줘.", {"mime_type": file.content_type, "data": await file.read()}], False)
                    final_content += f"\n\n[{file.filename} 분석]\n{res.text}"
                except: pass
    await asyncio.to_thread(lambda: db.collection("knowledge").add({"title": title, "content": final_content, "subject": subject, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}))
    return {"success": True}

@app.post("/api/admin/knowledge/bulk", dependencies=[Depends(verify_admin)])
async def add_knowledge_bulk_admin(files: List[UploadFile] = File(...), subject: str = Form("korean")):
    if db is None: return {"success": False}
    subject = normalize_subject(subject)
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
                await asyncio.to_thread(lambda: db.collection("knowledge").add({"title": title, "content": f"[{title} 요약]\n{res.text}", "subject": subject, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}))
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
    subject: str = "korean"
    id: str = ""          # 있으면 그 출제본을 고친다


def sync_knowledge_from_source(doc_id: str, title: str, content: str, subject: str, source: str):
    """💡 원장님이 출제한 모의고사/퀴즈/문제 보관함 자료를 AI 채팅(학원 누적 자료)에
    자동으로 반영한다 — 학생이 'AI 국최'에게 그 시험 문제에 대해 물어볼 수 있으려면
    AI가 그 내용을 알고 있어야 하기 때문. 정답을 직접 알려주지 말라는 지시는
    시스템 프롬프트에 이미 있으므로(chat_with_ai), 내용 자체는 그대로 싣는다."""
    if db is None or not content.strip():
        return
    db.collection("knowledge").document(doc_id).set({
        "title": title, "content": content, "subject": normalize_subject(subject),
        "source": source, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }, merge=True)


def delete_synced_knowledge(doc_id: str):
    if db is not None:
        db.collection("knowledge").document(doc_id).delete()


PROBLEM_NUM_RE = re.compile(r"^(\d{1,2})\.\s+", re.M)


def parse_question_bank_content(content: str) -> dict:
    """'출제' 탭에서 만든 자료 한 편(지문+문항+해설+정답표가 한 텍스트에 뒤섞여 있음)을
    문항 번호 기준으로 갈라서, 나중에 원하는 번호만 골라 재조합할 수 있게 만든다."""
    body = content or ""
    table_text = ""
    if "[정답표]" in body:
        body, table_text = body.rsplit("[정답표]", 1)
    expl_text = ""
    if "[정답 및 해설]" in body:
        body, expl_text = body.split("[정답 및 해설]", 1)

    matches = list(PROBLEM_NUM_RE.finditer(body))
    preamble = body[:matches[0].start()].strip() if matches else body.strip()
    problems = {}
    for i, m in enumerate(matches):
        no = int(m.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        problems[no] = body[m.start():end].strip()

    expl_matches = list(PROBLEM_NUM_RE.finditer(expl_text))
    explanations = {}
    for i, m in enumerate(expl_matches):
        no = int(m.group(1))
        end = expl_matches[i + 1].start() if i + 1 < len(expl_matches) else len(expl_text)
        explanations[no] = expl_text[m.start():end].strip()

    answers = {}
    for line in table_text.splitlines():
        # 💡 실제 출제 프롬프트가 정답표에 요구하는 형식은 "1번 ⑤"인데(문제 출제
        # 예시 블록 참고), 이 정규식은 "1." / "1)" 형식만 받아들이고 있었다.
        # 그래서 이 앱이 직접 만든 정답표는 한 번도 여기 안 걸리고 늘 비어 있었다
        # — 재조합 기능의 정답표와 (아래) 문항별 영상의 정답 표시가 조용히 비던 원인.
        am = re.match(r"\s*(\d{1,2})\s*(?:번|[.\)])\s*(.+)", line)
        if am:
            answers[int(am.group(1))] = am.group(2).strip()

    return {"preamble": preamble, "problems": problems, "explanations": explanations, "answers": answers}


@app.post("/api/admin/questions", dependencies=[Depends(verify_admin)])
def save_question_admin(req: QuestionSaveReq):
    """출제본을 저장한다. id가 오면 새로 만들지 않고 그 출제본을 고친다.
    (자동 저장이 돌 때마다 사본이 쌓이지 않도록)"""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = req.title.strip() or "제목 없음"
    subject = normalize_subject(req.subject)

    if req.id.strip():
        ref = db.collection("questions").document(req.id.strip())
        if ref.get().exists:
            ref.set({"title": title, "content": req.content, "subject": subject, "updated_at": now}, merge=True)
            sync_knowledge_from_source(f"qbank_{req.id.strip()}", f"[출제] {title}", req.content, subject, "question_bank")
            return {"success": True, "id": req.id.strip(), "updated": True}

    return {"success": True, "id": store_question_bank(title, req.content, subject), "updated": False}


def store_question_bank(title: str, content: str, subject: str) -> str:
    """출제본을 문제 보관함에 새로 넣고, AI 학습 자료에도 반영한다.
    화면에서 저장할 때와 작업(백그라운드 출제)이 끝났을 때 같은 길을 쓴다."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = normalize_subject(subject)
    title = (title or "").strip() or "제목 없음"
    _, ref = db.collection("questions").add(
        {"title": title, "content": content, "subject": subject, "created_at": now}
    )
    sync_knowledge_from_source(f"qbank_{ref.id}", f"[출제] {title}", content, subject, "question_bank")
    return ref.id

@app.get("/api/admin/questions", dependencies=[Depends(verify_admin)])
def get_questions_admin(subject: str = ""):
    if db is None: return {"success": False, "questions": []}
    rows = [{"id": d.id, **d.to_dict()} for d in db.collection("questions").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]
    if subject:
        subj = normalize_subject(subject)
        rows = [r for r in rows if normalize_subject(r.get("subject", "korean")) == subj]
    return {"success": True, "questions": rows}

@app.delete("/api/admin/questions/{q_id}", dependencies=[Depends(verify_admin)])
def delete_question_admin(q_id: str):
    if db:
        db.collection("questions").document(q_id).delete()
        delete_synced_knowledge(f"qbank_{q_id}")
    return {"success": True}


@app.get("/api/admin/questions/{q_id}/parsed", dependencies=[Depends(verify_admin)])
def get_parsed_question_bank(q_id: str):
    """이 출제본 안에 문항이 몇 번까지 있는지, 각 문항이 무슨 내용인지 보여준다 —
    재조합할 때 몇 번 문항을 가져올지 고르는 화면에서 쓴다."""
    if db is None:
        return {"success": False}
    doc = db.collection("questions").document(q_id).get()
    if not doc.exists:
        return {"success": False, "detail": "존재하지 않는 자료입니다."}
    data = doc.to_dict()
    parsed = parse_question_bank_content(data.get("content", ""))
    problems = [{"no": no, "text": text} for no, text in sorted(parsed["problems"].items())]
    return {"success": True, "title": data.get("title", ""), "subject": data.get("subject", "korean"),
            "preamble": parsed["preamble"], "problems": problems}


class RecombineSource(BaseModel):
    id: str
    numbers: list = []


class RecombineReq(BaseModel):
    sources: list  # [{"id": "...", "numbers": [1,3,5]}]


@app.post("/api/admin/questions/recombine", dependencies=[Depends(verify_admin)])
async def recombine_questions(req: RecombineReq):
    """무작위로 새로 뽑는 게 아니라, 원장님이 이미 저장해둔 여러 출제본에서
    원하는 문항 번호만 골라 한 편으로 다시 엮는다."""
    if db is None:
        return {"success": False, "detail": "DB 오류"}
    if not req.sources:
        return {"success": False, "detail": "재조합할 자료를 선택하세요."}

    parts_body, parts_expl, parts_table = [], [], []
    cursor = 1

    for src in req.sources:
        sid = str((src or {}).get("id", "")).strip()
        try:
            numbers = sorted(set(int(n) for n in (src or {}).get("numbers") or []))
        except (TypeError, ValueError):
            numbers = []
        if not sid or not numbers:
            continue
        doc = await asyncio.to_thread(lambda sid=sid: db.collection("questions").document(sid).get())
        if not doc.exists:
            continue
        data = doc.to_dict()
        parsed = parse_question_bank_content(data.get("content", ""))
        src_title = data.get("title", "제목 없음")

        picked_here = [n for n in numbers if n in parsed["problems"]]
        if not picked_here:
            continue

        if parsed["preamble"]:
            parts_body.append(f"[{src_title}에서 가져온 지문]\n{parsed['preamble']}")

        for n in picked_here:
            parts_body.append(re.sub(r"^\d{1,2}\.", f"{cursor}.", parsed["problems"][n], count=1))
            if n in parsed["explanations"]:
                parts_expl.append(re.sub(r"^\d{1,2}\.", f"{cursor}.", parsed["explanations"][n], count=1))
            if n in parsed["answers"]:
                parts_table.append(f"{cursor}. {parsed['answers'][n]}")
            cursor += 1

    total_picked = cursor - 1
    if not total_picked:
        return {"success": False, "detail": "선택한 문항을 찾지 못했습니다."}

    content = "\n\n".join(parts_body)
    if parts_expl:
        content += "\n\n[정답 및 해설]\n" + "\n\n".join(parts_expl)
    if parts_table:
        content += "\n\n[정답표]\n" + "\n".join(parts_table)

    return {"success": True, "content": content, "count": total_picked}


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

# 💡 기존 4종(과목별 성향)은 '공통'으로 두고, 원장님이 주신 학교급·영역별 진단
#    설문지 16종(초등·중등·고등·재수N수 × 국어·수학·영어·학습태도, 각 27문항)을 함께 싣는다.
#    학년이 다르면 물어볼 것도 달라서, 화면에서는 학교급으로 묶어 고르게 한다.
for _k, _s in TENDENCY_SETS.items():
    _s.setdefault("stage", "common")
    _s.setdefault("stage_name", "공통")
    _s.setdefault("subject", _k)

try:
    from diagnostic_sets import DIAGNOSTIC_SETS
    TENDENCY_SETS.update(DIAGNOSTIC_SETS)
except Exception as _e:   # 진단 설문지 파일이 없어도 나머지 기능은 그대로 돌아가야 한다
    print("진단 설문지를 불러오지 못했습니다:", _e)

STAGE_ORDER = ["common", "elem", "mid", "high", "repeat"]


def get_tendency_set(key: str) -> dict:
    return TENDENCY_SETS.get(str(key or "").strip(), TENDENCY_SETS[DEFAULT_TENDENCY_SET])


def tendency_weak_items(set_key: str, answers: dict, limit: int = 6) -> list:
    """가장 낮게 답한 문항들 — 축 점수만으로는 안 보이는 '무엇이 약한지'를 짚어준다."""
    tset = get_tendency_set(set_key)
    axis_names = {a["key"]: a["name"] for a in tset["axes"]}
    rows = []
    for q in tset["questions"]:
        raw = (answers or {}).get(str(q["id"]), (answers or {}).get(q["id"]))
        try:
            v = int(raw)
        except (TypeError, ValueError):
            continue
        v = max(1, min(5, v))
        if q.get("reverse"):
            v = 6 - v
        rows.append({"id": q["id"], "text": q["text"], "score": v,
                     "axis": q["axis"], "axis_name": axis_names.get(q["axis"], "")})
    rows.sort(key=lambda r: (r["score"], r["id"]))
    return [r for r in rows if r["score"] <= 3][:limit]


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
        "record_facts": data.get("record_facts") or None,
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
        weak = t.get("weak_items") or []
        if weak:
            out.append("  낮게 답한 문항:")
            out += [f"    · ({w.get('axis_name', '')}) {w.get('text', '')}" for w in weak[:6]]
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
    sets = [
        {"key": s["key"], "name": s["name"], "icon": s["icon"], "desc": s["desc"],
         "stage": s.get("stage", "common"), "stage_name": s.get("stage_name", "공통"),
         "subject": s.get("subject", ""),
         "count": len(s["questions"]), "axes": [a["name"] for a in s["axes"]]}
        for s in TENDENCY_SETS.values()
    ]
    sets.sort(key=lambda s: (STAGE_ORDER.index(s["stage"]) if s["stage"] in STAGE_ORDER else 9, s["key"]))
    stages = []
    for s in sets:
        if not any(g["key"] == s["stage"] for g in stages):
            stages.append({"key": s["stage"], "name": s["stage_name"]})
    return {"success": True, "sets": sets, "stages": stages}


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


class TendencyAllowReq(BaseModel):
    student_name: str
    allow: bool


@app.post("/api/admin/student/tendency_allow", dependencies=[Depends(verify_admin)])
async def set_tendency_allow(req: TendencyAllowReq):
    """💡 학생이 마음대로(원장님 승인 없이) 학습 성향 검사를 시작·재검사하지 못하도록,
    원장님이 미리 허락해준 경우에만 제출을 받는다. 여기서 그 허락을 켜고 끈다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.student_name.strip()
    if not name:
        return {"success": False, "detail": "학생을 먼저 선택해주세요."}
    ref = db.collection("students").document(sanitize_doc_id(name))
    doc = await asyncio.to_thread(ref.get)
    if not doc.exists:
        return {"success": False, "detail": "등록된 학생이 아닙니다."}
    await asyncio.to_thread(lambda: ref.set({"tendency_allowed": bool(req.allow)}, merge=True))
    return {"success": True, "allowed": bool(req.allow)}


@app.post("/api/counsel/tendency_submit")
async def submit_tendency(req: TendencySubmitReq):
    """학생 본인이 검사를 제출한다. 채점은 서버에서만 한다."""
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    name = req.student_name.strip()
    if not name:
        return {"success": False, "detail": "학생 정보가 없습니다."}

    s_ref = db.collection("students").document(sanitize_doc_id(name))
    s_doc = await asyncio.to_thread(s_ref.get)
    if not s_doc.exists:
        return {"success": False, "detail": "등록된 학생이 아닙니다."}

    # 💡 원장님이 미리 허락해준 경우에만 제출을 받는다 — 학생이 마음대로 응시하지
    # 못하게 해달라는 요청. 제출이 끝나면 허락을 그 자리에서 소모(reset)해서,
    # 다음에 또 하려면 다시 허락을 받아야 한다.
    if not bool(s_doc.to_dict().get("tendency_allowed")):
        return {"success": False, "detail": "원장님의 승인이 필요합니다. 선생님께 검사 허락을 요청해주세요."}

    tset = get_tendency_set(req.set)
    axes = score_tendency(req.answers or {}, tset["key"])
    if sum(a["answered"] for a in axes) < len(tset["questions"]):
        return {"success": False, "detail": "모든 문항에 답해주세요."}

    payload = {
        "set": tset["key"], "set_name": tset["name"],
        "answers": {str(k): v for k, v in (req.answers or {}).items()},
        "axes": axes,
        # 축 점수만으로는 '무엇이' 약한지 안 보여서, 낮게 답한 문항도 함께 남긴다
        "weak_items": tendency_weak_items(tset["key"], req.answers or {}),
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
    await asyncio.to_thread(lambda: s_ref.set({"tendency_allowed": False}, merge=True))
    send_telegram_message(f"🧭 [{tset['name']}]\n{name} 학생이 검사를 마쳤습니다.")
    return {"success": True, "axes": axes, "set": tset["key"], "set_name": tset["name"]}


@app.get("/api/counsel/me/{student_name}")
def get_my_counsel(student_name: str):
    """학생 본인이 보는 상담 카드 — 원장님만 보는 항목(학생부 원문 등)은 빼고 준다."""
    if db is None:
        return {"success": False}
    name = urllib.parse.unquote(student_name)
    v = build_counsel_view(name)
    tendency_allowed = False
    if db is not None:
        s_doc = db.collection("students").document(sanitize_doc_id(name)).get()
        if s_doc.exists:
            tendency_allowed = bool(s_doc.to_dict().get("tendency_allowed"))
    return {"success": True, "counsel": {
        "naesin": v["naesin"], "mock": v["mock"], "track": v["track"], "tiers": v["tiers"],
        "table_note": v["table_note"],
        "tendency": v["tendency"], "tendencies": v["tendencies"], "tendency_allowed": tendency_allowed,
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
        return {"success": False, "detail": f"AI 평가 실패\n{friendly_ai_error(e)}"}

    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    counsel_ref(name).set({
        "student_name": name, "record_text": body, "target_major": major,
        "record_eval": text, "record_eval_at": at, "updated_at": at,
    }, merge=True)
    return {"success": True, "record_eval": text, "at": at}


# ── 학생부에서 출결·봉사·독서만 따로 뽑아내기 ─────────────
#   학생부 양식은 학교마다·연도마다 표기가 조금씩 달라서 규칙으로 긁으면 꼭 어긋난다.
#   그래서 AI에게 '원문에 적힌 것만' 뽑아 표로 정리하게 하고, 합계는 서버가 직접 센다.
RECORD_FACTS_PROMPT = """아래는 한 학생의 학교생활기록부 원문입니다.
여기서 '교과 성적(내신)', '출결상황', '봉사활동 시간', '독서활동(읽은 책)' 네 가지를 뽑아 JSON으로 정리해줘.

[반드시 지킬 것]
- 원문에 적힌 것만 옮겨라. 원문에 없는 숫자나 책 제목을 절대 지어내지 마라.
- 찾지 못한 항목은 빈 배열로 두어라. 억지로 채우지 마라.
- 숫자는 숫자로만 적어라(단위·글자 빼고). 모르면 null.
- 학년은 "1", "2", "3" 처럼 숫자만. 학년 구분이 없으면 "".
- 교과 성적(naesin)은 '교과학습발달상황' 표의 과목을 한 줄도 빠뜨리지 말고 모두 옮겨라.
  · term: "학년-학기" 형태. 예) 1학년 1학기 → "1-1"
  · unit: 단위수(이수단위). rank_grade: 석차등급(1~9 또는 1~5).
  · rank: 석차(등수), total: 수강자수. '12/250' 처럼 적혀 있으면 rank=12, total=250.
  · 석차등급이 없는 과목(진로선택 과목 등)은 rank_grade를 null로 두고 그대로 넣어라.
- 다른 설명 없이 아래 형태의 JSON 객체 하나만 출력해라.

{
  "naesin": [
    {"term":"1-1","subject":"국어","unit":4,"score":88,"subject_avg":72.3,
     "rank_grade":2,"rank":25,"total":250,"achievement":"A"}
  ],
  "attendance": [
    {"grade":"1","school_days":190,"absence_illness":0,"absence_unauth":0,"absence_etc":0,
     "late":0,"leave_early":0,"result":0,"note":"특기사항 원문 그대로"}
  ],
  "volunteer": [
    {"grade":"1","hours":15,"detail":"활동 내용 원문 그대로"}
  ],
  "books": [
    {"grade":"1","subject":"국어","title":"책 제목","author":"지은이"}
  ]
}

[학생부 원문]
"""


def build_naesin_rows(raw_rows: list) -> list:
    """학생부에서 뽑아낸 교과 성적을 성적표에 그대로 넣을 수 있는 형태로 다듬는다.
    석차와 수강자수가 함께 있으면 석차백분율까지 계산해 준다 — 백분율이 있어야
    9등급제·5등급제 환산이 정확해지기 때문."""
    out = []
    for r in raw_rows[:200]:
        subject = str(r.get("subject", "")).strip()
        if not subject:
            continue
        term = str(r.get("term", "")).strip()
        row = {"term": term, "subject": subject[:40]}
        unit = _num(r.get("unit"))
        if unit is not None:
            row["unit"] = unit
        grade = _num(r.get("rank_grade"))
        if grade is not None:
            row["grade"] = grade
        rank, total = _num(r.get("rank")), _num(r.get("total"))
        if rank is not None and total:
            row["pct"] = round(rank / total * 100, 2)
        out.append(row)
    return out


def _facts_num(v):
    n = _num(v)
    return n if n is not None else None


def summarize_record_facts(facts: dict) -> dict:
    """뽑아낸 표에서 합계를 서버가 직접 센다 (AI가 더한 숫자는 믿지 않는다)."""
    att = facts.get("attendance") or []
    vol = facts.get("volunteer") or []
    books = facts.get("books") or []

    def total(rows, key):
        vals = [_facts_num(r.get(key)) for r in rows]
        vals = [v for v in vals if v is not None]
        return round(sum(vals), 1) if vals else 0

    unauth = total(att, "absence_unauth") + total(att, "late") + total(att, "leave_early") + total(att, "result")
    naesin = facts.get("naesin") or []
    return {
        "naesin_count": len(naesin),
        "naesin_terms": sorted({str(r.get("term", "")).strip() for r in naesin if str(r.get("term", "")).strip()}),
        "attendance_total": {
            "absence_illness": total(att, "absence_illness"),
            "absence_unauth": total(att, "absence_unauth"),
            "absence_etc": total(att, "absence_etc"),
            "late": total(att, "late"),
            "leave_early": total(att, "leave_early"),
            "result": total(att, "result"),
        },
        "attendance_clean": unauth == 0,
        "volunteer_total": total(vol, "hours"),
        "book_count": len(books),
        "book_subjects": sorted({str(b.get("subject", "")).strip() for b in books if str(b.get("subject", "")).strip()}),
    }


class RecordFactsReq(BaseModel):
    student_name: str
    record_text: str = ""


@app.post("/api/admin/counsel/record_facts", dependencies=[Depends(verify_admin)])
async def extract_record_facts(req: RecordFactsReq):
    """학생부에서 출결·봉사시간·독서활동을 뽑아 표로 만든다."""
    name = req.student_name.strip()
    if not name:
        return {"success": False, "detail": "학생을 먼저 선택해주세요."}
    body = (req.record_text or "").strip()
    if not body:
        body = str((load_counsel(name) or {}).get("record_text", "")).strip()
    if len(body) < 30:
        return {"success": False, "detail": "학생부 내용을 먼저 붙여넣어 주세요."}

    try:
        res = await asyncio.to_thread(lambda: safe_generate(RECORD_FACTS_PROMPT + body[:20000]))
        raw = (res.text or "").strip()
    except Exception as e:
        return {"success": False, "detail": f"AI 정리 실패\n{friendly_ai_error(e)}"}

    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    start, end = raw.find("{"), raw.rfind("}")
    try:
        facts = json.loads(raw[start:end + 1] if start >= 0 and end > start else raw)
    except Exception:
        # 💡 왜 실패했는지 그대로 보여준다 — 뭉뚱그린 안내는 원인 파악을 막는다
        return {"success": False, "detail": f"AI가 표 형태로 답하지 않았습니다. 받은 내용 앞부분: {raw[:200]}"}

    facts = {
        "naesin": build_naesin_rows(list(facts.get("naesin") or [])),
        "attendance": list(facts.get("attendance") or [])[:6],
        "volunteer": list(facts.get("volunteer") or [])[:20],
        "books": list(facts.get("books") or [])[:200],
    }
    summary = summarize_record_facts(facts)
    at = datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {**facts, "summary": summary, "at": at}
    await asyncio.to_thread(lambda: counsel_ref(name).set({
        "student_name": name, "record_text": body,
        "record_facts": payload, "updated_at": at,
    }, merge=True))
    return {"success": True, "facts": payload}


# ── 모의고사 성적표를 그대로 읽어 성적으로 만들기 ─────────
#   성적표는 학교·기관마다 양식이 제각각이고, 대개 캡처 이미지나 PDF로 온다.
#   규칙으로 긁지 않고 AI에게 그대로 보여주고 읽게 한다.
MOCK_EXTRACT_PROMPT = """아래 자료는 한 학생의 모의고사(또는 수능) 성적표입니다.
과목별 성적을 빠짐없이 뽑아 JSON으로 정리해줘.

[반드시 지킬 것]
- 성적표에 실제로 적힌 것만 옮겨라. 없는 숫자를 지어내지 마라.
- date: 시행 시기를 "연도-월" 두 자리 월로. 예) 2026년 6월 시행 → "2026-06". 연도가 없으면 월만 "-06"이 아니라 "" 로 두어라.
- subject: 성적표에 적힌 과목 이름 그대로(국어, 수학, 영어, 한국사, 생활과윤리 …).
  선택과목이 따로 적혀 있으면 "국어(언어와매체)"처럼 괄호로 붙여라.
- raw: 원점수, standard: 표준점수, percentile: 백분위, grade: 등급.
- 영어·한국사·제2외국어는 절대평가라 백분위가 없다. 없으면 null로 두어라.
- 한 성적표에 여러 회차가 함께 있으면 회차마다 모든 과목을 각각 넣어라.
- 다른 설명 없이 아래 형태의 JSON 객체 하나만 출력해라.

{"rows":[{"date":"2026-06","subject":"국어","raw":88,"standard":129,"percentile":92,"grade":2}]}
"""


def build_mock_rows(raw_rows: list) -> list:
    """성적표에서 뽑아낸 줄을 모의고사 성적표에 그대로 넣을 수 있는 형태로 다듬는다."""
    out = []
    for r in raw_rows[:200]:
        subject = str((r or {}).get("subject", "")).strip()
        if not subject:
            continue
        row = {"subject": subject[:40], "date": str(r.get("date", "")).strip()[:10]}
        for key, src in (("raw", "raw"), ("grade", "grade"), ("percentile", "percentile")):
            v = _num(r.get(src))
            if v is not None:
                row[key] = v
        # 영어·한국사처럼 절대평가 과목에 백분위가 잘못 들어오면 빼 준다
        if is_absolute_subject(subject):
            row.pop("percentile", None)
        out.append(row)
    return out


def is_absolute_subject(name: str) -> bool:
    """절대평가라 백분위가 없는 과목인지."""
    n = str(name or "")
    return any(k in n for k in ["영어", "한국사", "제2외국어", "한문", "아랍어", "일본어",
                                 "중국어", "독일어", "프랑스어", "스페인어", "러시아어", "베트남어"])


@app.post("/api/admin/counsel/mock_extract", dependencies=[Depends(verify_admin)])
async def extract_mock_scores(student_name: str = Form(...), text: str = Form(""),
                              files: Optional[List[UploadFile]] = File(None)):
    """모의고사 성적표(사진·캡처·PDF·엑셀·붙여넣은 글)를 읽어 성적 줄로 만들어 준다."""
    name = student_name.strip()
    if not name:
        return {"success": False, "detail": "학생을 먼저 선택해주세요."}

    parts, extra_text = [], (text or "").strip()
    for f in (files or []):
        if not f.filename:
            continue
        raw = await f.read()
        low = f.filename.lower()
        if low.endswith(".pdf"):
            try:
                pdf_doc = fitz.open(stream=raw, filetype="pdf")
                for page in pdf_doc[:10]:
                    pix = page.get_pixmap(dpi=150)
                    parts.append({"mime_type": "image/png", "data": pix.tobytes("png")})
                pdf_doc.close()
            except Exception as e:
                return {"success": False, "detail": f"PDF를 읽지 못했습니다: {e}"}
        elif low.endswith((".xlsx", ".csv")):
            try:
                rows = await asyncio.to_thread(_read_sheet, raw, f.filename, "", 300)
            except Exception as e:
                return {"success": False, "detail": f"파일을 읽지 못했습니다: {e}"}
            table = "\n".join(" | ".join(str(c or "").strip() for c in r)
                              for r in rows if any(str(c or "").strip() for c in r))
            extra_text = (extra_text + "\n" + table).strip()
        elif (f.content_type or "").startswith("image/"):
            parts.append({"mime_type": f.content_type, "data": raw})
        else:
            return {"success": False, "detail": f"'{f.filename}' 은(는) 읽을 수 없는 형식입니다. 사진·캡처 이미지, PDF, 엑셀만 올려주세요."}

    if not parts and not extra_text:
        return {"success": False, "detail": "성적표 사진이나 파일을 올리거나, 성적표 내용을 붙여넣어 주세요."}

    contents = [MOCK_EXTRACT_PROMPT + (f"\n\n[성적표 내용]\n{extra_text[:12000]}" if extra_text else "")] + parts
    try:
        resp = await asyncio.to_thread(lambda: safe_generate(contents))
        raw_text = (resp.text or "").strip()
    except Exception as e:
        return {"success": False, "detail": f"AI 읽기 실패\n{friendly_ai_error(e)}"}

    match = re.search(r"\{.*\}", raw_text, re.S)
    if not match:
        preview = re.sub(r"\s+", " ", raw_text)[:200]
        return {"success": False,
                "detail": "AI가 성적표 형식으로 답하지 않았습니다." + (f" 받은 내용: {preview}" if preview else " (빈 응답)")}
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError) as e:
        return {"success": False, "detail": f"AI 응답을 해석하지 못했습니다: {e}"}

    rows = build_mock_rows(parsed.get("rows") or [])
    if not rows:
        return {"success": False, "detail": "성적표에서 과목별 성적을 찾지 못했습니다. 과목·점수가 또렷하게 보이는 사진인지 확인해주세요."}
    dates = sorted({r["date"] for r in rows if r.get("date")})
    return {"success": True, "rows": rows, "count": len(rows), "dates": dates}


class RecordSearchReq(BaseModel):
    student_name: str
    keyword: str
    context: int = 140


@app.post("/api/admin/counsel/record_search", dependencies=[Depends(verify_admin)])
def search_record(req: RecordSearchReq):
    """학생부 원문에서 원장님이 넣은 낱말을 찾아, 그 앞뒤 내용까지 함께 보여준다.
    (AI를 거치지 않는다 — 원문 그대로여야 하고, 즉시 나와야 하므로)"""
    name = req.student_name.strip()
    if not name:
        return {"success": False, "detail": "학생을 먼저 선택해주세요."}
    body = str((load_counsel(name) or {}).get("record_text", ""))
    if not body.strip():
        return {"success": False, "detail": "저장된 학생부 내용이 없습니다. 먼저 학생부를 붙여넣고 저장해주세요."}

    # 쉼표로 여러 낱말을 한 번에 찾을 수 있다
    words = [w.strip() for w in re.split(r"[,\n]", req.keyword or "") if w.strip()]
    if not words:
        return {"success": False, "detail": "찾을 낱말을 입력해주세요."}

    pad = max(20, min(400, int(req.context or 140)))
    low = body.lower()
    groups = []
    for w in words[:10]:
        needle = w.lower()
        hits, pos = [], 0
        while len(hits) < 30:
            i = low.find(needle, pos)
            if i < 0:
                break
            s, e = max(0, i - pad), min(len(body), i + len(w) + pad)
            hits.append({
                "before": ("…" if s > 0 else "") + body[s:i],
                "match": body[i:i + len(w)],
                "after": body[i + len(w):e] + ("…" if e < len(body) else ""),
                "pos": i,
            })
            pos = i + len(w)
        groups.append({"keyword": w, "count": len(hits), "hits": hits})

    return {"success": True, "total": sum(g["count"] for g in groups),
            "groups": groups, "length": len(body)}


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
# 💡 입결 자료는 전형 종류에 따라 견줄 성적이 다르다.
#    수시(교과·종합)는 내신, 논술은 논술전형 입결, 정시는 수능 — 셋을 섞으면 판단이 어긋난다.
UNIV_KINDS = ("susi", "nonsul", "jeongsi")
UNIV_KIND_LABELS = {"susi": "수시", "nonsul": "논술", "jeongsi": "정시"}


def normalize_univ_kind(value: str) -> str:
    v = str(value or "").strip().lower()
    if v.startswith("정") or v == "jeongsi":
        return "jeongsi"
    if v.startswith("논") or v in ("nonsul", "논술"):
        return "nonsul"
    return "susi"


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


# ── 입결 자료 표준 양식 ──────────────────────────────────
# 💡 쓰시던 엑셀을 그대로 올려 열을 하나하나 짝지어도 되지만, 매번 짝짓는 게 번거롭다.
# 아래 표준 양식대로 채워 오면 열 짝짓기가 자동으로 끝난다 — 그 '기준이 되는 틀'.
# 수시와 정시는 보는 숫자가 달라서(수시: 인원·수능최저·경쟁률 / 정시: 영어등급) 양식을 나눴다.
# (key, 열 이름, 필수 여부, 예시, 설명)
_COL_UNIV = ("univ", "대학", True, "중앙대학교",
             "대학 이름. '중앙대', '중앙대학교' 어느 쪽이든 괜찮습니다. 캠퍼스가 다르면 '고려대학교(세종)'처럼 적어주세요.")
_COL_REGION = ("region", "소재지", False, "서울 동작구",
               "이 칸을 채우면 학생의 지원 가능 대학이 지도 위에 표시됩니다. '서울 동작구'처럼 시도와 시군구를 함께 적으면 가장 정확합니다.")
_COL_MAJOR = ("major", "학과", True, "미디어커뮤니케이션학부", "모집단위·학과 이름.")
_COL_YEAR = ("year", "연도", False, "2026", "이 입결이 어느 학년도 자료인지.")
_COL_NOTE = ("note", "비고", False, "", "그 밖에 상담 때 같이 보고 싶은 내용.")

UNIV_TEMPLATES = {
    "susi": {
        "label": "수시",
        "filename": "입결자료_수시양식.xlsx",
        "columns": [
            _COL_UNIV, _COL_REGION, _COL_MAJOR,
            ("type", "전형", False, "학생부교과(지역균형)", "전형 이름. 교과 / 종합 / 논술 등."),
            ("quota", "인원", False, "12", "모집 인원."),
            ("cut50", "50%컷", False, "1.9", "합격자 50%컷(중간) 등급."),
            ("cut70", "70%컷", True, "2.1", "합격자 70%컷 등급. 합격선 판단의 기준으로 씁니다."),
            ("min_suneung", "수능최저", False, "국수영탐 3합 7",
             "수능 최저학력기준. 적어두면 상담 때 학과마다 함께 보여줍니다."),
            ("rate", "경쟁률", False, "12.4", "경쟁률. 숫자만 적어주세요(예: 12.4)."),
            _COL_YEAR, _COL_NOTE,
        ],
        "samples": [
            {"univ": "중앙대학교", "region": "서울 동작구", "major": "미디어커뮤니케이션학부",
             "type": "학생부교과(지역균형)", "quota": "12", "cut50": "1.9", "cut70": "2.1",
             "min_suneung": "국수영탐 3합 7", "rate": "12.4", "year": "2026", "note": ""},
            {"univ": "아주대학교", "region": "경기 수원시 영통구", "major": "경영학과",
             "type": "학생부종합(ACE)", "quota": "20", "cut50": "2.4", "cut70": "2.7",
             "min_suneung": "없음", "rate": "9.8", "year": "2026", "note": ""},
        ],
        "tips": [
            "● 첫 줄(열 이름)은 지우거나 바꾸지 마세요. 이 이름을 보고 프로그램이 알아서 열을 짝지어 줍니다.",
            "● 2번째 줄부터가 실제 자료입니다. 예시로 넣어둔 두 줄은 지우고 쓰시면 됩니다.",
            "● 합격선은 70%컷을 기준으로 판단합니다. 70%컷이 없으면 50%컷으로 대신합니다.",
            "● 수시 자료는 학생의 내신 등급과 견줍니다. 등급이 아닌 점수로 적으실 거면 올릴 때 '점수 종류'를 바꿔주세요.",
            "● 소재지를 채우면 상담 화면 지도에 지원 가능 대학이 표시됩니다. 비워두면 이름이 알려진 대학은 자동으로 채워집니다.",
            "● 논술 자료는 올릴 때 '논술'을 골라주세요. 같은 양식을 그대로 쓰시면 됩니다.",
        ],
    },
    "jeongsi": {
        "label": "정시",
        "filename": "입결자료_정시양식.xlsx",
        "columns": [
            _COL_UNIV, _COL_REGION, _COL_MAJOR,
            ("type", "전형", False, "수능위주(일반전형)", "전형 이름."),
            ("cut50", "50%컷", False, "89.5", "합격자 50%컷(중간)."),
            ("cut70", "70%컷", True, "88.0", "합격자 70%컷. 합격선 판단의 기준으로 씁니다."),
            ("eng", "영어등급", False, "2", "영어 반영·최저 등급."),
            _COL_YEAR, _COL_NOTE,
        ],
        "samples": [
            {"univ": "부산대학교", "region": "부산 금정구", "major": "경영학과",
             "type": "수능위주(일반전형)", "cut50": "89.5", "cut70": "88.0", "eng": "2",
             "year": "2026", "note": "국수영탐 백분위 평균"},
            {"univ": "충남대학교", "region": "대전 유성구", "major": "행정학부",
             "type": "수능위주(일반전형)", "cut50": "85.0", "cut70": "83.5", "eng": "3",
             "year": "2026", "note": ""},
        ],
        "tips": [
            "● 첫 줄(열 이름)은 지우거나 바꾸지 마세요. 이 이름을 보고 프로그램이 알아서 열을 짝지어 줍니다.",
            "● 2번째 줄부터가 실제 자료입니다. 예시로 넣어둔 두 줄은 지우고 쓰시면 됩니다.",
            "● 합격선은 70%컷을 기준으로 판단합니다. 70%컷이 없으면 50%컷으로 대신합니다.",
            "● 정시 자료는 학생의 수능 백분위(또는 원점수)와 견줍니다. 올릴 때 '점수 종류'를 백분위/점수 중 맞는 것으로 골라주세요.",
            "● 소재지를 채우면 상담 화면 지도에 지원 가능 대학이 표시됩니다. 비워두면 이름이 알려진 대학은 자동으로 채워집니다.",
        ],
    },
}

# 예전 이름 — 수시 양식을 가리킨다
UNIV_TEMPLATE_COLUMNS = UNIV_TEMPLATES["susi"]["columns"]

# 자동 짝짓기용 — 열 이름에 이 낱말이 들어 있으면 그 자리로 본다
UNIV_HEADER_HINTS = {
    "univ": ["대학명", "대학교", "대학", "학교명", "univ"],
    "major": ["모집단위", "학과", "전공", "학부", "major"],
    "type": ["전형명", "전형유형", "전형", "type"],
    "track": ["계열", "모집계열", "track"],
    "region": ["소재지", "지역", "위치", "캠퍼스소재", "region"],
    "year": ["학년도", "연도", "년도", "year"],
    "quota": ["모집인원", "인원", "선발인원", "quota"],
    "cut70": ["70%컷", "70퍼컷", "70컷", "70%", "70cut"],
    "cut50": ["50%컷", "50퍼컷", "50컷", "50%", "50cut", "평균등급", "중간값"],
    "min_suneung": ["수능최저", "최저학력", "최저기준", "수능최저학력기준", "최저"],
    "rate": ["경쟁률", "경쟁율", "지원율", "rate"],
    "cut": ["기준점수", "합격선", "등급컷", "커트", "cut", "점수"],
    "metric_col": ["점수종류", "점수구분", "기준구분", "metric"],
    "eng": ["영어등급", "영어", "eng"],
    "note": ["비고", "메모", "note"],
}


def guess_univ_mapping(columns: list) -> dict:
    """열 이름을 보고 무엇이 무엇인지 스스로 짝지어 본다.
    표준 양식대로 올렸으면 이것만으로 짝짓기가 끝난다."""
    norm = [re.sub(r"[\s()·\-_/]", "", str(c or "")).lower() for c in columns]
    out, used = {}, set()
    for key, hints in UNIV_HEADER_HINTS.items():
        for hint in hints:
            h = hint.lower()
            # 정확히 같은 이름을 먼저, 없으면 포함하는 이름
            for exact in (True, False):
                for i, c in enumerate(norm):
                    if i in used or not c:
                        continue
                    if (c == h) if exact else (h in c):
                        out[key] = i
                        used.add(i)
                        break
                if key in out:
                    break
            if key in out:
                break
    return out


def build_univ_template_xlsx(kind: str = "susi") -> bytes:
    """수시/정시 표준 양식 엑셀 파일을 만들어 돌려준다 (작성 안내 시트 포함)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    spec = UNIV_TEMPLATES.get(kind) or UNIV_TEMPLATES["susi"]
    columns = spec["columns"]

    wb = Workbook()
    ws = wb.active
    ws.title = f"{spec['label']}입결"

    head_fill = PatternFill("solid", fgColor="1F3864")
    req_fill = PatternFill("solid", fgColor="C00000")
    white_bold = Font(color="FFFFFF", bold=True, size=11)

    for i, (_key, label, required, _example, _desc) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=i, value=label + ("*" if required else ""))
        cell.fill = req_fill if required else head_fill
        cell.font = white_bold
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[cell.column_letter].width = max(12, min(30, len(label) * 2 + 9))
    for r, sample in enumerate(spec["samples"], start=2):
        for i, (key, *_rest) in enumerate(columns, start=1):
            ws.cell(row=r, column=i, value=sample.get(key, ""))
    ws.freeze_panes = "A2"

    guide = wb.create_sheet("작성안내")
    guide.column_dimensions["A"].width = 16
    guide.column_dimensions["B"].width = 10
    guide.column_dimensions["C"].width = 24
    guide.column_dimensions["D"].width = 86
    for i, text in enumerate(["열 이름", "필수", "예시", "설명"], start=1):
        c = guide.cell(row=1, column=i, value=text)
        c.fill = head_fill
        c.font = white_bold
    for r, (_key, label, required, example, desc) in enumerate(columns, start=2):
        guide.cell(row=r, column=1, value=label)
        guide.cell(row=r, column=2, value="필수" if required else "선택")
        guide.cell(row=r, column=3, value=example)
        guide.cell(row=r, column=4, value=desc)
    for r, line in enumerate(spec["tips"], start=len(columns) + 3):
        guide.cell(row=r, column=1, value=line)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@app.get("/api/admin/univ_table/template", dependencies=[Depends(verify_admin)])
def download_univ_template(kind: str = "susi"):
    key = "jeongsi" if normalize_univ_kind(kind) == "jeongsi" else "susi"
    try:
        data = build_univ_template_xlsx(key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"양식을 만들지 못했습니다: {e}")
    fname = urllib.parse.quote(UNIV_TEMPLATES[key]["filename"].encode("utf-8"))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"},
    )


@app.post("/api/admin/univ_table/preview", dependencies=[Depends(verify_admin)])
async def preview_univ_table(file: UploadFile = File(...), sheet: str = Form(""),
                             header_row: int = Form(-1), header_span: int = Form(0)):
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

    # 열 이름만 보고 자동으로 짝지어 본다 — 표준 양식이면 이것만으로 끝난다
    auto = guess_univ_mapping(columns)
    is_template, template_kind = False, ""
    for key, spec in UNIV_TEMPLATES.items():
        required = [k for k, _l, req, *_x in spec["columns"] if req]
        if all(k in auto for k in required):
            is_template, template_kind = True, key
            break

    return {"success": True, "sheets": sheets, "sheet": sheet or (sheets[0] if sheets else ""),
            "header_row": hidx, "header_span": span, "columns": columns, "sample": sample,
            "row_count": total, "filename": file.filename, "head_preview": head_preview,
            "auto_mapping": auto, "is_template": is_template, "template_kind": template_kind}


@app.post("/api/admin/univ_table/import", dependencies=[Depends(verify_admin)])
async def import_univ_table(
    file: UploadFile = File(...),
    mapping: str = Form(...),
    label: str = Form(""),
    sheet: str = Form(""),
    header_row: int = Form(-1),
    header_span: int = Form(0),
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
    kind = normalize_univ_kind(kind)

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
        # 💡 표준 양식은 50%컷·70%컷을 따로 받는다. 합격선 판단은 70%컷을 쓰고,
        #    70%컷이 비어 있으면 50%컷으로, 그것도 없으면 예전 '기준점수' 열로 대신한다.
        cut70 = _num(cell(r, "cut70"))
        cut50 = _num(cell(r, "cut50"))
        cut = cut70 if cut70 is not None else (cut50 if cut50 is not None else _num(cell(r, "cut")))
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
        if cut70 is not None:
            e["cut70"] = round(cut70, 3)
        if cut50 is not None:
            e["cut50"] = round(cut50, 3)
        quota = _num(cell(r, "quota"))
        if quota is not None:
            e["quota"] = int(quota)
        rate = _num(cell(r, "rate"))
        if rate is not None:
            e["rate"] = round(rate, 2)
        min_suneung = cell(r, "min_suneung")
        if min_suneung:
            e["min_suneung"] = min_suneung[:60]
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
        "nonsul_count": kinds.get("nonsul", 0),
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


# ─────────────────────────────────────────────────────────
# 대학 소재지 — 지원 가능 대학을 지도에 뿌리기 위한 자료
#   입결 엑셀에 '소재지' 열이 있으면 그것을 먼저 쓰고, 없으면 아래 표로 채운다.
#   시군구 이름은 화면에서 쓰는 지도 데이터(korea-map.js, 통계청 2013 행정구역)와
#   같은 표기를 써야 지도 위에서 짝이 맞는다. (예: 수원시는 '수원시영통구'처럼 구까지)
# ─────────────────────────────────────────────────────────
SIDO_CODES = {
    "서울": "11", "부산": "21", "대구": "22", "인천": "23", "광주": "24", "대전": "25",
    "울산": "26", "세종": "29", "경기": "31", "강원": "32", "충북": "33", "충남": "34",
    "전북": "35", "전남": "36", "경북": "37", "경남": "38", "제주": "39",
}
SIDO_NAMES = {v: k for k, v in SIDO_CODES.items()}
# 특별시·광역시·특별자치시 — 이 안의 시군구는 구/군이라 이름이 '시'로 시작하지 않는다
METRO_SIDO = {"서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종"}
# 길게 적힌 시도 이름도 알아듣게
SIDO_ALIASES = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산",
    "세종특별자치시": "세종", "세종시": "세종", "경기도": "경기",
    "강원도": "강원", "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남",
    "전라북도": "전북", "전북특별자치도": "전북", "전라남도": "전남",
    "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주", "제주도": "제주",
}

UNIV_REGIONS = {
    # ── 서울 ──
    "서울대": ("11", "관악구"), "연세대": ("11", "서대문구"), "고려대": ("11", "성북구"),
    "서강대": ("11", "마포구"), "성균관대": ("11", "종로구"), "한양대": ("11", "성동구"),
    "중앙대": ("11", "동작구"), "경희대": ("11", "동대문구"), "한국외대": ("11", "동대문구"),
    "서울시립대": ("11", "동대문구"), "건국대": ("11", "광진구"), "동국대": ("11", "중구"),
    "홍익대": ("11", "마포구"), "숙명여대": ("11", "용산구"), "국민대": ("11", "성북구"),
    "숭실대": ("11", "동작구"), "세종대": ("11", "광진구"), "광운대": ("11", "노원구"),
    "명지대": ("11", "서대문구"), "상명대": ("11", "종로구"), "서울여대": ("11", "노원구"),
    "성신여대": ("11", "성북구"), "덕성여대": ("11", "도봉구"), "동덕여대": ("11", "성북구"),
    "이화여대": ("11", "서대문구"), "삼육대": ("11", "노원구"), "서경대": ("11", "성북구"),
    "한성대": ("11", "성북구"), "서울과학기술대": ("11", "노원구"), "서울과기대": ("11", "노원구"),
    "한국체육대": ("11", "송파구"), "서울교대": ("11", "서초구"), "서울교육대": ("11", "서초구"),
    "총신대": ("11", "동작구"), "장로회신학대": ("11", "광진구"), "감리교신학대": ("11", "서대문구"),
    "성공회대": ("11", "구로구"), "추계예술대": ("11", "서대문구"),
    "한국예술종합": ("11", "성북구"), "한예종": ("11", "성북구"),
    "서울기독대": ("11", "은평구"), "kc대": ("11", "강서구"),
    "육군사관": ("11", "노원구"), "경기대(서울)": ("11", "서대문구"),
    # ── 경기 ──
    "아주대": ("31", "수원시영통구"), "경기대": ("31", "수원시영통구"),
    "성균관대(자연)": ("31", "수원시장안구"), "성균관대(수원)": ("31", "수원시장안구"),
    "경희대(국제)": ("31", "용인시기흥구"), "단국대": ("31", "용인시수지구"),
    "명지대(자연)": ("31", "용인시처인구"), "한국외대(글로벌)": ("31", "용인시처인구"),
    "강남대": ("31", "용인시기흥구"), "용인대": ("31", "용인시처인구"),
    "루터대": ("31", "용인시기흥구"), "칼빈대": ("31", "용인시처인구"),
    "한양대(erica)": ("31", "안산시상록구"), "한양대(안산)": ("31", "안산시상록구"),
    "한신대": ("31", "오산시"), "대진대": ("31", "포천시"), "차의과학대": ("31", "포천시"),
    "가천대": ("31", "성남시수정구"), "을지대": ("31", "성남시수정구"),
    "신한대": ("31", "의정부시"), "한세대": ("31", "군포시"), "평택대": ("31", "평택시"),
    "협성대": ("31", "화성시"), "수원대": ("31", "화성시"), "수원가톨릭대": ("31", "화성시"),
    "가톨릭대": ("31", "부천시원미구"), "서울신학대": ("31", "부천시원미구"),
    "안양대": ("31", "안양시만안구"), "성결대": ("31", "안양시만안구"),
    "경동대(양주)": ("31", "양주시"), "서정대": ("31", "양주시"),
    "동국대(바이오메디)": ("31", "고양시일산동구"), "동국대(일산)": ("31", "고양시일산동구"),
    "한국항공대": ("31", "고양시덕양구"), "중앙대(안성)": ("31", "안성시"),
    "한경대": ("31", "안성시"), "한경국립대": ("31", "안성시"),
    # ── 인천 ──
    "인하대": ("23", "남구"), "인천대": ("23", "연수구"), "경인교대": ("23", "계양구"),
    "경인교육대": ("23", "계양구"), "인천가톨릭대": ("23", "강화군"),
    "가천대(메디컬)": ("23", "남동구"),
    # ── 부산 ──
    "부산대": ("21", "금정구"), "동아대": ("21", "사하구"), "부경대": ("21", "남구"),
    "한국해양대": ("21", "영도구"), "동의대": ("21", "부산진구"), "경성대": ("21", "남구"),
    "신라대": ("21", "사상구"), "부산외대": ("21", "금정구"), "동서대": ("21", "사상구"),
    "고신대": ("21", "영도구"), "동명대": ("21", "남구"), "부산가톨릭대": ("21", "금정구"),
    "부산교대": ("21", "연제구"), "부산교육대": ("21", "연제구"),
    # ── 대구 ──
    "경북대": ("22", "북구"), "계명대": ("22", "달서구"), "대구교대": ("22", "남구"),
    "대구교육대": ("22", "남구"), "대구보건대": ("22", "북구"),
    # ── 인천·경기 외 광역시 ──
    "전남대": ("24", "북구"), "조선대": ("24", "동구"), "지스트": ("24", "북구"),
    "광주과학기술원": ("24", "북구"), "gist": ("24", "북구"), "호남대": ("24", "광산구"),
    "광주대": ("24", "남구"), "광주여대": ("24", "광산구"), "남부대": ("24", "광산구"),
    "송원대": ("24", "남구"), "광주교대": ("24", "북구"), "광주교육대": ("24", "북구"),
    "충남대": ("25", "유성구"), "한남대": ("25", "대덕구"), "배재대": ("25", "서구"),
    "목원대": ("25", "서구"), "대전대": ("25", "동구"), "우송대": ("25", "동구"),
    "한밭대": ("25", "유성구"), "카이스트": ("25", "유성구"), "kaist": ("25", "유성구"),
    "한국과학기술원": ("25", "유성구"), "을지대(대전)": ("25", "중구"),
    "침례신학대": ("25", "유성구"), "대전교대": ("25", "서구"), "대전교육대": ("25", "서구"),
    "울산대": ("26", "남구"), "유니스트": ("26", "울주군"), "unist": ("26", "울주군"),
    "울산과학기술원": ("26", "울주군"), "울산과학대": ("26", "동구"),
    "고려대(세종)": ("29", "세종시"), "홍익대(세종)": ("29", "세종시"),
    "한국영상대": ("29", "세종시"),
    # ── 강원 ──
    "강원대": ("32", "춘천시"), "연세대(미래)": ("32", "원주시"), "연세대(원주)": ("32", "원주시"),
    "한림대": ("32", "춘천시"), "강릉원주대": ("32", "강릉시"), "상지대": ("32", "원주시"),
    "한라대": ("32", "원주시"), "가톨릭관동대": ("32", "강릉시"), "경동대": ("32", "고성군"),
    "강원대(삼척)": ("32", "삼척시"), "춘천교대": ("32", "춘천시"), "춘천교육대": ("32", "춘천시"),
    # ── 충북 ──
    "충북대": ("33", "청주시흥덕구"), "한국교통대": ("33", "충주시"),
    "청주대": ("33", "청주시상당구"), "서원대": ("33", "청주시흥덕구"),
    "세명대": ("33", "제천시"), "건국대(글로컬)": ("33", "충주시"), "건국대(충주)": ("33", "충주시"),
    "중원대": ("33", "괴산군"), "한국교원대": ("33", "청주시흥덕구"),
    "청주교대": ("33", "청주시흥덕구"), "청주교육대": ("33", "청주시흥덕구"),
    "유원대": ("33", "영동군"), "극동대": ("33", "음성군"),
    # ── 충남 ──
    "단국대(천안)": ("34", "천안시동남구"), "순천향대": ("34", "아산시"), "호서대": ("34", "아산시"),
    "선문대": ("34", "아산시"), "남서울대": ("34", "천안시서북구"),
    "상명대(천안)": ("34", "천안시동남구"), "백석대": ("34", "천안시동남구"),
    "공주대": ("34", "공주시"), "한국기술교육대": ("34", "천안시동남구"),
    "코리아텍": ("34", "천안시동남구"), "나사렛대": ("34", "천안시서북구"),
    "건양대": ("34", "논산시"), "중부대": ("34", "금산군"), "청운대": ("34", "홍성군"),
    "한서대": ("34", "서산시"), "공주교대": ("34", "공주시"), "공주교육대": ("34", "공주시"),
    # ── 전북 ──
    "전북대": ("35", "전주시덕진구"), "원광대": ("35", "익산시"), "전주대": ("35", "전주시완산구"),
    "군산대": ("35", "군산시"), "우석대": ("35", "완주군"), "호원대": ("35", "군산시"),
    "예수대": ("35", "전주시완산구"), "한일장신대": ("35", "완주군"),
    "전주교대": ("35", "전주시완산구"), "전주교육대": ("35", "전주시완산구"),
    # ── 전남 ──
    "순천대": ("36", "순천시"), "목포대": ("36", "무안군"), "목포해양대": ("36", "목포시"),
    "동신대": ("36", "나주시"), "초당대": ("36", "무안군"), "세한대": ("36", "영암군"),
    "광주가톨릭대": ("36", "나주시"), "한국에너지공대": ("36", "나주시"), "켄텍": ("36", "나주시"),
    "목포가톨릭대": ("36", "목포시"),
    # ── 경북 ──
    "포항공대": ("37", "포항시남구"), "포스텍": ("37", "포항시남구"), "postech": ("37", "포항시남구"),
    "한동대": ("37", "포항시북구"), "영남대": ("37", "경산시"), "대구대": ("37", "경산시"),
    "대구가톨릭대": ("37", "경산시"), "경일대": ("37", "경산시"), "대구한의대": ("37", "경산시"),
    "금오공대": ("37", "구미시"), "안동대": ("37", "안동시"), "위덕대": ("37", "경주시"),
    "동국대(경주)": ("37", "경주시"), "경주대": ("37", "경주시"), "김천대": ("37", "김천시"),
    "경운대": ("37", "구미시"), "대구예술대": ("37", "칠곡군"),
    # ── 경남 ──
    "경상국립대": ("38", "진주시"), "경상대": ("38", "진주시"), "창원대": ("38", "창원시의창구"),
    "인제대": ("38", "김해시"), "경남대": ("38", "창원시마산합포구"), "영산대": ("38", "양산시"),
    "부산장신대": ("38", "김해시"), "가야대": ("38", "김해시"),
    "진주교대": ("38", "진주시"), "진주교육대": ("38", "진주시"), "한국국제대": ("38", "진주시"),
    # ── 제주 ──
    "제주대": ("39", "제주시"), "제주국제대": ("39", "제주시"),
}

# 캠퍼스를 가리키는 말 — '고려대 세종캠퍼스'처럼 붙어 오면 캠퍼스별 소재지로 찾는다
UNIV_CAMPUS_HINTS = ["세종", "글로벌", "국제", "erica", "안산", "미래", "원주", "천안", "경주",
                     "자연", "수원", "안성", "충주", "글로컬", "삼척", "일산", "바이오메디",
                     "메디컬", "대전", "서울", "양주"]


def normalize_univ_name(name: str) -> str:
    """'서울대학교' → '서울대' 처럼 견주기 좋은 형태로 다듬는다."""
    s = re.sub(r"\s+", "", str(name or "")).lower()
    s = s.replace("캠퍼스", "").replace("학교", "")
    s = re.sub(r"[\[\]{}<>]", "", s)
    return s


def univ_lookup_keys(name: str) -> list:
    """캠퍼스까지 맞춘 키를 먼저, 그다음 본교 키를 돌려준다."""
    s = normalize_univ_name(name)
    if not s:
        return []
    inner = re.findall(r"[(（]([^)）]*)[)）]", s)
    base = re.sub(r"[(（][^)）]*[)）]", "", s).strip()
    keys = []
    campus_words = []
    for token in inner:
        for hint in UNIV_CAMPUS_HINTS:
            if hint in token:
                campus_words.append(hint)
    # 괄호가 없더라도 '한양대erica'처럼 뒤에 붙어 오는 경우
    if not campus_words:
        for hint in UNIV_CAMPUS_HINTS:
            if base.endswith(hint) and len(base) > len(hint) + 1:
                campus_words.append(hint)
                base = base[: -len(hint)]
                break
    for w in campus_words:
        keys.append(f"{base}({w})")
    keys.append(base)
    return keys


def resolve_univ_region(univ: str, region_text: str = "") -> dict:
    """대학이 어느 시도·시군구에 있는지 정한다.
    ① 엑셀 '소재지' 열 → ② 내장 소재지 표 → ③ 알 수 없음."""
    txt = re.sub(r"\s+", " ", str(region_text or "")).strip()
    if txt:
        flat = txt.replace(" ", "")
        # 긴 이름('서울특별시')을 먼저 맞춰 보고, 그다음 짧은 이름('서울')을 본다
        hit = None
        for full, short in sorted(SIDO_ALIASES.items(), key=lambda kv: -len(kv[0])):
            if flat.startswith(full):
                hit = (short, flat[len(full):])
                break
        if hit is None:
            for short, code in SIDO_CODES.items():
                if flat.startswith(short):
                    rest = flat[len(short):]
                    # 💡 '서울시 동작구'처럼 짧은 이름 뒤에 시/도가 더 붙어 오면 그것까지 떼야
                    #    '동작구'가 남는다. 안 떼면 '시동작구'가 되어 지도에서 짝을 못 찾는다.
                    #    다만 도(道)에서는 '경기 시흥시'처럼 시군구 이름이 '시'로 시작할 수 있어
                    #    '도'만 떼고 '시'는 건드리지 않는다.
                    tails = ("특별자치시", "광역시", "특별시", "시") if short in METRO_SIDO \
                        else ("특별자치도", "도")
                    for tail in tails:
                        if rest.startswith(tail):
                            rest = rest[len(tail):]
                            break
                    hit = (short, rest)
                    break
        if hit:
            short, rest = hit
            # 세종은 시 전체가 하나의 시군구다 — 소재지를 '세종시'라고만 적어도 지도에 얹힌다
            if short == "세종" and not rest:
                rest = "세종시"
            return {"sido": short, "sido_code": SIDO_CODES[short], "sigungu": rest, "source": "file"}

    for key in univ_lookup_keys(univ):
        hit = UNIV_REGIONS.get(key)
        if hit:
            code, sigungu = hit
            return {"sido": SIDO_NAMES[code], "sido_code": code, "sigungu": sigungu, "source": "table"}
    return {"sido": "", "sido_code": "", "sigungu": "", "source": "unknown"}


class UnivMapReq(BaseModel):
    student_name: str
    kind: str = "susi"
    only_reachable: bool = True


@app.post("/api/admin/counsel/univ_map", dependencies=[Depends(verify_admin)])
def get_univ_map(req: UnivMapReq):
    """학생의 지금 성적으로 지원 가능한 대학을 소재지와 함께 돌려준다.
    화면에서는 이걸 전국 지도 → 시도 지도 → 대학 목록 순으로 파고들며 본다."""
    name = req.student_name.strip()
    if not name:
        return {"success": False, "detail": "학생을 먼저 선택해주세요."}
    rows = load_univ_table()
    if not rows:
        return {"success": False, "detail": "입결 자료가 아직 올라오지 않았습니다. '입결 자료(엑셀) 관리'에서 먼저 올려주세요."}

    view = build_counsel_view(name)
    mine_all = student_scores(view)
    # 💡 '전체'로 보면 수시·논술·정시를 한 지도 위에 서로 다른 색으로 함께 본다
    want_all = str(req.kind).strip().lower() in ("all", "전체", "함께")
    kind = "all" if want_all else normalize_univ_kind(req.kind)
    kinds = list(UNIV_KINDS) if want_all else [kind]

    # 💡 견줄 성적이 아예 없으면 지도가 텅 비어 나온다 — 왜 비었는지 먼저 알려준다
    if kind == "susi" and mine_all["grade"] is None:
        return {"success": False, "detail": "내신 성적이 입력되어 있지 않아 수시 지원 가능 대학을 계산할 수 없습니다. '성적 · 진학 전략' 탭에서 내신을 먼저 입력하고 저장해주세요."}
    if kind == "jeongsi" and mine_all["percentile"] is None and mine_all["score"] is None:
        return {"success": False, "detail": "모의고사 백분위(또는 원점수)가 입력되어 있지 않아 정시 지원 가능 대학을 계산할 수 없습니다. 모의고사 성적을 먼저 입력해주세요."}
    # 논술 입결은 자료마다 기준이 내신 등급일 수도, 논술·수능 점수일 수도 있어 둘 다 본다
    if kind in ("nonsul", "all") and all(mine_all[k] is None for k in ("grade", "percentile", "score")):
        return {"success": False, "detail": "견줄 성적이 없어 지원 가능 대학을 계산할 수 없습니다. 내신이나 모의고사 성적을 먼저 입력해주세요."}

    # 대학 하나로 묶는다 — 같은 대학의 여러 학과 중 가장 가까운(잘 닿는) 줄을 대표로.
    # 한 대학이 수시에도 정시에도 있을 수 있어 전형 갈래까지 함께 열쇠로 삼는다.
    merged = {}
    for r in rows:
        r_kind = normalize_univ_kind(r.get("kind", "susi"))
        if r_kind not in kinds:
            continue
        item = compare_univ_row(r, mine_all)
        if not item or item["gap"] is None:
            continue
        univ = item["univ"]
        slot = merged.setdefault((univ, r_kind), {
            "univ": univ, "kind": r_kind, "total": 0, "reachable": 0,
            "best": None, "majors": [], "region_text": "",
        })
        slot["total"] += 1
        if item["reach"]:
            slot["reachable"] += 1
        if slot["best"] is None or item["gap"] < slot["best"]["gap"]:
            slot["best"] = item
        if len(slot["majors"]) < 40:
            slot["majors"].append({
                "major": item["major"], "type": item["type"], "cut": item["cut"],
                "gap": item["gap"], "reach": item["reach"], "unit": item["unit"],
                "cut50": item["cut50"], "cut70": item["cut70"],
                "quota": item["quota"], "rate": item["rate"],
                "min_suneung": item["min_suneung"], "eng_cut": item["eng_cut"],
            })
        if not slot["region_text"]:
            slot["region_text"] = r.get("region", "")

    out, unknown = [], []
    region_sources = {"file": 0, "table": 0, "unknown": 0}
    for (univ, r_kind), slot in merged.items():
        if req.only_reachable and not slot["reachable"]:
            continue
        reg = resolve_univ_region(univ, slot.get("region_text", ""))
        region_sources[reg["source"]] = region_sources.get(reg["source"], 0) + 1
        best = slot["best"]
        entry = {
            "univ": univ, "kind": r_kind, "kind_name": UNIV_KIND_LABELS.get(r_kind, r_kind),
            "total": slot["total"], "reachable": slot["reachable"],
            "gap": best["gap"], "cut": best["cut"], "unit": best["unit"],
            "mine": best["mine"], "metric": best["metric"],
            "majors": sorted(slot["majors"], key=lambda m: m["gap"])[:20],
            **reg,
        }
        if entry["sido_code"]:
            out.append(entry)
        else:
            unknown.append(entry)

    out.sort(key=lambda e: (e["sido_code"], e["gap"]))
    unknown.sort(key=lambda e: e["gap"])

    by_sido = {}
    for e in out:
        s = by_sido.setdefault(e["sido_code"], {"sido": e["sido"], "univ_count": 0, "reachable": 0,
                                                "kinds": {}})
        s["univ_count"] += 1
        s["reachable"] += e["reachable"]
        s["kinds"][e["kind"]] = s["kinds"].get(e["kind"], 0) + 1

    return {
        "success": True, "kind": kind,
        "kinds": kinds,
        "student": name,
        "mine": mine_all,
        "univs": out[:600], "unknown": unknown[:100],
        "by_sido": by_sido,
        "region_sources": region_sources,
        "only_reachable": req.only_reachable,
        "note": "수시·논술은 내신 등급, 정시는 백분위·점수를 기준으로 견줍니다.",
    }


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
        "cut50": r.get("cut50"), "cut70": r.get("cut70"),
        "quota": r.get("quota"), "rate": r.get("rate"),
        "min_suneung": r.get("min_suneung", ""),
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
    groups = {k: [] for k in UNIV_KINDS}
    for r in hits[:200]:
        item = compare_univ_row(r, mine_all)
        if item:
            groups[item["kind"] if item["kind"] in groups else "susi"].append(item)

    out = {"status": "ok", "univ": univ, "major": major}
    for k in UNIV_KINDS:
        items = groups[k]
        scored = sorted([i for i in items if i["gap"] is not None], key=lambda x: x["gap"])
        out[k] = {
            "items": items[:20],
            "closest": scored[0] if scored else None,
            "reachable": sum(1 for i in scored if i["reach"]),
            "total": len(scored),
            "count": len(items),
        }
    if not any(out[k]["count"] for k in UNIV_KINDS):
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

    groups = {k: [] for k in UNIV_KINDS}
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
    for k in UNIV_KINDS:
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
    name = urllib.parse.unquote(student_name)
    view = build_counsel_view(name)
    s_doc = db.collection("students").document(sanitize_doc_id(name)).get()
    view["tendency_allowed"] = bool(s_doc.to_dict().get("tendency_allowed")) if s_doc.exists else False
    return {"success": True, "counsel": view}
