# Civ 6 Agent Bridge Plan

This document tracks the Civ 6 adapter path. Keep it about reusable harness
behavior, not about any specific live match.

## Goal

Create a Civ 6 adapter that presents the same kind of LLM-facing interface as
the Freeciv harness:

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

The external agent should not need to know Civ 6 Lua API trivia. Raw Civ 6 IDs
can be present for targeting and debugging, but every state view should include
human names and concise explanations.

## Architecture

Use Civ 6 hotseat mode for a visible, sequential game:

- Civ 6 GUI is the recording surface.
- Hotseat turn order gives one active human-controlled civilization at a time.
- Civ 6 itself enforces the active player's fog of war.
- The harness controls the active player through a Civ 6 Lua bridge.

The adapter has three layers:

1. `civ6_mods/Civ6AgentBridge/`: Civ 6 Lua mod that reads game state and
   exposes command functions.
2. `civ6_agent/`: local Python bridge that parses Civ 6 logs, reports install
   status, enables the scanned bridge mod when possible, and reads command
   result frames.
3. `players/<agent>/bin/game`: eventual player-scoped CLI that maps the common
   agent command language onto the Civ 6 bridge.

Communication should match the Freeciv harness contract:

- Public communication is a deliberate `say` command if Civ 6 exposes a chat or
  hotseat message surface we can drive reliably.
- Private turn narration is harness-owned and game-agnostic. The agent should
  submit a private intent at the end of its turn; this is stored for video
  narration and analysis, not sent to the opponent and not treated as player
  memory.

## State Reading

The first state-reading path is log-framed snapshots:

1. Civ 6 loads `Civ6AgentBridge.lua` through an `AddGameplayScripts` mod
   action.
2. The bridge reads the active player's units, cities, research/civics, and
   revealed map plots through Civ 6 Lua APIs.
3. The bridge prints one framed snapshot to `Lua.log` when it loads and on
   turn/local-player events:

```text
CIV6_AGENT_STATE	{"schema":"civ6-agent-state-v0",...}
```

4. `python3 -m civ6_agent.cli latest-state` tails/parses the log and returns
   the most recent valid JSON state.

The log route is intentionally first because Civ 6 Lua file writes may be
restricted. If file reads/writes are available in the installed build, we can
replace or augment this with a command-file bridge.

## Command Path

The first command path to validate is debug Lua or another verified in-process
entry point. The bridge currently exposes these functions through
`ExposedMembers.Civ6AgentBridge`:

```lua
ExposedMembers.Civ6AgentBridge.DumpState()
ExposedMembers.Civ6AgentBridge.MoveUnit(unitID, x, y)
ExposedMembers.Civ6AgentBridge.FoundCity(unitID)
ExposedMembers.Civ6AgentBridge.SetCityProduction(cityID, "UNIT_BUILDER")
ExposedMembers.Civ6AgentBridge.SetResearch("TECH_WRITING")
ExposedMembers.Civ6AgentBridge.EndTurn()
```

The current Lua implementation uses Civ 6's own local UI/game APIs:

- `UnitManager.CanStartOperation` / `UnitManager.RequestOperation` for
  `MOVE_TO` and `FOUND_CITY`.
- `CityManager.CanStartOperation` / `CityManager.RequestOperation` for city
  production.
- `UI.RequestPlayerOperation(..., PlayerOperations.RESEARCH, ...)` for
  research selection.
- `UI.RequestAction(ActionTypes.ACTION_ENDTURN)` for ending the active turn.

Each command emits a framed result to `Lua.log`:

```text
CIV6_AGENT_COMMAND	{"schema":"civ6-agent-command-result-v0",...}
```

The exact runtime behavior still needs live validation in a loaded game. The
installed macOS Steam build shows Civ 6 tuner panel assets and
`Civ6TunerPlugin.dll`, but no standalone FireTuner app in the Steam library, so
command injection may need a different path than FireTuner.

## Local Commands

Run these from the harness repo:

