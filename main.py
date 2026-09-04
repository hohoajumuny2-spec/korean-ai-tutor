import os
import json
import shutil
import uuid
import mimetypes
import base64
import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

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

@app.get("/uploads/{folder}/{filename}")
def get_upload_file(folder: str, filename: str):
    filepath = f"uploads/{folder}/{filename}"
    if os.path.exists(filepath):
        response = FileResponse(filepath)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response
    raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

firebase_key_str = os.environ.get("FIREBASE_KEY")
db = None
if firebase_key_str:
    try:
        cred_dict = json.loads(firebase_key_str)
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as e:
        pass

# ===============================================
# 💡 다이렉트 통신망(REST API) 자동 탐색/우회 엔진 완벽 적용
# ===============================================
def call_gemini_api(contents, stream=False):
    gemini_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        raise Exception("API 키가 설정되지 않았습니다.")
    
    formatted_parts = []
    for item in contents:
        if isinstance(item, str):
            formatted_parts.append({"text": item})
        elif isinstance(item, dict):
            b64_data = base64.b64encode(item['data']).decode('utf-8')
            formatted_parts.append({"inline_data": {"mime_type": item['mime_type'], "data": b64_data}})
    
    payload = {"contents": [{"parts": formatted_parts}]}
    
    # 💡 최신 모델이 404 에러로 튕기면 즉시 구형 모델 주소로 갈아탑니다.
    models_to_try = ['gemini-1.5-flash', 'gemini-1.0-pro', 'gemini-pro']
    last_err = ""
    
    for m_name in models_to_try:
        if stream:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:streamGenerateContent?alt=sse&key={gemini_key}"
            res = requests.post(url, json=payload, stream=True)
            if res.status_code == 200:
                return res
            else:
                last_err = res.text
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={gemini_key}"
            res = requests.post(url, json=payload)
            if res.status_code == 200:
                try:
                    return res.json()["candidates"][0]["content"]["parts"][0]["text"]
                except Exception:
                    last_err = "API 응답 형식을 읽을 수 없습니다."
            else:
                last_err = res.text
                
    # 모든 모델 주소가 거부되었을 때만 에러 발생
    raise Exception(f"구글 API 거부 (모든 모델 접속 불가). 마지막 에러: {last_err}")

# 실시간 모의고사 웹소켓
class ConnectionManager:
    def __init__(self):
        self.active_connections = {}
    async def connect(self, ws: WebSocket, room: str):
        await ws.accept()
        if room not in self.active_connections:
            self.active_connections[room] = []
        self.active_connections[room].append(ws)
    def disconnect(self, ws: WebSocket, room: str):
        if room in self.active_connections and ws in self.active_connections[room]:
            self.active_connections[room].remove(ws)
    async def broadcast(self, message: str, room: str, sender: WebSocket):
        if room in self.active_connections:
            for connection in self.active_connections[room]:
                if connection != sender:
                    try: await connection.send_text(message)
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


# ===============================================
# API 엔드포인트
# ===============================================

class AuthRequest(BaseModel):
    school: str = ""
    grade: str = ""
    student_name: str
    admin_password: str = ""

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
            
            return {"success": True, "is_admin": False, "xp": current_xp, "reward": XP_REWARD_LOGIN if last_login != today else 0}
    return {"success": False, "detail": "명부에 이름이 없거나 학교/학년이 틀립니다."}

