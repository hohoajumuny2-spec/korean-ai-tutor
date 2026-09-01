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

# ==========================================
# DB 및 AI 초기화
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

# 💡 확실한 정답: 서버가 에러창에서 대놓고 요구한 'gemini-3.6-flash'로 영구 고정
gemini_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
model = None
if gemini_key:
    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel('gemini-3.6-flash')

# ==========================================
# 데이터 모델
# ==========================================
class AuthRequest(BaseModel):
    school: str
    grade: str
    student_name: str
    admin_password: str = ""

class ChatRequest(BaseModel):
    school: str
    grade: str
    student_name: str
    prompt: str

class OMRRequest(BaseModel):
    school: str
    grade: str
    student_name: str
    task_name: str
    answers: list

class DeployExamRequest(BaseModel):
    title: str
    target_group: str
    raw_text: str

class BulkStudentRequest(BaseModel):
    students: list

class KnowledgeRequest(BaseModel):
    title: str
    content: str

@app.get("/api/health")
def health_check(): return {"status": "ok"}

# ==========================================
# 1. 로그인 (학교/학년/이름 기준) 및 로그인 유지
# ==========================================
@app.post("/api/auth")
def authenticate(req: AuthRequest):
    if req.admin_password == "1234": return {"success": True, "is_admin": True}
    if db is None: raise HTTPException(status_code=500, detail="DB 오류")
    
    doc = db.collection("students").document(req.student_name).get()
    if doc.exists:
        data = doc.to_dict()
        if data.get("school") == req.school and data.get("grade") == req.grade:
            return {"success": True, "is_admin": False}
    return {"success": False, "detail": "명부에 이름이 없거나 학교/학년 정보가 틀립니다."}

# ==========================================
# 2. AI 튜터 (학습 데이터 기반 RAG 검색)
# ==========================================
@app.post("/api/chat")
def chat_with_ai(req: ChatRequest):
    if model is None: return {"success": False, "reply": "AI 연결 오류."}
    
    knowledge_base = ""
    if db:
        kb_docs = db.collection("knowledge").limit(10).stream()
        knowledge_base = "\n".join([f"[{d.to_dict().get('title')}] {d.to_dict().get('content')}" for d in kb_docs])

    system_prompt = f"""
    당신은 로지에듀 국어학원 최준용 원장님의 AI 튜터 '국최'입니다.
    아래 [학원 누적 자료]는 원장님이 직접 등록한 수업 자료 및 출제/해설 데이터입니다.
    학생의 질문에 대답할 때, **이 자료를 최우선으로 참고하여 답변**하세요.
    자료에 없는 내용이라면 일반적인 국어 지식을 활용하여 친절하게 설명해 주세요.

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

# ==========================================
# 3. 학생 관리 및 일괄 엑셀 등록
# ==========================================
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

@app.delete("/api/admin/student/{name}")
def delete_student(name: str):
    if db is None: return {"success": False}
    db.collection("students").document(name).delete()
    return {"success": True}

# ==========================================
# 4. 성적 및 지식 베이스(학습) 관리
# ==========================================
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
        "student_name": req.student_name, "school": req.school, "grade": req.grade,
        "task_name": req.task_name, "type": "OMR 채점", "score": score, "wrongs": wrongs
    })
    return {"success": True, "score": score, "wrongs": wrongs}

@app.post("/api/admin/knowledge")
def add_knowledge(req: KnowledgeRequest):
    if db:
        db.collection("knowledge").add({"title": req.title, "content": req.content, "created_at": datetime.now()})
    return {"success": True}

# ==========================================
# 5. 정밀 세분화된 AI 문제 출제 엔진
# ==========================================
@app.post("/api/admin/generate")
async def generate_questions(
    q_mode: str = Form(...), q_style: str = Form(...), q_types: str = Form(...),
    cnt_killer: int = Form(0), cnt_semi: int = Form(0), cnt_high: int = Form(0), cnt_mid: int = Form(0), cnt_low: int = Form(0),
    q_text: str = Form(""), files: Optional[List[UploadFile]] = File(None)
):
    if model is None: return {"success": False, "detail": "AI 연결 안 됨"}
    total = cnt_killer + cnt_semi + cnt_high + cnt_mid + cnt_low
    
    prompt = f"""
    당신은 로지에듀 국어학원의 수석 출제 위원입니다. 주어진 텍스트를 바탕으로 완벽한 문제를 출제하세요.

    [출제 요청 사항]
    - 선택된 문제 유형: {q_types} (이 유형들 중에서만 섞어서 출제)
    - 문항 수 및 난이도: 킬러 {cnt_killer}문항, 준킬러 {cnt_semi}문항, 상 {cnt_high}문항, 중 {cnt_mid}문항, 하 {cnt_low}문항 (총 {total}문항)

    [난이도별 출제 원리 - 엄격하게 지킬 것]
    1. 킬러/준킬러: 지문의 인과, 순서, 목적을 교묘하게 바꾸거나, 대조되는 정보의 차이점 중 하나를 섞어서 오답을 만드세요. 지문에 생략된 전제를 심층 추론하게 하거나, 구체적 사례(보기)에 대입하여 비판하는 문제로 구성하세요.
    2. 난이도 상/중: 지문에 명시된 정보의 일치/불일치(Paraphrasing 활용), 문단별 핵심어 및 글 전체의 주제/요지, 구조와 전개 방식을 묻는 문제로 구성하세요.
    3. 난이도 하: 지문의 내용을 단순히 사실적으로 묻는 직관적인 문제로 구성하세요.

    [규칙]
    - 5지 선다형은 선택지 번호를 [1], [2], [3], [4], [5] 로 구성하세요. (* 등 마크다운 기호 사용 절대 금지)
    - 출력 포맷:
    ===지문===
    (내용)
    ===문항===
    1. 발문
    [1] ...
    ===해설===
    정답: ...
    난이도: ...
    유형: ...
    해설: ...

    [입력 자료]
    {q_text}
    """
    contents = [prompt]
    if files:
        for f in files:
            if f.filename: contents.append({"mime_type": f.content_type or "application/pdf", "data": await f.read()})
    
    try:
        response = model.generate_content(contents)
        return {"success": True, "result": response.text}
    except Exception as e:
        return {"success": False, "detail": str(e)}

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
        "제목": req.title, "대상반": req.target_group,
        "문제지": "\n\n".join(q_arr), "해설지": "\n\n".join(a_arr),
        "문항수": len(q_arr), "문항배열": q_arr, "정답배열": ans_arr,
        "난이도배열": diff_arr, "유형배열": type_arr,
        "출제일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    db.collection("knowledge").add({
        "title": f"[기출] {req.title}",
        "content": f"문제:\n{chr(10).join(q_arr)}\n\n해설:\n{chr(10).join(a_arr)}",
        "created_at": datetime.now()
    })
    
    return {"success": True}
