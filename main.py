<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>로지에듀 최준용 국어 - AI 스마트 플랫폼</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
    <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
        body { font-family: 'Pretendard', sans-serif; background-color: #1a1e29; color: #ffffff; scroll-behavior: smooth; }
        .fade-in { animation: fadeIn 0.4s ease-out forwards; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #1a1e29; }
        ::-webkit-scrollbar-thumb { background: #3b82f6; border-radius: 4px; }
        .modal-bg { background-color: rgba(15, 23, 42, 0.85); backdrop-filter: blur(5px); }
        .app-card:hover { transform: translateY(-8px); box-shadow: 0 20px 25px -5px rgba(59, 130, 246, 0.2); border-color: #3b82f6; }
        .admin-tab-content { display: none; }
        .admin-tab-content.active { display: block; animation: fadeIn 0.3s ease-out forwards; }
    </style>
</head>
<body class="min-h-screen flex flex-col">

    <nav class="fixed top-0 w-full flex justify-between items-center px-8 py-6 z-50 bg-[#1a1e29]/90 border-b border-gray-800">
        <div class="text-2xl font-black text-white cursor-pointer" onclick="goHome()">로지에듀<span class="text-blue-500">*</span></div>
        <div class="flex items-center gap-4 text-sm font-medium">
            <div id="auth-nav">
                <button onclick="showModal('login')" class="hover:text-blue-400 transition"><i class="fa-solid fa-lock mr-1"></i> 로그인</button>
            </div>
            <div id="user-nav" class="hidden items-center gap-4">
                <span id="header-user-info" class="text-blue-400 font-bold text-lg"></span>
                <button onclick="goToDashboard()" class="text-white hover:text-blue-400 font-bold border border-gray-600 px-3 py-1 rounded">학습실 입장</button>
                <button onclick="logout()" class="hover:text-white underline">로그아웃</button>
            </div>
        </div>
    </nav>

    <div id="home-view" class="w-full flex-grow flex items-center justify-center min-h-screen pt-20">
        <div class="text-center z-10 fade-in">
            <h1 class="text-5xl font-bold text-white mb-6">우리는 언제나<br><span class="text-blue-500">'올바름'</span>을 찾아냈습니다</h1>
            <button onclick="showModal('login')" class="bg-blue-600 hover:bg-blue-700 text-white px-10 py-4 rounded font-bold text-lg">스마트 학습실 입장하기</button>
        </div>
    </div>

    <!-- 대시보드 뷰 -->
    <div id="dashboard-screen" class="hidden flex-grow pt-28 px-4 max-w-7xl mx-auto w-full fade-in pb-12">
        <div id="dashboard-home">
            <h2 class="text-3xl font-bold mb-8">스마트 학습실</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                <div onclick="openProgram('chat')" class="bg-[#151922] border border-gray-700 p-8 rounded-2xl cursor-pointer app-card">
                    <div class="w-14 h-14 bg-blue-600 text-white rounded-xl flex items-center justify-center text-2xl mb-6"><i class="fa-solid fa-robot"></i></div>
                    <h3 class="text-xl font-bold mb-2">24시간 AI 튜터</h3>
                    <p class="text-gray-400 text-sm">질의응답을 언제든 자유롭게 진행합니다.</p>
                </div>
                <div onclick="openProgram('omr')" class="bg-[#151922] border border-gray-700 p-8 rounded-2xl cursor-pointer app-card">
                    <div class="w-14 h-14 bg-indigo-600 text-white rounded-xl flex items-center justify-center text-2xl mb-6"><i class="fa-solid fa-check-double"></i></div>
                    <h3 class="text-xl font-bold mb-2">OMR 자동 채점</h3>
                    <p class="text-gray-400 text-sm">과제 정답을 마킹하고 채점받습니다.</p>
                </div>
                <div id="card-admin" onclick="openProgram('admin')" class="hidden bg-[#1e2430] border border-red-500 p-8 rounded-2xl cursor-pointer app-card flex-col items-start relative">
                    <div class="w-14 h-14 bg-red-600 text-white rounded-xl flex items-center justify-center text-2xl mb-6"><i class="fa-solid fa-gears"></i></div>
                    <h3 class="text-xl font-bold mb-2 text-white">시스템 관리</h3>
                    <p class="text-red-300 text-sm">문제 출제 및 통합 시스템을 관리합니다.</p>
                </div>
            </div>
        </div>

        <div id="program-view" class="hidden fade-in">
            <button onclick="closeProgram()" class="mb-8 text-gray-400 hover:text-white font-bold flex items-center gap-2"><i class="fa-solid fa-arrow-left"></i> 돌아가기</button>

            <!-- 💬 AI 튜터 -->
            <div id="prog-chat" class="prog-content hidden w-full max-w-6xl mx-auto bg-[#1e2430] p-8 rounded-xl border border-gray-800 shadow-2xl">
                <h2 class="text-3xl font-bold text-blue-400 mb-6"><i class="fa-solid fa-robot mr-2"></i>AI 튜터 국최</h2>
                <div id="chat-history" class="h-[65vh] overflow-y-auto mb-6 space-y-6 bg-[#151922] p-6 rounded-xl border border-gray-700 text-lg leading-loose"></div>
                <div class="flex gap-3">
                    <input type="text" id="chat-input" class="flex-grow bg-[#151922] border border-gray-600 text-white p-4 rounded-xl text-lg focus:border-blue-500 outline-none" placeholder="궁금한 점을 자세히 질문해 보세요..." onkeypress="if(event.key==='Enter') sendChat()">
                    <button onclick="sendChat()" class="bg-blue-600 hover:bg-blue-700 px-8 rounded-xl text-white text-xl transition"><i class="fa-solid fa-paper-plane"></i></button>
                </div>
            </div>

            <!-- 💯 OMR -->
            <div id="prog-omr" class="prog-content hidden w-full max-w-4xl mx-auto bg-[#1e2430] p-6 rounded-xl border border-gray-800">
                <h2 class="text-2xl font-bold text-indigo-400 mb-6">OMR 자동 채점</h2>
                <input type="text" id="omr-task" placeholder="과제명" class="w-full bg-[#151922] border border-gray-600 text-white p-4 rounded mb-4">
                <div class="grid grid-cols-5 gap-3 mb-6">
                    <input type="text" placeholder="1" class="w-full bg-[#151922] border border-gray-600 p-4 text-center rounded omr-ans">
                    <input type="text" placeholder="2" class="w-full bg-[#151922] border border-gray-600 p-4 text-center rounded omr-ans">
                    <input type="text" placeholder="3" class="w-full bg-[#151922] border border-gray-600 p-4 text-center rounded omr-ans">
                    <input type="text" placeholder="4" class="w-full bg-[#151922] border border-gray-600 p-4 text-center rounded omr-ans">
                    <input type="text" placeholder="5" class="w-full bg-[#151922] border border-gray-600 p-4 text-center rounded omr-ans">
                </div>
                <button onclick="submitOMR()" class="w-full bg-indigo-600 py-4 font-bold rounded-lg text-white">채점 제출</button>
                <div id="omr-result" class="mt-6"></div>
            </div>

            <!-- ⚙️ 관리자 모드 -->
            <div id="prog-admin" class="prog-content hidden w-full max-w-6xl mx-auto">
                <div class="bg-[#1e2430] border border-gray-800 p-8 rounded-xl shadow-xl">
                    <div class="flex gap-4 border-b border-gray-700 pb-4 mb-8">
                        <button onclick="switchAdminTab('admin-users')" id="btn-admin-users" class="text-white font-bold bg-gray-800 px-4 py-2 rounded">👥 학생 및 장부</button>
                        <button onclick="switchAdminTab('admin-knowledge')" id="btn-admin-knowledge" class="text-emerald-500 font-bold border border-emerald-600/50 px-4 py-2 rounded">📚 AI 자료 학습</button>
                        <button onclick="switchAdminTab('admin-generator')" id="btn-admin-generator" class="text-yellow-500 font-bold border border-yellow-600/50 px-4 py-2 rounded">🪄 정밀 문제 출제</button>
                    </div>

                    <!-- 학생 관리 탭 -->
                    <div id="admin-users" class="admin-tab-content active text-gray-300">
                        <div class="grid grid-cols-2 gap-8">
                            <div class="bg-[#151922] p-6 border border-gray-700 rounded-lg">
                                <h3 class="text-lg font-bold mb-4 text-white">엑셀 일괄 등록 (학교/학년/이름)</h3>
                                <input type="file" id="excel-file" accept=".xlsx, .xls, .csv" class="mb-4 text-sm text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded file:bg-gray-700 file:text-white">
                                <button onclick="uploadExcel()" class="bg-blue-600 text-white px-4 py-2 rounded w-full font-bold">엑셀 데이터 업로드</button>
                                <p class="text-xs text-gray-500 mt-2">* 엑셀 1행 영문 제목: school, grade, name</p>
                            </div>
                            <div class="bg-[#151922] p-6 border border-gray-700 rounded-lg h-64 overflow-y-auto">
                                <h3 class="text-lg font-bold mb-4 text-white">성적 및 과제 장부</h3>
                                <button onclick="fetchReports()" class="bg-gray-700 px-3 py-1 rounded mb-4 text-sm">새로고침</button>
                                <div id="report-list" class="text-sm space-y-2"></div>
                            </div>
                        </div>
                    </div>

                    <!-- AI 지식베이스(학습) 탭 -->
                    <div id="admin-knowledge" class="admin-tab-content text-gray-300">
                        <div class="bg-[#151922] p-6 border border-gray-700 rounded-lg">
                            <h3 class="text-lg font-bold mb-2 text-emerald-400"><i class="fa-solid fa-brain mr-2"></i>원장님 자료 AI 학습시키기</h3>
                            <p class="text-sm text-gray-400 mb-4">여기에 올린 자료를 AI 튜터가 최우선으로 검색하여 답변합니다.</p>
                            <input type="text" id="kb-title" placeholder="자료 제목 (예: 미강고 1단원 핵심 요약)" class="w-full bg-[#1e2430] border border-gray-600 p-3 rounded text-white mb-3">
                            <textarea id="kb-content" class="w-full h-40 bg-[#1e2430] border border-gray-600 p-3 rounded text-white mb-4" placeholder="AI가 학습할 내용을 붙여넣으세요."></textarea>
                            <button onclick="uploadKnowledge()" class="bg-emerald-600 text-white font-bold py-3 rounded w-full">AI 두뇌에 저장</button>
                        </div>
                    </div>

                    <!-- 네이티브 문제 출제기 -->
                    <div id="admin-generator" class="admin-tab-content">
                        <div class="bg-[#151922] border border-gray-700 p-6 rounded-lg">
                            <h3 class="text-xl font-bold mb-6 text-white"><i class="fa-solid fa-wand-magic-sparkles text-yellow-400 mr-2"></i>AI 정밀 문제 생성 엔진</h3>
                            
                            <div class="grid grid-cols-2 gap-4 mb-4">
                                <div><label class="text-sm font-bold text-gray-400 block mb-2">시험 제목</label><input type="text" id="gen-title" class="w-full bg-[#1e2430] border border-gray-600 p-3 rounded text-white" placeholder="예: 미강고 대비"></div>
                                <div><label class="text-sm font-bold text-gray-400 block mb-2">대상 그룹</label><input type="text" id="gen-target" class="w-full bg-[#1e2430] border border-gray-600 p-3 rounded text-white" value="전체"></div>
                            </div>
                            
                            <div class="bg-[#1e2430] p-4 rounded border border-gray-700 mb-4">
                                <label class="text-sm font-bold text-gray-300 block mb-2">📌 문제 유형 다중 선택</label>
                                <div class="flex flex-wrap gap-4 text-sm" id="gen-types">
                                    <label><input type="checkbox" value="5지 선다형" checked> 5지 선다형</label>
                                    <label><input type="checkbox" value="헷갈리는 선지 2지 선다형"> 2지 선다형</label>
                                    <label><input type="checkbox" value="O/X 문제"> O/X 문제</label>
                                    <label><input type="checkbox" value="단답형"> 단답형</label>
                                    <label><input type="checkbox" value="서술형"> 서술형</label>
                                </div>
                            </div>

                            <div class="grid grid-cols-5 gap-2 mb-4">
                                <div><label class="text-xs font-bold text-red-400 block mb-1">🔥킬러 문항 수</label><input type="number" id="c-killer" value="0" min="0" class="w-full bg-[#1e2430] border border-gray-600 p-2 rounded text-white"></div>
                                <div><label class="text-xs font-bold text-orange-400 block mb-1">⚡준킬러 문항 수</label><input type="number" id="c-semi" value="0" min="0" class="w-full bg-[#1e2430] border border-gray-600 p-2 rounded text-white"></div>
                                <div><label class="text-xs font-bold text-yellow-400 block mb-1">📈난이도 상</label><input type="number" id="c-high" value="1" min="0" class="w-full bg-[#1e2430] border border-gray-600 p-2 rounded text-white"></div>
                                <div><label class="text-xs font-bold text-emerald-400 block mb-1">📊난이도 중</label><input type="number" id="c-mid" value="2" min="0" class="w-full bg-[#1e2430] border border-gray-600 p-2 rounded text-white"></div>
                                <div><label class="text-xs font-bold text-blue-400 block mb-1">📉난이도 하</label><input type="number" id="c-low" value="0" min="0" class="w-full bg-[#1e2430] border border-gray-600 p-2 rounded text-white"></div>
                            </div>
                            
                            <div class="mb-4">
                                <label class="text-sm font-bold text-gray-400 block mb-2">기준 텍스트</label>
                                <textarea id="gen-text" class="w-full h-32 bg-[#1e2430] border border-gray-600 p-3 rounded text-white" placeholder="지문이나 기출문제를 텍스트로 입력하세요..."></textarea>
                            </div>

                            <!-- 💡 복구된 PDF 및 이미지 파일 첨부 (업로드) 영역 -->
                            <div class="mb-6">
                                <label class="text-sm font-bold text-gray-400 block mb-2">자료 첨부 파일 (PDF 또는 이미지)</label>
                                <input type="file" id="gen-file" multiple accept=".pdf, .jpg, .jpeg, .png" class="w-full text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-bold file:bg-gray-700 file:text-white hover:file:bg-gray-600 transition cursor-pointer">
                            </div>

                            <button onclick="generateQuestions()" id="btn-generate" class="w-full bg-yellow-600 hover:bg-yellow-700 text-white font-bold py-4 rounded-lg transition mb-6">🚀 조건에 맞춘 AI 정밀 출제 시작</button>

                            <div id="gen-result-area" class="hidden">
                                <div class="flex justify-between items-center mb-3">
                                    <h4 class="text-lg font-bold text-emerald-400">생성된 문제 (편집 가능)</h4>
                                    <!-- PDF 인쇄 -->
                                    <button onclick="printPDF()" class="bg-gray-200 text-black px-4 py-2 rounded font-bold hover:bg-white text-sm"><i class="fa-solid fa-file-pdf mr-1"></i> PDF 인쇄</button>
                                </div>
                                <textarea id="gen-result-text" class="w-full h-96 bg-[#1e2430] border border-gray-600 text-white p-4 rounded mb-4 font-mono text-sm leading-relaxed"></textarea>
                                <button onclick="deployGeneratedExam()" id="btn-deploy" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-4 rounded-lg transition">✅ 시험장 배포 및 AI 학습시키기</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- 로그인 모달 -->
    <div id="auth-modal" class="hidden fixed inset-0 z-[100] modal-bg flex items-center justify-center p-4">
        <div class="bg-[#1e2430] border border-gray-700 p-8 rounded-2xl w-full max-w-md shadow-2xl">
            <button onclick="closeModal()" class="float-right text-gray-400 hover:text-white text-2xl transition"><i class="fa-solid fa-xmark"></i></button>
            <h2 id="modal-title" class="text-3xl font-black mb-8 text-center tracking-wide text-white">로그인</h2>
            <div id="login-form" class="space-y-4">
                <div class="bg-[#151922] p-4 rounded-xl border border-gray-700">
                    <p class="text-xs text-blue-400 mb-3 font-bold">* 학생은 모두 기재, 원장님은 스텔스 키만 입력하면 프리패스</p>
                    <input type="text" id="login-school" placeholder="학교 (예: 미강고)" class="w-full bg-transparent border-b border-gray-600 p-3 text-white focus:outline-none focus:border-blue-500 text-lg mb-2">
                    <input type="text" id="login-grade" placeholder="학년 (예: 1학년)" class="w-full bg-transparent border-b border-gray-600 p-3 text-white focus:outline-none focus:border-blue-500 text-lg mb-2">
                    <input type="text" id="login-name" placeholder="이름 (원장님은 본인 이름)" class="w-full bg-transparent border-b border-gray-600 p-3 text-white focus:outline-none focus:border-blue-500 text-lg">
                </div>
                <input type="password" id="login-pw" placeholder="원장님 전용 스텔스 키 (학생은 비움)" class="w-full bg-[#151922] border border-gray-700 p-4 rounded-xl text-white text-lg focus:outline-none focus:border-red-500">
                <button id="login-btn" onclick="login()" class="w-full bg-blue-600 hover:bg-blue-700 py-4 rounded-xl text-white font-bold text-xl transition mt-4">입장하기</button>
            </div>
        </div>
    </div>

    <script>
        const API_URL = "https://korean-ai-tutor.onrender.com"; 
        let currentUser = null;

        window.addEventListener('DOMContentLoaded', () => { 
            fetch(`${API_URL}/api/health`).catch(() => console.log('Waking up server...')); 
            const savedUser = sessionStorage.getItem('logyedu_user');
            if (savedUser) {
                currentUser = JSON.parse(savedUser);
                document.getElementById('auth-nav').classList.add('hidden');
                document.getElementById('user-nav').classList.remove('hidden'); document.getElementById('user-nav').classList.add('flex');
                document.getElementById('header-user-info').innerText = currentUser.isAdmin ? '원장님' : `${currentUser.school} ${currentUser.grade} ${currentUser.name}`;
                if(currentUser.isAdmin) { document.getElementById('card-admin').classList.remove('hidden'); document.getElementById('card-admin').classList.add('flex'); }
            }
        });

        function showModal(type) { document.getElementById('auth-modal').classList.remove('hidden'); }
        function closeModal() { document.getElementById('auth-modal').classList.add('hidden'); }
        function goHome() { document.getElementById('dashboard-screen').classList.add('hidden'); document.getElementById('home-view').classList.remove('hidden'); }
        function goToDashboard() {
            if(!currentUser) return showModal('login');
            document.getElementById('home-view').classList.add('hidden'); document.getElementById('dashboard-screen').classList.remove('hidden'); closeProgram();
        }
        function openProgram(progId) {
            document.getElementById('dashboard-home').classList.add('hidden'); document.getElementById('program-view').classList.remove('hidden');
            document.querySelectorAll('.prog-content').forEach(el => el.classList.add('hidden'));
            document.getElementById('prog-' + progId).classList.remove('hidden');
            if (progId === 'admin') switchAdminTab('admin-users');
        }
        function closeProgram() { document.getElementById('program-view').classList.add('hidden'); document.getElementById('dashboard-home').classList.remove('hidden'); }
        
        function switchAdminTab(tabId) {
            ['admin-users', 'admin-knowledge', 'admin-generator'].forEach(id => {
                document.getElementById('btn-'+id).classList.replace('bg-gray-800', 'border');
                document.getElementById(id).classList.remove('active');
            });
            document.getElementById('btn-'+tabId).classList.replace('border', 'bg-gray-800');
            document.getElementById(tabId).classList.add('active');
            if(tabId === 'admin-users') fetchReports();
        }

        async function login() {
            const sch = document.getElementById('login-school').value; const gr = document.getElementById('login-grade').value; 
            const nm = document.getElementById('login-name').value; const pw = document.getElementById('login-pw').value;
            
            if(!nm) return alert("이름을 입력해주세요.");

            try {
                const res = await fetch(`${API_URL}/api/auth`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ school: sch, grade: gr, student_name: nm, admin_password: pw }) });
                const data = await res.json();
                if (data.success) {
                    currentUser = { school: sch, grade: gr, name: nm, isAdmin: data.is_admin };
                    sessionStorage.setItem('logyedu_user', JSON.stringify(currentUser)); 
                    closeModal(); location.reload();
                } else alert(data.detail);
            } catch(e) { alert("서버 연결 실패"); }
        }
        function logout() { sessionStorage.removeItem('logyedu_user'); currentUser = null; location.reload(); }

        async function sendChat() {
            const input = document.getElementById('chat-input');
            const prompt = input.value; if(!prompt) return;
            const history = document.getElementById('chat-history');
            history.innerHTML += `<div class="text-right mb-6"><span class="bg-blue-600 px-5 py-3 rounded-2xl text-white text-lg inline-block shadow-lg">${prompt}</span></div>`;
            input.value = '';
            
            const loadId = "load-" + Date.now();
            history.innerHTML += `<div id="${loadId}" class="text-left mb-6 fade-in"><span class="bg-[#2a3441] px-5 py-4 rounded-2xl text-blue-300 text-lg font-bold inline-block border border-gray-600" id="${loadId}-text"><i class="fa-solid fa-spinner fa-spin mr-2"></i>AI 국최가 답변을 고민 중입니다...</span></div>`;
            history.scrollTop = history.scrollHeight;

            const msgs = ["<i class='fa-solid fa-spinner fa-spin mr-2'></i>AI 국최가 답변을 고민 중입니다...", "<i class='fa-solid fa-magnifying-glass mr-2'></i>원장님의 수업 자료를 탐색 중입니다...", "<i class='fa-solid fa-lightbulb text-yellow-400 mr-2'></i>정답에 근접했습니다!"];
            let mIdx = 0;
            const loadInt = setInterval(() => { mIdx = (mIdx+1)%3; const el = document.getElementById(loadId+'-text'); if(el) el.innerHTML = msgs[mIdx]; }, 2000);

            try {
                const res = await fetch(`${API_URL}/api/chat`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ school: currentUser.school, grade: currentUser.grade, student_name: currentUser.name, prompt: prompt }) });
                const data = await res.json();
                clearInterval(loadInt); document.getElementById(loadId).remove();
                
                if(data.success) {
                    history.innerHTML += `<div class="text-left mb-6 fade-in"><span class="bg-gray-800 px-6 py-5 rounded-2xl text-white text-lg inline-block leading-loose shadow-lg border border-gray-700"><span class="block mb-3 font-bold text-blue-400 text-xl"><i class="fa-solid fa-robot mr-2"></i>국최</span>${data.reply.replace(/\n/g, '<br>')}</span></div>`;
                } else {
                    history.innerHTML += `<div class="text-left mb-6 fade-in"><span class="bg-red-900/30 px-6 py-5 rounded-2xl text-red-200 text-lg inline-block border border-red-800"><i class="fa-solid fa-triangle-exclamation mr-2"></i>${data.reply}</span></div>`;
                }
            } catch(e) { clearInterval(loadInt); document.getElementById(loadId).remove(); history.innerHTML += `<div class="text-red-400">오류 발생</div>`; }
            history.scrollTop = history.scrollHeight;
        }

        async function submitOMR() {
            const task = document.getElementById('omr-task').value;
            const answers = Array.from(document.querySelectorAll('.omr-ans')).map(i => i.value);
            try {
                const res = await fetch(`${API_URL}/api/omr/submit`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ school: currentUser.school, grade: currentUser.grade, student_name: currentUser.name, task_name: task, answers: answers }) });
                const data = await res.json();
                document.getElementById('omr-result').innerHTML = `<p class="text-indigo-400 font-bold text-xl">점수: ${data.score}점</p>`;
            } catch(e) { alert("서버 오류"); }
        }

        async function generateQuestions() {
            if (!document.getElementById('gen-title').value) return alert("시험 제목을 적어주세요.");
            const btn = document.getElementById('btn-generate');
            btn.disabled = true; btn.innerText = "AI 두뇌 정밀 가동 중... (약 20초 소요)";

            const selectedTypes = Array.from(document.querySelectorAll('#gen-types input:checked')).map(cb => cb.value).join(', ');

            const formData = new FormData();
            formData.append("q_mode", "신규 문제 창조");
            formData.append("q_style", "수능/내신형");
            formData.append("q_types", selectedTypes || "5지 선다형");
            formData.append("cnt_killer", document.getElementById('c-killer').value);
            formData.append("cnt_semi", document.getElementById('c-semi').value);
            formData.append("cnt_high", document.getElementById('c-high').value);
            formData.append("cnt_mid", document.getElementById('c-mid').value);
            formData.append("cnt_low", document.getElementById('c-low').value);
            formData.append("q_text", document.getElementById('gen-text').value);
            
            // 💡 파일 첨부 로직 (자바스크립트가 업로드된 파일을 백엔드로 전송)
            const files = document.getElementById('gen-file').files;
            for (let i = 0; i < files.length; i++) formData.append("files", files[i]);
            
            try {
                const res = await fetch(`${API_URL}/api/admin/generate`, { method: 'POST', body: formData });
                const data = await res.json();
                if (data.success) {
                    document.getElementById('gen-result-area').classList.remove('hidden');
                    document.getElementById('gen-result-text').value = data.result;
                    alert("출제가 완료되었습니다!");
                } else alert("오류: " + data.detail);
            } catch (e) { alert("서버 연결 실패"); }
            btn.disabled = false; btn.innerText = "🚀 조건에 맞춘 AI 정밀 출제 시작";
        }

        async function deployGeneratedExam() {
            const btn = document.getElementById('btn-deploy');
            btn.disabled = true; btn.innerText = "배포 및 학습 중...";
            try {
                const res = await fetch(`${API_URL}/api/admin/deploy_exam`, {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ title: document.getElementById('gen-title').value, target_group: document.getElementById('gen-target').value, raw_text: document.getElementById('gen-result-text').value })
                });
                const data = await res.json();
                if (data.success) alert("시험장 배포 및 AI 지식베이스 학습이 완료되었습니다!");
                else alert("배포 오류: " + data.detail);
            } catch (e) { alert("서버 오류"); }
            btn.disabled = false; btn.innerText = "✅ 온라인 시험장에 배포 및 AI 지식에 학습시키기";
        }

        function printPDF() {
            const text = document.getElementById('gen-result-text').value;
            const printWindow = window.open('', '', 'width=800,height=900');
            printWindow.document.write(`<html><head><title>문제 출력</title></head><body style="font-family: sans-serif; padding: 20px; line-height: 1.6;"><pre style="white-space: pre-wrap; font-size: 16px;">${text}</pre><script>window.print();<\/script></body></html>`);
            printWindow.document.close();
        }

        function uploadExcel() {
            const file = document.getElementById('excel-file').files[0];
            if(!file) return alert("파일을 선택하세요.");
            const reader = new FileReader();
            reader.onload = async function(e) {
                const data = new Uint8Array(e.target.result);
                const workbook = XLSX.read(data, {type: 'array'});
                const sheet = workbook.Sheets[workbook.SheetNames[0]];
                const jsonData = XLSX.utils.sheet_to_json(sheet);
                
                try {
                    const res = await fetch(`${API_URL}/api/admin/student/bulk`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({students: jsonData}) });
                    const rData = await res.json();
                    if(rData.success) alert("일괄 등록 성공!");
                } catch(err) { alert("업로드 실패"); }
            };
            reader.readAsArrayBuffer(file);
        }

        async function fetchReports() {
            try {
                const res = await fetch(`${API_URL}/api/admin/reports`);
                const data = await res.json();
                if(data.success) {
                    const el = document.getElementById('report-list'); el.innerHTML = '';
                    data.reports.forEach(r => {
                        el.innerHTML += `<div class="border-b border-gray-700 py-3"><span class="text-blue-400 font-bold text-lg mr-2">[${r.task_name}]</span> <span class="text-gray-300 text-lg">${r.school} ${r.grade} ${r.student_name}</span> - <span class="text-emerald-400 font-bold text-lg">${r.score}점</span></div>`;
                    });
                }
            } catch(e) {}
        }

        async function uploadKnowledge() {
            const t = document.getElementById('kb-title').value; const c = document.getElementById('kb-content').value;
            if(!t || !c) return alert("제목과 내용을 채워주세요.");
            try {
                const res = await fetch(`${API_URL}/api/admin/knowledge`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title: t, content: c}) });
                const data = await res.json();
                if(data.success) { alert("AI가 내용을 학습했습니다."); document.getElementById('kb-title').value=''; document.getElementById('kb-content').value=''; }
            } catch(e) { alert("학습 실패"); }
        }
    </script>
</body>
</html>
