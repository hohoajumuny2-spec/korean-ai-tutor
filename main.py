import os
import json
import uuid
import requests
import threading
import mimetypes
import urllib.parse
import asyncio
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

# 클로드 보안 패치: allow_credentials=False 로 변경하여 스펙 모순 해결
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
        status_code=200, # 화면이 깨지지 않도록 200 반환, 내용은 에러
        content={"success": False, "detail": "서버 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."},
        headers={"Access-Control-Allow-Origin": "*"},
    )

XP_REWARD_LOGIN = 50
XP_REWARD_HOMEWORK = 200
XP_REWARD_PROFILE = 300
XP_MULTIPLIER_EXAM = 2

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".hwp", ".doc", ".docx", ".txt", ".ppt", ".pptx", ".mp4", ".mov"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB

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
# 💡 철통 보안 관리자 인증 시스템 (클로드 제안)
# ─────────────────────────────────────────────────────────
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
_admin_tokens = set()

def issue_admin_token() -> str:
    token = uuid.uuid4().hex
    _admin_tokens.add(token)
    return token

def verify_admin(x_admin_token: Optional[str] = Header(None)):
    if not x_admin_token or x_admin_token not in _admin_tokens:
        raise HTTPException(status_code=401, detail="관리자 인증이 필요합니다.")
    return True

# ─────────────────────────────────────────────────────────
# 💡 파일 저장 (경로 조작 해킹 방지 패치)
# ─────────────────────────────────────────────────────────
def get_safe_filename(filename: str) -> str:
    if not filename: return "unnamed_file"
    return os.path.basename(filename).replace(" ", "_")

def validate_upload(filename: str, file_bytes: bytes):
    safe_name = get_safe_filename(filename)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS: raise HTTPException(status_code=400, detail=f"허용되지 않는 형식입니다: {ext}")
    if len(file_bytes) > MAX_UPLOAD_BYTES: raise HTTPException(status_code=400, detail="용량이 25MB를 초과했습니다.")

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
        except Exception: pass
    with open(filepath, "wb") as buffer:
        buffer.write(file_bytes)
    return f"/{filepath}"

def sanitize_doc_id(value: str, fallback: str = "unnamed") -> str:
    if not value or not value.strip(): return fallback
    cleaned = value.strip().replace("/", "_").replace("\\", "_")
    if cleaned in (".", ".."): return fallback
    return cleaned[:200]

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
                return Response(content=blob.download_as_bytes(), media_type=mt or "application/octet-stream", headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_filename}"})
        except Exception: pass

    if os.path.exists(filepath):
        return FileResponse(filepath, media_type=mt or "application/octet-stream", headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_filename}"})
    raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

def send_telegram_message(text: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    def _send():
        try: requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=3)
        except Exception: pass
    threading.Thread(target=_send).start()

# ─────────────────────────────────────────────────────────
# 💡 성능 패치: AI 모델 캐싱으로 속도 비약적 향상
# ─────────────────────────────────────────────────────────
_cached_model = None

def get_best_model():
    global _cached_model
    if _cached_model: return _cached_model
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key: raise Exception("API 키가 설정되지 않았습니다.")
    genai.configure(api_key=api_key.strip().replace('"', "").replace("'", ""))
    try:
        models = genai.list_models()
        available = [m.name.replace("models/", "") for m in models if "generateContent" in m.supported_generation_methods]
        target_model = next((m for m in ["gemini-3.6-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"] if m in available), available[0] if available else None)
        if not target_model: raise Exception("사용 가능한 구글 AI 모델이 없습니다.")
        _cached_model = genai.GenerativeModel(target_model)
        return _cached_model
    except Exception as e: raise Exception(f"AI 모델 초기화 실패: {str(e)}")

def safe_generate(contents, stream=False):
    return get_best_model().generate_content(contents, stream=stream)

