// Persistent meta-progress, settings, the current run (army, hero, build), and stat modifiers.
const SAVE_KEY = 'squad.save.v2';

G.defaultSettings = () => ({ fast: false, sound: true, shake: true, autoCast: false });
G.defaultMeta = () => ({ points: 0, ranks: {}, cleared: {}, heatCleared: {}, codex: {}, runs: 0, clears: 0, heroXp: {}, lastArmy: null, lastHero: 'okafor', seenTips: {} });

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
G.applySettings = () => { G.speed = G.testMode ? 0.01 : G.settings.fast ? 0.55 : 1; };

G.rank = (id) => G.meta.ranks[id] || 0;
G.has = (id) => G.rank(id) > 0;
G.metaLevel = () => Object.values(G.meta.ranks).reduce((s, n) => s + n, 0);

// ---------- army cap ----------
G.clearedCount = () => D.chapters.filter((c) => G.meta.cleared[c.id]).length;
G.armyCap = () => D.config.cap.base + D.config.cap.perClear * G.clearedCount() + G.rank('cmd_cap');

// ---------- veterancy & heroes ----------
const VET = () => D.config.veterancy;
G.vetRank = (xp) => { const t = VET().xp; let r = 0; for (let i = 0; i < t.length; i++) if (xp >= t[i]) r = i; return r; };
G.vetName = (xp) => VET().ranks[G.vetRank(xp)];
G.vetNext = (xp) => { const t = VET().xp; const r = G.vetRank(xp); return r + 1 < t.length ? t[r + 1] : null; };
G.heroLevel = (id) => { const t = D.config.heroes.xpPerLevel; const xp = G.meta.heroXp[id] || 0; let l = 1; for (let i = 0; i < t.length; i++) if (xp >= t[i]) l = i + 1; return Math.min(l, t.length); };
G.heroNext = (id) => { const t = D.config.heroes.xpPerLevel; const l = G.heroLevel(id); return l < t.length ? t[l] : null; };
G.heroUnlocked = (id) => !D.heroes[id].unlock || G.has(D.heroes[id].unlock);
G.unitUnlocked = (type) => !D.units[type].unlock || G.has(D.units[type].unlock);
G.unitTypes = () => Object.keys(D.units).filter(G.unitUnlocked);

// an army entry: { uid, type, frac, xp }   the hero: { id, frac }
G.newSquad = (type) => ({ uid: `${type}-${Math.random().toString(36).slice(2, 7)}`, type, frac: 1, xp: G.has('bar_vet') ? VET().xp[1] : 0 });
G.squadDef = (sq) => D.units[sq.type];
G.squadMaxHp = (sq) => Math.round(D.units[sq.type].hp * D.config.combat.hpScale * (1 + G.vetRank(sq.xp) * VET().bonusPerRank) * Math.max(0.3, 1 + G.mod('passive', 'maxHpPct')));
G.heroMaxHp = (h) => Math.round(D.heroes[h.id].hp * D.config.combat.hpScale * (1 + (G.heroLevel(h.id) - 1) * D.config.heroes.bonusPerLevel) * Math.max(0.3, 1 + G.mod('passive', 'maxHpPct')));
G.armyCost = (army) => army.reduce((s, sq) => s + D.units[sq.type].cost, 0);

// ---------- modifiers ----------
const HOOKS = ['passive', 'volley', 'cast', 'break', 'kill', 'battleStart', 'crit', 'burnTick', 'lowHp'];
const addInto = (dst, src, mult = 1) => { for (const [k, v] of Object.entries(src || {})) if (typeof v === 'number') dst[k] = (dst[k] || 0) + v * mult; };
G.boonById = (id) => D.boons.boons.find((b) => b.id === id);
G.recalc = () => {
  const m = { skills: {} };
  HOOKS.forEach((h) => (m[h] = {}));
  for (const up of D.meta.upgrades) { const r = G.rank(up.id); if (r && up.mods) addInto(m.passive, up.mods, r); }
  if (G.has('arm_shard')) addInto(m.battleStart, { burnAll: 2 });
  const addMods = (mods) => {
    HOOKS.forEach((h) => addInto(m[h], mods[h]));
    for (const [sk, sm] of Object.entries(mods.skills || {})) { m.skills[sk] = m.skills[sk] || {}; addInto(m.skills[sk], sm); }
  };
  if (G.run) {
    for (const id of G.run.boons) { const b = G.boonById(id); if (b) addMods(b.mods); }
    if (G.run.hero) {
      const h = D.heroes[G.run.hero.id];
      const lvl = G.heroLevel(G.run.hero.id);
      for (const [l, perk] of Object.entries(h.perks || {})) if (lvl >= +l) addMods(perk);
    }
  }
  m.passive.dmgPct = Math.min(m.passive.dmgPct || 0, 2.0);
  m.passive.critPct = Math.min(m.passive.critPct || 0, 0.6);
  G.mods = m;
  return m;
};
G.mod = (hook, key) => (G.mods && G.mods[hook] && G.mods[hook][key]) || 0;
G.skillMod = (skill, key) => (G.mods && G.mods.skills[skill] && G.mods.skills[skill][key]) || 0;

// ---------- run ----------
G.newRun = (chapterId, heat, armyTypes, heroId) => {
  const ch = D.chapters.find((c) => c.id === chapterId);
  const items = { grenade: 0, medkit: 1, stim: 0, smoke: 0 };
  if (G.has('arm_grenades')) items.grenade += 2;
  if (G.has('arm_medical')) { items.medkit += 1; items.stim += 1; }
  G.run = {
    chapterId, heat,
    map: G.genMap(ch),
    node: null, visited: [],
    army: armyTypes.map(G.newSquad),
    hero: heroId ? { id: heroId, frac: 1, xpEarned: 0 } : null,
    boons: [],
    gold: D.config.startGold + (G.has('base_gold') ? 40 : 0),
    items,
    rerolls: D.config.draft.baseRerolls + G.rank('cmd_reroll'),
    stats: { fights: 0, kills: 0, wipes: 0, casts: 0, breaks: 0, picks: 0, rankUps: 0 },
    earned: 0, timeMs: 0,
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
G.allSquads = () => [...G.run.army, ...(G.run.hero ? [G.run.hero] : [])];
G.healArmy = (pct) => { for (const s of G.allSquads()) s.frac = Math.min(1, Math.max(0, s.frac) + pct); };
G.damageArmy = (pct) => { for (const s of G.allSquads()) if (s.frac > 0) s.frac = Math.max(0.05, s.frac - pct); };
G.giveXp = (sq, xp) => {
  const before = G.vetRank(sq.xp);
  sq.xp = (sq.xp || 0) + xp;
  const after = G.vetRank(sq.xp);
  if (after > before) G.run.stats.rankUps++;
  return after > before;
};
G.giveHeroXp = (xp) => {
  if (!G.run || !G.run.hero) return false;
  const id = G.run.hero.id;
  const before = G.heroLevel(id);
  G.meta.heroXp[id] = (G.meta.heroXp[id] || 0) + Math.round(xp);
  G.run.hero.xpEarned = (G.run.hero.xpEarned || 0) + Math.round(xp);
  const up = G.heroLevel(id) > before;
  if (up) G.recalc();
  return up;
};
