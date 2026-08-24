import streamlit as st
import requests
import base64
import os
import csv
import pymupdf as fitz
from datetime import datetime

# API 키 및 저장 파일 설정 (스트림릿 비밀 금고 연동)
MY_API_KEY = st.secrets["MY_API_KEY"]
log_file_path = "학생질문_모니터링_기록.csv"

# 기록용 엑셀(CSV) 파일이 없으면 새로 만들기
if not os.path.exists(log_file_path):
    with open(log_file_path, mode='w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["질문 일시", "학생 이름", "질문 내용", "사진 첨부 여부", "AI 답변 요약"])

# 웹사이트 탭 이름과 아이콘 변경
st.set_page_config(page_title="24시간 국최", page_icon="🦉", layout="centered")

# 해설지 기억 저장소 초기화
if "reference_doc" not in st.session_state:
    st.session_state.reference_doc = ""

# ==========================================
# 👈 왼쪽 사이드바 메뉴 설정
# ==========================================
with st.sidebar:
    st.title("👤 학생 인증")
    student_name = st.text_input("본인의 이름을 정확히 입력하세요.", placeholder="예: 홍길동")
    st.info("이름을 입력해야 질문 창이 활성화됩니다.")
    
    st.divider()
    
    # SOS 원장님 호출 카카오톡 버튼
    st.title("🚨 SOS 원장님 호출")
    st.markdown("AI 튜터의 설명이 부족하다면 언제든 '찐' 국최 원장님을 호출하세요!")
    
    # ⭐️ 원장님의 실제 카카오톡 1:1 오픈채팅방 링크 적용 완료! ⭐️
    st.link_button("🚨 찐 국최 원장님께 직접 질문하기", "https://open.kakao.com/o/sERIEkKi")
    
    st.divider()
    
    # 관리자 전용 해설지 업로드 메뉴
    st.title("🔒 관리자 메뉴")
    admin_pw = st.text_input("관리자 비밀번호를 입력하세요.", type="password")
    
    if admin_pw == "1234":
        st.success("관리자 인증 성공")
        ref_file = st.file_uploader("오늘의 숙제/해설지 파일 업로드 (PDF/TXT)", type=["pdf", "txt"])
        
        if ref_file:
            if st.button("해설지 챗봇에 학습시키기"):
                with st.spinner("파일을 읽어 들이는 중입니다..."):
                    extracted_text = ""
                    if ref_file.name.lower().endswith('.pdf'):
                        doc = fitz.open(stream=ref_file.read(), filetype="pdf")
                        for page in doc:
                            extracted_text += page.get_text()
                        doc.close()
                    else:
                        extracted_text = ref_file.getvalue().decode("utf-8")
                    
                    st.session_state.reference_doc = extracted_text
                    st.success("✅ 해설지 학습 완료!")

# 학생이 이름을 입력하지 않으면 챗봇 화면을 띄우지 않음
if not student_name:
    st.warning("👈 화면 왼쪽 메뉴에 이름을 먼저 입력해 주세요.")
    st.stop()

# ==========================================
# 💬 메인 챗봇 화면 설정
# ==========================================
# 메인 화면 타이틀
st.title(f"🦉 24시간 국최 ({student_name} 학생)")
st.markdown("모르는 문제나 지문은 타이핑하거나 **사진을 찍어서** 올려주세요. 국최가 24시간 언제든 명쾌하게 답변해 드립니다!")

# 대화 기록 저장소 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 이전 대화 내용 화면에 그려주기
for msg in st.session_state.messages:
    if msg["role"] != "system":
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            if "image" in msg:
                st.image(msg["image"], width=350)
            st.markdown(msg["parts"][0]["text"])

# 사진 업로드 버튼
uploaded_file = st.file_uploader("📷 질문할 교재나 시험지 사진을 올려주세요.", type=["jpg", "jpeg", "png"])

# 학생이 질문을 입력했을 때 작동하는 코드
if prompt := st.chat_input("궁금한 점을 질문해 주세요."):
    
    # 1. 학생의 질문을 화면에 표시
    with st.chat_message("user"):
        if uploaded_file:
            st.image(uploaded_file, width=350)
        st.markdown(prompt)
        
    user_msg_data = {"role": "user", "parts": [{"text": prompt}]}
    if uploaded_file:
        user_msg_data["image"] = uploaded_file.getvalue()
    st.session_state.messages.append(user_msg_data)
    
    # 2. AI 튜터의 답변 생성 및 표시
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("분석 중입니다...")
        
        try:
            # 구글 AI 서버와 통신 준비
            list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={MY_API_KEY}"
            list_resp = requests.get(list_url)
            
            target_model = "gemini-3.6-flash" 
            if list_resp.status_code == 200:
                models_data = list_resp.json().get('models', [])
                valid_models = [m['name'].replace('models/', '') for m in models_data if 'generateContent' in m.get('supportedGenerationMethods', [])]
                if valid_models:
                    target_model = valid_models[0]
                    for m in valid_models:
                        if '3.6-flash' in m:
                            target_model = m
                            break

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={MY_API_KEY}"
            headers = {'Content-Type': 'application/json'}
            
            # AI의 역할(Role) 부여: 로지에듀 최준용 국어 원장 '국최'
            base_instruction = f"당신은 로지에듀 최준용 국어 원장 '국최'입니다. 학생 이름은 '{student_name}'입니다. 학생이 질문하면 빙빙 돌리지 말고 가장 정확하고 올바른 정답과 명쾌한 해설을 즉시 제공하세요. 추가적인 활동을 시키지 말고 궁금증을 완벽히 해결해 주어야 합니다."
            
            # 원장님이 업로드한 해설지가 있다면 우선 참고하도록 지시
            if st.session_state.reference_doc:
                base_instruction += f"\n\n[학원 자체 해설지 자료]\n아래 자료를 최우선으로 참고하여 답하세요. 자료와 무관한 질문이면 '해당 내용은 오늘 수업 범위가 아니니 원장님께 직접 질문하렴'이라고 대답하세요.\n\n{st.session_state.reference_doc}"
                
            parts_list = [{"text": f"{base_instruction}\n\n학생 질문: {prompt}"}]
            
            # 사진이 있으면 사진도 함께 전송
            if uploaded_file:
                image_bytes = uploaded_file.getvalue()
                encoded_image = base64.b64encode(image_bytes).decode('utf-8')
                parts_list.append({
                    "inlineData": {
                        "mimeType": uploaded_file.type,
                        "data": encoded_image
                    }
                })
                
            data = {"contents": [{"parts": parts_list}]}
            
            # 구글 AI에게 질문 보내고 답변 받기
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                ai_response = response.json()['candidates'][0]['content']['parts'][0]['text']
                message_placeholder.markdown(ai_response)
                st.session_state.messages.append({"role": "model", "parts": [{"text": ai_response}]})
                
                # 3. 질문 및 답변 내역을 엑셀(CSV) 파일에 몰래 기록하기
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                has_photo = "O" if uploaded_file else "X"
                
                with open(log_file_path, mode='a', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow([now_str, student_name, prompt, has_photo, ai_response[:50] + "..."])
                    
            else:
                error_msg = response.json().get('error', {}).get('message', '알 수 없는 서버 오류')
                message_placeholder.error(f"분석 중 오류가 발생했습니다 ({target_model}):\n{error_msg}")
        
        except Exception as e:
            message_placeholder.error(f"통신 오류가 발생했습니다: {e}")
