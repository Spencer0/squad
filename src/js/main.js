// Run flow: base -> deploy -> map -> nodes -> boss -> results -> base.
G.clock = { t: G.now() };
G.tickClock = () => {
  const n = G.now();
  if (G.run) G.run.timeMs += n - G.clock.t;
  G.clock.t = n;
};

G.startRun = async (chId, heat, squad) => {
  G.newRun(chId, heat, squad);
  G.clock.t = G.now();
  G.renderMapScreen();
  await G.dialog(G.chapter().story.start);
  if (G.has('cmd_promo')) await G.draft({ kind: 'common', title: 'Field Promotion', eyebrow: 'Start of chapter · pick a Common boon', noSkip: true });
  G.saveAll();
  G.mapLoop();
};
G.resumeRun = () => {
  G.recalc();
  G.clock.t = G.now();
  G.mapLoop();
};

G.renderMapScreen = () => {
  const run = G.run;
  const ch = G.chapter();
  G.show('map');
  G.$('#map-place').textContent = `${ch.place}${run.heat ? ` · Heat ${run.heat}` : ''}`;
  G.$('#map-name').textContent = ch.name;
  const stats = G.$('#map-stats');
  stats.innerHTML = '';
  const xpNeed = D.config.rewards.xpPerLevel;
  stats.append(
    G.el('span', { class: 'chip' }, 'Gold ', G.el('b', { text: String(run.gold) })),
    G.el('span', { class: 'chip' }, `Lv ${run.level} `, G.el('b', { text: `${run.xp % xpNeed}/${xpNeed}` })),
    G.el('button', { class: 'chip', type: 'button', onclick: () => G.showBuild() }, 'Boons ', G.el('b', { text: String(run.boons.length) }))
  );
  G.$('#map-menu').onclick = () => G.showRunMenu();
  const foot = G.$('#map-foot');
  foot.innerHTML = '';
  run.squad.forEach((s, i) => {
    const hp = Math.round(Math.max(0, s.frac) * G.maxHp(s.cls));
    foot.append(G.el('div', { class: 'mini-sq', title: D.classes[s.cls].name },
      G.el('img', { src: G.art.portrait({ side: 'ally', cls: s.cls, art: 'soldier' }, 64), alt: '' }),
      G.el('div', {}, G.el('div', { text: `${D.classes[s.cls].name}${i >= 3 ? ' (R)' : ''}` }), G.el('div', { class: 'mini-hp' }, G.el('i', { style: { width: `${Math.max(0, s.frac) * 100}%`, background: s.frac < 0.35 ? 'var(--bad)' : '' } })), G.el('small', { class: 'muted', text: `${hp} HP` }))));
  });
  foot.append(G.el('div', { class: 'map-hint', text: 'Tap a circled node to move there.' }));
};

G.mapLoop = () => {
  G.tickClock();
  G.saveAll();
  G.renderMapScreen();
  G.renderMap((id) => G.visitNode(id));
  if (G.testMode) setTimeout(() => { const a = G.mapAvailable(); if (a.length && G.screen === 'map') G.visitNode(G.pick(a)); }, 5);
};

