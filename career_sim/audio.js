// 어땠을까 — 배경 음악과 효과음
//  소리 파일 없이 브라우저(Web Audio)에서 바로 만든다. 학년·시기(phase)마다 곡 분위기가 바뀌고,
//  선택이 좋았는지·아쉬웠는지에 따라 효과음이 다르다. 브라우저 정책상 첫 터치·클릭 뒤에 소리가 난다.
(function (root) {
'use strict';
let ctx = null, master = null, musicBus = null, sfxBus = null, noiseBuf = null;
const pref = { music: true, sfx: true };
try { const v = JSON.parse(localStorage.getItem('ccs:sound') || 'null'); if (v) Object.assign(pref, v); } catch (e) {}
function save() { try { localStorage.setItem('ccs:sound', JSON.stringify(pref)); } catch (e) {} }

function ensure() {
  if (ctx) { if (ctx.state === 'suspended' && !document.hidden) ctx.resume(); return true; }
  const AC = root.AudioContext || root.webkitAudioContext;
  if (!AC) return false;
  ctx = new AC();
  const comp = ctx.createDynamicsCompressor();
  comp.threshold.value = -18; comp.ratio.value = 3;
  master = ctx.createGain(); master.gain.value = 0.9;
  musicBus = ctx.createGain(); musicBus.gain.value = pref.music ? 0.2 : 0;
  sfxBus = ctx.createGain(); sfxBus.gain.value = pref.sfx ? 0.55 : 0;
  musicBus.connect(master); sfxBus.connect(master); master.connect(comp); comp.connect(ctx.destination);
  noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 0.5, ctx.sampleRate);
  const d = noiseBuf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  return true;
}
const hz = m => 440 * Math.pow(2, (m - 69) / 12);

// 음 하나: 파형·길이·크기·엔벨로프
function tone(bus, t, midi, dur, vol, type, opt) {
  opt = opt || {};
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = type || 'triangle';
  o.frequency.setValueAtTime(hz(midi), t);
  if (opt.slide) o.frequency.exponentialRampToValueAtTime(hz(midi + opt.slide), t + dur);
  if (opt.detune) o.detune.value = opt.detune;
  const a = opt.attack || 0.008, r = opt.release || Math.min(0.25, dur * 0.8);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(vol, t + a);
  g.gain.setValueAtTime(vol, t + Math.max(a, dur - r));
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  let node = o;
  if (opt.lp) { const f = ctx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = opt.lp; o.connect(f); node = f; }
  node.connect(g); g.connect(bus);
  o.start(t); o.stop(t + dur + 0.02);
}
function noise(bus, t, dur, vol, hp, lp) {
  const s = ctx.createBufferSource(), g = ctx.createGain(), f = ctx.createBiquadFilter();
  s.buffer = noiseBuf; f.type = hp ? 'highpass' : 'lowpass'; f.frequency.value = hp || lp || 2000;
  g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  s.connect(f); f.connect(g); g.connect(bus); s.start(t); s.stop(t + dur + 0.02);
}
function kick(t, vol) {
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = 'sine'; o.frequency.setValueAtTime(130, t); o.frequency.exponentialRampToValueAtTime(45, t + 0.14);
  g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
  o.connect(g); g.connect(musicBus); o.start(t); o.stop(t + 0.22);
}

// ── 곡 ────────────────────────────────────────────────
//  root: 으뜸음(MIDI), scale: 음계, prog: 마디마다 화음(음계 안 몇 번째 음), bpm, lead: 멜로디 악기, beat: 드럼 정도
const MAJ = [0, 2, 4, 5, 7, 9, 11], MIN = [0, 2, 3, 5, 7, 8, 10];
const SONGS = {
  intro: { root: 65, scale: MAJ, prog: [0, 5, 3, 4], bpm: 92, lead: 'sine', beat: 0, seed: 3, dens: 0.45 },
  g1:    { root: 67, scale: MAJ, prog: [0, 4, 5, 3], bpm: 112, lead: 'square', beat: 2, seed: 11, dens: 0.6 },
  g2:    { root: 62, scale: MAJ, prog: [3, 4, 2, 5], bpm: 116, lead: 'triangle', beat: 2, seed: 23, dens: 0.62 },
  g3:    { root: 64, scale: MIN, prog: [0, 5, 2, 6], bpm: 98, lead: 'triangle', beat: 1, seed: 37, dens: 0.5 },
  adm:   { root: 62, scale: MIN, prog: [0, 0, 5, 4], bpm: 88, lead: 'sine', beat: 1, seed: 41, dens: 0.4 },
  col:   { root: 69, scale: MAJ, prog: [0, 5, 3, 4], bpm: 120, lead: 'square', beat: 2, seed: 53, dens: 0.6 },
  end:   { root: 65, scale: MAJ, prog: [3, 4, 0, 5], bpm: 80, lead: 'sine', beat: 0, seed: 67, dens: 0.38 },
};
function rng(seed) { let a = seed >>> 0; return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const deg = (S, d, oct) => S.root + S.scale[((d % 7) + 7) % 7] + 12 * (Math.floor(d / 7) + (oct || 0));
// 4마디(64칸) 멜로디를 정해진 씨앗으로 만든다 — 같은 시기엔 늘 같은 곡, 두 번째 바퀴는 살짝 다르게
function makeMelody(S, variant) {
  const R = rng(S.seed * 7 + variant), mel = [];
  let cur = 2;
  for (let bar = 0; bar < 4; bar++) {
    const ch = S.prog[bar];
    for (let st = 0; st < 16; st += 2) {
      const strong = st % 8 === 0, p = R();
      if (!strong && p > S.dens) { mel.push(null); continue; }
      if (strong) { const ct = [ch, ch + 2, ch + 4]; cur = ct[Math.floor(R() * 3)]; }
      else cur += [-1, 1, 1, -2, 2, 0][Math.floor(R() * 6)];
      cur = Math.max(-1, Math.min(9, cur));
      const len = R() < 0.25 && !strong ? 1 : 2;
      mel.push({ d: cur, len: (bar === 3 && st === 14) ? 2 : len * (R() < 0.2 ? 2 : 1) });
    }
  }
  return mel;
}
let song = null, songKey = null, nextKey = 'intro', step = 0, nextT = 0, timer = null, loopN = 0, mels = {};
function melOf(key, v) { const k = key + v; return mels[k] || (mels[k] = makeMelody(SONGS[key], v)); }
function schedule() {
  if (!ctx || !pref.music) return;
  const ahead = 0.15;
  while (nextT < ctx.currentTime + ahead) {
    if (step % 64 === 0) { if (nextKey !== songKey) { songKey = nextKey; step = 0; loopN = 0; } song = SONGS[songKey]; }
    const S = song, st = step % 64, bar = Math.floor(st / 16), ch = S.prog[bar], t = nextT, sp = 60 / S.bpm / 4;
    // 패드: 마디 첫 칸에 화음
    if (st % 16 === 0) [0, 2, 4].forEach((x, i) => tone(musicBus, t, deg(S, ch + x, -1), sp * 16, 0.05 - i * 0.008, 'sine', { attack: 0.3, release: 0.6 }));
    // 베이스
    if (st % 8 === 0) tone(musicBus, t, deg(S, ch, -2), sp * 6, 0.16, 'triangle', { lp: 600 });
    if (S.beat >= 2 && st % 8 === 6) tone(musicBus, t, deg(S, ch + 4, -2), sp * 2, 0.1, 'triangle', { lp: 600 });
    // 멜로디(8분음표 칸)
    if (st % 2 === 0) {
      const n = melOf(songKey, loopN % 2)[st / 2];
      if (n) tone(musicBus, t, deg(S, n.d, 1), sp * 2 * n.len * 0.95, S.lead === 'square' ? 0.045 : 0.09, S.lead, { lp: S.lead === 'square' ? 2400 : 4000 });
    }
    // 드럼
    if (S.beat >= 1 && st % 8 === 0) kick(t, S.beat >= 2 ? 0.35 : 0.22);
    if (S.beat >= 2 && st % 4 === 2) noise(musicBus, t, 0.04, 0.05, 7000);
    if (S.beat >= 2 && st % 16 === 8) noise(musicBus, t, 0.12, 0.08, 1800);
    nextT += sp; step++;
    if (step % 64 === 0) loopN++;
  }
}
function startMusic() {
  if (!ensure() || timer) return;
  nextT = ctx.currentTime + 0.1; step = 0; songKey = null;
  timer = setInterval(schedule, 40);
}
function stopMusic() { clearInterval(timer); timer = null; }

// ── 효과음 ──────────────────────────────────────────────
const SFX = {
  tap: t => tone(sfxBus, t, 84, 0.06, 0.12, 'sine'),
  select: t => { tone(sfxBus, t, 79, 0.07, 0.16, 'triangle'); tone(sfxBus, t + 0.06, 86, 0.1, 0.14, 'triangle'); },
  plus: t => tone(sfxBus, t, 81, 0.07, 0.12, 'square', { slide: 5, lp: 3000 }),
  minus: t => tone(sfxBus, t, 79, 0.07, 0.12, 'square', { slide: -5, lp: 3000 }),
  good: t => [72, 76, 79, 84].forEach((m, i) => tone(sfxBus, t + i * 0.07, m, 0.22, 0.17, 'triangle')),
  normal: t => { tone(sfxBus, t, 74, 0.14, 0.13, 'sine'); tone(sfxBus, t + 0.12, 76, 0.2, 0.12, 'sine'); },
  bad: t => { tone(sfxBus, t, 67, 0.22, 0.15, 'square', { slide: -2, lp: 1400 }); tone(sfxBus, t + 0.2, 63, 0.4, 0.15, 'square', { slide: -3, lp: 1200 }); },
  fate: t => { tone(sfxBus, t, 55, 0.9, 0.12, 'sine', { attack: 0.05, release: 0.6 }); tone(sfxBus, t + 0.25, 61, 0.9, 0.09, 'sine', { attack: 0.05, release: 0.6 }); noise(sfxBus, t, 0.5, 0.05, null, 600); },   // 운: 낮게 울리는 두 음
  bell: t => [76, 72, 74, 67].forEach((m, i) => tone(sfxBus, t + i * 0.32, m, 0.6, 0.11, 'sine', { release: 0.5 })),   // 학교 종
  page: t => noise(sfxBus, t, 0.18, 0.12, 900),
  exam: t => { [0, 0.18, 0.36].forEach(d => tone(sfxBus, t + d, 88, 0.1, 0.1, 'square', { lp: 3000 })); },
  pass: t => { [72, 76, 79].forEach(m => tone(sfxBus, t, m, 0.3, 0.1, 'square', { lp: 2600 })); [77, 81, 84].forEach(m => tone(sfxBus, t + 0.28, m, 0.3, 0.1, 'square', { lp: 2600 })); [79, 84, 88].forEach(m => tone(sfxBus, t + 0.56, m, 0.7, 0.11, 'square', { lp: 2600 })); },
  fail: t => [71, 70, 69, 68].forEach((m, i) => tone(sfxBus, t + i * 0.28, m, i === 3 ? 0.8 : 0.3, 0.12, 'triangle', { slide: i === 3 ? -1 : 0 })),
  end: t => { [60, 64, 67, 72, 76].forEach((m, i) => tone(sfxBus, t + i * 0.12, m, 1.2 - i * 0.1, 0.09, 'sine', { attack: 0.02, release: 0.8 })); },
};
function sfx(name) {
  if (!pref.sfx || !SFX[name] || !ensure()) return;
  SFX[name](ctx.currentTime + 0.01);
}

const API = {
  // 첫 터치·클릭 때 부른다(브라우저가 그 전엔 소리를 막는다)
  unlock() { if (!ensure()) return; if (pref.music) startMusic(); },
  setPhase(key) { nextKey = SONGS[key] ? key : 'intro'; },
  sfx,
  get music() { return pref.music; },
  get effects() { return pref.sfx; },
  toggleMusic() {
    pref.music = !pref.music; save();
    if (ensure()) { musicBus.gain.setTargetAtTime(pref.music ? 0.2 : 0, ctx.currentTime, 0.1); if (pref.music) startMusic(); else stopMusic(); }
    return pref.music;
  },
  toggleSfx() { pref.sfx = !pref.sfx; save(); if (ensure()) sfxBus.gain.value = pref.sfx ? 0.55 : 0; return pref.sfx; },
};
document.addEventListener('visibilitychange', () => { if (!ctx) return; if (document.hidden) ctx.suspend(); else ctx.resume(); });
root.CareerAudio = API;
})(typeof window !== 'undefined' ? window : this);
