# Freeciv Agent Harness

This harness is for visible Freeciv games where agents control players and a
normal GTK client stays connected as the recording view.

Detailed protocol and MCP-design notes live in
`docs/freeciv-agent-harness.md`.

The Civ 5 and Civ 6 adapter tracks are documented separately in
`docs/civ5-agent-bridge.md` and `docs/civ6-agent-bridge.md`. Their first
milestone is a Lua bridge mod that dumps active-player visible state to
`Lua.log` for the local Python harness to parse.

## Current Working Setup

Preferred stable startup uses the repo-local runtime wrapper. It detaches both
processes, writes pid files and logs under `runtime/`, and starts Freeciv with a
startup script that sets `phasemode PLAYER` and `aifill 0`:

```sh
cd "/Users/richardwilliams/Game AI Science/freeciv-agent-harness"
scripts/freeciv-runtime start
scripts/freeciv-runtime status
scripts/freeciv-runtime logs
scripts/freeciv-runtime stop
```

Manual startup for debugging is still possible. Start the JSON-capable Freeciv
3.2 server built from the local S3_2 worktree:

```sh
cd "/Users/richardwilliams/Game AI Science/freeciv-s3_2-agent/build-agent-server"
./run.sh freeciv-server --Announce none -p 5560
```

Before starting an agent-controlled game, set the server to player-alternating
phases:

```text
set phasemode PLAYER
set aifill 0
```

`phasemode PLAYER` means only one civilization player is in phase at a time.
This avoids concurrent state changes while an isolated LLM agent is deciding its
turn. Set it before game start; Freeciv applies phase-mode changes at the next
turn boundary if changed mid-game.

If this is changed through an ordinary player socket after game start, Freeciv
may create a vote. Prefer setting it from the server console or startup script.

For an omniscient debugging view, start a visible GTK client:

```sh
/opt/homebrew/bin/freeciv-gtk4 -a -s 127.0.0.1 -p 5560 -n Observer
```

In the server console, make that GUI connection a global observer:

```text
observe Observer
```

For recording actual player perspective with fog of war, attach GUI clients as
player observers instead of global observers:

```sh
/opt/homebrew/bin/freeciv-gtk4 -a -s 127.0.0.1 -p 5560 -n AgentAView
/opt/homebrew/bin/freeciv-gtk4 -a -s 127.0.0.1 -p 5560 -n Observer
```

Then in the server console:

```text
observe AgentAView Matthias
observe Observer "Valdemar Sejr"
```

`observe <connection> <player>` gives that connection the selected player's map
visibility rather than god-mode visibility. The player names are the in-game
leader/player names, not the JSON agent usernames.

Then connect agent clients over JSON:

```sh
cd "/Users/richardwilliams/Game AI Science/freeciv-agent-harness"
python3 -m freeciv_agent.smoke_join --name AgentA --listen-seconds 5
```

The important split is:

- GTK client: visible recording/observer view, using Freeciv's normal binary protocol.
- Agent clients: structured control sockets, using Freeciv's JSON protocol on the same server.

## Status

The current Python control server keeps persistent player sockets open and
exposes a local control surface. Use `scripts/freeciv-runtime start-control` for
detached operation, or run it in the foreground for debugging:

```sh
python3 -m freeciv_agent.control_server --players AgentA AgentB
python3 -m freeciv_agent.control_cli state
python3 -m freeciv_agent.control_cli brief
python3 -m freeciv_agent.control_cli brief AgentA
python3 -m freeciv_agent.control_cli messages AgentA --limit 20
python3 -m freeciv_agent.control_cli local-view AgentA --unit-id 105 --radius 2
python3 -m freeciv_agent.control_cli ascii-view AgentA --unit-id 105 --radius 3 --text
python3 -m freeciv_agent.control_cli valid-moves AgentA 105
python3 -m freeciv_agent.control_cli ready AgentA
python3 -m freeciv_agent.control_cli say AgentA "public message"
python3 -m freeciv_agent.control_cli phase-done AgentA --intent "private turn intent"
python3 -m freeciv_agent.control_cli found-city AgentA --city-name Alpha
python3 -m freeciv_agent.control_cli move-unit AgentA 105 --dx 1
python3 -m freeciv_agent.control_cli move-unit AgentA 105 --direction 4
python3 -m freeciv_agent.control_cli unit-activity AgentA 103 mine
python3 -m freeciv_agent.control_cli unit-activity AgentA 103 road --target Road
python3 -m freeciv_agent.control_cli packet AgentA '{"pid":89}'
```

