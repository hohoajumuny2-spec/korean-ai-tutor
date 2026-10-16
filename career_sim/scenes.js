/* ─────────────────────────────────────────────────────────
 * 장면 그림 — 상황마다 몇 초짜리로 반복 재생되는 움직이는 일러스트.
 *  · 모두 코드로 그린 SVG라 바깥 파일 없이 동작한다.
 *  · 색은 CSS 변수(--sc-*)로 받아 낮/밤, 다크 모드, 학년별 색을 따른다.
 *  · media/<장면>.mp4 같은 실제 영상을 넣고 싶으면 CareerScenes.VIDEOS[장면]에 주소를 넣으면 그림 대신 영상이 나온다.
 * ───────────────────────────────────────────────────────── */
(function (root) {
'use strict';
let uid = 0;
const F = n => `style="fill:var(--sc-${n})"`;
const S = (n, w) => `style="stroke:var(--sc-${n});stroke-width:${w || 3};fill:none;stroke-linecap:round"`;
const A = (cls, extra) => `class="${cls}"${extra ? ' style="' + extra + '"' : ''}`;

// ── 사람 ──
function person(x, y, o) {
  o = o || {};
  const sc = o.s || 1, shirt = o.shirt || 'accent', hair = o.hair || 'hair', pose = o.pose || 'stand';
  const flip = o.flip ? -1 : 1;
  const g = [];
  if (pose === 'stand' || pose === 'phone' || pose === 'wave' || pose === 'run') {
    g.push(`<rect x="-11" y="-46" width="9" height="46" rx="4" ${F('pants')}/><rect x="2" y="-46" width="9" height="46" rx="4" ${F('pants')}/>`);
  }
  const by = pose === 'sit' ? -40 : -96;
  g.push(`<rect x="-19" y="${by}" width="38" height="54" rx="15" ${F(shirt)}/>`);
  // 팔
  if (pose === 'phone') g.push(`<path d="M14 ${by + 14} Q30 ${by + 6} 18 ${by - 10}" ${S(shirt, 9)}/><rect x="10" y="${by - 26}" width="12" height="18" rx="3" ${F('ink')}/><rect x="12" y="${by - 24}" width="8" height="13" rx="2" class="a-glow" ${F('glow')}/>`);
  else if (pose === 'wave') g.push(`<path d="M-15 ${by + 14} Q-24 ${by + 32} -18 ${by + 46}" ${S(shirt, 9)}/><g class="a-wave" style="transform-origin:16px ${by + 12}px"><path d="M16 ${by + 12} Q30 ${by - 4} 26 ${by - 22}" ${S(shirt, 9)}/></g>`);
  else if (pose === 'sit') g.push(`<path d="M-14 ${by + 16} Q-22 ${by + 34} -4 ${by + 40}" ${S(shirt, 9)}/><path d="M14 ${by + 16} Q24 ${by + 34} 6 ${by + 40}" ${S(shirt, 9)}/>`);
  else g.push(`<path d="M-17 ${by + 14} Q-24 ${by + 32} -20 ${by + 48}" ${S(shirt, 9)}/><path d="M17 ${by + 14} Q24 ${by + 32} 20 ${by + 48}" ${S(shirt, 9)}/>`);
  // 머리
  const hy = by - 20;
  g.push(`<circle cx="0" cy="${hy}" r="18" ${F('skin')}/>`);
  g.push(o.long ? `<path d="M-19 ${hy + 14} Q-22 ${hy - 22} 0 ${hy - 20} Q22 ${hy - 22} 19 ${hy + 14} L14 ${hy - 2} Q0 ${hy - 10} -14 ${hy - 2} Z" ${F(hair)}/>` : `<path d="M-18 ${hy - 2} Q-16 ${hy - 22} 0 ${hy - 20} Q18 ${hy - 22} 18 ${hy - 2} Q8 ${hy - 10} -18 ${hy - 2} Z" ${F(hair)}/>`);
  if (!o.back) g.push(`<circle cx="${6 * flip}" cy="${hy + 2}" r="2" ${F('ink')}/><circle cx="${-6 * flip}" cy="${hy + 2}" r="2" ${F('ink')}/>` + (o.mood === 'sad' ? `<path d="M-5 ${hy + 11} Q0 ${hy + 7} 5 ${hy + 11}" ${S('ink', 1.6)}/>` : o.mood === 'happy' ? `<path d="M-5 ${hy + 8} Q0 ${hy + 13} 5 ${hy + 8}" ${S('ink', 1.6)}/>` : `<path d="M-4 ${hy + 10} L4 ${hy + 10}" ${S('ink', 1.6)}/>`));
  const cls = pose === 'run' ? 'a-bob' : o.cls || 'a-breathe';
  return `<g transform="translate(${x} ${y}) scale(${sc * flip} ${sc})"><g class="${cls}">${g.join('')}</g></g>`;
}

// ── 소품 ──
function sky(tod) { return `<rect width="640" height="360" ${F(tod === 'night' ? 'night' : tod === 'sunset' ? 'sunset' : 'sky')}/>`; }
function wall(c, floorY) { return `<rect width="640" height="360" ${F(c || 'wall')}/><rect y="${floorY || 290}" width="640" height="${360 - (floorY || 290)}" ${F('floor')}/>`; }
function particles(season, x0, y0, w, h) {
  if (!season) return '';
  const out = [];
  const n = season === 'rain' ? 26 : 14;
  for (let i = 0; i < n; i++) {
    const x = x0 + ((i * 53) % w), d = (i * 0.37) % 4, dur = season === 'rain' ? 0.9 + (i % 4) * 0.15 : 4 + (i % 5);
    const st = `animation-delay:-${d}s;animation-duration:${dur}s`;
    if (season === 'spring') out.push(`<ellipse cx="${x}" cy="${y0 - 10}" rx="4" ry="2.6" class="a-fall" style="${st}" fill="#f6a5c0"/>`);
    else if (season === 'autumn') out.push(`<path d="M${x} ${y0 - 10} l5 -4 l5 4 l-5 6 z" class="a-fall" style="${st}" fill="#e8893a"/>`);
    else if (season === 'winter') out.push(`<circle cx="${x}" cy="${y0 - 10}" r="${2 + (i % 3)}" class="a-fall" style="${st}" fill="#ffffff"/>`);
    else if (season === 'summer') out.push(i < 5 ? `<circle cx="${x0 + w - 40}" cy="${y0 + 40}" r="${26 + i * 10}" class="a-pulse" style="animation-delay:-${i * 0.6}s" fill="none" stroke="#ffd34d" stroke-opacity=".35" stroke-width="2"/>` : '');
    else if (season === 'rain') out.push(`<line x1="${x}" y1="${y0 - 20}" x2="${x - 4}" y2="${y0}" class="a-rain" style="${st}" stroke="#9cc3ff" stroke-width="2"/>`);
  }
  return `<g clip-path="url(#clip${uid})"><clipPath id="clip${uid}"><rect x="${x0}" y="${y0}" width="${w}" height="${h}"/></clipPath>${out.join('')}</g>`;
}
function windowEl(x, y, w, h, tod, season) {
  return `<rect x="${x - 6}" y="${y - 6}" width="${w + 12}" height="${h + 12}" rx="4" ${F('frame')}/><rect x="${x}" y="${y}" width="${w}" height="${h}" ${F(tod === 'night' ? 'night' : tod === 'sunset' ? 'sunset' : 'sky')}/>` +
    (tod === 'night' ? `<circle cx="${x + w - 30}" cy="${y + 30}" r="14" fill="#fff6c9"/>${stars(x, y, w, h)}` : `<g class="a-drift"><ellipse cx="${x + 40}" cy="${y + 30}" rx="26" ry="9" fill="#fff" opacity=".8"/></g>`) +
    particles(season, x, y, w, h) + `<line x1="${x + w / 2}" y1="${y}" x2="${x + w / 2}" y2="${y + h}" ${S('frame', 5)}/>`;
}
function stars(x, y, w, h) { let o = ''; for (let i = 0; i < 6; i++) o += `<circle cx="${x + 12 + (i * 37) % (w - 20)}" cy="${y + 12 + (i * 23) % (h / 2)}" r="1.8" fill="#fff" class="a-twinkle" style="animation-delay:-${i * 0.5}s"/>`; return o; }
function clock(x, y, r) {
  r = r || 20;
  return `<circle cx="${x}" cy="${y}" r="${r}" style="fill:var(--sc-sheet);stroke:var(--sc-ink);stroke-width:3"/>` +
    `<line x1="${x}" y1="${y}" x2="${x}" y2="${y - r * 0.6}" class="a-spin-slow" style="stroke:var(--sc-ink);stroke-width:3;stroke-linecap:round;transform-origin:${x}px ${y}px"/>` +
    `<line x1="${x}" y1="${y}" x2="${x + r * 0.75}" y2="${y}" class="a-spin" style="stroke:var(--sc-accent);stroke-width:2;transform-origin:${x}px ${y}px"/>`;
}
function desk(x, y, w) { return `<rect x="${x}" y="${y}" width="${w}" height="10" rx="3" ${F('wood')}/><rect x="${x + 8}" y="${y + 10}" width="6" height="${290 - y - 10}" ${F('wood2')}/><rect x="${x + w - 14}" y="${y + 10}" width="6" height="${290 - y - 10}" ${F('wood2')}/>`; }
function book(x, y, c) { return `<rect x="${x}" y="${y}" width="34" height="6" rx="1" ${F(c || 'accent')}/><rect x="${x + 3}" y="${y - 6}" width="30" height="6" rx="1" ${F('accent2')}/>`; }
function bubble(x, y, text, delay, side) {
  const w = Math.max(56, text.length * 13 + 24);
  const bx = side === 'r' ? x - w : x;
  return `<g class="a-pop" style="animation-delay:${delay || 0}s;transform-origin:${x}px ${y + 16}px"><rect x="${bx}" y="${y}" width="${w}" height="32" rx="16" style="fill:var(--sc-sheet);stroke:var(--sc-line);stroke-width:1.5"/><text x="${bx + w / 2}" y="${y + 21}" text-anchor="middle" font-size="14" ${F('ink')} font-family="var(--f-body, sans-serif)">${text}</text></g>`;
}
function hearts(x, y) { let o = ''; for (let i = 0; i < 4; i++) o += `<path d="M${x + i * 14} ${y} c-6 -8 -16 -2 -10 6 l10 9 l10 -9 c6 -8 -4 -14 -10 -6z" fill="#ff6b8b" class="a-rise" style="animation-delay:-${i * 0.9}s"/>`; return o; }
function lampGlow(x, y) { return `<g opacity=".28"><path d="M${x - 70} ${y + 110} L${x - 12} ${y} L${x + 12} ${y} L${x + 70} ${y + 110} Z" fill="#ffe8a3" class="a-flicker"/></g><path d="M${x - 16} ${y} L${x + 16} ${y} L${x + 8} ${y - 18} L${x - 8} ${y - 18} Z" ${F('accent')}/><line x1="${x}" y1="${y - 18}" x2="${x + 20}" y2="${y - 60}" ${S('ink', 3)}/>`; }
function skyline(y, night) {
  let o = '';
  const bs = [[0, 90], [70, 140], [130, 70], [200, 160], [270, 110], [350, 180], [420, 95], [490, 150], [560, 120]];
  bs.forEach(([x, h], i) => {
    o += `<rect x="${x}" y="${y - h}" width="64" height="${h}" ${F(night ? 'bldgN' : 'bldg')}/>`;
    for (let r = 0; r < Math.floor(h / 26); r++) for (let c = 0; c < 3; c++) {
      o += `<rect x="${x + 8 + c * 18}" y="${y - h + 10 + r * 26}" width="10" height="12" fill="${night ? '#ffd76b' : '#cfe3ff'}" opacity="${night ? ((i + r + c) % 3 ? 0.9 : 0.15) : 0.7}" ${night && (i + r * c) % 5 === 0 ? 'class="a-twinkle" style="animation-delay:-' + ((r + c) % 4) + 's"' : ''}/>`;
    }
  });
  return o;
}
function tree(x, y, season) {
  const leaf = season === 'autumn' ? '#e8893a' : season === 'winter' ? '#e8eef5' : season === 'spring' ? '#f6b7cd' : '#5bbf7a';
  return `<rect x="${x - 5}" y="${y - 60}" width="10" height="60" ${F('wood2')}/><g class="a-sway" style="transform-origin:${x}px ${y - 50}px"><circle cx="${x}" cy="${y - 80}" r="34" fill="${leaf}"/><circle cx="${x - 24}" cy="${y - 62}" r="22" fill="${leaf}"/><circle cx="${x + 24}" cy="${y - 62}" r="22" fill="${leaf}"/></g>`;
}
function speechShake(x, y, text) { return `<g class="a-shake"><path d="M${x} ${y} l20 -10 l10 12 l18 -14 l8 16 l22 -6 l-8 20 l16 10 l-22 6 l4 18 l-20 -10 l-12 16 l-8 -18 l-22 6 l8 -18 l-18 -10 z" fill="#ffd2cc" stroke="#d94a3b" stroke-width="2"/><text x="${x + 32}" y="${y + 18}" text-anchor="middle" font-size="15" font-weight="700" fill="#b8322a">${text}</text></g>`; }

// ── 장면 ──
const SCENES = {
  classroom: o => wall('wall', 292) + windowEl(470, 60, 130, 110, 'day', o.season) +
    `<rect x="60" y="50" width="330" height="150" rx="6" fill="#2f5b4b"/><rect x="60" y="200" width="330" height="8" ${F('wood')}/>` +
    `<text x="90" y="100" font-size="22" fill="#e9f5ec" font-family="var(--f-hand, cursive)">∫ f(x)dx = ?</text><path d="M90 140 q30 -24 60 0 t60 0" stroke="#e9f5ec" stroke-width="2" fill="none" class="a-draw"/>` +
    clock(430, 40, 18) + desk(120, 250, 150) + desk(360, 250, 150) + person(195, 275, { pose: 'sit', back: true, shirt: 'accent' }) + person(435, 275, { pose: 'sit', back: true, shirt: 'accent2', long: true }) + book(170, 244),
  night_study: o => wall('wallN', 292) + windowEl(60, 50, 150, 120, 'night', o.season === 'winter' ? 'winter' : null) + clock(560, 60, 22) +
    desk(250, 230, 260) + lampGlow(460, 160) + person(360, 255, { pose: 'sit', shirt: 'accent' }) + book(300, 224) +
    `<rect x="400" y="214" width="16" height="16" rx="3" fill="#fff"/><path d="M404 210 q4 -10 0 -18 M410 210 q4 -10 0 -18" stroke="#ccc" stroke-width="2" fill="none" class="a-steam"/>` +
    `<text x="540" y="110" font-size="13" ${F('muted')}>AM 1:40</text>`,
  phone: o => wall('wallN', 292) + windowEl(470, 50, 120, 100, 'night', null) +
    `<rect x="60" y="220" width="360" height="60" rx="10" ${F('bed')}/><rect x="60" y="200" width="90" height="34" rx="12" fill="#fff"/>` +
    person(240, 262, { pose: 'phone', shirt: 'accent2', s: 1 }) +
    `<g opacity=".18"><circle cx="258" cy="140" r="60" fill="#9ad0ff" class="a-glow"/></g>` +
    bubble(300, 60, '♥ 1.2만', 0.2) + bubble(330, 100, '▶ 다음 영상', 0.9) + bubble(290, 140, '알림 99+', 1.6) +
    `<text x="490" y="190" font-size="15" fill="#ffd76b" class="a-blink">03:12</text>`,
  chat: o => `<rect width="640" height="360" ${F('wall')}/><rect x="200" y="20" width="240" height="330" rx="28" ${F('ink')}/><rect x="212" y="40" width="216" height="290" rx="14" ${F('sheet')}/>` +
    bubble(222, 60, o.a || 'ㅋㅋ 오늘 ㄱ?', 0.1) + bubble(418, 104, o.b || '어디서?', 0.8, 'r') + bubble(222, 148, o.c || 'PC방 9시', 1.5) + bubble(222, 192, o.d || '다들 온대 ㅋㅋ', 2.2) +
    `<g class="a-pop" style="animation-delay:2.9s"><rect x="222" y="240" width="60" height="26" rx="13" ${F('line')}/><circle cx="238" cy="253" r="3" ${F('muted')} class="a-blink"/><circle cx="252" cy="253" r="3" ${F('muted')} class="a-blink" style="animation-delay:.2s"/><circle cx="266" cy="253" r="3" ${F('muted')} class="a-blink" style="animation-delay:.4s"/></g>`,
  friends: o => sky('night') + stars(0, 0, 640, 180) + skyline(300, true) + `<rect y="300" width="640" height="60" ${F('road')}/>` +
    `<rect x="380" y="170" width="200" height="130" ${F('bldgN')}/><rect x="395" y="185" width="170" height="34" rx="6" fill="#1b1f3a"/><text x="480" y="210" text-anchor="middle" font-size="20" font-weight="800" fill="#5ef0ff" class="a-neon">PC ROOM 24H</text>` +
    person(200, 320, { shirt: 'accent', mood: 'happy' }) + person(260, 322, { shirt: 'accent2', pose: 'wave', long: true, mood: 'happy' }) + person(320, 320, { shirt: 'pants', flip: true, mood: 'happy' }),
  love: o => sky('sunset') + `<circle cx="500" cy="200" r="60" fill="#ffd27a" opacity=".9"/><rect y="270" width="640" height="90" fill="#7ab87f"/>` + tree(110, 280, o.season) +
    `<rect x="230" y="250" width="200" height="12" rx="4" ${F('wood')}/><rect x="245" y="262" width="8" height="28" ${F('wood2')}/><rect x="405" y="262" width="8" height="28" ${F('wood2')}/>` +
    person(290, 268, { pose: 'sit', shirt: 'accent', mood: 'happy' }) + person(370, 268, { pose: 'sit', shirt: 'accent2', long: true, flip: true, mood: 'happy' }) + hearts(310, 150) + particles(o.season, 0, 0, 640, 360),
  breakup: o => sky('night') + `<rect y="290" width="640" height="70" ${F('road')}/><rect x="420" y="90" width="8" height="200" ${F('ink')}/><path d="M400 92 h48 l-10 -16 h-28 z" ${F('ink')}/>` +
    `<g opacity=".18"><path d="M370 300 L398 96 L450 96 L478 300 Z" fill="#fff3b8" class="a-flicker"/></g>` + person(424, 300, { shirt: 'accent2', mood: 'sad' }) + particles('rain', 0, 0, 640, 360) +
    `<rect x="120" y="160" width="140" height="70" rx="10" ${F('sheet')} class="a-pop" style="animation-delay:.6s"/><text x="190" y="200" text-anchor="middle" font-size="14" ${F('ink')} class="a-pop" style="animation-delay:.6s">우리 잠깐…</text>`,
  family: o => wall('wallWarm', 300) + `<g class="a-sway" style="transform-origin:320px 0px"><line x1="320" y1="0" x2="320" y2="70" ${S('ink', 2)}/><path d="M290 70 h60 l-12 -18 h-36 z" ${F('accent')}/><ellipse cx="320" cy="92" rx="80" ry="22" fill="#ffe8a3" opacity=".35"/></g>` +
    `<rect x="170" y="230" width="300" height="14" rx="4" ${F('wood')}/><rect x="190" y="244" width="10" height="56" ${F('wood2')}/><rect x="440" y="244" width="10" height="56" ${F('wood2')}/>` +
    `<ellipse cx="260" cy="226" rx="22" ry="6" fill="#fff"/><ellipse cx="380" cy="226" rx="22" ry="6" fill="#fff"/><ellipse cx="320" cy="224" rx="30" ry="8" fill="#f2b680"/>` +
    person(210, 270, { pose: 'sit', shirt: 'pants', s: 1.1 }) + person(320, 262, { pose: 'sit', shirt: 'accent', mood: o.mood === 'bad' ? 'sad' : '' }) + person(430, 270, { pose: 'sit', shirt: 'accent2', long: true, s: 1.1, flip: true }) +
    (o.mood === 'bad' ? speechShake(420, 70, '!!') : bubble(400, 120, '…', 0.8)),
  parentFight: o => wall('wallN', 300) + `<rect x="80" y="70" width="120" height="230" ${F('door')}/><rect x="186" y="70" width="12" height="230" fill="#ffe8a3" opacity=".7" class="a-flicker"/>` +
    person(140, 300, { pose: 'sit', shirt: 'accent', mood: 'sad', s: 0.9 }) + speechShake(330, 80, '그만해!') + speechShake(460, 150, '이혼해') + `<g class="a-shake"><path d="M520 260 l10 -20 l8 14 l12 -18" stroke="#d94a3b" stroke-width="3" fill="none"/></g>`,
  hospital: o => wall('wallCool', 292) + `<rect x="100" y="210" width="320" height="40" rx="8" fill="#fff"/><rect x="100" y="250" width="320" height="12" ${F('frame')}/><rect x="110" y="190" width="80" height="26" rx="10" fill="#e7f1ff"/>` +
    `<rect x="470" y="70" width="6" height="200" ${F('frame')}/><rect x="450" y="70" width="46" height="60" rx="8" fill="#d8ecff" stroke="#9cc3ff"/><circle cx="473" cy="150" r="4" fill="#9cc3ff" class="a-drip"/>` +
    `<rect x="520" y="90" width="100" height="70" rx="8" fill="#1b2a2a"/><path d="M528 130 h18 l6 -20 l8 36 l6 -16 h40" stroke="#5ef08a" stroke-width="2" fill="none" class="a-draw"/>` +
    person(230, 222, { pose: 'sit', shirt: 'accent2', s: 0.95, long: true, mood: 'sad' }) + person(330, 290, { shirt: 'accent' }),
  exam: o => wall('wallCool', 292) + clock(560, 60, 30) + `<text x="560" y="115" text-anchor="middle" font-size="14" font-weight="700" fill="#d94a3b" class="a-blink">종료 20분 전</text>` +
    [100, 230, 360].map((x, i) => desk(x, 240, 110) + person(x + 55, 262, { pose: 'sit', back: true, shirt: i === 1 ? 'accent' : 'pants', s: 0.95 })).join('') +
    `<g class="a-shake-soft"><rect x="250" y="226" width="70" height="16" fill="#fff"/><g fill="#f0a3b3">${[0, 1, 2, 3, 4].map(i => `<circle cx="${258 + i * 13}" cy="234" r="4"/>`).join('')}</g></g>`,
  academy: o => sky('night') + stars(0, 0, 640, 120) + skyline(300, true) + `<rect y="300" width="640" height="60" ${F('road')}/>` +
    `<rect x="60" y="120" width="120" height="30" rx="4" fill="#ffd34d"/><text x="120" y="141" text-anchor="middle" font-size="16" font-weight="800" fill="#1b2433">수학 학원</text><rect x="420" y="160" width="140" height="30" rx="4" fill="#5ef0ff"/><text x="490" y="181" text-anchor="middle" font-size="16" font-weight="800" fill="#1b2433">영어 · 과탐</text>` +
    `<g class="a-drive"><rect x="-220" y="250" width="200" height="56" rx="12" fill="#ffc83d"/><rect x="-205" y="262" width="40" height="22" rx="3" fill="#cfe3ff"/><rect x="-155" y="262" width="40" height="22" rx="3" fill="#cfe3ff"/><rect x="-105" y="262" width="40" height="22" rx="3" fill="#cfe3ff"/><circle cx="-180" cy="308" r="12" fill="#222"/><circle cx="-60" cy="308" r="12" fill="#222"/></g>` +
    person(300, 330, { shirt: 'accent', pose: 'phone', s: 0.9 }),
  stage: o => `<rect width="640" height="360" fill="#120f22"/><path d="M180 0 L240 0 L380 300 L60 300 Z" fill="#fff6c9" opacity=".18" class="a-sweep" style="transform-origin:210px 0"/><path d="M420 0 L470 0 L600 300 L300 300 Z" fill="#c9e6ff" opacity=".14" class="a-sweep" style="transform-origin:445px 0;animation-delay:-2s"/>` +
    `<rect y="250" width="640" height="20" fill="#2b2448"/>` + person(320, 252, { shirt: 'accent', pose: 'wave', mood: 'happy' }) +
    `<line x1="290" y1="252" x2="290" y2="180" stroke="#888" stroke-width="3"/><circle cx="290" cy="176" r="6" fill="#444"/>` +
    [0, 1, 2, 3, 4, 5, 6, 7, 8].map(i => `<g class="a-wave" style="transform-origin:${40 + i * 70}px 360px;animation-delay:-${i * 0.3}s"><line x1="${40 + i * 70}" y1="360" x2="${40 + i * 70}" y2="300" stroke="#555" stroke-width="4"/><circle cx="${40 + i * 70}" cy="296" r="9" fill="${['#ff6b8b', '#5ef0ff', '#ffd34d'][i % 3]}" class="a-glow"/></g>`).join(''),
  game: o => wall('wallN', 292) + desk(140, 220, 360) + `<rect x="230" y="110" width="180" height="110" rx="6" ${F('ink')}/><rect x="238" y="118" width="164" height="92" rx="3" fill="#1d2b5a"/>` +
    [0, 1, 2, 3].map(i => `<rect x="${250 + i * 38}" y="${150 + (i % 2) * 20}" width="26" height="26" rx="4" fill="${['#ff6b8b', '#5ef0ff', '#ffd34d', '#8be38b'][i]}" class="a-blink" style="animation-delay:-${i * 0.4}s"/>`).join('') +
    `<rect x="250" y="226" width="140" height="10" rx="3" class="a-rgb"/><text x="320" y="140" text-anchor="middle" font-size="13" fill="#fff" class="a-blink">VICTORY</text>` + person(320, 290, { pose: 'sit', back: true, shirt: 'accent', s: 1.1 }),
  art: o => wall('wallWarm', 292) + windowEl(470, 60, 130, 110, 'day', o.season) + `<path d="M220 290 L260 90 L300 290 M260 90 L260 290" ${S('wood2', 6)}/><rect x="190" y="110" width="140" height="110" fill="#fff" stroke="#ccc"/>` +
    `<path d="M205 190 q30 -50 60 -10 t50 -20" stroke="#ff6b8b" stroke-width="8" fill="none" class="a-draw"/><circle cx="290" cy="140" r="16" fill="#ffd34d" class="a-pop" style="animation-delay:1.2s"/>` + person(390, 290, { shirt: 'accent2', long: true, flip: true }),
  sport: o => sky('day') + `<circle cx="560" cy="60" r="30" fill="#ffd34d"/><rect y="250" width="640" height="110" fill="#d9653b"/>` +
    [0, 1, 2].map(i => `<line x1="0" y1="${275 + i * 25}" x2="640" y2="${275 + i * 25}" stroke="#fff" stroke-width="2" opacity=".7"/>`).join('') +
    `<g class="a-runacross">${person(0, 290, { pose: 'run', shirt: 'accent', mood: 'happy' })}</g>` + tree(80, 250, o.season),
  code: o => wall('wallN', 292) + desk(140, 230, 360) + `<rect x="230" y="140" width="180" height="90" rx="6" ${F('ink')}/><rect x="238" y="148" width="164" height="74" fill="#0f1b2d"/>` +
    [0, 1, 2, 3, 4].map(i => `<rect x="${246 + (i % 2) * 14}" y="${156 + i * 13}" width="${60 + (i * 37) % 70}" height="6" rx="2" fill="${['#5ef0ff', '#ffd34d', '#ff6b8b', '#8be38b', '#c3a6ff'][i]}" class="a-type" style="animation-delay:${i * 0.5}s"/>`).join('') +
    `<rect x="200" y="230" width="240" height="10" rx="3" ${F('frame')}/>` + person(320, 292, { pose: 'sit', back: true, shirt: 'accent', s: 1.1 }),
  consult: o => wall('wallCool', 292) + desk(160, 220, 320) + `<rect x="200" y="150" width="70" height="70" fill="#fff" stroke="#ccc"/><rect x="210" y="190" width="10" height="22" fill="#9cc3ff"/><rect x="226" y="176" width="10" height="36" fill="#ff6b8b"/><rect x="242" y="164" width="10" height="48" fill="#ffd34d" class="a-grow" style="transform-origin:247px 212px"/>` +
    person(400, 262, { pose: 'sit', shirt: 'ink', s: 1.1, flip: true }) + person(150, 290, { shirt: 'accent' }) + bubble(330, 70, '스토리가 필요해요', 0.6),
  summer: o => sky('day') + `<circle cx="540" cy="70" r="40" fill="#ffd34d" class="a-pulse"/><rect y="220" width="640" height="70" fill="#3fa9e8"/>` +
    [0, 1, 2].map(i => `<path d="M${-40 + i * 10} ${240 + i * 16} q40 -12 80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0" stroke="#fff" stroke-width="3" fill="none" class="a-wavex" style="animation-delay:-${i}s"/>`).join('') +
    `<rect y="290" width="640" height="70" fill="#f3d9a4"/>` + person(220, 330, { shirt: 'accent', pose: 'wave', mood: 'happy' }) + person(300, 330, { shirt: 'accent2', long: true, mood: 'happy' }),
  winter: o => wall('wallN', 292) + windowEl(80, 50, 200, 140, 'night', 'winter') + desk(330, 230, 240) + lampGlow(520, 160) + person(430, 255, { pose: 'sit', shirt: 'accent' }) + book(380, 224) +
    `<text x="180" y="230" text-anchor="middle" font-size="18" font-weight="800" ${F('accent')}>D-300</text>`,
  campus: o => sky('day') + `<rect x="160" y="80" width="320" height="190" ${F('bldg')}/><path d="M150 84 L320 30 L490 84 Z" ${F('bldgN')}/>` +
    [0, 1, 2, 3, 4].map(i => `<rect x="${185 + i * 60}" y="110" width="30" height="40" fill="#cfe3ff"/><rect x="${185 + i * 60}" y="180" width="30" height="40" fill="#cfe3ff"/>`).join('') +
    `<rect y="270" width="640" height="90" fill="#7ab87f"/>` + tree(80, 280, o.season || 'spring') + tree(560, 280, o.season || 'spring') +
    person(260, 320, { shirt: 'accent', pose: 'wave', mood: 'happy' }) + person(340, 322, { shirt: 'accent2', long: true, mood: 'happy' }) + particles(o.season || 'spring', 0, 0, 640, 360),
  army: o => sky('day') + `<rect y="250" width="640" height="110" fill="#6e8a4e"/><rect x="380" y="150" width="200" height="100" fill="#8a9a6a"/><path d="M370 150 L480 100 L590 150 Z" fill="#5d6e45"/>` +
    `<line x1="160" y1="250" x2="160" y2="80" stroke="#888" stroke-width="4"/><path d="M162 82 q30 -8 60 0 t0 36 q-30 -8 -60 0 z" fill="#ffffff" stroke="#ccc" class="a-flag" style="transform-origin:162px 100px"/><circle cx="192" cy="100" r="9" fill="#d94a3b"/>` +
    person(280, 300, { shirt: 'army' }) + person(330, 300, { shirt: 'army' }),
  office: o => wall('wallCool', 292) + `<rect x="380" y="40" width="230" height="170" ${F('frame')}/><g clip-path="url(#ow${uid})"><clipPath id="ow${uid}"><rect x="386" y="46" width="218" height="158"/></clipPath>${skyline(204, o.tod === 'night')}</g>` +
    desk(80, 230, 300) + `<rect x="160" y="170" width="110" height="64" rx="5" ${F('ink')}/><rect x="166" y="176" width="98" height="50" fill="#dfeaff"/><rect x="175" y="200" width="70" height="6" fill="#9cc3ff" class="a-type"/>` +
    `<rect x="300" y="214" width="16" height="16" rx="3" fill="#fff"/><path d="M304 210 q4 -10 0 -18 M310 210 q4 -10 0 -18" stroke="#ccc" stroke-width="2" fill="none" class="a-steam"/>` +
    person(215, 262, { pose: 'sit', shirt: 'accent', back: true, s: 1.1 }),
  result: o => wall('wallN', 292) + desk(140, 230, 360) + `<rect x="210" y="110" width="220" height="120" rx="8" ${F('ink')}/><rect x="218" y="118" width="204" height="104" fill="${o.mood === 'good' ? '#e8fff1' : o.mood === 'bad' ? '#fff0ee' : '#eef3ff'}"/>` +
    `<circle cx="320" cy="160" r="16" stroke="#9cc3ff" stroke-width="4" fill="none" stroke-dasharray="60 40" class="a-spin" style="transform-origin:320px 160px"/>` +
    `<text x="320" y="205" text-anchor="middle" font-size="18" font-weight="800" fill="${o.mood === 'good' ? '#18a058' : o.mood === 'bad' ? '#d94a3b' : '#5b6676'}" class="a-pop" style="animation-delay:1.4s">${o.mood === 'good' ? '합격을 축하합니다' : o.mood === 'bad' ? '불합격' : '결과 조회'}</text>` +
    person(320, 292, { pose: 'sit', back: true, shirt: 'accent', s: 1.1 }) + (o.mood === 'good' ? confetti() : ''),
  street: o => sky(o.tod || 'day') + skyline(300, o.tod === 'night') + `<rect y="300" width="640" height="60" ${F('road')}/>` + person(320, 330, { shirt: 'accent' }) + particles(o.season, 0, 0, 640, 300),
  shop: o => wall('wallWarm', 292) + `<rect x="60" y="170" width="520" height="120" rx="8" ${F('wood')}/><rect x="80" y="130" width="480" height="40" fill="#fff" opacity=".7"/>` +
    [0, 1, 2, 3, 4, 5].map(i => `<ellipse cx="${120 + i * 75}" cy="150" rx="24" ry="14" fill="${['#f2b680', '#e8893a', '#f6d28b'][i % 3]}"/>`).join('') +
    `<path d="M300 110 q4 -14 0 -28 M320 110 q4 -14 0 -28" stroke="#ccc" stroke-width="3" fill="none" class="a-steam"/>` + person(440, 300, { shirt: 'accent', mood: 'happy' }),
  lab: o => wall('wallCool', 292) + desk(100, 220, 440) + `<path d="M180 220 L190 160 L200 160 L210 220 Z" fill="#cfe3ff" stroke="#9cc3ff"/><rect x="188" y="150" width="14" height="10" fill="#9cc3ff"/>` +
    [0, 1, 2].map(i => `<circle cx="${195}" cy="${200 - i * 18}" r="4" fill="#8be38b" class="a-rise" style="animation-delay:-${i * 0.7}s"/>`).join('') +
    `<rect x="380" y="150" width="110" height="70" rx="6" ${F('ink')}/><path d="M390 200 l20 -20 l20 10 l20 -30 l20 15" stroke="#5ef0ff" stroke-width="3" fill="none" class="a-draw"/>` + person(300, 290, { shirt: 'labcoat' }),
};
function confetti() { let o = ''; for (let i = 0; i < 18; i++) o += `<rect x="${30 + (i * 37) % 580}" y="-10" width="8" height="12" fill="${['#ff6b8b', '#ffd34d', '#5ef0ff', '#8be38b'][i % 4]}" class="a-fall" style="animation-delay:-${(i * 0.3) % 3}s;animation-duration:${2.4 + (i % 4) * 0.4}s"/>`; return o; }

// ── 장면 고르기 ──
const EVENT_SCENE = {
  pc: 'chat', academyCall: 'family', fight: 'street', cheat: 'chat', favorBack: 'classroom', studyGroup: 'classroom', rivalGap: 'classroom', bully: 'classroom', sns: 'chat',
  dropoutFriend: 'street', confess: 'love', seeAgain: 'classroom', crush: 'love', dateExam: 'love', partnerGrade: 'phone', breakup: 'breakup', datingRumor: 'family',
  parentTalk: 'family', tutor: 'family', consult: 'consult', compare: 'family', push: 'family', secretFound: 'family', parentFight: 'parentFight', crisis: 'family', sick: 'hospital',
  phone: 'phone', mockShock: 'night_study', burnout: 'night_study', sleep: 'night_study', seteuk: 'classroom', groupWork: 'classroom', senior: 'campus',
  contest: 'lab', council: 'stage', careerDay: 'consult', rank: 'game', esports: 'game', casting: 'stage', youtube: 'phone', coding: 'code', artAcademy: 'art', sportsTeam: 'sport',
  injury: 'hospital', concert: 'stage', transfer: 'classroom', partTime: 'shop', teacher: 'classroom', interview: 'consult', cold: 'hospital',
  cc: 'campus', distance: 'phone', startupFriend: 'office', compareSNS: 'phone', drink: 'friends', retire: 'family', coin: 'phone', prof: 'lab', friendReunion: 'street',
};
const SEASON = { g1s1: 'spring', g1v1: 'summer', g1s2: 'autumn', g1v2: 'winter', g2s1: 'spring', g2v1: 'summer', g2s2: 'autumn', g2v2: 'winter', g3s1: 'spring', g3v1: 'summer', g3s2: 'autumn' };
function sceneFor(prompt) {
  const k = prompt.key || '';
  const turn = k.split(':')[0];
  const season = SEASON[turn] || null;
  const m = k.match(/:ev:(\w+)/);
  if (m && EVENT_SCENE[m[1]]) return { name: EVENT_SCENE[m[1]], season };
  if (/:methods$/.test(k)) return { name: turn === 'g3s1' ? 'night_study' : 'academy', season };
  if (/:hp$/.test(k)) return { name: 'exam', season };
  if (/:alloc$/.test(k)) return { name: turn === 'g3s2' ? 'night_study' : 'classroom', season };
  if (/:vac$/.test(k)) return { name: season === 'winter' ? 'winter' : 'summer', season };
  if (/:club$/.test(k)) return { name: 'stage', season };
  if (/:subject$/.test(k) || /:class$/.test(k)) return { name: 'classroom', season };
  if (/sameUni/.test(k)) return { name: 'love', season: 'summer' };
  if (/g3v1/.test(k)) return { name: 'consult', season };
  if (/d100/.test(k)) return { name: 'night_study', season: 'autumn' };
  if (/csat/.test(k)) return { name: 'exam', season: 'winter' };
  if (/:strategy|:pick/.test(k)) return { name: 'result', season };
  if (/^retake/.test(k)) return { name: /sns/.test(k) ? 'phone' : 'night_study', season };
  if (/^col1/.test(k)) return { name: 'campus', season: 'spring' };
  if (/^col2/.test(k)) return { name: /입영/.test(prompt.title || '') ? 'army' : 'campus', season: 'autumn' };
  if (/^col3/.test(k)) return { name: /안 맞/.test(prompt.title || '') ? 'night_study' : 'lab', season };
  if (/^car/.test(k)) return { name: 'office', season };
  if (/^alt/.test(k)) return { name: 'street', season };
  return { name: 'street', season };
}
const CAREER_SCENE = { med: 'hospital', nurse: 'hospital', eng: 'lab', sci: 'lab', cs: 'code', biz: 'office', law: 'office', edu: 'classroom', hum: 'office', soc: 'consult', media: 'stage', art: 'art', perf: 'stage', sport: 'sport', none: 'shop' };
function sceneForCareer(ending, field) {
  if (/크리에이터|유튜버|스트리머/.test(ending.career)) return { name: 'phone' };
  if (/프로게이머/.test(ending.career)) return { name: 'game' };
  if (/아이돌|배우|뮤지/.test(ending.career)) return { name: 'stage' };
  if (/사장|제과|가게|정비|용접|전기/.test(ending.career)) return { name: 'shop' };
  if (/교사|강사/.test(ending.career)) return { name: 'classroom' };
  return { name: CAREER_SCENE[field] || 'office', tod: ending.satTag === 'regret' ? 'night' : 'day' };
}

const VIDEOS = {};   // 예: VIDEOS.exam = 'media/exam.mp4'
function render(name, o) {
  o = o || {};
  uid++;
  if (VIDEOS[name]) return `<video class="clipvideo" src="${VIDEOS[name]}" autoplay muted loop playsinline></video>`;
  const fn = SCENES[name] || SCENES.street;
  const tod = /night|phone|breakup|parentFight|friends|academy|winter|game|code|stage/.test(name) ? 'night' : 'day';
  // 한 태그에 style이 두 번 들어간 곳은 하나로 합친다(두 번째 style은 브라우저가 버린다)
  const body = fn(o).replace(/<([a-zA-Z]+)((?:\s+[^>]*?)?)(\/?)>/g, (m, tag, attrs, close) => {
    const st = []; const rest = attrs.replace(/\sstyle="([^"]*)"/g, (_, v) => { st.push(v); return ''; });
    return st.length > 1 ? `<${tag}${rest} style="${st.join(';')}"${close}>` : m;
  });
  return `<svg class="scene" data-tod="${o.tod || tod}" viewBox="0 0 640 360" role="img" aria-label="${o.label || name}" preserveAspectRatio="xMidYMid slice">${body}</svg>`;
}

root.CareerScenes = { render, sceneFor, sceneForCareer, VIDEOS, names: Object.keys(SCENES) };
})(typeof window !== 'undefined' ? window : this);
