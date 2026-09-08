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
    # 404 에러 방지를 위해 latest 모델 명시 및 안전장치
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

# 만능 데이터 수정 API (모든 관리자 탭 수정용)
@app.post("/api/admin/universal_update")
def universal_update(req: UpdateRequest):
    if db is None: return {"success": False}
    try:
        db.collection(req.collection).document(req.doc_id).update(req.updates)
        return {"success": True}
    except Exception as e:
        return {"success": False, "detail": str(e)}

@app.post("/api/chat")
async def chat_with_ai(
    school: str = Form(""), grade: str = Form(""), student_name: str = Form(""),
    prompt: str = Form(...), files: Optional[List[UploadFile]] = File(None)
):
    if model is None: return {"success": False, "reply": "AI 모델 설정 오류입니다. API 키를 확인하세요."}
    
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

@app.post("/api/admin/student/delete_bulk")
def delete_students_bulk(ids: list = Form(...)):
    if db is None: return {"success": False}
    batch = db.batch()
    for student_id in ids:
        batch.delete(db.collection("students").document(student_id))
    batch.commit()
    return {"success": True}

@app.get("/api/admin/reports")
def get_reports():
    if db is None: return {"success": False, "reports": []}
    return {"success": True, "reports": [d.to_dict() for d in db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(200).stream()]}

@app.get("/api/student/profile/{student_name}")
def get_student_profile(student_name: str):
    if db is None: return {"success": False}
    return {"success": True, "reports": [d.to_dict() for d in db.collection("reports").where("student_name", "==", student_name).stream()]}

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

