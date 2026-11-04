// Menus and between-fight screens.
G.show = (name) => {
  for (const s of ['title', 'base', 'map', 'battle']) G.$(`#scr-${s}`).hidden = s !== name;
  G.screen = name;
  if (name === 'battle' && G._resizeStage) requestAnimationFrame(G._resizeStage);
};

// ---------- modal helpers ----------
G.closeModal = () => { G.$('#modal').hidden = true; G.$('#modal-card').innerHTML = ''; };
G.openModal = (build, opts = {}) => {
  const m = G.$('#modal');
  const card = G.$('#modal-card');
  card.className = `modal-card ${opts.cls || ''}`;
  card.innerHTML = '';
  build(card);
  m.hidden = false;
  card.scrollTop = 0;
};
// opens a modal whose builder calls done(value); resolves with that value
G.ask = (build, opts) => new Promise((resolve) => {
  G.openModal((card) => build(card, (v) => { G.closeModal(); resolve(v); }), opts);
  if (G.testMode && opts && opts.auto) setTimeout(() => opts.auto((v) => { G.closeModal(); resolve(v); }), 1);
});

// ---------- dialog (radio chatter) ----------
const SPEAKERS = { radio: 'Hearth (radio)', rifleman: 'Rifleman', mg: 'Machine Gunner', medic: 'Medic', sniper: 'Sniper', sapper: 'Sapper', veteran: 'Sgt. Okafor' };
G.dialog = async (lines) => {
  if (!lines || !lines.length || G.testMode) return;
  const box = G.$('#dialog');
  const pc = G.$('#dialog-portrait');
  const c = pc.getContext('2d');
  for (const line of lines) {
    G.$('#dialog-name').textContent = SPEAKERS[line.who] || line.who;
    G.$('#dialog-text').textContent = line.text;
    c.clearRect(0, 0, 160, 160);
    if (line.who === 'radio') {
      c.fillStyle = '#3a3a2a'; c.fillRect(0, 0, 160, 160);
      c.fillStyle = '#5d6b30'; c.fillRect(30, 50, 100, 80); c.strokeStyle = '#1b1a14'; c.lineWidth = 6; c.strokeRect(30, 50, 100, 80);
      c.fillStyle = '#1b1a14'; for (let i = 0; i < 4; i++) c.fillRect(44, 64 + i * 14, 40, 6);
      c.beginPath(); c.arc(108, 92, 14, 0, 7); c.fill();
      c.strokeStyle = '#c9c3a8'; c.lineWidth = 4; c.beginPath(); c.moveTo(118, 50); c.lineTo(132, 12); c.stroke();
    } else {
      const img = new Image();
      img.src = G.art.portrait({ side: 'ally', cls: line.who, art: 'soldier' }, 160);
      await new Promise((r) => { img.onload = r; img.onerror = r; });
      c.drawImage(img, 0, 0, 160, 160);
    }
    box.hidden = false;
    await new Promise((resolve) => {
      const go = (e) => { if (e.type === 'keydown' && !['Space', 'Enter'].includes(e.code)) return; e.preventDefault(); box.removeEventListener('pointerdown', go); window.removeEventListener('keydown', go); G.sfx('click'); resolve(); };
      setTimeout(() => { box.addEventListener('pointerdown', go); window.addEventListener('keydown', go); }, 250);
    });
  }
  box.hidden = true;
};

