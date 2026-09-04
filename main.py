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
os.makedirs("uploads/profiles", exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 🏆 학생 경험치(XP) 보상 수치 설정 (원장님 마음대로 수정 가능)
# ==========================================
XP_REWARD_LOGIN = 50        # 하루 1번 로그인 출석 시 획득량
XP_REWARD_HOMEWORK = 200    # 과제 1회 제출 시 획득량 
XP_REWARD_PROFILE = 300     # 최초 다짐 및 아바타 설정 시 보너스
XP_MULTIPLIER_EXAM = 2      # 모의고사 점수 배수 (예: 80점 맞으면 x2 해서 160 XP 지급)
# ==========================================

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

# ==========================================
# 💡 핵심 수정: 에러를 내던 3.6-flash를 지우고 실제 구동되는 최신 1.5-flash로 완벽 교체
# ==========================================
gemini_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
model = None
if gemini_key:
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

class AuthRequest(BaseModel):
    school: str = ""
    grade: str = ""
    student_name: str
    admin_password: str = ""

class BulkStudentRequest(BaseModel):
    students: list

class SingleStudentRequest(BaseModel):
    school: str
    grade: str
    name: str

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
            
            return {"success": True, "is_admin": False, "xp": current_xp, "reward": XP_REWARD_LOGIN}
    return {"success": False, "detail": "명부에 이름이 없거나 학교/학년 정보가 틀립니다."}

@app.get("/api/student/profile/{student_name}")
def get_student_profile(student_name: str):
    if db is None: return {"success": False}
    doc = db.collection("students").document(student_name).get()
    if not doc.exists: return {"success": False}
    
    reports = []
    report_docs = db.collection("reports").where("student_name", "==", student_name).order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(20).stream()
    for r in report_docs:
        reports.append(r.to_dict())
        
    return {"success": True, "profile": doc.to_dict(), "reports": reports}

@app.post("/api/student/profile_update")
async def update_profile(
    student_name: str = Form(...),
    motto: str = Form(""),
    avatar: str = Form(""),
    file: Optional[UploadFile] = File(None)
):
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
    return {"success": True, "xp": current_xp, "profile_image": update_data.get("profile_image", data.get("profile_image", ""))}

@app.post("/api/chat")
async def chat_with_ai(
    school: str = Form(""), grade: str = Form(""), student_name: str = Form(""),
    prompt: str = Form(...), files: Optional[List[UploadFile]] = File(None)
):
    if model is None: return {"success": False, "reply": "AI 연결 오류."}
    knowledge_base = ""
    if db:
        kb_docs = db.collection("knowledge").limit(10).stream()
        knowledge_base = "\n".join([f"[{d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in kb_docs])
    system_prompt = f"당신은 로지에듀 국어학원 AI 튜터 '국최'입니다. 아래 [학원 누적 자료]를 최우선 참고하여 답변하세요.\n[학원 누적 자료]\n{knowledge_base}\n\n[학생 질문]\n{prompt}"
    contents = [system_prompt]
    if files:
        for f in files:
            if f.filename:
                contents.append({"mime_type": f.content_type or "application/octet-stream", "data": await f.read()})
    try:
        res = model.generate_content(contents)
        return {"success": True, "reply": res.text}
    except Exception as e:
        return {"success": False, "reply": str(e)}

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
        batch.set(doc_ref, {"school": s.get("school"), "grade": s.get("grade")}, merge=True)
    batch.commit()
    return {"success": True}

@app.post("/api/admin/student")
def add_single_student(req: SingleStudentRequest):
    if db is None: return {"success": False}
    db.collection("students").document(req.name).set({"school": req.school, "grade": req.grade}, merge=True)
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

class LectureRequest(BaseModel):
    title: str
    desc: str
    video_url: str

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
    title: str = Form(...), exam_data: str = Form(...), video_url: str = Form(""), explanation_text: str = Form(""), file: Optional[UploadFile] = File(None)
):
    if db is None: return {"success": False}
    pdf_url = ""
    if file and file.filename:
        filename = f"{uuid.uuid4()}_{file.filename}"
        with open(f"uploads/exams/{filename}", "wb") as buffer: shutil.copyfileobj(file.file, buffer)
        pdf_url = f"/uploads/exams/{filename}"

    db.collection("exams").document(title).set({
        "title": title, "exam_data": exam_data, "pdf_url": pdf_url, 
        "video_url": video_url, "explanation_text": explanation_text,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
                if diff in wrong_by_diff: wrong_by_diff[diff] += 1
                if diff in ["A", "B"]: missed_ab_score += score
                elif diff == "C": missed_c_score += score
                    
    potential_ab = actual_score + missed_ab_score
    potential_abc = potential_ab + missed_c_score
    
    db.collection("reports").add({
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "student_name": req.student_name, "school": req.school, "grade": req.grade,
        "task_name": req.title, "type": "모의고사", "score": actual_score, "wrongs": wrongs
    })
    
    s_doc = db.collection("students").document(req.student_name).get()
    if s_doc.exists:
        earned_xp = actual_score * XP_MULTIPLIER_EXAM
        xp = s_doc.to_dict().get("xp", 0) + earned_xp
        db.collection("students").document(req.student_name).set({"xp": xp}, merge=True)
    
    return {
        "success": True, "score": actual_score, "wrongs": wrongs,
        "wrong_by_diff": wrong_by_diff, "potential_ab": potential_ab, "potential_abc": potential_abc,
        "video_url": data.get("video_url", ""), "explanation_text": data.get("explanation_text", "")
    }

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
            if f.filename: contents.append({"mime_type": f.content_type or "application/octet-stream", "data": await f.read()})
    if model is None: raise HTTPException(status_code=500, detail="AI 에러")
    response = model.generate_content(contents, stream=True)
    def iter_response():
        for chunk in response:
            if chunk.text: yield chunk.text
    return StreamingResponse(iter_response(), media_type="text/plain")

@app.post("/api/admin/knowledge")
async def add_knowledge(title: str = Form(...), content: str = Form(""), files: Optional[List[UploadFile]] = File(None)):
    if db is None: return {"success": False}
    final_content = content
    if files:
        for file in files:
            if file.filename:
                try:
                    file_bytes = await file.read()
                    res = model.generate_content(["이 문서의 핵심 지식을 요약해줘.", {"mime_type": file.content_type or "application/pdf", "data": file_bytes}])
                    final_content += f"\n\n[{file.filename} 분석]\n{res.text}"
                except Exception: pass
    db.collection("knowledge").add({"title": title, "content": final_content, "created_at": datetime.now()})
    return {"success": True}
