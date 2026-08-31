import os
import json
import time
import shutil
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================
# 🚀 FastAPI 앱 및 RAG 지식 베이스 세팅
# ==========================================
app = FastAPI(title="LogyEDU 24시 국최 API Engine", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

KNOWLEDGE_DIR = "knowledge_base"
os.makedirs(KNOWLEDGE_DIR, exist_ok=True)

# 구글 Gemini 연동
MY_API_KEY = os.getenv("MY_API_KEY", "YOUR_GEMINI_API_KEY")
genai.configure(api_key=MY_API_KEY)

# 파이어베이스 초기화
if not firebase_admin._apps:
    try:
        if os.path.exists("firebase_key.json"):
            cred = credentials.Certificate("firebase_key.json")
            firebase_admin.initialize_app(cred)
    except Exception as e:
        pass

try:
    db = firestore.client()
except Exception:
    db = None

# 임시 메모리 DB (파이어베이스 대용)
MEMORY_DB = {
    "students": [
        {"class": "고1 미강고", "name": "이연서"},
        {"class": "고1 미사고", "name": "김민준"},
        {"class": "고1 하남고", "name": "박서준"},
        {"class": "논술", "name": "최준용"}
    ],
    "omr_tasks": {"고1 미강고": {"미강고 중간고사 대비 1회": ["1", "3", "2", "5", "4", "O", "X", "단답형답"]}},
    "videos": [],
    "live_exam": None,
    "submissions": []
}

# ==========================================
# 📄 Request 데이터 모델
# ==========================================
class AuthReq(BaseModel):
    student_class: str
    student_name: str
    admin_password: Optional[str] = None

class ChatReq(BaseModel):
    student_class: str
    student_name: str
    prompt: str

class VideoLectureReq(BaseModel):
    title: str
    target_class: str
    youtube_url: str
    description: Optional[str] = ""

class LiveExamStartReq(BaseModel):
    exam_title: str
    target_class: str
    time_limit_minutes: int
    questions: Optional[List[Dict[str, Any]]] = []

class LiveExamSubmitReq(BaseModel):
    student_class: str
    student_name: str
    exam_title: str
    answers: List[str]

class OMRSubmitReq(BaseModel):
    student_class: str
    student_name: str
    task_name: str
    answers: List[str]

# ==========================================
# 🎯 API Endpoints
# ==========================================

# 1. 인증 API
@app.post("/api/auth")
def authenticate(req: AuthReq):
    if req.student_class == "논술" and req.student_name == "최준용":
        if req.admin_password == "2024":
            return {"success": True, "is_admin": True, "message": "원장님 관리자 모드가 활성화되었습니다."}
        raise HTTPException(status_code=401, detail="관리자 비밀번호 불일치")
    return {"success": True, "is_admin": False, "message": f"{req.student_name} 학생 인증 완료"}


# 2. 🧠 RAG 기반 AI 질문 API
@app.post("/api/chat")
async def ai_chat(req: ChatReq):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # 지식 베이스 읽기
        academy_materials = ""
        for filename in os.listdir(KNOWLEDGE_DIR):
            if filename.endswith(".txt"):
                file_path = os.path.join(KNOWLEDGE_DIR, filename)
                with open(file_path, "r", encoding="utf-8") as f:
                    academy_materials += f"\n\n[자료명: {filename}]\n{f.read()}"

        system_prompt = f"""
        당신은 '로지에듀 최준용 국어학원'의 전용 AI 국최입니다. 학생 이름: {req.student_name}, 소속: {req.student_class}.
        
        [로지에듀 공식 자료]
        {academy_materials if academy_materials else "현재 등록된 자료가 없습니다."}

        [🚨 답변 규칙]
        1. 질문의 답이 [로지에듀 공식 자료]에 있다면 오직 그 내용을 근거로 완벽히 해설하세요.
        2. 공식 자료에 내용이 없다면 일반 지식으로 대답하되, 마지막에 반드시 "※ 안내: 위 해설은 학원 공식 자료에 없는 내용으로, AI 국최의 외부 지식을 활용하여 답변했습니다." 라고 적으세요.
        3. 시작할 때 '안녕하세요! AI 국최입니다.'로 인사하세요.
        """
        
        response = model.generate_content(f"{system_prompt}\n\n[학생 질문]: {req.prompt}")
        return {"success": True, "reply": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 오류: {str(e)}")


# 3. 🧠 원장님 관제실: RAG 지식 대량 업로드
@app.post("/api/admin/knowledge/bulk")
async def upload_knowledge_bulk(files: List[UploadFile] = File(...)):
    try:
        saved_count = 0
        for file in files:
            file_path = os.path.join(KNOWLEDGE_DIR, file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            saved_count += 1
        return {"success": True, "message": f"총 {saved_count}개의 학원 자료가 AI 두뇌에 완벽히 이식되었습니다!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"업로드 실패: {str(e)}")


# 4. 동영상 강의 API
@app.get("/api/videos/{student_class}")
def get_videos(student_class: str):
    videos = [v for v in MEMORY_DB["videos"] if v["target_class"] in [student_class, "전체"]]
    return {"success": True, "videos": videos}

@app.post("/api/admin/videos")
def add_video(req: VideoLectureReq):
    video_id = req.youtube_url.split("youtu.be/")[1].split("?")[0] if "youtu.be/" in req.youtube_url else req.youtube_url.split("v=")[1].split("&")[0] if "v=" in req.youtube_url else req.youtube_url
    new_video = {
        "id": f"vid-{len(MEMORY_DB['videos'])+1}", "title": req.title,
        "target_class": req.target_class, "embed_url": f"https://www.youtube.com/embed/{video_id}", "description": req.description
    }
    MEMORY_DB["videos"].append(new_video)
    return {"success": True, "message": "동영상 강의 배포 완료"}


# 5. 실시간 모의고사 API
@app.get("/api/live/status/{student_class}")
def get_live_exam_status(student_class: str):
    live_data = MEMORY_DB.get("live_exam")
    if not live_data or live_data["target_class"] not in [student_class, "전체"]:
        return {"active": False}
    
    remain_ms = live_data["end_timestamp"] - int(time.time() * 1000)
    if remain_ms <= 0: return {"active": False, "message": "시간 종료"}
    
    return {"active": True, "exam_title": live_data["exam_title"], "remaining_ms": remain_ms, "questions": live_data["questions"]}

@app.post("/api/admin/live/start")
def start_live_exam(req: LiveExamStartReq):
    MEMORY_DB["live_exam"] = {
        "exam_title": req.exam_title, "target_class": req.target_class,
        "end_timestamp": int((datetime.now() + timedelta(minutes=req.time_limit_minutes)).timestamp() * 1000),
        "questions": [{"text": "1. 다음 중 적절한 것은?", "options": ["1", "2", "3", "4", "5"]}] # 임시 문항 세팅
    }
    return {"success": True, "message": f"'{req.exam_title}' 실시간 모의고사 배포 완료"}

@app.post("/api/admin/live/stop")
def stop_live_exam():
    MEMORY_DB["live_exam"] = None
    return {"success": True, "message": "모의고사 강제 종료"}

@app.post("/api/live/submit")
def submit_live_exam(req: LiveExamSubmitReq):
    MEMORY_DB["submissions"].append(req.dict())
    return {"success": True, "message": "답안 제출 완료"}


# 6. OMR 자동 채점 API
@app.post("/api/omr/submit")
def submit_omr(req: OMRSubmitReq):
    correct_answers = MEMORY_DB["omr_tasks"].get(req.student_class, {}).get(req.task_name, [])
    if not correct_answers:
        raise HTTPException(status_code=404, detail="해당 과제의 정답 세팅 정보가 없습니다.")

    total_q = len(correct_answers)
    wrongs = []
    details = []

    for i in range(total_q):
        s_ans = req.answers[i].strip().lower() if i < len(req.answers) else "미입력"
        c_ans = correct_answers[i].strip().lower()
        if s_ans != c_ans:
            wrongs.append(f"{i+1}번")
            details.append({"q_num": i+1, "correct": False, "student": s_ans, "answer": c_ans})
        else:
            details.append({"q_num": i+1, "correct": True, "student": s_ans, "answer": c_ans})

    score = int(((total_q - len(wrongs)) / total_q) * 100) if total_q > 0 else 0
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    result_data = {
        "datetime": now_str, "class": req.student_class, "name": req.student_name,
        "task_name": req.task_name, "score": score, "wrongs": wrongs, "details": details
    }
    MEMORY_DB["submissions"].append(result_data)
    
    return {"success": True, "score": score, "wrongs": wrongs, "details": details}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)