// Real-time side-view auto-battle. Squads fire on their own; the player spends AP on abilities and items,
// and picks a focus target. Unit roles counter each other (rock-paper-scissors) via D.config.counters.
G.battle = (() => {
  const W = 1000, H = 620;
  let B = null;
  let cv, ctx, scale = 1, rafId = 0, last = 0;
  const floaters = [], particles = [], tracers = [], lobs = [], flames = [];
  let shakeT = 0, shakeMag = 0;
  const C = () => D.config.combat;
  const FIG_S = 0.4; // 256px figure canvas -> ~102 logical px
  const ALLY_SLOTS = {
    front: [[400, 500], [400, 590], [290, 462], [290, 552]],
    back: [[178, 500], [178, 590], [70, 462], [70, 552]],
  };

  // ---------- canvas ----------
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
    if (window.ResizeObserver) new ResizeObserver(resize).observe(wrap);
    window.addEventListener('resize', resize);
    resize();
    G._resizeStage = resize;
    cv.addEventListener('pointerdown', onCanvasDown);
    window.addEventListener('keydown', onKey);
  }
  function toLogical(e) {
    const r = cv.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
  }
  function unitBox(u) {
    if (u.vehicle) { const sz = G.art.size(u.art); return { x0: u.x - (sz.w * u.s) / 2, x1: u.x + (sz.w * u.s) / 2, y0: u.y - sz.h * u.s, y1: u.y + 10 }; }
    const h = (u.isHero ? 120 : 95) * (u.big ? 1.2 : 1);
    return { x0: u.x - 62, x1: u.x + 62, y0: u.y - h, y1: u.y + 16 };
  }
  function onCanvasDown(e) {
    if (!B || B.over) return;
    G.audio.unlock();
    const p = toLogical(e);
    const hit = B.enemies.filter((u) => !u.dead).find((u) => { const b = unitBox(u); return p.x > b.x0 && p.x < b.x1 && p.y > b.y0 && p.y < b.y1; });
    if (hit) { B.focus = B.focus === hit ? null : hit; G.sfx('click'); renderFocus(); }
  }
  function onKey(e) {
    if (!B || B.over || e.repeat) return;
    if (!G.$('#modal').hidden) return;
    if (e.code === 'Space' || e.code === 'KeyP') { e.preventDefault(); togglePause(); return; }
    const n = { Digit1: 0, Digit2: 1, Digit3: 2, Digit4: 3, Digit5: 4, Digit6: 5, Digit7: 6, Digit8: 7, Digit9: 8 }[e.code];
    if (n !== undefined) { const live = B.allies.filter((u) => !u.dead); if (live[n]) castAbility(live[n]); return; }
    if (e.code === 'Tab' || e.code === 'ArrowRight' || e.code === 'ArrowLeft') {
      e.preventDefault();
      const alive = B.enemies.filter((u) => !u.dead);
      if (!alive.length) return;
      const i = alive.indexOf(B.focus);
      B.focus = alive[(i + (e.code === 'ArrowLeft' ? -1 : 1) + alive.length) % alive.length];
      renderFocus();
    }
  }

  // ---------- unit construction ----------
  const vetBonus = (u) => (u.isHero ? (u.level - 1) * D.config.heroes.bonusPerLevel : u.rank * D.config.veterancy.bonusPerRank);
  function formation(n, big) {
    const pts = {
      1: [[0, 0]], 2: [[-20, -8], [22, 6]], 3: [[-30, -10], [6, 8], [36, -6]], 4: [[-36, -10], [-6, 10], [24, -10], [44, 8]],
      5: [[-42, -12], [-14, 8], [12, -12], [36, 8], [52, -10]], 6: [[-44, -12], [-18, 8], [8, -12], [30, 8], [50, -12], [62, 8]],
    }[n] || [[0, 0]];
    return pts.map(([dx, dy]) => ({ dx: dx * (big ? 1.3 : 1), dy, ph: Math.random() * 6, dead: false, dieT: 0, atkT: -9 }));
  }
  function mkAlly(sq, isHero) {
    const def = isHero ? D.heroes[sq.id] : D.units[sq.type];
    const maxHp = isHero ? G.heroMaxHp(sq) : G.squadMaxHp(sq);
    const hp = Math.round(Math.max(0, sq.frac) * maxHp);
    const u = {
      side: 'ally', def, ref: sq, isHero, name: def.name, figure: def.figure, tent: !!def.tent,
      count: isHero ? 1 : def.count, maxHp, hp, dead: hp <= 0, role: def.role, dmgType: def.dmgType, row: def.row,
      rank: isHero ? 0 : G.vetRank(sq.xp), level: isHero ? G.heroLevel(sq.id) : 1,
      atkTimer: Math.random() * def.rate, atkCount: 0, burn: 0, burnT: 0, decayT: 0, shield: 0, hasteUntil: 0, slowUntil: 0,
      ability: { def: def.ability, cdLeft: 2 }, kills: 0, lowHpFired: false, flanker: def.dmgType === 'precision',
      x: 0, y: 0, s: FIG_S * (isHero ? 1.25 : 1),
    };
    u.figs = formation(u.count, false);
    syncFigs(u, true);
    return u;
  }
  function mkEnemy(key, tier) {
    const def = D.enemies[key];
    const ch = G.chapter();
    const heat = (G.run.heat || 0) * D.config.rewards.heatEnemyPct;
    const t = def.boss || def.vehicle ? Math.min(tier, 4) : tier;
    const hpM = ch.scale * (1 + t * ch.tierScale) * (1 + heat);
    const atkM = (1 + (ch.scale - 1) * 0.8) * (1 + t * ch.tierScale * 0.6) * (1 + heat);
    const hp = Math.round(def.hp * hpM * C().enemyHpScale);
    const u = {
      side: 'enemy', key, def, name: def.name, figure: def.figure, art: def.sprite, vehicle: !!def.vehicle, boss: !!def.boss, occult: !!def.occult, big: key === 'shock',
      count: def.count, maxHp: hp, hp, dead: false, role: def.role, dmgType: def.dmgType, row: def.row, flanker: !!def.flanker,
      atkM: atkM * C().enemyDmgScale, atkTimer: 0.6 + Math.random() * def.rate, atkCount: 0, burn: 0, burnT: 0, decayT: 0, shield: 0, hasteUntil: 0, slowUntil: 0, brokenUntil: 0,
      breakMax: def.break ? Math.round(def.break * hpM * C().breakScale) : 0, brk: 0, cast: null,
      abilities: (def.abilities || []).map((a) => ({ def: a, cdLeft: a.cd * (0.45 + Math.random() * 0.4) })),
      x: 0, y: 0, s: def.vehicle ? 1 : FIG_S * (key === 'shock' ? 1.1 : 1), rank: 0, level: 1,
    };
    u.figs = def.vehicle ? [] : formation(u.count, key === 'shock');
    return u;
  }
  // how many figures are still standing
  function syncFigs(u, instant) {
    if (u.vehicle || u.isHero) return;
    const alive = u.dead ? 0 : Math.max(1, Math.ceil((u.count * u.hp) / u.maxHp));
    let standing = u.figs.filter((f) => !f.dead).length;
    for (let i = u.figs.length - 1; i >= 0 && standing > alive; i--) {
      if (!u.figs[i].dead) { u.figs[i].dead = true; u.figs[i].dieT = instant ? -9 : B ? B.t : 0; standing--; }
    }
    for (let i = 0; i < u.figs.length && standing < alive; i++) {
      if (u.figs[i].dead) { u.figs[i].dead = false; standing++; }
    }
  }
  function layout() {
    const front = B.allies.filter((u) => u.row === 'front');
    const back = B.allies.filter((u) => u.row !== 'front');
    const fs = ALLY_SLOTS.front.slice(), bs = ALLY_SLOTS.back.slice();
    const place = (u, pref, alt) => { const s = pref.shift() || alt.shift(); u.x = s[0]; u.y = s[1]; };
    // heroes take the most central slot of their row
    front.sort((a, b) => (b.isHero ? 1 : 0) - (a.isHero ? 1 : 0)).forEach((u) => place(u, fs, bs));
    back.sort((a, b) => (b.isHero ? 1 : 0) - (a.isHero ? 1 : 0)).forEach((u) => place(u, bs, fs));
    // enemies: vehicles in the middle, squads around them
    const vehicles = B.enemies.filter((e) => e.vehicle);
    const squads = B.enemies.filter((e) => !e.vehicle);
    const eFront = [[600, 500], [600, 590], [710, 462], [710, 552]], eBack = [[822, 500], [822, 590], [930, 462], [930, 552]];
    vehicles.forEach((v, i) => {
      const sz = G.art.size(v.art);
      const maxW = v.boss ? 330 : 230;
      v.s = Math.min(1.2, maxW / sz.w);
      v.x = vehicles.length > 1 ? 700 + i * 170 : v.boss ? 760 : 740;
      v.y = 585 - i * 40;
    });
    let ef = eFront.slice(), eb = eBack.slice();
    if (vehicles.length) { ef = [[590, 500], [590, 592]]; eb = vehicles.some((v) => v.boss) ? [[935, 470], [935, 575]] : [[920, 480], [920, 585]]; }
    squads.filter((u) => u.row === 'front').forEach((u) => { const s = ef.shift() || eb.shift() || [600, 540]; u.x = s[0]; u.y = s[1]; });
    squads.filter((u) => u.row !== 'front').forEach((u) => { const s = eb.shift() || ef.shift() || [820, 540]; u.x = s[0]; u.y = s[1]; });
  }

  // ---------- effects ----------
  const floater = (x, y, text, color = '#fff', size = 22) => { if (floaters.length < 60) floaters.push({ x, y, text, color, size, t: G.now() }); };
  function burst(x, y, n, cols, spd = 4, life = 600) {
    for (let i = 0; i < n && particles.length < 400; i++) {
      const a = Math.random() * Math.PI * 2, v = Math.random() * spd;
      particles.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 1.5, t: G.now(), life: life * (0.5 + Math.random()), col: G.pick(cols), r: 2 + Math.random() * 4 });
    }
  }
  function explosion(x, y, big = 1) { burst(x, y, 20 * big, ['#fff2a8', '#ffb347', '#d9480f', '#555', '#333'], 5 * big, 700); shake(7 * big); G.sfx('boom'); }
  const tracer = (x1, y1, x2, y2, col = '#fff3b0') => { if (tracers.length < 80) tracers.push({ x1, y1, x2, y2, col, t: G.now() }); };
  const shake = (m) => { if (!G.settings.shake) return; shakeMag = Math.max(shakeMag, m); shakeT = G.now(); };
  const center = (u) => (u.vehicle ? { x: u.x, y: u.y - G.art.size(u.art).h * u.s * 0.5 } : { x: u.x, y: u.y - 45 * (u.isHero ? 1.25 : 1) });
  function muzzleOf(u) {
    if (u.vehicle) {
      const sp = G.art.spriteInfo(u.art), sz = G.art.size(u.art);
      if (sp && sp.muzzle) return { x: u.x + (0.5 - sp.muzzle[0]) * sz.w * u.s, y: u.y - (1 - sp.muzzle[1]) * sz.h * u.s };
      return { x: u.x - sz.w * u.s * 0.5, y: u.y - sz.h * u.s * 0.7 };
    }
    const live = u.figs.filter((f) => !f.dead);
    const f = live.length ? G.pick(live) : { dx: 0, dy: 0 };
    const dir = u.side === 'ally' ? 1 : -1;
    const m = G.art.figMuzzle(u.figure);
    const k = u.s * 256;
    return { x: u.x + f.dx * dir + (m[0] - 0.5) * k * dir, y: u.y + f.dy - (250 / 256 - m[1]) * k, f };
  }

  // ---------- combat math ----------
  const counter = (dmgType, role) => ((D.config.counters[dmgType] || {})[role] ?? 1);
  const outMult = (u) => (u.count > 1 && !u.vehicle ? 0.35 + 0.65 * (u.hp / u.maxHp) : 1);
  const alive = (side) => (side === 'ally' ? B.allies : B.enemies).filter((u) => !u.dead);
  const foesOf = (u) => alive(u.side === 'ally' ? 'enemy' : 'ally');
  const officerAura = () => (B.enemies.some((e) => !e.dead && e.def.aura) ? Math.max(...B.enemies.filter((e) => !e.dead && e.def.aura).map((e) => e.def.aura)) : 0);

  function pickTarget(u) {
    let foes = foesOf(u);
    if (!foes.length) return null;
    if (u.side === 'ally' && B.focus && !B.focus.dead) return B.focus;
    if (!u.flanker) { const front = foes.filter((f) => f.row === 'front'); if (front.length) foes = front; }
    let best = -1, pool = [];
    for (const f of foes) {
      const m = counter(u.dmgType, f.role) + (u.side === 'enemy' ? Math.random() * 0.3 : 0);
      if (m > best + 1e-6) { best = m; pool = [f]; } else if (Math.abs(m - best) < 1e-6) pool.push(f);
    }
    return pool.sort((a, b) => a.hp / a.maxHp - b.hp / b.maxHp)[0];
  }
  function neighbours(t) {
    const same = alive(t.side).filter((x) => x !== t).sort((a, b) => Math.hypot(a.x - t.x, a.y - t.y) - Math.hypot(b.x - t.x, b.y - t.y));
    return [t, ...same.slice(0, 1)];
  }
  function heal(u, amount, quiet) {
    if (u.dead || amount <= 0) return 0;
    const before = u.hp;
    u.hp = Math.min(u.maxHp, u.hp + amount);
    const got = u.hp - before;
    if (got >= 1 && !quiet) floater(u.x + G.ri(-20, 20), u.y - 105, `+${Math.round(got)}`, '#9cc95e', 18);
    syncFigs(u);
    return got;
  }
  const healPower = () => 1 + G.mod('passive', 'healPowerPct');
  function shieldU(u, pct) { if (!u.dead && pct > 0) u.shield = Math.min(u.maxHp * C().shieldCapPct, u.shield + u.maxHp * pct); }
  function applyBurn(t, n) { if (!t || t.dead || n <= 0) return; t.burn = Math.min(C().burnCap, t.burn + n); }

  function runHook(hook, actor, target) {
    const m = G.mods[hook] || {};
    if (!Object.keys(m).length) return;
    if (m.burn && target) applyBurn(target, Math.round(m.burn));
    if (m.burnAll) alive('enemy').forEach((e) => applyBurn(e, Math.round(m.burnAll)));
    if (m.ap) gainAp(m.ap);
    if (m.shieldPct && actor) shieldU(actor, m.shieldPct);
    if (m.shieldAllPct) alive('ally').forEach((a) => shieldU(a, m.shieldAllPct));
    if (m.healPct && actor) heal(actor, actor.maxHp * m.healPct * healPower());
    if (m.healAllPct) alive('ally').forEach((a) => heal(a, a.maxHp * m.healAllPct * healPower()));
    if (m.healLowest) { const l = alive('ally').sort((a, b) => a.hp / a.maxHp - b.hp / b.maxHp)[0]; if (l) heal(l, m.healLowest, true); }
    if (m.haste && actor) actor.hasteUntil = Math.max(actor.hasteUntil, B.t + m.haste);
    if (m.breakFlatPct && target && !target.dead && target.breakMax) addBreak(target, target.breakMax * m.breakFlatPct, actor);
  }
  function gainAp(n) { B.ap = Math.min(C().apMax, B.ap + n); }

  function addBreak(t, amount, src) {
    if (t.dead || !t.breakMax || t.brokenUntil > B.t || amount <= 0) return;
    t.brk = Math.min(t.breakMax, t.brk + amount);
    if (t.brk >= t.breakMax) {
      t.brokenUntil = B.t + C().brokenSec;
      t.brk = 0;
      const c = center(t);
      floater(c.x, c.y - 60, t.cast ? 'BREAK! Interrupted' : 'BREAK!', '#ffffff', 30);
      t.cast = null;
      G.sfx('break'); shake(8); burst(c.x, c.y, 16, ['#fff', '#f0c75a'], 5);
      G.run.stats.breaks++;
      runHook('break', src, t);
    }
  }
  function damage(src, t, dmg, opts = {}) {
    if (t.dead || dmg <= 0) return;
    if (t.side === 'ally') {
      dmg *= 1 + G.mod('passive', 'dmgTakenPct') + (t.row === 'front' ? G.mod('passive', 'frontDmgTakenPct') : 0);
      if (B.smokeUntil > B.t) dmg *= 1 - C().smokeReduce;
      if (t.shield > 0) { const ab = Math.min(t.shield, dmg); t.shield -= ab; dmg -= ab; }
    } else if (t.brokenUntil > B.t) dmg *= 1 + C().brokenBonus + G.mod('passive', 'brokenDmgPct');
    if (dmg <= 0) return;
    t.hp -= dmg;
    t.hurtT = G.now();
    const c = center(t);
    if (dmg >= 2 || opts.crit) floater(c.x + G.ri(-26, 26), c.y - 30 + G.ri(-10, 10), String(Math.round(dmg)), opts.crit ? '#f0c75a' : t.side === 'ally' ? '#ff8a6a' : '#ffffff', opts.crit ? 26 : opts.big ? 28 : 17);
    if (t.side === 'enemy' && t.breakMax) {
      const bm = opts.breakMult ?? (src && src.dmgType === 'at' ? 1.6 : src && src.dmgType === 'precision' ? 1.3 : 0.6);
      addBreak(t, (opts.breakDmg ?? dmg * bm) * (1 + G.mod('passive', 'breakPct')), src);
    }
    if (t.side === 'ally' && !t.lowHpFired && t.hp > 0 && t.hp < t.maxHp * 0.4) { t.lowHpFired = true; runHook('lowHp', t, null); }
    if (t.hp <= 0) {
      t.hp = 0; t.dead = true; t.deadT = G.now(); t.cast = null;
      if (t.vehicle) explosion(c.x, c.y, t.boss ? 2 : 1.3);
      if (t.side === 'enemy') {
        G.run.stats.kills++; if (src && src.side === 'ally') src.kills++;
        gainAp(C().apPerKill);
        runHook('kill', src, t);
        if (B.focus === t) { B.focus = null; renderFocus(); }
        floater(c.x, c.y - 70, 'DESTROYED', '#f0c75a', 22);
      } else { floater(c.x, c.y - 70, 'SQUAD WIPED', '#ff8a6a', 22); G.run.stats.wipes++; }
    }
    syncFigs(t);
  }
  function hitRoll(u, t, base, opts = {}) {
    let dmgPct = 0, crit = false;
    if (u.side === 'ally') {
      dmgPct = G.mod('passive', 'dmgPct') + (opts.skillDmgPct || 0) + (opts.spread ? G.mod('passive', 'blastDmgPct') : 0) + (t.role === 'armor' ? G.mod('passive', 'armorDmgPct') : 0) + vetBonus(u) + (opts.volleyBonus || 0);
      if (Math.random() < C().baseCrit + G.mod('passive', 'critPct')) crit = true;
    } else dmgPct = officerAura();
    let dmg = base * counter(u.dmgType, t.role) * (1 + dmgPct) * (u.side === 'enemy' ? u.atkM : C().allyDmgScale);
    if (crit) dmg *= C().critMult;
    dmg *= 1 + (Math.random() * 2 - 1) * C().variance;
    return { dmg, crit };
  }

  // ---------- attacks ----------
  function setAttackPose(u) {
    const live = u.figs.filter((f) => !f.dead);
    live.forEach((f) => (f.atkT = B.t + Math.random() * 0.12));
    u.atkPoseT = B.t;
  }
  function doAttack(u) {
    const def = u.def;
    if (def.dmgType === 'heal') {
      const pool = alive('ally').filter((a) => a.hp < a.maxHp - 1).sort((a, b) => a.hp / a.maxHp - b.hp / b.maxHp);
      if (!pool.length) return;
      const t = pool[0];
      setAttackPose(u);
      heal(t, def.heal * C().healScale * outMult(u) * healPower() * (1 + vetBonus(u)));
      burst(center(t).x, center(t).y, 6, ['#9cc95e', '#e7f5c8'], 2);
      return;
    }
    const t = pickTarget(u);
    if (!t) return;
    u.atkCount++;
    const volley = u.side === 'ally' && u.atkCount % 4 === 0;
    const targets = def.spread ? neighbours(t) : [t];
    setAttackPose(u);
    const m = muzzleOf(u);
    const base = def.dmg * outMult(u);
    const resolve = () => {
      targets.forEach((tt, i) => {
        if (tt.dead) return;
        const h = hitRoll(u, tt, base * (i === 0 ? 1 : 0.6), { spread: def.spread, volleyBonus: volley ? G.mod('volley', 'dmgBonus') : 0 });
        damage(u, tt, h.dmg, { crit: h.crit });
        if (def.burn) applyBurn(tt, def.burn);
        if (u.side === 'ally') {
          if (h.crit) runHook('crit', u, tt);
          if (u.hasteUntil > B.t && G.skillMod('volley', 'burnOnHit') && u.ability.def.id === 'volley') applyBurn(tt, G.skillMod('volley', 'burnOnHit'));
        }
      });
      if (volley) runHook('volley', u, t);
    };
    if (def.lob) {
      const c = center(t);
      lobs.push({ x1: m.x, y1: m.y, x2: c.x + G.ri(-20, 20), y2: c.y + 20, t: G.now(), dur: 520, done: () => { explosion(c.x, c.y + 10, 0.5); resolve(); } });
      G.sfx('click');
    } else if (def.flame) {
      flames.push({ x: m.x, y: m.y, dir: u.side === 'ally' ? 1 : -1, len: Math.abs(center(t).x - m.x), t: G.now() });
      resolve();
    } else {
      const c = center(t);
      const n = Math.min(3, u.figs.filter((f) => !f.dead).length || 1);
      for (let i = 0; i < n; i++) { const mm = muzzleOf(u); tracer(mm.x, mm.y, c.x + G.ri(-24, 24), c.y + G.ri(-20, 20), u.side === 'enemy' && u.occult ? '#6dffb4' : '#fff3b0'); }
      G.sfx(u.dmgType === 'blast' || u.dmgType === 'cannon' ? 'mg' : 'shot');
      if (u.dmgType === 'cannon') explosion(c.x, c.y, 0.45);
      resolve();
    }
  }

  // ---------- abilities ----------
  const abilityCost = (u) => Math.max(0, u.ability.def.ap + G.skillMod(u.ability.def.id, 'apCost') + G.mod('passive', 'apCostAll'));
  const abilityCd = (u) => Math.max(2, (u.ability.def.cd + G.skillMod(u.ability.def.id, 'cd')) * (1 + G.mod('passive', 'cdPct')));
  const canCast = (u) => !u.dead && B && !B.over && u.ability.cdLeft <= 0 && B.ap >= abilityCost(u);
  function castAbility(u) {
    if (!canCast(u)) { if (!u.dead && u.ability.cdLeft <= 0 && !G.testMode) G.toast('Not enough AP', 900); return; }
    const a = u.ability.def, id = a.id;
    const sk = (k) => G.skillMod(id, k);
    B.ap -= abilityCost(u);
    u.ability.cdLeft = abilityCd(u);
    G.run.stats.casts++;
    banner(a.name);
    G.sfx('perfect');
    const bonus = 1 + vetBonus(u) + G.mod('passive', 'dmgPct') + sk('dmgPct');
    setAttackPose(u);
    if (a.haste) u.hasteUntil = B.t + a.haste;
    const hasteAll = (a.hasteAll || 0) + sk('hasteAll');
    if (hasteAll) alive('ally').forEach((x) => (x.hasteUntil = Math.max(x.hasteUntil, B.t + hasteAll)));
    const shieldAll = (a.shieldAllPct || 0) + sk('shieldAllPct');
    if (shieldAll) alive('ally').forEach((x) => shieldU(x, shieldAll));
    if (a.healAllPct) { alive('ally').forEach((x) => { heal(x, x.maxHp * a.healAllPct * healPower()); burst(center(x).x, center(x).y, 8, ['#9cc95e', '#e7f5c8'], 2.5); }); G.sfx('heal'); }
    if (a.blastDmg) {
      alive('enemy').forEach((e) => {
        const c = center(e);
        explosion(c.x, c.y, 0.5);
        const h = hitRoll(u, e, a.blastDmg * C().abilityScale, { spread: true, skillDmgPct: sk('dmgPct') });
        damage(u, e, h.dmg, { crit: h.crit, big: true, breakDmg: a.breakAll ? a.breakAll * C().abilityScale : h.dmg * 0.6 });
      });
    }
    if (a.slow) alive('enemy').forEach((e) => (e.slowUntil = B.t + a.slow));
    if (sk('burnAll')) alive('enemy').forEach((e) => applyBurn(e, Math.round(sk('burnAll'))));
    if (sk('breakFlatPct')) alive('enemy').forEach((e) => e.breakMax && addBreak(e, e.breakMax * sk('breakFlatPct'), u));
    if (a.nuke) {
      const t = B.focus && !B.focus.dead ? B.focus : pickTarget(u);
      if (t) {
        const m = muzzleOf(u), c = center(t);
        tracer(m.x, m.y, c.x, c.y, '#ffffff'); tracer(m.x, m.y - 2, c.x, c.y + 2, '#f0c75a');
        G.sfx('shot');
        const h = hitRoll(u, t, a.nuke * C().abilityScale * (1 + sk('dmgPct')), {});
        damage(u, t, h.dmg, { crit: h.crit, big: true, breakDmg: (a.breakDmg || 0) * C().abilityScale * (1 + sk('dmgPct')) });
        burst(c.x, c.y, 10, ['#fff', '#f0c75a'], 4);
      }
    }
    runHook('cast', u, null);
    renderHud(true);
  }
  function useItem(id) {
    if (!B || B.over || !G.run.items[id]) return;
    G.run.items[id]--;
    const it = D.items[id];
    banner(it.name);
    if (id === 'grenade') {
      const mult = 1 + G.mod('passive', 'grenadePct') + G.mod('passive', 'dmgPct') + G.mod('passive', 'blastDmgPct');
      alive('enemy').forEach((e) => { const c = center(e); explosion(c.x, c.y, 0.7); damage(null, e, it.dmg * C().abilityScale * mult * counter('blast', e.role), { big: true, breakDmg: it.break * C().abilityScale }); });
    } else if (id === 'medkit') {
      const l = alive('ally').sort((a, b) => a.hp / a.maxHp - b.hp / b.maxHp)[0];
      if (l) { heal(l, l.maxHp * it.heal * healPower()); G.sfx('heal'); }
    } else if (id === 'stim') { gainAp(it.ap); G.sfx('good'); }
    else if (id === 'smoke') { B.smokeUntil = B.t + C().smokeSec; burst(260, 520, 50, ['#cfcfc4', '#a9a99c', '#8a8a7e'], 3, 1600); }
    renderHud(true);
  }

  // ---------- enemy casts ----------
  function startCast(e, ab) {
    e.cast = { def: ab.def, t: 0, dur: ab.def.cast };
    ab.cdLeft = ab.def.cd * C().enemyCastCdMult;
    banner(`${e.name}: ${ab.def.name}`, true);
    if (e.occult) G.sfx('occult');
  }
  function resolveCast(e) {
    const a = e.cast.def;
    e.cast = null;
    setAttackPose(e);
    if (a.healAllPct) { alive('enemy').forEach((x) => { x.hp = Math.min(x.maxHp, x.hp + x.maxHp * a.healAllPct); syncFigs(x); floater(center(x).x, center(x).y - 50, 'Rallied', '#9cc95e', 18); }); return; }
    let targets = alive('ally');
    if (a.target === 'front') { const fr = targets.filter((t) => t.row === 'front'); if (fr.length) targets = fr; }
    if (a.target === 'single') targets = [pickTarget(e)].filter(Boolean);
    const m = muzzleOf(e);
    targets.forEach((t) => {
      const c = center(t);
      if (a.target === 'single') { tracer(m.x, m.y, c.x, c.y, e.occult ? '#6dffb4' : '#ffd9a0'); explosion(c.x, c.y, 0.9); }
      else explosion(c.x, c.y, 0.6);
      const h = hitRoll(e, t, a.dmg * C().enemyCastScale, {});
      damage(e, t, h.dmg, { big: true });
      if (a.burn) applyBurn(t, a.burn);
    });
    shake(10);
  }

  // ---------- simulation ----------
  function tickUnit(u, dt) {
    if (u.dead) return;
    // burn
    if (u.burn > 0) {
      u.burnT += dt; u.decayT += dt;
      if (u.burnT >= 1) {
        u.burnT -= 1;
        const mult = u.side === 'enemy' ? 1 + G.mod('passive', 'burnDmgPct') : 1;
        damage(null, u, u.burn * C().burnDpsPerStack * mult, { breakDmg: 0 });
        burst(center(u).x, center(u).y, 3, ['#ffb347', '#d9480f'], 1.5, 400);
        if (u.side === 'enemy') runHook('burnTick', null, u);
        if (u.dead) return;
      }
      if (u.decayT >= C().burnDecaySec) { u.decayT = 0; u.burn = Math.max(0, u.burn - 1); }
    }
    if (u.side === 'ally') {
      const drain = G.mod('passive', 'hpDrainPct');
      if (drain > 0 && u.hp > 1) { u.hp = Math.max(1, u.hp - u.maxHp * drain * dt); syncFigs(u); }
      if (u.ability.cdLeft > 0) u.ability.cdLeft -= dt;
    }
    if (u.side === 'enemy') {
      if (u.brokenUntil > B.t) return;
      if (u.cast) { u.cast.t += dt; if (u.cast.t >= u.cast.dur) resolveCast(u); return; }
      for (const ab of u.abilities) {
        ab.cdLeft -= dt;
        if (ab.cdLeft <= 0 && !u.cast) { startCast(u, ab); return; }
      }
    }
    let rate = 1;
    if (u.hasteUntil > B.t) rate *= 2;
    if (u.slowUntil > B.t) rate *= 0.6;
    if (u.side === 'ally') rate *= 1 + G.mod('passive', 'ratePct');
    u.atkTimer -= dt * rate;
    if (u.atkTimer <= 0) { u.atkTimer += u.def.rate; doAttack(u); }
  }
  function step(dt) {
    B.t += dt;
    B.ap = Math.min(C().apMax, B.ap + C().apPerSec * (1 + G.mod('passive', 'apRegenPct')) * dt);
    for (const u of B.allies) tickUnit(u, dt);
    for (const u of B.enemies) tickUnit(u, dt);
    // auto-cast (setting or test bot)
    if (G.settings.autoCast || G.testMode) {
      B.autoT = (B.autoT || 0) + dt;
      if (B.autoT > 0.7) {
        B.autoT = 0;
        const ready = B.allies.filter(canCast);
        if (ready.length) castAbility(G.pick(ready));
        if (G.testMode && G.itemCount() && Math.random() < 0.05) useItem(Object.keys(G.run.items).find((k) => G.run.items[k] > 0));
      }
    }
    if (!alive('enemy').length) end('win');
    else if (!alive('ally').length) end('lose');
  }

  // ---------- render ----------
  function frame(now) {
    rafId = requestAnimationFrame(frame);
    if (!B) return;
    const realDt = Math.min(0.05, (now - last) / 1000 || 0);
    last = now;
    if (!B.paused && !B.over) {
      let dt = realDt * B.speedMult * (G.testMode ? 12 : 1);
      while (dt > 0 && !B.over) { const d = Math.min(dt, 0.05); step(d); dt -= d; }
    }
    draw(now);
    B.hudT = (B.hudT || 0) + realDt;
    if (B.hudT > 0.12) { B.hudT = 0; renderHud(); }
  }
  function draw(now) {
    const t = now / 1000;
    let sx = 0, sy = 0;
    if (shakeMag > 0) { const age = (now - shakeT) / 320; if (age > 1) shakeMag = 0; else { sx = (Math.random() - 0.5) * shakeMag * (1 - age); sy = (Math.random() - 0.5) * shakeMag * (1 - age); } }
    ctx.setTransform(scale, 0, 0, scale, sx * scale, sy * scale);
    ctx.drawImage(B.bg, 0, 0, W, H);
    if (B.bgKey.includes('snow')) {
      ctx.fillStyle = 'rgba(255,255,255,0.75)';
      for (let i = 0; i < 60; i++) ctx.fillRect((i * 97 + t * (20 + (i % 5) * 8)) % W, (i * 61 + t * (40 + (i % 7) * 10)) % H, 2 + (i % 2), 2 + (i % 2));
    }
    if (B.occult) { ctx.fillStyle = `rgba(80,255,170,${0.035 + 0.025 * Math.sin(t * 1.5)})`; ctx.fillRect(0, 0, W, H); }
    if (B.smokeUntil > B.t) { ctx.fillStyle = 'rgba(200,200,190,0.18)'; ctx.fillRect(0, 380, 560, 240); }
    const units = [...B.allies, ...B.enemies].sort((a, b) => a.y - b.y);
    for (const u of units) drawUnit(u, now, t);
    for (const u of units) if (!u.dead) bars(u, t);
    if (B.focus && !B.focus.dead) reticle(B.focus, t);
    // flames
    for (let i = flames.length - 1; i >= 0; i--) {
      const f = flames[i]; const age = (now - f.t) / 380;
      if (age > 1) { flames.splice(i, 1); continue; }
      ctx.save(); ctx.globalAlpha = 1 - age; ctx.translate(f.x, f.y); ctx.scale(f.dir, 1);
      G.art.flame(ctx, 0, 0, Math.min(260, f.len)); ctx.restore();
    }
    // lobbed shells
    for (let i = lobs.length - 1; i >= 0; i--) {
      const l = lobs[i]; const a = (now - l.t) / (l.dur * Math.max(0.15, 1 / (B.speedMult * (G.testMode ? 12 : 1))));
      if (a >= 1) { lobs.splice(i, 1); l.done(); continue; }
      const x = G.lerp(l.x1, l.x2, a), y = G.lerp(l.y1, l.y2, a) - Math.sin(a * Math.PI) * 120;
      ctx.fillStyle = '#2b2a24'; ctx.beginPath(); ctx.arc(x, y, 5, 0, 7); ctx.fill();
    }
    for (let i = tracers.length - 1; i >= 0; i--) {
      const tr = tracers[i]; const age = (now - tr.t) / 160;
      if (age > 1) { tracers.splice(i, 1); continue; }
      ctx.save(); ctx.globalAlpha = 1 - age; ctx.strokeStyle = tr.col; ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.moveTo(G.lerp(tr.x1, tr.x2, age * 0.6), G.lerp(tr.y1, tr.y2, age * 0.6)); ctx.lineTo(tr.x2, tr.y2); ctx.stroke(); ctx.restore();
    }
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i]; const age = (now - p.t) / p.life;
      if (age > 1) { particles.splice(i, 1); continue; }
      p.x += p.vx; p.y += p.vy; p.vy += 0.12;
      ctx.globalAlpha = 1 - age; ctx.fillStyle = p.col; ctx.beginPath(); ctx.arc(p.x, p.y, p.r * (1 - age * 0.5), 0, 7); ctx.fill();
    }
    ctx.globalAlpha = 1;
    for (let i = floaters.length - 1; i >= 0; i--) {
      const f = floaters[i]; const age = (now - f.t) / 900;
      if (age > 1) { floaters.splice(i, 1); continue; }
      ctx.save(); ctx.globalAlpha = Math.min(1, 2 - age * 2);
      ctx.font = `700 ${f.size}px 'Barlow Condensed', 'Arial Narrow', sans-serif`; ctx.textAlign = 'center';
      ctx.lineWidth = 4; ctx.strokeStyle = '#000'; const y = f.y - age * 34;
      ctx.strokeText(f.text, f.x, y); ctx.fillStyle = f.color; ctx.fillText(f.text, f.x, y); ctx.restore();
    }
    if (B.paused) {
      ctx.fillStyle = 'rgba(0,0,0,0.45)'; ctx.fillRect(0, 0, W, H);
      ctx.font = "700 46px 'Stardos Stencil', Impact, sans-serif"; ctx.textAlign = 'center'; ctx.fillStyle = '#e6dbbd';
      ctx.fillText('PAUSED', W / 2, H / 2);
    }
  }
  function drawUnit(u, now, t) {
    const hurt = u.hurtT && now - u.hurtT < 120;
    if (u.vehicle) {
      let alpha = 1;
      if (u.dead) { const age = (now - u.deadT) / 800; if (age > 1) return; alpha = 1 - age; }
      ctx.save();
      if (u.occult && !u.dead) { ctx.shadowColor = '#6dffb4'; ctx.shadowBlur = 16 + 8 * Math.sin(t * 2); }
      const casting = u.cast ? `rgba(255,90,60,${0.18 + 0.15 * Math.sin(now / 60)})` : null;
      G.art.drawUnit(ctx, { side: 'enemy', art: u.art }, u.x, u.y, u.s, { t, alpha, flash: u.atkPoseT && B.t - u.atkPoseT < 0.08, tint: hurt ? 'rgba(255,255,255,0.45)' : casting });
      ctx.restore();
      return;
    }
    if (u.tent && !u.dead) G.art.drawTent(ctx, u.x - 30, u.y - 26, u.s);
    if (u.isHero && !u.dead) {
      ctx.save(); ctx.globalAlpha = 0.55 + 0.25 * Math.sin(t * 3);
      ctx.strokeStyle = '#f0c75a'; ctx.lineWidth = 3; ctx.beginPath(); ctx.ellipse(u.x, u.y + 2, 34, 9, 0, 0, 7); ctx.stroke(); ctx.restore();
    }
    const dir = u.side === 'ally' ? 1 : -1;
    const figs = u.figs.slice().sort((a, b) => a.dy - b.dy);
    for (const f of figs) {
      let alpha = 1, pose = 'idle';
      if (f.dead) {
        if (f.dieT < 0) continue;
        const age = (B.t - f.dieT) / 0.8;
        if (age > 1 || age < 0) continue;
        alpha = 1 - age; pose = 'down';
      } else if (B.t - f.atkT < 0.22 && B.t >= f.atkT) pose = 'attack';
      const bob = pose === 'idle' ? Math.sin(t * 2.2 + f.ph) * 1.2 : 0;
      const casting = u.cast ? `rgba(255,90,60,${0.2 + 0.15 * Math.sin(now / 60)})` : null;
      const broken = u.brokenUntil > B.t;
      G.art.drawFigure(ctx, u.figure, pose, u.x + f.dx * dir, u.y + f.dy + bob, u.s, { flip: dir < 0, alpha, tint: hurt ? 'rgba(255,255,255,0.5)' : casting || (broken ? 'rgba(255,240,150,0.25)' : null), glow: u.occult, t: t + f.ph });
    }
  }
  function bars(u, t) {
    const b = unitBox(u);
    const w = u.vehicle ? Math.max(90, Math.min(180, b.x1 - b.x0)) : 92;
    const x = u.x - w / 2, y = b.y0 - 14;
    ctx.fillStyle = '#000000a8'; ctx.fillRect(x - 2, y - 2, w + 4, u.breakMax ? 15 : 10);
    ctx.fillStyle = u.side === 'ally' ? '#24340f' : '#3a0f08'; ctx.fillRect(x, y, w, 6);
    ctx.fillStyle = u.side === 'ally' ? '#9cc95e' : '#e0603f'; ctx.fillRect(x, y, w * (u.hp / u.maxHp), 6);
    if (u.shield > 0) { ctx.fillStyle = '#d8e6ff'; ctx.fillRect(x, y, w * Math.min(1, u.shield / u.maxHp), 2); }
    if (u.breakMax) {
      ctx.fillStyle = '#2a2614'; ctx.fillRect(x, y + 8, w, 4);
      ctx.fillStyle = u.brokenUntil > B.t ? '#ffffff' : '#f0c75a'; ctx.fillRect(x, y + 8, w * (u.brokenUntil > B.t ? 1 : u.brk / u.breakMax), 4);
    }
    // rank chevrons / hero level / role tag
    ctx.font = "700 12px 'Barlow Condensed', sans-serif"; ctx.textAlign = 'left'; ctx.fillStyle = '#fff';
    const tag = u.isHero ? `Lv ${u.level}` : u.side === 'ally' && u.rank ? '★'.repeat(u.rank) : '';
    if (tag) { ctx.fillStyle = '#f0c75a'; ctx.fillText(tag, x, y - 4); }
    if (u.burn > 0) { ctx.fillStyle = '#ff9a4a'; ctx.textAlign = 'right'; ctx.fillText(`🔥${u.burn}`, x + w, y - 4); }
    if (u.brokenUntil > B.t) { ctx.fillStyle = '#ffffff'; ctx.textAlign = 'center'; ctx.fillText('STUNNED', u.x, y - 4); }
    if (u.cast) {
      const cw = w + 20, cy = y - 22;
      ctx.fillStyle = '#000000c0'; ctx.fillRect(u.x - cw / 2 - 2, cy - 2, cw + 4, 10);
      ctx.fillStyle = '#e0603f'; ctx.fillRect(u.x - cw / 2, cy, cw * (u.cast.t / u.cast.dur), 6);
      ctx.fillStyle = '#ffd9c4'; ctx.textAlign = 'center'; ctx.font = "700 13px 'Barlow Condensed', sans-serif"; ctx.fillText(u.cast.def.name.toUpperCase(), u.x, cy - 5);
    }
  }
  function reticle(u, t) {
    const b = unitBox(u);
    const p = 4 * Math.sin(t * 6), L = 14;
    ctx.save(); ctx.strokeStyle = '#f0c75a'; ctx.lineWidth = 3.5;
    [[b.x0 - p, b.y0 - p, 1, 1], [b.x1 + p, b.y0 - p, -1, 1], [b.x0 - p, b.y1 + p, 1, -1], [b.x1 + p, b.y1 + p, -1, -1]].forEach(([x, y, sx, sy]) => {
      ctx.beginPath(); ctx.moveTo(x, y + sy * L); ctx.lineTo(x, y); ctx.lineTo(x + sx * L, y); ctx.stroke();
    });
    ctx.restore();
  }

  // ---------- HUD ----------
  let hudRefs = null;
  function banner(text, enemy) {
    const b = G.$('#banner');
    b.textContent = text; b.className = `banner ${enemy ? 'enemy' : ''}`; b.hidden = !text;
    clearTimeout(banner._t);
    if (text) banner._t = setTimeout(() => (b.hidden = true), 1400);
  }
  function togglePause() { if (!B || B.over) return; B.paused = !B.paused; renderHud(true); }
  function buildHud() {
    const top = G.$('#timeline');
    top.innerHTML = '';
    const apBar = G.el('div', { class: 'ap-meter' }, G.el('i'), G.el('span'));
    const speed = G.el('button', { class: 'icon-btn', type: 'button', id: 'btn-speed' }, '1x');
    speed.addEventListener('click', () => { B.speedMult = B.speedMult === 1 ? 2 : 1; G.sfx('click'); renderHud(true); });
    const pause = G.el('button', { class: 'icon-btn', type: 'button', id: 'btn-pause' }, 'Pause');
    pause.addEventListener('click', togglePause);
    top.append(G.el('span', { class: 'tl-label', text: 'AP' }), apBar, speed, pause);
    const cards = G.$('#squad-cards');
    cards.innerHTML = '';
    cards.className = 'squad-cards rt';
    const refs = [];
    B.allies.forEach((u, i) => {
      const a = u.ability.def;
      const btn = G.el('button', { class: 'ab-card', type: 'button' },
        G.el('img', { src: G.art.figPortrait(u.figure, 64, 'ally'), alt: '' }),
        G.el('div', { class: 'ab-main' },
          G.el('div', { class: 'ab-name' }, G.el('span', { text: u.isHero ? u.name : u.def.name }), G.el('em', { text: u.isHero ? `Lv ${u.level}` : '★'.repeat(u.rank) })),
          G.el('div', { class: 'bar' }, G.el('i'), G.el('span')),
          G.el('div', { class: 'ab-skill' }, G.el('b', { text: a.name }), G.el('small', { text: `${abilityCost(u)} AP` }))),
        G.el('div', { class: 'ab-cd' }));
      btn.addEventListener('click', () => { G.audio.unlock(); castAbility(u); });
      if (u.isHero) btn.classList.add('hero');
      cards.append(btn);
      refs.push({ u, btn, hp: btn.querySelector('.bar i'), hpTxt: btn.querySelector('.bar span'), cd: btn.querySelector('.ab-cd'), cost: btn.querySelector('.ab-skill small') });
    });
    const cmds = G.$('#cmds');
    cmds.innerHTML = '';
    cmds.className = 'cmds items';
    const itemRefs = [];
    Object.keys(D.items).forEach((id) => {
      const b = G.el('button', { class: 'cmd', type: 'button' }, D.items[id].name, G.el('small'));
      b.addEventListener('click', () => { G.sfx('click'); useItem(id); });
      cmds.append(b);
      itemRefs.push({ id, b, n: b.querySelector('small') });
    });
    hudRefs = { apBar, speed, pause, refs, itemRefs };
  }
  function renderHud(force) {
    if (!B || !hudRefs) return;
    const { apBar, speed, pause, refs, itemRefs } = hudRefs;
    apBar.querySelector('i').style.width = `${(B.ap / C().apMax) * 100}%`;
    apBar.querySelector('span').textContent = `${Math.floor(B.ap)} / ${C().apMax}`;
    speed.textContent = `${B.speedMult}x`;
    pause.textContent = B.paused ? 'Resume' : 'Pause';
    for (const r of refs) {
      const u = r.u;
      r.hp.style.width = `${(u.hp / u.maxHp) * 100}%`;
      r.hpTxt.textContent = u.dead ? 'Wiped' : `${Math.ceil(u.hp)}/${u.maxHp}`;
      const cost = abilityCost(u);
      r.cost.textContent = `${cost} AP`;
      const cdFrac = u.ability.cdLeft > 0 ? u.ability.cdLeft / abilityCd(u) : 0;
      r.cd.style.height = `${cdFrac * 100}%`;
      r.btn.disabled = u.dead;
      r.btn.classList.toggle('ready', canCast(u));
      r.btn.classList.toggle('poor', !u.dead && u.ability.cdLeft <= 0 && B.ap < cost);
    }
    for (const r of itemRefs) { const n = G.run.items[r.id] || 0; r.n.textContent = `x${n}`; r.b.disabled = !n || B.over; }
  }
  function renderFocus() {
    const el = G.$('#target-line');
    if (!B) return;
    el.innerHTML = B.focus && !B.focus.dead
      ? `Focus: <b>${G.esc(B.focus.name)}</b> · ${G.esc(roleName(B.focus.role))} · tap again to clear`
      : 'Tap an enemy to focus fire. Tap an ability card to cast it.';
  }
  const roleName = (r) => ({ infantry: 'Infantry', recon: 'Recon', support: 'Support', armor: 'Armor' }[r] || r);

  // ---------- lifecycle ----------
  let endResolve = null;
  function end(result) {
    if (B.over) return;
    B.over = true;
    B.result = result;
    banner(result === 'win' ? 'Area secured' : 'Army wiped out', result !== 'win');
    G.sfx(result === 'win' ? 'win' : 'lose');
    renderHud(true);
    setTimeout(() => endResolve && endResolve(result), 1400 * G.speed);
  }
  function run(spec) {
    initCanvas();
    G.show('battle');
    floaters.length = particles.length = tracers.length = lobs.length = flames.length = 0;
    const ch = G.chapter();
    const army = spec.army || G.run.army;
    B = {
      allies: [...army.map((sq) => mkAlly(sq, false)), ...(G.run.hero ? [mkAlly(G.run.hero, true)] : [])].filter((u) => !u.dead || true),
      enemies: spec.enemies.map((k) => mkEnemy(k, spec.tier || 0)),
      t: 0, ap: Math.min(C().apMax, C().apStart + G.mod('passive', 'startAp')), focus: null, over: false, paused: false, speedMult: G.settings.fast ? 2 : 1,
      bg: G.art.backdrop(spec.bg), bgKey: spec.bg || '', occult: spec.enemies.some((k) => D.enemies[k].occult), smokeUntil: 0,
    };
    // squads that start wiped sit out the fight
    B.allies = B.allies.filter((u) => !u.dead);
    layout();
    buildHud(); renderHud(true); renderFocus();
    const boss = B.enemies.find((e) => e.boss);
    banner(boss ? boss.name : spec.title || 'Contact!', !!boss);
    runHook('battleStart', null, null);
    if (!G.meta.seenTips.rt && !G.testMode) { G.meta.seenTips.rt = true; G.toast('Your squads fire on their own. Spend AP on ability cards. Tap an enemy to focus fire.', 5200); }
    last = G.now();
    if (!rafId) rafId = requestAnimationFrame(frame);
    G._resizeStage && G._resizeStage();
    return new Promise((resolve) => {
      endResolve = (result) => {
        endResolve = null;
        const out = { result, units: B.allies.map((u) => ({ ref: u.ref, isHero: u.isHero, dead: u.dead, frac: u.hp / u.maxHp, kills: u.kills })) };
        B = null; hudRefs = null;
        resolve(out);
      };
    });
  }
  document.addEventListener('visibilitychange', () => { if (document.hidden && B && !B.over) { B.paused = true; renderHud(true); } });

  return { run, W, H, counter };
})();
