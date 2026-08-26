import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="AI 모델 스캐너", page_icon="🔍")
st.markdown("### 🔍 구글 서버 모델 스캐너")
st.write("원장님의 API 키로 접근 가능한 진짜 모델 이름을 추적합니다.")

if "MY_API_KEY" not in st.secrets:
    st.error("🔑 Secrets에 MY_API_KEY가 없습니다.")
    st.stop()

try:
    # 구글 서버 다이렉트 연결
    genai.configure(api_key=st.secrets["MY_API_KEY"])
    models = genai.list_models()
    
    st.success("✅ 구글 서버 인증 완벽 성공! 아래 목록이 원장님의 열쇠로 사용할 수 있는 모델의 정확한 공식 명칭입니다.")
    
    # 텍스트 분석이 가능한 모델만 걸러서 화면에 출력
    count = 0
    for m in models:
        if 'generateContent' in m.supported_generation_methods:
            st.markdown(f"- **`{m.name.replace('models/', '')}`**")
            count += 1
            
    if count == 0:
        st.warning("⚠️ 인증은 성공했으나, 현재 사용할 수 있는 AI 모델 목록이 비어 있습니다. (구글 클라우드 권한 확인 필요)")

except Exception as e:
    st.error(f"❌ 서버 통신 에러: {e}")
