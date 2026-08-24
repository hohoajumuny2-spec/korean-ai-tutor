import streamlit as st
import requests
import base64
import os
import csv
import pymupdf as fitz
from datetime import datetime

# ==========================================
# ⭐️ 하루 1,500번 넉넉하게 돌아가는 가장 안정적인 공식 모델 ⭐️
# ==========================================
TARGET_MODEL = "gemini-1.5-pro" 
# ==========================================

# API 키 및 저장 파일 설정 
MY_API_KEY = st.secrets["MY_API_KEY"]
log_file_path = "학생질문_모니터링_기록.csv"
reference_file_path = "공용해설지_누적본.txt" 

# 기록 파일 초기화
if not os.path.exists(log_file_path):
    with open(log_file_path, mode='w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["질문 일시", "학생 이름", "질문 내용", "첨부파일 수", "AI 답변 요약"])

st.set_page_config(page_title="24시간 국최", page_icon="🦉", layout="centered")

# ==========================================
# 👈 왼쪽 사이드바 메뉴 설정
# ==========================================
with st.sidebar:
    st.title("👤 학생 인증")
    student_name = st.text_input("본인의 이름을 정확히 입력하세요.", placeholder="예: 이연서")
    
    if student_name:
        st.success(f"✅ {student_name} 학생, 환영합니다!")
    else:
        st.info("이름을 입력해야 질문 창이 활성화됩니다.")
    
    st.divider()
    
    st.title("🚨 SOS 원장님 호출")
    st.markdown("AI 튜터의 설명이 부족하다면 언제든 '찐' 국최 원장님을 호출하세요!")
    st.link_button("🚨 찐 국최 원장님께 직접 질문하기", "https://open.kakao.com/o/sERIEkKi")
    
    st.divider()
    
    st.title("🔒 관리자 메뉴")
    admin_pw = st.text_input("관리자 비밀번호를 입력하세요.", type="password")
    
    if admin_pw == "1234":
        st.success("관리자 인증 성공")
        
        ref_files = st.file_uploader("새로운 해설지 파일 업로드 (여러 개 가능)", type=["pdf", "txt"], accept_multiple_files=True)
        
        if ref_files:
            if st.button("해설지 누적 학습시키기"):
                with st.spinner("파일들을 읽어 들이고 공용 서버에 누적하는 중입니다..."):
                    extracted_text = ""
                    for ref_file in ref_files:
                        if ref_file.name.lower().endswith('.pdf'):
                            doc = fitz.open(stream=ref_file.read(), filetype="pdf")
                            for page in doc:
                                extracted_text += page.get_text()
                            doc.close()
                        else:
                            extracted_text += ref_file.getvalue().decode("utf-8") + "\n"
                    
                    with open(reference_file_path, mode='a', encoding='utf-8') as f:
                        f.write(f"\n\n--- [업로드 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ---\n")
                        f.write(extracted_text)
                    
                    st.success("✅ 해설지 누적 학습 완료! 이제 모든 학생의 챗봇에 즉시 적용됩니다.")
        
        if os.path.exists(reference_file_path):
            if st.button("🗑️ 누적된 해설지 전체 삭제 (초기화)"):
                os.remove(reference_file_path)
                st.warning("해설지 기억이 모두 깨끗하게 삭제되었습니다.")

# 이름이 없으면 여기서 화면을 멈춤
if not student_name:
    st.stop()

# ==========================================
# 💬 메인 챗봇 화면 설정
# ==========================================
st.title(f"🦉 24시간 국최 ({student_name} 학생)")
st.markdown("모르는 문제나 지문은 타이핑하거나 **사진/PDF를 첨부**해서 올려주세요. 국최가 24시간 언제든 명쾌하게 답변해 드립니다!")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    if msg["role"] != "system":
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            if "files" in msg:
                for f_data in msg["files"]:
                    if f_data["type"].startswith("image"):
                        st.image(f_data["bytes"], width=350)
                    else:
                        st.markdown(f"📄 **{f_data['name']}** (PDF 파일)")
            st.markdown(msg["parts"][0]["text"])

uploaded_files = st.file_uploader("📷 질문할 사진이나 PDF를 올려주세요. (여러 개 동시 업로드 가능)", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True)

if prompt := st.chat_input("궁금한 점을 질문해 주세요."):
    
    with st.chat_message("user"):
        if uploaded_files:
            for uf in uploaded_files:
                if uf.type.startswith("image"):
                    st.image(uf, width=350)
                else:
                    st.markdown(f"📄 **{uf.name}** (PDF 파일)")
        st.markdown(prompt)
        
    user_msg_data = {"role": "user", "parts": [{"text": prompt}]}
    if uploaded_files:
        file_list = []
        for uf in uploaded_files:
            file_list.append({"name": uf.name, "type": uf.type, "bytes": uf.getvalue()})
        user_msg_data["files"] = file_list
    st.session_state.messages.append(user_msg_data)
    
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("분석 중입니다...")
        
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{TARGET_MODEL}:generateContent?key={MY_API_KEY}"
            headers = {'Content-Type': 'application/json'}
            
            base_instruction = f"당신은 로지에듀 최준용 국어 원장 '국최'입니다. 학생 이름은 '{student_name}'입니다. 학생이 질문하면 빙빙 돌리지 말고 가장 정확하고 올바른 정답과 명쾌한 해설을 즉시 제공하세요. "
            
            if os.path.exists(reference_file_path):
                with open(reference_file_path, mode='r', encoding='utf-8') as f:
                    accumulated_doc = f.read()
                if accumulated_doc.strip():
                    base_instruction += f"\n\n[학원 자체 누적 해설지 자료]\n아래 자료를 우선적으로 참고하여 답하세요.\n\n{accumulated_doc}\n\n"
                    
            base_instruction += """
            [매우 중요한 지시사항]
            1. 학생의 질문이 '국어 학습(개념, 문법, 독해, 문학 등)'과 관련된 정당한 질문이라면, 위 자료에 없더라도 당신의 국어 지식을 총동원하여 원장님처럼 친절하고 정확하게 설명해 주어야 합니다. (절대 거절하지 마세요)
            2. 단, 학생의 질문이 국어 공부와 전혀 무관한 사적인 잡담이나 장난(예: 친구 이야기, 게임 이야기 등)이라면 절대로 답변하지 말고 반드시 "해당 내용은 오늘 수업 범위가 아니니 원장님께 직접 질문하렴"이라고 단호하게 대답하세요.
            """
                
            parts_list = [{"text": f"{base_instruction}\n\n학생 질문: {prompt}"}]
            
            if uploaded_files:
                for uf in uploaded_files:
                    file_bytes = uf.getvalue()
                    encoded_file = base64.b64encode(file_bytes).decode('utf-8')
                    parts_list.append({
                        "inlineData": {
                            "mimeType": uf.type,
                            "data": encoded_file
                        }
                    })
                
            data = {"contents": [{"parts": parts_list}]}
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                ai_response = response.json()['candidates'][0]['content']['parts'][0]['text']
                message_placeholder.markdown(ai_response)
                st.session_state.messages.append({"role": "model", "parts": [{"text": ai_response}]})
                
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                file_count = str(len(uploaded_files)) if uploaded_files else "0"
                
                with open(log_file_path, mode='a', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow([now_str, student_name, prompt, f"{file_count}개", ai_response[:50] + "..."])
                    
            else:
                error_msg = response.json().get('error', {}).get('message', '알 수 없는 서버 오류')
                message_placeholder.error(f"분석 중 오류가 발생했습니다:\n{error_msg}")
        
        except Exception as e:
            message_placeholder.error(f"통신 오류가 발생했습니다: {e}")
