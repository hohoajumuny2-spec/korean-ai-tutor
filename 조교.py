import streamlit as st
import os
import sys
import subprocess
import csv
import base64
import requests
import pymupdf as fitz
from datetime import datetime

# ==========================================
# 🚨 서버 필수 부품 강제 설치
# ==========================================
@st.cache_resource
def ensure_dependencies():
    try:
        import google.generativeai
        import pymupdf
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pymupdf", "requests", "google-generativeai"])

ensure_dependencies()

import google.generativeai as genai

# ==========================================
# 🔒 비밀 금고 안전장치 (열쇠 확인)
# ==========================================
if "MY_API_KEY" not in st.secrets:
    st.warning("🔑 아직 열쇠가 없습니다! 우측 하단 `< 앱 관리 (Manage app)` -> `Settings` -> `Secrets` 에 구글 API 키를 먼저 넣어주세요.")
    st.stop()

MY_API_KEY = st.secrets["MY_API_KEY"]
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# 구글 다이렉트 엔진에 원장님 열쇠 꽂기
genai.configure(api_key=MY_API_KEY)

# ==========================================
# 🤖 구글 서버 내 열쇠 스캔 및 호환 모델 자동 장착
# ==========================================
@st.cache_resource
def get_compatible_models():
    try:
        # 원장님 키로 접근 가능한 모든 모델 목록을 스캔
        available_models = [m.name.replace("models/", "") for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # 최신 1.5 모델이 사용 가능한 경우 (사진/텍스트 통합 처리)
        if "gemini-1.5-flash" in available_models:
            return "gemini-1.5-flash", "gemini-1.5-flash"
        elif "gemini-1.5-pro" in available_models:
            return "gemini-1.5-pro", "gemini-1.5-pro"
        
        # 구형 1.0 모델만 사용 가능한 특수 계정인 경우 (사진/텍스트 분리)
        if "gemini-pro" in available_models:
            return "gemini-pro", "gemini-pro-vision"
            
        # 만약 목록을 못 가져오면 가장 뼈대가 되는 기본값으로 강제 세팅
        return "gemini-pro", "gemini-pro-vision"
    except Exception:
        return "gemini-pro", "gemini-pro-vision"

TEXT_MODEL, VISION_MODEL = get_compatible_models()

def send_telegram_alert(message):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=3)
        except Exception:
            pass 

# 파일 및 폴더 설정
log_file_path = "학생질문_모니터링_기록.csv"
reference_file_path = "공용해설지_누적본.txt" 
hw_log_path = "과제제출_기록.csv"
HW_FOLDER = "hw_uploads"
ANS_FOLDER = "answers"

CLASS_LIST = [
    "중등부 문해력", "고1 미강고", "고1 미사고", "고1 하남고", "고1 풍산고",
    "고2 미강고 토요일", "고2 미강고 일요일", "고2 하남고", "고2 미사고", "고2 풍산고",
    "고3 / N수", "모의고사", "논술"
]

def get_safe_name(name):
    return name.replace("/", "_").replace(" ", "")

