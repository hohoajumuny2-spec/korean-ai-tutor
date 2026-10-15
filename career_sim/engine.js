/* ─────────────────────────────────────────────────────────
 * 진로 시뮬레이션 엔진 — "그때 그 선택"
 *
 *  · 같은 (학생 정보, 시드, 선택 기록)을 넣으면 언제나 같은 인생이 나온다.
 *    그래서 끝난 뒤 한 선택만 바꿔 다시 돌려 보면, '그 선택 하나'가 만든 차이를
 *    그대로 보여 줄 수 있다(후회 분석).
 *  · 운(난수)은 시점마다 따로 뽑는다. 앞에서 다른 선택을 해도 그 시점의 운은
 *    같으므로, 결과 차이는 운이 아니라 선택에서 온다.
 *  · 화면 쪽은 simulate()를 처음부터 다시 돌리며 아직 답하지 않은 질문(prompt)을 받아 간다.
 * ───────────────────────────────────────────────────────── */
(function (root) {
'use strict';

// ── 난수 ────────────────────────────────────────────────
function hashStr(str) {
  let h = 1779033703 ^ str.length;
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  h = Math.imul(h ^ (h >>> 16), 2246822507);
  h = Math.imul(h ^ (h >>> 13), 3266489909);
  return (h ^= h >>> 16) >>> 0;
}
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function makeRng(seed, key) {
  const r = mulberry32(hashStr(seed + '|' + key));
  const R = {
    next: r,
    range: (a, b) => a + (b - a) * r(),
    int: (a, b) => a + Math.floor(r() * (b - a + 1)),
    pick: arr => arr[Math.floor(r() * arr.length)],
    chance: p => r() < p,
    normal: () => {
      let u = 0, v = 0;
      while (u === 0) u = r();
      while (v === 0) v = r();
      return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    },
  };
  return R;
}

// ── 수학 도우미 ──────────────────────────────────────────
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const sigmoid = x => 1 / (1 + Math.exp(-x));
function phi(z) {
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const d = 0.3989423 * Math.exp(-z * z / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return z > 0 ? 1 - p : p;
}
function invNorm(p) {
  const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924];
  const b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857];
  const c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878];
  const d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742];
  const pl = 0.02425, ph = 1 - pl;
  let q, r;
  if (p < pl) { q = Math.sqrt(-2 * Math.log(p)); return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
  if (p <= ph) { q = p - 0.5; r = q * q; return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1); }
  q = Math.sqrt(-2 * Math.log(1 - p));
  return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
}
// 상위 p% ↔ z점수
const zFromTop = p => invNorm(1 - clamp(p, 0.03, 99.9) / 100);
const topFromZ = z => clamp((1 - phi(z)) * 100, 0.01, 100);
const CUT9 = [4, 11, 23, 40, 60, 77, 89, 96, 100];
const CUT5 = [10, 34, 66, 90, 100];
const grade9 = pct => { for (let i = 0; i < 9; i++) if (pct <= CUT9[i]) return i + 1; return 9; };
const grade5 = pct => { for (let i = 0; i < 5; i++) if (pct <= CUT5[i]) return i + 1; return 5; };
// 위로 갈수록 오르기 어렵다
const damp = z => (z > 1 ? 1 / (1 + 0.45 * (z - 1)) : 1);

function josa(word, pair) {
  const [a, b] = pair.split('/');
  // '계약직 (진로 전환)'처럼 괄호로 끝나면 괄호 앞 글자로 받침을 본다
  const base = String(word).replace(/\s*\([^)]*\)\s*$/, '');
  const c = base.charCodeAt(base.length - 1);
  if (c < 0xAC00 || c > 0xD7A3) return word + b;
  const jong = (c - 0xAC00) % 28;
  if (pair === '으로/로') return word + (jong === 0 || jong === 8 ? b : a);
  return word + (jong ? a : b);
}
const jo = (w, pair) => josa(w, pair).slice(String(w).length);
const won = n => (n >= 10000 ? (Math.floor(n / 10000) + '억 ' + (n % 10000 ? (n % 10000).toLocaleString() + '만' : '')).trim() : n.toLocaleString() + '만') + ' 원';

// ── 기본 자료 ────────────────────────────────────────────
const FIELDS = {
  med:   { name: '의약계열',      track: '자연', majors: ['의예과'],                                   talent: null },
  nurse: { name: '간호·보건',     track: '자연', majors: ['간호학과', '물리치료학과', '임상병리학과'],    talent: null },
  eng:   { name: '공학',          track: '자연', majors: ['기계공학과', '전자공학과', '화학공학과', '신소재공학과'], talent: null },
  cs:    { name: '컴퓨터·AI',     track: '자연', majors: ['컴퓨터공학과', '소프트웨어학과', '인공지능학과'], talent: 'code' },
  sci:   { name: '자연과학',      track: '자연', majors: ['생명과학과', '화학과', '물리학과', '수학과'],    talent: null },
  biz:   { name: '경영·경제',     track: '인문', majors: ['경영학과', '경제학과', '회계학과'],            talent: null },
  law:   { name: '법·행정·정치',  track: '인문', majors: ['행정학과', '정치외교학과', '경찰행정학과'],    talent: null },
  edu:   { name: '교육',          track: '인문', majors: ['초등교육과'],                               talent: null },
  hum:   { name: '인문·어문',     track: '인문', majors: ['국어국문학과', '영어영문학과', '사학과', '철학과', '중어중문학과'], talent: 'verbal' },
  soc:   { name: '사회·심리',     track: '인문', majors: ['심리학과', '사회학과', '사회복지학과'],        talent: 'people' },
  media: { name: '미디어·광고',   track: '인문', majors: ['미디어커뮤니케이션학과', '광고홍보학과'],     talent: 'media' },
  art:   { name: '디자인·미술',   track: '예체', majors: ['시각디자인과', '산업디자인과', '서양화과', '애니메이션과'], talent: 'art' },
  perf:  { name: '음악·공연',     track: '예체', majors: ['실용음악과', '연극영화과', '작곡과'],          talent: 'perf' },
  sport: { name: '체육',          track: '예체', majors: ['체육교육과', '스포츠과학과', '경호학과'],      talent: 'sport' },
};
const FIELD_KEYS = Object.keys(FIELDS);
// 같은 대학 안에서도 학과에 따라 합격선이 다르다(z 기준, +면 더 어렵다)
const FIELD_DIFF = { med: 0, nurse: 0.2, eng: 0.05, cs: 0.12, sci: -0.12, biz: 0.06, law: 0, edu: 0, hum: -0.15, soc: -0.05, media: 0, art: -0.1, perf: -0.1, sport: -0.2 };
const SILGI = { art: 1, perf: 1, sport: 1 };

const TIERS = [
  { key: 't0', name: '서울대',          pct: 0.6, prestige: 100, gi: 0, unis: ['서울대'] },
  { key: 't1', name: '연고대',          pct: 1.5, prestige: 93, gi: 1, unis: ['연세대', '고려대'] },
  { key: 't2', name: '서성한',          pct: 3.2, prestige: 86, gi: 2, unis: ['서강대', '성균관대', '한양대'] },
  { key: 't3', name: '중경외시',        pct: 5.5, prestige: 80, gi: 3, unis: ['중앙대', '경희대', '한국외대', '서울시립대'] },
  { key: 't4', name: '건동홍',          pct: 8.5, prestige: 74, gi: 4, unis: ['건국대', '동국대', '홍익대'] },
  { key: 't5', name: '국숭세단',        pct: 12, prestige: 68, gi: 5, unis: ['국민대', '숭실대', '세종대', '단국대'] },
  { key: 't6', name: '광명상가·인하아주', pct: 17, prestige: 63, gi: 6, unis: ['광운대', '명지대', '상명대', '가톨릭대', '인하대', '아주대'] },
  { key: 't7', name: '지방거점국립대',   pct: 23, prestige: 60, gi: 7, unis: ['부산대', '경북대', '전남대', '충남대', '충북대', '전북대'] },
  { key: 't8', name: '수도권 4년제',     pct: 38, prestige: 50, gi: 8, unis: ['수도권 4년제 대학'] },
  { key: 't9', name: '지방 4년제',       pct: 62, prestige: 40, gi: 9, unis: ['지방 4년제 대학'] },
  { key: 't10', name: '전문대',          pct: 100, prestige: 30, gi: 10, unis: ['전문대학'] },
];
const MED_TIERS = [
  { key: 'm0', name: '서울대 의대',       pct: 0.08, prestige: 100, gi: 0, unis: ['서울대'], majors: ['의예과'], fo: 'med' },
  { key: 'm1', name: '연고·성균관대 의대', pct: 0.16, prestige: 99, gi: 0, unis: ['연세대', '고려대', '성균관대'], majors: ['의예과'], fo: 'med' },
  { key: 'm2', name: '수도권 의대',       pct: 0.3, prestige: 98, gi: 0, unis: ['한양대', '중앙대', '경희대', '가톨릭대', '인하대', '아주대'], majors: ['의예과'], fo: 'med' },
  { key: 'm3', name: '지방 의대',         pct: 0.55, prestige: 96, gi: 0, unis: ['부산대', '경북대', '전남대', '충남대', '계명대', '원광대'], majors: ['의예과'], fo: 'med' },
  { key: 'm4', name: '치의예·한의예',     pct: 0.95, prestige: 92, gi: 1, unis: ['경희대', '연세대', '부산대', '원광대', '단국대'], majors: ['치의예과', '한의예과'], fo: 'med' },
  { key: 'm5', name: '약학·수의예',       pct: 1.6, prestige: 88, gi: 1, unis: ['중앙대', '성균관대', '경희대', '충남대', '강원대'], majors: ['약학과', '수의예과'], fo: 'med' },
];
const EDU_TIERS = [
  { key: 'e0', name: '서울대·연고대 사범대', pct: 1.8, prestige: 92, gi: 1, unis: ['서울대', '고려대'], majors: ['국어교육과', '수학교육과', '영어교육과'], teacher: 'sec' },
  { key: 'e1', name: '서성한 사범대',       pct: 3.6, prestige: 85, gi: 2, unis: ['성균관대', '한양대'], majors: ['국어교육과', '수학교육과', '영어교육과'], teacher: 'sec' },
  { key: 'e2', name: '서울·경인교대',       pct: 7, prestige: 79, gi: 3, unis: ['서울교대', '경인교대'], majors: ['초등교육과'], teacher: 'elem' },
  { key: 'e3', name: '지방 교대',           pct: 12, prestige: 73, gi: 4, unis: ['부산교대', '대구교대', '광주교대', '청주교대', '공주교대', '춘천교대', '전주교대', '진주교대'], majors: ['초등교육과'], teacher: 'elem' },
  { key: 'e4', name: '거점국립대 사범대',   pct: 22, prestige: 60, gi: 7, unis: ['부산대', '경북대', '전남대', '충남대'], majors: ['국어교육과', '수학교육과', '영어교육과', '사회교육과'], teacher: 'sec' },
  { key: 'e5', name: '사립대 사범대',       pct: 40, prestige: 50, gi: 8, unis: ['수도권 4년제 대학', '지방 4년제 대학'], majors: ['국어교육과', '영어교육과', '사회교육과'], teacher: 'sec' },
  { key: 'e6', name: '전문대 유아교육과',   pct: 100, prestige: 30, gi: 10, unis: ['전문대학'], majors: ['유아교육과'], teacher: 'kinder' },
];
function tierList(field, s) {
  if (field === 'med') {
    const local = s && (s.p.region === 'city' || s.p.region === 'rural');
    const med = MED_TIERS.map(t => (t.key === 'm3' && local ? Object.assign({}, t, { pct: 1.1, name: '지방 의대(지역인재)' }) : t))
      .sort((a, b) => a.pct - b.pct);
    // 의대가 안 되면 생명 계열로 내려간다
    const rest = TIERS.slice(2, 9).map(t => Object.assign({}, t, { majors: ['생명과학과', '생명공학과', '화학과'], fo: 'sci' }));
    return med.concat(rest);
  }
  if (field === 'edu') return EDU_TIERS;
  return TIERS;
}
const GOALS = {
  med:     { name: '의대',           gi: 0 },
  sky:     { name: '서울대·연고대',   gi: 1 },
  ssh:     { name: '서성한',         gi: 2 },
  jkos:    { name: '중경외시',        gi: 3 },
  kdh:     { name: '건동홍',          gi: 4 },
  inseoul: { name: '인서울',         gi: 6 },
  local:   { name: '지방거점국립대',  gi: 7 },
  any:     { name: '어디든 괜찮다',   gi: 9 },
};
const PARENT_STYLES = {
  strict:  { name: '엄격·통제형',  pressure: 30, rel: 45, mental: -6 },
  warm:    { name: '다정·지지형',  pressure: 4,  rel: 78, mental: 10 },
  lax:     { name: '방임·무관심형', pressure: 0,  rel: 50, mental: 0 },
  anxious: { name: '과보호·불안형', pressure: 22, rel: 62, mental: -4 },
  absent:  { name: '바쁨·부재형',  pressure: 6,  rel: 40, mental: -6 },
};
const PARENT_DESIRES = {
  med:      { name: '의사가 됐으면',          field: 'med' },
  prestige: { name: '무조건 명문대 간판',      field: null },
  stable:   { name: '공무원·교사 같은 안정',   field: 'edu' },
  law:      { name: '법조인·고위 공무원',      field: 'law' },
  biz:      { name: '사업·가업을 이어받길',    field: 'biz' },
  money:    { name: '빨리 자리 잡고 돈 벌기',  field: null },
  free:     { name: '네가 원하는 걸 하렴',     field: null },
};
const STYLES = {
  steady:  { name: '꾸준형',     naesin: 1.0,  csat: 1.0,  var: 0.16, stress: 0 },
  cram:    { name: '벼락치기형',  naesin: 1.05, csat: 0.82, var: 0.42, stress: 3 },
  immerse: { name: '몰입형',     naesin: 0.9,  csat: 1.08, var: 0.32, stress: 0 },
  perfect: { name: '완벽주의형',  naesin: 1.08, csat: 0.98, var: 0.12, stress: 6 },
  hack:    { name: '요령형',     naesin: 1.0,  csat: 0.92, var: 0.24, stress: -2 },
};
const HOBBIES = {
  game:   { name: '게임',        lazy: 2.2, talent: { code: 6, game: 22 },  interest: { cs: 8 } },
  sport:  { name: '운동',        lazy: 0,   talent: { sport: 25 },           interest: { sport: 25 } },
  draw:   { name: '그림·디자인',  lazy: 0.4, talent: { art: 25 },             interest: { art: 30 } },
  music:  { name: '음악·노래',   lazy: 0.4, talent: { perf: 25 },            interest: { perf: 28 } },
  read:   { name: '독서',        lazy: -0.5, talent: { verbal: 22 },         interest: { hum: 20, edu: 5 } },
  code:   { name: '코딩',        lazy: 0.3, talent: { code: 28 },            interest: { cs: 30, eng: 6 } },
  video:  { name: '영상·유튜브',  lazy: 1.6, talent: { media: 24 },           interest: { media: 26 } },
  webtoon:{ name: '웹툰·애니',    lazy: 1.2, talent: { art: 12 },             interest: { art: 15, media: 8 } },
  volunteer:{ name: '봉사·돌봄', lazy: -0.3, talent: { people: 18 },         interest: { soc: 18, nurse: 12, edu: 12 } },
  science:{ name: '과학 실험·탐구', lazy: 0, talent: { verbal: 4 },          interest: { sci: 24, med: 10, eng: 8 } },
  debate: { name: '토론·시사',   lazy: 0,   talent: { verbal: 16, people: 8 }, interest: { law: 24, soc: 8, media: 6 } },
  idol:   { name: '아이돌 덕질',  lazy: 1.4, talent: { perf: 8, media: 8 },   interest: { media: 14, perf: 8 } },
  fashion:{ name: '패션·뷰티',   lazy: 0.8, talent: { art: 12, people: 6 },  interest: { art: 14, biz: 10 } },
  cook:   { name: '요리·베이킹',  lazy: 0.2, talent: { craft: 22 },           interest: { biz: 6 } },
};
const FRIEND_GROUPS = {
  rival:  { name: '공부 라이벌 무리', lazy: -1.2, study: 0.012, social: 0, stress: 1.2 },
  party:  { name: '노는 무리',       lazy: 1.6,  study: -0.012, social: 2, stress: -1 },
  gamers: { name: '게임 친구들',     lazy: 1.3,  study: -0.008, social: 0.5, stress: -0.5 },
  club:   { name: '동아리·예체능 친구', lazy: 0.2, study: 0, social: 1.5, stress: -0.5 },
  alone:  { name: '친구가 거의 없다',  lazy: 0.3,  study: 0.005, social: -2, stress: 1 },
};
const NAMES = ['지우', '서진', '하율', '시온', '은재', '도하', '윤슬', '태이', '주원', '다온', '해솔', '로운'];
const FRIEND_NAMES = ['민재', '수아', '현우', '예린', '준서', '채원', '건우', '소율', '지환', '나은'];

// ── 진로(직업) 자료: [최상, 상, 중, 하] 단계별 두 갈래 ─────────────────
const JOBS = {
  nurse: [[['빅5 대학병원 간호사', 5200], ['대학병원 전담간호사', 5600]], [['지방 대학병원 간호사', 4400], ['보건직 공무원', 4100]], [['종합병원 간호사', 3900], ['요양병원 간호사', 3600]], [['3교대 번아웃 후 쉬는 간호사', 2400], ['병원 원무과 직원', 3000]]],
  eng:   [[['반도체 대기업 공정 엔지니어', 8600], ['완성차 대기업 연구소 연구원', 8200]], [['대기업 계열사 엔지니어', 6600], ['방산기업 연구원', 6300]], [['중견 제조업체 설비 엔지니어', 4600], ['협력업체 품질관리 담당', 4300]], [['중소기업 생산관리', 3400], ['공장 교대 근무 엔지니어', 3600]]],
  cs:    [[['대형 IT 플랫폼 백엔드 개발자', 8800], ['빅테크 AI 엔지니어', 9800]], [['IT 대기업 계열사 개발자', 6900], ['유니콘 스타트업 개발자', 6600]], [['중견 SI업체 개발자', 4800], ['게임회사 클라이언트 개발자', 4900]], [['소규모 에이전시 웹 개발자', 3300], ['부트캠프 수료 후 구직 중', 1800]]],
  sci:   [[['제약회사 R&D 연구원', 6900], ['정부출연연구소 연구원', 6400]], [['바이오 기업 연구원', 5500], ['화학 대기업 품질연구원', 5800]], [['식품회사 품질관리', 4100], ['바이오벤처 연구원', 3900]], [['연구실 계약직 연구보조원', 2800], ['전공과 무관한 사무직', 3100]]],
  biz:   [[['증권사 IB 애널리스트', 9500], ['대기업 전략기획팀', 8200]], [['시중은행 행원', 6900], ['대기업 영업관리', 6500]], [['중견기업 재무팀', 4700], ['보험사 영업관리', 4500]], [['중소기업 경리·총무', 3200], ['계약직 영업사원', 3000]]],
  law:   [[['대기업 법무·대관팀', 7200], ['국회 보좌관', 6200]], [['공공기관 정책연구원', 5300], ['언론사 정치부 기자', 5400]], [['중견기업 인사팀', 4200], ['시민단체 활동가', 3000]], [['법률사무소 사무장', 3200], ['행정 계약직', 2800]]],
  edu:   [[['에듀테크 기업 콘텐츠 기획자', 6200], ['대형 입시학원 인기 강사', 9000]], [['교육 공공기관 연구원', 5000], ['대치동 학원 강사', 5200]], [['동네 학원 강사', 3600], ['교육 출판사 편집자', 3700]], [['기간제 교사', 3200], ['공부방 운영', 2600]]],
  hum:   [[['대기업 해외영업', 6800], ['출판사 기획편집자(팀장 트랙)', 5200]], [['외국계 기업 마케터', 5400], ['통번역사', 4800]], [['중견기업 사무직', 3900], ['콘텐츠 에디터', 3500]], [['계약직 사무보조', 2700], ['카페 매니저(진로 고민 중)', 2600]]],
  soc:   [[['대기업 HR 피플팀', 6400], ['임상심리전문가', 5600]], [['리서치 회사 연구원', 4700], ['공공기관 상담사', 4300]], [['복지관 사회복지사', 3400], ['기업 상담센터 상담사', 3600]], [['비정규직 상담원', 2700], ['심리 대학원 진학 고민 중', 2000]]],
  media: [[['방송사 PD', 7200], ['대형 광고대행사 AE', 6800]], [['언론사 기자', 5200], ['플랫폼 기업 콘텐츠 마케터', 5400]], [['외주 제작사 조연출', 3300], ['중소 광고회사 기획자', 3700]], [['프리랜서 영상 편집자', 2800], ['MCN 계약직', 2700]]],
  art:   [[['대기업 UX 디자이너', 6600], ['글로벌 브랜드 디자이너', 6200]], [['IT 기업 프로덕트 디자이너', 5300], ['웹툰 작가(정식 연재)', 5800]], [['디자인 에이전시 디자이너', 3600], ['게임회사 원화가', 4200]], [['불안정한 프리랜서 디자이너', 2500], ['미술 학원 강사', 2800]]],
  perf:  [[['뮤지컬 주연 배우', 8000], ['히트곡을 낸 작곡가', 9000]], [['세션 연주자', 4200], ['방송 음악감독 팀원', 4500]], [['실용음악 학원 강사', 3200], ['공연기획사 직원', 3400]], [['단역 배우 겸 아르바이트', 1900], ['무명 인디 뮤지션', 1600]]],
  sport: [[['프로 구단 트레이너', 5600], ['체육 정교사', 5000]], [['스포츠 브랜드 마케터', 5000], ['경찰공무원(경장)', 4700]], [['헬스장 PT 트레이너', 3600], ['생활체육 지도자', 3100]], [['아르바이트 트레이너', 2400], ['진로 전환 준비 중', 1800]]],
  none:  [[['대기업 생산직(정규직)', 6500], ['공기업 고졸 채용', 5200]], [['중견기업 기술직', 4500], ['프랜차이즈 점장', 4200]], [['배달·물류 기사', 4000], ['판매직 정규직', 3100]], [['아르바이트 전전', 2100], ['쉬었음 청년', 600]]],
};
const LEVEL_NAMES = ['최상', '상', '중', '하'];