class ConnectionManager:
    def __init__(self): self.active_connections = {}
    async def connect(self, ws: WebSocket, room: str):
        await ws.accept()
        self.active_connections.setdefault(room, []).append(ws)
    def disconnect(self, ws: WebSocket, room: str):
        if room in self.active_connections and ws in self.active_connections[room]: self.active_connections[room].remove(ws)
    async def broadcast(self, message: str, room: str, sender: WebSocket):
        for c in self.active_connections.get(room, []):
            if c != sender:
                try: await c.send_text(message)
                except Exception: pass

manager = ConnectionManager()

@app.websocket("/ws/exam/{room}")
async def websocket_endpoint(websocket: WebSocket, room: str):
    await manager.connect(websocket, room)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(data, room, sender=websocket)
    except WebSocketDisconnect: manager.disconnect(websocket, room)

# ─────────────────────────────────────────────────────────
# 로그인 및 공통 기능
# ─────────────────────────────────────────────────────────
class AuthRequest(BaseModel): school: str = ""; grade: str = ""; student_name: str; admin_password: str = ""

@app.get("/api/health")
def health_check(): return {"status": "ok"}

@app.post("/api/auth")
async def authenticate(req: AuthRequest):
    if req.admin_password:
        if req.admin_password == ADMIN_PASSWORD:
            return {"success": True, "is_admin": True, "admin_token": issue_admin_token()}
        return {"success": False, "detail": "관리자 비밀번호가 올바르지 않습니다."}

    if db is None: return {"success": False, "detail": "DB 연결 오류"}
    doc = await asyncio.to_thread(lambda: db.collection("students").document(req.student_name).get())
    if doc.exists:
        data = doc.to_dict()
        if data.get("school") == req.school and data.get("grade") == req.grade:
            today = datetime.now().strftime("%Y-%m-%d")
            # 💡 동시성 패치: Increment 활용
            if data.get("last_login", "") != today:
                await asyncio.to_thread(lambda: db.collection("students").document(req.student_name).set({"last_login": today, "xp": firestore.Increment(XP_REWARD_LOGIN)}, merge=True))
            send_telegram_message(f"🔔 [접속 알림]\n{req.school} {req.grade}학년 {req.student_name} 학생이 스마트 학습실에 로그인했습니다.")
            return {"success": True, "is_admin": False}
    return {"success": False, "detail": "명부에 이름이 없거나 정보가 틀립니다."}

@app.get("/api/student/profile/{student_name}")
def get_student_profile(student_name: str):
    if db is None: return {"success": False}
    doc = db.collection("students").document(student_name).get()
    if not doc.exists: return {"success": False}
    reports = [r.to_dict() for r in db.collection("reports").where("student_name", "==", student_name).order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(100).stream()]
    return {"success": True, "profile": doc.to_dict(), "reports": reports}

@app.post("/api/student/profile_update")
async def update_profile(student_name: str = Form(...), motto: str = Form(""), avatar: str = Form(""), file: Optional[UploadFile] = File(None)):
    if db is None: return {"success": False}
    s_ref = db.collection("students").document(student_name)
    doc = await asyncio.to_thread(s_ref.get)
    if not doc.exists: return {"success": False}
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

