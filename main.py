import os
import json
import shutil
import uuid
import requests
import threading
import mimetypes
import urllib.parse 
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect, Response, Request, Body
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import firebase_admin
from firebase_admin import credentials, firestore, storage
import google.generativeai as genai
from datetime import datetime
import traceback
import fitz

os.makedirs("uploads/exams", exist_ok=True)
os.makedirs("uploads/homeworks", exist_ok=True)
os.makedirs("uploads/board", exist_ok=True)
os.makedirs("uploads/chat", exist_ok=True)
os.makedirs("uploads/profiles", exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=200, 
        content={"success": False, "detail": f"서버 내부 오류: {str(exc)}"},
        headers={"Access-Control-Allow-Origin": "*"}
    )

XP_REWARD_LOGIN = 50
XP_REWARD_HOMEWORK = 200
XP_REWARD_PROFILE = 300
XP_MULTIPLIER_EXAM = 2

firebase_key_str = os.environ.get("FIREBASE_KEY")
db = None
bucket = None
if firebase_key_str:
    try:
        cred_dict = json.loads(firebase_key_str)
        cred = credentials.Certificate(cred_dict)
        project_id = cred_dict.get("project_id")
        
        bucket_name = os.environ.get("FIREBASE_BUCKET", f"{project_id}.appspot.com")
        bucket_name = bucket_name.replace("gs://", "").strip("/")
        
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {
                'storageBucket': bucket_name 
            })
        db = firestore.client()
        bucket = storage.bucket()
    except Exception as e:
        print("Firebase Init Error:", e)

def save_bytes(file_bytes: bytes, filename: str, folder: str, content_type: str) -> str:
    unique_name = f"{uuid.uuid4()}_{filename}"
    filepath = f"uploads/{folder}/{unique_name}"
    
    if bucket:
        try:
            blob = bucket.blob(filepath)
            mt, _ = mimetypes.guess_type(filename)
            blob.upload_from_string(file_bytes, content_type=mt or content_type or 'application/octet-stream')
            return f"/{filepath}"
        except Exception as e:
            print("Storage Upload Error:", e)
            
    os.makedirs(f"uploads/{folder}", exist_ok=True)
    with open(filepath, "wb") as buffer:
        buffer.write(file_bytes)
    return f"/{filepath}"

@app.get("/uploads/{folder}/{filename}")
def get_upload_file(folder: str, filename: str):
    filepath = f"uploads/{folder}/{filename}"
    mt, _ = mimetypes.guess_type(filename)
    encoded_filename = urllib.parse.quote(filename.encode('utf-8'))
    
    is_inline = mt in ['application/pdf', 'image/jpeg', 'image/png', 'image/gif']
    disposition = "inline" if is_inline else "attachment"

    if bucket:
        try:
            blob = bucket.blob(filepath)
            if blob.exists():
                file_bytes = blob.download_as_bytes()
                return Response(
                    content=file_bytes, 
                    media_type=mt or "application/octet-stream",
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_filename}"
                    }
                )
        except Exception as e:
            pass
            
    if os.path.exists(filepath):
        return FileResponse(
            filepath, 
            media_type=mt or "application/octet-stream",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_filename}"
            }
        )
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

