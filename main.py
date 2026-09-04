import os
import json
import shutil
import uuid
import mimetypes
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from datetime import datetime

os.makedirs("uploads/exams", exist_ok=True)
os.makedirs("uploads/homeworks", exist_ok=True)
os.makedirs("uploads/board", exist_ok=True)
os.makedirs("uploads/chat", exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def send_telegram_msg(text: str):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=5)
    except Exception as e: pass

class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()
        if room_id not in self.active_connections: self.active_connections[room_id] = []
        self.active_connections[room_id].append(websocket)

    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.active_connections:
            try: self.active_connections[room_id].remove(websocket)
            except ValueError: pass

    async def broadcast(self, message: str, room_id: str):
        if room_id in self.active_connections:
            for connection in self.active_connections[room_id]:
                try: await connection.send_text(message)
                except: pass

manager = ConnectionManager()

@app.websocket("/ws/exam/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await manager.connect(websocket, room_id)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(data, room_id)
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)

@app.get("/uploads/{folder}/{filename}")
def get_upload_file(folder: str, filename: str):
    filepath = f"uploads/{folder}/{filename}"
    if os.path.exists(filepath):
        mt, _ = mimetypes.guess_type(filepath)
        return FileResponse(filepath, media_type=mt or "application/octet-stream", headers={"Content-Disposition": "inline"})
    raise HTTPException(status_code=404, detail="파일 없음")

firebase_key_str = os.environ.get("FIREBASE_KEY")
db = None
if firebase_key_str:
    try:
        cred_dict = json.loads(firebase_key_str)
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps: firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as e: print("Firebase Error:", e)

gemini_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
model = None
if gemini_key:
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

class AuthRequest(BaseModel): school: str = ""; grade: str = ""; student_name: str; admin_password: str = ""
class BulkStudentRequest(BaseModel): students: list
class SingleStudentRequest(BaseModel): school: str; grade: str; name: str
class UpdateStudentRequest(BaseModel): old_id: str; new_name: str; school: str; grade: str
class BulkDeleteRequest(BaseModel): ids: list
class LectureRequest(BaseModel): title: str; desc: str; video_url: str
class ExamSubmitRequest(BaseModel): school: str; grade: str; student_name: str; title: str; answers: list
class TwinRequest(BaseModel): diff: str; score: int
class QuestionArchiveRequest(BaseModel): title: str; content: str

@app.get("/api/health")
def health_check(): return {"status": "ok"}

@app.post("/api/auth")
def authenticate(req: AuthRequest):
    if req.admin_password == "1234": return {"success": True, "is_admin": True}
    if db is None: raise HTTPException(status_code=500, detail="DB 오류")
    
    new_doc_id = f"{req.school}_{req.grade}_{req.student_name}"
    doc = db.collection("students").document(new_doc_id).get()
    
    if doc.exists:
        send_telegram_msg(f"🔔 [접속] {req.school} {req.grade} {req.student_name} 학생이 로그인했습니다.")
        db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": req.student_name, "school": req.school, "grade": req.grade, "task_name": "스마트 학습실 접속", "type": "로그인", "score": "접속됨"})
        return {"success": True, "is_admin": False}
        
    old_doc = db.collection("students").document(req.student_name).get()
    if old_doc.exists:
        data = old_doc.to_dict()
        if data.get("school") == req.school and data.get("grade") == req.grade:
            send_telegram_msg(f"🔔 [접속] {req.school} {req.grade} {req.student_name} 학생이 로그인했습니다.")
            db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": req.student_name, "school": req.school, "grade": req.grade, "task_name": "스마트 학습실 접속", "type": "로그인", "score": "접속됨"})
            return {"success": True, "is_admin": False}
            
    return {"success": False, "detail": "명단 정보 불일치"}

