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

# DB 초기화
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

# AI 설정
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

class ChatRequest(BaseModel):
    school: str
    grade: str
    student_name: str
    prompt: str

class DeployExamRequest(BaseModel):
    title: str
    target_group: str
    raw_text: str

class BulkStudentRequest(BaseModel):
    students: list

# 💡 실시간 모의고사용 데이터 규격
class ExamSetupRequest(BaseModel):
    title: str
    time_limit: int
    pdf_data: str
    answer_key: str

class ExamSubmitRequest(BaseModel):
    school: str
    grade: str
    student_name: str
    title: str
    answers: list

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
            return {"success": True, "is_admin": False}
    return {"success": False, "detail": "명부에 이름이 없거나 학교/학년 정보가 틀립니다."}

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

@app.get("/api/admin/reports")
def get_reports():
    if db is None: return {"success": False, "reports": []}
    return {"success": True, "reports": [d.to_dict() for d in db.collection("reports").order_by("submitted_at", direction=firestore.Query.DESCENDING).limit(50).stream()]}

# 💡 수정: 여러 개의 파일을 한 번에 처리하도록 List 적용
@app.post("/api/admin/knowledge")
async def add_knowledge(
    title: str = Form(...), 
    content: str = Form(""), 
    files: Optional[List[UploadFile]] = File(None)
):
    if db is None: return {"success": False, "detail": "DB 연결 오류"}
    
    final_content = content
    if files:
        for file in files:
            if file.filename:
                try:
                    file_bytes = await file.read()
                    mime_type = file.content_type or "application/pdf"
                    res = model.generate_content(["이 문서의 모든 텍스트 내용과 핵심 지식을 빠짐없이 추출해서 정리해줘.", {"mime_type": mime_type, "data": file_bytes}])
                    final_content += f"\n\n[첨부문서({file.filename}) 분석 내용]\n{res.text}"
                except Exception as e:
                    print(f"파일 분석 오류: {e}")
                    
    db.collection("knowledge").add({"title": title, "content": final_content, "created_at": datetime.now()})
    return {"success": True}

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
    - 선택된 문제 유형: {q_types}
    - 문항 수 및 난이도: 킬러 {cnt_killer}문항, 준킬러 {cnt_semi}문항, 상 {cnt_high}문항, 중 {cnt_mid}문항, 하 {cnt_low}문항 (총 {total}문항)

    [난이도별 출제 원리]
    1. 킬러/준킬러: 지문의 인과, 순서, 목적 변경. 대조되는 정보 섞기. 심층 추론, 구체적 사례 대입 비판.
    2. 상/중: 사실적 이해(Paraphrasing), 주제/요지/구조 파악.
    3. 하: 단순 사실적 이해.

    [규칙]
    - 5지 선다형은 선택지 번호를 [1], [2], [3], [4], [5] 로 구성. (* 기호 절대 금지)
    - 포맷:
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
                    q_arr.append(f"{passage}\n\n{q_str}")
                    ans_arr.append(ans)
                    a_arr.append(f"▶️ 정답 및 해설\n{a_str}")

    db.collection("online_exams").document(req.title).set({
        "제목": req.title, "대상반": req.target_group,
        "문제지": "\n\n".join(q_arr), "해설지": "\n\n".join(a_arr),
        "출제일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    db.collection("knowledge").add({
        "title": f"[기출] {req.title}",
        "content": f"문제:\n{chr(10).join(q_arr)}\n\n해설:\n{chr(10).join(a_arr)}",
        "created_at": datetime.now()
    })
    return {"success": True}

# 💡 실시간 모의고사 개설 (원장님 -> DB 저장)
@app.post("/api/admin/set_exam")
def set_exam(req: ExamSetupRequest):
    if db:
        db.collection("settings").document("current_exam").set({
            "title": req.title,
            "time_limit": req.time_limit,
            "pdf_data": req.pdf_data,
            "answer_key": req.answer_key,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    return {"success": True}

# 💡 실시간 모의고사 입장 (학생 -> DB 호출)
@app.get("/api/exam/current")
def get_current_exam():
    if db:
        doc = db.collection("settings").document("current_exam").get()
        if doc.exists:
            return {"success": True, "exam": doc.to_dict()}
    return {"success": False, "detail": "현재 열려있는 실시간 모의고사가 없습니다."}

# 💡 실시간 모의고사 제출 (정답 비교 및 채점)
@app.post("/api/exam/submit")
def submit_exam(req: ExamSubmitRequest):
    if db is None: return {"success": False}
    doc = db.collection("settings").document("current_exam").get()
    score = 0
    wrongs = []
    
    if doc.exists:
        data = doc.to_dict()
        # 원장님이 입력한 정답(예: 3,1,4,2)을 배열로 변환
        correct_answers = [ans.strip() for ans in data.get("answer_key", "").split(",") if ans.strip()]
        total = len(correct_answers)
        correct_count = 0
        
        # 학생 답안과 정답 비교
        for i in range(min(len(req.answers), total)):
            if str(req.answers[i]).strip() == str(correct_answers[i]).strip():
                correct_count += 1
            else:
                wrongs.append(i+1)
        
        # 제출 안 한 나머지 문제 틀림 처리
        if len(req.answers) < total:
            for i in range(len(req.answers), total):
                wrongs.append(i+1)

        if total > 0: score = int((correct_count / total) * 100)
    
    # 성적 장부에 기록
    db.collection("reports").add({
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "student_name": req.student_name,
        "school": req.school,
        "grade": req.grade,
        "task_name": req.title,
        "type": "실시간 모의고사",
        "score": score,
        "wrongs": wrongs
    })
    return {"success": True, "score": score, "wrongs": wrongs}