Implemented commands cover join, ready, phase done, ping/pong, compact unit/city
state, recent server messages, local terrain/resource views, deterministic ASCII
map views, ruleset unit-type/terrain/extra decoding, valid movement directions,
city founding, unit movement, worker activities, action queries, and a raw
packet escape hatch. Unit movement uses Freeciv `PACKET_UNIT_ORDERS` and
accounts for the default isometric-hex map topology when translating
`--dx/--dy`. `move-unit` and `unit-activity` return both the attempted command
and observed unit state after the command, so an agent can distinguish an
applied command from a sent but unapplied order.

Named commands include city production, economy rates, research selection,
movement, worker activity, action queries, and a raw packet escape hatch.

## Codex Player MVP

The MVP player architecture uses one persistent Codex session per player. Each
turn is still invoked non-interactively, but after the first turn the runner uses
`codex exec resume <session-id>` so the player keeps its prior conversation
context.

## API/MCP Player MVP

The cheaper non-Codex player path uses the OpenAI Responses API directly. Each
player keeps continuity through `previous_response_id`, stored in
`players/<player>/.api-agent-session.json`, and all game interaction goes
through the same player-scoped Freeciv MCP server used by Codex MCP
experiments.

Run one API-controlled turn:

```sh
export OPENAI_API_KEY=...
scripts/run-api-turn AgentA --model gpt-5.4-nano --reasoning-effort low --mcp-version v2
```

Run an API/MCP match against an already-running Freeciv runtime:

```sh
OPENAI_API_KEY=... \
PLAYERS="AgentA AgentB AgentC AgentD" \
MODEL=gpt-5.4-nano \
REASONING_EFFORT=low \
MCP_VERSIONS="AgentA=v1 AgentB=v2 AgentC=v2 AgentD=v2" \
MCP_ARTIFACT_MODES="AgentD=file-only" \
PUBLIC_TURN_MESSAGE=1 \
VICTORY_MODES="AgentA=conquest AgentB=conquest AgentC=conquest AgentD=conquest" \
scripts/start-api-match
```

Start a fresh server/control/viewer/API match end-to-end:

```sh
OPENAI_API_KEY=... \
PLAYERS="AgentA AgentB AgentC AgentD" \
MODEL=gpt-5.4-nano \
REASONING_EFFORT=low \
PUBLIC_TURN_MESSAGE=1 \
VICTORY_MODES="AgentA=conquest AgentB=conquest AgentC=conquest AgentD=conquest" \
scripts/start-fresh-api-match
```

The API runner writes final turn JSON and raw API/MCP transcripts under
`runtime/turns/`. Usage totals are recorded per player-turn and can be summarized
with:

```sh
scripts/analyze-api-usage
```

Each player has a scoped workspace:

```text
players/AgentA/
players/AgentB/
```

Inside each workspace, `bin/game` is the only game interface. It hardcodes the
player identity, so AgentA commands cannot accidentally request AgentB state.

Run one player turn with the default Codex model:

```sh
scripts/run-codex-turn AgentA
scripts/run-codex-turn AgentB
```

Choose the model at match start:

```sh
scripts/run-codex-turn AgentA --model <codex-model>
```

Run repeated turns:

```sh
scripts/run-codex-match --model <codex-model> --max-rounds 50 --reset-sessions
```

The first turn for a player creates `players/<player>/.codex-session.json`.
Subsequent turns resume that session. The runner writes turn outputs under
`runtime/turns/` and requires the final Codex answer to match
`schemas/turn-result.schema.json`.

The baseline player setup intentionally does not use player-authored
`memory.md`, `plan.md`, or note files. The player's job is to inspect current
game state through `bin/game`, choose useful actions for exactly one turn, end
the phase with `bin/game phase-done --intent "..."`, and return a short
`turn_summary` plus `private_intent` for the match log. Memory-file and
structured-planning variants should be added as explicit experimental modes.
The turn runner fails baseline turns that edit files or run commands other than
`bin/game`. It also blocks broad or verbose game views in baseline mode:
`bin/game state`, `bin/game valid-moves --json`, and `bin/game ascii-view`
without `--text`.

Agents can send public diplomacy with `bin/game say "..."`. Their private
end-of-turn intent is stored by the harness under
`runtime/audit/private-intents.jsonl`; it is not sent to the opponent.

Narrative-log mode is an explicit experiment flag, not baseline behavior. With
`NARRATIVE_LOG=1`, every player is instructed and permitted to append exactly
one concise Markdown entry per turn to `players/<player>/narrative.md`. With
`NARRATIVE_PLAYERS="AgentC AgentD"`, only those players get the instruction and
file-write permission. The validator still rejects all other player-authored
file edits. These entries are meant as visible story/audit material for video
review: what changed, what the agent did, and what it is trying to set up next.
They are not hidden chain-of-thought and should not be treated as the baseline
memory/plan feature.

The same control surface is available as a player-scoped MCP server for
experiments that compare CLI command use against typed tool calling:

