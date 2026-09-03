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
    except Exception as e:
        print("Telegram Error:", e)

class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
        self.active_connections[room_id].append(websocket)

    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.active_connections:
            try:
                self.active_connections[room_id].remove(websocket)
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
    raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

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
    model = genai.GenerativeModel('gemini-3.6-flash')

class AuthRequest(BaseModel): school: str = ""; grade: str = ""; student_name: str; admin_password: str = ""
class BulkStudentRequest(BaseModel): students: list
class SingleStudentRequest(BaseModel): school: str; grade: str; name: str
class UpdateStudentRequest(BaseModel): old_name: str; new_name: str; school: str; grade: str
class BulkDeleteRequest(BaseModel): names: list
class LectureRequest(BaseModel): title: str; desc: str; video_url: str
class ExamSubmitRequest(BaseModel): school: str; grade: str; student_name: str; title: str; answers: list
class TwinRequest(BaseModel): diff: str; score: int

@app.get("/api/health")
def health_check(): return {"status": "ok"}

@app.post("/api/auth")
def authenticate(req: AuthRequest):
    if req.admin_password == "1234": return {"success": True, "is_admin": True}
    if db is None: raise HTTPException(status_code=500, detail="DB 오류")
    doc = db.collection("students").document(req.student_name).get()
    if doc.exists:
        data = doc.to_dict()
        if data.get("school") == req.school and data.get("grade") == req.grade: return {"success": True, "is_admin": False}
    return {"success": False, "detail": "명부에 이름이 없거나 학교/학년 정보가 틀립니다."}

