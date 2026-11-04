// World map: each chapter is a continent; cities are nodes joined by fixed routes (data/world.json).
// City positions come from the Blender map render (assets/maps/maps.json) or a fallback projection.
G.NODE_INFO = {
  skirmish: { name: 'Battle', text: 'An enemy force. Win a boon draft.' },
  elite: { name: 'Elite force', text: 'Tougher fight. The draft has a guaranteed Rare.' },
  intel: { name: 'Intel', text: 'Something happened here. Make a choice.' },
  supply: { name: 'Supply depot', text: 'Recruit squads, buy boons and items, heal.' },
  camp: { name: 'Field camp', text: 'Rest to heal, or drill your squads for XP.' },
  cache: { name: 'Cache', text: 'A draft with a guaranteed Rare, or salvage.' },
  miniboss: { name: 'Strongpoint', text: 'Mini-boss. The middle of the operation.' },
  boss: { name: 'Objective', text: 'The boss. Take this city to finish the chapter.' },
};

G.genMap = (ch) => {
  const world = D.world[ch.id];
  const lastTier = Math.max(...world.cities.map((c) => c.tier));
  const miniTier = Math.round(lastTier / 2);
  const nodes = {};
  for (const c of world.cities) nodes[c.id] = { id: c.id, name: c.name, tier: c.tier, type: null, next: [] };
  for (const [a, b] of world.edges) nodes[a].next.push(b);
  for (const n of Object.values(nodes)) {
    const t = n.tier;
    if (t === 0) n.type = 'skirmish';
    else if (t === lastTier) n.type = 'boss';
    else if (t === miniTier) n.type = 'miniboss';
    else if (t === lastTier - 1) n.type = G.pick(['camp', 'camp', 'supply']);
    else if (t === miniTier - 1) n.type = G.pick(['camp', 'supply', 'skirmish', 'intel']);
    else n.type = G.weighted([['skirmish', 46], ['elite', t >= 3 ? 14 : 0], ['intel', 14], ['supply', t >= 2 ? 11 : 0], ['camp', t >= 3 ? 8 : 0], ['cache', t >= 2 ? 8 : 0]], (p) => p[1])[0];
  }
  // avoid a fork where every option is a non-fight
  for (const n of Object.values(nodes)) {
    const nx = n.next.map((id) => nodes[id]);
    if (nx.length > 1 && nx.every((x) => !['skirmish', 'elite', 'miniboss', 'boss'].includes(x.type))) nx[0].type = 'skirmish';
  }
  const start = world.cities.find((c) => c.tier === 0).id;
  return { nodes, start, lastTier, miniTier };
};

G.mapAvailable = () => {
  const run = G.run;
  if (!run.node) return [run.map.start];
  const cur = run.map.nodes[run.node];
  return cur ? cur.next : [];
};

// city positions as fractions of the map image
G.cityPos = (chId) => {
  const m = D.assets && D.assets.maps && D.assets.maps[chId];
  const world = D.world[chId];
  if (m && m.cities) {
    const pos = { ...m.cities };
    const known = world.cities.filter((c) => pos[c.id]);
    const missing = world.cities.filter((c) => !pos[c.id]);
    if (missing.length && known.length >= 3) {
      // least-squares affine fit lat/lon -> image fractions from the cities we do know
      const fit = (k) => {
        let s = [[0, 0, 0], [0, 0, 0], [0, 0, 0]], r = [0, 0, 0];
        known.forEach((c) => { const v = [c.lon, c.lat, 1]; for (let i = 0; i < 3; i++) { r[i] += v[i] * pos[c.id][k]; for (let j = 0; j < 3; j++) s[i][j] += v[i] * v[j]; } });
        const det = (M) => M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1]) - M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0]) + M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]);
        const D0 = det(s);
        return [0, 1, 2].map((i) => det(s.map((row, ri) => row.map((x, ci) => (ci === i ? r[ri] : x)))) / D0);
      };
      const fx = fit(0), fy = fit(1);
      missing.forEach((c) => { pos[c.id] = [fx[0] * c.lon + fx[1] * c.lat + fx[2], fy[0] * c.lon + fy[1] * c.lat + fy[2]]; });
    }
    if (world.cities.every((c) => pos[c.id])) return { pos, w: m.w, h: m.h, src: m.src };
  }
  const lats = world.cities.map((c) => c.lat), lons = world.cities.map((c) => c.lon);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const k = Math.cos((midLat * Math.PI) / 180);
  const xs = world.cities.map((c) => c.lon * k), ys = world.cities.map((c) => -c.lat);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pos = {};
  world.cities.forEach((c, i) => { pos[c.id] = [0.08 + ((xs[i] - x0) / (x1 - x0 || 1)) * 0.84, 0.1 + ((ys[i] - y0) / (y1 - y0 || 1)) * 0.8]; });
  return { pos, w: 1600, h: 1100, src: null };
};

