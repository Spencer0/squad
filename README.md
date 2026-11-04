# Squad

A WW2-flavored roguelite auto-battler. You command a small army of squads and a hero across real continents against the fictional Vossmark army and its occult Lantern Bureau. Every model is 3D, rendered in Blender. Gameplay is a strict 2D side view, the way Super Smash Bros puts 3D models on a 2D plane.

**Play:** https://spencer0.github.io/squad/ (or open `dist/index.html` locally; it's one self-contained file).

## How it plays

- **World map:** each chapter is a continent: North America (Denver to New York), Europe (Cherbourg to Cologne) and East Asia (Hong Kong to Harbin). Cities are nodes on real geography. Pick your route city to city, and the node types reshuffle every run.
- **Real-time battles:** squads fire on their own. AP builds over time and from kills; tap a squad's card to cast its ability, and tap an enemy to focus fire. Enemy big attacks show a cast bar, and filling their Break gauge interrupts them. You get items, 1x/2x speed and pause (Space).
- **Squads, not soldiers:** each unit is a group of 2-5 figures sharing one HP bar. Figures drop as it takes damage, and damage output drops with them. A Medic Tent is a tent plus three medics.
- **Counters:**

  | Attacker | Strong against |
  | --- | --- |
  | Rifles | Recon |
  | Recon (snipers) | Support |
  | Support (MGs, grenadiers, mortars) | Infantry |
  | Sappers | Armor |
  | Armor | Infantry and Support |

  An intel report before each fight shows enemy roles so you can deploy the right squads.
- **Rows:** front-row squads shield the back row. Snipers, enemy ski scouts and mortars can hit the back row anyway.
- **Veterancy (Halo Wars style):** squads earn XP and rank up from Recruit to Veteran, Elite and Legendary (+15% HP and damage per rank). A wiped squad comes back at low strength and drops a rank. Ranks reset when the chapter ends.
- **Heroes:** Sgt. Okafor, Doc Halloran (the best medic in the division) and Lt. Vasquez "Ghost". Heroes level up permanently and unlock perks at levels 3, 6 and 9.
- **Army cap:** squads cost cap points. The cap starts at 6 and grows by 2 per continent cleared, plus up to 3 more from Logistics at the Command Post. Enemies scale up by continent.
- **Boons:** after battles you pick 1 of 3. There are five doctrines (Incendiary, Field Medic, Recon, Sapper, Captured Relics) plus Duo and Curse cards. The build is wiped when the chapter ends.
- **Base:** spend meta-points on the command tree, recruits and heroes, armory gear, and unlocks.

## Art pipeline (Blender 5 as a Python module)

| Script | Renders |
| --- | --- |
| `tools/blender/render_sprites.py` | vehicles and bosses (tank, relic tank, armored car, MG bunker, Hollow Saint) |
| `tools/blender/render_units.py` | squad figures (idle + attack poses on a fixed 256px canvas), the medic tent, the Lantern Colossus |
| `tools/blender/render_world.py` | battle backdrops, the forward base, and the three continent map boards from Natural Earth data, with city positions projected from the camera |

All use emission-only toon banding with an inverted-hull outline. To re-render (after `pip install bpy`):

```
python tools/blender/render_units.py            # everything, or name a few: rifleman e_shock
python tools/blender/render_world.py na us_farm
```

## Tune and rebuild

All numbers live in `data/*.json`:

| File | Contents |
| --- | --- |
| `units.json` | squad types |
| `heroes.json` | heroes |
| `enemies.json` | enemies |
| `config.json` | counters table, veterancy, hero levels, army cap, global combat scales, rewards |
| `chapters.json` | continents and encounter tables |
| `world.json` | cities and routes |
| `boons.json` | boons |
| `meta.json` | meta upgrades |
| `events.json` | events |

Then rebuild:

```
node build.mjs
```

This writes `dist/index.html` (standalone, with all art inlined) and `dist/artifact.html`.

Testing:
- `dist/index.html#autotest` plays all three continents with a bot.
- `G.simBattle(chapter, tier, enemies, army, hero, boons)` in the console simulates a single fight for balance checks.
