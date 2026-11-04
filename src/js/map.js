// Operation map: a branching node path drawn on a field map. Rows run bottom (landing) to top (boss).
const MAP_ROWS = 13; // short chapter: ~13 stops, 20-30 minutes
const MINI_ROW = 6, BOSS_ROW = MAP_ROWS - 1, CAMP_ROW = MAP_ROWS - 2;
const LANES = 5;
G.NODE_INFO = {
  skirmish: { name: 'Skirmish', text: 'An enemy squad. Win a boon draft.' },
  elite: { name: 'Elite squad', text: 'Tougher fight. The draft has a guaranteed Rare.' },
  intel: { name: 'Intel', text: 'Something happened here. Make a choice.' },
  supply: { name: 'Supply drop', text: 'Spend gold on boons, items and healing.' },
  camp: { name: 'Field camp', text: 'Rest to heal, or drill for a stat card.' },
  cache: { name: 'Cache', text: 'A draft with a guaranteed Rare, or salvage.' },
  miniboss: { name: 'Strongpoint', text: 'Mini-boss. The middle of the operation.' },
  boss: { name: 'Objective', text: 'The boss. Clear it to finish the chapter.' },
};

G.genMap = (ch) => {
  const nodes = {};
  const key = (r, l) => `${r}-${l}`;
  const add = (r, l, type) => { const k = key(r, l); if (!nodes[k]) nodes[k] = { id: k, row: r, lane: l, type, next: [] }; return nodes[k]; };
  const link = (a, b) => { if (!a.next.includes(b.id)) a.next.push(b.id); };
  add(0, 2, 'skirmish');
  add(MINI_ROW, 2, 'miniboss');
  add(BOSS_ROW, 2, 'boss');
  // random walks from the start to the mini-boss, then from the mini-boss to the boss
  const walk = (fromRow, toRow, walks) => {
    for (let w = 0; w < walks; w++) {
      let lane = 2;
      let prev = nodes[key(fromRow, 2)];
      let lastDelta = 0;
      for (let r = fromRow + 1; r < toRow; r++) {
        const spread = r === fromRow + 1 ? [-1, 0, 1, -2, 2] : [-1, 0, 1];
        let d = G.pick(spread);
        if (r === fromRow + 1) d = [-2, -1, 1, 2][w % 4] ?? d;
        if (d === -lastDelta && Math.random() < 0.5) d = 0;
        lane = G.clamp(lane + d, 0, LANES - 1);
        // steer back toward the centre near the merge row
        if (r === toRow - 1) lane = G.clamp(lane, 1, 3);
        lastDelta = d;
        const n = add(r, lane, null);
        link(prev, n);
        prev = n;
      }
      link(prev, nodes[key(toRow, 2)]);
    }
  };
  walk(0, MINI_ROW, 4);
  walk(MINI_ROW, BOSS_ROW, 4);
  // assign types
  const all = Object.values(nodes);
  for (const n of all) {
    if (n.type) continue;
    if (n.row === CAMP_ROW) { n.type = Math.random() < 0.7 ? 'camp' : 'supply'; continue; }
    if (n.row === MINI_ROW - 1) { n.type = G.pick(['camp', 'supply', 'skirmish', 'intel']); continue; }
    const r = n.row;
    const pool = [
      ['skirmish', 46],
      ['elite', r >= 3 ? 14 : 0],
      ['intel', 14],
      ['supply', r >= 2 ? 10 : 0],
      ['camp', r >= 4 && r !== MINI_ROW + 1 ? 9 : 0],
      ['cache', r >= 2 ? 8 : 0],
    ];
    n.type = G.weighted(pool, (p) => p[1])[0];
  }
  // make sure the route has enough fights and every lane is not all shops
  for (const n of all) {
    const nexts = n.next.map((id) => nodes[id]);
    if (nexts.length > 1 && nexts.every((x) => x.type === nexts[0].type && !['skirmish', 'miniboss', 'boss'].includes(x.type))) nexts[0].type = 'skirmish';
  }
  // jitter positions for a hand-drawn feel
  for (const n of all) { n.jx = G.ri(-14, 14); n.jy = G.ri(-10, 10); }
  return { nodes, start: key(0, 2) };
};

G.mapAvailable = () => {
  const run = G.run;
  if (!run.node) return [run.map.start];
  const cur = run.map.nodes[run.node];
  return cur ? cur.next : [];
};

