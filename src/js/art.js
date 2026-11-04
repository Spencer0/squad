// Procedural art: chunky cel-shaded soldiers, vehicles, painted backdrops, portraits and icons.
// Every unit is drawn facing right with its feet at (0,0); enemies are mirrored by the caller.
G.art = (() => {
  const P = {
    olive: '#5f6c35', oliveD: '#47512a', oliveL: '#7a8846', khaki: '#b3a26f', khakiD: '#8d7e52',
    skin: '#e2b48a', skinD: '#c08f66', boot: '#2f241a', brown: '#6b4a2b', brownD: '#4b331d', metal: '#2c2f2c', metalL: '#5a5f5a',
    grey: '#6e736a', greyD: '#545950', greyL: '#8b9086', mask: '#3a3d37', lens: '#b7c9ad', glow: '#6dffb4',
    white: '#efe9d6', red: '#9b3a2a', line: '#1b1a14',
  };
  const LW = 3;

  const rr = (c, x, y, w, h, r) => {
    r = Math.min(r, Math.abs(w) / 2, Math.abs(h) / 2);
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
  };
  const fillStroke = (c, fill, lw = LW) => {
    c.fillStyle = fill;
    c.fill();
    c.lineWidth = lw;
    c.strokeStyle = P.line;
    c.stroke();
  };
  const shape = (c, fill, fn, lw = LW) => { c.beginPath(); fn(); fillStroke(c, fill, lw); };
  const circle = (c, x, y, r, fill, lw = LW) => { c.beginPath(); c.arc(x, y, r, 0, Math.PI * 2); fillStroke(c, fill, lw); };
  const limb = (c, x1, y1, x2, y2, w, col) => {
    c.lineCap = 'round';
    c.strokeStyle = P.line; c.lineWidth = w + LW * 2;
    c.beginPath(); c.moveTo(x1, y1); c.lineTo(x2, y2); c.stroke();
    c.strokeStyle = col; c.lineWidth = w;
    c.beginPath(); c.moveTo(x1, y1); c.lineTo(x2, y2); c.stroke();
  };
  // soft highlight band to fake cel shading
  const shade = (c, fn, col = '#ffffff', a = 0.12) => { c.save(); c.globalAlpha = a; c.fillStyle = col; c.beginPath(); fn(); c.fill(); c.restore(); };

  // ---------- weapons (drawn at the hand, pointing +x) ----------
  function weapon(c, kind, flash) {
    if (kind === 'rifle' || kind === 'carbine' || kind === 'sniper') {
      const L = kind === 'carbine' ? 44 : kind === 'sniper' ? 70 : 58;
      shape(c, P.brown, () => { c.moveTo(-22, -4); c.lineTo(6, -6); c.lineTo(L - 18, -5); c.lineTo(L - 18, 2); c.lineTo(4, 3); c.lineTo(-20, 8); c.closePath(); }, 2.5);
      rr(c, 0, -9, L, 5, 2); fillStroke(c, P.metal, 2.5);
      if (kind === 'sniper') { rr(c, 8, -17, 26, 7, 3); fillStroke(c, P.metal, 2.5); circle(c, 34, -13.5, 4, P.lens, 2); }
      if (flash) muzzle(c, L + 2, -6.5, 1);
    } else if (kind === 'mg') {
      rr(c, -20, -6, 26, 12, 3); fillStroke(c, P.brown, 2.5);
      rr(c, 0, -11, 46, 13, 3); fillStroke(c, P.metal, 2.5);
      rr(c, 40, -8, 30, 5, 2); fillStroke(c, P.metalL, 2.5);
      rr(c, 12, 2, 14, 12, 2); fillStroke(c, P.olive, 2.5);
      limb(c, 52, -3, 46, 18, 2, P.metal); limb(c, 52, -3, 60, 18, 2, P.metal);
      if (flash) muzzle(c, 72, -5.5, 1.3);
    } else if (kind === 'trench') {
      shape(c, P.brown, () => { c.moveTo(-20, -3); c.lineTo(4, -6); c.lineTo(20, -4); c.lineTo(20, 3); c.lineTo(2, 4); c.lineTo(-18, 9); c.closePath(); }, 2.5);
      rr(c, 2, -10, 44, 7, 2); fillStroke(c, P.metal, 2.5);
      rr(c, 14, -3, 18, 5, 2); fillStroke(c, P.brownD, 2);
      if (flash) muzzle(c, 48, -6.5, 1.5);
    } else if (kind === 'pistol') {
      rr(c, 0, -8, 22, 7, 2); fillStroke(c, P.metal, 2.5);
      rr(c, 2, -2, 7, 11, 2); fillStroke(c, P.brownD, 2.5);
      if (flash) muzzle(c, 24, -4.5, 0.8);
    } else if (kind === 'flamer') {
      rr(c, -6, -7, 50, 9, 3); fillStroke(c, P.metal, 2.5);
      rr(c, -4, 0, 10, 12, 2); fillStroke(c, P.brownD, 2.5);
      c.fillStyle = '#ffb347'; c.beginPath(); c.arc(47, -3, 3 + Math.random() * 1.5, 0, 7); c.fill();
      if (flash) flame(c, 48, -3);
    } else if (kind === 'club') {
      limb(c, -6, 4, 54, -10, 7, P.brown);
      for (let i = 0; i < 4; i++) { c.fillStyle = P.metalL; c.beginPath(); c.arc(40 + i * 4, -7 - i, 3, 0, 7); c.fill(); }
    } else if (kind === 'grenade') {
      limb(c, 0, 0, 0, -26, 4, P.brown);
      rr(c, -6, -40, 12, 16, 3); fillStroke(c, P.greyD, 2.5);
    }
  }
  function muzzle(c, x, y, s) {
    c.save(); c.translate(x, y); c.scale(s, s);
    c.fillStyle = '#fff3b0'; c.beginPath();
    c.moveTo(0, 0); c.lineTo(14, -9); c.lineTo(12, -2); c.lineTo(28, 0); c.lineTo(12, 3); c.lineTo(15, 10); c.closePath(); c.fill();
    c.fillStyle = '#ffb347'; c.beginPath(); c.arc(4, 0, 6, 0, 7); c.fill();
    c.restore();
  }
  function flame(c, x, y) {
    const g = c.createLinearGradient(x, y, x + 150, y);
    g.addColorStop(0, '#fff2a8'); g.addColorStop(0.3, '#ffb347'); g.addColorStop(0.8, '#d9480f'); g.addColorStop(1, 'rgba(120,30,10,0)');
    c.fillStyle = g; c.beginPath(); c.moveTo(x, y - 3);
    c.quadraticCurveTo(x + 80, y - 30 - Math.random() * 8, x + 150, y - 12);
    c.quadraticCurveTo(x + 90, y + 20 + Math.random() * 8, x, y + 4); c.fill();
  }

  // ---------- soldiers ----------
  const ALLY_GEAR = {
    rifleman: { weapon: 'rifle' }, mg: { weapon: 'mg', belt: true }, medic: { weapon: 'carbine', medic: true },
    sniper: { weapon: 'sniper', hood: true }, sapper: { weapon: 'trench', satchels: true }, veteran: { weapon: 'rifle', chevrons: true, scarf: true },
  };
  const ENEMY_GEAR = {
    infantry: { weapon: 'rifle' }, grenadier: { weapon: 'rifle', grenadeArm: true }, flamer: { weapon: 'flamer', tanks: true },
    ski: { weapon: 'carbine', winter: true, skis: true }, officer: { weapon: 'pistol', cap: true }, shock: { weapon: 'club', occult: true, bulky: true },
    mortar: { weapon: 'none', mortar: true },
  };

  function soldier(c, gear, enemy, pose, t, flash) {
    const coat = enemy ? (gear.winter ? '#d9dde0' : gear.cap ? '#4d524a' : P.grey) : P.olive;
    const coatD = enemy ? (gear.winter ? '#aab1b6' : P.greyD) : P.oliveD;
    const helm = enemy ? (gear.winter ? '#e7ebee' : P.greyD) : '#55602f';
    const trouser = enemy ? (gear.winter ? '#c6ccd0' : P.greyD) : P.khakiD;
    const crouch = pose === 'cover' || gear.mortar ? 22 : 0;
    const bob = pose === 'idle' ? Math.sin(t * 2.4) * 1.5 : 0;
    const lean = pose === 'attack' ? 0.08 : pose === 'hurt' ? -0.16 : 0;
    c.save();
    if (gear.bulky) c.scale(1.12, 1);
    // skis
    if (gear.skis) { rr(c, -34, -4, 82, 5, 2); fillStroke(c, P.brown, 2); }
    // legs
    const legTop = -52 + crouch;
    if (crouch) {
      limb(c, -8, legTop, -18, -20, 13, trouser); limb(c, -18, -20, -4, -6, 12, trouser);
      limb(c, 8, legTop, 20, -26, 13, trouser); limb(c, 20, -26, 22, -6, 12, trouser);
    } else {
      limb(c, -7, legTop, -9, -10, 14, trouser); limb(c, 8, legTop, 12, -10, 14, trouser);
    }
    rr(c, -17, -12, 18, 12, 4); fillStroke(c, P.boot);
    rr(c, 4, -12, 20, 12, 4); fillStroke(c, P.boot);
    c.translate(0, crouch + bob);
    c.rotate(lean);
    // back gear
    if (gear.tanks) { rr(c, -32, -104, 14, 46, 6); fillStroke(c, '#6b5b3a'); rr(c, -24, -100, 14, 46, 6); fillStroke(c, '#7d6a44'); }
    if (gear.medic && !enemy) { rr(c, -30, -82, 16, 24, 4); fillStroke(c, P.khaki); }
    // torso
    if (enemy && !gear.mortar) {
      shape(c, coat, () => { c.moveTo(-18, -104); c.lineTo(20, -104); c.lineTo(28, -34); c.lineTo(-26, -34); c.closePath(); });
      shade(c, () => { c.moveTo(4, -100); c.lineTo(18, -100); c.lineTo(24, -40); c.lineTo(10, -40); c.closePath(); });
      c.strokeStyle = P.line; c.lineWidth = 2; c.beginPath(); c.moveTo(1, -100); c.lineTo(2, -36); c.stroke();
      rr(c, -21, -76, 44, 7, 2); fillStroke(c, '#2d2a22', 2);
    } else {
      rr(c, -19, -106, 38, 56, 9); fillStroke(c, coat);
      shade(c, () => rr(c, 2, -102, 13, 48, 6));
      rr(c, -20, -64, 40, 7, 2); fillStroke(c, P.khaki, 2);
      if (!enemy) { rr(c, -15, -97, 10, 10, 2); fillStroke(c, P.khaki, 2); rr(c, 5, -97, 10, 10, 2); fillStroke(c, P.khaki, 2); }
    }
    if (gear.belt) { c.save(); c.strokeStyle = '#c9a54a'; c.lineWidth = 5; c.setLineDash([3, 2]); c.beginPath(); c.moveTo(-16, -104); c.lineTo(16, -60); c.stroke(); c.restore(); }
    if (gear.satchels) { for (let i = 0; i < 2; i++) { rr(c, -16 + i * 14, -92, 12, 16, 2); fillStroke(c, '#8a6a3a', 2); } }
    if (gear.scarf) { rr(c, -14, -110, 28, 8, 3); fillStroke(c, '#8a2f24', 2); }
    // head
    const hx = 2, hy = -120;
    if (gear.occult || (enemy && !gear.cap)) {
      circle(c, hx, hy, 16, P.mask);
      const lc = gear.occult ? P.glow : P.lens;
      if (gear.occult) { c.save(); c.shadowColor = P.glow; c.shadowBlur = 14; }
      circle(c, hx + 9, hy - 3, 5, lc, 2); circle(c, hx - 1, hy - 3, 5, lc, 2);
      if (gear.occult) c.restore();
      rr(c, hx + 6, hy + 5, 10, 13, 3); fillStroke(c, '#2b2d28', 2);
    } else if (gear.cap) {
      circle(c, hx, hy, 15, P.skin);
      c.fillStyle = P.line; c.fillRect(hx + 7, hy - 4, 3, 3);
    } else {
      circle(c, hx, hy, 15, P.skin);
      shade(c, () => c.arc(hx - 5, hy + 2, 9, 0, 7), P.skinD, 0.5);
      c.fillStyle = P.line; c.fillRect(hx + 7, hy - 3, 3, 4);
      c.fillRect(hx + 4, hy + 6, 7, 2);
    }
    // helmet / headgear
    if (gear.hood) {
      shape(c, '#4f5a2a', () => { c.moveTo(hx - 22, hy + 10); c.quadraticCurveTo(hx - 22, hy - 30, hx + 4, hy - 30); c.quadraticCurveTo(hx + 26, hy - 28, hx + 20, hy - 8); c.lineTo(hx + 10, hy - 12); c.quadraticCurveTo(hx - 2, hy - 8, hx - 8, hy + 14); c.closePath(); });
      c.strokeStyle = '#7d8a44'; c.lineWidth = 2;
      for (let i = 0; i < 7; i++) { c.beginPath(); c.moveTo(hx - 20 + i * 6, hy - 22 + (i % 2) * 6); c.lineTo(hx - 24 + i * 6, hy - 6 + (i % 3) * 4); c.stroke(); }
    } else if (gear.cap) {
      shape(c, '#3e433b', () => { c.moveTo(hx - 17, hy - 9); c.quadraticCurveTo(hx - 12, hy - 30, hx + 10, hy - 27); c.lineTo(hx + 18, hy - 12); c.closePath(); });
      rr(c, hx - 4, hy - 13, 26, 5, 2); fillStroke(c, P.line, 1);
      c.fillStyle = '#c0c4b8'; c.fillRect(hx + 1, hy - 21, 6, 4);
    } else if (enemy) {
      // Vossmark helmet: tall dome with a flared rear skirt and a crest ridge
      shape(c, helm, () => { c.moveTo(hx - 24, hy + 4); c.lineTo(hx - 18, hy - 12); c.quadraticCurveTo(hx - 10, hy - 34, hx + 8, hy - 32); c.quadraticCurveTo(hx + 22, hy - 28, hx + 20, hy - 8); c.lineTo(hx + 22, hy - 4); c.lineTo(hx - 6, hy - 6); c.lineTo(hx - 12, hy + 6); c.closePath(); });
      rr(c, hx - 4, hy - 37, 8, 10, 3); fillStroke(c, helm, 2);
      shade(c, () => c.arc(hx + 4, hy - 22, 7, 0, 7));
    } else {
      // Allied helmet: wide oversized dome with a flat brim
      shape(c, helm, () => { c.ellipse(hx, hy - 12, 24, 19, 0, Math.PI, 0); c.closePath(); });
      rr(c, hx - 30, hy - 14, 60, 7, 3); fillStroke(c, helm);
      shade(c, () => c.ellipse(hx + 6, hy - 22, 9, 6, 0, 0, 7));
      c.strokeStyle = '#3b4220'; c.lineWidth = 2; c.beginPath(); c.moveTo(hx - 18, hy - 14); c.lineTo(hx - 14, hy - 26); c.stroke();
    }
    // arms + weapon
    const shoulder = [-2, -96];
    const aim = pose === 'attack';
    const hand = gear.grenadeArm && aim ? [-14, -126] : aim ? [26, -88] : [18, -74];
    if (gear.mortar) {
      // mortar tube on the ground in front
      c.save(); c.translate(36, -crouch - bob); c.rotate(-0.85);
      rr(c, -4, -60, 13, 62, 4); fillStroke(c, P.metal); c.restore();
      limb(c, 22, -crouch - bob, 52, -crouch - bob, 3, P.metal);
      limb(c, shoulder[0], shoulder[1], 26, -84, 10, coatD);
      if (flash) { c.save(); c.translate(76, -66 - crouch); c.fillStyle = '#fff3b0'; c.beginPath(); c.arc(0, 0, 10, 0, 7); c.fill(); c.restore(); }
    } else {
      limb(c, shoulder[0], shoulder[1], hand[0], hand[1], 11, enemy ? coatD : P.oliveD);
      if (gear.medic && !enemy) { c.save(); c.translate(shoulder[0] + (hand[0] - shoulder[0]) * 0.35, shoulder[1] + (hand[1] - shoulder[1]) * 0.35); c.fillStyle = P.white; c.fillRect(-6, -6, 12, 9); c.fillStyle = P.olive; c.fillRect(-1.5, -5, 3, 7); c.fillRect(-4.5, -2.5, 9, 3); c.restore(); }
      if (gear.chevrons) { c.save(); c.translate(shoulder[0] + 5, shoulder[1] + 6); c.strokeStyle = '#d8c07a'; c.lineWidth = 2; for (let i = 0; i < 3; i++) { c.beginPath(); c.moveTo(-5, i * 4); c.lineTo(0, i * 4 - 4); c.lineTo(5, i * 4); c.stroke(); } c.restore(); }
      circle(c, hand[0], hand[1], 6, gear.occult || (enemy && !gear.cap) ? '#3a3a32' : P.skin, 2);
      c.save(); c.translate(hand[0] - 4, hand[1] + 2);
      if (gear.grenadeArm && aim) { c.rotate(-0.5); weapon(c, 'grenade'); }
      else if (gear.weapon !== 'none') { c.rotate(aim ? 0 : 0.35); weapon(c, gear.weapon, flash); }
      c.restore();
    }
    c.restore();
  }

  // ---------- vehicles & monsters ----------
  function track(c, x, y, w, h) {
    rr(c, x, y, w, h, h / 2); fillStroke(c, '#2a2b27');
    const n = Math.floor(w / 26);
    for (let i = 0; i < n; i++) circle(c, x + h / 2 + i * ((w - h) / (n - 1)), y + h / 2, h / 2 - 5, '#4a4c46', 2);
  }
  function tank(c, t, relic, flash) {
    const S = relic ? 1.18 : 1;
    c.save(); c.scale(S, S);
    const body = relic ? '#3e433c' : '#6d7268';
    track(c, -110, -38, 220, 38);
    shape(c, body, () => { c.moveTo(-112, -40); c.lineTo(-100, -78); c.lineTo(84, -78); c.lineTo(116, -48); c.lineTo(108, -38); c.closePath(); });
    shade(c, () => { c.moveTo(-96, -74); c.lineTo(80, -74); c.lineTo(88, -66); c.lineTo(-98, -66); c.closePath(); });
    // turret
    shape(c, body, () => { c.moveTo(-52, -78); c.lineTo(-44, -116); c.lineTo(34, -116); c.lineTo(50, -78); c.closePath(); });
    rr(c, 44, -104, relic ? 120 : 104, 10, 3); fillStroke(c, '#3a3d38');
    rr(c, -20, -128, 30, 13, 4); fillStroke(c, body);
    if (!relic) { c.fillStyle = '#5a5f4a'; c.beginPath(); c.ellipse(-40, -60, 22, 10, 0.2, 0, 7); c.ellipse(40, -58, 18, 9, -0.2, 0, 7); c.fill(); }
    if (relic) {
      const pulse = 0.55 + 0.45 * Math.sin(t * 3);
      c.save(); c.shadowColor = P.glow; c.shadowBlur = 18 * pulse; c.strokeStyle = `rgba(109,255,180,${0.5 + pulse * 0.5})`; c.lineWidth = 3;
      const runes = [[-80, -60], [-50, -58], [-20, -62], [10, -58], [40, -60], [-24, -100], [4, -100]];
      runes.forEach(([x, y], i) => { c.beginPath(); c.moveTo(x, y - 7); c.lineTo(x + 6, y); c.lineTo(x, y + 7); if (i % 2) { c.moveTo(x - 4, y - 3); c.lineTo(x + 8, y - 3); } else { c.moveTo(x - 3, y); c.lineTo(x + 3, y + 6); } c.stroke(); });
      c.fillStyle = `rgba(109,255,180,${0.35 * pulse})`; c.beginPath(); c.ellipse(-6, -130, 16, 6, 0, 0, 7); c.fill();
      c.restore();
      c.strokeStyle = '#8d8f86'; c.lineWidth = 3; c.setLineDash([5, 3]); c.beginPath(); c.moveTo(-100, -72); c.quadraticCurveTo(-10, -50, 80, -72); c.stroke(); c.setLineDash([]);
    }
    if (flash) muzzle(c, 44 + (relic ? 122 : 106), -99, 2.2);
    c.restore();
  }
  function armoredCar(c, t, flash) {
    circle(c, -56, -18, 18, '#2a2b27'); circle(c, -56, -18, 8, '#5a5c55', 2);
    circle(c, 52, -18, 18, '#2a2b27'); circle(c, 52, -18, 8, '#5a5c55', 2);
    shape(c, P.grey, () => { c.moveTo(-90, -24); c.lineTo(-84, -70); c.lineTo(40, -74); c.lineTo(92, -46); c.lineTo(88, -24); c.closePath(); });
    shade(c, () => { c.moveTo(-80, -66); c.lineTo(38, -70); c.lineTo(46, -62); c.lineTo(-80, -60); c.closePath(); });
    c.fillStyle = P.line; c.fillRect(46, -60, 22, 6);
    shape(c, P.greyD, () => { c.moveTo(-34, -72); c.lineTo(-26, -98); c.lineTo(18, -98); c.lineTo(24, -72); c.closePath(); });
    rr(c, 18, -92, 52, 7, 2); fillStroke(c, P.metal);
    if (flash) muzzle(c, 72, -88.5, 1.4);
  }
  function bunker(c, t, flash) {
    for (let i = 0; i < 7; i++) { rr(c, -110 + i * 31, -24, 34, 24, 10); fillStroke(c, '#8d7e52', 2.5); }
    shape(c, '#8e8c80', () => { c.moveTo(-96, -20); c.quadraticCurveTo(-90, -116, 0, -118); c.quadraticCurveTo(90, -116, 96, -20); c.closePath(); });
    shade(c, () => { c.moveTo(-60, -90); c.quadraticCurveTo(0, -116, 60, -90); c.lineTo(50, -84); c.quadraticCurveTo(0, -104, -50, -84); c.closePath(); });
    c.fillStyle = '#7a786c'; [[-50, -50], [30, -40], [-10, -88], [60, -70]].forEach(([x, y]) => { c.beginPath(); c.arc(x, y, 6, 0, 7); c.fill(); });
    rr(c, -40, -74, 96, 16, 5); fillStroke(c, '#151510');
    rr(c, 30, -70, 60, 7, 2); fillStroke(c, P.metal);
    if (flash) muzzle(c, 92, -66.5, 1.4);
  }
  function horror(c, t, flash) {
    const sway = Math.sin(t * 1.4) * 6;
    c.save();
    // halo
    const g = c.createRadialGradient(0, -190, 10, 0, -190, 120);
    g.addColorStop(0, 'rgba(210,255,230,0.35)'); g.addColorStop(1, 'rgba(210,255,230,0)');
    c.fillStyle = g; c.beginPath(); c.arc(0, -190, 120, 0, 7); c.fill();
    // tentacles
    for (let i = 0; i < 6; i++) {
      const a = -1 + i * 0.4;
      const ph = t * 2 + i;
      c.lineCap = 'round';
      c.strokeStyle = P.line; c.lineWidth = 16;
      c.beginPath(); c.moveTo(a * 30, -80);
      c.quadraticCurveTo(a * 110 + Math.sin(ph) * 20, -70 + Math.cos(ph) * 30, a * 150 + Math.sin(ph * 1.3) * 25, -10 + Math.sin(ph) * 10);
      c.stroke();
      c.strokeStyle = '#2b2a33'; c.lineWidth = 10; c.stroke();
    }
    // robed body
    shape(c, '#1d1c24', () => { c.moveTo(-70, 0); c.quadraticCurveTo(-80 + sway, -140, -30, -200); c.quadraticCurveTo(0, -230, 30, -200); c.quadraticCurveTo(80 + sway, -140, 70, 0); c.closePath(); });
    shade(c, () => { c.moveTo(-30, -190); c.quadraticCurveTo(0, -216, 26, -190); c.lineTo(20, -40); c.lineTo(-20, -40); c.closePath(); }, '#cfe', 0.06);
    // face: pale mask with many eyes
    shape(c, '#d9d4c3', () => c.ellipse(0, -186, 24, 30, 0, 0, 7));
    c.save(); c.shadowColor = P.glow; c.shadowBlur = 16;
    const eyes = [[-9, -194], [9, -194], [0, -178], [-12, -172], [12, -172], [0, -204]];
    eyes.forEach(([x, y], i) => { const o = 0.6 + 0.4 * Math.sin(t * 3 + i); c.fillStyle = `rgba(109,255,180,${o})`; c.beginPath(); c.arc(x, y, 3.5, 0, 7); c.fill(); });
    c.restore();
    // hands
    circle(c, -54 + sway, -110, 12, '#d9d4c3'); circle(c, 54 + sway, -112, 12, '#d9d4c3');
    if (flash) { c.fillStyle = 'rgba(109,255,180,0.5)'; c.beginPath(); c.arc(0, -186, 60, 0, 7); c.fill(); }
    c.restore();
  }

  const SIZES = {
    soldier: { w: 70, h: 150 }, infantry: { w: 70, h: 150 }, grenadier: { w: 70, h: 150 }, flamer: { w: 76, h: 150 }, ski: { w: 80, h: 150 },
    officer: { w: 70, h: 150 }, mortar: { w: 100, h: 120 }, shock: { w: 92, h: 190 },
    armoredcar: { w: 190, h: 105 }, bunker: { w: 220, h: 125 }, tank: { w: 240, h: 135 }, relictank: { w: 300, h: 160 }, horror: { w: 260, h: 260 },
  };
  const sprites = {};
  const spriteInfo = (art) => G.art.sprites && G.art.sprites[art];
  const size = (art) => {
    const base = SIZES[art] || SIZES.soldier;
    const sp = spriteInfo(art);
    if (sp && sp.img && sp.img.width) return { w: base.w, h: Math.round((base.w * sp.img.height) / sp.img.width) };
    return base;
  };
  let tintCv = null;

  // u: { art, side, cls }  o: { pose, t, flash, alpha, tint }
  function drawUnit(c, u, x, y, s, o = {}) {
    if (o.tint) {
      // draw into an offscreen canvas so the tint only covers the unit itself
      const sz = size(u.art);
      const pad = 40;
      const w = Math.ceil(sz.w * s * 1.6 + pad * 2), h = Math.ceil(sz.h * s * 1.25 + pad * 2);
      if (!tintCv) tintCv = document.createElement('canvas');
      const tr = c.getTransform ? c.getTransform() : { a: 1 };
      const k = Math.max(1, Math.min(3, Math.abs(tr.a) || 1));
      tintCv.width = Math.ceil(w * k); tintCv.height = Math.ceil(h * k);
      const tc = tintCv.getContext('2d');
      tc.setTransform(k, 0, 0, k, 0, 0);
      drawUnit(tc, u, w / 2, h - pad, s, { ...o, tint: null, alpha: undefined });
      tc.globalCompositeOperation = 'source-atop';
      tc.fillStyle = o.tint; tc.fillRect(0, 0, w, h);
      tc.globalCompositeOperation = 'source-over';
      c.save();
      if (o.alpha !== undefined) c.globalAlpha = o.alpha;
      c.drawImage(tintCv, x - w / 2, y - (h - pad), w, h);
      c.restore();
      return;
    }
    const pose = o.pose || 'idle';
    const t = o.t || 0;
    c.save();
    c.translate(x, y);
    // ground shadow
    const sz = size(u.art);
    c.fillStyle = 'rgba(0,0,0,0.32)';
    c.beginPath(); c.ellipse(0, 2, sz.w * 0.55 * s, 9 * s, 0, 0, 7); c.fill();
    c.scale(s * (u.side === 'enemy' ? -1 : 1), s);
    if (o.alpha !== undefined) c.globalAlpha = o.alpha;
    if (pose === 'down') { c.translate(-40, -6); c.rotate(-Math.PI / 2 + 0.1); c.translate(0, 30); }
    const flash = o.flash;
    const sp = u.side === 'enemy' && spriteInfo(u.art);
    if (sp && sp.img) {
      const sz = size(u.art);
      const bob = Math.sin(t * 2) * 1.2;
      c.drawImage(sp.img, -sz.w / 2, -sz.h + bob, sz.w, sz.h);
      if (u.art === 'relictank' || u.art === 'horror') {
        const pulse = 0.5 + 0.5 * Math.sin(t * 3);
        c.globalCompositeOperation = 'lighter'; c.globalAlpha = (o.alpha ?? 1) * 0.22 * pulse;
        c.drawImage(sp.img, -sz.w / 2, -sz.h + bob, sz.w, sz.h);
        c.globalCompositeOperation = 'source-over'; c.globalAlpha = o.alpha ?? 1;
      }
      if (flash && sp.muzzle) muzzle(c, -sz.w / 2 + sp.muzzle[0] * sz.w, -sz.h + sp.muzzle[1] * sz.h + bob, u.art === 'bunker' ? 1.4 : 2.2);
    } else if (u.side === 'ally') soldier(c, ALLY_GEAR[u.cls] || ALLY_GEAR.rifleman, false, pose, t, flash);
    else if (u.art === 'tank') tank(c, t, false, flash);
    else if (u.art === 'relictank') tank(c, t, true, flash);
    else if (u.art === 'armoredcar') armoredCar(c, t, flash);
    else if (u.art === 'bunker') bunker(c, t, flash);
    else if (u.art === 'horror') horror(c, t, flash);
    else {
      const sc = u.art === 'shock' ? 1.25 : 1;
      c.scale(sc, sc);
      soldier(c, ENEMY_GEAR[u.art] || ENEMY_GEAR.infantry, true, pose, t, flash);
    }
    c.restore();
  }

  // ---------- backdrops ----------
  function sky(c, w, h, top, mid, horizon) {
    const g = c.createLinearGradient(0, 0, 0, h * 0.72);
    g.addColorStop(0, top); g.addColorStop(0.6, mid); g.addColorStop(1, horizon);
    c.fillStyle = g; c.fillRect(0, 0, w, h);
  }
  function hills(c, w, base, amp, col, seed) {
    c.fillStyle = col; c.beginPath(); c.moveTo(0, base);
    for (let x = 0; x <= w; x += 20) c.lineTo(x, base - amp * (0.5 + 0.5 * Math.sin(x * 0.006 + seed) * Math.cos(x * 0.013 + seed * 2)));
    c.lineTo(w, base + 400); c.lineTo(0, base + 400); c.fill();
  }
  function strokes(c, w, h, y0, y1, cols, n, len) {
    for (let i = 0; i < n; i++) {
      c.globalAlpha = 0.08 + Math.random() * 0.1;
      c.strokeStyle = G.pick(cols); c.lineWidth = 2 + Math.random() * 5; c.lineCap = 'round';
      const x = Math.random() * w, y = y0 + Math.random() * (y1 - y0);
      c.beginPath(); c.moveTo(x, y); c.lineTo(x + (Math.random() - 0.3) * len, y + (Math.random() - 0.5) * 6); c.stroke();
    }
    c.globalAlpha = 1;
  }
  function ground(c, w, h, top, col, colD, cols) {
    const g = c.createLinearGradient(0, top, 0, h);
    g.addColorStop(0, col); g.addColorStop(1, colD);
    c.fillStyle = g; c.beginPath(); c.moveTo(0, top + 8);
    for (let x = 0; x <= w; x += 40) c.lineTo(x, top + Math.sin(x * 0.02) * 4);
    c.lineTo(w, h); c.lineTo(0, h); c.fill();
    strokes(c, w, h, top + 10, h, cols, 260, 60);
  }
  function ruin(c, x, base, w, hgt, col) {
    c.fillStyle = col; c.beginPath(); c.moveTo(x, base);
    c.lineTo(x, base - hgt); c.lineTo(x + w * 0.3, base - hgt); c.lineTo(x + w * 0.45, base - hgt * 0.7); c.lineTo(x + w * 0.6, base - hgt * 0.85);
    c.lineTo(x + w * 0.7, base - hgt * 0.55); c.lineTo(x + w, base - hgt * 0.6); c.lineTo(x + w, base); c.fill();
    c.fillStyle = 'rgba(255,190,120,0.18)';
    for (let i = 0; i < 3; i++) c.fillRect(x + w * (0.15 + i * 0.25), base - hgt * 0.45, w * 0.1, hgt * 0.14);
  }
  function pine(c, x, base, hgt, col, snow) {
    c.fillStyle = '#2b2219'; c.fillRect(x - 3, base - hgt * 0.2, 6, hgt * 0.2);
    for (let i = 0; i < 4; i++) {
      const y = base - hgt * 0.15 - i * hgt * 0.2, ww = hgt * (0.32 - i * 0.06);
      c.fillStyle = col; c.beginPath(); c.moveTo(x - ww, y); c.lineTo(x, y - hgt * 0.32); c.lineTo(x + ww, y); c.fill();
      if (snow) { c.fillStyle = snow; c.beginPath(); c.moveTo(x - ww * 0.6, y - hgt * 0.12); c.lineTo(x, y - hgt * 0.32); c.lineTo(x + ww * 0.5, y - hgt * 0.14); c.fill(); }
    }
  }

  const bgCache = {};
  function bg(key, w = 1000, h = 620) {
    const k = `${key}-${w}x${h}`;
    if (bgCache[k]) return bgCache[k];
    const cv = document.createElement('canvas');
    cv.width = w; cv.height = h;
    const c = cv.getContext('2d');
    const GY = h * 0.7;
    if (key === 'snow') {
      sky(c, w, h, '#4b5872', '#8f9cb0', '#d6c8b8');
      c.fillStyle = 'rgba(255,240,220,0.5)'; c.beginPath(); c.arc(w * 0.72, h * 0.3, 26, 0, 7); c.fill();
      hills(c, w, GY - 120, 60, '#a9b4c2', 1.2);
      for (let i = 0; i < 26; i++) pine(c, Math.random() * w, GY - 60 + Math.random() * 20, 90 + Math.random() * 60, '#56647a', '#c6d0dc');
      hills(c, w, GY - 40, 30, '#c9d2dc', 3);
      for (let i = 0; i < 14; i++) pine(c, Math.random() * w, GY - 10 + Math.random() * 10, 150 + Math.random() * 90, '#2f3d36', '#e4ecf2');
      ground(c, w, h, GY, '#e4eaf0', '#a9b6c4', ['#ffffff', '#9fb0c2', '#c9d4de']);
    } else if (key === 'village') {
      sky(c, w, h, '#2c2b45', '#7a4f5a', '#e09a5a');
      hills(c, w, GY - 110, 40, '#4a3f4a', 0.4);
      ruin(c, 40, GY - 20, 150, 170, '#3a3138'); ruin(c, 230, GY - 20, 110, 130, '#3f353b');
      // broken steeple
      c.fillStyle = '#33292f'; c.beginPath(); c.moveTo(420, GY - 20); c.lineTo(420, GY - 220); c.lineTo(445, GY - 270); c.lineTo(462, GY - 230); c.lineTo(470, GY - 20); c.fill();
      ruin(c, 520, GY - 20, 170, 150, '#3a3138'); ruin(c, 760, GY - 20, 200, 180, '#3f353b');
      c.fillStyle = 'rgba(60,50,55,0.5)'; for (let i = 0; i < 4; i++) { c.beginPath(); c.arc(100 + i * 260, GY - 70 - i * 10, 60, 0, 7); c.fill(); }
      ground(c, w, h, GY - 10, '#6b5a46', '#3b3024', ['#8a7458', '#4a3c2c', '#9b8466']);
      c.fillStyle = '#4a3d30'; for (let i = 0; i < 10; i++) { c.beginPath(); c.ellipse(Math.random() * w, GY + 10 + Math.random() * 20, 20 + Math.random() * 30, 8, 0, 0, 7); c.fill(); }
    } else {
      // hedgerow
      sky(c, w, h, '#33405a', '#8c6b6b', '#e8a865');
      hills(c, w, GY - 120, 50, '#5b6150', 0.8);
      hills(c, w, GY - 70, 40, '#4c5a3a', 2.1);
      for (let row = 0; row < 3; row++) {
        const y = GY - 60 + row * 24;
        for (let x = -20; x < w + 40; x += 34) { c.fillStyle = row === 2 ? '#2c3a22' : row ? '#34452a' : '#3e4f32'; c.beginPath(); c.arc(x + Math.random() * 10, y - Math.random() * 12, 26 + Math.random() * 10, 0, 7); c.fill(); }
      }
      for (let i = 0; i < 6; i++) { const x = Math.random() * w; c.fillStyle = '#2a3520'; c.beginPath(); c.arc(x, GY - 110 - Math.random() * 30, 40 + Math.random() * 20, 0, 7); c.fill(); c.fillStyle = '#2b2219'; c.fillRect(x - 4, GY - 90, 8, 40); }
      ground(c, w, h, GY - 10, '#6f7443', '#3c3f24', ['#8c8f55', '#4c5030', '#a39a62']);
      c.fillStyle = '#3d2e1e'; for (let x = 20; x < w; x += 90) c.fillRect(x, GY - 6, 5, 22);
    }
    // vignette
    const v = c.createRadialGradient(w / 2, h * 0.55, h * 0.3, w / 2, h * 0.55, w * 0.75);
    v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, 'rgba(0,0,0,0.45)');
    c.fillStyle = v; c.fillRect(0, 0, w, h);
    bgCache[k] = cv;
    return cv;
  }

  // ---------- portraits ----------
  const portraitCache = {};
  function portrait(u, sz = 96) {
    const k = `${u.side}-${u.cls || u.art}-${sz}`;
    if (portraitCache[k]) return portraitCache[k];
    const cv = document.createElement('canvas');
    cv.width = sz; cv.height = sz;
    const c = cv.getContext('2d');
    const g = c.createRadialGradient(sz / 2, sz * 0.4, 4, sz / 2, sz / 2, sz * 0.7);
    if (u.side === 'ally') { g.addColorStop(0, '#8b9558'); g.addColorStop(1, '#2f3620'); } else { g.addColorStop(0, '#8a5a48'); g.addColorStop(1, '#2d1712'); }
    c.fillStyle = g; c.fillRect(0, 0, sz, sz);
    const art = u.art;
    const big = ['tank', 'relictank', 'armoredcar', 'bunker', 'horror'].includes(art);
    if (big) {
      const s2 = size(art);
      const s = (sz * 0.95) / Math.max(s2.w, s2.h);
      drawUnit(c, u, sz / 2, sz / 2 + (s2.h * s) / 2, s, { t: 1 });
    } else {
      const s = sz / 62;
      const sc = art === 'shock' ? 1.25 : 1;
      drawUnit(c, u, sz / 2 - 2 * s, sz / 2 + 118 * s * sc, s, { t: 0 });
    }
    portraitCache[k] = cv.toDataURL();
    return portraitCache[k];
  }

  // ---------- base scene (logical 1000x560) ----------
  const BASE_W = 1000, BASE_H = 560;
  const STATIONS = {
    radio: { x: 845, y: 250, label: 'Radio Tent', sub: 'Start an operation' },
    command: { x: 470, y: 205, label: 'Command Post', sub: 'Command tree' },
    barracks: { x: 215, y: 200, label: 'Barracks', sub: 'Recruit soldiers' },
    armory: { x: 640, y: 300, label: 'Quartermaster', sub: 'Armory and base' },
    crate: { x: 360, y: 400, label: 'Relic Crate', sub: 'Unlocks and codex' },
  };
  function baseScene(c, t) {
    const w = BASE_W, h = BASE_H;
    const g = c.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, '#0e1424'); g.addColorStop(0.6, '#223048'); g.addColorStop(1, '#384a52');
    c.fillStyle = g; c.fillRect(0, 0, w, h);
    c.fillStyle = '#e8e2c8';
    for (let i = 0; i < 70; i++) { const x = (i * 137.5) % w, y = (i * 53.3) % (h * 0.45); c.globalAlpha = 0.3 + 0.3 * Math.sin(t * 2 + i); c.fillRect(x, y, 2, 2); }
    c.globalAlpha = 1;
    c.fillStyle = '#f2e9c9'; c.beginPath(); c.arc(140, 70, 26, 0, 7); c.fill();
    c.fillStyle = '#0e1424'; c.beginPath(); c.arc(152, 64, 24, 0, 7); c.fill();
    hills(c, w, 330, 50, '#1b2530', 0.3);
    // ground
    c.fillStyle = '#2f3a2a'; c.fillRect(0, 330, w, h);
    c.fillStyle = '#3c4834'; c.beginPath(); c.ellipse(500, 470, 520, 120, 0, 0, 7); c.fill();
    // barn (barracks)
    shape(c, '#5a2e22', () => { c.moveTo(110, 330); c.lineTo(110, 240); c.lineTo(215, 175); c.lineTo(320, 240); c.lineTo(320, 330); c.closePath(); });
    shape(c, '#3a1d16', () => { c.moveTo(185, 330); c.lineTo(185, 270); c.lineTo(245, 270); c.lineTo(245, 330); c.closePath(); });
    c.strokeStyle = '#d8c9a0'; c.lineWidth = 3; c.beginPath(); c.moveTo(185, 270); c.lineTo(245, 330); c.moveTo(245, 270); c.lineTo(185, 330); c.stroke();
    // farmhouse (command post)
    shape(c, '#8a8070', () => { c.moveTo(380, 330); c.lineTo(380, 235); c.lineTo(560, 235); c.lineTo(560, 330); c.closePath(); });
    shape(c, '#4a3226', () => { c.moveTo(365, 238); c.lineTo(470, 180); c.lineTo(575, 238); c.closePath(); });
    const lamp = 0.75 + 0.25 * Math.sin(t * 5);
    c.fillStyle = `rgba(255,200,110,${lamp})`; c.fillRect(405, 260, 30, 26); c.fillRect(505, 260, 30, 26);
    c.fillStyle = '#2a1d15'; c.fillRect(455, 280, 30, 50);
    // radio tent with antenna
    shape(c, '#6b7040', () => { c.moveTo(760, 330); c.lineTo(845, 250); c.lineTo(930, 330); c.closePath(); });
    c.strokeStyle = '#c9c3a8'; c.lineWidth = 3; c.beginPath(); c.moveTo(900, 330); c.lineTo(905, 160); c.stroke();
    c.fillStyle = `rgba(255,80,60,${0.5 + 0.5 * Math.sin(t * 4)})`; c.beginPath(); c.arc(905, 158, 5, 0, 7); c.fill();
    c.fillStyle = 'rgba(255,200,110,0.7)'; c.beginPath(); c.moveTo(830, 330); c.lineTo(845, 290); c.lineTo(860, 330); c.fill();
    // quartermaster tent + racks
    shape(c, '#7c7446', () => { c.moveTo(570, 380); c.lineTo(640, 300); c.lineTo(720, 380); c.closePath(); });
    for (let i = 0; i < 4; i++) limb(c, 590 + i * 10, 395, 596 + i * 10, 350, 3, P.brown);
    // jeep
    c.save(); c.translate(150, 430); c.scale(0.9, 0.9);
    circle(c, -40, -12, 14, '#1b1b18'); circle(c, 40, -12, 14, '#1b1b18');
    shape(c, P.olive, () => { c.moveTo(-60, -14); c.lineTo(-58, -42); c.lineTo(20, -44); c.lineTo(34, -32); c.lineTo(62, -30); c.lineTo(62, -14); c.closePath(); });
    c.fillStyle = '#e9e3cb'; c.beginPath(); c.arc(-10, -30, 7, 0, 7); c.fill(); c.restore();
    // sandbags
    for (let i = 0; i < 8; i++) { rr(c, 700 + i * 30, 420, 32, 20, 8); fillStroke(c, '#8d7e52', 2); }
    // relic crate
    rr(c, 320, 405, 80, 46, 3); fillStroke(c, '#5a4a30');
    c.save(); const pulse = 0.5 + 0.5 * Math.sin(t * 2.2); c.shadowColor = P.glow; c.shadowBlur = 20 * pulse;
    c.strokeStyle = `rgba(109,255,180,${0.4 + pulse * 0.5})`; c.lineWidth = 3; c.strokeRect(324, 409, 72, 38); c.restore();
    // campfire
    c.fillStyle = `rgba(255,170,80,${0.15 + 0.05 * Math.sin(t * 9)})`; c.beginPath(); c.arc(520, 430, 80, 0, 7); c.fill();
    c.fillStyle = '#ffb347'; c.beginPath(); c.moveTo(505, 440); c.quadraticCurveTo(520, 400 + Math.sin(t * 10) * 6, 535, 440); c.fill();
    // idle soldiers
    drawUnit(c, { side: 'ally', cls: 'rifleman' }, 470, 455, 0.5, { t });
    drawUnit(c, { side: 'ally', cls: 'medic' }, 570, 460, 0.5, { t: t + 1 });
    c.save(); c.translate(1000, 0); c.scale(-1, 1); drawUnit(c, { side: 'ally', cls: 'mg' }, 160, 470, 0.5, { t: t + 2 }); c.restore();
  }

  // ---------- SVG icons for cards and map nodes ----------
  const ICONS = {
    flame: '<path d="M32 6c4 10 14 14 14 28a14 14 0 0 1-28 0c0-7 4-11 6-15 1 5 3 7 5 8-1-9 1-15 3-21z" fill="currentColor"/><path d="M32 30c3 5 7 7 7 13a7 7 0 0 1-14 0c0-4 3-6 7-13z" fill="#00000055"/>',
    cross: '<rect x="8" y="8" width="48" height="48" rx="6" fill="currentColor" opacity=".25"/><path d="M26 12h12v14h14v12H38v14H26V38H12V26h14z" fill="currentColor"/>',
    binoculars: '<circle cx="20" cy="40" r="12" fill="none" stroke="currentColor" stroke-width="6"/><circle cx="44" cy="40" r="12" fill="none" stroke="currentColor" stroke-width="6"/><path d="M14 30l6-18h8l2 18M50 30l-6-18h-8l-2 18" fill="currentColor"/><rect x="28" y="30" width="8" height="8" fill="currentColor"/>',
    satchel: '<rect x="10" y="20" width="44" height="34" rx="4" fill="currentColor"/><path d="M22 20v-6h20v6" fill="none" stroke="currentColor" stroke-width="5"/><path d="M42 30c6-6 10-10 14-18" stroke="currentColor" stroke-width="3" fill="none" stroke-dasharray="3 3"/><rect x="18" y="30" width="28" height="6" fill="#00000055"/>',
    relic: '<path d="M32 4l22 14v28L32 60 10 46V18z" fill="none" stroke="currentColor" stroke-width="4"/><ellipse cx="32" cy="32" rx="14" ry="9" fill="currentColor"/><circle cx="32" cy="32" r="5" fill="#00000088"/>',
    chevron: '<path d="M10 26l22-14 22 14v8L32 20 10 34z M10 42l22-14 22 14v8L32 36 10 50z" fill="currentColor"/>',
  };
  const icon = (name) => `<svg viewBox="0 0 64 64" aria-hidden="true">${ICONS[name] || ICONS.chevron}</svg>`;

  const NODE_ICONS = {
    skirmish: '<path d="M-11 9L9-11M-9 11L11-9M-11-9L9 11M-9-11L11 9" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/>',
    elite: '<path d="M-10-2a10 10 0 0 1 20 0c0 5-3 6-3 9h-14c0-3-3-4-3-9z" fill="currentColor"/><circle cx="-4" cy="-2" r="2.6" fill="#e6dbbd"/><circle cx="4" cy="-2" r="2.6" fill="#e6dbbd"/><rect x="-5" y="8" width="10" height="4" fill="currentColor"/>',
    intel: '<text x="0" y="8" text-anchor="middle" font-size="24" font-weight="700" fill="currentColor" font-family="Georgia,serif">?</text>',
    supply: '<rect x="-10" y="-9" width="20" height="18" fill="currentColor"/><path d="M-10-9L10 9M10-9L-10 9" stroke="#e6dbbd" stroke-width="2"/>',
    camp: '<path d="M-11 9L0-11 11 9z" fill="currentColor"/><path d="M-3 9L0 1 3 9z" fill="#e6dbbd"/>',
    cache: '<path d="M0-11l3 7h8l-6 5 2 8-7-4-7 4 2-8-6-5h8z" fill="currentColor"/>',
    miniboss: '<path d="M-12 9a12 12 0 0 1 24 0z" fill="currentColor"/><rect x="-7" y="1" width="14" height="3" fill="#e6dbbd"/><rect x="4" y="1" width="10" height="2" fill="currentColor"/>',
    boss: '<path d="M-12-2a12 12 0 0 1 24 0c0 6-4 7-4 11h-16c0-4-4-5-4-11z" fill="currentColor"/><path d="M-12-6l-3-8 7 4M12-6l3-8-7 4" fill="currentColor"/><circle cx="-4.5" cy="-1" r="3" fill="#57e0a4"/><circle cx="4.5" cy="-1" r="3" fill="#57e0a4"/>',
  };

  return { drawUnit, bg, portrait, size, sprites, spriteInfo, baseScene, BASE_W, BASE_H, STATIONS, icon, NODE_ICONS, rr, muzzle, flame };
})();
