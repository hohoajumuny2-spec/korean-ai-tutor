import os
import json
import shutil
import uuid
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
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

@app.get("/uploads/{folder}/{filename}")
def get_upload_file(folder: str, filename: str):
    filepath = f"uploads/{folder}/{filename}"
    if os.path.exists(filepath): return FileResponse(filepath)
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

class AuthRequest(BaseModel):
    school: str = ""
    grade: str = ""
    student_name: str
    admin_password: str = ""

class BulkStudentRequest(BaseModel): students: list
class SingleStudentRequest(BaseModel): school: str; grade: str; name: str
class UpdateStudentRequest(BaseModel): old_name: str; new_name: str; school: str; grade: str
class BulkDeleteRequest(BaseModel): names: list
class LectureRequest(BaseModel): title: str; desc: str; video_url: str
class ExamSubmitRequest(BaseModel): school: str; grade: str; student_name: str; title: str; answers: list

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

@app.post("/api/chat")
async def chat_with_ai(school: str=Form(""), grade: str=Form(""), student_name: str=Form(""), prompt: str=Form(...), files: Optional[List[UploadFile]]=File(None)):
    if model is None: return {"success": False, "reply": "AI 연결 오류."}
    knowledge_base = ""
    if db:
        kb_docs = db.collection("knowledge").limit(10).stream()
        knowledge_base = "\n".join([f"[{d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in kb_docs])
    system_prompt = f"당신은 로지에듀 국어학원 AI 튜터 '국최'입니다. 아래 [학원 누적 자료]를 최우선 참고하여 답변하세요.\n[학원 누적 자료]\n{knowledge_base}\n\n[학생 질문]\n{prompt}"
    contents = [system_prompt]
    if files:
        for f in files:
            if f.filename: contents.append({"mime_type": f.content_type or "application/octet-stream", "data": await f.read()})
    try:
        res = model.generate_content(contents)
        return {"success": True, "reply": res.text}
    except Exception as e: return {"success": False, "reply": str(e)}

# 💡 AI 국최 논술/요약 첨삭 (빨간펜 마킹 적용 및 PDF 처리)
@app.post("/api/essay/grade")
async def grade_essay(
    school: str = Form(...), grade: str = Form(...), student_name: str = Form(...),
    topic: str = Form(...), file: UploadFile = File(...)
):
    if model is None: return {"success": False, "detail": "AI 연결 오류"}
    try:
        file_bytes = await file.read()
        mime_type = file.content_type or "application/pdf"
        
        prompt = f"""
        당신은 대치동 최고의 국어/논술 전문 강사 '국최' 원장님입니다. 첨부된 문서(이미지 또는 PDF)는 학생이 작성한 논술문(또는 요약문)입니다.
        [논제/주제]: {topic}
        
        학생이 출력해서 볼 수 있도록 순수 HTML 형식으로만 작성해 주세요. (```html 등의 마크다운 기호는 절대 쓰지 마세요)
        학생이 틀린 부분이나 고쳐야 할 부분은 원문 바로 옆에 반드시 <span style="color:#ef4444; font-weight:bold;">[첨삭: 고친 내용]</span> 태그를 붙여서 빨간색 펜으로 직접 첨삭한 것처럼 보이게 해주세요.
        
        <h3 style="color:#3b82f6; font-size:1.5em; border-bottom:2px solid #3b82f6; padding-bottom:10px; margin-bottom:20px;">📝 작성 원문 및 AI 직접 첨삭</h3>
        <p style="line-height:2.0; font-size:1.1em; background:#f8fafc; padding:20px; border-radius:10px; color:#1e293b;">
        (이곳에 학생의 원문을 타이핑하되, 교정이 필요한 부분은 바로 옆에 빨간색 첨삭 태그를 삽입하세요.)
        </p>
        
        <h3 style="color:#3b82f6; font-size:1.5em; border-bottom:2px solid #3b82f6; padding-bottom:10px; margin-top:30px; margin-bottom:20px;">📊 AI 국최의 총평 및 점수</h3>
        <p style="line-height:1.8; font-size:1.1em; color:#333;">(100점 만점 기준 점수와 논리성, 표현력 등에 대한 예리한 총평)</p>
        
        <h3 style="color:#3b82f6; font-size:1.5em; border-bottom:2px solid #3b82f6; padding-bottom:10px; margin-top:30px; margin-bottom:20px;">✨ 모범 답안 (Rewrite)</h3>
        <p style="line-height:1.8; font-size:1.1em; color:#333;">(원장님의 세련된 문장으로 완벽하게 재작성된 답안)</p>
        """
        res = model.generate_content([prompt, {"mime_type": mime_type, "data": file_bytes}])
        
        if db:
            db.collection("reports").add({
                "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "student_name": student_name, "school": school, "grade": grade,
                "task_name": f"AI 국최 논술 첨삭: {topic[:10]}...", "type": "논술 첨삭", "score": "첨삭완료"
            })
        return {"success": True, "feedback": res.text}
    except Exception as e:
        return {"success": False, "detail": str(e)}

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
async def create_homework(title: str = Form(...), desc: str = Form(""), answer_text: str = Form(""), answer_file: Optional[UploadFile] = File(None)):
    if db is None: return {"success": False}
    ans_url = ""
    if answer_file and answer_file.filename:
        filename = f"{uuid.uuid4()}_{answer_file.filename}"
        with open(f"uploads/homeworks/{filename}", "wb") as buffer:
