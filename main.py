import os
import json
import shutil
import uuid
import requests
import threading
import mimetypes
import urllib.parse 
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import firebase_admin
from firebase_admin import credentials, firestore, storage
import google.generativeai as genai
from datetime import datetime
import traceback

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

def safe_generate(contents, stream=False):
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key: raise Exception("API 키 오류")
    clean_key = api_key.strip().replace('"', '').replace("'", "")
    genai.configure(api_key=clean_key)
    for m_name in ['gemini-3.1-flash-preview', 'gemini-3.1-pro-preview']:
        try:
            model = genai.GenerativeModel(m_name)
            return model.generate_content(contents, stream=stream)
        except Exception as e:
            last_err = str(e)
            continue 
    raise Exception(f"AI 실패: {last_err}")

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
            send_telegram_message(f"🔔 [접속 알림]\n{req.school} {req.grade}학년 {req.student_name} 학생이 스마트 학습실에 로그인했습니다.")
            return {"success": True, "is_admin": False, "xp": current_xp, "reward": XP_REWARD_LOGIN if last_login != today else 0}
    return {"success": False, "detail": "명부에 이름이 없거나 학교/학년이 틀립니다."}

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
    doc = s_ref.get()
    if not doc.exists: return {"success": False}
    data = doc.to_dict()
    update_data = {"motto": motto, "avatar": avatar}
    current_xp = data.get("xp", 0)
    if not data.get("profile_setup_done"):
        current_xp += XP_REWARD_PROFILE
        update_data["xp"] = current_xp
        update_data["profile_setup_done"] = True
        
    if file and file.filename:
        file_bytes = await file.read()
        file_url = save_bytes(file_bytes, file.filename, "profiles", file.content_type)
        update_data["profile_image"] = file_url
        update_data["avatar"] = "" 
        
    s_ref.set(update_data, merge=True)
    return {"success": True}

@app.get("/api/admin/students")
def get_students():
    if db is None: return {"success": False, "students": []}
    return {"success": True, "students": [{"id": d.id, "student_name": d.id, **d.to_dict()} for d in db.collection("students").stream()]}

class SingleStudentRequest(BaseModel): school: str; grade: str; name: str
@app.post("/api/admin/student")
def add_single_student(req: SingleStudentRequest):
    if db: db.collection("students").document(req.name).set({"school": req.school, "grade": req.grade}, merge=True)
    return {"success": True}

class BulkStudentRequest(BaseModel): students: list
@app.post("/api/admin/student/bulk")
def add_students_bulk(req: BulkStudentRequest):
    if db:
        batch = db.batch()
        for s in req.students:
            doc_ref = db.collection("students").document(s.get("name"))
            batch.set(doc_ref, {"school": s.get("school"), "grade": s.get("grade")}, merge=True)
        batch.commit()
    return {"success": True}

class StudentUpdateReq(BaseModel): old_name: str = None; old_id: str = None; new_name: str; school: str; grade: str
@app.post("/api/admin/student/update")
def update_student(req: StudentUpdateReq):
    if db is None: return {"success": False}
    target = req.old_name or req.old_id
    if target:
        doc_ref = db.collection("students").document(target)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            data['school'] = req.school; data['grade'] = req.grade
            if target != req.new_name:
                db.collection("students").document(req.new_name).set(data)
                doc_ref.delete()
            else:
                doc_ref.set(data, merge=True)
    return {"success": True}

class BulkDeleteReq(BaseModel): names: list = None; ids: list = None
@app.post("/api/admin/student/delete_bulk")
def delete_students_bulk(req: BulkDeleteReq):
    if db:
        targets = req.names or req.ids or []
        for t in targets: db.collection("students").document(t).delete()
    return {"success": True}

