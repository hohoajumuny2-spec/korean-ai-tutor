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
import fitz  # 💡 PDF 텍스트 초고속 추출을 위한 PyMuPDF 라이브러리

app = FastAPI()

# 크롬 통신 차단을 뚫어주는 CORS 출입증
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 파이어베이스(DB) 및 AI 세팅
# ==========================================
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
        print("Firebase Error:", e)

gemini_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
model = None
if gemini_key:
    genai.configure(api_key=gemini_key)
    # 에러 방지를 위해 가장 안정적인 모델로 강제 고정
    model = genai.GenerativeModel('gemini-1.5-flash')

# ==========================================
# 데이터 규격 (Pydantic Models)
# ==========================================
class AuthRequest(BaseModel):
    student_class: str
    student_name: str
    admin_password: str = ""

class ChatRequest(BaseModel):
    student_class: str
    student_name: str
    prompt: str

class OMRRequest(BaseModel):
    student_class: str
    student_name: str
    task_name: str
    answers: list

class StudentAddRequest(BaseModel):
    student_class: str
    student_name: str
    phone: str = ""

@app.get("/api/health")
def health_check():
    return {"status": "ok"}

# 1. 로그인 인증
@app.post("/api/auth")
def authenticate(req: AuthRequest):
    if req.admin_password == "1234":
        return {"success": True, "is_admin": True, "message": "원장님 관리자 모드가 활성화되었습니다."}
    
    if db is None:
        raise HTTPException(status_code=500, detail="DB 연결 오류")
        
    doc = db.collection("students").document(req.student_name).get()
    if doc.exists:
        data = doc.to_dict()
        if data.get("student_class") == req.student_class:
            return {"success": True, "is_admin": False}
            
    return {"success": False, "detail": "명부에 이름이 없거나 소속 반이 틀립니다."}

# 2. AI 국최 튜터 (RAG 지식 검색)
@app.post("/api/chat")
def chat_with_ai(req: ChatRequest):
    if model is None:
        return {"success": False, "reply": "AI 연결 오류."}
    
    knowledge_base = ""
    if db:
        kb_docs = db.collection("knowledge").order_by("created_at", direction=firestore.Query.DESCENDING).limit(10).stream()
        knowledge_base = "\n".join([f"[{d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in kb_docs])

    system_prompt = f"""
    당신은 로지에듀 국어학원 최준용 원장님의 AI 튜터 '국최'입니다.
    아래 [학원 누적 자료]를 최우선으로 참고하여 답변하세요.
    [학원 누적 자료]
    {knowledge_base}

    [학생 질문]
    {req.prompt}
    """
    try:
        res = model.generate_content(system_prompt)
        return {"success": True, "reply": res.text}
    except Exception as e:
        return {"success": False, "reply": str(e)}

# 3. 학생 명부 관리 (가져오기, 등록, 삭제)
@app.get("/api/admin/students")
def get_students():
    if db is None: return {"success": False, "students": []}
    users_ref = db.collection("students").stream()
    students = [{"student_name": doc.id, "student_class": doc.to_dict().get("student_class", ""), "phone": doc.to_dict().get("phone", "")} for doc in users_ref]
    return {"success": True, "students": students}

@app.post("/api/admin/student")
def add_student(req: StudentAddRequest):
    if db is None: return {"success": False}
    db.collection("students").document(req.student_name).set({
        "student_class": req.student_class,
        "phone": req.phone
    })
    return {"success": True}

@app.delete("/api/admin/student/{name}")
def delete_student(name: str):
    if db is None: return {"success": False}
    db.collection("students").document(name).delete()
    return {"success": True}

# 4. 장부(성적/과제) 가져오기
@app.get("/api/admin/reports")
def get_reports():
    if db is None: return {"success": False, "reports": []}
    reports_ref = db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(50).stream()
    return {"success": True, "reports": [doc.to_dict() for doc in reports_ref]}

# 5. OMR 채점
@app.post("/api/omr/submit")
def submit_omr(req: OMRRequest):
    if db is None: return {"success": False, "detail": "DB 연결 오류"}
    
    score = 100
    wrongs = []
    for i, ans in enumerate(req.answers):
        if not ans.strip():  
            score -= 20
            wrongs.append(i+1)
            
    if score < 0: score = 0

    report_data = {
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "student_name": req.student_name,
        "student_class": req.student_class,
        "task_name": req.task_name,
        "type": "OMR 채점",
        "score": score,
        "wrongs": wrongs
    }
    db.collection("reports").add(report_data)
    
    return {"success": True, "score": score, "wrongs": wrongs}

# 💡 6. [핵심] 대용량 PDF 텍스트 추출 및 지식 베이스(RAG) 주입
@app.post("/api/admin/knowledge/bulk")
async def add_knowledge_bulk(files: List[UploadFile] = File(...)):
    if db is None: return {"success": False, "detail": "DB 연결 오류"}
    processed = 0
    for file in files:
        if file.filename:
            try:
                file_bytes = await file.read()
                extracted_text = ""
                title = file.filename.rsplit('.', 1)[0]
                
                # PDF 파일이면 PyMuPDF로 텍스트만 즉시 추출
                if file.filename.lower().endswith(".pdf"):
                    doc = fitz.open(stream=file_bytes, filetype="pdf")
                    for page in doc:
                        extracted_text += page.get_text()
                else:
                    # 텍스트 파일(.txt)인 경우
                    extracted_text = file_bytes.decode('utf-8', errors='ignore')

                # 긴 텍스트를 AI 두뇌에 바로 넣기 위해 핵심만 요약
                if model:
                    prompt = f"다음 문서의 핵심 지식을 상세히 요약하고 국어 해설/개념을 정리해줘.\n\n[문서 내용]\n{extracted_text[:90000]}"
                    response = model.generate_content(prompt)
                    summary = response.text
                else:
                    summary = extracted_text[:1000]

                db.collection("knowledge").add({
                    "title": title,
                    "content": f"[{title} 요약 및 핵심]\n{summary}",
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                processed += 1
            except Exception as e:
                print(f"File Parsing Error: {str(e)}")
                pass
    return {"success": True, "message": f"총 {processed}개의 대용량 파일이 AI 두뇌에 완벽히 이식되었습니다!"}