@app.get("/api/student/profile/{student_name}")
def get_student_profile(student_name: str):
    if db is None: return {"success": False}
    doc = db.collection("students").document(student_name).get()
    if not doc.exists: return {"success": False}
    reports = [r.to_dict() for r in db.collection("reports").where("student_name", "==", student_name).order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(20).stream()]
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
        filename = f"{uuid.uuid4()}_{file.filename}"
        with open(f"uploads/profiles/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        update_data["profile_image"] = f"/uploads/profiles/{filename}"
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
async def chat_with_ai(prompt: str = Form(...), files: Optional[List[UploadFile]] = File(None)):
    knowledge_base = ""
    if db:
        kb_docs = db.collection("knowledge").limit(10).stream()
        knowledge_base = "\n".join([f"[{d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in kb_docs])
    
    system_prompt = f"당신은 로지에듀 국어학원 AI 튜터 '국최'입니다. 아래 [학원 누적 자료]를 최우선 참고하여 답변하세요.\n[학원 누적 자료]\n{knowledge_base}\n\n[학생 질문]\n{prompt}"
    contents = [system_prompt]
    
    if files:
        for f in files:
            if f.filename:
                mime = f.content_type
                if "pdf" in f.filename.lower(): mime = "application/pdf"
                elif "png" in f.filename.lower(): mime = "image/png"
                elif "jpg" in f.filename.lower() or "jpeg" in f.filename.lower(): mime = "image/jpeg"
                contents.append({"mime_type": mime or "application/octet-stream", "data": await f.read()})
    try:
        reply_text = call_gemini_api(contents)
        return {"success": True, "reply": reply_text}
    except Exception as e:
        return {"success": False, "reply": f"AI 분석 중 오류가 발생했습니다: {str(e)}"}

@app.post("/api/essay/grade")
async def grade_essay(school: str = Form(""), grade: str = Form(""), student_name: str = Form(""), topic: str = Form(...), file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        mime = file.content_type
        if "pdf" in file.filename.lower(): mime = "application/pdf"
        elif "png" in file.filename.lower(): mime = "image/png"
        elif "jpg" in file.filename.lower() or "jpeg" in file.filename.lower(): mime = "image/jpeg"

        prompt = f"다음은 학생이 작성한 논술/요약문입니다. 논제: {topic}\n이 글을 분석하고, 빨간펜 선생님처럼 다정하지만 예리하게 칭찬과 개선점, 첨삭 피드백을 HTML 형식(<b>, <br> 등 사용)으로 작성해주세요."
        
        res_text = call_gemini_api([prompt, {"mime_type": mime or "application/octet-stream", "data": file_bytes}])
        
        filename = f"{uuid.uuid4()}_{file.filename}"
        with open(f"uploads/homeworks/{filename}", "wb") as buffer: buffer.write(file_bytes)
        
        if db:
            db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": topic, "type": "논술 첨삭", "score": "완료", "file_url": f"/uploads/homeworks/{filename}"})
            s_doc = db.collection("students").document(student_name).get()
            if s_doc.exists:
                xp = s_doc.to_dict().get("xp", 0) + XP_REWARD_HOMEWORK
                db.collection("students").document(student_name).set({"xp": xp}, merge=True)
            
        return {"success": True, "feedback": res_text}
    except Exception as e: return {"success": False, "detail": str(e)}

@app.post("/api/admin/knowledge")
async def add_knowledge(title: str = Form(...), content: str = Form(""), files: Optional[List[UploadFile]] = File(None)):
    if db is None: return {"success": False}
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
                    
                    res_text = call_gemini_api(["이 문서의 핵심 지식을 요약해줘.", {"mime_type": mime or "application/pdf", "data": file_bytes}])
                    final_content += f"\n\n[{file.filename} 분석]\n{res_text}"
                except Exception: pass
                
    db.collection("knowledge").add({"title": title, "content": final_content, "created_at": datetime.now()})
    return {"success": True}

@app.get("/api/knowledge")
def get_knowledge():
    if db is None: return {"success": False, "knowledge": []}
    docs = db.collection("knowledge").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "knowledge": [{"id": d.id, **d.to_dict()} for d in docs]}

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
    if db is None: return {"success": False}
    ans_url = ""
    if answer_file and answer_file.filename:
        filename = f"{uuid.uuid4()}_{answer_file.filename}"
        with open(f"uploads/homeworks/{filename}", "wb") as buffer: shutil.copyfileobj(answer_file.file, buffer)
        ans_url = f"/uploads/homeworks/{filename}"
    db.collection("homeworks").document(title).set({"title": title, "desc": desc, "answer_text": answer_text, "answer_file": ans_url, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

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
async def submit_homework(school: str = Form(...), grade: str = Form(...), student_name: str = Form(...), title: str = Form(...), file: UploadFile = File(...)):
    if db is None: return {"success": False}
    filename = f"{uuid.uuid4()}_{file.filename}"
    with open(f"uploads/homeworks/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": title, "type": "과제 제출", "score": "제출완료", "file_url": f"/uploads/homeworks/{filename}"})
    
    s_doc = db.collection("students").document(student_name).get()
    if s_doc.exists:
        xp = s_doc.to_dict().get("xp", 0) + XP_REWARD_HOMEWORK
        db.collection("students").document(student_name).set({"xp": xp}, merge=True)
        
    doc = db.collection("homeworks").document(title).get()
    ans_data = doc.to_dict() if doc.exists else {}
    return {"success": True, "answer_file": ans_data.get("answer_file", "")}

@app.post("/api/admin/board")
async def create_board_post(title: str = Form(...), desc: str = Form(""), file: Optional[UploadFile] = File(None)):
    if db is None: return {"success": False}
    file_url = ""
    if file and file.filename:
        filename = f"{uuid.uuid4()}_{file.filename}"
        with open(f"uploads/board/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        file_url = f"/uploads/board/{filename}"
    db.collection("board").add({"title": title, "desc": desc, "file_url": file_url, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

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
    if db is None: return {"success": False}
    pdf_url = ""
    if file and file.filename:
        filename = f"{uuid.uuid4()}_{file.filename}"
        with open(f"uploads/exams/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        pdf_url = f"/uploads/exams/{filename}"
    db.collection("exams").document(title).set({"title": title, "objective": objective, "exam_data": exam_data, "pdf_url": pdf_url, "video_url": video_url, "explanation_text": explanation_text, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

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

@app.post("/api/admin/generate_stream")
async def generate_stream(
    q_mode: str = Form(...), q_types: str = Form(...),
    cnt_killer: int = Form(0), cnt_semi: int = Form(0), cnt_high: int = Form(0), cnt_mid: int = Form(0), cnt_low: int = Form(0),
    q_text: str = Form(""), files: Optional[List[UploadFile]] = File(None)
):
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
    prompt = f"로지에듀 국어학원 수석 출제 위원입니다. 오류 없는 문제를 출제하세요.\n- 유형: {q_types}\n- 총 {total}문항\n[입력자료]\n{q_text}"
    contents = [prompt]
    
    if files:
        for f in files:
            if f.filename: 
                mime = f.content_type
                if "pdf" in f.filename.lower(): mime = "application/pdf"
                elif "png" in f.filename.lower(): mime = "image/png"
                elif "jpg" in f.filename.lower() or "jpeg" in f.filename.lower(): mime = "image/jpeg"
                contents.append({"mime_type": mime or "application/octet-stream", "data": await f.read()})
            
    try:
        response = call_gemini_api(contents, stream=True)
        def iter_response():
            if response.status_code != 200:
                yield f"❌ API 서버 통신 오류: {response.text}"
                return
            for line in response.iter_lines():
                if line:
                    decoded = line.decode('utf-8')
                    if decoded.startswith('data: '):
                        try:
                            data = json.loads(decoded[6:])
                            yield data["candidates"][0]["content"]["parts"][0]["text"]
                        except Exception: pass
        return StreamingResponse(iter_response(), media_type="text/plain")
    except Exception as e:
        def err_response():
            yield f"❌ AI 출제 실패: {str(e)}"
        return StreamingResponse(err_response(), media_type="text/plain")
