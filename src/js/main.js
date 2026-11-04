// Run flow: base -> muster -> world map -> cities -> capital -> results -> base.
G.clock = { t: G.now() };
G.tickClock = () => { const n = G.now(); if (G.run) G.run.timeMs += n - G.clock.t; G.clock.t = n; };

G.startRun = async (chId, heat, army, heroId) => {
  G.newRun(chId, heat, army, heroId);
  G.clock.t = G.now();
  G.renderMapScreen();
  G.renderMap(() => {});
  await G.dialog(G.chapter().story.start);
  if (G.has('cmd_promo')) await G.draft({ kind: 'common', title: 'Field Promotion', eyebrow: 'Start of chapter · pick a Common boon', noSkip: true });
  G.saveAll();
  G.mapLoop();
};
G.resumeRun = () => { G.recalc(); G.clock.t = G.now(); G.mapLoop(); };

G.renderMapScreen = () => {
  const run = G.run;
  const ch = G.chapter();
  G.show('map');
  G.$('#map-place').textContent = `${ch.place}${run.heat ? ` · Heat ${run.heat}` : ''}`;
  G.$('#map-name').textContent = ch.name;
  const stats = G.$('#map-stats');
  stats.innerHTML = '';
  stats.append(
    G.el('span', { class: 'chip' }, 'Gold ', G.el('b', { text: String(run.gold) })),
    G.el('span', { class: 'chip' }, 'Cap ', G.el('b', { text: `${G.armyCap()}` })),
    G.el('button', { class: 'chip', type: 'button', onclick: () => G.showBuild() }, 'Army ', G.el('b', { text: String(run.army.length) }), ' · Boons ', G.el('b', { text: String(run.boons.length) }))
  );
  G.$('#map-menu').onclick = () => G.showRunMenu();
  const foot = G.$('#map-foot');
  foot.innerHTML = '';
  const entries = [...(run.hero ? [{ hero: true, figure: D.heroes[run.hero.id].figure, name: D.heroes[run.hero.id].name, frac: run.hero.frac, tag: `Lv ${G.heroLevel(run.hero.id)}` }] : []),
    ...run.army.map((sq) => ({ figure: D.units[sq.type].figure, name: D.units[sq.type].name, frac: sq.frac, tag: '★'.repeat(G.vetRank(sq.xp)) }))];
  entries.forEach((e) => foot.append(G.el('div', { class: `mini-sq ${e.hero ? 'hero' : ''}`, title: e.name },
    G.el('img', { src: G.art.figPortrait(e.figure, 64), alt: '' }),
    G.el('div', {}, G.el('div', { text: `${e.name} ${e.tag}` }), G.el('div', { class: 'mini-hp' }, G.el('i', { style: { width: `${Math.max(0, e.frac) * 100}%`, background: e.frac < 0.35 ? 'var(--bad)' : '' } }))))));
  
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
      G.el('button', { class: 'btn', type: 'button', onclick: () => G.showBuild() }, 'Army & build'),
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
    G.tickClock(); G.saveAll();
    const n = run.map.nodes[id];
    let ended = false;
    if (['skirmish', 'elite', 'miniboss', 'boss'].includes(n.type)) ended = await G.fightNode(n, n.type);
    else if (n.type === 'intel') {
      const r = await G.intel();
      if (r.fight) ended = await G.fightNode(n, r.fight, { noDraft: !!r.boon });
      if (!ended && r.boon) {
        const kind = r.boon === 'relic' || r.boon === 'curse' ? r.boon : null;
        if (kind) { const b = G.pick(D.boons.boons.filter((x) => G.boonEligible(x, kind))); if (b) { G.addBoon(b.id); G.toast(`Gained ${b.name}`); } }
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
    if (G.testMode) G.testLog.push({ error: String(err && err.stack || err) });
    G.toast('Something went wrong. Returning to the map.');
    if (G.run) G.mapLoop();
  }
};

G.pickBg = (ch, n, type) => {
  if (type === 'boss') return ch.bgs.boss;
  if (ch.bgs.north && n.tier >= ch.bgs.northFromTier) return G.pick(ch.bgs.north);
  return G.pick(ch.bgs.default);
};

// returns true when the run ended
G.fightNode = async (n, type, opts = {}) => {
  const ch = G.chapter();
  const enc = ch.encounters;
  let enemies;
  if (type === 'boss') enemies = enc.boss;
  else if (type === 'miniboss') enemies = enc.miniboss;
  else if (type === 'elite') enemies = G.pick(enc.elite);
  else enemies = G.pick(n.tier <= 3 ? enc.early : enc.late);
  if (type === 'miniboss') await G.dialog(ch.story.mid);
  if (type === 'boss') await G.dialog(ch.story.end);
  const title = `${n.name}${type === 'elite' ? ' · Elite force' : type === 'miniboss' ? ' · Strongpoint' : type === 'boss' ? ' · Objective' : ''}`;
  const army = await G.deployScreen(enemies, title);
  const res = await G.battle.run({ enemies, tier: n.tier, army, bg: G.pickBg(ch, n, type), title });
  G.tickClock();
  // write back HP, XP and ranks
  const V = D.config.veterancy, HC = D.config.heroes;
  const lines = [];
  for (const u of res.units) {
    if (u.isHero) {
      G.run.hero.frac = u.dead ? (res.result === 'win' ? D.config.combat.reviveFrac : 0) : u.frac;
      if (res.result === 'win') {
        const xp = HC.xpPerBattle + u.kills * HC.xpPerKill;
        const up = G.giveHeroXp(xp);
        const h = D.heroes[G.run.hero.id];
        lines.push({ figure: h.figure, name: h.name, right: `+${xp} XP`, up: up ? `Level ${G.heroLevel(G.run.hero.id)}!` : '', text: up ? 'Hero level up. Their level is permanent.' : `${u.kills} kills` });
      }
      continue;
    }
    const sq = u.ref;
    const d = D.units[sq.type];
    if (u.dead) {
      sq.frac = res.result === 'win' ? D.config.combat.reviveFrac : 0;
      const r = G.vetRank(sq.xp);
      if (r > 0) sq.xp = V.xp[Math.max(0, r - V.rankLossOnWipe)];
      lines.push({ figure: d.figure, name: d.name, right: 'Wiped', up: '', text: r > 0 ? `Reinforced at low strength. Dropped to ${G.vetName(sq.xp)}.` : 'Reinforced at low strength.' });
    } else {
      sq.frac = u.frac;
      if (res.result === 'win') {
        const xp = V.xpPerBattle + u.kills * V.xpPerKill;
        const up = G.giveXp(sq, xp);
        lines.push({ figure: d.figure, name: d.name, right: `+${xp} XP`, up: up ? `${G.vetName(sq.xp)}!` : '', text: up ? 'Ranked up: more HP and damage.' : `${u.kills} kills · ${Math.round(sq.frac * 100)}% HP` });
      }
    }
  }
  if (res.result !== 'win') { await G.endRun(false); return true; }
  const rw = D.config.rewards[type] || D.config.rewards.skirmish;
  const gold = Math.round(G.ri(rw.gold[0], rw.gold[1]));
  G.run.gold += gold;
  G.run.earned += rw.points;
  G.run.stats.fights++;
  if (type === 'boss') { await G.endRun(true); return true; }
  G.renderMapScreen();
  G.renderMap(() => {});
  if (lines.some((l) => l.up)) await G.showAfterAction(lines);
  if (!opts.noDraft) await G.draft({ guaranteeRare: type !== 'skirmish', eyebrow: `Victory · +${gold} gold · +${rw.points} meta-points`, title: type === 'skirmish' ? 'Choose a boon' : 'Choose a boon · Rare guaranteed' });
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
  const capBefore = G.armyCap();
  if (win) {
    const base = run.earned;
    lines.push(['Battles and events', `${base}`]);
    lines.push(['Capital taken', `${R.clearBonus}`]);
    let sub = base + R.clearBonus;
    if (run.stats.wipes === 0) { const nd = Math.round(sub * R.noWipePct); lines.push(['No squad wiped', `${nd}`]); sub += nd; }
    if (run.timeMs < R.speedBonusMinutes * 60000) { const sp = Math.round(sub * R.speedBonusPct); lines.push([`Under ${R.speedBonusMinutes} minutes`, `${sp}`]); sub += sp; }
    if (run.heat) { const hb = Math.round(sub * run.heat * R.heatPointsPct); lines.push([`Heat ${run.heat}`, `${hb}`]); sub += hb; }
    total = sub;
    G.meta.cleared[ch.id] = true;
    G.meta.heatCleared[ch.id] = Math.max(G.meta.heatCleared[ch.id] ?? -1, run.heat || 0);
    G.meta.clears++;
    if (run.hero) G.giveHeroXp(D.config.heroes.xpClear);
  } else {
    lines.push(['Points earned this run', `${run.earned}`]);
    lines.push([`Banked on a loss (${G.pct(R.deathBankPct)})`, '']);
    total = run.earned > 0 ? Math.max(1, Math.round(run.earned * R.deathBankPct)) : 0;
  }
  G.meta.points += total;
  const next = D.chapters.find((c) => c.unlockAfter === ch.id);
  const summary = { win, chapterId: ch.id, heat: run.heat, lines, total, stats: run.stats, timeMs: run.timeMs, hero: run.hero && run.hero.id, heroXp: run.hero ? run.hero.xpEarned || 0 : 0,
    capUp: G.armyCap() > capBefore, unlockText: win && next && G.armyCap() > capBefore ? `${next.place} is now open.` : '' };
  const army = run.army.map((s) => s.type), hero = run.hero && run.hero.id;
  G.run = null;
  G.recalc();
  G.saveAll();
  if (win) await G.dialog(ch.story.win);
  G.lastResult = summary;
  const choice = await G.showResults(summary);
  if (choice === 'retry') G.startRun(ch.id, summary.heat, (G.meta.lastArmy || army), hero);
  else G.showBase();
};

// ---------- assets (Blender renders inlined by build.mjs) ----------
G.loadAssets = (cb) => {
  const A = D.assets || {};
  const jobs = [];
  const load = (src, set) => jobs.push(new Promise((r) => { const img = new Image(); img.onload = () => { set(img); r(); }; img.onerror = r; img.src = src; }));
  G.art.sprites = {};
  for (const [k, s] of Object.entries(D.sprites || {})) load(s.src, (img) => (G.art.sprites[k] = { img, ...s }));
  G.art.units = {};
  for (const [k, u] of Object.entries(A.units || {})) {
    G.art.units[k] = { canvas: u.canvas, muzzle: u.muzzle };
    if (u.idle) load(u.idle, (img) => (G.art.units[k].idleImg = img));
    if (u.attack) load(u.attack, (img) => (G.art.units[k].attackImg = img));
  }
  G.art.bgImgs = {};
  for (const [k, src] of Object.entries((A.bg && A.bg.files) || {})) load(src, (img) => (G.art.bgImgs[k] = img));
  let done = false;
  const fin = () => { if (!done) { done = true; cb(); } };
  Promise.all(jobs).then(fin);
  setTimeout(fin, 6000);
};

G.boot = () => {
  G.testMode = location.hash === '#autotest';
  G.loadAll();
  if (G.testMode) { G.meta = G.defaultMeta(); G.run = null; G.applySettings(); }
  G.recalc();
  document.addEventListener('pointerdown', () => G.audio.unlock(), { passive: true });
  window.addEventListener('pagehide', () => { G.tickClock(); G.saveAll(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { G.tickClock(); G.saveAll(); } else G.clock.t = G.now(); });
  G.loadAssets(() => { G.showTitle(); if (G.testMode) G.autotest(); });
};

// headless smoke test: open the page with #autotest and a bot plays full chapters
G.autotest = async () => {
  G.testLog = [];
  G.testDone = false;
  try {
    const plan = G.testPlan || ['na', 'eu', 'asia'];
    for (const chId of plan) {
      const done = new Promise((r) => (G._testRunDone = r));
      const origEnd = G.endRun;
      G.endRun = async (win) => {
        G.testLog.push({ chapter: chId, win, fights: G.run.stats.fights, kills: G.run.stats.kills, wipes: G.run.stats.wipes, rankUps: G.run.stats.rankUps, army: G.run.army.length, boons: G.run.boons.length, gold: G.run.gold, visited: G.run.visited.length, minutes: +(G.run.timeMs / 60000).toFixed(1), heroLv: G.run.hero && G.heroLevel(G.run.hero.id) });
        await origEnd(win); G.endRun = origEnd; G._testRunDone();
      };
      const cap = G.armyCap();
      const army = [];
      const types = ['rifle', 'mg', 'sapper', 'shield', 'bugler', 'medic', 'rifle', 'sapper', 'mg'];
      for (const t of types) if (G.armyCost(army.map((type) => ({ type }))) + D.units[t].cost <= cap) army.push(t);
      G.startRun(chId, 0, army, 'okafor');
      await done;
    }
  } catch (e) { G.testLog.push({ error: String(e && e.stack || e) }); }
  G.testDone = true;
};

if (document.fonts && document.fonts.ready) {
  let booted = false;
  const go = () => { if (!booted) { booted = true; G.boot(); } };
  document.fonts.ready.then(go);
  setTimeout(go, 1500);
} else G.boot();

// balance harness: G.simBattle('na', 2, ['rifle','grenadier'], ['rifle','mg','sapper'], 'okafor') -> outcome
G.simBattle = async (chId, tier, enemies, armyTypes, heroId, boons = []) => {
  G.newRun(chId, 0, armyTypes, heroId);
  boons.forEach((b) => G.addBoon(b));
  const t0 = G.now();
  const res = await G.battle.run({ enemies, tier, army: G.run.army, bg: 'us_farm' });
  return { result: res.result, hpLeft: +(res.units.reduce((s, u) => s + (u.dead ? 0 : u.frac), 0) / res.units.length).toFixed(2), wiped: res.units.filter((u) => u.dead).length, secs: +((G.now() - t0) / 1000 * 12).toFixed(0) };
};
