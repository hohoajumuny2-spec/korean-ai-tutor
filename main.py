import os
import re
import json
import time
import uuid
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
    }


def level_up_info(old_xp, delta):
    """xp가 old_xp에서 old_xp+delta로 늘어날 때 레벨이 오르면 축하 화면에 쓸 정보를 반환, 아니면 None."""
    if not delta:
        return None
    old_lv = compute_level_info(old_xp)
    new_lv = compute_level_info((old_xp or 0) + delta)
    if new_lv["level"] > old_lv["level"]:
        return {"from": old_lv["level"], "to": new_lv["level"], "name": new_lv["name"], "icon": new_lv["icon"]}
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
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    def _send():
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=3,
            )
        except Exception:
            pass

    threading.Thread(target=_send).start()


# ─────────────────────────────────────────────────────────
# AI 모델 (캐싱 유지)
# ─────────────────────────────────────────────────────────
_cached_model = None

def get_best_model():
    global _cached_model
    if _cached_model:
        return _cached_model

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise Exception("API 키가 설정되지 않았습니다.")
    genai.configure(api_key=api_key.strip().replace('"', "").replace("'", ""))

    try:
        models = genai.list_models()
        available = [m.name.replace("models/", "") for m in models if "generateContent" in m.supported_generation_methods]
        target_model = next(
            (m for m in ["gemini-3.6-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"] if m in available),
            available[0] if available else None,
        )
        if not target_model:
            raise Exception("사용 가능한 구글 AI 모델이 없습니다.")

        _cached_model = genai.GenerativeModel(target_model)
        return _cached_model
    except Exception as e:
        raise Exception(f"AI 모델 초기화 실패: {str(e)}")


def safe_generate(contents, stream=False):
    model = get_best_model()
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
    gender: str
    item: str = "none"


@app.post("/api/student/avatar")
async def save_avatar(req: AvatarSaveRequest):
    if db is None:
        return {"success": False}
    if req.gender not in ("boy", "girl"):
        return {"success": False, "detail": "성별 값이 올바르지 않습니다."}

    s_ref = db.collection("students").document(req.student_name)
    doc = await asyncio.to_thread(s_ref.get)
    if not doc.exists:
        return {"success": False, "detail": "학생 정보를 찾을 수 없습니다."}

    info = compute_level_info(doc.to_dict().get("xp"))
    unlocked_ids = {it["id"] for it in info["unlocked_items"]}
    item = req.item if (req.item == "none" or req.item in unlocked_ids) else "none"

    await asyncio.to_thread(lambda: s_ref.set({"avatar_gender": req.gender, "avatar_item": item}, merge=True))
    return {"success": True, "gender": req.gender, "item": item}


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

@app.post("/api/admin/student")
def add_single_student(req: SingleStudentRequest, _: bool = Depends(verify_admin)):
    if db is None:
        return {"success": False, "detail": "DB 연결 오류"}
    db.collection("students").document(sanitize_doc_id(req.name)).set({"school": req.school, "grade": req.grade}, merge=True)
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

