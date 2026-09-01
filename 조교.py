import streamlit as st
import streamlit.components.v1 as components 
import os
import sys
import csv
import requests
import json
import re
import time
from datetime import datetime, timedelta
import io
from xml.sax.saxutils import escape  

import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# ==========================================
# 📄 PDF 조판 엔진 및 PDF 내장 아시아 폰트(CID) 세팅 (🔥 기호 증발 원천 차단)
# ==========================================
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, KeepTogether, NextPageTemplate, PageBreak
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont 
from reportlab.lib import colors
from reportlab.lib.units import cm

@st.cache_resource
def load_fonts_v5():
    pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))
    pdfmetrics.registerFont(UnicodeCIDFont('HYGothic-Medium'))    
    pdfmetrics.registerFontFamily('BatangFont', normal='HYSMyeongJo-Medium', bold='HYGothic-Medium')
    return 'BatangFont'

# 💡 404 에러 해결: 구글이 100% 인식하는 'gemini-pro' 모델로 고정
TARGET_MODEL = "gemini-pro" 

# ==========================================
# 🔒 비밀 금고 안전장치 및 파이어베이스 연동 (코드 내 하드코딩 금지)
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

def clean_ai_text(text):
    text = text.replace("**", "") 
    text = text.replace("[1]", "①").replace("[2]", "②").replace("[3]", "③").replace("[4]", "④").replace("[5]", "⑤")
    text = re.sub(r'^1\)\s*', '① ', text, flags=re.MULTILINE)
    text = re.sub(r'^2\)\s*', '② ', text, flags=re.MULTILINE)
    text = re.sub(r'^3\)\s*', '③ ', text, flags=re.MULTILINE)
    text = re.sub(r'^4\)\s*', '④ ', text, flags=re.MULTILINE)
    text = re.sub(r'^5\)\s*', '⑤ ', text, flags=re.MULTILINE)
    return text

def safe_text(text):
    return escape(text)

log_file_path = "학생질문_모니터링_기록.csv"
reference_file_path = "공용해설지_누적본.txt" 
hw_log_path = "과제제출_기록.csv"
score_log_path = "OMR_채점_기록.csv" 
ROSTER_FILE = "원생명단_DB.csv" 
OMR_ANS_DB = "OMR_정답_세팅.csv" 
HW_FOLDER = "hw_uploads"
ANS_FOLDER = "answers"
PUBLIC_FOLDER = "public_materials"

CLASS_LIST = ["중등부 문해력", "고1 미강고", "고1 미사고", "고1 하남고", "고1 풍산고", "고2 미강고 토요일", "고2 미강고 일요일", "고2 하남고", "고2 미사고", "고2 풍산고", "고3 / N수", "모의고사", "논술"]

def get_safe_name(name):
    return name.replace("/", "_").replace(" ", "")

for folder in [HW_FOLDER, ANS_FOLDER, PUBLIC_FOLDER]:
    if not os.path.exists(folder): os.makedirs(folder)

for file_path, headers in [
    (log_file_path, ["질문 일시", "반 이름", "학생 이름", "질문 내용", "첨부파일 수", "AI 답변 요약"]),
    (hw_log_path, ["제출 일시", "반 이름", "학생 이름", "제출 파일명"]),
    (ROSTER_FILE, ["반 이름", "학생 이름"]),
    (score_log_path, ["채점 일시", "반 이름", "학생 이름", "시험(과제)명", "점수", "틀린 번호"]),
    (OMR_ANS_DB, ["반 이름", "과제명", "정답데이터"])
]:
    if not os.path.exists(file_path):
        with open(file_path, mode='w', newline='', encoding='utf-8-sig') as f:
            csv.writer(f).writerow(headers)

