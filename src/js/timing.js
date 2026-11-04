// Timing inputs: shrinking rings (press), beat sequences (rhythm), hold-and-release gauges (hold),
// and defensive rings (Hit the Dirt / Counter-shot). Positions are in stage coordinates.
G.timing = (() => {
  let op = null; // the active timing operation
  const fx = []; // fading judge flashes
  const T = () => D.config.timing;
  const ws = () => T().windowScale[G.settings.window] || 1;
  const R0 = 30;

  const finishLater = (o, ms = 160) => setTimeout(() => { if (op === o) op = null; }, ms * Math.max(G.speed, 0.2));
  const flash = (x, y, res) => fx.push({ x, y, res, t: G.now() });

  // ---- press ----
  function press(o) {
    return new Promise((resolve) => {
      const ringMs = (o.ringMs || T().ringMs) * (G.testMode ? 0.05 : 1);
      const start = G.now() + T().leadInMs * (G.testMode ? 0.05 : 1);
      const cur = { kind: 'press', x: o.x, y: o.y, start, ringMs, T: start + ringMs, done: false, label: o.label || 'TAP' };
      cur.judge = (t) => {
        if (cur.done) return;
        const err = Math.abs(t - cur.T);
        const res = err <= T().perfectMs * ws() ? 'perfect' : err <= T().goodMs * ws() ? 'good' : 'miss';
        cur.done = true; cur.res = res; flash(cur.x, cur.y, res); finishLater(cur);
        resolve(res);
      };
      cur.onPress = (t) => { if (t >= cur.start - 40) cur.judge(t); };
      cur.tick = (now) => {
        if (cur.done) return;
        if (G.settings.autoOffense || G.testMode) { if (now >= cur.T) { cur.done = true; cur.res = 'good'; flash(cur.x, cur.y, 'good'); finishLater(cur); resolve('good'); } return; }
        if (now > cur.T + T().goodMs * ws()) cur.judge(now + 9999);
      };
      op = cur;
    });
  }

  // ---- rhythm: n beats, onBeat(i, res) fires as each beat is judged ----
  function rhythm(o) {
    return new Promise((resolve) => {
      const k = G.testMode ? 0.05 : 1;
      const ringMs = (o.ringMs || T().ringMs * 0.8) * k;
      const gap = (o.gap || T().rhythmGapMs) * k;
      const start = G.now() + T().leadInMs * k;
      const beats = [];
      for (let i = 0; i < o.beats; i++) beats.push({ T: start + ringMs + i * gap, res: null });
      const cur = { kind: 'rhythm', x: o.x, y: o.y, beats, ringMs, done: false, label: o.label || 'TAP x' + o.beats };
      const judgeBeat = (i, res) => {
        beats[i].res = res; flash(cur.x + (i - (o.beats - 1) / 2) * 30, cur.y - 46, res);
        o.onBeat && o.onBeat(i, res);
        if (beats.every((b) => b.res)) { cur.done = true; finishLater(cur); resolve(beats.map((b) => b.res)); }
      };
      cur.onPress = (t) => {
        if (cur.done) return;
        const i = beats.findIndex((b) => !b.res);
        if (i < 0) return;
        const b = beats[i];
        if (t < b.T - ringMs) return; // ring not visible yet
        const err = Math.abs(t - b.T);
        judgeBeat(i, err <= T().perfectMs * ws() ? 'perfect' : err <= T().goodMs * ws() ? 'good' : 'miss');
      };
      cur.tick = (now) => {
        if (cur.done) return;
        beats.forEach((b, i) => {
          if (b.res) return;
          if ((G.settings.autoOffense || G.testMode) && now >= b.T && beats.slice(0, i).every((x) => x.res)) judgeBeat(i, 'good');
          else if (now > b.T + T().goodMs * ws() && beats.slice(0, i).every((x) => x.res)) judgeBeat(i, 'miss');
        });
      };
      op = cur;
    });
  }

  // ---- hold: press, then release in the green zone ----
  function hold(o) {
    return new Promise((resolve) => {
      const k = G.testMode ? 0.05 : 1;
      const holdMs = (o.holdMs || T().holdMs) * k;
      const cur = { kind: 'hold', x: o.x, y: o.y, holdMs, p0: null, done: false, sweet: T().holdSweet, created: G.now(), label: 'HOLD' };
      const W = () => 1.25 * ws();
      const judge = (t) => {
        if (cur.done || cur.p0 === null) return;
        const target = cur.p0 + cur.sweet * holdMs;
        const err = Math.abs(t - target);
        const res = err <= T().perfectMs * W() ? 'perfect' : err <= T().goodMs * W() ? 'good' : 'miss';
        cur.done = true; cur.res = res; cur.fill = (t - cur.p0) / holdMs; flash(cur.x, cur.y, res); finishLater(cur, 260);
        resolve(res);
      };
      cur.onPress = (t) => { if (!cur.done && cur.p0 === null) cur.p0 = t; };
      cur.onRelease = (t) => { if (cur.p0 !== null) judge(t); };
      cur.tick = (now) => {
        if (cur.done) return;
        if (G.settings.autoOffense || G.testMode) {
          if (cur.p0 === null && now - cur.created > 200 * k) cur.p0 = now;
          if (cur.p0 !== null && now >= cur.p0 + cur.sweet * holdMs) { cur.done = true; cur.res = 'good'; flash(cur.x, cur.y, 'good'); finishLater(cur); resolve('good'); }
          return;
        }
        if (cur.p0 !== null && now > cur.p0 + holdMs * 1.08) judge(now + 9999);
      };
      op = cur;
    });
  }

  // ---- defense: returns 'parry' | 'dodge' | 'hit' ----
  function defend(o) {
    return new Promise((resolve) => {
      const k = G.testMode ? 0.05 : 1;
      const ringMs = (o.ringMs || T().ringMs) * k;
      const start = G.now() + 120 * k;
      const pauseMs = o.feint ? G.ri(280, 520) * k : 0;
      const pauseAt = ringMs * 0.55;
      const cur = { kind: 'defend', x: o.x, y: o.y, start, ringMs, pauseMs, pauseAt, feint: !!o.feint, T: start + ringMs + pauseMs, done: false, label: o.label || '' };
      const dodgeW = () => Math.max(40, T().dodgeMs * ws() * (1 + G.mod('passive', 'dodgeWindowPct')));
      const parryW = () => Math.max(25, T().parryMs * ws() * (1 + G.mod('passive', 'parryWindowPct')));
      const done = (res) => { cur.done = true; cur.res = res; flash(cur.x, cur.y, res); finishLater(cur, 200); resolve(res); };
      cur.onDefend = (kind, t) => {
        if (cur.done || t < cur.start) return;
        const err = Math.abs(t - cur.T);
        if (kind === 'counter') done(err <= parryW() ? 'parry' : 'hit');
        else done(err <= dodgeW() ? 'dodge' : 'hit');
      };
      cur.tick = (now) => {
        if (cur.done) return;
        if (G.settings.autoDefense || G.testMode) {
          if (now >= cur.T) done(G.testMode && G.testDefense ? G.testDefense() : 'dodge');
          return;
        }
        if (now > cur.T + dodgeW()) done('hit');
      };
      op = cur;
    });
  }

  // ---- input routing ----
  function onPress(t = G.now()) { if (op && op.onPress) op.onPress(t); }
  function onRelease(t = G.now()) { if (op && op.onRelease) op.onRelease(t); }
  function onDefend(kind, t = G.now()) { if (op && op.onDefend) op.onDefend(kind, t); }
  const active = () => op;

  // ---- drawing ----
  const COL = { perfect: '#f0c75a', good: '#9cc95e', miss: '#e0603f', parry: '#f0c75a', dodge: '#c9d2a9', hit: '#e0603f' };
  const WORD = { perfect: 'PERFECT', good: 'GOOD', miss: 'MISS', parry: 'COUNTER!', dodge: 'DODGED', hit: 'HIT' };
  function ring(c, x, y, r, col, w, alpha = 1) {
    c.save(); c.globalAlpha = alpha; c.strokeStyle = col; c.lineWidth = w;
    c.beginPath(); c.arc(x, y, Math.max(0, r), 0, Math.PI * 2); c.stroke(); c.restore();
  }
  function draw(c, now) {
    if (op && op.tick) op.tick(now);
    const o = op;
    if (o && !o.done) {
      if (o.kind === 'press') {
        if (now >= o.start - 60) {
          const fr = (o.T - now) / o.ringMs;
          ring(c, o.x, o.y, R0, '#fff8e0', 5);
          ring(c, o.x, o.y, R0 * (1 + 2.3 * Math.max(-0.4, fr)), '#f0c75a', 4);
          label(c, o.x, o.y + R0 + 26, o.label);
        }
      } else if (o.kind === 'rhythm') {
        o.beats.forEach((b, i) => {
          const bx = o.x + (i - (o.beats.length - 1) / 2) * 30, by = o.y - 46;
          c.fillStyle = b.res ? COL[b.res] : '#00000088'; c.beginPath(); c.arc(bx, by, 8, 0, 7); c.fill();
          c.strokeStyle = '#fff8e0'; c.lineWidth = 2; c.stroke();
        });
        const nb = o.beats.find((b) => !b.res);
        if (nb && now >= nb.T - o.ringMs) {
          const fr = (nb.T - now) / o.ringMs;
          ring(c, o.x, o.y, R0, '#fff8e0', 5);
          ring(c, o.x, o.y, R0 * (1 + 2.3 * Math.max(-0.4, fr)), '#f0c75a', 4);
        }
        label(c, o.x, o.y + R0 + 26, 'TAP ON EACH BEAT');
      } else if (o.kind === 'hold') {
        const W = 160, H = 18, x0 = o.x - W / 2, y0 = o.y - 9;
        c.fillStyle = '#000000aa'; c.fillRect(x0 - 4, y0 - 4, W + 8, H + 8);
        const sw = (T().goodMs * 1.25 * ws()) / o.holdMs, pw = (T().perfectMs * 1.25 * ws()) / o.holdMs;
        c.fillStyle = '#9cc95e88'; c.fillRect(x0 + (o.sweet - sw) * W, y0, sw * 2 * W, H);
        c.fillStyle = '#f0c75acc'; c.fillRect(x0 + (o.sweet - pw) * W, y0, pw * 2 * W, H);
        const fill = o.p0 === null ? 0 : Math.min(1.1, (now - o.p0) / o.holdMs);
        c.fillStyle = '#fff8e0'; c.fillRect(x0 + Math.min(1, fill) * W - 2, y0 - 6, 4, H + 12);
        c.strokeStyle = '#fff8e0'; c.lineWidth = 2; c.strokeRect(x0, y0, W, H);
        label(c, o.x, y0 + H + 28, o.p0 === null ? 'PRESS AND HOLD' : 'RELEASE IN THE GOLD');
      } else if (o.kind === 'defend') {
        let el = now - o.start;
        let pausing = false;
        if (o.feint && el > o.pauseAt) { if (el < o.pauseAt + o.pauseMs) pausing = true; el = Math.max(o.pauseAt, el - o.pauseMs); }
        if (el >= -60) {
          const fr = 1 - el / o.ringMs;
          ring(c, o.x, o.y, R0 + 4, '#ffe0d0', 5);
          const blink = pausing ? (Math.floor(now / 70) % 2 ? 0.35 : 1) : 1;
          ring(c, o.x, o.y, (R0 + 4) * (1 + 2.6 * Math.max(-0.4, fr)), '#e0603f', 5, blink);
          if (pausing) label(c, o.x, o.y - R0 - 30, 'FEINT...', '#ffb3a0');
        }
      }
    }
    // judge flashes
    for (let i = fx.length - 1; i >= 0; i--) {
      const f = fx[i];
      const age = (now - f.t) / 700;
      if (age > 1) { fx.splice(i, 1); continue; }
      ring(c, f.x, f.y, R0 * (1 + age * 1.2), COL[f.res], 4 * (1 - age), 1 - age);
      c.save(); c.globalAlpha = 1 - age; c.font = `700 ${f.res === 'perfect' || f.res === 'parry' ? 30 : 24}px 'Stardos Stencil', Impact, sans-serif`;
      c.textAlign = 'center'; c.lineWidth = 5; c.strokeStyle = '#000'; c.strokeText(WORD[f.res], f.x, f.y - R0 - 14 - age * 24);
      c.fillStyle = COL[f.res]; c.fillText(WORD[f.res], f.x, f.y - R0 - 14 - age * 24); c.restore();
    }
  }
  function label(c, x, y, text, col = '#fff8e0') {
    c.save(); c.font = "700 18px 'Barlow Condensed', 'Arial Narrow', sans-serif"; c.textAlign = 'center';
    c.lineWidth = 4; c.strokeStyle = '#000'; c.strokeText(text, x, y); c.fillStyle = col; c.fillText(text, x, y); c.restore();
  }
  const clear = () => { op = null; fx.length = 0; };

  return { press, rhythm, hold, defend, onPress, onRelease, onDefend, draw, active, clear };
})();