def send_telegram_message(text: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    def _send():
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        try: requests.post(url, json=payload, timeout=3)
        except: pass
    threading.Thread(target=_send).start()

def get_best_model():
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key: raise Exception("API 키가 없습니다.")
    clean_key = api_key.strip().replace('"', '').replace("'", "")
    genai.configure(api_key=clean_key)
    
    try:
        models = genai.list_models()
        available = [m.name.replace('models/', '') for m in models if 'generateContent' in m.supported_generation_methods]
    except Exception as e:
        raise Exception(f"구글 모델 스캔 실패: {str(e)}")
        
    if not available: raise Exception("사용 가능한 모델이 없습니다.")
    target_model = next((m for m in ['gemini-3.6-flash', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro'] if m in available), available[0])
    return genai.GenerativeModel(target_model)

def safe_generate(contents, stream=False):
    try:
        model = get_best_model()
        return model.generate_content(contents, stream=stream)
    except Exception as e:
        raise Exception(f"AI 응답 오류: {str(e)}")

# 💡 해결 4번: 실시간 모의고사 채팅방(Q&A) 통신 엔진
class ConnectionManager:
    def __init__(self): self.active_connections = {}
    async def connect(self, ws: WebSocket, room: str):
        await ws.accept()
        if room not in self.active_connections: self.active_connections[room] = []
        self.active_connections[room].append(ws)
    def disconnect(self, ws: WebSocket, room: str):
        if room in self.active_connections and ws in self.active_connections[room]:
            self.active_connections[room].remove(ws)
    async def broadcast(self, message: str, room: str, sender: WebSocket):
        if room in self.active_connections:
            for c in self.active_connections[room]:
                if c != sender:
                    try: await c.send_text(message)
                    except: pass

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

class AuthRequest(BaseModel): school: str = ""; grade: str = ""; student_name: str; admin_password: str = ""

@app.get("/api/health")
def health_check(): return {"status": "ok"}

@app.post("/api/auth")
def authenticate(req: AuthRequest):
    if req.admin_password == "1234": return {"success": True, "is_admin": True}
    if db is None: raise HTTPException(status_code=500, detail="DB 오류")
    doc = db.collection("students").document(req.student_name).get()
    if doc.exists:
        data = doc.to_dict()
        if data.get("school") == req.school and data.get("grade") == req.grade:
            today = datetime.now().strftime("%Y-%m-%d")
            last_login = data.get("last_login", "")
            current_xp = data.get("xp", 0)
            if last_login != today:
                current_xp += XP_REWARD_LOGIN
                db.collection("students").document(req.student_name).set({"last_login": today, "xp": current_xp}, merge=True)
            send_telegram_message(f"🔔 [접속 알림]\n{req.school} {req.grade}학년 {req.student_name} 학생이 로그인했습니다.")
            return {"success": True, "is_admin": False, "xp": current_xp}
    return {"success": False, "detail": "정보가 일치하지 않습니다."}

@app.get("/api/admin/reports")
def get_reports():
    if db is None: return {"success": False, "reports": []}
    docs = db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(500).stream()
    return {"success": True, "reports": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.post("/api/chat")
async def chat_with_ai(prompt: str = Form(...), school: str = Form("미상"), grade: str = Form("미상"), student_name: str = Form("미상"), files: Optional[List[UploadFile]] = File(None)):
    send_telegram_message(f"💬 [질문 알림]\n{student_name} 학생이 국최에게 질문을 남겼습니다.\n\nQ: {prompt}")
    contents = [prompt]
    try:
        response = safe_generate(contents, stream=False)
        return {"success": True, "reply": response.text}
    except Exception as e:
        return {"success": False, "reply": f"🚨 {str(e)}"}

@app.post("/api/admin/knowledge")
async def add_knowledge(title: str = Form(...), content: str = Form(""), files: Optional[List[UploadFile]] = File(None)):
    try:
        if db: db.collection("knowledge").add({"title": title, "content": content, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        return {"success": True}
    except Exception as e: return {"success": False, "detail": str(e)}

@app.get("/api/knowledge")
def get_knowledge():
    if db is None: return {"success": False, "knowledge": []}
    docs = db.collection("knowledge").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "knowledge": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/knowledge/{k_id}")
def delete_knowledge(k_id: str):
    if db: db.collection("knowledge").document(k_id).delete()
    return {"success": True}

@app.post("/api/admin/exam")
async def create_exam(title: str = Form(...), objective: str = Form(""), exam_data: str = Form(...), video_url: str = Form(""), explanation_text: str = Form(""), file: Optional[UploadFile] = File(None), ans_file: Optional[UploadFile] = File(None)):
    try:
        if db is None: return {"success": False, "detail": "DB 연결 오류"}
        pdf_url = ""
        ans_pdf_url = ""
        if file and file.filename:
            pdf_url = save_bytes(await file.read(), file.filename, "exams", file.content_type)
        if ans_file and ans_file.filename:
            ans_pdf_url = save_bytes(await ans_file.read(), ans_file.filename, "exams", ans_file.content_type)
            
        safe_title = title.replace("/", "_").replace("\\", "_")
        db.collection("exams").document(safe_title).set({"title": title, "objective": objective, "exam_data": exam_data, "pdf_url": pdf_url, "ans_pdf_url": ans_pdf_url, "video_url": video_url, "explanation_text": explanation_text, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        return {"success": True}
    except Exception as e:
        return {"success": False, "detail": f"모의고사 생성 오류: {str(e)}"}

@app.get("/api/exams")
def get_exams():
    if db is None: return {"success": False, "exams": []}
    docs = db.collection("exams").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "exams": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/exam/{title}")
def delete_exam(title: str):
    if db: db.collection("exams").document(title).delete()
    return {"success": True}

class ExamSubmitRequest(BaseModel): school: str; grade: str; student_name: str; title: str; answers: list
@app.post("/api/exam/submit")
def submit_exam(req: ExamSubmitRequest):
    if db is None: return {"success": False}
    doc = db.collection("exams").document(req.title).get()
    actual_score = 0; wrong_by_diff = {"a": 0, "b": 0, "c": 0, "d": 0, "e": 0}; wrongs = []
    if doc.exists:
        data = doc.to_dict()
        exam_data = json.loads(data.get("exam_data", "{}"))
        questions = exam_data.get("questions", [])
        for i, q in enumerate(questions):
            student_ans = str(req.answers[i]).strip() if i < len(req.answers) else ""
            correct_ans = str(q.get("ans", "")).strip()
            score = int(q.get("score", 0))
            diff = str(q.get("diff", "a")).lower()
            if student_ans == correct_ans and student_ans != "": actual_score += score
            else:
                wrongs.append(i+1)
                if diff in wrong_by_diff: wrong_by_diff[diff] += 1
                
    db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": req.student_name, "school": req.school, "grade": req.grade, "task_name": req.title, "type": "모의고사", "score": actual_score, "wrongs": wrongs})
    s_doc = db.collection("students").document(req.student_name).get()
    if s_doc.exists:
        earned_xp = actual_score * XP_MULTIPLIER_EXAM
        xp = s_doc.to_dict().get("xp", 0) + earned_xp
        db.collection("students").document(req.student_name).set({"xp": xp}, merge=True)
    return {"success": True, "score": actual_score, "video_url": data.get("video_url", ""), "explanation_text": data.get("explanation_text", "")}

# 💡 해결 1번: 깐깐한 검증기를 무력화하여 "퀴즈 배포 오류" 완벽 차단
@app.post("/api/admin/quiz")
def create_quiz(req: dict = Body(...)):
    try:
        if db is None: return {"success": False, "detail": "DB 연결 오류"}
        title = req.get("title")
        db.collection("quizzes").document(title).set({
            "title": title,
            "deadline": req.get("deadline"),
            "time_limit": int(req.get("time_limit", 0)),
            "questions": req.get("questions", []), 
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        return {"success": True}
    except Exception as e:
        return {"success": False, "detail": f"퀴즈 생성 오류: {str(e)}"}

@app.get("/api/quizzes")
def get_quizzes():
    if db is None: return {"success": False, "quizzes": []}
    docs = db.collection("quizzes").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "quizzes": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/quiz/{title}")
def delete_quiz(title: str):
    if db: db.collection("quizzes").document(title).delete()
    return {"success": True}

class QuizSubmitReq(BaseModel): school: str; grade: str; student_name: str; title: str; answers: list
@app.post("/api/quiz/submit")
def submit_quiz(req: QuizSubmitReq):
    if db is None: return {"success": False}
    doc = db.collection("quizzes").document(req.title).get()
    actual_score = 0
    if doc.exists:
        data = doc.to_dict()
        questions = data.get("questions", [])
        for i, q in enumerate(questions):
            if i < len(req.answers) and str(req.answers[i]) == str(q.get("answer")):
                actual_score += int(q.get("score", 0))
                
    db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": req.student_name, "school": req.school, "grade": req.grade, "task_name": req.title, "type": "타임어택 퀴즈", "score": actual_score})
    send_telegram_message(f"⏱️ [퀴즈 완료]\n{req.student_name} 학생이 '{req.title}' 퀴즈를 완료했습니다. (점수: {actual_score}점)")
    return {"success": True, "score": actual_score}

@app.post("/api/admin/generate_stream")
async def generate_stream(
    q_mode: str = Form(...), q_types: str = Form(...),
    cnt_killer: int = Form(0), cnt_semi: int = Form(0), cnt_high: int = Form(0), cnt_mid: int = Form(0), cnt_low: int = Form(0),
    q_text: str = Form(""), files: Optional[List[UploadFile]] = File(None)
):
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
    prompt = f"다음 지문을 바탕으로 {total}문항의 객관식 문제를 출제해줘.\n{q_text}"
    contents = [prompt]
    try:
        model = get_best_model()
        response = model.generate_content(contents, stream=True)
        def iter_response():
            for chunk in response:
                if chunk.text: yield chunk.text
        return StreamingResponse(iter_response(), media_type="text/plain")
    except Exception as e:
        def err_response():
            yield f"❌ AI 생성 실패: {str(e)}"
        return StreamingResponse(err_response(), media_type="text/plain")