// ── 상태 만들기 ──────────────────────────────────────────
function normalizeProfile(p) {
  const d = {
    name: '나', gender: 'x', grade: 1, track: '자연', school: 'general', region: 'metro',
    gpaPct: 30, mockPct: 30, recordLv: 3, style: 'steady',
    diligence: 3, grit: 3, social: 3, curiosity: 3, confidence: 3, impulse: 3,
    focus: 3, comprehension: 3, memory: 3,
    hobbies: [], interest: 'unknown', goal: 'inseoul',
    pStyle: 'warm', pDesire: 'free', wealth: 'mid', sibling: 'none',
    friendGroup: 'club', bestFriend: true,
  };
  const out = Object.assign({}, d, p || {});
  out.hobbies = (out.hobbies || []).filter(h => HOBBIES[h]).slice(0, 3);
  out.grade = clamp(parseInt(out.grade, 10) || 1, 1, 3);
  ['diligence', 'grit', 'social', 'curiosity', 'confidence', 'impulse', 'focus', 'comprehension', 'memory', 'recordLv']
    .forEach(k => { out[k] = clamp(parseInt(out[k], 10) || 3, 1, 5); });
  out.gpaPct = clamp(+out.gpaPct || 30, 0.5, 99);
  out.mockPct = clamp(+out.mockPct || 30, 0.3, 99);
  if (!out.name || !String(out.name).trim()) out.name = '나';
  out.name = String(out.name).trim().slice(0, 10);
  return out;
}

function initState(p, seed) {
  const r = makeRng(seed, 'init');
  const ps = PARENT_STYLES[p.pStyle] || PARENT_STYLES.warm;
  const s = {
    p, seed,
    zN: zFromTop(p.gpaPct), zC: zFromTop(p.mockPct),
    naesinRec: [], mocks: [],
    record: 18 + p.recordLv * 6 + (p.school !== 'general' ? 4 : 0),
    recFit: {},
    mental: clamp(42 + p.grit * 5 + ps.mental, 10, 95),
    stress: 28 + (p.school !== 'general' ? 8 : 0),
    health: 72,
    lazy: clamp(18 + p.impulse * 8 - p.diligence * 5, 3, 80),
    parentRel: ps.rel, pressure: 0,
    social: clamp(20 + p.social * 10 + (p.bestFriend ? 6 : -6), 5, 95),
    friendGroup: p.friendGroup, bestFriend: !!p.bestFriend,
    bestName: r.pick(FRIEND_NAMES),
    romance: { status: 'none', partner: null, studious: false, since: 0, score: 0, count: 0, firstLove: null },
    interest: {}, talent: { art: 15, perf: 15, sport: 25, code: 12, verbal: 20, people: 15 + p.social * 5, media: 12, game: 15, craft: 10 },
    money: { high: 110, mid: 60, low: 22 }[p.wealth] || 60,
    track: p.track,
    subject: null,
    autonomy: 0,     // 내가 정한 길(+)인지 부모님이 정한 길(-)인지
    flags: {}, seen: {},
    log: [], history: [],
    turnIdx: 0, turnLabel: '', age: 16 + p.grade,
    phase: 'hs',
    uni: null, col: null, career: null, ending: null,
    attempts: 0,
  };
  s.pressure = ps.pressure + (p.pDesire !== 'free' ? 14 : 0) + (p.sibling === 'better' ? 10 : 0);
  FIELD_KEYS.forEach(f => { s.interest[f] = 5 + r.int(0, 6); s.recFit[f] = 0; });
  if (FIELDS[p.interest]) { s.interest[p.interest] += 40; s.recFit[p.interest] += p.recordLv * 3; }
  p.hobbies.forEach(h => {
    const H = HOBBIES[h];
    Object.keys(H.talent).forEach(t => { s.talent[t] = (s.talent[t] || 0) + H.talent[t] + r.int(0, 12); });
    Object.keys(H.interest).forEach(f => { s.interest[f] += H.interest[f]; });
    s.lazy = clamp(s.lazy + H.lazy * 3, 0, 100);
  });
  const desire = PARENT_DESIRES[p.pDesire];
  if (desire && desire.field) s.interest[desire.field] += 8;   // 자라면서 스며든 부모님 기대
  if (p.track === '자연') ['med', 'eng', 'cs', 'sci', 'nurse'].forEach(f => { s.interest[f] += 4; });
  else ['biz', 'law', 'hum', 'soc', 'media', 'edu'].forEach(f => { s.interest[f] += 4; });
  // 고2·고3으로 시작하면 지난 학기 내신은 입력값으로 채운다
  const prevSem = (p.grade - 1) * 2;
  for (let i = 0; i < prevSem; i++) s.naesinRec.push(clamp(p.gpaPct * (0.9 + r.next() * 0.2), 0.5, 99));
  return s;
}

function topInterest(s, exclude) {
  let best = null, bv = -1;
  FIELD_KEYS.forEach(f => { if (f !== exclude && s.interest[f] > bv) { bv = s.interest[f]; best = f; } });
  return best;
}
function fitOf(s, field) {
  const mx = Math.max.apply(null, FIELD_KEYS.map(f => s.interest[f]));
  return clamp(s.interest[field] / mx, 0, 1);
}
function avgNaesin(s) {
  const rec = s.naesinRec;
  if (!rec.length) return s.p.gpaPct;
  // 고1 20% · 고2 40% · 고3 1학기 40%에 가깝게
  const w = rec.map((_, i) => (i < 2 ? 1 : i < 4 ? 2 : 2));
  const tot = w.reduce((a, b) => a + b, 0);
  return rec.reduce((a, v, i) => a + v * w[i], 0) / tot;
}

// ── 기록 도우미 ──────────────────────────────────────────
function inc(s, k, v) { s[k] = clamp((s[k] || 0) + v, 0, 100); }
function L(s, text, kind) { s.log.push({ t: s.turnLabel, text, kind: kind || 'info', i: s.log.length }); }
function hasHobby(s, h) { return s.p.hobbies.indexOf(h) >= 0; }
const phoneHobby = s => ['game', 'video', 'webtoon', 'idol'].some(h => hasHobby(s, h));
const parentWord = s => (s.p.pStyle === 'absent' ? '오랜만에 집에 온 아빠' : s.p.pStyle === 'anxious' ? '엄마' : s.p.pStyle === 'strict' ? '아빠' : '엄마');

// ── 질문하기 ─────────────────────────────────────────────
function Pending(prompt) { this.prompt = prompt; }
function ask(ctx, prompt) {
  const s = ctx.s;
  prompt.turn = s.turnLabel;
  prompt.age = s.age;
  const v = ctx.resolve(prompt, s);
  if (v === undefined) throw new Pending(prompt);
  s.history.push({ key: prompt.key, turn: s.turnLabel, title: prompt.title, prompt: stripPrompt(prompt), choice: v, idx: s.history.length });
  return v;
}
function stripPrompt(pr) {
  return { key: pr.key, type: pr.type, title: pr.title, text: pr.text, turn: pr.turn,
    options: pr.options ? pr.options.map(o => ({ id: o.id, label: o.label, tags: o.tags, w: o.w })) : undefined,
    cats: pr.cats, def: pr.def, total: pr.total };
}
function choose(ctx, key, title, text, options) {
  const opts = options.filter(Boolean);
  const id = ask(ctx, { type: 'choice', key, title, text, options: opts.map(o => ({ id: o.id, label: o.label, hint: o.hint, tags: o.tags || [], w: o.w || 0 })) });
  const o = opts.find(x => x.id === id) || opts[0];
  return o;
}

// ── 성향대로 고르는 '나' (되감기·자동 진행에 쓴다) ──────────────────
function persona(s, prompt) {
  const p = s.p;
  const W = {
    study: p.diligence * 1.1 + (8 - (GOALS[p.goal] || GOALS.inseoul).gi) * 0.2 - p.impulse * 0.3,
    fun: p.impulse * 0.9 + (5 - p.diligence) * 0.4,
    social: p.social * 0.9,
    romance: p.social * 0.6 + p.impulse * 0.5,
    obey: (p.pStyle === 'strict' || p.pStyle === 'anxious' ? 2.6 : 1) + (5 - p.confidence) * 0.5,
    rebel: p.confidence * 0.8 + (p.pStyle === 'strict' ? 0.6 : 0),
    safe: (5 - p.confidence) * 0.9 + 0.8,
    risk: p.confidence * 0.55 + p.curiosity * 0.3,
    rest: (5 - p.grit) * 0.6 + 0.6,
    record: p.curiosity * 0.9 + p.diligence * 0.3,
    kind: p.social * 0.4 + 1.2,
    work: p.wealth === 'low' ? 3.2 : 0.4,
    self: p.confidence * 0.5 + p.curiosity * 0.6,
  };
  if (prompt.type === 'alloc') return defaultAlloc(s, prompt.cats);
  let best = prompt.options[0].id, bv = -1e9;
  prompt.options.forEach((o, i) => {
    const tags = o.tags && o.tags.length ? o.tags : ['safe'];
    const v = tags.reduce((a, t) => a + (W[t] != null ? W[t] : 1), 0) / tags.length + (o.w || 0) - i * 0.01;
    if (v > bv) { bv = v; best = o.id; }
  });
  return best;
}
function defaultAlloc(s, cats) {
  const p = s.p, ids = cats.map(c => c.id);
  const w = {
    study: 2 + p.diligence * 0.7 - p.impulse * 0.2,
    academy: s.money > 30 ? 1.2 + (p.pStyle === 'strict' || p.pStyle === 'anxious' ? 1 : 0) + (p.wealth === 'high' ? 0.8 : 0) : 0,
    activity: 0.4 + p.curiosity * 0.3,
    hobby: 0.6 + p.impulse * 0.35,
    friends: 0.3 + p.social * 0.35,
    rest: 1.2,
    date: 1.2,
    work: p.wealth === 'low' ? 1 : 0,
  };
  const raw = ids.map(id => Math.max(0, w[id] || 0));
  const tot = raw.reduce((a, b) => a + b, 0) || 1;
  const out = {}; let used = 0;
  ids.forEach((id, i) => { out[id] = Math.floor(raw[i] / tot * 10); used += out[id]; });
  // 남는 칸은 큰 순서대로
  const order = ids.map((id, i) => [id, raw[i] / tot * 10 - out[id]]).sort((a, b) => b[1] - a[1]);
  for (let i = 0; used < 10; i = (i + 1) % order.length) { out[order[i][0]]++; used++; }
  return out;
}
function normAlloc(a, cats) {
  const out = {}; let t = 0;
  cats.forEach(c => { out[c.id] = clamp(Math.round(+((a || {})[c.id]) || 0), 0, 10); t += out[c.id]; });
  // 10칸을 넘으면 뒤에서부터 줄이고, 모자라면 휴식에 넣는다
  for (let i = cats.length - 1; t > 10 && i >= 0; i--) { const cut = Math.min(out[cats[i].id], t - 10); out[cats[i].id] -= cut; t -= cut; }
  if (t < 10) out.rest = (out.rest || 0) + (10 - t);
  return out;
}

// ── 고등학교 시점 ────────────────────────────────────────
const HS_TURNS = [
  { id: 'g1s1', label: '고1 1학기', type: 'sem' },
  { id: 'g1v1', label: '고1 여름방학', type: 'vac' },
  { id: 'g1s2', label: '고1 2학기', type: 'sem' },
  { id: 'g1v2', label: '고1 겨울방학', type: 'vac' },
  { id: 'g2s1', label: '고2 1학기', type: 'sem' },
  { id: 'g2v1', label: '고2 여름방학', type: 'vac' },
  { id: 'g2s2', label: '고2 2학기', type: 'sem' },
  { id: 'g2v2', label: '고3 직전 겨울방학', type: 'vac', big: true },
  { id: 'g3s1', label: '고3 1학기', type: 'sem' },
  { id: 'g3v1', label: '고3 여름 · 원서', type: 'apply' },
  { id: 'g3s2', label: '고3 2학기 · 수능', type: 'final' },
];

function allocCats(s, turn) {
  const cats = [
    { id: 'study', label: '자습', desc: '혼자 하는 공부. 성실하고 집중력이 좋을수록 효과가 크다.' },
    { id: 'academy', label: '학원·과외', desc: s.money > 25 ? '돈이 든다. 수능형 실력에 특히 효과.' : '집안 형편이 빠듯해 부담이 크다.' },
    { id: 'activity', label: '생기부 활동', desc: '동아리·탐구·봉사. 학종에 쓰인다.' },
    { id: 'hobby', label: '취미', desc: s.p.hobbies.length ? s.p.hobbies.map(h => HOBBIES[h].name).join('·') : '좋아하는 것' },
    { id: 'friends', label: '친구', desc: FRIEND_GROUPS[s.friendGroup].name },
    { id: 'rest', label: '휴식·잠', desc: '체력과 멘탈을 채운다.' },
  ];
  if (s.romance.status === 'dating') cats.push({ id: 'date', label: '연애', desc: s.romance.partner + '와(과)의 시간' });
  if (s.p.wealth === 'low' || s.flags.work) cats.push({ id: 'work', label: '아르바이트', desc: '용돈·생활비' });
  return cats;
}

function semesterEffects(ctx, turn, a) {
  const s = ctx.s, p = s.p, r = makeRng(s.seed, turn.id + ':sem');
  const st = STYLES[p.style] || STYLES.steady;
  const fg = FRIEND_GROUPS[s.friendGroup];
  const lossFrac = clamp((s.lazy - 22) / 115, 0, 0.5);
  const planned = a.study + a.academy;
  let academyEff = s.money >= 6 ? 1 : 0.45;
  const studied = a.study * (1 - lossFrac) + a.academy * academyEff * (1 - lossFrac * 0.45);
  const lost = a.study * lossFrac + a.academy * lossFrac * 0.45;
  if (lost >= 0.7) L(s, `계획한 공부 ${planned}칸 중 약 ${lost.toFixed(1)}칸이 핸드폰·딴짓으로 증발했다. (나태 ${Math.round(s.lazy)})`, 'warn');
  const ability = (p.focus * 0.4 + p.comprehension * 0.35 + p.memory * 0.25) / 3;
  const cond = 0.72 + s.mental / 380 + s.health / 420 - (s.stress > 70 ? 0.08 : 0);
  const goal = GOALS[p.goal] || GOALS.inseoul;
  const motive = 1 + (goal.gi <= 3 && p.diligence >= 3 ? 0.05 : 0) + (s.flags.fireUp ? 0.06 : 0);
  const eff = studied * ability * cond * motive;
  const baseN = p.school === 'special' ? 5.1 : p.school === 'jasa' ? 4.8 : p.region === 'gangnam' ? 4.5 : 4.2;
  const memF = 0.85 + p.memory * 0.05, compF = 0.75 + p.comprehension * 0.08;
  // 위로 갈수록 경쟁자들도 그만큼 공부한다 — 기준선이 올라간다
  const dN = (eff * st.naesin * memF - baseN - Math.max(0, s.zN) * 0.5) * 0.046 + fg.study * a.friends;
  const dC = (eff * st.csat * compF - 4.3 - Math.max(0, s.zC) * 0.55) * 0.04 + (a.academy * academyEff * 0.012) + fg.study * a.friends * 0.7;
  s.zN += dN * damp(s.zN);
  s.zC += dC * damp(s.zC);

  // 생기부
  const recGain = a.activity * 2.2 * (0.7 + p.curiosity * 0.1) * (1 - s.record / 160);
  s.record = clamp(s.record + recGain - (a.activity === 0 ? 1.5 : 0), 0, 100);
  const ti = topInterest(s);
  s.recFit[ti] = (s.recFit[ti] || 0) + a.activity * 2;
  if (a.activity) s.interest[ti] += a.activity * 0.8;

  // 취미
  p.hobbies.forEach(h => {
    Object.keys(HOBBIES[h].talent).forEach(t => { s.talent[t] = clamp((s.talent[t] || 0) + a.hobby * 1.6, 0, 100); });
    Object.keys(HOBBIES[h].interest).forEach(f => { s.interest[f] += a.hobby * 0.6; });
    inc(s, 'lazy', a.hobby * HOBBIES[h].lazy * 0.3);
  });
  inc(s, 'mental', a.hobby * 1.3);

  // 친구
  inc(s, 'social', a.friends * 2.4 - 3.5 + fg.social);
  inc(s, 'mental', a.friends * 0.9 - (a.friends === 0 ? 3 : 0));
  inc(s, 'lazy', fg.lazy * (0.6 + a.friends * 0.25) * (s.flags.distanced ? 0.4 : 1));

  // 휴식
  inc(s, 'health', (a.rest - 2) * 4.5);
  inc(s, 'mental', (a.rest - 2) * 1.8);
  inc(s, 'stress', -a.rest * 2.6);
  if (a.rest === 0) L(s, '잠을 줄였다. 아침마다 머리가 멍하다.', 'warn');

  // 연애
  if (a.date) {
    s.romance.score = clamp(s.romance.score + a.date * 7 - 6, 0, 100);
    inc(s, 'mental', a.date * 1.6);
    if (s.romance.studious && a.date <= 2) { s.zN += 0.015; }
  } else if (s.romance.status === 'dating') {
    s.romance.score = clamp(s.romance.score - 12, 0, 100);
  }
  // 알바
  if (a.work) { s.money += a.work * 4; inc(s, 'mental', -a.work * 0.6); s.flags.workExp = (s.flags.workExp || 0) + a.work; }

  // 학원비
  s.money -= a.academy * (p.region === 'gangnam' ? 3.4 : 2.6);
  if (s.money < 0) { s.money = 0; inc(s, 'parentRel', -3); s.flags.moneyTight = true; }

  // 스트레스·멘탈
  const load = planned * 2.1 - 9 + s.pressure * 0.16 + st.stress + fg.stress * 2 + (p.school !== 'general' ? 3 : 0);
  inc(s, 'stress', load - (p.pStyle === 'warm' ? 3 : 0) - p.grit * 0.8);
  if (s.stress > 60) inc(s, 'mental', -(s.stress - 60) / 4);
  inc(s, 'mental', (55 - s.mental) * 0.05);  // 시간이 지나면 조금은 돌아온다

  // 나태 습관
  let dl = p.impulse * 1.1 - p.diligence * 1.05 + (phoneHobby(s) ? 0.8 : 0) + (p.pStyle === 'lax' ? 1.8 : p.pStyle === 'strict' ? -1 : 0) - (a.study >= 5 ? 2 : 0) + (a.rest >= 5 ? 1.5 : 0);
  if (planned <= 2) dl += 3;
  // 습관은 타고난 성향 쪽으로 조금씩 되돌아간다
  const lazyBase = clamp(14 + p.impulse * 8 - p.diligence * 5 + (phoneHobby(s) ? 6 : 0), 3, 75);
  dl -= (s.lazy - lazyBase) * 0.16;
  inc(s, 'lazy', dl + r.normal() * 1.5);

  // 시험 결과
  const sc = s.zN + r.normal() * st.var + (s.stress > 75 ? -0.12 : 0) + (s.health < 30 ? -0.08 : 0);
  const pct = clamp(topFromZ(sc), 0.4, 99);
  const prev = s.naesinRec.length ? s.naesinRec[s.naesinRec.length - 1] : p.gpaPct;
  s.naesinRec.push(pct);
  const mockPct = clamp(topFromZ(s.zC + r.normal() * 0.18), 0.1, 99);
  s.mocks.push(mockPct);
  const diff = prev - pct;
  const word = diff > 4 ? '올랐다' : diff < -4 ? '떨어졌다' : '비슷했다';
  L(s, `기말 결과 — 내신 상위 ${pct.toFixed(1)}% (${gradeText(s, pct)}). 지난 학기보다 ${word}. 모의고사는 상위 ${mockPct.toFixed(1)}% (${grade9(mockPct)}등급).`, diff < -4 ? 'bad' : diff > 4 ? 'good' : 'info');

  // 부모님 반응
  if ((p.pStyle === 'strict' || p.pStyle === 'anxious') && diff < -4) { inc(s, 'parentRel', -6); inc(s, 'stress', 6); L(s, `성적표를 본 ${parentWord(s)}의 얼굴이 굳었다. 그날 밤 집이 조용했다.`, 'bad'); }
  else if (p.pStyle === 'warm' && diff < -4) { inc(s, 'mental', 3); L(s, '"괜찮아, 다음에 잘하면 돼." 그 말에 조금 울컥했다.', 'info'); }
  else if (p.pStyle === 'strict' && diff > 4) { inc(s, 'parentRel', 4); }
  if (p.sibling === 'better' && r.chance(0.35)) { inc(s, 'mental', -3); L(s, '"형(언니)은 이맘때 1등급이었는데." 또 그 얘기다.', 'warn'); }
  // 연애 자연 진행
  if (s.romance.status === 'dating') s.romance.since++;
}
function gradeText(s, pct) {
  return s.p.grade >= 3 ? grade9(pct) + '등급(9등급제)' : grade5(pct) + '등급(5등급제)';
}

function vacationTurn(ctx, turn) {
  const s = ctx.s, p = s.p, r = makeRng(s.seed, turn.id + ':vac');
  const big = turn.big ? 1.6 : 1;
  const opts = [
    { id: 'cram', label: s.money > 15 ? '방학 특강·선행 학원 (학원비 부담)' : '무리해서 방학 특강 등록', tags: ['study', 'obey'] },
    { id: 'self', label: '스터디카페에서 독학 계획표대로', tags: ['study', 'self'] },
    { id: 'activity', label: '탐구 보고서·캠프·봉사로 생기부 채우기', tags: ['record'] },
    { id: 'hobby', label: p.hobbies.length ? HOBBIES[p.hobbies[0]].name + '에 푹 빠져 보기' : '하고 싶던 것 해 보기', tags: ['fun', 'self'] },
    { id: 'rest', label: '가족 여행·푹 쉬기', tags: ['rest'] },
    { id: 'game', label: '폰·게임 몰아서 하기', tags: ['fun'] },
    (p.wealth !== 'high' || s.flags.work) ? { id: 'work', label: '아르바이트로 돈 벌기', tags: ['work'] } : null,
  ];
  const o = choose(ctx, turn.id + ':vac', turn.label, turn.big
    ? '고3 직전 겨울. 다들 "이번 방학이 수능을 결정한다"고 말한다. 이 방학을 어떻게 보낼까?'
    : '방학이다. 어떻게 보낼까?', opts);
  const ab = (p.focus + p.comprehension) / 6;
  switch (o.id) {
    case 'cram':
      s.money -= 8 * big; if (s.money < 0) { s.money = 0; s.flags.moneyTight = true; inc(s, 'parentRel', -4); }
      s.zC += 0.075 * ab * big * damp(s.zC) * (1 - s.lazy / 250); s.zN += 0.03 * big;
      inc(s, 'stress', 7); inc(s, 'lazy', -3);
      L(s, '아침 9시부터 밤 10시까지 학원. 진도는 나갔지만 피곤이 쌓였다.'); break;
    case 'self': {
      const kept = p.diligence / 5 * (1 - s.lazy / 160);
      s.zC += (0.02 + 0.07 * kept) * ab * big * damp(s.zC); s.zN += 0.02 * kept * big;
      inc(s, 'lazy', kept > 0.5 ? -6 : 4);
      L(s, kept > 0.5 ? '계획표의 대부분을 지켰다. 스스로가 조금 대견하다.' : '첫 주는 지켰다. 둘째 주부터는 스터디카페에서 유튜브를 봤다.', kept > 0.5 ? 'good' : 'warn'); break;
    }
    case 'activity': {
      const ti = topInterest(s);
      s.record = clamp(s.record + 9 * big * (0.7 + p.curiosity * 0.1), 0, 100); s.recFit[ti] += 7; s.interest[ti] += 6;
      L(s, `${FIELDS[ti].name} 관련 탐구 보고서를 썼다. 생기부에 한 줄이 늘었다.`, 'good'); break;
    }
    case 'hobby':
      p.hobbies.forEach(h => Object.keys(HOBBIES[h].talent).forEach(t => { s.talent[t] = clamp(s.talent[t] + 10, 0, 100); }));
      p.hobbies.forEach(h => Object.keys(HOBBIES[h].interest).forEach(f => { s.interest[f] += 6; }));
      inc(s, 'mental', 9); inc(s, 'lazy', 3); s.zC -= 0.02 * big;
      L(s, '좋아하는 걸 실컷 했다. 이게 진짜 내 길일지도 모른다는 생각이 스쳤다.'); break;
    case 'rest':
      inc(s, 'mental', 12); inc(s, 'health', 10); inc(s, 'stress', -16); inc(s, 'lazy', 3); inc(s, 'parentRel', 4); s.zC -= 0.015 * big;
      L(s, '오랜만에 가족과 시간을 보냈다. 머리가 맑아졌다.', 'good'); break;
    case 'game':
      inc(s, 'mental', 4); inc(s, 'lazy', 7 * big); inc(s, 'health', -4); s.zC -= 0.05 * big; s.zN -= 0.02 * big;
      s.talent.game = clamp(s.talent.game + 10, 0, 100);
      L(s, '방학이 순삭됐다. 개학 전날 밤, 해 놓은 게 없다는 걸 깨달았다.', 'bad'); break;
    case 'work':
      s.money += 14; s.flags.work = true; s.flags.workExp = (s.flags.workExp || 0) + 3; inc(s, 'mental', -2); s.zC -= 0.02;
      L(s, '편의점 알바로 번 돈으로 처음 내 돈으로 산 물건이 생겼다. 돈 버는 게 쉽지 않다는 것도 알았다.'); break;
  }
  if (turn.big) s.flags.winter = o.id;
}

