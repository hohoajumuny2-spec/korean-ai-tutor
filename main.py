import os
import json
import shutil
import uuid
import fitz  # PyMuPDF: PDF 해독용[cite: 4]
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

# 브라우저 차단(CORS) 방지[cite: 3, 6]
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
    if os.path.exists(filepath):
        return FileResponse(filepath)
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
        print("Firebase Error:", e)

gemini_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
model = None
if gemini_key:
    genai.configure(api_key=gemini_key)
    # 구형 모델 충돌을 막기 위해 최신 flash 모델을 우선 사용[cite: 2]
    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
    except:
        model = genai.GenerativeModel('gemini-pro')

class AuthRequest(BaseModel):
    school: str = ""
    grade: str = ""
    student_name: str
    admin_password: str = ""

class BulkStudentRequest(BaseModel):
    students: list

class UpdateRequest(BaseModel):
    collection: str
    doc_id: str
    updates: dict

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
            return {"success": True, "is_admin": False, "student_name": req.student_name}
    return {"success": False, "detail": "명부에 이름이 없거나 학교/학년 정보가 틀립니다."}

@app.post("/api/chat")
async def chat_with_ai(
    school: str = Form(""), grade: str = Form(""), student_name: str = Form(""),
    prompt: str = Form(...), files: Optional[List[UploadFile]] = File(None)
):
    if model is None: return {"success": False, "reply": "AI 모델 설정 오류입니다."}
    
    knowledge_base = ""
    if db:
        kb_docs = db.collection("knowledge").limit(10).stream()
        knowledge_base = "\n".join([f"[{d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in kb_docs])

    system_prompt = f"""당신은 '로지에듀 최준용 국어학원'의 전용 AI 튜터 '국최'입니다. 학생 이름: {student_name}.
    아래 [로지에듀 공식 자료]를 최우선으로 참고하세요.
    [로지에듀 공식 자료]\n{knowledge_base}\n\n[학생 질문]\n{prompt}"""
    
    contents = [system_prompt]
    if files:
        for f in files:
            if f.filename:
                file_bytes = await f.read()
                if f.filename.lower().endswith(".pdf"):
                    doc = fitz.open(stream=file_bytes, filetype="pdf")
                    extracted_text = "".join([page.get_text() for page in doc])
                    contents[0] += f"\n\n[첨부 문서 내용]\n{extracted_text[:30000]}"
                else:
                    mime_type = f.content_type or "application/octet-stream"
                    contents.append({"mime_type": mime_type, "data": file_bytes})
                
    try:
        res = model.generate_content(contents)
        return {"success": True, "reply": res.text}
    except Exception as e:
        return {"success": False, "reply": f"AI 통신 오류: {str(e)}"}

@app.get("/api/admin/students")
def get_students():
    if db is None: return {"success": False, "students": []}
    return {"success": True, "students": [{"student_name": d.id, **d.to_dict()} for d in db.collection("students").stream()]}

@app.post("/api/admin/student")
def add_single_student(school: str = Form(...), grade: str = Form(...), name: str = Form(...)):
    if db: db.collection("students").document(name).set({"school": school, "grade": grade})
    return {"success": True}

@app.post("/api/admin/student/bulk")
def add_students_bulk(req: BulkStudentRequest):
    if db is None: return {"success": False}
    batch = db.batch()
    for s in req.students:
        batch.set(db.collection("students").document(s.get("name")), {"school": s.get("school"), "grade": s.get("grade")})
    batch.commit()
    return {"success": True}

@app.get("/api/admin/reports")
def get_reports():
    if db is None: return {"success": False, "reports": []}
    return {"success": True, "reports": [d.to_dict() for d in db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(200).stream()]}

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

@app.post("/api/homework/submit")
async def submit_homework(school: str = Form(...), grade: str = Form(...), student_name: str = Form(...), title: str = Form(...), files: List[UploadFile] = File(...)):
    if db is None: return {"success": False}
    file_urls = []
    for file in files:
        if file.filename:
            filename = f"{uuid.uuid4()}_{file.filename}"
            with open(f"uploads/homeworks/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
            file_urls.append(f"/uploads/homeworks/{filename}")
    db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": title, "type": "과제 제출", "score": "제출완료", "file_url": ",".join(file_urls)})
    doc = db.collection("homeworks").document(title).get()
    ans_data = doc.to_dict() if doc.exists else {}
    return {"success": True, "answer_text": ans_data.get("answer_text", ""), "answer_file": ans_data.get("answer_file", "")}

# ==========================================
# 💡 초정밀 모의고사 방 개설 및 채점 로직 (A~E 난이도 및 가능 점수 통합)[cite: 3]
# ==========================================
@app.post("/api/admin/exam")
async def create_exam(
    title: str = Form(...), 
    exam_data: str = Form(...),
    file: Optional[UploadFile] = File(None)
):
    if db is None: return {"success": False}
    pdf_url = ""
    if file and file.filename:
        filename = f"{uuid.uuid4()}_{file.filename}"
        with open(f"uploads/exams/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        pdf_url = f"/uploads/exams/{filename}"

    db.collection("exams").document(title).set({
        "title": title, "exam_data": exam_data, "pdf_url": pdf_url, 
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    return {"success": True}

@app.get("/api/exams")
def get_exams():
    if db is None: return {"success": False, "exams": []}
    docs = db.collection("exams").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "exams": [{"id": d.id, **d.to_dict()} for d in docs]}

class ExamSubmitRequest(BaseModel):
    school: str
    grade: str
    student_name: str
    title: str
    answers: list

@app.post("/api/exam/submit")
def submit_exam(req: ExamSubmitRequest):
    if db is None: return {"success": False}
    doc = db.collection("exams").document(req.title).get()
    
    actual_score = 0
    wrong_by_diff = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    wrongs = []
    missed_ab_score = 0
    missed_c_score = 0
    
    if doc.exists:
        data = doc.to_dict()
        exam_data = json.loads(data.get("exam_data", "{}"))
        questions = exam_data.get("questions", [])
        
        for i, q in enumerate(questions):
            student_ans = str(req.answers[i]).strip() if i < len(req.answers) else ""
            correct_ans = str(q.get("ans", "")).strip()
            score = int(q.get("score", 0))
            diff = q.get("diff", "C")
            
            if student_ans == correct_ans and student_ans != "":
                actual_score += score
            else:
                wrongs.append(i+1)
                if diff in wrong_by_diff:
                    wrong_by_diff[diff] += 1
                
                if diff in ["A", "B"]:
                    missed_ab_score += score
                elif diff == "C":
                    missed_c_score += score
                    
    potential_ab = actual_score + missed_ab_score
    potential_abc = potential_ab + missed_c_score
    
    db.collection("reports").add({
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "student_name": req.student_name, "school": req.school, "grade": req.grade,
        "task_name": req.title, "type": "모의고사", "score": actual_score, "wrongs": wrongs
    })
    
    return {
        "success": True, 
        "score": actual_score, 
        "wrongs": wrongs,
        "wrong_by_diff": wrong_by_diff,
        "potential_ab": potential_ab,
        "potential_abc": potential_abc
    }

# ==========================================
# 💡 자료 대량 일괄 등록 및 PyMuPDF 적용[cite: 4]
# ==========================================
@app.post("/api/admin/knowledge/bulk")
async def add_knowledge_bulk(files: List[UploadFile] = File(...)):
    if db is None: return {"success": False}
    processed = 0
    for file in files:
        if file.filename:
            try:
                file_bytes = await file.read()
                extracted_text = ""
                title = file.filename.rsplit('.', 1)[0] 
                
                if file.filename.lower().endswith(".pdf"):
                    doc = fitz.open(stream=file_bytes, filetype="pdf")
                    for page in doc:
                        extracted_text += page.get_text()
                else:
                    extracted_text = file_bytes.decode('utf-8', errors='ignore')

                prompt = f"다음 문서의 핵심 지식을 상세히 요약하고 핵심 개념을 정리해줘.\n\n[문서 내용]\n{extracted_text[:100000]}"
                res = model.generate_content([prompt])
                
                db.collection("knowledge").add({
                    "title": title, 
                    "content": f"[{title} 요약 및 핵심]\n{res.text}", 
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                processed += 1
            except Exception as e: 
                print(f"Parsing Error: {str(e)}")
                pass
    return {"success": True, "count": processed}

# ==========================================
# 💡 문제 자동 출제 (PyMuPDF 연동으로 스트리밍 충돌 방지)[cite: 2]
# ==========================================
@app.post("/api/admin/generate_stream")
async def generate_stream(
    q_mode: str = Form(...), q_types: str = Form(...),
    cnt_killer: int = Form(0), cnt_semi: int = Form(0), cnt_high: int = Form(0), cnt_mid: int = Form(0), cnt_low: int = Form(0),
    q_text: str = Form(""), files: Optional[List[UploadFile]] = File(None)
):
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
    prompt_text = f"로지에듀 국어학원 수석 출제 위원입니다. 오류 없는 문제를 출제하세요.\n유형: {q_types}\n총 {total}문항\n[입력자료]\n{q_text}"
    
    contents = [prompt_text]
    if files:
        for f in files:
            if f.filename:
                file_bytes = await f.read()
                # PDF는 이미지 형태가 아닌 텍스트로 치환하여 AI 과부하 원천 차단
                if f.filename.lower().endswith(".pdf"):
                    doc = fitz.open(stream=file_bytes, filetype="pdf")
                    extracted = "".join([page.get_text() for page in doc])
                    contents[0] += f"\n\n[PDF 참고 자료]\n{extracted[:30000]}"
                else:
                    mime_type = f.content_type or "image/jpeg"
                    contents.append({"mime_type": mime_type, "data": file_bytes})
    
    try:
        response = model.generate_content(contents, stream=True)
        def iter_response():
            try:
                for chunk in response:
                    if chunk.text: yield chunk.text
            except Exception as inner_e:
                yield f"\n\n❌ 스트리밍 중 오류 발생: {str(inner_e)}"
        return StreamingResponse(iter_response(), media_type="text/plain")
    except Exception as e:
        def err_response(): yield f"❌ AI 생성 실패 (서버 또는 API 할당량 초과): {str(e)}"
        return StreamingResponse(err_response(), media_type="text/plain")
