import os
import tempfile
import streamlit as st
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    GoogleGenerativeAIEmbeddings,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 1. 페이지 기본 설정
st.set_page_config(
    page_title="24시 국최 (AI 국어 튜터)", layout="wide"
)

# 2. 세션 상태(Session State) 초기화 (로그인 및 숙제 제출 여부 기억)
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "student_class" not in st.session_state:
    st.session_state.student_class = ""
if "student_name" not in st.session_state:
    st.session_state.student_name = ""
if "hw_submitted" not in st.session_state:
    st.session_state.hw_submitted = False
if "messages" not in st.session_state:
    st.session_state.messages = []

# 3. 사이드바: 원장님 전용 설정 영역 (API 키 및 자료 업로드)
with st.sidebar:
    st.header("⚙️ 원장님 전용 설정 (자료실)")
    api_key = st.text_input("Gemini API Key 입력", type="password")
    
    st.markdown("---")
    uploaded_pdfs = st.file_uploader(
        "국어 해설지/답안지 PDF 업로드",
        type=["pdf"],
        accept_multiple_files=True,
    )

if not api_key:
    st.warning("⚠️ 좌측 사이드바에 Gemini API Key를 먼저 입력해 주세요.")
    st.stop()

# 환경변수에 API 키 설정
os.environ["GOOGLE_API_KEY"] = api_key

# 4. RAG 벡터 데이터베이스 구축 (원장님 업로드 자료 학습)
retriever = None
if uploaded_pdfs:
    _files_hash = tuple((f.name, f.size) for f in uploaded_pdfs)

    @st.cache_resource
    def load_and_vectorize(files_hash):
        docs = []
        for uploaded_file in uploaded_pdfs:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = tmp.name
            loader = PyPDFLoader(tmp_path)
            docs.extend(loader.load())
            os.unlink(tmp_path) 

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(docs)

        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        vectorstore = Chroma.from_documents(documents=splits, embedding=embeddings)

        return vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 3})

    try:
        with st.spinner("🔄 업로드된 자료의 본문 내용을 분석 중입니다..."):
            retriever = load_and_vectorize(_files_hash)
        st.sidebar.success(f"✅ 총 {len(uploaded_pdfs)}개 파일 학습 완료!")
    except Exception as e:
        st.sidebar.error(f"오류 발생: {e}")

# =====================================================================
# 5. 메인 화면 로직 (로그인 전 / 로그인 후 분리)
# =====================================================================

# [A] 로그인 전 화면 (가이드 이미지 및 로그인 폼)
if not st.session_state.logged_in:
    # 준비하신 메인 이미지 출력
    try:
        st.image("제목을 입력해주세요. (42)_1.jpg", use_column_width=True)
    except FileNotFoundError:
        st.error("⚠️ '제목을 입력해주세요. (42)_1.jpg' 이미지 파일을 파이썬 코드와 같은 폴더에 넣어주세요.")

    st.markdown("### 🔒 학생 로그인")
    st.write("가이드라인 1번에 따라 자신의 반을 선택하고 이름을 입력하세요.")
    
    col1, col2 = st.columns(2)
    with col1:
        # 실제 학원 반 이름으로 수정해서 사용하세요
        selected_class = st.selectbox("소속 반 선택", ["반을 선택하세요", "미강고 1학년", "하남고 1학년", "미사고 2학년", "중등부", "기타"])
    with col2:
        entered_name = st.text_input("학생 이름")
    
    if st.button("로그인 및 24시 국최 입장"):
        if selected_class != "반을 선택하세요" and entered_name.strip():
            st.session_state.logged_in = True
            st.session_state.student_class = selected_class
            st.session_state.student_name = entered_name
            st.rerun() # 화면 새로고침
        else:
            st.error("🚫 반을 선택하고 이름을 정확히 입력해야 로그인이 가능합니다.")

# [B] 로그인 후 화면 (채팅창 및 숙제 제출)
else:
    st.title(f"📚 24시 국최 - {st.session_state.student_class} [{st.session_state.student_name}] 학생")
    
    # 가이드 3, 4번: 숙제 사진 제출 시스템
    if not st.session_state.hw_submitted:
        st.info("💡 가이드라인 3번: 질문을 하려면 먼저 오늘 푼 숙제 사진을 제출해야 합니다.")
        hw_file = st.file_uploader("📸 숙제 사진(이미지) 업로드", type=["jpg", "jpeg", "png"])
        if hw_file is not None:
            st.session_state.hw_submitted = True
            st.success("✅ 숙제 제출이 확인되었습니다! 이제 숙제에 대한 질문이 가능합니다.")
            st.rerun()
    else:
        st.success("✅ 숙제 제출 완료! 모르는 내용을 질문하세요.")

    st.markdown("---")

    # 대화 기록 출력
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # 학생 질문 입력 및 처리
    if prompt := st.chat_input("숙제 중 모르는 내용을 질문하세요 (예: 15번 정답 근거가 뭐야?)"):
        
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            # 숙제를 내지 않으면 답변을 강제 거부
            if not st.session_state.hw_submitted:
                response = "🚫 숙제 사진이 제출되지 않았습니다! 상단의 업로드 창에 숙제를 먼저 제출해야 답을 확인할 수 있습니다."
                st.markdown(response)
            
            # 원장님이 자료를 올리지 않은 경우
            elif retriever is None:
                response = "🚫 아직 원장님께서 해설지 자료를 업로드하지 않으셨습니다. 사이드바를 확인해 주세요."
                st.markdown(response)
            
            # 숙제도 내고, 자료도 있을 경우 -> 제미나이가 해설 진행
            else:
                llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0)

                # 원장님의 철학을 담은 강력한 시스템 프롬프트
                system_prompt = (
                    "당신은 오직 제공된 문서의 내용만을 근거로 완벽하게 정확한 답변을 제공하는 '24시 국최' AI 튜터입니다.\n"
                    "아래의 규칙을 엄격하게 준수하세요.\n"
                    "1. 학생의 질문에 답할 때, 반드시 검색된 문서 내용만을 기반으로 설명하세요.\n"
                    "2. 문서에 정답이나 해설 근거가 없다면 절대 지어내지 말고, '해당 내용은 제공된 자료로 해결할 수 없습니다. 찐 국최 선생님에게 1:1 질문을 해주세요.'라고 답변하세요. (가이드라인 5번)\n"
                    "3. 국어 학습과 무관한 질문이나 사담에는 '수업과 무관한 내용은 답하지 않습니다.'라고 단호하게 거절하세요. (가이드라인 2번)\n\n"
                    "검색된 문서 본문 내용:\n{context}"
                )

                prompt_template = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    ("human", "{input}"),
                ])

                question_answer_chain = create_stuff_documents_chain(llm, prompt_template)
                rag_chain = create_retrieval_chain(retriever, question_answer_chain)

                with st.status("🔍 원장님의 해설지에서 정답을 찾는 중...", expanded=False):
                    result = rag_chain.invoke({"input": prompt})

                response = result["output"]
                st.markdown(response)

        # 시스템 답변을 대화 기록에 저장
        st.session_state.messages.append(
            {"role": "assistant", "content": response}
        )