// ── 정해진 이벤트 ─────────────────────────────────────────
function fixedEvents(ctx, turn) {
  const s = ctx.s, p = s.p;
  if (turn.id === 'g1s1') {
    const ti = topInterest(s);
    const o = choose(ctx, 'g1s1:club', '동아리 정하기', '입학 2주 차. 동아리 신청서를 내야 한다.', [
      { id: 'major', label: `${FIELDS[ti].name} 탐구 동아리 (생기부용)`, tags: ['record', 'study'] },
      { id: 'band', label: '방송부·밴드·댄스 동아리', tags: ['fun', 'social'] },
      { id: 'follow', label: s.bestFriend ? `${s.bestName}${jo(s.bestName, '이/가')} 들어가는 곳으로` : '아무 데나 자리 남는 곳', tags: ['social'] },
      { id: 'none', label: '동아리는 최소한만. 공부 시간 확보', tags: ['study', 'safe'] },
    ]);
    if (o.id === 'major') { s.record += 9; s.recFit[ti] += 10; s.interest[ti] += 5; s.flags.club = 'major'; L(s, `${FIELDS[ti].name} 동아리에 들어갔다. 선배들이 생기부 쓰는 법부터 알려줬다.`); }
    if (o.id === 'band') { s.record += 4; s.talent.perf += 8; s.talent.media += 8; inc(s, 'social', 8); inc(s, 'mental', 5); s.flags.club = 'band'; L(s, '동아리방에서 보내는 시간이 학교생활의 낙이 됐다.'); }
    if (o.id === 'follow') { s.record += 2; inc(s, 'social', 6); s.flags.club = 'follow'; L(s, '친구 따라 들어간 동아리. 활동은 그냥 그렇지만 같이 있어서 좋다.'); }
    if (o.id === 'none') { s.zN += 0.03; s.record -= 2; s.flags.club = 'none'; L(s, '동아리는 이름만 걸었다. 그 시간에 문제집을 풀었다.'); }
  }
  if (turn.id === 'g1s2' && p.grade === 1) {
    const o = choose(ctx, 'g1s2:subject', '고2 선택과목', '고교학점제. 고2 때 들을 과목을 골라야 한다. 대학은 이걸 보고 "이 학생이 전공을 준비했는지"를 본다.', [
      { id: 'phys', label: '미적분·물리·화학 (공대·자연대 정석)', tags: ['study', 'risk'] },
      { id: 'bio', label: '생명과학·화학 (의약·생명)', tags: ['study'] },
      { id: 'soc', label: '경제·정치와 법·사회문화 (상경·사회)', tags: ['safe'] },
      { id: 'lang', label: '언어와 매체·윤리·제2외국어 (인문·교육)', tags: ['safe'] },
      { id: 'easy', label: '내신 따기 쉬운 과목 위주로', tags: ['fun', 'safe'] },
    ]);
    s.subject = o.id;
    if (o.id === 'phys' || o.id === 'bio') s.track = '자연'; else if (o.id !== 'easy') s.track = '인문';
    if (o.id === 'phys') { s.zN -= 0.08; s.interest.eng += 6; s.interest.cs += 4; L(s, '물리·화학 반에는 이과 최상위권이 몰렸다. 내신 경쟁이 빡빡해졌다.', 'warn'); }
    if (o.id === 'bio') { s.zN -= 0.04; s.interest.med += 5; s.interest.nurse += 4; L(s, '생명과학 반. 의대 지망생이 반이다.'); }
    if (o.id === 'easy') { s.zN += 0.12; L(s, '내신은 확실히 편해졌다. 하지만 학종 면접관이 "왜 이 과목을 들었냐"고 물으면 할 말이 없을지도.', 'warn'); }
    if (o.id === 'soc' || o.id === 'lang') L(s, '인문 계열 과목을 골랐다. 이과 학과에 지원하기엔 이제 불리하다.');
  }
  if (turn.id === 'g2s1') {
    const r = makeRng(s.seed, 'g2s1:class');
    const vibe = r.pick(['rival', 'party', 'club']);
    const vName = { rival: '면학 분위기가 빡센', party: '시끌벅적 노는 분위기의', club: '두루두루 친한' }[vibe];
    const o = choose(ctx, 'g2s1:class', '고2 반 배정', `새 반은 ${vName} 반이다. ${s.bestFriend ? `${s.bestName}${jo(s.bestName, '와/과')}는 다른 반이 됐다.` : ''}`, [
      { id: 'blend', label: '새 반 친구들과 어울린다', tags: ['social'] },
      { id: 'keep', label: '원래 친구들과 계속 다닌다', tags: ['safe'] },
      { id: 'solo', label: '이참에 혼자 공부에 집중한다', tags: ['study'] },
    ]);
    if (o.id === 'blend') { s.friendGroup = vibe; inc(s, 'social', 5); L(s, `새 친구들이 생겼다. 반 분위기에 금방 물들었다.`); }
    if (o.id === 'keep') { inc(s, 'social', 1); L(s, '쉬는 시간마다 옆 반에 간다.'); }
    if (o.id === 'solo') { s.friendGroup = 'alone'; inc(s, 'social', -10); inc(s, 'lazy', -6); L(s, '점심도 혼자 빨리 먹고 자습실로 간다. 편하지만 가끔 외롭다.'); }
  }
}

// ── 무작위 이벤트 (고등학교) ─────────────────────────────────
function newPartner(s, r) {
  const name = r.pick(NAMES.filter(n => n !== s.romance.partner));
  return { name, studious: r.chance(0.45) };
}
function startDating(s, name, studious) {
  s.romance.status = 'dating'; s.romance.partner = name; s.romance.studious = studious;
  s.romance.since = 0; s.romance.score = 55; s.romance.count++;
  if (!s.romance.firstLove) s.romance.firstLove = name;
  s.flags.datedHS = true;
}
function breakUp(s, turnId) {
  s.romance.status = 'broke'; s.romance.score = 0;
  s.flags.breakups = (s.flags.breakups || 0) + 1;
  if (turnId === 'g3s1' || turnId === 'g3v1' || turnId === 'g3s2') s.flags.breakupG3 = true;
}

