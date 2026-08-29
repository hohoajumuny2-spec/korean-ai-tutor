import streamlit as st
import os
import sys
import subprocess
import csv
import requests
import json
import re
from datetime import datetime
import io

# ==========================================
# 🚨 서버 필수 부품 강제 설치 (PDF 패키지 reportlab 추가)
# ==========================================
@st.cache_resource
def ensure_dependencies():
    try:
        import google.generativeai
        import firebase_admin
        import reportlab
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "requests", "google-generativeai", "firebase-admin", "reportlab"])

ensure_dependencies()
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# ==========================================
# 📄 PDF 조판 엔진 및 폰트 자동 세팅
# ==========================================
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, KeepTogether, NextPageTemplate, PageBreak
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.units import cm

@st.cache_resource
def load_fonts():
    import urllib.request
    
    # 1. 기본 고딕 폰트 (문제/선택지용)
    base_font_path = "NanumGothic.ttf"
    if not os.path.exists(base_font_path):
        url = "[https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf](https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf)"
        urllib.request.urlretrieve(url, base_font_path)
    pdfmetrics.registerFont(TTFont('KoreanFont', base_font_path))
    
    # 2. 지문 전용 폰트 (HY그래픽)
    hy_font_path = "HYGraphic.ttf"
    if os.path.exists(hy_font_path):
        pdfmetrics.registerFont(TTFont('HYGraphic', hy_font_path))
        passage_font = 'HYGraphic'
    else:
        passage_font = 'KoreanFont' # HY그래픽 파일이 없을 경우 임시 대체
        
    return passage_font

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
TELEGRAM_TOKEN = st.