// ---------- title ----------
G.showTitle = () => {
  G.show('title');
  const acts = G.$('#title-actions');
  acts.innerHTML = '';
  const start = G.el('button', { class: 'btn primary', type: 'button', id: 'btn-start' }, G.run ? 'Continue operation' : G.meta.runs ? 'Report to base' : 'Start');
  start.addEventListener('click', () => { G.audio.unlock(); G.sfx('click'); if (G.run) G.resumeRun(); else G.showBase(); });
  acts.append(start);
  if (G.run) acts.append(G.el('button', { class: 'btn ghost', type: 'button', onclick: () => { G.audio.unlock(); G.showBase(); } }, 'Base'));
  acts.append(G.el('button', { class: 'btn ghost', type: 'button', onclick: () => G.showHowTo() }, 'How to play'));
  acts.append(G.el('button', { class: 'btn ghost', type: 'button', onclick: () => G.showSettings() }, 'Settings'));
  // animated backdrop
  const cv = G.$('#title-canvas');
  const draw = () => {
    if (G.screen !== 'title') return;
    const r = cv.getBoundingClientRect();
    const dpr = Math.min(2, devicePixelRatio || 1);
    if (cv.width !== Math.floor(r.width * dpr)) { cv.width = Math.floor(r.width * dpr); cv.height = Math.floor(r.height * dpr); }
    const c = cv.getContext('2d');
    const s = Math.max(cv.width / 1000, cv.height / 620);
    c.setTransform(s, 0, 0, s, (cv.width - 1000 * s) / 2, (cv.height - 620 * s) / 2);
    c.drawImage(G.art.bg('village'), 0, 0);
    const t = G.now() / 1000;
    G.art.drawUnit(c, { side: 'ally', cls: 'mg' }, 170, 540, 1, { t });
    G.art.drawUnit(c, { side: 'ally', cls: 'rifleman' }, 300, 520, 1, { t: t + 1 });
    G.art.drawUnit(c, { side: 'ally', cls: 'medic' }, 80, 560, 1, { t: t + 2 });
    c.save(); c.shadowColor = '#6dffb4'; c.shadowBlur = 20;
    G.art.drawUnit(c, { side: 'enemy', art: 'relictank' }, 820, 560, 0.95, { t });
    c.restore();
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.fillStyle = 'rgba(10,12,8,0.62)'; c.fillRect(0, 0, cv.width, cv.height);
    requestAnimationFrame(draw);
  };
  requestAnimationFrame(draw);
};

G.showHowTo = () => G.openModal((card) => {
  card.append(
    G.el('h2', { text: 'How to play' }),
    G.el('div', { class: 'howto' },
      ...[
        ['Goal', 'Each chapter is one operation: pick a route across the map and beat the boss at the top. If the whole squad goes down, the chapter restarts.'],
        ['Your turn', 'Fire (builds 1 AP), use the soldier\'s Ability (spends AP), use an Item, Take Cover (blocks damage until your next turn, +1 AP), or Swap in a reserve.'],
        ['Timing', 'Every action has a timing input. Ring: tap as the gold ring meets the white ring. Beats: tap once per ring. Hold: hold, then release in the gold zone. Perfect = +50%, Miss = -50%.'],
        ['Defense', 'When an enemy attacks, a red ring closes on the target. Hit the Dirt has a wide window and takes no damage. Counter is a tight window: no damage, +1 AP, and parrying every hit of an attack fires a counter-shot. Watch for feints.'],
        ['Break', 'Damage fills the gold Break bar under each enemy. When it is full the enemy loses its next turn and takes 50% more damage. Perfect hits break heavy armor twice as fast.'],
        ['Boons', 'After fights you pick 1 of 3 boons. Doctrines you already hold show up more often. Your build is wiped when the chapter ends, win or lose.'],
        ['Progress', 'Every fight earns meta-points. Spend them at base on the Command tree, recruits, armory gear and unlocks. Dying still banks 25% of what the run earned.'],
        ['Controls', 'Tap or click. Keyboard: Space = tap or Hit the Dirt, X = Counter, 1-5 = commands, arrow keys = switch target.'],
      ].map(([a, b]) => G.el('div', {}, G.el('b', { text: a }), G.el('p', { text: b })))
    ),
    G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn primary', type: 'button', onclick: G.closeModal }, 'Got it'))
  );
});