const HS_EVENTS = [
  { id: 'pc', w: s => (s.friendGroup === 'party' || s.friendGroup === 'gamers' ? 4 : hasHobby(s, 'game') ? 2 : 0.6),
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '오늘 PC방 콜?', `단톡방에 ${s.bestName}${jo(s.bestName, '이/가')} 올렸다. "오늘 학원 째고 PC방 ㄱ?" 다들 간다는 분위기다.`, [
        { id: 'go', label: '간다. 오늘 하루쯤은', tags: ['fun', 'social'] },
        { id: 'skip', label: '학원은 간다. 다음에 갈게', tags: ['study'] },
        { id: 'distance', label: '요즘 너무 노는 것 같다. 이 무리와 거리를 둔다', tags: ['study', 'self'] },
      ]);
      if (o.id === 'go') { inc(s, 'social', 6); inc(s, 'mental', 4); inc(s, 'lazy', 6); s.zC -= 0.03; L(s, '새벽 1시에 들어왔다. 다음 날 1교시부터 졸았다. 그래도 재밌었다.'); }
      if (o.id === 'skip') { inc(s, 'social', -2); inc(s, 'lazy', -2); L(s, '"ㅇㅋ 담에 와" 단톡방이 잠깐 조용해졌다.'); }
      if (o.id === 'distance') { inc(s, 'social', -10); inc(s, 'mental', -4); inc(s, 'lazy', -7); s.flags.distanced = true; L(s, '단톡방 알림을 껐다. 처음 몇 주는 어색하고 외로웠다.', 'warn'); }
    } },
  { id: 'confess', w: s => (s.romance.status !== 'dating' && (s.romance.count < 2) ? 0.8 + s.p.social * 0.35 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s, pt = newPartner(s, r);
      const o = choose(ctx, key, '갑작스러운 고백', `체육대회가 끝난 저녁, 같은 학년 ${pt.name}에게서 DM이 왔다. "나 너 좋아하는 것 같아. 사귈래?" ${pt.studious ? '전교권 성적의 성실한 아이다.' : '같이 있으면 웃긴 분위기 메이커다.'}`, [
        { id: 'yes', label: '사귄다', tags: ['romance'] },
        { id: 'no', label: '"미안, 지금은 공부에 집중하고 싶어"', tags: ['study', 'safe'] },
        { id: 'later', label: '"시험 끝나고 대답해도 될까?"', tags: ['safe'] },
      ]);
      if (o.id === 'yes') { startDating(s, pt.name, pt.studious); inc(s, 'mental', 10); L(s, `${pt.name}${jo(pt.name, '와/과')} 사귀기 시작했다. 하루 종일 폰만 본다.`, 'good'); }
      if (o.id === 'no') { inc(s, 'mental', -2); L(s, `${pt.name}${jo(pt.name, '은/는')} "알겠어"라고만 했다. 복도에서 마주칠 때마다 어색하다.`); }
      if (o.id === 'later') {
        if (r.chance(0.5)) { startDating(s, pt.name, pt.studious); L(s, `${pt.name}${jo(pt.name, '은/는')} 기다려 줬다. 시험이 끝난 날 사귀기 시작했다.`, 'good'); }
        else { inc(s, 'mental', -4); L(s, `시험이 끝났을 때 ${pt.name}에게는 이미 다른 사람이 있었다.`, 'warn'); }
      }
    } },
  { id: 'crush', w: s => (s.romance.status !== 'dating' && s.romance.count < 2 ? 0.9 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s, pt = newPartner(s, r), p = s.p;
      const o = choose(ctx, key, '짝사랑', `요즘 자꾸 ${pt.name}에게 눈이 간다. 수업 시간에도 생각난다.`, [
        { id: 'confess', label: '용기 내서 고백한다', tags: ['romance', 'risk'] },
        { id: 'keep', label: '마음속에만 담아 둔다', tags: ['safe'] },
        { id: 'fuel', label: '이 감정을 공부 동력으로 바꾼다', tags: ['study'] },
      ]);
      if (o.id === 'confess') {
        const ok = r.chance(0.28 + p.social * 0.06 + p.confidence * 0.04);
        if (ok) { startDating(s, pt.name, pt.studious); inc(s, 'mental', 14); L(s, `"사실 나도." ${pt.name}${jo(pt.name, '이/가')} 웃었다.`, 'good'); }
        else { inc(s, 'mental', -14); inc(s, 'social', -3); s.flags.rejected = true; L(s, '거절당했다. 다음 날 반 애들이 다 알고 있었다.', 'bad'); }
      }
      if (o.id === 'keep') { inc(s, 'lazy', 3); inc(s, 'mental', -2); L(s, '말 못 한 마음은 생각보다 오래 갔다.'); }
      if (o.id === 'fuel') { if (p.diligence >= 3) { s.zN += 0.04; L(s, '이상하게 집중이 잘 됐다. 멋있는 사람이 되고 싶었다.', 'good'); } else { inc(s, 'lazy', 3); L(s, '공부하려고 앉으면 그 사람 인스타를 보고 있었다.', 'warn'); } }
    } },
  { id: 'dateExam', w: s => (s.romance.status === 'dating' ? 3 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s, nm = s.romance.partner;
      const o = choose(ctx, key, '시험 2주 전, 데이트 신청', `${nm}${jo(nm, '이/가')} "이번 주말에 영화 보자"고 한다. 기말까지 2주.`, [
        { id: 'go', label: '간다. 하루쯤은 괜찮다', tags: ['romance'] },
        { id: 'study', label: '"스터디카페 같이 가자"', tags: ['study', 'romance'] },
        { id: 'no', label: '"시험 끝나고 보자"', tags: ['study'] },
      ]);
      if (o.id === 'go') { s.romance.score += 10; inc(s, 'mental', 5); s.zN -= 0.04; L(s, '영화 보고, 밥 먹고, 카페까지. 집에 오니 밤 11시였다.'); }
      if (o.id === 'study') {
        if (s.romance.studious) { s.zN += 0.03; s.romance.score += 6; L(s, `${nm}${jo(nm, '은/는')} 진짜 공부했다. 덩달아 나도 했다.`, 'good'); }
        else { s.zN -= 0.015; s.romance.score += 4; L(s, '결국 둘이 수다만 떨다 나왔다.'); }
      }
      if (o.id === 'no') {
        s.romance.score -= 14; s.zN += 0.025;
        if (s.romance.score < 30 && r.chance(0.5)) { breakUp(s, ctx.turn.id); inc(s, 'mental', -12); L(s, `"너는 맨날 공부가 먼저지." 그날 ${nm}${jo(nm, '와/과')} 헤어졌다.`, 'bad'); }
        else L(s, `${nm}${jo(nm, '이/가')} 서운해했다.`, 'warn');
      }
    } },
  { id: 'breakup', w: s => (s.romance.status === 'dating' && s.romance.since >= 1 ? 1 + (100 - s.romance.score) / 50 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s, nm = s.romance.partner;
      const o = choose(ctx, key, '이별 통보', `밤 12시, ${nm}에게서 긴 메시지가 왔다. "우리 잠깐 시간을 갖자. 요즘 너무 지쳐."`, [
        { id: 'hold', label: '붙잡는다', tags: ['romance'] },
        { id: 'cool', label: '"알겠어. 그동안 고마웠어."', tags: ['safe'] },
        { id: 'grind', label: '헤어지고 독하게 공부에 몰두한다', tags: ['study'] },
      ]);
      if (o.id === 'hold' && r.chance(0.45)) { s.romance.score = 35; inc(s, 'mental', -6); L(s, '밤새 통화했다. 일단은 다시 만나기로 했다. 불안하다.', 'warn'); return; }
      breakUp(s, ctx.turn.id);
      if (o.id === 'hold') { inc(s, 'mental', -16); L(s, '붙잡았지만 소용없었다. 몇 주 동안 아무것도 손에 안 잡혔다.', 'bad'); }
      if (o.id === 'cool') { inc(s, 'mental', -9 + s.p.grit); L(s, '덤덤한 척했다. 혼자 있을 때만 울었다.', 'bad'); }
      if (o.id === 'grind') { inc(s, 'mental', -11); if (s.p.grit >= 4) { s.zC += 0.06; s.flags.fireUp = true; L(s, '이를 악물었다. 성적으로 보여 주겠다고.', 'good'); } else { inc(s, 'lazy', 5); L(s, '공부하겠다고 앉았지만, 자꾸 옛날 사진을 봤다.', 'bad'); } }
    } },
  { id: 'parentTalk', w: s => (s.p.pStyle === 'strict' || s.p.pStyle === 'anxious' ? 2.4 : 1),
    run: (ctx, key, r) => {
      const s = ctx.s, p = s.p, pw = parentWord(s);
      const line = { strict: '"이 성적으로 대학 가겠니? 핸드폰 내놔."', anxious: '"엄마가 다 알아봤는데, 이렇게 하면 망한대. 학원 하나 더 다니자."', warm: '"요즘 힘들지? 엄마는 네가 행복했으면 좋겠어."', lax: '"알아서 해. 네 인생이니까."', absent: '"바빠서 미안. 성적은 어때? 잘하고 있지?"' }[p.pStyle];
      const o = choose(ctx, key, '성적표가 나온 날', `${pw}${jo(pw, '이/가')} 말했다. ${line}`, [
        { id: 'promise', label: '"다음엔 꼭 올릴게요."', tags: ['obey'] },
        { id: 'rebel', label: '"제 인생이에요! 그만 좀 하세요!"', tags: ['rebel'] },
        { id: 'talk', label: '하고 싶은 진로 이야기를 차분히 꺼낸다', tags: ['self'] },
      ]);
      if (o.id === 'promise') { s.pressure += 4; inc(s, 'parentRel', 4); if (p.diligence >= 3) inc(s, 'lazy', -3); L(s, '약속은 했다. 지킬 수 있을지는 모르겠다.'); }
      if (o.id === 'rebel') { inc(s, 'parentRel', -15); inc(s, 'mental', -4); s.autonomy += 1; s.flags.rebel = (s.flags.rebel || 0) + 1; L(s, '문을 쾅 닫고 들어왔다. 며칠 동안 밥을 따로 먹었다.', 'bad'); }
      if (o.id === 'talk') {
        const ok = p.pStyle === 'warm' || p.pStyle === 'lax' || r.chance(0.25 + p.confidence * 0.05);
        if (ok) { inc(s, 'parentRel', 8); s.pressure -= 5; s.autonomy += 1; s.flags.parentHeard = true; L(s, `처음으로 ${pw}${jo(pw, '이/가')} 끝까지 들어 줬다.`, 'good'); }
        else { inc(s, 'parentRel', -6); L(s, '"그런 건 대학 가서 생각해." 대화는 3분 만에 끝났다.', 'warn'); }
      }
    } },
  { id: 'tutor', w: s => (s.p.wealth !== 'low' && ['med', 'prestige', 'law'].indexOf(s.p.pDesire) >= 0 ? 2 : s.p.wealth === 'high' ? 0.8 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, p = s.p;
      const o = choose(ctx, key, '1타 과외', `${parentWord(s)}${jo(parentWord(s), '이/가')} 말했다. "대치동 유명 선생님 과외 자리가 났어. 한 달에 200이야. 해 볼래?"`, [
        { id: 'yes', label: '한다', tags: ['obey', 'study'] },
        { id: 'self', label: '"혼자 해 볼게요."', tags: ['self', 'rebel'] },
        { id: 'online', label: '"인강으로 할게요. 돈 아까워요."', tags: ['safe', 'self'] },
      ]);
      if (o.id === 'yes') { s.money -= 16; s.zC += 0.1 * p.comprehension / 3; s.zN += 0.05; inc(s, 'stress', 7); inc(s, 'parentRel', 5); s.autonomy -= 1; L(s, '선생님은 확실히 달랐다. 대신 숙제가 하루 4시간 분량이다.'); }
      if (o.id === 'self') { inc(s, 'parentRel', -5); s.autonomy += 1; if (p.diligence >= 4) { s.zC += 0.05; L(s, '혼자 해 보겠다고 한 말을 지키려고 더 독하게 했다.', 'good'); } else L(s, '혼자 하겠다고 했지만, 혼자는 생각보다 어려웠다.', 'warn'); }
      if (o.id === 'online') { s.money -= 2; s.zC += 0.035 * p.diligence / 3; L(s, '인강 패스를 끊었다. 완강률이 관건이다.'); }
    } },
  { id: 'compare', w: s => (s.p.sibling === 'better' ? 2 : s.p.pDesire === 'prestige' ? 1.2 : 0.3), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const who = s.p.sibling === 'better' ? '형(언니)' : '사촌';
      const o = choose(ctx, key, '명절의 비교', `명절. 친척들 앞에서 ${who} 얘기가 나왔다. "${who === '사촌' ? '○○이는 이번에 의대 붙었다며?' : '너희 형(언니)은 전교 1등이었잖아.'}" 모두의 시선이 나에게 왔다.`, [
        { id: 'fuel', label: '두고 보라지. 오기가 생긴다', tags: ['study', 'rebel'] },
        { id: 'shrug', label: '웃어넘긴다', tags: ['safe'] },
        { id: 'tell', label: '집에 와서 부모님께 서운했다고 말한다', tags: ['self'] },
      ]);
      if (o.id === 'fuel') { s.zN += 0.03; s.zC += 0.03; inc(s, 'stress', 10); L(s, '그날부터 독서실 마감까지 있었다. 마음 한구석은 계속 쓰렸다.'); }
      if (o.id === 'shrug') { inc(s, 'mental', -4); L(s, '웃었지만 밤에 잠이 잘 안 왔다.'); }
      if (o.id === 'tell') { const ok = s.p.pStyle !== 'strict' || r.chance(0.3); if (ok) { inc(s, 'parentRel', 7); s.pressure -= 4; L(s, '"미안해. 엄마 아빠가 생각이 짧았어."', 'good'); } else { inc(s, 'parentRel', -5); L(s, '"그게 다 너 잘되라고 하는 말이야."', 'warn'); } }
    } },
  { id: 'push', w: s => { const d = PARENT_DESIRES[s.p.pDesire]; return d && d.field && topInterest(s) !== d.field ? 2.2 : 0; }, once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, p = s.p, d = PARENT_DESIRES[p.pDesire], my = topInterest(s);
      const o = choose(ctx, key, '부모님이 정한 진로', `"너는 ${FIELDS[d.field].name} 쪽으로 가야 해. 그게 다 너 잘되라고 하는 거야." 나는 ${FIELDS[my].name} 쪽에 더 끌린다.`, [
        { id: 'obey', label: '부모님 뜻을 따른다', tags: ['obey', 'safe'] },
        { id: 'persuade', label: '내 계획을 정리해서 설득한다', tags: ['self', 'risk'] },
        { id: 'secret', label: '말은 안 하고 몰래 내 길을 준비한다', tags: ['rebel', 'self'] },
      ]);
      if (o.id === 'obey') { s.flags.obeyParent = true; s.interest[d.field] += 14; s.autonomy -= 2; inc(s, 'parentRel', 8); if (fitOf(s, d.field) < 0.7) inc(s, 'mental', -5); L(s, `"알겠어요." ${FIELDS[d.field].name} 쪽으로 생기부 방향을 틀었다.`); }
      if (o.id === 'persuade') {
        const ok = r.chance((p.pStyle === 'warm' ? 0.7 : p.pStyle === 'lax' ? 0.65 : 0.22) + p.confidence * 0.04 + (s.recFit[my] > 15 ? 0.15 : 0));
        if (ok) { s.flags.parentAccept = true; s.pressure -= 10; s.autonomy += 2; inc(s, 'parentRel', 5); L(s, `한참 듣던 ${parentWord(s)}${jo(parentWord(s), '이/가')} 말했다. "그래, 네가 그렇게까지 생각했으면."`, 'good'); }
        else { inc(s, 'parentRel', -9); inc(s, 'stress', 6); L(s, '"현실을 몰라서 그래." 설득은 실패했다.', 'bad'); }
      }
      if (o.id === 'secret') { s.flags.secretPath = true; s.autonomy += 1; s.recFit[my] += 6; inc(s, 'stress', 6); inc(s, 'parentRel', -2); L(s, '부모님 몰래 원하는 분야 탐구 보고서를 쓰기 시작했다.'); }
    } },
  { id: 'crisis', w: s => (s.p.wealth === 'high' ? 0.1 : s.p.wealth === 'low' ? 0.8 : 0.4), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      s.money = Math.max(0, s.money - 25); s.flags.crisis = true;
      const o = choose(ctx, key, '집안 사정', '아빠 회사가 어려워졌다. 밤마다 부모님 목소리가 높아진다. 학원을 끊어야 할 수도 있다.', [
        { id: 'work', label: '주말 알바를 시작한다', tags: ['work', 'kind'] },
        { id: 'focus', label: '공부로 보답하겠다고 더 독하게 한다', tags: ['study'] },
        { id: 'ignore', label: '모른 척한다. 내가 할 수 있는 게 없다', tags: ['safe'] },
      ]);
      if (o.id === 'work') { s.money += 8; s.flags.work = true; s.zN -= 0.04; inc(s, 'parentRel', 8); s.flags.mature = true; L(s, '주말마다 식당에서 일했다. 엄마가 몰래 울었다는 걸 나중에 알았다.'); }
      if (o.id === 'focus') { inc(s, 'stress', 12); if (s.p.grit >= 3) { s.zN += 0.04; L(s, '독서실에서 버텼다. 그게 내가 할 수 있는 전부였다.', 'good'); } else { inc(s, 'mental', -9); L(s, '집중이 안 됐다. 집에 들어가기 싫었다.', 'bad'); } }
      if (o.id === 'ignore') { inc(s, 'parentRel', -4); inc(s, 'mental', -4); L(s, '이어폰 볼륨을 키웠다.'); }
    } },
  { id: 'phone', w: s => (s.lazy >= 38 ? s.lazy / 22 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '스크린타임 7시간', '새벽 3시. 숏폼을 "딱 하나만" 보다가 4시간이 지났다. 이번 주 하루 평균 스크린타임 7시간 12분.', [
        { id: 'lock', label: '앱 잠금을 걸고 공부 타이머를 켠다', tags: ['study', 'self'] },
        { id: 'ignore', label: '다들 이 정도는 하잖아', tags: ['fun'] },
        { id: 'parent', label: '부모님께 폰을 맡긴다', tags: ['obey', 'study'] },
      ]);
      if (o.id === 'lock') { const d = s.p.diligence >= 3 ? 14 : 6; inc(s, 'lazy', -d); inc(s, 'mental', -2); L(s, d > 10 ? '사흘은 금단 증상이 있었다. 일주일 뒤엔 시간이 생겼다.' : '앱 잠금은 3일 만에 풀었다.', d > 10 ? 'good' : 'warn'); }
      if (o.id === 'ignore') { inc(s, 'lazy', 8); inc(s, 'health', -5); L(s, '다음 날도, 그다음 날도 똑같았다.', 'bad'); }
      if (o.id === 'parent') { inc(s, 'lazy', -12); inc(s, 'parentRel', 3); inc(s, 'social', -3); L(s, '단톡방 소식을 몰라 조금 소외됐지만 공부 시간은 늘었다.', 'good'); }
    } },
  { id: 'rank', w: s => (hasHobby(s, 'game') ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '랭크 상위 1%', '랭크게임 상위 1% 달성. 친구들이 "너 프로 해 봐"라고 한다.', [
        { id: 'pro', label: '진지하게 프로를 꿈꿔 본다', tags: ['risk', 'fun'] },
        { id: 'quit', label: '고등학생이니까. 게임을 지운다', tags: ['study'] },
        { id: 'mod', label: '적당히 즐긴다', tags: ['safe'] },
      ]);
      if (o.id === 'pro') { s.flags.proDream = true; s.talent.game = clamp(s.talent.game + 20, 0, 100); inc(s, 'lazy', 8); s.zC -= 0.05; inc(s, 'parentRel', -8); L(s, '하루 8시간씩 랭크를 돌렸다. 부모님과 매일 싸웠다.', 'warn'); }
      if (o.id === 'quit') { inc(s, 'lazy', -12); inc(s, 'mental', -6); inc(s, 'social', -3); L(s, '계정을 지웠다. 한동안 허전했다.'); }
      if (o.id === 'mod') { inc(s, 'mental', 4); inc(s, 'lazy', 2); L(s, '주말에만 하기로 했다. 대체로는 지켰다.'); }
    } },
  { id: 'esports', w: s => (s.flags.proDream && s.talent.game >= 60 ? 2.5 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '프로팀 아카데미 제안', 'e스포츠 프로팀 아카데미에서 DM이 왔다. "테스트 한번 받아 볼래요? 합격하면 숙소 생활이에요."', [
        { id: 'go', label: '간다. 이건 기회다', tags: ['risk'] },
        { id: 'no', label: '거절한다. 대학은 가야지', tags: ['safe', 'obey'] },
      ]);
      if (o.id === 'go') { s.flags.esports = true; inc(s, 'parentRel', -15); s.zN -= 0.25; s.zC -= 0.2; L(s, '테스트에 붙었다. 학교는 출석만 했다. 부모님은 반대했다.', 'warn'); }
      else L(s, '정중히 거절했다. 가끔 그 DM을 다시 열어 본다.');
    } },
  { id: 'casting', w: s => ((hasHobby(s, 'music') || hasHobby(s, 'idol')) && s.p.social >= 3 && s.turnIdx <= 6 ? 0.8 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '길거리 캐스팅', '홍대 앞에서 기획사 명함을 받았다. "오디션 한번 볼래요?"', [
        { id: 'aud', label: '오디션을 본다', tags: ['risk', 'fun'] },
        { id: 'no', label: '수상하다. 무시한다', tags: ['safe'] },
      ]);
      if (o.id === 'aud') {
        if (r.chance(s.talent.perf / 130)) { s.flags.trainee = true; inc(s, 'parentRel', -6); s.zN -= 0.1; L(s, '연습생 계약 제안을 받았다. 심장이 터질 것 같다.', 'good'); }
        else { inc(s, 'mental', -6); L(s, '"아직은 부족하네요." 노래 연습을 더 하고 싶어졌다.'); s.talent.perf += 6; }
      } else L(s, '명함은 서랍 속에 들어갔다.');
    } },
  { id: 'contest', w: s => (s.turnIdx <= 8 ? 1.4 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s, ti = topInterest(s);
      const o = choose(ctx, key, '교내 탐구대회', `교내 탐구보고서 대회 공고가 붙었다. 주제는 자유. ${FIELDS[ti].name} 쪽으로 써 볼 수 있다.`, [
        { id: 'join', label: '참가한다 (시험 기간과 겹친다)', tags: ['record'] },
        { id: 'skip', label: '패스. 내신이 먼저다', tags: ['study', 'safe'] },
      ]);
      if (o.id === 'join') {
        s.record += 7; s.recFit[ti] += 9; inc(s, 'stress', 4); s.zN -= 0.02;
        if (r.chance(0.18 + s.p.curiosity * 0.07)) { s.record += 6; s.flags.award = (s.flags.award || 0) + 1; L(s, '금상을 받았다! 세특에 들어갈 문장이 생겼다.', 'good'); }
        else L(s, '입상은 못 했지만 보고서는 생기부에 남았다.');
      } else L(s, '대회는 건너뛰었다.');
    } },
  { id: 'council', w: s => (s.p.social >= 3 && s.turnIdx <= 6 ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '학생회 선거', '학생회 부회장 후보 추천이 들어왔다.', [
        { id: 'run', label: '출마한다', tags: ['risk', 'social', 'record'] },
        { id: 'no', label: '시간 아깝다. 안 나간다', tags: ['study'] },
      ]);
      if (o.id === 'run') {
        if (r.chance(0.3 + s.p.social * 0.09)) { s.record += 10; s.talent.people += 10; inc(s, 'stress', 6); s.flags.council = true; L(s, '당선됐다. 리더십 항목에 쓸 게 생겼다. 대신 바빠졌다.', 'good'); }
        else { inc(s, 'mental', -5); L(s, '아깝게 떨어졌다.'); }
      }
    } },
  { id: 'burnout', w: s => (s.stress >= 62 || s.mental <= 32 ? 3.5 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '번아웃', '아무것도 하기 싫다. 책을 펴도 글자가 안 들어온다. 이유 없이 눈물이 난다.', [
        { id: 'counsel', label: 'Wee클래스 상담실 문을 두드린다', tags: ['self', 'rest'] },
        { id: 'rest', label: '일주일 동안 공부를 내려놓고 쉰다', tags: ['rest'] },
        { id: 'push', label: '버틴다. 남들도 다 힘들다', tags: ['study'] },
      ]);
      if (o.id === 'counsel') { inc(s, 'mental', 16); inc(s, 'stress', -16); L(s, '상담 선생님 앞에서 처음으로 힘들다고 말했다. 조금 가벼워졌다.', 'good'); }
      if (o.id === 'rest') { inc(s, 'stress', -22); inc(s, 'mental', 10); s.zN -= 0.03; L(s, '죄책감이 들었지만, 다시 책을 펼 수 있게 됐다.'); }
      if (o.id === 'push') { inc(s, 'stress', 10); inc(s, 'mental', -10); s.flags.burnout = (s.flags.burnout || 0) + 1; if (s.p.grit >= 4) { s.zN += 0.03; L(s, '버텼다. 대신 웃는 일이 줄었다.'); } else { inc(s, 'health', -10); L(s, '버티다 결국 몸살이 났다.', 'bad'); } }
    } },
  { id: 'cheat', w: s => (s.friendGroup === 'party' || s.friendGroup === 'gamers' ? 1.2 : 0.5), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '수행평가 베끼기', `${s.bestName}${jo(s.bestName, '이/가')} 말했다. "네 보고서 좀 보여 줘. 살짝 바꿔서 낼게."`, [
        { id: 'give', label: '보여 준다', tags: ['social', 'fun'] },
        { id: 'no', label: '거절한다', tags: ['safe'] },
        { id: 'teach', label: '같이 쓰는 법을 알려준다', tags: ['kind'] },
      ]);
      if (o.id === 'give') { if (r.chance(0.3)) { s.record -= 12; inc(s, 'parentRel', -8); inc(s, 'mental', -8); s.flags.caught = true; L(s, '선생님에게 걸렸다. 둘 다 0점. 행동특성란이 걱정된다.', 'bad'); } else { inc(s, 'social', 4); L(s, '무사히 넘어갔다. 찜찜했다.'); } }
      if (o.id === 'no') { inc(s, 'social', -5); L(s, '"치사하네." 며칠 동안 서먹했다.'); }
      if (o.id === 'teach') { inc(s, 'social', 4); s.record += 2; s.talent.people += 4; L(s, '둘이 같이 밤새 썼다. 우정이 조금 깊어졌다.', 'good'); }
    } },
  { id: 'fight', w: s => (s.bestFriend ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, b = s.bestName;
      const o = choose(ctx, key, '절친과의 싸움', `${b}${jo(b, '와/과')} 크게 싸웠다. 사소한 오해였는데 말이 심해졌다.`, [
        { id: 'sorry', label: '먼저 사과한다', tags: ['kind', 'social'] },
        { id: 'wait', label: '상대가 먼저 오길 기다린다', tags: ['safe'] },
        { id: 'cut', label: '이참에 손절한다', tags: ['rebel'] },
      ]);
      if (o.id === 'sorry') { inc(s, 'social', 5); inc(s, 'mental', 3); s.flags.friendForever = true; L(s, `"나도 미안해." ${b}${jo(b, '와/과')} 편의점 앞에서 라면을 먹었다.`, 'good'); }
      if (o.id === 'wait') { if (r.chance(0.5)) { L(s, `${b}${jo(b, '이/가')} 먼저 연락했다. 다행이다.`); } else { s.bestFriend = false; s.flags.lostBest = true; inc(s, 'social', -10); inc(s, 'mental', -8); L(s, '아무도 먼저 연락하지 않았다. 그렇게 멀어졌다.', 'bad'); } }
      if (o.id === 'cut') { s.bestFriend = false; s.flags.lostBest = true; inc(s, 'mental', -6); inc(s, 'social', -6); L(s, '차단 버튼을 눌렀다.', 'bad'); }
    } },
  { id: 'studyGroup', w: s => (s.friendGroup === 'rival' ? 2 : s.p.social >= 3 ? 0.8 : 0.3), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, nm = r.pick(FRIEND_NAMES.filter(n => n !== s.bestName));
      const o = choose(ctx, key, '전교 1등의 스터디 제안', `전교 1등 ${nm}${jo(nm, '이/가')} "같이 수학 스터디 할래?"라고 물었다.`, [
        { id: 'join', label: '한다', tags: ['study', 'social'] },
        { id: 'no', label: '혼자가 편하다', tags: ['self'] },
      ]);
      if (o.id === 'join') { s.zC += 0.05; s.zN += 0.035; inc(s, 'stress', 5); inc(s, 'social', 3); s.flags.studyGroup = true; L(s, '푸는 방식이 완전히 달랐다. 자극을 많이 받았다.', 'good'); }
      else L(s, '혼자 하는 게 맞다고 생각했다.');
    } },
  { id: 'bully', w: () => 0.6, once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '따돌림을 봤다', '반에서 한 친구가 은근히 따돌림당하고 있다. 다들 모른 척한다.', [
        { id: 'help', label: '먼저 말을 걸고 같이 다닌다', tags: ['kind', 'risk'] },
        { id: 'report', label: '담임 선생님께 조용히 알린다', tags: ['kind', 'safe'] },
        { id: 'ignore', label: '괜히 끼어들었다 나까지 당할라', tags: ['safe'] },
      ]);
      if (o.id === 'help') { inc(s, 'social', -3); inc(s, 'mental', 4); s.talent.people += 6; s.record += 3; s.interest.soc += 6; s.flags.kind = true; L(s, '그 친구가 나중에 말했다. "그때 너 아니었으면 자퇴했을 거야."', 'good'); }
      if (o.id === 'report') { s.flags.kind = true; inc(s, 'mental', 2); L(s, '선생님이 조용히 해결해 주셨다.'); }
      if (o.id === 'ignore') { inc(s, 'mental', -3); s.flags.ignoredBully = true; L(s, '그 친구는 다음 학기에 전학을 갔다. 가끔 생각난다.', 'warn'); }
    } },
  { id: 'youtube', w: s => (hasHobby(s, 'video') ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '알고리즘의 선택', '취미로 올린 영상이 알고리즘을 탔다. 조회수 34만, 구독자 1.2만.', [
        { id: 'grow', label: '채널을 본격적으로 키운다', tags: ['risk', 'fun'] },
        { id: 'bal', label: '주 1회만 올린다', tags: ['safe'] },
        { id: 'stop', label: '고등학생이니까 접는다', tags: ['study'] },
      ]);
      if (o.id === 'grow') { s.flags.creator = (s.flags.creator || 0) + 2; s.talent.media += 15; inc(s, 'lazy', 4); s.zN -= 0.06; L(s, '편집하느라 새벽 3시에 잔다. 댓글 보는 게 제일 재밌다.'); }
      if (o.id === 'bal') { s.flags.creator = (s.flags.creator || 0) + 1; s.talent.media += 7; L(s, '공부와 채널 사이에서 줄타기 중이다.'); }
      if (o.id === 'stop') { inc(s, 'mental', -3); L(s, '채널을 비공개로 돌렸다.'); }
    } },
  { id: 'coding', w: s => (hasHobby(s, 'code') ? 2 : s.interest.cs > 30 ? 0.6 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '청소년 해커톤', '청소년 해커톤 공고가 떴다. 2박 3일, 기말 1주 전.', [
        { id: 'join', label: '나간다', tags: ['record', 'risk'] },
        { id: 'skip', label: '시험이 먼저다', tags: ['study'] },
      ]);
      if (o.id === 'join') { s.talent.code += 12; s.recFit.cs += 12; s.record += 5; s.zN -= 0.03; if (r.chance(0.2 + s.talent.code / 250)) { s.flags.award = (s.flags.award || 0) + 1; s.record += 6; L(s, '우수상! 개발자가 되고 싶다는 마음이 확실해졌다.', 'good'); } else L(s, '상은 못 탔지만 처음으로 서비스 하나를 끝까지 만들었다.'); s.interest.cs += 8; }
    } },
  { id: 'artAcademy', w: s => (hasHobby(s, 'draw') || hasHobby(s, 'webtoon') ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '미대 입시', '미술 선생님이 말씀하셨다. "너 그림 감각 있어. 입시미술 해 볼 생각 없니?" 입시미술 학원은 한 달에 80만 원.', [
        { id: 'yes', label: '미대 입시를 준비한다', tags: ['risk', 'self'] },
        { id: 'hobby', label: '그림은 취미로 남긴다', tags: ['safe'] },
      ]);
      if (o.id === 'yes') { s.flags.artPath = true; s.money -= 10; s.talent.art += 15; s.interest.art += 15; s.zN -= 0.04; if (s.p.pDesire !== 'free') inc(s, 'parentRel', -6); L(s, '주 4일 입시미술 학원에 다닌다. 손에 늘 물감이 묻어 있다.'); }
      else L(s, '스케치북은 책상 서랍 깊숙이 들어갔다.');
    } },
  { id: 'sportsTeam', w: s => (hasHobby(s, 'sport') ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '체대 입시', '체육 선생님이 "체대 입시 생각 있니? 실기 학원 다니면 승산 있어"라고 하셨다.', [
        { id: 'yes', label: '체대 입시를 준비한다', tags: ['risk', 'self'] },
        { id: 'no', label: '운동은 취미로', tags: ['safe'] },
      ]);
      if (o.id === 'yes') { s.flags.sportPath = true; s.money -= 6; s.talent.sport += 15; s.interest.sport += 15; L(s, '방과 후엔 실기 학원. 몸은 힘든데 마음은 편하다.'); }
    } },
  { id: 'transfer', w: s => (s.p.school !== 'general' && s.naesinRec.length && s.naesinRec[s.naesinRec.length - 1] > 45 && s.turnIdx <= 4 ? 2.5 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '일반고 전학', '내신이 바닥이다. "일반고로 전학 가면 내신 2등급은 오른다"는 얘기를 들었다.', [
        { id: 'go', label: '일반고로 전학한다', tags: ['risk'] },
        { id: 'stay', label: '남는다. 학종에선 여기가 유리하다', tags: ['safe'] },
      ]);
      if (o.id === 'go') { s.p = Object.assign({}, s.p, { school: 'general' }); s.zN += 0.55; inc(s, 'social', -12); inc(s, 'mental', -4); s.flags.transferred = true; L(s, '새 학교에서는 반 3등이었다. 대신 친구가 하나도 없다.'); }
      else L(s, '버티기로 했다.');
    } },
  { id: 'mockShock', w: s => (s.turnIdx >= 4 ? 1.2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '모의고사 수학 4등급', '모의고사 수학이 4등급이 나왔다. 성적표를 보고 한참 멍했다.', [
        { id: 'review', label: '오답노트를 처음부터 다시 만든다', tags: ['study'] },
        { id: 'academy', label: '학원을 바꾼다', tags: ['obey'] },
        { id: 'giveup', label: '수학은 버리고 다른 과목에 올인', tags: ['fun', 'risk'] },
      ]);
      if (o.id === 'review') { s.zC += 0.045 * s.p.diligence / 3; L(s, '틀린 문제를 다시 풀다 보니 어디서 막히는지 보이기 시작했다.', 'good'); }
      if (o.id === 'academy') { s.money -= 5; s.zC += 0.025; L(s, '새 학원 레벨테스트에서 중간반에 배정됐다.'); }
      if (o.id === 'giveup') { s.flags.mathGiveUp = true; s.zC -= 0.08; inc(s, 'lazy', 4); inc(s, 'stress', -6); s.interest.hum += 4; L(s, '수포자 선언. 마음은 편해졌는데, 원서 쓸 때 후회할지도 모른다.', 'warn'); }
    } },
  { id: 'sick', w: () => 0.25, once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '엄마의 입원', '엄마가 갑자기 쓰러져 입원하셨다. 수술은 잘 됐지만 한 달은 병원에 계셔야 한다.', [
        { id: 'care', label: '학원을 빼고 병원과 집안일을 챙긴다', tags: ['kind'] },
        { id: 'focus', label: '걱정 끼치지 않게 공부에 집중한다', tags: ['study'] },
      ]);
      if (o.id === 'care') { inc(s, 'parentRel', 14); s.zN -= 0.05; s.flags.mature = true; L(s, '병원 침대 옆에서 문제집을 풀었다. 엄마 손이 생각보다 작았다.'); }
      else { inc(s, 'stress', 8); inc(s, 'parentRel', -2); L(s, '"엄마 괜찮아. 공부해." 그 말이 더 마음에 걸렸다.'); }
    } },
  { id: 'partTime', w: s => (s.money < 35 && s.turnIdx <= 8 ? 1.5 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '알바 제안', '친구가 일하는 카페에서 주말 알바를 구한다. 시급 1만 원대.', [
        { id: 'take', label: '한다. 용돈이 필요하다', tags: ['work'] },
        { id: 'no', label: '공부할 시간이 줄어든다. 안 한다', tags: ['study'] },
      ]);
      if (o.id === 'take') { s.money += 10; s.flags.work = true; s.zN -= 0.03; L(s, '주말이 사라졌다. 통장에 돈이 쌓이는 건 좋다.'); }
    } },
  { id: 'sleep', w: s => (s.stress >= 48 || s.lazy >= 42 ? 1.2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '새벽 2시 취침', '매일 새벽 2시에 자고 6시 반에 일어난다. 오후 수업은 기억이 없다.', [
        { id: 'fix', label: '12시 전에 자기로 한다', tags: ['rest', 'self'] },
        { id: 'keep', label: '잠은 대학 가서 자면 된다', tags: ['study'] },
      ]);
      if (o.id === 'fix') { inc(s, 'health', 10); inc(s, 'lazy', -3); inc(s, 'mental', 4); L(s, '수업 시간에 깨어 있게 됐다. 이게 이렇게 큰 차이일 줄이야.', 'good'); }
      else { inc(s, 'health', -11); s.zN += 0.01; L(s, '커피와 에너지 드링크로 버틴다.', 'warn'); }
    } },
  { id: 'sns', w: s => (s.p.social >= 3 ? 0.8 : 0.3), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '단톡방 뒷담화', '내 뒷담화를 한 단톡방 캡처가 돌았다. 친하다고 생각한 애도 있었다.', [
        { id: 'confront', label: '직접 따진다', tags: ['rebel'] },
        { id: 'ignore', label: '모른 척한다', tags: ['safe'] },
        { id: 'adult', label: '신경 쓸 사람만 신경 쓴다. 내 사람들에게 집중한다', tags: ['self'] },
      ]);
      if (o.id === 'confront') { inc(s, 'social', -5); inc(s, 'mental', r.chance(0.5) ? 4 : -8); L(s, '말다툼이 커졌다. 반 분위기가 갈렸다.'); }
      if (o.id === 'ignore') { inc(s, 'mental', -8); L(s, '아무렇지 않은 척했다. 하나도 안 괜찮았다.', 'bad'); }
      if (o.id === 'adult') { inc(s, 'mental', s.p.grit >= 3 ? -2 : -6); inc(s, 'social', 2); L(s, '진짜 친구가 누군지 알게 됐다.'); }
    } },
  { id: 'careerDay', w: s => (s.turnIdx <= 6 ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, a = topInterest(s), d = PARENT_DESIRES[s.p.pDesire].field;
      const others = FIELD_KEYS.filter(f => f !== a && f !== d);
      const x = r.pick(others), y = r.pick(others.filter(f => f !== x));
      const fs = [a, d, x, y].filter((f, i, arr) => f && arr.indexOf(f) === i).slice(0, 3);
      const o = choose(ctx, key, '진로 특강', '진로의 날. 현직자 특강 세 개 중 하나를 들어야 한다.', fs.map(f => ({ id: f, label: `${FIELDS[f].name} 현직자 특강`, tags: f === a ? ['self'] : f === d ? ['obey'] : ['risk'] })));
      s.interest[o.id] += 12; s.flags.clarity = (s.flags.clarity || 0) + 1;
      L(s, `${FIELDS[o.id].name} 현직자의 하루를 들었다. ${fitOf(s, o.id) > 0.8 ? '"바로 이거다" 싶었다.' : '생각보다 현실적인 이야기가 많았다.'}`);
    } },
  { id: 'concert', w: s => (hasHobby(s, 'idol') ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '티켓팅 성공', '최애 콘서트 티켓팅에 성공했다! 그런데 공연 날이 중간고사 전날이다.', [
        { id: 'go', label: '간다. 이건 못 참는다', tags: ['fun'] },
        { id: 'sell', label: '눈물을 머금고 양도한다', tags: ['study'] },
      ]);
      if (o.id === 'go') { inc(s, 'mental', 12); s.zN -= 0.04; L(s, '인생 최고의 밤이었다. 시험은... 그럭저럭.'); }
      else { inc(s, 'mental', -6); s.zN += 0.01; L(s, '공연 날 밤, 트위터로 후기만 봤다.'); }
    } },
  { id: 'teacher', w: () => 0.4, once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '담임의 탐구 주제 제안', `담임 선생님이 "${FIELDS[topInterest(s)].name} 쪽이면 이 주제로 탐구해서 세특에 넣어 보자"고 하셨다.`, [
        { id: 'follow', label: '선생님 주제로 한다', tags: ['obey', 'record'] },
        { id: 'own', label: '내가 궁금한 주제로 바꿔 본다', tags: ['self', 'record'] },
        { id: 'no', label: '공부할 시간도 없다', tags: ['study'] },
      ]);
      const ti = topInterest(s);
      if (o.id === 'follow') { s.record += 6; s.recFit[ti] += 6; L(s, '무난한 보고서가 나왔다.'); }
      if (o.id === 'own') { s.record += 3 + s.p.curiosity * 2; s.recFit[ti] += 9; s.interest[ti] += 4; L(s, s.p.curiosity >= 4 ? '선생님이 "이거 너만 쓸 수 있는 보고서다"라고 하셨다.' : '주제를 바꿨더니 생각보다 어려웠다.', s.p.curiosity >= 4 ? 'good' : 'info'); }
    } },
];

