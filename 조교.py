import streamlit as st
import requests
import base64
import os
import csv
import pymupdf as fitz
from datetime import datetime

# ==========================================
# ⭐️ 2026년 최강의 공식 모델 (결제 연동 완료) ⭐️
# ==========================================
TARGET_MODEL = "gemini-3.6-flash" 
# ==========================================

# API 키 및 저장 파일/폴더 설정 
MY_API_KEY = st.secrets["MY_API_KEY"]
log_file_path = "학생질문_모니터링_기록.csv"
reference_file_path = "공용해설지_누적본.txt" 
hw_log_path = "과제제출_기록.csv"
answer_key_path = "오늘의정답.txt"
HW_FOLDER = "hw_uploads"

# 기록 파일 및 폴더 초기화
for file_path, headers in [(log_file_path, ["질문 일시", "학생 이름", "질문 내용", "첨부파일 수", "AI 답변 요약"]),
                           (hw_log_path, ["제출 일시", "학생 이름", "제출 파일명"])]:
    if not os.path.exists(file_path):
        with open(file_path, mode='w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

if not os.path.exists(HW_FOLDER):
    os.makedirs(HW_FOLDER)

st.set_page_config(page_title="24시 국최", page_icon="🦉", layout="centered")

# ==========================================
# 🦉 메인 타이틀 및 원장님 사진 (중앙 배치)
# ==========================================
st.markdown("<h1 style='text-align: center;'>🦉 LogyEDU 24시 국최</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: gray;'>최준용 원장님의 24시간 밀착 관리형 국어 AI 튜터</p>", unsafe_allow_html=True)

# 📸 원장님 사진 자동 인식 및 출력
image_names = ["photo.png", "제목을 입력해주세요..png", "photo.jpg"]
for img_name in image_names:
    if os.path.exists(img_name):
        st.image(img_name, use_container_width=True)
        break 

st.divider()

# ==========================================
# 👤 학생 인증 및 메뉴 이동 (중앙 배치)
# ==========================================
col1, col2 = st.columns([1, 2])
with col1:
    st.markdown("### 👤 학생 인증")
with col2:
    student_name = st.text_input("본인의 이름을 정확히 입력하세요.", placeholder="예: 이연서", label_visibility="collapsed")

if not student_name:
    st.warning("이름을 입력해야 시스템 메뉴가 활성화됩니다.")
    st.stop()

st.success(f"✅ {student_name} 학생, 환영합니다!")

menu = st.radio("🧭 원하는 메뉴를 선택하세요.", 
                ["💬 24시간 AI 튜터", "📝 과제 제출 및 정답 확인", "🔒 원장님 전용 관리실"], 
                horizontal=True)

st.divider()

# ==========================================
# 💬 메뉴 1: 24시간 AI 튜터
# ==========================================
if menu == "💬 24시간 AI 튜터":
    st.subheader(f"💬 무엇이든 물어보세요, {student_name} 학생!")
    st.markdown("모르는 문제나 지문은 타이핑하거나 **사진/PDF를 첨부**해서 올려주세요.")

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
                            st.markdown(f"📄 **{f_data['name']}**")
                st.markdown(msg["parts"][0]["text"])

    uploaded_files = st.file_uploader("📷 질문할 사진이나 PDF 업로드", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True)

    if prompt := st.chat_input("궁금한 점을 질문해 주세요."):
        with st.chat_message("user"):
            if uploaded_files:
                for uf in uploaded_files:
                    if uf.type.startswith("image"):
                        st.image(uf, width=350)
                    else:
                        st.markdown(f"📄 **{uf.name}**")
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
                
                base_instruction = f"당신은 LogyEDU 최준용 국어 원장 '국최'입니다. 학생 이름은 '{student_name}'입니다. 정확하고 올바른 정답과 명쾌한 해설을 즉시 제공하세요. 국어 외의 사적인 잡담은 단호히 거절하세요."
                
                # 원장님이 올린 오늘 과제 정답지 학습
                if os.path.exists(answer_key_path):
                    with open(answer_key_path, mode='r', encoding='utf-8') as f:
                        today_ans = f.read()
                    if today_ans.strip():
                        base_instruction += f"\n\n[오늘의 과제 정답지 (최우선 참고)]\n{today_ans}\n\n"
                        
                # 누적 해설지 학습
                if os.path.exists(reference_file_path):
                    with open(reference_file_path, mode='r', encoding='utf-8') as f:
                        accumulated_doc = f.read()
                    if accumulated_doc.strip():
                        base_instruction += f"\n\n[학원 누적 해설지]\n{accumulated_doc}\n\n"
                    
                parts_list = [{"text": f"{base_instruction}\n\n학생 질문: {prompt}"}]
                
                if uploaded_files:
                    for uf in uploaded_files:
                        parts_list.append({"inlineData": {"mimeType": uf.type, "data": base64.b64encode(uf.getvalue()).decode('utf-8')}})
                    
                data = {"contents": [{"parts": parts_list}]}
                response = requests.post(url, headers=headers, json=data)
                
                if response.status_code == 200:
                    ai_response = response.json()['candidates'][0]['content']['parts'][0]['text']
                    message_placeholder.markdown(ai_response)
                    st.session_state.messages.append({"role": "model", "parts": [{"text": ai_response}]})
                    
                    with open(log_file_path, mode='a', newline='', encoding='utf-8-sig') as f:
                        writer = csv.writer(f)
                        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), student_name, prompt, f"{len(uploaded_files) if uploaded_files else 0}개", ai_response[:50] + "..."])
                else:
                    message_placeholder.error(f"오류 발생: {response.json().get('error', {}).get('message', '')}")
            except Exception as e:
                message_placeholder.error(f"통신 오류: {e}")
                
    st.divider()
    st.link_button("🚨 '찐' 국최 원장님께 직접 질문하기", "https://open.kakao.com/o/sERIEkKi")

