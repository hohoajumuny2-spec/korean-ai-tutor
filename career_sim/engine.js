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
// ── 예체능 ──────────────────────────────────────────────
//  실기(talent)와 수능·내신을 함께 본다. 대학마다 실기 비중(silgiW)이 다르다. 홍익대 미대처럼 실기 없이 서류·수능으로 뽑는 곳도 있다.
//  음대·실용음악은 경쟁률이 수십~수백 대 일이고, 체대는 수능·내신 비중이 생각보다 높다.
const ARTS_FIELD = { art: 'art', music: 'perf', sport: 'sport' };
const ARTS_NAME = { art: '미술', music: '음악', sport: '체육' };
const ART_TIERS = [
  { key: 'a0', name: '서울대 미대',            pct: 0.5, prestige: 98, gi: 0, unis: ['서울대'], majors: ['디자인과', '동양화과', '서양화과'], silgiW: 0.55, arts: 'art' },
  { key: 'a1', name: '홍익대 미대(비실기)',     pct: 1.6, prestige: 90, gi: 1, unis: ['홍익대'], majors: ['시각디자인과', '산업디자인과', '회화과'], silgiW: 0.15, arts: 'art' },
  { key: 'a2', name: '국민대·건국대·이화여대 미대', pct: 4, prestige: 82, gi: 3, unis: ['국민대', '건국대', '이화여대'], majors: ['시각디자인과', '산업디자인과', '조형예술과'], silgiW: 0.6, arts: 'art' },
  { key: 'a3', name: '중앙대·경희대·서울과기대 디자인', pct: 7, prestige: 78, gi: 4, unis: ['중앙대', '경희대', '서울과기대', '숙명여대'], majors: ['시각디자인과', '산업디자인과', '공예과'], silgiW: 0.6, arts: 'art' },
  { key: 'a4', name: '수도권 미대',             pct: 15, prestige: 65, gi: 6, unis: ['상명대', '한성대', '경기대', '단국대'], majors: ['시각디자인과', '애니메이션과', '회화과'], silgiW: 0.65, arts: 'art' },
  { key: 'a5', name: '지방 미대',               pct: 35, prestige: 50, gi: 8, unis: ['지방 4년제 미대'], majors: ['디자인학과', '미술학과'], silgiW: 0.7, arts: 'art' },
  { key: 'a6', name: '전문대 디자인과',          pct: 100, prestige: 30, gi: 10, unis: ['전문대학'], majors: ['시각디자인과', '웹툰과'], silgiW: 0.7, arts: 'art' },
];
const MUSIC_TIERS = [
  { key: 'm0', name: '서울대 음대',            pct: 0.3, prestige: 98, gi: 0, unis: ['서울대'], majors: ['성악과', '기악과', '작곡과'], silgiW: 0.8, arts: 'music' },
  { key: 'm1', name: '한예종',                 pct: 0.45, prestige: 97, gi: 0, unis: ['한국예술종합학교'], majors: ['음악원 기악과', '음악원 성악과'], silgiW: 0.9, arts: 'music' },
  { key: 'm2', name: '연세대·한양대 음대',       pct: 1.6, prestige: 88, gi: 1, unis: ['연세대', '한양대'], majors: ['성악과', '관현악과', '작곡과'], silgiW: 0.75, arts: 'music' },
  { key: 'm3', name: '실용음악 명문(경쟁률 100:1)', pct: 2.5, prestige: 74, gi: 4, unis: ['서울예대', '호원대', '동아방송예대'], majors: ['실용음악과'], silgiW: 0.9, arts: 'music' },
  { key: 'm4', name: '경희대·숙명여대·국민대 음대', pct: 5, prestige: 78, gi: 3, unis: ['경희대', '숙명여대', '국민대'], majors: ['성악과', '피아노과', '포스트모던음악학과'], silgiW: 0.7, arts: 'music' },
  { key: 'm5', name: '수도권 음대·실용음악과',   pct: 15, prestige: 62, gi: 6, unis: ['단국대', '상명대', '백석대', '한세대'], majors: ['실용음악과', '음악학과'], silgiW: 0.75, arts: 'music' },
  { key: 'm6', name: '지방 음대',               pct: 35, prestige: 48, gi: 8, unis: ['지방 4년제 음대'], majors: ['음악학과', '실용음악과'], silgiW: 0.75, arts: 'music' },
  { key: 'm7', name: '전문대 실용음악과',        pct: 100, prestige: 30, gi: 10, unis: ['전문대학'], majors: ['실용음악과'], silgiW: 0.8, arts: 'music' },
];
const SPORT_TIERS = [
  { key: 's0', name: '서울대 체육교육과',        pct: 0.6, prestige: 97, gi: 0, unis: ['서울대'], majors: ['체육교육과'], silgiW: 0.4, teacher: 'sec', arts: 'sport' },
  { key: 's1', name: '고려대·연세대 체교과',      pct: 2.2, prestige: 90, gi: 1, unis: ['고려대', '연세대'], majors: ['체육교육과', '스포츠응용산업학과'], silgiW: 0.4, teacher: 'sec', arts: 'sport' },
  { key: 's2', name: '한국체대',                pct: 2.5, prestige: 84, gi: 2, unis: ['한국체대'], majors: ['체육학과', '스포츠건강복지학과'], silgiW: 0.65, arts: 'sport' },
  { key: 's3', name: '경희대·중앙대·성균관대 스포츠', pct: 5, prestige: 80, gi: 3, unis: ['경희대', '중앙대', '성균관대'], majors: ['스포츠지도학과', '체육학과', '스포츠과학과'], silgiW: 0.5, arts: 'sport' },
  { key: 's4', name: '인서울 체육학과',          pct: 9, prestige: 72, gi: 5, unis: ['국민대', '동국대', '세종대', '숭실대'], majors: ['스포츠건강재활학과', '체육학과', '스포츠산업학과'], silgiW: 0.5, arts: 'sport' },
  { key: 's5', name: '수도권 체대',              pct: 18, prestige: 62, gi: 6, unis: ['용인대', '인천대', '가천대', '단국대'], majors: ['체육학과', '경호학과', '태권도학과'], silgiW: 0.55, arts: 'sport' },
  { key: 's6', name: '지방 체대',                pct: 35, prestige: 50, gi: 8, unis: ['지방 4년제 체대'], majors: ['체육학과', '스포츠지도학과'], silgiW: 0.6, arts: 'sport' },
  { key: 's7', name: '전문대 생활체육과',         pct: 100, prestige: 30, gi: 10, unis: ['전문대학'], majors: ['생활체육과', '경호과'], silgiW: 0.6, arts: 'sport' },
];
// 예체능 학원·레슨. 실기는 혼자 늘기 어렵다 — 입시 전문 학원은 대학별 출제 경향까지 잡아 준다
const ARTS_ACAD = {
  none:  { name: '혼자 연습',            mult: 0.8,  cost: 0,   desc: '방향을 봐 줄 사람이 없다. 틀린 습관이 굳으면 연습해도 안 는다' },
  local: { name: '동네 학원·레슨',        mult: 1.15, cost: 2.2, desc: '기본기는 잡힌다. 입시 유형은 따로 봐야 한다' },
  ipsi:  { name: '입시 전문 학원',        mult: 1.45, cost: 4.5, desc: '대학별 실기 유형·채점 기준을 안다. 비싸고 주 4~5일' },
  tutor: { name: '개인 레슨(1:1)',        mult: 1.4,  cost: 6,   desc: '선생님에 따라 편차가 크다. 음대 입시는 거의 필수' },
};
const artsField = s => (s.arts ? ARTS_FIELD[s.arts] : s.flags.artPath ? 'art' : s.flags.sportPath ? 'sport' : s.flags.musicPath ? 'perf' : null);
const artsOf = f => ({ art: 'art', perf: 'music', sport: 'sport' }[f] || null);
function artsTiers(field) { return field === 'art' ? ART_TIERS : field === 'perf' ? MUSIC_TIERS : field === 'sport' ? SPORT_TIERS : null; }
function artsMult(s) { const k = s.artsAcad || 'none'; if (s.money < 3) return 1; return ARTS_ACAD[k] ? ARTS_ACAD[k].mult : 1; }
function tierList(field, s) {
  const at = artsTiers(field);
  if (at) return at;
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
  steady:  { name: '꾸준형',     naesin: 1.0,  csat: 1.0,  var: 0.1, stress: 0 },
  cram:    { name: '벼락치기형',  naesin: 1.05, csat: 0.82, var: 0.25, stress: 3 },
  immerse: { name: '몰입형',     naesin: 0.9,  csat: 1.08, var: 0.19, stress: 0 },
  perfect: { name: '완벽주의형',  naesin: 1.08, csat: 0.98, var: 0.08, stress: 6 },
  hack:    { name: '요령형',     naesin: 1.0,  csat: 0.92, var: 0.15, stress: -2 },
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
  art:   [[['대기업 UX 디자이너', 6600], ['글로벌 브랜드 디자이너', 6200]], [['IT 기업 프로덕트 디자이너', 5300], ['브랜드 패키지 디자이너', 4300]], [['디자인 에이전시 디자이너', 3600], ['게임회사 원화가', 4200]], [['불안정한 프리랜서 디자이너', 2500], ['미술 학원 강사', 2800]]],
  perf:  [[['뮤지컬 주연 배우', 8000], ['히트곡을 낸 작곡가', 9000]], [['세션 연주자', 4200], ['방송 음악감독 팀원', 4500]], [['실용음악 학원 강사', 3200], ['공연기획사 직원', 3400]], [['단역 배우 겸 아르바이트', 1900], ['무명 인디 뮤지션', 1600]]],
  sport: [[['프로 구단 트레이너', 5600], ['체육 정교사', 5000]], [['스포츠 브랜드 마케터', 5000], ['경찰공무원(경장)', 4700]], [['헬스장 PT 트레이너', 3600], ['생활체육 지도자', 3100]], [['아르바이트 트레이너', 2400], ['진로 전환 준비 중', 1800]]],
  none:  [[['대기업 생산직(정규직)', 6500], ['공기업 고졸 채용', 5200]], [['중견기업 기술직', 4500], ['프랜차이즈 점장', 4200]], [['배달·물류 기사', 4000], ['판매직 정규직', 3100]], [['아르바이트 전전', 2100], ['쉬었음 청년', 600]]],
};
const LEVEL_NAMES = ['최상', '상', '중', '하'];

// ── 과목 ───────────────────────────────────────────────
//  국·수·영·탐을 따로 굴린다. 국어 문해력은 영어 장문·탐구 지문의 효율을 바꾸고,
//  이과 수학은 탐구(물리·화학) 계산에 도움이 된다. 정시는 계열별 반영 비율로, 수시는 수능 최저로 과목 등급을 쓴다.
const SUBJECTS = [{ k: 'kor', name: '국어' }, { k: 'math', name: '수학' }, { k: 'eng', name: '영어' }, { k: 'inq', name: '탐구' }];
const SUBJ_NAME = { kor: '국어', math: '수학', eng: '영어', inq: '탐구' };
const SUB_KEYS = ['kor', 'math', 'eng', 'inq'];
const CUT_ENG = [7, 20, 38, 55, 70, 82, 90, 96, 100];   // 영어는 절대평가라 1등급 폭이 더 넓다
const MID9 = [2, 7.5, 17, 31.5, 50, 68.5, 83, 92.5, 98];
const MIDENG = [3.5, 13.5, 29, 46.5, 62.5, 76, 86, 93, 98];
const gradeEng = pct => { for (let i = 0; i < 9; i++) if (pct <= CUT_ENG[i]) return i + 1; return 9; };
const subjGrade = (k, z) => (k === 'eng' ? gradeEng(topFromZ(z)) : grade9(topFromZ(z)));
const subjFromGrade = (k, g) => zFromTop((k === 'eng' ? MIDENG : MID9)[clamp(Math.round(g), 1, 9) - 1]);
const meanSub = o => (o.kor + o.math + o.eng + o.inq) / 4;
function mockGrades(sub) { const o = {}; SUB_KEYS.forEach(k => { o[k] = subjGrade(k, sub[k]); }); return o; }
function gradesText(g) { return `국어 ${g.kor} · 수학 ${g.math} · 영어 ${g.eng} · 탐구 ${g.inq}`; }
function subjAbility(p, k) {
  return ({ kor: p.comprehension * 0.5 + p.focus * 0.3 + p.memory * 0.2, math: p.comprehension * 0.55 + p.focus * 0.35 + p.memory * 0.1,
    eng: p.memory * 0.4 + p.comprehension * 0.3 + p.focus * 0.3, inq: p.memory * 0.5 + p.comprehension * 0.3 + p.focus * 0.2 })[k] / 3;
}
// 정시 반영 비율(계열별)
function subjWeights(field) {
  const t = FIELDS[field] ? FIELDS[field].track : '인문';
  if (field === 'med') return { kor: 0.2, math: 0.35, eng: 0.1, inq: 0.35 };
  if (t === '자연') return { kor: 0.2, math: 0.35, eng: 0.15, inq: 0.3 };
  if (t === '예체') return { kor: 0.4, math: 0.1, eng: 0.3, inq: 0.2 };
  return { kor: 0.35, math: 0.25, eng: 0.2, inq: 0.2 };
}
function compositeZ(sub, field) { const w = subjWeights(field); return SUB_KEYS.reduce((a, k) => a + w[k] * sub[k], 0); }
// 수능 최저: 국·수·영·탐(1과목) 중 n개 등급 합
function minReq(tier, type) {
  if (type === 'jungsi') return null;
  if (tier.arts) return tier.gi <= 1 ? { n: 2, sum: 5 } : tier.gi <= 3 ? { n: 2, sum: 7 } : null;
  if (type === 'silgi') return null;
  if (tier.fo === 'med') return tier.key === 'm4' || tier.key === 'm5' ? { n: 3, sum: 5 } : { n: 4, sum: 5 };
  if (type === 'jonghap') return tier.gi === 1 ? { n: 4, sum: 8 } : null;
  if (tier.teacher === 'elem') return { n: 4, sum: 12 };
  const T = { 0: [3, 7], 1: [3, 6], 2: [3, 7], 3: [2, 5], 4: [2, 5], 5: [2, 6], 6: [2, 6], 7: [2, 7] }[tier.gi];
  return T ? { n: T[0], sum: T[1] } : null;
}
const reqText = q => (q ? `${q.n}합 ${q.sum}` : '최저 없음');
function checkMin(q, g) { const sum = [g.kor, g.math, g.eng, g.inq].sort((a, b) => a - b).slice(0, q.n).reduce((a, b) => a + b, 0); return { ok: sum <= q.sum, sum }; }
// 학과별 취업률·취업의 질 (계열 평균을 바탕으로 한 대략값, 대학 수준에 따라 조금씩 달라진다)
const EMPLOY = {
  med: [90, 'A+', 6000, '면허 직업이라 실업이 거의 없다'], nurse: [83, 'A', 3800, '병원 수요는 많지만 3교대가 힘들다'],
  eng: [71, 'A-', 4100, '반도체·제조 대기업 채용이 많다'], cs: [70, 'A-', 4300, '개발자 수요는 많지만 신입 경쟁이 세졌다'],
  sci: [60, 'B', 3300, '대학원 진학이 많고 학부 졸업 후 바로 취업은 적다'], biz: [64, 'B+', 3800, '금융·대기업 사무직, 자격증과 인턴이 갈림길'],
  law: [57, 'B', 3400, '공무원·공기업 준비 기간이 길다'], edu: [60, 'B+', 3600, '임용 합격이 곧 취업이다'],
  hum: [54, 'C+', 3000, '전공을 살린 취업 자리가 적다'], soc: [58, 'B-', 3200, '공공·복지 분야가 많고 초봉이 낮다'],
  media: [59, 'C+', 3100, '경쟁이 심하고 계약직이 많다'], art: [57, 'C', 2800, '프리랜서 비중이 높다'],
  perf: [50, 'C-', 2400, '정규직 자리가 드물다'], sport: [60, 'C+', 2900, '지도자·트레이너 위주라 소득 편차가 크다'],
};
function employOf(field, prestige, teacher) {
  const e = EMPLOY[field] || EMPLOY.hum, pr = prestige == null ? 62 : prestige;
  let rate = e[0] + Math.round((pr - 62) * 0.18), grade = e[1], note = e[3];
  if (teacher === 'elem') { rate = 84; grade = 'A-'; note = '초등 임용 합격률이 높은 편이다'; }
  if (teacher === 'sec') { rate = 46; grade = 'B'; note = '중등 임용 경쟁률이 높아 기간제·학원으로 가는 경우가 많다'; }
  const pay = Math.round(e[2] * (1 + (pr - 62) / 250) / 100) * 100;
  return { rate: clamp(rate, 30, 97), grade, pay, note };
}
function employText(field, prestige, teacher) { const e = employOf(field, prestige, teacher); return `취업률 약 ${e.rate}% · 취업의 질 ${e.grade} (초봉 약 ${e.pay.toLocaleString()}만) — ${e.note}`; }

// ── 학원 ───────────────────────────────────────────────
//  자기주도(독학)도 되지만, 맞는 학원은 같은 시간을 써도 더 많이 오른다. 대신 돈이 들고, 복습을 안 하면 효과가 줄어든다.
//  mult: 그 과목 공부 효율, lazyCut: 나태로 새는 시간을 얼마나 막아 주나, naesin: 학교 내신 대비 효과, cost: 학기당 학원비
const ACAD = {
  none:     { name: '독학(자기주도)',         mult: 1.0,  lazyCut: 0,    naesin: 0,     cost: 0,   desc: '돈이 안 들지만 방향과 피드백을 혼자 찾아야 한다' },
  online:   { name: '인강',                  mult: 1.04, lazyCut: 0,    naesin: 0,     cost: 0.6, desc: '싸고 강의 질은 좋지만, 성실하지 않으면 완강을 못 한다' },
  big:      { name: '대형 학원 유명 강사 현강', mult: 1.15, lazyCut: 0.1,  naesin: 0.005,  cost: 3.2, desc: '상위권에 맞춘 진도와 자료. 기초가 약하면 따라가기 벅차다' },
  managed:  { name: '관리형 학원',            mult: 1.14, lazyCut: 0.55, naesin: 0.009,  cost: 3.0, desc: '출결·숙제·자습을 붙잡아 준다. 나태한 학생에게 특히 효과' },
  director: { name: '원장 직강 소규모 학원',   mult: 1.2,  lazyCut: 0.4,  naesin: 0.02,   cost: 2.8, desc: '원장이 직접 가르치고 첨삭·상담·입시 설계까지 해 준다. 학교별 내신 대비가 강하고, 흔들릴 때 잡아 준다' },
  group:    { name: '그룹 과외',              mult: 1.14, lazyCut: 0.25, naesin: 0.01,  cost: 3.4, desc: '3~4명 소수 수업. 같이 하는 친구 수준에 따라 효과가 갈린다' },
  tutor:    { name: '1:1 과외',               mult: 1.17, lazyCut: 0.35, naesin: 0.012,  cost: 5.0, desc: '나에게 딱 맞춘 수업. 비싸고, 선생님에 따라 편차가 크다' },
};
const ACAD_KEYS = Object.keys(ACAD);
// 학생에게 맞는 정도까지 넣은 실제 효율
function acadMult(s, k) {
  const t = s.acad[k] || 'none', A = ACAD[t], p = s.p, z = s.sub[k];
  if (t === 'none') return 1;
  if (s.money < 3) return 1;                        // 학원비를 못 내 사실상 쉬는 중
  let m = A.mult;
  if (t === 'online') m += (p.diligence - 3) * 0.03;               // 성실해야 인강이 산다
  if (t === 'big') m += z > 0.5 ? 0.03 : z < -0.3 ? -0.06 : 0;      // 기초가 약하면 진도를 못 따라간다
  if (t === 'director') m += z < 0.3 ? 0.03 : 0.01;                // 소규모라 하위·중위권을 끌어올리는 힘이 크다
  if (t === 'tutor') m += (s.tutorQ && s.tutorQ[k] != null ? s.tutorQ[k] : 0);
  if (t === 'managed') m += p.diligence <= 2 ? 0.03 : 0;
  return m;
}
function acadCost(s) { const g = s.p.region === 'gangnam' ? 1.3 : 1; return SUB_KEYS.reduce((t, k) => t + ACAD[s.acad[k] || 'none'].cost, 0) * g; }
function acadText(s) { const on = SUB_KEYS.filter(k => s.acad[k] && s.acad[k] !== 'none'); return on.length ? on.map(k => `${SUBJ_NAME[k]} ${ACAD[s.acad[k]].name}`).join(', ') : '학원 없이 독학'; }

// ── 국어 세부 영역 ─────────────────────────────────────────
//  국어 실력(sub.kor) 위에 영역별 편차(korOff)를 둔다. 독서는 문해력(영어·탐구 연계, 논술, 면접)으로,
//  문학·화법·언어·매체는 내신 국어·서술형·수행평가로 이어진다. 국어를 어떻게 공부하느냐(korFocus)에 따라 영역이 달리 오른다.
// 지나온 1·2학년 학력평가를 어떻게 봤나(중간에서 시작할 때 입력)
const PAST_MOCK = {
  real:   { name: '실전처럼 준비하고 오답까지 정리했다', v: 0.85 },
  review: { name: '따로 준비는 안 했지만 오답은 봤다', v: 0.55 },
  casual: { name: '그냥 봤다(성적표만 확인)', v: 0.3 },
  skip:   { name: '대충 찍고 자거나 거의 안 봤다', v: 0.05 },
};
const KOR_PARTS = [{ k: 'read', name: '독서(비문학)' }, { k: 'lit', name: '문학' }, { k: 'lang', name: '화법·언어·매체' }];
const KOR_FOCUS = {
  read:   { name: '독서 지문 매일 풀기', w: { read: 1, lit: 0.2, lang: 0.1 }, eff: 1.0 },
  lit:    { name: '문학 작품·개념어 정리', w: { read: 0.2, lit: 1, lang: 0.1 }, eff: 1.0 },
  lang:   { name: '문법·화법 개념 정리', w: { read: 0.1, lit: 0.2, lang: 1 }, eff: 1.0 },
  gichul: { name: '평가원 기출 분석', w: { read: 0.6, lit: 0.6, lang: 0.4 }, eff: 1.07 },
  mock:   { name: '사설 모의고사 반복 풀이', w: { read: 0.4, lit: 0.4, lang: 0.3 }, eff: 0.93 },
  hw:     { name: '학원 숙제만', w: { read: 0.4, lit: 0.4, lang: 0.4 }, eff: 0.97 },
  drop:   { name: '접는다 — 수업만 듣고 최소한만', w: { read: 0.3, lit: 0.3, lang: 0.3 }, eff: 0.5, drop: true },
};
// 공부법마다 모의고사(실전) 쪽으로 쌓이는 정도(mock)와 학교 내신 쪽으로 쌓이는 정도(nae)
Object.assign(KOR_FOCUS.read, { mock: 0.6, nae: 0.3 }); Object.assign(KOR_FOCUS.lit, { mock: 0.35, nae: 0.8 }); Object.assign(KOR_FOCUS.lang, { mock: 0.35, nae: 0.65 });
Object.assign(KOR_FOCUS.gichul, { mock: 0.9, nae: 0.35 }); Object.assign(KOR_FOCUS.mock, { mock: 1, nae: 0.1 }); Object.assign(KOR_FOCUS.hw, { mock: 0.5, nae: 0.55 }); Object.assign(KOR_FOCUS.drop, { mock: 0.1, nae: 0.1 });
// 과목을 접는 것(수포자·영포자)은 흔한 전략이다. 시간을 다른 과목에 몰아주는 대신 그 과목을 보는 대학·최저가 닫힌다
const DROP_HINT = {
  kor: '국어는 거의 모든 대학·모든 전형이 본다 · 접으면 갈 곳이 거의 없다',
  math: '국어·영어·탐구에 시간을 몬다 · 상경·이공계와 중경외시 이상 정시는 사실상 닫힌다. 3과목 반영 대학(광명상가 이하)은 열려 있다',
  eng: '절대평가라 3등급까지는 쉬운 편 · 완전히 접으면 최저(영어 포함)와 정시 감점이 크다',
  inq: '시간을 국·수·영에 몬다 · 3합 최저가 어려워지고 이과 정시 탐구 30%를 잃는다',
};
const DROP_METHOD = k => ({ name: '접는다 — 수업만 듣고 최소한만', eff: 0.5, mock: 0.1, nae: 0.1, drop: true, hint: DROP_HINT[k] });

// ── 과목별 공부법 ──────────────────────────────────────────
//  같은 시간을 써도 방법이 실력에 맞아야 오른다. eff: 수능·모의고사 실력 효율, fit: 지금 실력(z)에 따른 보정,
//  mock: 모의고사(실전)로 쌓이는 정도 — 1·2학년 때 쌓인 만큼 고3 모의고사·수능에서 시간 배분과 실전 감각으로 돌아온다,
//  nae: 학교 내신 시험에 맞는 정도
const SUBJ_METHODS = {
  kor: KOR_FOCUS,
  math: {
    concept: { name: '개념서·교과서 예제부터 다시', eff: 1.0, fit: z => (z < -0.2 ? 0.1 : z > 1 ? -0.08 : 0.02), mock: 0.2, nae: 0.75, hint: '기초가 약할수록 효과가 크다 · 상위권에겐 느리다' },
    drill:   { name: '유형 문제집(쎈·RPM) 반복', eff: 1.0, fit: z => (z > -0.6 && z < 1 ? 0.04 : -0.02), mock: 0.4, nae: 0.85, hint: '내신·중위권에 강하다 · 처음 보는 문제엔 약하다' },
    gichul:  { name: '평가원 기출·4점 문항 분석', eff: 1.0, fit: z => (z > 0.3 ? 0.08 : z < -0.5 ? -0.12 : 0), mock: 0.9, nae: 0.3, hint: '수능형 사고력 · 개념이 비어 있으면 손도 못 댄다' },
    mock:    { name: '실전 모의고사 시간 재고 풀기', eff: 0.92, fit: z => (z > 0.8 ? 0.06 : -0.04), mock: 1, nae: 0.1, hint: '시간 감각 · 구멍 난 개념은 그대로' },
    wrong:   { name: '틀린 문제만 오답노트로 다시', eff: 0.98, fit: (z, s) => (s.p.diligence - 3) * 0.035, mock: 0.55, nae: 0.6, hint: '같은 실수를 줄인다 · 꾸준하지 않으면 노트만 남는다' },
    hw:      { name: '학원 숙제만', eff: 0.97, mock: 0.45, nae: 0.6, hint: '방향 고민이 없다 · 학원 수준만큼 오른다' },
    drop:    DROP_METHOD('math'),
  },
  eng: {
    voca:    { name: '단어 매일 + 구문 독해', eff: 1.0, fit: z => (z < 0.8 ? 0.08 : -0.05), mock: 0.4, nae: 0.5, hint: '기초 체력 · 상위권엔 효과가 작다' },
    gichul:  { name: '기출 지문 분석(빈칸·순서·삽입)', eff: 1.0, fit: z => (z > 0 ? 0.06 : -0.03), mock: 0.9, nae: 0.3, hint: '수능 유형에 강해진다 · 단어가 약하면 막힌다' },
    mock:    { name: '모의고사 풀이 위주', eff: 0.93, fit: z => (z > 1 ? 0.04 : 0), mock: 1, nae: 0.1, hint: '시간 관리 · 실력 자체는 천천히 오른다' },
    naesin:  { name: '교과서·부교재 본문 암기', eff: 0.88, mock: 0.1, nae: 1, hint: '내신 영어에 강하다 · 처음 보는 지문엔 약하다' },
    hw:      { name: '학원 숙제만', eff: 0.97, mock: 0.45, nae: 0.6, hint: '방향 고민이 없다 · 학원 수준만큼 오른다' },
    drop:    DROP_METHOD('eng'),
  },
  inq: {
    concept: { name: '개념 정리 + 백지 복습', eff: 1.05, mock: 0.3, nae: 0.75, hint: '오래 남는다 · 시간이 많이 든다' },
    gichul:  { name: '기출 문제집 3회독', eff: 1.03, fit: z => (z < -0.8 ? -0.06 : 0), mock: 0.9, nae: 0.4, hint: '수능 출제 패턴이 보인다 · 개념이 없으면 답만 외운다' },
    mock:    { name: '실전 모의고사 위주', eff: 0.9, fit: z => (z > 0.6 ? 0.06 : -0.05), mock: 1, nae: 0.1, hint: '시간 감각 · 개념이 약하면 같은 데서 계속 틀린다' },
    cram:    { name: '시험 직전에 몰아서 암기', eff: 0.78, mock: 0.1, nae: 0.6, hint: '내신은 버틴다 · 수능 땐 다 잊어버린다' },
    hw:      { name: '학원 숙제만', eff: 0.97, mock: 0.45, nae: 0.6, hint: '방향 고민이 없다 · 학원 수준만큼 오른다' },
    drop:    DROP_METHOD('inq'),
  },
};
SUBJ_METHODS.kor.drop.hint = DROP_HINT.kor;
const isDropped = (s, k) => methodOf(s, k) === 'drop';
const droppedList = s => SUB_KEYS.filter(k => isDropped(s, k));
// 접은 과목이 전략으로 말이 되는가: 문과 수포자가 광명상가 이하를 노리면 그럴 수 있다. 나머지는 손해다
function dropPrior(k, track, goalGi, z) {
  if (k === 'kor') return -3.5;
  if (k === 'math') return track === '자연' ? -3.5 : goalGi >= 6 && z < -0.3 ? -0.2 : goalGi >= 4 ? -1.2 : -2.5;
  if (k === 'eng') return -1.8;
  return track === '자연' ? -3 : goalGi >= 6 && z < -0.5 ? -0.8 : -2.2;
}
const METHOD_TAGS = { drop: ['risk', 'self'], concept: ['study', 'safe'], drill: ['study', 'safe'], gichul: ['study', 'self'], mock: ['study', 'risk'], wrong: ['study', 'self'], hw: ['obey', 'safe'],
  voca: ['study', 'safe'], naesin: ['study', 'safe'], cram: ['fun', 'risk'], read: ['study'], lit: ['study', 'safe'], lang: ['study', 'safe'] };
function methodOf(s, k) { return k === 'kor' ? s.korFocus : (s.method && s.method[k]) || 'hw'; }
function methodInfo(s, k) { const M = SUBJ_METHODS[k]; return M[methodOf(s, k)] || M.hw; }
function methodEff(s, k) { const M = methodInfo(s, k); return M.eff + (M.fit ? M.fit(s.sub[k], s) : 0); }
function defaultMethod(s, k) { const ac = s.acad[k] && s.acad[k] !== 'none' && s.acad[k] !== 'online'; if (ac) return 'hw'; return { kor: 'mock', math: 'drill', eng: 'voca', inq: 'concept' }[k]; }

// ── 정시 합격선: 대학어디가 2023~2026 정시 발표 자료의 '최종 70%컷'(백분위) ─────────────
//  대학·계열별로 4개 연도 일반전형 학과들의 중앙값. [인문, 자연]. 이름 없는 수도권 4년제는 그 지역 나머지 대학들의 하위 25%,
//  지방 4년제는 하위 10% 값이다(그 정도면 갈 수 있는 곳이 생긴다는 뜻).
//  자료: https://ppakangna-svg.github.io/jungsiipgyeol23-26/
const PCT70 = {
  서울대: [96.8, 95.8], 연세대: [91.5, 94], 고려대: [94, 94.7], 서강대: [91, 92], 성균관대: [92.5, 94.2], 한양대: [92.3, 92.5],
  중앙대: [90.9, 91], 경희대: [88, 88.8], 한국외대: [87.5, 88.3], 서울시립대: [87.7, 89.8], 이화여대: [89.3, 90],
  건국대: [87.3, 89], 동국대: [87.1, 88.2], 홍익대: [86.6, 87.5], 국민대: [85.9, 86.5], 숭실대: [83.5, 85], 세종대: [82.8, 83], 단국대: [83.3, 83.3],
  광운대: [80.5, 81], 명지대: [79.7, 79.3], 상명대: [80, 81], 가톨릭대: [79.3, 83], 인하대: [79.8, 83], 아주대: [82, 84.8],
  부산대: [80, 79.5], 경북대: [78.1, 78.5], 전남대: [73.2, 73.7], 충남대: [75, 75.5], 충북대: [71, 69.4], 전북대: [69.2, 67.3],
  서울교대: [87.7, 87.7], 경인교대: [83.3, 83.3], 부산교대: [79, 79], 대구교대: [80, 80], 광주교대: [79, 79], 청주교대: [70.8, 70.8], 공주교대: [78.5, 78.5],
  춘천교대: [80.2, 80.2], 전주교대: [80.2, 80.2], 진주교대: [78, 78], 한국교원대: [85.5, 86.3],
  '수도권 4년제 대학': [71.4, 71.4], '지방 4년제 대학': [46, 46], 전문대학: [15, 15],   // 전문대는 사실상 성적 제한이 거의 없다
};
const PCT70_SRC = '대학어디가 2023~2026 정시 최종 70%컷';
const ENG_PEN = [0, 0.6, 1.8, 3.4, 5.2, 7, 9, 11, 13];   // 영어 등급에 따른 감점(백분위 점수 기준, 대략값)
const pctile = z => clamp(100 * phi(z), 0, 100);
function pctOf(sub) { const o = {}; SUB_KEYS.forEach(k => { o[k] = Math.round(pctile(sub[k]) * 10) / 10; }); return o; }
// 정시 점수: 국·수·탐 백분위를 계열 반영 비율로 평균(절반은 단순 평균), 영어는 등급 감점
const ENG_AS_PCT = [97, 92, 85, 75, 62, 50, 38, 25, 12];   // 3과목 반영 대학에서 영어를 백분위처럼 칠 때
function jungsiScore(sub, field, gi) {
  const w = subjWeights(field), P = pctOf(sub), d = w.kor + w.math + w.inq;
  // 중하위권 인문(광명상가 이하)은 국·수·영·탐 중 잘 본 3과목만 보는 대학이 많다 — 수포자가 가는 길
  if (gi != null && gi >= 6 && trackIdx(field) === 0) {
    const e = ENG_AS_PCT[subjGrade('eng', sub.eng) - 1];
    const top3 = [P.kor, P.math, P.inq, e].sort((a, b) => b - a).slice(0, 3);
    return (top3[0] + top3[1] + top3[2]) / 3 - 1.5;
  }
  const weighted = (w.kor * P.kor + w.math * P.math + w.inq * P.inq) / d, plain = (P.kor + P.math + P.inq) / 3;
  return (weighted + plain) / 2 - ENG_PEN[subjGrade('eng', sub.eng) - 1];
}
const trackIdx = field => (FIELDS[field] && FIELDS[field].track === '자연' ? 1 : 0);
function uniCut(uni, field) { const c = PCT70[uni]; return c ? c[trackIdx(field)] : null; }
function tierCut(t, field) { const cs = t.unis.map(u => uniCut(u, field)).filter(v => v != null).sort((a, b) => a - b); return cs.length ? cs[Math.floor(cs.length / 2)] : null; }
const usesPct = (field, list) => !SILGI[field] && list.every(t => t.fo !== 'med' && tierCut(t, field) != null);
// 지금 성적이면 정시로 어디쯤인가 — 자료의 70%컷과 비교
function jungsiFit(s, sub) {
  const field = s.applyField || (s.track === '자연' ? 'eng' : 'biz'), sc = jungsiScore(sub, field);
  const list = TIERS.slice(0, 10), ti = trackIdx(field);
  let best = null;
  list.forEach(t => t.unis.forEach(u => { const c = uniCut(u, field), sc2 = jungsiScore(sub, field, t.gi); if (c != null && c <= sc2 + 0.3 && (!best || c > best.cut)) best = { uni: u, cut: c }; }));
  return { score: Math.round(sc * 10) / 10, uni: best ? best.uni : '전문대학', cut: best ? best.cut : null, track: ti ? '자연' : '인문' };
}
function jungsiFitText(s, sub) { const f = jungsiFit(s, sub); return `국수탐 백분위 환산 ${f.score.toFixed(1)}점 — ${PCT70_SRC}로 보면 ${f.uni}${f.cut != null ? `(${f.track} ${f.cut})` : ''} 수준`; }
const korPart = (s, k) => s.sub.kor + (s.korOff ? s.korOff[k] : 0);
function korGrades(s, base) { const b = base != null ? base : s.sub.kor; const o = {}; KOR_PARTS.forEach(({ k }) => { o[k] = grade9(topFromZ(b + s.korOff[k])); }); return o; }
function korText(g) { return `독서 ${g.read} · 문학 ${g.lit} · 화법·언어·매체 ${g.lang}`; }

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
    startTurn: null, subject: null, subj: null,
    pJob: 'office', pBond: 'good', romanceNow: 'none', screen: 2, academies: 1, clarity: 2, acad: null, korFocus: null, pastMock: 'casual',
    artKind: null, artLv: 3, artAcad: 'local', dropped: [],
  };
  const out = Object.assign({}, d, p || {});
  out.hobbies = (out.hobbies || []).filter(h => HOBBIES[h]).slice(0, 3);
  // 시작 시점: 고1 1학기(0) ~ 고3 2학기(10). 없으면 학년의 1학기로
  let st = parseInt(out.startTurn, 10);
  if (!(st >= 0 && st < HS_TURNS.length)) st = (clamp(parseInt(out.grade, 10) || 1, 1, 3) - 1) * 4;
  if (st > 9) st = 9;   // 원서(고3 여름)는 건너뛸 수 없다
  out.startTurn = st;
  out.grade = st < 4 ? 1 : st < 8 ? 2 : 3;
  out.screen = clamp(parseInt(out.screen, 10) || 2, 1, 4);
  out.academies = clamp(parseInt(out.academies, 10) || 0, 0, 3);
  // 과목별 학원: 없으면 학원 수만큼 '대형 학원'으로 채운다(예전 설정과 호환)
  const acad = {};
  SUB_KEYS.forEach((k, i) => { const v = out.acad && out.acad[k]; acad[k] = ACAD[v] ? v : (!out.acad && i < out.academies ? 'big' : 'none'); });
  out.acad = acad;
  out.academies = SUB_KEYS.filter(k => acad[k] !== 'none' && acad[k] !== 'online').length;
  if (!KOR_FOCUS[out.korFocus]) out.korFocus = null;
  if (!PAST_MOCK[out.pastMock]) out.pastMock = 'casual';
  // 예체능: 계열이 '예체'면 종류(미술·음악·체육)·실기 수준·학원이 따라온다. 학과 공부 쪽 계열은 인문으로 둔다
  if (out.track === '예체' || out.track === '예체능') { out.track = '예체'; if (!ARTS_FIELD[out.artKind]) out.artKind = 'art'; }
  else out.artKind = null;
  out.artLv = clamp(parseInt(out.artLv, 10) || 3, 1, 5);
  if (!ARTS_ACAD[out.artAcad]) out.artAcad = 'local';
  out.dropped = Array.isArray(out.dropped) ? out.dropped.filter(k => SUB_KEYS.indexOf(k) >= 0) : [];
  out.clarity = clamp(parseInt(out.clarity, 10) || 2, 1, 3);
  if (out.subj) ['kor', 'math', 'eng', 'inq'].forEach(k => { out.subj[k] = clamp(+out.subj[k] || 5, 1, 9); });
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
    zN: zFromTop(p.gpaPct),
    sub: {}, csatSub: null, csatG: null,
    naesinRec: [], mocks: [], mockG: [],
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
    rivalName: null,
    romance: { status: 'none', partner: null, studious: false, since: 0, score: 0, count: 0, firstLove: null },
    interest: {}, talent: { art: 15, perf: 15, sport: 25, code: 12, verbal: 20, people: 15 + p.social * 5, media: 12, game: 15, craft: 10 },
    money: { high: 110, mid: 60, low: 22 }[p.wealth] || 60,
    track: p.track === '예체' ? '인문' : p.track,
    arts: p.track === '예체' ? p.artKind : null,       // 예체능 지망(미술·음악·체육)
    artsAcad: p.track === '예체' ? p.artAcad : 'none',
    subject: null,
    autonomy: 0,     // 내가 정한 길(+)인지 부모님이 정한 길(-)인지
    flags: {}, seen: {},
    log: [], history: [],
    turnIdx: 0, turnLabel: '', age: 16 + p.grade,
    phase: 'hs',
    uni: null, col: null, career: null, ending: null,
    attempts: 0,
  };
  SUB_KEYS.forEach(k => { s.sub[k] = p.subj ? subjFromGrade(k, p.subj[k]) : zFromTop(p.mockPct) + r.normal() * 0.15; });
  // 예전 코드가 쓰던 '수능형 실력 하나'(zC)는 네 과목 평균으로 보이고, 더하면 네 과목에 똑같이 더해진다
  Object.defineProperty(s, 'zC', { enumerable: true, get() { return meanSub(this.sub); }, set(v) { const d = v - meanSub(this.sub); SUB_KEYS.forEach(k => { this.sub[k] += d; }); } });
  s.rivalName = r.pick(FRIEND_NAMES.filter(n => n !== s.bestName));
  s.pressure = ps.pressure + (p.pDesire !== 'free' ? 14 : 0) + (p.sibling === 'better' ? 10 : 0) + (p.pJob === 'pro' ? 6 : 0);
  // 스마트폰·학원·부모님 사이·직업
  s.lazy = clamp(s.lazy + (p.screen - 2) * 7, 0, 100);
  s.acad = Object.assign({}, p.acad);
  s.tutorQ = {}; SUB_KEYS.forEach(k => { s.tutorQ[k] = r.normal() * 0.06; });   // 과외 선생님마다 실력 차이
  s.korOff = { read: r.normal() * 0.12, lit: r.normal() * 0.12, lang: r.normal() * 0.12 };
  s.korFocus = p.korFocus || (p.academies && s.acad.kor !== 'none' ? 'hw' : 'mock');
  s.method = {}; ['math', 'eng', 'inq'].forEach(k => { s.method[k] = defaultMethod(s, k); });
  (p.dropped || []).forEach(k => { if (k === 'kor') s.korFocus = 'drop'; else s.method[k] = 'drop'; s.flags['dropped_' + k] = true; });
  // 1·2학년 학력평가(모의고사)를 어떻게 봐 왔나 — 지나온 학기는 입력값으로 채운다
  s.mockPrep = 0; s.mockSem = 0; s.examSense = null;
  const pastSem = HS_TURNS.slice(0, Math.min(p.startTurn, 8)).filter(t => t.type === 'sem').length;
  s.mockPrep = PAST_MOCK[p.pastMock].v * pastSem; s.mockSem = pastSem;
  if (p.pBond === 'fight') { s.mental -= 8; s.stress += 6; }
  if (p.pBond === 'cold') { s.parentRel -= 6; }
  if (p.pBond === 'single') { s.money -= 14; s.mental -= 3; s.parentRel += 4; s.flags.singleParent = true; }
  if (p.pJob === 'labor') s.money -= 8;
  if (p.pJob === 'pro') s.money += 10;
  if (p.pJob === 'self') s.flags.familyBiz = true;
  s.money = Math.max(4, s.money);
  // 과목별 모의고사 등급
  if (p.subj) {
    const avg = (p.subj.kor + p.subj.math + p.subj.eng + p.subj.inq) / 4;
    s.talent.verbal += (5 - p.subj.kor) * 4 + (5 - p.subj.eng) * 2;
  }
  if (p.subject) { s.subject = p.subject; if (p.subject === 'phys' || p.subject === 'bio') s.track = '자연'; else if (p.subject !== 'easy') s.track = '인문'; }
  if (p.romanceNow === 'dating') { const nm = r.pick(NAMES); startDating(s, nm, r.chance(0.45)); s.romance.since = 1; s.romance.score = 60; }
  if (p.romanceNow === 'crush') s.flags.crushNow = r.pick(NAMES);
  FIELD_KEYS.forEach(f => { s.interest[f] = 5 + r.int(0, 6); s.recFit[f] = 0; });
  if (FIELDS[p.interest]) { s.interest[p.interest] += 25 + p.clarity * 8; s.recFit[p.interest] += p.recordLv * (p.clarity + 1); }
  p.hobbies.forEach(h => {
    const H = HOBBIES[h];
    Object.keys(H.talent).forEach(t => { s.talent[t] = (s.talent[t] || 0) + H.talent[t] + r.int(0, 12); });
    Object.keys(H.interest).forEach(f => { s.interest[f] += H.interest[f]; });
    s.lazy = clamp(s.lazy + H.lazy * 3, 0, 100);
  });
  const desire = PARENT_DESIRES[p.pDesire];
  if (desire && desire.field) s.interest[desire.field] += 8;   // 자라면서 스며든 부모님 기대
  if (p.track === '자연') ['med', 'eng', 'cs', 'sci', 'nurse'].forEach(f => { s.interest[f] += 4; });
  else if (p.track === '예체') {
    const f = ARTS_FIELD[p.artKind], tk = FIELDS[f].talent;
    s.interest[f] += 40; s.talent[tk] = clamp(28 + p.artLv * 12 + r.normal() * 5, 10, 95);
    s.flags[{ art: 'artPath', music: 'musicPath', sport: 'sportPath' }[p.artKind]] = true;
    s.flags.artsSince = p.startTurn;
  }
  else ['biz', 'law', 'hum', 'soc', 'media', 'edu'].forEach(f => { s.interest[f] += 4; });
  // 중간에서 시작하면 지난 학기 내신은 입력값으로 채운다
  const prevSem = HS_TURNS.slice(0, p.startTurn).filter(t => t.type === 'sem').length;
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
function Lf(s, text) { s.log.push({ t: s.turnLabel, text: text + ' (운)', kind: 'fate' }); s.fateSinceLast = text; (s.fates = s.fates || []).push({ t: s.turnLabel, text }); }
function L(s, text, kind) { s.log.push({ t: s.turnLabel, text, kind: kind || 'info', i: s.log.length }); }
function hasHobby(s, h) { return s.p.hobbies.indexOf(h) >= 0; }
const phoneHobby = s => ['game', 'video', 'webtoon', 'idol'].some(h => hasHobby(s, h));
// 관리형·원장 직강 학원에 다니는 과목이 많을수록 저녁 시간을 자습실에서 보낸다 → PC방·도박·싸움 같은 일에 덜 노출된다
const guarded = s => SUB_KEYS.filter(k => s.acad && (s.acad[k] === 'managed' || s.acad[k] === 'director')).length;
const expo = s => 1 - Math.min(0.55, guarded(s) * 0.2);
const hasDirector = s => SUB_KEYS.some(k => s.acad && s.acad[k] === 'director');
const noAcademy = s => SUB_KEYS.every(k => !s.acad || s.acad[k] === 'none' || s.acad[k] === 'online');
const parentWord = s => (s.p.pStyle === 'absent' ? '오랜만에 집에 온 아빠' : s.p.pStyle === 'anxious' ? '엄마' : s.p.pStyle === 'strict' ? '아빠' : '엄마');

// ── 질문하기 ─────────────────────────────────────────────
function Pending(prompt) { this.prompt = prompt; }
// ── 선택 평가: 한 선택 뒤 다음 질문까지 무엇이 달라졌나 ──────────────────
function snap(s) {
  return { zN: s.zN, zC: s.zC, zCsat: s.zCsat, mental: s.mental, stress: s.stress, health: s.health, lazy: s.lazy,
    parentRel: s.parentRel, social: s.social, record: s.record, gpa: s.col ? s.col.gpa : null, spec: s.col ? s.col.spec : null,
    prestige: s.uni ? s.uni.prestige : null, rom: s.romance.status, log: s.log.length, sub: Object.assign({}, s.sub) };
}
function judge(s, b, a) {
  let d = 0;
  d += ((a.zN - b.zN) * 0.7 + (a.zC - b.zC) * 0.9) * 40;
  if (a.zCsat != null && b.zCsat == null) d += (a.zCsat - a.zC) * 25;   // 수능 당일
  d += (a.mental - b.mental) * 0.12 + (a.parentRel - b.parentRel) * 0.08 + (a.social - b.social) * 0.07;
  d += (a.record - b.record) * 0.18 - (a.lazy - b.lazy) * 0.12 + (a.health - b.health) * 0.05 - (a.stress - b.stress) * 0.05;
  if (a.gpa != null && b.gpa != null) d += (a.gpa - b.gpa) * 12 + (a.spec - b.spec) * 0.15;
  if (a.prestige != null && b.prestige != null) d += (a.prestige - b.prestige) * 0.25;
  if (b.rom !== 'dating' && a.rom === 'dating') d += 2;
  if (b.rom === 'dating' && a.rom === 'broke') d -= 2;
  s.log.slice(b.log, a.log).forEach(l => { d += l.kind === 'good' ? 2.5 : l.kind === 'bad' ? -2.5 : l.kind === 'warn' ? -1 : 0; });
  return { score: Math.round(d * 10) / 10, verdict: d >= 2.5 ? 'good' : d <= -2.5 ? 'bad' : 'normal' };
}
// 선택 자체의 성격: 공부·생기부를 챙긴 선택은 대체로 좋고, 놀거나 미룬 선택은 대체로 나쁘다
const TAG_PRIOR = { study: 1.6, record: 1.0, self: 0.4, kind: 0.5, safe: 0.2, obey: 0, social: -0.2, work: 0, risk: -0.2, rest: 0, romance: -0.6, rebel: -0.9, fun: -2.2 };
function choicePrior(h, b) {
  const pr = h.prompt;
  if (pr.type === 'alloc') {
    const a = h.choice || {};
    const study = SUB_KEYS.reduce((t, k) => t + (a[k] || 0), 0);
    let v = (study - 6) * 0.8;
    SUB_KEYS.forEach(k => { if (pr.cats.some(c => c.id === k && !c.dropped) && !(a[k] > 0)) v -= k === 'kor' || k === 'math' ? 2.5 : 1.5; });
    if (!(a.rest > 0)) v -= 1.5; if ((a.rest || 0) >= 5) v -= 1;
    if (pr.cats.some(c => c.id === 'silgi')) { if (!(a.silgi > 0)) v -= 2.5; else if (a.silgi >= 2) v += 0.8; }
    if ((a.hobby || 0) + (a.friends || 0) + (a.date || 0) >= 7) v -= 1.5;
    return v;
  }
  if (pr.type === 'methods') {
    // 몰아서 암기·실력과 안 맞는 방법은 나쁘고, 실력에 맞는 방법은 좋다
    const c = h.choice || {};
    return SUB_KEYS.reduce((v, k) => { const id = c[k], M = SUBJ_METHODS[k][id]; if (!M) return v; const z = h.before.sub ? h.before.sub[k] : 0; if (id === 'drop') return v + dropPrior(k, (h.pp || {}).track, (h.pp || {}).goalGi != null ? h.pp.goalGi : 6, z); const e = M.eff + (M.fit ? M.fit(z, { p: h.pp || { diligence: 3 } }) : 0); return v + (e - 0.99) * 12 + (id === 'cram' ? -1.2 : 0); }, 0);
  }
  const tv = o => { const t = o.tags && o.tags.length ? o.tags : ['safe']; return t.reduce((x, k) => x + (k === 'rest' && b.stress >= 60 ? 1 : (TAG_PRIOR[k] || 0)), 0) / t.length; };
  const chosen = pr.options.find(o => o.id === h.choice);
  if (!chosen) return 0;
  const avg = pr.options.reduce((x, o) => x + tv(o), 0) / pr.options.length;
  return (tv(chosen) - avg) * 1.6;
}
function settle(s) {
  const h = s.history[s.history.length - 1];
  if (!h || h.verdict) return;
  const j = judge(s, h.before, snap(s));
  const prior = choicePrior(h, h.before);
  let score = j.score * 0.55 + prior * 1.2;
  // 그 사이에 운이 끼었으면 결과는 선택 탓이 아니다 — 선택의 성격만 본다
  if (s.fateSinceLast) { h.fate = s.fateSinceLast; s.fateSinceLast = null; score = prior * 1.2; if (!h.note) h.note = `이 구간엔 운이 끼었다 — ${h.fate} 결과가 나빠졌어도 선택 탓이 아니다.`; }
  // 핵심 과목을 통째로 비우거나, 놀기를 고른 선택은 결과가 잠깐 좋아 보여도 '좋은 선택'이 될 수 없다
  if (h.prompt.type === 'alloc') {
    const a = h.choice || {}, miss = SUB_KEYS.filter(k => h.prompt.cats.some(c => c.id === k && !c.dropped) && !(a[k] > 0));
    if (miss.length) { score = Math.min(score, miss.some(k => k === 'kor' || k === 'math') ? -2 : 1.5); h.note = `${miss.map(k => SUBJ_NAME[k]).join('·')}에 한 칸도 쓰지 않았다. 지금은 티가 안 나도 그 과목은 계속 떨어진다.`; }
  } else if (h.prompt.type === 'methods') {
    const bad = SUB_KEYS.filter(k => (h.choice || {})[k] === 'cram');
    if (bad.length) { score = Math.min(score, -1); h.note = '탐구를 시험 직전에 몰아서 외우면 내신은 버텨도 수능 날엔 대부분 잊어버린다.'; }
    const dr = SUB_KEYS.filter(k => (h.choice || {})[k] === 'drop');
    if (dr.length) { const pp = h.pp || {}; const ok = dr.every(k => dropPrior(k, pp.track, pp.goalGi != null ? pp.goalGi : 6, h.before.sub ? h.before.sub[k] : 0) > -1); h.note = ok ? `${dr.map(k => SUBJ_NAME[k]).join('·')}을(를) 접었다. 목표 대학 수준에서는 말이 되는 전략이다 — 대신 그 과목을 보는 대학과 최저는 포기한 셈이다.` : `${dr.map(k => SUBJ_NAME[k]).join('·')}을(를) 접었다. 지금 계열·목표에서는 그 과목 때문에 닫히는 문이 너무 많다.`; if (!ok) score = Math.min(score, -2); }
  } else {
    const ch = h.prompt.options.find(o => o.id === h.choice);
    if (ch && (ch.tags || []).indexOf('fun') >= 0 && score > 1.5) { score = 1.5; }
  }
  h.verdict = score >= 2 ? 'good' : score <= -2 ? 'bad' : 'normal';
  h.score = Math.round(score * 10) / 10;
  h.logs = [h.before.log, s.log.length];
}
function ask(ctx, prompt) {
  const s = ctx.s;
  settle(s);
  prompt.turn = s.turnLabel;
  prompt.age = s.age;
  const v = ctx.resolve(prompt, s);
  if (v === undefined) throw new Pending(prompt);
  s.history.push({ key: prompt.key, turn: s.turnLabel, title: prompt.title, prompt: stripPrompt(prompt), choice: v, idx: s.history.length, before: snap(s), pp: { diligence: s.p.diligence, track: s.track, goalGi: (GOALS[s.p.goal] || GOALS.inseoul).gi } });
  return v;
}
function stripPrompt(pr) {
  return { key: pr.key, type: pr.type, title: pr.title, text: pr.text, turn: pr.turn,
    options: pr.options ? pr.options.map(o => ({ id: o.id, label: o.label, tags: o.tags, w: o.w })) : undefined,
    cats: pr.cats ? pr.cats.map(c => ({ id: c.id, label: c.label, desc: c.desc, dropped: c.dropped })) : undefined, def: pr.def, total: pr.total,
    rows: pr.rows ? pr.rows.map(r => ({ k: r.k, name: r.name, def: r.def, options: r.options.map(o => ({ id: o.id, label: o.label, tags: o.tags })) })) : undefined };
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
  if (prompt.type === 'methods') {
    // 성향대로: 성실하고 목표가 높으면 기출·오답, 충동적이면 몰아서·모의고사만, 학원 다니면 숙제
    const out = {};
    prompt.rows.forEach(r => {
      const sc = id => (id === 'gichul' ? p.diligence * 0.5 + (s.sub[r.k] > 0.3 ? 0.8 : -0.4) : 0) + (id === 'hw' ? 1.6 + (p.pStyle === 'strict' ? 0.4 : 0) : 0)
        + (id === 'concept' ? (s.sub[r.k] < -0.2 ? 1.4 : 0.3) : 0) + (id === 'drill' || id === 'voca' ? 1.2 : 0) + (id === 'wrong' ? (p.diligence - 3) * 0.6 + 0.5 : 0)
        + (id === 'mock' ? p.impulse * 0.25 + 0.3 : 0) + (id === 'cram' ? p.impulse * 0.35 - p.diligence * 0.3 + 0.4 : 0) + (id === 'naesin' ? 0.6 : 0)
        + (id === r.def ? 0.5 : 0) + ((id === 'read' || id === 'lit' || id === 'lang') ? 0.4 : 0)
        + (id === 'drop' ? (r.def === 'drop' ? 3 : (r.k === 'math' && s.track !== '자연' && s.sub.math < -0.7 && p.diligence <= 3 && (GOALS[p.goal] || GOALS.inseoul).gi >= 6 ? 1.6 : -6)) : 0);
      out[r.k] = r.options.reduce((b, o) => (sc(o.id) > sc(b) ? o.id : b), r.options[0].id);
    });
    return out;
  }
  let best = prompt.options[0].id, bv = -1e9;
  prompt.options.forEach((o, i) => {
    const tags = o.tags && o.tags.length ? o.tags : ['safe'];
    const v = tags.reduce((a, t) => a + (W[t] != null ? W[t] : 1), 0) / tags.length + (o.w || 0) - i * 0.01;
    if (v > bv) { bv = v; best = o.id; }
  });
  return best;
}
const ALLOC_TOTAL = 12;
function defaultAlloc(s, cats) {
  const p = s.p, ids = cats.map(c => c.id), T = ALLOC_TOTAL;
  const studyW = 2.6 + p.diligence * 0.95 - p.impulse * 0.25 + (s.acad ? SUB_KEYS.filter(k => s.acad[k] !== 'none').length : p.academies) * 0.35 + (p.pStyle === 'strict' || p.pStyle === 'anxious' ? 0.5 : 0);
  const avg = meanSub(s.sub), wt = subjWeights(s.track === '자연' ? 'eng' : 'biz');
  const need = {}; let nt = 0;
  SUB_KEYS.forEach(k => { need[k] = isDropped(s, k) ? 0.001 : Math.max(0.4, 1 + 0.35 * (avg - s.sub[k]) + (wt[k] - 0.25) * 2); nt += need[k]; });
  const w = {
    kor: studyW * need.kor / nt, math: studyW * need.math / nt, eng: studyW * need.eng / nt, inq: studyW * need.inq / nt,
    activity: 0.4 + p.curiosity * 0.3,
    silgi: artsField(s) ? 3.2 : 0,
    hobby: 0.6 + p.impulse * 0.35,
    friends: 0.3 + p.social * 0.35,
    rest: 1.2,
    date: 1.2,
    work: p.wealth === 'low' ? 1 : 0,
  };
  const raw = ids.map(id => Math.max(0, w[id] || 0));
  const tot = raw.reduce((a, b) => a + b, 0) || 1;
  const out = {}; let used = 0;
  ids.forEach((id, i) => { out[id] = Math.floor(raw[i] / tot * T); used += out[id]; });
  // 남는 칸은 큰 순서대로
  const order = ids.map((id, i) => [id, raw[i] / tot * T - out[id]]).sort((a, b) => b[1] - a[1]);
  for (let i = 0; used < T; i = (i + 1) % order.length) { out[order[i][0]]++; used++; }
  // 학원 다니는 과목은 복습 시간 2칸을 먼저 챙긴다(놀거나 쉬는 칸에서 가져온다)
  if (s.acad) SUB_KEYS.forEach(k => {
    if (ids.indexOf(k) < 0 || s.acad[k] === 'none' || s.acad[k] === 'online') return;
    while (out[k] < 2) {
      const donor = ['hobby', 'friends', 'date', 'rest', 'activity'].filter(d => ids.indexOf(d) >= 0 && out[d] > (d === 'rest' ? 1 : 0)).sort((x, y) => out[y] - out[x])[0];
      if (!donor) break;
      out[donor]--; out[k]++;
    }
  });
  return out;
}
function normAlloc(a, cats) {
  const out = {}, T = ALLOC_TOTAL; let t = 0;
  cats.forEach(c => { out[c.id] = clamp(Math.round(+((a || {})[c.id]) || 0), 0, T); t += out[c.id]; });
  // 칸을 넘으면 뒤에서부터 줄이고, 모자라면 휴식에 넣는다
  for (let i = cats.length - 1; t > T && i >= 0; i--) { const cut = Math.min(out[cats[i].id], t - T); out[cats[i].id] -= cut; t -= cut; }
  if (t < T) out.rest = (out.rest || 0) + (T - t);
  SUB_KEYS.concat(['activity', 'silgi', 'hobby', 'friends', 'rest', 'date', 'work']).forEach(k => { if (out[k] == null) out[k] = 0; });
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

function subjectCats(s) {
  const g = mockGrades(s.sub), sci = s.track === '자연';
  const base = [
    { id: 'kor', label: '국어', desc: `지금 ${g.kor}등급. 독해력·문해력은 영어 장문과 탐구 지문 이해에도 그대로 쓰인다.` },
    { id: 'math', label: '수학', desc: `지금 ${g.math}등급. ${sci ? '이과 정시 반영 비율이 가장 높고, 물리·화학 계산에도 도움이 된다.' : '정시 문과에서도 등급 차이를 크게 가른다.'}` },
    { id: 'eng', label: '영어', desc: `지금 ${g.eng}등급(절대평가). 수능 최저에 자주 들어간다. 국어 독해력이 약하면 장문에서 막힌다.` },
    { id: 'inq', label: '탐구', desc: `지금 ${g.inq}등급. 암기가 중요하고, 지문을 빨리 읽을수록 유리하다.` },
  ];
  base.forEach(c => { if (isDropped(s, c.id)) { c.desc = `접은 과목 (지금 ${g[c.id]}등급). 0칸이어도 평가에서 깎지 않는다. 수업만 듣는다.`; c.dropped = true; } });
  return base;
}
function allocCats(s, turn) {
  const cats = [
    ...subjectCats(s),
    { id: 'activity', label: '생기부 활동', desc: '동아리·탐구·봉사. 학종에 쓰인다.' },
    { id: 'hobby', label: '취미', desc: s.p.hobbies.length ? s.p.hobbies.map(h => HOBBIES[h].name).join('·') : '좋아하는 것' },
    { id: 'friends', label: '친구', desc: FRIEND_GROUPS[s.friendGroup].name },
    { id: 'rest', label: '휴식·잠', desc: '체력과 멘탈을 채운다.' },
  ];
  if (s.romance.status === 'dating') cats.push({ id: 'date', label: '연애', desc: s.romance.partner + '와(과)의 시간' });
  if (s.p.wealth === 'low' || s.flags.work) cats.push({ id: 'work', label: '아르바이트', desc: '용돈·생활비' });
  const af = artsField(s);
  if (af) { const tk = FIELDS[af].talent; cats.splice(4, 0, { id: 'silgi', label: { art: '실기(그림)', perf: '실기(연습)', sport: '실기(훈련)' }[af], desc: `지금 실기 ${Math.round(s.talent[tk])}점 · ${ARTS_ACAD[s.artsAcad || 'none'].name}. 실기는 손을 놓으면 바로 무뎌진다.` }); }
  return cats;
}

// 고교를 마쳤을 때의 과목 등급(수능, 없으면 지금 모의고사)
function endG(s) { return s.csatG || mockGrades(s.sub); }
const STEM = ['eng', 'cs', 'sci', 'med', 'nurse'];
// 진로 결과에 들어가는 과목 실력: 이공계는 수학, 상경은 수학·영어, 인문·법·미디어는 국어·영어
function subjCareerBonus(s, field) {
  const G = endG(s);
  if (STEM.indexOf(field) >= 0) return Math.max(-3, (4 - G.math) * 1) + (4 - G.eng) * 0.5;
  if (field === 'biz') return (4 - G.math) * 1 + (4 - G.eng) * 1;
  if (['hum', 'law', 'media', 'soc', 'edu'].indexOf(field) >= 0) return (4 - G.kor) * 1.2 + (4 - G.eng) * 0.8;
  return (4 - G.kor) * 0.5 + (4 - G.eng) * 0.5;
}
// 한 과목을 놓았을 때 / 붙잡았을 때 생기는 일
const SUBJ_DOWN = {
  kor: (g0, g1, s) => `국어 ${g0}→${g1}등급. 국어를 거의 안 봤더니 비문학 지문 읽는 속도부터 느려졌다. 영어 장문, 탐구 자료 해석에서도 시간이 모자라기 시작했다.${s.applyField && ['hum', 'law', 'media', 'edu', 'biz', 'soc'].indexOf(s.applyField) >= 0 ? ' 문과 정시는 국어 반영 비율이 가장 높다.' : ''}`,
  math: (g0, g1, s) => `수학 ${g0}→${g1}등급. 한 학기 손을 놓았더니 다음 단원 개념이 이해가 안 된다. 수학은 앞 단원에 구멍이 나면 뒤가 줄줄이 무너진다.${s.track === '자연' ? ' 이대로면 공대·자연대 지원 자체가 어려워진다.' : ' 상경 계열 지원과 정시 등급 합에 바로 타격이 온다.'}`,
  eng: (g0, g1) => `영어 ${g0}→${g1}등급. 단어를 안 외웠더니 빈칸·순서 문제에서 감이 사라졌다. 영어는 거의 모든 대학의 수능 최저에 들어간다.`,
  inq: (g0, g1, s) => `탐구 ${g0}→${g1}등급. "탐구는 막판에 외우면 된다"며 미뤘는데 외울 양만 쌓였다.${s.track === '자연' ? ' 이과 정시는 탐구 반영 비율이 30%다.' : ' 수능 최저에서 탐구 한 과목이 빠지면 등급 합을 맞추기 어렵다.'}`,
};
const SUBJ_UP = {
  kor: (g0, g1) => `국어 ${g0}→${g1}등급. 지문 구조가 보이기 시작했다. 영어 장문과 탐구 자료도 덜 막힌다.`,
  math: (g0, g1) => `수학 ${g0}→${g1}등급. 개념 구멍을 메우니 처음 보는 문제도 접근이 된다.`,
  eng: (g0, g1) => `영어 ${g0}→${g1}등급. 단어가 쌓이니 지문이 한 번에 읽힌다. 수능 최저가 한결 편해졌다.`,
  inq: (g0, g1) => `탐구 ${g0}→${g1}등급. 개념이 정리되니 자료 해석 문제도 빨라졌다.`,
};

// 과목별 공부 효과 — 국어 문해력이 영어·탐구 효율을, 이과 수학이 탐구 계산을 끌어올린다
function studySubjects(s, a, coef, r, quiet) {
  const p = s.p, st = STYLES[p.style] || STYLES.steady, fg = FRIEND_GROUPS[s.friendGroup];
  const lossFrac = clamp((s.lazy - 22) / 115, 0, 0.5);
  const planned = SUB_KEYS.reduce((t, k) => t + (a[k] || 0), 0);
  const lost = planned * lossFrac;
  if (!quiet && lost >= 0.8) L(s, `계획한 공부 ${planned}칸 중 약 ${lost.toFixed(1)}칸이 핸드폰·딴짓으로 증발했다. (나태 ${Math.round(s.lazy)})`, 'warn');
  const cond = 0.72 + s.mental / 380 + s.health / 420 - (s.stress > 70 ? 0.08 : 0);
  const goal = GOALS[p.goal] || GOALS.inseoul;
  const motive = 1 + (goal.gi <= 3 && p.diligence >= 3 ? 0.05 : 0) + (s.flags.fireUp ? 0.06 : 0);
  // 문해력은 국어 중에서도 독서(비문학) 실력이다
  const lit = clamp(korPart(s, 'read'), -1.5, 2);
  const mathL = clamp(s.sub.math, -1.5, 2);
  const sci = s.track === '자연';
  s.neglect = s.neglect || { kor: 0, math: 0, eng: 0, inq: 0 };
  // 수학 구멍: 두 학기 넘게 놓으면 생기고, 3칸 이상씩 두 학기를 해야 메워진다. 구멍이 있으면 수학 공부 효율이 떨어진다
  const hole = s.flags.mathHole ? 0.7 : 1;
  const mult = { kor: 1, math: (1 + 0.04 * lit) * hole, eng: 1 + 0.1 * lit, inq: 1 + 0.08 * lit + (sci ? 0.06 * mathL : 0) };
  const eff = {}; let effSum = 0;
  const wasted = [];
  SUB_KEYS.forEach(k => {
    const t = s.acad[k] || 'none', b = a[k] || 0;
    let am = acadMult(s, k);
    // 학원만 다니고 복습·숙제 시간이 없으면 효과가 반으로 준다
    if (t !== 'none' && t !== 'online' && b < 2) { am = 1 + (am - 1) * 0.4; wasted.push(k); }
    const loss = lossFrac * (1 - ACAD[t].lazyCut);
    // 공부법이 지금 실력에 맞는가. 고3에는 1·2학년 때 쌓은 실전 감각(약점을 아는 정도)도 효율에 들어간다
    const kf = methodEff(s, k) + (s.examSense != null ? s.examSense * 0.25 : 0);
    eff[k] = b * (1 - loss) * subjAbility(p, k) * cond * motive * am * kf; effSum += eff[k];
  });
  const spill = { kor: 0, math: 0, eng: eff.kor * 0.025, inq: eff.kor * 0.025 + (sci ? eff.math * 0.025 : 0) };
  const before = mockGrades(s.sub);
  SUB_KEYS.forEach(k => {
    const b = a[k] || 0;
    if (b <= 1) s.neglect[k]++; else if (b >= 3) s.neglect[k] = Math.max(0, s.neglect[k] - 1);
    const base = 1.63 + Math.max(0, s.sub[k]) * 0.22 + Math.max(0, s.sub[k] - 1.5) * 0.35;   // 최상위권은 경쟁이 더 치열하다
    // 안 하면 잊어버린다: 놓은 학기가 이어질수록 더 크게 떨어진다
    const forget = b <= 1 ? 0.045 * Math.min(4, s.neglect[k]) : 0;
    const d = (eff[k] * mult[k] * st.csat - base) * coef + spill[k] + fg.study * (a.friends || 0) * 0.7 - forget;
    // 내려갈 때도 바닥 근처에서는 천천히 내려간다(이미 안 하는 학생이 많은 구간)
    s.sub[k] += d > 0 ? d * damp(s.sub[k]) : d * (s.sub[k] < -0.8 ? 0.45 : 1);
  });
  // 국어 영역: 공부법에 따라 오르는 영역이 다르고, 손을 놓은 영역은 조금씩 처진다
  if ((a.kor || 0) >= 2) {
    const F = KOR_FOCUS[s.korFocus] || KOR_FOCUS.mock, sc = Math.min(1.5, (a.kor || 0) / 3);
    const mean = (F.w.read + F.w.lit + F.w.lang) / 3;
    KOR_PARTS.forEach(({ k }) => { s.korOff[k] = clamp(s.korOff[k] + (F.w[k] - mean) * 0.08 * sc, -0.9, 0.9); });
    if (s.acad.kor === 'director') { const wk = KOR_PARTS.reduce((w, x) => (s.korOff[x.k] < s.korOff[w] ? x.k : w), 'read'); s.korOff[wk] += 0.04; }   // 원장 직강: 약한 영역을 골라 메워 준다
  }
  if (!s.flags.mathHole && s.neglect.math >= 2) { s.flags.mathHole = true; s.mathFix = 0; if (!quiet) L(s, '수학에 구멍이 생겼다. 앞 단원을 비워 둔 채 다음 단원을 들으니 수업이 외국어처럼 들린다. 메우려면 몇 학기 동안 수학에 시간을 크게 써야 한다.', 'bad'); }
  else if (s.flags.mathHole && (a.math || 0) >= 3) { s.mathFix = (s.mathFix || 0) + 1; if (s.mathFix >= 2) { s.flags.mathHole = false; if (!quiet) L(s, '수학 구멍을 메웠다. 앞 단원부터 다시 쌓으니 이제 수업이 들린다.', 'good'); } }
  if (!quiet) {
    const after = mockGrades(s.sub);
    SUB_KEYS.forEach(k => {
      if (after[k] > before[k] && isDropped(s, k)) L(s, `${SUBJ_NAME[k]} ${before[k]}→${after[k]}등급. 접은 과목이라 예상한 대로다. 그 시간은 다른 과목에 갔다.`, 'info');
      else if (after[k] > before[k]) L(s, SUBJ_DOWN[k](before[k], after[k], s), (a[k] || 0) <= 1 ? 'bad' : 'warn');
      else if (after[k] < before[k] && (a[k] || 0) >= 3) L(s, SUBJ_UP[k](before[k], after[k], s), 'good');
      else if ((a[k] || 0) === 0 && s.neglect[k] >= 2 && !isDropped(s, k)) L(s, `${SUBJ_NAME[k]}${jo(SUBJ_NAME[k], '을/를')} ${s.neglect[k]}학기째 거의 안 했다. 등급은 아직 버티지만 실력은 계속 빠지고 있다.`, 'warn');
    });
    if (wasted.length) L(s, `${wasted.map(k => SUBJ_NAME[k]).join('·')} 학원은 다니는데 복습·숙제 시간을 거의 안 뒀다. 수업만 듣고 오니 남는 게 적다.`, 'warn');
    const kg = korGrades(s), weakP = KOR_PARTS.reduce((w, x) => (kg[x.k] > kg[w.k] ? x : w), KOR_PARTS[0]);
    if (kg[weakP.k] >= after.kor + 1 && kg[weakP.k] >= 4) L(s, {
      read: `국어 중 독서(비문학)가 ${kg.read}등급으로 가장 약하다. 긴 지문에서 문단 관계를 놓쳐 시간이 녹는다. 이 약점은 영어 장문·탐구 자료 해석까지 끌어내린다.`,
      lit: `국어 중 문학이 ${kg.lit}등급으로 가장 약하다. 작품은 읽히는데 선지의 '적절하지 않은 것'을 자꾸 놓친다. 내신 국어 서술형에서도 감점이 나온다.`,
      lang: `국어 중 화법·언어·매체가 ${kg.lang}등급으로 가장 약하다. 문법 개념이 흔들려 확실히 맞혀야 할 문항에서 점수가 샌다.`,
    }[weakP.k], 'warn');
    if (eff.kor >= 2.3 && lit > 0.2 && !s.flags.litShown && (s.flags.litShown = true)) L(s, '국어 독해력이 붙으면서 영어 장문과 탐구 지문도 덜 막힌다. 다른 과목 공부 효율이 같이 올랐다.', 'good');
    else if (lit < -0.4 && (a.eng || 0) + (a.inq || 0) >= 4) L(s, '영어·탐구에 시간을 많이 썼는데 지문이 잘 안 읽혀 효율이 떨어졌다. 국어 문해력이 발목을 잡는다.', 'warn');
    if (sci && eff.math >= 2.6 && mathL > 0.4) L(s, '수학이 탄탄해지니 물리·화학 계산 문제도 빨라졌다.', 'good');
    if (acadCost(s) >= 6 && s.money < 15) L(s, `학원비(${acadText(s)})가 집에 부담이 되고 있다.`, 'warn');
  }
  return { effSum, planned, before };
}
// 1·2학년: 학기마다 공부법이 모의고사 쪽으로 얼마나 쌓였는지 + 학력평가를 어떻게 봤는지
function trackMockPrep(s, turn, a) {
  if (!/^g[12]/.test(turn.id)) {
    // 고3에도 실전 연습은 조금씩 감각을 키운다
    if (s.examSense != null) { const m = SUB_KEYS.reduce((t, k) => t + methodInfo(s, k).mock * Math.min(1, (a[k] || 0) / 3), 0) / 4; s.examSense = clamp(s.examSense + (m - 0.45) * 0.05, -0.2, 0.22); }
    return;
  }
  const m = SUB_KEYS.reduce((t, k) => t + methodInfo(s, k).mock * Math.min(1, (a[k] || 0) / 3), 0) / 4;
  s.mockPrep += m * 0.5 + (s.hpThis != null ? s.hpThis : 0.15);
  s.mockSem++;
  s.hpThis = null;
}
// 고3이 되는 순간: 1·2학년 모의고사 공부가 '실전 감각'으로 정산된다
function settleExamSense(s) {
  if (s.examSense != null) return;
  const avg = s.mockSem ? s.mockPrep / s.mockSem : 0.4;
  s.examSense = clamp((avg - 0.55) * 0.32, -0.14, 0.15);
  const v = s.examSense;
  if (v >= 0.08) L(s, `고3 3월 학평. 1·2학년 때 학평을 실전처럼 보고 오답을 정리해 온 게 지금 나온다. 80분 시간 배분이 몸에 배어 있고, 내가 어떤 유형에서 틀리는지 안다. (실전 감각 +)`, 'good');
  else if (v <= -0.06) L(s, `고3 3월 학평. 1·2학년 학평을 대충 보고 넘긴 게 이제야 티가 난다. 실력보다 점수가 덜 나온다. 시간이 모자라 마지막 문제들은 찍었고, 어디서 틀리는지도 정리돼 있지 않다. (실전 감각 −)`, 'bad');
  else L(s, '고3 3월 학평. 1·2학년 때 학평을 보통으로 봐 왔다. 실전 감각은 실력만큼이다.', 'info');
}
const HP_NAME = { g1s1: '고1 3월 학평', g1s2: '고1 9월 학평', g2s1: '고2 6월 학평', g2s2: '고2 11월 학평' };
function hakpyeong(ctx, turn) {
  const s = ctx.s, p = s.p, g = mockGrades(s.sub);
  const nm = HP_NAME[turn.id];
  const o = choose(ctx, turn.id + ':hp', nm + ' D-5', `${nm}이 다음 주다. 학평은 내신에 안 들어간다. 반 친구 절반은 "어차피 성적 안 들어가잖아"라며 그 주에도 내신 수행평가만 챙긴다. 그런데 담임 선생님은 "고3 성적은 1·2학년 때 학평을 어떻게 봤는지에서 갈린다"고 하신다. 지난 학평은 ${gradesText(g)}였다.`, [
    O('real', '기출 학평 두 회를 80분 타이머로 풀고, 시험 끝나고 오답 정리까지 한다', '실전 감각과 약점 목록이 쌓인다 · 그 주 내신 공부 시간이 준다', ['study', 'self']),
    O('review', '따로 준비는 안 하고, 끝나고 틀린 문제만 다시 본다', '부담 없이 약점은 챙긴다 · 시간 배분 연습은 안 된다', ['study', 'safe']),
    O('naesin', '학평은 그냥 보고, 그 시간에 내신 수행평가를 챙긴다', '내신에 조금 이득 · 모의고사 감각은 쌓이지 않는다', ['safe']),
    O('sleep', '어차피 안 들어가니 대충 찍고 엎드려 잔다', '편하다 · 고3에 가서 실전 감각이 없다', ['fun']),
  ]);
  s.hpThis = { real: 0.55, review: 0.32, naesin: 0.08, sleep: -0.12 }[o.id];
  if (o.id === 'real') { SUB_KEYS.forEach(k => { s.sub[k] += 0.012; }); s.zN -= 0.008; inc(s, 'stress', 2); L(s, '학평 날, 시계를 보며 국어 독서에 몇 분 쓸지까지 정해 두고 들어갔다. 끝나고 틀린 문제 열한 개를 노트에 옮겼다.'); }
  if (o.id === 'review') { SUB_KEYS.forEach(k => { s.sub[k] += 0.005; }); L(s, '시험 끝나고 해설지를 받아 틀린 문제만 다시 풀었다.'); }
  if (o.id === 'naesin') { s.zN += 0.008; L(s, '학평은 그냥 봤다. 성적표는 가방 속에서 구겨졌다.'); }
  if (o.id === 'sleep') { inc(s, 'lazy', 3); L(s, '2교시부터 엎드려 잤다. OMR 카드에는 한 줄로 찍은 자국만 남았다.', 'warn'); }
}
function artsPractice(s, a, r, quiet) {
  const af = artsField(s);
  if (!af) return;
  const tk = FIELDS[af].talent, b = a.silgi || 0, cur = s.talent[tk], before = Math.round(cur);
  const cond = 0.75 + s.mental / 300 + s.health / 400 - (s.flags.reinjury && af === 'sport' ? 0.2 : 0) - (s.flags.handInjury && af === 'art' ? 0.25 : 0) - (s.flags.vocalNodule && af === 'perf' ? 0.25 : 0);
  // 위로 갈수록 느리게 는다(50점까지는 금방, 80점부터는 한 학기에 2점 늘기도 어렵다)
  const slow = clamp(1 - Math.max(0, cur - 50) / 60, 0.12, 1) * (s.artsAcad === 'none' && cur > 65 ? 0.6 : 1);   // 봐 주는 사람 없이는 65점 위로 올라가기 어렵다
  const decay = 3.2 + Math.max(0, cur - 60) * 0.05;
  const gain = b * 1.25 * artsMult(s) * cond * slow * (1 - clamp((s.lazy - 25) / 150, 0, 0.4)) - (b === 0 ? decay * 1.3 : b === 1 ? decay * 0.5 : 0) + (b >= 2 ? r.normal() * 1.0 : 0);
  s.talent[tk] = clamp(cur + gain, 5, 100);
  s.artsSem = (s.artsSem || 0) + (b >= 2 ? 1 : 0);
  if (s.artsAcad && s.artsAcad !== 'none') s.money -= ARTS_ACAD[s.artsAcad].cost;
  if (quiet) return;
  const after = Math.round(s.talent[tk]), nm = { art: '그림', perf: '연주·노래', sport: '기록' }[af];
  if (after - before >= 4) L(s, `${nm} 실기 ${before} → ${after}. ${s.artsAcad === 'ipsi' ? '학원에서 대학별 유형을 반복하니 손이 먼저 움직인다.' : s.artsAcad === 'none' ? '혼자 연습했다. 늘긴 하는데 뭐가 틀린지는 모르겠다.' : '연습한 만큼 늘었다.'}`, 'good');
  else if (after - before <= -3) L(s, `${nm} 실기 ${before} → ${after}. 실기는 ${b === 0 ? '한 학기만 손을 놓아도' : '연습이 모자라면'} 바로 무뎌진다. ${af === 'sport' ? '기록이 떨어졌다.' : af === 'art' ? '선이 흔들린다.' : '소리가 흔들린다.'}`, 'bad');
  if (s.artsAcad !== 'none' && ARTS_ACAD[s.artsAcad].cost >= 4 && s.money < 15) L(s, `${ARTS_ACAD[s.artsAcad].name} 비용이 집에 큰 부담이 되고 있다.`, 'warn');
}
function semesterEffects(ctx, turn, a) {
  const s = ctx.s, p = s.p, r = makeRng(s.seed, turn.id + ':sem');
  const st = STYLES[p.style] || STYLES.steady;
  const fg = FRIEND_GROUPS[s.friendGroup];
  const { effSum, planned } = studySubjects(s, a, 0.13, r, false);
  trackMockPrep(s, turn, a);
  const baseN = (p.school === 'special' ? 5.1 : p.school === 'jasa' ? 4.8 : p.region === 'gangnam' ? 4.5 : 4.2) + 0.9;
  const memF = 0.85 + p.memory * 0.05;
  // 위로 갈수록 경쟁자들도 그만큼 공부한다 — 기준선이 올라간다
  const acadN = SUB_KEYS.reduce((t, k) => t + ((a[k] || 0) >= 2 && s.money >= 3 ? ACAD[s.acad[k] || 'none'].naesin : 0), 0);
  const korN = ((s.korOff.lit + s.korOff.lang) / 2) * 0.05;   // 국어 내신은 문학·문법 서술형 비중이 크다
  // 공부법이 내신 시험에 맞는가(교과서·유형 반복은 내신에, 기출·모의고사 위주는 수능에)
  const methN = SUB_KEYS.reduce((t, k) => t + (methodInfo(s, k).nae - 0.5) * Math.min(1, (a[k] || 0) / 3), 0) * 0.012;
  const dropN = droppedList(s).reduce((t, k) => t + (k === 'kor' || k === 'math' ? 0.07 : 0.045), 0);   // 접은 과목의 내신(수학 6~7등급)이 평균을 끌어내린다
  const dN = (effSum * st.naesin * memF - baseN - Math.max(0, s.zN) * 0.5) * 0.046 + fg.study * a.friends + acadN + korN + methN - dropN;
  s.zN += dN * damp(s.zN);

  // 실기: 연습한 만큼 늘고, 안 하면 바로 무뎌진다. 입시 전문 학원이면 같은 시간에 더 는다
  artsPractice(s, a, r, false);
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
  if (s.flags.selfStudy) SUB_KEYS.forEach(k => { if (s.acad[k] !== 'online') s.acad[k] = 'none'; });
  s.money -= acadCost(s);
  if (s.money < 3 && SUB_KEYS.some(k => s.acad[k] !== 'none')) { L(s, '학원비가 밀렸다. 이번 학기는 학원을 제대로 다니지 못했다.', 'bad'); inc(s, 'parentRel', -3); }
  if (s.money < 0) { s.money = 0; inc(s, 'parentRel', -3); s.flags.moneyTight = true; }

  // 스트레스·멘탈
  const load = planned * 1.8 - 9 + s.pressure * 0.16 + st.stress + fg.stress * 2 + (p.school !== 'general' ? 3 : 0);
  inc(s, 'stress', load - (p.pStyle === 'warm' ? 3 : 0) - p.grit * 0.8);
  if (s.stress > 60) inc(s, 'mental', -(s.stress - 60) / 4);
  inc(s, 'mental', (55 - s.mental) * 0.05);  // 시간이 지나면 조금은 돌아온다

  // 나태 습관
  let dl = p.impulse * 1.1 - p.diligence * 1.05 + (phoneHobby(s) ? 0.8 : 0) + (p.pStyle === 'lax' ? 1.8 : p.pStyle === 'strict' ? -1 : 0) - (planned >= 7 ? 2 : 0) + (a.rest >= 5 ? 1.5 : 0);
  if (planned <= 3) dl += 3;
  // 습관은 타고난 성향 쪽으로 조금씩 되돌아간다
  const lazyBase = clamp(14 + p.impulse * 8 - p.diligence * 5 + (phoneHobby(s) ? 6 : 0), 3, 75);
  dl -= (s.lazy - lazyBase) * 0.16;
  inc(s, 'lazy', dl + r.normal() * 1.5);

  // 시험 결과
  const sc = s.zN + r.normal() * st.var + (s.stress > 75 ? -0.12 : 0) + (s.health < 30 ? -0.08 : 0);
  const pct = clamp(topFromZ(sc), 0.4, 99);
  const prev = s.naesinRec.length ? s.naesinRec[s.naesinRec.length - 1] : p.gpaPct;
  s.naesinRec.push(pct);
  const diff = prev - pct;
  const word = diff > 4 ? '올랐다' : diff < -4 ? '떨어졌다' : '비슷했다';
  L(s, `기말 결과 — 내신 상위 ${pct.toFixed(1)}% (${gradeText(s, pct)}). 지난 학기보다 ${word}.`, diff < -4 ? 'bad' : diff > 4 ? 'good' : 'info');
  mockExam(s, r, '모의고사');

  // 부모님 반응
  if ((p.pStyle === 'strict' || p.pStyle === 'anxious') && diff < -4) { inc(s, 'parentRel', -6); inc(s, 'stress', 6); L(s, `성적표를 본 ${parentWord(s)}의 얼굴이 굳었다. 그날 밤 집이 조용했다.`, 'bad'); }
  else if (p.pStyle === 'warm' && diff < -4) { inc(s, 'mental', 3); L(s, '"괜찮아, 다음에 잘하면 돼." 그 말에 조금 울컥했다.', 'info'); }
  else if (p.pStyle === 'strict' && diff > 4) { inc(s, 'parentRel', 4); }
  if (p.sibling === 'better' && r.chance(0.35)) { inc(s, 'mental', -3); L(s, '"형(언니)은 이맘때 1등급이었는데." 또 그 얘기다.', 'warn'); }
  // 연애 자연 진행
  if (s.romance.status === 'dating') s.romance.since++;
}
// 모의고사: 과목별 등급과 추세. 추세는 멘탈에도 영향을 준다
function mockExam(s, r, name) {
  // 고3 모의고사에는 1·2학년 때 쌓은 실전 감각(시간 배분·약점 관리)이 더해진다
  const sense = s.turnIdx >= 8 && s.examSense != null ? s.examSense : 0;
  if (s.turnIdx < 8 && name === '모의고사') name = '학력평가';
  const mk = {}; SUB_KEYS.forEach(k => { mk[k] = s.sub[k] + sense + r.normal() * 0.1; });
  s.lastMock = mk;
  const g = mockGrades(mk), pct = clamp(topFromZ(meanSub(mk)), 0.1, 99);
  const prevPct = s.mocks.length ? s.mocks[s.mocks.length - 1] : null;
  s.mocks.push(pct); s.mockG.push(g);
  const weak = SUB_KEYS.reduce((w, k) => (g[k] > g[w] ? k : w), 'kor');
  const trend = prevPct == null ? '' : prevPct - pct > 4 ? ' 지난번보다 올랐다.' : pct - prevPct > 4 ? ' 지난번보다 떨어졌다.' : '';
  if (trend.indexOf('올랐') >= 0) inc(s, 'mental', 3); if (trend.indexOf('떨어') >= 0) { inc(s, 'mental', -3); inc(s, 'stress', 3); }
  const P = pctOf(mk);
  L(s, `${name} — ${gradesText(g)} (백분위 국어 ${Math.round(P.kor)} · 수학 ${Math.round(P.math)} · 탐구 ${Math.round(P.inq)}).${trend} 가장 약한 과목은 ${SUBJ_NAME[weak]}. ${jungsiFitText(s, mk)}.`, trend.indexOf('올랐') >= 0 ? 'good' : trend.indexOf('떨어') >= 0 ? 'bad' : 'info');
  return g;
}
function gradeText(s, pct) {
  return s.p.grade >= 3 ? grade9(pct) + '등급(9등급제)' : grade5(pct) + '등급(5등급제)';
}

function vacationTurn(ctx, turn) {
  const s = ctx.s, p = s.p, r = makeRng(s.seed, turn.id + ':vac');
  const big = turn.big ? 1.6 : 1;
  const opts = [
    { id: 'cram', label: s.money > 15 ? '방학 특강·선행 학원 (주 5일, 아침 9시~밤 10시)' : '무리해서라도 방학 특강 등록', hint: s.money > 15 ? '진도와 실력이 확실히 나감 · 학원비와 피로' : '실력은 오름 · 집에 큰 부담', tags: ['study', 'obey'] },
    { id: 'self', label: '스터디카페 독학, 하루 계획표대로', hint: '돈 안 들고 내 페이스 · 지키는 건 오로지 내 의지', tags: ['study', 'self'] },
    { id: 'activity', label: '탐구 보고서·캠프·봉사로 생기부 채우기', hint: '학종에 쓸 이야기 · 수능 공부는 멈춘다', tags: ['record'] },
    { id: 'hobby', label: p.hobbies.length ? HOBBIES[p.hobbies[0]].name + '에 제대로 빠져 보기' : '하고 싶던 것 해 보기', hint: '재능과 진로를 발견할 수도 · 공부 감각이 무뎌진다', tags: ['fun', 'self'] },
    { id: 'rest', label: '가족 여행 가고 푹 쉬기', hint: '멘탈·체력·가족 관계 회복 · 남들은 달리는 중', tags: ['rest'] },
    { id: 'game', label: '폰·게임 몰아서 하기', hint: '스트레스 해소 · 습관이 무너진다', tags: ['fun'] },
    (p.wealth !== 'high' || s.flags.work) ? { id: 'work', label: '아르바이트로 돈 벌기', hint: '용돈과 사회 경험 · 공부 시간 감소', tags: ['work'] } : null,
  ];
  const afv = artsField(s);
  if (afv) opts.splice(1, 0, { id: 'camp', label: { art: '입시미술 방학 집중반 (하루 8시간 그림)', perf: '실기 집중 레슨·마스터클래스', sport: '체대 입시 집중 훈련반' }[afv], hint: '실기가 크게 는다 · 비용이 크고 교과 공부는 멈춘다', tags: ['study', 'self'] });
  const lastN = s.naesinRec.length ? s.naesinRec[s.naesinRec.length - 1] : p.gpaPct;
  const vtext = turn.big
    ? `고3 직전 겨울. 학원마다 "고3 수능은 이번 겨울에 결정된다"는 현수막이 걸렸다. 지금 내신은 상위 ${lastN.toFixed(0)}%, 모의고사는 ${grade9(topFromZ(s.zC))}등급. 친구들은 벌써 독서실 정기권을 끊었다. ${p.pStyle === 'strict' || p.pStyle === 'anxious' ? '부모님은 윈터스쿨(기숙 학원) 전단지를 식탁에 올려 두셨다.' : ''} 이 방학을 어떻게 보낼까?`
    : `${turn.label}. 방학은 5주. 학원 상담 문자가 하루에 세 통씩 온다. ${s.bestFriend ? `${s.bestName}${jo(s.bestName, '은/는')} "이번 방학엔 놀자"고 하고,` : ''} 담임 선생님은 "방학에 생기부 활동 하나는 꼭 하라"고 하셨다. 지난 학기 내신은 상위 ${lastN.toFixed(0)}%.`;
  const o = choose(ctx, turn.id + ':vac', turn.label, vtext, opts);
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
    case 'camp': {
      const tk = FIELDS[artsField(s)].talent;
      s.money -= 9 * big; if (s.money < 0) { s.money = 0; s.flags.moneyTight = true; inc(s, 'parentRel', -4); }
      s.talent[tk] = clamp(s.talent[tk] + (4 + 2.5 * big) * artsMult(s) * clamp(1 - Math.max(0, s.talent[tk] - 50) / 60, 0.12, 1) * (1 - s.lazy / 250), 5, 100); s.zC -= 0.03 * big; inc(s, 'health', -5);
      L(s, `방학 내내 실기만 했다. 실기 ${Math.round(s.talent[tk])}점. 교과서는 한 번도 안 폈다.`, 'good'); break;
    }
    case 'work':
      s.money += 14; s.flags.work = true; s.flags.workExp = (s.flags.workExp || 0) + 3; inc(s, 'mental', -2); s.zC -= 0.02;
      L(s, '편의점 알바로 번 돈으로 처음 내 돈으로 산 물건이 생겼다. 돈 버는 게 쉽지 않다는 것도 알았다.'); break;
  }
  if (turn.big) s.flags.winter = o.id;
}

// ── 정해진 이벤트 ─────────────────────────────────────────
// 국어 공부법 정하기: 학년이 바뀔 때마다. 어떤 방법이냐에 따라 오르는 영역이 다르다
// 과목별 공부법: 학년이 바뀔 때마다(그리고 시작할 때) 네 과목을 한 번에 정한다
function studyMethod(ctx, turn) {
  const s = ctx.s, g = mockGrades(s.sub), kg = korGrades(s);
  const weakK = KOR_PARTS.reduce((w, x) => (kg[x.k] > kg[w.k] ? x : w), KOR_PARTS[0]);
  const rows = SUB_KEYS.map(k => {
    const M = SUBJ_METHODS[k], ac = s.acad[k] && s.acad[k] !== 'none' && s.acad[k] !== 'online';
    const ids = Object.keys(M).filter(id => id !== 'hw' || ac);
    const status = k === 'kor' ? `${g.kor}등급 · 독서 ${kg.read} 문학 ${kg.lit} 언매 ${kg.lang} (약한 영역: ${weakK.name})` : `${g[k]}등급${ac ? ' · ' + ACAD[s.acad[k]].name : ''}`;
    const cur = methodOf(s, k);
    return { k, name: SUBJ_NAME[k], status, def: ids.indexOf(cur) >= 0 ? cur : ids[0],
      options: ids.map(id => ({ id, label: M[id].name, hint: M[id].hint || ({ read: '독해력이 오르고 영어·탐구 지문도 덜 막힌다 · 문학·문법은 처진다', lit: '문학과 내신 서술형이 강해진다 · 독서는 그대로', lang: '확실히 맞힐 문항이 늘어난다 · 독서·문학엔 효과가 작다', gichul: '세 영역이 고르게 오르고 효율이 좋다 · 꾸준함이 필요하다', mock: '실전 감각 · 틀린 유형이 반복된다', hw: '방향 고민이 없다 · 학원 수준만큼 오른다' })[id], tags: METHOD_TAGS[id] || ['study'] })) };
  });
  const lead = turn.id === 'g3s1' ? '고3이다. 6월·9월 모평과 수능은 평가원이 같은 원리로 낸다. 내신 마지막 학기이기도 하다.'
    : turn.id === 'g1s1' ? '고등학교 첫 학기. 중학교 때처럼 시험 전에 몰아서 하는 방식은 여기서 안 통한다고들 한다.'
    : '새 학년이다. 과목마다 공부법을 다시 정할 때다.';
  const v = ask(ctx, { type: 'methods', key: turn.id + ':methods', title: '과목별 공부법 정하기',
    text: `${turn.label}. ${lead} 지금 모의고사는 ${gradesText(g)}. 같은 시간을 써도 방법이 지금 실력에 맞아야 오른다. 교과서·유형 반복은 내신에, 기출·실전 모의고사는 수능에 더 잘 쌓인다. 1·2학년 때 모의고사 쪽으로 쌓아 둔 만큼 고3 모의고사와 수능에서 실전 감각으로 돌아온다.`,
    rows });
  const out = normMethods(v, rows);
  const wasDropped = droppedList(s);
  s.korFocus = out.kor; ['math', 'eng', 'inq'].forEach(k => { s.method[k] = out[k]; });
  const nowDropped = droppedList(s);
  nowDropped.filter(k => wasDropped.indexOf(k) < 0).forEach(k => {
    s.flags['dropped_' + k] = true;
    L(s, { kor: '국어를 접기로 했다. 국어는 거의 모든 대학이 본다. 갈 수 있는 대학이 크게 줄어든다.',
      math: s.track === '자연' ? '수학을 접기로 했다. 이과에서 수학을 접으면 공대·자연대·의약은 사실상 닫힌다. 계열을 바꾸거나 3과목 반영 대학을 찾아야 한다.' : '수학을 접기로 했다(문과 수포자). 하루 2~3칸이 국어·영어·탐구로 간다. 대신 상경 계열과 중경외시 이상 정시는 사실상 닫히고, 수학이 들어가는 3합 최저도 어려워진다. 국·영·탐 3과목만 보는 대학(광명상가 이하)이 목표가 된다.',
      eng: '영어를 접기로 했다. 영어는 절대평가라 3등급까지는 비교적 쉬운데, 완전히 놓으면 5~6등급이 되고 최저 대부분에서 걸린다. 정시 감점도 크다.',
      inq: '탐구를 접기로 했다. 3합 최저는 사실상 2과목으로 맞춰야 하고, 정시 탐구 반영(20~35%)을 잃는다.' }[k], 'warn');
  });
  wasDropped.filter(k => nowDropped.indexOf(k) < 0).forEach(k => { L(s, `${SUBJ_NAME[k]}${jo(SUBJ_NAME[k], '을/를')} 다시 잡기로 했다. 놓았던 기간만큼 구멍이 있다. 처음엔 더디다.`, 'info'); });
  L(s, '공부법 — ' + SUB_KEYS.map(k => `${SUBJ_NAME[k]}: ${methodInfo(s, k).name}`).join(' / ') + '.');
}
function normMethods(v, rows) { const o = {}; rows.forEach(r => { const c = v && v[r.k]; o[r.k] = r.options.some(x => x.id === c) ? c : r.def; }); return o; }

// 학원 다시 짜기: 겨울방학마다. 가장 약한 과목부터
function acadPlan(ctx, turn) {
  const s = ctx.s, p = s.p, g = mockGrades(s.sub);
  const weak = SUB_KEYS.reduce((w, k) => (g[k] > g[w] ? k : w), 'kor');
  const cur = s.acad[weak] || 'none';
  const lowMoney = s.money < 20;
  const opts = [
    cur !== 'director' ? O('director', `${SUBJ_NAME[weak]} — 원장 직강 소규모 학원`, '원장이 직접 가르치고 첨삭·상담·학교별 내신 대비까지 · 학원비 중간', ['study', 'safe']) : null,
    cur !== 'big' ? O('big', `${SUBJ_NAME[weak]} — 대형 학원 유명 강사 현강`, g[weak] <= 2 ? '상위권 진도와 자료 · 비싸고 경쟁이 세다' : '자료와 강의는 최고 · 기초가 약하면 따라가기 벅차다', ['study', 'risk']) : null,
    cur !== 'managed' ? O('managed', `${SUBJ_NAME[weak]} — 관리형 학원`, '출결·숙제·자습 관리로 딴짓을 막는다 · 수업 수준은 평범', ['obey', 'study']) : null,
    cur !== 'tutor' && !lowMoney ? O('tutor', `${SUBJ_NAME[weak]} — 1:1 과외`, '나에게 맞춘 수업 · 가장 비싸고 선생님에 따라 편차가 크다', ['study', 'risk']) : null,
    cur !== 'online' ? O('online', `${SUBJ_NAME[weak]} — 인강으로 바꾸기`, '돈이 거의 안 든다 · 성실하지 않으면 완강을 못 한다', ['self', 'safe']) : null,
    O('keep', `지금 그대로 (${ACAD[cur].name})`, '바꾸는 부담이 없다 · 약한 과목은 그대로일 수 있다', ['safe']),
  ];
  const o = choose(ctx, turn.id + ':acad', '학원 다시 짜기', `${turn.label}. 다음 학기 학원을 정할 때다. 지금 모의고사는 ${gradesText(g)}, 가장 약한 과목은 ${SUBJ_NAME[weak]}. 지금 학원: ${acadText(s)}. ${lowMoney ? '집에서는 학원비가 부담된다고 한다.' : ''}`, opts);
  if (o.id === 'keep') { L(s, '학원은 그대로 다니기로 했다.'); return; }
  s.acad[weak] = o.id;
  if (o.id === 'tutor') s.tutorQ[weak] = makeRng(s.seed, turn.id + ':tutor').normal() * 0.06;
  const line = { director: `${SUBJ_NAME[weak]} 원장 직강 학원에 상담을 갔다. 원장님이 레벨테스트지를 직접 채점하더니 약한 단원 세 개를 짚었다. "여기부터 메우자."`, big: `${SUBJ_NAME[weak]} 대형 학원 유명 강사 현강반에 등록했다. 교실에 120명이 앉아 있다.`, managed: `${SUBJ_NAME[weak]} 관리형 학원에 등록했다. 폰은 입구에서 걷고, 자습 시간도 출결로 관리한다.`, tutor: `${SUBJ_NAME[weak]} 1:1 과외를 시작했다. 한 달 60만 원.`, online: `${SUBJ_NAME[weak]}은(는) 인강으로 바꿨다. 학원비가 줄었다.` }[o.id];
  L(s, line.replace(`${SUBJ_NAME[weak]}은(는)`, SUBJ_NAME[weak] + jo(SUBJ_NAME[weak], '은/는')));
}

function fixedEvents(ctx, turn) {
  const s = ctx.s, p = s.p;
  if (['g1s1', 'g2s1', 'g3s1'].indexOf(turn.id) >= 0 || turn.id === HS_TURNS[p.startTurn].id) studyMethod(ctx, turn);
  if (HP_NAME[turn.id]) hakpyeong(ctx, turn);
  if (turn.id === 'g1s1') {
    const ti = topInterest(s);
    const o = choose(ctx, 'g1s1:club', '동아리 신청서', `입학 2주 차. 동아리 박람회 날, 강당에 부스가 서른 개쯤 있다. 선배들이 귓속말로 알려 준다. "학종 갈 거면 전공 관련 동아리 들어가. 근데 거긴 매주 보고서 써야 돼." 방송부 부스에서는 음악이 크게 나오고, ${s.bestFriend ? `${s.bestName}${jo(s.bestName, '은/는')} 벌써 거기 줄을 섰다.` : '아는 얼굴이 하나도 없다.'}`, [
      { id: 'major', label: `${FIELDS[ti].name} 탐구 동아리`, hint: '생기부 전공 적합성 · 매주 보고서, 재미는 덜하다', tags: ['record', 'study'] },
      { id: 'band', label: '방송부·밴드·댄스 동아리', hint: '학교생활이 즐거워짐 · 행사 때마다 시간이 많이 든다', tags: ['fun', 'social'] },
      { id: 'follow', label: s.bestFriend ? `${s.bestName}${jo(s.bestName, '이/가')} 들어가는 곳으로` : '자리 남는 아무 데나', hint: '친구와 함께 · 생기부에 남는 건 애매하다', tags: ['social'] },
      { id: 'none', label: '이름만 걸어 두고 공부 시간 확보', hint: '내신 집중 · 3년 동안 쓸 이야기가 부족해질 수 있다', tags: ['study', 'safe'] },
    ]);
    if (o.id === 'major') { s.record += 9; s.recFit[ti] += 10; s.interest[ti] += 5; s.flags.club = 'major'; L(s, `${FIELDS[ti].name} 동아리에 들어갔다. 선배들이 생기부 쓰는 법부터 알려줬다.`); }
    if (o.id === 'band') { s.record += 4; s.talent.perf += 8; s.talent.media += 8; inc(s, 'social', 8); inc(s, 'mental', 5); s.flags.club = 'band'; L(s, '동아리방에서 보내는 시간이 학교생활의 낙이 됐다.'); }
    if (o.id === 'follow') { s.record += 2; inc(s, 'social', 6); s.flags.club = 'follow'; L(s, '친구 따라 들어간 동아리. 활동은 그냥 그렇지만 같이 있어서 좋다.'); }
    if (o.id === 'none') { s.zN += 0.03; s.record -= 2; s.flags.club = 'none'; L(s, '동아리는 이름만 걸었다. 그 시간에 문제집을 풀었다.'); }
  }
  if (turn.id === 'g1s2' && !s.subject) {
    const o = choose(ctx, 'g1s2:subject', '고2 선택과목 신청', `고교학점제. 다음 주까지 고2 선택과목을 내야 한다. 대학은 '권장 과목'을 들었는지로 "전공을 준비한 학생인지"를 본다. 그런데 물리는 이과 최상위권이 몰려서 수강생이 30명뿐이다. 30명 중 1등급은 3명. ${FIELDS[topInterest(s)].name}에 끌리는 지금, 무엇을 고를까?`, [
      { id: 'phys', label: '미적분·물리·화학 (공대·자연대 권장)', hint: (isDropped(s, 'math') ? '수학을 접은 채 미적분·물리를 고르는 건 모순이다 · ' : '') + '이공계 지원에 유리 · 내신 경쟁이 가장 치열하다', tags: ['study', 'risk'], w: isDropped(s, 'math') ? -6 : 0 },
      { id: 'bio', label: '생명과학·화학 (의약·생명 권장)', hint: (isDropped(s, 'math') ? '수학 없이 의약·생명은 어렵다 · ' : '') + '의대·간호·생명 지원에 유리 · 의대 지망생들과 경쟁', tags: ['study'], w: isDropped(s, 'math') ? -5 : 0 },
      { id: 'soc', label: '경제·정치와 법·사회문화 (상경·사회 권장)', hint: '경영·행정에 유리 · 이과 학과는 사실상 어렵다', tags: ['safe'] },
      { id: 'lang', label: '언어와 매체·윤리·제2외국어 (인문·교육 권장)', hint: '인문·교대에 유리 · 이과 학과는 사실상 어렵다', tags: ['safe'] },
      { id: 'easy', label: '수강생 많고 1등급 따기 쉬운 과목 위주', hint: '내신 등급이 오름 · 학종에서 "왜 이 과목?" 질문을 받는다', tags: ['fun', 'safe'] },
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
    const o = choose(ctx, 'g2s1:class', '고2 반 배정', `고2 첫날. 새 반은 ${vName} 반이다. ${vibe === 'rival' ? '쉬는 시간에도 문제집을 펴는 애들이 절반이다.' : vibe === 'party' ? '첫날부터 뒷자리에서 PC방 약속이 잡힌다.' : '첫날부터 반 단톡방이 시끌시끌하다.'} ${s.bestFriend ? `${s.bestName}${jo(s.bestName, '와/과')}는 다른 반이 됐다. 점심시간마다 같이 먹자고 연락이 온다.` : ''}`, [
      { id: 'blend', label: '새 반 친구들과 어울린다', hint: '새 무리가 생긴다 · 반 분위기에 그대로 물든다', tags: ['social'] },
      { id: 'keep', label: '원래 친구들과 계속 다닌다', hint: '익숙한 관계 · 우리 반에서는 겉돌 수 있다', tags: ['safe'] },
      { id: 'solo', label: '이참에 혼자 다니며 공부에 집중한다', hint: '흔들림 없음 · 외롭고 정보가 줄어든다', tags: ['study'] },
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

// 선택지 하나 = { id, label, hint(얻는 것과 잃을 수 있는 것), tags(성향대로 고를 때 쓰는 꼬리표) }
const O = (id, label, hint, tags, w) => ({ id, label, hint, tags, w });
const semIs = (s, ids) => ids.indexOf(HS_TURNS[s.turnIdx] && HS_TURNS[s.turnIdx].id) >= 0;
const examSeason = s => s.turnIdx >= 8;

const HS_EVENTS = [
  // ── 친구 ─────────────────────────────────────────
  { id: 'pc', w: s => (s.friendGroup === 'party' || s.friendGroup === 'gamers' ? 3.2 : hasHobby(s, 'game') ? 1.6 : 0.5) * expo(s),
    run: (ctx, key, r) => {
      const s = ctx.s, b = s.bestName;
      const o = choose(ctx, key, '학원 가는 길, 단톡방',
        `밤 9시 40분, 학원 버스를 기다리는데 단톡방이 울린다. ${b}: "오늘 학원 쌤 출장이래 ㅋㅋ 대타 쌤은 출석 안 부름. PC방 ㄱ?" 다들 "ㄱㄱ"를 보낸다. 오늘 진도는 다음 주 단원평가 범위고, 엄마는 학원 앱으로 출결 알림을 받는다.`, [
        O('go', '같이 간다. 출석은 친구한테 대신 부탁', '친구들과 가까워짐 · 학원에서 집에 연락이 갈 수도', ['fun', 'social']),
        O('half', '1시간만 하고 학원 자습실로 간다', '둘 다 챙기는 척 · 어느 쪽도 제대로는 못 함', ['social', 'safe']),
        O('skip', '"난 오늘 패스" 하고 학원에 간다', '진도는 지킴 · 다음 날 단톡방 대화에 못 낀다', ['study']),
        O('distance', '요즘 이 무리랑 너무 논다. 단톡방 알림을 끈다', '공부 시간이 늘어남 · 한동안 외로울 수 있다', ['study', 'self']),
      ]);
      if (o.id === 'go') { inc(s, 'social', 6); inc(s, 'mental', 4); inc(s, 'lazy', 6); s.zC -= 0.03; s.flags.skippedAcademy = (s.flags.skippedAcademy || 0) + 1; L(s, '새벽 1시에 들어왔다. 다음 날 1교시부터 졸았다. 그래도 오랜만에 크게 웃었다.'); }
      if (o.id === 'half') { inc(s, 'social', 2); s.zC -= 0.01; inc(s, 'lazy', 2); L(s, '1시간은 2시간이 됐다. 자습실에 도착했을 땐 집중이 안 됐다.'); }
      if (o.id === 'skip') { inc(s, 'social', -3); inc(s, 'lazy', -2); L(s, '다음 날 아침, 어제 PC방 얘기로 다들 웃는데 혼자 못 끼었다.'); }
      if (o.id === 'distance') { inc(s, 'social', -10); inc(s, 'mental', -4); inc(s, 'lazy', -7); s.flags.distanced = true; L(s, '알림을 껐다. 처음 몇 주는 점심시간이 길게 느껴졌다.', 'warn'); }
    } },
  { id: 'academyCall', w: s => ((s.flags.skippedAcademy || 0) >= 1 && !s.seen.academyCall ? 4 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, pw = parentWord(s);
      const o = choose(ctx, key, '학원에서 온 전화',
        `저녁 식탁. ${pw}의 휴대폰이 울린다. "어머님, ○○이가 이번 달에 두 번 결석해서요…" 전화를 끊은 ${pw}${jo(pw, '이/가')} 숟가락을 내려놓는다. "어디 갔었니?"`, [
        O('truth', '사실대로 말한다. PC방에 갔다고', '거짓말은 안 함 · 크게 혼날 수 있다', ['self']),
        O('lie', '"몸이 안 좋아서 독서실에 있었어요"', '오늘은 넘어감 · 들키면 신뢰가 무너진다', ['fun', 'safe']),
        O('turn', '"솔직히 그 학원 나랑 안 맞아요" 하고 학원 얘기를 꺼낸다', '진짜 문제를 꺼냄 · 반항으로 보일 수 있다', ['rebel', 'self']),
      ]);
      if (o.id === 'truth') { inc(s, 'parentRel', s.p.pStyle === 'strict' ? -6 : 2); s.pressure += 3; L(s, s.p.pStyle === 'strict' ? '한 달 동안 휴대폰을 뺏겼다.' : '"다음부턴 미리 말해." 생각보다 덜 혼났다.'); if (s.p.pStyle === 'strict') inc(s, 'lazy', -6); }
      if (o.id === 'lie') { if (r.chance(0.45)) { inc(s, 'parentRel', -14); s.flags.liar = true; L(s, '독서실 출입 기록을 확인한 엄마가 아무 말도 하지 않았다. 그게 더 무서웠다.', 'bad'); } else { L(s, '넘어갔다. 하지만 거짓말이 하나 늘었다.', 'warn'); s.flags.liar = true; } }
      if (o.id === 'turn') { const ok = s.p.pStyle === 'warm' || s.p.pStyle === 'lax' || r.chance(0.3); if (ok) { s.money += 4; s.autonomy += 1; inc(s, 'parentRel', 3); L(s, '학원을 바꾸기로 했다. 처음으로 내 공부 방식을 내가 정했다.', 'good'); } else { inc(s, 'parentRel', -8); L(s, '"핑계 대지 마." 대화는 거기서 끝났다.', 'bad'); } }
    } },
  { id: 'fight', w: s => (s.bestFriend ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, b = s.bestName;
      const o = choose(ctx, key, '절친과의 싸움',
        `${b}${jo(b, '이/가')} 다른 친구들 앞에서 내 성적 얘기를 했다. "얘 이번에 수학 망했잖아 ㅋㅋ" 농담이었다는 건 안다. 그런데 웃음이 안 나왔다. 그날 저녁부터 서로 DM을 읽고 답하지 않는다. 사흘째다.`, [
        O('sorry', '먼저 연락한다. "그때 내가 예민했어"', '우정은 지킴 · 내 서운함은 묻힌다', ['kind', 'social']),
        O('honest', '만나서 왜 서운했는지 정확히 말한다', '관계가 깊어질 수도 · 더 크게 싸울 수도', ['self', 'risk']),
        O('wait', '걔가 먼저 연락할 때까지 기다린다', '자존심은 지킴 · 그대로 멀어질 수 있다', ['safe']),
        O('cut', '이참에 손절한다', '감정 소모 끝 · 학교생활이 쓸쓸해진다', ['rebel']),
      ]);
      if (o.id === 'sorry') { inc(s, 'social', 5); inc(s, 'mental', 1); L(s, `"아 미안 ㅠ 나도 생각 없었어." ${b}${jo(b, '와/과')} 편의점 앞에서 라면을 먹었다.`, 'good'); }
      if (o.id === 'honest') { if (r.chance(0.55 + s.p.social * 0.05)) { inc(s, 'social', 8); inc(s, 'mental', 5); s.flags.friendForever = true; L(s, `${b}${jo(b, '이/가')} 진지하게 사과했다. 그날 처음으로 서로 진로 고민을 털어놨다.`, 'good'); } else { s.bestFriend = false; s.flags.lostBest = true; inc(s, 'social', -10); inc(s, 'mental', -8); L(s, '"그걸 그렇게까지 받아들여?" 말다툼은 더 커졌고, 그렇게 멀어졌다.', 'bad'); } }
      if (o.id === 'wait') { if (r.chance(0.5)) L(s, `일주일 뒤 ${b}${jo(b, '이/가')} 아무 일 없었다는 듯 말을 걸었다. 둘 다 그 일은 다시 꺼내지 않았다.`); else { s.bestFriend = false; s.flags.lostBest = true; inc(s, 'social', -10); inc(s, 'mental', -8); L(s, '아무도 먼저 연락하지 않았다. 다음 학기, 우리는 그냥 아는 사이가 됐다.', 'bad'); } }
      if (o.id === 'cut') { s.bestFriend = false; s.flags.lostBest = true; inc(s, 'mental', -6); inc(s, 'social', -6); L(s, '차단 버튼을 눌렀다. 같은 반이라 매일 마주친다.', 'bad'); }
    } },
  { id: 'cheat', w: s => (s.friendGroup === 'party' || s.friendGroup === 'gamers' ? 1.3 : 0.6), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, b = s.bestName;
      const o = choose(ctx, key, '수행평가 보고서',
        `수행평가 마감 전날 밤 11시. ${b}에게서 카톡이 온다. "나 진짜 하나도 못 했어… 네 거 파일만 보내 주면 문장 다 바꿔서 낼게. 진짜 한 번만." 이 보고서는 3주 동안 쓴 거고, 세특에 들어갈 내용이다.`, [
        O('give', '보내 준다', '친구에게 고마운 사람이 됨 · 걸리면 둘 다 0점', ['social', 'kind']),
        O('outline', '파일 대신 목차와 참고자료만 보내 준다', '선은 지킴 · 친구는 서운할 수 있다', ['kind', 'safe']),
        O('call', '전화해서 같이 밤새 써 준다', '우정이 깊어짐 · 내 잠과 컨디션을 잃는다', ['kind', 'social']),
        O('no', '"미안, 이건 안 돼"', '내 노력은 지킴 · 관계가 서먹해진다', ['self']),
      ]);
      if (o.id === 'give') { if (r.chance(0.3)) { s.record -= 12; inc(s, 'parentRel', -8); inc(s, 'mental', -8); s.flags.caught = true; L(s, '표절 검사에 걸렸다. 둘 다 0점. 담임 선생님이 행동특성란 얘기를 꺼냈다.', 'bad'); } else { inc(s, 'social', 4); s.flags.owedFavor = true; L(s, '무사히 넘어갔다. 친구는 "평생 은인"이라고 했다. 찜찜했다.'); } }
      if (o.id === 'outline') { inc(s, 'social', 1); L(s, '친구는 "고마워"라고 했지만 답장이 조금 늦었다.'); }
      if (o.id === 'call') { inc(s, 'social', 5); inc(s, 'health', -6); s.talent.people += 4; s.flags.friendForever = true; L(s, '새벽 3시에 둘 다 제출 버튼을 눌렀다. 다음 날 수업은 기억이 없다.', 'good'); }
      if (o.id === 'no') { inc(s, 'social', -5); L(s, '"치사하네." 며칠 동안 단톡방에서 내 말에만 답이 없었다.'); }
    } },
  { id: 'favorBack', w: s => (s.flags.owedFavor && s.turnIdx >= 4 ? 3 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, b = s.bestName;
      const o = choose(ctx, key, '그때의 빚',
        `${b}${jo(b, '이/가')} 조용히 USB를 건넨다. "우리 학원 쌤이 너희 학교 기출 3년 치 정리해 둔 거야. 지난번에 네가 도와줬잖아." 다른 애들은 이 자료가 있는 줄도 모른다.`, [
        O('take', '받는다. 기출 정리는 불법도 아니다', '내신에 확실히 도움 · 다른 친구들에겐 비밀이 하나 생김', ['study']),
        O('share', '받아서 반 단톡방에 공유한다', '반 분위기가 좋아짐 · 내 상대 등수는 오르지 않는다', ['kind', 'social']),
        O('no', '"괜찮아, 그건 너 해"', '깔끔하다 · 기회를 놓친다', ['self', 'safe']),
      ]);
      if (o.id === 'take') { s.zN += 0.06; L(s, '기출 유형이 그대로 나왔다. 이번 기말은 쉬웠다.', 'good'); }
      if (o.id === 'share') { s.zN += 0.01; inc(s, 'social', 8); s.talent.people += 4; L(s, '"너 천사냐?" 반 분위기가 확 좋아졌다.', 'good'); }
      if (o.id === 'no') L(s, '친구는 머쓱해했다.');
    } },
  { id: 'studyGroup', w: s => (s.friendGroup === 'rival' ? 2 : s.p.social >= 3 ? 0.9 : 0.4), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, nm = s.rivalName;
      const o = choose(ctx, key, '전교 1등의 제안',
        `점심시간, 전교 1등 ${nm}${jo(nm, '이/가')} 다가온다. "토요일마다 수학 스터디 하는데 한 자리 비었어. 대신 매주 서로 문제 출제하고, 못 하면 나가는 거야." 토요일은 지금 유일하게 쉬는 날이다.`, [
        O('join', '들어간다', '실력이 확 늘 수 있음 · 쉬는 날이 사라지고 비교가 시작된다', ['study', 'social']),
        O('maybe', '한 달만 해 보겠다고 한다', '부담은 적음 · 어중간하면 금방 밀려난다', ['safe']),
        O('no', '"나는 혼자가 편해"', '내 페이스 유지 · 좋은 자극 하나를 놓친다', ['self']),
      ]);
      if (o.id === 'join') { s.zC += 0.05; s.zN += 0.035; inc(s, 'stress', 7); inc(s, 'social', 3); s.flags.studyGroup = true; L(s, `${nm}${jo(nm, '은/는')} 한 문제를 세 가지 방법으로 풀었다. 처음엔 기가 죽었고, 나중엔 따라 하게 됐다.`, 'good'); }
      if (o.id === 'maybe') { if (s.p.diligence >= 3) { s.zC += 0.025; L(s, '한 달은 버텼다. 출제한 문제가 칭찬받은 날도 있었다.'); } else { inc(s, 'mental', -4); L(s, '두 번째 주에 숙제를 못 해 와서 조용히 빠졌다.', 'warn'); } }
      if (o.id === 'no') L(s, '토요일 늦잠은 지켰다.');
    } },
  { id: 'rivalGap', w: s => (s.flags.studyGroup || s.friendGroup === 'rival' ? 1.6 : 0.5), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, nm = s.rivalName;
      const o = choose(ctx, key, '한 등급 차이',
        `성적표가 나왔다. ${nm}${jo(nm, '은/는')} 1등급, 나는 2등급. 원점수 차이는 단 2점. 서술형 한 문제에서 부분 점수가 갈렸다. 채점 기준표를 보니 내 답도 맞다고 볼 여지가 있다.`, [
        O('appeal', '선생님께 이의 신청을 한다', '등급이 바뀔 수도 · 선생님과 어색해질 수 있다', ['risk', 'self']),
        O('accept', '받아들이고 다음 시험을 준비한다', '마음 정리 · 2점이 계속 마음에 남는다', ['safe', 'study']),
        O('envy', '그날은 아무것도 손에 안 잡힌다', '솔직한 감정 · 하루가 날아간다', ['rest']),
      ]);
      if (o.id === 'appeal') { if (r.chance(0.35)) { s.zN += 0.07; L(s, '부분 점수가 인정됐다. 1등급 컷에 걸렸다!', 'good'); } else { s.record -= 2; inc(s, 'mental', -4); L(s, '"채점 기준대로 한 거야." 선생님 표정이 굳었다. 그 과목 세특이 걱정된다.', 'warn'); } }
      if (o.id === 'accept') { s.zN += 0.015; inc(s, 'stress', 3); L(s, '오답노트 첫 줄에 서술형 채점 기준을 적었다.'); }
      if (o.id === 'envy') { inc(s, 'mental', -5); inc(s, 'lazy', 2); L(s, '잠들기 전까지 2점을 생각했다.', 'warn'); }
    } },
  { id: 'bully', w: () => 0.6, once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '단톡방에서 빠진 이름',
        `반 단톡방이 새로 만들어졌는데 한 친구만 초대되지 않았다. 일부러라는 걸 다들 안다. 그 친구는 요즘 쉬는 시간마다 엎드려 있다. 무리의 중심에는 반에서 가장 목소리 큰 애가 있다.`, [
        O('invite', '내가 그 친구를 단톡방에 초대한다', '옳은 일 · 무리에게 찍힐 수 있다', ['kind', 'risk']),
        O('private', '단톡방은 건드리지 않고, 따로 그 친구에게 말을 건다', '그 친구에겐 힘이 됨 · 상황은 그대로', ['kind', 'safe']),
        O('report', 'Wee클래스 선생님께 조용히 알린다', '어른이 해결 · 누가 말했는지 알려질 위험', ['kind', 'safe']),
        O('ignore', '괜히 끼어들었다가 나까지 당할라', '내 학교생활은 무사 · 마음에 무언가가 남는다', ['safe']),
      ]);
      if (o.id === 'invite') { inc(s, 'social', -6); inc(s, 'mental', 3); s.talent.people += 8; s.record += 3; s.interest.soc += 6; s.flags.kind = true; L(s, '단톡방이 잠깐 조용해졌다. 일주일 뒤, 그 친구가 내 책상에 음료수를 놓고 갔다.', 'good'); }
      if (o.id === 'private') { inc(s, 'mental', 2); s.talent.people += 4; s.flags.kind = true; L(s, '같이 매점에 갔다. 별말 없었지만 그 친구가 조금 웃었다.'); }
      if (o.id === 'report') { s.flags.kind = true; if (r.chance(0.3)) { inc(s, 'social', -6); L(s, '누가 말했는지 소문이 돌았다. 그래도 단톡방 일은 정리됐다.', 'warn'); } else L(s, '선생님이 조용히 해결해 주셨다.'); }
      if (o.id === 'ignore') { inc(s, 'mental', -3); s.flags.ignoredBully = true; L(s, '그 친구는 다음 학기에 전학을 갔다. 가끔 생각난다.', 'warn'); }
    } },
  { id: 'sns', w: s => (s.p.social >= 3 ? 0.8 : 0.3), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '캡처 한 장',
        `누군가 캡처 한 장을 보내왔다. 나 빼고 만든 단톡방. "걔 요즘 공부하는 척 오지지 않냐 ㅋㅋ" 그 밑에 웃는 이모티콘을 단 사람 중에는 매일 같이 급식 먹는 친구도 있다.`, [
        O('confront', '그 친구를 따로 불러 직접 묻는다', '진실을 알게 됨 · 일이 커질 수 있다', ['rebel', 'self']),
        O('ignore', '못 본 척한다', '평화 유지 · 혼자 삭인다', ['safe']),
        O('reset', '친구 관계를 정리하고, 진짜 내 편에게 집중한다', '관계가 단단해짐 · 무리에서 멀어진다', ['self']),
      ]);
      if (o.id === 'confront') { if (r.chance(0.5)) { inc(s, 'mental', 4); inc(s, 'social', 2); L(s, '"미안… 분위기에 휩쓸렸어." 사과를 받았다.'); } else { inc(s, 'social', -7); inc(s, 'mental', -8); L(s, '"캡처 돌린 애가 더 나쁜 거 아니야?" 말다툼은 반 전체로 번졌다.', 'bad'); } }
      if (o.id === 'ignore') { inc(s, 'mental', -8); L(s, '아무렇지 않은 척했다. 하나도 안 괜찮았다.', 'bad'); }
      if (o.id === 'reset') { inc(s, 'mental', s.p.grit >= 3 ? -2 : -6); inc(s, 'social', -3); if (s.bestFriend) s.flags.friendForever = true; L(s, '친구 수는 줄었다. 대신 누가 진짜 친구인지 알게 됐다.'); }
    } },
  { id: 'dropoutFriend', w: s => (s.turnIdx >= 2 && s.turnIdx <= 6 ? 0.9 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, b = s.bestName;
      const o = choose(ctx, key, '자퇴하고 정시 하자',
        `${b}${jo(b, '이/가')} 진지하게 말한다. "나 자퇴하고 검정고시 본 다음 정시만 할 거야. 내신 이미 망했잖아. 학교 다니는 시간이 아까워. 너도 같이 할래? 재종반 같이 다니면 되잖아." 요즘 실제로 이렇게 하는 애들이 꽤 있다.`, [
        O('join', '나도 자퇴하고 정시에 올인한다', '하루 전체를 수능에 쓸 수 있음 · 학종·교과는 끝, 혼자 버텨야 한다', ['risk', 'rebel']),
        O('think', '부모님과 담임 선생님께 상담해 본다', '신중한 결정 · 시간이 걸린다', ['safe', 'obey']),
        O('stop', '친구를 말린다', '친구를 위한 말 · 친구가 서운해할 수 있다', ['kind']),
        O('respect', '"너는 너대로, 나는 나대로" 응원만 한다', '관계 유지 · 나는 아무것도 바꾸지 않는다', ['safe']),
      ]);
      if (o.id === 'join') { s.flags.ged = true; inc(s, 'parentRel', s.p.pStyle === 'warm' ? -3 : -12); inc(s, 'social', -12); s.zC += 0.08; s.autonomy += 2; L(s, '자퇴서를 냈다. 다음 날부터 아침 8시에 재종반으로 간다. 교복이 옷장에 걸려 있다.', 'warn'); }
      if (o.id === 'think') { inc(s, 'parentRel', 3); L(s, '담임 선생님이 내 생기부를 펼쳐 보이며 말했다. "너는 아직 수시 카드가 있어."'); }
      if (o.id === 'stop') { if (r.chance(0.5)) { inc(s, 'social', 4); L(s, `${b}${jo(b, '은/는')} 학교에 남기로 했다. "네 말 듣길 잘한 것 같아."`, 'good'); } else { inc(s, 'social', -4); L(s, `${b}${jo(b, '은/는')} 결국 자퇴했다. 빈자리가 크다.`); } }
      if (o.id === 'respect') L(s, `${b}${jo(b, '은/는')} 다음 달 자퇴했다. 가끔 재종반 사진을 보낸다.`);
    } },

  // ── 연애 ─────────────────────────────────────────
  { id: 'confess', w: s => (s.romance.status !== 'dating' && s.romance.count < 2 ? 0.8 + s.p.social * 0.35 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s, pt = newPartner(s, r);
      const o = choose(ctx, key, '체육대회가 끝난 저녁',
        `체육대회 계주에서 우리 반이 1등을 했다. 집에 가는 길, ${pt.name}에게서 DM이 온다. "오늘 너 뛰는 거 멋있었어. 사실 예전부터 좋아했어. 나랑 사귈래?" ${pt.studious ? `${pt.name}${jo(pt.name, '은/는')} 전교권 성적에 늘 독서실 마감까지 있는 아이다.` : `${pt.name}${jo(pt.name, '은/는')} 있으면 반 분위기가 밝아지는 아이다. 공부에는 별 관심이 없다.`} 기말까지는 3주 남았다.`, [
        O('yes', '"나도 좋아." 사귄다', '설렘과 위로 · 시간과 감정이 많이 든다', ['romance']),
        O('later', '"시험 끝나고 대답해도 될까?"', '시험은 지킴 · 상대가 기다려 줄지는 모른다', ['safe']),
        O('no', '"고마워. 그런데 지금은 공부에 집중하고 싶어"', '흔들림 없음 · 복도에서 마주칠 때마다 어색하다', ['study']),
      ]);
      if (o.id === 'yes') { startDating(s, pt.name, pt.studious); inc(s, 'mental', 10); L(s, `${pt.name}${jo(pt.name, '와/과')} 사귀기 시작했다. 하루 종일 폰만 본다.`, 'good'); }
      if (o.id === 'no') { inc(s, 'mental', -2); s.flags.rejectedName = pt.name; L(s, `${pt.name}${jo(pt.name, '은/는')} "알겠어"라고만 했다.`); }
      if (o.id === 'later') {
        if (r.chance(0.5)) { startDating(s, pt.name, pt.studious); L(s, `${pt.name}${jo(pt.name, '은/는')} 기다려 줬다. 시험이 끝난 날 사귀기 시작했다.`, 'good'); }
        else { inc(s, 'mental', -4); s.flags.rejectedName = pt.name; L(s, `시험이 끝났을 때 ${pt.name}에게는 이미 다른 사람이 있었다.`, 'warn'); }
      }
    } },
  { id: 'seeAgain', w: s => (s.flags.rejectedName && s.romance.status !== 'dating' && s.turnIdx >= 4 ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, nm = s.flags.rejectedName;
      const o = choose(ctx, key, '같은 조',
        `고2 수행평가 조 편성표에 내 이름 옆에 ${nm}${jo(nm, '이/가')} 있다. 예전에 내가 거절했던 그 사람이다. 첫 회의 날, ${nm}${jo(nm, '이/가')} 아무렇지 않게 웃으며 말한다. "오랜만이다. 잘 해 보자." 이상하게 그 웃음이 계속 생각난다.`, [
        O('confess', '이번엔 내가 먼저 마음을 말한다', '두 번째 기회 · 이번엔 내가 거절당할 수도', ['romance', 'risk']),
        O('friend', '좋은 친구로 지낸다', '편한 관계 · 마음은 정리되지 않는다', ['safe']),
        O('focus', '수행평가만 깔끔하게 끝낸다', '흔들리지 않음 · 기회는 지나간다', ['study']),
      ]);
      if (o.id === 'confess') { if (r.chance(0.45)) { startDating(s, nm, r.chance(0.5)); inc(s, 'mental', 12); L(s, `"너 진짜 늦었다." ${nm}${jo(nm, '이/가')} 웃었다.`, 'good'); } else { inc(s, 'mental', -12); L(s, '"이제는 그냥 친구가 좋아." 이번엔 내가 들었다.', 'bad'); } }
      if (o.id === 'friend') { inc(s, 'social', 4); L(s, '조 활동은 즐거웠다. 가끔 아쉬웠다.'); }
      if (o.id === 'focus') { s.record += 3; L(s, '수행평가는 A를 받았다.'); }
    } },
  { id: 'crush', w: s => (s.romance.status !== 'dating' && s.romance.count < 2 ? (s.flags.crushNow ? 4 : 0.9) : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, p = s.p;
      const nm = s.flags.crushNow || newPartner(s, r).name;
      const o = choose(ctx, key, '짝사랑',
        `${nm}. 요즘 수업 시간에도 그 사람 뒤통수만 보인다. 인스타 스토리에 올린 노래를 하루에 열 번 듣는다. 친구들은 "그냥 말해 봐, 너 티 다 나"라고 한다. 다음 주가 ${nm}의 생일이다.`, [
        O('confess', '생일에 편지와 함께 고백한다', '잘되면 연애 시작 · 안 되면 소문까지 감당해야 한다', ['romance', 'risk']),
        O('gift', '고백은 말고 작은 선물만 준다', '관계를 조금 가깝게 · 마음은 그대로 남는다', ['safe', 'romance']),
        O('keep', '마음속에만 담아 둔다', '아무 일도 안 일어남 · 계속 신경 쓰인다', ['safe']),
        O('fuel', '"멋진 사람이 되자." 공부로 마음을 돌린다', '동기가 될 수도 · 그냥 핑계일 수도', ['study']),
      ]);
      if (o.id === 'confess') {
        if (r.chance(0.28 + p.social * 0.06 + p.confidence * 0.04)) { startDating(s, nm, r.chance(0.45)); inc(s, 'mental', 14); L(s, `편지를 다 읽은 ${nm}${jo(nm, '이/가')} 말했다. "사실 나도."`, 'good'); }
        else { inc(s, 'mental', -14); inc(s, 'social', -3); s.flags.rejected = true; L(s, '"미안, 너는 좋은 친구야." 다음 날 반 애들이 다 알고 있었다.', 'bad'); }
      }
      if (o.id === 'gift') { inc(s, 'mental', 3); if (r.chance(0.35)) { startDating(s, nm, r.chance(0.45)); L(s, `일주일 뒤, ${nm}${jo(nm, '이/가')} 먼저 "주말에 뭐 해?"라고 물었다.`, 'good'); } else L(s, '"고마워!" 그게 다였다.'); }
      if (o.id === 'keep') { inc(s, 'lazy', 3); inc(s, 'mental', -2); L(s, '말 못 한 마음은 생각보다 오래 갔다.'); }
      if (o.id === 'fuel') { if (p.diligence >= 3) { s.zN += 0.04; L(s, '이상하게 집중이 잘 됐다.', 'good'); } else { inc(s, 'lazy', 3); L(s, '공부하려고 앉으면 그 사람 인스타를 보고 있었다.', 'warn'); } }
      delete s.flags.crushNow;
    } },
  { id: 'dateExam', w: s => (s.romance.status === 'dating' ? 2.5 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s, nm = s.romance.partner;
      const o = choose(ctx, key, '기말 2주 전, 주말',
        `${nm}: "이번 주말에 우리 100일이야. 나 진짜 오래 기다렸어. 영화 예매해 놨어 🥹" 기말까지 2주. 수학은 아직 한 단원이 남았다. ${s.romance.studious ? `${nm}${jo(nm, '은/는')} 어차피 공부를 다 해 놨다.` : ''}`, [
        O('go', '간다. 100일은 한 번뿐이다', '관계가 깊어짐 · 하루가 통째로 사라진다', ['romance']),
        O('short', '영화만 보고 저녁엔 독서실에 간다', '둘 다 챙김 · 상대가 아쉬워할 수 있다', ['safe', 'romance']),
        O('study', '"스터디카페에서 같이 공부하자, 끝나고 케이크 먹자"', '둘 다 성장할 수도 · 결국 수다만 떨 수도', ['study', 'romance']),
        O('no', '"미안, 시험 끝나고 제대로 하자"', '시험은 지킴 · 상대는 크게 서운하다', ['study']),
      ]);
      if (o.id === 'go') { s.romance.score += 12; inc(s, 'mental', 6); s.zN -= 0.04; L(s, '영화, 밥, 카페, 인생네컷까지. 집에 오니 밤 11시였다. 행복했다.'); }
      if (o.id === 'short') { s.romance.score += 5; s.zN -= 0.01; L(s, `헤어질 때 ${nm}${jo(nm, '이/가')} 조금 아쉬운 얼굴이었다.`); }
      if (o.id === 'study') { if (s.romance.studious) { s.zN += 0.03; s.romance.score += 6; L(s, `${nm}${jo(nm, '은/는')} 진짜 공부했다. 덩달아 나도 했다.`, 'good'); } else { s.zN -= 0.015; s.romance.score += 4; L(s, '결국 둘이 수다만 떨다 나왔다. 그래도 즐거웠다.'); } }
      if (o.id === 'no') {
        s.romance.score -= 16; s.zN += 0.025;
        if (s.romance.score < 30 && r.chance(0.5)) { breakUp(s, ctx.turn.id); inc(s, 'mental', -12); L(s, `"너는 맨날 공부가 먼저지." 그날 ${nm}${jo(nm, '와/과')} 헤어졌다.`, 'bad'); }
        else L(s, `${nm}${jo(nm, '이/가')} 하루 종일 답장을 짧게 했다.`, 'warn');
      }
    } },
  { id: 'partnerGrade', w: s => (s.romance.status === 'dating' && s.romance.since >= 1 ? 1.4 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, nm = s.romance.partner;
      const o = choose(ctx, key, '"너 때문에 성적 떨어졌대"',
        `${nm}의 엄마가 ${nm}에게 한 말이 돌고 돌아 내 귀에 들어왔다. "그 애 만나고 나서 성적이 떨어졌잖아. 헤어져." ${nm}${jo(nm, '은/는')} 나한테 그 얘기를 하지 않았다. 그런데 요즘 연락이 뜸하다.`, [
        O('talk', '먼저 그 얘기를 꺼내고 같이 방법을 찾는다', '관계가 단단해질 수도 · 무거운 대화가 된다', ['romance', 'self']),
        O('study', '"우리 같이 성적 올려서 보여 주자"', '서로 자극이 됨 · 연애가 숙제처럼 될 수도', ['study', 'romance']),
        O('end', '내가 먼저 놓아준다', '상대 집과의 갈등 끝 · 이별의 상처', ['safe']),
      ]);
      if (o.id === 'talk') { if (r.chance(0.6)) { s.romance.score += 10; L(s, '둘이서 한참 울고 웃었다. 일주일에 한 번만 만나기로 했다.', 'good'); } else { breakUp(s, ctx.turn.id); inc(s, 'mental', -10); L(s, `"미안, 지금은 엄마랑 싸울 힘이 없어." ${nm}${jo(nm, '이/가')} 말했다.`, 'bad'); } }
      if (o.id === 'study') { s.zN += 0.03; s.romance.score += 4; inc(s, 'stress', 5); L(s, '도서관 데이트가 늘었다.'); }
      if (o.id === 'end') { breakUp(s, ctx.turn.id); inc(s, 'mental', -10); L(s, '"네가 힘들어지는 게 싫어." 내가 먼저 말했다.', 'bad'); }
    } },
  { id: 'breakup', w: s => (s.romance.status === 'dating' && s.romance.since >= 1 ? 0.8 + (100 - s.romance.score) / 50 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s, nm = s.romance.partner;
      const o = choose(ctx, key, '밤 12시의 긴 메시지',
        `${nm}: "요즘 우리 만나도 둘 다 폰만 보는 것 같아. 나도 공부도 안 되고, 너한테 미안하고. 우리 잠깐 시간을 갖는 게 맞는 것 같아." 메시지 끝에 '읽음'이 뜬 지 10분째. 아직 답을 못 했다.`, [
        O('hold', '전화를 건다. 붙잡는다', '다시 만날 수도 · 더 상처받을 수도', ['romance']),
        O('time', '"알겠어. 시간 갖자. 기다릴게"', '여지를 남김 · 기다리는 동안 흔들린다', ['safe', 'romance']),
        O('cool', '"그동안 고마웠어"라고 정리한다', '깔끔한 끝 · 혼자 감당해야 한다', ['safe']),
        O('grind', '답장 대신 문제집을 편다', '아픔을 동력으로 · 감정이 늦게 터질 수 있다', ['study']),
      ]);
      if (o.id === 'hold' && r.chance(0.45)) { s.romance.score = 35; inc(s, 'mental', -6); L(s, '새벽 3시까지 통화했다. 일단은 다시 만나기로 했다. 불안하다.', 'warn'); return; }
      if (o.id === 'time' && r.chance(0.35)) { s.romance.status = 'pause'; inc(s, 'mental', -6); L(s, '한 달 동안 연락하지 않기로 했다. 매일 인스타를 확인한다.', 'warn'); return; }
      breakUp(s, ctx.turn.id);
      if (o.id === 'hold') { inc(s, 'mental', -16); L(s, '붙잡았지만 소용없었다. 몇 주 동안 아무것도 손에 안 잡혔다.', 'bad'); }
      if (o.id === 'time') { inc(s, 'mental', -12); L(s, '"잠깐"은 끝이 됐다.', 'bad'); }
      if (o.id === 'cool') { inc(s, 'mental', -9 + s.p.grit); L(s, '덤덤한 척했다. 혼자 있을 때만 울었다.', 'bad'); }
      if (o.id === 'grind') { inc(s, 'mental', -11); if (s.p.grit >= 4) { s.zC += 0.06; s.flags.fireUp = true; L(s, '이를 악물었다. 성적으로 보여 주겠다고.', 'good'); } else { inc(s, 'lazy', 5); L(s, '문제집을 폈지만, 자꾸 옛날 사진을 봤다.', 'bad'); } }
    } },
  { id: 'datingRumor', w: s => (s.romance.status === 'dating' && (s.p.pStyle === 'strict' || s.p.pStyle === 'anxious') ? 1.6 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, nm = s.romance.partner, pw = parentWord(s);
      const o = choose(ctx, key, '들켰다',
        `${pw}${jo(pw, '이/가')} 내 폰 알림에 뜬 "${nm} ❤️ 오늘 보고 싶어"를 봤다. "너 연애하니? 고2가 지금 연애할 때야? 당장 정리해."`, [
        O('lie', '"그냥 친구예요"', '오늘은 넘어감 · 몰래 하는 연애가 된다', ['safe']),
        O('honest', '"사귀고 있어요. 성적 안 떨어뜨릴게요"', '당당함 · 성적이 떨어지면 끝이다', ['self', 'rebel']),
        O('end', '부모님 말대로 정리한다', '집안 평화 · 상대와 나 둘 다 상처', ['obey']),
      ]);
      if (o.id === 'lie') { s.flags.secretLove = true; inc(s, 'stress', 6); L(s, '몰래 만나는 연애가 시작됐다. 매번 알리바이를 만든다.', 'warn'); }
      if (o.id === 'honest') { s.flags.loveDeal = true; s.autonomy += 1; inc(s, 'parentRel', -4); s.pressure += 4; L(s, '"그 말 꼭 지켜." 조건부 허락을 받았다.'); }
      if (o.id === 'end') { breakUp(s, ctx.turn.id); inc(s, 'parentRel', 4); inc(s, 'mental', -14); s.autonomy -= 1; L(s, `${nm}에게 이별 메시지를 보내고 엎드려 울었다.`, 'bad'); }
    } },

  // ── 부모님·가족 ────────────────────────────────────
  { id: 'parentTalk', w: s => (s.p.pStyle === 'strict' || s.p.pStyle === 'anxious' ? 2 : 0.9),
    run: (ctx, key, r) => {
      const s = ctx.s, p = s.p, pw = parentWord(s);
      const line = {
        strict: `"이 성적으로 어디 가겠다는 거야? 다음 달부터 핸드폰은 저녁 9시에 반납해. 그리고 주말 학원 하나 더 알아봤다."`,
        anxious: `"엄마가 입시 카페에서 봤는데, 이맘때 이 성적이면 인서울 힘들대. 컨설팅 한번 받아 보자. 엄마가 다 알아볼게."`,
        warm: `"요즘 많이 힘들지? 엄마는 성적보다 네 얼굴이 더 걱정돼. 혹시 하고 싶은 거 생겼어?"`,
        lax: `"성적표 나왔다며? 알아서 해. 네 인생이니까. 대학 안 가도 엄마는 상관없어."`,
        absent: `(카톡) "아빠 이번 주도 늦어. 성적표 사진 찍어서 보내 줘. 잘하고 있지? 👍"`,
      }[p.pStyle];
      const o = choose(ctx, key, '성적표가 나온 날', `${pw}: ${line}`, [
        O('promise', '"다음엔 꼭 올릴게요."', '갈등을 피함 · 지키지 못할 약속이 쌓인다', ['obey']),
        O('plan', '내가 짠 공부 계획을 보여 주며 이대로 해 보겠다고 한다', '믿음을 얻을 수도 · 계획대로 해야 한다', ['self', 'study']),
        O('rebel', '"제발 그만 좀 하세요!"', '속은 시원함 · 관계에 금이 간다', ['rebel']),
        O('dream', '사실 하고 싶은 진로가 따로 있다고 꺼낸다', '진짜 대화의 시작 · 무시당할 수도 있다', ['self', 'risk']),
      ]);
      if (o.id === 'promise') { s.pressure += 4; inc(s, 'parentRel', 3); if (p.diligence >= 3) inc(s, 'lazy', -3); L(s, '약속은 했다. 지킬 수 있을지는 모르겠다.'); }
      if (o.id === 'plan') { if (p.diligence >= 3 || r.chance(0.4)) { inc(s, 'parentRel', 6); s.pressure -= 4; s.autonomy += 1; inc(s, 'lazy', -4); L(s, '"한번 해 봐. 대신 엄마한테 매주 보여 줘."', 'good'); } else { inc(s, 'parentRel', -3); L(s, '"계획은 맨날 세우잖아." 말문이 막혔다.', 'warn'); } }
      if (o.id === 'rebel') { inc(s, 'parentRel', -15); inc(s, 'mental', -4); s.autonomy += 1; s.flags.rebel = (s.flags.rebel || 0) + 1; L(s, '문을 쾅 닫고 들어왔다. 며칠 동안 밥을 따로 먹었다.', 'bad'); }
      if (o.id === 'dream') {
        const ok = p.pStyle === 'warm' || p.pStyle === 'lax' || r.chance(0.25 + p.confidence * 0.05);
        if (ok) { inc(s, 'parentRel', 8); s.pressure -= 5; s.autonomy += 1; s.flags.parentHeard = true; L(s, `처음으로 ${pw}${jo(pw, '이/가')} 끝까지 들어 줬다.`, 'good'); }
        else { inc(s, 'parentRel', -6); L(s, '"그런 건 대학 가서 생각해." 대화는 3분 만에 끝났다.', 'warn'); }
      }
    } },
  { id: 'tutor', w: s => (s.p.wealth !== 'low' && ['med', 'prestige', 'law'].indexOf(s.p.pDesire) >= 0 ? 2 : s.p.wealth === 'high' ? 0.8 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, p = s.p, pw = parentWord(s);
      const o = choose(ctx, key, '한 달 200만 원',
        `${pw}${jo(pw, '이/가')} 상담 실장과 통화를 끝내고 들어온다. "대치동 ○○ 선생님 그룹 과외에 자리가 하나 났대. 한 달 200. 대기만 1년이래. 엄마 적금 깨면 돼." 아빠는 거실에서 아무 말도 하지 않는다.`, [
        O('yes', '한다', '실력이 확실히 오를 수 있음 · 집안 형편과 숙제 부담', ['obey', 'study']),
        O('online', '"인강 패스로 할게요. 그 돈은 아껴 주세요"', '돈을 아낌 · 스스로 끝까지 들어야 한다', ['self', 'safe']),
        O('self', '"혼자 해 볼게요. 대신 성적으로 증명할게요"', '자율성 · 증명 못 하면 더 큰 압박', ['self', 'rebel']),
      ]);
      if (o.id === 'yes') { const wk = SUB_KEYS.reduce((w, k) => (s.sub[k] < s.sub[w] ? k : w), 'math'); s.acad[wk] = 'tutor'; s.tutorQ[wk] = Math.abs(s.tutorQ[wk]) + 0.04; s.money -= 16; s.zC += 0.1 * p.comprehension / 3; s.zN += 0.05; inc(s, 'stress', 7); inc(s, 'parentRel', 5); s.autonomy -= 1; L(s, '선생님은 확실히 달랐다. 대신 숙제가 하루 4시간 분량이다. 엄마가 적금을 깼다는 게 계속 마음에 걸렸다.'); }
      if (o.id === 'self') { inc(s, 'parentRel', -5); s.autonomy += 1; s.pressure += 6; if (p.diligence >= 4) { s.zC += 0.05; L(s, '혼자 해 보겠다고 한 말을 지키려고 더 독하게 했다.', 'good'); } else L(s, '혼자 하겠다고 했지만, 혼자는 생각보다 어려웠다.', 'warn'); }
      if (o.id === 'online') { s.money -= 2; s.zC += 0.035 * p.diligence / 3; L(s, '인강 패스를 끊었다. 완강률이 관건이다.'); }
    } },
  { id: 'consult', w: s => (s.p.wealth !== 'low' && s.p.pStyle === 'anxious' && s.turnIdx >= 4 ? 2 : s.p.wealth === 'high' && s.turnIdx >= 4 ? 0.6 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '입시 컨설팅',
        `엄마 손에 이끌려 간 입시 컨설팅 사무실. 컨설턴트가 내 생기부를 넘기며 말한다. "솔직히 말씀드리면 지금 생기부는 방향이 없어요. 남은 기간 동안 '스토리'를 만들어야 합니다. 저희 패키지가 300입니다." 엄마가 내 얼굴을 본다.`, [
        O('buy', '하겠다고 한다', '생기부 방향이 잡힘 · 비싸고, 내 이야기가 아닐 수 있다', ['obey', 'record']),
        O('own', '"제가 진짜 관심 있는 걸로 직접 만들어 볼게요"', '내 진짜 이야기 · 혼자 방향을 잡아야 한다', ['self', 'record']),
        O('no', '"수시 말고 정시로 갈래요"', '돈을 아낌 · 수시 카드를 스스로 버린다', ['rebel', 'study']),
      ]);
      if (o.id === 'buy') { s.money -= 18; s.record += 9; s.autonomy -= 1; s.recFit[topInterest(s)] += 8; L(s, '컨설턴트가 정해 준 탐구 주제 3개를 받았다. 솔직히 하나도 궁금하지 않다.'); }
      if (o.id === 'own') { s.record += 3 + s.p.curiosity * 1.5; s.recFit[topInterest(s)] += 10; s.autonomy += 1; L(s, '내가 정말 궁금했던 질문으로 탐구 계획을 짰다.', s.p.curiosity >= 4 ? 'good' : 'info'); }
      if (o.id === 'no') { s.flags.leanJungsi = true; inc(s, 'parentRel', -4); s.zC += 0.02; L(s, '엄마는 한숨을 쉬었다. 나는 수능 기출을 펼쳤다.'); }
    } },
  { id: 'compare', w: s => (s.p.sibling === 'better' ? 2 : s.p.pDesire === 'prestige' ? 1.2 : 0.3), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const sib = s.p.sibling === 'better';
      const o = choose(ctx, key, '명절의 거실',
        `추석. 큰아버지가 TV를 보다가 묻는다. "${sib ? '형(언니)은 이번에 장학금 받았다며? 너는 몇 등이냐?' : '○○이는 이번에 의대 붙었다더라. 너는 어디 생각하니?'}" 거실이 조용해진다. 엄마가 대신 웃으며 말한다. "얘도 요즘 열심히 해요." 엄마 웃음이 어색하다.`, [
        O('answer', '내 목표를 또박또박 말한다', '당당함 · 말한 만큼 부담이 생긴다', ['self', 'risk']),
        O('fuel', '대답 대신 속으로 이를 간다', '오기가 생긴다 · 마음은 계속 쓰리다', ['study', 'rebel']),
        O('shrug', '"그냥 열심히 하고 있어요" 하고 웃는다', '무난함 · 밤에 잠이 안 온다', ['safe']),
        O('tell', '집에 와서 엄마에게 서운했다고 말한다', '관계 회복의 기회 · 엄마도 상처받을 수 있다', ['self', 'kind']),
      ]);
      if (o.id === 'answer') { s.flags.saidGoal = true; inc(s, 'stress', 6); s.zN += 0.02; L(s, '"오, 큰소리 쳤다?" 다들 웃었다. 그 말이 머릿속에 오래 남았다.'); }
      if (o.id === 'fuel') { s.zN += 0.03; s.zC += 0.03; inc(s, 'stress', 10); L(s, '그날부터 독서실 마감까지 있었다. 마음 한구석은 계속 쓰렸다.'); }
      if (o.id === 'shrug') { inc(s, 'mental', -4); L(s, '웃었지만 밤에 잠이 잘 안 왔다.'); }
      if (o.id === 'tell') { const ok = s.p.pStyle !== 'strict' || r.chance(0.3); if (ok) { inc(s, 'parentRel', 8); s.pressure -= 4; L(s, '"미안해. 엄마가 너를 지켜 줬어야 했는데."', 'good'); } else { inc(s, 'parentRel', -5); L(s, '"그게 다 너 잘되라고 하는 말이야."', 'warn'); } }
    } },
  { id: 'push', w: s => { const d = PARENT_DESIRES[s.p.pDesire]; return d && d.field && topInterest(s) !== d.field ? 2.2 : 0; }, once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, p = s.p, d = PARENT_DESIRES[p.pDesire], my = topInterest(s), pw = parentWord(s);
      const o = choose(ctx, key, '부모님이 정한 진로',
        `${pw}${jo(pw, '이/가')} 생기부 진로 희망란을 보고 말한다. "${FIELDS[my].name}? 그거 해서 뭐 먹고살 건데. ${FIELDS[d.field].name} 쪽으로 써. 엄마 아빠 친구 자식들 봐. 그쪽이 결국 안정적이야. 네가 몰라서 그래." 진로 희망란은 다음 주까지 담임 선생님께 내야 한다.`, [
        O('obey', `진로 희망란에 ${FIELDS[d.field].name}${jo(FIELDS[d.field].name, '이라고/라고')} 쓴다`, '집안 평화와 지원 · 내가 원하는 길과 멀어진다', ['obey', 'safe']),
        O('both', `${FIELDS[d.field].name}${jo(FIELDS[d.field].name, '이라고/라고')} 쓰되, 활동은 두 분야에 걸쳐 한다`, '선택을 미룸 · 생기부 방향이 흐려질 수 있다', ['safe']),
        O('persuade', `${FIELDS[my].name} 직업의 현실(연봉·전망)을 조사해서 설득한다`, '설득되면 든든한 지원 · 실패하면 갈등이 커진다', ['self', 'risk']),
        O('secret', `말없이 ${FIELDS[my].name}${jo(FIELDS[my].name, '이라고/라고')} 써서 낸다`, '내 길 · 들키면 큰 싸움', ['rebel', 'self']),
      ]);
      if (o.id === 'obey') { s.flags.obeyParent = true; s.interest[d.field] += 14; s.recFit[d.field] += 6; s.autonomy -= 2; inc(s, 'parentRel', 8); if (fitOf(s, d.field) < 0.7) inc(s, 'mental', -5); L(s, `"알겠어요." ${FIELDS[d.field].name} 쪽으로 생기부 방향을 틀었다.`); }
      if (o.id === 'both') { s.recFit[d.field] += 4; s.recFit[my] += 4; s.flags.splitPath = true; L(s, '두 분야 활동을 반씩 했다. 담임 선생님이 "그래서 넌 뭘 하고 싶니?"라고 물었다.', 'warn'); }
      if (o.id === 'persuade') {
        const ok = r.chance((p.pStyle === 'warm' ? 0.7 : p.pStyle === 'lax' ? 0.65 : 0.22) + p.confidence * 0.04 + (s.recFit[my] > 15 ? 0.15 : 0));
        if (ok) { s.flags.parentAccept = true; s.pressure -= 10; s.autonomy += 2; inc(s, 'parentRel', 5); L(s, `PPT까지 만들어 보여 줬다. 한참 듣던 ${pw}${jo(pw, '이/가')} 말했다. "그래, 네가 그렇게까지 생각했으면."`, 'good'); }
        else { inc(s, 'parentRel', -9); inc(s, 'stress', 6); L(s, '"인터넷에 나온 거 다 믿니?" 설득은 실패했다.', 'bad'); }
      }
      if (o.id === 'secret') { s.flags.secretPath = true; s.autonomy += 1; s.recFit[my] += 6; inc(s, 'stress', 6); L(s, '진로 희망란에 내 꿈을 썼다. 부모님은 아직 모른다.'); }
    } },
  { id: 'secretFound', w: s => (s.flags.secretPath && s.turnIdx >= 4 ? 3.5 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, my = topInterest(s), pw = parentWord(s);
      const o = choose(ctx, key, '학부모 상담 주간',
        `학부모 상담에 다녀온 ${pw}${jo(pw, '이/가')} 현관에서 신발도 안 벗고 서 있다. "담임 선생님이 그러시더라. 네 진로 희망이 ${FIELDS[my].name}${jo(FIELDS[my].name, '이라고/라고')}. 엄마만 몰랐네?"`, [
        O('sorry', '"죄송해요. 말하면 반대할 것 같았어요"', '솔직한 사과 · 진로를 지킬 수 있을지는 모른다', ['kind', 'self']),
        O('stand', '"네, 저 이거 할 거예요"', '내 길을 선언 · 정면충돌', ['rebel', 'self']),
        O('give', '"알겠어요. 다시 바꿀게요"', '갈등 종료 · 꿈을 내려놓는다', ['obey']),
      ]);
      if (o.id === 'sorry') { if (s.p.pStyle === 'warm' || r.chance(0.4)) { s.flags.parentAccept = true; inc(s, 'parentRel', 4); L(s, '"…얼마나 하고 싶었으면." 그날 밤 처음으로 진로 얘기를 오래 했다.', 'good'); } else { inc(s, 'parentRel', -8); L(s, '"일단은 엄마 말 들어." 아무것도 정해지지 않았다.', 'warn'); } }
      if (o.id === 'stand') { inc(s, 'parentRel', -16); s.autonomy += 2; s.flags.rebel = (s.flags.rebel || 0) + 1; s.flags.parentWar = true; L(s, '그날 이후 집에서 진로 얘기는 금기어가 됐다.', 'bad'); }
      if (o.id === 'give') { s.autonomy -= 2; delete s.flags.secretPath; s.flags.obeyParent = true; const d = PARENT_DESIRES[s.p.pDesire].field; if (d) s.interest[d] += 10; inc(s, 'mental', -8); L(s, '진로 희망란을 다시 고쳐 냈다. 손이 떨렸다.', 'bad'); }
    } },
  { id: 'parentFight', w: s => (s.p.pBond === 'fight' ? 2.2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '새벽 1시, 거실',
        `방문 너머로 부모님 목소리가 커진다. "애 앞에서 그만해!" "애가 뭘 알아!" 유리컵 깨지는 소리. 그리고 엄마가 말한다. "이혼해. 애 수능 끝나면 진짜 이혼해." 내일은 중간고사 첫날이다.`, [
        O('out', '방에서 나가 둘 사이에 선다', '싸움이 멈출 수도 · 내가 짊어지게 된다', ['kind', 'risk']),
        O('earphone', '이어폰을 끼고 문제집을 본다', '시험은 지킴 · 마음은 전혀 괜찮지 않다', ['study']),
        O('friend', `${s.bestFriend ? s.bestName : '친구'}에게 "자니?" 하고 연락한다`, '털어놓을 곳 · 잠은 더 못 잔다', ['social']),
        O('counsel', '다음 날 상담 선생님을 찾아간다', '어른의 도움 · 집안일을 꺼내는 게 두렵다', ['self', 'rest']),
      ]);
      if (o.id === 'out') { inc(s, 'parentRel', 6); inc(s, 'mental', -8); s.flags.mature = true; s.zN -= 0.03; L(s, '"그만 좀 해요!" 둘 다 멈췄다. 엄마가 나를 안고 울었다.'); }
      if (o.id === 'earphone') { inc(s, 'mental', -10); s.zN -= 0.01; L(s, '음악 볼륨을 끝까지 올렸다. 그날 시험은 기억이 안 난다.', 'bad'); }
      if (o.id === 'friend') { inc(s, 'mental', -3); inc(s, 'health', -4); if (s.bestFriend) s.flags.friendForever = true; L(s, `새벽 3시까지 ${s.bestFriend ? s.bestName : '친구'}${jo(s.bestFriend ? s.bestName : '친구', '이/가')} 들어 줬다.`); }
      if (o.id === 'counsel') { inc(s, 'mental', 6); inc(s, 'stress', -8); L(s, '"네 잘못이 아니야." 그 말을 처음 들었다.', 'good'); }
    } },
  { id: 'crisis', w: s => (s.p.wealth === 'high' ? 0.1 : s.p.wealth === 'low' ? 0.8 : 0.4) + (s.p.pJob === 'self' ? 0.6 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      s.money = Math.max(0, s.money - 25); s.flags.crisis = true;
      const job = s.p.pJob === 'self' ? '가게 매출이 반토막 났다. 대출 이자가 밀렸다고 한다' : '아빠 회사가 구조조정에 들어갔다. 아빠 이름이 명단에 있다고 한다';
      const o = choose(ctx, key, '식탁 위의 고지서',
        `${job}. 식탁 위에 고지서가 쌓여 있다. 엄마가 조심스럽게 말한다. "다음 달부터 학원 하나만 다니면 안 될까? 미안해." 동생 학원은 그대로다.`, [
        O('work', '"주말에 알바할게요. 학원비 보탤게요"', '집에 보탬 · 공부 시간이 줄어든다', ['work', 'kind']),
        O('cut', '"학원 다 끊고 인강으로 할게요"', '돈 걱정을 덜어 줌 · 혼자 해내야 한다', ['self', 'kind']),
        O('keep', '"이 학원은 꼭 다녀야 해요"', '공부 환경 유지 · 집에 부담이 된다', ['study']),
        O('ignore', '아무 말도 하지 않는다', '부딪히지 않음 · 서로 서운함이 쌓인다', ['safe']),
      ]);
      if (o.id === 'work') { s.money += 8; s.flags.work = true; s.zN -= 0.04; inc(s, 'parentRel', 8); s.flags.mature = true; L(s, '주말마다 식당에서 일했다. 엄마가 몰래 울었다는 걸 나중에 알았다.'); }
      if (o.id === 'cut') { s.money += 6; inc(s, 'parentRel', 6); s.flags.selfStudy = true; if (s.p.diligence >= 3) { s.zC += 0.02; L(s, '인강 진도표를 벽에 붙였다.', 'good'); } else { inc(s, 'lazy', 6); L(s, '인강은 1.5배속으로 틀어 놓고 잠들기 일쑤였다.', 'warn'); } }
      if (o.id === 'keep') { s.money -= 6; inc(s, 'parentRel', -4); s.flags.moneyTight = true; L(s, '엄마는 알겠다고 했다. 그 달부터 엄마가 저녁에 부업을 시작했다.'); }
      if (o.id === 'ignore') { inc(s, 'parentRel', -4); inc(s, 'mental', -4); L(s, '이어폰 볼륨을 키웠다.'); }
    } },
  { id: 'sick', w: () => 0.25, once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '응급실',
        `수업 중에 담임 선생님이 나를 부른다. "어머니가 쓰러지셔서 병원에 계신대." 수술은 잘 됐지만 한 달은 입원해야 한다. 아빠는 지방 출장 중이고, 집에는 초등학생 동생이 있다. 다음 주가 기말고사다.`, [
        O('care', '학원을 쉬고 병원과 동생을 챙긴다', '가족 곁을 지킴 · 시험 준비가 무너진다', ['kind']),
        O('split', '학교 끝나고 병원에 들렀다가 밤에 공부한다', '둘 다 해 보려 함 · 몸이 버틸지 모른다', ['safe', 'kind']),
        O('focus', '"엄마 걱정 말고 공부해" 말대로 공부에 집중한다', '시험은 지킴 · 마음의 짐이 남는다', ['study']),
      ]);
      if (o.id === 'care') { inc(s, 'parentRel', 14); s.zN -= 0.06; s.flags.mature = true; L(s, '병원 침대 옆에서 문제집을 풀었다. 엄마 손이 생각보다 작았다.'); }
      if (o.id === 'split') { inc(s, 'parentRel', 8); inc(s, 'health', -12); s.zN -= 0.02; L(s, '한 달 동안 하루 4시간씩 잤다.'); }
      if (o.id === 'focus') { inc(s, 'stress', 8); inc(s, 'parentRel', -2); L(s, '"엄마 괜찮아. 공부해." 그 말이 더 마음에 걸렸다.'); }
    } },

  // ── 공부·습관 ───────────────────────────────────────
  { id: 'phone', w: s => (s.lazy >= 38 ? s.lazy / 24 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '스크린타임 주간 리포트',
        `일요일 밤, 휴대폰이 알려 준다. "이번 주 하루 평균 사용 시간 7시간 12분, 지난주보다 18% 증가." 가장 많이 쓴 앱은 숏폼. 새벽 2시에 '딱 하나만' 보다가 4시가 된 날이 사흘이다. 그런데 친구들 다 이 정도는 한다.`, [
        O('lock', '공부 시간엔 앱 잠금을 걸고 타이머 앱을 켠다', '시간이 생긴다 · 의지가 약하면 3일 만에 푼다', ['study', 'self']),
        O('give', '부모님께 폰을 맡긴다', '확실함 · 단톡방 소식에서 소외된다', ['obey', 'study']),
        O('swap', '2G폰(공기계)으로 바꾼다', '가장 확실함 · 친구들과의 연결이 거의 끊긴다', ['study', 'risk']),
        O('ignore', '다들 이 정도는 한다', '스트레스 없음 · 계속 같은 주가 반복된다', ['fun']),
      ]);
      if (o.id === 'lock') { const d = s.p.diligence >= 3 ? 14 : 6; inc(s, 'lazy', -d); inc(s, 'mental', -2); L(s, d > 10 ? '사흘은 금단 증상이 있었다. 일주일 뒤엔 시간이 생겼다.' : '앱 잠금은 3일 만에 풀었다.', d > 10 ? 'good' : 'warn'); }
      if (o.id === 'give') { inc(s, 'lazy', -12); inc(s, 'parentRel', 3); inc(s, 'social', -3); L(s, '단톡방 소식을 몰라 조금 소외됐지만 공부 시간은 늘었다.', 'good'); }
      if (o.id === 'swap') { inc(s, 'lazy', -20); inc(s, 'social', -8); inc(s, 'mental', -3); L(s, '폴더폰을 열면 문자 3통이 와 있다. 하루가 길어졌다.', 'good'); }
      if (o.id === 'ignore') { inc(s, 'lazy', 8); inc(s, 'health', -5); L(s, '다음 주 리포트는 7시간 40분이었다.', 'bad'); }
    } },
  { id: 'mockShock', w: s => (s.turnIdx >= 4 ? 1.2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '수학 4등급',
        `모의고사 수학이 4등급이 나왔다. 21번, 29번, 30번은 손도 못 댔고, 쉬운 14번을 계산 실수로 틀렸다. 학원 선생님은 "개념은 되는데 시간이 부족해서 그래"라고 하고, 담임 선생님은 "개념부터 다시 해"라고 한다. 둘 다 맞는 말 같다.`, [
        O('basic', '개념서를 처음부터 다시 본다', '기초가 단단해짐 · 진도가 몇 달 늦어진다', ['study', 'safe']),
        O('drill', '실전 모의고사를 매일 1회씩 시간 재고 푼다', '시간 감각이 생김 · 구멍 난 개념은 그대로', ['study', 'risk']),
        O('academy', '수학 학원을 옮긴다', '새로운 방식 · 적응에 시간이 들고 돈이 든다', ['obey']),
        O('giveup', '수학은 3등급 유지만 하고 다른 과목에 올인', '다른 과목이 오름 · 원서 쓸 때 선택지가 줄어든다', ['fun', 'risk']),
      ]);
      if (o.id === 'basic') { s.sub.math += (s.p.comprehension >= 3 ? 0.18 : 0.12) * s.p.diligence / 3; s.zN -= 0.01; L(s, '중학교 개념에서 막혀 있던 걸 발견했다. 뭔가 풀리기 시작했다.', 'good'); }
      if (o.id === 'drill') { s.sub.math += s.p.comprehension >= 4 ? 0.22 : 0.07; inc(s, 'stress', 5); L(s, s.p.comprehension >= 4 ? '시간이 남기 시작했다.' : '매일 같은 유형에서 틀렸다.', s.p.comprehension >= 4 ? 'good' : 'warn'); }
      if (o.id === 'academy') { s.money -= 5; s.sub.math += 0.1; s.acad.math = s.sub.math < 0.3 ? 'director' : 'big'; L(s, s.acad.math === 'director' ? '소규모 원장 직강 수학 학원으로 옮겼다. 원장님이 중학교 개념부터 다시 잡자고 했다.' : '대형 학원 레벨테스트에서 중간반에 배정됐다.'); }
      if (o.id === 'giveup') { s.flags.mathGiveUp = true; s.sub.math -= 0.35; s.sub.kor += 0.06; s.sub.eng += 0.06; s.zN += 0.02; inc(s, 'stress', -6); s.interest.hum += 4; L(s, '수학 시간을 국어·영어로 돌렸다. 공대·경영 쪽 원서는 쓰기 어려워졌다.', 'warn'); }
    } },
  { id: 'burnout', w: s => (s.stress >= 62 || s.mental <= 32 ? 3.5 : 0),
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '아무것도 하기 싫다',
        `책을 펴도 글자가 안 들어온다. 아침에 눈을 뜨면 "오늘도 똑같겠지"라는 생각부터 든다. 밥맛이 없고, 이유 없이 눈물이 난다. 그런데 다음 달이 모의고사다. 쉬면 뒤처질 것 같고, 계속하면 무너질 것 같다.`, [
        O('counsel', 'Wee클래스 상담실 문을 두드린다', '마음이 회복됨 · 처음 말을 꺼내기가 어렵다', ['self', 'rest']),
        O('rest', '일주일 동안 책을 덮고 쉰다', '다시 일어설 힘 · 죄책감과 진도 공백', ['rest']),
        O('lower', '목표를 한 단계 낮춰 다시 계획을 짠다', '부담이 줄어듦 · 스스로 실망할 수 있다', ['safe']),
        O('push', '버틴다. 남들도 다 힘들다', '진도는 유지 · 더 크게 무너질 수 있다', ['study']),
      ]);
      if (o.id === 'counsel') { inc(s, 'mental', 16); inc(s, 'stress', -16); L(s, '상담 선생님 앞에서 처음으로 힘들다고 말했다. 조금 가벼워졌다.', 'good'); }
      if (o.id === 'rest') { inc(s, 'stress', -22); inc(s, 'mental', 10); s.zN -= 0.03; L(s, '죄책감이 들었지만, 다시 책을 펼 수 있게 됐다.'); }
      if (o.id === 'lower') { inc(s, 'stress', -12); inc(s, 'mental', 6); s.flags.loweredGoal = true; L(s, '목표를 낮췄더니 오히려 공부가 손에 잡혔다.'); }
      if (o.id === 'push') { inc(s, 'stress', 10); inc(s, 'mental', -10); s.flags.burnout = (s.flags.burnout || 0) + 1; if (s.p.grit >= 4) { s.zN += 0.03; L(s, '버텼다. 대신 웃는 일이 줄었다.'); } else { inc(s, 'health', -10); L(s, '버티다 결국 몸살로 사흘을 앓았다.', 'bad'); } }
    } },
  { id: 'sleep', w: s => (s.stress >= 48 || s.lazy >= 42 ? 1.2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '새벽 2시와 아침 6시 반 사이',
        `매일 새벽 2시에 자고 6시 반에 일어난다. 오후 수업은 기억이 없다. 에너지 드링크를 하루 두 캔 마신다. 반 1등은 "나 12시에 자는데?"라고 한다. 거짓말 같다.`, [
        O('fix', '12시 전에 자고, 대신 쉬는 시간을 줄인다', '수업 집중력 회복 · 밤의 자유 시간이 사라진다', ['rest', 'self']),
        O('nap', '점심시간에 20분 낮잠을 잔다', '오후가 살아남 · 점심시간 친구들과의 시간이 준다', ['rest']),
        O('keep', '잠은 대학 가서 자면 된다', '공부 시간 유지 · 체력이 바닥난다', ['study']),
      ]);
      if (o.id === 'fix') { inc(s, 'health', 10); inc(s, 'lazy', -3); inc(s, 'mental', 4); L(s, '수업 시간에 깨어 있게 됐다. 이게 이렇게 큰 차이일 줄이야.', 'good'); }
      if (o.id === 'nap') { inc(s, 'health', 6); inc(s, 'social', -2); L(s, '오후 수업이 들리기 시작했다.'); }
      if (o.id === 'keep') { inc(s, 'health', -11); s.zN += 0.01; L(s, '커피와 에너지 드링크로 버틴다.', 'warn'); }
    } },
  { id: 'seteuk', w: s => (s.turnIdx >= 2 && s.turnIdx <= 8 ? 1.3 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, ti = topInterest(s);
      const o = choose(ctx, key, '세특 마감',
        `학기 말, 과목 선생님이 말씀하신다. "세특(세부능력 및 특기사항)에 쓸 활동 보고서, 금요일까지 내. 안 내면 쓸 게 없다." 반 단톡방에는 작년 선배들의 '합격 세특 예시' 파일이 돌고 있다. 그대로 베끼면 30분이면 끝난다.`, [
        O('deep', `${FIELDS[ti].name}${jo(FIELDS[ti].name, '와/과')} 연결해서 직접 탐구한 내용으로 쓴다`, '나만의 이야기 · 일주일 밤을 쓴다', ['record', 'self']),
        O('copy', '선배 예시를 참고해서 비슷하게 쓴다', '시간 절약 · 비슷한 세특이 수십 개라 눈에 안 띈다', ['safe']),
        O('min', '최소한만 써서 낸다', '시험공부 시간 확보 · 생기부 한 칸이 비어 보인다', ['study']),
      ]);
      if (o.id === 'deep') { s.record += 5 + s.p.curiosity * 1.5; s.recFit[ti] += 9; s.zN -= 0.02; L(s, '선생님이 보고서에 "흥미로운 질문"이라고 적어 주셨다.', 'good'); }
      if (o.id === 'copy') { s.record += 2; L(s, '무난하게 냈다. 아마 아무도 기억 못 할 것이다.'); }
      if (o.id === 'min') { s.record -= 1; s.zN += 0.015; L(s, '그 시간에 기출을 한 회 더 풀었다.'); }
    } },
  { id: 'groupWork', w: s => (s.turnIdx <= 8 ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '무임승차',
        `모둠 발표 수행평가. 네 명 중 두 명은 단톡방을 읽기만 한다. 마감은 사흘 뒤. 점수는 모둠 전체가 같이 받는다. 남은 한 명이 말한다. "그냥 우리 둘이 하자. 선생님한테 말하면 우리만 이상해져."`, [
        O('do', '둘이서 다 한다', '점수는 지킴 · 억울하고 시간이 든다', ['kind', 'study']),
        O('assign', '역할을 나눠 단톡방에 공지하고, 마감을 정한다', '리더십 · 안 하면 결국 내가 해야 한다', ['self', 'social']),
        O('teacher', '선생님께 기여도를 따로 말씀드린다', '공정함 · 모둠 분위기가 험해진다', ['self', 'risk']),
      ]);
      if (o.id === 'do') { s.record += 3; inc(s, 'stress', 6); L(s, '발표는 잘 끝났다. 무임승차한 둘은 "고마워 ㅋㅋ"라고만 했다.'); }
      if (o.id === 'assign') { if (r.chance(0.55 + s.p.social * 0.05)) { s.record += 5; s.talent.people += 6; L(s, '공지가 통했다. 다들 자기 몫을 해 왔다.', 'good'); } else { s.record += 3; inc(s, 'stress', 8); L(s, '결국 새벽에 혼자 PPT를 마저 만들었다.', 'warn'); } }
      if (o.id === 'teacher') { s.record += 4; inc(s, 'social', -6); L(s, '선생님은 개인 점수를 따로 주셨다. 두 명은 나를 피한다.'); }
    } },
  { id: 'senior', w: s => (s.turnIdx >= 4 && s.turnIdx <= 8 ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '재수한 선배의 조언',
        `동아리 선배가 재수 끝에 연세대에 붙어 학교에 강연을 왔다. 끝나고 따로 물었다. 선배가 말했다. "나는 고2 때 수시랑 정시 사이에서 갈팡질팡하다 둘 다 놓쳤어. 너는 지금 하나를 정해. 둘 다 하려면 진짜 두 배로 해야 돼."`, [
        O('susi', '수시(내신·생기부)를 주력으로 정한다', '학교생활에 집중 · 수능 최저가 발목 잡을 수 있다', ['safe', 'record']),
        O('jungsi', '정시(수능)를 주력으로 정한다', '한 방에 역전 가능 · 내신을 포기하면 돌아갈 길이 없다', ['risk', 'study']),
        O('both', '그래도 둘 다 해 본다', '선택지를 유지 · 둘 다 어중간해질 수 있다', ['study']),
      ]);
      if (o.id === 'susi') { s.flags.leanSusi = true; s.zN += 0.03; s.record += 3; s.zC -= 0.02; L(s, '내신 시험 3주 전부터는 수능 공부를 내려놓기로 했다.'); }
      if (o.id === 'jungsi') { s.flags.leanJungsi = true; s.zC += 0.05; s.zN -= 0.04; L(s, '수업 시간에 몰래 수능 기출을 푼다. 내신은 조금씩 내려간다.'); }
      if (o.id === 'both') { inc(s, 'stress', 8); L(s, '하루가 모자랐다.'); }
    } },

  // ── 활동·재능 ───────────────────────────────────────
  { id: 'contest', w: s => (s.turnIdx <= 8 ? 1.2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, ti = topInterest(s);
      const o = choose(ctx, key, '교내 탐구대회',
        `교내 탐구보고서 대회 공고가 붙었다. 수상하면 생기부 수상 경력에 남는다. 마감은 기말고사 1주 전. ${FIELDS[ti].name} 쪽으로 평소 궁금했던 주제가 하나 있다. 친구 둘이 "같이 팀으로 나가자"고 한다.`, [
        O('solo', '혼자 내 주제로 나간다', '전공 적합성이 뚜렷해짐 · 시험 직전 시간을 뺏긴다', ['record', 'self']),
        O('team', '친구들과 팀으로 나간다', '부담이 나뉨 · 주제가 내 관심사와 멀어질 수 있다', ['record', 'social']),
        O('skip', '이번엔 건너뛴다. 내신이 먼저다', '시험에 집중 · 생기부 한 줄을 놓친다', ['study', 'safe']),
      ]);
      if (o.id === 'solo') { s.record += 7; s.recFit[ti] += 10; inc(s, 'stress', 5); s.zN -= 0.025; if (r.chance(0.18 + s.p.curiosity * 0.07)) { s.record += 6; s.flags.award = (s.flags.award || 0) + 1; L(s, '금상을 받았다! 세특에 들어갈 문장이 생겼다.', 'good'); } else L(s, '입상은 못 했지만 보고서는 생기부에 남았다.'); }
      if (o.id === 'team') { s.record += 5; s.recFit[ti] += 4; inc(s, 'social', 4); s.zN -= 0.01; if (r.chance(0.3)) { s.flags.award = (s.flags.award || 0) + 1; s.record += 4; L(s, '팀으로 은상을 받았다.', 'good'); } else L(s, '팀플은 즐거웠다. 결과는 아쉬웠다.'); }
      if (o.id === 'skip') L(s, '대회는 건너뛰었다.');
    } },
  { id: 'council', w: s => (s.p.social >= 3 && s.turnIdx <= 6 ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '학생회 선거',
        `담임 선생님이 학생회 부회장 후보로 나가 보라고 하신다. "리더십은 학종에서 중요하게 본다." 선거 운동은 2주, 당선되면 매주 회의와 행사 준비가 있다. 상대 후보는 인기 많은 축구부 주장이다.`, [
        O('run', '출마한다', '리더십 경력 · 떨어지면 시간과 자존심만 잃는다', ['risk', 'social', 'record']),
        O('help', '친구 선거 캠프를 돕는다', '부담 적은 경험 · 생기부에 남는 건 거의 없다', ['social']),
        O('no', '시간이 아깝다', '공부 시간 유지 · 기회 하나를 넘긴다', ['study']),
      ]);
      if (o.id === 'run') { if (r.chance(0.3 + s.p.social * 0.09)) { s.record += 10; s.talent.people += 10; inc(s, 'stress', 6); s.flags.council = true; L(s, '당선됐다. 리더십 항목에 쓸 게 생겼다. 대신 바빠졌다.', 'good'); } else { inc(s, 'mental', -5); L(s, '아깝게 떨어졌다. 득표 차는 11표.'); } }
      if (o.id === 'help') { inc(s, 'social', 5); L(s, '포스터를 붙이며 친구가 많이 생겼다.'); }
    } },
  { id: 'careerDay', w: s => (s.turnIdx <= 6 ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, a = topInterest(s), d = PARENT_DESIRES[s.p.pDesire].field;
      const others = FIELD_KEYS.filter(f => f !== a && f !== d);
      const x = r.pick(others);
      const fs = [a, d, x].filter((f, i, arr) => f && arr.indexOf(f) === i);
      const o = choose(ctx, key, '진로의 날',
        `진로의 날, 현직자 특강이 세 개 열린다. 하나만 들을 수 있다. 신청서를 낼 때 옆자리 친구가 묻는다. "너 진짜 하고 싶은 거 있어? 나는 아직도 모르겠어."`,
        fs.map(f => O(f, `${FIELDS[f].name} 현직자 특강`, f === a ? '내가 끌리는 분야를 확인' : f === d ? '부모님이 원하는 분야를 직접 보기' : '전혀 생각 안 해 본 분야', f === a ? ['self'] : f === d ? ['obey'] : ['risk'])));
      s.interest[o.id] += 12; s.flags.clarity = (s.flags.clarity || 0) + 1;
      L(s, `${FIELDS[o.id].name} 현직자의 하루를 들었다. ${fitOf(s, o.id) > 0.8 ? '"바로 이거다" 싶었다.' : '생각보다 현실적인 이야기가 많았다. 연봉, 야근, 경쟁률.'}`);
    } },
  { id: 'rank', w: s => (hasHobby(s, 'game') ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '랭크 상위 0.8%',
        `랭크게임 상위 0.8% 달성. 같이 듀오하는 형이 말한다. "너 손이 진짜 좋아. 프로 아카데미 테스트 받아 봐. 근데 하려면 지금부터 하루 10시간은 해야 돼." 성적은 반에서 중간쯤이다.`, [
        O('pro', '진지하게 프로를 꿈꾼다', '진짜 재능일지도 · 학업과 부모님과의 관계를 건다', ['risk', 'fun']),
        O('weekend', '주말에만 랭크를 돌리며 실력을 유지한다', '꿈을 남겨 둠 · 둘 다 어중간해질 수 있다', ['safe', 'fun']),
        O('quit', '계정을 지운다. 지금은 아니다', '공부에 집중 · 큰 낙이 사라진다', ['study']),
      ]);
      if (o.id === 'pro') { s.flags.proDream = true; s.talent.game = clamp(s.talent.game + 20, 0, 100); inc(s, 'lazy', 8); s.zC -= 0.05; inc(s, 'parentRel', -8); L(s, '하루 8시간씩 랭크를 돌렸다. 부모님과 매일 싸웠다.', 'warn'); }
      if (o.id === 'weekend') { s.talent.game += 6; inc(s, 'mental', 4); inc(s, 'lazy', 2); L(s, '주말에만 하기로 했다. 대체로는 지켰다.'); }
      if (o.id === 'quit') { inc(s, 'lazy', -12); inc(s, 'mental', -6); inc(s, 'social', -3); L(s, '계정을 지웠다. 한동안 허전했다.'); }
    } },
  { id: 'esports', w: s => (s.flags.proDream && s.talent.game >= 60 ? 2.5 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '프로팀 아카데미',
        `e스포츠 프로팀 아카데미 테스트에 붙었다. 코치가 말한다. "숙소 생활이고, 학교는 출석만 맞추면 돼. 2년 안에 1군 못 올라가면 그때 다시 생각하자." 계약서에 부모님 서명란이 있다.`, [
        O('go', '부모님을 설득해서 간다', '꿈에 도전 · 실패하면 2년 공백', ['risk']),
        O('later', '"수능 끝나고 다시 연락드려도 될까요?"', '대학을 지킴 · 기회는 다시 안 올 수도', ['safe']),
        O('no', '거절한다', '평범한 길 · 평생 궁금할 수 있다', ['safe', 'obey']),
      ]);
      if (o.id === 'go') { s.flags.esports = true; inc(s, 'parentRel', -15); s.zN -= 0.25; s.zC -= 0.2; L(s, '부모님은 끝까지 반대하다 서명했다. 다음 주에 숙소로 들어간다.', 'warn'); }
      else if (o.id === 'later') { if (r.chance(0.3)) s.flags.esportsLater = true; L(s, '"그때 자리가 있으면." 코치가 웃었다.'); }
      else L(s, '정중히 거절했다. 가끔 그 DM을 다시 열어 본다.');
    } },
  { id: 'casting', w: s => ((hasHobby(s, 'music') || hasHobby(s, 'idol')) && s.p.social >= 3 && s.turnIdx <= 6 ? 0.8 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '길거리 캐스팅',
        `홍대 앞에서 누군가 명함을 내민다. 중소 기획사 캐스팅 매니저다. "노래하는 영상 봤어요. 오디션 한번 볼래요? 붙으면 연습생 계약이고, 학교는 다니면서 해도 돼요." 검색해 보니 데뷔시킨 그룹은 두 팀, 둘 다 1년 안에 해체했다.`, [
        O('aud', '오디션을 본다', '꿈의 시작일 수도 · 공부와 시간을 건다', ['risk', 'fun']),
        O('check', '부모님과 함께 회사를 알아본 뒤 결정한다', '안전함 · 시간이 지나면 기회가 사라질 수 있다', ['safe', 'obey']),
        O('no', '명함을 버린다', '흔들림 없음 · 평생 궁금할 수 있다', ['safe']),
      ]);
      if (o.id === 'aud' || (o.id === 'check' && r.chance(0.5))) {
        if (r.chance(s.talent.perf / 130)) { s.flags.trainee = true; inc(s, 'parentRel', o.id === 'check' ? 0 : -6); s.zN -= 0.1; L(s, '연습생 계약 제안을 받았다. 심장이 터질 것 같다.', 'good'); }
        else { inc(s, 'mental', -6); s.talent.perf += 6; L(s, '"아직은 부족하네요." 노래 연습을 더 하고 싶어졌다.'); }
      } else L(s, '명함은 서랍 속에 들어갔다.');
    } },
  { id: 'youtube', w: s => (hasHobby(s, 'video') ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '알고리즘의 선택',
        `취미로 올린 공부 브이로그가 알고리즘을 탔다. 조회수 34만, 구독자 1.2만. 광고 제안 메일이 두 통 와 있다. 댓글: "언니(형) 다음 영상 언제 올라와요?" 편집에는 영상 하나당 6시간이 든다.`, [
        O('grow', '주 2회 업로드로 채널을 키운다', '새 진로의 가능성 · 공부 시간이 크게 준다', ['risk', 'fun']),
        O('bal', '주 1회, 방학엔 몰아서 올린다', '둘 다 유지 · 성장 속도는 느리다', ['safe']),
        O('stop', '수능 끝날 때까지 채널을 쉰다', '공부 집중 · 알고리즘은 기다려 주지 않는다', ['study']),
      ]);
      if (o.id === 'grow') { s.flags.creator = (s.flags.creator || 0) + 2; s.talent.media += 15; inc(s, 'lazy', 4); s.zN -= 0.06; s.money += 4; L(s, '편집하느라 새벽 3시에 잔다. 첫 광고 수익 37만 원이 들어왔다.'); }
      if (o.id === 'bal') { s.flags.creator = (s.flags.creator || 0) + 1; s.talent.media += 7; L(s, '공부와 채널 사이에서 줄타기 중이다.'); }
      if (o.id === 'stop') { inc(s, 'mental', -3); L(s, '"수능 끝나고 돌아올게요" 공지를 올렸다.'); }
    } },
  { id: 'coding', w: s => (hasHobby(s, 'code') ? 2 : s.interest.cs > 30 ? 0.6 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '청소년 해커톤',
        `청소년 해커톤 공고. 2박 3일, 기말 1주 전이다. 같이 나가자는 친구는 디자인을 하고, 나는 개발을 맡는다. 작년 수상팀 중 한 명은 이걸로 학종 카이스트에 붙었다는 소문이 있다.`, [
        O('join', '나간다', '진짜 실력과 이야기가 생김 · 기말 준비가 흔들린다', ['record', 'risk']),
        O('online', '온라인 코딩테스트 대회만 따로 나간다', '부담 적음 · 남는 이야기는 작다', ['safe', 'record']),
        O('skip', '시험이 먼저다', '내신 지킴 · 기회를 넘긴다', ['study']),
      ]);
      if (o.id === 'join') { s.talent.code += 12; s.recFit.cs += 12; s.record += 5; s.zN -= 0.03; s.interest.cs += 8; if (r.chance(0.2 + s.talent.code / 250)) { s.flags.award = (s.flags.award || 0) + 1; s.record += 6; L(s, '우수상! 개발자가 되고 싶다는 마음이 확실해졌다.', 'good'); } else L(s, '상은 못 탔지만 처음으로 서비스 하나를 끝까지 만들었다.'); }
      if (o.id === 'online') { s.talent.code += 5; s.recFit.cs += 4; L(s, '상위 15%에 들었다.'); }
    } },
  { id: 'artAcademy', w: s => (hasHobby(s, 'draw') || hasHobby(s, 'webtoon') ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '미대 입시',
        `미술 선생님이 그림을 한참 보시다 말씀하신다. "너 감각 있어. 지금 시작해도 늦지 않아." 입시미술 학원은 한 달 80만 원, 주 4일. 미대는 실기 비중이 크지만 내신·수능도 본다. 부모님은 "그림으로 먹고살 수 있겠니?"라고 물을 것이다.`, [
        O('yes', '미대 입시를 시작한다', '재능을 키울 기회 · 돈과 공부 시간, 부모님 설득', ['risk', 'self']),
        O('design', '실기 없는 디자인 관련 학과(학종)로 방향을 잡는다', '공부와 병행 가능 · 실기 실력은 늘지 않는다', ['safe', 'record']),
        O('hobby', '그림은 취미로 남긴다', '안정적 · 마음 한쪽이 아쉽다', ['safe']),
      ]);
      if (o.id === 'yes') { s.flags.artPath = true; s.money -= 10; s.talent.art += 15; s.interest.art += 15; s.zN -= 0.04; if (s.p.pDesire !== 'free') inc(s, 'parentRel', -6); L(s, '주 4일 입시미술 학원에 다닌다. 손에 늘 물감이 묻어 있다.'); }
      if (o.id === 'design') { s.interest.art += 8; s.recFit.art += 8; s.record += 3; L(s, '디자인 관련 탐구 활동을 생기부에 쌓기 시작했다.'); }
      if (o.id === 'hobby') L(s, '스케치북은 책상 서랍 깊숙이 들어갔다.');
    } },
  { id: 'sportsTeam', w: s => (hasHobby(s, 'sport') ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '체대 입시',
        `체육 선생님이 부르신다. "너 제자리멀리뛰기 학교 기록이야. 체대 입시 생각 있니? 실기 학원 다니면 승산 있어. 대신 부상 한 번이면 끝이야." 체대 실기 학원은 한 달 50만 원.`, [
        O('yes', '체대 입시를 준비한다', '좋아하는 걸로 대학을 · 부상 위험과 학원비', ['risk', 'self']),
        O('police', '경찰·소방 공무원을 목표로 체력만 관리한다', '현실적인 진로 · 대학 선택지는 그대로', ['safe']),
        O('no', '운동은 취미로', '공부 집중 · 재능을 묻어 둔다', ['safe']),
      ]);
      if (o.id === 'yes') { s.flags.sportPath = true; s.money -= 6; s.talent.sport += 15; s.interest.sport += 15; L(s, '방과 후엔 실기 학원. 몸은 힘든데 마음은 편하다.'); }
      if (o.id === 'police') { s.interest.law += 8; s.talent.sport += 6; L(s, '경찰행정학과를 검색해 봤다.'); }
    } },
  { id: 'injury', w: s => (s.flags.sportPath || hasHobby(s, 'sport') ? 0.8 : 0.2), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '발목',
        `체육 시간 농구를 하다 착지를 잘못했다. 정형외과 의사가 말한다. "인대가 부분 파열이에요. 6주는 깁스하고, 재활까지 3개월." 목발을 짚고 계단을 오르는 게 하루 중 가장 힘든 일이 됐다.`, [
        O('study', '움직일 수 없는 김에 앉아서 공부만 한다', '공부량이 늘어남 · 우울해질 수 있다', ['study']),
        O('rehab', '재활 치료를 꼬박꼬박 받는다', '몸이 제대로 회복됨 · 시간과 돈이 든다', ['rest', 'safe']),
        O('rush', '실기 때문에 재활을 서둘러 끝낸다', '빨리 복귀 · 재발 위험', ['risk']),
      ]);
      if (o.id === 'study') { s.zN += 0.04; s.zC += 0.03; inc(s, 'mental', -6); s.talent.sport -= 8; L(s, '깁스한 6주 동안 문제집 세 권을 끝냈다.'); }
      if (o.id === 'rehab') { s.money -= 4; inc(s, 'health', 4); L(s, '석 달 뒤, 다시 뛸 수 있게 됐다.', 'good'); }
      if (o.id === 'rush') { if (r.chance(0.4)) { s.talent.sport -= 20; inc(s, 'mental', -12); s.flags.reinjury = true; L(s, '재발했다. 의사가 "이제 무리하면 안 된다"고 했다.', 'bad'); } else L(s, '다행히 버텨 줬다.'); }
    } },
  { id: 'concert', w: s => (hasHobby(s, 'idol') ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '티켓팅 성공',
        `피켓팅 성공. 최애 그룹 콘서트, 그것도 앞에서 다섯 번째 줄. 그런데 공연 날이 6월 모평 전날이다. 중고 거래 앱에 올리면 프리미엄 붙여 40만 원은 받을 수 있다. 같이 가기로 한 친구는 벌써 응원봉을 샀다.`, [
        O('go', '간다. 이건 인생에 한 번이다', '평생 기억 · 다음 날 컨디션은 엉망', ['fun']),
        O('give', '친구에게 정가에 넘긴다', '친구는 행복 · 내 마음이 쓰리다', ['kind', 'study']),
        O('sell', '팔고 그 돈으로 인강 패스를 산다', '실속 · 덕질 친구가 실망한다', ['study']),
      ]);
      if (o.id === 'go') { inc(s, 'mental', 12); s.zC -= 0.03; L(s, '인생 최고의 밤이었다. 모평은... 그럭저럭.'); }
      if (o.id === 'give') { inc(s, 'mental', -4); inc(s, 'social', 5); L(s, '친구가 울면서 고맙다고 했다.'); }
      if (o.id === 'sell') { inc(s, 'mental', -7); s.money += 4; s.zC += 0.02; L(s, '공연 날 밤, 트위터로 후기만 봤다.'); }
    } },
  { id: 'transfer', w: s => (s.p.school !== 'general' && s.naesinRec.length && s.naesinRec[s.naesinRec.length - 1] > 45 && s.turnIdx <= 4 ? 2.5 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '내신 지옥',
        `이번 학기 내신이 반에서 끝에서 다섯 번째다. 여기서는 열심히 해도 4등급이다. 같은 반 친구 둘이 일반고로 전학 간다는 소문이 돈다. "일반고 가면 바로 1~2등급이래." 하지만 이 학교 생기부는 대학이 알아준다는 말도 있다.`, [
        O('go', '일반고로 전학한다', '내신이 크게 오름 · 친구도 환경도 처음부터', ['risk']),
        O('stay', '남는다. 학종에서는 여기가 유리하다', '좋은 환경과 생기부 · 내신은 계속 바닥', ['safe']),
        O('jungsi', '남되, 정시로 방향을 튼다', '수능에 집중 · 학교 활동 의미가 줄어든다', ['study', 'risk']),
      ]);
      if (o.id === 'go') { s.p = Object.assign({}, s.p, { school: 'general' }); s.zN += 0.55; inc(s, 'social', -12); inc(s, 'mental', -4); s.flags.transferred = true; L(s, '새 학교에서는 반 3등이었다. 대신 친구가 하나도 없다.'); }
      if (o.id === 'stay') L(s, '버티기로 했다.');
      if (o.id === 'jungsi') { s.flags.leanJungsi = true; s.zC += 0.04; L(s, '내신 시험 기간에도 수능 기출을 풀었다.'); }
    } },
  { id: 'partTime', w: s => (s.money < 35 && s.turnIdx <= 8 ? 1.5 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '주말 알바',
        `친구가 일하는 카페에서 주말 알바를 구한다. 토·일 6시간씩, 한 달이면 60만 원 정도. 사고 싶은 패딩도 있고, 엄마한테 용돈 달라는 말도 이제 하기 싫다. 그런데 주말은 밀린 공부를 몰아서 하는 시간이다.`, [
        O('take', '한다', '돈과 경험 · 주말 공부 시간이 사라진다', ['work']),
        O('short', '토요일 하루만 한다', '적당히 · 둘 다 애매할 수 있다', ['work', 'safe']),
        O('no', '안 한다', '공부 시간 유지 · 돈 문제는 그대로', ['study']),
      ]);
      if (o.id === 'take') { s.money += 10; s.flags.work = true; s.zN -= 0.03; L(s, '주말이 사라졌다. 통장에 돈이 쌓이는 건 좋다.'); }
      if (o.id === 'short') { s.money += 5; s.flags.work = true; s.zN -= 0.012; L(s, '토요일엔 카페, 일요일엔 독서실.'); }
    } },
  { id: 'teacher', w: () => 0.5, once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, ti = topInterest(s);
      const o = choose(ctx, key, '담임 선생님의 제안',
        `담임 선생님이 부르신다. "${FIELDS[ti].name} 쪽 간다고 했지? 이 주제로 탐구해서 세특에 넣어 보자. 대신 끝까지 해야 한다." 선생님이 주신 주제는 무난하지만, 나는 사실 다른 게 더 궁금하다.`, [
        O('follow', '선생님 주제로 한다', '안전하고 확실함 · 내 이야기는 아니다', ['obey', 'record']),
        O('own', '"제가 궁금한 걸로 바꿔도 될까요?"', '나만의 탐구 · 어려우면 흐지부지될 수 있다', ['self', 'record']),
        O('no', '"지금은 공부할 시간도 부족해요"', '시간 확보 · 선생님이 서운해하신다', ['study']),
      ]);
      if (o.id === 'follow') { s.record += 6; s.recFit[ti] += 6; L(s, '무난한 보고서가 나왔다.'); }
      if (o.id === 'own') { s.record += 3 + s.p.curiosity * 2; s.recFit[ti] += 9; s.interest[ti] += 4; L(s, s.p.curiosity >= 4 ? '선생님이 "이건 너만 쓸 수 있는 보고서다"라고 하셨다.' : '주제를 바꿨더니 생각보다 어려웠다.', s.p.curiosity >= 4 ? 'good' : 'info'); }
      if (o.id === 'no') { s.record -= 1; L(s, '"그래, 네 판단이니까." 선생님이 조금 서운해 보였다.'); }
    } },
  { id: 'interview', w: s => (examSeason(s) && s.applyType === 'jonghap' ? 6 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '면접이냐 수능이냐',
        `학종 1차 합격 발표. 면접이 수능 2주 전 토요일이다. 면접 학원은 "예상 질문 50개를 다 외워야 한다"고 하고, 학교 선생님은 "최저 못 맞추면 면접도 소용없다"고 한다. 하루가 24시간뿐이다.`, [
        O('interview', '면접 준비에 집중한다', '면접 합격률이 오름 · 수능 최저가 위험해진다', ['record']),
        O('csat', '면접은 생기부만 다시 읽고, 수능에 집중한다', '최저 안전 · 면접에서 말이 막힐 수 있다', ['study']),
        O('both', '낮엔 수능, 밤엔 면접 연습', '둘 다 챙김 · 체력이 버틸지 모른다', ['study', 'risk']),
      ]);
      if (o.id === 'interview') { s.flags.interviewPrep = 2; s.zC -= 0.04; L(s, '거울 앞에서 같은 대답을 스무 번 했다.'); }
      if (o.id === 'csat') { s.flags.interviewPrep = 0; s.zC += 0.02; L(s, '면접 대기실에서 생기부를 처음부터 다시 읽었다.'); }
      if (o.id === 'both') { s.flags.interviewPrep = 1; inc(s, 'health', -12); inc(s, 'stress', 8); L(s, '하루 4시간씩 잤다.', 'warn'); }
    } },
  { id: 'cold', w: s => (examSeason(s) ? 0.9 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '수능 3주 전, 감기',
        `수능 3주 전. 목이 따끔하더니 열이 38.5도까지 올랐다. 독감 검사는 음성. 의사는 "사흘은 푹 쉬세요"라고 한다. 반 친구들은 이번 주가 마지막 실전 모의고사 주간이다.`, [
        O('rest', '사흘 동안 푹 쉰다', '빨리 회복 · 마지막 실전 연습을 놓친다', ['rest']),
        O('push', '약 먹고 모의고사는 본다', '실전 감각 유지 · 감기가 길어질 수 있다', ['study']),
        O('light', '쉬면서 오답노트만 가볍게 본다', '균형 · 어느 쪽도 완벽하지 않다', ['safe']),
      ]);
      if (o.id === 'rest') { inc(s, 'health', 10); s.zC -= 0.01; L(s, '사흘을 잤다. 몸이 가벼워졌다.', 'good'); }
      if (o.id === 'push') { if (r.chance(0.45)) { inc(s, 'health', -18); L(s, '감기가 2주를 갔다. 수능 날까지 기침을 했다.', 'bad'); } else { s.zC += 0.02; L(s, '버텼다. 모의고사도 평소만큼 나왔다.'); } }
      if (o.id === 'light') { inc(s, 'health', 4); L(s, '오답노트를 두 번 넘겼다.'); }
    } },
  // ── 국어 ──────────────────────────────────────────
  { id: 'vocab', w: s => (s.turnIdx <= 6 ? 1.3 : 0.4), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '모르는 단어',
        `국어 모의고사 독서 지문. "이 이론은 시장의 자기 조정 기능을 상정(想定)한다." 상정? 그 문장에서 멈췄다. 다음 문단엔 '전제', '수반', '도외시'가 줄줄이 나온다. 아는 단어 같은데 정확한 뜻을 대라면 말을 못 하겠다. 채점해 보니 그 지문에서만 세 개를 틀렸다.`, [
        O('note', '지문에서 막힌 단어를 어휘 노트에 정리하고 매일 10개씩 본다', '독서 지문이 덜 막힌다 · 효과는 몇 달 뒤에 온다', ['study', 'self']),
        O('hanja', '한자어 어휘 교재를 한 권 끝낸다', '어휘력이 단단해진다 · 시간이 꽤 든다', ['study']),
        O('ask', '국어 선생님께 어휘 공부법을 물어본다', '방향을 잡는다 · 실천은 내 몫', ['self', 'kind']),
        O('skip', '문맥으로 대충 넘긴다. 다들 그렇게 한다', '시간 절약 · 같은 함정에 계속 빠진다', ['fun', 'safe']),
      ]);
      if (o.id === 'note') { s.korOff.read += 0.08; s.sub.kor += 0.05; s.flags.vocab = true; L(s, '어휘 노트가 두 권이 됐다. 지문 속 단어가 걸리지 않으니 읽는 속도가 붙었다.', 'good'); }
      if (o.id === 'hanja') { s.korOff.read += 0.1; s.sub.kor += 0.06; s.sub.inq += 0.02; s.flags.vocab = true; L(s, '한자어 교재를 끝냈다. 사회·과학 지문 속 개념어까지 쉽게 읽힌다.', 'good'); }
      if (o.id === 'ask') { s.korOff.read += 0.04; L(s, `"모르는 단어는 사전 뜻 말고 지문 속 뜻으로 적어." ${s.acad.kor === 'director' ? '원장님이 다음 수업부터 어휘 테스트를 넣었다.' : '선생님이 정리법을 알려 주셨다.'}`); if (s.acad.kor === 'director') s.korOff.read += 0.04; }
      if (o.id === 'skip') { s.korOff.read -= 0.06; L(s, '다음 모의고사에서도 비슷한 단어에서 걸렸다.', 'warn'); }
    } },
  { id: 'readHabit', w: s => (s.turnIdx <= 5 ? 1.1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '책 한 권',
        `국어 선생님이 말씀하셨다. "비문학 점수는 결국 평소에 얼마나 읽었느냐로 갈린다." 집에 와서 책을 펴 봤지만 세 쪽째에서 폰을 집었다. 유튜브에는 '책 10분 요약' 영상이 넘쳐난다.`, [
        O('book', '한 달에 두 권, 신문 칼럼 하루 하나를 읽는다', '긴 글을 버티는 힘이 생긴다 · 당장 점수는 안 오른다', ['study', 'self']),
        O('club', '독서 토론 동아리에 들어간다', '읽고 말하는 힘, 생기부 · 시간이 든다', ['record', 'social']),
        O('summary', '요약 영상으로 줄거리만 챙긴다', '시간이 거의 안 든다 · 읽는 힘은 그대로', ['fun']),
      ]);
      if (o.id === 'book') { s.korOff.read += 0.1; s.sub.kor += 0.04; s.talent.verbal += 6; L(s, '긴 글을 끝까지 읽는 게 덜 힘들어졌다.', 'good'); }
      if (o.id === 'club') { s.korOff.read += 0.06; s.record += 5; s.recFit.hum = (s.recFit.hum || 0) + 5; s.talent.verbal += 8; L(s, '토론 준비를 하며 같은 글을 세 번씩 읽었다.', 'good'); }
      if (o.id === 'summary') { s.korOff.read -= 0.04; L(s, '줄거리는 아는데, 긴 글은 여전히 버겁다.'); }
    } },
  { id: 'korTime', w: s => (s.turnIdx >= 2 ? 1.3 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, kg = korGrades(s);
      const o = choose(ctx, key, '국어 80분이 모자라다',
        `국어 모의고사. 독서 세트에서 25분을 쓰고 나니 문학 두 세트와 화법·언어·매체가 남았는데 시간은 20분뿐이다. 마지막 다섯 문제는 찍었다. 지금 국어는 ${korText(kg)}. 다음 시험부터 푸는 순서를 바꿔야 할 것 같다.`, [
        O('langFirst', '화법·언어·매체 → 문학 → 독서 순서로 푼다', '확실한 점수부터 챙긴다 · 독서에서 시간에 쫓긴다', ['safe', 'study']),
        O('timer', '세트별 제한 시간을 정하고 넘기면 과감히 넘어간다', '시간 관리가 몸에 붙는다 · 연습이 많이 필요하다', ['study', 'self']),
        O('consult', `${s.acad.kor !== 'none' ? '국어 학원 선생님께' : '담임 선생님께'} 시험지를 들고 가 상담한다`, '내 습관을 정확히 짚어 준다 · 고칠 건 내 몫', ['self', 'kind']),
        O('same', '순서는 그대로, 그냥 더 빨리 읽으려고 한다', '바꿀 필요 없음 · 다음에도 시간이 모자랄 수 있다', ['safe']),
      ]);
      if (o.id === 'langFirst') { s.korOff.lang += 0.05; s.sub.kor += 0.04; L(s, '화법·언어·매체를 15분 안에 끝내니 마음이 편해졌다.'); }
      if (o.id === 'timer') { s.sub.kor += s.p.diligence >= 3 ? 0.08 : 0.03; L(s, s.p.diligence >= 3 ? '두 달 연습하니 80분 안에 다 풀고 검토까지 했다.' : '타이머를 맞춰 놓고도 자꾸 시간을 넘겼다.', s.p.diligence >= 3 ? 'good' : 'warn'); }
      if (o.id === 'consult') { const dir = s.acad.kor === 'director'; s.sub.kor += dir ? 0.09 : s.acad.kor !== 'none' ? 0.06 : 0.04; L(s, dir ? '원장님이 시험지에 내 시선 순서를 표시해 가며 짚어 주셨다. "너는 1문단을 너무 꼼꼼히 읽어. 구조만 잡고 넘어가." 다음 시험에서 바로 효과가 났다.' : '선생님이 시간이 새는 곳을 짚어 주셨다.', 'good'); }
      if (o.id === 'same') { s.sub.kor -= 0.02; L(s, '다음 시험에서도 마지막 장을 찍었다.', 'warn'); }
    } },
  { id: 'korNaesin', w: s => (s.turnIdx <= 8 ? 1.2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, d = s.acad.kor === 'director';
      const o = choose(ctx, key, '국어 내신 서술형',
        `국어 내신 범위는 교과서 작품 12개와 선생님 프린트 30장. 작년 기출을 보니 서술형이 40%, "화자의 태도 변화를 두 문장으로 서술하시오" 같은 문제다. ${d ? '다니는 원장 직강 학원에서는 우리 학교 3년 치 기출을 분석한 자료를 나눠 줬다.' : ''}`, [
        O('understand', '작품마다 화자·시점·표현법을 직접 정리한다', '서술형에서 강하다 · 시간이 많이 든다', ['study', 'self']),
        O('memorize', '선생님 프린트를 통째로 외운다', '객관식은 확실 · 처음 보는 서술형에 약하다', ['study', 'safe']),
        d ? O('academy', '학원 학교별 기출 자료로 예상 문제를 반복한다', '우리 학교 출제 경향에 딱 맞다 · 학원에 의존하게 된다', ['study', 'obey']) : O('cram', '시험 3일 전에 몰아서 본다', '다른 과목 시간을 확보 · 범위가 넓어 다 못 본다', ['fun']),
      ]);
      if (o.id === 'understand') { s.korOff.lit += 0.08; s.zN += 0.05; L(s, '서술형 두 문제를 만점 받았다. 처음 보는 작품도 정리한 틀로 읽힌다.', 'good'); }
      if (o.id === 'memorize') { s.zN += 0.03; L(s, '객관식은 다 맞혔다. 서술형 하나는 교과서 밖 작품이 나와 부분 점수만 받았다.'); }
      if (o.id === 'academy') { s.zN += 0.07; s.korOff.lit += 0.03; L(s, '예상 문제와 비슷한 서술형이 두 개나 나왔다. 국어 내신 1등급 컷을 넘었다.', 'good'); }
      if (o.id === 'cram') { s.zN -= 0.05; L(s, '프린트 30장 중 절반도 못 봤다. 서술형 답안 칸을 반쯤 비웠다.', 'bad'); }
    } },
  { id: 'critique', w: s => (s.turnIdx <= 8 ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '수행평가 비평문',
        `국어 수행평가: 소설 한 편을 읽고 1,500자 비평문 쓰기. 세특에 그대로 들어간다. 반에서 몇 명은 AI로 초안을 뽑았다는 소문이 돈다. 담임 선생님은 "AI 문장은 다 티 난다"고 경고했다.`, [
        O('self', '직접 쓰고, 첨삭을 받아 두 번 고친다', '글쓰기 실력과 세특 · 밤을 두 번 새운다', ['study', 'record']),
        O('ai', 'AI 초안을 받아 말투만 바꿔 낸다', '시간이 거의 안 든다 · 걸리면 0점에 세특도 날아간다', ['fun', 'risk']),
        O('quick', '혼자 한 번에 쓰고 제출한다', '무난함 · 세특 문장이 평범해진다', ['safe']),
      ]);
      if (o.id === 'self') { const dir = s.acad.kor === 'director' || s.acad.kor === 'tutor'; s.record += dir ? 9 : 6; s.korOff.read += 0.03; s.korOff.lit += 0.03; s.talent.verbal += 6; L(s, dir ? '국어 학원 원장님이 빨간 펜으로 세 번 첨삭해 주셨다. 선생님이 "올해 최고의 비평문"이라며 세특에 길게 적어 주셨다.' : '친구와 서로 첨삭해 주며 두 번 고쳤다. 세특에 "논거가 탄탄하다"고 적혔다.', 'good'); }
      if (o.id === 'ai') { if (r.chance(0.45)) { s.record -= 10; s.flags.caught = true; inc(s, 'mental', -8); L(s, '표절·AI 검사에 걸렸다. 0점, 그리고 담임 상담. 세특 칸은 비게 됐다.', 'bad'); } else { s.record += 1; L(s, '무사히 넘어갔다. 세특에는 "성실히 제출함" 한 줄뿐이었다.', 'warn'); } }
      if (o.id === 'quick') { s.record += 3; L(s, '평범한 비평문이었다.'); }
    } },
  { id: 'classic', w: s => (s.turnIdx >= 2 && s.turnIdx <= 8 ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '고전시가',
        `"하늘 아래 떠 있는 구름이 ~" 현대어는 알겠는데, '님'이 임금인지 연인인지, '두어라'가 체념인지 다짐인지 매번 헷갈린다. 고전시가는 시험마다 한 세트씩 나온다. 친구는 "어차피 한 세트니까 버려"라고 한다.`, [
        O('word', '고전 어휘 200개를 외우고 작품 30개를 정리한다', '문학 한 세트를 확실히 지킨다 · 지루하고 오래 걸린다', ['study']),
        O('gichul', '평가원 기출에 나온 고전시가만 반복한다', '효율적이다 · 처음 보는 작품엔 약하다', ['study', 'safe']),
        O('drop', '고전시가는 버린다', '다른 데 시간을 쓴다 · 한 세트 3~4문제를 매번 잃는다', ['fun', 'risk']),
      ]);
      if (o.id === 'word') { s.korOff.lit += 0.1; s.sub.kor += 0.04; L(s, '고전시가 세트를 처음으로 다 맞혔다.', 'good'); }
      if (o.id === 'gichul') { s.korOff.lit += 0.06; s.sub.kor += 0.03; L(s, '기출 작품은 이제 눈에 익었다.'); }
      if (o.id === 'drop') { s.korOff.lit -= 0.12; s.sub.kor -= 0.05; s.flags.dropClassic = true; L(s, '고전시가 세트는 찍는다. 국어 1등급 컷에서 늘 3~4점이 모자라기 시작했다.', 'bad'); }
    } },
  { id: 'korPlateau', w: s => (s.turnIdx >= 4 && s.mockG.length >= 2 && s.mockG[s.mockG.length - 1].kor >= s.mockG[s.mockG.length - 2].kor ? 1.8 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, g = s.mockG[s.mockG.length - 1].kor;
      const o = choose(ctx, key, '국어는 해도 안 오른다',
        `국어 ${g}등급. 석 달째 그대로다. 수학은 한 만큼 오르는데 국어는 아무리 풀어도 제자리다. 반 친구들 사이에선 "국어는 타고나는 거야, 차라리 수학에 시간 써"라는 말이 돈다.`, [
        O('method', '공부법을 바꾼다. 문제 양 대신 지문 하나를 분석하는 데 시간을 쓴다', '근본적인 독해력이 오른다 · 한동안 점수가 안 보인다', ['study', 'self']),
        O('academy', s.acad.kor === 'director' ? '원장님께 상담을 받는다' : '국어 학원(원장 직강 소규모)에 상담을 받으러 간다', '정확한 진단과 처방 · 학원비가 든다', ['self', 'obey']),
        O('drop', '국어 시간을 줄이고 수학에 몰아준다', '수학이 오른다 · 국어는 더 떨어지고 영어·탐구 지문도 흔들린다', ['risk']),
      ]);
      if (o.id === 'method') { s.korFocus = 'gichul'; s.korOff.read += 0.06; s.sub.kor += s.p.diligence >= 3 ? 0.06 : 0.02; L(s, '평가원 기출 한 지문을 한 시간씩 뜯어봤다. 문단과 문단 사이의 관계가 보이기 시작했다.', 'good'); }
      if (o.id === 'academy') {
        if (s.acad.kor !== 'director') { s.acad.kor = 'director'; s.money -= 3; L(s, '원장님이 시험지 세 장을 보고 바로 말했다. "읽는 건 되는데, 선지를 지문에 대조하지 않고 기억으로 풀어." 그 학원에 등록했다.', 'good'); }
        else L(s, '원장님이 오답을 같이 뜯어보며 말했다. "너는 독서 3문단에서 늘 무너져. 거기만 잡자." 숙제가 바뀌었다.', 'good');
        s.korFocus = 'gichul'; s.sub.kor += 0.07; inc(s, 'stress', -4);
      }
      if (o.id === 'drop') { s.sub.kor -= 0.1; s.korOff.read -= 0.05; s.sub.math += 0.06; L(s, '수학은 조금 올랐다. 국어는 한 등급 더 내려갔고, 영어 장문에서도 시간이 모자라기 시작했다.', 'bad'); }
    } },
  { id: 'saseol', w: s => (s.turnIdx >= 6 ? 1.2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '사설 모의고사 vs 평가원 기출',
        `고3이 다가오자 반 친구들이 사설 모의고사를 주 3회씩 푼다. 시중 실전 모의고사 세트가 책상마다 쌓여 있다. 그런데 국어 선생님은 "평가원 기출을 세 번 본 사람이 사설 열 회 푼 사람보다 낫다"고 하신다.`, [
        O('gichul', '평가원 기출 5개년을 세 번씩 분석한다', '출제 원리가 보인다 · 실전 감각은 느리게 붙는다', ['study', 'self']),
        O('mock', '사설 모의고사를 주 3회 푼다', '실전 감각과 시간 관리 · 문제 질이 들쭉날쭉하다', ['study']),
        O('both', '평일엔 기출 분석, 주말엔 사설 1회', '균형 · 시간이 많이 든다', ['study', 'safe']),
      ]);
      s.korFocus = o.id === 'mock' ? 'mock' : 'gichul';
      if (o.id === 'gichul') { s.sub.kor += 0.06; L(s, '기출을 세 번째 볼 때, 평가원이 선지를 만드는 방식이 보였다.', 'good'); }
      if (o.id === 'mock') { s.sub.kor += 0.02; L(s, '푼 양은 많은데 틀리는 유형이 그대로다.', 'warn'); }
      if (o.id === 'both') { s.sub.kor += 0.05; inc(s, 'stress', 4); L(s, '주말마다 실전 연습까지 하니 시간 감각도 붙었다.', 'good'); }
    } },
  // ── 학원 ──────────────────────────────────────────
  { id: 'acadHomework', w: s => (SUB_KEYS.filter(k => s.acad[k] !== 'none' && s.acad[k] !== 'online').length >= 2 ? 1.4 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '학원 숙제 폭탄',
        `학원 두 곳의 숙제가 하루 네 시간 분량이다. 학교 수행평가까지 겹쳐 사흘째 새벽 2시에 잔다. ${acadText(s)}.`, [
        O('all', '다 한다. 학원비가 아깝다', '학원 효과를 다 뽑는다 · 체력이 바닥난다', ['study', 'obey']),
        O('choose', '약한 과목 숙제는 다 하고, 나머지는 핵심만 한다', '효율적 · 학원 선생님께 혼날 수 있다', ['self', 'study']),
        O('skip', '숙제를 안 하고 학원만 간다', '잠은 잔다 · 수업만 듣고 남는 게 없다', ['fun']),
      ]);
      if (o.id === 'all') { s.zC += 0.04; inc(s, 'health', -10); inc(s, 'stress', 8); L(s, '숙제는 다 했다. 대신 오후 수업 시간에 졸았다.'); }
      if (o.id === 'choose') { s.zC += 0.03; L(s, '선생님은 "다음엔 다 해 와"라고만 했다. 약한 과목은 확실히 올랐다.', 'good'); }
      if (o.id === 'skip') { s.zC -= 0.03; inc(s, 'lazy', 4); L(s, '학원에 앉아 있었지만 머리에 남은 건 없었다.', 'bad'); }
    } },
  { id: 'directorCall', w: s => (s.acad.kor === 'director' && s.mockG.length >= 1 ? 2.2 : SUB_KEYS.some(k => s.acad[k] === 'director') ? 1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, sub = SUB_KEYS.find(k => s.acad[k] === 'director') || 'kor';
      const o = choose(ctx, key, '원장님 면담',
        `수업이 끝나고 ${SUBJ_NAME[sub]} 학원 원장님이 따로 부르셨다. "요즘 표정이 안 좋다. 숙제도 반만 해 오고. 무슨 일 있니?" 소규모 학원이라 원장님은 반 아이들 사정을 다 안다.`, [
        O('open', '요즘 힘든 이야기를 솔직하게 털어놓는다', '마음이 가벼워지고 계획을 다시 잡는다 · 자존심이 조금 상한다', ['self', 'kind']),
        O('plan', '"괜찮아요" 하고 공부 계획만 같이 짠다', '학습 방향을 잡는다 · 속마음은 그대로', ['study', 'safe']),
        O('nothing', '"아무 일 없어요" 하고 나온다', '그대로 · 원장님이 부모님께 연락할 수도 있다', ['rebel']),
      ]);
      if (o.id === 'open') { inc(s, 'mental', 10); inc(s, 'stress', -10); inc(s, 'lazy', -6); s.sub[sub] += 0.05; L(s, '원장님은 한참 듣고 나서 숙제 양을 조정해 주셨다. "성적은 내가 책임질 테니 잠은 자라."', 'good'); }
      if (o.id === 'plan') { s.sub[sub] += 0.06; inc(s, 'lazy', -4); L(s, '원장님이 4주짜리 계획표를 같이 짜 주셨다.', 'good'); }
      if (o.id === 'nothing') { if (s.p.pStyle === 'strict' || s.p.pStyle === 'anxious') { inc(s, 'parentRel', -4); L(s, '그날 밤 엄마에게 원장님 전화가 왔다.', 'warn'); } else L(s, '원장님은 더 묻지 않으셨다.'); }
    } },
  { id: 'tutorChange', w: s => (SUB_KEYS.some(k => s.acad[k] === 'tutor') ? 1.6 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, sub = SUB_KEYS.find(k => s.acad[k] === 'tutor');
      const good = (s.tutorQ[sub] || 0) >= 0;
      const o = choose(ctx, key, '과외 선생님',
        `${SUBJ_NAME[sub]} 과외 석 달째. ${good ? '선생님은 꼼꼼하지만 진도가 느리다.' : '대학생 선생님은 친절한데, 수업의 절반이 잡담이다. 성적은 그대로다.'} 한 달에 60만 원이 나간다.`, [
        O('keep', '그대로 계속한다', '익숙함 · 효과는 지금 그대로', ['safe']),
        O('change', '경력 많은 전문 과외 선생님으로 바꾼다', '수업 질이 오를 수 있다 · 비용이 더 든다', ['study', 'risk']),
        O('academy', '과외를 끊고 원장 직강 소규모 학원으로 옮긴다', '비용은 줄고 관리는 된다 · 1:1만큼 맞춤은 아니다', ['safe', 'study']),
      ]);
      if (o.id === 'change') { s.tutorQ[sub] = Math.max(s.tutorQ[sub], 0) + 0.05; s.money -= 4; L(s, '새 선생님은 첫 수업에 내 약점 세 가지를 정확히 짚었다.', 'good'); }
      if (o.id === 'academy') { s.acad[sub] = 'director'; L(s, `${SUBJ_NAME[sub]}${jo(SUBJ_NAME[sub], '은/는')} 원장 직강 소규모 학원으로 옮겼다. 원장님이 레벨테스트 결과를 보고 반을 정해 주셨다.`); }
      if (o.id === 'keep') L(s, '그대로 다니기로 했다.');
    } },

  // ── 탈선과 위기 ───────────────────────────────────
  { id: 'gamble', w: s => ((s.friendGroup === 'party' || s.friendGroup === 'gamers' ? 1.7 : 0.55) + (s.p.impulse - 3) * 0.2) * expo(s), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, b = s.bestFriend ? s.bestName : '같은 반 애';
      const o = choose(ctx, key, '단톡방에 뜬 링크',
        `${b}${jo(b, '이/가')} 단톡방에 링크를 올렸다. "이거 사다리 게임인데 어제 5만 원 넣고 30만 원 땄음 ㅋㅋ 가입하면 첫 충전 2배." 화면엔 1분마다 결과가 뜬다. 반에서 벌써 여섯 명이 한다고 한다. 누구는 "이걸로 에어팟 샀다"고 했다.`, [
        O('try', '만 원만 넣어 본다', '재미 반 호기심 반 · 따면 멈추기 어렵다', ['fun', 'risk']),
        O('no', '"난 안 해" 하고 링크를 안 누른다', '아무 일 없음 · 분위기에 못 낀다', ['safe', 'self']),
        O('tell', '불법 도박 사이트라고 담임께 알린다', '친구들을 막을 수도 · "고자질"로 찍힌다', ['kind', 'self']),
      ]);
      if (o.id === 'try') { s.flags.gambling = 1; if (r.chance(0.6)) { inc(s, 'mental', 4); inc(s, 'lazy', 5); L(s, '만 원이 7만 원이 됐다. 심장이 뛰었다. 그날 밤 세 번 더 들어갔다.', 'warn'); } else { inc(s, 'mental', -3); L(s, '만 원이 3분 만에 사라졌다. "본전은 찾아야지"라는 생각이 들었다.', 'warn'); } }
      if (o.id === 'no') { inc(s, 'social', -2); L(s, '링크를 누르지 않았다. 다음 날 쉬는 시간, 걔들끼리 모여 폰을 본다.'); }
      if (o.id === 'tell') { inc(s, 'social', -9); inc(s, 'mental', 2); s.record += 1; L(s, '학교에 교육이 들어왔고 몇 명은 상담을 받았다. 단톡방에서 나는 조용히 강퇴됐다.'); }
    } },
  { id: 'gambleDebt', w: s => (s.flags.gambling ? 4 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, pw = parentWord(s);
      const o = choose(ctx, key, '50만 원',
        `두 달 만에 용돈과 세뱃돈이 다 들어갔고, 사이트 "대리 충전"으로 50만 원 빚이 생겼다. 단톡방 아는 형이 "이자 하루 1만 원"이라고 했다. 밤에 잠이 안 온다.`, [
        O('confess', `${pw}께 전부 털어놓는다`, '빚은 끝난다 · 신뢰가 바닥까지 떨어진다', ['self', 'kind']),
        O('borrow', '친구들에게 조금씩 빌려 막는다', '당장은 넘어감 · 빚이 사람 관계로 번진다', ['risk', 'social']),
        O('bet', '한 번 크게 걸어 만회한다', '운 좋으면 끝 · 대부분 빚이 네 배가 된다', ['fun', 'risk']),
        O('sell', '물건을 팔거나… 돈 될 걸 찾는다', '빚은 갚는다 · 선을 넘기 직전', ['rebel', 'risk']),
      ]);
      if (o.id === 'confess') { s.flags.gambling = 0; s.money -= 6; inc(s, 'parentRel', -14); inc(s, 'mental', 6); L(s, `${pw}${jo(pw, '이/가')} 말없이 계좌이체를 했다. 그날 밤 거실에서 우는 소리가 들렸다. 사이트는 그날로 지웠다.`, 'warn'); }
      if (o.id === 'borrow') { s.flags.gambling = 2; s.flags.owedFavor = true; inc(s, 'social', -6); L(s, '친구 다섯 명에게 5만 원씩 빌렸다. "이번 달에 꼭 갚을게." 못 갚았다.', 'bad'); }
      if (o.id === 'bet') { if (r.chance(0.2)) { s.flags.gambling = 1; inc(s, 'mental', 6); inc(s, 'lazy', 8); L(s, '땄다. 빚을 갚고도 20만 원이 남았다. 그래서 더 위험해졌다 — 멈출 이유가 사라졌다.', 'warn'); } else { s.flags.gambleSpiral = true; inc(s, 'mental', -12); inc(s, 'lazy', 10); s.zC -= 0.08; L(s, '빚이 200만 원이 됐다. 수업 시간에도 결과창만 새로고침한다.', 'bad'); } }
      if (o.id === 'sell') { s.flags.theftPlan = true; inc(s, 'mental', -6); L(s, '에어팟과 패딩을 중고로 팔았다. 아직 모자란다.', 'bad'); }
    } },
  { id: 'gambleSpiral', w: s => (s.flags.gambleSpiral ? 4 : s.flags.gambling === 2 ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, pw = parentWord(s);
      const o = choose(ctx, key, '독촉',
        `모르는 번호로 하루 열 통씩 전화가 온다. "학교로 찾아간다." 집 앞에 낯선 성인이 서 있던 날, 결국 일이 커졌다. 학교에 알려졌고 선도위원회가 열린다.`, [
        O('parent', `${pw}과 함께 경찰에 신고하고 해결한다`, '사채는 불법이라 갚지 않아도 된다 · 집이 뒤집힌다', ['self', 'kind']),
        O('run', '집을 나간다', '마주하지 않음 · 모든 게 더 나빠진다', ['rebel', 'risk']),
      ]);
      s.flags.discipline = true; s.record = Math.max(0, s.record - 6); s.zN -= 0.1; s.flags.gambling = 0; s.flags.gambleSpiral = false;
      if (o.id === 'parent') { inc(s, 'parentRel', -18); inc(s, 'mental', -8); L(s, '경찰에 신고했고 사이트 운영자는 잡혔다. 선도위원회에서 교내봉사 10시간. 부모님은 한 달 동안 나를 똑바로 보지 않았다.', 'bad'); }
      if (o.id === 'run') { s.flags.runaway = true; inc(s, 'parentRel', -25); inc(s, 'mental', -15); s.zC -= 0.1; inc(s, 'lazy', 10); L(s, '친구 집, PC방, 찜질방을 전전했다. 열흘 만에 경찰이 찾아 데려왔다.', 'bad'); }
    } },
  { id: 'theft', w: s => (s.flags.theftPlan ? 5 : (s.friendGroup === 'party' ? 0.45 : 0.15)) * expo(s), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '무인 매장',
        `${s.flags.theftPlan ? '빚 때문에 머리가 멍하다. ' : ''}밤 11시, 무인 아이스크림 가게. 친구가 과자 두 봉지를 가방에 넣으며 웃는다. "CCTV 고장 났대. 다들 그냥 가져가." 계산대 옆엔 '절도는 범죄입니다' 스티커가 붙어 있다.`, [
        O('do', '나도 몇 개 넣는다', '별것 아닌 것 같다 · 걸리면 경찰·학교·부모님', ['rebel', 'risk']),
        O('no', '내 건 계산한다', '아무 일 없음 · 친구가 "쫄보"라고 한다', ['safe', 'self']),
        O('watch', '말리지도 끼지도 않는다', '중간 · CCTV에는 같이 찍힌다', ['safe']),
      ]);
      if (o.id === 'do') { if (r.chance(0.55)) { s.flags.discipline = true; inc(s, 'parentRel', -20); inc(s, 'mental', -12); inc(s, 'social', -8); s.record = Math.max(0, s.record - 5); L(s, 'CCTV는 고장 나지 않았다. 사장이 학교로 연락했고, 경찰서에서 부모님이 데리러 왔다. 교내봉사 처분. 초범이라 기록은 남지 않았지만, 부모님 눈빛은 남았다.', 'bad'); } else { inc(s, 'mental', -5); inc(s, 'lazy', 3); s.flags.theftPlan = false; L(s, '걸리지 않았다. 과자는 맛이 없었다.', 'warn'); } }
      if (o.id === 'no') { inc(s, 'social', -3); s.flags.theftPlan = false; L(s, '내 것만 계산했다. 다음 날 친구들은 아무 일 없었다는 듯 웃었다.'); }
      if (o.id === 'watch') { if (r.chance(0.2)) { inc(s, 'parentRel', -8); inc(s, 'mental', -6); L(s, '같이 찍힌 CCTV 때문에 학교에 불려 갔다. 안 가져갔다는 걸 증명하는 데 일주일이 걸렸다.', 'bad'); } else L(s, '그 자리에 있었다는 게 찝찝했다.'); }
    } },
  { id: 'pcAddict', w: s => ((hasHobby(s, 'game') && s.lazy >= 42 ? 2.4 : s.lazy >= 58 ? 1.2 : 0)) * expo(s), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '새벽 4시, PC방',
        `이번 주만 세 번째 밤샘이다. 1교시는 엎드려 자고, 지각이 벌써 일곱 번. 담임 선생님이 "미인정 지각이 더 쌓이면 출결에 남는다"고 했다. 게임을 끄면 손이 허전하고, 켜면 시간이 사라진다.`, [
        O('quit', '계정을 지우고 PC방 출입을 끊는다', '가장 확실함 · 처음 2주가 지옥', ['study', 'self']),
        O('weekend', '주말에만 하기로 정한다', '현실적인 타협 · 지키기가 쉽지 않다', ['safe']),
        O('go', '어차피 공부는 글렀다. 계속한다', '지금은 편함 · 출결·성적이 무너진다', ['fun']),
      ]);
      if (o.id === 'quit') { inc(s, 'lazy', -14); inc(s, 'mental', -4); inc(s, 'health', 6); L(s, '첫 주는 손이 떨렸다. 셋째 주부터 아침에 눈이 떠졌다.', 'good'); }
      if (o.id === 'weekend') { if (r.chance(0.5 + (s.p.diligence - 3) * 0.12)) { inc(s, 'lazy', -5); L(s, '주말 규칙을 지켰다. 평일 밤이 길어졌다.'); } else { inc(s, 'lazy', 5); s.zC -= 0.03; L(s, '"오늘만"이 매일이 됐다.', 'warn'); } }
      if (o.id === 'go') { inc(s, 'lazy', 12); s.zC -= 0.08; s.zN -= 0.08; s.flags.lateHabit = true; inc(s, 'health', -8); L(s, '미인정 지각 15회, 결석 3회가 생기부 출결에 남았다. 교과 전형에서 출결 감점을 받는 대학이 많다.', 'bad'); }
    } },
  { id: 'gameSpend', w: s => (hasHobby(s, 'game') && s.p.impulse >= 3 ? 1.1 : 0.3), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, pw = parentWord(s);
      const o = choose(ctx, key, '결제 문자',
        `${pw} 폰에 "결제 완료 59,000원"이 떴다. 이번 달에 여섯 번째. 게임 뽑기에 쓴 돈이 모두 합쳐 60만 원이 넘는다. ${pw}${jo(pw, '이/가')} 카드 명세서를 들고 방문을 열었다.`, [
        O('confess', '사실대로 말하고 갚겠다고 한다', '신뢰는 지킨다 · 폰을 뺏길 수 있다', ['self', 'kind']),
        O('lie', '"해킹당한 것 같다"고 한다', '오늘은 넘어감 · 들키면 거짓말까지 더해진다', ['fun', 'risk']),
      ]);
      if (o.id === 'confess') { inc(s, 'parentRel', -8); s.money -= 6; inc(s, 'lazy', -4); L(s, '석 달 동안 용돈이 끊겼다. 뽑기는 그 뒤로 안 했다.'); }
      if (o.id === 'lie') { if (r.chance(0.55)) { inc(s, 'parentRel', -18); s.flags.liar = true; inc(s, 'mental', -6); L(s, `카드사에 확인한 ${pw}${jo(pw, '이/가')} 결제 기기 정보를 보여 줬다. 내 폰이었다.`, 'bad'); } else { inc(s, 'mental', -3); L(s, '넘어갔다. 카드는 정지됐고, 거짓말이 하나 쌓였다.', 'warn'); } }
    } },
  { id: 'smoke', w: s => (s.friendGroup === 'party' ? 1.5 : 0.4) * expo(s), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '학교 뒤 골목',
        `점심시간, 학교 뒤 골목. 친구가 전자담배를 내민다. "이거 냄새 안 나. 선생님도 몰라." 멀리서 학생부 선생님이 순찰을 도는 게 보인다.`, [
        O('yes', '한 모금 빤다', '어울림 · 걸리면 선도 조치, 습관이 되면 끊기 어렵다', ['fun', 'social', 'risk']),
        O('no', '"난 됐어" 하고 교실로 간다', '아무 일 없음 · 그 무리에서 조금 멀어진다', ['safe', 'self']),
      ]);
      if (o.id === 'yes') { inc(s, 'health', -4); inc(s, 'lazy', 3); if (r.chance(0.3)) { s.flags.discipline = true; s.record = Math.max(0, s.record - 4); inc(s, 'parentRel', -10); L(s, '학생부에 적발됐다. 금연 교육 8시간, 부모님 호출. 생기부 행동특성란에 한 줄이 들어갈 뻔했다.', 'bad'); } else { s.flags.smoker = true; L(s, '안 걸렸다. 그 뒤로 점심시간마다 골목에 간다.', 'warn'); } }
      if (o.id === 'no') { inc(s, 'social', -3); L(s, '교실로 돌아왔다. 그 애들과는 조금 멀어졌다.'); }
    } },
  { id: 'runaway', w: s => (s.parentRel < 32 && s.turnIdx <= 8 && !s.flags.runaway ? 2.6 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, pw = parentWord(s);
      const o = choose(ctx, key, '현관문',
        `${pw}${jo(pw, '와/과')} 또 싸웠다. "너 같은 애 키우려고 내가…"에서 뭔가 끊어졌다. 밤 11시, 패딩을 집어 들고 현관문을 나왔다. 폰 배터리 40%. 갈 데가 없다.`, [
        O('friend', s.bestFriend ? `${s.bestName}네 집에서 이틀 지낸다` : '친구 집에서 이틀 지낸다', '숨을 돌린다 · 돌아가면 더 큰 싸움', ['rebel', 'social']),
        O('walk', '밤새 걷다가 새벽에 들어간다', '아무도 모른다 · 아무것도 해결되지 않는다', ['safe']),
        O('leave', '진짜 나간다. 알바하며 혼자 산다', '독립 · 학교와 입시가 통째로 흔들린다', ['rebel', 'risk']),
      ]);
      if (o.id === 'friend') { s.flags.runaway = true; s.zN -= 0.05; inc(s, 'mental', -4); if (s.p.pStyle === 'warm' || s.p.pStyle === 'anxious' || r.chance(0.4)) { inc(s, 'parentRel', 8); L(s, `이틀 뒤 ${pw}${jo(pw, '이/가')} 친구 집 앞에 와 있었다. 아무 말 없이 같이 걸어 돌아왔다. 그날 처음으로 길게 이야기했다.`); } else { inc(s, 'parentRel', -8); L(s, '돌아간 집은 더 차가웠다. "나갈 거면 아예 나가라"는 말을 들었다.', 'bad'); } }
      if (o.id === 'walk') { inc(s, 'mental', -6); inc(s, 'health', -4); L(s, '편의점 앞 벤치에서 해 뜨는 걸 봤다. 집에 들어가니 아무도 깨어 있지 않았다.', 'warn'); }
      if (o.id === 'leave') { s.flags.runaway = true; s.flags.work = true; inc(s, 'parentRel', -25); s.zN -= 0.2; s.zC -= 0.12; inc(s, 'lazy', 8); s.money += 10; inc(s, 'mental', -10); L(s, '고시원 월세 35만 원, 편의점 야간 알바. 학교는 가다 말다 했다.', 'bad'); }
    } },
  { id: 'brawl', w: s => ((s.friendGroup === 'party' ? 1.3 : 0.5) + (s.p.impulse - 3) * 0.25) * expo(s), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '급식실 앞',
        `급식 줄에서 옆 반 애가 어깨를 치고 지나갔다. "뭘 봐?" 주변에서 "오오" 소리가 난다. 걔가 먼저 밀었다. 학폭 조치는 생기부에 기재되고, 학종은 물론 2026학년도부터는 정시에서도 반영된다는 걸 머리로는 안다.`, [
        O('punch', '주먹이 먼저 나간다', '속은 시원함 · 학폭위, 생기부 기재', ['rebel', 'risk']),
        O('words', '밀치지 않고 말로 받아친다', '선을 안 넘음 · 쌍방으로 신고당할 수도', ['safe', 'self']),
        O('leave', '자리를 뜬다', '아무 일 없음 · "쫄았다"는 말이 돈다', ['safe']),
      ]);
      if (o.id === 'punch') { const heavy = r.chance(0.6); s.flags.violence = heavy ? 2 : 1; s.record = Math.max(0, s.record - (heavy ? 12 : 6)); inc(s, 'parentRel', -14); inc(s, 'mental', -8); inc(s, 'social', heavy ? -6 : 2); L(s, heavy ? '상대가 코뼈에 금이 갔다. 학폭위에서 출석정지 5일(6호). 생기부에 기재됐다. 학종은 사실상 닫혔고 교과·정시도 감점이다. 치료비 180만 원.' : '학폭위에서 서면사과(1호) 처분. 졸업과 동시에 삭제되는 조치지만, 담임의 눈빛이 달라졌다.', 'bad'); }
      if (o.id === 'words') { if (r.chance(0.3)) { s.flags.violence = 1; s.record = Math.max(0, s.record - 4); inc(s, 'mental', -6); L(s, '걔 부모가 "언어폭력"으로 신고했다. 쌍방 학폭위. 서면사과 처분을 받았다. 억울했다.', 'bad'); } else { inc(s, 'mental', 2); L(s, '"너 지금 밀었다. 선생님 부른다." 걔가 먼저 물러섰다.'); } }
      if (o.id === 'leave') { inc(s, 'social', -4); inc(s, 'mental', -3); L(s, '자리를 떴다. 며칠 동안 "쫄보"라는 말이 들렸다. 일주일 뒤엔 아무도 기억하지 않았다.'); }
    } },
  { id: 'bullyWitness', w: s => (s.turnIdx <= 8 ? 1.0 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '뒷자리의 일',
        `반에서 조용한 애 하나가 표적이 됐다. 체육복이 변기에 들어가 있었고, 단톡방엔 그 애 사진으로 만든 짤이 돈다. 다들 웃는다. 그 애는 요즘 급식을 안 먹는다.`, [
        O('report', '담임·117에 알린다', '멈출 수 있다 · "고자질"로 찍히고 보복이 있을 수도', ['kind', 'self']),
        O('side', '그 애 옆에 가서 같이 밥을 먹는다', '한 사람이 생긴다 · 나도 표적이 될 수 있다', ['kind', 'social']),
        O('ignore', '모른 척한다', '안전함 · 밤에 떠오른다', ['safe']),
        O('laugh', '분위기 맞춰 같이 웃는다', '무리에 낀다 · 가해자로 지목될 수 있다', ['fun', 'social']),
      ]);
      if (o.id === 'report') { inc(s, 'mental', 5); s.record += 3; if (r.chance(0.3)) { inc(s, 'social', -10); inc(s, 'mental', -8); L(s, '신고한 게 알려졌다. 한동안 내 책상에도 낙서가 생겼다.', 'bad'); } else { inc(s, 'social', -3); L(s, '학폭위가 열렸고 가해자들은 분리됐다. 그 애가 복도에서 작게 "고마워"라고 했다.', 'good'); } }
      if (o.id === 'side') { inc(s, 'mental', 6); if (r.chance(0.25)) { inc(s, 'social', -8); L(s, '나도 표적이 됐다. 그래도 둘이라서 버틸 만했다.', 'warn'); } else { inc(s, 'social', 3); s.flags.friendForever = true; L(s, '그 애와 지금도 연락한다.', 'good'); } }
      if (o.id === 'ignore') { inc(s, 'mental', -5); L(s, '모른 척했다. 그 애는 학기 중에 전학 갔다.', 'warn'); }
      if (o.id === 'laugh') { inc(s, 'social', 3); if (r.chance(0.25)) { s.flags.violence = 1; s.record = Math.max(0, s.record - 6); inc(s, 'parentRel', -10); inc(s, 'mental', -8); L(s, '피해 학생 진술서에 내 이름이 있었다. "같이 웃었다." 학폭위에서 서면사과 처분. 생기부에 남았다.', 'bad'); } else L(s, '웃었다. 그 애 얼굴이 가끔 떠오른다.', 'warn'); }
    } },
  { id: 'snsBully', w: s => (s.p.social >= 3 ? 0.7 : 0.4), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '저격 글',
        `익명 커뮤니티에 내 얘기가 올라왔다. 이름은 없지만 다 알 수 있는 내용. 댓글 40개. "걔 원래 그래." 누가 썼는지 짐작은 간다.`, [
        O('capture', '캡처해 두고 담임·학폭 신고', '사이버폭력도 학폭이다 · 시간이 걸린다', ['self']),
        O('confront', '쓴 애한테 직접 간다', '속은 시원함 · 싸움으로 번질 수 있다', ['rebel', 'risk']),
        O('ignore', '무시한다', '시간이 지나면 묻힌다 · 밤마다 새로고침하게 된다', ['safe']),
      ]);
      if (o.id === 'capture') { if (r.chance(0.6)) { inc(s, 'mental', 6); L(s, '게시글은 삭제됐고 쓴 학생은 서면사과했다.', 'good'); } else { inc(s, 'mental', -4); L(s, '"특정이 어렵다"고 했다. 글은 그대로 남았다.', 'warn'); } }
      if (o.id === 'confront') { if (r.chance(0.35)) { s.flags.violence = 1; s.record = Math.max(0, s.record - 4); inc(s, 'mental', -8); L(s, '복도에서 멱살을 잡았다. 쌍방 학폭위. 서면사과 처분을 받았다.', 'bad'); } else { inc(s, 'mental', 3); inc(s, 'social', 2); L(s, '"네가 썼지." 걔가 글을 지웠다.'); } }
      if (o.id === 'ignore') { inc(s, 'mental', -7); inc(s, 'lazy', 3); L(s, '무시했다. 그래도 매일 밤 댓글을 확인했다.', 'warn'); }
    } },
  { id: 'teacherClash', w: s => (s.p.impulse >= 3 ? 1.0 : 0.4), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '압수된 폰',
        `수업 중 폰을 보다 걸렸다. 선생님이 폰을 가져가며 "종례 때 찾아가"라고 했다. 반 애들이 다 보고 있다. 억울한 건, 옆자리 애는 아까부터 보고 있었다는 거다.`, [
        O('sorry', '"죄송합니다" 하고 넘어간다', '끝 · 억울함은 남는다', ['safe', 'obey']),
        O('argue', '"왜 저만요?" 하고 따진다', '할 말은 함 · 벌점, 행동특성란이 달라진다', ['rebel']),
        O('later', '종례 뒤 따로 가서 차분히 말한다', '어른스럽다 · 당장은 참아야 한다', ['self', 'kind']),
      ]);
      if (o.id === 'sorry') L(s, '종례 때 폰을 돌려받았다. 옆자리 애는 끝까지 안 걸렸다.');
      if (o.id === 'argue') { s.record = Math.max(0, s.record - 5); inc(s, 'mental', -3); s.flags.teacherBad = true; L(s, '"지금 선생님한테 대드는 거니?" 벌점 5점. 그 선생님이 담임이었다. 행동특성란에 "교사와의 관계에서 다소 감정적" 한 줄이 들어갔다.', 'bad'); }
      if (o.id === 'later') { s.record += 2; inc(s, 'mental', 2); L(s, '종례 뒤 교무실. "선생님, 아까 저만 걸린 건 억울했어요. 그래도 제가 본 건 맞아요." 선생님이 웃었다.', 'good'); }
    } },
  { id: 'lateHabit', w: s => (s.lazy >= 50 && !s.flags.lateHabit ? 1.4 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '지각 9회',
        `담임 선생님이 출결 화면을 보여 줬다. 미인정 지각 9회, 조퇴 2회. "10회 넘으면 교과 전형 출결 감점이고, 학종 서류에서도 성실성으로 읽혀. 이번 학기 안에 끊어."`, [
        O('fix', '알람 세 개, 밤 12시 취침을 지킨다', '습관을 바꾼다 · 처음 2주가 힘들다', ['study', 'self']),
        O('same', '어차피 아침잠은 못 이긴다', '편함 · 출결이 생기부에 남는다', ['fun']),
      ]);
      if (o.id === 'fix') { inc(s, 'lazy', -8); inc(s, 'health', 4); L(s, '첫 주는 지각 1회. 둘째 주부터 0회.', 'good'); }
      if (o.id === 'same') { s.flags.lateHabit = true; s.zN -= 0.05; s.record = Math.max(0, s.record - 4); L(s, '학기 말 미인정 지각 17회. 생기부 출결란에 그대로 찍혔다.', 'bad'); }
    } },
  { id: 'motorbike', w: s => (s.money < 25 && s.turnIdx >= 3 && s.turnIdx <= 8 ? 1.2 : 0.2), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '배달 알바 제안',
        `동네 형이 "배달 알바 할래? 하루 4시간에 6만 원"이라고 한다. 오토바이는 빌려준단다. 면허는 원동기 면허가 있으면 된다고. 편의점 알바는 시급 1만 원이다.`, [
        O('bike', '배달을 한다', '돈이 빨리 모인다 · 사고 위험, 밤이 짧아진다', ['work', 'risk']),
        O('store', '편의점 알바를 한다', '안전함 · 시간당 돈은 적다', ['work', 'safe']),
        O('no', '지금은 공부에 집중한다', '시간을 지킴 · 용돈이 늘 모자라다', ['study']),
      ]);
      if (o.id === 'bike') { s.money += 18; s.flags.work = true; s.zC -= 0.04; inc(s, 'health', -4); if (r.chance(0.12)) { inc(s, 'health', -25); inc(s, 'mental', -10); s.zN -= 0.1; L(s, '빗길 코너에서 미끄러졌다. 쇄골 골절, 입원 2주. 번 돈은 치료비로 다 나갔다.', 'bad'); } else L(s, '한 달에 100만 원 넘게 벌었다. 수업 시간엔 졸았다.'); }
      if (o.id === 'store') { s.money += 8; s.flags.work = true; s.zC -= 0.02; L(s, '주말 편의점 알바. 돈은 적지만 손님 없는 새벽엔 단어장을 외웠다.'); }
      if (o.id === 'no') L(s, '거절했다. 용돈은 여전히 빠듯하다.');
    } },
  { id: 'drinkParty', w: s => (s.friendGroup === 'party' ? 1.3 : 0.3) * expo(s), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '생일 파티',
        `친구 생일. 부모님 없는 집에서 모인다는데, 술이 있을 거라고 한다. ${s.romance.status === 'dating' ? `${s.romance.partner}도 온다.` : ''} 내일은 학교 가는 날이다.`, [
        O('go', '간다. 끝까지 논다', '추억 · 신고가 들어오면 경찰·부모님', ['fun', 'social', 'risk']),
        O('early', '얼굴만 비추고 10시에 나온다', '적당히 · 분위기 깨는 애가 된다', ['social', 'safe']),
        O('no', '안 간다', '아무 일 없음 · 다음 날 대화에 못 낀다', ['study', 'safe']),
      ]);
      if (o.id === 'go') { inc(s, 'social', 6); inc(s, 'mental', 3); inc(s, 'lazy', 4); s.zN -= 0.02; if (r.chance(0.2)) { s.flags.discipline = true; inc(s, 'parentRel', -12); inc(s, 'mental', -6); L(s, '이웃 신고로 경찰이 왔다. 새벽 1시에 부모님이 지구대로 데리러 왔다. 학교에도 통보됐다.', 'bad'); } else L(s, '새벽 2시에 들어왔다. 다음 날 1교시부터 4교시까지 잤다.'); }
      if (o.id === 'early') { inc(s, 'social', 2); L(s, '10시에 나왔다. 단톡방은 새벽 3시까지 울렸다.'); }
      if (o.id === 'no') { inc(s, 'social', -3); inc(s, 'lazy', -1); L(s, '안 갔다. 다음 날 걔들끼리만 아는 얘기가 하루 종일 돌았다.'); }
    } },
  { id: 'depression', w: s => (s.mental <= 36 ? 2.6 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, pw = parentWord(s), warm = s.p.pStyle === 'warm';
      const o = choose(ctx, key, '아무것도 하기 싫다',
        `2주째 아침에 일어나는 게 힘들다. 좋아하던 것도 재미가 없고, 이유 없이 눈물이 난다. 성적 때문이 아니라 그냥 다 무겁다. 보건 선생님이 "이건 의지 문제가 아니라 치료 문제"라고 했다.`, [
        O('help', '위클래스·정신건강의학과 상담을 받는다', '회복이 시작된다 · 용기가 필요하다', ['self', 'kind']),
        O('parent', `${pw}께 지금 상태를 말한다`, '혼자가 아니게 된다 · 반응은 부모님에 달렸다', ['kind']),
        O('alone', '혼자 버틴다. 티 안 낸다', '아무도 모른다 · 더 깊어질 수 있다', ['safe']),
      ]);
      if (o.id === 'help') { inc(s, 'mental', 16); inc(s, 'stress', -10); L(s, '상담과 약을 시작했다. 한 달 뒤, 아침에 일어나는 게 조금 덜 무거웠다.', 'good'); }
      if (o.id === 'parent') { if (warm || s.p.pStyle === 'anxious') { inc(s, 'mental', 11); inc(s, 'parentRel', 8); L(s, `${pw}${jo(pw, '이/가')} 다음 날 바로 병원을 예약했다. "진작 말하지." 그 말에 울었다.`, 'good'); } else { inc(s, 'mental', 2); inc(s, 'parentRel', -3); L(s, '"다들 힘들어. 정신력 문제야." 더 말하지 않았다.', 'warn'); } }
      if (o.id === 'alone') { inc(s, 'mental', -8); inc(s, 'lazy', 6); if (r.chance(0.4)) { s.zC -= 0.1; s.zN -= 0.08; L(s, '한 학기가 통째로 비었다. 책상에 앉아 있었지만 아무것도 남지 않았다.', 'bad'); } else L(s, '어떻게든 버텼다. 지금도 그 시기를 떠올리면 가슴이 답답하다.', 'warn'); }
    } },
  { id: 'fakeGrade', w: s => ((s.p.pStyle === 'strict' || s.p.pStyle === 'anxious') && s.naesinRec.length >= 2 && s.naesinRec[s.naesinRec.length - 1] > s.naesinRec[s.naesinRec.length - 2] + 5 ? 1.3 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, pw = parentWord(s);
      const o = choose(ctx, key, '성적표',
        `성적표가 나왔다. 지난 학기보다 떨어졌다. ${pw}${jo(pw, '은/는')} "성적표 나오면 바로 보여 줘"라고 했다. 가방 안에서 종이가 구겨진다.`, [
        O('show', '그대로 보여 드린다', '혼나지만 끝난다 · 학원이 늘 수도', ['self', 'kind']),
        O('hide', '"아직 안 나왔어요"라고 한다', '당장은 피함 · 학교 알림으로 들통난다', ['fun', 'risk']),
      ]);
      if (o.id === 'show') { inc(s, 'parentRel', -4); inc(s, 'stress', 5); const k = SUB_KEYS.reduce((w, k) => (s.sub[k] < s.sub[w] ? k : w), 'kor'); if (s.money > 20 && r.chance(0.5) && (s.acad[k] === 'none' || s.acad[k] === 'online')) { s.acad[k] = 'managed'; L(s, `그날 밤 ${SUBJ_NAME[k]} 관리형 학원이 등록됐다.`); } else L(s, '한참 혼났다. 다음 날 아침엔 평소처럼 밥을 차려 주셨다.'); }
      if (o.id === 'hide') { if (r.chance(0.65)) { inc(s, 'parentRel', -18); s.flags.liar = true; inc(s, 'mental', -6); L(s, '학교 알림 앱으로 성적이 먼저 갔다. 거짓말이 성적보다 더 큰 문제가 됐다.', 'bad'); } else { inc(s, 'mental', -3); L(s, '넘어갔다. 다음 성적표가 더 무서워졌다.', 'warn'); } }
    } },
  // ── 학원: 방향을 잡아 주는 사람 ─────────────────────────
  { id: 'lostDirection', w: s => (noAcademy(s) && s.turnIdx >= 2 && s.turnIdx <= 8 ? 1.9 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, g = mockGrades(s.sub), weak = SUB_KEYS.reduce((w, k) => (g[k] > g[w] ? k : w), 'kor');
      const o = choose(ctx, key, '혼자 공부의 벽',
        `석 달째 ${SUBJ_NAME[weak]} 성적이 그대로다. 문제집은 세 권째인데 틀리는 데서 계속 틀린다. 뭐가 문제인지 봐 줄 사람이 없다. 인터넷엔 "이 방법이 정답"이라는 글이 서로 다른 말을 한다.`, [
        O('director', `${SUBJ_NAME[weak]} 원장 직강 소규모 학원에 상담을 간다`, '약점을 짚어 준다 · 학원비', ['study', 'safe']),
        O('managed', `${SUBJ_NAME[weak]} 관리형 학원에 등록한다`, '시간을 잡아 준다 · 학원비', ['study', 'obey']),
        O('online', '인강 커리큘럼을 처음부터 따라간다', '돈이 덜 든다 · 완강할 수 있을까', ['self', 'safe']),
        O('alone', '내 방식대로 계속 밀고 간다', '돈 안 듦 · 같은 자리를 맴돌 수 있다', ['self', 'risk']),
      ]);
      if (o.id === 'director') { s.acad[weak] = 'director'; s.sub[weak] += 0.06; L(s, `레벨테스트를 채점한 원장님이 틀린 문제 다섯 개를 묶어 보여 줬다. "다 같은 이유야." 석 달 동안 못 본 걸 10분 만에 봤다.`, 'good'); }
      if (o.id === 'managed') { s.acad[weak] = 'managed'; s.sub[weak] += 0.03; inc(s, 'lazy', -4); L(s, '매일 자습 시간이 생겼다. 방향은 여전히 내가 찾아야 하지만 시간은 확보됐다.'); }
      if (o.id === 'online') { s.acad[weak] = 'online'; if (s.p.diligence >= 4) { s.sub[weak] += 0.04; L(s, '완강했다. 커리큘럼대로 가니 구멍이 보였다.'); } else { L(s, '3강까지 듣고 멈췄다. 결제 내역만 남았다.', 'warn'); } }
      if (o.id === 'alone') { s.sub[weak] -= 0.05; inc(s, 'lazy', 3); L(s, `한 학기가 더 지났다. ${SUBJ_NAME[weak]}${jo(SUBJ_NAME[weak], '은/는')} 그대로였다.`, 'bad'); }
    } },
  { id: 'directorCare', w: s => (hasDirector(s) && (s.mental <= 42 || s.stress >= 62 || (s.mocks.length >= 2 && s.mocks[s.mocks.length - 1] > s.mocks[s.mocks.length - 2] + 4)) ? 2.6 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, k = SUB_KEYS.find(k => s.acad[k] === 'director') || 'kor';
      const o = choose(ctx, key, '원장실',
        `수업이 끝나고 원장님이 불렀다. "요즘 눈빛이 다르다. 무슨 일 있어?" 성적 얘기가 아니었다. 30분 동안 내 얘기를 들었다. 그리고 ${SUBJ_NAME[k]} 공부 계획을 처음부터 다시 짜 줬다.`, [
        O('open', '솔직하게 털어놓는다', '마음이 가벼워지고 계획이 생긴다 · 부끄럽다', ['self', 'kind']),
        O('fine', '"괜찮아요" 하고 넘긴다', '편함 · 기회를 놓친다', ['safe']),
      ]);
      if (o.id === 'open') { inc(s, 'mental', 10); inc(s, 'stress', -8); s.sub[k] += 0.05; inc(s, 'lazy', -4); L(s, '원장님이 부모님과도 통화했다. 집 분위기가 조금 달라졌다. 계획표대로 2주를 보내니 다시 문제가 풀렸다.', 'good'); if (s.p.pStyle === 'strict' || s.p.pStyle === 'anxious') inc(s, 'parentRel', 5); }
      if (o.id === 'fine') { inc(s, 'mental', 2); L(s, '"그래, 힘들면 언제든 와." 그 말이 묘하게 남았다.'); }
    } },
  { id: 'acadFriend', w: s => (SUB_KEYS.some(k => s.acad[k] === 'managed' || s.acad[k] === 'director' || s.acad[k] === 'group') && s.turnIdx <= 8 ? 1.1 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s;
      const o = choose(ctx, key, '학원 자습실의 그 애',
        `학원 자습실 옆자리에 다른 학교 애가 앉는다. 매일 밤 10시까지 있다. 쉬는 시간에 틀린 문제를 서로 물어보기 시작했다. 학교 친구들과는 다른 종류의 친구다.`, [
        O('study', '매일 같이 남아 공부하는 사이가 된다', '서로 끌어올림 · 학교 친구와 멀어진다', ['study', 'social']),
        O('casual', '가끔 묻는 정도로 둔다', '부담 없음 · 큰 변화는 없다', ['safe']),
      ]);
      if (o.id === 'study') { s.zC += 0.05; inc(s, 'lazy', -6); inc(s, 'mental', 4); inc(s, 'social', 2); s.flags.studyGroup = true; L(s, '자습실 라이벌이 생겼다. 걔가 남아 있으면 나도 못 일어난다.', 'good'); }
      if (o.id === 'casual') { s.zC += 0.01; L(s, '가끔 문제를 묻는 사이로 남았다.'); }
    } },
  // ── 예체능 ─────────────────────────────────────────
  { id: 'artsContest', w: s => (artsField(s) && s.turnIdx <= 8 ? 1.7 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, af = artsField(s), tk = FIELDS[af].talent, tl = s.talent[tk];
      const nm = { art: '전국 학생 미술 공모전', perf: '청소년 음악 콩쿠르', sport: '시도 학생체육대회' }[af];
      const o = choose(ctx, key, nm,
        `${nm} 공고가 붙었다. ${s.artsAcad !== 'none' ? '학원 선생님은 "지금 실력이면 해 볼 만하다"고 했다.' : '봐 줄 사람이 없어 내 실력이 어디쯤인지 모르겠다.'} 준비하려면 한 달은 교과 공부를 접어야 한다. 입상하면 생기부와 포트폴리오에 남는다.`, [
        O('go', '출전한다', '입상하면 큰 자산 · 떨어지면 한 달이 날아간다', ['self', 'risk']),
        O('skip', '이번엔 넘어간다', '교과 공부 유지 · 경험을 쌓을 기회를 놓친다', ['safe', 'study']),
      ]);
      if (o.id === 'go') { s.zC -= 0.03; const P = clamp((tl - 55) / 45 + (s.artsAcad === 'ipsi' ? 0.12 : 0), 0.05, 0.85); if (r.chance(P)) { s.record += 9; s.talent[tk] = clamp(tl + 3, 5, 100); inc(s, 'mental', 10); s.flags.award = (s.flags.award || 0) + 1; L(s, `${nm} 입상! 처음으로 내 이름이 상장에 적혔다.`, 'good'); } else { inc(s, 'mental', -6); s.talent[tk] = clamp(tl + 1, 5, 100); L(s, '예선 탈락. 심사평은 "기본기는 있으나 완성도 부족". 한 달이 아까웠다.', 'bad'); } }
      if (o.id === 'skip') L(s, '이번엔 넘어갔다. 입상한 애들 사진이 학교 게시판에 붙었다.');
    } },
  { id: 'artsSlump', w: s => (artsField(s) && (s.artsSem || 0) >= 2 ? 1.3 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, af = artsField(s), tk = FIELDS[af].talent;
      const o = choose(ctx, key, '슬럼프',
        `${{ art: '그리는 것마다 마음에 안 든다. 한 달 전 그림이 더 나은 것 같다.', perf: '연습할수록 소리가 이상하다. 녹음을 들으면 지우고 싶다.', sport: '기록이 두 달째 제자리다. 몸이 무겁다.' }[af]} 실기 하는 애들은 다 겪는다는데, 내 것만 끝이 없는 것 같다.`, [
        O('rest', '일주일 완전히 쉰다', '머리가 비워진다 · 감이 조금 떨어진다', ['rest']),
        O('push', '더 많이 한다. 양으로 뚫는다', '뚫리면 한 단계 오른다 · 번아웃 위험', ['study', 'risk']),
        O('teacher', s.artsAcad !== 'none' ? '선생님께 지금 상태를 보여 주고 처방을 받는다' : '유튜브·커뮤니티에서 방법을 찾는다', s.artsAcad !== 'none' ? '원인을 짚어 준다 · 자존심이 상한다' : '혼자 찾아야 한다 · 맞는 방법인지 모른다', ['self']),
      ]);
      if (o.id === 'rest') { s.talent[tk] = clamp(s.talent[tk] - 2, 5, 100); inc(s, 'mental', 7); L(s, '일주일 뒤 다시 잡으니 오히려 편했다.'); }
      if (o.id === 'push') { if (r.chance(0.55)) { s.talent[tk] = clamp(s.talent[tk] + 4, 5, 100); inc(s, 'mental', -5); L(s, '어느 날 갑자기 뚫렸다. 선이(소리가, 몸이) 달라졌다.', 'good'); } else { inc(s, 'mental', -12); inc(s, 'stress', 10); inc(s, 'health', -6); L(s, '번아웃이 왔다. 2주 동안 손도 못 댔다.', 'bad'); } }
      if (o.id === 'teacher') { if (s.artsAcad !== 'none') { s.talent[tk] = clamp(s.talent[tk] + 4, 5, 100); inc(s, 'mental', 5); L(s, '선생님이 10초 보고 말했다. "힘이 들어갔어. 기본 연습으로 돌아가." 2주 뒤 풀렸다.', 'good'); } else { if (r.chance(0.4)) { s.talent[tk] = clamp(s.talent[tk] + 1, 5, 100); L(s, '영상 하나가 도움이 됐다. 운이 좋았다.'); } else { inc(s, 'mental', -4); L(s, '방법은 많은데 내 것은 없었다. 슬럼프가 길어졌다.', 'warn'); } } }
    } },
  { id: 'artsInjury', w: s => (artsField(s) === 'art' ? 0.7 : artsField(s) === 'perf' ? 0.7 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, af = artsField(s), tk = FIELDS[af].talent;
      const o = choose(ctx, key, af === 'art' ? '손목' : '목',
        af === 'art' ? '하루 8시간 그리던 손목이 저리기 시작했다. 정형외과: "손목터널증후군 초기. 3주는 쉬어야 해요." 실기 시험이 두 달 남았다.' : '고음에서 소리가 갈라진다. 이비인후과: "성대 결절 초기. 2주 침묵 치료." 실기 시험이 두 달 남았다.', [
        O('rest', '시키는 대로 쉰다', '제대로 낫는다 · 두 달 중 3주를 잃는다', ['rest', 'safe']),
        O('push', '참고 연습한다', '시간을 지킨다 · 악화되면 실기 당일이 위험하다', ['study', 'risk']),
      ]);
      if (o.id === 'rest') { s.talent[tk] = clamp(s.talent[tk] - 3, 5, 100); L(s, '3주를 쉬었다. 돌아오니 감은 떨어졌지만 통증은 사라졌다.'); }
      if (o.id === 'push') { if (r.chance(0.45)) { s.flags[af === 'art' ? 'handInjury' : 'vocalNodule'] = true; s.talent[tk] = clamp(s.talent[tk] - 8, 5, 100); inc(s, 'mental', -10); L(s, af === 'art' ? '악화됐다. 연필을 10분 이상 못 쥔다. 실기 당일까지 낫는다는 보장이 없다.' : '결절이 커졌다. 수술 얘기가 나왔다. 실기 당일까지 낫는다는 보장이 없다.', 'bad'); } else { s.talent[tk] = clamp(s.talent[tk] + 1, 5, 100); L(s, '버텼다. 운이 좋았다.'); } }
    } },
  { id: 'artsCost', w: s => (artsField(s) && s.artsAcad && s.artsAcad !== 'none' && s.money < 25 ? 2.2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, af = artsField(s), pw = parentWord(s);
      const o = choose(ctx, key, '현실적으로 생각해',
        `${pw}${jo(pw, '이/가')} 학원비 고지서를 식탁에 올려놓았다. "${ARTS_ACAD[s.artsAcad].name} 한 달에 ${Math.round(ARTS_ACAD[s.artsAcad].cost * 25)}만 원이야. 재료비까지. 솔직히 이걸로 먹고살 수 있겠니? 현실적으로 생각해 보자."`, [
        O('keep', '"1년만 더 믿어 줘" 하고 설득한다', '꿈을 지킨다 · 집에 부담, 결과로 보여야 한다', ['self', 'risk']),
        O('cheap', '학원을 끊고 혼자 연습한다', '돈은 아낀다 · 실기는 혼자 늘기 어렵다', ['safe', 'self']),
        O('quit', `${ARTS_NAME[artsOf(af)]}을 접고 공부로 돌아간다`, '현실적인 선택 · 몇 년 연습이 사라진다', ['safe', 'obey']),
      ]);
      if (o.id === 'keep') { s.money -= 6; inc(s, 'parentRel', s.p.pDesire === 'free' ? 0 : -7); inc(s, 'stress', 6); L(s, `${pw}${jo(pw, '은/는')} 한참 말이 없다가 "1년"이라고 했다. 이제 결과로 보여야 한다.`); }
      if (o.id === 'cheap') { s.artsAcad = 'none'; L(s, '학원을 끊었다. 혼자 그리는(연습하는) 밤, 뭐가 틀렸는지 봐 줄 사람이 없다.', 'warn'); }
      if (o.id === 'quit') { const f = af; s.arts = null; s.flags.artPath = s.flags.musicPath = s.flags.sportPath = false; s.flags.artsQuit = true; s.interest[f] -= 20; inc(s, 'mental', -14); s.zC += 0.03; L(s, '도구를 정리해 상자에 넣었다. 교과서를 폈는데 글자가 눈에 안 들어왔다.', 'bad'); }
    } },
  { id: 'artsParent', w: s => (artsField(s) && ['med', 'prestige', 'stable', 'law'].indexOf(s.p.pDesire) >= 0 && s.turnIdx <= 6 && !s.flags.artsParentOk ? 2 : 0), once: true,
    run: (ctx, key, r) => {
      const s = ctx.s, af = artsField(s), pw = parentWord(s);
      const o = choose(ctx, key, '"그걸로 뭐 하려고"',
        `${pw}${jo(pw, '이/가')} 실기 가방을 보며 말했다. "${ARTS_NAME[artsOf(af)]}은 취미로 해. ${PARENT_DESIRES[s.p.pDesire].name}." 식탁이 조용해졌다.`, [
        O('persuade', '포트폴리오(기록)와 입시 자료를 보여 주며 설득한다', '인정받으면 든든하다 · 안 되면 더 멀어진다', ['self']),
        O('secret', '"알겠어요" 하고 몰래 계속한다', '당장은 조용함 · 들키면 신뢰가 깨진다', ['rebel', 'risk']),
        O('quit', '접는다', '집이 조용해진다 · 마음 한쪽이 비어 간다', ['obey', 'safe']),
      ]);
      if (o.id === 'persuade') { if (r.chance(0.4 + (s.p.confidence - 3) * 0.1 + (s.talent[FIELDS[af].talent] >= 70 ? 0.2 : 0))) { s.flags.artsParentOk = true; inc(s, 'parentRel', 6); s.autonomy += 1; L(s, `${pw}${jo(pw, '이/가')} 자료를 한참 보더니 "그래, 해 봐"라고 했다. 대신 "교과 성적도 놓지 마"가 붙었다.`, 'good'); } else { inc(s, 'parentRel', -9); inc(s, 'mental', -5); L(s, '"그 대학 나와서 뭐 하는데." 대화가 끊겼다.', 'bad'); } }
      if (o.id === 'secret') { s.flags.secretPath = true; s.autonomy += 1; L(s, '학원비는 알바로 댔다. 가방은 친구 집에 뒀다.', 'warn'); }
      if (o.id === 'quit') { const f = af; s.arts = null; s.flags.artPath = s.flags.musicPath = s.flags.sportPath = false; s.flags.artsQuit = true; s.interest[f] -= 20; inc(s, 'mental', -12); inc(s, 'parentRel', 4); L(s, '접었다. 집은 조용해졌다.', 'bad'); }
    } },
];

// ── 운 ────────────────────────────────────────────────
//  내 선택과 상관없이 벌어지는 일. 바르게 살아도 겪고, 대충 살아도 피해 간다. 기록에 '(운)'으로 남고, 선택 평가에서는 뺀다.
const FATES = [
  { id: 'accident', w: s => 1, run: (ctx, key, r) => { const s = ctx.s;
      if (r.chance(0.22)) { Lf(s, '등굣길 횡단보도에서 신호를 어긴 차에 치였다. 골반 골절과 뇌진탕, 입원 석 달. 한 학기가 통째로 비었다.'); inc(s, 'health', -40); inc(s, 'mental', -16); s.zN -= 0.24; s.zC -= 0.14; s.record = Math.max(0, s.record - 6); s.flags.bigAccident = true; L(s, '퇴원하니 반 애들은 다음 단원을 나가고 있었다. 재활 때문에 저녁 공부도 어렵다.', 'bad'); return; }
      Lf(s, '등굣길 횡단보도에서 우회전하던 차에 치였다. 다리 골절, 입원 3주.'); inc(s, 'health', -20); inc(s, 'mental', -6); s.zN -= 0.08; s.zC -= 0.03;
      const o = choose(ctx, key, '병실에서', '깁스를 한 채 병실 천장을 보고 있다. 중간고사가 2주 뒤다. 담임 선생님은 "병결은 인정 결석이니 걱정 말고, 시험은 인정점(직전 시험의 80%)으로 처리할 수도 있다"고 하셨다.', [
        O('rest', '치료에 집중한다. 시험은 인정점으로', '몸이 제대로 낫는다 · 이번 내신은 깎인다', ['rest', 'safe']),
        O('study', '병실에서 문제집을 푼다. 시험은 본다', '내신을 지킬 수도 · 회복이 늦어진다', ['study']),
      ]);
      if (o.id === 'rest') { s.zN -= 0.04; inc(s, 'health', 8); L(s, '3주 뒤 목발을 짚고 등교했다. 인정점으로 처리된 내신은 평소보다 조금 낮았다.'); }
      else { s.zN += 0.03; inc(s, 'health', -6); L(s, '병원 침대에서 문제집 두 권을 끝냈다. 시험은 평소만큼 봤다. 뼈는 예정보다 2주 늦게 붙었다.'); } } },
  { id: 'parentIll', w: s => 0.7, once: true, run: (ctx, key, r) => { const s = ctx.s, pw = parentWord(s); Lf(s, `${pw}${jo(pw, '이/가')} 건강검진에서 암 진단을 받았다. 수술과 항암이 시작됐다.`); s.money = Math.max(4, s.money - 22); inc(s, 'mental', -14); inc(s, 'stress', 10);
      const o = choose(ctx, key, '병원과 학교 사이', `주말마다 병원에 간다. 집안 분위기가 가라앉았고, 학원비 얘기는 아무도 꺼내지 않는다. ${s.p.sibling === 'younger' ? '동생 저녁은 내가 챙긴다.' : ''} 어떻게 할까?`, [
        O('care', '간병과 집안일을 많이 맡는다', '가족이 가까워진다 · 공부 시간이 준다', ['kind']),
        O('study', '"내가 할 수 있는 건 공부"라며 책상에 앉는다', '성적은 지킨다 · 죄책감이 남는다', ['study']),
        O('talk', '담임·위클래스에 사정을 말하고 도움을 받는다', '장학·지원 정보를 얻는다 · 알려지는 게 싫을 수 있다', ['self', 'kind']),
      ]);
      if (o.id === 'care') { inc(s, 'parentRel', 10); s.zC -= 0.06; s.zN -= 0.05; inc(s, 'mental', 4); s.flags.caregiver = true; L(s, '병원 복도에서 단어장을 외웠다. 성적은 조금 떨어졌지만 후회는 없다.'); }
      if (o.id === 'study') { s.zC += 0.01; inc(s, 'parentRel', -4); inc(s, 'mental', -5); L(s, '"공부 열심히 하는 게 효도"라는 말을 붙잡고 책상에 앉았다. 밤마다 죄책감이 올라왔다.'); }
      if (o.id === 'talk') { s.money += 10; inc(s, 'mental', 6); s.record += 2; L(s, '학교에서 긴급 복지 지원과 장학금을 연결해 줬다. 담임 선생님이 자주 들여다봐 주셨다.', 'good'); } } },
  { id: 'bankrupt', w: s => (s.p.wealth === 'high' ? 0.25 : s.p.pJob === 'self' ? 1.3 : 0.7), once: true, run: (ctx, key, r) => { const s = ctx.s; const t = s.p.pJob === 'self' ? '가게가 문을 닫았다. 보증금까지 날렸다.' : s.p.pJob === 'labor' ? '아빠가 다니던 공장이 폐업했다.' : '회사 구조조정 명단에 아빠 이름이 있었다.'; Lf(s, `집에 큰일이 났다. ${t}`); s.money = Math.max(4, s.money - 35); s.flags.moneyTight = true; inc(s, 'mental', -10); inc(s, 'stress', 10);
      const cut = SUB_KEYS.filter(k => s.acad[k] !== 'none' && s.acad[k] !== 'online');
      if (cut.length) { cut.forEach(k => { s.acad[k] = 'online'; }); L(s, `${cut.map(k => SUBJ_NAME[k]).join('·')} 학원을 모두 끊고 인강으로 바꿨다.`, 'bad'); }
      if (s.artsAcad && s.artsAcad !== 'none') { s.artsAcad = 'none'; L(s, '실기 학원도 끊었다. 이제 혼자 연습해야 한다.', 'bad'); }
      const o = choose(ctx, key, '달라진 식탁', '저녁 식탁에서 부모님이 말을 아낀다. 학원비 자동이체 문자가 더 이상 오지 않는다. 어떻게 할까?', [
        O('work', '주말 알바를 시작한다', '내 용돈은 내가 번다 · 공부 시간이 준다', ['work']),
        O('scholar', '교육청·학교 장학과 교육비 지원을 알아본다', '학원 하나는 다시 다닐 수 있다 · 서류와 시간이 든다', ['self', 'study']),
        O('hold', '아무 말 않고 하던 대로 한다', '부모님 부담을 안 늘림 · 혼자 삭인다', ['safe']),
      ]);
      if (o.id === 'work') { s.flags.work = true; s.money += 12; s.zC -= 0.03; L(s, '주말 열 시간 알바. 월말에 처음으로 내 돈으로 문제집을 샀다.'); }
      if (o.id === 'scholar') { s.money += 8; const k = SUB_KEYS.reduce((w, k) => (s.sub[k] < s.sub[w] ? k : w), 'kor'); s.acad[k] = 'director'; L(s, `교육비 지원으로 ${SUBJ_NAME[k]} 학원 하나는 다시 다닌다. 원장님이 사정을 듣고 수강료를 깎아 주셨다.`, 'good'); }
      if (o.id === 'hold') { inc(s, 'mental', -5); L(s, '아무 일 없는 것처럼 지냈다. 밤에 부모님이 작게 다투는 소리가 들렸다.'); } } },
  { id: 'divorce', w: s => (s.p.pBond === 'fight' ? 2 : s.p.pBond === 'cold' ? 1 : 0.3), once: true, run: (ctx, key, r) => { const s = ctx.s; Lf(s, '부모님이 이혼하기로 했다. 누구와 살지 묻는 자리가 있었다.'); inc(s, 'mental', -14); inc(s, 'parentRel', -6); inc(s, 'lazy', 4); s.p.pBond = 'single';
      const o = choose(ctx, key, '아무에게도 말하지 못한 일', '학교에서는 아무 일 없는 척한다. 그런데 수업 시간에 자꾸 멍해진다. 어떻게 할까?', [
        O('counsel', '위클래스 상담 선생님을 찾아간다', '마음이 정리된다 · 처음 한 걸음이 어렵다', ['self', 'kind']),
        O('friend', s.bestFriend ? `${s.bestName}에게 털어놓는다` : '친구에게 털어놓는다', '혼자가 아니게 된다 · 소문이 날 수도', ['social']),
        O('alone', '아무에게도 말하지 않는다', '티가 안 난다 · 속으로 곪는다', ['safe']),
      ]);
      if (o.id === 'counsel') { inc(s, 'mental', 10); L(s, '매주 수요일 점심시간, 상담실. 울고 나니 조금 가벼워졌다.', 'good'); }
      if (o.id === 'friend') { inc(s, 'mental', 6); inc(s, 'social', 4); if (r.chance(0.2)) { inc(s, 'social', -8); L(s, '반에 소문이 돌았다. 믿었던 만큼 아팠다.', 'bad'); } else L(s, '친구가 아무 말 없이 떡볶이를 사 줬다.'); }
      if (o.id === 'alone') { inc(s, 'mental', -6); s.zC -= 0.03; L(s, '혼자 삭였다. 성적표가 나올 때쯤 티가 났다.', 'warn'); } } },
  { id: 'victim', w: s => (s.turnIdx <= 6 ? 0.9 : 0.3) * (s.social < 35 ? 1.6 : 1), once: true, run: (ctx, key, r) => { const s = ctx.s; Lf(s, '이유 없이 표적이 됐다. 책상에 낙서, 단톡방에서 저격, 급식실에서 혼자. 학교폭력 피해자가 됐다.'); inc(s, 'social', -14); inc(s, 'mental', -16); inc(s, 'stress', 10);
      const o = choose(ctx, key, '어떻게 할까', '한 달째다. 등교하는 아침마다 배가 아프다. 부모님은 아직 모른다.', [
        O('report', '학교폭력으로 신고한다(117·담임)', '멈출 가능성 · 절차가 길고 보복이 있을 수 있다', ['self']),
        O('bear', '졸업할 때까지 참는다', '일을 키우지 않음 · 마음이 계속 다친다', ['safe']),
        O('transfer', '부모님께 말하고 전학한다', '환경이 바뀐다 · 친구·내신을 새로 쌓아야 한다', ['rebel', 'self']),
      ]);
      if (o.id === 'report') { if (r.chance(0.6)) { inc(s, 'mental', 12); inc(s, 'social', 6); L(s, '학폭위가 열렸고 가해 학생들은 분리 조치됐다. 처음으로 급식실에서 밥이 넘어갔다.', 'good'); } else { inc(s, 'mental', -8); L(s, '"신고했다"는 게 알려지면서 교묘해졌다. 증거가 부족하다는 말을 들었다.', 'bad'); } }
      if (o.id === 'bear') { inc(s, 'mental', -8); inc(s, 'lazy', 4); s.zC -= 0.04; L(s, '참았다. 책이 눈에 들어오지 않는 날이 많았다.', 'bad'); }
      if (o.id === 'transfer') { inc(s, 'mental', 8); inc(s, 'social', -6); s.zN -= 0.05; s.friendGroup = 'alone'; L(s, '전학 간 학교의 첫날, 아무도 나를 모른다는 게 이렇게 편할 줄 몰랐다.'); } } },
  { id: 'recordMiss', w: s => (s.turnIdx <= 8 ? 0.9 : 0), once: true, run: (ctx, key, r) => { const s = ctx.s; Lf(s, '담임 선생님이 생기부를 급하게 썼다. 내가 한 활동 절반이 빠지고, 다른 학생과 비슷한 문장이 들어갔다.'); s.record = Math.max(0, s.record - 8); } },
  { id: 'recordLucky', w: s => (s.turnIdx <= 8 ? 0.7 : 0), once: true, run: (ctx, key, r) => { const s = ctx.s; Lf(s, '담임 선생님이 생기부를 공들여 써 주셨다. 내가 지나가듯 한 말까지 세특에 들어갔다.'); s.record = Math.min(100, s.record + 8); } },
  { id: 'examError', w: s => (s.turnIdx <= 8 ? 0.8 : 0), run: (ctx, key, r) => { const s = ctx.s; const d = (r.next() - 0.5) * 0.14; Lf(s, d < 0 ? '기말고사 수학에서 출제 오류가 나와 두 문항이 전원 정답 처리됐다. 내가 맞혔던 문제라 등급이 밀렸다.' : '기말고사 출제 오류로 두 문항이 전원 정답 처리됐다. 틀렸던 문제라 등급이 올랐다.'); s.zN += d; } },
  { id: 'flu', w: s => 0.8, run: (ctx, key, r) => { const s = ctx.s; Lf(s, '시험 전날 독감에 걸렸다. 39도에서 시험지를 받았다.'); s.zN -= 0.07; inc(s, 'health', -8); } },
  { id: 'scholarship', w: s => (s.p.wealth === 'high' ? 0.1 : 0.5), once: true, run: (ctx, key, r) => { const s = ctx.s; Lf(s, '지역 장학재단 장학생으로 뽑혔다. 학기마다 60만 원.'); s.money += 14; inc(s, 'mental', 4); } },
  { id: 'teacherGood', w: s => 0.9, once: true, run: (ctx, key, r) => { const s = ctx.s, k = r.pick(SUB_KEYS); Lf(s, `${SUBJ_NAME[k]} 선생님이 바뀌었다. 수업이 재미있어서 처음으로 그 과목이 기다려진다.`); s.sub[k] += 0.08; s.interest[k === 'math' ? 'eng' : k === 'kor' ? 'hum' : k === 'eng' ? 'hum' : 'sci'] += 4; } },
  { id: 'teacherBad', w: s => 0.6, once: true, run: (ctx, key, r) => { const s = ctx.s, k = r.pick(SUB_KEYS); Lf(s, `${SUBJ_NAME[k]} 선생님이 바뀌었다. 수업은 자습, 시험은 수업 안 한 데서 나온다. 반 전체 평균이 무너졌다.`); s.sub[k] -= 0.05; inc(s, 'stress', 4); } },
  { id: 'move', w: s => (s.turnIdx <= 6 ? 0.5 : 0), once: true, run: (ctx, key, r) => { const s = ctx.s; Lf(s, '부모님 직장 때문에 이사했다. 전학 첫날, 아는 얼굴이 하나도 없다.'); inc(s, 'social', -12); s.zN -= 0.04; s.bestFriend = false; s.friendGroup = 'alone'; inc(s, 'mental', -6); } },
  { id: 'artsReform', w: s => (artsField(s) && s.turnIdx >= 4 && s.turnIdx <= 8 ? 1.2 : 0), once: true, run: (ctx, key, r) => { const s = ctx.s; Lf(s, '가려던 대학이 내년부터 실기 비중을 줄이고 수능·서류를 더 보기로 했다는 입시 요강이 떴다.'); s.flags.artsReform = true; inc(s, 'stress', 8); } },
];
function rollFate(ctx, turn, prob) {
  const s = ctx.s, r = makeRng(s.seed, turn.id + ':fate');
  if (!r.chance(prob)) return;
  const pool = FATES.filter(e => !(e.once && s.seen['f:' + e.id]) && e.w(s) > 0);
  const ws = pool.map(e => e.w(s)), tot = ws.reduce((a, b) => a + b, 0);
  if (tot <= 0) return;
  let x = r.next() * tot, ev = pool[0];
  for (let i = 0; i < pool.length; i++) { x -= ws[i]; if (x <= 0) { ev = pool[i]; break; } }
  s.seen['f:' + ev.id] = true;
  ev.run(ctx, turn.id + ':fate:' + ev.id, makeRng(s.seed, turn.id + ':f:' + ev.id));
}
function randomEvents(ctx, turn, n) {
  const s = ctx.s, r = makeRng(s.seed, turn.id + ':ev');
  const count = n != null ? n : 3 + (r.chance(0.5) ? 1 : 0);
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

function semesterBrief(s, turn) {
  const last = s.naesinRec.length ? s.naesinRec[s.naesinRec.length - 1] : s.p.gpaPct;
  const notes = [];
  const g = mockGrades(s.sub);
  notes.push(`지난 성적은 내신 상위 ${last.toFixed(0)}%, 모의고사 ${gradesText(g)}.`);
  if (g.kor >= 4 && g.kor >= Math.min(g.eng, g.inq) + 1) notes.push('국어가 약하면 영어·탐구 지문 이해도 같이 막힌다.');
  notes.push(`지금 학원: ${acadText(s)}. 학원 다니는 과목은 복습·숙제용으로 2칸 이상 남겨야 효과가 제대로 난다.`);
  notes.push(`국어는 ${korText(korGrades(s))}. 공부법: ${(KOR_FOCUS[s.korFocus] || KOR_FOCUS.mock).name}.`);
  if (s.lazy >= 45) notes.push('요즘 계획한 공부 시간이 자꾸 폰으로 새어 나간다.');
  if (s.stress >= 60) notes.push('스트레스가 높다. 쉬지 않으면 무너질 수 있다.');
  if (s.health <= 45) notes.push('체력이 바닥이다.');
  if (s.money <= 15) notes.push('학원비가 집에 부담이 되고 있다.');
  if (s.romance.status === 'dating') notes.push(`${s.romance.partner}${jo(s.romance.partner, '은/는')} 더 자주 보고 싶어 한다.`);
  if (turn.id === 'g3s1') notes.push('고3 1학기 내신은 수시에 반영되는 마지막 성적이다.');
  if (turn.id === 'g2s2') notes.push('고2 2학기는 학종에서 가장 꼼꼼히 보는 학기다.');
  return `하루 중 쓸 수 있는 시간을 ${ALLOC_TOTAL}칸으로 나눠 과목별로 이번 학기를 계획하자. ` + notes.join(' ');
}

function semesterTurn(ctx, turn) {
  const s = ctx.s;
  fixedEvents(ctx, turn);
  const cats = allocCats(s, turn);
  const def = defaultAlloc(s, cats);
  const raw = ask(ctx, { type: 'alloc', key: turn.id + ':alloc', title: turn.label + ' 시간 쓰기',
    text: semesterBrief(s, turn), cats, def, total: ALLOC_TOTAL });
  const a = normAlloc(raw, cats);
  ['study', 'academy', 'activity', 'hobby', 'friends', 'rest', 'date', 'work'].forEach(k => { if (a[k] == null) a[k] = 0; });
  s.lastAlloc = a;
  semesterEffects(ctx, turn, a);
  rollFate(ctx, turn, 0.16);
  randomEvents(ctx, turn);
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
  const cs = s.csatSub || s.sub;
  const zcs = compositeZ(cs, field);
  switch (type) {
    case 'gyogwa': return zNavg - trackPen * 0.5 - (s.flags.applyMathWeak || 0) * 0.04 - (s.flags.lateHabit ? 0.06 : 0) - (s.flags.violence >= 2 ? 0.08 : 0);
    case 'jonghap': {
      const sb = p.school === 'special' ? 0.45 : p.school === 'jasa' ? 0.25 : p.region === 'gangnam' ? 0.05 : 0;
      return zNavg + 0.3 * zRec + sb + fitRec * 0.22 + ((s.flags.interviewPrep || 0) - 1) * 0.06 + (s.flags.splitPath ? -0.08 : 0) + subjFit - trackPen + (s.flags.award ? 0.06 : 0) + (s.flags.caught ? -0.2 : 0) + (s.flags.council ? 0.05 : 0) - (s.flags.applyMathWeak || 0) * 0.08 - (s.flags.korWeakInterview ? 0.06 : 0) - (s.flags.lateHabit ? 0.1 : 0) - (s.flags.discipline ? 0.08 : 0) - (s.flags.teacherBad ? 0.05 : 0);
    }
    case 'nonsul': return 0.45 * (cs.kor + s.korOff.read) + 0.25 * zcs + (p.comprehension - 3) * 0.22 + (s.talent.verbal - 40) / 110;   // 논술은 국어 독해력이 핵심
    case 'silgi': {
      const tk = FIELDS[field].talent;
      // 실기 점수(z) + 실기 당일 운. 미술은 손, 음악은 목·컨디션, 체육은 날씨·부상. 심사 주관성도 있다
      const day = s.silgiDay != null ? s.silgiDay : 0;
      const tal = (s.talent[tk] - 50) / 16 + (s.flags.artsSince != null ? 0.15 : 0) + (field === 'perf' && s.flags.trainee ? 0.4 : 0) + (field === 'sport' && s.flags.reinjury ? -0.5 : 0) + day;
      return 0.65 * tal + 0.35 * (zcs + zNavg) / 2;
    }
    // 계열별 반영 비율로 합친 과목 점수. 다들 반영 비율 높은 과목에 몰아 공부하므로, 평균과의 차이는 절반만 이득으로 친다
    case 'jungsi': return (zcs + meanSub(cs)) / 2;
  }
  return zcs;
}
function cutZ(tier, field) { if (tier.arts) return zFromTop(tier.pct); return zFromTop(tier.pct) + (tier.fo ? 0 : FIELD_DIFF[field] || 0) + (SILGI[field] ? -0.35 : 0); }
// 예체능 대학: 실기 비중(silgiW)만큼 실기 z, 나머지는 수능·내신 z
function artsZ(s, tier, field, type) {
  const zs = studentZ(s, 'silgi', field);
  const cs = s.csatSub || s.sub, zc = (compositeZ(cs, field) + meanSub(cs)) / 2, zN = zFromTop(avgNaesin(s));
  const acad = type === 'jungsi' ? zc : (zc + zN) / 2;
  const w = clamp(tier.silgiW - (s.flags.artsReform ? 0.15 : 0), 0.1, 0.95);
  return w * zs + (1 - w) * acad;
}
function estimateIdx(s, list, z, field, r, bias) {
  const pz = z + bias + r.normal() * 0.07;
  for (let i = 0; i < list.length; i++) if (pz >= cutZ(list[i], field)) return i;
  return list.length - 1;
}
function cardP(s, c, field) {
  // 정시(일반 학과): 대학어디가 70%컷과 국수탐 백분위 점수를 바로 비교한다. 70%컷이면 붙는 쪽이 많다
  if (c.type === 'jungsi' && !SILGI[field] && c.tier.fo !== 'med' && uniCut(c.uni, field) != null) {
    const sc = jungsiScore(s.csatSub || s.sub, field, c.tier.gi), cut = uniCut(c.uni, field) + (FIELD_DIFF[field] || 0) * 8;
    c.cut = cut; c.score = sc;
    return sigmoid(0.85 * (sc - cut + 0.9));
  }
  if (c.tier.arts) {
    const z = artsZ(s, c.tier, field, c.type);
    let P = sigmoid(4.5 * (z - cutZ(c.tier, field)));
    if (c.tier.key === 'm3') P *= 0.6;   // 실용음악 명문은 경쟁률이 100대 1을 넘는다
    if (s.flags.violence >= 2 && c.type !== 'jungsi') P *= 0.5;
    return P;
  }
  const z = studentZ(s, c.type, field);
  const k = { gyogwa: 8, jonghap: 5.5, nonsul: 3, silgi: 5, jungsi: 11 }[c.type];
  let P = sigmoid(k * (z - cutZ(c.tier, field)));
  if (c.type === 'nonsul') P = P * 0.32 + 0.02;
  if (c.type === 'jonghap') P = P * 0.92;
  if (hasDirector(s) && (c.type === 'jonghap' || c.type === 'gyogwa')) P *= 1.06;   // 자소서·면접을 원장이 봐 줬다
  // 접은 과목: 상위권 서류·교과에서는 수학 7등급이 바로 보인다. 중하위권은 덜 본다
  if (c.type === 'jonghap' || c.type === 'gyogwa') droppedList(s).forEach(k => { const core = k === 'kor' || k === 'math'; P *= c.tier.gi <= 3 ? (core ? 0.35 : 0.6) : c.tier.gi <= 5 ? (core ? 0.7 : 0.85) : (k === 'kor' ? 0.7 : 1); });
  // 학폭 조치 기록·징계는 서류에서 바로 걸린다
  const vio = s.flags.violence || 0;
  if (vio && c.type === 'jonghap') P *= vio >= 2 ? 0.25 : 0.6;
  if (vio >= 2 && c.type === 'gyogwa') P *= 0.75;
  if (vio >= 2 && c.type === 'jungsi') P *= 0.85;
  return P;
}
function makeCards(s, field, type, strategy, count, r, estZ) {
  const list = tierList(field, s);
  const z = list[0].arts ? artsZ(s, list[Math.floor(list.length / 2)], field, type) : studentZ(s, type, field);
  const bias = (s.p.confidence - 3) * 0.08 + (s.pressure > 30 ? 0.05 : 0) - (s.consultQ || 0);
  let est = estimateIdx(s, list, estZ != null ? estZ : z, field, r, bias);
  if (type === 'jungsi' && usesPct(field, list)) {
    // 정시 모의지원: 내 백분위 점수와 대학별 70%컷을 놓고 고른다
    est = list.length - 1;
    for (let i = 0; i < list.length; i++) { const sc = jungsiScore(s.csatSub || s.sub, field, list[i].gi) + bias * 8 + r.normal() * 0.6; if (sc >= tierCut(list[i], field) + (FIELD_DIFF[field] || 0) * 8 - 0.9) { est = i; break; } }
  }
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
    const c = { tier: t, uni, major, field: fo, applyField: field, type, label: o < 0 ? '상향' : o === 0 ? '적정' : '안정', req: minReq(t, type) };
    c.P = cardP(s, c, field);
    return c;
  });
}
function rollCards(s, cards, r) {
  cards.forEach(c => {
    c.P = cardP(s, c, c.applyField || c.field);
    if (c.req) { const m = checkMin(c.req, s.csatG || mockGrades(s.sub)); c.minOk = m.ok; c.minSum = m.sum; } else c.minOk = true;
    c.pass = c.minOk && r.next() < c.P;
  });
  return cards;
}
function cardText(c) { return `${c.uni} ${c.major}(${TYPE_NAMES[c.type]}·${c.label}${c.req ? ', 최저 ' + reqText(c.req) : ''})`; }

function applyTurn(ctx, turn) {
  const s = ctx.s, p = s.p;
  // 여름: 연애 중이면 같은 대학 고민
  if (s.romance.status === 'dating') {
    const nm = s.romance.partner;
    const o = choose(ctx, 'g3v1:sameUni', '같은 대학 가자', `원서 접수 3주 전, 독서실 앞 벤치. ${nm}${jo(nm, '이/가')} 대학 목록을 적은 메모를 내민다. "우리 같은 대학 쓰자. 안 되면 같은 지역이라도. 장거리 연애는 자신 없어." 메모 속 대학들은 내 성적보다 한두 단계 낮다.`, [
      { id: 'match', label: '좋아. 원서를 맞춘다', hint: '함께하는 미래 · 내가 갈 수 있는 대학보다 낮춰 쓴다', tags: ['romance'] },
      { id: 'own', label: '"원서는 각자 소신대로 쓰고, 어디든 만나러 갈게"', hint: '내 입시를 지킴 · 관계가 흔들릴 수 있다', tags: ['self'] },
      { id: 'end', label: '수능 끝날 때까지 연애를 잠시 멈추자고 한다', hint: '수능에 집중 · "잠시"가 끝이 될 수 있다', tags: ['study'] },
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
  const trackOk = f => FIELDS[f].track !== '자연' || s.track === '자연';
  const ej = f => employText(f, 62);
  const fOpts = [{ id: my, label: `${FIELDS[my].name} — 내가 가장 끌리는 분야`, hint: (trackOk(my) ? '' : '선택과목이 맞지 않아 불리 · ') + ej(my), tags: ['self'] }];
  if (d && d !== my) fOpts.push({ id: d, label: `${FIELDS[d].name} — 부모님이 원하는 분야`, hint: ej(d), tags: ['obey'] });
  if (second !== d && second !== my) fOpts.push({ id: second, label: `${FIELDS[second].name} — 두 번째로 관심 있는 분야`, hint: ej(second), tags: ['safe'] });
  // 취업률 우선: 내 계열에서 갈 만한 학과 중 취업률이 가장 높은 곳(의대는 성적이 될 때만)
  const pool = (s.track === '자연' ? ['nurse', 'eng', 'cs'] : ['biz', 'edu', 'law']).concat(topFromZ(s.zC) <= 1.5 ? ['med'] : []);
  const bestJob = pool.reduce((b, f) => (employOf(f, 62).rate > employOf(b, 62).rate ? f : b), pool[0]);
  if (fOpts.every(o => o.id !== bestJob)) fOpts.push({ id: bestJob, label: `${FIELDS[bestJob].name} — 취업이 잘 되는 학과`, hint: ej(bestJob) + (fitOf(s, bestJob) < 0.5 ? ' · 흥미는 별로 없다' : ''), tags: ['safe', 'obey'] });
  if (p.pDesire === 'prestige' || p.pDesire === 'money' || p.goal === 'sky' || p.goal === 'ssh') {
    const easy = s.track === '자연' ? 'sci' : 'hum';
    if (fOpts.every(o => o.id !== easy)) fOpts.push({ id: easy, label: `${FIELDS[easy].name} — 학과보다 대학 간판(합격선 낮은 과)`, hint: '한 단계 높은 대학 · ' + ej(easy), tags: ['safe', 'obey'] });
  }
  const af0 = artsField(s);
  if (af0) {
    const tk = FIELDS[af0].talent, tl = Math.round(s.talent[tk]);
    const lbl = { art: `디자인·미술 — 준비해 온 미대 실기 (실기 ${tl}점)`, perf: `음악 — 준비해 온 음대·실용음악 실기 (실기 ${tl}점)`, sport: `체육 — 준비해 온 체대 실기 (실기 ${tl}점)` }[af0];
    for (let i = fOpts.length - 1; i >= 0; i--) if (fOpts[i].id === af0) fOpts.splice(i, 1);
    fOpts.unshift({ id: af0, label: lbl, hint: tl >= 75 ? '실기가 강하다 · 수능·내신도 같이 본다' : tl >= 55 ? '실기는 중간 · 수능·내신으로 보태야 한다' : '실기가 아직 약하다 · 안전한 곳만 노려야 한다', tags: ['self'], w: 3 });
    if (tl < 55) fOpts.push({ id: s.track === '자연' ? 'eng' : 'biz', label: `${FIELDS[s.track === '자연' ? 'eng' : 'biz'].name} — 실기를 접고 일반 전형으로`, hint: '몇 년 연습이 아깝다 · 실기가 약하면 현실적인 선택', tags: ['safe'] });
  }
  const pw = parentWord(s);
  const fo = choose(ctx, 'g3v1:field', '원서에 쓸 학과', `6월 모평 성적표가 나왔다. ${gradesText(mockGrades(s.sub))} (평균 상위 ${topFromZ(s.zC).toFixed(1)}%). 학과마다 취업률과 취업의 질도 다르다. 내신 평균은 상위 ${avgNaesin(s).toFixed(1)}%, 생기부 활동 점수는 ${Math.round(s.record)}점. 담임 선생님과의 원서 상담에서 선생님이 묻는다. "학과부터 정하자. 대학 이름을 볼 거니, 학과를 볼 거니?" ${d && d !== my ? `${pw}${jo(pw, '은/는')} 어젯밤에도 "${FIELDS[d].name} 아니면 안 된다"고 했다.` : ''}`, fOpts);
  s.applyField = fo.id;
  if (d && fo.id === d && d !== my) { s.autonomy -= 2; s.flags.parentField = true; inc(s, 'parentRel', 6); }
  if (d && fo.id !== d) { inc(s, 'parentRel', p.pStyle === 'strict' ? -10 : -4); s.autonomy += 1; }
  // 2) 전형
  const field = fo.id;
  L(s, `${FIELDS[field].name} 쪽으로 정했다. ${employText(field, 62)}`, 'info');
  const gA = mockGrades(s.sub);
  if (STEM.indexOf(field) >= 0 && gA.math >= 4) { s.flags.applyMathWeak = 2; L(s, `수학 ${gA.math}등급으로 ${FIELDS[field].name}에 지원한다. 학종 서류에서는 '수학 역량 부족'으로 읽히고, 교과에서도 수학 등급을 따로 보는 대학이 많다.`, 'bad'); }
  else if (field === 'biz' && gA.math >= 5) { s.flags.applyMathWeak = 1; L(s, `경영·경제인데 수학 ${gA.math}등급이다. 상경 계열은 수학 등급을 꽤 본다.`, 'warn'); }
  const drs = droppedList(s);
  if (drs.length) L(s, `접은 과목: ${drs.map(k => SUBJ_NAME[k]).join('·')}. ${drs.indexOf('math') >= 0 && s.track !== '자연' ? '국·영·탐 3과목만 보는 대학(광명상가 이하)이 현실적인 목표다. 그 위는 수학 반영 때문에 어렵다. ' : ''}${drs.some(k => k !== 'eng') ? '3합 최저는 남은 과목으로 맞춰야 한다.' : '영어가 들어가는 최저는 피해야 한다.'}`, 'warn');
  if (gA.kor >= 5) { s.flags.korWeakInterview = true; L(s, `국어 ${gA.kor}등급. 학종 면접에서 질문 요지를 놓치거나 논술 답안의 논지가 흔들릴 수 있다.`, 'warn'); }
  if (gA.eng >= 4) L(s, `영어 ${gA.eng}등급. 최저가 있는 전형은 영어 때문에 등급 합을 맞추기 어렵다.`, 'warn');
  if (s.flags.violence) L(s, s.flags.violence >= 2 ? '생기부에 학교폭력 조치(출석정지)가 기재돼 있다. 학종은 서류에서 거의 걸러지고, 교과·정시에서도 감점을 받는다.' : '생기부에 학교폭력 서면사과 조치가 있다. 학종 서류에서 불리하다.', 'bad');
  if (s.flags.lateHabit) L(s, '미인정 지각·결석이 출결에 남아 있다. 교과 전형 출결 감점, 학종에서는 성실성 문제로 읽힌다.', 'warn');
  if (s.flags.discipline && !s.flags.violence) L(s, '교내 징계 이력이 있다. 생기부에 직접 남지는 않았지만 담임 추천서와 행동특성란 어조가 달라졌다.', 'warn');
  if (s.flags.ged) { s.applyField = field; s.applyType = 'none'; s.susiCards = []; L(s, '검정고시 출신이라 수시는 쓰지 않고 정시에 모든 걸 건다.'); return; }
  const tOpts = SILGI[field] ? [
    { id: 'silgi', label: '실기 위주 전형 (수시 실기 + 내신·최저)', hint: `실기 ${Math.round(s.talent[FIELDS[field].talent])}점으로 승부 · 실기 당일 컨디션이 크다`, tags: ['self'], w: 1 },
    { id: 'jonghap', label: field === 'art' ? '비실기 전형 (홍익대식 서류·면접 + 수능)' : '학생부종합 (서류·면접)', hint: '실기가 약해도 서류로 · 내신·수능·최저가 더 중요해진다', tags: ['record'] },
    { id: 'none', label: '정시 (수능 + 실기)', hint: '수능 비중이 큰 대학 · 수능 하루와 실기 하루에 다 건다', tags: ['risk', 'study'] },
  ] : [
    { id: 'jonghap', label: `학생부종합 위주 (생기부 ${Math.round(s.record)}점)`, hint: '내신이 조금 낮아도 생기부로 역전 · 면접 준비와 결과 예측이 어렵다', tags: ['record'] },
    { id: 'gyogwa', label: `학생부교과 위주 (내신 상위 ${avgNaesin(s).toFixed(1)}%)`, hint: '가장 예측 가능 · 수능 최저를 못 맞추면 끝', tags: ['safe'] },
    { id: 'nonsul', label: '논술 위주', hint: '내신과 무관한 한 방 · 경쟁률 수십 대 일', tags: ['risk'] },
    SILGI[field] ? { id: 'silgi', label: '실기 위주', hint: '준비한 실력으로 승부 · 실기 당일 컨디션이 전부', tags: ['self'] } : null,
    { id: 'none', label: '수시는 최소한만. 정시 올인', hint: '수능만 잘 보면 됨 · 수능 하루에 모든 걸 건다', tags: ['risk', 'study'] },
  ];
  if (SILGI[field]) L(s, `${FIELDS[field].name} 입시: 대학마다 실기 비중이 다르다. ${field === 'art' ? '홍익대는 실기 없이 서류·수능으로, 국민대·건국대는 실기 60%, 지방 미대는 실기 70%쯤.' : field === 'perf' ? '음대는 실기 70~90%. 실용음악과는 경쟁률이 100대 1을 넘는 곳도 있다.' : '체대는 실기 40~65%, 나머지가 수능·내신. 체교과는 수능 비중이 더 크다.'}`, 'info');
  const to = choose(ctx, 'g3v1:type', '전형 고르기', `수시 원서는 6장. 담임 선생님이 상담 기록을 넘기며 말한다. "기억해. 수시에 하나라도 붙으면 정시에는 지원할 수 없어. 수능을 잘 봐도." 지금 내신은 상위 ${avgNaesin(s).toFixed(1)}%, 모의고사는 상위 ${topFromZ(s.zC).toFixed(1)}%. ${avgNaesin(s) < topFromZ(s.zC) - 3 ? '내신이 모의고사보다 좋은 편이다.' : avgNaesin(s) > topFromZ(s.zC) + 3 ? '모의고사가 내신보다 좋은 편이다.' : '내신과 모의고사가 비슷하다.'}`, tOpts);
  s.applyType = to.id;
  if (to.id !== 'none') {
    const g6 = mockGrades(s.sub);
    const so = choose(ctx, 'g3v1:strategy', '6장의 배분', `6월 모평 등급은 ${gradesText(g6)}. 이 등급이면 수능 최저 ${['2합 5', '2합 6', '3합 7', '3합 6', '4합 8'].map(t => { const [n, sm] = t.split('합 ').map(Number); return `${t} ${checkMin({ n, sum: sm }, g6).ok ? '충족' : '미충족'}`; }).join(' · ')}. ` + `입시 커뮤니티에는 "6광탈(6장 모두 탈락)" 후기와 "안정으로 썼다가 수능 대박 나서 후회" 후기가 같이 올라온다. ${s.p.wealth === 'low' ? '집에서는 재수 비용을 감당하기 어렵다.' : ''} ${s.p.confidence >= 4 ? '솔직히 수능은 잘 볼 것 같은 느낌이다.' : ''}`, [
      { id: 'up', label: '상향 위주 — 떨어져도 정시가 있다', hint: '더 높은 대학 가능 · 모두 떨어지고 정시에 몰릴 수 있다', tags: ['risk'] },
      { id: 'mid', label: '상향 2 · 적정 2 · 안정 2', hint: '균형 · 수능을 잘 보면 "수시 납치"가 될 수 있다', tags: ['safe'] },
      { id: 'safe', label: '안정 위주 — 재수는 절대 안 된다', hint: '어디든 붙음 · 내 실력보다 낮은 곳에 갈 수 있다', tags: ['safe', 'obey'] },
    ]);
    s.applyStrategy = so.id;
  }
  // 원장 직강 학원이 있으면 원장이 모의지원을 같이 봐 준다 → 상향·적정·안정을 현실적으로 짠다
  if (hasDirector(s)) { s.consultQ = 0.07; L(s, '학원 원장님이 모의지원 결과를 같이 봤다. "여긴 네 내신으로 안 돼. 대신 여기는 작년 추합이 많이 돌았어." 6장을 현실적으로 다시 짰다.', 'good'); }
  // 원서 접수: 여름에 쓰고, 결과는 수능 뒤에 나온다
  const rc = makeRng(s.seed, 'susi');
  if (to.id !== 'none') s.susiCards = makeCards(s, field, to.id, s.flags.matchUni ? 'safe' : s.applyStrategy || 'mid', 6, rc);
  else s.susiCards = makeCards(s, field, SILGI[field] ? 'silgi' : 'nonsul', 'up', 3, rc, SILGI[field] ? undefined : studentZ(s, 'jungsi', field) + 0.25);
  const st6 = minStatus(s, mockGrades(s.sub));
  L(s, `원서 접수 완료 — ${s.susiCards.map(cardText).join(' / ')}.${st6.total ? ` 지금 모의고사 기준 최저 충족 ${st6.ok}/${st6.total}곳.` : ''}`, 'info');
}

// 시험 보기: 과목마다 따로 흔들린다. 반환값은 평소 대비 평균 변화
function sitExam(s, r, sd, common, hardKey, hardD) {
  const out = {}, k0 = 1.35 - s.mental / 140;
  const sense = s.examSense || 0;
  SUB_KEYS.forEach(k => { out[k] = s.sub[k] + sense + r.normal() * sd * k0 + (common || 0) + (k === hardKey ? (hardD || 0) : 0); });
  s.csatSub = out; s.csatG = mockGrades(out);
  s.zCsat = meanSub(out); s.csatPct = topFromZ(s.zCsat);
  return s.zCsat - meanSub(s.sub);
}
// 지원한 수시 카드들의 최저 충족 여부(지금 등급 g 기준)
function minStatus(s, g) {
  const cards = (s.susiCards || []).filter(c => c.req);
  const miss = [];
  let ok = 0;
  cards.forEach(c => { const m = checkMin(c.req, g); if (m.ok) ok++; else miss.push(`${c.uni}(${reqText(c.req)}, 내 합 ${m.sum})`); });
  return { total: cards.length, ok, miss };
}
function minStatusText(s, sub) {
  const st = minStatus(s, mockGrades(sub));
  return st.total ? `지원한 수시 중 최저가 있는 곳은 ${st.total}곳, 지금 실력이면 ${st.ok}곳 충족이다.` : '';
}
function finalTurn(ctx, turn) {
  const s = ctx.s, p = s.p;
  const cats = allocCats(s, turn).filter(c => c.id !== 'activity');
  if (!s.susiCards && s.p.startTurn >= 10) s.susiCards = [];
  const def = defaultAlloc(s, cats);
  const raw = ask(ctx, { type: 'alloc', key: turn.id + ':alloc', title: '수능까지 남은 넉 달', text: `원서는 냈다. 이제 남은 건 9월 모평과 수능. 지금 모의고사는 ${gradesText(mockGrades(s.sub))}. ${minStatusText(s, s.sub)} 남은 넉 달 동안 하루 ${ALLOC_TOTAL}칸을 과목별로 어떻게 쓸까? ${s.applyType === 'none' ? '정시 올인이다. 계열별 반영 비율이 높은 과목이 결과를 가른다.' : ''}`, cats, def, total: ALLOC_TOTAL });
  const a = normAlloc(raw, cats);
  s.lastAlloc = a;
  randomEvents(ctx, turn, 2);
  // 마지막 학기 공부 효과(수능만)
  const { planned } = studySubjects(s, a, 0.13, makeRng(s.seed, 'g3s2:study'), false);
  inc(s, 'stress', planned * 1.7 - 8 - a.rest * 2.5);
  inc(s, 'mental', (a.rest - 2) * 2 + (a.friends + a.hobby) - 2);
  if (a.date) { s.romance.score += a.date * 6; inc(s, 'mental', a.date * 2); }
  const sept = mockExam(s, makeRng(s.seed, 'sept'), '9월 모평');
  const st9 = minStatus(s, sept);
  if (st9.total) L(s, `9월 모평 기준 수시 최저: ${st9.total}곳 중 ${st9.ok}곳 충족.${st9.miss.length ? ' 미충족: ' + st9.miss.join(', ') + '.' : ''}`, st9.ok === st9.total ? 'good' : st9.ok === 0 ? 'bad' : 'warn');

  const o = choose(ctx, 'g3s2:d100', '수능 D-100', `교실 칠판 오른쪽 구석에 "D-100"이 적혔다. 반 분위기가 확 바뀌었다. 누구는 폰을 공기계로 바꿨고, 누구는 "어차피 수시파"라며 웃는다. 9월 모평은 ${grade9(topFromZ(s.zC))}등급이었다. ${s.romance.status === 'dating' ? `${s.romance.partner}${jo(s.romance.partner, '은/는')} "100일만 덜 보자"고 했다.` : ''}`, [
    { id: 'allin', label: '폰을 공기계로 바꾸고 단톡방도 다 나간다', hint: '하루가 길어진다 · 고립감과 스트레스', tags: ['study'] },
    { id: 'pace', label: '지금 페이스를 그대로 유지한다', hint: '흔들림 없음 · 극적인 상승은 없다', tags: ['safe'] },
    { id: 'relax', label: '수시에 걸었다. 최저만 맞추자', hint: '마음이 편함 · 수능을 잘 봐야 하는 상황이면 위험', tags: ['fun', 'rest'] },
  ]);
  if (o.id === 'allin') { inc(s, 'lazy', -18); inc(s, 'social', -6); s.zC += 0.06 * p.diligence / 3; inc(s, 'stress', 8); L(s, '단톡방을 다 나왔다. 하루가 길어졌다.'); }
  if (o.id === 'pace') { inc(s, 'mental', 4); s.zC += 0.015; L(s, '하던 대로 했다. 흔들리지 않는 것도 실력이다.'); }
  if (o.id === 'relax') { inc(s, 'mental', 6); s.zC -= 0.05; L(s, '마음은 편했다. 수능 성적표를 받기 전까지는.'); }

  // 수능 당일
  const r = makeRng(s.seed, 'csatDay');
  const hard = r.pick(['국어', '수학', '영어']);
  const c = choose(ctx, 'g3s2:csat', '수능 당일, 시험장', `11월, 낯선 학교 교실. 감독관이 시간을 알린다. "종료 20분 전입니다." ${hard} 시험이 역대급으로 어렵다. ${hard === '국어' ? '독서 지문 하나를 붙잡고 12분을 썼는데 아직 문학 두 세트와 선택과목이 남았다.' : hard === '수학' ? '22번은커녕 15번부터 막혔다. 뒤에 아직 손도 안 댄 문제가 다섯 개다.' : '빈칸 추론 세 문제에서 시간이 녹았다. 듣기 끝나고 남은 시간이 거의 없다.'} 옆자리 수험생이 한숨을 쉰다. 손이 떨린다.`, [
    { id: 'skip', label: '한 지문(문제)을 과감히 버리고 아는 것부터 푼다', hint: '남은 문제를 살림 · 버린 문제가 쉬웠다면 뼈아프다', tags: ['risk'] },
    { id: 'hold', label: '끝까지 붙잡는다. 포기는 없다', hint: '풀어내면 대박 · 시간이 다 녹을 수 있다', tags: ['study'] },
    { id: 'breath', label: '펜을 내려놓고 10초 심호흡한 뒤 순서대로 푼다', hint: '평정심 회복 · 10초가 아깝게 느껴진다', tags: ['self', 'rest'] },
  ]);
  // 고른 대처는 어려웠던 그 과목에 크게, 몸·마음 상태는 모든 과목에 들어간다
  const hardKey = { 국어: 'kor', 수학: 'math', 영어: 'eng' }[hard];
  let choiceD = 0;
  if (c.id === 'skip') choiceD = p.comprehension >= 3 ? 0.15 : -0.08;
  if (c.id === 'hold') choiceD = r.normal() * 0.12 - 0.05;
  if (c.id === 'breath') choiceD = 0.05 + (p.grit - 3) * 0.08;
  let common = 0;
  if (s.flags.breakupG3) common -= 0.1;
  if (s.health < 30) common -= 0.08;
  if (s.stress > 80) common -= 0.06;
  if (hardKey === 'eng' || hardKey === 'kor') common += 0;
  let fateKey = null;
  if (r.chance(0.05)) { fateKey = r.pick(SUB_KEYS); Lf(s, { kor: '1교시 국어 도중 앞자리 수험생이 쓰러져 시험이 10분 중단됐다. 다시 시작했을 때 지문이 눈에 안 들어왔다.', math: '수학 시간, 배가 뒤틀리기 시작했다. 화장실에 다녀오느라 15분을 잃었다.', eng: '영어 듣기 방송이 중간에 끊겼다가 다시 나왔다. 3번부터 7번까지 놓쳤다.', inq: '탐구 시간, 시계가 멈춰 있었다. 종료 5분 전 안내에 서른 문제 중 여덟 개가 비어 있었다.' }[fateKey]); }
  const day = sitExam(s, r, 0.11, common, hardKey, choiceD);
  if (fateKey) { s.csatSub[fateKey] -= 0.45; s.csatG = mockGrades(s.csatSub); s.zCsat = meanSub(s.csatSub); s.csatPct = topFromZ(s.zCsat); }
  const pct = s.csatPct;
  const diffWord = day > 0.12 ? '평소보다 훨씬 잘 봤다.' : day < -0.12 ? '평소 실력이 나오지 않았다.' : '평소 실력만큼 나왔다.';
  L(s, `수능 가채점 — ${gradesText(s.csatG)} (평균 상위 ${pct.toFixed(1)}%). ${diffWord}`, day < -0.12 ? 'bad' : day > 0.12 ? 'good' : 'info');
  const stc = minStatus(s, s.csatG);
  if (stc.total) L(s, `수시 최저 가채점: ${stc.total}곳 중 ${stc.ok}곳 충족.${stc.miss.length ? ' 미충족: ' + stc.miss.join(', ') + '.' : ''}`, stc.ok === stc.total ? 'good' : stc.ok === 0 ? 'bad' : 'warn');
  if (s.flags.breakupG3) L(s, '고3 때의 이별이 끝까지 발목을 잡았다.', 'warn');
  if (s.romance.status === 'pause') { s.romance.status = 'dating'; L(s, `수능이 끝난 날, ${s.romance.partner}에게 전화했다.`); }
}

// ── 입시 결과 ────────────────────────────────────────────
function admissions(ctx) {
  const s = ctx.s, p = s.p;
  const field = s.applyField || topInterest(s);
  if (SILGI[field]) silgiDay(s, field, makeRng(s.seed, 'silgiDay'));
  const susi = rollCards(s, s.susiCards || [], makeRng(s.seed, 'susiRoll'));
  s.susi = susi;
  // 면접 당일의 운
  { const rf = makeRng(s.seed, 'susiFate'); const pi = susi.findIndex(c => c.pass && c.type === 'jonghap'); if (pi >= 0 && rf.chance(0.06)) { susi[pi].pass = false; Lf(s, `${susi[pi].uni} 면접 날 지하철이 멈췄다. 20분 지각, 면접은 3분 만에 끝났다.`); }
    else if (!susi.some(c => c.pass) && susi.length && rf.chance(0.07)) { const ci = susi.reduce((b, c, i) => (c.minOk && c.label !== '상향' && (b < 0 || c.P > susi[b].P) ? i : b), -1); if (ci >= 0) { susi[ci].pass = true; Lf(s, `${susi[ci].uni} ${susi[ci].major} 예비 번호가 돌았다. 추가합격.`); } } }
  const passed = susi.filter(c => c.pass);
  L(s, '수시 결과 — ' + (susi.length ? susi.map(c => `${c.uni} ${c.major}(${TYPE_NAMES[c.type]}) ${c.pass ? '합격' : c.minOk ? (c.req ? `불합격(최저 ${reqText(c.req)} 충족, 합 ${c.minSum})` : '불합격') : `최저 미충족(${reqText(c.req)} 필요, 내 합 ${c.minSum})`}`).join(' / ') : '지원 안 함'), passed.length ? 'good' : 'bad');
  const minFail = susi.filter(c => !c.minOk).length;
  if (minFail) L(s, `수시 ${susi.length}장 중 ${minFail}장이 수능 최저를 못 맞춰 면접·서류와 상관없이 떨어졌다.`, 'bad');
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
// 실기 당일: 몇 달 연습이 하루에 걸린다. 운이 꽤 크다
function silgiDay(s, field, r) {
  const d = r.normal() * 0.28;
  let note = '';
  if (field === 'sport' && r.chance(0.08)) { s.silgiDay = d - 0.6; L(s, '실기 당일, 첫 종목 제자리멀리뛰기에서 착지하며 발목을 접질렸다. 남은 종목을 절뚝이며 뛰었다. (운)', 'fate'); return; }
  if (field === 'perf' && r.chance(0.08)) { s.silgiDay = d - 0.5; L(s, '실기 전날 밤 목이 잠겼다. 당일 아침 고음이 갈라졌다. (운)', 'fate'); return; }
  if (field === 'art' && r.chance(0.06)) { s.silgiDay = d - 0.5; L(s, '실기 시험장에 들어가니 출제 주제가 올해 처음 보는 유형이었다. 손이 굳었다. (운)', 'fate'); return; }
  s.silgiDay = d;
  if (d > 0.3) note = '실기 당일 컨디션이 최고였다. 평소보다 잘 나왔다.';
  else if (d < -0.3) note = '실기 당일 유난히 손이 안 풀렸다. 평소 실력이 안 나왔다.';
  else note = '실기는 평소 실력만큼 나왔다.';
  L(s, note + (Math.abs(d) > 0.3 ? ' (운)' : ''), d > 0.3 ? 'good' : d < -0.3 ? 'bad' : 'info');
}
function jungsiRound(ctx, field, key) {
  const s = ctx.s;
  const w = subjWeights(field);
  const o = choose(ctx, key + ':strategy', '정시 원서 3장', `수능 성적표가 나왔다. ${gradesText(s.csatG)}. ${jungsiFitText(Object.assign({}, s, { applyField: field }), s.csatSub)}. ${FIELDS[field].name} 계열 반영 비율은 국어 ${Math.round(w.kor * 100)} · 수학 ${Math.round(w.math * 100)} · 영어 ${Math.round(w.eng * 100)} · 탐구 ${Math.round(w.inq * 100)}%. 가·나·다군에 한 장씩, 세 장을 쓸 수 있다. 입시 사이트의 모의지원 결과는 칸마다 "적정", "소신", "위험"이 섞여 있다. 다군은 해마다 합격선이 크게 출렁인다.`, [
    { id: 'up', label: '상향 — 한 장이라도 대박을 노린다', hint: '더 높은 대학 가능 · 셋 다 떨어지면 재수', tags: ['risk'] },
    { id: 'mid', label: '적정 — 상향 하나, 적정 하나, 안정 하나', hint: '하나는 붙을 가능성 · 큰 반전은 어렵다', tags: ['safe'] },
    { id: 'safe', label: '안정 — 무조건 붙는 곳으로', hint: '확실한 합격 · 실력보다 낮은 대학', tags: ['safe', 'obey'] },
  ]);
  const r = makeRng(s.seed, key);
  const cards = rollCards(s, makeCards(s, field, 'jungsi', o.id, 3, r), r);
  // 다군 '펑크'(합격선 붕괴)나 '폭발'은 해마다 있다
  if (r.chance(0.04)) { cards[2].pass = true; cards[2].punk = true; Lf(s, `${cards[2].uni} ${cards[2].major}에 '펑크'가 났다. 작년보다 합격선이 크게 내려갔다.`); }
  else if (r.chance(0.05)) { const si = cards.findIndex(c => c.label === '안정' && c.pass); if (si >= 0) { cards[si].pass = false; cards[si].boom = true; Lf(s, `${cards[si].uni} ${cards[si].major}에 '폭발'이 났다. 안정이라던 곳에 지원자가 몰려 합격선이 치솟았다.`); } }
  else if (!cards.some(c => c.pass) && r.chance(0.07)) { const si = cards.length - 1; cards[si].pass = true; cards[si].waitlist = true; Lf(s, `${cards[si].uni} ${cards[si].major} 예비 23번. 2월 마지막 날 추가합격 전화가 왔다.`); }
  s.jungsi = cards;
  L(s, '정시 결과 — ' + cards.map((c, i) => `${'가나다'[i]}군 ${c.uni} ${c.major}${c.cut != null ? `(70%컷 ${c.cut.toFixed(1)} · 내 점수 ${c.score.toFixed(1)})` : ''} ${c.pass ? '합격' + (c.punk ? '(펑크 덕분!)' : '') : '불합격'}`).join(' / '), cards.some(c => c.pass) ? 'good' : 'bad');
  return pickUniversity(ctx, cards.filter(c => c.pass), key);
}
function pickUniversity(ctx, passed, key) {
  const s = ctx.s, p = s.p;
  const canRetry = s.attempts < 2;
  const goal = GOALS[p.goal] || GOALS.inseoul;
  const bestP = passed.reduce((m, c) => Math.max(m, c.tier.prestige), 0);
  const opts = passed.map((c, i) => ({ id: 'u' + i, label: `${c.uni} ${c.major} 등록`, hint: employText(c.field, c.tier.prestige, c.tier.teacher), tags: c.tier.gi <= goal.gi ? ['safe', 'self'] : ['safe'],
    w: (c.tier.prestige - bestP) / 6 + (c.field === topInterest(s) ? 0.6 : 0) + (employOf(c.field, c.tier.prestige, c.tier.teacher).rate - 60) / 25 + 1.5 }));
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
  const o = choose(ctx, 'retake' + n + ':how', s.turnLabel, n === 1 ? `2월. 친구들은 새내기 OT에 간다. 나는 재수 학원 상담실에 앉아 있다. 상담 실장이 말한다. "재수생 중에 성적 오르는 건 절반이 안 돼요. 관리가 전부예요." ${p.wealth === 'low' ? '엄마가 통장 잔고를 확인하는 걸 봤다.' : ''}` : '한 번 더. 동기들은 벌써 2학년이다. 이번이 진짜 마지막이다. 부모님 얼굴을 똑바로 보기가 어렵다.', [
    p.wealth !== 'low' || s.money > 30 ? { id: 'academy', label: '재수종합학원 (월 250만 원, 아침 7시 반~밤 10시)', hint: '철저한 관리 · 큰 비용, 숨 막히는 일상', tags: ['study', 'obey'] } : null,
    { id: 'self', label: '독학재수 (관리형 독서실 + 인강)', hint: '돈이 덜 들고 내 페이스 · 무너져도 아무도 모른다', tags: ['self', 'study'] },
    { id: 'work', label: '오전엔 알바, 오후엔 공부', hint: '집에 부담 안 줌 · 공부 시간이 반이다', tags: ['work'] },
  ]);
  const r = makeRng(s.seed, 'retake' + n);
  // 재수 중 이벤트
  if (s.romance.status === 'dating' && r.chance(0.55)) { breakUp(s, 'retake'); inc(s, 'mental', -10); L(s, `대학생이 된 ${s.romance.partner}${jo(s.romance.partner, '와/과')}는 점점 연락이 뜸해졌고, 결국 헤어졌다.`, 'bad'); }
  const t = choose(ctx, 'retake' + n + ':sns', '5월의 인스타', `5월, 대학 축제 시즌. 친구들 인스타에 과잠, 축제 무대, MT 사진이 줄줄이 올라온다. ${s.bestFriend ? `${s.bestName}${jo(s.bestName, '이/가')} "주말에 잠깐 나와. 밥 사 줄게"라고 한다.` : ''} 6월 모평은 3주 뒤다.`, [
    { id: 'delete', label: '인스타를 지운다', hint: '흔들림이 줄어든다 · 세상과 단절된 느낌', tags: ['study'] },
    { id: 'look', label: '가끔 본다. 자극이 된다', hint: '동기 부여 · 비교하다 무너질 수도', tags: ['safe'] },
    { id: 'meet', label: '주말엔 친구들을 만난다', hint: '숨통이 트임 · 리듬이 깨진다', tags: ['social', 'fun'] },
  ]);
  let g = 0.1 + 0.07 * (p.diligence - 3) + 0.05 * (p.grit - 3) - s.lazy / 300 + r.normal() * 0.12;
  if (o.id === 'academy') { g += 0.09; s.money -= 30; }
  if (o.id === 'work') { g -= 0.06; s.money += 10; s.flags.mature = true; }
  if (t.id === 'delete') { g += 0.03; inc(s, 'social', -8); }
  if (t.id === 'meet') { g -= 0.04; inc(s, 'mental', 6); }
  if (n === 2) { g -= 0.04; inc(s, 'mental', -8); }
  if (s.money < 0) { s.money = 0; inc(s, 'parentRel', -6); }
  inc(s, 'mental', -6); inc(s, 'lazy', -5);
  s.zC += g * damp(s.zC);
  const day = sitExam(s, r, 0.1, 0, null, 0);
  L(s, `${n === 1 ? '재수' : '삼수'} 수능 — ${gradesText(s.csatG)} (평균 상위 ${topFromZ(s.zCsat).toFixed(1)}%). ${g + day > 0.15 ? '확실히 올랐다.' : g + day < 0 ? '오히려 떨어졌다. 눈앞이 캄캄했다.' : '조금 올랐다.'}`, g + day > 0.15 ? 'good' : g + day < 0 ? 'bad' : 'info');
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
  s.col = { gpa: clamp(3.2 + (p.diligence - 3) * 0.14 - Math.max(0, s.lazy - 40) / 90 + r0.normal() * 0.1, 1.8, 4.4), spec: clamp(10 + s.record / 6, 0, 100), network: s.social / 2 + (p.pJob === 'pro' ? 10 : 0), effort: 0 };
  s.fit = fitOf(s, u.field);
  // 고교 때 놓은 과목은 대학 전공 기초에서 다시 돌아온다
  const G = endG(s);
  if (STEM.indexOf(u.field) >= 0 && G.math >= 4) { s.col.gpa -= 0.25; inc(s, 'mental', -6); s.flags.fMath = true; L(s, `수학 ${G.math}등급으로 들어온 ${u.major}. 1학년 미적분학·일반물리에서 F가 나왔다. 재수강해야 한다.`, 'bad'); }
  else if (STEM.indexOf(u.field) >= 0 && G.math <= 2) { s.col.gpa += 0.1; L(s, '고등학교 때 다진 수학 덕분에 전공 기초 과목이 수월했다.', 'good'); }
  if ((u.field === 'biz' || u.field === 'soc') && G.math >= 5) { s.col.gpa -= 0.15; L(s, `경제원론·통계학에서 수식이 나오자 손을 놓았다. C를 받았다.`, 'warn'); }
  if (G.kor >= 4) { s.col.gpa -= 0.12; s.col.spec -= 3; L(s, `국어 ${G.kor}등급 때의 습관이 남았다. 리포트마다 "논지가 불분명하다"는 코멘트가 달린다.`, 'warn'); }
  if (G.eng >= 4) { s.col.gpa -= 0.1; s.col.spec -= 5; L(s, `영어 ${G.eng}등급. 원서 교재와 영어 강의를 따라가기 버겁고, 토익 점수도 낮다.`, 'warn'); }
  if (STEM.indexOf(u.field) >= 0 && G.inq >= 5) { s.col.gpa -= 0.1; L(s, '탐구 기초가 부족해 일반화학·생물학 실험 과목이 힘들다.', 'warn'); }
  if (s.flags.parentField && s.fit < 0.7) L(s, `부모님이 원한 ${FIELDS[u.field].name}. 첫 학기부터 '내가 왜 여기 있지?'라는 생각이 들었다.`, 'warn');

  // 1) 1~2학년
  s.turnLabel = '대학 1~2학년';
  const goal = GOALS[p.goal] || GOALS.inseoul;
  const o1 = choose(ctx, 'col1', '스무 살, 첫 학기', `${u.name} ${u.major}. 3월 첫 주, 과 단톡방이 하루 300개씩 울린다. 개강총회, 동아리 홍보, 선배들의 밥약. 시간표를 내가 짜고, 출석을 부르는 사람은 없다. ${u.gi > goal.gi ? `솔직히 목표였던 ${goal.name}보다 낮은 학교라 마음 한구석이 계속 불편하다.` : ''} ${p.wealth === 'low' ? '등록금 고지서와 자취방 월세가 같은 날 나왔다.' : ''}`, [
    { id: 'party', label: '고등학교 때 못 논 거 몰아서 논다', hint: '평생 친구와 추억 · 1학년 학점은 졸업까지 따라온다', tags: ['fun', 'social'] },
    { id: 'grind', label: '학점 관리부터. 장학금을 노린다', hint: '높은 학점과 장학금 · 과에서 존재감이 없다', tags: ['study'] },
    { id: 'club', label: '학회·동아리에 들어가 사람을 만난다', hint: '선배 인맥과 정보 · 학점은 적당히', tags: ['social', 'record'] },
    { id: 'work', label: '알바로 생활비·등록금을 번다', hint: '경제적 독립 · 공부와 사람 둘 다 시간이 없다', tags: ['work'] },
    (u.gi > goal.gi && u.gi >= 2 && s.attempts < 2) ? { id: 'retake', label: '휴학계는 안 내고 몰래 반수한다', hint: '목표 대학을 다시 노림 · 실패하면 1학년이 통째로 날아간다', tags: ['risk', 'study'] } : null,
  ]);
  const c = s.col;
  if (o1.id === 'party') { c.gpa -= 0.45; inc(s, 'social', 12); inc(s, 'mental', 8); inc(s, 'lazy', 8); s.flags.partyCollege = true; L(s, '술자리, MT, 축제. 1학년 1학기 학점은 2점대였다.'); }
  if (o1.id === 'grind') { c.gpa += 0.35; c.spec += 5; inc(s, 'social', -4); L(s, '과탑 장학금을 받았다. 동기들은 내 이름만 안다.', 'good'); }
  if (o1.id === 'club') { c.network += 15; c.spec += 10; c.gpa -= 0.1; L(s, '학회에서 만난 선배들이 진로 얘기를 많이 해 줬다.'); }
  if (o1.id === 'work') { s.money += 20; c.gpa -= 0.2; inc(s, 'mental', -4); c.spec += 3; s.flags.work = true; L(s, '주 20시간 알바. 수업 끝나면 바로 가게로 간다.'); }
  if (o1.id === 'retake') {
    const r = makeRng(s.seed, 'banSu');
    const g = 0.04 + 0.06 * (p.diligence - 3) + r.normal() * 0.12 - s.lazy / 350;
    s.zC += g; sitExam(s, r, 0.09, 0, null, 0);
    const list = tierList(s.applyField || u.field, s);
    const idx = estimateIdx(s, list, compositeZ(s.csatSub, u.field), u.field, r, 0);
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
    ? choose(ctx, 'col2', '입영 통지서', `1학년 겨울. 과 동기 남자애들 단톡방이 "입대 날짜 공유방"이 됐다. 병무청 앱에는 육군 대기 인원이 표시되고, 공군은 경쟁률이 3 대 1이다. ${s.romance.status === 'dating' ? `${s.romance.partner}${jo(s.romance.partner, '은/는')} "기다릴게"라고 했지만 목소리가 떨렸다.` : ''}`, [
      { id: 'now', label: '1학년 마치고 바로 육군 입대', hint: '빨리 끝냄 · 18개월 동안 모든 게 멈춘다', tags: ['safe'] },
      { id: 'air', label: '공군·카투사에 지원한다', hint: '자기계발 시간이 있음 · 떨어지면 시간만 버린다', tags: ['risk', 'study'] },
      { id: 'later', label: '2학년 마치고 간다', hint: '학교에 적응한 뒤 입대 · 복학하면 동기가 없다', tags: ['safe'] },
      ['eng', 'cs', 'sci'].indexOf(s.uni.field) >= 0 ? { id: 'rnd', label: '대학원 진학 후 전문연구요원을 노린다', hint: '군 복무 대신 연구 · 학점과 연구실 경쟁이 치열하다', tags: ['study', 'risk'] } : null,
    ])
    : choose(ctx, 'col2', '2학년, 쉬어 갈까', `2학년 1학기가 끝났다. 동기들 사이에서 "교환학생 붙었다", "휴학하고 인턴 한다", "그냥 빨리 졸업할래"가 오간다. 학과 사무실 게시판에는 교환학생 모집 공고가 붙어 있다. 학점 3.4 이상, 토플 점수 필요.`, [
      { id: 'exchange', label: '교환학생에 지원한다', hint: '외국 경험과 어학 · 비용이 들고 학점 기준이 있다', tags: ['risk', 'self'] },
      { id: 'intern', label: '휴학하고 인턴·대외활동', hint: '실무 경력 · 졸업이 1년 늦어진다', tags: ['record'] },
      { id: 'straight', label: '쉬지 않고 바로 졸업한다', hint: '빠른 취업 시장 진입 · 쌓아 둔 경험이 적다', tags: ['safe', 'study'] },
      { id: 'rest', label: '휴학하고 여행·쉬기', hint: '번아웃 회복 · 공백기를 설명해야 한다', tags: ['rest', 'fun'] },
    ]);
  const r2 = makeRng(s.seed, 'col2');
  if (o2.id === 'now' || o2.id === 'later') { s.age += 2; inc(s, 'lazy', -8); s.flags.army = true; c.gpa -= o2.id === 'later' ? 0 : 0.05; if (s.romance.status === 'dating' && r2.chance(0.6)) { breakUp(s, 'army'); L(s, `군대에 있는 동안 ${s.romance.partner}${jo(s.romance.partner, '와/과')} 헤어졌다. 흔한 이야기라는데 하나도 흔하지 않았다.`, 'bad'); } L(s, '18개월. 전역하던 날, 시간을 허투루 쓰지 않겠다고 다짐했다.'); }
  if (o2.id === 'air') { if (r2.chance(0.45 + (p.diligence - 3) * 0.08)) { s.age += 2; c.spec += 12; s.flags.army = true; L(s, '합격. 군 생활 동안 토익과 자격증을 땄다.', 'good'); } else { s.age += 2; s.flags.army = true; L(s, '떨어지고 결국 육군으로 갔다.'); } }
  if (o2.id === 'rnd') { s.flags.rndPlan = true; c.gpa += 0.1; L(s, '학점과 연구실 경력을 쌓기 시작했다.'); }
  if (o2.id === 'exchange') { if (endG(s).eng >= 4) { L(s, `교환학생은 어학 성적이 필요하다. 영어 ${endG(s).eng}등급 실력으로는 토플 기준을 넘지 못했다.`, 'bad'); } else if (c.gpa >= 3.4 && (s.money >= 30 || p.wealth === 'high')) { c.spec += 14; s.talent.verbal += 10; s.money -= 15; s.flags.exchange = true; s.age += 0.5; L(s, '한 학기 동안 유럽에서 지냈다. 세상이 넓다는 걸 알았다.', 'good'); } else { L(s, '학점이나 비용 문제로 선발되지 못했다.', 'warn'); } }
  if (o2.id === 'intern') { c.spec += 12; s.age += 1; L(s, '스타트업 인턴. 일 잘한다는 소리를 처음 들었다.', 'good'); }
  if (o2.id === 'straight') { c.gpa += 0.1; s.flags.fastGrad = true; L(s, '쉬지 않고 달렸다. 동기들보다 1년 빨리 졸업 준비를 시작했다.'); }
  if (o2.id === 'rest') { s.age += 1; inc(s, 'mental', 12); inc(s, 'lazy', 5); L(s, '한 학기를 쉬었다. 마음이 좀 편해졌다.'); }
  collegeEvent(ctx, 'col2');

  // 3) 전공 적성
  s.fit = fitOf(s, s.uni.field);
  if (s.fit < 0.6) {
    const my = topInterest(s);
    const o3 = choose(ctx, 'col3', '전공이 안 맞는다', `3학년 전공 필수 수업 시간. 교수님 말이 한 마디도 들어오지 않는다. 노트 귀퉁이에 낙서한 건 ${FIELDS[my].name} 관련된 것들뿐이다. ${s.flags.parentField ? '이 학과는 부모님이 원해서 왔다. ' : ''}이번 학기 학점은 ${s.col.gpa.toFixed(2)}. 같은 과 선배는 "다들 그래, 졸업하면 전공 상관없어"라고 하고, 다른 선배는 "아니다 싶으면 빨리 틀어"라고 한다.`, [
      { id: 'stay', label: '버틴다. 졸업장은 따야 한다', hint: '안정적인 졸업 · 남은 2년이 고역이다', tags: ['safe', 'obey'] },
      { id: 'double', label: `${my === 'cs' || my === 'biz' ? FIELDS[my].name : '컴퓨터·경영'} 복수전공을 한다`, hint: '취업 선택지가 넓어짐 · 졸업이 한 학기 늦어진다', tags: ['study', 'self'] },
      { id: 'switch', label: `${FIELDS[my].name} 쪽으로 전과·편입을 시도한다`, hint: '진짜 원하는 공부 · 학점이 낮으면 떨어진다', tags: ['risk', 'self'] },
      { id: 'drop', label: '자퇴하고 처음부터 다시 시작한다', hint: '완전한 새 출발 · 학력과 부모님의 신뢰를 잃는다', tags: ['risk', 'rebel'] },
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
    const o3 = choose(ctx, 'col3', '3학년의 시간표', `${s.uni.major} 공부가 꽤 재미있다. 학점은 ${s.col.gpa.toFixed(2)}. 취업 커뮤니티에서는 "3학년 때 뭘 했는지가 서류를 가른다"고 한다. 연구실 학부연구생 모집, 대기업 공모전, 토익 학원 광고가 같은 주에 나왔다.`, [
      { id: 'lab', label: '학부연구생으로 연구실에 들어간다', hint: '대학원·연구직 길이 열림 · 교수님 일정에 묶인다', tags: ['study', 'record'] },
      { id: 'contest', label: '공모전·대외활동', hint: '이야깃거리와 인맥 · 수상 못 하면 남는 게 적다', tags: ['record', 'social'] },
      { id: 'cert', label: '토익·자격증 같은 정량 스펙', hint: '서류 통과에 확실 · 남들과 차별점은 없다', tags: ['safe', 'study'] },
      { id: 'enjoy', label: '마지막 대학 생활을 즐긴다', hint: '후회 없는 20대 초반 · 취업 준비가 늦어진다', tags: ['fun'] },
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
  const emp = employOf(u.field, u.prestige, u.teacher).rate;
  return (emp - 62) * 0.25 + u.prestige * 0.36 + gpaS * 0.14 + clamp(c.spec, 0, 100) * 0.24 + clamp(c.network, 0, 100) * 0.05 + s.mental * 0.08 + c.effort * 6 + s.fit * 9 - s.lazy * 0.15 + subjCareerBonus(s, u.field) + r.normal() * 3;
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
  } else if (SILGI[f]) {
    const tl = Math.round(s.talent[FIELDS[f].talent]);
    if (f === 'art') {
      opts.push({ id: 'artist', label: `전업 작가·웹툰 연재에 도전 (실기 ${tl})`, hint: '되면 내 이름으로 산다 · 대부분 3년 안에 통장이 빈다', tags: ['risk', 'self'], w: (tl - 78) / 8 + (p.confidence - 3) * 0.3 });
      opts.push({ id: 'job', label: '디자인 회사·기업 디자이너로 취업', hint: '월급은 나온다 · 야근이 많고 초봉이 낮다', tags: ['safe'], w: 1 });
      opts.push({ id: 'acadT', label: '입시미술 학원 강사', hint: '수요가 꾸준하다 · 저녁·주말 근무', tags: ['safe', 'work'], w: 0.3 });
      opts.push({ id: 'grad', label: '유학·대학원 (순수미술·디자인)', tags: ['study', 'self'], w: p.wealth === 'high' ? 0.3 : -1 });
    } else if (f === 'perf') {
      opts.push({ id: 'musician', label: `전업 뮤지션 — 오디션·음원·공연 (실기 ${tl})`, hint: '무대에 산다 · 수입은 몇 년간 교통비 수준', tags: ['risk', 'self'], w: (tl - 78) / 8 + (p.confidence - 3) * 0.3 });
      if (/성악|기악|관현악|피아노|작곡/.test(u.major)) opts.push({ id: 'orchestra', label: '교향악단·합창단 단원 공채', hint: '안정적 · 자리가 한 해 몇 개 안 난다', tags: ['safe', 'study'], w: 0.5 });
      opts.push({ id: 'acadT', label: '실용음악 학원 강사·보컬 트레이너', hint: '음악으로 먹고산다 · 저녁·주말 근무', tags: ['safe', 'work'], w: 0.6 });
      opts.push({ id: 'job', label: '공연기획사·음반사·음악 외 일반 취업', hint: '월급은 나온다 · 전공은 반쯤 접는다', tags: ['safe'], w: 0.4 });
    } else {
      if (u.teacher) opts.push({ id: 'teacher', label: '체육 임용고시 (경쟁률 높음)', tags: ['safe', 'study', 'obey'], w: 1 });
      opts.push({ id: 'police', label: '경찰·소방 공채 (체력 + 필기)', hint: '체대 출신의 정석 · 필기(국어·영어·형사법)가 관건', tags: ['safe', 'study'], w: 0.9 + (p.pDesire === 'stable' ? 0.5 : 0) });
      opts.push({ id: 'trainer', label: '트레이너·필라테스·재활 (창업 포함)', hint: '몸으로 번다 · 소득 편차가 크다', tags: ['self', 'work'], w: 0.5 + (p.social - 3) * 0.3 });
      opts.push({ id: 'job', label: '스포츠 브랜드·구단·협회 취업', hint: '안정적인 쪽 · 자리가 많지 않다', tags: ['safe'], w: 0.3 });
    }
    opts.push({ id: 'civil', label: '공무원 시험 (7·9급)', tags: ['safe', 'obey', 'study'], w: (p.pDesire === 'stable' ? 0.5 : -0.6) });
    if (s.flags.creator) opts.push({ id: 'creator', label: '크리에이터·프리랜서', tags: ['risk', 'fun', 'self'], w: 0 });
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
  if ((desire === 'biz' || s.flags.familyBiz) && !opts.find(o => o.id === 'family')) opts.push({ id: 'family', label: '부모님 사업을 물려받는다', tags: ['obey', 'safe'] });
  const o = choose(ctx, 'car1', '어떤 길로 갈까', text, opts);
  s.careerPath = o.id;
  if (['soe', 'civil', 'teacher', 'family'].indexOf(o.id) >= 0 && (desire === 'stable' || desire === 'biz' || desire === 'money')) { inc(s, 'parentRel', 8); s.autonomy -= 1; }
  if (o.id === 'startup' || o.id === 'creator') { if (p.pStyle === 'strict' || p.pStyle === 'anxious') inc(s, 'parentRel', -8); s.autonomy += 1; }

  const e = choose(ctx, 'car2', '얼마나 걸 것인가', `${{ job: '자소서 마감이 다섯 개 겹쳤다.', soe: 'NCS 문제집이 책상에 세 권 쌓였다.', civil: '노량진 독서실 한 달 이용권을 끊었다.', pro: '수험 기간은 보통 2~3년이라고 한다.', grad: '대학원 입학 면접이 다음 달이다.', startup: '정부 지원사업 서류 마감이 2주 남았다.', creator: '첫 영상 촬영 장비를 샀다.', abroad: '영어 면접 준비를 시작했다.', teacher: '임용고시는 1년에 한 번뿐이다.' }[o.id] || '준비가 시작됐다.'} ${s.romance.status === 'dating' ? `${s.romance.partner}${jo(s.romance.partner, '은/는')} "요즘 우리 얼굴 본 지 2주 됐어"라고 한다.` : ''} ${s.p.wealth === 'low' ? '생활비는 아직 알바로 번다.' : ''}`, [
    { id: 'all', label: '올인. 연애도 친구도 잠시 멈춘다', hint: '합격 확률이 가장 높다 · 관계와 마음이 닳는다', tags: ['study'] },
    { id: 'bal', label: '병행. 내 삶도 지키면서 간다', hint: '지속 가능함 · 경쟁자보다 시간이 적다', tags: ['safe', 'social'] },
    { id: 'easy', label: '적당히. 되면 좋고', hint: '마음이 편함 · 떨어질 가능성이 크다', tags: ['fun', 'rest'] },
  ]);
  s.col.effort = { all: 1.4, bal: 0.8, easy: 0.1 }[e.id];
  if (e.id === 'all') { inc(s, 'social', -10); s.romance.score -= 15; inc(s, 'stress', 10); if (s.romance.status === 'dating' && s.romance.score < 35) { breakUp(s, 'car'); L(s, `"너한테 나는 늘 2순위야." ${s.romance.partner}${jo(s.romance.partner, '와/과')} 헤어졌다.`, 'bad'); } }
  if (e.id === 'easy') { inc(s, 'mental', 5); inc(s, 'lazy', 6); }

  s.turnLabel = '20대 후반';
  let res = resolveCareer(s, o.id, makeRng(s.seed, 'car:' + o.id + ':1'), 1);
  if (!res.ok) {
    L(s, res.failText, 'bad');
    const o2 = choose(ctx, 'car3', '불합격 문자', `${res.failText} 나이는 ${Math.floor(s.age + 4)}살. 친구들 중 절반은 이미 회사에 다닌다. ${s.p.pStyle === 'warm' ? '엄마는 "천천히 해도 돼"라고 하신다.' : s.p.pStyle === 'strict' ? '아빠는 저녁 식탁에서 말이 없다.' : '부모님께 결과를 말하지 못했다.'} 통장 잔고는 두 달 치 생활비다.`, [
      { id: 'retry', label: '한 번만 더 도전한다', hint: '이번엔 될 수도 · 또 떨어지면 공백이 길어진다', tags: ['risk', 'study'] },
      { id: 'lower', label: '눈높이를 낮춰 지금 갈 수 있는 곳에 간다', hint: '바로 수입이 생김 · 처음 원하던 자리는 아니다', tags: ['safe'] },
      { id: 'pivot', label: '완전히 다른 길을 찾는다', hint: '진짜 맞는 일을 찾을 수도 · 처음부터 다시', tags: ['self', 'risk'] },
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
    // ── 예체능 ──  재능이 바탕이지만 운이 꽤 크다. 바르게 살아도 안 풀리는 사람이 많은 동네다
    case 'artist': {
      const sc = s.talent.art * 0.5 + clamp(s.col.spec, 0, 100) * 0.15 + eff * 8 + p.confidence * 2 + p.diligence * 2 - s.lazy * 0.2 + r.normal() * 10 + (attempt - 1) * 4;
      if (sc > 92) return mk('art-webtoon', '네이버 웹툰 정식 연재 작가', 7500, 'art', 0);
      if (sc > 80) return mk('art-solo', '개인전을 여는 작가 겸 강사', 3900, 'art', 1);
      if (sc > 64) return mk('art-illust', '외주로 버티는 일러스트레이터', 2700, 'art', 2);
      return { ok: false, failText: '3년 동안 공모전과 연재 심사에서 떨어졌다. 통장 잔고가 바닥났다.' };
    }
    case 'musician': {
      const sc = s.talent.perf * 0.5 + eff * 8 + p.social * 2 + p.grit * 2 - s.lazy * 0.2 + r.normal() * 11 + (attempt - 1) * 4;
      if (sc > 93) return mk('mus-chart', '음원 차트에 오른 싱어송라이터', 9000, 'perf', 0);
      if (sc > 80) return mk('mus-session', '세션·공연으로 먹고사는 뮤지션', 4200, 'perf', 1);
      if (sc > 64) return mk('mus-indie', '홍대 공연 + 레슨으로 버티는 뮤지션', 2600, 'perf', 2);
      return { ok: false, failText: '오디션에서 번번이 떨어졌다. 공연 수입은 교통비도 안 됐다.' };
    }
    case 'orchestra': {
      const P = sigmoid((s.talent.perf - 80) / 6 + eff * 0.5 + (u.prestige - 80) / 15 + (attempt - 1) * 0.5);
      if (r.next() < P) return mk('mus-orch', r.pick(['시립교향악단 단원', '국립합창단 단원', '시립국악관현악단 단원']), 4800, 'perf', 1);
      return { ok: false, failText: '단원 공채 실기에서 세 번 떨어졌다. 한 자리에 80명이 왔다.' };
    }
    case 'acadT': {
      const tk = FIELDS[f].talent;
      const sc = s.talent[tk] * 0.3 + u.prestige * 0.3 + eff * 8 + p.social * 3 + p.diligence * 2 - s.lazy * 0.15 + r.normal() * 5;
      if (sc > 72) return mk('acad-owner-' + f, f === 'art' ? '입시미술 학원 원장' : '실용음악 학원 원장', 6500, f, 1);
      if (sc > 52) return mk('acad-t-' + f, f === 'art' ? '입시미술 학원 강사' : '보컬·악기 전문 강사', 3600, f, 2);
      return mk('acad-pt-' + f, '동네 학원 시간강사', 2500, f, 3);
    }
    case 'police': {
      const G = endG(s);
      const sc = s.talent.sport * 0.15 + p.diligence * 6 + p.memory * 5 + eff * 10 + (5 - G.kor) * 2 + (5 - G.eng) * 1.5 - s.lazy * 0.2 + r.normal() * 6 + (attempt - 1) * 6;
      if (sc > 66) return r.chance(0.5) ? mk('police', '경찰관 (순경 공채)', 4500, 'law', 1) : mk('fire', '소방관', 4600, 'law', 1);
      return { ok: false, failText: '경찰 공채 필기(형사법·헌법)에서 떨어졌다. 체력은 만점이었는데.' };
    }
    case 'trainer': {
      const sc = s.talent.sport * 0.35 + p.social * 4 + p.confidence * 3 + eff * 8 - s.lazy * 0.15 + r.normal() * 7;
      if (sc > 76) return mk('tr-owner', '필라테스·PT 스튜디오 대표', 6000, 'sport', 1);
      if (sc > 56) return mk('tr-head', '대형 헬스장 수석 트레이너', 3800, 'sport', 2);
      return mk('tr-free', '프리랜서 PT 트레이너', 2600, 'sport', 3);
    }
    case 'double': return { ok: true, career: jobAt(u.double, levelFrom(C - 3), r, s) };
    case 'family': {
      const ok = r.chance(0.55 + p.diligence * 0.05);
      return ok ? mk('family-ok', '부모님 사업을 이어받아 키운 2세 대표', 6500, 'biz', 1) : mk('family-meh', '부모님 가게를 물려받아 버티는 중', 3800, 'biz', 2);
    }
    case 'soe': {
      const G2 = endG(s);
      const P = sigmoid((C - 58 + p.comprehension * 2 + eff * 4 + (5 - G2.kor) * 1.5 + (5 - G2.math) * 1) / 6);   // NCS: 의사소통(국어)·수리(수학)
      if (r.next() < P) { const org = r.pick(['한국전력공사', '국민건강보험공단', '한국토지주택공사', '인천국제공항공사', '한국수자원공사']); return mk('soe-' + org, `공기업 직원 (${org})`, 5600, 'law', 1); }
      return { ok: false, failText: 'NCS 필기에서 연달아 떨어졌다.' };
    }
    case 'civil': {
      const G = endG(s); const sc = p.diligence * 8 + p.memory * 6 + p.grit * 4 + eff * 10 - s.lazy / 3 + (5 - G.kor) * 2 + (5 - G.eng) * 1.5 + r.normal() * 5 + (attempt - 1) * 6;   // 공무원: 국어·영어(검정) 실력이 바탕
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
        const P = sigmoid((p.comprehension * 8 + p.memory * 5 + p.diligence * 6 + eff * 12 - 72 + (4 - endG(s).math) * 3 - s.lazy * 0.15 + (attempt - 1) * 6) / 6);   // CPA는 수학·회계 계산
        if (r.next() < P) return r.chance(0.6) ? mk('cpa-big4', '대형 회계법인 공인회계사', 7800, 'biz', 0) : mk('cpa-firm', '기업 재무팀 회계사', 7000, 'biz', 0);
        return { ok: false, failText: 'CPA 2차 시험에서 과락이 나왔다.' };
      }
      if (f === 'soc') {
        const P = sigmoid((p.memory * 7 + p.diligence * 7 + eff * 12 - 66 + (attempt - 1) * 6) / 7);
        if (r.next() < P) return mk('labor', '노무법인 공인노무사', 6200, 'soc', 0);
        return { ok: false, failText: '노무사 2차 시험에서 떨어졌다.' };
      }
      if (f === 'eng' || f === 'sci' || f === 'cs') {
        const P = sigmoid((p.comprehension * 7 + p.diligence * 7 + eff * 12 + (u.prestige - 70) * 0.4 - 70 + (4 - endG(s).math) * 2 - s.lazy * 0.15 + (attempt - 1) * 6) / 6);
        if (r.next() < P) return mk('patent', '특허법인 변리사', 8500, f, 0);
        return { ok: false, failText: '변리사 2차 시험에서 떨어졌다.' };
      }
      // 로스쿨
      const leet = p.comprehension * 9 + s.talent.verbal * 0.3 + u.prestige * 0.35 + (s.col.gpa - 3) * 20 + (5 - endG(s).kor) * 3 + r.normal() * 4 + eff * 6 - s.lazy * 0.1;   // LEET는 국어 독해력 시험에 가깝다
      if (leet < 64) return { ok: false, failText: '로스쿨 입시에서 모두 떨어졌다.' };
      if (r.chance(0.12)) return { ok: false, failText: '로스쿨은 졸업했지만 변호사시험에 떨어졌다.' };
      if (leet > 88 && u.prestige >= 86) return mk('law-big', '대형 로펌 변호사', 12000, 'law', 0);
      return r.chance(0.5) ? mk('law-in', '대기업 사내 변호사', 8000, 'law', 0) : mk('law-small', '중소 로펌 변호사', 6000, 'law', 1);
    }
    case 'grad': {
      const sc = u.prestige * 0.4 + (s.col.gpa - 3) * 25 + p.curiosity * 4 + eff * 5 + r.normal() * 5 + (s.flags.lab ? 4 : 0) - s.lazy * 0.1;
      s.age += 5;
      const hum = ['hum', 'soc', 'media', 'art', 'perf'].indexOf(f) >= 0 ? 8 : 0;   // 인문계 박사는 자리가 더 적다
      if (sc - hum > 92 && r.chance(0.35)) return mk('grad-prof', '대학교수 (정년트랙)', 7500, f, 0);
      if (sc - hum > 80) return r.chance(0.5) ? mk('grad-postdoc', '해외 연구소 박사후연구원', 5800, f, 0) : mk('grad-inst', '국책연구소 박사 연구원', 7000, f, 0);
      if (sc - hum > 66 && !hum) return mk('grad-corp', '대기업 연구소 박사급 연구원', 8800, f, 0);
      if (sc > 52) return mk('grad-lect', '대학 시간강사 (박사)', 2800, f, 2);
      return mk('grad-drift', '박사 수료 후 진로 고민 중', 2200, f, 3);
    }
    case 'startup': {
      // 창업: 실력(스펙·학점)·인맥·추진력이 바탕이고 운은 일부. 대부분은 3년 안에 접는다
      const sc = clamp(s.col.spec, 0, 100) * 0.25 + clamp(s.col.network, 0, 100) * 0.2 + (s.col.gpa - 3) * 8 + p.confidence * 4 + p.curiosity * 3 + (s.flags.startupExp ? 8 : 0) + eff * 7 - s.lazy * 0.3 + r.normal() * 8;
      if (sc > 82) return mk('st-big', '연매출 100억 스타트업 대표', 15000, f, 0);
      if (sc > 68) return mk('st-a', '시리즈A 투자 유치한 스타트업 공동창업자', 6000, f, 1);
      if (sc > 55) return mk('st-small', '작은 회사를 꾸려 가는 1인 대표', 3600, f, 2);
      s.flags.startupFail = true;
      if (p.wealth === 'high') return { ok: false, failText: '창업 3년 만에 회사를 접었다. 부모님 돈도 날렸다.' };
      return { ok: false, failText: '창업은 실패했다. 빚이 남았다.' };
    }
    case 'creator': {
      const tal = Math.max(s.talent.media, s.talent.art, s.talent.perf);
      // 크리에이터: 구독자 100만은 극소수. 재능·꾸준함·이미 키워 둔 채널이 있어야 한다
      const sc = tal * 0.45 + (s.flags.creator || 0) * 7 + p.diligence * 4 + eff * 7 - s.lazy * 0.3 + r.normal() * 6;
      if (sc > 84) return mk('cr-1m', '구독자 100만 크리에이터', 12000, 'media', 0);
      if (sc > 68) return mk('cr-100k', '구독자 15만 크리에이터', 5000, 'media', 1);
      if (sc > 52) return mk('cr-side', '부업 크리에이터 겸 회사원', 3800, 'media', 2);
      return { ok: false, failText: '2년 동안 영상을 올렸지만 구독자는 3천 명에서 멈췄다.' };
    }
    case 'abroad': {
      const sc = s.talent.verbal * 0.3 + s.col.spec * 0.4 + u.prestige * 0.25 + eff * 5 + r.normal() * 5 + (s.flags.exchange ? 6 : 0) + (3 - endG(s).eng) * 5 - s.lazy * 0.1;   // 해외는 영어가 먼저다
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
  const o = choose(ctx, 'alt1', '대학 대신', `대학에 가지 않기로 했다. ${p.pDesire === 'free' ? '부모님은 "네가 정했으면 응원할게"라고 하셨다.' : '부모님과는 한 달째 말을 안 한다.'} 친구들이 과잠을 입고 찍은 사진을 올릴 때, 나는 다른 출발선에 서 있다. 무엇을 할까?`, opts);
  inc(s, 'parentRel', p.pDesire === 'free' ? 0 : -10); s.autonomy += 1;
  const r = makeRng(s.seed, 'alt:' + o.id);
  const e = choose(ctx, 'alt2', '20대의 하루', '대학생 친구들보다 4년 일찍 사회에 나왔다. 일찍 시작한 만큼 앞서갈 수도, 길을 잃을 수도 있다. 하루를 어떻게 쓸까?', [
    { id: 'all', label: '죽어라 한다', hint: '빨리 자리를 잡음 · 몸과 관계가 닳는다', tags: ['study'] },
    { id: 'bal', label: '일과 삶의 균형을 지킨다', hint: '오래 버팀 · 성장 속도는 느리다', tags: ['safe'] },
    { id: 'easy', label: '흘러가는 대로', hint: '여유로움 · 30대가 막막할 수 있다', tags: ['fun'] },
  ]);
  const eff = { all: 1.4, bal: 0.8, easy: 0.1 }[e.id];
  const mk = (id, title, base, field, level) => ({ id, title, base, field, level });
  let car;
  if (o.id === 'esports') {
    const sc = s.talent.game * 0.55 + eff * 8 + p.grit * 3 - s.lazy * 0.1 + r.normal() * 7;
    car = sc > 78 ? mk('esp-1', '1군 프로게이머 (국제대회 출전)', 30000, 'none', 0) : sc > 62 ? mk('esp-st', '은퇴한 프로게이머 출신 스트리머', 6000, 'media', 1) : mk('esp-qa', '프로 실패 후 게임회사 QA', 3200, 'cs', 2);
  } else if (o.id === 'trainee') {
    const sc = s.talent.perf * 0.5 + eff * 8 + p.social * 3 - s.lazy * 0.1 + r.normal() * 8;
    car = sc > 80 ? mk('idol-hit', '음원 차트 1위 아이돌', 25000, 'perf', 0) : sc > 60 ? mk('idol-disband', '데뷔 후 해체, 보컬 트레이너', 3600, 'perf', 2) : mk('idol-fail', '연습생 6년 끝에 진로 전환', 2600, 'none', 3);
  } else if (o.id === 'creator') {
    const sc = s.talent.media * 0.45 + (s.flags.creator || 0) * 7 + p.diligence * 4 + eff * 7 - s.lazy * 0.3 + r.normal() * 6;
    car = sc > 84 ? mk('cr-1m', '구독자 100만 크리에이터', 12000, 'media', 0) : sc > 66 ? mk('cr-100k', '구독자 15만 크리에이터', 5000, 'media', 1) : mk('cr-fail', '채널을 접고 영상 편집 외주', 2800, 'media', 3);
  } else if (o.id === 'skill') {
    const t = r.pick([['skill-elec', '전기기사 (대기업 협력사)', 5200], ['skill-weld', '조선소 특수용접 기술자', 6800], ['skill-bake', hasHobby(s, 'cook') ? '동네 유명 베이커리 사장' : '제과점 사장', 4600], ['skill-car', '자동차 정비소 사장', 5000]]);
    const ok = eff > 0.5 && s.lazy < 60;
    car = ok ? mk(t[0], t[1], t[2], 'none', 1) : mk(t[0] + '-j', t[1].replace('사장', '직원').replace('기술자', '보조'), Math.round(t[2] * 0.6), 'none', 2);
  } else if (o.id === 'civil') {
    const sc = p.diligence * 8 + p.memory * 6 + eff * 10 - s.lazy / 3 + r.normal() * 5;
    car = sc > 56 ? (r.chance(0.5) ? mk('hs-soe', '공기업 고졸 채용 직원', 5000, 'none', 1) : mk('hs-civil9', '9급 공무원 (고졸)', 3400, 'law', 2)) : mk('hs-civil-fail', '공시 3년 차, 편의점 알바', 1800, 'none', 3);
  } else if (o.id === 'nco') {
    car = mk('nco', eff > 0.5 ? '육군 상사 (장기복무)' : '육군 중사', 4800, 'none', 1);
  } else {
    const lv = levelFrom(34 + eff * 10 + p.diligence * 4 - s.lazy * 0.15 + r.normal() * 4);
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
  // 서른이 되기 전, 직장에서의 운. 바르게 살았어도 회사가 망하고, 대충 살았어도 운이 트이기도 한다
  const rf = makeRng(s.seed, 'careerFate'), x = rf.next();
  const pub = /^(police|fire|civil|teach|soe|nco|hs-civil|hs-soe|md-core|grad-prof|grad-inst)/.test(car.id);   // 공무원·교사·공기업·교수는 잘리지 않는다
  if (x < 0.03 && !pub) { car.level = Math.min(3, car.level + 2); car.base = Math.round(car.base * 0.5); car.title += ' → 회사 부도, 빚을 안고 재출발'; car.id += '-ruin'; Lf(s, '다니던 회사가 임금을 석 달 밀리다 부도났다. 지인 소개로 넣은 투자금 2천만 원도 사기였다. 바르게 살았는데 서른을 빚으로 시작한다.'); inc(s, 'mental', -18); }
  else if (x < 0.1 && car.level <= 2 && !pub) { car.level += 1; car.base = Math.round(car.base * 0.72); car.title += ' → 구조조정 뒤 재취업 준비'; car.id += '-lay'; Lf(s, '입사 3년 차에 회사가 사업부를 접었다. 구조조정 명단에 내 이름이 있었다.'); inc(s, 'mental', -10); }
  else if (x < 0.13 && car.level <= 1 && !pub) { car.base = Math.round(car.base * 0.8); car.title += ' (업계 침체)'; car.id += '-down'; Lf(s, '잘 나가던 업계가 2년 만에 얼어붙었다. 연봉은 동결, 팀은 절반이 나갔다.'); inc(s, 'mental', -6); }
  else if (x < 0.17) { Lf(s, '번아웃이 왔다. 공황 증상으로 반년을 쉬었다.'); inc(s, 'mental', -14); car.base = Math.round(car.base * 0.9); }
  else if (x < 0.22 && car.level >= 1 && !pub) { car.level -= 1; car.base = Math.round(car.base * 1.28); car.title += ' → 스카우트'; car.id += '-up'; Lf(s, '우연히 맡은 프로젝트가 윗선 눈에 들었다. 경쟁사에서 연봉을 올려 데려갔다.'); inc(s, 'mental', 6); }
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
  const goalMet = s.uni ? (gi <= goal.gi ? 1 : gi <= goal.gi + 2 ? 0.4 : 0) : (car.level <= 1 ? 0.3 : 0);
  const income = clamp((salary - 2000) / 80, 0, 100);
  let sat = cf * 30 + clamp(s.autonomy, -4, 4) * 2 + goalMet * 10 + income * 0.2 + (marital === 'single' || marital === 'never' ? 0 : 6) + (s.parentRel - 50) * 0.08 + (s.social - 50) * 0.05 + (s.mental - 50) * 0.15 + 26 - car.level * 7 + r.normal() * 2;
  if (s.flags.parentField && cf < 0.6) sat -= 8;
  if (s.flags.medBurnout) sat -= 6;
  sat = clamp(Math.round(sat), 0, 100);
  const satTag = sat >= 70 ? 'happy' : sat >= 50 ? 'ok' : 'regret';
  // 인생 점수: 만족도만이 아니라 수입·학력·관계·마음을 함께 본다
  const edu = s.uni ? (s.uni.dropped ? 20 : s.uni.prestige) : 15;
  const life = Math.round(sat * 0.3 + income * 0.32 + edu * 0.16 + (s.parentRel + s.social) / 2 * 0.11 + s.mental * 0.11);
  const arche = archetype(s, car, sat, salary, marital);
  const code = [car.id, s.uni ? s.uni.tier.key : 'nc', satTag, marital].join('|');
  s.ending = {
    code, archetype: arche, career: car.title, careerId: car.id, level: car.level, salary,
    uni: s.uni ? s.uni.name : '대학 진학 안 함', major: s.uni ? s.uni.major : '', tierName: s.uni ? s.uni.tier.name : '',
    prestige: s.uni ? s.uni.prestige : 25, path: s.careerPath, attempts: s.attempts,
    marital, maritalText: MAR[marital], partner: partnerName, parentTag, friendTag,
    mental: Math.round(s.mental), sat, satTag, life, income: Math.round(income),
    csatPct: s.csatPct, naesinAvg: s.naesinRec.length ? avgNaesin(s) : null,
    csatG: s.csatG, employ: s.uni ? employOf(s.uni.field, s.uni.prestige, s.uni.teacher) : null,
    fates: (s.fates || []).slice(),
  };
  s.ending.story = epilogue(s, s.ending);
}
function archetype(s, car, sat, salary, marital) {
  const p = s.p, f = s.flags;
  if (car.id.indexOf('esp-1') === 0) return '게임으로 세계 무대에 선 사람';
  if (car.id === 'idol-hit') return '무대 위의 별';
  if (car.id === 'st-big') return '판을 뒤집은 사람';
  if (car.id === 'art-webtoon' || car.id === 'mus-chart') return '좋아하는 걸로 이름을 얻은 사람';
  if (/^acad-owner/.test(car.id)) return '가르치는 일에서 자리를 잡은 사람';
  if (s.arts && car.field !== FIELDS[ARTS_FIELD[s.arts]].talent && ['art', 'perf', 'sport'].indexOf(car.field) < 0 && sat < 55) return '실기를 접은 뒤의 서른';
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
  if (s.uni && e.employ) lines.push(`${e.major}의 취업률은 약 ${e.employ.rate}%, 취업의 질은 ${e.employ.grade}였다. ${e.employ.note}.`);
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
    const start = p.startTurn;
    if (start > 0) L(s, `${HS_TURNS[start].label}에서 시작한다. 지금까지의 내신은 상위 ${p.gpaPct.toFixed(0)}% 안팎이었다.`);
    for (let i = start; i < HS_TURNS.length; i++) {
      const t = HS_TURNS[i];
      s.turnIdx = i; s.turnLabel = t.label; s.age = 17 + Math.floor(i / 4);
      if (i >= 8) settleExamSense(s);
      if (i === start && t.type !== 'sem') studyMethod(ctx, t);
      if (t.type === 'sem') semesterTurn(ctx, t);
      else if (t.type === 'vac') { if (t.id === 'g1v2' || t.id === 'g2v2' || t.id === 'g1v1' && p.startTurn <= 1) acadPlan(ctx, t); vacationTurn(ctx, t); rollFate(ctx, t, 0.07); randomEvents(ctx, t, 2); }
      else if (t.type === 'apply') applyTurn(ctx, t);
      else if (t.type === 'final') finalTurn(ctx, t);
    }
    s.turnLabel = '입시 결과';
    admissions(ctx);
    if (s.uni) collegePhase(ctx); else noCollege(ctx);
    finalize(ctx);
    settle(s);
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
    if (d !== undefined && (pr.type === 'alloc' || pr.type === 'methods' || pr.options.some(o => o.id === d))) return d;
    return persona(s, pr);
  });
}

// ── 후회 분석 ────────────────────────────────────────────
function allocAlternatives(h) {
  const a = Object.assign({}, h.choice), cats = h.prompt.cats.map(c => c.id);
  const alts = [];
  const subs = SUB_KEYS.filter(k => cats.indexOf(k) >= 0);
  if (!subs.length) return alts;
  const funKeys = ['hobby', 'friends', 'date', 'rest', 'work'].filter(k => cats.indexOf(k) >= 0);
  const donor = funKeys.slice().sort((x, y) => (a[y] || 0) - (a[x] || 0))[0];
  const least = subs.slice().sort((x, y) => (a[x] || 0) - (a[y] || 0))[0];
  const most = subs.slice().sort((x, y) => (a[y] || 0) - (a[x] || 0))[0];
  if (donor && (a[donor] || 0) >= 2) { const b = Object.assign({}, a); b[donor] -= 2; b[least] = (b[least] || 0) + 2; alts.push({ choice: b, label: `${catName(h, donor)} 2칸을 ${catName(h, least)}에 썼다면` }); }
  if (most !== 'kor' && (a[most] || 0) >= 3) { const b = Object.assign({}, a); b[most] -= 2; b.kor = (b.kor || 0) + 2; alts.push({ choice: b, label: `${catName(h, most)} 2칸을 국어(문해력)에 썼다면` }); }
  if ((a[most] || 0) >= 3) { const b = Object.assign({}, a); b[most] -= 2; b.rest = (b.rest || 0) + 1; if (cats.indexOf('friends') >= 0) b.friends = (b.friends || 0) + 1; else b.rest += 1; alts.push({ choice: b, label: `${catName(h, most)} 2칸을 줄이고 쉬고 친구를 만났다면` }); }
  if (cats.indexOf('activity') >= 0 && (a.activity || 0) <= 1 && donor && (a[donor] || 0) >= 2) { const b = Object.assign({}, a); b[donor] -= 2; b.activity = (b.activity || 0) + 2; alts.push({ choice: b, label: `${catName(h, donor)} 2칸을 생기부 활동에 썼다면` }); }
  return alts;
}
// 공부법: 과목 하나씩, 그 과목에서 가장 정석인 방법(기출 분석)이나 실력에 맞는 방법으로 바꿨다면
function methodAlternatives(h) {
  const c = h.choice || {}, alts = [];
  h.prompt.rows.forEach(r => {
    const z = h.before.sub ? h.before.sub[r.k] : 0;
    const want = z < -0.3 && r.options.some(o => o.id === 'concept') ? 'concept' : r.k === 'eng' && z < 0.3 ? 'voca' : 'gichul';
    const alt = r.options.find(o => o.id === want && o.id !== c[r.k]) || r.options.find(o => o.id !== c[r.k] && o.id !== 'cram' && o.id !== 'hw' && o.id !== 'drop');
    if (!alt) return;
    const b = Object.assign({}, c); b[r.k] = alt.id;
    alts.push({ choice: b, label: c[r.k] === 'drop' ? `${r.name}을(를) 접지 않고 '${alt.label}'(으)로 붙잡았다면` : `${r.name} 공부법을 '${alt.label}'(으)로 했다면` });
    // 많이 약한 과목은 '접었다면'도 하나 본다
    if (c[r.k] !== 'drop' && z < -0.6 && r.k !== 'kor' && r.options.some(o => o.id === 'drop')) { const d = Object.assign({}, c); d[r.k] = 'drop'; alts.push({ choice: d, label: `${r.name}을(를) 접고 그 시간을 다른 과목에 몰았다면` }); }
  });
  return alts;
}
function methodsText(h) { const c = h.choice || {}; return h.prompt.rows.map(r => `${r.name}: ${(r.options.find(o => o.id === c[r.k]) || {}).label || '-'}`).join(' · '); }
function catName(h, id) { const c = h.prompt.cats.find(x => x.id === id); return c ? c.label : id; }
function decisionsOf(history) { const d = {}; history.forEach(h => { d[h.key] = h.choice; }); return d; }

function analyze(profile, seed, history, base) {
  const decisions = decisionsOf(history);
  const out = [];
  history.forEach(h => {
    let alts = [];
    if (h.prompt.type === 'alloc') alts = allocAlternatives(h);
    else if (h.prompt.type === 'methods') alts = methodAlternatives(h);
    else alts = h.prompt.options.filter(o => o.id !== h.choice).slice(0, 3).map(o => ({ choice: o.id, label: o.label }));
    alts.forEach(alt => {
      const res = autoplay(profile, seed, decisions, { key: h.key, choice: alt.choice });
      if (!res.done) return;
      const e = res.ending;
      const chosenLabel = h.prompt.type === 'alloc' ? allocText(h) : h.prompt.type === 'methods' ? methodsText(h) : (h.prompt.options.find(o => o.id === h.choice) || {}).label;
      out.push({
        idx: h.idx, key: h.key, turn: h.turn, title: h.title, chosen: chosenLabel, alt: alt.label, altChoice: alt.choice,
        ending: e, delta: e.life - base.life, dSalary: e.salary - base.salary, dSat: e.sat - base.sat, dPrestige: e.prestige - base.prestige,
        same: e.code === base.code && e.life === base.life && e.uni === base.uni,
      });
    });
  });
  const changed = out.filter(x => !x.same);
  const impact = x => Math.abs(x.delta) + Math.abs(x.dPrestige) * 0.15 + Math.abs(x.dSalary) / 800;
  const regrets = changed.filter(x => x.delta > 0 || (x.delta === 0 && x.dSalary > 0)).sort((a, b) => impact(b) - impact(a));
  const goods = changed.filter(x => x.delta < 0).sort((a, b) => impact(b) - impact(a));
  // 같은 결정에서 하나만
  // 같은 결정에서 하나만, 그리고 이미 보여 준 결말과 같은 결말은 빼서 서로 다른 갈림길을 보여 준다
  const uniq = arr => { const seen = {}, ends = {}; return arr.filter(x => { const ek = x.ending.career + '|' + x.ending.uni; if (seen[x.key] || ends[ek]) return false; seen[x.key] = ends[ek] = true; return true; }); };
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
    subj: mockGrades(s.csatSub || s.sub),
    kor: korGrades(s, (s.csatSub || s.sub).kor),
    acad: SUB_KEYS.map(k => ({ k, name: SUBJ_NAME[k], type: s.acad[k], label: ACAD[s.acad[k]].name })),
    korFocus: (KOR_FOCUS[s.korFocus] || KOR_FOCUS.mock).name,
    methods: SUB_KEYS.map(k => ({ k, name: SUBJ_NAME[k], label: isDropped(s, k) ? '접음(최소한만)' : methodInfo(s, k).name, dropped: isDropped(s, k) })),
    dropped: droppedList(s),
    arts: artsField(s) ? { field: artsField(s), name: { art: '미술', perf: '음악', sport: '체육' }[artsField(s)], talent: Math.round(s.talent[FIELDS[artsField(s)].talent]), acad: ARTS_ACAD[s.artsAcad || 'none'].name } : null,
    pct: pctOf(s.csatSub || s.lastMock || s.sub),
    jfit: jungsiFit(s, s.csatSub || s.lastMock || s.sub),
    sense: s.examSense != null ? (s.examSense >= 0.08 ? '실전 감각 좋음' : s.examSense <= -0.06 ? '실전 감각 부족' : '실전 감각 보통') : (s.mockSem ? (s.mockPrep / s.mockSem >= 0.7 ? '학평 준비 꾸준함' : s.mockPrep / s.mockSem <= 0.35 ? '학평 준비 부족' : '학평 준비 보통') : null),
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
  fitFromGrades: (g, track) => { const sub = {}; SUB_KEYS.forEach(k => { sub[k] = subjFromGrade(k, +g[k] || 5); }); return jungsiFit({ track: track === '자연' ? '자연' : '인문' }, sub); },
  ACAD, KOR_FOCUS, SUBJ_METHODS, PAST_MOCK, PCT70, ARTS_ACAD, ARTS_NAME, FIELDS, GOALS, PARENT_STYLES, PARENT_DESIRES, STYLES, HOBBIES, FRIEND_GROUPS, TIERS,
  _internal: { persona, simulate, makeRng, topFromZ, zFromTop, grade9, grade5 },
};
if (typeof module !== 'undefined' && module.exports) module.exports = API;
else root.CareerSim = API;
})(typeof window !== 'undefined' ? window : this);