function randomEvents(ctx, turn, n) {
  const s = ctx.s, r = makeRng(s.seed, turn.id + ':ev');
  const count = n != null ? n : (r.chance(0.5) ? 2 : 1);
  for (let k = 0; k < count; k++) {
    const pool = HS_EVENTS.filter(e => !(e.once && s.seen[e.id]) && !s.seen[turn.id + e.id]);
    const ws = pool.map(e => Math.max(0, e.w(s)));
    const tot = ws.reduce((a, b) => a + b, 0);
    if (tot <= 0) return;
    let x = r.next() * tot, ev = pool[0];
    for (let i = 0; i < pool.length; i++) { x -= ws[i]; if (x <= 0) { ev = pool[i]; break; } }
    s.seen[ev.id] = true; s.seen[turn.id + ev.id] = true;
    ctx.turn = turn;
    ev.run(ctx, turn.id + ':ev:' + ev.id, makeRng(s.seed, turn.id + ':' + ev.id));
  }
}

function semesterTurn(ctx, turn) {
  const s = ctx.s;
  fixedEvents(ctx, turn);
  const cats = allocCats(s, turn);
  const def = defaultAlloc(s, cats);
  const raw = ask(ctx, { type: 'alloc', key: turn.id + ':alloc', title: turn.label + ' 시간 쓰기',
    text: '이번 학기, 하루를 10칸으로 나눠 어디에 쓸지 정하자. 작은 차이도 쌓이면 결과가 달라진다.', cats, def, total: 10 });
  const a = normAlloc(raw, cats);
  ['study', 'academy', 'activity', 'hobby', 'friends', 'rest', 'date', 'work'].forEach(k => { if (a[k] == null) a[k] = 0; });
  s.lastAlloc = a;
  randomEvents(ctx, turn);
  semesterEffects(ctx, turn, a);
}

// ── 원서 ───────────────────────────────────────────────
const TYPE_NAMES = { gyogwa: '학생부교과', jonghap: '학생부종합', nonsul: '논술', silgi: '실기', jungsi: '정시' };
function studentZ(s, type, field) {
  const p = s.p, zNavg = zFromTop(avgNaesin(s));
  const zRec = clamp((s.record - 55) / 30, -1.5, 1.4);
  const fitRec = clamp((s.recFit[field] || 0) / 40, 0, 1);
  const trackPen = (FIELDS[field].track === '자연' && s.track !== '자연') ? 0.3 : (FIELDS[field].track === '인문' && s.track === '자연' ? 0.08 : 0);
  const subj = s.subject;
  const subjFit = !subj ? 0 : subj === 'easy' ? -0.18 :
    ({ phys: ['eng', 'cs', 'sci'], bio: ['med', 'nurse', 'sci'], soc: ['biz', 'law', 'soc', 'media'], lang: ['hum', 'edu', 'media', 'soc'] }[subj].indexOf(field) >= 0 ? 0.12 : 0);
  const zcs = s.zCsat != null ? s.zCsat : s.zC;
  switch (type) {
    case 'gyogwa': return zNavg - trackPen * 0.5;
    case 'jonghap': {
      const sb = p.school === 'special' ? 0.45 : p.school === 'jasa' ? 0.25 : p.region === 'gangnam' ? 0.05 : 0;
      return zNavg + 0.3 * zRec + sb + fitRec * 0.22 + subjFit - trackPen + (s.flags.award ? 0.06 : 0) + (s.flags.caught ? -0.2 : 0) + (s.flags.council ? 0.05 : 0);
    }
    case 'nonsul': return zcs * 0.55 + (p.comprehension - 3) * 0.32 + (s.talent.verbal - 40) / 90;
    case 'silgi': {
      const tk = FIELDS[field].talent;
      const tal = (s.talent[tk] - 50) / 18 + ((field === 'art' && s.flags.artPath) || (field === 'sport' && s.flags.sportPath) ? 0.5 : 0) + (field === 'perf' && s.flags.trainee ? 0.4 : 0);
      return 0.65 * tal + 0.35 * zcs;
    }
    case 'jungsi': return zcs;
  }
  return zcs;
}
function cutZ(tier, field) { return zFromTop(tier.pct) + (tier.fo ? 0 : FIELD_DIFF[field] || 0) + (SILGI[field] ? -0.35 : 0); }
function estimateIdx(s, list, z, field, r, bias) {
  const pz = z + bias + r.normal() * 0.13;
  for (let i = 0; i < list.length; i++) if (pz >= cutZ(list[i], field)) return i;
  return list.length - 1;
}
function minCsatOk(s, tier, type) {
  if (type === 'jonghap' && !tier.fo && tier.key !== 'm0') { if (tier.gi > 1) return true; }
  const pct = topFromZ(s.zCsat);
  const need = tier.fo === 'med' ? 2.5 : tier.gi <= 1 ? 7 : tier.gi <= 3 ? 12 : tier.gi <= 5 ? 24 : 101;
  return pct <= need;
}
function makeCards(s, field, type, strategy, count, r, estZ) {
  const list = tierList(field, s);
  const z = studentZ(s, type, field);
  const bias = (s.p.confidence - 3) * 0.08 + (s.pressure > 30 ? 0.05 : 0);
  const est = estimateIdx(s, list, estZ != null ? estZ : z, field, r, bias);
  const offs = count === 6
    ? { up: [-3, -2, -2, -1, -1, 0], mid: [-2, -1, -1, 0, 0, 1], safe: [-1, 0, 0, 1, 1, 2] }[strategy]
    : { up: [-2, -1, 0], mid: [-1, 0, 1], safe: [0, 1, 2] }[strategy];
  const used = {};
  const minIdx = type === 'nonsul' && list[0].key === 't0' ? 1 : 0;   // 서울대는 논술 전형이 없다
  return offs.map(o => {
    const ti = clamp(est + o, minIdx, list.length - 1), t = list[ti];
    const pool = t.unis.filter(u => !used[t.key + u]);
    const uni = r.pick(pool.length ? pool : t.unis); used[t.key + uni] = 1;
    const fo = t.fo || field;
    const major = r.pick(t.majors || FIELDS[fo].majors);
    const k = { gyogwa: 5, jonghap: 3.4, nonsul: 3, silgi: 3, jungsi: 7 }[type];
    let P = sigmoid(k * (z - cutZ(t, field)));
    if (type === 'nonsul') P = P * 0.32 + 0.02;
    if (type === 'jonghap') P = P * 0.92;
    return { tier: t, uni, major, field: fo, type, P, label: o < 0 ? '상향' : o === 0 ? '적정' : '안정' };
  });
}
function rollCards(s, cards, r) {
  cards.forEach(c => {
    const need = (c.type === 'gyogwa' || c.type === 'nonsul' || (c.type === 'jonghap' && (c.tier.fo === 'med' || c.tier.gi <= 1)));
    c.minOk = !need || minCsatOk(s, c.tier, c.type);
    c.pass = c.minOk && r.next() < c.P;
  });
  return cards;
}

function applyTurn(ctx, turn) {
  const s = ctx.s, p = s.p;
  // 여름: 연애 중이면 같은 대학 고민
  if (s.romance.status === 'dating') {
    const nm = s.romance.partner;
    const o = choose(ctx, 'g3v1:sameUni', '같은 대학 가자', `${nm}${jo(nm, '이/가')} 말했다. "우리 같은 대학, 아니면 같은 지역으로 쓰자."`, [
      { id: 'match', label: '좋아. 원서를 맞춘다', tags: ['romance'] },
      { id: 'own', label: '원서는 각자 소신대로 쓰자', tags: ['self'] },
      { id: 'end', label: '수능까지 연애를 잠시 멈추자고 한다', tags: ['study'] },
    ]);
    if (o.id === 'match') { s.flags.matchUni = true; s.romance.score += 10; L(s, '둘이 같이 원서 쓸 대학 목록을 만들었다.'); }
    if (o.id === 'own') { s.romance.score -= 4; L(s, '"그래, 각자 최선을 다하자."'); }
    if (o.id === 'end') {
      const r = makeRng(s.seed, 'g3v1:pause');
      if (r.chance(0.5)) { breakUp(s, 'g3v1'); inc(s, 'mental', -12); L(s, '"잠시"라는 말은 결국 끝이 됐다.', 'bad'); }
      else { s.romance.status = 'pause'; inc(s, 'mental', -4); s.zC += 0.03; L(s, '수능 끝나고 다시 만나기로 했다.'); }
    }
  }
  // 1) 학과
  const my = topInterest(s), d = PARENT_DESIRES[p.pDesire].field;
  const second = topInterest(s, my);
  const fOpts = [{ id: my, label: `${FIELDS[my].name} — 내가 가장 끌리는 분야`, tags: ['self'] }];
  if (d && d !== my) fOpts.push({ id: d, label: `${FIELDS[d].name} — 부모님이 원하는 분야`, tags: ['obey'] });
  if (second !== d && second !== my) fOpts.push({ id: second, label: `${FIELDS[second].name} — 두 번째로 관심 있는 분야`, tags: ['safe'] });
  if (p.pDesire === 'prestige' || p.pDesire === 'money' || p.goal === 'sky' || p.goal === 'ssh') {
    const easy = s.track === '자연' ? 'sci' : 'hum';
    if (fOpts.every(o => o.id !== easy)) fOpts.push({ id: easy, label: `${FIELDS[easy].name} — 학과보다 대학 간판(합격선 낮은 과)`, tags: ['safe', 'obey'] });
  }
  if (s.flags.artPath && fOpts.every(o => o.id !== 'art')) fOpts.push({ id: 'art', label: '디자인·미술 — 준비해 온 미대 실기', tags: ['self', 'risk'] });
  if (s.flags.sportPath && fOpts.every(o => o.id !== 'sport')) fOpts.push({ id: 'sport', label: '체육 — 준비해 온 체대 실기', tags: ['self', 'risk'] });
  const fo = choose(ctx, 'g3v1:field', '어느 학과로 원서를 쓸까', `6월 모평 결과가 나왔다(상위 ${topFromZ(s.zC).toFixed(1)}%, ${grade9(topFromZ(s.zC))}등급). 내신 평균은 상위 ${avgNaesin(s).toFixed(1)}%. 이제 원서를 써야 한다.`, fOpts);
  s.applyField = fo.id;
  if (d && fo.id === d && d !== my) { s.autonomy -= 2; s.flags.parentField = true; inc(s, 'parentRel', 6); }
  if (d && fo.id !== d) { inc(s, 'parentRel', p.pStyle === 'strict' ? -10 : -4); s.autonomy += 1; }
  // 2) 전형
  const field = fo.id;
  const tOpts = [
    { id: 'jonghap', label: `학생부종합 위주 (생기부 ${Math.round(s.record)}점)`, tags: ['record'] },
    { id: 'gyogwa', label: `학생부교과 위주 (내신 상위 ${avgNaesin(s).toFixed(1)}%)`, tags: ['safe'] },
    { id: 'nonsul', label: '논술 위주 (경쟁률 수십 대 일, 한 방)', tags: ['risk'] },
    SILGI[field] ? { id: 'silgi', label: '실기 위주', tags: ['self'] } : null,
    { id: 'none', label: '수시는 최소한만. 정시 올인', tags: ['risk', 'study'] },
  ];
  const to = choose(ctx, 'g3v1:type', '어떤 전형으로', '수시 원서는 6장. 수시에 하나라도 붙으면 정시에는 지원할 수 없다.', tOpts);
  s.applyType = to.id;
  if (to.id !== 'none') {
    const so = choose(ctx, 'g3v1:strategy', '수시 6장의 배분', '상향으로 쓸까, 안정으로 쓸까?', [
      { id: 'up', label: '상향 위주 — 떨어져도 정시가 있다', tags: ['risk'] },
      { id: 'mid', label: '적정 위주 — 상향 2 · 적정 2 · 안정 2', tags: ['safe'] },
      { id: 'safe', label: '안정 위주 — 재수는 절대 안 된다', tags: ['safe', 'obey'] },
    ]);
    s.applyStrategy = so.id;
  }
}

function finalTurn(ctx, turn) {
  const s = ctx.s, p = s.p;
  const cats = allocCats(s, turn).filter(c => c.id !== 'activity');
  const def = defaultAlloc(s, cats);
  const raw = ask(ctx, { type: 'alloc', key: turn.id + ':alloc', title: '수능까지 남은 시간', text: '수능까지 넉 달. 마지막 시간 배분이다.', cats, def, total: 10 });
  const a = normAlloc(raw, cats);
  ['study', 'academy', 'activity', 'hobby', 'friends', 'rest', 'date', 'work'].forEach(k => { if (a[k] == null) a[k] = 0; });
  s.lastAlloc = a;
  randomEvents(ctx, turn, 1);
  // 마지막 학기 공부 효과(수능만)
  const lossFrac = clamp((s.lazy - 22) / 115, 0, 0.5);
  const ability = (p.focus * 0.4 + p.comprehension * 0.35 + p.memory * 0.25) / 3;
  const cond = 0.72 + s.mental / 380 + s.health / 420 - (s.stress > 70 ? 0.08 : 0);
  const studied = (a.study + a.academy * (s.money >= 6 ? 1 : 0.45)) * (1 - lossFrac);
  s.zC += ((studied * ability * cond * (0.75 + p.comprehension * 0.08)) - 4.3 - Math.max(0, s.zC) * 0.55) * 0.05 * damp(s.zC);
  inc(s, 'stress', (a.study + a.academy) * 2 - 8 - a.rest * 2.5);
  inc(s, 'mental', (a.rest - 2) * 2 + (a.friends + a.hobby) - 2);
  if (a.date) { s.romance.score += a.date * 6; inc(s, 'mental', a.date * 2); }
  L(s, `9월 모평 — 상위 ${topFromZ(s.zC).toFixed(1)}% (${grade9(topFromZ(s.zC))}등급).`);

  const o = choose(ctx, 'g3s2:d100', '수능 D-100', '수능 100일 전. 교실 칠판에 D-100이 적혔다.', [
    { id: 'allin', label: '폰을 공기계로 바꾸고 전부 끊는다', tags: ['study'] },
    { id: 'pace', label: '지금 페이스를 유지한다', tags: ['safe'] },
    { id: 'relax', label: '수시에 걸었다. 최저만 맞추자', tags: ['fun', 'rest'] },
  ]);
  if (o.id === 'allin') { inc(s, 'lazy', -18); inc(s, 'social', -6); s.zC += 0.06 * p.diligence / 3; inc(s, 'stress', 8); L(s, '단톡방을 다 나왔다. 하루가 길어졌다.'); }
  if (o.id === 'pace') { inc(s, 'mental', 4); s.zC += 0.015; L(s, '하던 대로 했다. 흔들리지 않는 것도 실력이다.'); }
  if (o.id === 'relax') { inc(s, 'mental', 6); s.zC -= 0.05; L(s, '마음은 편했다. 수능 성적표를 받기 전까지는.'); }

  // 수능 당일
  const r = makeRng(s.seed, 'csatDay');
  const hard = r.pick(['국어', '수학', '영어']);
  const c = choose(ctx, 'g3s2:csat', '수능 당일', `${hard} 시간. 역대급으로 어렵다. 시계를 보니 20분 남았는데 아직 문제가 한참 남았다. 손이 떨린다.`, [
    { id: 'skip', label: '과감히 한 지문(문제)을 버리고 아는 것부터 푼다', tags: ['risk'] },
    { id: 'hold', label: '끝까지 붙잡는다. 포기는 없다', tags: ['study'] },
    { id: 'breath', label: '펜을 내려놓고 10초 심호흡한다', tags: ['self', 'rest'] },
  ]);
  let day = r.normal() * 0.2 * (1.35 - s.mental / 140);
  if (c.id === 'skip') day += p.comprehension >= 3 ? 0.06 : -0.03;
  if (c.id === 'hold') day += r.normal() * 0.14 - 0.02;
  if (c.id === 'breath') day += 0.02 + (p.grit - 3) * 0.035;
  if (s.flags.breakupG3) day -= 0.1;
  if (s.health < 30) day -= 0.08;
  if (s.stress > 80) day -= 0.06;
  s.zCsat = s.zC + day;
  const pct = topFromZ(s.zCsat);
  s.csatPct = pct;
  const diffWord = day > 0.12 ? '평소보다 훨씬 잘 봤다.' : day < -0.12 ? '평소 실력이 나오지 않았다.' : '평소 실력만큼 나왔다.';
  L(s, `수능 가채점 — 상위 ${pct.toFixed(1)}% (평균 ${grade9(pct)}등급). ${diffWord}`, day < -0.12 ? 'bad' : day > 0.12 ? 'good' : 'info');
  if (s.flags.breakupG3) L(s, '고3 때의 이별이 끝까지 발목을 잡았다.', 'warn');
  if (s.romance.status === 'pause') { s.romance.status = 'dating'; L(s, `수능이 끝난 날, ${s.romance.partner}에게 전화했다.`); }
}