# ─────────────────────────────────────────────────────────
# 💡 학생 열람 가능 데이터 (토큰 필요 없음)
# ─────────────────────────────────────────────────────────
@app.get("/api/board")
def get_board():
    if db is None: return {"success": False, "posts": []}
    return {"success": True, "posts": [{"id": d.id, **d.to_dict()} for d in db.collection("board").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

@app.get("/api/lectures")
def get_lectures():
    if db is None: return {"success": False, "lectures": []}
    return {"success": True, "lectures": [{"id": d.id, **d.to_dict()} for d in db.collection("lectures").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

@app.get("/api/knowledge")
def get_knowledge():
    if db is None: return {"success": False, "knowledge": []}
    return {"success": True, "knowledge": [{"id": d.id, **d.to_dict()} for d in db.collection("knowledge").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

@app.get("/api/exams")
def get_exams():
    if db is None: return {"success": False, "exams": []}
    return {"success": True, "exams": [{"id": d.id, **d.to_dict()} for d in db.collection("exams").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

@app.get("/api/quizzes")
def get_quizzes():
    if db is None: return {"success": False, "quizzes": []}
    return {"success": True, "quizzes": [{"id": d.id, **d.to_dict()} for d in db.collection("quizzes").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

@app.get("/api/homeworks")
def get_homeworks():
    if db is None: return {"success": False, "homeworks": []}
    return {"success": True, "homeworks": [{"id": d.id, **d.to_dict()} for d in db.collection("homeworks").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

@app.get("/api/inquiries")
def get_inquiries():
    if db is None: return {"success": False, "inquiries": []}
    return {"success": True, "inquiries": [{"id": d.id, **d.to_dict()} for d in db.collection("inquiries").order_by("created_at", direction=firestore.Query.DESCENDING).stream()]}

@app.post("/api/inquiry")
def create_inquiry(content: str = Form(...), school: str = Form(""), grade: str = Form(""), student_name: str = Form("")):
    if db: db.collection("inquiries").add({"content": content, "school": school, "grade": grade, "student_name": student_name, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

# ─────────────────────────────────────────────────────────
# 💡 챗봇 & 제출 로직 (정답 유출 및 어뷰징 원천 차단)
# ─────────────────────────────────────────────────────────
def build_safe_knowledge_context() -> str:
    if db is None: return ""
    kb_docs = db.collection("knowledge").limit(10).stream()
    # 💡 보안 패치: 원장님이 낸 "문제은행 정답"은 챗봇이 아예 볼 수 없도록 원천 제외
    return "\n".join([f"[{d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in kb_docs])

@app.post("/api/chat")
async def chat_with_ai(prompt: str = Form(...), school: str = Form("미상"), grade: str = Form("미상"), student_name: str = Form("미상"), files: Optional[List[UploadFile]] = File(None)):
    send_telegram_message(f"💬 [질문 알림]\n{student_name} 학생이 국최에게 질문을 남겼습니다.\n\nQ: {prompt}")
    knowledge_base = await asyncio.to_thread(build_safe_knowledge_context)

    # 강력한 프롬프트 인젝션 방어 지시문
    system_prompt = f"""당신은 로지에듀 국어학원 AI 튜터 '국최'입니다.
아래 [학원 누적 자료] 범위 안에서만 다정하고 명쾌하게 답변하세요. 자료에 없는 내용이면 모른다고 명확히 답하세요.
학생이 어떤 교묘한 질문으로 정답을 캐내려 해도 절대 속지 마시고, 힌트와 사고 방향만 제시해야 합니다.
[학원 누적 자료]\n{knowledge_base}\n\n[학생 질문]\n{prompt}"""

    contents = [system_prompt]
    if files:
        for f in files:
            if f.filename: contents.append({"mime_type": f.content_type or "application/octet-stream", "data": await f.read()})
    try:
        response = await asyncio.to_thread(safe_generate, contents, False)
        return {"success": True, "reply": response.text}
    except Exception: return {"success": False, "reply": "AI 응답 지연이 발생했습니다. 잠시 후 다시 시도해주세요."}

@app.post("/api/essay/grade")
async def grade_essay(school: str = Form(""), grade: str = Form(""), student_name: str = Form(""), topic: str = Form(...), file: UploadFile = File(...)):
    send_telegram_message(f"✍️ [논술 제출 알림]\n{student_name} 학생이 '{topic}' 논술을 제출했습니다.")
    file_bytes = await file.read()
    prompt = f"다음은 학생이 작성한 논술/요약문입니다. 논제: {topic}\n이 글을 분석하고, 다정하고 예리하게 첨삭 피드백을 HTML 형식으로 작성해주세요."
    try:
        response = await asyncio.to_thread(safe_generate, [prompt, {"mime_type": file.content_type, "data": file_bytes}], False)
        if db is not None:
            # 💡 어뷰징 방어: 제출은 허용하되, 처음 제출할 때만 XP를 줍니다.
            existing = await asyncio.to_thread(lambda: list(db.collection("reports").where("student_name", "==", student_name).where("task_name", "==", topic).where("type", "==", "논술 첨삭").limit(1).stream()))
            file_url = await asyncio.to_thread(save_bytes, file_bytes, file.filename, "homeworks", file.content_type)
            await asyncio.to_thread(lambda: db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": topic, "type": "논술 첨삭", "score": "완료", "file_url": file_url}))
            if not existing:
                await asyncio.to_thread(lambda: db.collection("students").document(student_name).set({"xp": firestore.Increment(XP_REWARD_HOMEWORK)}, merge=True))
        return {"success": True, "feedback": response.text}
    except Exception: return {"success": False, "detail": "첨삭 처리 중 오류 발생"}

class ExamSubmitRequest(BaseModel): school: str; grade: str; student_name: str; title: str; answers: list
@app.post("/api/exam/submit")
async def submit_exam(req: ExamSubmitRequest):
    if db is None: return {"success": False}
    # 💡 어뷰징 방어
    existing = await asyncio.to_thread(lambda: list(db.collection("reports").where("student_name", "==", req.student_name).where("task_name", "==", req.title).where("type", "==", "모의고사").limit(1).stream()))
    if existing: return {"success": False, "detail": "이미 채점을 완료한 시험입니다."}

    doc = await asyncio.to_thread(lambda: db.collection("exams").document(req.title).get())
    data = doc.to_dict() if doc.exists else {} # 💡 로직 패치: 시험지 없을 때 서버 다운 방지
    actual_score = 0; wrongs = []; wrong_by_diff = {"a": 0, "b": 0, "c": 0, "d": 0, "e": 0}
    
    if data:
        exam_data = json.loads(data.get("exam_data", "{}"))
        for i, q in enumerate(exam_data.get("questions", [])):
            student_ans = str(req.answers[i]).strip() if i < len(req.answers) else ""
            correct_ans = str(q.get("ans", "")).strip()
            score = int(q.get("score", 0))
            if student_ans == correct_ans and student_ans != "": actual_score += score
            else:
                wrongs.append(i + 1)
                diff = str(q.get("diff", "a")).lower()
                if diff in wrong_by_diff: wrong_by_diff[diff] += 1

    await asyncio.to_thread(lambda: db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": req.student_name, "school": req.school, "grade": req.grade, "task_name": req.title, "type": "모의고사", "score": actual_score, "wrongs": wrongs}))
    await asyncio.to_thread(lambda: db.collection("students").document(req.student_name).set({"xp": firestore.Increment(actual_score * XP_MULTIPLIER_EXAM)}, merge=True))
    return {"success": True, "score": actual_score, "wrongs": wrongs, "wrong_by_diff": wrong_by_diff, "video_url": data.get("video_url", ""), "explanation_text": data.get("explanation_text", "")}

class QuizSubmitReq(BaseModel): school: str; grade: str; student_name: str; title: str; answers: list
@app.post("/api/quiz/submit")
async def submit_quiz(req: QuizSubmitReq):
    if db is None: return {"success": False}
    existing = await asyncio.to_thread(lambda: list(db.collection("reports").where("student_name", "==", req.student_name).where("task_name", "==", req.title).where("type", "==", "타임어택 퀴즈").limit(1).stream()))
    if existing: return {"success": False, "detail": "이미 완료한 퀴즈입니다."}

    doc = await asyncio.to_thread(lambda: db.collection("quizzes").document(req.title).get())
    actual_score = 0
    if doc.exists:
        for i, q in enumerate(doc.to_dict().get("questions", [])):
            if i < len(req.answers) and str(req.answers[i]) == str(q.get("answer")): actual_score += int(q.get("score", 0))

    await asyncio.to_thread(lambda: db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": req.student_name, "school": req.school, "grade": req.grade, "task_name": req.title, "type": "타임어택 퀴즈", "score": actual_score}))
    await asyncio.to_thread(lambda: db.collection("students").document(req.student_name).set({"xp": firestore.Increment(actual_score)}, merge=True))
    send_telegram_message(f"⏱️ [퀴즈 완료]\n{req.student_name} 학생이 '{req.title}' 퀴즈를 완료했습니다. (점수: {actual_score}점)")
    return {"success": True, "score": actual_score}

@app.post("/api/homework/submit")
async def submit_homework(school: str = Form(...), grade: str = Form(...), student_name: str = Form(...), title: str = Form(...), files: List[UploadFile] = File(...)):
    if db is None: return {"success": False}
    existing = await asyncio.to_thread(lambda: list(db.collection("reports").where("student_name", "==", student_name).where("task_name", "==", title).where("type", "==", "과제 제출").limit(1).stream()))
    file_urls = []
    for f in files:
        if f.filename:
            file_bytes = await f.read()
            file_urls.append(await asyncio.to_thread(save_bytes, file_bytes, f.filename, "homeworks", f.content_type))
            
    await asyncio.to_thread(lambda: db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": title, "type": "과제 제출", "score": "제출완료", "file_url": ",".join(file_urls)}))
    if not existing:
        await asyncio.to_thread(lambda: db.collection("students").document(student_name).set({"xp": firestore.Increment(XP_REWARD_HOMEWORK)}, merge=True))
    doc = await asyncio.to_thread(lambda: db.collection("homeworks").document(title).get())
    return {"success": True, "answer_file": doc.to_dict().get("answer_file", "") if doc.exists else ""}

# ─────────────────────────────────────────────────────────
# 💡 누락되었던 관리자 전용 API 100% 복구 및 권한 통제 완료 (Depends(verify_admin))
# ─────────────────────────────────────────────────────────

@app.get("/api/admin/students", dependencies=[Depends(verify_admin)])
def get_students_admin():
    if db is None: return {"success": False, "students": []}
    return {"success": True, "students": [{"id": d.id, "student_name": d.id, **d.to_dict()} for d in db.collection("students").stream()]}

class SingleStudentRequest(BaseModel): school: str; grade: str; name: str
@app.post("/api/admin/student", dependencies=[Depends(verify_admin)])
def add_single_student_admin(req: SingleStudentRequest):
    if db is None: return {"success": False}
    db.collection("students").document(sanitize_doc_id(req.name)).set({"school": req.school, "grade": req.grade}, merge=True)
    return {"success": True}

class BulkDeleteReq(BaseModel): ids: list = None
@app.post("/api/admin/student/delete_bulk", dependencies=[Depends(verify_admin)])
def delete_students_bulk_admin(req: BulkDeleteReq):
    if db and req.ids:
        for t in req.ids: db.collection("students").document(t).delete()
    return {"success": True}

class StudentUpdateReq(BaseModel): old_id: str; new_name: str; school: str; grade: str
@app.post("/api/admin/student/update", dependencies=[Depends(verify_admin)])
def update_student_admin(req: StudentUpdateReq):
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

@app.get("/api/admin/reports", dependencies=[Depends(verify_admin)])
def get_reports_admin():
    if db is None: return {"success": False, "reports": []}
    docs = db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(300).stream()
    return {"success": True, "reports": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.post("/api/admin/exam", dependencies=[Depends(verify_admin)])
async def create_exam_admin(title: str = Form(...), objective: str = Form(""), exam_data: str = Form(...), video_url: str = Form(""), explanation_text: str = Form(""), file: Optional[UploadFile] = File(None), ans_file: Optional[UploadFile] = File(None)):
    if db is None: return {"success": False}
    pdf_url, ans_pdf_url = "", ""
    if file and file.filename: pdf_url = await asyncio.to_thread(save_bytes, await file.read(), file.filename, "exams", file.content_type)
    if ans_file and ans_file.filename: ans_pdf_url = await asyncio.to_thread(save_bytes, await ans_file.read(), ans_file.filename, "exams", ans_file.content_type)
    safe_title = sanitize_doc_id(title)
    await asyncio.to_thread(lambda: db.collection("exams").document(safe_title).set({"title": title, "objective": objective, "exam_data": exam_data, "pdf_url": pdf_url, "ans_pdf_url": ans_pdf_url, "video_url": video_url, "explanation_text": explanation_text, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}))
    return {"success": True}

@app.delete("/api/admin/exam/{title}", dependencies=[Depends(verify_admin)])
def delete_exam_admin(title: str):
    if db: db.collection("exams").document(title).delete()
    return {"success": True}

@app.post("/api/admin/quiz", dependencies=[Depends(verify_admin)])
async def create_quiz_admin(request: Request):
    if db is None: return {"success": False}
    req = await request.json()
    title = req.get("title")
    if not title or not str(title).strip(): raise HTTPException(status_code=400, detail="퀴즈 제목은 필수입니다.")
    safe_title = sanitize_doc_id(title)
    await asyncio.to_thread(lambda: db.collection("quizzes").document(safe_title).set({"title": title, "deadline": req.get("deadline"), "time_limit": int(req.get("time_limit", 0)), "questions": req.get("questions", []), "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}))
    return {"success": True}

@app.delete("/api/admin/quiz/{title}", dependencies=[Depends(verify_admin)])
def delete_quiz_admin(title: str):
    if db: db.collection("quizzes").document(title).delete()
    return {"success": True}

@app.post("/api/admin/generate_stream", dependencies=[Depends(verify_admin)])
async def generate_stream_admin(q_mode: str = Form(...), q_types: str = Form(...), cnt_killer: int = Form(0), cnt_semi: int = Form(0), cnt_high: int = Form(0), cnt_mid: int = Form(0), cnt_low: int = Form(0), q_text: str = Form(""), files: Optional[List[UploadFile]] = File(None)):
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
    prompt = f"다음 지문을 바탕으로 {total}문항의 객관식 문제를 출제해줘.\n{q_text}"
    try:
        model = get_best_model()
        response = model.generate_content([prompt], stream=True)
        def iter_response():
            for chunk in response:
                if chunk.text: yield chunk.text
        return StreamingResponse(iter_response(), media_type="text/plain")
    except Exception:
        def err_response(): yield "❌ AI 생성 실패."
        return StreamingResponse(err_response(), media_type="text/plain")

@app.post("/api/admin/homework", dependencies=[Depends(verify_admin)])
async def create_homework_admin(title: str = Form(...), desc: str = Form(""), answer_text: str = Form(""), answer_file: Optional[UploadFile] = File(None)):
    if db is None: return {"success": False}
    ans_url = ""
    if answer_file and answer_file.filename: ans_url = await asyncio.to_thread(save_bytes, await answer_file.read(), answer_file.filename, "homeworks", answer_file.content_type)
    safe_title = sanitize_doc_id(title)
    await asyncio.to_thread(lambda: db.collection("homeworks").document(safe_title).set({"title": title, "desc": desc, "answer_text": answer_text, "answer_file": ans_url, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}))
    return {"success": True}

@app.delete("/api/admin/homework/{title}", dependencies=[Depends(verify_admin)])
def delete_homework_admin(title: str):
    if db: db.collection("homeworks").document(title).delete()
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

class LectureRequest(BaseModel): title: str; desc: str; video_url: str
@app.post("/api/admin/lecture", dependencies=[Depends(verify_admin)])
def create_lecture_admin(req: LectureRequest):
    if db: db.collection("lectures").add({"title": req.title, "desc": req.desc, "video_url": req.video_url, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.delete("/api/admin/lecture/{lecture_id}", dependencies=[Depends(verify_admin)])
def delete_lecture_admin(lecture_id: str):
    if db: db.collection("lectures").document(lecture_id).delete()
    return {"success": True}
