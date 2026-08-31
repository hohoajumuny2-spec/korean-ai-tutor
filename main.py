from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from datetime import datetime
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

# 1. 렌더에 저장한 파이어베이스 열쇠 꺼내서 연결하기
firebase_key_json = os.environ.get("FIREBASE_KEY")
if firebase_key_json:
    try:
        cred_dict = json.loads(firebase_key_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ 파이어베이스 DB 연결 성공!")
    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        db = None
else:
    print("❌ FIREBASE_KEY를 찾을 수 없습니다.")
    db = None

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ★ 원장님 전용 스텔스 로그인 비밀번호 (원하시는 번호로 변경하세요)
ADMIN_PW = "1234"

class AuthReq(BaseModel):
    student_class: str
    student_name: str
    admin_password: str = ""

class StudentReq(BaseModel):
    student_class: str
    student_name: str
    phone: str

class OMRSubmitReq(BaseModel):
    student_class: str
    student_name: str
    task_name: str
    answers: List[str]

class ChatReq(BaseModel):
    student_class: str
    student_name: str
    prompt: str

@app.get("/api/health")
def health_check():
    return {"status": "ok"}

# 1. 로그인 (DB 대조)
@app.post("/api/auth")
def login(req: AuthReq):
    if req.admin_password == ADMIN_PW:
        return {"success": True, "is_admin": True, "message": "원장님 로그인 성공"}
    
    if not db:
        raise HTTPException(status_code=500, detail="데이터베이스 연결 오류")

    # DB에서 학생 이름으로 검색
    doc = db.collection("students").document(req.student_name).get()
    if doc.exists:
        data = doc.to_dict()
        if data.get("student_class") == req.student_class:
            return {"success": True, "is_admin": False}
        else:
            raise HTTPException(status_code=401, detail="소속 반이 일치하지 않습니다.")
    else:
        raise HTTPException(status_code=401, detail="명부에 없는 학생입니다. 원장님께 등록을 요청하세요.")

# 2. 학생 등록 (원장님 전용)
@app.post("/api/admin/student")
def add_student(req: StudentReq):
    if not db:
        raise HTTPException(status_code=500, detail="DB 오류")
    db.collection("students").document(req.student_name).set({
        "student_class": req.student_class,
        "student_name": req.student_name,
        "phone": req.phone,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    return {"success": True}

# 3. 학생 목록 조회
@app.get("/api/admin/students")
def get_students():
    if not db:
        return {"success": False, "students": []}
    docs = db.collection("students").stream()
    return {"success": True, "students": [doc.to_dict() for doc in docs]}

# 4. 학생 삭제
@app.delete("/api/admin/student/{name}")
def delete_student(name: str):
    if not db:
        raise HTTPException(status_code=500, detail="DB 오류")
    db.collection("students").document(name).delete()
    return {"success": True}

# 5. OMR 채점 및 장부(리포트) 기록
@app.post("/api/omr/submit")
def submit_omr(req: OMRSubmitReq):
    # 테스트용 임시 정답
    correct_answers = ["1", "2", "3", "4", "5"]
    score = 0
    wrongs = []
    for i in range(min(len(req.answers), 5)):
        if req.answers[i] == correct_answers[i]:
            score += 20
        else:
            wrongs.append(f"{i+1}번")
    
    if db:
        db.collection("reports").add({
            "student_class": req.student_class,
            "student_name": req.student_name,
            "task_name": req.task_name,
            "type": "OMR 채점",
            "score": f"{score}점",
            "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

    return {"success": True, "score": score, "wrongs": wrongs}

# 6. 논술/요약 첨삭 및 장부 기록
@app.post("/api/chat")
def chat(req: ChatReq):
    # 나중에 Gemini 코드로 교체될 자리
    reply = "작성해주신 내용의 논리 구조가 훌륭합니다. 세부 근거만 조금 더 보완해 주세요."
    
    # 논술이나 첨삭 요청이면 장부에 기록
    if "[논술/요약 첨삭 요청]" in req.prompt and db:
        db.collection("reports").add({
            "student_class": req.student_class,
            "student_name": req.student_name,
            "task_name": "자유 논술/요약 제출",
            "type": "AI 첨삭",
            "score": "분석 완료",
            "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        
    return {"success": True, "reply": reply}

# 7. 성적 장부(리포트) 불러오기
@app.get("/api/admin/reports")
def get_reports():
    if not db:
        return {"success": False, "reports": []}
    docs = db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).stream()
    return {"success": True, "reports": [doc.to_dict() for doc in docs]}

# 8. AI 지식 주입
@app.post("/api/admin/knowledge/bulk")
def upload_knowledge(files: List[UploadFile] = File(...)):
    return {"success": True, "message": f"{len(files)}개의 파일이 서버에 이식되었습니다."}