// ── 입시 결과 ────────────────────────────────────────────
function admissions(ctx) {
  const s = ctx.s, p = s.p;
  const field = s.applyField || topInterest(s);
  let susi = [];
  if (s.applyType && s.applyType !== 'none') {
    const r = makeRng(s.seed, 'susi');
    const strat = s.flags.matchUni ? 'safe' : s.applyStrategy || 'mid';
    susi = rollCards(s, makeCards(s, field, s.applyType, strat, 6, r), r);
  } else if (s.applyType === 'none') {
    const r = makeRng(s.seed, 'susi');
    // 정시파도 보통 논술 몇 장은 쓴다 — 정시로 갈 곳보다 높은 대학에만
    susi = rollCards(s, makeCards(s, field, 'nonsul', 'up', 3, r, studentZ(s, 'jungsi', field) + 0.25), r);
  }
  s.susi = susi;
  const passed = susi.filter(c => c.pass);
  L(s, '수시 결과 — ' + (susi.length ? susi.map(c => `${c.uni} ${c.major}(${TYPE_NAMES[c.type]}·${c.label}) ${c.pass ? '합격' : c.minOk ? '불합격' : '최저 미충족'}`).join(' / ') : '지원 안 함'), passed.length ? 'good' : 'bad');
  let options = passed.slice();
  if (passed.length) {
    // 수시 납치: 수능을 너무 잘 봤는데 정시를 못 쓴다
    const best = passed.reduce((a, c) => (c.tier.prestige > a.tier.prestige ? c : a));
    const r2 = makeRng(s.seed, 'jungsiShadow');
    const shadow = makeCards(s, field, 'jungsi', 'mid', 3, r2)[1];
    if (shadow.tier.prestige >= best.tier.prestige + 10 && shadow.tier.gi <= 7 && s.zCsat - s.zC > 0.08) { s.flags.susiKidnap = { got: best.uni, could: shadow.uni + ' ' + shadow.major }; L(s, `수능을 너무 잘 봤다. 정시라면 ${shadow.uni}도 가능했을 점수지만, 수시에 붙어 정시를 쓸 수 없다. (수시 납치)`, 'warn'); }
    return pickUniversity(ctx, options, 'susi');
  }
  return jungsiRound(ctx, field, 'jungsi1');
}
function jungsiRound(ctx, field, key) {
  const s = ctx.s;
  const o = choose(ctx, key + ':strategy', '정시 원서', `수능 성적표가 나왔다. 상위 ${topFromZ(s.zCsat).toFixed(1)}%. 가·나·다군 세 장을 써야 한다.`, [
    { id: 'up', label: '상향 — 한 장이라도 대박을 노린다', tags: ['risk'] },
    { id: 'mid', label: '적정 — 하나는 붙는 구성', tags: ['safe'] },
    { id: 'safe', label: '안정 — 무조건 붙는다', tags: ['safe', 'obey'] },
  ]);
  const r = makeRng(s.seed, key);
  const cards = rollCards(s, makeCards(s, field, 'jungsi', o.id, 3, r), r);
  // 다군 '펑크'(합격선 붕괴)나 '폭발'은 해마다 있다
  if (r.chance(0.12)) { cards[2].pass = true; cards[2].punk = true; }
  s.jungsi = cards;
  L(s, '정시 결과 — ' + cards.map((c, i) => `${'가나다'[i]}군 ${c.uni} ${c.major} ${c.pass ? '합격' + (c.punk ? '(펑크 덕분!)' : '') : '불합격'}`).join(' / '), cards.some(c => c.pass) ? 'good' : 'bad');
  return pickUniversity(ctx, cards.filter(c => c.pass), key);
}
function pickUniversity(ctx, passed, key) {
  const s = ctx.s, p = s.p;
  const canRetry = s.attempts < 2;
  const goal = GOALS[p.goal] || GOALS.inseoul;
  const bestP = passed.reduce((m, c) => Math.max(m, c.tier.prestige), 0);
  const opts = passed.map((c, i) => ({ id: 'u' + i, label: `${c.uni} ${c.major} 등록`, tags: c.tier.gi <= goal.gi ? ['safe', 'self'] : ['safe'],
    w: (c.tier.prestige - bestP) / 6 + (c.field === topInterest(s) ? 0.6 : 0) + 1.5 }));
  if (canRetry) {
    const pushRetry = (p.pDesire === 'med' || p.pDesire === 'prestige') && p.wealth !== 'low';
    const gap = (passed.length ? Math.min.apply(null, passed.map(c => c.tier.gi)) : 11) - goal.gi;
    const rw = (passed.length ? -1.5 : 0.8) + gap * 0.35 + (pushRetry ? 0.8 : 0) + (p.diligence - 3) * 0.3 - s.attempts * 1.6 - (p.wealth === 'low' ? 1 : 0);
    opts.push({ id: 'retry', label: s.attempts === 0 ? (passed.length ? '등록하지 않고 재수한다' : '재수한다') : '한 번만 더. 삼수한다', tags: pushRetry ? ['risk', 'obey'] : ['risk'], w: rw });
  }
  opts.push({ id: 'nocollege', label: '대학 대신 다른 길로 간다', tags: ['rebel', 'risk'], w: (s.flags.esports || s.flags.trainee ? 1 : -2.5) + (passed.length ? -1 : 0.5) });
  let text = passed.length ? `합격한 곳 중 하나를 골라야 한다. 목표는 ${goal.name}이었다.` : '모든 원서가 떨어졌다. 어떻게 할까?';
  if ((p.pDesire === 'med' || p.pDesire === 'prestige') && passed.every(c => c.tier.gi > goal.gi)) text += ` ${parentWord(s)}${jo(parentWord(s), '은/는')} "한 번만 더 해 보자"고 한다.`;
  if (p.wealth === 'low') text += ' 재수 학원비는 집에 큰 부담이다.';
  if (s.flags.esports) text += ' 프로팀에서는 "대학 대신 숙소로 오라"고 한다.';
  if (s.flags.trainee) text += ' 기획사는 "대학은 나중에 가도 된다"고 한다.';
  const o = choose(ctx, key + ':pick', '어디로 갈까', text, opts);
  if (o.id === 'retry') return retake(ctx);
  if (o.id === 'nocollege') { s.uni = null; return; }
  const c = passed[+o.id.slice(1)];
  s.uni = { name: c.uni, major: c.major, field: c.field, tier: c.tier, prestige: c.tier.prestige, gi: c.tier.gi, type: c.type, attempts: s.attempts, teacher: c.tier.teacher || null };
  if (s.flags.matchUni && s.romance.status === 'dating') { s.romance.score += 10; }
  L(s, `${c.uni} ${c.major}에 등록했다.${s.attempts ? ` (${s.attempts === 1 ? '재수' : '삼수'} 끝에)` : ''}`, 'good');
}
function retake(ctx) {
  const s = ctx.s, p = s.p;
  s.attempts++;
  const n = s.attempts;
  s.turnLabel = n === 1 ? '재수 1년' : '삼수 1년';
  s.age++;
  const o = choose(ctx, 'retake' + n + ':how', s.turnLabel, n === 1 ? '친구들은 대학 새내기다. 나는 다시 수능을 준비한다.' : '한 번 더. 이번이 진짜 마지막이다.', [
    p.wealth !== 'low' || s.money > 30 ? { id: 'academy', label: '재수종합학원 (월 250만 원)', tags: ['study', 'obey'] } : null,
    { id: 'self', label: '독학재수 (관리형 독서실)', tags: ['self', 'study'] },
    { id: 'work', label: '알바하면서 혼자 준비', tags: ['work'] },
  ]);
  const r = makeRng(s.seed, 'retake' + n);
  // 재수 중 이벤트
  if (s.romance.status === 'dating' && r.chance(0.55)) { breakUp(s, 'retake'); inc(s, 'mental', -10); L(s, `대학생이 된 ${s.romance.partner}${jo(s.romance.partner, '와/과')}는 점점 연락이 뜸해졌고, 결국 헤어졌다.`, 'bad'); }
  const t = choose(ctx, 'retake' + n + ':sns', '인스타 속 새내기들', '친구들 인스타에 MT, 축제, 과잠 사진이 올라온다.', [
    { id: 'delete', label: '인스타를 지운다', tags: ['study'] },
    { id: 'look', label: '가끔 본다. 자극이 된다', tags: ['safe'] },
    { id: 'meet', label: '주말엔 친구들을 만난다', tags: ['social', 'fun'] },
  ]);
  let g = 0.1 + 0.07 * (p.diligence - 3) + 0.05 * (p.grit - 3) - s.lazy / 420 + r.normal() * 0.24;
  if (o.id === 'academy') { g += 0.09; s.money -= 30; }
  if (o.id === 'work') { g -= 0.06; s.money += 10; s.flags.mature = true; }
  if (t.id === 'delete') { g += 0.03; inc(s, 'social', -8); }
  if (t.id === 'meet') { g -= 0.04; inc(s, 'mental', 6); }
  if (n === 2) { g -= 0.04; inc(s, 'mental', -8); }
  if (s.money < 0) { s.money = 0; inc(s, 'parentRel', -6); }
  inc(s, 'mental', -6); inc(s, 'lazy', -5);
  s.zC += g * damp(s.zC);
  const day = r.normal() * 0.18 * (1.35 - s.mental / 140);
  s.zCsat = s.zC + day;
  L(s, `${n === 1 ? '재수' : '삼수'} 수능 — 상위 ${topFromZ(s.zCsat).toFixed(1)}% (평균 ${grade9(topFromZ(s.zCsat))}등급). ${g + day > 0.15 ? '확실히 올랐다.' : g + day < 0 ? '오히려 떨어졌다. 눈앞이 캄캄했다.' : '조금 올랐다.'}`, g + day > 0.15 ? 'good' : g + day < 0 ? 'bad' : 'info');
  s.flags.retakeGain = (s.flags.retakeGain || 0) + g + day;
  const field = s.applyField || topInterest(s);
  return jungsiRound(ctx, field, 'retake' + n);
}

// ── 대학 생활 ────────────────────────────────────────────
function collegePhase(ctx) {
  const s = ctx.s, p = s.p, u = s.uni;
  s.phase = 'college';
  s.age = 20 + s.attempts;
  const r0 = makeRng(s.seed, 'col0');
  s.col = { gpa: clamp(3.2 + (p.diligence - 3) * 0.14 + r0.normal() * 0.18, 2, 4.4), spec: clamp(10 + s.record / 6, 0, 100), network: s.social / 2, effort: 0 };
  s.fit = fitOf(s, u.field);
  if (s.flags.parentField && s.fit < 0.7) L(s, `부모님이 원한 ${FIELDS[u.field].name}. 첫 학기부터 '내가 왜 여기 있지?'라는 생각이 들었다.`, 'warn');

  // 1) 1~2학년
  s.turnLabel = '대학 1~2학년';
  const goal = GOALS[p.goal] || GOALS.inseoul;
  const o1 = choose(ctx, 'col1', '스무 살', `${u.name} ${u.major}. 드디어 대학생이다. 시간표도, 하루도 내가 정한다.`, [
    { id: 'party', label: '고등학교 때 못 논 거 몰아서 논다', tags: ['fun', 'social'] },
    { id: 'grind', label: '학점 관리부터. 장학금을 노린다', tags: ['study'] },
    { id: 'club', label: '학회·동아리에서 사람을 만난다', tags: ['social', 'record'] },
    { id: 'work', label: '알바로 생활비·등록금을 번다', tags: ['work'] },
    (u.gi > goal.gi && u.gi >= 2 && s.attempts < 2) ? { id: 'retake', label: '반수한다. 여기서 끝낼 수 없다', tags: ['risk', 'study'] } : null,
  ]);
  const c = s.col;
  if (o1.id === 'party') { c.gpa -= 0.45; inc(s, 'social', 12); inc(s, 'mental', 8); inc(s, 'lazy', 8); s.flags.partyCollege = true; L(s, '술자리, MT, 축제. 1학년 1학기 학점은 2점대였다.'); }
  if (o1.id === 'grind') { c.gpa += 0.35; c.spec += 5; inc(s, 'social', -4); L(s, '과탑 장학금을 받았다. 동기들은 내 이름만 안다.', 'good'); }
  if (o1.id === 'club') { c.network += 15; c.spec += 10; c.gpa -= 0.1; L(s, '학회에서 만난 선배들이 진로 얘기를 많이 해 줬다.'); }
  if (o1.id === 'work') { s.money += 20; c.gpa -= 0.2; inc(s, 'mental', -4); c.spec += 3; s.flags.work = true; L(s, '주 20시간 알바. 수업 끝나면 바로 가게로 간다.'); }
  if (o1.id === 'retake') {
    const r = makeRng(s.seed, 'banSu');
    const g = 0.04 + 0.06 * (p.diligence - 3) + r.normal() * 0.25 - s.lazy / 500;
    s.zCsat = s.zC + g;
    const list = tierList(s.applyField || u.field, s);
    const idx = estimateIdx(s, list, s.zCsat, u.field, r, 0);
    const t = list[idx];
    if (t.prestige > u.prestige + 3) {
      const nu = r.pick(t.unis), nm = r.pick(t.majors || FIELDS[t.fo || u.field].majors);
      s.uni = Object.assign({}, u, { name: nu, major: nm, tier: t, prestige: t.prestige, gi: t.gi, field: t.fo || u.field, banSu: true, teacher: t.teacher || null });
      s.age++; c.gpa = 3.3; L(s, `반수 성공! ${nu} ${nm}${jo(nm, '으로/로')} 옮겼다. 1학년을 다시 시작한다.`, 'good');
    } else { c.gpa -= 0.6; inc(s, 'mental', -10); s.flags.banSuFail = true; L(s, '반수는 실패했다. 1학년 학점만 망가졌다.', 'bad'); }
  }
  collegeEvent(ctx, 'col1');

  // 2) 군대 / 교환학생
  s.turnLabel = '대학 2~3학년';
  const male = p.gender === 'm';
  const o2 = male
    ? choose(ctx, 'col2', '입대 시기', '동기들이 하나둘 입대한다.', [
      { id: 'now', label: '1학년 마치고 바로 육군 입대', tags: ['safe'] },
      { id: 'air', label: '공군·카투사에 지원한다 (경쟁, 대신 자기계발 시간)', tags: ['risk', 'study'] },
      { id: 'later', label: '2학년 마치고 간다', tags: ['safe'] },
      ['eng', 'cs', 'sci'].indexOf(s.uni.field) >= 0 ? { id: 'rnd', label: '대학원 진학 후 전문연구요원을 노린다', tags: ['study', 'risk'] } : null,
    ])
    : choose(ctx, 'col2', '휴학할까', '동기들이 교환학생, 휴학, 인턴 이야기를 한다.', [
      { id: 'exchange', label: '교환학생에 지원한다', tags: ['risk', 'self'] },
      { id: 'intern', label: '휴학하고 인턴·대외활동', tags: ['record'] },
      { id: 'straight', label: '쉬지 않고 바로 졸업한다', tags: ['safe', 'study'] },
      { id: 'rest', label: '휴학하고 여행·쉬기', tags: ['rest', 'fun'] },
    ]);
  const r2 = makeRng(s.seed, 'col2');
  if (o2.id === 'now' || o2.id === 'later') { s.age += 2; inc(s, 'lazy', -8); s.flags.army = true; c.gpa -= o2.id === 'later' ? 0 : 0.05; if (s.romance.status === 'dating' && r2.chance(0.6)) { breakUp(s, 'army'); L(s, `군대에 있는 동안 ${s.romance.partner}${jo(s.romance.partner, '와/과')} 헤어졌다. 흔한 이야기라는데 하나도 흔하지 않았다.`, 'bad'); } L(s, '18개월. 전역하던 날, 시간을 허투루 쓰지 않겠다고 다짐했다.'); }
  if (o2.id === 'air') { if (r2.chance(0.45 + (p.diligence - 3) * 0.08)) { s.age += 2; c.spec += 12; s.flags.army = true; L(s, '합격. 군 생활 동안 토익과 자격증을 땄다.', 'good'); } else { s.age += 2; s.flags.army = true; L(s, '떨어지고 결국 육군으로 갔다.'); } }
  if (o2.id === 'rnd') { s.flags.rndPlan = true; c.gpa += 0.1; L(s, '학점과 연구실 경력을 쌓기 시작했다.'); }
  if (o2.id === 'exchange') { if (c.gpa >= 3.4 && (s.money >= 30 || p.wealth === 'high')) { c.spec += 14; s.talent.verbal += 10; s.money -= 15; s.flags.exchange = true; s.age += 0.5; L(s, '한 학기 동안 유럽에서 지냈다. 세상이 넓다는 걸 알았다.', 'good'); } else { L(s, '학점이나 비용 문제로 선발되지 못했다.', 'warn'); } }
  if (o2.id === 'intern') { c.spec += 12; s.age += 1; L(s, '스타트업 인턴. 일 잘한다는 소리를 처음 들었다.', 'good'); }
  if (o2.id === 'straight') { c.gpa += 0.1; s.flags.fastGrad = true; L(s, '쉬지 않고 달렸다. 동기들보다 1년 빨리 졸업 준비를 시작했다.'); }
  if (o2.id === 'rest') { s.age += 1; inc(s, 'mental', 12); inc(s, 'lazy', 5); L(s, '한 학기를 쉬었다. 마음이 좀 편해졌다.'); }
  collegeEvent(ctx, 'col2');

  // 3) 전공 적성
  s.fit = fitOf(s, s.uni.field);
  if (s.fit < 0.6) {
    const my = topInterest(s);
    const o3 = choose(ctx, 'col3', '전공이 안 맞는다', `${s.uni.major} 전공 수업이 고역이다. 정말 하고 싶은 건 ${FIELDS[my].name} 쪽인 것 같다.`, [
      { id: 'stay', label: '버틴다. 졸업장은 따야 한다', tags: ['safe', 'obey'] },
      { id: 'double', label: `${my === 'cs' || my === 'biz' ? FIELDS[my].name : '컴퓨터·경영'} 복수전공을 한다`, tags: ['study', 'self'] },
      { id: 'switch', label: `${FIELDS[my].name} 쪽으로 전과·편입을 시도한다`, tags: ['risk', 'self'] },
      { id: 'drop', label: '자퇴하고 처음부터 다시 시작한다', tags: ['risk', 'rebel'] },
    ]);
    const r3 = makeRng(s.seed, 'col3');
    if (o3.id === 'stay') { c.gpa -= 0.15; inc(s, 'mental', -6); s.flags.endured = true; L(s, '꾸역꾸역 학점을 채웠다.'); }
    if (o3.id === 'double') { const df = (my === 'cs' || my === 'biz') ? my : (s.uni.field === 'cs' ? 'biz' : 'cs'); s.uni.double = df; c.spec += 8; s.age += 0.5; s.interest[df] += 8; L(s, `${FIELDS[df].name} 복수전공을 시작했다. 졸업이 한 학기 늦어진다.`); }
    if (o3.id === 'switch') {
      if (r3.chance(0.3 + (c.gpa - 3) * 0.3)) { s.uni.field = my; s.uni.major = r3.pick(FIELDS[my].majors); s.uni.switched = true; inc(s, 'mental', 10); s.autonomy += 2; L(s, `${s.uni.major}${jo(s.uni.major, '으로/로')} 전과에 성공했다!`, 'good'); }
      else { inc(s, 'mental', -8); L(s, '전과 면접에서 떨어졌다.', 'bad'); }
    }
    if (o3.id === 'drop') { s.flags.dropout = true; s.autonomy += 2; inc(s, 'parentRel', -15); s.uni.dropped = true; L(s, '자퇴서를 냈다. 부모님과 크게 싸웠다.', 'bad'); }
  } else {
    const o3 = choose(ctx, 'col3', '전공 심화', `${s.uni.major} 공부가 꽤 재미있다. 3학년, 무엇에 시간을 쓸까?`, [
      { id: 'lab', label: '학부연구생으로 연구실에 들어간다', tags: ['study', 'record'] },
      { id: 'contest', label: '공모전·대외활동', tags: ['record', 'social'] },
      { id: 'cert', label: '토익·자격증 같은 정량 스펙', tags: ['safe', 'study'] },
      { id: 'enjoy', label: '마지막 대학 생활을 즐긴다', tags: ['fun'] },
    ]);
    if (o3.id === 'lab') { c.spec += 10; s.flags.lab = true; c.gpa += 0.1; s.interest[s.uni.field] += 6; L(s, '교수님이 대학원 이야기를 꺼내셨다.'); }
    if (o3.id === 'contest') { c.spec += 13; c.network += 6; L(s, '공모전에서 장려상을 받았다.', 'good'); }
    if (o3.id === 'cert') { c.spec += 11; L(s, '토익 900점을 넘겼다.'); }
    if (o3.id === 'enjoy') { inc(s, 'mental', 8); c.network += 5; inc(s, 'lazy', 4); L(s, '좋은 추억은 많이 남았다.'); }
  }
  collegeEvent(ctx, 'col3');
  if (s.uni.dropped) { s.uni = Object.assign({}, s.uni, { name: s.uni.name + '(중퇴)', prestige: 25, gi: 10 }); }
  careerPhase(ctx);
}

