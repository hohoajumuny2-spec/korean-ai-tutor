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

# 1. 페이지 설정
st.set_page_config(
    page_title="24시 국어 해결사 (내용 기반 RAG)", layout="wide"
)
st.title("📚 24시 국어 해결사 (AI 국어 튜터)")
st.markdown(
    "업로드된 해설지 본문 내용을 스스로 분석하여 정확한 정답과 해설을"
    " 제공합니다."
)

# 2. 사이드바: API 키 및 파일 업로드
with st.sidebar:
  st.header("⚙️ 환경 설정 및 자료 관리")
  api_key = st.text_input("Gemini API Key 입력", type="password")

  st.markdown("---")
  uploaded_files = st.file_uploader(
      "국어 해설지/답안지 PDF 업로드",
      type=["pdf"],
      accept_multiple_files=True,
  )

if not api_key:
  st.warning(
      "⚠️ 좌측 사이드바에 Gemini API Key를 먼저 입력해 주세요. (무료 키"
      " 사용 가능)"
  )
  st.stop()

# 환경변수에 API 키 설정
os.environ["GOOGLE_API_KEY"] = api_key

# 3. 업로드된 파일들을 읽어 '내용 기반 벡터 데이터베이스(Vector DB)'로 변환
retriever = None
if uploaded_files:
  # 파일 변경 시에만 다시 처리하도록 캐싱 처리
  @st.cache_resource
  _files_hash = tuple((f.name, f.size) for f in uploaded_files)

  def load_and_vectorize(files_hash):
    docs = []
    for uploaded_file in uploaded_files:
      # 스트림릿 임시 파일 생성 로직
      with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

      # PDF 파일 읽기
      loader = PyPDFLoader(tmp_path)
      docs.extend(loader.load())
      os.unlink(tmp_path)  # 임시 파일 삭제

    # 텍스트를 AI가 검색하기 좋게 잘게 쪼개기 (Chunking)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, chunk_overlap=200
    )
    splits = text_splitter.split_documents(docs)

    # 제미나이 임베딩 모델로 의미 값 변환 및 벡터 저장소(Chroma) 구축
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    vectorstore = Chroma.from_documents(documents=splits, embedding=embeddings)

    # 검색기(Retriever) 생성 (질문과 가장 유사한 본문 조각 3개를 가져옴)
    return vectorstore.as_retriever(
        search_type="similarity", search_kwargs={"k": 3}
    )

  try:
    with st.spinner("🔄 업로드된 자료의 본문 내용을 분석 중입니다..."):
      retriever = load_and_vectorize(_files_hash)
    st.sidebar.success(
        f"✅ 총 {len(uploaded_files)}개 파일의 본문 분석 및 학습 완료!"
    )
  except Exception as e:
    st.sidebar.error(f"오류 발생: {e}")
else:
  st.info(
      "👉 좌측 사이드바에서 해설지 PDF 파일을 업로드하면 AI가 본문 내용을"
      " 학습하기 시작합니다."
  )

# 4. 채팅 화면 구성
if "messages" not in st.session_state:
  st.session_state.messages = []

# 이전 대화 기록 출력
for message in st.session_state.messages:
  with st.chat_message(message["role"]):
    st.markdown(message["content"])

# 사용자 질문 입력창
if prompt := st.chat_input(
    "국어 질문을 입력하세요 (예: 15번 문제 정답과 해설이 뭐야?)"
):
  st.session_state.messages.append({"role": "user", "content": prompt})
  with st.chat_message("user"):
    st.markdown(prompt)

  with st.chat_message("assistant"):
    if retriever is None:
      response = "먼저 좌측 사이드바에 해설지 PDF 파일을 업로드해 주세요!"
      st.markdown(response)
    else:
      # 제미나이 모델 세팅 (온도 0: 창작을 막고 오직 사실에만 기반하게 설정)
      llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0)

      # '옳지 않은 답'을 차단하는 엄격한 시스템 프롬프트 작성
      system_prompt = (
          "당신은 오직 제공된 문서의 본문 내용만을 근거로 정확하고 올바른"
          " 답변을 제공하는 국어 전문 AI 튜터입니다.\n"
          "학생의 질문에 답할 때, 반드시 아래에 검색된 문서 내용을"
          " 기반으로만 설명하세요.\n"
          "만약 제공된 문서 내용 안에 정답이나 해설의 근거가 없다면, 절대"
          ' 지어내지 말고 "업로드된 자료에서 해당 내용을 찾을 수 없습니다."'
          "라고만 대답하세요.\n\n"
          "검색된 문서 본문 내용:\n{context}"
      )

      prompt_template = ChatPromptTemplate.from_messages([
          ("system", system_prompt),
          ("human", "{input}"),
      ])

      # RAG 체인 구성 및 실행
      question_answer_chain = create_stuff_documents_chain(llm, prompt_template)
      rag_chain = create_retrieval_chain(retriever, question_answer_chain)

      with st.status("🔍 업로드된 자료 본문에서 해설을 찾는 중...", expanded=False):
        result = rag_chain.invoke({"input": prompt})

      response = result["output"]
      st.markdown(response)

  st.session_state.messages.append(
      {"role": "assistant", "content": response}
  )
