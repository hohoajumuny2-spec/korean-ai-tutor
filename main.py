import requests # 파일 맨 위쪽에 있는지 확인하세요

# ==========================================
# 📱 알림 발송 설정 (텔레그램 봇 연동)
# ==========================================
TELEGRAM_TOKEN = "여기에_원장님_봇토큰_입력"
TELEGRAM_CHAT_ID = "여기에_원장님_챗아이디_입력"

def send_notification(message: str):
    """원장님 텔레그램으로 즉시 알림을 전송하는 함수"""
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=3)
        except Exception as e:
            print(f"알림 전송 실패: {e}")

# ... (기존 코드 유지) ...

# 🚀 1. 로그인 시 알림 보내기 (기존 /api/auth 라우터 내부 수정)
@app.post("/api/auth")
def login(req: LoginRequest):
    # ...(기존 인증 로직 유지)...
    
    # 인증 성공 시 알림 전송 (관리자 로그인은 제외)
    if not is_admin:
        alert_msg = f"🟢 [로그인 알림]\n{req.school} {req.grade}학년 {req.student_name} 학생이 스마트 학습실에 접속했습니다."
        send_notification(alert_msg)
        
    return {"success": True, "is_admin": is_admin}

# 🚀 2. 학생이 AI 국최에게 질문 시 알림 보내기 (기존 /api/chat 라우터 내부 수정)
@app.post("/api/chat")
def chat(school: str = Form(...), grade: str = Form(...), student_name: str = Form(...), prompt: str = Form(...)):
    # ...(기존 AI 답변 생성 로직 유지)...
    
    # 질문 등록 시 알림 전송
    alert_msg = f"💬 [새로운 질문 도착]\n👤 학생: {school} {grade} {student_name}\n❓ 질문 내용: {prompt}"
    send_notification(alert_msg)
    
    return {"success": True, "reply": ai_reply}
