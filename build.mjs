// Builds dist/index.html: one self-contained file with all data, CSS and JS inlined.
// Usage: node build.mjs
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');

const DATA = ['config', 'units', 'heroes', 'enemies', 'items', 'boons', 'chapters', 'meta', 'events', 'world'];
const JS = ['util', 'audio', 'art', 'state', 'boons', 'battle', 'map', 'screens', 'main'];

const data = {};
for (const name of DATA) data[name] = JSON.parse(read(`./data/${name}.json`));

// Optional pre-rendered 3D sprites (tools/blender/render_sprites.py), inlined as data URIs.
data.sprites = {};
const spriteMeta = new URL('./assets/sprites/sprites.json', import.meta.url);
if (existsSync(spriteMeta)) {
  const meta = JSON.parse(readFileSync(spriteMeta, 'utf8'));
  for (const [key, s] of Object.entries(meta)) {
    const file = new URL(`./assets/sprites/${s.file}`, import.meta.url);
    if (!existsSync(file)) continue;
    data.sprites[key] = { src: `data:image/png;base64,${readFileSync(file).toString('base64')}`, muzzle: s.muzzle || null };
  }
}

// Blender renders: squad figures, backdrops, world maps
const b64 = (path, mime) => `data:${mime};base64,${readFileSync(new URL(path, import.meta.url)).toString('base64')}`;
const has = (path) => existsSync(new URL(path, import.meta.url));
data.assets = { units: {}, bg: { files: {}, stations: null }, maps: {} };
if (has('./assets/units/units.json')) {
  for (const [k, u] of Object.entries(JSON.parse(read('./assets/units/units.json')))) {
    const entry = { canvas: u.canvas, muzzle: u.muzzle || null };
    if (u.idle && has(`./assets/units/${u.idle}`)) entry.idle = b64(`./assets/units/${u.idle}`, 'image/png');
    if (u.attack && has(`./assets/units/${u.attack}`)) entry.attack = b64(`./assets/units/${u.attack}`, 'image/png');
    if (entry.idle) data.assets.units[k] = entry;
  }
  // the colossus is a big unit drawn like the vehicles
  const col = data.assets.units.colossus;
  if (col) { data.sprites.colossus = { src: col.idle, muzzle: col.muzzle }; delete data.assets.units.colossus; }
}
if (has('./assets/bg/bg.json')) {
  const meta = JSON.parse(read('./assets/bg/bg.json'));
  const list = Array.isArray(meta) ? meta : meta.files || Object.entries(meta).filter(([k]) => k !== 'stations').map(([name, v]) => ({ name, ...(typeof v === 'object' ? v : {}) }));
  for (const f of list) {
    const name = f.name || f.id;
    const file = f.file || `${name}.jpg`;
    if (name && has(`./assets/bg/${file}`)) data.assets.bg.files[name.replace(/\.jpg$/, '')] = b64(`./assets/bg/${file}`, 'image/jpeg');
  }
  data.assets.bg.stations = meta.stations || (meta.base && meta.base.stations) || null;
}
if (has('./assets/maps/maps.json')) {
  for (const [k, m] of Object.entries(JSON.parse(read('./assets/maps/maps.json')))) {
    if (has(`./assets/maps/${m.file}`)) data.assets.maps[k] = { src: b64(`./assets/maps/${m.file}`, 'image/jpeg'), w: m.w, h: m.h, cities: m.cities };
  }
}

const js = JS.map((name) => `// ---- ${name}.js ----\n${read(`./src/js/${name}.js`)}`).join('\n');
const css = read('./src/style.css');
let html = read('./src/index.html');

const dataScript = `window.GAME_DATA = ${JSON.stringify(data)};`;
html = html
  .replace('/*__CSS__*/', () => css)
  .replace('/*__DATA__*/', () => dataScript)
  .replace('/*__JS__*/', () => `(function(){\n'use strict';\n${js}\n})();`);

mkdirSync(new URL('./dist/', import.meta.url), { recursive: true });
// artifact.html: page body only (the Claude artifact host adds the document skeleton).
writeFileSync(new URL('./dist/artifact.html', import.meta.url), html);
// index.html: a full standalone document for opening locally or hosting anywhere.
const full = `<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n</head>\n<body>\n${html}\n</body>\n</html>\n`;
writeFileSync(new URL('./dist/index.html', import.meta.url), full);
console.log(`dist/index.html + dist/artifact.html written (${(full.length / 1024).toFixed(1)} KB)`);
