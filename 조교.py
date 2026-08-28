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

if not firebase_admin._apps:
    try:
        key_dict = json.loads(st.secrets["firebase_key"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🚨 파이어베이스 연결 오류: {e}")

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

# 파일/폴더 자동 세팅
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

for folder in [HW_FOLDER, ANS_FOLDER, PUBLIC_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

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
        menu_options = ["🔒 원장님 전용 관리실", "💬 24시간 AI 튜터", "📝 과제 파일 제출", "💯 OMR 자동 채점", "💻 온라인 시험장", "📂 학원 자료실"]
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
    
    menu_options = ["💬 24시간 AI 튜터", "📝 과제 파일 제출", "💯 OMR 자동 채점", "💻 온라인 시험장", "📂 학원 자료실"]
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
                base_instruction = f"당신은 LogyEDU 최준용 국어 원장님의 지식과 관리 방식을 완벽하게 물려받은 'AI 국최'입니다. 학생 이름은 '{student_name}'이고 소속은 '{student_class}'입니다. 대답을 시작할 때 항상 '안녕하세요! AI 국최입니다.' 와 같이 자신의 정체성을 밝히세요. 학생의 질문에 조금의 오류도 없이 정확하고 올바른 정답과 명쾌한 해설을 제공하세요. 국어 외의 사적인 잡담은 거절하세요."
                
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
                    base_instruction += f"\n\n[해당 반 누적 과제 정답지]\n{fb_class_ans}"
                elif os.path.exists(class_ans_txt):
                    with open(class_ans_txt, mode='r', encoding='utf-8') as f:
                        today_ans = f.read()
                    if today_ans.strip(): base_instruction += f"\n\n[해당 반 누적 과제 정답지]\n{today_ans}"
                
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
                    
                send_telegram_alert(f"💡 [국어 질문]\n- 반: {student_class}\n- 학생: {student_name}\n- 질문: {prompt}")

            except Exception as e:
                message_placeholder.error(f"오류: {e}")

# ==========================================
# 📝 메뉴 2: 과제 제출
# ==========================================
elif menu == "📝 과제 파일 제출":
    st.subheader(f"📝 [{student_class}] 과제 파일 제출")
    st.info("💡 푼 과제를 제출해야 해당 반의 정답지 락(Lock)이 해제됩니다.")
    hw_files = st.file_uploader("📸 과제 사진/PDF 업로드", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True)
    hw_session_key = f"hw_submitted_{safe_class}"
    if hw_session_key not in st.session_state: st.session_state[hw_session_key] = False

    if hw_files and st.button("🚀 제출하기"):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file_names = []
        for hw in hw_files:
            save_path = os.path.join(HW_FOLDER, f"[{safe_class}] {student_name}_{hw.name}")
            with open(save_path, "wb") as f: f.write(hw.getbuffer())
            file_names.append(hw.name)
        with open(hw_log_path, mode='a', newline='', encoding='utf-8-sig') as f:
            csv.writer(f).writerow([now_str, student_class, student_name, ", ".join(file_names)])
        if db:
            db.collection("homework_logs").add({"제출일시": now_str, "반이름": student_class, "학생이름": student_name, "제출파일명": ", ".join(file_names)})
        st.session_state[hw_session_key] = True
        st.balloons(); st.success("✅ 제출 완료! 락이 해제되었습니다.")

    if st.session_state[hw_session_key] or is_admin:
        st.subheader("🔓 공식 해설지")
        if os.path.exists(class_ans_txt):
            with open(class_ans_txt, "r", encoding="utf-8") as f: st.markdown(f.read())
    else:
        st.warning("⚠️ 과제를 제출해야 정답이 보입니다.")

# ==========================================
# 💯 메뉴 3: OMR 자동 채점
# ==========================================
elif menu == "💯 OMR 자동 채점":
    st.subheader(f"💯 [{student_class}] OMR 자동 채점")
    all_omr_data = load_omr_answers() if os.path.exists(OMR_ANS_DB) else []
    class_omr_tasks = {d["과제명"]: d["정답데이터"] for d in all_omr_data if d["반 이름"] == student_class}
    omr_session_key = f"omr_{safe_class}"
    
    if class_omr_tasks:
        selected_task = st.selectbox("📌 채점할 과제를 선택하세요.", ["선택하세요"] + list(class_omr_tasks.keys()))
        if selected_task != "선택하세요":
            c_ans = class_omr_tasks[selected_task].split(",")
            t_q = len(c_ans)
            with st.form("omr_form"):
                s_ans = [st.text_input(f"{i+1}번") for i in range(t_q)]
                if st.form_submit_button("🚀 자동 채점하기"):
                    wrongs = [f"{i+1}번(내답:{s_ans[i]})" for i in range(t_q) if s_ans[i].strip().lower() != c_ans[i].strip().lower()]
                    score = int(((t_q - len(wrongs)) / t_q) * 100) if t_q else 0
                    st.session_state[f"score_{omr_session_key}"] = score
                    st.session_state[f"wrongs_{omr_session_key}"] = wrongs
                    st.success("채점 완료!")
            if f"score_{omr_session_key}" in st.session_state:
                st.info(f"**점수:** {st.session_state[f'score_{omr_session_key}']}점")
                st.error(f"**틀린 문항:** {', '.join(st.session_state[f'wrongs_{omr_session_key}'])}")
    else:
        st.warning("등록된 OMR 과제가 없습니다.")

# ==========================================
# 💻 메뉴 6: 온라인 시험장
# ==========================================
elif menu == "💻 온라인 시험장":
    st.subheader(f"💻 [{student_class}] 온라인 시험장")
    if db:
        docs = db.collection("online_exams").get()
        av_exams = [d.to_dict() for d in docs if d.to_dict().get("대상반") in ["전체", student_class]]
        if av_exams:
            s_ex = st.selectbox("📝 응시할 시험 선택", ["선택하세요"] + [ex["제목"] for ex in av_exams])
            if s_ex != "선택하세요":
                c_ex = next(e for e in av_exams if e["제목"] == s_ex)
                
                st.markdown("### 📜 문제지")
                st.markdown(c_ex["문제지"])
                
                q_cnt = c_ex.get("문항수", 5) 
                
                st.divider()
                st.markdown("### ✍️ 직관적인 OMR 답안 작성란")
                st.info("💡 각 번호에 맞는 정답(숫자) 또는 주관식 답안을 아래 칸에 바로 입력하세요.")
                
                with st.form("ol_form"):
                    student_answers = []
                    for i in range(0, q_cnt, 2):
                        cols = st.columns(2)
                        with cols[0]:
                            ans = st.text_input(f"✅ {i+1}번 문항", key=f"ol_ans_{i}")
                            student_answers.append(ans)
                        if i + 1 < q_cnt:
                            with cols[1]:
                                ans2 = st.text_input(f"✅ {i+2}번 문항", key=f"ol_ans_{i+1}")
                                student_answers.append(ans2)
                                
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.form_submit_button("🚀 답안 최종 제출 및 해설 확인", use_container_width=True):
                        ans_text = " | ".join([f"{idx+1}번: {a.strip() if a.strip() else '미입력'}" for idx, a in enumerate(student_answers)])
                        
                        db.collection("online_exam_submissions").add({
                            "제출일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "반이름": student_class, 
                            "학생이름": student_name, 
                            "시험제목": s_ex, 
                            "학생답안": ans_text
                        })
                        st.session_state[f"ol_done_{s_ex}"] = True
                        st.success("✅ 원장님께 답안이 성공적으로 제출되었습니다!")
                        
                if st.session_state.get(f"ol_done_{s_ex}") or is_admin:
                    st.divider()
                    st.markdown("### 💡 공식 해설지")
                    st.markdown(c_ex["해설지"])
        else:
            st.warning("현재 응시 가능한 시험이 없습니다.")

# ==========================================
# 📂 메뉴 4: 학원 자료실
# ==========================================
elif menu == "📂 학원 자료실":
    st.subheader("📂 공용 학원 자료실")
    if os.path.exists(PUBLIC_FOLDER) and os.listdir(PUBLIC_FOLDER):
        for f_name in sorted(os.listdir(PUBLIC_FOLDER)):
            with open(os.path.join(PUBLIC_FOLDER, f_name), "rb") as f:
                st.download_button(f"📥 {f_name} 다운로드", f.read(), file_name=f_name)
    else:
        st.info("등록된 자료가 없습니다.")

# ==========================================
# 🔒 메뉴 5: 원장님 전용 관리실
# ==========================================
elif menu == "🔒 원장님 전용 관리실":
    st.subheader("🔒 원장님 전용 관리실")
    
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs(["💯 OMR 세팅", "🔑 반별 해설지 등록", "📝 채점 현황", "📊 질문 내역", "📚 해설지 누적", "📂 공개 자료실", "👥 명단 관리", "🪄 AI 문제 출제기"])
    
    with tab1:
        st.markdown("#### 💯 반별 OMR 자동 채점 정답 세팅")
        t_cls = st.selectbox("📌 반 선택", CLASS_LIST, key="omr_c")
        t_nm = st.text_input("📝 과제 이름")
        o_ans = st.text_area("🔑 정답 입력 (쉼표 구분)")
        if st.button("🚀 세팅 및 배포") and t_nm and o_ans:
            a_list = [a.strip() for a in o_ans.split(",") if a.strip()]
            c_str = ",".join(a_list)
            data = [d for d in (load_omr_answers() if os.path.exists(OMR_ANS_DB) else []) if not (d["반 이름"] == t_cls and d["과제명"] == t_nm)]
            data.append({"반 이름": t_cls, "과제명": t_nm, "정답데이터": c_str})
            with open(OMR_ANS_DB, mode='w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=["반 이름", "과제명", "정답데이터"]); writer.writeheader(); writer.writerows(data)
            st.success("✅ 세팅 완료!")

    with tab2:
        st.markdown("#### 반별 과제 해설지 파일 등록")
        ans_cls = st.selectbox("📌 반 선택", CLASS_LIST, key="ans_c")
        new_ans = st.text_area("📝 텍스트 해설 누적", height=200)
        if st.button("🚀 최종 배포"):
            with open(os.path.join(ANS_FOLDER, f"ans_txt_{get_safe_name(ans_cls)}.txt"), "w", encoding="utf-8") as f: f.write(new_ans)
            if db: db.collection("ai_knowledge").document(f"class_{get_safe_name(ans_cls)}").set({"text": new_ans})
            st.success("✅ 배포 완료!")

    with tab3:
        st.markdown("#### 📝 오프라인 과제 및 OMR 채점 기록")
        if os.path.exists(score_log_path): st.download_button("📥 OMR 채점 엑셀 다운로드", open(score_log_path, "r", encoding='utf-8-sig').read().encode('utf-8-sig'), "OMR기록.csv")
        if os.path.exists(hw_log_path): st.download_button("📥 과제 제출 엑셀 다운로드", open(hw_log_path, "r", encoding='utf-8-sig').read().encode('utf-8-sig'), "과제기록.csv")

        st.divider()
        st.markdown("#### 💻 파이어베이스 실시간 [온라인 시험 제출 현황판]")
        if db:
            if st.button("🔄 최신 학생 제출 결과 불러오기"):
                try:
                    # 💡 한글 필드명 버그 해결: 직접 가져온 뒤 파이썬에서 정렬
                    subs_ref = db.collection("online_exam_submissions").get()
                    raw_list = [doc.to_dict() for doc in subs_ref]
                    sorted_list = sorted(raw_list, key=lambda x: x.get("제출일시", ""), reverse=True)[:50]
                    
                    sub_list = []
                    for data in sorted_list:
                        sub_list.append({
                            "제출일시": data.get("제출일시", ""),
                            "반": data.get("반이름", ""),
                            "이름": data.get("학생이름", ""),
                            "시험제목": data.get("시험제목", ""),
                            "답안": data.get("학생답안", "")
                        })
                        
                    if sub_list:
                        st.dataframe(sub_list)
                    else:
                        st.info("아직 학생들이 제출한 온라인 시험 답안이 없습니다.")
                except Exception as e:
                    st.error(f"결과를 불러오는 중 오류가 발생했습니다: {e}")
        else:
            st.warning("파이어베이스 연결이 필요합니다.")

    with tab4:
        st.markdown("#### 질문 내역")
        if os.path.exists(log_file_path): st.download_button("📥 질문 기록", open(log_file_path, "r", encoding='utf-8-sig').read().encode('utf-8-sig'), "질문기록.csv")

    with tab5:
        st.markdown("#### 챗봇 두뇌 강화 (해설지 업로드)")
        ref_fs = st.file_uploader("해설지 업로드", accept_multiple_files=True)
        if ref_fs and st.button("🚀 학습시키기"):
            for rf in ref_fs:
                txt = rf.getvalue().decode("utf-8") if rf.name.endswith(".txt") else genai.GenerativeModel(TARGET_MODEL).generate_content(["추출", {"mime_type": "application/pdf", "data": rf.getvalue()}]).text
                with open(reference_file_path, "a", encoding="utf-8") as f: f.write(f"\n{txt}")
                if db:
                    dr = db.collection("ai_knowledge").document("common_reference")
                    ex_t = dr.get().to_dict().get("text", "") if dr.get().exists else ""
                    dr.set({"text": ex_t + "\n" + txt})
            st.success("✅ 학습 완료!")

    with tab6:
        st.markdown("#### 공개 자료실 등록")
        p_fs = st.file_uploader("파일 업로드", accept_multiple_files=True)
        if p_fs and st.button("🚀 배포"):
            for pf in p_fs:
                with open(os.path.join(PUBLIC_FOLDER, pf.name), "wb") as f: f.write(pf.getbuffer())
            st.success("✅ 등록 완료")

    with tab7:
        st.markdown("#### 원생 명단 관리")
        r_c = st.selectbox("반", CLASS_LIST); r_n = st.text_input("이름")
        if st.button("➕ 추가") and r_n:
            with open(ROSTER_FILE, mode='a', newline='', encoding='utf-8-sig') as f: csv.writer(f).writerow([r_c, r_n])
            st.success("✅ 추가 완료")

    with tab8:
        st.markdown("#### 🪄 로지에듀 전용 AI 문제 출제기")
        st.info("💡 원장님의 까다로운 출제 원칙(크로스 함정, 인과관계 역전 등)이 프롬프트에 완벽히 세팅되어 있습니다.")
        
        q_mode = st.radio("📝 출제 모드 선택", ["✨ 새로운 지문 기반 신규 문제 창조", "🔄 기존 기출문제 기반 쌍둥이 변형 문제 출제"], horizontal=True)
        st.divider()

        col_t1, col_t2 = st.columns([2, 1])
        with col_t1: q_test_title = st.text_input("📝 시험 제목", placeholder="예: 미강고 2학년 중간고사 대비 쪽지시험 1회")
        with col_t2: q_target_class = st.selectbox("🎯 온라인 배포 대상", ["전체"] + CLASS_LIST)
            
        col_q1, col_q2 = st.columns(2)
        with col_q1:
            q_style = st.selectbox("🎯 출제 스타일", ["수능형", "내신형", "문해력형"])
            q_diff = st.selectbox("🔥 난이도", ["킬러 문항", "준킬러 문항", "상난이도", "중난이도", "하난이도"])
            q_count = st.number_input("🔢 출제할 문항 수", min_value=1, max_value=20, value=3)
        with col_q2:
            q_type = st.multiselect("📝 문제 유형 (복수 선택)", 
                                    ["5지 선다형", "복잡한 선택지 2지 선다형", "O/X 문제형", "단답형", "빈칸 채우기형", "내용 일치/불일치", "핵심어/주제 추론", "서술형/논술형", "<보기> 적용형"], 
                                    default=["5지 선다형", "내용 일치/불일치"])
        
        q_files = st.file_uploader("📂 기준 자료 파일 업로드 (PDF, 이미지 등)", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True)
        if "신규" in q_mode:
            q_text = st.text_area("📄 출제할 지문 텍스트 (파일만 올려도 무방합니다)", height=150)
        else:
            q_text = st.text_area("📄 변형할 원본 기출문제 텍스트 (파일만 올려도 무방합니다)", height=150)
        
        if "q_list" not in st.session_state: st.session_state.q_list = []
        if "q_contents_cache" not in st.session_state: st.session_state.q_contents_cache = []
            
        if st.button("🚀 로지에듀 수준의 완벽한 문제 최초 생성", use_container_width=True):
            if not q_text.strip() and not q_files:
                st.warning("⚠️ 출제/변형할 기준 자료(파일 또는 텍스트)를 넣어주세요.")
            elif not q_type:
                st.warning("⚠️ 문제 유형을 선택해 주세요.")
            else:
                with st.spinner("AI가 자료를 정밀 분석하여 매력적인 함정 선지를 설계 중입니다... (약 10~20초)"):
                    try:
                        q_model = genai.GenerativeModel(TARGET_MODEL)
                        q_prompt = f"""
                        당신은 최상위권 학생들을 지도하는 '로지에듀 국어학원'의 수석 출제 위원입니다. 
                        원장님이 옳지 않은 답과 엉성한 문제를 매우 싫어하므로, 단 하나의 논리적 오류나 복수 정답 논란이 없는 완벽한 문제를 출제하세요.
                        
                        [출제 기본 조건]
                        - 작업 모드: {q_mode}
                        - 대상 및 스타일: {q_style}
                        - 문제 유형: {', '.join(q_type)}
                        - 난이도: {q_diff}
                        - 문항 수: 총 {q_count}문제
                        
                        [⭐ 로지에듀 특별 출제 매뉴얼 (필수 반영)]
                        1. 선택지 길이: 1번부터 5번까지 선택지의 길이를 실전 모의고사처럼 적절하고 균형 있게 맞추세요.
                        2. 어휘 제한: 외부 어휘 개입을 최소화하고 자료에 있는 어휘를 최대한 활용하세요.
                        3. 함정 패턴 (중난이도 이상 필수 적용):
                           - 직관적으로 답이 1초 만에 보이는 1차원적인 문제는 절대 배제하세요.
                           - (대비) 서로 대비되는 정보의 공통점과 차이점을 교묘하게 묻는 문항을 포함하세요.
                           - (크로스 오답) A의 특징과 B의 특징을 교차(섞어서)하여 오답을 생성하세요.
                           - (숨은 공통점) 두 개 이상의 대상에 대해, 잘 안 보이는 공통점을 묻거나 공통점을 마치 차이점인 것처럼 속이는 선지를 만드세요.
                           - (문학 특화 왜곡) 문학 문제의 경우, 지문의 내용 자체(Fact)는 틀리게 바꾸고 뒷부분(효과, 감상)은 옳게 만들어서 그럴싸한 오답을 구성하세요.
                           - (인과/순서 역전) 순서, 과정, 원인과 결과의 논리적 선후 관계를 섞거나 뒤집어서 내는 문항을 반드시 포함하세요.
                           
                        [출력 형식 - 매우 중요]
                        반드시 아래의 특수 구분선을 사용하여 각 문제와 해설을 철저히 분리하세요.
                        ---문항---
                        1. 발문과 선지 내용...
                        ---해설---
                        정답: 
                        해설: 정답의 근거 및 위 매뉴얼의 어떤 '함정 패턴'을 사용해 오답을 만들었는지 원장님이 확인할 수 있도록 분석.
                        ---문항---
                        2. 발문과 선지 내용...
                        ---해설---
                        ...
                        
                        [입력 자료]
                        {q_text}
                        """
                        contents = [q_prompt]
                        if q_files:
                            for qf in q_files:
                                contents.append({"mime_type": qf.type if not qf.type.endswith("pdf") else "application/pdf", "data": qf.getvalue()})
                        
                        st.session_state.q_contents_cache = contents 
                        
                        q_response = q_model.generate_content(contents)
                        blocks = q_response.text.split("---문항---")
                        
                        parsed_list = []
                        for block in blocks:
                            if "---해설---" in block:
                                parts = block.split("---해설---")
                                q_str = parts[0].strip()
                                a_str = parts[1].strip()
                                if q_str and a_str:
                                    parsed_list.append({"q": q_str, "a": a_str})
                                    
                        st.session_state.q_list = parsed_list
                        st.success(f"✅ {len(parsed_list)}문제가 로지에듀 기준에 맞춰 성공적으로 출제되었습니다!")
                    except Exception as e:
                        st.error(f"🚨 출제 오류: {e}")
        
        if st.session_state.q_list:
            st.markdown("---")
            st.markdown("#### 🛠️ 문항 개별 확인 및 편집")
            
            for idx, item in enumerate(st.session_state.q_list):
                with st.expander(f"📌 {idx+1}번 문항 (클릭하여 텍스트 직접 수정 가능)", expanded=False):
                    new_q = st.text_area(f"{idx+1}번 문제지 영역", item["q"], key=f"edit_q_{idx}", height=150)
                    new_a = st.text_area(f"{idx+1}번 해설지 영역", item["a"], key=f"edit_a_{idx}", height=100)
                    
                    st.session_state.q_list[idx]["q"] = new_q
                    st.session_state.q_list[idx]["a"] = new_a
                    
                    if st.button("❌ 이 문항 삭제", key=f"del_{idx}"):
                        st.session_state.q_list.pop(idx)
                        st.rerun()
            
            if st.button("➕ 현재 자료 기준으로 완전히 새로운 문제 1개 추가 생성"):
                with st.spinner("새로운 문항을 1개 추가 생성 중입니다..."):
                    try:
                        add_model = genai.GenerativeModel(TARGET_MODEL)
                        add_prompt = "앞서 제시한 자료와 동일한 매뉴얼을 적용하여, 기존에 출제한 것과 겹치지 않는 새로운 함정 문제 딱 1개만 더 만들어줘. 출력 형식(---문항---, ---해설---)을 반드시 지켜."
                        add_contents = st.session_state.q_contents_cache + [add_prompt]
                        
                        add_response = add_model.generate_content(add_contents)
                        blocks = add_response.text.split("---문항---")
                        
                        for block in blocks:
                            if "---해설---" in block:
                                parts = block.split("---해설---")
                                q_str = parts[0].strip()
                                a_str = parts[1].strip()
                                if q_str and a_str:
                                    st.session_state.q_list.append({"q": q_str, "a": a_str})
                                    st.rerun()
                    except Exception as e:
                        st.error("추가 출제 실패")

            final_q_text = "\n\n".join([item["q"] for item in st.session_state.q_list])
            final_a_text = "\n\n".join([item["a"] for item in st.session_state.q_list])
            
            st.markdown("---")
            col_res1, col_res2 = st.columns(2)
            with col_res1:
                st.download_button("📥 완성된 문제지 다운로드", data=final_q_text, file_name=f"{q_test_title}_문제지.txt")
            with col_res2:
                st.download_button("📥 완성된 해설지 다운로드", data=final_a_text, file_name=f"{q_test_title}_해설지.txt")
                
            if st.button("🚀 원장님 최종 승인: 위 문항을 [온라인 시험장]으로 배포하기"):
                if not q_test_title:
                    st.error("시험 제목을 입력해 주세요.")
                elif not db:
                    st.error("파이어베이스 연결이 필요합니다.")
                else:
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    db.collection("online_exams").document(q_test_title).set({
                        "제목": q_test_title,
                        "대상반": q_target_class,
                        "문제지": final_q_text,
                        "해설지": final_a_text,
                        "문항수": len(st.session_state.q_list),
                        "출제일시": now_str
                    })
                    st.success(f"✅ '{q_test_title}' 시험이 [{q_target_class}] 반 온라인 시험장으로 배포되었습니다!")
                    st.balloons()
            
        st.markdown("---")
        st.markdown("#### 🗑️ 배포된 온라인 시험 관리 (조회 및 삭제)")
        if db:
            try:
                # 💡 한글 필드명 버그 해결: 직접 가져온 뒤 파이썬에서 정렬
                exams_ref = db.collection("online_exams").get()
                raw_exams = [doc.to_dict() for doc in exams_ref]
                exam_list = sorted(raw_exams, key=lambda x: x.get("출제일시", ""), reverse=True)
                
                if exam_list:
                    for idx, exam in enumerate(exam_list):
                        ex_title = exam.get("제목", "제목 없음")
                        ex_class = exam.get("대상반", "알 수 없음")
                        ex_date = exam.get("출제일시", "")
                        
                        col_ex1, col_ex2 = st.columns([4, 1])
                        col_ex1.write(f"📝 **{ex_title}** [{ex_class} 전용] ({ex_date})")
                        if col_ex2.button("❌ 시험 삭제", key=f"del_exam_db_{idx}"):
                            db.collection("online_exams").document(ex_title).delete()
                            st.rerun()
                else:
                    st.info("현재 파이어베이스에 배포된 시험이 없습니다.")
            except Exception as e:
                st.error(f"시험 목록을 불러오는 중 오류가 발생했습니다: {e}")
        else:
            st.warning("파이어베이스 연결이 필요합니다.")
