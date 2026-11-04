// Side-view, turn-based squad combat with timing inputs on offense and defense.
G.battle = (() => {
  const W = 1000, H = 620;
  let B = null;
  let cv, ctx, scale = 1, rafId = 0, resizeObs = null;
  const floaters = [], particles = [], tracers = [];
  let shakeT = 0, shakeMag = 0;
  const C = () => D.config.combat;
  const ALLY_SLOTS = [{ x: 310, y: 528 }, { x: 205, y: 498 }, { x: 95, y: 540 }];

  // ---------- setup ----------
  function initCanvas() {
    if (cv) return;
    cv = G.$('#stage');
    ctx = cv.getContext('2d');
    const wrap = G.$('#stage-wrap');
    const resize = () => {
      const bw = wrap.clientWidth, bh = wrap.clientHeight;
      if (!bw || !bh) return;
      const s = Math.min(bw / W, bh / H);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      cv.style.width = `${Math.floor(W * s)}px`;
      cv.style.height = `${Math.floor(H * s)}px`;
      cv.width = Math.floor(W * s * dpr);
      cv.height = Math.floor(H * s * dpr);
      scale = s * dpr;
    };
    if (window.ResizeObserver) { resizeObs = new ResizeObserver(resize); resizeObs.observe(wrap); }
    window.addEventListener('resize', resize);
    resize();
    G._resizeStage = resize;
    cv.addEventListener('pointerdown', onCanvasDown);
    cv.addEventListener('pointerup', (e) => { G.timing.onRelease(G.now()); });
    cv.addEventListener('pointercancel', () => G.timing.onRelease(G.now()));
    window.addEventListener('keydown', onKey);
    window.addEventListener('keyup', (e) => {
      if (!B || B.over) return;
      if (['Space', 'Enter', 'KeyZ', 'KeyX', 'KeyJ', 'KeyK'].includes(e.code)) G.timing.onRelease(G.now());
    });
  }

  const offenseOp = () => { const o = G.timing.active(); return o && !o.done && o.kind !== 'defend' ? o : null; };
  const defenseOp = () => { const o = G.timing.active(); return o && !o.done && o.kind === 'defend' ? o : null; };

  function toLogical(e) {
    const r = cv.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
  }
  function onCanvasDown(e) {
    if (!B || B.over) return;
    G.audio.unlock();
    if (offenseOp()) { e.preventDefault(); G.timing.onPress(G.now()); return; }
    if (B.phase === 'command') {
      const p = toLogical(e);
      const hit = B.enemies.filter((u) => !u.dead).find((u) => {
        const sz = G.art.size(u.art);
        return Math.abs(p.x - u.x) < (sz.w * u.s) / 2 + 12 && p.y < u.y + 20 && p.y > u.y - sz.h * u.s - 20;
      });
      if (hit) { B.target = hit; G.sfx('click'); renderTargetLine(); }
    }
  }
  function onKey(e) {
    if (!B || B.over || e.repeat) return;
    if (G.$('#modal') && !G.$('#modal').hidden) return;
    const code = e.code;
    if (offenseOp()) {
      if (['Space', 'Enter', 'KeyZ', 'KeyX', 'KeyJ', 'KeyK'].includes(code)) { e.preventDefault(); G.timing.onPress(G.now()); }
      return;
    }
    if (B.phase === 'enemy') {
      if (['Space', 'KeyZ', 'KeyA', 'ArrowLeft', 'KeyJ'].includes(code)) { e.preventDefault(); G.timing.onDefend('dodge', G.now()); }
      else if (['KeyX', 'KeyD', 'ArrowRight', 'KeyK', 'Enter', 'ShiftLeft', 'ShiftRight'].includes(code)) { e.preventDefault(); G.timing.onDefend('counter', G.now()); }
      return;
    }
    if (B.phase === 'command') {
      if (code === 'ArrowLeft' || code === 'ArrowRight' || code === 'Tab') {
        e.preventDefault();
        const alive = B.enemies.filter((u) => !u.dead);
        const i = alive.indexOf(B.target);
        B.target = alive[(i + (code === 'ArrowLeft' ? -1 : 1) + alive.length) % alive.length];
        renderTargetLine();
        return;
      }
      const n = { Digit1: 0, Digit2: 1, Digit3: 2, Digit4: 3, Digit5: 4, Space: 0 }[code];
      if (n !== undefined) {
        const btns = G.$$('#cmds button:not(:disabled)');
        const all = G.$$('#cmds button');
        const b = code === 'Space' ? btns[0] : all[n];
        if (b && !b.disabled) { e.preventDefault(); b.click(); }
      }
    }
  }

  // ---------- units ----------
  const interval = (u) => 1000 / Math.max(1, u.spd * (u.side === 'ally' ? 1 + G.mod('passive', 'spdPct') : 1));
  function mkAlly(soldier) {
    const def = G.classDef(soldier.cls);
    const maxHp = G.maxHp(soldier.cls);
    const hp = Math.round(Math.max(0, soldier.frac) * maxHp);
    return {
      side: 'ally', cls: soldier.cls, art: 'soldier', def, ref: soldier, name: def.name,
      maxHp, hp, dead: hp <= 0, spd: def.spd, atk: def.atk,
      ap: Math.min(C().apMax, C().startAp + G.mod('passive', 'startAp')), burn: 0, shield: 0, cover: false,
      s: 0.92, x: 0, y: 0, pose: 'idle', fx: {},
    };
  }
  function mkEnemy(key, row) {
    const def = D.enemies[key];
    const ch = G.chapter();
    const heat = (G.run.heat || 0) * D.config.rewards.heatEnemyPct;
    // bosses and strongpoints are tuned by hand, so they skip the per-row ramp
    const rowF = def.boss || def.heavy ? Math.min(row, 4) : row;
    const hpM = ch.scale * (1 + rowF * ch.rowScale) * (1 + heat);
    const atkM = (1 + (ch.scale - 1) * 0.75) * (1 + row * ch.rowScale * 0.6) * (1 + heat);
    const hp = Math.round(def.hp * hpM);
    return {
      side: 'enemy', key, art: def.art, def, name: def.name, maxHp: hp, hp, atk: def.atk * atkM, spd: def.spd,
      breakMax: Math.round(def.break * hpM), brk: 0, broken: false, heavy: !!def.heavy, boss: !!def.boss, occult: !!def.occult,
      burn: 0, dead: false, s: 1, x: 0, y: 0, pose: 'idle', fx: {},
    };
  }
  function layoutAllies() {
    B.allies.forEach((u, i) => { u.x = ALLY_SLOTS[i].x; u.y = ALLY_SLOTS[i].y; });
  }
  function layoutEnemies() {
    const es = B.enemies;
    const gap = 16;
    const ws = es.map((e) => G.art.size(e.art).w * e.s);
    let total = ws.reduce((a, b) => a + b, 0) + gap * (es.length - 1);
    const maxW = 470;
    const k = total > maxW ? maxW / total : 1;
    if (k < 1) es.forEach((e) => (e.s *= k));
    let x = 770 - (total * k) / 2;
    es.forEach((e, i) => {
      e.x = x + (ws[i] * k) / 2;
      e.y = e.heavy ? 548 : 532 - (i % 2) * 34;
      x += (ws[i] + gap) * k;
    });
  }

  // ---------- effects ----------
  function floater(x, y, text, color = '#fff', size = 26) { floaters.push({ x, y, text, color, size, t: G.now() }); }
  function burst(x, y, n, cols, spd = 4, life = 600) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, v = Math.random() * spd;
      particles.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 1.5, t: G.now(), life: life * (0.5 + Math.random()), col: G.pick(cols), r: 2 + Math.random() * 5 });
    }
  }
  function explosion(x, y, big = 1) {
    burst(x, y, 26 * big, ['#fff2a8', '#ffb347', '#d9480f', '#555', '#333'], 6 * big, 800);
    shake(10 * big);
    G.sfx('boom');
  }
  function tracer(x1, y1, x2, y2, col = '#fff3b0') { tracers.push({ x1, y1, x2, y2, col, t: G.now() }); }
  function shake(m) { if (!G.settings.shake) return; shakeMag = Math.max(shakeMag, m); shakeT = G.now(); }
  const chest = (u) => ({ x: u.x, y: u.y - G.art.size(u.art).h * u.s * 0.55 });
  const muzzlePt = (u) => {
    if (u.side === 'ally') return { x: u.x + 60 * u.s, y: u.y - 88 * u.s };
    const sp = G.art.spriteInfo && G.art.spriteInfo(u.art);
    const sz = G.art.size(u.art);
    if (sp && sp.muzzle) return { x: u.x + (0.5 - sp.muzzle[0]) * sz.w * u.s, y: u.y - (1 - sp.muzzle[1]) * sz.h * u.s };
    if (u.heavy) return { x: u.x - sz.w * u.s * 0.55, y: u.y - sz.h * u.s * 0.72 };
    return { x: u.x - 56 * u.s, y: u.y - 88 * u.s };
  };
  const hurt = (u) => { u.fx.hurt = G.now(); };
  const lunge = (u) => { u.fx.lunge = G.now(); };

  // ---------- render loop ----------
  function frame() {
    rafId = requestAnimationFrame(frame);
    if (!B) return;
    const now = G.now();
    const t = now / 1000;
    let sx = 0, sy = 0;
    if (shakeMag > 0) {
      const age = (now - shakeT) / 320;
      if (age > 1) shakeMag = 0;
      else { sx = (Math.random() - 0.5) * shakeMag * (1 - age); sy = (Math.random() - 0.5) * shakeMag * (1 - age); }
    }
    ctx.setTransform(scale, 0, 0, scale, sx * scale, sy * scale);
    ctx.drawImage(B.bg, 0, 0, W, H);
    if (B.bgKey === 'snow') {
      ctx.fillStyle = 'rgba(255,255,255,0.75)';
      for (let i = 0; i < 60; i++) {
        const x = (i * 97 + t * (20 + (i % 5) * 8)) % W, y = (i * 61 + t * (40 + (i % 7) * 10)) % H;
        ctx.fillRect(x, y, 2 + (i % 2), 2 + (i % 2));
      }
    }
    // occult haze for occult fights
    if (B.occult) {
      ctx.fillStyle = `rgba(80,255,170,${0.04 + 0.03 * Math.sin(t * 1.5)})`;
      ctx.fillRect(0, 0, W, H);
    }
    const units = [...B.allies, ...B.enemies].sort((a, b) => a.y - b.y);
    for (const u of units) drawUnitFull(u, now, t);
    // target reticle
    if (B.phase === 'command' && B.target && !B.target.dead) reticle(B.target, t);
    // actor marker
    if (B.actor && !B.actor.dead) {
      const sz = G.art.size(B.actor.art);
      const ty = B.actor.y - sz.h * B.actor.s - 26 + Math.sin(t * 5) * 4;
      ctx.fillStyle = B.actor.side === 'ally' ? '#f0c75a' : '#e0603f';
      ctx.beginPath(); ctx.moveTo(B.actor.x - 10, ty - 10); ctx.lineTo(B.actor.x + 10, ty - 10); ctx.lineTo(B.actor.x, ty + 2); ctx.closePath(); ctx.fill();
      ctx.strokeStyle = '#000'; ctx.lineWidth = 2; ctx.stroke();
    }
    // tracers
    for (let i = tracers.length - 1; i >= 0; i--) {
      const tr = tracers[i];
      const age = (now - tr.t) / 180;
      if (age > 1) { tracers.splice(i, 1); continue; }
      ctx.save(); ctx.globalAlpha = 1 - age; ctx.strokeStyle = tr.col; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(G.lerp(tr.x1, tr.x2, age * 0.6), G.lerp(tr.y1, tr.y2, age * 0.6)); ctx.lineTo(tr.x2, tr.y2); ctx.stroke(); ctx.restore();
    }
    // particles
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      const age = (now - p.t) / p.life;
      if (age > 1) { particles.splice(i, 1); continue; }
      p.x += p.vx; p.y += p.vy; p.vy += 0.12;
      ctx.globalAlpha = 1 - age; ctx.fillStyle = p.col; ctx.beginPath(); ctx.arc(p.x, p.y, p.r * (1 - age * 0.5), 0, 7); ctx.fill();
    }
    ctx.globalAlpha = 1;
    G.timing.draw(ctx, now);
    // floaters
    for (let i = floaters.length - 1; i >= 0; i--) {
      const f = floaters[i];
      const age = (now - f.t) / 1000;
      if (age > 1) { floaters.splice(i, 1); continue; }
      ctx.save(); ctx.globalAlpha = Math.min(1, 2 - age * 2);
      ctx.font = `700 ${f.size}px 'Barlow Condensed', 'Arial Narrow', sans-serif`; ctx.textAlign = 'center';
      ctx.lineWidth = 5; ctx.strokeStyle = '#000'; const y = f.y - age * 40;
      ctx.strokeText(f.text, f.x, y); ctx.fillStyle = f.color; ctx.fillText(f.text, f.x, y); ctx.restore();
    }
  }
  function drawUnitFull(u, now, t) {
    let alpha = 1;
    if (u.dead && u.side === 'enemy') {
      const age = (now - (u.deadT || 0)) / 700;
      if (age > 1) return;
      alpha = 1 - age;
    }
    let dx = 0;
    if (u.fx.lunge) { const a = (now - u.fx.lunge) / 260; if (a < 1) dx = Math.sin(a * Math.PI) * 22 * (u.side === 'ally' ? 1 : -1); }
    let pose = u.pose;
    let tint = null;
    if (u.fx.hurt) { const a = (now - u.fx.hurt) / 260; if (a < 1) { pose = u.dead ? pose : 'hurt'; tint = `rgba(255,255,255,${0.7 * (1 - a)})`; dx += (u.side === 'ally' ? -1 : 1) * 6 * (1 - a); } }
    if (u.side === 'ally' && u.dead) pose = 'down';
    else if (u.side === 'ally' && u.cover && pose === 'idle') pose = 'cover';
    if (u.side === 'enemy' && u.fx.tell) { const a = Math.sin(now / 60); tint = `rgba(255,90,60,${0.25 + 0.2 * a})`; }
    const flash = u.fx.flash && now - u.fx.flash < 90;
    ctx.save();
    if (u.side === 'enemy' && u.occult && !u.dead) { ctx.shadowColor = '#6dffb4'; ctx.shadowBlur = 18 + 8 * Math.sin(t * 2); }
    G.art.drawUnit(ctx, u, u.x + dx, u.y, u.s, { pose, t: t + u.x * 0.01, flash, alpha, tint });
    ctx.restore();
    if (u.side === 'ally' && u.cover && !u.dead) sandbags(u);
    if (u.shield > 0 && !u.dead) {
      ctx.save(); ctx.globalAlpha = 0.25 + 0.1 * Math.sin(t * 4); ctx.strokeStyle = '#d8e6ff'; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.ellipse(u.x, u.y - 70, 52, 86, 0, 0, 7); ctx.stroke(); ctx.restore();
    }
    if (u.side === 'enemy' && !u.dead) enemyBars(u);
    if (u.side === 'ally' && !u.dead && u.burn > 0) statusIcon(u.x - 30, u.y + 18, 'burn', u.burn);
  }
  function sandbags(u) {
    for (let i = 0; i < 3; i++) {
      G.art.rr(ctx, u.x + 4 + i * 4, u.y - 18 - i * 14, 46 - i * 6, 18, 8);
      ctx.fillStyle = '#8d7e52'; ctx.fill(); ctx.strokeStyle = '#1b1a14'; ctx.lineWidth = 2.5; ctx.stroke();
    }
  }
  function enemyBars(u) {
    const w = Math.max(70, Math.min(170, G.art.size(u.art).w * u.s * 0.7));
    const x = u.x - w / 2, y = u.y + 12;
    ctx.fillStyle = '#000000b0'; ctx.fillRect(x - 2, y - 2, w + 4, 18);
    ctx.fillStyle = '#3a0f08'; ctx.fillRect(x, y, w, 8);
    ctx.fillStyle = '#e0603f'; ctx.fillRect(x, y, w * (u.hp / u.maxHp), 8);
    ctx.fillStyle = '#2a2614'; ctx.fillRect(x, y + 10, w, 4);
    ctx.fillStyle = u.broken ? '#ffffff' : '#f0c75a'; ctx.fillRect(x, y + 10, w * (u.brk / u.breakMax), 4);
    ctx.font = "600 13px 'Barlow Condensed', sans-serif"; ctx.textAlign = 'center'; ctx.fillStyle = '#fff';
    ctx.fillText(`${Math.ceil(u.hp)}`, u.x, y + 29);
    let ix = x + w + 10;
    if (u.burn > 0) { statusIcon(ix, y + 6, 'burn', u.burn); ix += 26; }
    if (u.broken) { statusIcon(ix, y + 6, 'stun', 0); }
  }
  function statusIcon(x, y, kind, n) {
    ctx.save();
    ctx.fillStyle = kind === 'burn' ? '#d9480f' : '#f0c75a';
    ctx.beginPath(); ctx.arc(x, y, 10, 0, 7); ctx.fill(); ctx.strokeStyle = '#000'; ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = '#fff'; ctx.font = "700 12px 'Barlow Condensed', sans-serif"; ctx.textAlign = 'center';
    ctx.fillText(kind === 'burn' ? String(n) : '!', x, y + 4);
    ctx.restore();
  }
  function reticle(u, t) {
    const sz = G.art.size(u.art);
    const w = sz.w * u.s * 0.6 + 14, h = sz.h * u.s + 10;
    const cx = u.x, cy = u.y - h / 2 + 4;
    const p = 4 * Math.sin(t * 6);
    ctx.save(); ctx.strokeStyle = '#f0c75a'; ctx.lineWidth = 4;
    const L = 16;
    [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([sx, sy]) => {
      const x = cx + sx * (w / 2 + p), y = cy + sy * (h / 2 + p);
      ctx.beginPath(); ctx.moveTo(x, y - sy * L); ctx.lineTo(x, y); ctx.lineTo(x - sx * L, y); ctx.stroke();
    });
    ctx.restore();
  }

  // ---------- HUD ----------
  function renderTimeline() {
    const el = G.$('#timeline');
    const live = [...B.allies, ...B.enemies].filter((u) => !u.dead);
    const sim = live.map((u) => ({ u, next: u === B.actor ? B.time : u.next }));
    const order = [];
    for (let i = 0; i < 9 && sim.length; i++) {
      sim.sort((a, b) => a.next - b.next);
      const s = sim[0];
      order.push(s.u);
      s.next += interval(s.u);
    }
    el.innerHTML = '';
    el.appendChild(G.el('span', { class: 'tl-label', text: 'Turn' }));
    order.forEach((u, i) => {
      el.appendChild(G.el('div', { class: `tl-item ${u.side} ${i === 0 ? 'now' : ''}`, title: u.name }, G.el('img', { src: G.art.portrait(u, 64), alt: u.name })));
    });
  }
  function renderSquad() {
    const el = G.$('#squad-cards');
    el.innerHTML = '';
    B.allies.forEach((u) => {
      const hpPct = (u.hp / u.maxHp) * 100;
      const shPct = Math.min(100 - hpPct, (u.shield / u.maxHp) * 100);
      const status = [u.cover ? 'Cover' : '', u.burn ? `Burn ${u.burn}` : ''].filter(Boolean).join(' · ');
      el.appendChild(G.el('div', { class: `sq-card ${u === B.actor ? 'actor' : ''} ${u.dead ? 'down' : ''}` },
        G.el('img', { src: G.art.portrait(u, 64), alt: '' }),
        G.el('div', { class: 'sq-name', text: u.dead ? `${u.name} (down)` : u.name }),
        G.el('div', { class: 'bar' }, G.el('i', { style: { width: `${hpPct}%` } }), G.el('i', { class: 'shield', style: { left: `${hpPct}%`, width: `${shPct}%` } }), G.el('span', { text: `${Math.ceil(u.hp)}/${u.maxHp}` })),
        G.el('div', { class: 'ap-pips' }, ...Array.from({ length: C().apMax }, (_, i) => G.el('i', { class: i < u.ap ? 'on' : '' })), G.el('em', { text: status }))
      ));
    });
  }
  function renderTargetLine() {
    const el = G.$('#target-line');
    const res = B.reserve.filter((u) => !u.dead);
    const resTxt = res.length ? ` · Reserve: ${res.map((u) => `${u.name} ${Math.ceil(u.hp)}hp`).join(', ')}` : '';
    if (B.phase === 'command' && B.target && !B.target.dead) {
      el.innerHTML = `Target: <b>${G.esc(B.target.name)}</b> <span>(tap an enemy to switch)</span>${G.esc(resTxt)}`;
    } else if (B.phase === 'enemy') {
      el.innerHTML = `<b>Enemy turn.</b> Hit the Dirt: wide window. Counter-shot: tight window, +1 AP.`;
    } else el.textContent = resTxt.replace(/^ · /, '');
  }
  function cmdBtn(cls, label, sub, onClick, disabled) {
    const b = G.el('button', { class: `cmd ${cls}`, type: 'button', disabled: disabled || undefined }, label, sub ? G.el('small', { text: sub }) : null);
    b.addEventListener('click', () => { if (!b.disabled) { G.sfx('click'); onClick(); } });
    return b;
  }
  function renderCmds(mode, u, resolve) {
    const el = G.$('#cmds');
    el.innerHTML = '';
    el.className = 'cmds';
    if (mode === 'command') {
      const ab = u.def.ability;
      const cost = abilityCost(u);
      el.append(
        cmdBtn('fire', 'Fire', '+1 AP', () => resolve({ type: 'fire' })),
        cmdBtn('ability', ab.name, `${cost} AP · have ${u.ap}`, () => resolve({ type: 'ability' }), u.ap < cost || (ab.target === 'single' && !B.target)),
        cmdBtn('', 'Item', `${G.itemCount()} left`, () => renderCmds('items', u, resolve), G.itemCount() === 0),
        cmdBtn('', 'Cover', 'Half dmg · +1 AP', () => resolve({ type: 'cover' })),
        cmdBtn('', 'Swap', B.reserve.some((r) => !r.dead) ? 'Costs the turn' : 'No reserve', () => renderCmds('swap', u, resolve), !B.reserve.some((r) => !r.dead))
      );
    } else if (mode === 'items') {
      el.className = 'cmds';
      Object.entries(G.run.items).filter(([, n]) => n > 0).forEach(([id, n]) => {
        const it = D.items[id];
        el.append(cmdBtn('', it.name, `x${n}`, () => resolve({ type: 'item', id })));
      });
      el.append(cmdBtn('back', 'Back', '', () => renderCmds('command', u, resolve)));
    } else if (mode === 'swap') {
      B.reserve.forEach((r, i) => { if (!r.dead) el.append(cmdBtn('', r.name, `${Math.ceil(r.hp)}/${r.maxHp} HP`, () => resolve({ type: 'swap', idx: i }))); });
      el.append(cmdBtn('back', 'Back', '', () => renderCmds('command', u, resolve)));
    } else if (mode === 'tap') {
      el.className = 'cmds one';
      const b = G.el('button', { class: 'cmd big tap', type: 'button' }, u || 'TAP', G.el('small', { text: 'or press Space' }));
      b.addEventListener('pointerdown', (e) => { e.preventDefault(); G.audio.unlock(); G.timing.onPress(G.now()); });
      b.addEventListener('pointerup', () => G.timing.onRelease(G.now()));
      b.addEventListener('pointercancel', () => G.timing.onRelease(G.now()));
      b.addEventListener('pointerleave', () => G.timing.onRelease(G.now()));
      el.append(b);
    } else if (mode === 'defend') {
      el.className = 'cmds wide';
      const d = G.el('button', { class: 'cmd big dodge', type: 'button' }, 'Hit the Dirt', G.el('small', { text: 'wide window · Space' }));
      const c = G.el('button', { class: 'cmd big counter', type: 'button' }, 'Counter', G.el('small', { text: 'tight · +1 AP · X' }));
      d.addEventListener('pointerdown', (e) => { e.preventDefault(); G.audio.unlock(); G.timing.onDefend('dodge', G.now()); });
      c.addEventListener('pointerdown', (e) => { e.preventDefault(); G.audio.unlock(); G.timing.onDefend('counter', G.now()); });
      el.append(d, c);
    } else {
      el.className = 'cmds one';
      el.append(cmdBtn('wait', mode, '', () => {}, true));
    }
  }
  function banner(text, enemy) {
    const b = G.$('#banner');
    b.textContent = text;
    b.className = `banner ${enemy ? 'enemy' : ''}`;
    b.hidden = !text;
  }
  const abilityCost = (u) => Math.max(0, u.def.ability.ap + G.skillMod(u.def.ability.id, 'apCost'));

  // ---------- combat math ----------
  const timingMult = (res) => (res === 'perfect' ? C().perfectMult : res === 'good' ? C().goodMult : C().missMult);
  const gainAp = (u, n) => { if (!u.dead) u.ap = Math.min(C().apMax, u.ap + Math.min(n, D.config.caps.apPerEvent)); };
  function applyBurn(t, n) {
    if (!t || t.dead || n <= 0) return;
    const room = D.config.caps.burnPerAction - (B.actionBurn || 0);
    const add = Math.max(0, Math.min(n, room));
    if (!add) return;
    B.actionBurn = (B.actionBurn || 0) + add;
    t.burn = Math.min(C().burnCap, t.burn + add);
    floater(t.x, t.y - 40, `+${add} Burn`, '#ffb347', 18);
  }
  function healUnit(u, amount, quiet) {
    if (u.dead || amount <= 0) return 0;
    const before = u.hp;
    u.hp = Math.min(u.maxHp, u.hp + Math.round(amount));
    const got = u.hp - before;
    if (got > 0 && !quiet) floater(u.x, u.y - 150, `+${got}`, '#9cc95e', 24);
    return got;
  }
  function shieldUnit(u, pct) {
    if (u.dead || pct <= 0) return;
    u.shield = Math.min(u.maxHp * C().shieldCapPct, u.shield + Math.round(u.maxHp * pct));
  }
  function advance(u, frac) {
    if (frac <= 0 || u.dead) return;
    frac = Math.min(frac, D.config.caps.timeline);
    if (u === B.actor) { u.pendingAdvance = (u.pendingAdvance || 0) + frac; return; }
    u.next = Math.max(B.time + 1, u.next - frac * interval(u));
    floater(u.x, u.y - 170, 'Moves up', '#c9d2a9', 16);
  }
  function runHook(hook, actor, target) {
    const m = G.mods[hook] || {};
    if (m.burn && target) applyBurn(target, Math.round(m.burn));
    if (m.burnAll) B.enemies.forEach((e) => { if (!e.dead) { e.burn = Math.min(C().burnCap, e.burn + Math.round(m.burnAll)); } });
    if (m.burnAll) floater(780, 300, `Every enemy +${Math.round(m.burnAll)} Burn`, '#ffb347', 20);
    if (m.ap && actor) gainAp(actor, Math.round(m.ap));
    if (m.apAll) B.allies.forEach((a) => gainAp(a, Math.round(m.apAll)));
    if (m.shieldPct && actor) shieldUnit(actor, m.shieldPct);
    if (m.shieldAllPct) B.allies.forEach((a) => shieldUnit(a, m.shieldAllPct));
    if (m.healPct && actor) healUnit(actor, actor.maxHp * m.healPct * (1 + G.mod('passive', 'healPowerPct')));
    if (m.healAllPct) B.allies.forEach((a) => healUnit(a, a.maxHp * m.healAllPct * (1 + G.mod('passive', 'healPowerPct'))));
    if (m.timeline && actor) advance(actor, m.timeline);
    if (m.breakFlatPct && target && !target.dead) addBreak(target, target.breakMax * m.breakFlatPct, actor);
  }
  function addBreak(t, amount, src) {
    if (t.dead || t.broken || amount <= 0) return;
    t.brk = Math.min(t.breakMax, t.brk + amount);
    if (t.brk >= t.breakMax) {
      t.broken = true;
      floater(t.x, t.y - G.art.size(t.art).h * t.s - 10, 'BREAK!', '#ffffff', 34);
      G.sfx('break'); shake(8); burst(chest(t).x, chest(t).y, 16, ['#fff', '#f0c75a'], 5);
      runHook('break', src, t);
      B.stats.breaks = (B.stats.breaks || 0) + 1;
    }
  }
  function damageEnemy(t, dmg, brk, src, opts = {}) {
    if (t.dead) return;
    dmg = Math.max(1, Math.round(dmg));
    t.hp -= dmg;
    hurt(t);
    const c = chest(t);
    floater(c.x + G.ri(-14, 14), c.y - 20, String(dmg), opts.crit ? '#f0c75a' : '#ffffff', opts.crit ? 34 : 26);
    if (opts.crit) floater(c.x, c.y - 52, 'CRIT', '#f0c75a', 18);
    if (t.hp <= 0) {
      t.hp = 0; t.dead = true; t.deadT = G.now(); G.run.stats.kills++;
      if (t.heavy) explosion(c.x, c.y, 1.6); else burst(c.x, c.y, 10, ['#6e736a', '#3a3d37', '#8a2f24'], 3);
      runHook('kill', src, t);
      if (B.target === t) B.target = B.enemies.find((e) => !e.dead) || null;
      return;
    }
    addBreak(t, brk, src);
  }
  function damageAlly(t, dmg, src) {
    if (t.dead) return;
    dmg *= 1 + G.mod('passive', 'dmgTakenPct');
    if (t.cover) dmg *= 1 - Math.min(0.9, C().coverReduce + G.mod('passive', 'coverReducePct'));
    dmg = Math.max(1, Math.round(dmg));
    if (t.shield > 0) { const ab = Math.min(t.shield, dmg); t.shield -= ab; dmg -= ab; if (ab) floater(t.x + 20, t.y - 120, `-${ab} shield`, '#d8e6ff', 16); }
    if (dmg <= 0) return;
    t.hp -= dmg;
    hurt(t);
    G.run.stats.hits++;
    floater(t.x + G.ri(-10, 10), t.y - 100, String(dmg), '#e0603f', 26);
    if (t.hp <= 0) {
      t.hp = 0; t.dead = true; G.run.stats.downs++;
      floater(t.x, t.y - 140, 'DOWN', '#e0603f', 30);
      t.burn = 0; t.shield = 0; t.cover = false;
    }
  }
  function computeHit(u, t, spec, sm, res, multiTarget) {
    let dmgPct = G.mod('passive', 'dmgPct') + (sm.dmgPct || 0);
    if (multiTarget || spec.target === 'spread' || spec.target === 'blast') dmgPct += G.mod('passive', 'blastDmgPct');
    if (res === 'perfect') dmgPct += G.mod('perfect', 'dmgPct');
    let dmg = u.atk * (spec.mult || 1) * timingMult(res) * (1 + dmgPct);
    let crit = false;
    const critChance = C().baseCrit + G.mod('passive', 'critPct') + (spec.crit || 0);
    if (res !== 'miss' && Math.random() < critChance) { crit = true; dmg *= C().critMult; }
    if (t.broken) dmg *= 1 + C().brokenBonus + G.mod('passive', 'brokenDmgPct');
    dmg *= 1 + (Math.random() * 2 - 1) * C().variance;
    let brk = dmg * (spec.break || 1) * (1 + G.mod('passive', 'breakPct') + (sm.breakPct || 0));
    if (t.heavy && res === 'perfect') brk *= C().heavyPerfectBreak;
    if (spec.target === 'blast') brk += t.breakMax * G.mod('passive', 'blastBreakPct');
    return { dmg, brk, crit };
  }

  // ---------- player actions ----------
  function targetsFor(spec) {
    const alive = B.enemies.filter((e) => !e.dead);
    if (!alive.length) return [];
    let primary = B.target && !B.target.dead ? B.target : alive[0];
    if (spec.target === 'blast') return alive;
    if (spec.target === 'spread') {
      const i = alive.indexOf(primary);
      return [alive[i - 1], primary, alive[i + 1]].filter(Boolean);
    }
    return [primary];
  }
  function fireVisual(u, targets, kind) {
    u.fx.flash = G.now();
    const m = muzzlePt(u);
    targets.forEach((t) => { const c = chest(t); tracer(m.x, m.y, c.x + G.ri(-10, 10), c.y + G.ri(-14, 14)); });
    if (kind === 'boom') targets.forEach((t) => explosion(chest(t).x, chest(t).y, 0.7));
    else G.sfx(kind === 'mg' ? 'mg' : 'shot');
  }
  function countRes(res) {
    if (res === 'perfect') G.run.stats.perfects++;
    else if (res === 'good') G.run.stats.goods++;
    else G.run.stats.misses++;
    G.sfx(res === 'perfect' ? 'perfect' : res === 'good' ? 'good' : 'miss');
  }
  function resolveHit(u, spec, sm, targets, res) {
    countRes(res);
    const live = targets.filter((t) => !t.dead);
    if (!live.length) return;
    const kind = spec.boom ? 'boom' : u.cls === 'mg' ? 'mg' : 'shot';
    fireVisual(u, live, kind);
    let anyCrit = false;
    for (const t of live) {
      const h = computeHit(u, t, spec, sm, res, live.length > 1);
      if (h.crit) anyCrit = true;
      damageEnemy(t, h.dmg, h.brk, u, { crit: h.crit });
      if (sm.burn && !t.dead) applyBurn(t, Math.round(sm.burn));
      if (h.crit && !t.dead) runHook('crit', null, t);
      if (spec.pushBack && !t.dead) t.next += spec.pushBack * interval(t);
    }
    if (anyCrit) runHook('crit', u, null);
    if (res === 'perfect') runHook('perfect', u, live.find((t) => !t.dead) || null);
  }
  async function attack(u, spec, skillId) {
    const sm = (skillId && G.mods.skills[skillId]) || {};
    const targets = targetsFor(spec);
    if (!targets.length) return;
    B.actionBurn = 0;
    u.pose = 'attack';
    const anchor = { x: u.x + 10, y: u.y - 80 };
    if (spec.input === 'rhythm') {
      renderCmds('tap', 'TAP x' + (spec.beats + (sm.extraHits || 0)));
      await G.timing.rhythm({
        ...anchor, beats: spec.beats + (sm.extraHits || 0),
        onBeat: (i, res) => { lunge(u); resolveHit(u, spec, sm, targetsFor(spec), res); },
      });
    } else if (spec.input === 'hold') {
      renderCmds('tap', 'HOLD');
      const res = await G.timing.hold({ ...anchor });
      lunge(u);
      // automatic weapons rattle a few times on release
      const isMg = u.cls === 'mg';
      if (isMg) for (let i = 0; i < 4; i++) { setTimeout(() => { u.fx.flash = G.now(); G.sfx('mg'); }, i * 90 * G.speed); }
      resolveHit(u, { ...spec, boom: !isMg }, sm, targets, res);
    } else {
      renderCmds('tap', 'TAP');
      const res = await G.timing.press({ ...anchor, ringMs: spec.ringMs });
      lunge(u);
      resolveHit(u, spec, sm, targets, res);
    }
    renderCmds('…', u);
    await G.wait(380);
    u.pose = 'idle';
  }
  async function heal(u, spec, skillId) {
    const sm = (skillId && G.mods.skills[skillId]) || {};
    u.pose = 'attack';
    renderCmds('tap', 'TAP');
    const res = await G.timing.press({ x: u.x + 10, y: u.y - 80 });
    countRes(res);
    const mult = res === 'perfect' ? 1.5 : res === 'good' ? 1 : 0.5;
    const pool = B.allies.filter((a) => !a.dead);
    const targets = sm.allTargets ? pool : [pool.slice().sort((a, b) => a.hp / a.maxHp - b.hp / b.maxHp)[0]];
    G.sfx('heal');
    targets.forEach((t) => { healUnit(t, t.maxHp * spec.heal * mult * (1 + G.mod('passive', 'healPowerPct'))); burst(t.x, t.y - 80, 8, ['#9cc95e', '#e7f5c8'], 2.5); });
    if (res === 'perfect') runHook('perfect', u, null);
    renderCmds('…', u);
    await G.wait(380);
    u.pose = 'idle';
  }
  async function useItem(u, id) {
    const it = D.items[id];
    G.run.items[id]--;
    banner(it.name);
    if (id === 'grenade') {
      u.pose = 'attack';
      renderCmds('tap', 'TAP');
      const res = await G.timing.press({ x: u.x + 10, y: u.y - 80 });
      countRes(res);
      const alive = B.enemies.filter((e) => !e.dead);
      alive.forEach((t) => explosion(chest(t).x, chest(t).y, 0.8));
      const m = timingMult(res) * (1 + G.mod('passive', 'grenadePct') + G.mod('passive', 'dmgPct') + G.mod('passive', 'blastDmgPct'));
      alive.forEach((t) => damageEnemy(t, it.dmg * m * (t.broken ? 1 + C().brokenBonus : 1), it.break * (1 + G.mod('passive', 'breakPct')) + t.breakMax * G.mod('passive', 'blastBreakPct'), u));
    } else if (id === 'medkit') {
      const pool = B.allies.filter((a) => !a.dead).sort((a, b) => a.hp / a.maxHp - b.hp / b.maxHp);
      if (pool[0]) { healUnit(pool[0], pool[0].maxHp * it.heal * (1 + G.mod('passive', 'healPowerPct'))); G.sfx('heal'); }
    } else if (id === 'stim') {
      gainAp(u, 2); floater(u.x, u.y - 150, '+2 AP', '#f0c75a', 22); G.sfx('good');
    } else if (id === 'smoke') {
      B.allies.forEach((a) => { if (!a.dead) a.cover = true; });
      burst(200, 460, 40, ['#cfcfc4', '#a9a99c', '#8a8a7e'], 3, 1400);
    }
    renderCmds('…', u);
    await G.wait(420);
    u.pose = 'idle';
    banner('');
  }
  function swap(u, idx) {
    const r = B.reserve[idx];
    const slot = B.allies.indexOf(u);
    B.allies[slot] = r;
    B.reserve[idx] = u;
    u.cover = false;
    r.next = B.time + interval(r) * 0.5;
    layoutAllies();
    floater(r.x, r.y - 160, `${r.name} moves up`, '#f0c75a', 20);
  }
  function refillActive() {
    B.allies.forEach((a, slot) => {
      if (!a.dead) return;
      const idx = B.reserve.findIndex((r) => !r.dead);
      if (idx < 0) return;
      const r = B.reserve[idx];
      B.allies[slot] = r; B.reserve[idx] = a;
      r.next = B.time + interval(r) * 0.4;
      layoutAllies();
      floater(r.x, r.y - 160, `${r.name} moves up`, '#f0c75a', 20);
    });
  }

  function waitCommand(u) {
    return new Promise((resolve) => {
      if (G.testMode) {
        const cost = abilityCost(u);
        let cmd = { type: 'fire' };
        if (u.ap >= cost && Math.random() < 0.6) cmd = { type: 'ability' };
        else if (G.itemCount() && Math.random() < 0.15) cmd = { type: 'item', id: Object.keys(G.run.items).find((k) => G.run.items[k] > 0) };
        else if (Math.random() < 0.05) cmd = { type: 'cover' };
        setTimeout(() => resolve(cmd), 1);
        return;
      }
      renderCmds('command', u, resolve);
    });
  }

  async function allyTurn(u) {
    B.phase = 'command';
    if (!B.target || B.target.dead) B.target = B.enemies.find((e) => !e.dead);
    renderSquad(); renderTargetLine();
    if (!G.meta.seenTips.command && !G.testMode) { G.meta.seenTips.command = true; G.toast('Your turn. Fire builds AP; abilities spend it. Tap an enemy to target it.', 4200); }
    const cmd = await waitCommand(u);
    B.phase = 'act';
    renderTargetLine();
    const def = u.def;
    if (cmd.type === 'fire') {
      banner(def.fire.name);
      if (!G.meta.seenTips.ring && !G.testMode) { G.meta.seenTips.ring = true; G.toast('Tap when the gold ring meets the white one. Perfect = +50% damage.', 3800); }
      await attack(u, def.fire, null);
      gainAp(u, 1);
    } else if (cmd.type === 'ability') {
      const ab = def.ability;
      u.ap -= abilityCost(u);
      banner(ab.name);
      if (ab.target === 'ally') await heal(u, ab, ab.id);
      else await attack(u, ab, ab.id);
    } else if (cmd.type === 'item') {
      await useItem(u, cmd.id);
    } else if (cmd.type === 'cover') {
      u.cover = true;
      gainAp(u, 1);
      shieldUnit(u, G.mod('passive', 'coverShieldPct'));
      floater(u.x, u.y - 150, 'Taking cover', '#c9d2a9', 20);
      await G.wait(350);
    } else if (cmd.type === 'swap') {
      swap(u, cmd.idx);
      await G.wait(400);
    }
    banner('');
  }

  async function enemyTurn(e) {
    B.phase = 'enemy';
    const def = e.def;
    const hurtAllies = B.enemies.some((x) => !x.dead && x.hp < x.maxHp * 0.7);
    const moves = def.moves.filter((m) => !m.heal || hurtAllies);
    const move = G.weighted(moves, (m) => m.w || 1);
    renderSquad(); renderTargetLine();
    renderCmds(move.heal ? 'Enemy turn' : 'defend');
    banner(`${e.name}: ${move.name}`, true);
    if (!G.meta.seenTips.defend && !G.testMode && !move.heal) { G.meta.seenTips.defend = true; G.toast('Incoming! Press Hit the Dirt or Counter as the red ring closes.', 4200); }
    e.fx.tell = true; e.pose = 'attack';
    if (e.occult) G.sfx('occult');
    await G.wait(move.feint ? 520 : 420);
    e.fx.tell = false;
    if (move.heal) {
      B.enemies.forEach((x) => { if (!x.dead) { x.hp = Math.min(x.maxHp, x.hp + Math.round(x.maxHp * move.heal)); floater(x.x, x.y - 160, `+${Math.round(x.maxHp * move.heal)}`, '#9cc95e', 22); } });
      await G.wait(500);
      e.pose = 'idle'; banner('');
      return;
    }
    const alive = () => B.allies.filter((a) => !a.dead);
    let targets;
    if (move.target === 'all') targets = alive();
    else {
      const pool = alive();
      targets = [Math.random() < 0.35 ? pool.slice().sort((a, b) => a.hp - b.hp)[0] : G.pick(pool)];
    }
    const hits = move.hits || 1;
    let parriedAll = true;
    for (let h = 0; h < hits; h++) {
      targets = targets.filter((t) => !t.dead);
      if (!targets.length || e.dead) break;
      const cx = move.target === 'all' ? 205 : targets[0].x + 6;
      const cy = move.target === 'all' ? 430 : targets[0].y - 78;
      const feint = Math.random() < (move.feint || 0);
      const res = await G.timing.defend({ x: cx, y: cy, ringMs: move.ringMs || D.config.timing.ringMs * 0.85, feint });
      // fire visuals
      e.fx.flash = G.now(); lunge(e);
      const m = muzzlePt(e);
      if (move.target === 'all' && (move.name.includes('Grenade') || move.name.includes('Gun') || move.name.includes('Mortar') || move.name.includes('Barrage') || move.name === 'Wail')) {
        targets.forEach((t) => explosion(chest(t).x, chest(t).y, 0.6));
      } else {
        targets.forEach((t) => tracer(m.x, m.y, chest(t).x, chest(t).y, e.occult ? '#6dffb4' : '#ffd9a0'));
        G.sfx(hits > 2 ? 'mg' : 'shot');
      }
      if (def.art === 'flamer' || move.burn) targets.forEach((t) => burst(chest(t).x, chest(t).y, 8, ['#ffb347', '#d9480f'], 3));
      if (res === 'parry') {
        G.run.stats.parries++; G.sfx('parry');
        targets.forEach((t) => { gainAp(t, 1); floater(t.x, t.y - 150, '+1 AP', '#f0c75a', 20); runHook('parry', t, e); });
      } else if (res === 'dodge') {
        parriedAll = false;
        G.run.stats.dodges++; G.sfx('dodge');
        targets.forEach((t) => { runHook('dodge', t, null); });
      } else {
        parriedAll = false;
        G.sfx('hit'); shake(5);
        targets.forEach((t) => {
          damageAlly(t, e.atk * (move.mult || 1) * (1 + (Math.random() * 2 - 1) * C().variance), e);
          if (move.burn && !t.dead) t.burn = Math.min(C().burnCap, t.burn + move.burn);
        });
      }
      renderSquad();
      await G.wait(move.interval || 260);
    }
    // a full parry chain earns a counter-shot
    const shooter = targets.find((t) => !t.dead);
    if (parriedAll && shooter && !e.dead) {
      await G.wait(150);
      shooter.pose = 'attack'; shooter.fx.flash = G.now(); lunge(shooter);
      const mz = muzzlePt(shooter);
      tracer(mz.x, mz.y, chest(e).x, chest(e).y);
      G.sfx('shot');
      floater(shooter.x, shooter.y - 170, 'COUNTER-SHOT', '#f0c75a', 22);
      const dmg = shooter.atk * C().counterMult * (1 + G.mod('passive', 'counterDmgPct') + G.mod('passive', 'dmgPct'));
      damageEnemy(e, dmg, dmg, shooter);
      await G.wait(350);
      shooter.pose = 'idle';
    }
    e.pose = 'idle';
    banner('');
  }

  // returns true if the unit loses its turn
  async function turnStart(u) {
    if (u.side === 'ally') {
      u.cover = false;
      const drain = G.mod('passive', 'hpDrainPct');
      if (drain > 0 && u.hp > 1) { const d = Math.min(u.hp - 1, Math.round(u.maxHp * drain)); if (d > 0) { u.hp -= d; floater(u.x, u.y - 120, `-${d}`, '#57e0a4', 18); } }
    }
    if (u.burn > 0) {
      const mult = u.side === 'enemy' ? 1 + G.mod('passive', 'burnDmgPct') : 1;
      const dmg = Math.round(C().burnPerStack * u.burn * mult);
      burst(chest(u).x, chest(u).y, 6, ['#ffb347', '#d9480f'], 2);
      if (u.side === 'enemy') {
        damageEnemy(u, dmg, dmg * 0.5, null);
        const h = G.mod('burnTick', 'healAll');
        if (h) B.allies.forEach((a) => healUnit(a, h, true));
      } else damageAlly(u, dmg, null);
      u.burn = Math.max(0, u.burn - 1);
      await G.wait(300);
      if (u.dead) return true;
    }
    if (u.side === 'enemy' && u.broken) {
      floater(u.x, u.y - G.art.size(u.art).h * u.s - 10, 'STUNNED', '#f0c75a', 26);
      u.broken = false; u.brk = 0;
      await G.wait(500);
      return true;
    }
    return false;
  }

  function checkEnd() {
    if (B.enemies.every((e) => e.dead)) return 'win';
    if ([...B.allies, ...B.reserve].every((a) => a.dead)) return 'lose';
    return null;
  }
  function nextUnit() {
    const live = [...B.allies, ...B.enemies].filter((u) => !u.dead);
    return live.reduce((a, b) => (b.next < a.next ? b : a));
  }

  // ---------- entry point ----------
  async function run(spec) {
    initCanvas();
    G.show('battle');
    G.timing.clear();
    floaters.length = particles.length = tracers.length = 0;
    const ch = G.chapter();
    const squad = G.run.squad;
    const nActive = Math.min(3, squad.length);
    const bgKey = spec.bg || G.pick(ch.bgs);
    B = {
      allies: squad.slice(0, nActive).map(mkAlly),
      reserve: squad.slice(nActive).map(mkAlly),
      enemies: spec.enemies.map((k) => mkEnemy(k, spec.row || 0)),
      time: 0, phase: 'intro', actor: null, target: null, over: false, stats: {},
      bg: G.art.bg(bgKey), bgKey, occult: spec.enemies.some((k) => D.enemies[k].occult),
    };
    // dead actives get replaced from reserve before the fight starts
    B.allies.forEach((a, i) => {
      if (!a.dead) return;
      const j = B.reserve.findIndex((r) => !r.dead);
      if (j >= 0) { B.allies[i] = B.reserve[j]; B.reserve[j] = a; }
    });
    layoutAllies(); layoutEnemies();
    const first = G.mod('battleStart', 'first') > 0;
    [...B.allies, ...B.reserve].forEach((u) => (u.next = (first ? 0.05 : 0.2 + Math.random() * 0.8) * interval(u)));
    B.enemies.forEach((u) => (u.next = (first ? 0.6 : 0.2) * interval(u) + Math.random() * 0.8 * interval(u)));
    B.target = B.enemies[0];
    if (!rafId) frame();
    G._resizeStage && G._resizeStage();
    renderSquad(); renderTimeline(); renderTargetLine(); renderCmds('…');
    const boss = B.enemies.find((e) => e.boss);
    banner(boss ? boss.name : spec.title || 'Contact!', !!boss);
    // battle-start hooks
    runHook('battleStart', null, null);
    await G.wait(900);
    banner('');
    let result = null;
    while (!result) {
      const u = nextUnit();
      B.time = Math.max(B.time, u.next);
      B.actor = u;
      renderTimeline(); renderSquad();
      const skip = await turnStart(u);
      result = checkEnd();
      if (result) break;
      if (!skip && !u.dead) {
        if (u.side === 'ally') await allyTurn(u);
        else await enemyTurn(u);
      }
      u.next = B.time + interval(u);
      if (u.pendingAdvance) { u.next = Math.max(B.time + 1, u.next - u.pendingAdvance * interval(u)); floater(u.x, u.y - 170, 'Moves up', '#c9d2a9', 16); u.pendingAdvance = 0; }
      refillActive();
      renderSquad();
      result = checkEnd();
    }
    B.over = true;
    B.phase = 'over';
    B.actor = null;
    renderCmds(result === 'win' ? 'Victory' : 'Squad down');
    banner(result === 'win' ? 'Area secured' : 'Squad down', result !== 'win');
    G.sfx(result === 'win' ? 'win' : 'lose');
    await G.wait(1300);
    banner('');
    // write HP back to the run
    const order = [...B.allies, ...B.reserve];
    G.run.squad = order.map((u) => {
      u.ref.frac = u.dead ? (result === 'win' ? C().reviveFrac : 0) : u.hp / u.maxHp;
      return u.ref;
    });
    const out = result;
    B = null;
    G.timing.clear();
    return out;
  }

  return { run, W, H };
})();