@app.post("/api/inquiry")
async def submit_inquiry(school: str=Form(""), grade: str=Form(""), student_name: str=Form(""), content: str=Form(...)):
    send_telegram_msg(f"📞 [문의] {school} {grade} {student_name}\n- {content}")
    if db: db.collection("inquiries").add({"school": school, "grade": grade, "student_name": student_name, "content": content, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.get("/api/inquiries")
def get_inquiries():
    if db is None: return {"success": False, "inquiries": []}
    docs = db.collection("inquiries").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "inquiries": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/inquiry/{inq_id}")
def delete_inquiry(inq_id: str):
    if db: db.collection("inquiries").document(inq_id).delete()
    return {"success": True}

@app.post("/api/chat")
async def chat_with_ai(school: str=Form(""), grade: str=Form(""), student_name: str=Form(""), prompt: str=Form(...), files: Optional[List[UploadFile]]=File(None)):
    if model is None: return StreamingResponse(iter(["AI 오류"]), media_type="text/plain")
    send_telegram_msg(f"💬 [질문] {school} {grade} {student_name}\n- {prompt}")

    kb = ""
    if db:
        kb_docs = db.collection("knowledge").limit(10).stream()
        kb = "\n".join([f"[{d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in kb_docs])
    sys_prompt = f"당신은 국어 AI 튜터 '국최'입니다. [자료] 참고하여 답변하세요.\n[자료]\n{kb}\n\n[질문]\n{prompt}"
    contents = [sys_prompt]
    
    if files:
        for f in files:
            if f.filename: 
                mime = f.content_type
                if "pdf" in f.filename.lower(): mime = "application/pdf"
                elif "png" in f.filename.lower(): mime = "image/png"
                elif "jpg" in f.filename.lower() or "jpeg" in f.filename.lower(): mime = "image/jpeg"
                contents.append({"mime_type": mime or "application/octet-stream", "data": await f.read()})
    try:
        response = model.generate_content(contents, stream=True)
        def iter_response():
            for chunk in response:
                if chunk.text: yield chunk.text
        return StreamingResponse(iter_response(), media_type="text/plain")
    except Exception as e: return StreamingResponse(iter([f"오류: {str(e)}"]), media_type="text/plain")

@app.post("/api/essay/grade")
async def grade_essay(school: str=Form(...), grade: str=Form(...), student_name: str=Form(...), topic: str=Form(...), file: UploadFile=File(...)):
    if model is None: return {"success": False, "detail": "AI 오류"}
    try:
        file_bytes = await file.read()
        mime = file.content_type
        if "pdf" in file.filename.lower(): mime = "application/pdf"
        elif "png" in file.filename.lower(): mime = "image/png"
        elif "jpg" in file.filename.lower() or "jpeg" in file.filename.lower(): mime = "image/jpeg"
        
        prompt = f"""당신은 국어 논술 강사입니다. 첨부된 논술문을 첨삭하세요.
        [주제]: {topic}
        HTML 형식으로 작성. <span style="color:#ef4444;">[첨삭: 고친 내용]</span> 태그 필수.
        <h3 style="color:#3b82f6;">📝 원문 및 첨삭</h3><p>(원문)</p>
        <h3 style="color:#3b82f6;">📊 총평 및 점수</h3><p>(총평)</p>
        <h3 style="color:#3b82f6;">✨ 모범 답안</h3><p>(답안)</p>"""
        res = model.generate_content([prompt, {"mime_type": mime or "application/pdf", "data": file_bytes}])
        if db:
            db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": f"AI 첨삭: {topic[:10]}...", "type": "논술 첨삭", "score": "첨삭완료"})
        send_telegram_msg(f"📝 [논술 제출] {school} {grade} {student_name}\n- {topic}")
        return {"success": True, "feedback": res.text}
    except Exception as e: return {"success": False, "detail": str(e)}

@app.get("/api/admin/students")
def get_students():
    if db is None: return {"success": False, "students": []}
    students = []
    for d in db.collection("students").stream():
        data = d.to_dict()
        students.append({"id": d.id, "school": data.get("school", ""), "grade": data.get("grade", ""), "student_name": data.get("student_name", d.id)})
    return {"success": True, "students": students}

@app.post("/api/admin/student/bulk")
def add_students_bulk(req: BulkStudentRequest):
    if db is None: return {"success": False}
    batch = db.batch()
    for s in req.students:
        doc_id = f"{s.get('school')}_{s.get('grade')}_{s.get('name')}"
        batch.set(db.collection("students").document(doc_id), {"school": s.get("school"), "grade": s.get("grade"), "student_name": s.get("name")})
    batch.commit()
    return {"success": True}

@app.post("/api/admin/student")
def add_single_student(req: SingleStudentRequest):
    if db is None: return {"success": False}
    doc_id = f"{req.school}_{req.grade}_{req.name}"
    db.collection("students").document(doc_id).set({"school": req.school, "grade": req.grade, "student_name": req.name})
    return {"success": True}

@app.post("/api/admin/student/update")
def update_student(req: UpdateStudentRequest):
    if db is None: return {"success": False}
    db.collection("students").document(req.old_id).delete()
    new_id = f"{req.school}_{req.grade}_{req.new_name}"
    db.collection("students").document(new_id).set({"school": req.school, "grade": req.grade, "student_name": req.new_name})
    return {"success": True}

@app.post("/api/admin/student/delete_bulk")
def delete_students_bulk(req: BulkDeleteRequest):
    if db is None: return {"success": False}
    batch = db.batch()
    for doc_id in req.ids: batch.delete(db.collection("students").document(doc_id))
    batch.commit()
    return {"success": True}

@app.get("/api/admin/reports")
def get_reports():
    if db is None: return {"success": False, "reports": []}
    docs = db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(500).stream()
    return {"success": True, "reports": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.post("/api/admin/homework")
async def create_homework(title: str=Form(...), desc: str=Form(""), answer_text: str=Form(""), answer_file: Optional[UploadFile]=File(None)):
    if db is None: return {"success": False}
    ans_url = ""
    if answer_file and answer_file.filename:
        safe_filename = f"{uuid.uuid4().hex}{os.path.splitext(answer_file.filename)[1]}"
        filepath = f"uploads/homeworks/{safe_filename}"
        with open(filepath, "wb") as buffer: shutil.copyfileobj(answer_file.file, buffer)
        ans_url = f"/{filepath}"
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
async def submit_homework(school: str=Form(...), grade: str=Form(...), student_name: str=Form(...), title: str=Form(...), file: UploadFile=File(...)):
    if db is None: return {"success": False}
    safe_filename = f"{uuid.uuid4().hex}{os.path.splitext(file.filename)[1]}"
    filepath = f"uploads/homeworks/{safe_filename}"
    with open(filepath, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": title, "type": "과제 제출", "score": "제출완료", "file_url": f"/{filepath}"})
    doc = db.collection("homeworks").document(title).get()
    send_telegram_msg(f"📚 [과제 제출] {school} {grade} {student_name}\n- {title}")
    return {"success": True, "answer_text": "", "answer_file": doc.to_dict().get("answer_file", "") if doc.exists else ""}

@app.post("/api/admin/board")
async def create_board_post(title: str=Form(...), desc: str=Form(""), file: Optional[UploadFile]=File(None)):
    if db is None: return {"success": False}
    file_url = ""
    if file and file.filename:
        safe_filename = f"{uuid.uuid4().hex}{os.path.splitext(file.filename)[1]}"
        filepath = f"uploads/board/{safe_filename}"
        with open(filepath, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        file_url = f"/{filepath}"
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

@app.post("/api/admin/lecture")
def create_lecture(req: LectureRequest):
    if db is None: return {"success": False}
    db.collection("lectures").add({"title": req.title, "desc": req.desc, "video_url": req.video_url, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
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
async def create_exam(
    title: str=Form(...), exam_data: str=Form(...), objective: str=Form(""), 
    allowed_students: str=Form("all"), video_url: str=Form(""), explanation_text: str=Form(""), file: Optional[UploadFile]=File(None)
):
    if db is None: return {"success": False}
    pdf_url = ""
    if file and file.filename:
        safe_filename = f"{uuid.uuid4().hex}{os.path.splitext(file.filename)[1]}"
        filepath = f"uploads/exams/{safe_filename}"
        with open(filepath, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        pdf_url = f"/{filepath}"
    
    student_list = [s.strip() for s in allowed_students.split(",")] if allowed_students != "all" else ["all"]
    db.collection("exams").document(title).set({"title": title, "exam_data": exam_data, "objective": objective, "allowed_students": student_list, "pdf_url": pdf_url, "video_url": video_url, "explanation_text": explanation_text, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
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

@app.post("/api/exam/submit")
def submit_exam(req: ExamSubmitRequest):
    if db is None: return {"success": False}
    doc = db.collection("exams").document(req.title).get()
    actual_score = 0; wrong_by_diff = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}; wrongs = []; missed_ab_score = 0; missed_c_score = 0
    if doc.exists:
        exam_data = json.loads(doc.to_dict().get("exam_data", "{}"))
        questions = exam_data.get("questions", [])
        for i, q in enumerate(questions):
            student_ans = str(req.answers[i]).strip() if i < len(req.answers) else ""
            correct_ans = str(q.get("ans", "")).strip()
            score = int(q.get("score", 0)); diff = q.get("diff", "C")
            if student_ans == correct_ans and student_ans != "": actual_score += score
            else:
                wrongs.append(i+1)
                if diff in wrong_by_diff: wrong_by_diff[diff] += 1
                if diff in ["A", "B"]: missed_ab_score += score
                elif diff == "C": missed_c_score += score
    potential_ab = actual_score + missed_ab_score
    potential_abc = potential_ab + missed_c_score
    db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": req.student_name, "school": req.school, "grade": req.grade, "task_name": req.title, "type": "모의고사", "score": actual_score, "wrongs": wrongs})
    send_telegram_msg(f"🏆 [시험 제출] {req.school} {req.grade} {req.student_name}\n- {req.title}: {actual_score}점")
    return {"success": True, "score": actual_score, "wrongs": wrongs, "wrong_by_diff": wrong_by_diff, "potential_ab": potential_ab, "potential_abc": potential_abc, "video_url": doc.to_dict().get("video_url", ""), "explanation_text": doc.to_dict().get("explanation_text", "")}

@app.post("/api/exam/twin")
async def generate_twin(req: TwinRequest):
    if model is None: return {"success": False}
    prompt = f"국어 모의고사 난이도 '{req.diff}', {req.score}점짜리 수능형 객관식 문제 1개 출제. 문항번호 1., 선택지 ①. 마크다운 사용 금지."
    try: return {"success": True, "twin_data": model.generate_content([prompt]).text}
    except: return {"success": False}

@app.post("/api/admin/questions")
def save_question(req: QuestionArchiveRequest):
    if db: db.collection("question_banks").add({"title": req.title, "content": req.content, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.get("/api/admin/questions")
def get_questions():
    if db is None: return {"success": False, "questions": []}
    docs = db.collection("question_banks").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "questions": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/questions/{q_id}")
def delete_question(q_id: str):
    if db: db.collection("question_banks").document(q_id).delete()
    return {"success": True}

@app.post("/api/admin/generate_stream")
async def generate_stream(q_mode: str=Form(...), q_types: str=Form(...), cnt_killer: int=Form(0), cnt_semi: int=Form(0), cnt_high: int=Form(0), cnt_mid: int=Form(0), cnt_low: int=Form(0), q_text: str=Form(""), files: Optional[List[UploadFile]]=File(None)):
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
    prompt = f"대치동 수석 출제 위원. {total}문항({q_types}). 마크다운 금지. 문항번호 1. 선택지 ①. [지문] 및 <보기> 형식 준수. 마지막에 [정답 및 해설], [정답표], [상세 해설] 작성.\n[자료]\n{q_text}"
    contents = [prompt]
    if files:
        for f in files:
            if f.filename: contents.append({"mime_type": "application/pdf" if "pdf" in f.filename.lower() else "image/jpeg", "data": await f.read()})
    if model is None: raise HTTPException(status_code=500, detail="AI 에러")
    response = model.generate_content(contents, stream=True)
    def iter_response():
        for chunk in response:
            if chunk.text: yield chunk.text
    return StreamingResponse(iter_response(), media_type="text/plain")

@app.post("/api/admin/knowledge")
async def add_knowledge(title: str=Form(...), content: str=Form(""), files: Optional[List[UploadFile]]=File(None)):
    if db is None: return {"success": False}
    final_content = content
    if files:
        for file in files:
            if file.filename:
                try:
                    res = model.generate_content(["이 문서 요약해줘.", {"mime_type": "application/pdf" if "pdf" in file.filename.lower() else "image/jpeg", "data": await file.read()}])
                    final_content += f"\n\n[{file.filename}]\n{res.text}"
                except: pass
    db.collection("knowledge").add({"title": title, "content": final_content, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.get("/api/knowledge")
def get_knowledge():
    if db is None: return {"success": False, "knowledge": []}
    docs = db.collection("knowledge").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "knowledge": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/knowledge/{kb_id}")
def delete_knowledge(kb_id: str):
    if db: db.collection("knowledge").document(kb_id).delete()
    return {"success": True}
