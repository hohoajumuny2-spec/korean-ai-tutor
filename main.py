import os
import json
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB 세팅
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

# AI 세팅 (키 이름 상관없이 작동)
gemini_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
model = None
if gemini_key:
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

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

class DeployExamRequest(BaseModel):
    title: str
    target_class: str
    raw_text: str

@app.get("/api/health")
def health_check(): return {"status": "ok"}

@app.post("/api/auth")
def authenticate(req: AuthRequest):
    if req.admin_password == "1234": return {"success": True, "is_admin": True}
    if db is None: raise HTTPException(status_code=500, detail="DB 오류")
    doc = db.collection("students").document(req.student_name).get()
    if doc.exists and doc.to_dict().get("student_class") == req.student_class:
        return {"success": True, "is_admin": False}
    return {"success": False, "detail": "명부 불일치"}

@app.post("/api/chat")
def chat_with_ai(req: ChatRequest):
    if model is None: return {"success": False, "reply": "AI 연결 오류"}
    try:
        res = model.generate_content(req.prompt)
        return {"success": True, "reply": res.text}
    except Exception as e:
        return {"success": False, "reply": str(e)}

@app.get("/api/admin/students")
def get_students():
    if db is None: return {"success": False, "students": []}
    return {"success": True, "students": [{"student_name": d.id, "student_class": d.to_dict().get("student_class", "")} for d in db.collection("students").stream()]}

@app.get("/api/admin/reports")
def get_reports():
    if db is None: return {"success": False, "reports": []}
    return {"success": True, "reports": [d.to_dict() for d in db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(50).stream()]}

@app.post("/api/omr/submit")
def submit_omr(req: OMRRequest):
    if db is None: return {"success": False, "detail": "DB 오류"}
    score = 100
    wrongs = []
    for i, ans in enumerate(req.answers):
        if not ans.strip():
            score -= 20; wrongs.append(i+1)
    if score < 0: score = 0
    db.collection("reports").add({
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "student_name": req.student_name, "student_class": req.student_class,
        "task_name": req.task_name, "type": "OMR 채점", "score": score, "wrongs": wrongs
    })
    return {"success": True, "score": score, "wrongs": wrongs}

# 💡 새롭게 추가된 네이티브 문제 출제 엔진
@app.post("/api/admin/generate")
async def generate_questions(
    q_mode: str = Form(...),
    q_style: str = Form(...),
    q_type: str = Form(...),
    total_q_count: int = Form(...),
    q_text: str = Form(""),
    files: Optional[List[UploadFile]] = File(None)
):
    if model is None: return {"success": False, "detail": "AI 연결 안 됨"}
    try:
        prompt = f"""
        로지에듀 국어학원 수석 출제 위원입니다. 오류 없는 문제를 출제하세요.
        - 모드: {q_mode} / 대상: {q_style} / 유형: {q_type} / 총 문항 수: {total_q_count}문제
        - 규칙: 별표(*) 사용 금지. 5지 선다는 무조건 [1], [2] 포맷 사용.
        - 출력형식:
        ===지문===
        (지문 내용)
        ===문항===
        1. 발문...
        [1] 보기1
        ===해설===
        정답: 1
        난이도: 중난이도
        유형: 5지 선다형
        해설: ...
        
        [입력 자료]
        {q_text}
        """
        contents = [prompt]
        if files:
            for f in files:
                if f.filename:
                    contents.append({"mime_type": f.content_type or "application/pdf", "data": await f.read()})
        
        response = model.generate_content(contents)
        return {"success": True, "result": response.text}
    except Exception as e:
        return {"success": False, "detail": str(e)}

# 💡 생성된 문제를 DB 시험장으로 쏘아주는 파서
@app.post("/api/admin/deploy_exam")
def deploy_generated_exam(req: DeployExamRequest):
    if db is None: return {"success": False, "detail": "DB 연결 오류"}
    
    raw = req.raw_text.replace("**", "").replace("[1]", "①").replace("[2]", "②").replace("[3]", "③").replace("[4]", "④").replace("[5]", "⑤")
    blocks = raw.split("===지문===")
    
    q_arr, ans_arr, diff_arr, type_arr, a_arr = [], [], [], [], []
    for b in blocks:
        if not b.strip(): continue
        parts = b.split("===문항===")
        if len(parts) > 0:
            passage = parts[0].strip()
            for q_block in parts[1:]:
                if "===해설===" in q_block:
                    qs = q_block.split("===해설===")
                    q_str, a_str = qs[0].strip(), qs[1].strip()
                    ans, diff, typ = "", "중난이도", "단답형"
                    for line in a_str.split('\n'):
                        if line.startswith("정답:"): ans = line.replace("정답:", "").strip()
                        if line.startswith("난이도:"): diff = line.replace("난이도:", "").strip()
                        if line.startswith("유형:"): typ = line.replace("유형:", "").strip()
                    
                    q_arr.append(f"{passage}\n\n{q_str}")
                    ans_arr.append(ans)
                    diff_arr.append(diff)
                    type_arr.append(typ)
                    a_arr.append(f"▶️ 정답 및 해설\n{a_str}")

    db.collection("online_exams").document(req.title).set({
        "제목": req.title, "대상반": req.target_class,
        "문제지": "\n\n".join(q_arr), "해설지": "\n\n".join(a_arr),
        "문항수": len(q_arr), "문항배열": q_arr, "정답배열": ans_arr,
        "난이도배열": diff_arr, "유형배열": type_arr,
        "출제일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    return {"success": True}