G.showSettings = () => G.openModal((card) => {
  const st = G.settings;
  const save = () => { G.applySettings(); G.saveAll(); };
  const check = (id, label, desc, key) => {
    const inp = G.el('input', { type: 'checkbox', id });
    inp.checked = !!st[key];
    inp.addEventListener('change', () => { st[key] = inp.checked; save(); });
    return G.el('div', { class: 'setting' }, G.el('label', { for: id, text: label }), inp, G.el('p', { text: desc }));
  };
  const sel = G.el('select', { id: 'set-window' }, ...['normal', 'wide', 'widest'].map((v) => G.el('option', { value: v, text: v[0].toUpperCase() + v.slice(1) })));
  sel.value = st.window;
  sel.addEventListener('change', () => { st.window = sel.value; save(); });
  const confirmBox = G.el('div', { class: 'modal-actions', hidden: true },
    G.el('span', { class: 'muted', text: 'Erase all progress and settings?' }),
    G.el('button', { class: 'btn small primary', type: 'button', onclick: () => { G.storage.del('squad.save.v1'); location.reload(); } }, 'Erase'),
    G.el('button', { class: 'btn small ghost', type: 'button', onclick: () => (confirmBox.hidden = true) }, 'Keep'));
  card.append(
    G.el('h2', { text: 'Settings' }),
    G.el('h3', { text: 'Accessibility' }),
    G.el('div', { class: 'settings-grid' },
      G.el('div', { class: 'setting' }, G.el('label', { for: 'set-window', text: 'Timing windows' }), sel, G.el('p', { text: 'Wider windows make Perfect, Good, Hit the Dirt and Counter easier to land.' })),
      check('set-autooff', 'Auto-timing on offense', 'Every attack lands as Good. Perfect bonuses need manual timing.', 'autoOffense'),
      check('set-autodef', 'Auto Hit the Dirt on defense', 'Every enemy attack is dodged automatically. Counters and their AP need manual timing.', 'autoDefense'),
      check('set-fast', 'Fast animations', 'Shortens pauses between actions. Timing rings keep their speed.', 'fast'),
      check('set-shake', 'Screen shake', '', 'shake'),
      check('set-sound', 'Sound', '', 'sound')
    ),
    G.el('h3', { text: 'Save' }),
    G.el('p', { class: 'muted', text: 'Progress saves in this browser automatically after every map step.' }),
    confirmBox,
    G.el('div', { class: 'modal-actions' },
      G.el('button', { class: 'btn ghost small', type: 'button', onclick: () => (confirmBox.hidden = false) }, 'Erase save'),
      G.el('button', { class: 'btn primary', type: 'button', onclick: () => { G.closeModal(); if (G.screen === 'base') G.showBase(); } }, 'Done'))
  );
});

// ---------- base ----------
G.showBase = () => {
  G.show('base');
  G.$('#base-stats').innerHTML = '';
  G.$('#base-stats').append(
    G.el('span', { class: 'chip' }, 'Meta-points ', G.el('b', { text: String(G.meta.points) })),
    G.el('span', { class: 'chip' }, 'Meta-level ', G.el('b', { text: String(G.metaLevel()) }))
  );
  G.$('#base-settings').onclick = () => G.showSettings();
  const hs = G.$('#base-hotspots');
  hs.innerHTML = '';
  const actions = { radio: G.showRadio, command: () => G.showTrack(['command'], 'Command Post'), barracks: () => G.showTrack(['barracks'], 'Barracks'), armory: () => G.showTrack(['armory', 'base'], 'Quartermaster'), crate: () => G.showTrack(['unlocks'], 'Relic Crate') };
  const btns = {};
  for (const [k, st] of Object.entries(G.art.STATIONS)) {
    const b = G.el('button', { class: `hotspot ${k === 'radio' ? 'go' : ''}`, type: 'button', id: `station-${k}` }, st.label, G.el('small', { text: st.sub }));
    b.addEventListener('click', () => { G.sfx('click'); actions[k](); });
    hs.append(b);
    btns[k] = b;
  }
  const cv = G.$('#base-canvas');
  const scene = G.$('#base-scene');
  const draw = () => {
    if (G.screen !== 'base') return;
    const r = scene.getBoundingClientRect();
    const dpr = Math.min(2, devicePixelRatio || 1);
    if (cv.width !== Math.floor(r.width * dpr) || cv.height !== Math.floor(r.height * dpr)) { cv.width = Math.floor(r.width * dpr); cv.height = Math.floor(r.height * dpr); }
    const s = Math.max(r.width / G.art.BASE_W, r.height / G.art.BASE_H);
    const ox = (r.width - G.art.BASE_W * s) / 2, oy = (r.height - G.art.BASE_H * s) / 2;
    const c = cv.getContext('2d');
    c.setTransform(s * dpr, 0, 0, s * dpr, ox * dpr, oy * dpr);
    G.art.baseScene(c, G.now() / 1000);
    for (const [k, st] of Object.entries(G.art.STATIONS)) {
      const x = G.clamp(st.x * s + ox, 56, r.width - 56), y = G.clamp(st.y * s + oy, 44, r.height - 8);
      btns[k].style.left = `${x}px`; btns[k].style.top = `${y}px`;
    }
    requestAnimationFrame(draw);
  };
  requestAnimationFrame(draw);
  if (!G.meta.seenTips.base) {
    G.meta.seenTips.base = true;
    G.saveAll();
    G.dialog([
      { who: 'radio', text: 'Welcome to the forward base, Able Squad. This farm is home between operations.' },
      { who: 'radio', text: 'Spend meta-points at the stations. When you are ready, head to the Radio Tent and pick an operation.' },
    ]);
  }
};

