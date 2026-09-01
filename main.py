import os
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from datetime import datetime

app = FastAPI()

# ==========================================
# 🚨 핵심: 크롬 통신 차단을 뚫어주는 CORS 출입증
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인(홈페이지)에서 접근 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 환경 변수 및 DB, AI 세팅
# ==========================================
# 1. 파이어베이스(DB) 연결 설정
firebase_key_str = os.environ.get("FIREBASE_KEY")
if firebase_key_str:
    try:
        cred_dict = json.loads(firebase_key_str)
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as e:
        print("Firebase Error:", e)
        db = None
else:
    db = None

# 2. 구글 제미나이(AI) 연결 설정
# 💡 수정됨: GOOGLE_API_KEY 또는 GEMINI_API_KEY 어떤 이름이든 무조건 찾아내도록 변경
gemini_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
if gemini_key:
    genai.configure(api_key=gemini_key)
    # 💡 핵심 수정: 에러를 뿜던 모델 대신 가장 안정적인 1.0-pro 모델로 완벽 교체
    model = genai.GenerativeModel('gemini-1.0-pro')
else:
    model = None

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

class StudentAddRequest(BaseModel):
    student_class: str
    student_name: str
    phone: str = ""

class ExamRequest(BaseModel):
    title: str
    time: int

class OMRRequest(BaseModel):
    student_class: str
    student_name: str
    task_name: str
    answers: list

# ==========================================
# 서버 기능 (API 엔드포인트)
# ==========================================
@app.get("/api/health")
def health_check():
    return {"status": "ok"}

@app.post("/api/auth")
def authenticate(req: AuthRequest):
    # 1. 원장님 스텔스 키 검사
    if req.admin_password == "1234":
        return {"success": True, "is_admin": True}
    
    # 2. 일반 학생 명부 검사
    if db is None:
        raise HTTPException(status_code=500, detail="서버 DB 연결 오류")
        
    doc = db.collection("students").document(req.student_name).get()
    if doc.exists:
        data = doc.to_dict()
        if data.get("student_class") == req.student_class:
            return {"success": True, "is_admin": False}
    
    return {"success": False, "detail": "명부에 이름이 없거나 소속 반이 틀립니다."}

@app.post("/api/chat")
def chat_with_ai(req: ChatRequest):
    if model is None:
        return {"success": False, "reply": "AI가 연결되지 않았습니다. 렌더 서버 환경변수에 GOOGLE_API_KEY를 확인하세요."}
    try:
        response = model.generate_content(req.prompt)
        return {"success": True, "reply": response.text}
    except Exception as e:
        return {"success": False, "reply": f"AI 응답 오류: {str(e)}"}

@app.get("/api/admin/students")
def get_students():
    if db is None: return {"success": False, "students": []}
    users_ref = db.collection("students").stream()
    students = [{"student_name": doc.id, "student_class": doc.to_dict().get("student_class", "")} for doc in users_ref]
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

@app.get("/api/admin/reports")
def get_reports():
    if db is None: return {"success": False, "reports": []}
    reports_ref = db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(50).stream()
    return {"success": True, "reports": [doc.to_dict() for doc in reports_ref]}

@app.post("/api/admin/exam")
def create_exam(req: ExamRequest):
    if db is None: return {"success": False}
    db.collection("settings").document("latest_exam").set({
        "title": req.title,
        "time": req.time,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    return {"success": True}

@app.get("/api/exam/latest")
def get_latest_exam():
    if db is None: return {"success": False}
    doc = db.collection("settings").document("latest_exam").get()
    if doc.exists: return {"success": True, "exam": doc.to_dict()}
    return {"success": False}

@app.post("/api/omr/submit")
def submit_omr(req: OMRRequest):
    if db is None: return {"success": False, "detail": "DB 연결 오류"}
    
    score = 100
    wrongs = []
    for i, ans in enumerate(req.answers):
        if not ans.strip():  # 마킹 안 한 문항 오답 처리
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