```bash
scripts/freeciv-mcp --player AgentA --control-url http://127.0.0.1:8787
```

See `docs/freeciv-mcp.md`.
MCP interface versions are documented in `docs/freeciv-mcp-versions.md`; use
`MCP_VERSIONS` to assign different MCP designs to different players in one
match.
MCP artifact mode is documented in `docs/freeciv-mcp-artifacts.md`; use
`MCP_ARTIFACT_MODE=file-only` to write full MCP tool results to per-player files
instead of returning the whole result into the tool-call context.

The match-loop experiment switch is:

```bash
INTERFACE=mcp MODEL=gpt-5.5 scripts/start-codex-match
```

Assign per-player victory focuses with `VICTORY_MODES`:

```bash
PLAYERS="AgentA AgentB AgentC AgentD" \
MCP_PLAYERS="AgentC AgentD" \
MCP_VERSIONS="AgentC=v1 AgentD=v2" \
MCP_ARTIFACT_MODE=file-only \
NARRATIVE_LOG=1 \
VICTORY_MODES="AgentA=conquest AgentB=spacerace AgentC=culture AgentD=score" \
MODEL=gpt-5.5 scripts/start-fresh-match
```

With `RESET_SESSIONS=1`, the runner deletes stored Codex session ids and any
baseline `memory.md`, `plan.md`, or `notes.md` files before the first turn.
Fresh-match startup also sweeps old `players/<player>/narrative.md` files by
default through `RESET_NARRATIVE=1`, so each new match starts with clean
narrative artifacts. Use `RESET_NARRATIVE=0` only when intentionally resuming
or preserving an in-progress narrative log. It also deletes old
`players/<player>/mcp-artifacts/` directories by default through
`RESET_MCP_ARTIFACTS=1`, which keeps filesystem-artifact experiments from
mixing payloads across matches.

`bin/game valid-moves <unit_id>` defaults to a compact text view intended for
LLM play. Use `--json` only when debugging outside the baseline player loop.
`bin/game brief` is also compact by default and highlights every owned unit with
`movesleft > 0` before listing inactive units.

For a fresh end-to-end local match, use:

```sh
scripts/start-fresh-match
```

That command replaces the manual startup sequence: it stops stale match/runtime
processes, starts a fresh Freeciv server, starts the control API, opens muted
player-perspective viewers, resets player Codex sessions, and starts the match
loop.

The runner defaults to `--sandbox danger-full-access` for the initial Codex
session because the player must reach the local control server on
`127.0.0.1:8787`. Resumed turns use Codex's resume-compatible sandbox bypass for
the same reason.

## Civ 6 Adapter Track

Initial Civ 6 files:

```text
civ6_mods/Civ6AgentBridge/
civ6_agent/
scripts/civ6-bridge
scripts/install-civ6-bridge-mod
docs/civ6-agent-bridge.md
```

After Civ 6 is installed and launched once, install the bridge mod with:

```sh
scripts/install-civ6-bridge-mod
```

For the repeatable setup/status loop, use:

```sh
scripts/civ6-runtime setup
scripts/civ6-runtime launch
scripts/civ6-runtime status
```

`status` reads Steam's `libraryfolders.vdf`, checks every registered Steam
library, and reports whether Civ 6 is a macOS `Civ6.app` build, a Windows depot,
or an incomplete install. The current bridge mod targets macOS Civ 6 Lua logs
first; a Windows/Proton install needs a separate runtime path.

Once a supported Civ 6 runtime loads the mod, it writes framed state records to
`Lua.log` automatically on bridge load and turn/local-player events. The local
parser reads the latest framed state record with:

```sh
scripts/civ6-bridge log-paths
scripts/civ6-bridge latest-state --pretty
scripts/civ6-bridge brief
```

## Civ 5 Adapter Track

Initial Civ 5 files:

```text
civ5_mods/Civ5AgentBridge/
civ5_agent/
scripts/civ5-bridge
scripts/install-civ5-bridge-mod
scripts/civ5-runtime
docs/civ5-agent-bridge.md
```

The local Steam install is detected at:

```text
/Volumes/PolymarketData/SteamLibrary/steamapps/common/Sid Meier's Civilization V/Civilization V.app
```

Install the bridge mod and enable Civ 5 debug/Lua logging with:

```sh
bash scripts/civ5-runtime setup
bash scripts/civ5-runtime status
bash scripts/civ5-runtime launch
```

After enabling `Civ5AgentBridge` in Civ 5 Mods and starting a hotseat game, the
bridge should write framed state records to `Lua.log`; inspect them with:

```sh
bash scripts/civ5-bridge log-paths
bash scripts/civ5-bridge wait-state --pretty --timeout 600
bash scripts/civ5-bridge latest-state --pretty
bash scripts/civ5-bridge brief
```