@app.post("/api/admin/student/update")
def update_student(req: StudentUpdateReq, _: bool = Depends(verify_admin)):
    if db is None: return {"success": False}
    doc_ref = db.collection("students").document(req.old_id)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        data['school'] = req.school; data['grade'] = req.grade
        if req.old_id != req.new_name:
            db.collection("students").document(req.new_name).set(data)
            doc_ref.delete()
        else: doc_ref.set(data, merge=True)
    return {"success": True}

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
    except Exception:
        return {"success": False, "reply": "AI 응답 지연이 발생했습니다. 잠시 후 다시 시도해주세요."}


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
    except Exception:
        return {"success": False, "detail": "첨삭 처리 중 오류 발생"}


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

    if data:
        exam_data = json.loads(data.get("exam_data", "{}"))
        for i, q in enumerate(exam_data.get("questions", [])):
            student_ans = str(req.answers[i]).strip() if i < len(req.answers) else ""
            if student_ans == str(q.get("ans", "")).strip() and student_ans != "":
                actual_score += int(q.get("score", 0))
            else:
                wrongs.append(i + 1)

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
    return {"success": True, "score": actual_score, "video_url": data.get("video_url", ""), "explanation_text": data.get("explanation_text", ""), "level_up": lvl_up}


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
    await asyncio.to_thread(
        lambda: db.collection("quizzes").document(safe_title).set(
            {
                "title": title,
                "deadline": req.get("deadline"),
                "time_limit": int(req.get("time_limit", 0)),
                "questions": req.get("questions", []),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    )
    return {"success": True}


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
    if doc.exists:
        for i, q in enumerate(doc.to_dict().get("questions", [])):
            if i < len(req.answers) and str(req.answers[i]) == str(q.get("answer")):
                actual_score += int(q.get("score", 0))

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
    return {"success": True, "score": actual_score, "level_up": lvl_up}


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
    q_principle: str = Form(""),
    files: Optional[List[UploadFile]] = File(None),
    _: bool = Depends(verify_admin),
):
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low

    # 난이도별 문항 수 × 원장님이 정한 출제 원칙을, 실제로 출제해야 하는 등급에 대해서만 프롬프트에 명시
    difficulty_block = ""
    if q_mode == "신규" and total > 0:
        difficulty_counts = [
            ("killer", cnt_killer), ("semi", cnt_semi), ("high", cnt_high),
            ("mid", cnt_mid), ("low", cnt_low),
        ]
        sections = [
            f"■ {DIFFICULTY_PRINCIPLES[key][0]} — {cnt}문항\n{DIFFICULTY_PRINCIPLES[key][1]}"
            for key, cnt in difficulty_counts if cnt > 0
        ]
        difficulty_block = "\n\n[난이도별 출제 원칙 - 지정된 문항 수와 출제 기준을 반드시 지켜서 출제하세요]\n" + "\n\n".join(sections)

    types_block = ""
    if q_mode == "신규" and q_types.strip():
        types_block = f"\n\n[문제 유형]\n다음 유형으로만 문제를 구성하세요: {q_types}"

    principle_block = ""
    if q_principle.strip():
        principle_block = f"""
[출제 원칙 - 원장님이 지정한 지침이므로 아래 형식 규칙 다음으로 최우선 반영]
{q_principle.strip()}
"""

    prompt = f"""다음 지문을 바탕으로 {total}문항의 객관식 문제를 출제해줘.

[출력 형식 규칙 - 반드시 지켜야 함]
- 마크다운 문법을 절대 사용하지 마세요. 굵게 표시하는 ** 기호, 제목에 쓰는 # 또는 ## 기호를 쓰지 마세요.
- 부등호/꺾쇠 기호 <, >는 절대 사용하지 마세요. "<보기>"라고 쓰지 말고 반드시 대괄호를 사용해 "[보기]"라고 쓰세요 (다른 항목들처럼 [지문], [정답 및 해설], [정답표]와 같은 형식으로 통일).
- 순수한 일반 텍스트로만 작성하세요. 강조가 필요하면 기호 없이 줄바꿈이나 문장으로 구분하세요.
{difficulty_block}{types_block}
{principle_block}
{q_text}"""
    contents = [prompt]
    # 💡 첨부된 자료 파일(교과서 PDF/이미지 등)이 실제로는 AI에게 전달되지 않고 무시되던 버그 수정
    if files:
        for f in files:
            if f.filename:
                file_bytes = await f.read()
                contents.append({"mime_type": f.content_type or "application/octet-stream", "data": file_bytes})
    try:
        model = get_best_model()
        response = model.generate_content(contents, stream=True)

        def iter_response():
            for chunk in response:
                if chunk.text:
                    yield chunk.text

        return StreamingResponse(iter_response(), media_type="text/plain")
    except Exception:
        def err_response():
            yield "❌ AI 생성 실패. 잠시 후 다시 시도하세요."

        return StreamingResponse(err_response(), media_type="text/plain")


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
        model = get_best_model()
        response = model.generate_content(contents, stream=True)

        def iter_response():
            for chunk in response:
                if chunk.text:
                    yield chunk.text

        return StreamingResponse(iter_response(), media_type="text/plain")
    except Exception:
        def err_response():
            yield "❌ AI 생성 실패. 잠시 후 다시 시도하세요."

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

class QuestionSaveReq(BaseModel): title: str; content: str
@app.post("/api/admin/questions", dependencies=[Depends(verify_admin)])
def save_question_admin(req: QuestionSaveReq):
    if db: db.collection("questions").add({"title": req.title, "content": req.content, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.get("/api/admin/questions", dependencies=[Depends(verify_admin)])
def get_questions_admin():
    if db is None: return {"success": False, "questions": []}
    return {"success": True, "questions": [{"id": d.id, **d.to_dict()} for d in db.collection("questions").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

@app.delete("/api/admin/questions/{q_id}", dependencies=[Depends(verify_admin)])
def delete_question_admin(q_id: str):
    if db: db.collection("questions").document(q_id).delete()
    return {"success": True}
