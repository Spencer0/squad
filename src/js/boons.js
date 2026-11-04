// Boon drafting: which cards are offered, weighted toward the doctrines you already hold.
G.familyUnlocked = (fam) => {
  const f = D.boons.families[fam];
  return f && (!f.unlock || G.has(f.unlock));
};
G.familyCounts = () => {
  const counts = {};
  for (const id of G.run.boons) {
    const b = G.boonById(id);
    if (!b || b.family === 'stat' || b.type === 'duo') continue;
    counts[b.family] = (counts[b.family] || 0) + 1;
  }
  return counts;
};
G.hasClass = (cls) => G.run.squad.some((s) => s.cls === cls);

G.boonEligible = (b, kind) => {
  const held = G.run.boons.includes(b.id);
  if (held && !b.stack) return false;
  if (kind === 'stat') return b.family === 'stat';
  if (b.family === 'stat') return false;
  if (b.class && !G.hasClass(b.class)) return false;
  if (b.type === 'duo') {
    if (!G.has('unl_duo') || kind === 'common') return false;
    const counts = G.familyCounts();
    return b.requires.every((f) => counts[f] > 0);
  }
  if (b.type === 'curse') return (kind === 'curse') || (G.has('unl_curse') && kind === 'normal');
  if (kind === 'curse') return false;
  if (kind === 'relic') return b.family === 'relic';
  if (!G.familyUnlocked(b.family)) return false;
  if (kind === 'common') return b.rarity === 'common';
  if (kind === 'rare') return b.rarity === 'rare' || b.rarity === 'epic';
  return true;
};

G.offerBoons = ({ count = 3, kind = 'normal', guaranteeRare = false } = {}) => {
  const cfg = D.config.draft;
  const counts = G.familyCounts();
  let pool = D.boons.boons.filter((b) => G.boonEligible(b, kind));
  const weight = (b, famPenalty) => {
    let w = b.rarity === 'duo' ? cfg.duoChance * 100 : cfg.rarityWeights[b.rarity] || 10;
    w *= 1 + cfg.familyBias * (counts[b.family] || 0);
    if (famPenalty[b.family]) w *= 0.35;
    return w;
  };
  const out = [];
  const famPenalty = {};
  if (guaranteeRare) {
    const rares = pool.filter((b) => ['rare', 'epic', 'duo'].includes(b.rarity));
    if (rares.length) {
      const b = G.weighted(rares, (x) => weight(x, famPenalty));
      out.push(b);
      famPenalty[b.family] = true;
      pool = pool.filter((x) => x !== b);
    }
  }
  while (out.length < count && pool.length) {
    const b = G.weighted(pool, (x) => weight(x, famPenalty));
    out.push(b);
    famPenalty[b.family] = true;
    pool = pool.filter((x) => x !== b);
  }
  return G.shuffle(out);
};

G.familyOf = (b) => D.boons.families[b.family] || D.boons.families.stat;
G.rarityLabel = (r) => ({ common: 'Common', rare: 'Rare', epic: 'Epic', duo: 'Duo', curse: 'Curse' }[r] || r);
G.typeLabel = (t) => ({ upgrade: 'Upgrade', trigger: 'Trigger', stat: 'Stat', duo: 'Duo', curse: 'Curse' }[t] || t);
G.boonPrice = (b) => {
  const base = D.config.prices[b.rarity] || 80;
  return Math.round(base * (G.has('base_supply') ? 0.85 : 1));
};