for folder in [HW_FOLDER, ANS_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

for file_path, headers in [(log_file_path, ["질문 일시", "반 이름", "학생 이름", "질문 내용", "첨부파일 수", "AI 답변 요약"]),
                           (hw_log_path, ["제출 일시", "반 이름", "학생 이름", "제출 파일명"])]:
    if not os.path.exists(file_path):
        with open(file_path, mode='w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

st.set_page_config(page_title="24시 국최", page_icon="🦉", layout="centered")

# ==========================================
# 🦉 메인 타이틀
# ==========================================
st.markdown("<h1 style='text-align: center;'>🦉 LogyEDU 24시 국최</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: gray;'>최준용 원장님의 24시간 밀착 관리형 국어 AI 튜터</p>", unsafe_allow_html=True)

image_names = ["photo.png", "제목을 입력해주세요..png", "photo.jpg"]
for img_name in image_names:
    if os.path.exists(img_name):
        st.image(img_name, use_container_width=True)
        break 

st.divider()

# ==========================================
# 👤 학생 인증 및 반 선택
# ==========================================
col1, col2 = st.columns([1, 2])
with col1:
    st.markdown("### 👤 학생 인증")
with col2:
    student_class = st.selectbox("본인의 수강 반을 선택하세요.", ["반을 선택해 주세요."] + CLASS_LIST, label_visibility="collapsed")
    student_name = st.text_input("본인의 이름을 정확히 입력하세요.", placeholder="예: 이연서", label_visibility="collapsed")

if student_class == "반을 선택해 주세요." or not student_name:
    st.warning("수강 반 선택과 이름 입력을 완료해야 시스템 메뉴가 활성화됩니다.")
    st.stop()

st.success(f"✅ [{student_class}] {student_name} 학생, 환영합니다!")

menu = st.radio("🧭 원하는 메뉴를 선택하세요.", 
                ["💬 24시간 AI 튜터", "📝 과제 제출 및 정답 확인", "🔒 원장님 전용 관리실"], 
                horizontal=True)

st.divider()

safe_class = get_safe_name(student_class)
class_ans_txt = os.path.join(ANS_FOLDER, f"ans_txt_{safe_class}.txt")
class_ans_file_info = os.path.join(ANS_FOLDER, f"ans_file_{safe_class}.txt")

# ==========================================
# 💬 메뉴 1: 24시간 AI 튜터
# ==========================================
if menu == "💬 24시간 AI 튜터":
    st.subheader(f"💬 무엇이든 물어보세요, {student_name} 학생!")
    st.markdown(f"모르는 문제나 지문은 타이핑하거나 **사진 또는 PDF 파일을 첨부**해서 올려주세요. *(현재 자동 연결된 모델: {TEXT_MODEL})*")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        if msg["role"] != "system":
            with st.chat_message("user" if msg["role"] == "user" else "assistant"):
                st.markdown(msg["content"])

    uploaded_files = st.file_uploader("📷 질문할 사진이나 PDF 파일 업로드", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True)

    if prompt := st.chat_input("궁금한 점을 질문해 주세요."):
        with st.chat_message("user"):
            st.markdown(prompt)
            if uploaded_files:
                for uf in uploaded_files:
                    if uf.type.startswith("image"):
                        st.image(uf, width=350)
                    else:
                        st.markdown(f"📄 **{uf.name}** 첨부됨")
            
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown("구글 AI 엔진이 분석 중입니다...")
            
            try:
                # 🛠️ 사진 유무에 따라 스캔된 맞춤형 모델 자동 적용 (404 원천 차단)
                active_model = VISION_MODEL if uploaded_files else TEXT_MODEL
                model = genai.GenerativeModel(active_model)
                
                base_instruction = f"당신은 LogyEDU 최준용 국어 원장 '국최'입니다. 학생 이름은 '{student_name}'이고 소속은 '{student_class}'입니다. 학생의 질문에 정확하고 올바른 정답과 명쾌한 해설을 제공하세요. 국어 외의 사적인 잡담은 단호히 거절하세요."
                
                if os.path.exists(class_ans_txt):
                    with open(class_ans_txt, mode='r', encoding='utf-8') as f:
                        today_ans = f.read()
                    if today_ans.strip():
                        base_instruction += f"\n\n[해당 반({student_class}) 과제 정답지]\n{today_ans}"
                        
                if os.path.exists(reference_file_path):
                    with open(reference_file_path, mode='r', encoding='utf-8') as f:
                        accumulated_doc = f.read()
                    if accumulated_doc.strip():
                        base_instruction += f"\n\n[학원 누적 해설지]\n{accumulated_doc}"
                
                contents = [f"{base_instruction}\n\n[학생 질문]\n{prompt}"]
                
                if uploaded_files:
                    for uf in uploaded_files:
                        if uf.type.startswith("image"):
                            contents.append({"mime_type": uf.type, "data": uf.getvalue()})
                        elif uf.type == "application/pdf":
                            doc = fitz.open(stream=uf.read(), filetype="pdf")
                            pdf_text = ""
                            for page in doc:
                                pdf_text += page.get_text()
                            doc.close()
                            contents.append(f"\n[첨부된 PDF 내용]\n{pdf_text}")
                
                response = model.generate_content(contents)
                ai_response = response.text
                
                message_placeholder.markdown(ai_response)
                st.session_state.messages.append({"role": "model", "content": ai_response})
                
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                file_count = f"{len(uploaded_files)}개" if uploaded_files else "0개"
                
                with open(log_file_path, mode='a', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow([now_str, student_class, student_name, prompt, file_count, ai_response[:50] + "..."])
                    
                alert_msg = f"💡 [LogyEDU 새 질문 접수]\n- 반: {student_class}\n- 학생: {student_name}\n- 질문: {prompt}\n- 첨부파일: {file_count}\n- 시간: {now_str}"
                send_telegram_alert(alert_msg)

            except Exception as e:
                message_placeholder.error(f"구글 통신 오류: {e}")
                
    st.divider()
    st.link_button("🚨 '찐' 국최 원장님께 직접 질문하기", "https://open.kakao.com/o/sERIEkKi")

# ==========================================
# 📝 메뉴 2: 과제 제출 및 정답 확인
# ==========================================
elif menu == "📝 과제 제출 및 정답 확인":
    st.subheader(f"📝 [{student_class}] 오늘의 과제 제출")
    st.info("💡 푼 과제를 사진이나 PDF 파일로 제출해야만 해당 반의 정답을 확인할 수 있습니다.")
    
    hw_files = st.file_uploader("📸 과제 사진 또는 📄 PDF 파일을 업로드하세요 (여러 개 가능)", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True)
    
    hw_session_key = f"hw_submitted_{safe_class}"
    if hw_session_key not in st.session_state:
        st.session_state[hw_session_key] = False

    if hw_files:
        if st.button("🚀 과제 최종 제출하기"):
            with st.spinner("원장님 서버로 전송 중입니다..."):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                file_names = []
                for hw in hw_files:
                    save_path = os.path.join(HW_FOLDER, f"[{safe_class}] {student_name}_{hw.name}")
                    with open(save_path, "wb") as f:
                        f.write(hw.getbuffer())
                    file_names.append(hw.name)
                
                with open(hw_log_path, mode='a', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow([now_str, student_class, student_name, ", ".join(file_names)])
                
                st.session_state[hw_session_key] = True
            
            st.balloons() 
            st.success("✅ 과제 제출이 완벽하게 완료되었습니다! 아래에서 정답을 확인하세요.")
            
            alert_msg = f"🚨 [LogyEDU 과제 제출]\n- 반: {student_class}\n- 학생: {student_name}\n- 파일 수: {len(hw_files)}개\n- 시간: {now_str}"
            send_telegram_alert(alert_msg)

    st.divider()
    
    if st.session_state[hw_session_key]:
        st.subheader(f"🔓 [열림] {student_class} 정답 및 해설")
        st.success("과제 제출이 확인되어 해당 반의 정답지 열람 권한이 부여되었습니다.")
        
        if os.path.exists(class_ans_file_info):
            with open(class_ans_file_info, "r", encoding="utf-8") as f:
                ans_filename = f.read().strip()
            if os.path.exists(ans_filename):
                if ans_filename.lower().endswith('.pdf'):
                    with open(ans_filename, "rb") as f:
                        st.download_button(f"📄 {student_class} 정답지 원본 다운로드 (PDF)", f, file_name=f"{student_class}_정답.pdf", mime="application/pdf")
                else:
                    st.image(ans_filename, caption=f"[{student_class}] 공식 정답지 원본", use_container_width=True)
        
        if os.path.exists(class_ans_txt):
            with open(class_ans_txt, "r", encoding="utf-8") as f:
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
        
        tab1, tab2, tab3, tab4 = st.tabs(["🔑 반별 정답지 등록", "📝 과제 현황", "📊 질문 내역", "📚 해설지 누적"])
        
        with tab1:
            st.markdown("#### 반별 과제 정답 파일 등록")
            target_class = st.selectbox("📌 정답지를 배포할 반을 선택하세요.", CLASS_LIST)
            safe_target_class = get_safe_name(target_class)
            target_ans_txt_path = os.path.join(ANS_FOLDER, f"ans_txt_{safe_target_class}.txt")
            target_ans_file_path = os.path.join(ANS_FOLDER, f"ans_file_{safe_target_class}.txt")

            ans_file = st.file_uploader(f"📸 [{target_class}] 정답지 파일 업로드", type=["png", "jpg", "jpeg", "pdf"])
            
            if "extracted_ans" not in st.session_state:
                st.session_state.extracted_ans = ""
                
            if ans_file:
                if st.button("✨ 최고 성능 AI로 정답 자동 스캔하기 (인식률 100%)"):
                    with st.spinner("구글 네이티브 엔진이 스캔 중입니다... (약 10초 소요)"):
                        try:
                            scan_model_name = VISION_MODEL if ans_file.type.startswith("image") else TEXT_MODEL
                            scan_model = genai.GenerativeModel(scan_model_name)
                            scan_content = ["이 파일에 적힌 모든 정답과 해설 텍스트를 정확하게 추출해서 보여줘. 챗봇이 이 내용을 보고 학생들에게 해설해 줄 거야."]
                            
                            if ans_file.type.startswith("image"):
                                scan_content.append({"mime_type": ans_file.type, "data": ans_file.getvalue()})
                            elif ans_file.type == "application/pdf":
                                doc = fitz.open(stream=ans_file.read(), filetype="pdf")
                                pdf_text = ""
                                for page in doc:
                                    pdf_text += page.get_text()
                                doc.close()
                                scan_content.append(f"\n[첨부된 PDF 내용]\n{pdf_text}")
                                
                            response = scan_model.generate_content(scan_content)
                            
                            st.session_state.extracted_ans = response.text
                            st.success("✅ 텍스트 스캔 완료! 아래 입력창에 자동 반영되었습니다.")
                        except Exception as e:
                            st.error(f"추출 중 오류가 발생했습니다: {e}")
            
            saved_answer = st.session_state.extracted_ans
            if not saved_answer and os.path.exists(target_ans_txt_path):
                with open(target_ans_txt_path, "r", encoding="utf-8") as f:
                    saved_answer = f.read()
            
            new_answer = st.text_area(f"📝 [{target_class}] 정답 텍스트 입력 및 수정", value=saved_answer, height=200)
            
            if st.button(f"🚀 [{target_class}] 정답지 최종 배포하기"):
                with open(target_ans_txt_path, "w", encoding="utf-8") as f:
                    f.write(new_answer)
                
                if ans_file:
                    ext = ans_file.name.split('.')[-1]
                    save_path = os.path.join(ANS_FOLDER, f"원본_{safe_target_class}.{ext}")
                    with open(save_path, "wb") as f:
                        f.write(ans_file.getbuffer())
                with open(target_ans_file_path, "w", encoding="utf-8") as f:
                    f.write(save_path)
                        
                st.success(f"✅ [{target_class}] 정답지 파일과 텍스트가 성공적으로 배포 준비되었습니다!")
                st.session_state.extracted_ans = ""

        with tab2:
            st.markdown("#### 📊 실시간 과제 제출 기록")
            if os.path.exists(hw_log_path):
                with open(hw_log_path, "r", encoding='utf-8-sig') as f:
                    st.download_button("📥 전체 제출 기록 다운로드 (엑셀)", data=f.read().encode('utf-8-sig'), file_name="과제제출기록.csv", mime="text/csv")
                with open(hw_log_path, "r", encoding='utf-8-sig') as f:
                    hw_data = list(csv.reader(f))
                    if len(hw_data) > 1:
                        st.dataframe(hw_data[1:])
            
            st.divider()
            st.markdown("#### 📂 학생 제출 과제 원본 파일 확인")
            if os.path.exists(HW_FOLDER):
                submitted_files = sorted(os.listdir(HW_FOLDER), reverse=True)
                if submitted_files:
                    for f_name in submitted_files:
                        file_path = os.path.join(HW_FOLDER, f_name)
                        with open(file_path, "rb") as f:
                            file_bytes = f.read()
                        col_a, col_b = st.columns([4, 1])
                        with col_a:
                            st.write(f"📄 {f_name}")
                        with col_b:
                            st.download_button("📥 열기", data=file_bytes, file_name=f_name, key=f_name)
            
            st.divider()
            if st.button("🚨 과제 제출 기록 전체 삭제"):
                with open(hw_log_path, mode='w', newline='', encoding='utf-8-sig') as f:
                    csv.writer(f).writerow(["제출 일시", "반 이름", "학생 이름", "제출 파일명"])
                st.success("✅ 삭제 완료.")

        with tab3:
            st.markdown("#### 학생들이 챗봇에 질문한 내역")
            if os.path.exists(log_file_path):
                with open(log_file_path, "r", encoding='utf-8-sig') as f:
                    st.download_button("📥 질문 기록 다운로드 (엑셀)", data=f.read().encode('utf-8-sig'), file_name="질문기록.csv", mime="text/csv")
                with open(log_file_path, "r", encoding='utf-8-sig') as f:
                    data = list(csv.reader(f))
                    if len(data) > 1:
                        st.dataframe(data[1:])
            
            st.divider()
            if st.button("🚨 학생 질문 기록 전체 삭제"):
                with open(log_file_path, mode='w', newline='', encoding='utf-8-sig') as f:
                    csv.writer(f).writerow(["질문 일시", "반 이름", "학생 이름", "질문 내용", "첨부파일 수", "AI 답변 요약"])
                st.success("✅ 삭제 완료.")

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
