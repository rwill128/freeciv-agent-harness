# Freeciv Rules for Agents

This is the project-local rules primer for LLM players. It describes the
Freeciv rule surface agents need before making strategic decisions. It is not
current-match memory and must not contain observations from a specific game.

## Active Ruleset

The harness starts Freeciv with an explicit ruleset directory:

```text
rulesetdir civ2civ3
```

Agents can verify the active ruleset with:

```bash
bin/game ruleset
bin/game brief
```

The control API exposes the same data at:

```text
GET /ruleset
GET /brief
GET /players/<player>/brief
```

Exact ruleset files live under the Freeciv source tree:

```text
../freeciv-s3_2-agent/data/civ2civ3/game.ruleset
../freeciv-s3_2-agent/data/civ2civ3/units.ruleset
../freeciv-s3_2-agent/data/civ2civ3/techs.ruleset
../freeciv-s3_2-agent/data/civ2civ3/buildings.ruleset
../freeciv-s3_2-agent/data/civ2civ3/terrain.ruleset
../freeciv-s3_2-agent/data/civ2civ3/effects.ruleset
../freeciv-s3_2-agent/data/civ2civ3/README.civ2civ3
```

Use harness views first. Consult ruleset files only when the interface does not
yet expose a needed rule.

## Winning

The safest practical objective is conquest: conquer or destroy every enemy city
and eliminate enemy resistance. Agents should treat expansion, economy,
research, defense, and offense as support for that objective unless the harness
exposes a different active victory setting.

Freeciv can also support spacerace, allied, culture, and score/end-turn
outcomes depending on server settings. Do not assume those are active in a
specific match until the harness exposes the running server's `victories` and
`endturn` settings.

Culture support exists in the `civ2civ3` ruleset. The ruleset thresholds are:

```text
victory_min_points = 20000
victory_lead_pct   = 100
```

Do not assume culture victory is active unless the running server settings say
`victories` includes `CULTURE`.

## Turn Model

The harness starts matches with:

```text
set phasemode PLAYER
set aifill 0
```

`phasemode PLAYER` means one player acts at a time. An agent should act only
when its `brief` says `active_phase=True`.

Each turn:

1. Inspect `bin/game brief`.
2. Inspect units with `valid-moves`, `ascii-view`, or `local-view`.
3. Issue legal actions.
4. End the phase with `bin/game phase-done --intent "private note about what you tried to do and why"`.

Movement points do not carry over. A unit with remaining movement should usually
either move, start an activity, fortify, or intentionally stay put for a reason.

## Early Priorities

Good early play usually balances:

- Expansion: found additional cities quickly if settlers are available.
- Food: avoid starvation and grow cities by working good food tiles.
- Production: improve shield tiles and choose city production intentionally.
- Defense: keep cities defended before sending military units far away.
- Exploration: reveal nearby terrain, resources, city sites, and enemies.
- Research: choose technologies that unlock useful governments, economy,
  movement, military, or growth options.

On a tiny two-player map, contact and conflict can happen early. Do not build
only static defenders forever; scouts and military units should create map
knowledge and pressure when safe.

## Cities

Cities produce food, shields, and trade. Food supports growth, shields build
units/buildings/wonders, and trade feeds taxes, science, and luxury.

City production matters every turn. If a city is producing an item that no
longer matches the strategic situation, change it with:

```bash
bin/game set-city-production <city_id> <target> --kind unit
bin/game set-city-production <city_id> <target> --kind building
```

Use `bin/game production-targets` for exact production target names before
changing city production. Its compact output groups key unit targets by role.
Use `bin/game production-targets --all` when the compact target list is not
enough. In this ruleset, `Settlers` are the city-founder unit. `Migrants` are
population/settler-class utility units but cannot found cities; `found-city`
will reject them before sending a Freeciv action packet.

In `civ2civ3`, units can have upkeep costs. Overproducing supported military
from a small city can create food or economic pressure.

## Workers And Terrain

Workers improve terrain. Common actions:

- `road`: improves movement and trade routes where rules allow it.
- `mine`: often increases shield output on hills/mountains and some other
  terrain.
- `irrigate`: often increases food output on suitable terrain.
- `transform` or `cultivate`: changes terrain type when rules allow it.

Use `valid-moves`, `local-view`, and action results to check terrain, existing
extras, and known blockers. Do not repeatedly order a worker to build an
improvement already present on the tile.

Roads matter because `civ2civ3` gives strong movement bonuses on roads and
rivers. Improved city-adjacent tiles compound over time.

## Units And Combat

Each unit type has attack, defense, movement, hit points, build cost, and
requirements defined by the ruleset. The harness decodes known unit names and
basic stats where available.

Basic combat principles:

- Defenders benefit from terrain, fortification, city defenses, and unit type.
- Attacking with damaged or low-movement units can be inefficient.
- In `civ2civ3`, tired attack is enabled: units attacking with less than one
  full movement point have reduced attack power.
- Losing the only defender in a city can lose the city.
- Unescorted settlers/workers are vulnerable.

Use military units to defend cities, scout danger, control approaches, and
attack when odds and strategic payoff are favorable.

## Research

Research unlocks governments, units, buildings, wonders, diplomacy, naval
movement, and spaceship progress. Use:

```bash
bin/game set-research <tech>
bin/game set-tech-goal <tech>
```

In `civ2civ3`, tech costs are broadly linear by prerequisite depth, and tech
leakage can reduce costs when other civilizations know a technology and you have
an embassy with them.

Agents should not pick research randomly. Tie research to a plan: expansion,
economy, defense, offense, exploration, or long-term space race.

## Diplomacy

Diplomacy can matter once contact is made. The base harness currently exposes
limited diplomacy actions. Until more diplomacy tools exist, agents should at
least track contact, enemy positions, and whether peace/war status changes in
messages and state views.

Allied victory exists in the default victory setting, but the MVP harness should
not rely on diplomatic victory until treaty/action support is exposed cleanly.

## Score And Game-End Awareness

Freeciv scoring usually rewards empire strength: cities, population,
technology, wonders, spaceship progress, and other rule-dependent factors. For
agent play, treat score as a fallback objective, not the only goal.

The match runner currently needs reliable Freeciv state or messages before it
can declare game-over. Treat game-over detection as best-effort unless the
control view explicitly reports a surviving winner or the server emits a clear
victory/end-game message.

## Agent Conduct

Use canonical harness commands before reading raw protocol state:

```bash
bin/game brief
bin/game messages --limit 10
bin/game valid-moves <unit_id>
bin/game ascii-view --unit-id <unit_id> --text
bin/game local-view --unit-id <unit_id>
bin/game ruleset
```

Avoid raw IDs as reasoning concepts. Use IDs only to target commands. Reason in
terms of decoded names: terrain names, unit names, activities, technologies,
city production, and directions.

If the interface lacks a needed fact, inspect only the relevant ruleset file and
then continue through canonical commands. The long-term goal is to move any
commonly needed rule lookup into the harness so future agents do not need
source-tree access.
