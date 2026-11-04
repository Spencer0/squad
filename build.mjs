// Builds dist/index.html: one self-contained file with all data, CSS and JS inlined.
// Usage: node build.mjs
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');

const DATA = ['config', 'classes', 'enemies', 'items', 'boons', 'chapters', 'meta', 'events'];
const JS = ['util', 'audio', 'art', 'state', 'boons', 'timing', 'battle', 'map', 'screens', 'main'];

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