def get_roster():
    roster = []
    if db:
        try:
            docs = db.collection("students").get()
            for doc in docs:
                data = doc.to_dict()
                roster.append((data.get("class", ""), data.get("name", "")))
        except: pass
    if not roster and os.path.exists(ROSTER_FILE):
        with open(ROSTER_FILE, mode='r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                if (row["반 이름"], row["학생 이름"]) not in roster:
                    roster.append((row["반 이름"], row["학생 이름"]))
    return roster

def load_omr_answers():
    with open(OMR_ANS_DB, mode='r', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

st.set_page_config(page_title="24시 국최", page_icon="🦉", layout="centered")

st.markdown("<h1 style='text-align: center;'>🦉 LogyEDU 24시 국최</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: gray;'>최준용 원장님의 24시간 밀착 관리형 국어 AI 튜터</p>", unsafe_allow_html=True)

st.divider()

col1, col2 = st.columns([1, 2])
with col1: st.markdown("### 👤 학생 인증")
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
        menu_options = ["🔒 원장님 전용 관리실", "💬 24시간 AI 튜터", "📝 과제 파일 제출", "💯 OMR 자동 채점", "💻 온라인 시험장", "⏳ 실시간 모의고사", "✍️ AI 요약 첨삭", "📝 AI 국최 논술 첨삭", "📂 학원 자료실"]
    elif admin_pw:
        st.error("❌ 비밀번호가 틀렸습니다.")
        st.stop()
    else: st.stop()

if not is_admin:
    current_roster = get_roster()
    if (student_class, student_name) not in current_roster:
        st.error("🚨 등록되지 않은 원생입니다. 반과 이름이 정확한지 확인하시거나 학원에 문의해 주세요.")
        st.stop()
    menu_options = ["💬 24시간 AI 튜터", "📝 과제 파일 제출", "💯 OMR 자동 채점", "💻 온라인 시험장", "⏳ 실시간 모의고사", "✍️ AI 요약 첨삭", "📂 학원 자료실"]
    if student_class == "논술": menu_options.insert(6, "📝 AI 국최 논술 첨삭")
    st.success(f"✅ [{student_class}] {student_name} 학생, 환영합니다!")

menu = st.radio("🧭 원하는 메뉴를 선택하세요.", menu_options, horizontal=True)
st.divider()

safe_class = get_safe_name(student_class)
class_ans_txt = os.path.join(ANS_FOLDER, f"ans_txt_{safe_class}.txt")

if menu == "💬 24시간 AI 튜터":
    st.subheader(f"💬 무엇이든 물어보세요, {student_name} 학생!")
    st.markdown("모르는 문제나 지문은 타이핑하거나 **사진 또는 PDF 파일을 첨부**해서 올려주세요.")
    if "messages" not in st.session_state: st.session_state.messages = []
    for msg in st.session_state.messages:
        if msg["role"] != "system":
            with st.chat_message("user" if msg["role"] == "user" else "assistant"): st.markdown(msg["content"])
            
    uploaded_files = st.file_uploader("📷 질문할 사진이나 PDF 파일 업로드", type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True)
    if prompt := st.chat_input("궁금한 점을 질문해 주세요."):
        with st.chat_message("user"):
            st.markdown(prompt)
            if uploaded_files:
                for uf in uploaded_files:
                    if uf.type.startswith("image"): st.image(uf, width=350)
                    else: st.markdown(f"📄 **{uf.name}** 첨부됨")
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown("🤖 **'AI 국최'**가 질문을 분석 중입니다...")
            try:
                model = genai.GenerativeModel(TARGET_MODEL)
                base_instruction = f"당신은 LogyEDU 최준용 국어 원장님의 지식과 관리 방식을 완벽하게 물려받은 'AI 국최'입니다. 학생 이름은 '{student_name}'이고 소속은 '{student_class}'입니다. 대답을 시작할 때 항상 '안녕하세요! AI 국최입니다.' 와 같이 자신의 정체성을 밝히세요. 학생의 질문에 조금의 오류도 없이 정확하고 올바른 정답과 명쾌한 해설을 제공하세요. 국어 외의 사적인 잡담은 거절하세요."
                
                fb_class_ans = ""; fb_common_ans = ""
                if db:
                    try:
                        c_doc = db.collection("ai_knowledge").document(f"class_{safe_class}").get()
                        if c_doc.exists: fb_class_ans = c_doc.to_dict().get("text", "")
                        r_doc = db.collection("ai_knowledge").document("common_reference").get()
                        if r_doc.exists: fb_common_ans = r_doc.to_dict().get("text", "")
                    except: pass
                
                if fb_class_ans: base_instruction += f"\n\n[해당 반 누적 과제 정답지]\n{fb_class_ans}"
                elif os.path.exists(class_ans_txt):
                    with open(class_ans_txt, mode='r', encoding='utf-8') as f: today_ans = f.read()
                    if today_ans.strip(): base_instruction += f"\n\n[해당 반 누적 과제 정답지]\n{today_ans}"
                
                if fb_common_ans: base_instruction += f"\n\n[학원 누적 해설지]\n{fb_common_ans}"
                elif os.path.exists(reference_file_path):
                    with open(reference_file_path, mode='r', encoding='utf-8') as f: accumulated_doc = f.read()
                    if accumulated_doc.strip(): base_instruction += f"\n\n[학원 누적 해설지]\n{accumulated_doc}"
                
                contents = [f"{base_instruction}\n\n[학생 질문]\n{prompt}"]
                if uploaded_files:
                    for uf in uploaded_files: contents.append({"mime_type": uf.type if not uf.type.endswith("pdf") else "application/pdf", "data": uf.getvalue()})
                
                response = model.generate_content(contents)
                ai_response = response.text
                message_placeholder.markdown(ai_response)
                st.session_state.messages.append({"role": "model", "content": ai_response})
                
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                file_count = f"{len(uploaded_files)}개" if uploaded_files else "0개"
                with open(log_file_path, mode='a', newline='', encoding='utf-8-sig') as f:
                    csv.writer(f).writerow([now_str, student_class, student_name, prompt, file_count, ai_response[:50] + "..."])
                if db:
                    db.collection("chat_logs").add({"질문일시": now_str, "반이름": student_class, "학생이름": student_name, "질문내용": prompt, "첨부파일수": file_count, "AI답변요약": ai_response[:50] + "..."})
                send_telegram_alert(f"💡 [국어 질문]\n- 반: {student_class}\n- 학생: {student_name}\n- 질문: {prompt}")
            except Exception as e: message_placeholder.error(f"오류: {e}")
    st.divider(); st.link_button("🚨 '찐' 국최 원장님께 직접 질문하기", "https://open.kakao.com/o/sERIEkKi")

elif menu == "🔒 원장님 전용 관리실":
    st.subheader("🔒 원장님 전용 관리실")
    tab1, tab2, tab3 = st.tabs(["🪄 AI 문제 출제기", "⏳ 실시간 관제소", "💯 시스템 설정"])
    
    with tab1:
        st.markdown("#### 🪄 로지에듀 전용 AI 문제 출제기")
        q_mode = st.radio("📝 출제 모드 선택", ["✨ 새로운 지문 기반 신규 문제 창조", "🔄 기존 기출문제 기반 쌍둥이 변형 문제 출제"], horizontal=True)
        col_t1, col_t2 = st.columns([2, 1])
        with col_t1: q_test_title = st.text_input("📝 시험 제목", placeholder="예: 미강고 대비 1회")
        with col_t2: q_target_class = st.selectbox("🎯 온라인 배포 대상", ["전체"] + CLASS_LIST)
        col_q1, col_q2 = st.columns(2)
        with col_q1: q_style = st.selectbox("🎯 출제 스타일", ["수능형", "내신형", "문해력형"])
        with col_q2: q_type = st.multiselect("📝 문제 유형 선택", ["5지 선다형", "O/X 문제형", "단답형", "서술형/논술형"], default=[])
        
        col_d1, col_d2, col_d3 = st.columns(3)
        with col_d1: cnt_high = st.number_input("📈 상난이도", min_value=0, max_value=10, value=1)
        with col_d2: cnt_mid = st.number_input("📊 중난이도", min_value=0, max_value=10, value=2)
        with col_d3: cnt_low = st.number_input("📉 하난이도", min_value=0, max_value=10, value=0)
        total_q_count = cnt_high + cnt_mid + cnt_low
        
        q_files = st.file_uploader("📂 기준 자료 파일 업로드", type=["jpg", "png", "pdf"], accept_multiple_files=True)
        q_text = st.text_area("📄 텍스트 입력", height=150)
        
        if "q_list" not in st.session_state: st.session_state.q_list = []
        if st.button("🚀 로지에듀 수준의 완벽한 문제 최초 생성", use_container_width=True):
            if total_q_count == 0: st.warning("출제할 문항 수를 설정해 주세요.")
            else:
                with st.status("⏳ **AI 국최 두뇌 가동 중...**", expanded=True) as status:
                    try:
                        q_model = genai.GenerativeModel(TARGET_MODEL)
                        q_prompt = f"로지에듀 국어학원 출제위원입니다. 별표(*)사용금지. 지문당 최대 5문제. 총 {total_q_count}문제 출제. \n입력자료:\n{q_text}"
                        contents = [q_prompt]
                        if q_files:
                            for qf in q_files: contents.append({"mime_type": qf.type if not qf.type.endswith("pdf") else "application/pdf", "data": qf.getvalue()})
                        
                        stream_box = st.empty(); full_generated_text = ""
                        for chunk in q_model.generate_content(contents, stream=True):
                            full_generated_text += chunk.text
                            stream_box.markdown(clean_ai_text(full_generated_text) + " ▌")
                        stream_box.markdown(clean_ai_text(full_generated_text))
                        status.update(label="✅ 출제 완료!", state="complete", expanded=False)
                    except Exception as e:
                        status.update(label="🚨 오류 발생", state="error", expanded=True); st.error(str(e))
                        
    with tab2: st.info("실시간 관제 기능 작동 준비 중")
    with tab3: st.info("시스템 설정 준비 중")
else:
    st.info("준비 중인 메뉴입니다.")