```sh
scripts/civ6-runtime setup
scripts/civ6-runtime launch
scripts/civ6-runtime status
scripts/civ6-runtime enable-mod
scripts/civ6-runtime wait-state 600
scripts/civ6-runtime command
```

Direct Python equivalents:

```sh
python3 -m civ6_agent.cli status
python3 -m civ6_agent.cli enable-bridge
python3 -m civ6_agent.cli wait-state --pretty --timeout 600
python3 -m civ6_agent.cli latest-state --pretty
python3 -m civ6_agent.cli latest-command --pretty
python3 -m civ6_agent.cli brief
```

`setup` installs the bridge mod into all known macOS Civ 6 mod directories and
sets these `AppOptions.txt` values when the support file exists:

```text
EnableTuner 1
EnableDebugMenu 1
EnableAudio 0
```

The all-directory install is intentional during first-launch discovery because
Aspyr/Firaxis support paths differ across macOS Civ 6 builds and launch eras.

## MVP Milestones

1. Install Civ 6 and enable Lua logging / FireTuner.
2. Install `Civ6AgentBridge` as a local mod.
3. Start a tiny hotseat game with two human players.
4. Start a game with the bridge mod enabled and confirm `Lua.log` contains
   `CIV6_AGENT_BRIDGE_READY` and at least one `CIV6_AGENT_STATE` line.
5. Use `python3 -m civ6_agent.cli latest-state --pretty` to parse that snapshot.
6. Add and verify one command at a time:
- end turn
- private intent artifact
- public chat/message command if a reliable Civ 6 API exists
- move unit
   - found city
   - set research
   - set city production
7. Add a player-scoped `bin/game` CLI that mirrors the Freeciv command surface.

## Current First-Launch Status

Detected macOS Steam app path:

```text
/Volumes/PolymarketData/SteamLibrary/steamapps/common/Sid Meier's Civilization VI/Civ6.app
```

Detected Steam manifest path:

```text
/Volumes/PolymarketData/SteamLibrary/steamapps/appmanifest_289070.acf
```

The bridge setup can be run before Civ finishes first launch, but live
validation is blocked until Civ 6 completes Steam verification, launches far
enough to scan mods, and loads a game with `Civ6AgentBridge` enabled. Until that
happens, `enable-bridge` should report that the bridge has not been scanned and
`wait-state` should time out cleanly instead of producing a traceback.

## Live Validation Checklist

After Steam verification completes:

1. Run `scripts/civ6-runtime setup`.
2. Run `scripts/civ6-runtime launch`.
3. Let Civ 6 reach the main menu once so it creates/scans support files.
4. Run `scripts/civ6-runtime status`.
5. If status says the bridge is scanned but not enabled, run
   `scripts/civ6-runtime enable-mod`.
6. Start a tiny game with the bridge mod enabled.
7. Run `scripts/civ6-runtime wait-state 600`.
8. Run `scripts/civ6-bridge brief` and inspect whether active-player units,
   cities, and visible plots are decoded clearly.
9. Invoke one bridge command inside the game/debug Lua context.
10. Run `scripts/civ6-runtime command` to inspect the result frame.
11. Run `scripts/civ6-bridge latest-state --pretty` to confirm post-command
    state changed as expected.

## Open Questions

- Whether first launch/mod scanning registers `Civ6AgentBridge` from the
  Firaxis support path, Aspyr Documents path, or both.
- Exact macOS Civ 6 log path once a macOS build is available.
  - Existing support/log root from prior launch:
    `~/Library/Application Support/Sid Meier's Civilization VI/Firaxis Games/Sid Meier's Civilization VI/Logs/`
- Whether Steam macOS Civ 6 exposes an external debug Lua command surface at
  all. The current install does not include a standalone FireTuner app.
- Whether Lua can read command files from a safe mod storage path.
- Which command APIs work in UI context versus gameplay script context.
- Whether hotseat active-player state can be distinguished cleanly from local
  observer state via `Game.GetLocalPlayer()`, `Game.GetLocalObserver()`, or turn
  events.