G.showRunMenu = () => G.openModal((card) => {
  const confirmBox = G.el('div', { class: 'modal-actions', hidden: true },
    G.el('span', { class: 'muted', text: 'Abandon counts as a loss: you bank 25% of this run\'s points.' }),
    G.el('button', { class: 'btn small primary', type: 'button', onclick: () => { G.closeModal(); G.endRun(false); } }, 'Abandon'),
    G.el('button', { class: 'btn small ghost', type: 'button', onclick: () => (confirmBox.hidden = true) }, 'Stay'));
  card.append(
    G.el('h2', { text: 'Operation menu' }),
    G.el('div', { class: 'rows' },
      G.el('button', { class: 'btn', type: 'button', onclick: () => G.showBuild() }, 'View build'),
      G.el('button', { class: 'btn', type: 'button', onclick: () => G.showHowTo() }, 'How to play'),
      G.el('button', { class: 'btn', type: 'button', onclick: () => G.showSettings() }, 'Settings'),
      G.el('button', { class: 'btn ghost', type: 'button', onclick: () => (confirmBox.hidden = false) }, 'Abandon operation')),
    confirmBox,
    G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn primary', type: 'button', onclick: G.closeModal }, 'Resume')));
});

G.visitNode = async (id) => {
  if (G._visiting) return;
  G._visiting = true;
  try {
    const run = G.run;
    run.node = id;
    run.visited.push(id);
    G.tickClock();
    G.saveAll();
    const n = run.map.nodes[id];
    let ended = false;
    if (['skirmish', 'elite', 'miniboss', 'boss'].includes(n.type)) ended = await G.fightNode(n, n.type);
    else if (n.type === 'intel') {
      const r = await G.intel();
      if (r.fight) ended = await G.fightNode(n, r.fight, { noDraft: !!r.boon });
      if (!ended && r.boon) {
        if (r.boon === 'relic') { const b = G.pick(D.boons.boons.filter((x) => G.boonEligible(x, 'relic'))); if (b) { G.addBoon(b.id); G.toast(`Gained ${b.name}`); } }
        else if (r.boon === 'curse') { const b = G.pick(D.boons.boons.filter((x) => G.boonEligible(x, 'curse'))); if (b) { G.addBoon(b.id); G.toast(`Gained ${b.name}`); } }
        else await G.draft({ guaranteeRare: true, eyebrow: 'A gift · guaranteed Rare' });
      }
    } else if (n.type === 'supply') await G.shop();
    else if (n.type === 'camp') await G.camp();
    else if (n.type === 'cache') await G.cache();
    G._visiting = false;
    if (!ended && G.run) G.mapLoop();
  } catch (err) {
    G._visiting = false;
    console.error(err);
    G.toast('Something went wrong. Returning to the map.');
    if (G.run) G.mapLoop();
  }
};

// returns true when the run ended
G.fightNode = async (n, type, opts = {}) => {
  const ch = G.chapter();
  const enc = ch.encounters;
  let enemies;
  if (type === 'boss') enemies = enc.boss;
  else if (type === 'miniboss') enemies = enc.miniboss;
  else if (type === 'elite') enemies = G.pick(enc.elite);
  else enemies = G.pick(n.row <= 4 ? enc.early : enc.late);
  if (type === 'miniboss') await G.dialog(ch.story.mid);
  if (type === 'boss') await G.dialog(ch.story.end);
  const res = await G.battle.run({ enemies, row: n.row, bg: type === 'boss' ? ch.bossBg : undefined, title: type === 'elite' ? 'Elite squad!' : type === 'miniboss' ? 'Strongpoint' : 'Contact!' });
  G.tickClock();
  if (res !== 'win') { await G.endRun(false); return true; }
  const rw = D.config.rewards[type] || D.config.rewards.skirmish;
  const gold = Math.round(G.ri(rw.gold[0], rw.gold[1]));
  G.run.gold += gold;
  G.run.earned += rw.points;
  G.run.stats.fights++;
  if (type === 'boss') { await G.endRun(true); return true; }
  const before = Math.floor(G.run.xp / D.config.rewards.xpPerLevel);
  G.run.xp += rw.xp;
  const after = Math.floor(G.run.xp / D.config.rewards.xpPerLevel);
  G.renderMapScreen();
  G.renderMap(() => {});
  if (!opts.noDraft) await G.draft({ guaranteeRare: type !== 'skirmish', eyebrow: `Victory · +${gold} gold · +${rw.points} meta-points`, title: type === 'skirmish' ? 'Choose a boon' : 'Choose a boon · Rare guaranteed' });
  for (let i = before; i < after; i++) {
    G.run.level++;
    await G.draft({ kind: 'stat', title: `Level ${G.run.level}`, eyebrow: 'Level up · stat card', noSkip: true });
  }
  return false;
};

G.endRun = async (win) => {
  const run = G.run;
  if (!run) return;
  G.tickClock();
  const ch = G.chapter();
  const R = D.config.rewards;
  const lines = [];
  let total;
  if (win) {
    const base = run.earned;
    lines.push(['Fights and events', `${base}`]);
    lines.push(['Chapter clear', `${R.clearBonus}`]);
    let sub = base + R.clearBonus;
    const perf = Math.floor(run.stats.perfects / R.perfectsPerPoint);
    if (perf) { lines.push([`Perfects (${run.stats.perfects})`, `${perf}`]); sub += perf; }
    if (run.stats.downs === 0) { const nd = Math.round(sub * R.noDeathPct); lines.push(['Nobody went down', `${nd}`]); sub += nd; }
    if (run.timeMs < R.speedBonusMinutes * 60000) { const sp = Math.round(sub * R.speedBonusPct); lines.push([`Under ${R.speedBonusMinutes} minutes`, `${sp}`]); sub += sp; }
    if (run.heat) { const hb = Math.round(sub * run.heat * R.heatPointsPct); lines.push([`Heat ${run.heat}`, `${hb}`]); sub += hb; }
    total = sub;
    G.meta.cleared[ch.id] = true;
    G.meta.heatCleared[ch.id] = Math.max(G.meta.heatCleared[ch.id] ?? -1, run.heat || 0);
    G.meta.clears++;
  } else {
    lines.push(['Points earned this run', `${run.earned}`]);
    lines.push([`Banked on a loss (${G.pct(R.deathBankPct)})`, '']);
    total = run.earned > 0 ? Math.max(1, Math.round(run.earned * R.deathBankPct)) : 0;
  }
  G.meta.points += total;
  const summary = { win, chapterId: ch.id, heat: run.heat, lines, total, stats: run.stats, timeMs: run.timeMs };
  const squad = run.squad.map((s) => s.cls);
  G.run = null;
  G.recalc();
  G.saveAll();
  if (win) { G.renderMapScreen && G.show('map'); await G.dialog(ch.story.win); }
  G.lastResult = summary;
  const choice = await G.showResults(summary);
  if (choice === 'retry') G.startRun(ch.id, summary.heat, squad);
  else G.showBase();
};

// ---------- boot ----------
G.boot = () => {
  G.testMode = location.hash === '#autotest';
  if (G.testMode) G.testDefense = () => G.weighted(['parry', 'dodge', 'hit'], (r) => ({ parry: 1, dodge: 4, hit: 3 }[r]));
  G.loadAll();
  if (G.testMode) { G.meta = G.defaultMeta(); G.run = null; G.applySettings(); }
  G.recalc();
  document.addEventListener('pointerdown', () => G.audio.unlock(), { passive: true });
  window.addEventListener('pagehide', () => { G.tickClock(); G.saveAll(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { G.tickClock(); G.saveAll(); } else G.clock.t = G.now(); });
  G.loadSprites(() => {
    G.showTitle();
    if (G.testMode) G.autotest();
  });
};

// sprites pre-rendered in Blender (optional; procedural art is the fallback)
G.loadSprites = (cb) => {
  const list = Object.entries(D.sprites || {});
  if (!list.length) { cb(); return; }
  let left = list.length;
  const fin = () => { if (--left <= 0) cb(); };
  G.art.sprites = {};
  for (const [k, s] of list) {
    const img = new Image();
    img.onload = () => { G.art.sprites[k] = { img, ...s }; fin(); };
    img.onerror = fin;
    img.src = s.src;
  }
  setTimeout(() => { if (left > 0) { left = 0; cb(); } }, 4000);
};

// headless smoke test: plays full runs with a bot (open the page with #autotest)
G.autotest = async () => {
  G.testLog = [];
  G.testDone = false;
  try {
    for (let i = 0; i < (G.testRuns || 3); i++) {
      const chId = D.chapters[i % D.chapters.length].id;
      G.meta.cleared.hedgerow = true;
      const done = new Promise((r) => (G._testRunDone = r));
      const origEnd = G.endRun;
      G.endRun = async (win) => { G.testLog.push({ chapter: chId, win, fights: G.run.stats.fights, boons: G.run.boons.length, level: G.run.level, gold: G.run.gold, visited: G.run.visited.length }); await origEnd(win); G.endRun = origEnd; G._testRunDone(); };
      G.startRun(chId, 0, ['rifleman', 'mg', 'medic', 'sniper']);
      await done;
    }
  } catch (e) {
    G.testLog.push({ error: String(e && e.stack || e) });
  }
  G.testDone = true;
};

if (document.fonts && document.fonts.ready) {
  let booted = false;
  const go = () => { if (!booted) { booted = true; G.boot(); } };
  document.fonts.ready.then(go);
  setTimeout(go, 1500);
} else G.boot();