# ==========================================
# 📝 메뉴 2: 과제 제출 및 정답 확인
# ==========================================
elif menu == "📝 과제 제출 및 정답 확인":
    st.subheader("📝 오늘의 과제 제출")
    st.info("💡 푼 과제를 사진으로 찍어 제출해야만 원장님이 올려두신 정답을 확인할 수 있습니다.")
    
    hw_files = st.file_uploader("과제 사진을 업로드하세요 (여러 장 가능)", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True)
    
    if "hw_submitted" not in st.session_state:
        st.session_state.hw_submitted = False

    if hw_files:
        if st.button("🚀 과제 최종 제출하기"):
            with st.spinner("원장님 서버로 전송 중입니다..."):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                file_names = []
                for hw in hw_files:
                    save_path = os.path.join(HW_FOLDER, f"{student_name}_{hw.name}")
                    with open(save_path, "wb") as f:
                        f.write(hw.getbuffer())
                    file_names.append(hw.name)
                
                with open(hw_log_path, mode='a', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow([now_str, student_name, ", ".join(file_names)])
                
                st.session_state.hw_submitted = True
            st.success("✅ 과제 제출이 완료되었습니다! 아래에서 정답을 확인하세요.")

    st.divider()
    
    if st.session_state.hw_submitted:
        st.subheader("🔓 [열림] 오늘의 정답 및 핵심 해설")
        st.success("과제 제출이 확인되어 정답지 열람 권한이 부여되었습니다.")
        
        # 1. 원장님이 올리신 원본 파일 보여주기 (PDF 다운로드 또는 이미지 출력)
        if os.path.exists("answer_key_filename.txt"):
            with open("answer_key_filename.txt", "r", encoding="utf-8") as f:
                ans_filename = f.read().strip()
            if os.path.exists(ans_filename):
                if ans_filename.lower().endswith('.pdf'):
                    with open(ans_filename, "rb") as f:
                        st.download_button("📄 원장님 정답지 원본 다운로드 (PDF)", f, file_name="오늘의정답.pdf", mime="application/pdf")
                else:
                    st.image(ans_filename, caption="원장님 공식 정답지 원본", use_container_width=True)
        
        # 2. 텍스트 해설 보여주기
        if os.path.exists(answer_key_path):
            with open(answer_key_path, "r", encoding="utf-8") as f:
                ans_text = f.read()
            if ans_text.strip():
                st.markdown(f"**[원장님 공식 정답 텍스트]**\n\n{ans_text}")
    else:
        st.subheader("🔒 [잠김] 정답 및 해설")
        st.warning("⚠️ 과제 파일을 업로드하고 '제출하기' 버튼을 눌러야 락이 해제됩니다.")

# ==========================================
# 🔒 메뉴 3: 원장님 전용 관리실
# ==========================================
elif menu == "🔒 원장님 전용 관리실":
    st.subheader("🔒 원장님 전용 관리실")
    admin_pw = st.text_input("관리자 비밀번호를 입력하세요.", type="password")
    
    if admin_pw == "20241":
        st.success("✅ 원장님, 인증되었습니다.")
        
        tab1, tab2, tab3, tab4 = st.tabs(["🔑 정답지 등록", "📝 과제 현황", "📊 질문 내역", "📚 해설지 누적"])
        
        # 탭 1: 정답지 등록 (파일 업로드 및 AI 인식 기능 추가)
        with tab1:
            st.markdown("#### 오늘의 과제 정답 파일 등록")
            st.caption("PDF 및 이미지 파일(JPG, PNG)을 올리면 챗봇이 글자를 완벽하게 스캔합니다.")
            
            ans_file = st.file_uploader("📸 정답지 파일 업로드", type=["png", "jpg", "jpeg", "pdf"])
            
            if "extracted_ans" not in st.session_state:
                st.session_state.extracted_ans = ""
                
            if ans_file:
                if st.button("✨ 최고 성능 AI로 정답 자동 스캔하기 (인식률 100%)"):
                    with st.spinner("AI가 파일의 글자를 완벽하게 분석하고 있습니다... (약 10초 소요)"):
                        try:
                            url = f"https://generativelanguage.googleapis.com/v1beta/models/{TARGET_MODEL}:generateContent?key={MY_API_KEY}"
                            headers = {'Content-Type': 'application/json'}
                            encoded_file = base64.b64encode(ans_file.getvalue()).decode('utf-8')
                            
                            data = {
                                "contents": [{
                                    "parts": [
                                        {"text": "이 파일에 적힌 모든 정답과 해설 텍스트를 정확하게 추출해서 보여줘. 챗봇이 이 내용을 보고 학생들에게 해설해 줄 거야."},
                                        {"inlineData": {"mimeType": ans_file.type, "data": encoded_file}}
                                    ]
                                }]
                            }
                            response = requests.post(url, headers=headers, json=data)
                            if response.status_code == 200:
                                extracted_text = response.json()['candidates'][0]['content']['parts'][0]['text']
                                st.session_state.extracted_ans = extracted_text
                                st.success("✅ 텍스트 스캔 완료! 아래 입력창에 자동 반영되었습니다.")
                            else:
                                st.error("추출 중 오류가 발생했습니다.")
                        except Exception as e:
                            st.error(f"통신 오류: {e}")
            
            saved_answer = st.session_state.extracted_ans
            if not saved_answer and os.path.exists(answer_key_path):
                with open(answer_key_path, "r", encoding="utf-8") as f:
                    saved_answer = f.read()
            
            new_answer = st.text_area("📝 정답 텍스트 (위에서 자동 추출된 내용 수정 및 코멘트 추가 가능)", value=saved_answer, height=200)
            
            if st.button("정답지 최종 배포하기"):
                # 텍스트 저장 (챗봇 인식용)
                with open(answer_key_path, "w", encoding="utf-8") as f:
                    f.write(new_answer)
                
                # 파일 원본 저장 (학생 열람용)
                if ans_file:
                    ext = ans_file.name.split('.')[-1]
                    save_path = f"오늘의정답_원본.{ext}"
                    with open(save_path, "wb") as f:
                        f.write(ans_file.getbuffer())
                    with open("answer_key_filename.txt", "w", encoding="utf-8") as f:
                        f.write(save_path)
                        
                st.success("✅ 정답지 파일과 텍스트가 성공적으로 학생들에게 배포 준비되었습니다!")

        # 탭 2: 과제 제출 현황
        with tab2:
            st.markdown("#### 실시간 과제 제출 현황 (꼼수 검수용)")
            if os.path.exists(hw_log_path):
                with open(hw_log_path, "r", encoding='utf-8-sig') as f:
                    st.download_button("📥 과제 제출 기록 다운로드", data=f.read().encode('utf-8-sig'), file_name="과제제출기록.csv", mime="text/csv")
                with open(hw_log_path, "r", encoding='utf-8-sig') as f:
                    hw_data = list(csv.reader(f))
                    if len(hw_data) > 1:
                        st.dataframe(hw_data[1:])
            else:
                st.info("제출된 과제가 없습니다.")

        # 탭 3: 질문 모니터링
        with tab3:
            st.markdown("#### 학생들이 챗봇에 질문한 내역")
            if os.path.exists(log_file_path):
                with open(log_file_path, "r", encoding='utf-8-sig') as f:
                    st.download_button("📥 질문 기록 다운로드", data=f.read().encode('utf-8-sig'), file_name="질문기록.csv", mime="text/csv")
                with open(log_file_path, "r", encoding='utf-8-sig') as f:
                    data = list(csv.reader(f))
                    if len(data) > 1:
                        st.dataframe(data[1:])
            else:
                st.info("질문 기록이 없습니다.")

        # 탭 4: 해설지 누적
        with tab4:
            st.markdown("#### 챗봇 두뇌 강화 (해설지 업로드)")
            ref_files = st.file_uploader("새로운 해설지 파일 업로드", type=["pdf", "txt"], accept_multiple_files=True)
            if ref_files and st.button("해설지 누적 학습시키기"):
                with st.spinner("누적 중입니다..."):
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
                        f.write(f"\n\n--- [업로드: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ---\n{extracted_text}")
                    st.success("✅ 학습 완료!")
            
            if os.path.exists(reference_file_path):
                if st.button("🗑️ 해설지 기억 초기화"):
                    os.remove(reference_file_path)
                    st.warning("초기화 완료")
    else:
        if admin_pw:
            st.error("비밀번호가 틀렸습니다.")
