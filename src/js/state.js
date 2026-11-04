// Persistent meta-progress, settings, the current run, and stat modifiers.
const SAVE_KEY = 'squad.save.v1';

G.defaultSettings = () => ({ window: 'normal', autoOffense: false, autoDefense: false, fast: false, sound: true, shake: true, tips: true });
G.defaultMeta = () => ({ points: 0, ranks: {}, cleared: {}, heatCleared: {}, codex: {}, runs: 0, clears: 0, lastSquad: null, seenTips: {} });

G.loadAll = () => {
  const s = G.storage.get(SAVE_KEY, null) || {};
  G.meta = Object.assign(G.defaultMeta(), s.meta || {});
  G.settings = Object.assign(G.defaultSettings(), s.settings || {});
  G.run = s.run || null;
  G.applySettings();
};
G.saveAll = () => {
  if (G.testMode) return;
  G.storage.set(SAVE_KEY, { meta: G.meta, settings: G.settings, run: G.run });
};
G.applySettings = () => {
  G.speed = G.testMode ? 0.01 : G.settings.fast ? 0.55 : 1;
};

G.rank = (id) => G.meta.ranks[id] || 0;
G.has = (id) => G.rank(id) > 0;
G.metaLevel = () => Object.values(G.meta.ranks).reduce((s, n) => s + n, 0);
G.upgrade = (id) => D.meta.upgrades.find((u) => u.id === id);

// ---------- modifiers ----------
const HOOKS = ['passive', 'perfect', 'parry', 'dodge', 'break', 'kill', 'battleStart', 'crit', 'burnTick'];
const addInto = (dst, src, mult = 1) => {
  for (const [k, v] of Object.entries(src || {})) if (typeof v === 'number') dst[k] = (dst[k] || 0) + v * mult;
};
G.boonById = (id) => D.boons.boons.find((b) => b.id === id);
G.recalc = () => {
  const m = { skills: {} };
  HOOKS.forEach((h) => (m[h] = {}));
  for (const up of D.meta.upgrades) {
    const r = G.rank(up.id);
    if (r && up.mods) addInto(m.passive, up.mods, r);
  }
  if (G.has('arm_shard')) addInto(m.battleStart, { burnAll: 1 });
  if (G.run) {
    for (const id of G.run.boons) {
      const b = G.boonById(id);
      if (!b) continue;
      HOOKS.forEach((h) => addInto(m[h], b.mods[h]));
      for (const [sk, mods] of Object.entries(b.mods.skills || {})) {
        m.skills[sk] = m.skills[sk] || {};
        addInto(m.skills[sk], mods);
      }
    }
  }
  const cap = D.config.caps;
  m.passive.dmgPct = Math.min(m.passive.dmgPct || 0, cap.dmgPct);
  m.passive.critPct = Math.min(m.passive.critPct || 0, cap.critPct);
  G.mods = m;
  return m;
};
G.mod = (hook, key) => (G.mods && G.mods[hook] && G.mods[hook][key]) || 0;
G.skillMod = (skill, key) => (G.mods && G.mods.skills[skill] && G.mods.skills[skill][key]) || 0;

// ---------- soldiers ----------
G.classDef = (cls) => D.classes[cls];
G.maxHp = (cls) => Math.round(D.classes[cls].hp * Math.max(0.3, 1 + G.mod('passive', 'maxHpPct')));
G.unlockedClasses = () => Object.entries(D.classes).filter(([, c]) => !c.unlock || G.has(c.unlock)).map(([k]) => k);
G.reserveSlots = () => (G.has('bar_reserve2') ? 2 : 1);

// ---------- run ----------
G.newRun = (chapterId, heat, squad) => {
  const ch = D.chapters.find((c) => c.id === chapterId);
  const items = { grenade: 0, medkit: 1, stim: 0, smoke: 0 };
  if (G.has('arm_grenades')) items.grenade += 2;
  if (G.has('arm_medical')) { items.medkit += 1; items.stim += 1; }
  G.run = {
    chapterId, heat,
    map: G.genMap(ch),
    node: null,
    visited: [],
    squad: squad.map((cls) => ({ cls, frac: 1 })),
    boons: [],
    gold: D.config.startGold + (G.has('base_gold') ? 40 : 0),
    items,
    xp: 0, level: 1,
    rerolls: D.config.draft.baseRerolls + G.rank('cmd_reroll'),
    stats: { fights: 0, perfects: 0, goods: 0, misses: 0, parries: 0, dodges: 0, hits: 0, downs: 0, kills: 0, picks: 0 },
    earned: 0,
    timeMs: 0,
    pending: null,
  };
  G.meta.runs++;
  G.recalc();
  G.saveAll();
};
G.chapter = () => G.run && D.chapters.find((c) => c.id === G.run.chapterId);
G.addItem = (id, n = 1) => { G.run.items[id] = (G.run.items[id] || 0) + n; };
G.itemCount = () => Object.values(G.run.items).reduce((s, n) => s + n, 0);
G.addBoon = (id) => {
  const b = G.boonById(id);
  G.run.boons.push(id);
  G.meta.codex[id] = true;
  if (b && b.grant) for (const [it, n] of Object.entries(b.grant)) G.addItem(it, n);
  G.run.stats.picks++;
  G.recalc();
};
G.healSquad = (pct, alsoDown = true) => {
  for (const s of G.run.squad) {
    if (s.frac <= 0 && !alsoDown) continue;
    s.frac = Math.min(1, Math.max(0, s.frac) + pct);
  }
};
G.damageSquad = (pct) => {
  for (const s of G.run.squad) if (s.frac > 0) s.frac = Math.max(0.05, s.frac - pct);
};
