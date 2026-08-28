import streamlit as st
import os
import sys
import subprocess
import csv
import requests
import json
from datetime import datetime

# ==========================================
# 🚨 서버 필수 부품 강제 설치
# ==========================================
@st.cache_resource
def ensure_dependencies():
    try:
        import google.generativeai
        import firebase_admin
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "requests", "google-generativeai", "firebase-admin"])

ensure_dependencies()
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# ==========================================
# ⭐️ 구글 공식 최신 표준 모델
# ==========================================
TARGET_MODEL = "gemini-3.6-flash" 

# ==========================================
# 🔒 비밀 금고 안전장치 및 파이어베이스 연동
# ==========================================
if "MY_API_KEY" not in st.secrets:
    st.warning("🔑 아직 열쇠가 없습니다! 우측 하단 `< 앱 관리 (Manage app)` -> `Settings` -> `Secrets` 에 구글 API 키를 먼저 넣어주세요.")
    st.stop()

MY_API_KEY = st.secrets["MY_API_KEY"]
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

genai.configure(api_key=MY_API_KEY)

# 🔥 파이어베이스 영구 창고 연결
if not firebase_admin._apps:
    try:
        key_dict = json.loads(st.secrets["firebase_key"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🚨 파이어베이스 연결 오류: {e}")

# 데이터베이스 조종 리모컨
try:
    db = firestore.client()
except:
    db = None

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
score_log_path = "OMR_채점_기록.csv" 
ROSTER_FILE = "원생명단_DB.csv" 
OMR_ANS_DB = "OMR_정답_세팅.csv" 
HW_FOLDER = "hw_uploads"
ANS_FOLDER = "answers"
PUBLIC_FOLDER = "public_materials"

CLASS_LIST = [
    "중등부 문해력", "고1 미강고", "고1 미사고", "고1 하남고", "고1 풍산고",
    "고2 미강고 토요일", "고2 미강고 일요일", "고2 하남고", "고2 미사고", "고2 풍산고",
    "고3 / N수", "모의고사", "논술"
]

def get_safe_name(name):
    return name.replace("/", "_").replace(" ", "")

# 폴더 자동 생성
for folder in [HW_FOLDER, ANS_FOLDER, PUBLIC_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# 파일 자동 생성
for file_path, headers in [
    (log_file_path, ["질문 일시", "반 이름", "학생 이름", "질문 내용", "첨부파일 수", "AI 답변 요약"]),
    (hw_log_path, ["제출 일시", "반 이름", "학생 이름", "제출 파일명"]),
    (ROSTER_FILE, ["반 이름", "학생 이름"]),
    (score_log_path, ["채점 일시", "반 이름", "학생 이름", "시험(과제)명", "점수", "틀린 번호"]),
    (OMR_ANS_DB, ["반 이름", "과제명", "정답데이터"])
]:
    if not os.path.exists(file_path):
        with open(file_path, mode='w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

def get_roster():
    roster = []
    if os.path.exists(ROSTER_FILE):
        with open(ROSTER_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                roster.append((row["반 이름"], row["학생 이름"]))
    return roster

def load_omr_answers():
    with open(OMR_ANS_DB, mode='r', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

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
# 👤 학생 인증
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

is_admin = False
if student_class == "논술" and student_name == "최준용":
    admin_pw = st.text_input("🔑 관리자 비밀번호를 입력하세요.", type="password")
    if admin_pw == "2024":
        is_admin = True
        st.success("✅ 원장님, 환영합니다! 스텔스 관리자 모드가 활성화되었습니다.")
        menu_options = ["🔒 원장님 전용 관리실", "💬 24시간 AI 튜터", "📝 과제 파일 제출", "💯 OMR 자동 채점", "📂 학원 자료실"]
    elif admin_pw:
        st.error("❌ 비밀번호가 틀렸습니다.")
        st.stop()
    else:
        st.stop()

if not is_admin:
    current_roster = get_roster()
    if (student_class, student_name) not in current_roster:
        st.error("🚨 등록되지 않은 원생입니다. 반과 이름이 정확한지 확인하시거나 학원에 문의해 주세요.")
        st.stop()
    
    menu_options = ["💬 24시간 AI 튜터", "📝 과제 파일 제출", "💯 OMR 자동 채점", "📂 학원 자료실"]
    st.success(f"✅ [{student_class}] {student_name} 학생, 환영합니다!")

menu = st.radio("🧭 원하는 메뉴를 선택하세요.", menu_options, horizontal=True)
st.divider()

safe_class = get_safe_name(student_class)
class_ans_txt = os.path.join(ANS_FOLDER, f"ans_txt_{safe_class}.txt")
class_ans_file_info = os.path.join(ANS_FOLDER, f"ans_file_{safe_class}.txt")

# ==========================================
# 💬 메뉴 1: 24시간 AI 튜터
# ==========================================
if menu == "💬 24시간 AI 튜터":
    st.subheader(f"💬 무엇이든 물어보세요, {student_name} 학생!")
    st.markdown("모르는 문제나 지문은 타이핑하거나 **사진 또는 PDF 파일을 첨부**해서 올려주세요.")

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
            message_placeholder.markdown("🤖 **'AI 국최'**가 질문을 분석 중입니다...")
            
            try:
                model = genai.GenerativeModel(TARGET_MODEL)
                base_instruction = f"당신은 LogyEDU 최준용 국어 원장님의 지식과 관리 방식을 완벽하게 물려받은 'AI 국최'입니다. 학생 이름은 '{student_name}'이고 소속은 '{student_class}'입니다. 대답을 시작할 때 항상 '안녕하세요! AI 국최입니다.' 와 같이 자신의 정체성을 밝히세요. 학생의 질문에 조금의 오류도 없이 정확하고 올바른 정답과 명쾌한 해설을 제공하세요. 국어 외의 사적인 잡담은 단호히 거절하세요."
                
                # 🔥 파이어베이스 지식 우선 호출 로직
                fb_class_ans = ""
                fb_common_ans = ""
                if db:
                    try:
                        c_doc = db.collection("ai_knowledge").document(f"class_{safe_class}").get()
                        if c_doc.exists: fb_class_ans = c_doc.to_dict().get("text", "")
                        
                        r_doc = db.collection("ai_knowledge").document("common_reference").get()
                        if r_doc.exists: fb_common_ans = r_doc.to_dict().get("text", "")
                    except: pass
                
                if fb_class_ans:
                    base_instruction += f"\n\n[해당 반({student_class}) 누적 과제 정답지]\n{fb_class_ans}"
                elif os.path.exists(class_ans_txt):
                    with open(class_ans_txt, mode='r', encoding='utf-8') as f:
                        today_ans = f.read()
                    if today_ans.strip(): base_instruction += f"\n\n[해당 반({student_class}) 누적 과제 정답지]\n{today_ans}"
                
                if fb_common_ans:
                    base_instruction += f"\n\n[학원 누적 해설지]\n{fb_common_ans}"
                elif os.path.exists(reference_file_path):
                    with open(reference_file_path, mode='r', encoding='utf-8') as f:
                        accumulated_doc = f.read()
                    if accumulated_doc.strip(): base_instruction += f"\n\n[학원 누적 해설지]\n{accumulated_doc}"
                
                contents = [f"{base_instruction}\n\n[학생 질문]\n{prompt}"]
                if uploaded_files:
                    for uf in uploaded_files:
                        contents.append({"mime_type": uf.type if not uf.type.endswith("pdf") else "application/pdf", "data": uf.getvalue()})
                
                response = model.generate_content(contents)
                ai_response = response.text
                
                message_placeholder.markdown(ai_response)
                st.session_state.messages.append({"role": "model", "content": ai_response})
                
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                file_count = f"{len(uploaded_files)}개" if uploaded_files else "0개"
                
                with open(log_file_path, mode='a', newline='', encoding='utf-8-sig') as f:
                    csv.writer(f).writerow([now_str, student_class, student_name, prompt, file_count, ai_response[:50] + "..."])
                
                if db:
                    db.collection("chat_logs").add({
                        "질문일시": now_str, "반이름": student_class, "학생이름": student_name,
                        "질문내용": prompt, "첨부파일수": file_count, "AI답변요약": ai_response[:50] + "..."
                    })
                    
                send_telegram_alert(f"💡 [LogyEDU 국어 질문]\n- 반: {student_class}\n- 학생: {student_name}\n- 질문: {prompt}\n- 파일: {file_count}\n- 시간: {now_str}")

            except Exception as e:
                message_placeholder.error(f"오류: {e}")
                
    st.divider()
    st.link_button("🚨 '찐' 국최 원장님께 직접 질문하기", "https://open.kakao.com/o/sERIEkKi")

# ==========================================
# 📝 메뉴 2: 일반 과제 파일 제출
# ==========================================
elif menu == "📝 과제 파일 제출":
    st.subheader(f"📝 [{student_class}] 과제 파일 제출")
    st.info("💡 푼 과제를 사진이나 PDF 파일로 제출해야만 해당 반의 정답지 락(Lock)이 해제됩니다.")
    
    hw_files = st.file_uploader("📸 과제 사진 또는 📄 PDF 파일을 업로드하세요 (여러 개 가능)", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True)
    
    hw_session_key = f"hw_submitted_{safe_class}"
    if hw_session_key not in st.session_state:
        st.session_state[hw_session_key] = False

    if hw_files:
        if st.button("🚀 과제 최종 제출하기"):
            with st.spinner("서버로 전송 중입니다..."):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                file_names = []
                for hw in hw_files:
                    save_path = os.path.join(HW_FOLDER, f"[{safe_class}] {student_name}_{hw.name}")
                    with open(save_path, "wb") as f:
                        f.write(hw.getbuffer())
                    file_names.append(hw.name)
                
                with open(hw_log_path, mode='a', newline='', encoding='utf-8-sig') as f:
                    csv.writer(f).writerow([now_str, student_class, student_name, ", ".join(file_names)])
                
                if db:
                    db.collection("homework_logs").add({
                        "제출일시": now_str, "반이름": student_class, 
                        "학생이름": student_name, "제출파일명": ", ".join(file_names)
                    })
                
                st.session_state[hw_session_key] = True
            
            st.balloons() 
            st.success("✅ 과제 제출이 완료되었습니다! 아래에서 락이 해제된 정답을 확인하세요.")
            send_telegram_alert(f"🚨 [LogyEDU 과제 제출]\n- 반: {student_class}\n- 학생: {student_name}\n- 파일 수: {len(hw_files)}개")

    st.divider()
    
    if st.session_state[hw_session_key] or is_admin:
        st.subheader(f"🔓 [열림] {student_class} 공식 해설지")
        st.success("과제 제출이 확인되어 해당 반의 누적된 정답지 열람 권한이 부여되었습니다.")
        
        if os.path.exists(class_ans_file_info):
            with open(class_ans_file_info, "r", encoding="utf-8") as f:
                ans_filenames = f.read().splitlines()
            for idx, ans_filename in enumerate(ans_filenames):
                if os.path.exists(ans_filename):
                    if ans_filename.lower().endswith('.pdf'):
                        with open(ans_filename, "rb") as bf:
                            st.download_button(f"📄 {os.path.basename(ans_filename)} 다운로드", bf, file_name=os.path.basename(ans_filename), key=f"dl_{idx}")
                    else:
                        st.image(ans_filename, caption=f"[{student_class}] 공식 정답지 원본", use_container_width=True)
        
        if os.path.exists(class_ans_txt):
            with open(class_ans_txt, "r", encoding="utf-8") as f:
                st.markdown(f"**[원장님 공식 정답 텍스트]**\n\n{f.read()}")
    else:
        st.subheader("🔒 [잠김] 정답 및 해설")
        st.warning("⚠️ 과제 파일을 업로드하고 '제출하기' 버튼을 눌러야 락이 해제됩니다.")

# ==========================================
# 💯 메뉴 3: OMR 자동 채점
# ==========================================
elif menu == "💯 OMR 자동 채점":
    st.subheader(f"💯 [{student_class}] OMR 자동 채점")
    st.info("💡 모의고사 답안을 OMR 형식으로 입력하면 즉시 채점되어 결과가 나옵니다.")
    
    all_omr_data = []
    if os.path.exists(OMR_ANS_DB):
        all_omr_data = load_omr_answers()
    class_omr_tasks = {d["과제명"]: d["정답데이터"] for d in all_omr_data if d["반 이름"] == student_class}
    
    omr_session_key = f"omr_submitted_{safe_class}"
    
    if not class_omr_tasks:
        st.warning("현재 원장님께서 등록해 두신 OMR 자동 채점 과제가 없습니다.")
    else:
        selected_task = st.selectbox("📌 채점할 모의고사/과제를 선택하세요.", ["선택하세요"] + list(class_omr_tasks.keys()))
        
        if selected_task != "선택하세요":
            correct_answers = class_omr_tasks[selected_task].split(",")
            total_q = len(correct_answers)
            
            st.markdown(f"선택한 시험은 총 **{total_q}문항**입니다. 아래에 본인이 푼 정답을 입력하세요.")
            
            with st.form("omr_form"):
                student_answers = []
                
                for i in range(0, total_q, 5):
                    cols = st.columns(5)
                    for j in range(5):
                        q_idx = i + j
                        if q_idx < total_q:
                            with cols[j]:
                                ans = st.text_input(f"{q_idx+1}번", key=f"q_{q_idx}").strip()
                                student_answers.append(ans)
                        else:
                            with cols[j]:
                                st.write("")
                
                submit_btn = st.form_submit_button("🚀 답안 제출 및 자동 채점하기")
                
                if submit_btn:
                    with st.spinner("채점 및 저장 중입니다..."):
                        correct_count = 0
                        wrong_list = []
                        
                        for i in range(total_q):
                            c_ans = correct_answers[i].strip().replace(" ", "").lower()
                            s_ans = student_answers[i].strip().replace(" ", "").lower()
                            
                            if s_ans == "" or s_ans == "-":
                                wrong_list.append(f"{i+1}번(미입력)")
                            elif s_ans == c_ans:
                                correct_count += 1
                            else:
                                wrong_list.append(f"{i+1}번(내답:{s_ans})")
                        
                        final_score = int((correct_count / total_q) * 100) if total_q > 0 else 0
                        
                        st.session_state[omr_session_key] = True
                        st.session_state[f"score_{omr_session_key}"] = final_score
                        st.session_state[f"wrongs_{omr_session_key}"] = wrong_list
                        st.session_state[f"correct_cnt_{omr_session_key}"] = correct_count
                        
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        with open(score_log_path, mode='a', newline='', encoding='utf-8-sig') as f:
                            csv.writer(f).writerow([now_str, student_class, student_name, selected_task, f"{final_score}점", ",".join(student_answers), ", ".join([w.split("(")[0] for w in wrong_list])])
                        
                        if db:
                            db.collection("omr_logs").add({
                                "채점일시": now_str, "반이름": student_class, "학생이름": student_name,
                                "과제명": selected_task, "점수": final_score,
                                "학생답안": ",".join(student_answers), "틀린문항": ", ".join([w.split("(")[0] for w in wrong_list])
                            })
                        
                        st.balloons()
                        st.success("✅ 채점이 완료되었습니다! 아래에서 결과를 확인하세요.")
                        send_telegram_alert(f"💯 [LogyEDU 국어 채점]\n- 반: {student_class}\n- 학생: {student_name}\n- 시험: {selected_task}\n- 점수: {final_score}점\n- 오답: {len(wrong_list)}개")

    st.divider()
    
    if st.session_state.get(omr_session_key, False):
        st.subheader(f"🏆 {selected_task} 채점 결과")
        sc = st.session_state[f"score_{omr_session_key}"]
        cnt = st.session_state[f"correct_cnt_{omr_session_key}"]
        wl = st.session_state[f"wrongs_{omr_session_key}"]
        
        st.info(f"**원점수:** {sc}점 (총 {len(class_omr_tasks[selected_task].split(','))}문제 중 {cnt}문제 정답)")
        if wl:
            st.error(f"**❌ 틀린 문항:** {', '.join(wl)}")
            st.markdown("👉 **틀린 문제는 [💬 24시간 AI 튜터] 메뉴로 이동해서 질문하고 오답정리를 마무리하세요!**")
        else:
            st.success("🌟 완벽합니다! 모두 맞았습니다!")

# ==========================================
# 📂 메뉴 4: 학원 자료실
# ==========================================
elif menu == "📂 학원 자료실":
    st.subheader("📂 공용 학원 자료실")
    st.markdown("원장님께서 배포하신 해설지와 보충 자료를 언제든 자유롭게 다운로드할 수 있습니다.")
    st.divider()
    
    if os.path.exists(PUBLIC_FOLDER) and os.listdir(PUBLIC_FOLDER):
        for f_name in sorted(os.listdir(PUBLIC_FOLDER)):
            with open(os.path.join(PUBLIC_FOLDER, f_name), "rb") as f:
                col1, col2 = st.columns([4, 1])
                col1.write(f"📄 **{f_name}**")
                col2.download_button("📥 다운로드", data=f.read(), file_name=f_name, key=f"pub_{f_name}")
    else:
        st.info("현재 등록된 공개 자료가 없습니다.")

# ==========================================
# 🔒 메뉴 5: 원장님 전용 관리실
# ==========================================
elif menu == "🔒 원장님 전용 관리실":
    st.subheader("🔒 원장님 전용 관리실")
    
    # 💡 탭 8(AI 문제 출제기)이 추가되었습니다.
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs(["💯 OMR 세팅", "🔑 반별 해설지 등록", "📝 채점 현황", "📊 질문 내역", "📚 해설지 누적", "📂 공개 자료실", "👥 명단 관리", "🪄 AI 문제 출제기"])
    
    with tab1:
        st.markdown("#### 💯 반별 OMR 자동 채점 정답 세팅")
        target_class_omr = st.selectbox("📌 정답을 세팅할 반을 선택하세요.", CLASS_LIST, key="omr_class_sel")
        test_name = st.text_input("📝 과제 또는 모의고사 이름 (예: 고1 3월 학평)")
        
        st.markdown("##### 🤖 AI 자동 정답 추출 (수작업 입력 방지)")
        st.info("정답지(PDF 또는 사진)를 올리면 AI가 알아서 '1,4,3,2,5' 형태로 정답만 쏙쏙 뽑아줍니다!")
        omr_extract_file = st.file_uploader("정답지 파일 업로드", type=["png", "jpg", "jpeg", "pdf"], key="omr_extract_uploader")
        
        if "extracted_omr_ans" not in st.session_state:
            st.session_state.extracted_omr_ans = ""
            
        if omr_extract_file and st.button("✨ AI로 정답 자동 추출하기"):
            with st.spinner("AI가 정답을 판독 중입니다... (약 5초 소요)"):
                try:
                    extract_model = genai.GenerativeModel(TARGET_MODEL)
                    prompt = "이 파일은 국어 시험 정답지입니다. 1번부터 마지막 번호까지의 정답만 순서대로 추출해서, 문항 번호나 다른 설명은 싹 다 빼고 오직 정답만 쉼표(,)로 연결해서 한 줄로 출력해 줘. 예시: 1,3,5,2,4,4,1,2,시적화자"
                    contents = [prompt, {"mime_type": omr_extract_file.type if not omr_extract_file.type.endswith("pdf") else "application/pdf", "data": omr_extract_file.getvalue()}]
                    res = extract_model.generate_content(contents)
                    st.session_state.extracted_omr_ans = res.text.strip().replace("\n", "")
                    st.success("✅ 정답 추출 성공! 아래 입력란에 자동 반영되었습니다.")
                except Exception as e:
                    st.error(f"추출 실패: {e}")

        all_omr_data = []
        current_ans_str = ""
        if os.path.exists(OMR_ANS_DB):
            all_omr_data = load_omr_answers()
            for d in all_omr_data:
                if d["반 이름"] == target_class_omr and d["과제명"] == test_name:
                    current_ans_str = d["정답데이터"]
                    break
        
        if st.session_state.extracted_omr_ans:
            current_ans_str = st.session_state.extracted_omr_ans

        st.caption("※ 아래 칸에 정답을 직접 쉼표(,)로 치셔도 되고, 위에서 AI가 추출한 정답을 한 번 확인 후 수정하셔도 됩니다.")
        omr_input = st.text_area("🔑 최종 정답 입력란", value=current_ans_str, height=150)
        
        if st.button("🚀 OMR 정답 세팅 및 학생 배포"):
            if test_name and omr_input:
                ans_list = [ans.strip() for ans in omr_input.split(",") if ans.strip()]
                clean_ans_str = ",".join(ans_list)
                
                filtered_data = [d for d in all_omr_data if not (d["반 이름"] == target_class_omr and d["과제명"] == test_name)]
                filtered_data.append({"반 이름": target_class_omr, "과제명": test_name, "정답데이터": clean_ans_str})
                
                with open(OMR_ANS_DB, mode='w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=["반 이름", "과제명", "정답데이터"])
                    writer.writeheader()
                    writer.writerows(filtered_data)
                    
                if db:
                    db.collection("omr_settings").document(f"{target_class_omr}_{test_name}").set({
                        "반이름": target_class_omr,
                        "과제명": test_name,
                        "정답데이터": clean_ans_str
                    })
                    
                st.session_state.extracted_omr_ans = "" 
                st.success(f"✅ [{target_class_omr}] '{test_name}' (총 {len(ans_list)}문항) OMR 세팅 완료!")
            else:
                st.error("과제 이름과 정답을 모두 입력해 주세요.")
                
        st.divider()
        st.markdown("#### 🗑️ 등록된 자동 채점 목록 관리")
        current_omr_list = load_omr_answers() if os.path.exists(OMR_ANS_DB) else []
        if current_omr_list:
            for idx, row in enumerate(current_omr_list):
                col_a, col_b = st.columns([4, 1])
                col_a.write(f"[{row['반 이름']}] **{row['과제명']}** (문항 수: {len(row['정답데이터'].split(','))}개)")
                if col_b.button("❌ 삭제", key=f"del_omr_{idx}"):
                    current_omr_list.remove(row)
                    with open(OMR_ANS_DB, "w", newline='', encoding="utf-8-sig") as f:
                        writer = csv.DictWriter(f, fieldnames=["반 이름", "과제명", "정답데이터"])
                        writer.writeheader()
                        writer.writerows(current_omr_list)
                    if db:
                        db.collection("omr_settings").document(f"{row['반 이름']}_{row['과제명']}").delete()
                    st.rerun()
        else:
            st.write("등록된 자동 채점 과제가 없습니다.")

    with tab2:
        st.markdown("#### 반별 과제 해설지 파일 등록 (누적)")
        target_class = st.selectbox("📌 해설지를 배포할 반을 선택하세요.", CLASS_LIST, key="ans_class_sel")
        safe_target_class = get_safe_name(target_class)
        target_ans_txt_path = os.path.join(ANS_FOLDER, f"ans_txt_{safe_target_class}.txt")
        target_ans_file_path = os.path.join(ANS_FOLDER, f"ans_file_{safe_target_class}.txt")

        col_a, col_b = st.columns([3, 1])
        with col_a:
            ans_files = st.file_uploader(f"📸 [{target_class}] 해설지 업로드", type=["png", "jpg", "jpeg", "pdf"], accept_multiple_files=True)
        with col_b:
            st.write("")
            st.write("")
            if st.button("🗑️ 이 반 해설지 전체 초기화"):
                if os.path.exists(target_ans_txt_path): os.remove(target_ans_txt_path)
                if os.path.exists(target_ans_file_path): os.remove(target_ans_file_path)
                
                st.session_state.extracted_ans = ""
                st.success("✅ 로컬 파일 초기화 완료! (파이어베이스 영구 지식은 안전하게 보존됩니다.)")
                st.rerun()
        
        if "extracted_ans" not in st.session_state: st.session_state.extracted_ans = ""
            
        if ans_files and st.button("✨ 자동 스캔하기"):
            with st.spinner("스캔 중..."):
                scan_model = genai.GenerativeModel(TARGET_MODEL)
                for ans_file in ans_files:
                    try:
                        res = scan_model.generate_content(["이 파일에 적힌 모든 정답과 해설 텍스트를 정확하게 추출해서 보여줘.", {"mime_type": ans_file.type if not ans_file.type.endswith("pdf") else "application/pdf", "data": ans_file.getvalue()}])
                        st.session_state.extracted_ans += f"\n\n--- [{ans_file.name}] ---\n" + res.text
                    except Exception as e:
                        st.error(f"추출 중 오류: {e}")
                st.success("✅ 스캔 완료!")
        
        saved_answer = open(target_ans_txt_path, "r", encoding="utf-8").read() if os.path.exists(target_ans_txt_path) else ""
        new_answer = st.text_area("📝 텍스트 해설 누적 확인/수정", value=saved_answer + ("\n" + st.session_state.extracted_ans if st.session_state.extracted_ans else ""), height=200)
        
        if st.button(f"🚀 [{target_class}] 해설지 최종 배포(누적)하기"):
            with open(target_ans_txt_path, "w", encoding="utf-8") as f: f.write(new_answer)
            paths = open(target_ans_file_path, "r", encoding="utf-8").read().splitlines() if os.path.exists(target_ans_file_path) else []
            if ans_files:
                for af in ans_files:
                    p = os.path.join(ANS_FOLDER, f"원본_{safe_target_class}_{af.name}")
                    with open(p, "wb") as f: f.write(af.getbuffer())
                    if p not in paths: paths.append(p)
            with open(target_ans_file_path, "w", encoding="utf-8") as f: f.write("\n".join(paths))
            
            if db:
                db.collection("ai_knowledge").document(f"class_{safe_target_class}").set({
                    "text": new_answer,
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                
            st.success("✅ 배포 및 파이어베이스 AI 두뇌 연동 완료!")
            st.session_state.extracted_ans = ""

    with tab3:
        st.markdown("#### 💯 학생 OMR 채점 성적표")
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            if os.path.exists(score_log_path):
                st.download_button("📥 OMR 채점 기록 다운로드 (엑셀)", open(score_log_path, "r", encoding='utf-8-sig').read().encode('utf-8-sig'), "OMR채점기록.csv", "text/csv")
        with col_dl2:
            if os.path.exists(hw_log_path):
                st.download_button("📥 일반 과제 제출 기록 (엑셀)", open(hw_log_path, "r", encoding='utf-8-sig').read().encode('utf-8-sig'), "과제제출기록.csv", "text/csv")
        
        if os.path.exists(score_log_path):
            with open(score_log_path, "r", encoding='utf-8-sig') as f:
                omr_log_data = list(csv.reader(f))
                if len(omr_log_data) > 1:
                    st.dataframe(omr_log_data[1:])
        else:
            st.info("아직 채점 기록이 없습니다.")
            
        st.divider()
        st.markdown("#### 📂 학생 제출 과제 원본 파일 확인")
        if os.path.exists(HW_FOLDER) and os.listdir(HW_FOLDER):
            for f_name in sorted(os.listdir(HW_FOLDER), reverse=True):
                col_a, col_b = st.columns([4, 1])
                col_a.write(f"📄 {f_name}")
                col_b.download_button("📥 열기", open(os.path.join(HW_FOLDER, f_name), "rb").read(), f_name, key=f"hw_{f_name}")
        
        st.divider()
        if st.button("🚨 제출/채점 기록 및 원본 파일 전체 삭제"):
            with open(hw_log_path, mode='w', newline='', encoding='utf-8-sig') as f:
                csv.writer(f).writerow(["제출 일시", "반 이름", "학생 이름", "제출 파일명"])
            with open(score_log_path, mode='w', newline='', encoding='utf-8-sig') as f:
                csv.writer(f).writerow(["채점 일시", "반 이름", "학생 이름", "과제명", "원점수", "학생답안", "틀린문항"])
            if os.path.exists(HW_FOLDER):
                for f_name in os.listdir(HW_FOLDER):
                    os.remove(os.path.join(HW_FOLDER, f_name))
            st.success("✅ 삭제 완료.")

    with tab4:
        st.markdown("#### 학생들이 챗봇에 질문한 내역")
        if os.path.exists(log_file_path):
            st.download_button("📥 질문 기록 다운로드", open(log_file_path, "r", encoding='utf-8-sig').read().encode('utf-8-sig'), "질문기록.csv", "text/csv")
            with open(log_file_path, "r", encoding='utf-8-sig') as f:
                data = list(csv.reader(f))
                if len(data) > 1:
                    st.dataframe(data[1:])
        
        st.divider()
        if st.button("🚨 학생 질문 기록 전체 삭제"):
            with open(log_file_path, mode='w', newline='', encoding='utf-8-sig') as f:
                csv.writer(f).writerow(["질문 일시", "반 이름", "학생 이름", "질문 내용", "첨부파일 수", "AI 답변 요약"])
            st.success("✅ 삭제 완료.")

    with tab5:
        st.markdown("#### 챗봇 두뇌 강화 (해설지 업로드)")
        ref_files = st.file_uploader("새로운 해설지 누적", type=["pdf", "txt"], accept_multiple_files=True)
        
        if ref_files and st.button("🚀 학습시키기"):
            # 💡 AI가 문서를 읽는 동안 로딩 표시 추가
            with st.spinner("AI가 문서를 읽고 파이어베이스에 저장 중입니다... (PDF는 약 5~10초 소요)"):
                for rf in ref_files:
                    try:
                        text = rf.getvalue().decode("utf-8") if rf.name.endswith(".txt") else genai.GenerativeModel(TARGET_MODEL).generate_content(["텍스트 추출", {"mime_type": "application/pdf", "data": rf.getvalue()}]).text
                        with open(reference_file_path, "a", encoding="utf-8") as f: f.write(f"\n{text}")
                        
                        if db:
                            doc_ref = db.collection("ai_knowledge").document("common_reference")
                            doc = doc_ref.get()
                            existing_text = doc.to_dict().get("text", "") if doc.exists else ""
                            doc_ref.set({
                                "text": existing_text + "\n" + text,
                                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                    except Exception as e:
                        st.error(f"🚨 오류 발생: {e}")
                
                st.success("✅ 파이어베이스 AI 두뇌에 학습이 완벽하게 완료되었습니다!")
                st.rerun()

        st.markdown("---")
        # 💡 파이어베이스에 저장된 지식을 눈으로 확인하는 창
        current_common_text = "아직 파이어베이스에 등록된 공통 지식이 없습니다."
        if db:
            try:
                doc = db.collection("ai_knowledge").document("common_reference").get()
                if doc.exists:
                    current_common_text = doc.to_dict().get("text", "")
            except: pass
            
        st.text_area("🧠 현재 파이어베이스에 누적된 공통 지식 확인", value=current_common_text, height=200, disabled=True)
            
        if os.path.exists(reference_file_path) or (db and current_common_text != "아직 파이어베이스에 등록된 공통 지식이 없습니다."):
            if st.button("🗑️ 기억 초기화"):
                if os.path.exists(reference_file_path):
                    os.remove(reference_file_path)
                if db:
                    db.collection("ai_knowledge").document("common_reference").delete()
                st.success("✅ 파이어베이스와 서버의 공통 지식이 모두 초기화되었습니다.")
                st.rerun()

    with tab6:
        st.markdown("#### 📂 공용 국어 자료 올리기")
        pub_files = st.file_uploader("공개할 파일 업로드", accept_multiple_files=True, key="pub_up")
        if pub_files and st.button("🚀 배포하기"):
            for pf in pub_files:
                with open(os.path.join(PUBLIC_FOLDER, pf.name), "wb") as f: f.write(pf.getbuffer())
            st.success("✅ 등록 완료!")
            st.rerun()

        st.divider()
        if os.path.exists(PUBLIC_FOLDER) and os.listdir(PUBLIC_FOLDER):
            for f_name in sorted(os.listdir(PUBLIC_FOLDER)):
                col_a, col_b = st.columns([4, 1])
                col_a.write(f"📄 {f_name}")
                if col_b.button("❌ 삭제", key=f"del_pub_{f_name}"):
                    os.remove(os.path.join(PUBLIC_FOLDER, f_name))
                    st.rerun()

    with tab7:
        st.markdown("#### 👥 반별 원생 명단 관리")
        c1, c2 = st.columns(2)
        with c1: new_roster_class = st.selectbox("반 선택", CLASS_LIST, key="roster_cls")
        with c2: new_roster_name = st.text_input("학생 이름", key="roster_nm")
            
        if st.button("➕ 명단에 추가하기") and new_roster_name:
            with open(ROSTER_FILE, mode='a', newline='', encoding='utf-8-sig') as f:
                csv.writer(f).writerow([new_roster_class, new_roster_name])
            st.success(f"✅ [{new_roster_class}] {new_roster_name} 학생 등록!")
            st.rerun()
            
        st.divider()
        current_roster = get_roster()
        if current_roster:
            for r_class, r_name in current_roster:
                col_a, col_b = st.columns([4, 1])
                col_a.write(f"[{r_class}] **{r_name}**")
                if col_b.button("❌ 삭제", key=f"del_{r_class}_{r_name}"):
                    current_roster.remove((r_class, r_name))
                    with open(ROSTER_FILE, mode='w', newline='', encoding='utf-8-sig') as f:
                        writer = csv.writer(f)
                        writer.writerow(["반 이름", "학생 이름"])
                        for rc, rn in current_roster: writer.writerow([rc, rn])
                    st.rerun()

    # 💡 탭 8(AI 문제 출제기) 추가!
    with tab8:
        st.markdown("#### 🪄 로지에듀 전용 AI 문제 출제기")
        st.info("💡 교과서나 모의고사 지문을 넣으면, 단 한 치의 오류도 없는 완벽한 국어 문제를 즉시 생성합니다.")
        
        col_q1, col_q2 = st.columns(2)
        with col_q1:
            q_style = st.selectbox("🎯 출제 스타일", ["수능/모의고사형", "하남고 내신형", "미강고 내신형", "미사고 내신형", "풍산고 내신형", "중등부 문해력"])
            q_count = st.number_input("🔢 출제할 문항 수", min_value=1, max_value=10, value=3)
        with col_q2:
            q_type = st.multiselect("📝 문제 유형 (복수 선택 가능)", ["내용 일치/불일치", "핵심어/주제 추론", "문맥상 의미 파악", "표현상의 특징", "서술형/논술형", "<보기> 적용형"], default=["내용 일치/불일치", "핵심어/주제 추론"])
        
        q_text = st.text_area("📄 출제할 지문을 입력(복사+붙여넣기)하세요.", height=200)
        
        if st.button("🚀 로지에듀 수준의 완벽한 문제 생성하기", use_container_width=True):
            if not q_text.strip():
                st.warning("⚠️ 출제할 지문을 먼저 입력해 주세요.")
            elif not q_type:
                st.warning("⚠️ 문제 유형을 최소 1개 이상 선택해 주세요.")
            else:
                with st.spinner("AI가 지문을 정밀 분석하여 함정 선지와 함께 문제를 출제 중입니다... (약 10~20초)"):
                    try:
                        q_model = genai.GenerativeModel(TARGET_MODEL)
                        q_prompt = f"""
                        당신은 최상위권 학생들을 지도하는 '로지에듀 국어학원'의 수석 출제 위원입니다. 
                        주어진 지문을 바탕으로 단 하나의 논리적 오류나 복수 정답 논란이 없는 완벽하고 정확한 국어 문제를 출제해야 합니다.
                        오답 선지는 매력적인 함정을 포함하되, 지문에 근거하여 명백히 틀린 이유가 설명되어야 합니다.
                        
                        [출제 조건]
                        - 대상 및 스타일: {q_style}
                        - 문제 유형: {', '.join(q_type)}
                        - 문항 수: 총 {q_count}문제
                        
                        [요청 사항]
                        1. 각 문제에는 '문항 번호', '발문(질문)', '선지(1~5번)'를 명확히 작성하세요. (서술형인 경우 선지 제외)
                        2. 모든 문제가 끝난 후, 맨 아래에 [정답 및 명쾌한 해설] 파트를 따로 만들어서 정답의 근거와 오답의 이유를 하나하나 정확하게 설명하세요.
                        3. 국어 문법과 맞춤법을 완벽하게 준수하세요.
                        
                        [지문]
                        {q_text}
                        """
                        
                        q_response = q_model.generate_content(q_prompt)
                        st.session_state.generated_questions = q_response.text
                        st.success("✅ 출제가 완료되었습니다! 내용을 확인하시고 복사하여 한글이나 워드에 붙여넣어 사용하세요.")
                    except Exception as e:
                        st.error(f"🚨 문제 생성 중 오류가 발생했습니다: {e}")
        
        if "generated_questions" in st.session_state:
            st.markdown("---")
            st.markdown("#### 📜 생성된 문제 및 해설")
            st.text_area("복사해서 사용하세요 (Ctrl+A, Ctrl+C)", value=st.session_state.generated_questions, height=400)