G.renderMap = (onPick) => {
  const run = G.run;
  const ch = G.chapter();
  const { pos, w: VW, h: VH, src } = G.cityPos(ch.id);
  const P = (id) => ({ x: pos[id][0] * VW, y: pos[id][1] * VH });
  const nodes = run.map.nodes;
  const avail = new Set(G.mapAvailable());
  const visited = new Set(run.visited);
  const curTier = run.node ? nodes[run.node].tier : -1;
  const S = VW / 1600; // marker scale
  let svg = `<svg viewBox="0 0 ${VW} ${VH}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${G.esc(ch.place)} map">`;
  if (!src) {
    svg += `<rect width="${VW}" height="${VH}" fill="#2d4b52"/>`;
    svg += `<rect x="20" y="20" width="${VW - 40}" height="${VH - 40}" fill="#6f7a4c" opacity=".55" rx="40"/>`;
  }
  // routes
  for (const n of Object.values(nodes)) {
    const a = P(n.id);
    for (const id of n.next) {
      const b = P(id);
      const taken = visited.has(n.id) && visited.has(id);
      const live = run.node === n.id && avail.has(id);
      const past = nodes[id].tier <= curTier && !taken;
      const col = taken ? '#e0602c' : live ? '#fff6dc' : '#1b1a14';
      const op = taken ? 1 : live ? 1 : past ? 0.18 : 0.55;
      svg += `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="#000" stroke-opacity="${op * 0.5}" stroke-width="${(taken || live ? 9 : 6) * S}" stroke-linecap="round"/>`;
      svg += `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${col}" stroke-opacity="${op}" stroke-width="${(taken || live ? 5 : 3) * S}" ${taken ? '' : `stroke-dasharray="${12 * S} ${9 * S}"`} stroke-linecap="round"/>`;
    }
  }
  // cities
  for (const n of Object.values(nodes)) {
    const p = P(n.id);
    const isAvail = avail.has(n.id), isCur = run.node === n.id, done = visited.has(n.id);
    const big = n.type === 'boss' || n.type === 'miniboss';
    const r = (big ? 30 : 22) * S;
    const fill = done ? '#b9ad86' : isAvail ? '#fff6dc' : '#e6dbbd';
    const stroke = isAvail ? '#e0602c' : '#1b1a14';
    const iconCol = n.type === 'boss' || n.type === 'elite' || n.type === 'miniboss' ? '#7a2a17' : '#2b2a1d';
    const dim = n.tier < curTier && !done;
    svg += `<g class="map-node ${isAvail ? '' : 'locked'}" data-id="${n.id}" transform="translate(${p.x} ${p.y})" opacity="${dim ? 0.45 : 1}" ${isAvail ? 'tabindex="0" role="button"' : ''} aria-label="${G.esc(n.name)}, ${G.NODE_INFO[n.type].name}">`;
    if (isAvail) svg += `<circle r="${r + 12 * S}" fill="#e0602c" fill-opacity=".25" stroke="#e0602c" stroke-width="${4 * S}" stroke-dasharray="${6 * S} ${5 * S}"><animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="8s" repeatCount="indefinite"/></circle>`;
    svg += `<circle r="${r + 3 * S}" fill="#000" fill-opacity=".45" cy="${3 * S}"/>`;
    svg += `<circle r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${(isAvail ? 5 : 3.5) * S}"/>`;
    svg += `<g transform="scale(${(big ? 1.5 : 1.15) * S})" color="${iconCol}">${G.art.NODE_ICONS[n.type]}</g>`;
    const label = `${n.name}${isAvail ? ` · ${G.NODE_INFO[n.type].name}` : ''}`;
    const fs = (isAvail || big || isCur ? 24 : 19) * S;
    svg += `<text y="${r + fs + 4 * S}" text-anchor="middle" font-family="Barlow Condensed, Arial Narrow, sans-serif" font-weight="700" font-size="${fs}" fill="#fff6dc" stroke="#14170f" stroke-width="${5 * S}" paint-order="stroke">${G.esc(label)}</text>`;
    svg += `</g>`;
  }
  // army marker
  const cur = run.node ? P(run.node) : null;
  if (cur) svg += `<g transform="translate(${cur.x - 46 * S} ${cur.y - 30 * S}) scale(${1.6 * S})"><path d="M-2 14 V-16" stroke="#1b1a14" stroke-width="3"/><path d="M-1 -16 H18 L14 -10 L18 -4 H-1 Z" fill="#e0602c" stroke="#1b1a14" stroke-width="2"/></g>`;
  svg += `</svg>`;
  const table = G.$('#map-table');
  table.innerHTML = '';
  table.style.aspectRatio = `${VW} / ${VH}`;
  if (src) table.append(G.el('img', { src, alt: '', class: 'map-img' }));
  table.insertAdjacentHTML('beforeend', svg);
  G.$$('.map-node', table).forEach((g) => {
    const id = g.getAttribute('data-id');
    if (!avail.has(id)) return;
    const go = () => { G.sfx('click'); onPick(id); };
    g.addEventListener('click', go);
    g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
  });
  // scroll so the next choices are in view
  const wrap = G.$('#map-wrap');
  requestAnimationFrame(() => {
    const first = [...avail][0];
    if (!first) return;
    const p = P(first);
    const k = table.getBoundingClientRect().width / VW;
    wrap.scrollLeft = Math.max(0, p.x * k - wrap.clientWidth / 2);
    wrap.scrollTop = Math.max(0, p.y * k - wrap.clientHeight / 2);
  });
};
