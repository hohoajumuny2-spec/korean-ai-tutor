<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">
    <title>로지에듀 최준용 국어 - AI 스마트 플랫폼</title>
    <link rel="manifest" href="./manifest.json">
    <meta name="theme-color" content="#1a1e29">
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
    <script>pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';</script>
    <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
        body { font-family: 'Pretendard', sans-serif; background-color: #1a1e29; color: #ffffff; scroll-behavior: smooth; }
        .fade-in { animation: fadeIn 0.4s ease-out forwards; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        ::-webkit-scrollbar { width: 8px; } ::-webkit-scrollbar-track { background: #1a1e29; } ::-webkit-scrollbar-thumb { background: #3b82f6; border-radius: 4px; }
        .modal-bg { background-color: rgba(15, 23, 42, 0.85); backdrop-filter: blur(5px); }
        .app-card:hover { transform: translateY(-8px); box-shadow: 0 20px 25px -5px rgba(59, 130, 246, 0.2); border-color: #3b82f6; }
        .admin-tab-content, .prog-content { display: none; } .active-tab { display: block; animation: fadeIn 0.3s ease-out forwards; }
        .omr-circle { width: 32px; height: 32px; border-radius: 50%; border: 2px solid #4b5563; display: flex; align-items: center; justify-content: center; cursor: pointer; font-weight: bold; transition: all 0.2s; font-size: 0.9rem; outline: none; }
        @media (min-width: 1024px) { .omr-circle { width: 36px; height: 36px; font-size: 1rem; } }
        .omr-circle.active { background-color: #3b82f6; border-color: #3b82f6; color: white; }
        #toast-container { position: fixed; top: 20px; left: 50%; transform: translateX(-50%); z-index: 9999; }
        .toast { background-color: #ef4444; color: white; padding: 15px 30px; border-radius: 50px; font-weight: bold; font-size: 1.1rem; opacity: 0; transition: opacity 0.5s; display: flex; align-items: center; gap: 10px; }
        .toast.show { opacity: 1; }
        #live-toast-container { position: absolute; top: 10px; left: 50%; transform: translateX(-50%); z-index: 100; width: 90%; pointer-events: none;}
        .drop-zone { border: 2px dashed #4b5563; border-radius: 0.75rem; padding: 2rem; text-align: center; cursor: pointer; transition: all 0.3s ease; background-color: #1e2430; display: block; }
        .drop-zone:hover, .drop-zone.dragover { border-color: #3b82f6; background-color: #1e293b; }
        #pdf-render-wrapper { position: relative; overflow: auto; width: 100%; height: 100%; touch-action: pan-x pan-y pinch-zoom; background: #525659; }
        #pdf-inner-container { position: relative; margin: 0 auto; background: transparent; }
    </style>
</head>
<body class="min-h-screen flex flex-col relative overflow-x-hidden">

    <div id="global-loader" class="hidden fixed inset-0 z-[9999] bg-[#0f172a]/95 backdrop-blur-md flex flex-col items-center justify-center fade-in">
        <div class="relative w-24 h-24 mb-8">
            <div class="absolute inset-0 border-t-4 border-blue-500 border-solid rounded-full animate-spin"></div>
            <div class="absolute inset-2 border-r-4 border-emerald-500 border-solid rounded-full animate-spin" style="animation-direction: reverse; animation-duration: 1.5s;"></div>
        </div>
        <p id="global-loader-text" class="text-xl md:text-2xl font-black text-emerald-400 tracking-wider text-center px-4 animate-pulse whitespace-pre-wrap leading-relaxed bg-gray-900/80 p-4 rounded-xl shadow-2xl border border-emerald-500/30">파일을 업로드 중입니다...</p>
    </div>

    <div id="toast-container"></div>

    <div id="main-popup" class="hidden fixed inset-0 z-[200] modal-bg flex items-center justify-center p-4">
        <div class="bg-[#1e2430] border border-blue-500 p-8 rounded-2xl w-full max-w-md shadow-2xl flex flex-col fade-in relative overflow-hidden">
            <div class="absolute top-0 left-0 w-full h-2 bg-blue-500"></div>
            <h2 class="text-2xl font-black text-white mb-4 mt-2"><i class="fa-solid fa-bullhorn text-blue-400 mr-2"></i>로지에듀 스마트 플랫폼 오픈!</h2>
            <div class="text-gray-300 text-sm leading-relaxed mb-6">
                <p class="mb-2">학생 여러분, 환영합니다.</p>
                <p class="mb-2">이제 종이 없이 언제 어디서나 스마트폰과 태블릿으로 모의고사를 보고, 24시간 AI 튜터 '국최'에게 질문할 수 있습니다.</p>
                <p class="text-yellow-400 font-bold">오류 사항이나 문의는 상단 메뉴의 [문의 사항]을 이용해 주세요!</p>
            </div>
            <div class="flex gap-2">
                <button onclick="closeMainPopup(true)" class="flex-1 bg-gray-700 hover:bg-gray-600 text-gray-300 py-3 rounded-xl font-bold transition text-xs">오늘 하루 보지 않기</button>
                <button onclick="closeMainPopup(false)" class="flex-1 bg-blue-600 hover:bg-blue-700 text-white py-3 rounded-xl font-bold transition text-xs">닫기</button>
            </div>
        </div>
    </div>

    <div id="inquiry-modal" class="hidden fixed inset-0 z-[150] modal-bg flex items-center justify-center p-4">
        <div class="bg-[#1e2430] border border-gray-700 p-8 rounded-2xl w-full max-w-md shadow-2xl">
            <div class="flex justify-between items-center mb-6 border-b border-gray-700 pb-4">
                <h3 class="text-2xl font-black text-white"><i class="fa-solid fa-paper-plane text-emerald-400 mr-2"></i>원장님께 문의하기</h3>
                <button onclick="closeModal('inquiry-modal')" class="text-gray-400 hover:text-white text-2xl outline-none"><i class="fa-solid fa-xmark"></i></button>
            </div>
            <p class="text-xs text-gray-400 mb-4">작성하신 내용은 원장님께 실시간으로 전달됩니다.</p>
            <textarea id="inquiry-content" class="w-full h-32 bg-[#151922] border border-gray-600 p-4 rounded-xl text-white mb-6 outline-none focus:border-emerald-500 transition" placeholder="궁금한 점이나 오류 신고를 자유롭게 적어주세요..."></textarea>
            <button onclick="submitInquiry()" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-4 rounded-xl text-lg transition shadow-lg shadow-emerald-600/30">전송하기</button>
        </div>
    </div>

    <nav class="fixed top-0 w-full z-50 bg-[#1a1e29]/95 border-b border-gray-800 backdrop-blur-sm">
        <div class="flex justify-between items-center px-4 md:px-8 py-4">
            <div class="text-xl md:text-2xl font-black text-white cursor-pointer" onclick="goHome()">로지에듀<span class="text-blue-500">*</span></div>
            <div class="hidden md:flex gap-6 items-center text-sm font-bold text-gray-300">
                <!-- 💡 프로그램 소개, 이용 안내 링크 정상 작동 -->
                <button onclick="scrollToSection('intro-section')" class="hover:text-blue-400">프로그램 소개</button>
                <button onclick="scrollToSection('guide-section')" class="hover:text-blue-400">이용 안내</button>
                <button onclick="openProgram('board'); loadBoard();" class="hover:text-blue-400">공지사항</button>
                <button onclick="openProgram('inquiry'); loadInquiries();" class="hover:text-emerald-400">문의 사항</button>
            </div>
            <div class="flex items-center gap-3">
                <div id="auth-nav" class="flex gap-2">
                    <button onclick="scrollToSection('guide-section')" class="text-gray-300 hover:text-yellow-400 transition hidden md:inline-block"><i class="fa-solid fa-lightbulb mr-1"></i> 이용 가이드</button>
                    <button onclick="showModal('auth')" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-bold text-xs"><i class="fa-solid fa-lock mr-1"></i> 로그인</button>
                </div>
                <div id="user-nav" class="hidden items-center gap-3">
                    <span id="header-user-info" class="text-blue-400 font-bold text-xs md:text-sm"></span>
                    <button onclick="openProgram('mypage'); loadMyPage();" class="text-emerald-400 font-bold border border-emerald-600 px-3 py-1.5 rounded-lg text-xs bg-emerald-900/20" id="btn-mypage-nav" style="display:none;">마이페이지</button>
                    <button onclick="goToDashboard()" class="text-white hover:text-blue-400 font-bold border border-gray-600 px-3 py-1.5 rounded-lg text-xs">학습실</button>
                    <button onclick="logout()" class="text-gray-400 hover:text-white underline text-xs hidden md:inline">로그아웃</button>
                </div>
                <button class="md:hidden text-gray-300 text-xl focus:outline-none" onclick="toggleMobileMenu()"><i class="fa-solid fa-bars"></i></button>
            </div>
        </div>
        
        <div id="mobile-menu" class="hidden flex-col bg-[#151922] border-t border-gray-800 text-sm font-bold text-gray-300 shadow-xl">
            <button onclick="scrollToSection('intro-section'); toggleMobileMenu();" class="text-left p-4 border-b border-gray-800 hover:text-blue-400 w-full">프로그램 소개</button>
            <button onclick="scrollToSection('guide-section'); toggleMobileMenu();" class="text-left p-4 border-b border-gray-800 hover:text-blue-400 w-full">이용 안내</button>
            <button onclick="openProgram('board'); loadBoard(); toggleMobileMenu();" class="text-left p-4 border-b border-gray-800 hover:text-blue-400 w-full">공지사항</button>
            <button onclick="openProgram('inquiry'); loadInquiries(); toggleMobileMenu();" class="text-left p-4 border-b border-gray-800 hover:text-emerald-400 w-full">문의 사항</button>
            <button onclick="openProgram('mypage'); loadMyPage(); toggleMobileMenu();" class="text-left p-4 border-b border-gray-800 text-emerald-400 w-full" id="mobile-mypage-btn" style="display:none;">마이페이지</button>
            <a href="https://logyedu.com" target="_blank" class="p-4 border-b border-gray-800 hover:text-blue-400"><i class="fa-solid fa-globe mr-1"></i>로지에듀 홈페이지</a>
            <button onclick="logout()" class="text-left p-4 text-red-400 w-full" id="mobile-logout-btn" style="display:none;">로그아웃</button>
        </div>
    </nav>

    <!-- 💡 홈 화면(소개 및 이용안내 복구 완료) -->
    <div id="home-view" class="w-full flex-grow flex flex-col items-center pt-20 px-4 overflow-y-auto">
        <div class="text-center z-10 fade-in min-h-[80vh] flex flex-col justify-center items-center w-full">
            <h1 class="text-4xl md:text-6xl lg:text-[5rem] font-black text-white mb-10 tracking-tight leading-tight word-break-keep-all"><span class="text-blue-500">'로지는 언제나 올바름'</span>을 찾아냈습니다.<br><span class="text-2xl md:text-4xl lg:text-[2.5rem] mt-6 block text-gray-300 font-bold">그리고 그것이 <span class="text-blue-500">정답</span>이 되는 길을 만들었습니다.</span></h1>
            <div class="flex flex-col md:flex-row gap-4 justify-center">
                <button onclick="goToDashboard()" class="bg-blue-600 hover:bg-blue-700 text-white px-8 py-4 md:px-10 md:py-5 rounded-xl font-bold text-lg md:text-xl shadow-lg">스마트 학습실 입장하기</button>
            </div>
        </div>
        
        <div id="intro-section" class="w-full max-w-5xl mx-auto py-24 text-left border-t border-gray-800">
            <h2 class="text-3xl font-bold text-blue-400 mb-6"><i class="fa-solid fa-circle-info mr-2"></i>프로그램 소개</h2>
            <div class="bg-[#151922] p-8 rounded-2xl border border-gray-700 text-gray-300 leading-relaxed text-lg">
                <p class="mb-4"><strong>로지에듀 스마트 플랫폼</strong>은 학생들의 완벽한 국어 학습을 위해 탄생한 AI 기반 맞춤형 학습 시스템입니다.</p>
                <ul class="list-disc pl-6 space-y-2">
                    <li><strong class="text-white">24시간 AI 튜터:</strong> 언제든 질문하고 즉각적인 답변을 받을 수 있습니다.</li>
                    <li><strong class="text-white">타임어택 퀴즈:</strong> 정해진 기한과 시간 내에 긴장감 있게 퀴즈를 풀고 실력을 점검합니다.</li>
                    <li><strong class="text-white">실시간 모의고사:</strong> 실제 시험과 동일한 타이머와 OMR 카드를 통해 실전 감각을 극대화합니다.</li>
                    <li><strong class="text-white">AI 논술/요약 첨삭:</strong> 학생이 작성한 논술문을 AI가 꼼꼼하고 예리하게 첨삭하여 피드백을 제공합니다.</li>
                </ul>
            </div>
        </div>

        <div id="guide-section" class="w-full max-w-5xl mx-auto py-24 text-left border-t border-gray-800 mb-20">
            <h2 class="text-3xl font-bold text-emerald-400 mb-6"><i class="fa-solid fa-book-open mr-2"></i>이용 안내</h2>
            <div class="bg-[#151922] p-8 rounded-2xl border border-gray-700 text-gray-300 leading-relaxed text-lg">
                <div class="mb-6">
                    <h4 class="text-xl font-bold text-white mb-2">1. 로그인 방법</h4>
                    <p>우측 상단의 [로그인] 버튼을 클릭한 후, 원장님께서 명단에 등록하신 <strong>학교, 학년, 이름</strong>을 띄어쓰기 없이 정확히 입력해야 접속할 수 있습니다.</p>
                </div>
                <div>
                    <h4 class="text-xl font-bold text-white mb-2">2. 과제 제출 및 성적 확인</h4>
                    <p>스마트 학습실의 [과제 제출] 메뉴에서 사진이나 스캔본을 업로드하면, 즉시 정답 및 해설 파일을 열람할 수 있습니다. 퀴즈와 모의고사 성적은 [마이페이지]에서 언제든 확인 가능합니다.</p>
                </div>
            </div>
        </div>
    </div>

    <div id="dashboard-screen" class="hidden flex-grow pt-24 px-4 max-w-7xl mx-auto w-full fade-in pb-12">
        <div id="dashboard-home" class="active-tab">
            <h2 class="text-2xl font-bold mb-6">스마트 학습실</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-6">
                <div onclick="openProgram('chat')" class="bg-[#1e2430] border border-blue-600/50 p-6 md:p-8 rounded-2xl cursor-pointer app-card">
                    <div class="w-12 h-12 md:w-14 md:h-14 bg-blue-600 text-white rounded-xl flex items-center justify-center text-xl md:text-2xl mb-4 md:mb-6">🤖</div>
                    <h3 class="text-lg md:text-xl font-bold mb-2 text-white">24시간 AI 국최</h3>
                    <p class="text-blue-200/70 text-xs md:text-sm">국어와 관련된 어떤 질문이든 자유롭게 물어보세요.</p>
                </div>
                <div onclick="openProgram('quiz-list'); loadStudentQuizzes();" class="bg-[#1e2430] border border-orange-600/50 p-6 md:p-8 rounded-2xl cursor-pointer app-card">
                    <div class="w-12 h-12 md:w-14 md:h-14 bg-orange-600 text-white rounded-xl flex items-center justify-center text-xl md:text-2xl mb-4 md:mb-6">⏱️</div>
                    <h3 class="text-lg md:text-xl font-bold mb-2 text-white">타임어택 퀴즈</h3>
                    <p class="text-orange-200/70 text-xs md:text-sm">마감일과 제한시간이 있는 퀴즈를 풀고 점수를 확인하세요.</p>
                </div>
                <div onclick="openProgram('exam-list'); loadStudentExams();" class="bg-[#1e2430] border border-yellow-600/50 p-6 md:p-8 rounded-2xl cursor-pointer app-card">
                    <div class="w-12 h-12 md:w-14 md:h-14 bg-yellow-600 text-white rounded-xl flex items-center justify-center text-xl md:text-2xl mb-4 md:mb-6">⏳</div>
                    <h3 class="text-lg md:text-xl font-bold mb-2 text-white">실시간 모의고사</h3>
                    <p class="text-yellow-200/70 text-xs md:text-sm">타이머와 OMR 카드가 제공되는 실전 모의고사입니다.</p>
                </div>
                <div onclick="openProgram('lecture'); loadLectures();" class="bg-[#1e2430] border border-purple-600/50 p-6 md:p-8 rounded-2xl cursor-pointer app-card">
                    <div class="w-12 h-12 md:w-14 md:h-14 bg-purple-600 text-white rounded-xl flex items-center justify-center text-xl md:text-2xl mb-4 md:mb-6">🎬</div>
                    <h3 class="text-lg md:text-xl font-bold mb-2 text-white">해설 강의실</h3>
                    <p class="text-purple-200/70 text-xs md:text-sm">원장님의 명쾌 해설 강의를 수강하세요.</p>
                </div>
                <div onclick="openProgram('essay')" class="bg-[#1e2430] border border-pink-600/50 p-6 md:p-8 rounded-2xl cursor-pointer app-card">
                    <div class="w-12 h-12 md:w-14 md:h-14 bg-pink-600 text-white rounded-xl flex items-center justify-center text-xl md:text-2xl mb-4 md:mb-6">✍️</div>
                    <h3 class="text-lg md:text-xl font-bold mb-2 text-white">AI 논술/요약 첨삭</h3>
                    <p class="text-pink-200/70 text-xs md:text-sm">손글씨/PDF 논술문을 올리면 AI가 직접 빨간펜 첨삭을 해줍니다.</p>
                </div>
                <div onclick="openProgram('homework'); loadHomeworks();" class="bg-[#1e2430] border border-emerald-600/50 p-6 md:p-8 rounded-2xl cursor-pointer app-card">
                    <div class="w-12 h-12 md:w-14 md:h-14 bg-emerald-600 text-white rounded-xl flex items-center justify-center text-xl md:text-2xl mb-4 md:mb-6">📝</div>
                    <h3 class="text-lg md:text-xl font-bold mb-2 text-white">과제 제출</h3>
                    <p class="text-emerald-200/70 text-xs md:text-sm">원장님이 내주신 과제를 제출하고 해설을 확인하세요.</p>
                </div>
                <div onclick="openProgram('board'); loadBoard();" class="bg-[#1e2430] border border-gray-600 p-6 md:p-8 rounded-2xl cursor-pointer app-card">
                    <div class="w-12 h-12 md:w-14 md:h-14 bg-gray-600 text-white rounded-xl flex items-center justify-center text-xl md:text-2xl mb-4 md:mb-6">📢</div>
                    <h3 class="text-lg md:text-xl font-bold mb-2 text-white">공지사항</h3>
                    <p class="text-gray-400 text-xs md:text-sm">학원 필수 자료 및 공지사항을 확인합니다.</p>
                </div>
                
                <div id="card-admin" onclick="openProgram('admin')" class="hidden bg-[#1e2430] border border-red-500 p-6 md:p-8 rounded-2xl cursor-pointer app-card flex-col items-start">
                    <div class="w-12 h-12 md:w-14 md:h-14 bg-red-600 text-white rounded-xl flex items-center justify-center text-xl md:text-2xl mb-4 md:mb-6">⚙️</div>
                    <h3 class="text-lg md:text-xl font-bold mb-2 text-white">시스템 통합 관리</h3>
                    <p class="text-red-300 text-xs md:text-sm">출제, 시험/과제 오픈, 학생 명단을 관리합니다.</p>
                </div>
            </div>
        </div>

        <div id="program-view" style="display: none;" class="fade-in pt-24 px-4 pb-12 w-full max-w-7xl mx-auto">
            <button onclick="closeProgram()" class="mb-4 text-gray-400 hover:text-white font-bold"><i class="fa-solid fa-arrow-left"></i> 돌아가기</button>

            <!-- 마이페이지 -->
            <div id="prog-mypage" class="prog-content w-full max-w-5xl mx-auto bg-[#1e2430] p-6 rounded-xl border border-gray-800">
                <h2 class="text-2xl font-bold text-emerald-400 mb-4">나의 학습 기록</h2>
                <div class="grid grid-cols-2 gap-4 mb-4"><div class="bg-[#151922] p-4 rounded-xl border border-gray-700"><p id="mypage-info" class="text-lg text-white font-bold"></p></div><div class="bg-[#151922] p-4 rounded-xl border border-gray-700"><p id="mypage-count" class="text-xl text-emerald-400 font-black">0건</p></div></div>
                <div id="mypage-history-list" class="space-y-2 bg-[#151922] p-4 rounded-xl h-[400px] overflow-y-auto text-gray-300"></div>
            </div>

            <!-- 공지사항 -->
            <div id="prog-board" class="prog-content w-full max-w-4xl mx-auto">
                <div class="flex justify-between items-center mb-6">
                    <h2 class="text-3xl font-bold text-white"><i class="fa-solid fa-bullhorn text-emerald-400 mr-3"></i>공지사항</h2>
                    <button id="btn-show-board-write" onclick="document.getElementById('board-write-area').style.display='block'" class="hidden bg-emerald-600 hover:bg-emerald-700 px-6 py-2 rounded-lg text-white font-bold transition">새 글 작성</button>
                </div>
                
                <div id="board-write-area" class="hidden bg-[#1e2430] p-6 border border-emerald-500 rounded-2xl mb-8 shadow-xl">
                    <input type="text" id="bd-title" placeholder="제목을 입력하세요" class="w-full bg-[#151922] border border-gray-600 p-4 text-white mb-4 rounded-lg outline-none focus:border-emerald-500">
                    <textarea id="bd-desc" placeholder="내용을 입력하세요" class="w-full h-32 bg-[#151922] border border-gray-600 p-4 text-white mb-4 rounded-lg outline-none focus:border-emerald-500"></textarea>
                    <div class="flex items-center gap-4 mb-4">
                        <input type="file" id="bd-file" multiple accept=".pdf, image/*" class="text-white" onchange="handleFileSelect(event, bdFiles, 'bd-file-visual')">
                        <div id="bd-file-visual" class="flex flex-wrap gap-2"></div>
                    </div>
                    <div class="flex justify-end gap-2">
                        <button onclick="document.getElementById('board-write-area').style.display='none'" class="bg-gray-700 hover:bg-gray-600 px-6 py-2 rounded-lg text-white transition">취소</button>
                        <button onclick="createBoard()" class="bg-emerald-600 hover:bg-emerald-700 px-6 py-2 rounded-lg text-white font-bold transition">등록하기</button>
                    </div>
                </div>

                <div id="board-list" class="space-y-6"></div>
            </div>

            <!-- 문의 사항 -->
            <div id="prog-inquiry" class="prog-content w-full bg-[#1e2430] p-6 rounded-xl border border-gray-800">
                <h2 class="text-2xl font-bold text-emerald-400 mb-4">문의 사항</h2>
                <textarea id="inquiry-content-main" class="w-full h-24 bg-[#1e2430] p-4 text-white mb-4 rounded" placeholder="궁금한 점이나 오류 신고를 자유롭게 적어주세요..."></textarea><button onclick="submitInquiry('main')" class="w-full bg-emerald-600 py-3 rounded text-white font-bold">전송</button>
                <div id="inquiry-list" class="mt-4 space-y-2"></div>
            </div>

            <!-- 채팅 -->
            <div id="prog-chat" class="prog-content w-full max-w-6xl mx-auto bg-[#1e2430] p-4 md:p-8 rounded-xl border border-gray-800 shadow-2xl">
                <h2 class="text-2xl md:text-3xl font-bold text-blue-400 mb-4 md:mb-6"><i class="fa-solid fa-robot mr-2"></i>24시간 AI 국최</h2>
                <div id="chat-history" class="h-[60vh] overflow-y-auto mb-4 bg-[#151922] p-4 rounded-xl border border-gray-700 text-sm md:text-lg leading-relaxed">
                    <div class="text-left mb-6">
                        <span class="bg-gray-800 px-4 py-3 md:px-6 md:py-5 rounded-2xl text-white inline-block shadow-lg border border-gray-700">
                            <span class="block mb-2 font-bold text-blue-400 text-base md:text-xl">🤖 스마트 국최</span>
                            안녕하세요. 로지에듀 여러분! 저는 스마트 국최입니다. 국어에 대한 질문을 해주세요!
                        </span>
                    </div>
                </div>
                <div class="flex flex-col gap-2">
                    <div id="chat-file-visual" class="empty:hidden flex flex-wrap gap-2 px-1"></div>
                    <div class="flex gap-2 items-center w-full">
                        <label for="chat-file" class="cursor-pointer bg-gray-700 hover:bg-gray-600 p-3 rounded-xl text-white transition flex-shrink-0"><i class="fa-solid fa-paperclip"></i></label>
                        <input type="file" id="chat-file" class="hidden" multiple accept="image/*,.pdf" onchange="handleFileSelect(event, chatFiles, 'chat-file-visual')">
                        <input type="text" id="chat-input" class="flex-grow bg-[#151922] border border-gray-600 text-white p-3 rounded-xl text-sm md:text-lg outline-none" placeholder="질문 입력..." onkeypress="if(event.key==='Enter') sendChat()">
                        <div id="chat-file-label" class="hidden"></div>
                        <button onclick="sendChat()" class="bg-blue-600 hover:bg-blue-700 px-5 py-3 rounded-xl text-white transition flex-shrink-0"><i class="fa-solid fa-paper-plane"></i></button>
                    </div>
                </div>
            </div>

            <!-- 에세이 -->
            <div id="prog-essay" class="prog-content w-full bg-[#1e2430] p-6 rounded-xl border border-gray-800">
                <h2 class="text-2xl font-bold text-pink-400 mb-4">AI 첨삭</h2>
                <input type="text" id="essay-topic" placeholder="논제 입력" class="w-full bg-[#151922] p-3 text-white mb-4"><input type="file" id="essay-file" class="text-white"><button onclick="submitEssayGrade()" class="w-full bg-pink-600 py-3 mt-4 text-white font-bold rounded shadow-lg transition hover:bg-pink-700">첨삭 시작</button>
                <div id="essay-result-area" class="hidden bg-white p-6 mt-4 text-black rounded"><div id="essay-feedback"></div></div>
            </div>

            <!-- 강의실 -->
            <div id="prog-lecture" class="prog-content w-full bg-[#1e2430] p-6 rounded-xl"><h2 class="text-2xl font-bold text-purple-400 mb-4">강의실</h2><div id="student-lecture-list" class="grid grid-cols-2 gap-4"></div></div>
            
            <!-- 과제 제출 -->
            <div id="prog-homework" class="prog-content w-full bg-[#1e2430] p-6 rounded-xl">
                <h2 class="text-2xl font-bold text-emerald-400 mb-4">과제 제출</h2>
                <div id="student-hw-list" class="space-y-4"></div>
                <div id="hw-submit-area" class="hidden mt-6 bg-[#151922] p-6 rounded-xl border border-emerald-500 shadow-xl">
                    <h3 id="hw-target-title" class="text-xl text-white font-bold mb-4 border-b border-gray-700 pb-2"></h3>
                    <p class="text-gray-400 text-sm mb-4">문제 풀이 사진이나 스캔 파일을 여러 장 선택하여 제출할 수 있습니다.</p>
                    <input type="file" id="hw-file" multiple class="w-full text-white bg-gray-800 p-3 rounded mb-4">
                    <button onclick="submitHomework()" class="w-full bg-emerald-600 hover:bg-emerald-700 py-3 text-white font-bold rounded transition">과제 제출하기</button>
                    <div id="hw-result-area" class="hidden mt-4 text-white"></div>
                </div>
            </div>

            <!-- 타임어택 퀴즈 -->
            <div id="prog-quiz-list" class="prog-content w-full bg-[#1e2430] p-6 rounded-xl">
                <h2 class="text-2xl font-bold text-orange-500 mb-4">타임어택 퀴즈</h2>
                <p class="text-gray-400 text-sm mb-6">정해진 기한(마감)과 시험 시간이 있는 퀴즈입니다. 타이머가 0이 되면 자동 제출됩니다.</p>
                <div id="student-quiz-list" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>
            </div>

            <!-- 타임어택 퀴즈 룸 -->
            <div id="prog-quiz-room" class="prog-content w-full max-w-4xl mx-auto bg-[#1e2430] p-6 rounded-xl shadow-2xl relative">
                <div class="flex justify-between items-center mb-6 border-b border-gray-700 pb-4 sticky top-0 bg-[#1e2430] z-10">
                    <h2 id="quiz-room-title" class="text-2xl font-bold text-white"></h2>
                    <div class="text-right">
                        <span class="text-sm text-gray-400 block mb-1">남은 시간</span>
                        <span id="quiz-timer" class="text-3xl font-black text-orange-400">00:00</span>
                    </div>
                </div>
                <div id="quiz-questions-container" class="space-y-6 mb-8 text-white"></div>
                <button onclick="submitQuizReal()" class="w-full bg-orange-600 hover:bg-orange-700 py-4 rounded-xl text-white font-bold text-lg shadow-lg">퀴즈 제출하기</button>
            </div>

            <!-- 모의고사 목록 -->
            <div id="prog-exam-list" class="prog-content w-full bg-[#1e2430] p-6 rounded-xl"><h2 class="text-2xl font-bold text-yellow-500 mb-4">모의고사 목록</h2><div id="student-exam-list" class="grid grid-cols-2 gap-4"></div></div>

            <!-- 모의고사 룸 -->
            <div id="prog-exam-room" class="prog-content w-full h-[85vh] relative">
                <div id="exam-prep-overlay" class="absolute inset-0 bg-[#1a1e29] z-40 flex items-center justify-center p-4">
                    <div class="bg-[#1e2430] p-8 rounded-xl w-full max-w-2xl"><h2 id="prep-exam-title" class="text-2xl font-bold text-white mb-4"></h2><p id="prep-objective-text" class="text-blue-200 mb-4"></p><input type="number" id="prep-target-score" placeholder="목표 점수" class="w-full bg-[#151922] p-4 text-white mb-4"><div id="prep-sections-board" class="mb-4"></div><button onclick="startExamReal()" class="w-full bg-indigo-600 py-4 text-white font-bold rounded hover:bg-indigo-700 transition">시작</button></div>
                </div>
                <div class="flex h-full gap-4">
                    <div id="pdf-viewer-section" class="w-2/3 bg-[#1e2430] p-4 flex flex-col relative"><div class="flex justify-between mb-2"><h2 id="room-exam-title-active" class="text-white font-bold"></h2><div><button onclick="toggleFullscreen()" id="btn-fullscreen" class="bg-gray-700 text-white px-2 py-1 mr-1">전체화면</button><button onclick="toggleDrawMode()" id="btn-draw" class="bg-blue-600 text-white px-2 py-1">필기</button><button onclick="clearCanvas()" id="btn-clear" class="hidden bg-red-600 text-white px-2 py-1">지우기</button></div></div><div id="pdf-render-wrapper" class="flex-grow bg-gray-600 overflow-auto"><div id="pdf-loading" class="text-white">로딩중...</div><div id="pdf-inner-container"></div></div></div>
                    <div class="w-1/3 bg-[#1e2430] p-4 flex flex-col"><div id="live-admin-controls" class="hidden mb-4"><input type="text" id="live-msg-input" class="w-full p-2 bg-[#151922] text-white"><button onclick="sendLiveMessage()" class="bg-red-600 px-4 text-white">전송</button></div><div id="timer-ui-container" class="mb-4"><span id="active-target-score" class="text-yellow-400"></span><div id="active-section-timer" class="text-4xl text-emerald-400 font-bold text-center my-2">00:00</div><button onclick="nextExamSection()" id="btn-next-section" class="w-full bg-blue-600 text-white py-2">다음 구간</button></div><div id="exam-omr-container" class="flex-grow overflow-auto mb-4"></div><div id="exam-result-report" class="hidden text-white flex-grow overflow-auto"></div><button id="btn-submit-exam" onclick="submitRealtimeExam()" class="hidden bg-indigo-600 text-white py-3 w-full font-bold transition hover:bg-indigo-700">제출</button><div id="report-action-buttons" class="hidden flex gap-2"><button onclick="closeProgram()" class="flex-1 bg-blue-600 py-3 text-white">나가기</button></div></div>
                </div>
            </div>

            <!-- 통합 관리 (원장님 전용) -->
            <div id="prog-admin" class="prog-content w-full mx-auto">
                <div class="bg-[#1e2430] p-6 rounded-xl border border-gray-800">
                    <div class="flex flex-wrap gap-2 mb-6 border-b border-gray-700 pb-4">
                        <button onclick="switchAdminTab('admin-users')" id="btn-admin-users" class="text-white font-bold bg-gray-800 px-4 py-2 rounded">학생 명단</button>
                        <button onclick="switchAdminTab('admin-knowledge')" id="btn-admin-knowledge" class="text-emerald-500 font-bold border border-emerald-600 px-4 py-2 rounded">자료학습</button>
                        <button onclick="switchAdminTab('admin-generator')" id="btn-admin-generator" class="text-yellow-500 font-bold border border-yellow-600 px-4 py-2 rounded">출제</button>
                        <button onclick="switchAdminTab('admin-exam')" id="btn-admin-exam" class="text-indigo-400 font-bold border border-indigo-600 px-4 py-2 rounded">모의고사</button>
                        <button onclick="switchAdminTab('admin-quiz')" id="btn-admin-quiz" class="text-orange-400 font-bold border border-orange-600 px-4 py-2 rounded">퀴즈 출제</button>
                        <button onclick="switchAdminTab('admin-lecture')" id="btn-admin-lecture" class="text-purple-400 font-bold border border-purple-600 px-4 py-2 rounded">강의</button>
                        <button onclick="switchAdminTab('admin-hw')" id="btn-admin-hw" class="text-blue-400 font-bold border border-blue-600 px-4 py-2 rounded">과제/공지</button>
                    </div>

                    <div id="admin-users" class="admin-tab-content grid grid-cols-4 gap-4">
                        <div class="col-span-1 space-y-4"><div class="bg-[#151922] p-4 rounded"><input type="text" id="add-school" placeholder="학교" class="w-full p-2 mb-2 bg-gray-800 text-white"><input type="text" id="add-grade" placeholder="학년" class="w-full p-2 mb-2 bg-gray-800 text-white"><input type="text" id="add-name" placeholder="이름" class="w-full p-2 mb-2 bg-gray-800 text-white"><button onclick="addSingleStudent()" class="w-full bg-emerald-600 py-2 text-white">추가</button></div></div>
                        <div class="col-span-1 bg-[#151922] p-4 rounded h-[600px] flex flex-col"><h3 class="text-white font-bold mb-2">명단 (<span id="total-student-count">0</span>명)</h3><button onclick="deleteSelectedStudents()" class="bg-red-600 text-white px-2 py-1 text-xs mb-2">선택 삭제</button><div id="admin-student-list" class="flex-grow overflow-y-auto space-y-1"></div></div>
                        <div class="col-span-2 bg-[#151922] p-6 border border-gray-700 rounded-lg h-[600px] flex flex-col">
                            <h3 class="text-lg lg:text-xl font-bold mb-4 text-white flex justify-between items-center border-b border-gray-700 pb-4">
                                <span id="stats-title-span"><i class="fa-solid fa-chart-line mr-2"></i>전체 누적 통계</span>
                                <button onclick="fetchReports()" class="bg-blue-600 hover:bg-blue-700 px-3 py-1.5 text-xs rounded text-white">전체보기</button>
                            </h3>
                            <div id="student-detail-container" class="flex-grow flex flex-col overflow-y-auto pr-2 text-white"></div>
                        </div>
                    </div>

                    <div id="admin-quiz" class="admin-tab-content grid grid-cols-2 gap-4">
                        <div class="bg-[#151922] p-6 rounded">
                            <h3 class="text-lg font-bold text-orange-400 mb-4">새 퀴즈 출제</h3>
                            <input type="text" id="qz-title" placeholder="퀴즈 제목" class="w-full p-3 bg-gray-800 text-white mb-2 rounded border border-gray-600">
                            <div class="flex gap-2 mb-2">
                                <div class="w-1/2">
                                    <label class="text-xs text-gray-400 mb-1 block">마감 일시 (기한)</label>
                                    <input type="datetime-local" id="qz-deadline" class="w-full p-3 bg-gray-800 text-white rounded border border-gray-600">
                                </div>
                                <div class="w-1/2">
                                    <label class="text-xs text-gray-400 mb-1 block">제한 시간 (분)</label>
                                    <input type="number" id="qz-limit" placeholder="예: 10" class="w-full p-3 bg-gray-800 text-white rounded border border-gray-600">
                                </div>
                            </div>
                            <div class="mt-4 border-t border-gray-700 pt-4">
                                <h4 class="text-sm font-bold text-white mb-2">문제 목록 (5지 선다형)</h4>
                                <div id="qz-questions-board" class="space-y-4 max-h-[400px] overflow-y-auto mb-4 pr-2"></div>
                                <button onclick="addQuizQuestionUI()" class="w-full bg-gray-700 hover:bg-gray-600 transition py-3 text-white rounded font-bold text-sm">+ 문제 1개 추가</button>
                            </div>
                            <button onclick="createQuiz()" class="w-full bg-orange-600 hover:bg-orange-700 py-3 text-white font-bold rounded mt-6 transition">퀴즈 오픈(배포)하기</button>
                        </div>
                        <div class="bg-[#151922] p-6 rounded h-[650px] flex flex-col">
                            <h3 class="text-lg font-bold text-white mb-4">등록된 퀴즈 목록</h3>
                            <div id="admin-quiz-list" class="flex-grow overflow-auto space-y-2"></div>
                        </div>
                    </div>

                    <div id="admin-knowledge" class="admin-tab-content grid grid-cols-2 gap-4">
                        <div class="bg-[#151922] p-6 rounded">
                            <h4 class="text-white font-bold mb-2">단일 자료 직접 등록</h4>
                            <input type="text" id="kb-title" placeholder="자료 제목 (비워두면 파일명 자동등록)" class="w-full p-2 bg-gray-800 text-white mb-2">
                            <textarea id="kb-content" class="w-full h-24 bg-gray-800 text-white mb-2" placeholder="직접 내용을 입력하거나, 아래에서 파일을 선택하면 AI가 요약합니다."></textarea>
                            <input type="file" id="kb-files" multiple onchange="handleFileSelect(event, kbFiles, 'kb-files-visual')" class="text-white mb-2">
                            <div id="kb-files-visual" class="mb-2"></div>
                            <button id="btn-knowledge" onclick="uploadKnowledge()" class="w-full bg-emerald-600 hover:bg-emerald-700 py-3 text-white mt-2 transition font-bold shadow-lg">저장 및 학습</button>
                            
                            <h4 class="text-emerald-400 font-bold mb-2 mt-6 pt-4 border-t border-gray-700">⚡ 파일 대량 일괄 등록 (PDF, 이미지)</h4>
                            <p class="text-xs text-gray-400 mb-2">여러 개의 파일을 한 번에 선택하세요. 파일명이 제목으로 자동 지정되며, AI가 스스로 읽고 각각 저장합니다.</p>
                            <input type="file" id="kb-bulk-files" multiple accept=".pdf, image/*" class="w-full text-white mb-2">
                            <button onclick="uploadKnowledgeBulk()" class="w-full bg-blue-600 hover:bg-blue-700 py-3 text-white font-bold rounded mt-2 transition shadow-lg">여러 파일 한 번에 싹 다 넣기</button>
                        </div>
                        <div class="bg-[#151922] p-6 rounded h-[600px] flex flex-col">
                            <h3 class="text-lg font-bold text-emerald-400 mb-4 border-b border-gray-700 pb-2"><i class="fa-solid fa-list mr-2"></i>학습된 자료 목록</h3>
                            <div id="admin-kb-view-list" class="flex-grow overflow-y-auto text-white space-y-2"></div>
                        </div>
                    </div>

                    <div id="admin-generator" class="admin-tab-content grid grid-cols-1 lg:grid-cols-2 gap-6">
                        <div class="bg-[#151922] p-6 rounded flex flex-col h-[800px] border border-gray-700 relative">
                            <h3 class="text-xl font-bold mb-4 text-white"><i class="fa-solid fa-wand-magic-sparkles text-yellow-400 mr-2"></i>정밀 문제 출제 엔진</h3>
                            <input type="text" id="gen-title" placeholder="출제할 문제집의 제목을 입력하세요" class="w-full bg-[#1e2430] border border-blue-500 p-3 rounded-lg text-white mb-4 outline-none focus:ring-2 focus:ring-blue-500 transition shadow-lg">

                            <div class="bg-[#1e2430] p-4 rounded border border-gray-700 mb-4">
                                <div class="flex flex-wrap gap-3 text-sm text-white" id="gen-types">
                                    <label><input type="checkbox" value="5지 선다형" checked> 5지 선다</label>
                                    <label><input type="checkbox" value="2지 선다형"> 2지 선다</label>
                                    <label><input type="checkbox" value="O/X 문제"> O/X</label>
                                    <label><input type="checkbox" value="단답형"> 단답형</label>
                                    <label><input type="checkbox" value="서술형"> 서술형</label>
                                </div>
                            </div>
                            <div class="grid grid-cols-5 gap-2 mb-4 text-center">
                                <div><label class="text-xs text-red-400 block mb-1 font-bold">킬러</label><input type="number" id="c-killer" value="0" min="0" class="w-full bg-[#1e2430] p-2 rounded text-white outline-none border border-gray-600 text-center"></div>
                                <div><label class="text-xs text-orange-400 block mb-1 font-bold">준킬러</label><input type="number" id="c-semi" value="0" min="0" class="w-full bg-[#1e2430] p-2 rounded text-white outline-none border border-gray-600 text-center"></div>
                                <div><label class="text-xs text-yellow-400 block mb-1 font-bold">상</label><input type="number" id="c-high" value="1" min="0" class="w-full bg-[#1e2430] p-2 rounded text-white outline-none border border-gray-600 text-center"></div>
                                <div><label class="text-xs text-emerald-400 block mb-1 font-bold">중</label><input type="number" id="c-mid" value="2" min="0" class="w-full bg-[#1e2430] p-2 rounded text-white outline-none border border-gray-600 text-center"></div>
                                <div><label class="text-xs text-blue-400 block mb-1 font-bold">하</label><input type="number" id="c-low" value="0" min="0" class="w-full bg-[#1e2430] p-2 rounded text-white outline-none border border-gray-600 text-center"></div>
                            </div>

                            <div class="flex justify-between items-end mb-2">
                                <label class="text-white font-bold text-sm">기준 지문 입력</label>
                                <button onclick="openKnowledgeImportModal()" class="text-blue-400 hover:text-blue-300 font-bold text-sm transition bg-blue-900/30 px-3 py-1 rounded"><i class="fa-solid fa-file-import mr-1"></i>자료학습 데이터 가져오기</button>
                            </div>
                            <textarea id="gen-text" class="w-full h-24 bg-[#1e2430] border border-gray-600 p-3 rounded text-white mb-4 outline-none" placeholder="직접 기준 지문을 입력하거나 위 버튼을 눌러 기존 자료를 불러오세요."></textarea>
                            
                            <input type="file" id="gen-files" multiple accept=".pdf, image/*" class="text-white mb-2" onchange="handleFileSelect(event, genFiles, 'gen-files-visual')">
                            <div id="gen-files-visual" class="flex flex-wrap gap-2 mb-4"></div>
                            
                            <div class="flex gap-2 mb-4">
                                <button onclick="analyzeTextStream()" class="w-1/3 bg-emerald-600 hover:bg-emerald-700 py-3 text-white font-bold rounded transition text-sm">지문 분석/요약</button>
                                <button onclick="generateStreamQuestions()" class="w-2/3 bg-yellow-600 hover:bg-yellow-700 py-3 text-white font-bold rounded transition">AI 정밀 출제</button>
                            </div>
                            
                            <div id="gen-result-area" class="hidden flex-grow flex flex-col">
                                <textarea id="gen-result-text" class="flex-grow bg-[#1e2430] text-white p-3 mb-2 rounded border border-gray-600 outline-none text-xs font-mono"></textarea>
                                <div class="flex gap-2">
                                    <button id="btn-save-gen" onclick="saveGeneratedQuestion()" class="flex-1 bg-emerald-600 hover:bg-emerald-700 py-2 text-white font-bold rounded text-xs transition">보관함 저장</button>
                                    <button onclick="deployFromGenerator()" class="flex-1 bg-indigo-600 hover:bg-indigo-700 py-2 text-white font-bold rounded text-xs transition">방 개설하기</button>
                                    <button onclick="printGeneratedPDF()" class="bg-gray-200 hover:bg-white py-2 px-4 text-black font-bold rounded text-xs transition">인쇄</button>
                                </div>
                            </div>
                        </div>
                        <div class="bg-[#151922] p-6 rounded h-[800px] flex flex-col"><div id="admin-questions-list" class="flex-grow overflow-auto text-white space-y-2"></div></div>
                    </div>

                    <div id="admin-exam" class="admin-tab-content grid grid-cols-2 gap-4">
                        <div class="bg-[#151922] p-6 rounded">
                            <input type="text" id="rt-title" placeholder="시험 제목" class="w-full p-2 bg-gray-800 text-white mb-2"><input type="text" id="rt-objective" placeholder="공지사항" class="w-full p-2 bg-gray-800 text-white mb-4">
                            <label class="text-white block mb-2"><input type="checkbox" id="rt-student-all" checked onchange="toggleExamStudents()"> 전체 학생</label><div id="rt-student-list-container" class="hidden bg-gray-800 p-2 h-24 overflow-auto text-white mb-4"></div>
                            <div class="flex gap-2 mb-2"><input type="text" id="sec-name" class="w-1/2 p-2 bg-gray-800 text-white" placeholder="구간명"><input type="number" id="sec-time" class="w-1/4 p-2 bg-gray-800 text-white" placeholder="분"><button onclick="addAdminSection()" class="bg-yellow-600 text-white px-4">추가</button></div><div id="admin-section-board" class="mb-4 text-white flex flex-wrap"></div>
                            <input type="file" id="rt-pdf" accept=".pdf, image/*" class="mb-4 text-white">
                            <input type="text" id="rt-video" placeholder="해설강의 URL" class="w-full p-2 bg-gray-800 text-white mb-2"><textarea id="rt-exp" class="w-full p-2 bg-gray-800 text-white h-24 mb-4" placeholder="상세 해설지"></textarea>
                            <div class="flex gap-2 mb-2"><input type="number" id="rt-qcount" class="w-2/3 p-2 bg-gray-800 text-white" placeholder="문항수 (생략가능)"><button onclick="buildAdminOMR()" class="w-1/3 bg-gray-600 text-white">OMR 생성</button></div><div id="admin-omr-board" class="h-32 overflow-auto mb-4 text-white"></div>
                            <button onclick="setRealtimeExam()" class="w-full bg-indigo-600 py-3 text-white font-bold">오픈하기</button>
                        </div>
                        <div class="bg-[#151922] p-6 rounded h-[700px] flex flex-col"><div id="admin-exam-list" class="flex-grow overflow-auto space-y-2"></div></div>
                    </div>

                    <div id="admin-lecture" class="admin-tab-content grid grid-cols-2 gap-4">
                        <div class="bg-[#151922] p-6 rounded"><input type="text" id="lec-title" class="w-full p-2 mb-2 bg-gray-800 text-white"><input type="text" id="lec-url" class="w-full p-2 mb-2 bg-gray-800 text-white"><button onclick="createLecture()" class="w-full bg-purple-600 py-2 text-white">등록</button></div>
                        <div id="admin-lecture-list" class="bg-[#151922] p-6 rounded h-[500px] overflow-auto text-white"></div>
                    </div>

                    <div id="admin-hw" class="admin-tab-content grid grid-cols-2 gap-4">
                        <div class="bg-[#151922] p-6 rounded">
                            <h3 class="text-white font-bold mb-4">과제/정답 배포</h3>
                            <input type="text" id="hw-title" placeholder="과제명" class="w-full p-2 mb-2 bg-gray-800 text-white rounded outline-none border border-gray-600 focus:border-emerald-500">
                            <input type="file" id="hw-ans-file" class="mb-2 text-white" onchange="handleFileSelect(event, hwFilesAdmin, 'hw-ans-file-visual')">
                            <div id="hw-ans-file-visual" class="flex flex-wrap gap-2 mb-4"></div>
                            <button onclick="createHomework()" class="w-full bg-emerald-600 hover:bg-emerald-700 py-2 text-white font-bold rounded transition shadow-lg">배포하기</button>
                            <div id="admin-hw-view-list" class="mt-4 h-64 overflow-auto text-white space-y-2"></div>
                        </div>
                        <div class="bg-[#151922] p-6 rounded">
                            <h3 class="text-white font-bold mb-4">공지사항 등록</h3>
                            <input type="text" id="bd-title-admin" placeholder="공지제목" class="w-full p-2 mb-2 bg-gray-800 text-white rounded outline-none border border-gray-600 focus:border-blue-500">
                            <textarea id="bd-desc-admin" placeholder="내용을 입력하세요" class="w-full p-2 mb-2 bg-gray-800 text-white rounded outline-none border border-gray-600 focus:border-blue-500 h-24"></textarea>
                            <input type="file" id="bd-file-admin" class="mb-2 text-white" onchange="handleFileSelect(event, bdFilesAdmin, 'bd-file-admin-visual')">
                            <div id="bd-file-admin-visual" class="flex flex-wrap gap-2 mb-4"></div>
                            <button onclick="createBoardAdmin()" class="w-full bg-gray-600 hover:bg-gray-500 py-2 text-white font-bold rounded transition shadow-lg">공지 등록</button>
                            <div id="admin-board-view-list" class="mt-4 h-64 overflow-auto text-white space-y-2"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- 모달창 및 스크립트 연결부 유지됨 (다음 복사본에서 이어짐) -->