const COL_EVENTS = [
  { id: 'cc', w: s => (s.romance.status !== 'dating' ? 1.6 + s.p.social * 0.2 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s, pt = newPartner(s, r);
      const o = choose(ctx, key, '새로운 인연', `교양 수업 조별과제에서 만난 ${pt.name}. 끝나고 자꾸 같이 밥을 먹는다.`, [
        { id: 'yes', label: '먼저 연락한다', tags: ['romance'] },
        { id: 'no', label: '지금은 연애할 때가 아니다', tags: ['study'] },
      ]);
      if (o.id === 'yes') { if (r.chance(0.5 + s.p.social * 0.06)) { startDating(s, pt.name, pt.studious); s.romance.score = 60; s.flags.collegeLove = true; inc(s, 'mental', 8); L(s, `${pt.name}${jo(pt.name, '와/과')} 사귀게 됐다.`, 'good'); } else { inc(s, 'mental', -4); L(s, '좋은 친구로 남기로 했다.'); } }
    } },
  { id: 'distance', w: s => (s.romance.status === 'dating' && s.flags.datedHS && s.romance.partner === s.romance.firstLove ? 2.5 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, nm = s.romance.partner;
      const o = choose(ctx, key, '멀어지는 첫사랑', `다른 대학에 간 ${nm}${jo(nm, '와/과')}는 만날 시간이 점점 줄어든다.`, [
        { id: 'effort', label: '주말마다 KTX를 탄다', tags: ['romance'] },
        { id: 'let', label: '자연스럽게 놓아준다', tags: ['safe'] },
      ]);
      if (o.id === 'effort') { s.romance.score += 15; s.money -= 6; s.col.gpa -= 0.08; L(s, '통장은 가벼워졌지만 우리는 아직 함께다.', 'good'); if (s.romance.score > 60) s.flags.firstLoveKeep = true; }
      else { breakUp(s, 'col'); inc(s, 'mental', -8); L(s, '마지막 통화는 생각보다 담담했다.'); }
    } },
  { id: 'startupFriend', w: s => (s.p.social >= 3 || s.col.network > 30 ? 1 : 0.3), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '창업 제안', '학회 동기가 말했다. "우리 같이 앱 하나 만들어서 창업하자. 투자자도 만나 봤어."', [
        { id: 'join', label: '같이 한다', tags: ['risk', 'social'] },
        { id: 'no', label: '취업 준비가 먼저다', tags: ['safe'] },
      ]);
      if (o.id === 'join') { s.flags.startupExp = true; s.col.network += 10; s.col.gpa -= 0.15; s.interest.biz += 6; L(s, '밤새 사업계획서를 썼다. 정부 지원사업 1차를 통과했다.'); }
    } },
  { id: 'compareSNS', w: () => 1, once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '동창의 인스타', '고등학교 동창이 대기업 인턴 합격 인증을 올렸다. 나는 아직 아무것도 없다.', [
        { id: 'fuel', label: '자극받아 스펙을 쌓는다', tags: ['study'] },
        { id: 'unf', label: '언팔한다. 내 속도대로 간다', tags: ['self'] },
        { id: 'down', label: '하루 종일 우울하다', tags: ['rest'] },
      ]);
      if (o.id === 'fuel') { s.col.spec += 6; inc(s, 'stress', 8); L(s, '그날 밤 자소서 첫 줄을 썼다.'); }
      if (o.id === 'unf') { inc(s, 'mental', 4); L(s, '남과 비교하지 않기로 했다. 쉽지는 않다.'); }
      if (o.id === 'down') { inc(s, 'mental', -8); inc(s, 'lazy', 4); L(s, '침대에서 하루를 보냈다.', 'bad'); }
    } },
  { id: 'drink', w: s => (s.flags.partyCollege || s.lazy > 45 ? 2 : 0.4), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '매일 밤 술자리', '일주일에 네 번 술자리. 오전 수업은 거의 못 간다.', [
        { id: 'stop', label: '줄인다', tags: ['study'] },
        { id: 'keep', label: '청춘은 지금뿐이다', tags: ['fun'] },
      ]);
      if (o.id === 'stop') { inc(s, 'lazy', -6); s.col.gpa += 0.1; L(s, '술자리를 줄였더니 아침이 생겼다.'); }
      else { inc(s, 'lazy', 8); s.col.gpa -= 0.25; inc(s, 'health', -8); s.col.network += 6; L(s, '학사경고 직전까지 갔다.', 'bad'); }
    } },
  { id: 'retire', w: s => (s.p.wealth !== 'high' ? 0.8 : 0.1), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '부모님의 은퇴', '아빠가 명예퇴직을 하셨다. 다음 학기부터 생활비 지원이 어렵다고 하신다.', [
        { id: 'work', label: '알바를 늘린다', tags: ['work'] },
        { id: 'loan', label: '학자금 대출을 받는다', tags: ['safe'] },
      ]);
      if (o.id === 'work') { s.col.gpa -= 0.15; s.flags.mature = true; inc(s, 'parentRel', 6); L(s, '주 25시간 알바를 하며 학교에 다녔다.'); }
      else { s.flags.loan = true; inc(s, 'stress', 6); L(s, '졸업할 때 빚이 2천만 원 남는다.', 'warn'); }
    } },
  { id: 'coin', w: s => (s.friendGroup === 'party' || s.p.impulse >= 4 ? 1.2 : 0.4), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '코인 대박 친구', `고등학교 친구 ${s.bestName}${jo(s.bestName, '이/가')} 코인으로 큰돈을 벌었다며 "너도 들어와"라고 한다.`, [
        { id: 'in', label: '알바비 전부를 넣는다', tags: ['risk', 'fun'] },
        { id: 'no', label: '안 한다', tags: ['safe'] },
      ]);
      if (o.id === 'in') { if (r.chance(0.3)) { s.money += 20; L(s, '세 배가 됐다! ...그리고 바로 팔았다.', 'good'); } else { s.money -= 15; inc(s, 'mental', -8); L(s, '-87%. 한동안 그 친구 연락을 피했다.', 'bad'); } }
    } },
  { id: 'prof', w: s => (s.col.gpa >= 3.7 ? 1.5 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '교수님의 제안', '지도교수님이 "우리 연구실에서 대학원 해 볼 생각 없나?"라고 하셨다.', [
        { id: 'yes', label: '진지하게 생각해 본다', tags: ['study', 'record'] },
        { id: 'no', label: '취업하겠다고 말씀드린다', tags: ['safe'] },
      ]);
      if (o.id === 'yes') { s.flags.gradOffer = true; s.interest[s.uni.field] += 6; L(s, '연구실 세미나에 들어가 보기 시작했다.'); }
    } },
  { id: 'friendReunion', w: s => (s.bestFriend ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, b = s.bestName;
      const o = choose(ctx, key, '오랜 친구', `${b}${jo(b, '이/가')} 힘들다며 늦은 밤 전화를 했다. 내일은 중요한 시험이다.`, [
        { id: 'go', label: '나가서 이야기를 들어준다', tags: ['kind', 'social'] },
        { id: 'later', label: '"시험 끝나고 꼭 보자"', tags: ['study'] },
      ]);
      if (o.id === 'go') { s.flags.friendForever = true; s.col.gpa -= 0.05; inc(s, 'mental', 4); L(s, '새벽 4시까지 이야기했다. 이 친구와는 평생 갈 것 같다.', 'good'); }
      else { if (r.chance(0.4)) { s.bestFriend = false; L(s, '그 뒤로 연락이 줄었다.', 'warn'); } else L(s, '시험이 끝나고 만나 고기를 샀다.'); }
    } },
];
function collegeEvent(ctx, key) {
  const s = ctx.s, r = makeRng(s.seed, key + ':cev');
  const pool = COL_EVENTS.filter(e => !(e.once && s.seen[e.id]));
  const ws = pool.map(e => Math.max(0, e.w(s)));
  const tot = ws.reduce((a, b) => a + b, 0);
  if (tot <= 0) return;
  let x = r.next() * tot, ev = pool[0];
  for (let i = 0; i < pool.length; i++) { x -= ws[i]; if (x <= 0) { ev = pool[i]; break; } }
  s.seen[ev.id] = true;
  ev.run(ctx, key + ':ev:' + ev.id, makeRng(s.seed, key + ':' + ev.id));
}

// ── 진로 정하기 ──────────────────────────────────────────
function careerScore(s, r) {
  const c = s.col, u = s.uni;
  const gpaS = clamp((c.gpa - 2.5) / 1.9 * 100, 0, 100);
  return u.prestige * 0.36 + gpaS * 0.14 + clamp(c.spec, 0, 100) * 0.24 + clamp(c.network, 0, 100) * 0.05 + s.mental * 0.08 + c.effort * 6 + s.fit * 9 - s.lazy * 0.06 + r.normal() * 7;
}
function jobAt(field, level, r, s) {
  const tbl = JOBS[field] || JOBS.hum;
  const lv = clamp(level, 0, 3);
  const pair = tbl[lv];
  const j = pair[r.chance(0.5) ? 0 : 1];
  return { id: field + '-' + lv + '-' + pair.indexOf(j), title: j[0], base: j[1], field, level: lv };
}
function levelFrom(C) { return C >= 79 ? 0 : C >= 64 ? 1 : C >= 49 ? 2 : 3; }

function careerPhase(ctx) {
  const s = ctx.s, p = s.p, u = s.uni;
  s.turnLabel = '졸업 즈음';
  const f = u.field;
  const opts = [];
  if (u.dropped) {
    opts.push({ id: 'creator', label: '크리에이터·프리랜서', tags: ['risk', 'fun'] });
    opts.push({ id: 'startup', label: '창업한다', tags: ['risk'] });
    opts.push({ id: 'civil', label: '공무원 시험 (학력 무관)', tags: ['safe', 'study'] });
    opts.push({ id: 'skill', label: '기술을 배운다 (직업훈련)', tags: ['work', 'safe'] });
  } else if (f === 'med' && /^의예/.test(u.major)) {
    opts.push({ id: 'med_pop', label: '인기과(피부·성형·안과·정신) 전공의에 도전', tags: ['risk', 'study'] });
    opts.push({ id: 'med_core', label: '필수의료(내과·외과·소아·응급)를 택한다', tags: ['kind', 'study'] });
    opts.push({ id: 'med_gp', label: '수련 없이 일반의로 미용 개원가에 간다', tags: ['fun', 'safe'] });
    opts.push({ id: 'med_bio', label: '제약·바이오 회사나 연구로 간다', tags: ['self'] });
  } else if (f === 'med') {
    opts.push({ id: 'med_lic', label: '면허를 따고 개원을 목표로', tags: ['safe', 'study'] });
    opts.push({ id: 'med_hosp', label: '병원·기업에 소속되어 일한다', tags: ['safe'] });
    opts.push({ id: 'med_bio', label: '제약·바이오 회사나 연구로 간다', tags: ['self'] });
  } else {
    opts.push({ id: 'job', label: `${FIELDS[f].name} 전공을 살려 취업`, tags: ['safe'], w: 1.2 + (s.fit - 0.6) });
    if (u.double) opts.push({ id: 'double', label: `복수전공 ${FIELDS[u.double].name} 쪽으로 취업`, tags: ['self'] });
    if (u.teacher) opts.push({ id: 'teacher', label: u.teacher === 'elem' ? '초등 임용고시' : u.teacher === 'sec' ? '중등 임용고시 (경쟁률 높음)' : '유치원 임용·취업', tags: ['safe', 'study', 'obey'], w: 2 });
    opts.push({ id: 'soe', label: '공기업 (NCS 준비)', tags: ['safe', 'obey'], w: p.pDesire === 'stable' ? 0.6 : 0 });
    opts.push({ id: 'civil', label: f === 'law' ? '행정고시·7급 공무원' : '공무원 시험 (7·9급)', tags: ['safe', 'obey', 'study'], w: (p.pDesire === 'stable' ? 0.8 : 0) + (f === 'law' ? 0.6 : -0.3) });
    const pro = { law: '로스쿨 진학 → 변호사', biz: 'CPA(공인회계사) 시험', eng: '변리사 시험', sci: '변리사 시험', cs: '변리사 시험', soc: '노무사 시험', hum: '로스쿨 진학 → 변호사', media: '로스쿨 진학 → 변호사' }[f];
    if (pro) opts.push({ id: 'pro', label: pro, tags: ['risk', 'study'], w: (p.pDesire === 'law' ? 1 : 0) - 0.4 + (f === 'law' || f === 'biz' ? 0.4 : 0) });
    if (['eng', 'cs', 'sci', 'hum', 'soc'].indexOf(f) >= 0 || s.flags.gradOffer) opts.push({ id: 'grad', label: '대학원 진학 (석·박사)', tags: ['study', 'self'], w: (s.flags.gradOffer || s.flags.lab ? 0.4 : -0.6) + (p.curiosity - 3) * 0.3 });
    opts.push({ id: 'startup', label: '창업한다', tags: ['risk', 'rebel'], w: s.flags.startupExp ? 0 : -1 });
    if (s.flags.creator || ['media', 'art', 'perf'].indexOf(f) >= 0) opts.push({ id: 'creator', label: '크리에이터·프리랜서', tags: ['risk', 'fun', 'self'], w: (s.flags.creator || 0) * 0.4 - 0.7 });
    if (s.talent.verbal >= 45 || s.flags.exchange || p.wealth === 'high') opts.push({ id: 'abroad', label: '해외 취업·유학', tags: ['risk', 'self'], w: s.flags.exchange ? 0 : -0.8 });
  }
  const desire = p.pDesire;
  let text = `이제 진로를 정해야 한다. 학점 ${s.col.gpa.toFixed(2)}, 스펙 ${Math.round(s.col.spec)}점.`;
  if (desire === 'stable') text += ' 부모님은 "공무원이 최고"라고 하신다.';
  if (desire === 'money') text += ' 부모님은 "빨리 자리 잡아라"고 하신다.';
  if (desire === 'biz') text += ' 부모님은 가게(회사)를 물려받으라고 하신다.';
  if (desire === 'biz' && !opts.find(o => o.id === 'family')) opts.push({ id: 'family', label: '부모님 사업을 물려받는다', tags: ['obey', 'safe'] });
  const o = choose(ctx, 'car1', '어떤 길로 갈까', text, opts);
  s.careerPath = o.id;
  if (['soe', 'civil', 'teacher', 'family'].indexOf(o.id) >= 0 && (desire === 'stable' || desire === 'biz' || desire === 'money')) { inc(s, 'parentRel', 8); s.autonomy -= 1; }
  if (o.id === 'startup' || o.id === 'creator') { if (p.pStyle === 'strict' || p.pStyle === 'anxious') inc(s, 'parentRel', -8); s.autonomy += 1; }

  const e = choose(ctx, 'car2', '준비 방식', '얼마나 걸 것인가?', [
    { id: 'all', label: '올인. 연애도 친구도 잠시 멈춘다', tags: ['study'] },
    { id: 'bal', label: '병행. 내 삶도 지키면서 간다', tags: ['safe', 'social'] },
    { id: 'easy', label: '적당히. 되면 좋고', tags: ['fun', 'rest'] },
  ]);
  s.col.effort = { all: 1.4, bal: 0.8, easy: 0.1 }[e.id];
  if (e.id === 'all') { inc(s, 'social', -10); s.romance.score -= 15; inc(s, 'stress', 10); if (s.romance.status === 'dating' && s.romance.score < 35) { breakUp(s, 'car'); L(s, `"너한테 나는 늘 2순위야." ${s.romance.partner}${jo(s.romance.partner, '와/과')} 헤어졌다.`, 'bad'); } }
  if (e.id === 'easy') { inc(s, 'mental', 5); inc(s, 'lazy', 6); }

  s.turnLabel = '20대 후반';
  let res = resolveCareer(s, o.id, makeRng(s.seed, 'car:' + o.id + ':1'), 1);
  if (!res.ok) {
    L(s, res.failText, 'bad');
    const o2 = choose(ctx, 'car3', '실패 뒤에', `${res.failText} 나이는 ${Math.floor(s.age + 4)}살. 어떻게 할까?`, [
      { id: 'retry', label: '한 번만 더 도전한다', tags: ['risk', 'study'] },
      { id: 'lower', label: '눈높이를 낮춰 지금 갈 수 있는 곳에 간다', tags: ['safe'] },
      { id: 'pivot', label: '완전히 다른 길을 찾는다', tags: ['self', 'risk'] },
    ]);
    s.flags.careerFail = o.id;
    if (o2.id === 'retry') { s.flags.retryCareer = true; s.age += 1.5; res = resolveCareer(s, o.id, makeRng(s.seed, 'car:' + o.id + ':2'), 2); if (!res.ok) { s.flags.longExam = true; res = fallbackJob(s, makeRng(s.seed, 'car:fb'), 1); res.career.title = res.career.title + ' (수험 생활 정리 후)'; res.career.id += '-x'; } }
    else if (o2.id === 'lower') res = fallbackJob(s, makeRng(s.seed, 'car:fb'), 1);
    else { s.flags.pivot = true; s.autonomy += 1; res = pivotJob(s, makeRng(s.seed, 'car:pivot')); }
  }
  s.career = res.career;
  L(s, `서른 즈음의 자리 — ${res.career.title}`, res.career.level <= 1 ? 'good' : 'info');
}
function fallbackJob(s, r, down) {
  const C = careerScore(s, r);
  const f = s.uni && !s.uni.dropped ? s.uni.field : 'none';
  const j = jobAt(f === 'med' ? 'sci' : f, levelFrom(C) + down, r, s);
  return { ok: true, career: j };
}
function pivotJob(s, r) {
  const my = topInterest(s, s.uni ? s.uni.field : null);
  const C = careerScore(s, r) - 8 + s.p.curiosity * 2;
  const j = jobAt(my === 'med' ? 'sci' : my, levelFrom(C) + 1, r, s);
  j.title += ' (진로 전환)'; j.id += '-pv';
  return { ok: true, career: j };
}
function resolveCareer(s, path, r, attempt) {
  const p = s.p, u = s.uni, f = u.field;
  const C = careerScore(s, r) + (attempt - 1) * 5;
  const eff = s.col.effort;
  const mk = (id, title, base, field, level) => ({ ok: true, career: { id, title, base, field, level } });
  switch (path) {
    case 'job': return { ok: true, career: jobAt(f === 'med' ? 'sci' : f, levelFrom(C), r, s) };
    case 'double': return { ok: true, career: jobAt(u.double, levelFrom(C - 3), r, s) };
    case 'family': {
      const ok = r.chance(0.55 + p.diligence * 0.05);
      return ok ? mk('family-ok', '부모님 사업을 이어받아 키운 2세 대표', 6500, 'biz', 1) : mk('family-meh', '부모님 가게를 물려받아 버티는 중', 3800, 'biz', 2);
    }
    case 'soe': {
      const P = sigmoid((C - 58 + p.comprehension * 2 + eff * 4) / 7);
      if (r.next() < P) { const org = r.pick(['한국전력공사', '국민건강보험공단', '한국토지주택공사', '인천국제공항공사', '한국수자원공사']); return mk('soe-' + org, `공기업 직원 (${org})`, 5600, 'law', 1); }
      return { ok: false, failText: 'NCS 필기에서 연달아 떨어졌다.' };
    }
    case 'civil': {
      const sc = p.diligence * 8 + p.memory * 6 + p.grit * 4 + eff * 10 - s.lazy / 4 + r.normal() * 10 + (attempt - 1) * 6;
      if (f === 'law' && sc > 72 && u.prestige >= 80 && eff >= 1) return mk('civil-5', '5급 사무관 (행정고시 합격)', 5800, 'law', 0);
      if (sc > 60) return mk('civil-7', '7급 국가직 공무원', 4300, 'law', 1);
      if (sc > 47) return mk('civil-9', '9급 지방직 공무원', 3500, 'law', 2);
      return { ok: false, failText: '공무원 시험에서 몇 점 차이로 떨어졌다.' };
    }
    case 'teacher': {
      const base = u.teacher === 'elem' ? 0.62 : u.teacher === 'sec' ? 0.15 : 0.35;
      const P = clamp(base + (s.col.gpa - 3.3) * 0.15 + eff * 0.1 + (p.diligence - 3) * 0.05 + (attempt - 1) * 0.1, 0.03, 0.95);
      if (r.next() < P) {
        if (u.teacher === 'elem') return r.chance(0.5) ? mk('teach-elem-s', '초등교사 (서울)', 4200, 'edu', 1) : mk('teach-elem-l', '초등교사 (지방)', 4100, 'edu', 1);
        if (u.teacher === 'sec') return mk('teach-sec', '중등 정교사 (임용 합격)', 4300, 'edu', 1);
        return mk('teach-kinder', '국공립 유치원 교사', 3900, 'edu', 1);
      }
      return { ok: false, failText: '임용고시 2차에서 떨어졌다.' };
    }
    case 'pro': {
      if (f === 'biz') {
        const P = sigmoid((p.comprehension * 8 + p.memory * 5 + p.diligence * 6 + eff * 12 - 72 + (attempt - 1) * 6) / 7);
        if (r.next() < P) return r.chance(0.6) ? mk('cpa-big4', '대형 회계법인 공인회계사', 7800, 'biz', 0) : mk('cpa-firm', '기업 재무팀 회계사', 7000, 'biz', 0);
        return { ok: false, failText: 'CPA 2차 시험에서 과락이 나왔다.' };
      }
      if (f === 'soc') {
        const P = sigmoid((p.memory * 7 + p.diligence * 7 + eff * 12 - 66 + (attempt - 1) * 6) / 7);
        if (r.next() < P) return mk('labor', '노무법인 공인노무사', 6200, 'soc', 0);
        return { ok: false, failText: '노무사 2차 시험에서 떨어졌다.' };
      }
      if (f === 'eng' || f === 'sci' || f === 'cs') {
        const P = sigmoid((p.comprehension * 7 + p.diligence * 7 + eff * 12 + (u.prestige - 70) * 0.4 - 70 + (attempt - 1) * 6) / 7);
        if (r.next() < P) return mk('patent', '특허법인 변리사', 8500, f, 0);
        return { ok: false, failText: '변리사 2차 시험에서 떨어졌다.' };
      }
      // 로스쿨
      const leet = p.comprehension * 9 + s.talent.verbal * 0.3 + u.prestige * 0.35 + (s.col.gpa - 3) * 20 + r.normal() * 8 + eff * 6;
      if (leet < 64) return { ok: false, failText: '로스쿨 입시에서 모두 떨어졌다.' };
      if (r.chance(0.12)) return { ok: false, failText: '로스쿨은 졸업했지만 변호사시험에 떨어졌다.' };
      if (leet > 88 && u.prestige >= 86) return mk('law-big', '대형 로펌 변호사', 12000, 'law', 0);
      return r.chance(0.5) ? mk('law-in', '대기업 사내 변호사', 8000, 'law', 0) : mk('law-small', '중소 로펌 변호사', 6000, 'law', 1);
    }
    case 'grad': {
      const sc = u.prestige * 0.4 + (s.col.gpa - 3) * 25 + p.curiosity * 4 + eff * 5 + r.normal() * 10 + (s.flags.lab ? 4 : 0);
      s.age += 5;
      const hum = ['hum', 'soc', 'media', 'art', 'perf'].indexOf(f) >= 0 ? 8 : 0;   // 인문계 박사는 자리가 더 적다
      if (sc - hum > 92 && r.chance(0.35)) return mk('grad-prof', '대학교수 (정년트랙)', 7500, f, 0);
      if (sc - hum > 80) return r.chance(0.5) ? mk('grad-postdoc', '해외 연구소 박사후연구원', 5800, f, 0) : mk('grad-inst', '국책연구소 박사 연구원', 7000, f, 0);
      if (sc - hum > 66 && !hum) return mk('grad-corp', '대기업 연구소 박사급 연구원', 8800, f, 0);
      if (sc > 52) return mk('grad-lect', '대학 시간강사 (박사)', 2800, f, 2);
      return mk('grad-drift', '박사 수료 후 진로 고민 중', 2200, f, 3);
    }
    case 'startup': {
      const sc = p.confidence * 6 + p.social * 4 + p.curiosity * 4 + s.col.network * 0.2 + (s.flags.startupExp ? 8 : 0) + eff * 6 + r.normal() * 18;
      if (sc > 78) return mk('st-big', '연매출 100억 스타트업 대표', 15000, f, 0);
      if (sc > 62) return mk('st-a', '시리즈A 투자 유치한 스타트업 공동창업자', 6000, f, 1);
      if (sc > 50) return mk('st-small', '작은 회사를 꾸려 가는 1인 대표', 4000, f, 2);
      s.flags.startupFail = true;
      if (p.wealth === 'high') return { ok: false, failText: '창업 3년 만에 회사를 접었다. 부모님 돈도 날렸다.' };
      return { ok: false, failText: '창업은 실패했다. 빚이 남았다.' };
    }
    case 'creator': {
      const tal = Math.max(s.talent.media, s.talent.art, s.talent.perf);
      const sc = tal * 0.5 + (s.flags.creator || 0) * 8 + p.diligence * 3 + eff * 5 + r.normal() * 16;
      if (sc > 70) return mk('cr-1m', '구독자 100만 크리에이터', 12000, 'media', 0);
      if (sc > 55) return mk('cr-100k', '구독자 15만 크리에이터', 5000, 'media', 1);
      if (sc > 44) return mk('cr-side', '부업 크리에이터 겸 회사원', 4200, 'media', 2);
      return { ok: false, failText: '2년 동안 영상을 올렸지만 구독자는 3천 명에서 멈췄다.' };
    }
    case 'abroad': {
      const sc = s.talent.verbal * 0.3 + s.col.spec * 0.4 + u.prestige * 0.25 + eff * 5 + r.normal() * 10 + (s.flags.exchange ? 6 : 0);
      if (sc > 62) {
        if (f === 'cs' || f === 'eng') return mk('ab-sv', '미국 빅테크 엔지니어', 20000, f, 0);
        if (f === 'biz') return mk('ab-mba', '해외 MBA 후 외국계 컨설턴트', 14000, 'biz', 0);
        if (f === 'nurse') return mk('ab-nurse', '호주 간호사', 7500, 'nurse', 0);
        return mk('ab-local', '해외 현지 기업 직원', 6000, f, 1);
      }
      if (sc > 50) return mk('ab-holiday', '워홀 후 현지 정착 중', 3600, f, 2);
      return { ok: false, failText: '비자 문제로 결국 귀국했다.' };
    }
    case 'skill': {
      const t = r.pick([['skill-elec', '전기기사 (대기업 협력사)', 5200], ['skill-weld', '조선소 특수용접 기술자', 6800], ['skill-bake', '제과점 사장', 4300], ['skill-car', '자동차 정비사', 4200]]);
      return mk(t[0], t[1], t[2], 'none', 1);
    }
    case 'med_pop': {
      const P = sigmoid((s.col.gpa - 3.6) * 4 + s.col.network / 30 + eff * 0.8 - 0.5 + (attempt - 1) * 0.6);
      if (r.next() < P) return mk('md-pop-' + r.int(0, 3), r.pick(['피부과 전문의 (개원)', '성형외과 전문의', '안과 전문의', '정신건강의학과 전문의']), 18000, 'med', 0);
      return { ok: false, failText: '인기과 전공의 선발에서 떨어졌다.' };
    }
    case 'med_core': {
      s.flags.coreMed = true;
      const t = r.pick([['md-core-im', '대학병원 내과 교수', 16000], ['md-core-gs', '외과 전문의', 17000], ['md-core-ped', '소아청소년과 전문의', 13000], ['md-core-er', '응급의학과 전문의', 17000]]);
      if (s.mental < 35) { inc(s, 'mental', -6); s.flags.medBurnout = true; }
      return mk(t[0], t[1], t[2], 'med', 0);
    }
    case 'med_gp': return mk('md-gp', '미용 클리닉 일반의', 15000, 'med', 0);
    case 'med_lic': return /치의/.test(u.major) ? mk('dent', '치과의사 (개원)', 16000, 'med', 0) : /한의/.test(u.major) ? mk('kmd', '한의사 (개원)', 10000, 'med', 0) : /수의/.test(u.major) ? mk('vet', '동물병원 수의사', 7500, 'med', 0) : mk('pharm', '약국을 연 약사', 11000, 'med', 0);
    case 'med_hosp': return /약학/.test(u.major) ? mk('pharm-h', '대학병원 약사', 6800, 'med', 1) : mk('md-pay', '페이 닥터', 12000, 'med', 0);
    case 'med_bio': return mk('md-bio', '제약회사 메디컬 디렉터', 13000, 'med', 0);
  }
  return { ok: true, career: jobAt(f, levelFrom(C), r, s) };
}