G.showTrack = (tracks, title) => G.openModal((card) => {
  const render = () => {
    card.innerHTML = '';
    card.append(G.el('h2', { text: title }), G.el('p', { class: 'muted' }, 'Meta-points: ', G.el('b', { text: String(G.meta.points) })));
    for (const tr of tracks) {
      const t = D.meta.tracks[tr];
      card.append(G.el('h3', { text: `${t.name} · ${t.why}` }));
      const rows = G.el('div', { class: 'rows' });
      for (const up of D.meta.upgrades.filter((u) => u.track === tr)) {
        const r = G.rank(up.id);
        const max = up.costs.length;
        const cost = up.costs[r];
        const btn = G.el('button', { class: 'btn small', type: 'button', disabled: r >= max || G.meta.points < cost ? true : undefined }, r >= max ? 'Owned' : `Buy ${cost}`);
        btn.addEventListener('click', () => {
          if (r >= max || G.meta.points < cost) return;
          G.meta.points -= cost; G.meta.ranks[up.id] = r + 1; G.sfx('good'); G.saveAll(); render();
        });
        rows.append(G.el('div', { class: 'row' },
          G.el('h4', {}, up.name, max > 1 ? G.el('span', { class: 'pips' }, ...Array.from({ length: max }, (_, i) => G.el('i', { class: i < r ? 'on' : '' }))) : null),
          btn, G.el('p', { text: up.text })));
      }
      card.append(rows);
      if (tr === 'command') {
        const spent = D.meta.upgrades.filter((u) => u.track === 'command').reduce((s, u) => s + u.costs.slice(0, G.rank(u.id)).reduce((a, b) => a + b, 0), 0);
        if (spent) card.append(G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn ghost small', type: 'button', onclick: () => {
          D.meta.upgrades.filter((u) => u.track === 'command').forEach((u) => delete G.meta.ranks[u.id]);
          G.meta.points += spent; G.saveAll(); G.toast(`Refunded ${spent} meta-points`); render();
        } }, `Respec (refund ${spent})`)));
      }
    }
    if (tracks.includes('unlocks')) {
      const seen = Object.keys(G.meta.codex).length;
      card.append(G.el('h3', { text: 'Codex' }), G.el('p', { class: 'muted', text: `Boons seen: ${seen} of ${D.boons.boons.length}.` }));
    }
    card.append(G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn primary', type: 'button', onclick: () => { G.closeModal(); G.showBase(); } }, 'Close')));
  };
  render();
});

