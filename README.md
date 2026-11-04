# Squad

A 2D turn-based WW2 squad roguelite with timed inputs, built from the game spec. You command three soldiers through branching operations against the fictional Vossmark army and its occult Lantern Bureau. You draft a new boon build every chapter and bank meta-points at the forward base.

## Play

Open `dist/index.html` in any browser. It's one self-contained file with no server and no install. It works on phones (sideways gives the biggest battlefield) and on desktop.

Controls:

| Action | Touch / mouse | Keyboard |
| --- | --- | --- |
| Timed press, beats, hold | the big TAP button or the battlefield | Space (hold Space for hold inputs) |
| Hit the Dirt (wide window, no damage) | Hit the Dirt button | Space / Z / A / Left |
| Counter-shot (tight window, +1 AP) | Counter button | X / D / Right |
| Commands | buttons | 1-5 |
| Switch target | tap an enemy | Left / Right / Tab |

## What's in this build

- **Forward base:** Command Post (command tree, free respec), Barracks (Sniper, Sapper, second reserve slot, veteran Sgt. Okafor), Quartermaster (armory gear and base upgrades), Relic Crate (doctrine and duo unlocks, codex) and the Radio Tent (mission select, Heat 0-3 on cleared chapters).
- **Two chapters**, each about 13 stops and 20-30 minutes: *Operation Hedgerow* (boss: the relic tank "Grave Lantern") and *Operation Frostfall* (boss: the Hollow Saint).
- **Map nodes:** Skirmish, Elite, Intel (7 text events), Supply drop, Field camp, Cache, Strongpoint mini-boss and Boss. The map reshuffles every run; story beats stay fixed.
- **Combat:** turn-order timeline, Fire / Ability / Item / Take Cover / Swap, and AP. Offense uses three input types: a shrinking ring, rhythm beats and hold-and-release. Defense has Hit the Dirt, Counter-shot and feints. Also Break, Burn, shields, cover, and single/spread/blast targeting.
- **Boons:** 50 boons across Incendiary, Field Medic, Recon, Sapper, Captured Relics, Duo and Curse cards, plus 6 level-up stat cards. Rerolls and skip-for-gold.
- **Meta-progression:** points per fight, a clear bonus, Perfect, no-death and speed bonuses, and 25% banked on a loss.
- **Accessibility:** wider timing windows, auto-timing on offense, auto Hit the Dirt on defense, fast animations, screen shake and sound toggles.
- **Saves:** stored in the browser automatically after every map step.

Decisions taken on the spec's open questions: full wipe on clear (no Keepsake), always restart from node 1 on death, short chapters, phone-first layout that also plays on desktop.

## Art

- Soldiers, infantry, backdrops, the base, the map and UI are drawn in code (`src/js/art.js`) in a flat cel-shaded style.
- The war machines (light tank, relic tank, armored car, MG bunker) and the final boss are low-poly 3D models built and rendered in Blender (`tools/blender/render_sprites.py`) with toon banding and an inverted-hull outline, then inlined as sprites. If a sprite is missing, the game falls back to a 2D drawn version.

Re-render the sprites (Blender as a Python module, `pip install bpy`):

```
python tools/blender/render_sprites.py            # all sprites
python tools/blender/render_sprites.py tank bunker # just some
```

## Tune and rebuild

All numbers live in `data/*.json`: class stats and abilities, enemies and their moves, boons, chapters and encounter tables, events, meta upgrades, timing windows, rewards and prices. Edit them, then rebuild:

```
node build.mjs
```

This writes `dist/index.html` (standalone) and `dist/artifact.html` (the same page without a document wrapper, for hosting as a Claude artifact).

Smoke test: open `dist/index.html#autotest` and a bot plays three full chapters at high speed. It reports results in `G.testLog`.

## Stubbed or not yet built

- Operation Iron Tide (the coastal chapter) is listed in the Radio Tent as coming later.
- Named veterans beyond Sgt. Okafor, and armory relics beyond the Lantern Shard.
- There is no frame animation. Poses switch (idle, attack, hurt, cover, down) with short tweens.
- Sound is synthesized beeps and noise bursts; there's no music.