@app.get("/api/admin/reports")
def get_reports():
    if db is None: return {"success": False, "reports": []}
    docs = db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(500).stream()
    return {"success": True, "reports": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.post("/api/chat")
async def chat_with_ai(prompt: str = Form(...), school: str = Form("미상"), grade: str = Form("미상"), student_name: str = Form("미상"), files: Optional[List[UploadFile]] = File(None)):
    send_telegram_message(f"💬 [질문 알림]\n{school} {grade}학년 {student_name} 학생이 국최에게 질문을 남겼습니다.\n\nQ: {prompt}")
    knowledge_base = ""
    if db:
        kb_docs = db.collection("knowledge").limit(10).stream()
        knowledge_base = "\n".join([f"[{d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in kb_docs])
        q_docs = db.collection("questions").order_by("created_at", direction=firestore.Query.DESCENDING).limit(10).stream()
        questions_base = "\n".join([f"[원장님 출제문제: {d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in q_docs])
        if questions_base: knowledge_base += f"\n\n[학원 최근 출제 문제 및 정답 데이터]\n{questions_base}"
    
    system_prompt = f"당신은 로지에듀 국어학원 AI 튜터 '국최'입니다. 반드시 아래 제공된 [학원 누적 자료]와 [출제 문제 정답] 내에서만 근거를 찾아 다정하고 명쾌하게 답변하세요. 만약 제공된 자료에 전혀 없는 내용이라면 '해당 내용은 아직 학원 자료에 업데이트되지 않았습니다. 원장님께 직접 질문해 주세요!'라고 대답하세요. 마크다운(**)을 적극 활용하여 파란색 굵은 글씨가 적용되도록 가독성을 높이세요.\n[학원 누적 자료]\n{knowledge_base}\n\n[학생 질문]\n{prompt}"
    contents = [system_prompt]
    if files:
        for f in files:
            if f.filename:
                file_bytes = await f.read()
                mime = f.content_type
                if "pdf" in f.filename.lower(): mime = "application/pdf"
                elif "png" in f.filename.lower(): mime = "image/png"
                elif "jpg" in f.filename.lower() or "jpeg" in f.filename.lower(): mime = "image/jpeg"
                contents.append({"mime_type": mime or "application/octet-stream", "data": file_bytes})
    try:
        response = safe_generate(contents, stream=False)
        return {"success": True, "reply": response.text}
    except Exception as e:
        return {"success": False, "reply": f"🚨 {str(e)}"}

@app.post("/api/essay/grade")
async def grade_essay(school: str = Form(""), grade: str = Form(""), student_name: str = Form(""), topic: str = Form(...), file: UploadFile = File(...)):
    send_telegram_message(f"✍️ [논술/요약 제출 알림]\n{school} {grade}학년 {student_name} 학생이 '{topic}' 논술을 제출했습니다.")
    try:
        file_bytes = await file.read()
        mime = file.content_type
        if "pdf" in file.filename.lower(): mime = "application/pdf"
        elif "png" in file.filename.lower(): mime = "image/png"
        elif "jpg" in file.filename.lower() or "jpeg" in file.filename.lower(): mime = "image/jpeg"
        prompt = f"다음은 학생이 작성한 논술/요약문입니다. 논제: {topic}\n이 글을 분석하고, 빨간펜 선생님처럼 다정하지만 예리하게 칭찬과 개선점, 첨삭 피드백을 HTML 형식(<b>, <br> 등 사용)으로 작성해주세요."
        response = safe_generate([prompt, {"mime_type": mime or "application/octet-stream", "data": file_bytes}], stream=False)
        file_url = save_bytes(file_bytes, file.filename, "homeworks", mime)
        if db:
            db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": topic, "type": "논술 첨삭", "score": "완료", "file_url": file_url})
            s_doc = db.collection("students").document(student_name).get()
            if s_doc.exists:
                xp = s_doc.to_dict().get("xp", 0) + XP_REWARD_HOMEWORK
                db.collection("students").document(student_name).set({"xp": xp}, merge=True)
        return {"success": True, "feedback": response.text}
    except Exception as e: return {"success": False, "detail": str(e)}

@app.post("/api/admin/knowledge")
async def add_knowledge(title: str = Form(...), content: str = Form(""), files: Optional[List[UploadFile]] = File(None)):
    try:
        if db is None: return {"success": False, "detail": "DB 연결 오류"}
        final_content = content
        if files:
            for file in files:
                if file.filename:
                    try:
                        file_bytes = await file.read()
                        mime = file.content_type
                        if "pdf" in file.filename.lower(): mime = "application/pdf"
                        elif "png" in file.filename.lower(): mime = "image/png"
                        elif "jpg" in file.filename.lower() or "jpeg" in file.filename.lower(): mime = "image/jpeg"
                        response = safe_generate(["이 문서의 핵심 지식을 요약해줘.", {"mime_type": mime or "application/pdf", "data": file_bytes}], stream=False)
                        final_content += f"\n\n[{file.filename} 분석]\n{response.text}"
                    except Exception as ai_err:
                        final_content += f"\n\n[{file.filename} 분석 오류: {str(ai_err)}]"
        db.collection("knowledge").add({"title": title, "content": final_content, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        return {"success": True}
    except Exception as e:
        return {"success": False, "detail": f"서버 내부 오류: {str(e)}"}

@app.post("/api/admin/knowledge/bulk")
async def add_knowledge_bulk(files: List[UploadFile] = File(...)):
    try:
        if db is None: return {"success": False, "detail": "DB 연결 오류"}
        processed = 0
        for file in files:
            if file.filename:
                try:
                    file_bytes = await file.read()
                    mime = file.content_type
                    if "pdf" in file.filename.lower(): mime = "application/pdf"
                    elif "png" in file.filename.lower(): mime = "image/png"
                    elif "jpg" in file.filename.lower() or "jpeg" in file.filename.lower(): mime = "image/jpeg"
                    response = safe_generate(["이 문서의 핵심 지식을 상세히 요약하고 핵심 개념을 정리해줘.", {"mime_type": mime or "application/octet-stream", "data": file_bytes}], stream=False)
                    title = file.filename.rsplit('.', 1)[0] 
                    db.collection("knowledge").add({"title": title, "content": f"[{title} 요약 및 핵심]\n{response.text}", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                    processed += 1
                except Exception as e: pass
        return {"success": True, "count": processed}
    except Exception as e:
        return {"success": False, "detail": f"서버 내부 오류: {str(e)}"}

@app.get("/api/knowledge")
def get_knowledge():
    if db is None: return {"success": False, "knowledge": []}
    docs = db.collection("knowledge").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    results = []
    for d in docs:
        data = d.to_dict()
        if "created_at" in data and not isinstance(data["created_at"], str):
            data["created_at"] = str(data["created_at"])
        results.append({"id": d.id, **data})
    return {"success": True, "knowledge": results}

@app.delete("/api/admin/knowledge/{k_id}")
def delete_knowledge(k_id: str):
    if db: db.collection("knowledge").document(k_id).delete()
    return {"success": True}

@app.post("/api/inquiry")
def create_inquiry(content: str = Form(...), school: str = Form(""), grade: str = Form(""), student_name: str = Form("")):
    if db: db.collection("inquiries").add({"content": content, "school": school, "grade": grade, "student_name": student_name, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.get("/api/inquiries")
def get_inquiries():
    if db is None: return {"success": False, "inquiries": []}
    docs = db.collection("inquiries").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "inquiries": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/inquiry/{i_id}")
def delete_inquiry(i_id: str):
    if db: db.collection("inquiries").document(i_id).delete()
    return {"success": True}

class QuestionSaveReq(BaseModel): title: str; content: str
@app.post("/api/admin/questions")
def save_question(req: QuestionSaveReq):
    if db: db.collection("questions").add({"title": req.title, "content": req.content, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.get("/api/admin/questions")
def get_questions():
    if db is None: return {"success": False, "questions": []}
    docs = db.collection("questions").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "questions": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/questions/{q_id}")
def delete_question(q_id: str):
    if db: db.collection("questions").document(q_id).delete()
    return {"success": True}

@app.post("/api/admin/homework")
async def create_homework(title: str = Form(...), desc: str = Form(""), answer_text: str = Form(""), answer_file: Optional[UploadFile] = File(None)):
    try:
        if db is None: return {"success": False, "detail": "DB 연결 오류"}
        ans_url = ""
        if answer_file and answer_file.filename:
            file_bytes = await answer_file.read()
            ans_url = save_bytes(file_bytes, answer_file.filename, "homeworks", answer_file.content_type)
        db.collection("homeworks").document(title).set({"title": title, "desc": desc, "answer_text": answer_text, "answer_file": ans_url, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        return {"success": True}
    except Exception as e:
        return {"success": False, "detail": f"서버 내부 오류: {str(e)}"}

@app.get("/api/homeworks")
def get_homeworks():
    if db is None: return {"success": False, "homeworks": []}
    docs = db.collection("homeworks").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "homeworks": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/homework/{title}")
def delete_homework(title: str):
    if db: db.collection("homeworks").document(title).delete()
    return {"success": True}

@app.post("/api/homework/submit")
async def submit_homework(school: str = Form(...), grade: str = Form(...), student_name: str = Form(...), title: str = Form(...), files: List[UploadFile] = File(...)):
    try:
        if db is None: return {"success": False, "detail": "DB 연결 오류"}
        send_telegram_message(f"📝 [과제 제출 알림]\n{school} {grade}학년 {student_name} 학생이 '{title}' 과제를 제출했습니다.")
        file_urls = []
        for file in files:
            if file.filename:
                file_bytes = await file.read()
                url = save_bytes(file_bytes, file.filename, "homeworks", file.content_type)
                file_urls.append(url)
        joined_urls = ",".join(file_urls)
        db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": title, "type": "과제 제출", "score": "제출완료", "file_url": joined_urls})
        s_doc = db.collection("students").document(student_name).get()
        if s_doc.exists:
            xp = s_doc.to_dict().get("xp", 0) + XP_REWARD_HOMEWORK
            db.collection("students").document(student_name).set({"xp": xp}, merge=True)
        doc = db.collection("homeworks").document(title).get()
        ans_data = doc.to_dict() if doc.exists else {}
        return {"success": True, "answer_file": ans_data.get("answer_file", "")}
    except Exception as e:
        return {"success": False, "detail": f"서버 내부 오류: {str(e)}"}

@app.post("/api/admin/board")
async def create_board_post(title: str = Form(...), desc: str = Form(""), file: Optional[UploadFile] = File(None)):
    try:
        if db is None: return {"success": False, "detail": "DB 연결 오류"}
        file_url = ""
        if file and file.filename:
            file_bytes = await file.read()
            file_url = save_bytes(file_bytes, file.filename, "board", file.content_type)
        db.collection("board").add({"title": title, "desc": desc, "file_url": file_url, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        return {"success": True}
    except Exception as e:
        return {"success": False, "detail": f"서버 내부 오류: {str(e)}"}

@app.get("/api/board")
def get_board():
    if db is None: return {"success": False, "posts": []}
    docs = db.collection("board").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "posts": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/board/{post_id}")
def delete_board_post(post_id: str):
    if db: db.collection("board").document(post_id).delete()
    return {"success": True}

class LectureRequest(BaseModel): title: str; desc: str; video_url: str
@app.post("/api/admin/lecture")
def create_lecture(req: LectureRequest):
    if db: db.collection("lectures").add({"title": req.title, "desc": req.desc, "video_url": req.video_url, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.get("/api/lectures")
def get_lectures():
    if db is None: return {"success": False, "lectures": []}
    docs = db.collection("lectures").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "lectures": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/lecture/{lecture_id}")
def delete_lecture(lecture_id: str):
    if db: db.collection("lectures").document(lecture_id).delete()
    return {"success": True}

@app.post("/api/admin/exam")
async def create_exam(title: str = Form(...), objective: str = Form(""), exam_data: str = Form(...), video_url: str = Form(""), explanation_text: str = Form(""), file: Optional[UploadFile] = File(None)):
    try:
        if db is None: return {"success": False, "detail": "DB 연결 오류"}
        pdf_url = ""
        if file and file.filename:
            file_bytes = await file.read()
            pdf_url = save_bytes(file_bytes, file.filename, "exams", file.content_type)
        db.collection("exams").document(title).set({"title": title, "objective": objective, "exam_data": exam_data, "pdf_url": pdf_url, "video_url": video_url, "explanation_text": explanation_text, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        return {"success": True}
    except Exception as e:
        return {"success": False, "detail": f"서버 내부 오류: {str(e)}"}

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
    actual_score = 0; wrong_by_diff = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}; wrongs = []; missed_ab_score = 0; missed_c_score = 0
    if doc.exists:
        data = doc.to_dict()
        exam_data = json.loads(data.get("exam_data", "{}"))
        questions = exam_data.get("questions", [])
        for i, q in enumerate(questions):
            student_ans = str(req.answers[i]).strip() if i < len(req.answers) else ""
            correct_ans = str(q.get("ans", "")).strip()
            score = int(q.get("score", 0))
            diff = q.get("diff", "C")
            if student_ans == correct_ans and student_ans != "": actual_score += score
            else:
                wrongs.append(i+1)
                if diff in wrong_by_diff: wrong_by_diff[diff] += 1
                if diff in ["A", "B"]: missed_ab_score += score
                elif diff == "C": missed_c_score += score
    potential_ab = actual_score + missed_ab_score
    potential_abc = potential_ab + missed_c_score
    db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": req.student_name, "school": req.school, "grade": req.grade, "task_name": req.title, "type": "모의고사", "score": actual_score, "wrongs": wrongs})
    s_doc = db.collection("students").document(req.student_name).get()
    if s_doc.exists:
        earned_xp = actual_score * XP_MULTIPLIER_EXAM
        xp = s_doc.to_dict().get("xp", 0) + earned_xp
        db.collection("students").document(req.student_name).set({"xp": xp}, merge=True)
    return {"success": True, "score": actual_score, "wrongs": wrongs, "wrong_by_diff": wrong_by_diff, "potential_ab": potential_ab, "potential_abc": potential_abc, "video_url": data.get("video_url", ""), "explanation_text": data.get("explanation_text", "")}

class QuizQuestion(BaseModel):
    q_text: str
    options: list
    answer: int
    score: int

class QuizCreateReq(BaseModel):
    title: str
    deadline: str
    time_limit: int
    questions: list

@app.post("/api/admin/quiz")
def create_quiz(req: QuizCreateReq):
    if db is None: return {"success": False}
    db.collection("quizzes").document(req.title).set({
        "title": req.title,
        "deadline": req.deadline,
        "time_limit": req.time_limit,
        "questions": [q.dict() for q in req.questions],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    return {"success": True}

@app.get("/api/quizzes")
def get_quizzes():
    if db is None: return {"success": False, "quizzes": []}
    docs = db.collection("quizzes").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "quizzes": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/quiz/{title}")
def delete_quiz(title: str):
    if db: db.collection("quizzes").document(title).delete()
    return {"success": True}

class QuizSubmitReq(BaseModel):
    school: str
    grade: str
    student_name: str
    title: str
    answers: list

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
    send_telegram_message(f"⏱️ [퀴즈 완료]\n{req.school} {req.grade}학년 {req.student_name} 학생이 '{req.title}' 퀴즈를 완료했습니다. (점수: {actual_score}점)")
    return {"success": True, "score": actual_score}

@app.post("/api/admin/generate_stream")
async def generate_stream(
    q_mode: str = Form(...), q_types: str = Form(...),
    cnt_killer: int = Form(0), cnt_semi: int = Form(0), cnt_high: int = Form(0), cnt_mid: int = Form(0), cnt_low: int = Form(0),
    q_text: str = Form(""), files: Optional[List[UploadFile]] = File(None)
):
    if q_mode == "분석":
        prompt = f"""당신은 '로지에듀 최준용 국어'의 수석 연구원입니다.
다음 지문을 학생이 이해하기 쉽게 핵심만 요약하고, 이 지문에서 출제될 수 있는 '핵심 출제 요소'를 분석해 주세요. 
마크다운(**)을 적극 활용하여 가독성 좋게 작성해 주세요.
[입력 자료]
{q_text}"""
    else:
        total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
        prompt = f"""당신은 '로지에듀 최준용 국어'의 수석 출제 위원입니다. 
가장 중요한 절대 규칙: 사용자가 지시한 총 {total}문항을 중간에 끊거나 요약하지 말고 '한 번에 모두' 정확히 출력해야 합니다.
지문 길이가 짧더라도 가능한 모든 출제 요소를 동원하여 지시된 문항 수를 무조건 100% 채우십시오.

[⚠️편집을 위한 엄격한 제약 사항⚠️]
1. 원본 지문에 없는 영어 단어나 알파벳(English)은 절대 사용하지 마십시오.
2. "문제를 이렇게 출제했습니다", "요청하신 난이도에 맞췄습니다" 같은 AI의 부연 설명, 인사말, 맺음말을 일절 출력하지 마십시오. 오직 결과물만 건조하게 출력하십시오.

[출제 지시 사항]
- 출제 유형: {q_types}
- 출제 난이도 및 문항 수: 총 {total}문항 (킬러 {cnt_killer}, 준킬러 {cnt_semi}, 상 {cnt_high}, 중 {cnt_mid}, 하 {cnt_low})
- 추가 요구사항: 출제된 문제 맨 아래에 [정답 및 상세 해설] 파트를 반드시 분리하여 모아 작성할 것.

[입력자료]
{q_text}"""
        
    contents = [prompt]
    if files:
        for f in files:
            if f.filename: 
                file_bytes = await f.read()
                mime = f.content_type
                if "pdf" in f.filename.lower(): mime = "application/pdf"
                elif "png" in f.filename.lower(): mime = "image/png"
                elif "jpg" in f.filename.lower() or "jpeg" in f.filename.lower(): mime = "image/jpeg"
                contents.append({"mime_type": mime or "application/octet-stream", "data": file_bytes})
    try:
        response = safe_generate(contents, stream=True)
        def iter_response():
            for chunk in response:
                if chunk.text: yield chunk.text
        return StreamingResponse(iter_response(), media_type="text/plain")
    except Exception as e:
        def err_response():
            yield f"❌ AI 생성 실패: {str(e)}"
        return StreamingResponse(err_response(), media_type="text/plain")