// ---------- mission select ----------
G.chapterUnlocked = (ch) => !ch.unlockAfter || G.meta.cleared[ch.unlockAfter];
G.showRadio = () => G.openModal((card) => {
  card.append(G.el('h2', { text: 'Radio Tent' }), G.el('p', { class: 'muted', text: 'Pick an operation. Cleared operations can be replayed at higher Heat for more points.' }));
  const list = G.el('div', { class: 'chapters' });
  for (const ch of D.chapters) {
    const unlocked = G.chapterUnlocked(ch);
    const cleared = G.meta.cleared[ch.id];
    const maxHeat = cleared ? Math.min(3, (G.meta.heatCleared[ch.id] ?? -1) + 1) : 0;
    let heat = 0;
    const heatRow = G.el('div', { class: 'heat' });
    if (cleared) {
      heatRow.append(G.el('span', { text: 'Heat' }));
      for (let h = 0; h <= maxHeat; h++) {
        const b = G.el('button', { type: 'button', 'aria-pressed': h === 0 ? 'true' : 'false', text: String(h) });
        b.addEventListener('click', () => { heat = h; G.$$('button', heatRow).forEach((x) => x.setAttribute('aria-pressed', x === b ? 'true' : 'false')); });
        heatRow.append(b);
      }
      heatRow.append(G.el('span', { class: 'muted', text: `+${Math.round(D.config.rewards.heatEnemyPct * 100)}% enemy HP and damage per level, +${Math.round(D.config.rewards.heatPointsPct * 100)}% points` }));
    }
    const go = G.el('button', { class: 'btn primary', type: 'button', disabled: !unlocked || undefined }, unlocked ? 'Deploy' : 'Locked');
    go.addEventListener('click', () => { G.closeModal(); G.showSquadSelect(ch, heat); });
    list.append(G.el('div', { class: `chapter ${unlocked ? '' : 'locked'}` },
      G.el('h4', { text: ch.name }),
      go,
      G.el('div', { class: 'meta-line', text: `${ch.place} · Recommended meta-level ${ch.recLevel}${cleared ? ' · Cleared' : ''}` }),
      G.el('p', { text: unlocked ? ch.blurb : `Clear ${D.chapters.find((c) => c.id === ch.unlockAfter).name} to unlock.` }),
      heatRow));
  }
  list.append(G.el('div', { class: 'chapter locked' }, G.el('h4', { text: 'Operation Iron Tide' }), G.el('div', { class: 'meta-line', text: 'Coastal bunker line' }), G.el('p', { text: 'Coming in a later build.' })));
  card.append(list, G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn ghost', type: 'button', onclick: G.closeModal }, 'Close')));
});

G.showSquadSelect = (ch, heat) => G.openModal((card) => {
  const classes = G.unlockedClasses();
  const resSlots = G.reserveSlots();
  let picked = (G.meta.lastSquad || ['rifleman', 'mg', 'medic']).filter((c) => classes.includes(c));
  if (picked.length < 3) picked = ['rifleman', 'mg', 'medic'].filter((c) => classes.includes(c));
  picked = picked.slice(0, 3 + resSlots);
  const render = () => {
    card.innerHTML = '';
    card.append(G.el('h2', { text: `Squad for ${ch.name}` }), G.el('p', { class: 'muted', text: `Pick 3 active soldiers and up to ${resSlots} in reserve. The first three you pick deploy; the rest wait in reserve and can swap in (costs a turn).` }));
    const grid = G.el('div', { class: 'picker' });
    for (const cls of classes) {
      const d = D.classes[cls];
      const idx = picked.indexOf(cls);
      const b = G.el('button', { class: `pick ${idx >= 0 && idx < 3 ? 'on' : ''} ${idx >= 3 ? 'res' : ''}`, type: 'button' },
        G.el('img', { src: G.art.portrait({ side: 'ally', cls, art: 'soldier' }, 96), alt: '' }),
        G.el('b', { text: d.name }), G.el('span', { text: d.role }),
        G.el('span', { text: `${d.ability.name} · ${d.ability.ap} AP` }),
        G.el('em', { text: idx < 0 ? '' : idx < 3 ? `Active ${idx + 1}` : 'Reserve' }));
      b.addEventListener('click', () => {
        G.sfx('click');
        if (idx >= 0) picked.splice(idx, 1);
        else if (picked.length < 3 + resSlots) picked.push(cls);
        else G.toast('Squad is full. Tap a soldier to remove them.');
        render();
      });
      grid.append(b);
    }
    const locked = Object.entries(D.classes).filter(([k]) => !classes.includes(k));
    card.append(grid);
    if (locked.length) card.append(G.el('p', { class: 'muted', text: `Recruit more at the Barracks: ${locked.map(([, d]) => d.name).join(', ')}.` }));
    const go = G.el('button', { class: 'btn primary', type: 'button', disabled: picked.length < 3 || undefined }, 'Deploy');
    go.addEventListener('click', () => { G.closeModal(); G.meta.lastSquad = picked.slice(); G.startRun(ch.id, heat, picked.slice()); });
    card.append(G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn ghost', type: 'button', onclick: G.closeModal }, 'Back'), go));
  };
  render();
});

// ---------- boon cards ----------
G.cardEl = (b, opts = {}) => {
  const fam = G.familyOf(b);
  const el = G.el('button', { class: `card ${opts.cant ? 'cant' : ''}`, type: 'button', style: { '--fam': fam.color } },
    G.el('div', { class: 'card-top', html: G.art.icon(fam.icon) },
    ),
    G.el('div', { class: 'card-body' },
      G.el('div', { class: 'card-type', text: `${b.type === 'duo' ? b.requires.map((f) => D.boons.families[f].name).join(' + ') : fam.name} · ${G.typeLabel(b.type)}` }),
      G.el('div', { class: 'card-name', text: b.name }),
      G.el('div', { class: 'card-text', text: b.text }),
      opts.price ? G.el('div', { class: 'card-price', text: `${opts.price} gold` }) : null));
  const top = el.querySelector('.card-top');
  top.append(G.el('span', { class: 'card-fam', text: fam.name }), G.el('span', { class: `card-rar ${b.rarity}`, text: G.rarityLabel(b.rarity) }));
  return el;
};

// draft: pick 1 of 3. kind: normal|stat|common|relic|curse ; resolves when a pick or skip is made
G.draft = (opts = {}) => {
  const kind = opts.kind || 'normal';
  let offer = G.offerBoons({ kind, guaranteeRare: opts.guaranteeRare });
  if (!offer.length) return Promise.resolve(null);
  offer.forEach((b) => (G.meta.codex[b.id] = G.meta.codex[b.id] || false));
  return G.ask((card, done) => {
    const render = () => {
      card.innerHTML = '';
      card.append(G.el('div', { class: 'draft-head' },
        G.el('span', { class: 'eyebrow', text: opts.eyebrow || 'Boon draft · pick 1 of 3' }),
        G.el('h2', { text: opts.title || 'Choose a boon' })));
      const cards = G.el('div', { class: 'cards' });
      offer.forEach((b) => {
        const el = G.cardEl(b);
        el.addEventListener('click', () => { G.sfx('card'); G.addBoon(b.id); done(b); });
        cards.append(el);
      });
      card.append(cards);
      const acts = G.el('div', { class: 'draft-actions' });
      if (kind !== 'stat') {
        const rr = G.el('button', { class: 'btn ghost', type: 'button', disabled: G.run.rerolls <= 0 || undefined }, `Reroll (${G.run.rerolls} left)`);
        rr.addEventListener('click', () => { if (G.run.rerolls <= 0) return; G.run.rerolls--; G.sfx('card'); offer = G.offerBoons({ kind, guaranteeRare: opts.guaranteeRare }); render(); });
        acts.append(rr);
      }
      if (!opts.noSkip) acts.append(G.el('button', { class: 'btn ghost', type: 'button', onclick: () => { G.run.gold += D.config.rewards.skipGold; done(null); } }, `Skip (+${D.config.rewards.skipGold} gold)`));
      acts.append(G.el('button', { class: 'btn ghost', type: 'button', onclick: () => G.showBuild() }, `Build (${G.run.boons.length})`));
      card.append(acts);
    };
    render();
    G._draftBack = render;
  }, { cls: 'draft-wrap', auto: (done) => { const b = offer[0]; G.addBoon(b.id); done(b); } });
};

G.showBuild = () => {
  const prev = G.$('#modal').hidden ? null : G._draftBack;
  G.openModal((card) => {
    card.append(G.el('h2', { text: 'Current build' }));
    const counts = G.familyCounts();
    card.append(G.el('p', { class: 'muted', text: Object.keys(counts).length ? Object.entries(counts).map(([f, n]) => `${D.boons.families[f].name} ${n}`).join(' · ') : 'No doctrine boons yet.' }));
    const rows = G.el('div', { class: 'rows' });
    const tally = {};
    G.run.boons.forEach((id) => (tally[id] = (tally[id] || 0) + 1));
    Object.entries(tally).forEach(([id, n]) => {
      const b = G.boonById(id);
      const fam = G.familyOf(b);
      rows.append(G.el('div', { class: 'row' }, G.el('h4', {}, G.el('span', { class: 'fam-dot', style: { background: fam.color } }), b.name + (n > 1 ? ` x${n}` : ''), G.el('span', { class: 'tag', text: `${G.rarityLabel(b.rarity)} ${G.typeLabel(b.type)}` })), G.el('p', { text: b.text })));
    });
    if (!G.run.boons.length) rows.append(G.el('p', { class: 'muted', text: 'Win fights to draft boons.' }));
    card.append(rows);
    const items = Object.entries(G.run.items).filter(([, n]) => n > 0).map(([id, n]) => `${D.items[id].name} x${n}`).join(', ');
    card.append(G.el('h3', { text: 'Items' }), G.el('p', { class: 'muted', text: items || 'None' }));
    card.append(G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn primary', type: 'button', onclick: () => { if (prev) { G.openModal(() => {}, { cls: 'draft-wrap' }); prev(); } else G.closeModal(); } }, 'Back')));
  });
};

// ---------- supply drop ----------
G.shop = () => G.ask((card, done) => {
  const nBoons = 3 + (G.has('base_supply') ? 1 : 0);
  const stock = G.offerBoons({ count: nBoons }).map((b) => ({ b, price: G.boonPrice(b), sold: false }));
  const itemStock = G.shuffle(Object.keys(D.items)).slice(0, 3).map((id) => ({ id, price: Math.round(D.items[id].price * (G.has('base_supply') ? 0.85 : 1)), sold: false }));
  let healed = false;
  const render = () => {
    card.innerHTML = '';
    card.append(G.el('div', { class: 'draft-head' }, G.el('span', { class: 'eyebrow', text: 'Supply drop' }), G.el('h2', { text: 'Requisition' }), G.el('p', { class: 'muted' }, 'Gold: ', G.el('b', { text: String(G.run.gold) }))));
    const cards = G.el('div', { class: 'cards' });
    stock.forEach((s) => {
      if (s.sold) return;
      const el = G.cardEl(s.b, { price: s.price, cant: G.run.gold < s.price });
      el.addEventListener('click', () => {
        if (G.run.gold < s.price) { G.toast('Not enough gold'); return; }
        G.run.gold -= s.price; s.sold = true; G.addBoon(s.b.id); G.sfx('card'); render();
      });
      cards.append(el);
    });
    card.append(cards);
    const rows = G.el('div', { class: 'rows' });
    itemStock.forEach((s) => {
      if (s.sold) return;
      const it = D.items[s.id];
      const b = G.el('button', { class: 'btn small', type: 'button', disabled: G.run.gold < s.price || undefined }, `Buy ${s.price}`);
      b.addEventListener('click', () => { if (G.run.gold < s.price) return; G.run.gold -= s.price; s.sold = true; G.addItem(s.id); G.sfx('good'); render(); });
      rows.append(G.el('div', { class: 'row' }, G.el('h4', { text: it.name }), b, G.el('p', { text: it.text })));
    });
    const hc = D.config.prices.heal;
    const hb = G.el('button', { class: 'btn small', type: 'button', disabled: healed || G.run.gold < hc || undefined }, healed ? 'Done' : `Buy ${hc}`);
    hb.addEventListener('click', () => { if (healed || G.run.gold < hc) return; G.run.gold -= hc; healed = true; G.healSquad(D.config.prices.healPct); G.sfx('heal'); render(); });
    rows.append(G.el('div', { class: 'row' }, G.el('h4', { text: 'Field surgeon' }), hb, G.el('p', { text: `Heal every soldier ${G.pct(D.config.prices.healPct)}, including downed ones.` })));
    card.append(G.el('div', { style: { width: '100%' } }, rows));
    card.append(G.el('div', { class: 'draft-actions' }, G.el('button', { class: 'btn ghost', type: 'button', onclick: () => G.showBuild() }, 'Build'), G.el('button', { class: 'btn primary', type: 'button', onclick: () => done(true) }, 'Move out')));
  };
  render();
  G._draftBack = render;
}, { cls: 'draft-wrap', auto: (done) => done(true) });

// ---------- field camp ----------
G.camp = () => {
  const heal = (G.has('base_camp') ? 0.5 : D.config.camp.healPct) * Math.max(0.2, 1 + G.mod('passive', 'campHealPct'));
  return G.ask((card, done) => {
    card.append(
      G.el('span', { class: 'eyebrow', text: 'Field camp' }),
      G.el('h2', { text: 'Dig in for the night' }),
      G.el('p', { text: 'A quiet hollow behind a hedgerow. You have time for one thing before dawn.' }),
      G.el('div', { class: 'rows' },
        G.el('div', { class: 'row' }, G.el('h4', { text: 'Rest' }), G.el('button', { class: 'btn primary small', type: 'button', onclick: () => done('rest') }, 'Rest'), G.el('p', { text: `Every soldier heals ${G.pct(heal)} of max HP. Downed soldiers get back up.` })),
        G.el('div', { class: 'row' }, G.el('h4', { text: 'Drill' }), G.el('button', { class: 'btn small', type: 'button', onclick: () => done('drill') }, 'Drill'), G.el('p', { text: 'Draft a stat card instead of healing.' }))));
  }, { cls: 'paper', auto: (done) => done('rest') }).then(async (c) => {
    if (c === 'rest') { G.healSquad(heal); G.sfx('heal'); G.toast(`Squad healed ${G.pct(heal)}`); }
    else await G.draft({ kind: 'stat', title: 'Drill', eyebrow: 'Stat card · pick 1', noSkip: true });
  });
};

// ---------- cache ----------
G.cache = () => G.ask((card, done) => {
  const relic = G.has('unl_relic');
  card.append(
    G.el('span', { class: 'eyebrow', text: 'Cache' }),
    G.el('h2', { text: 'A buried supply cache' }),
    G.el('p', { text: 'Someone stashed this in a hurry. Take the good stuff or strip it for parts.' }),
    G.el('div', { class: 'rows' },
      G.el('div', { class: 'row' }, G.el('h4', { text: 'Open the crate' }), G.el('button', { class: 'btn primary small', type: 'button', onclick: () => done('draft') }, 'Open'), G.el('p', { text: 'A boon draft with a guaranteed Rare.' })),
      relic ? G.el('div', { class: 'row' }, G.el('h4', { text: 'Take the relic' }), G.el('button', { class: 'btn small', type: 'button', onclick: () => done('relic') }, 'Take'), G.el('p', { text: 'A random Captured Relic boon.' })) : null,
      G.el('div', { class: 'row' }, G.el('h4', { text: 'Salvage' }), G.el('button', { class: 'btn small', type: 'button', onclick: () => done('salvage') }, 'Salvage'), G.el('p', { text: '+40 gold and a Grenade.' }))));
}, { cls: 'paper', auto: (done) => done('draft') }).then(async (c) => {
  if (c === 'draft') await G.draft({ guaranteeRare: true, eyebrow: 'Cache · guaranteed Rare' });
  else if (c === 'relic') { const b = G.pick(D.boons.boons.filter((x) => G.boonEligible(x, 'relic'))); if (b) { G.addBoon(b.id); G.toast(`Gained ${b.name}`); } }
  else { G.run.gold += 40; G.addItem('grenade'); G.toast('+40 gold, +1 Grenade'); }
});

// ---------- intel event ----------
G.intel = async () => {
  const pool = D.events.filter((e) => !G.run.seenEvents || !G.run.seenEvents.includes(e.id));
  const ev = G.pick(pool.length ? pool : D.events);
  G.run.seenEvents = [...(G.run.seenEvents || []), ev.id];
  const choice = await G.ask((card, done) => {
    card.append(G.el('span', { class: 'eyebrow', text: 'Intel' }), G.el('h2', { text: ev.title }), G.el('p', { class: 'dialog-text', text: ev.text }));
    const rows = G.el('div', { class: 'rows' });
    ev.choices.forEach((c) => {
      const cant = c.cost && G.run.gold < c.cost;
      rows.append(G.el('button', { class: 'btn', type: 'button', disabled: cant || undefined, onclick: () => done(c) }, c.label));
    });
    card.append(rows);
  }, { cls: 'paper', auto: (done) => done(ev.choices[ev.choices.length - 1]) });
  if (choice.cost) G.run.gold -= choice.cost;
  const out = choice.chance !== undefined ? (Math.random() < choice.chance ? choice.success : choice.fail) : choice.outcome;
  const notes = [];
  if (out.gold) { G.run.gold = Math.max(0, G.run.gold + out.gold); }
  if (out.healPct) G.healSquad(out.healPct, false);
  if (out.damagePct) G.damageSquad(out.damagePct);
  if (out.rerolls) G.run.rerolls += out.rerolls;
  if (out.points) G.run.earned += out.points;
  if (out.item) G.addItem(out.item);
  if (out.item2) G.addItem(out.item2);
  let fight = out.fight || null;
  await G.ask((card, done) => {
    card.append(G.el('h2', { text: ev.title }), G.el('p', { class: 'dialog-text', text: out.say }), G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn primary', type: 'button', onclick: () => done(true) }, fight ? 'Fight' : 'Continue')));
  }, { cls: 'paper', auto: (done) => done(true) });
  return { fight, boon: out.boon };
};

// ---------- results ----------
G.showResults = (r) => G.ask((card, done) => {
  const ch = D.chapters.find((c) => c.id === r.chapterId);
  card.append(
    G.el('span', { class: 'eyebrow', text: r.win ? 'Operation complete' : 'Squad lost' }),
    G.el('h2', { text: r.win ? `${ch.name} cleared` : `${ch.name} failed` }),
    G.el('p', { text: r.win ? 'The build is wiped. Your meta-points are banked at base.' : `The chapter resets. You still bank ${G.pct(D.config.rewards.deathBankPct)} of the points this run earned.` }));
  const grid = G.el('div', { class: 'results-grid' });
  r.lines.forEach(([a, b]) => grid.append(G.el('span', { text: a }), G.el('span', { text: b })));
  grid.append(G.el('span', { class: 'total', text: 'Meta-points banked' }), G.el('span', { class: 'total', text: `+${r.total}` }));
  card.append(grid);
  card.append(G.el('h3', { text: 'Run stats' }), G.el('p', { class: 'muted', text: `${r.stats.fights} fights · ${r.stats.perfects} Perfects · ${r.stats.parries} counters · ${r.stats.dodges} dodges · ${r.stats.downs} soldiers downed · ${G.fmtTime(r.timeMs)}` }));
  const acts = G.el('div', { class: 'modal-actions' });
  if (!r.win) acts.append(G.el('button', { class: 'btn', type: 'button', onclick: () => done('retry') }, 'Redeploy'));
  acts.append(G.el('button', { class: 'btn primary', type: 'button', onclick: () => done('base') }, 'Return to base'));
  card.append(acts);
}, { cls: 'paper', auto: (done) => done('base') });