// ── 대학에 가지 않는 길 ────────────────────────────────────
function noCollege(ctx) {
  const s = ctx.s, p = s.p;
  s.phase = 'alt';
  s.turnLabel = '스무 살, 다른 길';
  s.age = 20 + s.attempts;
  const opts = [];
  if (s.flags.esports) opts.push({ id: 'esports', label: '프로게이머 숙소로 들어간다', tags: ['risk', 'fun'] });
  if (s.flags.trainee) opts.push({ id: 'trainee', label: '기획사 연습생 생활에 올인한다', tags: ['risk', 'fun'] });
  if (s.flags.creator) opts.push({ id: 'creator', label: '유튜브를 본업으로 한다', tags: ['risk', 'fun'] });
  opts.push({ id: 'skill', label: '직업훈련으로 기술을 배운다 (전기·용접·제빵·정비)', tags: ['work', 'safe'] });
  opts.push({ id: 'job', label: '바로 취업한다', tags: ['work', 'safe'] });
  opts.push({ id: 'civil', label: '고졸 공무원·공기업 채용을 준비한다', tags: ['safe', 'study'] });
  if (p.gender === 'm') opts.push({ id: 'nco', label: '부사관으로 입대한다', tags: ['safe'] });
  const o = choose(ctx, 'alt1', '대학 대신', '대학에 가지 않기로 했다. 무엇을 할까?', opts);
  inc(s, 'parentRel', p.pDesire === 'free' ? 0 : -10); s.autonomy += 1;
  const r = makeRng(s.seed, 'alt:' + o.id);
  const e = choose(ctx, 'alt2', '20대의 시간', '하루를 어떻게 쓸까?', [
    { id: 'all', label: '죽어라 한다', tags: ['study'] },
    { id: 'bal', label: '일과 삶의 균형을 지킨다', tags: ['safe'] },
    { id: 'easy', label: '흘러가는 대로', tags: ['fun'] },
  ]);
  const eff = { all: 1.4, bal: 0.8, easy: 0.1 }[e.id];
  const mk = (id, title, base, field, level) => ({ id, title, base, field, level });
  let car;
  if (o.id === 'esports') {
    const sc = s.talent.game * 0.6 + eff * 8 + p.grit * 3 + r.normal() * 15;
    car = sc > 70 ? mk('esp-1', '1군 프로게이머 (국제대회 출전)', 30000, 'none', 0) : sc > 55 ? mk('esp-st', '은퇴한 프로게이머 출신 스트리머', 6000, 'media', 1) : mk('esp-qa', '프로 실패 후 게임회사 QA', 3200, 'cs', 2);
  } else if (o.id === 'trainee') {
    const sc = s.talent.perf * 0.5 + eff * 8 + p.social * 3 + r.normal() * 18;
    car = sc > 72 ? mk('idol-hit', '음원 차트 1위 아이돌', 25000, 'perf', 0) : sc > 56 ? mk('idol-disband', '데뷔 후 해체, 보컬 트레이너', 3600, 'perf', 2) : mk('idol-fail', '연습생 6년 끝에 진로 전환', 2600, 'none', 3);
  } else if (o.id === 'creator') {
    const sc = s.talent.media * 0.5 + (s.flags.creator || 0) * 9 + eff * 6 + r.normal() * 16;
    car = sc > 68 ? mk('cr-1m', '구독자 100만 크리에이터', 12000, 'media', 0) : sc > 52 ? mk('cr-100k', '구독자 15만 크리에이터', 5000, 'media', 1) : mk('cr-fail', '채널을 접고 영상 편집 외주', 2800, 'media', 3);
  } else if (o.id === 'skill') {
    const t = r.pick([['skill-elec', '전기기사 (대기업 협력사)', 5200], ['skill-weld', '조선소 특수용접 기술자', 6800], ['skill-bake', hasHobby(s, 'cook') ? '동네 유명 베이커리 사장' : '제과점 사장', 4600], ['skill-car', '자동차 정비소 사장', 5000]]);
    const ok = eff > 0.5 || r.chance(0.5);
    car = ok ? mk(t[0], t[1], t[2], 'none', 1) : mk(t[0] + '-j', t[1].replace('사장', '직원').replace('기술자', '보조'), Math.round(t[2] * 0.6), 'none', 2);
  } else if (o.id === 'civil') {
    const sc = p.diligence * 8 + p.memory * 6 + eff * 10 - s.lazy / 4 + r.normal() * 10;
    car = sc > 52 ? (r.chance(0.5) ? mk('hs-soe', '공기업 고졸 채용 직원', 5000, 'none', 1) : mk('hs-civil9', '9급 공무원 (고졸)', 3400, 'law', 2)) : mk('hs-civil-fail', '공시 3년 차, 편의점 알바', 1800, 'none', 3);
  } else if (o.id === 'nco') {
    car = mk('nco', eff > 0.5 ? '육군 상사 (장기복무)' : '육군 중사', 4800, 'none', 1);
  } else {
    const lv = levelFrom(40 + eff * 12 + p.diligence * 4 + r.normal() * 10);
    car = jobAt('none', lv, r, s);
  }
  s.career = car;
  s.careerPath = 'alt-' + o.id;
  L(s, `서른 즈음의 자리 — ${car.title}`, car.level <= 1 ? 'good' : 'info');
}

// ── 서른 살 ─────────────────────────────────────────────
function finalize(ctx) {
  const s = ctx.s, p = s.p, r = makeRng(s.seed, 'final');
  s.turnLabel = '서른 살';
  s.age = 30;
  const car = s.career;
  const salary = Math.round(car.base * (0.86 + r.next() * 0.28) / 100) * 100;
  // 연애·결혼
  let marital;
  const rom = s.romance;
  if (rom.status === 'dating' && rom.score >= 45 && r.chance(0.55 + (salary >= 5000 ? 0.1 : 0) + (p.social - 3) * 0.04)) {
    marital = rom.partner === rom.firstLove && s.flags.datedHS ? 'firstlove' : 'married';
  } else if (rom.status === 'dating') marital = 'dating';
  else if (r.chance(0.18 + p.social * 0.06 + (s.social > 60 ? 0.1 : 0))) marital = r.chance(0.5) ? 'married' : 'dating';
  else marital = rom.count === 0 && p.social <= 2 ? 'never' : 'single';
  const MAR = { firstlove: '고등학교 첫사랑과 결혼', married: '결혼함', dating: '연애 중', single: '솔로', never: '연애 경험이 거의 없는 솔로' };
  const partnerName = marital === 'firstlove' ? rom.firstLove : (rom.status === 'dating' ? rom.partner : null);
  // 관계
  const parentTag = s.parentRel >= 65 ? '화목' : s.parentRel >= 40 ? '데면데면' : '거의 연락 안 함';
  const friendTag = s.bestFriend && (s.flags.friendForever || s.social >= 55) ? '평생 친구가 있다' : s.social >= 40 ? '가끔 만나는 친구 몇 명' : '외로운 편';
  // 만족도
  const cf = car.field && FIELDS[car.field] ? fitOf(s, car.field) : 0.45;
  const goal = GOALS[p.goal] || GOALS.inseoul;
  const gi = s.uni ? s.uni.gi : 11;
  const goalMet = s.uni ? (gi <= goal.gi ? 1 : gi <= goal.gi + 2 ? 0.5 : 0) : (car.level <= 1 ? 0.6 : 0.2);
  const income = clamp((salary - 2000) / 80, 0, 100);
  let sat = cf * 34 + clamp(s.autonomy, -4, 4) * 2.5 + goalMet * 8 + income * 0.16 + (marital === 'single' || marital === 'never' ? 0 : 7) + (s.parentRel - 50) * 0.08 + (s.social - 50) * 0.06 + (s.mental - 50) * 0.18 + 26 - car.level * 4 + r.normal() * 4;
  if (s.flags.parentField && cf < 0.6) sat -= 8;
  if (s.flags.medBurnout) sat -= 6;
  sat = clamp(Math.round(sat), 0, 100);
  const satTag = sat >= 70 ? 'happy' : sat >= 50 ? 'ok' : 'regret';
  const life = Math.round(sat * 0.55 + income * 0.25 + (s.parentRel + s.social) / 2 * 0.1 + s.mental * 0.1);
  const arche = archetype(s, car, sat, salary, marital);
  const code = [car.id, s.uni ? s.uni.tier.key : 'nc', satTag, marital].join('|');
  s.ending = {
    code, archetype: arche, career: car.title, careerId: car.id, level: car.level, salary,
    uni: s.uni ? s.uni.name : '대학 진학 안 함', major: s.uni ? s.uni.major : '', tierName: s.uni ? s.uni.tier.name : '',
    prestige: s.uni ? s.uni.prestige : 25, path: s.careerPath, attempts: s.attempts,
    marital, maritalText: MAR[marital], partner: partnerName, parentTag, friendTag,
    mental: Math.round(s.mental), sat, satTag, life, income: Math.round(income),
    csatPct: s.csatPct, naesinAvg: s.naesinRec.length ? avgNaesin(s) : null,
  };
  s.ending.story = epilogue(s, s.ending);
}
function archetype(s, car, sat, salary, marital) {
  const p = s.p, f = s.flags;
  if (car.id.indexOf('esp-1') === 0) return '게임으로 세계 무대에 선 사람';
  if (car.id === 'idol-hit') return '무대 위의 별';
  if (car.id === 'st-big') return '판을 뒤집은 사람';
  if (marital === 'firstlove' && sat >= 60) return '첫사랑과 끝까지 간 사람';
  if (p.pDesire === 'med' && car.field === 'med' && sat < 55) return '부모님의 꿈을 대신 사는 의사';
  if (car.field === 'med' && sat >= 65) return '사람을 살리는 일에서 의미를 찾은 사람';
  if (f.susiKidnap) return '수시 납치의 주인공';
  if (s.attempts >= 2 && s.uni && s.uni.prestige >= 80) return '삼수 끝에 웃은 사람';
  if (s.attempts >= 1 && (f.retakeGain || 0) < 0) return 'N수의 늪을 지나온 사람';
  if (s.attempts >= 1 && s.uni && s.uni.prestige >= 86) return '1년을 걸어 판을 바꾼 재수생';
  if (f.breakupG3 && s.csatPct && s.csatPct > (s.mocks[s.mocks.length - 1] || 50) + 3) return '수능 직전 이별에 흔들린 사람';
  if (f.dropout) return '스스로 레일 밖으로 나간 사람';
  if (f.pivot && sat >= 60) return '돌고 돌아 내 길을 찾은 사람';
  if (f.longExam) return '시험장에서 20대를 보낸 사람';
  if (f.parentField && sat < 50) return '부모님이 정해 준 길 위의 어른';
  if (s.lazy >= 60) return '"내일부터"의 결말';
  if (salary >= 8000 && sat < 50) return '성공했지만 공허한 사람';
  if (sat >= 72 && car.level >= 2) return '작지만 단단한 행복';
  if (sat >= 72) return '좋아하는 일을 하는 사람';
  if (s.parentRel < 35) return '부모님과 멀어진 독립형';
  if (s.social < 30) return '혼자가 익숙해진 사람';
  if (!s.uni) return '대학 대신 현장을 택한 사람';
  if (sat < 45) return '어디서부터 잘못됐는지 생각하는 서른';
  return '평범하지만 버텨 낸 사람';
}
function epilogue(s, e) {
  const nm = s.p.name;
  const lines = [];
  lines.push(`서른 살의 ${nm}. 지금 하는 일은 「${e.career}」. 연 수입은 약 ${won(e.salary)}.`);
  if (s.uni) lines.push(`${e.uni} ${e.major}${jo(e.major, '을/를')} ${s.attempts ? `${s.attempts === 1 ? '재수' : '삼수'} 끝에 들어가 ` : ''}${s.uni.dropped ? '다니다 그만뒀다' : '졸업했다'}.`);
  else lines.push('대학에는 가지 않았다.');
  const mar = { firstlove: `고등학교 때 만난 ${e.partner}${jo(e.partner || '', '와/과')} 결혼했다.`, married: `${e.partner ? e.partner + jo(e.partner, '와/과') : '대학·직장에서 만난 사람과'} 결혼했다.`, dating: `${e.partner ? e.partner + jo(e.partner, '와/과') : '누군가와'} 연애 중이다.`, single: '지금은 혼자다.', never: '연애다운 연애를 해 본 적이 거의 없다.' }[e.marital];
  lines.push(mar);
  lines.push(`부모님과는 ${e.parentTag === '화목' ? '사이가 좋다. 주말마다 밥을 먹는다' : e.parentTag === '데면데면' ? '명절에만 대화하는 사이다' : '거의 연락하지 않는다'}. 친구는 — ${e.friendTag}.`);
  lines.push(e.satTag === 'happy' ? '대체로 지금의 삶에 만족한다.' : e.satTag === 'ok' ? '나쁘지 않다. 가끔 다른 길을 상상하긴 한다.' : '밤에 누우면 자꾸 "그때 그랬다면"을 생각한다.');
  return lines;
}

// ── 시뮬레이션 실행 ───────────────────────────────────────
function simulate(profile, seed, resolve) {
  const p = normalizeProfile(profile);
  const s = initState(p, seed);
  const ctx = { s, resolve };
  try {
    const start = (p.grade - 1) * 4;
    for (let i = start; i < HS_TURNS.length; i++) {
      const t = HS_TURNS[i];
      s.turnIdx = i; s.turnLabel = t.label; s.age = 17 + Math.floor(i / 4);
      if (t.type === 'sem') semesterTurn(ctx, t);
      else if (t.type === 'vac') { vacationTurn(ctx, t); randomEvents(ctx, t, 1); }
      else if (t.type === 'apply') applyTurn(ctx, t);
      else if (t.type === 'final') finalTurn(ctx, t);
    }
    s.turnLabel = '입시 결과';
    admissions(ctx);
    if (s.uni) collegePhase(ctx); else noCollege(ctx);
    finalize(ctx);
    return { done: true, state: s, ending: s.ending };
  } catch (e) {
    if (e instanceof Pending) return { done: false, state: s, prompt: e.prompt };
    throw e;
  }
}
// 화면용: 고른 것만 쓰고, 아직 안 고른 질문이 나오면 멈춘다
function play(profile, seed, decisions) {
  return simulate(profile, seed, pr => (decisions && Object.prototype.hasOwnProperty.call(decisions, pr.key) ? decisions[pr.key] : undefined));
}
// 끝까지 자동으로: 고른 게 있으면 그대로, 없거나 이번 갈래에 없는 선택지면 내 성향대로
function autoplay(profile, seed, decisions, override) {
  return simulate(profile, seed, (pr, s) => {
    if (override && pr.key === override.key) return override.choice;
    const d = decisions ? decisions[pr.key] : undefined;
    if (d !== undefined && (pr.type === 'alloc' || pr.options.some(o => o.id === d))) return d;
    return persona(s, pr);
  });
}

// ── 후회 분석 ────────────────────────────────────────────
function allocAlternatives(h) {
  const a = Object.assign({}, h.choice), cats = h.prompt.cats.map(c => c.id);
  const alts = [];
  const funKeys = ['hobby', 'friends', 'date', 'rest', 'work'].filter(k => cats.indexOf(k) >= 0);
  const donor = funKeys.slice().sort((x, y) => (a[y] || 0) - (a[x] || 0))[0];
  if (donor && (a[donor] || 0) >= 2) { const b = Object.assign({}, a); b[donor] -= 2; b.study = (b.study || 0) + 2; alts.push({ choice: b, label: `${catName(h, donor)} 2칸을 자습으로 돌렸다면` }); }
  if ((a.study || 0) + (a.academy || 0) >= 3) { const b = Object.assign({}, a); const from = (b.academy || 0) >= 2 ? 'academy' : 'study'; b[from] -= 2; b.rest = (b.rest || 0) + 1; b.friends = (b.friends || 0) + 1; alts.push({ choice: b, label: `${catName(h, from)} 2칸을 줄이고 쉬고 친구를 만났다면` }); }
  if (cats.indexOf('activity') >= 0 && (a.activity || 0) <= 1 && donor && (a[donor] || 0) >= 2) { const b = Object.assign({}, a); b[donor] -= 2; b.activity = (b.activity || 0) + 2; alts.push({ choice: b, label: `${catName(h, donor)} 2칸을 생기부 활동에 썼다면` }); }
  return alts;
}
function catName(h, id) { const c = h.prompt.cats.find(x => x.id === id); return c ? c.label : id; }
function decisionsOf(history) { const d = {}; history.forEach(h => { d[h.key] = h.choice; }); return d; }

function analyze(profile, seed, history, base) {
  const decisions = decisionsOf(history);
  const out = [];
  history.forEach(h => {
    let alts = [];
    if (h.prompt.type === 'alloc') alts = allocAlternatives(h);
    else alts = h.prompt.options.filter(o => o.id !== h.choice).slice(0, 4).map(o => ({ choice: o.id, label: o.label }));
    alts.forEach(alt => {
      const res = autoplay(profile, seed, decisions, { key: h.key, choice: alt.choice });
      if (!res.done) return;
      const e = res.ending;
      const chosenLabel = h.prompt.type === 'alloc' ? allocText(h) : (h.prompt.options.find(o => o.id === h.choice) || {}).label;
      out.push({
        idx: h.idx, key: h.key, turn: h.turn, title: h.title, chosen: chosenLabel, alt: alt.label, altChoice: alt.choice,
        ending: e, delta: e.life - base.life, dSalary: e.salary - base.salary, dSat: e.sat - base.sat, dPrestige: e.prestige - base.prestige,
        same: e.code === base.code && e.life === base.life && e.uni === base.uni,
      });
    });
  });
  const changed = out.filter(x => !x.same);
  const regrets = changed.filter(x => x.delta > 0).sort((a, b) => b.delta - a.delta);
  const goods = changed.filter(x => x.delta < 0).sort((a, b) => a.delta - b.delta);
  // 같은 결정에서 하나만
  const uniq = arr => { const seen = {}; return arr.filter(x => (seen[x.key] ? false : (seen[x.key] = true))); };
  const forks = uniq(changed.slice().sort((a, b) => Math.abs(b.delta) + Math.abs(b.dPrestige) * 0.3 - Math.abs(a.delta) - Math.abs(a.dPrestige) * 0.3));
  return {
    regrets: uniq(regrets).slice(0, 4), goods: uniq(goods).slice(0, 3), forks: forks.slice(0, 6),
    tried: out.length, changed: changed.length,
    distinct: Object.keys(out.reduce((m, x) => { m[x.ending.code] = 1; return m; }, {})).length,
  };
}
function allocText(h) {
  const a = h.choice;
  return h.prompt.cats.filter(c => a[c.id]).map(c => `${c.label} ${a[c.id]}`).join(' · ');
}

// ── 화면에 보여 줄 상태 ────────────────────────────────────
function view(s) {
  const last = s.naesinRec.length ? s.naesinRec[s.naesinRec.length - 1] : s.p.gpaPct;
  const mock = s.zCsat != null ? topFromZ(s.zCsat) : topFromZ(s.zC);
  const rom = s.romance;
  return {
    name: s.p.name, age: s.age, turn: s.turnLabel, phase: s.phase,
    naesin: { pct: last, avg: s.naesinRec.length ? avgNaesin(s) : last, g: s.p.grade >= 3 ? grade9(last) + '등급' : grade5(last) + '등급(5등급제)' },
    mock: { pct: mock, g: grade9(mock) },
    bars: [
      { k: 'record', label: '생기부', v: Math.round(clamp(s.record, 0, 100)) },
      { k: 'mental', label: '멘탈', v: Math.round(s.mental) },
      { k: 'stress', label: '스트레스', v: Math.round(s.stress), bad: true },
      { k: 'health', label: '체력', v: Math.round(s.health) },
      { k: 'lazy', label: '나태', v: Math.round(s.lazy), bad: true },
      { k: 'parentRel', label: '부모님과 관계', v: Math.round(s.parentRel) },
      { k: 'social', label: '친구 관계', v: Math.round(s.social) },
    ],
    romance: rom.status === 'dating' ? `${rom.partner}${jo(rom.partner, '와/과')} 연애 중` : rom.status === 'pause' ? `${rom.partner}${jo(rom.partner, '와/과')} 잠시 멈춤` : rom.status === 'broke' ? '이별 후 혼자' : '솔로',
    interest: FIELDS[topInterest(s)].name,
    money: s.money > 70 ? '여유' : s.money > 30 ? '보통' : s.money > 10 ? '빠듯' : '바닥',
    uni: s.uni ? `${s.uni.name} ${s.uni.major}` : null,
    gpa: s.col ? s.col.gpa.toFixed(2) : null,
  };
}

const API = {
  play, autoplay, analyze, view, normalizeProfile, decisionsOf,
  FIELDS, GOALS, PARENT_STYLES, PARENT_DESIRES, STYLES, HOBBIES, FRIEND_GROUPS, TIERS,
  _internal: { persona, simulate, makeRng, topFromZ, zFromTop, grade9, grade5 },
};
if (typeof module !== 'undefined' && module.exports) module.exports = API;
else root.CareerSim = API;
})(typeof window !== 'undefined' ? window : this);
