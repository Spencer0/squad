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
const SPEAKERS = { radio: 'Hearth (radio)' };
G.dialog = async (lines) => {
  if (!lines || !lines.length || G.testMode) return;
  const box = G.$('#dialog');
  const pc = G.$('#dialog-portrait');
  const c = pc.getContext('2d');
  for (const line of lines) {
    const heroId = (G.run && G.run.hero && G.run.hero.id) || G.meta.lastHero || 'okafor';
    const hero = D.heroes[heroId];
    G.$('#dialog-name').textContent = line.who === 'hero' ? hero.name : SPEAKERS[line.who] || line.who;
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
      img.src = G.art.figPortrait(line.who === 'hero' ? hero.figure : line.who, 160);
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
    c.drawImage(G.art.backdrop('eu_village'), 0, 0, 1000, 620);
    const t = G.now() / 1000;
    [[150, 540, 'mg'], [250, 515, 'rifleman'], [300, 565, 'rifleman'], [360, 530, 'rifleman'], [70, 560, 'medic'], [420, 575, 'veteran']].forEach(([x, y, f], i) =>
      G.art.drawFigure(c, f, 'idle', x, y + Math.sin(t * 2 + i) * 1.2, f === 'veteran' ? 0.62 : 0.5, { t: t + i }));
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
        ['Goal', 'Each chapter is a continent. Move city to city across the map and take the capital at the end. If your whole army is wiped out, the chapter restarts.'],
        ['Battles', 'Battles run in real time. Your squads fire on their own. AP builds up over time and from kills: tap a squad\'s card to cast its ability. Tap an enemy to focus all fire on it. Space pauses.'],
        ['Counters', 'Rifles beat Recon. Recon (snipers) beats Support. Support (MGs, grenadiers, mortars) beats Infantry. Sappers beat Armor. Armor beats Infantry and Support. Check the intel before each fight and deploy the right squads.'],
        ['Rows', 'Front-row squads shield the back row. Snipers and enemy scouts and mortars can hit the back row anyway.'],
        ['Break', 'Damage fills the gold Break bar on tough enemies. When it fills they are stunned, take 50% more damage, and any big attack they are winding up is interrupted.'],
        ['Veterancy', 'Squads earn XP in every fight and rank up to Veteran, Elite and Legendary for more HP and damage. A wiped squad comes back at low HP and drops a rank. Ranks reset when the chapter ends.'],
        ['Heroes', 'Bring one hero. Heroes keep their level forever and unlock perks at levels 3, 6 and 9.'],
        ['Army cap', 'Each squad costs cap points. Your cap grows with every continent you clear and with Logistics at the Command Post.'],
        ['Boons', 'After fights you pick 1 of 3 boons. Doctrines you already hold show up more often. The build is wiped when the chapter ends.'],
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
  const confirmBox = G.el('div', { class: 'modal-actions', hidden: true },
    G.el('span', { class: 'muted', text: 'Erase all progress and settings?' }),
    G.el('button', { class: 'btn small primary', type: 'button', onclick: () => { G.storage.del('squad.save.v2'); location.reload(); } }, 'Erase'),
    G.el('button', { class: 'btn small ghost', type: 'button', onclick: () => (confirmBox.hidden = true) }, 'Keep'));
  card.append(
    G.el('h2', { text: 'Settings' }),
    G.el('h3', { text: 'Gameplay' }),
    G.el('div', { class: 'settings-grid' },
      check('set-autocast', 'Auto-cast abilities', 'Squads cast their ability by themselves whenever it is ready and you have the AP.', 'autoCast'),
      check('set-fast', 'Start battles at 2x speed', 'You can still switch speed during a battle.', 'fast'),
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
    G.el('span', { class: 'chip' }, 'Army cap ', G.el('b', { text: String(G.armyCap()) }))
  );
  G.$('#base-settings').onclick = () => G.showSettings();
  const hs = G.$('#base-hotspots');
  hs.innerHTML = '';
  const actions = { radio: G.showRadio, command: () => G.showTrack(['command'], 'Command Post'), barracks: () => G.showTrack(['barracks'], 'Barracks', true), armory: () => G.showTrack(['armory', 'base'], 'Quartermaster'), crate: () => G.showTrack(['unlocks'], 'Relic Crate') };
  const btns = {};
  for (const [k, st] of Object.entries(G.art.STATIONS)) {
    const b = G.el('button', { class: `hotspot ${k === 'radio' ? 'go' : ''}`, type: 'button', id: `station-${k}` }, st.label, G.el('small', { text: st.sub }));
    b.addEventListener('click', () => { G.sfx('click'); actions[k](); });
    hs.append(b);
    btns[k] = b;
  }
  const cv = G.$('#base-canvas');
  const scene = G.$('#base-scene');
  const img = G.art.bgImgs && G.art.bgImgs.base;
  const stations = D.assets && D.assets.bg && D.assets.bg.stations;
  const draw = () => {
    if (G.screen !== 'base') return;
    const r = scene.getBoundingClientRect();
    const dpr = Math.min(2, devicePixelRatio || 1);
    if (cv.width !== Math.floor(r.width * dpr) || cv.height !== Math.floor(r.height * dpr)) { cv.width = Math.floor(r.width * dpr); cv.height = Math.floor(r.height * dpr); }
    const c = cv.getContext('2d');
    if (img && stations) {
      const s = Math.max(r.width / img.width, r.height / img.height);
      const ox = (r.width - img.width * s) / 2, oy = (r.height - img.height * s) / 2;
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.drawImage(img, ox, oy, img.width * s, img.height * s);
      const t = G.now() / 1000;
      c.fillStyle = `rgba(255,190,110,${0.04 + 0.02 * Math.sin(t * 3)})`; c.fillRect(0, 0, r.width, r.height);
      for (const k of Object.keys(btns)) {
        const st = stations[k]; if (!st) continue;
        const x = G.clamp(st[0] * img.width * s + ox, 60, r.width - 60), y = G.clamp(st[1] * img.height * s + oy, 44, r.height - 8);
        btns[k].style.left = `${x}px`; btns[k].style.top = `${y}px`;
      }
    } else {
      const s = Math.max(r.width / G.art.BASE_W, r.height / G.art.BASE_H);
      const ox = (r.width - G.art.BASE_W * s) / 2, oy = (r.height - G.art.BASE_H * s) / 2;
      c.setTransform(s * dpr, 0, 0, s * dpr, ox * dpr, oy * dpr);
      G.art.baseScene(c, G.now() / 1000);
      for (const [k, st] of Object.entries(G.art.STATIONS)) {
        const x = G.clamp(st.x * s + ox, 56, r.width - 56), y = G.clamp(st.y * s + oy, 44, r.height - 8);
        btns[k].style.left = `${x}px`; btns[k].style.top = `${y}px`;
      }
    }
    requestAnimationFrame(draw);
  };
  requestAnimationFrame(draw);
  if (!G.meta.seenTips.base) {
    G.meta.seenTips.base = true;
    G.saveAll();
    G.dialog([
      { who: 'radio', text: 'Welcome to the forward base, Able Company. This farm is home between operations.' },
      { who: 'radio', text: 'Spend meta-points at the stations. When you are ready, head to the Radio Tent and pick a continent.' },
    ]);
  }
};

G.heroRow = (id) => {
  const h = D.heroes[id];
  const lvl = G.heroLevel(id), next = G.heroNext(id), xp = G.meta.heroXp[id] || 0;
  const perks = Object.entries(h.perks || {}).map(([l, p]) => `${lvl >= +l ? '✓' : `Lv ${l}`}: ${p.text}`).join(' · ');
  return G.el('div', { class: 'row hero-row' },
    G.el('h4', {}, G.el('img', { src: G.art.figPortrait(h.figure, 64), alt: '', class: 'row-portrait' }), h.name, G.el('span', { class: 'tag', text: G.heroUnlocked(id) ? `Level ${lvl}` : 'Locked' })),
    G.el('span', { class: 'muted small', text: next ? `${xp}/${next} XP` : 'Max level' }),
    G.el('p', { text: `${h.title}. ${h.blurb} ${h.ability.name}: ${h.ability.text}` }),
    G.el('p', { class: 'perks', text: perks }));
};

G.showTrack = (tracks, title, heroes) => G.openModal((card) => {
  const render = () => {
    card.innerHTML = '';
    card.append(G.el('h2', { text: title }), G.el('p', { class: 'muted' }, 'Meta-points: ', G.el('b', { text: String(G.meta.points) }), ` · Army cap ${G.armyCap()}`));
    if (heroes) {
      card.append(G.el('h3', { text: 'Heroes · keep their levels forever' }));
      card.append(G.el('div', { class: 'rows' }, ...Object.keys(D.heroes).map(G.heroRow)));
    }
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
  card.append(G.el('h2', { text: 'Radio Tent' }), G.el('p', { class: 'muted', text: `Pick a continent. Your army cap is ${G.armyCap()}. Cleared continents can be replayed at higher Heat for more points.` }));
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
    go.addEventListener('click', () => { G.closeModal(); G.showMuster(ch, heat); });
    list.append(G.el('div', { class: `chapter ${unlocked ? '' : 'locked'}` },
      G.el('h4', { text: `${ch.place}: ${ch.name}` }),
      go,
      G.el('div', { class: 'meta-line', text: `${D.world[ch.id].cities.length} cities · Recommended army cap ${ch.recCap}${cleared ? ' · Cleared' : ''}` }),
      G.el('p', { text: unlocked ? ch.blurb : `Clear ${D.chapters.find((c) => c.id === ch.unlockAfter).place} to unlock.` }),
      heatRow));
  }
  card.append(list, G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn ghost', type: 'button', onclick: G.closeModal }, 'Close')));
});

G.roleName = (r) => ({ infantry: 'Infantry', recon: 'Recon', support: 'Support', armor: 'Armor' }[r] || r);
G.dmgName = (d) => ({ rifle: 'Rifles', precision: 'Precision', blast: 'Blast', at: 'Anti-armor', cannon: 'Cannon', melee: 'Melee', heal: 'Healing' }[d] || d);
// which roles a damage type is strong against
G.strongVs = (dmgType) => Object.entries(D.config.counters[dmgType] || {}).filter(([, m]) => m > 1.05).map(([r]) => G.roleName(r));
G.unitChip = (type) => {
  const d = D.units[type];
  const sv = G.strongVs(d.dmgType);
  return `${G.roleName(d.role)} · ${sv.length ? `strong vs ${sv.join(', ')}` : G.dmgName(d.dmgType)}`;
};

// pick a hero and an army within the cap
G.showMuster = (ch, heat) => G.openModal((card) => {
  const cap = G.armyCap();
  const heroes = Object.keys(D.heroes).filter(G.heroUnlocked);
  let hero = heroes.includes(G.meta.lastHero) ? G.meta.lastHero : heroes[0];
  let army = (G.meta.lastArmy || ['rifle', 'mg', 'sapper']).filter((t) => G.unitUnlocked(t));
  while (G.armyCost(army.map((type) => ({ type }))) > cap) army.pop();
  const cost = () => army.reduce((s, t) => s + D.units[t].cost, 0);
  const render = () => {
    card.innerHTML = '';
    card.append(G.el('h2', { text: `Muster for ${ch.place}` }), G.el('p', { class: 'muted', text: `Choose a hero, then fill your army up to the cap. Army cap: ${cost()} / ${cap} used.` }));
    card.append(G.el('h3', { text: 'Hero' }));
    const hg = G.el('div', { class: 'picker' });
    for (const id of heroes) {
      const h = D.heroes[id];
      const b = G.el('button', { class: `pick ${id === hero ? 'on' : ''}`, type: 'button' },
        G.el('img', { src: G.art.figPortrait(h.figure, 96), alt: '' }), G.el('b', { text: h.name }), G.el('span', { text: `Level ${G.heroLevel(id)} · ${G.roleName(h.role)}` }), G.el('span', { text: h.ability.name }));
      b.addEventListener('click', () => { hero = id; G.sfx('click'); render(); });
      hg.append(b);
    }
    const locked = Object.keys(D.heroes).filter((id) => !G.heroUnlocked(id));
    card.append(hg);
    if (locked.length) card.append(G.el('p', { class: 'muted small', text: `Unlock more heroes at the Barracks: ${locked.map((id) => D.heroes[id].name).join(', ')}.` }));
    card.append(G.el('h3', { text: 'Squads' }));
    const rows = G.el('div', { class: 'rows' });
    for (const type of Object.keys(D.units)) {
      const d = D.units[type];
      const n = army.filter((t) => t === type).length;
      const ok = G.unitUnlocked(type);
      const minus = G.el('button', { class: 'btn small ghost', type: 'button', disabled: !n || undefined, 'aria-label': `Remove ${d.name}` }, '−');
      const plus = G.el('button', { class: 'btn small', type: 'button', disabled: !ok || cost() + d.cost > cap || undefined, 'aria-label': `Add ${d.name}` }, '+');
      minus.addEventListener('click', () => { army.splice(army.indexOf(type), 1); render(); });
      plus.addEventListener('click', () => { army.push(type); G.sfx('click'); render(); });
      rows.append(G.el('div', { class: `row unit-row ${ok ? '' : 'locked'}` },
        G.el('h4', {}, G.el('img', { src: G.art.figPortrait(d.figure, 64), alt: '', class: 'row-portrait' }), d.name, G.el('span', { class: 'tag', text: `cost ${d.cost}` }), n ? G.el('span', { class: 'tag on', text: `x${n}` }) : null),
        G.el('div', { class: 'stepper' }, minus, plus),
        G.el('p', { text: ok ? `${G.unitChip(type)}. ${d.ability.name}: ${d.ability.text}` : 'Unlock at the Barracks.' })));
    }
    card.append(rows);
    const go = G.el('button', { class: 'btn primary', type: 'button', disabled: !army.length || undefined }, 'Deploy');
    go.addEventListener('click', () => { G.closeModal(); G.meta.lastArmy = army.slice(); G.meta.lastHero = hero; G.startRun(ch.id, heat, army.slice(), hero); });
    card.append(G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn ghost', type: 'button', onclick: G.closeModal }, 'Back'), go));
  };
  render();
});

// before a fight: enemy intel and which squads to deploy
G.deployScreen = (enemies, title) => {
  const cap = G.armyCap();
  const army = G.run.army.filter((s) => s.frac > 0);
  let chosen = [];
  let used = 0;
  // default: best counters first, within cap
  const roles = enemies.map((k) => D.enemies[k].role);
  const score = (sq) => roles.reduce((s, r) => s + G.battle.counter(D.units[sq.type].dmgType === 'heal' ? 'rifle' : D.units[sq.type].dmgType, r), 0) + (D.units[sq.type].dmgType === 'heal' ? 1.5 : 0) + G.vetRank(sq.xp) * 0.3 + sq.frac;
  army.slice().sort((a, b) => score(b) - score(a)).forEach((sq) => { const c = D.units[sq.type].cost; if (used + c <= cap) { chosen.push(sq.uid); used += c; } });
  if (G.armyCost(army) <= cap) return Promise.resolve(army);
  return G.ask((card, done) => {
    const render = () => {
      const usedNow = army.filter((s) => chosen.includes(s.uid)).reduce((s, sq) => s + D.units[sq.type].cost, 0);
      card.innerHTML = '';
      card.append(G.el('span', { class: 'eyebrow', text: 'Intel report' }), G.el('h2', { text: title }));
      const intel = G.el('div', { class: 'intel' });
      const tally = {};
      enemies.forEach((k) => (tally[k] = (tally[k] || 0) + 1));
      Object.entries(tally).forEach(([k, n]) => {
        const e = D.enemies[k];
        const weak = Object.entries(D.config.counters).filter(([dt, row]) => dt !== '_doc' && dt !== 'cannon' && dt !== 'melee' && row[e.role] > 1.05).map(([dt]) => G.dmgName(dt));
        intel.append(G.el('div', { class: 'intel-row' },
          G.el('img', { src: e.figure ? G.art.figPortrait(e.figure, 64) : G.art.portrait({ side: 'enemy', art: e.sprite }, 64), alt: '' }),
          G.el('div', {}, G.el('b', { text: `${n > 1 ? `${n}x ` : ''}${e.name}` }), G.el('span', { text: `${G.roleName(e.role)} · weak to ${weak.join(', ') || 'nothing in particular'}` }))));
      });
      card.append(intel);
      card.append(G.el('h3', { text: `Deploy · ${usedNow} / ${cap} cap` }));
      const rows = G.el('div', { class: 'picker' });
      army.forEach((sq) => {
        const d = D.units[sq.type];
        const on = chosen.includes(sq.uid);
        const b = G.el('button', { class: `pick ${on ? 'on' : ''}`, type: 'button' },
          G.el('img', { src: G.art.figPortrait(d.figure, 64), alt: '' }), G.el('b', { text: d.name }),
          G.el('span', { text: `${G.vetName(sq.xp)} · ${Math.round(sq.frac * 100)}% HP · cost ${d.cost}` }), G.el('span', { text: G.unitChip(sq.type) }));
        b.addEventListener('click', () => {
          if (on) chosen = chosen.filter((u) => u !== sq.uid);
          else if (usedNow + d.cost <= cap) chosen.push(sq.uid);
          else { G.toast('Over the army cap. Remove a squad first.'); return; }
          G.sfx('click'); render();
        });
        rows.append(b);
      });
      card.append(rows);
      card.append(G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn primary', type: 'button', disabled: !chosen.length || undefined, onclick: () => done(army.filter((s) => chosen.includes(s.uid))) }, 'Engage')));
    };
    render();
  }, { cls: 'paper-ish', auto: (done) => done(army.filter((s) => chosen.includes(s.uid))) });
};

// ---------- boon cards ----------
G.cardEl = (b, opts = {}) => {
  const fam = G.familyOf(b);
  const el = G.el('button', { class: `card ${opts.cant ? 'cant' : ''}`, type: 'button', style: { '--fam': fam.color } },
    G.el('div', { class: 'card-top', html: G.art.icon(fam.icon) }),
    G.el('div', { class: 'card-body' },
      G.el('div', { class: 'card-type', text: `${b.type === 'duo' ? b.requires.map((f) => D.boons.families[f].name).join(' + ') : fam.name} · ${G.typeLabel(b.type)}${b.unit ? ` · ${D.units[b.unit].name}` : ''}` }),
      G.el('div', { class: 'card-name', text: b.name }),
      G.el('div', { class: 'card-text', text: b.text }),
      opts.price ? G.el('div', { class: 'card-price', text: `${opts.price} gold` }) : null));
  el.querySelector('.card-top').append(G.el('span', { class: 'card-fam', text: fam.name }), G.el('span', { class: `card-rar ${b.rarity}`, text: G.rarityLabel(b.rarity) }));
  return el;
};

G.draft = (opts = {}) => {
  const kind = opts.kind || 'normal';
  let offer = G.offerBoons({ kind, guaranteeRare: opts.guaranteeRare });
  if (!offer.length) return Promise.resolve(null);
  offer.forEach((b) => (G.meta.codex[b.id] = G.meta.codex[b.id] || false));
  return G.ask((card, done) => {
    const render = () => {
      card.innerHTML = '';
      card.append(G.el('div', { class: 'draft-head' }, G.el('span', { class: 'eyebrow', text: opts.eyebrow || 'Boon draft · pick 1 of 3' }), G.el('h2', { text: opts.title || 'Choose a boon' })));
      if (opts.notes && opts.notes.length) card.append(G.el('div', { class: 'notes' }, ...opts.notes.map((n) => G.el('span', { class: 'note', text: n }))));
      const cards = G.el('div', { class: 'cards' });
      offer.forEach((b) => { const el = G.cardEl(b); el.addEventListener('click', () => { G.sfx('card'); G.addBoon(b.id); done(b); }); cards.append(el); });
      card.append(cards);
      const acts = G.el('div', { class: 'draft-actions' });
      const rr = G.el('button', { class: 'btn ghost', type: 'button', disabled: G.run.rerolls <= 0 || undefined }, `Reroll (${G.run.rerolls} left)`);
      rr.addEventListener('click', () => { if (G.run.rerolls <= 0) return; G.run.rerolls--; G.sfx('card'); offer = G.offerBoons({ kind, guaranteeRare: opts.guaranteeRare }); render(); });
      acts.append(rr);
      if (!opts.noSkip) acts.append(G.el('button', { class: 'btn ghost', type: 'button', onclick: () => { G.run.gold += D.config.rewards.skipGold; done(null); } }, `Skip (+${D.config.rewards.skipGold} gold)`));
      acts.append(G.el('button', { class: 'btn ghost', type: 'button', onclick: () => G.showBuild() }, `Army & build`));
      card.append(acts);
    };
    render();
    G._draftBack = render;
  }, { cls: 'draft-wrap', auto: (done) => { const b = offer[0]; G.addBoon(b.id); done(b); } });
};

G.showBuild = () => {
  const prev = G.$('#modal').hidden ? null : G._draftBack;
  const prevCls = G.$('#modal-card').className;
  G.openModal((card) => {
    card.append(G.el('h2', { text: 'Army & build' }));
    const rows = G.el('div', { class: 'rows' });
    if (G.run.hero) {
      const h = D.heroes[G.run.hero.id];
      rows.append(G.el('div', { class: 'row' }, G.el('h4', {}, G.el('img', { src: G.art.figPortrait(h.figure, 64), alt: '', class: 'row-portrait' }), h.name, G.el('span', { class: 'tag on', text: `Hero · Lv ${G.heroLevel(G.run.hero.id)}` })), G.el('span', { class: 'muted small', text: `${Math.round(G.run.hero.frac * 100)}% HP` }), G.el('p', { text: h.ability.text })));
    }
    G.run.army.forEach((sq) => {
      const d = D.units[sq.type];
      const next = G.vetNext(sq.xp);
      rows.append(G.el('div', { class: 'row' }, G.el('h4', {}, G.el('img', { src: G.art.figPortrait(d.figure, 64), alt: '', class: 'row-portrait' }), d.name, G.el('span', { class: 'tag', text: `${'★'.repeat(G.vetRank(sq.xp))} ${G.vetName(sq.xp)}` })), G.el('span', { class: 'muted small', text: `${Math.round(sq.frac * 100)}% HP` }), G.el('p', { text: next ? `${sq.xp}/${next} XP to next rank` : 'Max rank' })));
    });
    card.append(G.el('h3', { text: `Army · cap ${G.armyCost(G.run.army)} / ${G.armyCap()} per battle` }), rows);
    const counts = G.familyCounts();
    card.append(G.el('h3', { text: 'Boons' }), G.el('p', { class: 'muted', text: Object.keys(counts).length ? Object.entries(counts).map(([f, n]) => `${D.boons.families[f].name} ${n}`).join(' · ') : 'No doctrine boons yet.' }));
    const brows = G.el('div', { class: 'rows' });
    G.run.boons.forEach((id) => {
      const b = G.boonById(id); const fam = G.familyOf(b);
      brows.append(G.el('div', { class: 'row' }, G.el('h4', {}, G.el('span', { class: 'fam-dot', style: { background: fam.color } }), b.name, G.el('span', { class: 'tag', text: `${G.rarityLabel(b.rarity)} ${G.typeLabel(b.type)}` })), G.el('p', { text: b.text })));
    });
    if (!G.run.boons.length) brows.append(G.el('p', { class: 'muted', text: 'Win battles to draft boons.' }));
    card.append(brows);
    const items = Object.entries(G.run.items).filter(([, n]) => n > 0).map(([id, n]) => `${D.items[id].name} x${n}`).join(', ');
    card.append(G.el('h3', { text: 'Items' }), G.el('p', { class: 'muted', text: items || 'None' }));
    card.append(G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn primary', type: 'button', onclick: () => { if (prev) { G.openModal(() => {}, { cls: prevCls.replace('modal-card', '').trim() }); prev(); } else G.closeModal(); } }, 'Back')));
  });
};

// ---------- supply depot ----------
G.shop = () => G.ask((card, done) => {
  const nBoons = 2 + (G.has('base_supply') ? 1 : 0);
  const disc = G.has('base_supply') ? 0.85 : 1;
  const stock = G.offerBoons({ count: nBoons }).map((b) => ({ b, price: G.boonPrice(b), sold: false }));
  const itemStock = G.shuffle(Object.keys(D.items)).slice(0, 3).map((id) => ({ id, price: Math.round(D.items[id].price * disc), sold: false }));
  const recruits = G.unitTypes().map((type) => ({ type, price: Math.round(D.units[type].recruit * disc * D.config.prices.recruitMult) }));
  let healed = false;
  const render = () => {
    card.innerHTML = '';
    card.append(G.el('div', { class: 'draft-head' }, G.el('span', { class: 'eyebrow', text: 'Supply depot' }), G.el('h2', { text: 'Requisition' }), G.el('p', { class: 'muted' }, 'Gold: ', G.el('b', { text: String(G.run.gold) }))));
    const rec = G.el('div', { class: 'rows' });
    recruits.forEach((r) => {
      const d = D.units[r.type];
      const b = G.el('button', { class: 'btn small', type: 'button', disabled: G.run.gold < r.price || undefined }, `Recruit ${r.price}`);
      b.addEventListener('click', () => { if (G.run.gold < r.price) return; G.run.gold -= r.price; G.run.army.push(G.newSquad(r.type)); G.sfx('good'); G.toast(`${d.name} joins your army`); render(); });
      rec.append(G.el('div', { class: 'row' }, G.el('h4', {}, G.el('img', { src: G.art.figPortrait(d.figure, 64), alt: '', class: 'row-portrait' }), d.name, G.el('span', { class: 'tag', text: `cost ${d.cost}` })), b, G.el('p', { text: G.unitChip(r.type) })));
    });
    card.append(G.el('div', { style: { width: '100%' } }, G.el('h3', { text: `Recruit · you have ${G.run.army.length} squads, cap ${G.armyCap()} per battle` }), rec));
    const cards = G.el('div', { class: 'cards' });
    stock.forEach((s) => {
      if (s.sold) return;
      const el = G.cardEl(s.b, { price: s.price, cant: G.run.gold < s.price });
      el.addEventListener('click', () => { if (G.run.gold < s.price) { G.toast('Not enough gold'); return; } G.run.gold -= s.price; s.sold = true; G.addBoon(s.b.id); G.sfx('card'); render(); });
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
    hb.addEventListener('click', () => { if (healed || G.run.gold < hc) return; G.run.gold -= hc; healed = true; G.healArmy(D.config.prices.healPct); G.sfx('heal'); render(); });
    rows.append(G.el('div', { class: 'row' }, G.el('h4', { text: 'Field surgeons' }), hb, G.el('p', { text: `Heal every squad ${G.pct(D.config.prices.healPct)}.` })));
    card.append(G.el('div', { style: { width: '100%' } }, G.el('h3', { text: 'Supplies' }), rows));
    card.append(G.el('div', { class: 'draft-actions' }, G.el('button', { class: 'btn ghost', type: 'button', onclick: () => G.showBuild() }, 'Army & build'), G.el('button', { class: 'btn primary', type: 'button', onclick: () => done(true) }, 'Move out')));
  };
  render();
  G._draftBack = render;
}, { cls: 'draft-wrap', auto: (done) => { const r = G.unitTypes()[0]; if (G.run.gold >= 80) { G.run.gold -= 60; G.run.army.push(G.newSquad(r)); } done(true); } });

// ---------- field camp ----------
G.camp = () => {
  const heal = (G.has('base_camp') ? 0.5 : D.config.camp.healPct) * Math.max(0.2, 1 + G.mod('passive', 'campHealPct'));
  const xp = D.config.veterancy.xpDrill;
  return G.ask((card, done) => {
    card.append(
      G.el('span', { class: 'eyebrow', text: 'Field camp' }),
      G.el('h2', { text: 'Dig in for the night' }),
      G.el('p', { text: 'A quiet place outside the city. You have time for one thing before dawn.' }),
      G.el('div', { class: 'rows' },
        G.el('div', { class: 'row' }, G.el('h4', { text: 'Rest' }), G.el('button', { class: 'btn primary small', type: 'button', onclick: () => done('rest') }, 'Rest'), G.el('p', { text: `Every squad heals ${G.pct(heal)} of max HP, wiped squads included.` })),
        G.el('div', { class: 'row' }, G.el('h4', { text: 'Drill' }), G.el('button', { class: 'btn small', type: 'button', onclick: () => done('drill') }, 'Drill'), G.el('p', { text: `Every squad gains ${xp} XP toward its next rank.` }))));
  }, { cls: 'paper', auto: (done) => done('rest') }).then((c) => {
    if (c === 'rest') { G.healArmy(heal); G.sfx('heal'); G.toast(`Army healed ${G.pct(heal)}`); }
    else { const ups = G.run.army.filter((sq) => G.giveXp(sq, xp)).length; G.sfx('good'); G.toast(ups ? `${ups} squad${ups > 1 ? 's' : ''} ranked up` : `+${xp} XP to every squad`); }
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
      G.el('div', { class: 'row' }, G.el('h4', { text: 'Salvage' }), G.el('button', { class: 'btn small', type: 'button', onclick: () => done('salvage') }, 'Salvage'), G.el('p', { text: '+50 gold and a Grenade Crate.' }))));
}, { cls: 'paper', auto: (done) => done('draft') }).then(async (c) => {
  if (c === 'draft') await G.draft({ guaranteeRare: true, eyebrow: 'Cache · guaranteed Rare' });
  else if (c === 'relic') { const b = G.pick(D.boons.boons.filter((x) => G.boonEligible(x, 'relic'))); if (b) { G.addBoon(b.id); G.toast(`Gained ${b.name}`); } }
  else { G.run.gold += 50; G.addItem('grenade'); G.toast('+50 gold, +1 Grenade Crate'); }
});

// ---------- intel event ----------
G.intel = async () => {
  const pool = D.events.filter((e) => !(G.run.seenEvents || []).includes(e.id));
  const ev = G.pick(pool.length ? pool : D.events);
  G.run.seenEvents = [...(G.run.seenEvents || []), ev.id];
  const choice = await G.ask((card, done) => {
    card.append(G.el('span', { class: 'eyebrow', text: 'Intel' }), G.el('h2', { text: ev.title }), G.el('p', { class: 'dialog-text', text: ev.text }));
    const rows = G.el('div', { class: 'rows' });
    ev.choices.forEach((c) => rows.append(G.el('button', { class: 'btn', type: 'button', disabled: (c.cost && G.run.gold < c.cost) || undefined, onclick: () => done(c) }, c.label)));
    card.append(rows);
  }, { cls: 'paper', auto: (done) => done(ev.choices[ev.choices.length - 1]) });
  if (choice.cost) G.run.gold -= choice.cost;
  const out = choice.chance !== undefined ? (Math.random() < choice.chance ? choice.success : choice.fail) : choice.outcome;
  if (out.gold) G.run.gold = Math.max(0, G.run.gold + out.gold);
  if (out.healPct) G.healArmy(out.healPct);
  if (out.damagePct) G.damageArmy(out.damagePct);
  if (out.rerolls) G.run.rerolls += out.rerolls;
  if (out.points) G.run.earned += out.points;
  if (out.item) G.addItem(out.item);
  if (out.item2) G.addItem(out.item2);
  if (out.recruit) G.run.army.push(G.newSquad(out.recruit));
  if (out.xp) G.run.army.forEach((sq) => G.giveXp(sq, out.xp));
  await G.ask((card, done) => {
    card.append(G.el('h2', { text: ev.title }), G.el('p', { class: 'dialog-text', text: out.say }), G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn primary', type: 'button', onclick: () => done(true) }, out.fight ? 'Fight' : 'Continue')));
  }, { cls: 'paper', auto: (done) => done(true) });
  return { fight: out.fight || null, boon: out.boon };
};

// ---------- after a battle ----------
G.showAfterAction = (lines) => G.ask((card, done) => {
  card.append(G.el('span', { class: 'eyebrow', text: 'After-action report' }), G.el('h2', { text: 'Area secured' }));
  card.append(G.el('div', { class: 'rows' }, ...lines.map((l) => G.el('div', { class: `row aar ${l.up ? 'up' : ''}` }, G.el('h4', {}, G.el('img', { src: G.art.figPortrait(l.figure, 64), alt: '', class: 'row-portrait' }), l.name, l.up ? G.el('span', { class: 'tag on', text: l.up }) : null), G.el('span', { class: 'muted small', text: l.right }), G.el('p', { text: l.text })))));
  card.append(G.el('div', { class: 'modal-actions' }, G.el('button', { class: 'btn primary', type: 'button', onclick: () => done(true) }, 'Continue')));
}, { cls: 'paper', auto: (done) => done(true) });

// ---------- results ----------
G.showResults = (r) => G.ask((card, done) => {
  const ch = D.chapters.find((c) => c.id === r.chapterId);
  card.append(
    G.el('span', { class: 'eyebrow', text: r.win ? 'Operation complete' : 'Army lost' }),
    G.el('h2', { text: r.win ? `${ch.place} liberated` : `${ch.name} failed` }),
    G.el('p', { text: r.win ? 'Your army and build are disbanded. Meta-points are banked at base and your hero keeps their levels.' : `The chapter resets. You still bank ${G.pct(D.config.rewards.deathBankPct)} of the points this run earned, and your hero keeps their XP.` }));
  const grid = G.el('div', { class: 'results-grid' });
  r.lines.forEach(([a, b]) => grid.append(G.el('span', { text: a }), G.el('span', { text: b })));
  grid.append(G.el('span', { class: 'total', text: 'Meta-points banked' }), G.el('span', { class: 'total', text: `+${r.total}` }));
  card.append(grid);
  if (r.capUp) card.append(G.el('p', { class: 'callout', text: `Army cap raised to ${G.armyCap()}. ${r.unlockText || ''}` }));
  card.append(G.el('h3', { text: 'Run stats' }), G.el('p', { class: 'muted', text: `${r.stats.fights} battles · ${r.stats.kills} enemy units destroyed · ${r.stats.rankUps} rank-ups · ${r.stats.casts} abilities cast · ${r.stats.wipes} squads wiped · ${G.fmtTime(r.timeMs)}` }));
  if (r.hero) card.append(G.el('p', { class: 'muted', text: `${D.heroes[r.hero].name}: +${r.heroXp} XP, now level ${G.heroLevel(r.hero)}.` }));
  const acts = G.el('div', { class: 'modal-actions' });
  if (!r.win) acts.append(G.el('button', { class: 'btn', type: 'button', onclick: () => done('retry') }, 'Redeploy'));
  acts.append(G.el('button', { class: 'btn primary', type: 'button', onclick: () => done('base') }, 'Return to base'));
  card.append(acts);
}, { cls: 'paper', auto: (done) => done('base') });