@app.post("/api/admin/exam")
async def create_exam(title: str = Form(...), time_limit: int = Form(45), answer_key: str = Form(...), file: Optional[UploadFile] = File(None), raw_text: str = Form(""), exam_data: str = Form("{}"), video_url: str = Form(""), explanation_text: str = Form("")):
    if db is None: return {"success": False}
    pdf_url = ""
    if file and file.filename:
        filename = f"{uuid.uuid4()}_{file.filename}"
        with open(f"uploads/exams/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        pdf_url = f"/uploads/exams/{filename}"
    db.collection("exams").document(title).set({"title": title, "time_limit": time_limit, "answer_key": answer_key, "exam_data": exam_data, "video_url": video_url, "explanation_text": explanation_text, "pdf_url": pdf_url, "raw_text": raw_text, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
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
    score = 0; wrongs = []
    if doc.exists:
        data = doc.to_dict()
        correct_answers = [ans.strip() for ans in data.get("answer_key", "").split(",") if ans.strip()]
        total = len(correct_answers)
        correct_count = 0
        for i in range(min(len(req.answers), total)):
            if str(req.answers[i]).strip() == str(correct_answers[i]).strip(): correct_count += 1
            else: wrongs.append(i+1)
        if total > 0: score = int((correct_count / total) * 100)
    db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": req.student_name, "school": req.school, "grade": req.grade, "task_name": req.title, "type": "모의고사", "score": score, "wrongs": wrongs})
    return {"success": True, "score": score, "wrongs": wrongs, "explanation_text": doc.to_dict().get("explanation_text", "")}

@app.post("/api/admin/quiz")
async def create_quiz(title: str = Form(...), deadline: str = Form(...), time_limit: int = Form(...), questions: str = Form(...)):
    if db: db.collection("quizzes").add({"title": title, "deadline": deadline, "time_limit": time_limit, "questions": questions, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.get("/api/quizzes")
def get_quizzes():
    if db is None: return {"success": False, "quizzes": []}
    docs = db.collection("quizzes").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "quizzes": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/quiz/{quiz_id}")
def delete_quiz(quiz_id: str):
    if db: db.collection("quizzes").document(quiz_id).delete()
    return {"success": True}

class QuizSubmitRequest(BaseModel):
    school: str
    grade: str
    student_name: str
    title: str
    quiz_id: str
    answers: list

@app.post("/api/quiz/submit")
def submit_quiz(req: QuizSubmitRequest):
    if db is None: return {"success": False}
    doc = db.collection("quizzes").document(req.quiz_id).get()
    score = 0
    if doc.exists:
        data = doc.to_dict()
        questions = json.loads(data.get("questions", "[]"))
        for i, q in enumerate(questions):
            if i < len(req.answers) and str(req.answers[i]).strip() == str(q.get("ans")).strip(): score += int(q.get("score", 0))
    db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": req.student_name, "school": req.school, "grade": req.grade, "task_name": req.title, "type": "타임어택 퀴즈", "score": score})
    return {"success": True, "score": score}

@app.get("/api/knowledge")
def get_knowledge():
    if db is None: return {"success": False, "knowledge": []}
    docs = db.collection("knowledge").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "knowledge": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.post("/api/admin/knowledge")
async def add_knowledge(title: str = Form(...), content: str = Form(""), files: Optional[List[UploadFile]] = File(None)):
    if db is None: return {"success": False}
    final_content = content
    if files:
        for file in files:
            if file.filename:
                try:
                    file_bytes = await file.read()
                    res = model.generate_content(["이 문서의 핵심을 요약해줘.", {"mime_type": file.content_type or "image/jpeg", "data": file_bytes}])
                    final_content += f"\n\n[{file.filename}]\n{res.text}"
                except Exception: pass
    db.collection("knowledge").add({"title": title, "content": final_content, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.post("/api/admin/knowledge/bulk")
async def add_knowledge_bulk(files: List[UploadFile] = File(...)):
    if db is None: return {"success": False}
    processed = 0
    for file in files:
        if file.filename:
            try:
                file_bytes = await file.read()
                title = file.filename.rsplit('.', 1)[0]
                res = model.generate_content(["이 문서를 요약해줘.", {"mime_type": file.content_type or "image/jpeg", "data": file_bytes}])
                db.collection("knowledge").add({"title": title, "content": res.text, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                processed += 1
            except Exception: pass
    return {"success": True, "count": processed}

@app.delete("/api/admin/knowledge/{doc_id}")
def delete_knowledge(doc_id: str):
    if db: db.collection("knowledge").document(doc_id).delete()
    return {"success": True}

@app.post("/api/admin/generate_stream")
async def generate_stream(
    q_mode: str = Form(...), q_types: str = Form(...),
    cnt_killer: int = Form(0), cnt_semi: int = Form(0), cnt_high: int = Form(0), cnt_mid: int = Form(0), cnt_low: int = Form(0),
    q_text: str = Form(""), files: Optional[List[UploadFile]] = File(None)
):
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
    prompt = f"로지에듀 국어학원 수석 출제 위원입니다. 오류 없는 문제를 출제하세요.\n유형: {q_types}\n총 {total}문항\n[입력자료]\n{q_text}"
    contents = [prompt]
    if files:
        for f in files:
            if f.filename: contents.append({"mime_type": f.content_type or "image/jpeg", "data": await f.read()})
    
    response = model.generate_content(contents, stream=True)
    def iter_response():
        for chunk in response:
            if chunk.text: yield chunk.text
    return StreamingResponse(iter_response(), media_type="text/plain")

@app.get("/api/admin/questions")
def get_questions():
    if db is None: return {"success": False, "questions": []}
    docs = db.collection("questions").stream()
    return {"success": True, "questions": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.post("/api/admin/questions")
def save_question(title: str = Form(...), content: str = Form(...)):
    if db: db.collection("questions").add({"title": title, "content": content})
    return {"success": True}

@app.delete("/api/admin/questions/{q_id}")
def delete_question(q_id: str):
    if db: db.collection("questions").document(q_id).delete()
    return {"success": True}

@app.post("/api/admin/lecture")
def create_lecture(title: str = Form(...), desc: str = Form(""), video_url: str = Form(...)):
    if db: db.collection("lectures").add({"title": title, "desc": desc, "video_url": video_url, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
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

@app.post("/api/essay/grade")
async def grade_essay(school: str = Form(...), grade: str = Form(...), student_name: str = Form(...), topic: str = Form(...), file: UploadFile = File(...)):
    if model is None: return {"success": False, "feedback": "AI 에러"}
    try:
        file_bytes = await file.read()
        res = model.generate_content([f"다음 논술/요약을 예리하게 첨삭해줘.\n주제: {topic}", {"mime_type": file.content_type or "image/jpeg", "data": file_bytes}])
        db.collection("reports").add({"submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "student_name": student_name, "school": school, "grade": grade, "task_name": topic, "type": "논술 첨삭", "score": "첨삭완료"})
        return {"success": True, "feedback": res.text}
    except Exception as e:
        return {"success": False, "feedback": str(e)}

@app.post("/api/inquiry")
def submit_inquiry(content: str = Form(...), school: str = Form(""), grade: str = Form(""), student_name: str = Form("")):
    if db: db.collection("inquiries").add({"content": content, "school": school, "grade": grade, "student_name": student_name, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return {"success": True}

@app.get("/api/inquiries")
def get_inquiries():
    if db is None: return {"success": False, "inquiries": []}
    docs = db.collection("inquiries").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "inquiries": [{"id": d.id, **d.to_dict()} for d in docs]}

@app.delete("/api/admin/inquiry/{inquiry_id}")
def delete_inquiry(inquiry_id: str):
    if db: db.collection("inquiries").document(inquiry_id).delete()
    return {"success": True}