@app.post("/api/inquiry")
async def submit_inquiry(school: str=Form("미로그인"), grade: str=Form(""), student_name: str=Form("알수없음"), content: str=Form(...)):
    msg = f"📞 [학원 문의사항 도착]\n- 발신자: {school} {grade} {student_name}\n- 문의내용: {content}"
    send_telegram_msg(msg)
    if db:
        db.collection("inquiries").add({"school": school, "grade": grade, "student_name": student_name, "content": content, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
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
    if model is None: return StreamingResponse(iter(["AI 연결 오류."]), media_type="text/plain")
    
    send_telegram_msg(f"💬 [질문 도착]\n- 학생: {school} {grade} {student_name}\n- 질문: {prompt}")

    knowledge_base = ""
    if db:
        kb_docs = db.collection("knowledge").limit(10).stream()
        knowledge_base = "\n".join([f"[{d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in kb_docs])
    system_prompt = f"당신은 로지에듀 국어학원 AI 튜터 '국최'입니다. 아래 [학원 누적 자료]를 최우선 참고하여 학생에게 친절하고 명쾌하게 답변하세요.\n[학원 누적 자료]\n{knowledge_base}\n\n[학생 질문]\n{prompt}"
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
        response = model.generate_content(contents, stream=True)
        def iter_response():
            for chunk in response:
                if chunk.text: yield chunk.text
        return StreamingResponse(iter_response(), media_type="text/plain")
    except Exception as e: 
        return StreamingResponse(iter([f"AI 분석 중 오류가 발생했습니다: {str(e)}"]), media_type="text/plain")

@app.post("/api/essay/grade")
async def grade_essay(school: str=Form(...), grade: str=Form(...), student_name: str=Form(...), topic: str=Form(...), file: UploadFile=File(...)):
    if model is None: return {"success": False, "detail": "AI 연결 오류"}
    try:
        file_bytes = await file.read()
        mime = file.content_type
        if "pdf" in file.filename.lower(): mime = "application/pdf"
        elif "png" in file.filename.lower(): mime = "image/png"
        elif "jpg" in file.filename.lower() or "jpeg" in file.filename.lower(): mime = "image/jpeg"
        
        prompt = f"""
        당신은 대치동 최고의 국어/논술 전문 강사 '국최' 원장님입니다. 첨부된 문서(이미지 또는 PDF)는 학생이 작성한 논술문(또는 요약문)입니다.
        [논제/주제]: {topic}
        학생이 출력해서 볼 수 있도록 순수 HTML 형식으로만 작성해 주세요.
        학생이 틀린 부분이나 고쳐야 할 부분은 원문 바로 옆에 반드시 <span style="color:#ef4444; font-weight:bold;">[첨삭: 고친 내용]</span> 태그를 붙여서 빨간색 펜으로 직접 첨삭한 것처럼 보이게 해주세요.
        <h3 style="color:#3b82f6; font-size:1.5em; border-bottom:2px solid #3b82f6; padding-bottom:10px; margin-bottom:20px;">📝 작성 원문 및 AI 직접 첨삭</h3>
        <p style="line-height:2.0; font-size:1.1em; background:#f8fafc; padding:20px; border-radius:10px; color:#1e293b;">(원문 및 첨삭)</p>
        <h3 style="color:#3b82f6; font-size:1.5em; border-bottom:2px solid #3b82f6; padding-bottom:10px; margin-top:30px; margin-bottom:20px;">📊 AI 국최의 총평 및 점수</h3>
        <p style="line-height:1.8; font-size:1.1em; color:#333;">(총평)</p>
        <h3 style="color:#3b82f6; font-size:1.5em; border-bottom:2px solid #3b82f6; padding-bottom:10px; margin-top:30px; margin-bottom:20px;">✨ 모범 답안 (Rewrite)</h3>
        <p style="line-height:1.8; font-size:1.1em; color:#333;">(재작성 답안)</p>
        """
        res = model.generate_content([prompt, {"mime_type": mime or "application/pdf", "data": file_bytes}])
        if db:
            db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": f"AI 국최 논술 첨삭: {topic[:10]}...", "type": "논술 첨삭", "score": "첨삭완료"})
        
        send_telegram_msg(f"📝 [논술/요약 제출]\n- 학생: {school} {grade} {student_name}\n- 논제: {topic}")
        return {"success": True, "feedback": res.text}
    except Exception as e: return {"success": False, "detail": str(e)}

@app.get("/api/admin/students")
def get_students():
    if db is None: return {"success": False, "students": []}
    return {"success": True, "students": [{"student_name": d.id, **d.to_dict()} for d in db.collection("students").stream()]}

@app.post("/api/admin/student/bulk")
def add_students_bulk(req: BulkStudentRequest):
    if db is None: return {"success": False}
    batch = db.batch()
    for s in req.students:
        doc_ref = db.collection("students").document(s.get("name"))
        batch.set(doc_ref, {"school": s.get("school"), "grade": s.get("grade")})
    batch.commit()
    return {"success": True}

@app.post("/api/admin/student")
def add_single_student(req: SingleStudentRequest):
    if db is None: return {"success": False}
    db.collection("students").document(req.name).set({"school": req.school, "grade": req.grade})
    return {"success": True}

@app.post("/api/admin/student/update")
def update_student(req: UpdateStudentRequest):
    if db is None: return {"success": False}
    if req.old_name != req.new_name: db.collection("students").document(req.old_name).delete()
    db.collection("students").document(req.new_name).set({"school": req.school, "grade": req.grade})
    return {"success": True}

@app.post("/api/admin/student/delete_bulk")
def delete_students_bulk(req: BulkDeleteRequest):
    if db is None: return {"success": False}
    batch = db.batch()
    for name in req.names:
        doc_ref = db.collection("students").document(name)
        batch.delete(doc_ref)
    batch.commit()
    return {"success": True}

@app.delete("/api/admin/student/{name}")
def delete_student(name: str):
    if db: db.collection("students").document(name).delete()
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
        filename = f"{uuid.uuid4()}_{answer_file.filename}"
        filepath = f"uploads/homeworks/{filename}"
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
    filename = f"{uuid.uuid4()}_{file.filename}"
    filepath = f"uploads/homeworks/{filename}"
    with open(filepath, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": title, "type": "과제 제출", "score": "제출완료", "file_url": f"/{filepath}"})
    doc = db.collection("homeworks").document(title).get()
    ans_data = doc.to_dict() if doc.exists else {}
    
    send_telegram_msg(f"📚 [일반 과제 제출]\n- 학생: {school} {grade} {student_name}\n- 과제명: {title}")
    return {"success": True, "answer_text": ans_data.get("answer_text", ""), "answer_file": ans_data.get("answer_file", "")}

@app.post("/api/admin/board")
async def create_board_post(title: str=Form(...), desc: str=Form(""), file: Optional[UploadFile]=File(None)):
    if db is None: return {"success": False}
    file_url = ""
    if file and file.filename:
        filename = f"{uuid.uuid4()}_{file.filename}"
        filepath = f"uploads/board/{filename}"
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
    allowed_students: str=Form("all"),
    video_url: str=Form(""), explanation_text: str=Form(""), file: Optional[UploadFile]=File(None)
):
    if db is None: return {"success": False}
    pdf_url = ""
    if file and file.filename:
        filename = f"{uuid.uuid4()}_{file.filename}"
        filepath = f"uploads/exams/{filename}"
        with open(filepath, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        pdf_url = f"/{filepath}"
    
    student_list = [s.strip() for s in allowed_students.split(",")] if allowed_students != "all" else ["all"]
        
    db.collection("exams").document(title).set({
        "title": title, "exam_data": exam_data, "objective": objective, "allowed_students": student_list,
        "pdf_url": pdf_url, "video_url": video_url, "explanation_text": explanation_text, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
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
    
    send_telegram_msg(f"🏆 [모의고사 제출]\n- 학생: {req.school} {req.grade} {req.student_name}\n- 시험명: {req.title}\n- 점수: {actual_score}점")
    
    return {"success": True, "score": actual_score, "wrongs": wrongs, "wrong_by_diff": wrong_by_diff, "potential_ab": potential_ab, "potential_abc": potential_abc, "video_url": data.get("video_url", ""), "explanation_text": data.get("explanation_text", "")}

@app.post("/api/exam/twin")
async def generate_twin(req: TwinRequest):
    if model is None: return {"success": False}
    prompt = f"국어 모의고사에서 난이도 '{req.diff}' 수준의 {req.score}점짜리 수능형 객관식 국어 문제를 1개 즉석에서 출제해주세요. 문제와 함께 상세한 해설을 적어주세요."
    try:
        res = model.generate_content([prompt])
        return {"success": True, "twin_data": res.text}
    except: return {"success": False}

@app.post("/api/admin/generate_stream")
async def generate_stream(q_mode: str=Form(...), q_types: str=Form(...), cnt_killer: int=Form(0), cnt_semi: int=Form(0), cnt_high: int=Form(0), cnt_mid: int=Form(0), cnt_low: int=Form(0), q_text: str=Form(""), files: Optional[List[UploadFile]]=File(None)):
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
    prompt = f"로지에듀 국어학원 수석 출제 위원입니다. 오류 없는 문제를 출제하세요.\n- 유형: {q_types}\n- 총 {total}문항\n[입력자료]\n{q_text}"
    contents = [prompt]
    if files:
        for f in files:
            mime = f.content_type
            if "pdf" in f.filename.lower(): mime = "application/pdf"
            elif "png" in f.filename.lower(): mime = "image/png"
            elif "jpg" in f.filename.lower() or "jpeg" in f.filename.lower(): mime = "image/jpeg"
            contents.append({"mime_type": mime or "application/octet-stream", "data": await f.read()})
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
                    file_bytes = await file.read()
                    mime = file.content_type
                    if "pdf" in file.filename.lower(): mime = "application/pdf"
                    elif "png" in file.filename.lower(): mime = "image/png"
                    elif "jpg" in file.filename.lower() or "jpeg" in file.filename.lower(): mime = "image/jpeg"
                    
                    res = model.generate_content(["이 문서의 핵심 지식을 요약해줘.", {"mime_type": mime or "application/pdf", "data": file_bytes}])
                    final_content += f"\n\n[{file.filename} 분석]\n{res.text}"
                except Exception: pass
    db.collection("knowledge").add({"title": title, "content": final_content, "created_at": datetime.now()})
    return {"success": True}

# 💡 지식 자료 목록 확인 및 삭제
@app.get("/api/knowledge")
def get_knowledge():
    if db is None: return {"success": False, "knowledge": []}
    docs = db.collection("knowledge").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "knowledge": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/knowledge/{kb_id}")
def delete_knowledge(kb_id: str):
    if db: db.collection("knowledge").document(kb_id).delete()
    return {"success": True}