G.renderMap = (onPick) => {
  const run = G.run;
  const ch = G.chapter();
  const nodes = Object.values(run.map.nodes);
  const VW = 600, rowH = 92, padT = 70, padB = 80;
  const VH = padT + padB + rowH * (MAP_ROWS - 1);
  const pos = (n) => ({ x: 70 + n.lane * ((VW - 140) / (LANES - 1)) + n.jx, y: VH - padB - n.row * rowH + n.jy });
  const avail = new Set(G.mapAvailable());
  const visited = new Set(run.visited);
  const curRow = run.node ? run.map.nodes[run.node].row : -1;
  let svg = `<svg viewBox="0 0 ${VW} ${VH}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Operation map">`;
  svg += `<defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#6b5f3e" stroke-opacity=".22" stroke-width="1"/></pattern>
    <filter id="rough"><feTurbulence baseFrequency=".04" numOctaves="2" seed="3"/><feDisplacementMap in="SourceGraphic" scale="3"/></filter></defs>`;
  // paper
  svg += `<rect x="14" y="10" width="${VW - 28}" height="${VH - 20}" fill="#e6dbbd" stroke="#2b2a1d" stroke-width="3"/>`;
  svg += `<rect x="14" y="10" width="${VW - 28}" height="${VH - 20}" fill="url(#grid)"/>`;
  // terrain doodles: coastline at bottom, fortress mountain at top
  svg += `<path d="M14 ${VH - 46} C 120 ${VH - 70}, 220 ${VH - 30}, 330 ${VH - 58} S 520 ${VH - 40}, ${VW - 14} ${VH - 62} V ${VH - 10} H 14 Z" fill="#9db3b8" opacity=".55"/>`;
  svg += `<path d="M180 70 L250 26 L300 52 L350 18 L420 70 Z" fill="#7a6a55" opacity=".35"/>`;
  for (let i = 0; i < 9; i++) svg += `<circle cx="${40 + ((i * 131) % (VW - 80))}" cy="${120 + ((i * 263) % (VH - 260))}" r="${10 + (i % 3) * 5}" fill="#6f7d45" opacity=".18"/>`;
  svg += `<text x="${VW / 2}" y="${VH - 20}" text-anchor="middle" font-family="Special Elite, Courier New, monospace" font-size="15" fill="#2b2a1d">${G.esc(ch.place.toUpperCase())}</text>`;
  // edges
  for (const n of nodes) {
    const a = pos(n);
    for (const id of n.next) {
      const b = pos(run.map.nodes[id]);
      const taken = visited.has(n.id) && (visited.has(id) || run.node === id);
      const live = run.node === n.id && avail.has(id);
      const col = taken ? '#b8552c' : live ? '#2b2a1d' : '#2b2a1d';
      const op = taken ? 1 : live ? 0.9 : n.row < curRow ? 0.15 : 0.45;
      const dash = taken ? '' : 'stroke-dasharray="7 6"';
      svg += `<path d="M${a.x} ${a.y} Q ${(a.x + b.x) / 2 + (n.jx - n.jy) * 0.6} ${(a.y + b.y) / 2}, ${b.x} ${b.y}" fill="none" stroke="${col}" stroke-opacity="${op}" stroke-width="${taken ? 4 : 2.5}" ${dash} stroke-linecap="round"/>`;
    }
  }
  // nodes
  for (const n of nodes) {
    const p = pos(n);
    const isAvail = avail.has(n.id);
    const isCur = run.node === n.id;
    const done = visited.has(n.id);
    const big = n.type === 'boss' || n.type === 'miniboss';
    const r = big ? 26 : 19;
    const fog = n.row > curRow + 5;
    const fill = done ? '#cdbf98' : isAvail ? '#f6efda' : '#e0d3ae';
    const stroke = isAvail ? '#b8552c' : '#2b2a1d';
    const iconCol = n.type === 'boss' || n.type === 'elite' || n.type === 'miniboss' ? '#7a2a17' : '#2b2a1d';
    svg += `<g class="map-node ${isAvail ? '' : 'locked'}" data-id="${n.id}" transform="translate(${p.x} ${p.y})" opacity="${fog ? 0.45 : done && !isCur ? 0.65 : 1}" ${isAvail ? 'tabindex="0" role="button"' : ''} aria-label="${G.NODE_INFO[n.type].name}">`;
    if (isAvail) svg += `<circle r="${r + 9}" fill="none" stroke="#b8552c" stroke-width="3" stroke-dasharray="4 4"><animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="8s" repeatCount="indefinite"/></circle>`;
    svg += `<circle r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${isAvail ? 3.5 : 2.5}"/>`;
    svg += `<g transform="scale(${big ? 1.25 : 0.95})" color="${iconCol}">${G.art.NODE_ICONS[n.type]}</g>`;
    if (isAvail) svg += `<text y="${r + 22}" text-anchor="middle" font-family="Barlow Condensed, Arial Narrow, sans-serif" font-weight="700" font-size="14" fill="#2b2a1d">${G.NODE_INFO[n.type].name.toUpperCase()}</text>`;
    svg += `</g>`;
  }
  // squad figurine on the current node (or below the start)
  const cur = run.node ? pos(run.map.nodes[run.node]) : { x: pos(run.map.nodes[run.map.start]).x, y: VH - 40 };
  svg += `<g transform="translate(${cur.x - 34} ${cur.y - 4})"><path d="M-7 10 L-5 -4 L5 -4 L7 10 Z" fill="#5d6b30" stroke="#1b1a14" stroke-width="2"/><circle cy="-9" r="6" fill="#e2b48a" stroke="#1b1a14" stroke-width="2"/><path d="M-9 -11 a9 7 0 0 1 18 0 z" fill="#55602f" stroke="#1b1a14" stroke-width="2"/></g>`;
  svg += `</svg>`;
  const table = G.$('#map-table');
  table.innerHTML = svg;
  G.$$('.map-node', table).forEach((g) => {
    const id = g.getAttribute('data-id');
    if (!avail.has(id)) return;
    const go = () => { G.sfx('click'); onPick(id); };
    g.addEventListener('click', go);
    g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
  });
  // scroll the current row into view
  const wrap = G.$('#map-wrap');
  requestAnimationFrame(() => {
    const svgEl = table.querySelector('svg');
    if (!svgEl) return;
    const k = svgEl.getBoundingClientRect().height / VH;
    wrap.scrollTop = Math.max(0, cur.y * k - wrap.clientHeight * 0.62);
  });
};
