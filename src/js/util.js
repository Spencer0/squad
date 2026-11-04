const G = (window.G = window.G || {});
const D = (G.D = window.GAME_DATA);

G.$ = (s, r = document) => r.querySelector(s);
G.$$ = (s, r = document) => Array.from(r.querySelectorAll(s));
G.rand = () => Math.random();
G.ri = (a, b) => a + Math.floor(Math.random() * (b - a + 1));
G.pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
G.clamp = (v, a, b) => Math.max(a, Math.min(b, v));
G.lerp = (a, b, t) => a + (b - a) * t;
G.shuffle = (arr) => {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
};
G.weighted = (items, wfn) => {
  const ws = items.map(wfn);
  const tot = ws.reduce((s, w) => s + w, 0);
  if (tot <= 0) return items[0];
  let r = Math.random() * tot;
  for (let i = 0; i < items.length; i++) {
    r -= ws[i];
    if (r <= 0) return items[i];
  }
  return items[items.length - 1];
};
G.now = () => performance.now();

// Animation pacing. Fast mode / test mode shorten every scripted wait.
G.speed = 1;
G.wait = (ms) => new Promise((r) => setTimeout(r, Math.max(0, ms * G.speed)));

G.el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    e.appendChild(typeof kid === 'string' || typeof kid === 'number' ? document.createTextNode(String(kid)) : kid);
  }
  return e;
};

G.esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
G.pct = (v) => `${Math.round(v * 100)}%`;

G.toast = (msg, ms = 1800) => {
  const t = G.$('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(G._toastT);
  G._toastT = setTimeout(() => (t.hidden = true), ms);
};

G.storage = {
  get(key, def) {
    try {
      const v = localStorage.getItem(key);
      return v ? JSON.parse(v) : def;
    } catch (e) {
      return def;
    }
  },
  set(key, val) {
    try {
      localStorage.setItem(key, JSON.stringify(val));
    } catch (e) {
      /* storage unavailable: play continues without saving */
    }
  },
  del(key) {
    try {
      localStorage.removeItem(key);
    } catch (e) {}
  },
};

G.fmtTime = (ms) => {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};
