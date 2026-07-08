# Civ 5 Agent Bridge Plan

This document tracks the Civ 5 adapter path. Keep it about reusable harness
behavior, not about any specific live match.

## Why Civ 5

Civ 5 is a better near-term video target than Freeciv:

- It has much stronger audience recognition.
- It is visually legible enough for YouTube without explaining Freeciv.
- Hotseat gives visible sequential turns, which matches isolated LLM agents.
- The installed macOS build exposes Lua logs, local mods, and game UI scripts.

## Local Install Facts

Detected on this machine:

```text
/Volumes/PolymarketData/SteamLibrary/steamapps/common/Sid Meier's Civilization V/Civilization V.app
~/Library/Application Support/Sid Meier's Civilization 5/
~/Library/Application Support/Sid Meier's Civilization 5/MODS/
~/Library/Application Support/Sid Meier's Civilization 5/Logs/Lua.log
~/Library/Application Support/Sid Meier's Civilization 5/Saves/hotseat/
```

Steam app id:

```text
8930
```

The current support config initially had:

```text
EnableTuner = 0
EnableLuaDebugLibrary = 0
MessageLog = 0
```

`bash scripts/civ5-runtime setup` installs the bridge mod and flips those debugging
settings on. It also disables music/Sid sounds for recording sanity.

## Goal

Expose Civ 5 through the same conceptual agent interface as the Freeciv harness:

```sh
bin/game brief
bin/game ascii-view --unit-id <id>
bin/game valid-actions <unit-id>
bin/game move-unit <unit-id> --x <x> --y <y>
bin/game found-city <unit-id>
bin/game set-city-production <city-id> <target>
bin/game set-research <tech>
bin/game say "public message"
bin/game private-intent "private note for narration"
bin/game end-turn
```

Agents should see decoded Civ 5 concepts: unit names, city names, research
names, terrain/resource names, production names, and active-player status. Raw
IDs should remain available for exact command targeting.

## Architecture

Use Civ 5 hotseat mode:

- Civ 5 GUI is the recording surface.
- Hotseat makes one human player active at a time.
- Civ 5 itself controls the visible player perspective.
- The harness reads state from a Lua bridge and later sends commands through a
  validated in-process path.

Adapter layers:

1. `civ5_mods/Civ5AgentBridge/`: Civ 5 mod that registers an in-game UI addin
   and prints framed state records to `Lua.log`.
2. `civ5_agent/`: Python CLI/status/log parser for install status, latest
   state, and bridge results.
3. Future `players/<agent>/bin/game`: game-agnostic player CLI matching the
   Freeciv/Civ 6 command vocabulary.

## State Reading

The first read path is log-framed snapshots:

```text
CIV5_AGENT_STATE	{"schema":"civ5-agent-state-v0",...}
```

The current Lua bridge emits a snapshot:

- when the bridge loads,
- at active player turn start,
- when Civ 5 signals game data dirty.

The state payload includes:

```json
{
  "schema": "civ5-agent-state-v0",
  "game": {
    "turn": 0,
    "year": -4000,
    "active_player_id": 0,
    "active_team_id": 0
  },
  "player": {
    "id": 0,
    "name": "Washington",
    "civilization_short_description": "America",
    "civilization_description": "American Empire",
    "civilization_type": 0,
    "team": 0,
    "gold": 0,
    "happiness": 9,
    "current_research": -1,
    "science": 0,
    "culture": 0,
    "is_human": true
  },
  "cities": [
    {
      "id": 8192,
      "name": "Washington",
      "x": 21,
      "y": 17,
      "population": 1,
      "damage": 0,
      "food": 0,
      "production": 0,
      "production_name": "Warrior"
    }
  ],
  "units": [
    {
      "id": 65536,
      "type": 0,
      "type_name": "UNIT_SETTLER",
      "name": "Settler",
      "x": 21,
      "y": 17,
      "damage": 0,
      "moves": 2,
      "combat_limit": 0,
      "ranged_combat": 0,
      "domain": 0,
      "is_embarked": false,
      "can_found": true,
      "is_trade": false
    }
  ],
  "visible_plots": [
    {
      "index": 417,
      "x": 21,
      "y": 17,
      "terrain": "TERRAIN_GRASS",
      "feature": null,
      "resource": null,
      "owner": 0,
      "is_city": true,
      "is_water": false,
      "is_hills": false,
      "is_mountain": false
    }
  ]
}
```

This example shows shape, not a confirmed live snapshot from the current game.
Live validation is still required after enabling the bridge in Civ 5.

## Command Path

Command execution is not considered validated yet.

The local Civ 5 Lua assets show likely command mechanisms:

- select a unit with `UI.SelectUnit(unit)`;
- move with `Game.SelectionListGameNetMessage(GameMessageTypes.GAMEMESSAGE_PUSH_MISSION, MissionTypes.MISSION_MOVE_TO, x, y, ...)`;
- found city through unit action/mission paths used by the normal UI;
- choose research through the same UI/game-message path used by `TechPanel.lua`;
- choose production through the same popup/city path used by `ProductionPopup.lua`.

The bridge currently emits command-result frames but does not claim command
success for unvalidated actions:

```text
CIV5_AGENT_COMMAND	{"schema":"civ5-agent-command-result-v0",...}
```

The next live work item is to validate one command at a time inside a hotseat
test game:

1. dump state;
2. end turn;
3. found city;
4. move unit;
5. set research;
6. set city production;
7. worker build action;
8. ranged/city attack.

## Local Commands

Run from the harness repo:

```sh
bash scripts/civ5-runtime setup
bash scripts/civ5-runtime launch
bash scripts/civ5-runtime status
bash scripts/civ5-runtime wait-state 600
bash scripts/civ5-runtime log
```

Direct Python equivalents:

```sh
python3 -m civ5_agent.cli status
python3 -m civ5_agent.cli log-paths
python3 -m civ5_agent.cli wait-state --pretty --timeout 600
python3 -m civ5_agent.cli latest-state --pretty
python3 -m civ5_agent.cli latest-command --pretty
python3 -m civ5_agent.cli brief
```

## Live Validation Checklist

1. Run `bash scripts/civ5-runtime setup`.
2. Run `bash scripts/civ5-runtime launch`.
3. In Civ 5, enable `Civ5AgentBridge` in Mods.
4. Start a small hotseat game.
5. Run `bash scripts/civ5-runtime wait-state 600`.
6. Run `bash scripts/civ5-bridge brief`.
7. Confirm units, cities, visible plots, gold, culture, science, and active
   player match the GUI.
8. Add and verify command execution one command at a time.

## Open Questions

- Whether the macOS build loads the `InGameUIAddin` row from the bridge XML
  without needing ModBuddy-generated metadata.
- Whether the install-time md5-stamped `.modinfo` is sufficient for Civ 5's mod
  scanner, or whether this build expects additional ModBuddy-generated fields.
- Whether command execution can happen entirely through a Lua UI addin, or
  whether we need FireTuner, a debug-panel route, or UI automation for actions.
- Whether hotseat turn changes consistently trigger `Events.ActivePlayerTurnStart`
  in this mod context.
