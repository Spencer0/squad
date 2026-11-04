// Small synthesized sound kit. Starts on the first user gesture.
G.audio = (() => {
  let ctx = null;
  let master = null;
  let noiseBuf = null;
  const ensure = () => {
    if (ctx) return ctx;
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      master = ctx.createGain();
      master.gain.value = 0.35;
      master.connect(ctx.destination);
      noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 1.0, ctx.sampleRate);
      const d = noiseBuf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    } catch (e) {
      ctx = null;
    }
    return ctx;
  };
  const enabled = () => G.settings && G.settings.sound && ensure();

  const tone = (freq, dur, type = 'square', vol = 0.3, slide = 0) => {
    if (!enabled()) return;
    const t = ctx.currentTime;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, freq + slide), t + dur);
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(g).connect(master);
    o.start(t);
    o.stop(t + dur + 0.02);
  };
  const noise = (dur, vol = 0.4, freq = 1200, q = 0.8, type = 'bandpass') => {
    if (!enabled()) return;
    const t = ctx.currentTime;
    const s = ctx.createBufferSource();
    s.buffer = noiseBuf;
    const f = ctx.createBiquadFilter();
    f.type = type;
    f.frequency.value = freq;
    f.Q.value = q;
    const g = ctx.createGain();
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    s.connect(f).connect(g).connect(master);
    s.start(t);
    s.stop(t + dur + 0.02);
  };

  const sfx = {
    click: () => tone(660, 0.05, 'square', 0.12),
    shot: () => { noise(0.12, 0.5, 1800, 0.7); tone(140, 0.08, 'square', 0.15, -80); },
    mg: () => { noise(0.07, 0.4, 2200, 0.9); },
    boom: () => { noise(0.6, 0.7, 300, 0.6, 'lowpass'); tone(70, 0.5, 'sine', 0.5, -40); },
    hit: () => { noise(0.08, 0.35, 700, 1.2); },
    perfect: () => { tone(880, 0.08, 'triangle', 0.25); setTimeout(() => tone(1320, 0.12, 'triangle', 0.25), 60); },
    good: () => tone(660, 0.09, 'triangle', 0.22),
    miss: () => tone(200, 0.15, 'sawtooth', 0.15, -60),
    parry: () => { tone(1500, 0.06, 'square', 0.18); tone(2200, 0.1, 'triangle', 0.15); },
    dodge: () => noise(0.18, 0.25, 500, 0.5, 'lowpass'),
    heal: () => { tone(520, 0.12, 'sine', 0.2, 200); setTimeout(() => tone(780, 0.16, 'sine', 0.2), 90); },
    break: () => { noise(0.3, 0.5, 900, 0.5); tone(220, 0.3, 'sawtooth', 0.25, -120); },
    tick: () => tone(1000, 0.03, 'square', 0.08),
    win: () => [523, 659, 784, 1046].forEach((f, i) => setTimeout(() => tone(f, 0.18, 'triangle', 0.22), i * 110)),
    lose: () => [392, 330, 262, 196].forEach((f, i) => setTimeout(() => tone(f, 0.25, 'sawtooth', 0.14), i * 160)),
    card: () => { noise(0.08, 0.2, 3000, 0.6); },
    occult: () => { tone(110, 0.8, 'sine', 0.25, 30); tone(166, 0.8, 'sine', 0.18, -20); },
  };
  return {
    unlock: () => { if (ensure() && ctx.state === 'suspended') ctx.resume(); },
    play: (name) => { try { sfx[name] && sfx[name](); } catch (e) {} },
  };
})();
G.sfx = (n) => G.audio.play(n);
