# Freeciv Agent Harness Notes

This document records the local Freeciv protocol and runtime findings needed to
build an MCP or Codex harness that can boot the game and play without relying on
conversation context.

## Goal

Run visible Freeciv games where agents control all civilization players. The
game should remain visible for recording, and actions should be issued through a
structured local interface rather than GUI clicks.

## Build And Runtime

Stable Freeciv `S3_2` is the working base. The build used locally is:

```sh
cd "/Users/richardwilliams/Game AI Science/freeciv-s3_2-agent"
CFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" \
PKG_CONFIG_PATH="/opt/homebrew/Cellar/icu4c@78/78.3/lib/pkgconfig:${PKG_CONFIG_PATH}" \
meson setup build-agent-server '-Dclients=[]' '-Dfcmp=[]' '-Dtools=[]' \
  -Daudio=none -Dnls=false -Djson-protocol=true

CFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" \
PKG_CONFIG_PATH="/opt/homebrew/Cellar/icu4c@78/78.3/lib/pkgconfig:${PKG_CONFIG_PATH}" \
ninja -C build-agent-server
```

### Stable Runtime Wrapper

The canonical local startup path is:

```sh
cd "/Users/richardwilliams/Game AI Science/freeciv-agent-harness"
scripts/freeciv-runtime start
scripts/freeciv-runtime status
```

This starts two detached processes:

- Freeciv server on port `5560`.
- Harness control server on `http://127.0.0.1:8787`.

Runtime files are kept under `runtime/`:

- `runtime/run/freeciv-server.pid`
- `runtime/run/control-server.pid`
- `runtime/logs/freeciv-server.log`
- `runtime/logs/control-server.log`
- `runtime/freeciv-startup.serv`
- `runtime/saves/`

Useful lifecycle commands:

```sh
scripts/freeciv-runtime status
scripts/freeciv-runtime logs
scripts/freeciv-runtime stop-control
scripts/freeciv-runtime stop-freeciv
scripts/freeciv-runtime stop
```

The wrapper accepts environment overrides:

```sh
FREECIV_PORT=5561 CONTROL_PORT=8788 PLAYERS="AgentA AgentB" FREECIV_RULESETDIR=civ2civ3 scripts/freeciv-runtime start
```

The wrapper writes the selected ruleset into `runtime/freeciv-startup.serv` and
passes it to the control API. The default is `FREECIV_RULESETDIR=civ2civ3`,
matching Freeciv's `data/default.serv`. Agents should use
`docs/freeciv-rules-for-agents.md` for the concise rules primer and
`bin/game ruleset` or `GET /ruleset` to verify the active ruleset.

The startup script also sets:

```text
set phasemode PLAYER
set aifill 0
set maxconnectionsperhost 16
```

`maxconnectionsperhost` must be above Freeciv's default of 4 when running
player-perspective observers from localhost. Four controlled player sockets plus
four `Agent*View` GTK observers already require eight localhost connections.

On macOS, the wrapper uses `launchctl` by default so processes are owned by user
launchd instead of a Codex tool session. Set `USE_LAUNCHD=0` to force detached
`screen` sessions for Freeciv and the control server when running the wrapper
from a normal Terminal or when you need direct `screen` inspection.

Prefer this wrapper for normal agent games. It avoids tying server lifetime to a
Codex foreground tool session.

### Manual Server Startup

The generated server is started with:

```sh
cd "/Users/richardwilliams/Game AI Science/freeciv-s3_2-agent/build-agent-server"
./run.sh freeciv-server --Announce none -p 5560
```

For isolated LLM-vs-LLM games, set player-alternating phases before the game
starts:

```text
rulesetdir civ2civ3
set phasemode PLAYER
set aifill 0
```

`phasemode` is Freeciv's simultaneous-phase control:

- `ALL`: all players may act concurrently.
- `PLAYER`: one player acts at a time; the current phase number is the active
  player number.
- `TEAM`: one team acts at a time; the current phase number is the active team
  number.

The canonical harness assumption is `PLAYER`: an LLM should get a stable
observation, issue actions for its own phase, then call `phase-done`. Do not ask
another isolated LLM to act while the current LLM has not ended its phase.
Freeciv accepts phase-mode changes mid-game, but the setting takes effect at the
next turn boundary.

When this command is sent from an ordinary player socket after the game starts,
Freeciv may create a vote instead of applying the command directly. For
repeatable harness runs, issue `set phasemode PLAYER` from the server console or
a startup script before the game starts. Use `/show phasemode` to inspect the
stored setting and `/explain phasemode` to inspect the mode still active for the
current turn.

The Homebrew GTK client works as a visible observer. A global observer is useful
for debugging, but it is god mode and sees the whole map:

```sh
/opt/homebrew/bin/freeciv-gtk4 -a -s 127.0.0.1 -p 5560 -n Observer
```

Use the server console to attach it as a global observer:

```text
observe Observer
```

For recording actual player fog of war, use `scripts/start-player-viewers`.
The launcher starts GTK clients in detached `screen` sessions; this matters on
macOS because plain background `nohup freeciv-gtk4 ... &` launches can die when
the launching shell exits.

The default mode is direct player view:

```sh
PLAYERS="AgentA AgentB AgentC AgentD" VIEWER_MODE=player scripts/start-player-viewers
```

This starts GUI clients as `AgentA`, `AgentB`, etc. Each window gets that
player's fog of war directly, without using `observe`. This is the most reliable
manual recovery/viewing mode for the current GTK4 client.

Observer mode keeps the protocol/control clients as the player connections and
uses separate GUI connection usernames:

```sh
PLAYERS="AgentA AgentB" VIEWER_MODE=observer scripts/start-player-viewers
```

Under the hood, observer mode runs server console commands like:

```text
observe AgentAView "<player A leader name>"
observe AgentBView "<player B leader name>"
list connections
```

That produces visible player-perspective observer windows:

- `AgentAView`: observes player A and sees player A fog of war.
- `AgentBView`: observes player B and sees player B fog of war.

The `observe <connection-name> <player-name>` server command takes Freeciv
connection names and in-game player names. The in-game player name may be the
leader name chosen by Freeciv, not the JSON agent username. Use `list` or
`list connections` to confirm the current names.

Known GTK4/console caveat: the `screen` server console path can mangle
non-ASCII leader names, and the GTK4 client may then hit invalid UTF-8 log-widget
assertions. For observer mode, prefer ASCII leader names in fresh matches or
replace the attach path with a UTF-8-safe protocol/admin command. If observer
clients connect and immediately show `Lost connection to server: read error`,
check `show maxconnectionsperhost`; the default limit of 4 is too low once the
four harness player sockets are connected.

Set civilization AI fill to zero for controlled-player tests:

```text
set aifill 0
```

This removes the default `AI*` civilization players. The ruleset may still add
the Animal Kingdom barbarian player.

## Harness Commands

Start the control server:

```sh
cd "/Users/richardwilliams/Game AI Science/freeciv-agent-harness"
python3 -m freeciv_agent.control_server --players AgentA AgentB
```

The HTTP API listens on `http://127.0.0.1:8787`.

CLI examples:

```sh
python3 -m freeciv_agent.control_cli state
python3 -m freeciv_agent.control_cli brief
python3 -m freeciv_agent.control_cli brief AgentA
python3 -m freeciv_agent.control_cli player AgentA
python3 -m freeciv_agent.control_cli ready AgentA
python3 -m freeciv_agent.control_cli found-city AgentA --city-name ExampleCity
python3 -m freeciv_agent.control_cli query-actions AgentA <unit_id> --dx 1
python3 -m freeciv_agent.control_cli move-unit AgentA <unit_id> --dx 1
python3 -m freeciv_agent.control_cli say AgentA "public message"
python3 -m freeciv_agent.control_cli private-intent AgentA "private note for edit/narration"
python3 -m freeciv_agent.control_cli phase-done AgentA --intent "private turn intent"
python3 -m freeciv_agent.control_cli packet AgentA '{"pid":89}'
```

HTTP endpoints currently implemented:

- `GET /state`
- `GET /brief`
- `GET /players/{name}`
- `GET /players/{name}/brief`
- `GET /players/{name}/messages`
- `GET /players/{name}/local-view`
- `GET /players/{name}/ascii-view`
- `GET /players/{name}/valid-moves`
- `POST /players/{name}/ready`
- `POST /players/{name}/say`
- `POST /players/{name}/private-intent`
- `POST /players/{name}/phase-done`
- `POST /players/{name}/found-city`
- `POST /players/{name}/move-unit`
- `POST /players/{name}/unit-activity`
- `POST /players/{name}/set-city-production`
- `POST /players/{name}/set-rates`
- `POST /players/{name}/set-research`
- `POST /players/{name}/set-tech-goal`
- `POST /players/{name}/query-actions`
- `POST /players/{name}/do-action`
- `POST /players/{name}/packet`

## Codex Player MVP

The first full-game MVP uses persistent Codex sessions. The harness starts a
fresh session for each player once, stores the session id in that player's
workspace, then sends later turns with `codex exec resume <session-id>`.

This preserves each player's prior conversation context across turns while still
allowing the runner to invoke turns non-interactively.

Player workspace layout:

```text
players/<player>/
  AGENTS.md
  bin/game
```

The baseline player workspace intentionally omits player-authored memory and
plan files. Baseline players should inspect the current game state through
`bin/game`, choose actions for one turn, call `phase-done --intent`, and return
a short `turn_summary` plus `private_intent` for audit logs. Persistent notes,
structured plans, and memory tools are experimental variants to enable
explicitly, not default behavior. The turn runner enforces this baseline by
failing turns that edit files or run shell commands other than `bin/game`. It
also rejects broad or verbose baseline commands: `bin/game state`, `bin/game
valid-moves --json`, and `bin/game ascii-view` without `--text`.

Narrative-log mode is a separate explicit experiment:

```bash
NARRATIVE_LOG=1 scripts/start-codex-match
NARRATIVE_PLAYERS="AgentC AgentD" scripts/start-codex-match
```

When enabled for a player, the turn prompt tells the player to append exactly
one concise Markdown entry at the end of each turn to:

```text
players/<player>/narrative.md
```

The entry should describe the visible story of the turn: turn/year if known,
what changed, actions taken, and what the agent is trying to set up next. It is
intended for post-game review and video narration. It is not hidden
chain-of-thought, and it is not the default memory/plan experiment. The Codex
event validator permits only this one file path when narrative mode is enabled;
all other player-authored file edits still fail the turn.

MCP players should use `narrative_append` to write the entry and
`narrative_read` to inspect the existing story log. They should not use shell
commands or direct file edits for narrative logging.

There are two communication channels:

- `bin/game say "..."` sends public Freeciv chat through
  `PACKET_CHAT_MSG_REQ`. The opponent can see this if Freeciv delivers it to
  normal chat.
- `bin/game private-intent "..."` and `bin/game phase-done --intent "..."`
  write a private harness artifact under `runtime/audit/private-intents.jsonl`.
  This is for post-game narration and analysis only. It is not sent to the
  opponent and is not persistent player memory.

`bin/game brief` defaults to a compact text summary for LLM use. It includes a
prominent `Units needing attention (movesleft > 0)` section before inactive
units so the model does not have to search a large JSON document for remaining
movable units.

`bin/game` wraps `freeciv_agent.player_cli` and hardcodes
`FREECIV_PLAYER_NAME`. The player-facing command set omits the player-name
argument:

```sh
bin/game brief
bin/game ruleset
bin/game production-targets
bin/game messages --limit 20
bin/game local-view --unit-id <unit_id> --radius 2
bin/game ascii-view --unit-id <unit_id> --radius 3 --text
bin/game valid-moves <unit_id>
bin/game move-unit <unit_id> --direction <direction_id>
bin/game unit-activity <unit_id> <activity>
bin/game set-city-production <city_id> <target> --kind unit
bin/game set-rates --tax 40 --luxury 0 --science 60
bin/game set-research <tech>
bin/game say "public message"
bin/game private-intent "private note"
bin/game phase-done --intent "private turn intent"
```

Production target names are ruleset-specific. Use `bin/game production-targets`
for exact unit/building target names before changing city production. The
default output is compact and groups key unit targets by role, such as city
founding, worker/population utility, military, and diplomacy/trade/exploration.
Use `bin/game production-targets --all` for the full decoded ruleset list. In
the active `civ2civ3` ruleset, `Settlers` are the city-founder unit. `Migrants`
are population/settler-class utility units but cannot found cities; `found-city`
will reject them before sending a Freeciv action packet.

The same player-scoped interface is also available as MCP tools for experiments
that should test typed tool calling instead of CLI command use. See
`docs/freeciv-mcp.md`. Use `INTERFACE=mcp scripts/start-codex-match` to run
the Codex match loop with MCP tools instead of `bin/game` commands.

Per-player strategic assignments are passed with `VICTORY_MODES`:

```bash
VICTORY_MODES="AgentA=conquest AgentB=spacerace AgentC=culture AgentD=score"
```

The runner injects the assigned focus into each turn prompt. These are prompt
conditions for strategy, not changes to Freeciv server victory settings.
`RESET_SESSIONS=1` removes stored Codex session ids plus baseline
`memory.md`, `plan.md`, and `notes.md` files before the first turn.
`RESET_NARRATIVE=1` removes old `players/<player>/narrative.md` files before
round 1. `scripts/start-fresh-match` defaults this on so every new match starts
with clean narrative artifacts. Set `RESET_NARRATIVE=0` only for an intentional
mid-match resume where the existing narrative log should continue.
`RESET_MCP_ARTIFACTS=1` removes old `players/<player>/mcp-artifacts/`
directories before round 1. Fresh-match startup defaults this on so filesystem
artifact experiments start with clean payload directories.

Run one Codex-controlled turn:

```sh
scripts/run-codex-turn AgentA
scripts/run-codex-turn AgentB
```

Select the model immediately before a match:

```sh
scripts/run-codex-turn AgentA --model <codex-model>
```

Run repeated turns:

```sh
scripts/run-codex-match --model <codex-model> --max-rounds 50 --reset-sessions
```

The turn runner:

- uses `codex exec` for a player's first turn;
- captures the Codex session id from `--json` event output;
- stores it in `players/<player>/.codex-session.json`;
- uses `codex exec resume <session-id>` for later turns;
- sets `-C players/<player>` on the initial session;
- uses `--sandbox danger-full-access` by default so Codex can connect to the
  localhost control server at `127.0.0.1:8787`;
- uses Codex's resume-compatible sandbox bypass for resumed turns, because
  `codex exec resume` does not accept `--sandbox`;
- passes `schemas/turn-result.schema.json` as the output schema;
- writes final turn JSON and execution transcripts under `runtime/turns/`.

The match runner writes loop history under `runtime/matches/`. If the harness
can decode the current active Freeciv phase, it runs only the active player;
otherwise it falls back to configured player order.

This is enough to test Codex-as-player behavior without Docker. Docker or
separate OS users can be added later for stronger filesystem isolation.

### API/MCP Runner

The API runner is the non-Codex control path for lower-cost experiments. It
uses the OpenAI Responses API directly, exposes the existing player-scoped
Freeciv MCP tools as function tools, and requires the model to finish each turn
by calling `submit_turn_result` with the same schema used by the Codex runner.

Per-player continuity is stored as:

```text
players/<player>/.api-agent-session.json
```

That file contains the last `response_id`; the next turn sends
`previous_response_id` so the model keeps its prior conversation context without
using Codex sessions or Codex quota.

Run one API turn:

```sh
export OPENAI_API_KEY=...
scripts/run-api-turn AgentA --model gpt-5.4-nano --reasoning-effort low --mcp-version v2
```

Run repeated API turns against an existing runtime:

```sh
OPENAI_API_KEY=... \
PLAYERS="AgentA AgentB AgentC AgentD" \
MODEL=gpt-5.4-nano \
REASONING_EFFORT=low \
MCP_VERSIONS="AgentA=v1 AgentB=v2 AgentC=v2 AgentD=v2" \
PUBLIC_TURN_MESSAGE=1 \
VICTORY_MODES="AgentA=conquest AgentB=conquest AgentC=conquest AgentD=conquest" \
scripts/start-api-match
```

Start a fresh API match end-to-end:

```sh
OPENAI_API_KEY=... \
PLAYERS="AgentA AgentB AgentC AgentD" \
MODEL=gpt-5.4-nano \
REASONING_EFFORT=low \
PUBLIC_TURN_MESSAGE=1 \
VICTORY_MODES="AgentA=conquest AgentB=conquest AgentC=conquest AgentD=conquest" \
scripts/start-fresh-api-match
```

The API runner writes:

- final turn result: `runtime/turns/*-api-turn-result.json`
- raw response/MCP transcript: `runtime/turns/*-api-transcript.json`
- per-player session pointer: `players/<player>/.api-agent-session.json`
- match history: `runtime/matches/latest-api-match-history.json`

Usage accounting is aggregated from Responses API `usage` fields. Run:

```sh
scripts/analyze-api-usage
```

to estimate observed cost per player-turn for `gpt-5.5`, `gpt-5.4`,
`gpt-5.4-mini`, and `gpt-5.4-nano`.

## LLM-Facing Interface Rules

The harness should not make an LLM reason from opaque Freeciv protocol IDs when
the meaning is known. Current views preserve raw IDs for exact targeting and
debugging, but add decoded language beside them.

Rules for canonical state/action payloads:

- Keep protocol fields such as `type`, `owner`, `activity`,
  `production_kind`, `production_value`, `topology_id`, and direction IDs.
- Add decoded fields such as `type_info`, `owner_info`, `activity_info`,
  `production`, `terrain_info`, `resource_info`, `direction_info`, and
  `topology`.
- Decode bitmasks into facts. For example, `topology_id=3` is exposed as
  `name=isometric hex`, `is_isometric=true`, `is_hex=true`, and a
  `valid_directions` list.
- Decode errors. Invalid movement now reports the attempted direction name,
  the topology name, and the allowed alternatives.
- Do not encode strategy, recommendations, or memory in these views. They are
  factual current-state surfaces; each LLM agent is responsible for its own
  planning and memory.

Important decoded fields now available:

- `map.topology`: topology name, wrap facts, valid directions, invalid
  directions, map size, and latitude bounds.
- `unit.owner_info`: `self`, `other`, `unowned`, or `unknown`.
- `unit.type_info`: unit type name/rule name and known stats such as attack,
  defense, move rate, hit points, build cost, and worker flag.
- `unit.activity_info`: activity name and decoded target extra when present.
- `city.production`: current build category and target. In the active S3_2
  protocol, `production_kind=6` is `UnitType`; `production_kind=3` is
  `Building`.
- `player.economy`: decoded gold and tax/luxury/science rates when available.
- `player.research`: decoded current research, goal, known techs, available
  tech choices, and special values such as unset/future tech.
- `tile.terrain_info`, `tile.resource_info`, and `tile.owner_info`: decoded
  tile facts for local views and valid-move targets.
- `move.direction_info`: direction ID, name, delta, and whether that direction
  is legal on the current topology.

## Protocol Findings

Freeciv JSON packets use the normal Freeciv packet framing:

- two-byte big-endian packet length
- compact JSON payload
- trailing NUL byte

The first packet on a server connection determines whether the connection is
JSON. The GTK observer can use the normal binary protocol on the same server
while agent clients use JSON.

Join packet:

```json
{
  "pid": 4,
  "username": "AgentA",
  "capability": "+Freeciv-3.2-network ownernull16 unignoresync tu32 hap2clnt",
  "version_label": "+",
  "major_version": 3,
  "minor_version": 2,
  "patch_version": 4
}
```

Join reply is `pid=5`. Startup often includes `pid=0`
`PACKET_PROCESSING_STARTED` before the join reply, so clients must read through
startup packets until `pid=5`.

Ping/pong:

- Server ping: `pid=88`
- Client pong: `pid=89`

Failing to pong causes Freeciv to disconnect the agent with ping timeout.

Useful packet IDs:

- `4`: `PACKET_SERVER_JOIN_REQ`
- `5`: `PACKET_SERVER_JOIN_REPLY`
- `10`: `PACKET_NATION_SELECT_REQ`
- `11`: `PACKET_PLAYER_READY`
- `15`: `PACKET_TILE_INFO`
- `16`: `PACKET_GAME_INFO`
- `30`: `PACKET_CITY_REMOVE`
- `31`: `PACKET_CITY_INFO`
- `51`: `PACKET_PLAYER_INFO`
- `52`: `PACKET_PLAYER_PHASE_DONE`
- `62`: `PACKET_UNIT_REMOVE`
- `63`: `PACKET_UNIT_INFO`
- `64`: `PACKET_UNIT_SHORT_INFO`
- `73`: `PACKET_UNIT_ORDERS`
- `84`: `PACKET_UNIT_DO_ACTION`
- `87`: `PACKET_UNIT_GET_ACTIONS`
- `88`: `PACKET_CONN_PING`
- `89`: `PACKET_CONN_PONG`
- `90`: `PACKET_UNIT_ACTIONS`
- `127`: `PACKET_NEW_YEAR`
- `140`: `PACKET_RULESET_UNIT`

`PACKET_MAP_INFO` provides `xsize`, `ysize`, topology, and wrap flags. On
rectangular maps, tile IDs commonly map to native coordinates with
`tile = y * xsize + x`, but movement should still use Freeciv's native-to-map
coordinate conversion because isometric and hex topologies alter adjacency.

Freeciv uses delta encoding for many JSON packets. Delta packets include a
`fields` byte array bitvector, and zero-valued fields may be omitted. Important
examples:

- Ready true first send: `{"pid":11,"fields":[3],"player_no":0}`
- Phase done first send: `{"pid":52,"fields":[1],"turn":1}`
- Unit action first send: `pid=84`, `fields:[31]`, and all five action fields.
- Unit order first send for one-step movement: `pid=73`, `fields:[103]`.

For `owner`, an omitted field means protocol value `0`, not "the current
viewer/player." This matters once another player can see player 0's units:
AgentB can receive a visible AgentA unit without an `owner` field. The
controller must reconstruct that as `owner=0`, otherwise AgentB will
misclassify AgentA units as friendly.

The control server now parses `PACKET_RULESET_UNIT` into `unit_types` and
enriches each owned unit in `/state` with `type_name`, `type_rule_name`, and
basic unit-type stats such as attack, defense, move rate, and worker flag when
present. This prevents agents from needing to know ruleset-specific numeric
unit type IDs.

`GET /brief` is the preferred state payload for LLM-agent turns. It omits the
large `unit_types` table and packet counters, keeps decoded owned units and
cities, and includes a count of known tiles. `GET /state` remains the full
debugging payload.

## Implemented Actions

### Found City

`Found City` is action ID `27` in `common/actions.h`.

The harness sends `PACKET_UNIT_DO_ACTION`:

```json
{
  "pid": 84,
  "fields": [31],
  "actor_id": 1001,
  "target_id": 2001,
  "sub_tgt_id": -1,
  "name": "ExampleCity",
  "action_type": 27
}
```

The target is the founding unit's current tile ID. Before sending the action,
the harness asks Freeciv whether `Found City` is legal for that unit on that
tile. A successful city-found action removes the founding unit and emits
`CITY_INFO` for the new city.

### Phase Done

The harness sends `PACKET_PLAYER_PHASE_DONE`:

```json
{
  "pid": 52,
  "fields": [1],
  "turn": 1
}
```

The turn advances after all active controlled players have sent phase done.

### Unit Move

Ordinary movement uses `PACKET_UNIT_ORDERS`, not `PACKET_UNIT_DO_ACTION`.
`Unit Move` action ID `110` exists in `common/actions.h`, but sending it via
`PACKET_UNIT_DO_ACTION` did not move units in the normal map-click case.

The working packet mirrors `client/control.c::request_unit_non_action_move`:

```json
{
  "pid": 73,
  "fields": [103],
  "unit_id": 1001,
  "src_tile": 2001,
  "length": 1,
  "orders": [
    {
      "order": 0,
      "activity": 16,
      "target": -1,
      "sub_target": -1,
      "action": 125,
      "dir": 4
    }
  ],
  "dest_tile": 2002
}
```

Relevant constants:

- `ORDER_MOVE = 0`
- `ACTIVITY_LAST = 16`
- `NO_TARGET = -1`
- `ACTION_NONE = 125`
- Direction enum: northwest `0`, north `1`, northeast `2`, west `3`, east `4`,
  southwest `5`, south `6`, southeast `7`

Some Freeciv maps use topology `3` (`TF_ISO | TF_HEX`) and wrap `3`
(`WRAP_X | WRAP_Y`). Do not translate relative movement with raw row-major tile
math. Freeciv movement converts native tile indexes to map coordinates, applies
`DIR_DX/DIR_DY`, and converts back.

The CLI can move by target tile or relative map delta:

```sh
python3 -m freeciv_agent.control_cli move-unit AgentA <unit_id> --dx 1
python3 -m freeciv_agent.control_cli move-unit AgentB <unit_id> --dx -1
python3 -m freeciv_agent.control_cli move-unit AgentA <unit_id> --direction 4
```

`move-unit` waits briefly for an observed unit update and returns both the
attempted order and the observed result:

```json
{
  "before": {"id": 1001, "tile": 2001, "movesleft": 6, "type_name": "Explorer"},
  "after": {"id": 1001, "tile": 2002, "movesleft": 4, "type_name": "Explorer"},
  "applied": true,
  "observed_changed": true,
  "target_tile": 2002,
  "direction": 4
}
```

If Freeciv accepts but does not immediately apply an order, `applied` will be
false and `after` reflects the last observed state. Agents should inspect this
instead of assuming every sent command changed the game.

If the local precheck can prove a non-action move is invalid, such as a land
unit trying to enter known Ocean terrain, `move-unit` returns `sent=false`,
`result=not_sent_known_invalid`, and does not send `PACKET_UNIT_ORDERS`.

### Local View

`local-view` returns a compact radius around a controlled unit, city, or tile.
This is the main LLM-facing map inspection command for local tactical context.

CLI examples:

```sh
python3 -m freeciv_agent.control_cli local-view AgentA --unit-id <unit_id> --radius 2
python3 -m freeciv_agent.control_cli local-view AgentB --city-id <city_id> --radius 2
python3 -m freeciv_agent.control_cli local-view AgentB --tile-id <tile_id> --radius 1
```

HTTP example:

```text
GET /players/AgentB/local-view?unit_id=<unit_id>&radius=2
```

Each tile entry includes relative `dx`/`dy`, tile id, known status,
terrain/resource ids and decoded names when known, owner/worked fields from the
tile packet, and visible units/cities on that tile. Terrain names come from
`PACKET_RULESET_TERRAIN` (`pid=151`); resource names come from
`PACKET_RULESET_EXTRA` (`pid=232`).

`local-view` is intentionally current-state only. The canonical harness should
not add past sightings, event memory, or recommendations to this view; those
belong in the agent's own notes and reasoning layer.

### Server Messages

`messages` exposes recent `PACKET_CHAT_MSG` / `PACKET_CONNECT_MSG` payloads
received by a player control connection. This is primarily a debugging and
integration probe for Freeciv server replies.

CLI:

```sh
python3 -m freeciv_agent.control_cli messages AgentA --limit 20
```

HTTP:

```text
GET /players/AgentA/messages?limit=20
```

This is not intended as a strategic memory surface. It is current connection
message history only, capped in memory.

### ASCII View

`ascii-view` renders the same current local facts into a deterministic spatial
prompt artifact. It is a presentation layer over current state only: it should
not contain memories, recommendations, inferred intentions, or suggested next
inspections.

CLI:

```sh
python3 -m freeciv_agent.control_cli ascii-view AgentB --unit-id <unit_id> --radius 3 --text
```

HTTP:

```text
GET /players/AgentB/ascii-view?unit_id=<unit_id>&radius=3
```

The JSON response includes `format=freeciv-agent-ascii-view-v2` and a `text`
field. The CLI `--text` flag prints only that text field.

Format v2 uses two-character cells:

- first character: terrain code
- second character: visible marker

Terrain codes:

- `?` unknown
- `~` water
- `a` arctic
- `d` desert
- `f` forest
- `g` grassland
- `h` hills
- `j` jungle
- `m` mountains
- `p` plains
- `s` swamp
- `t` tundra

Visible markers:

- `.` no visible entity
- uppercase letter: own unit, based on unit type
- lowercase letter: other visible unit, based on unit type
- `@` own city
- `&` other city
- `*` multiple visible units/cities on the tile

For the current isometric-hex topology (`topology_id=3`), format v2 uses a
hex-distance layout instead of a square matrix:

```text
hex_distance=(abs(dx)+abs(dy)+abs(dx-dy))/2
```

Cells outside the requested hex radius are omitted. The view also includes an
explicit `center-neighbors` block with the six legal adjacent directions:

- `0 northwest(-1,-1)`
- `1 north(+0,-1)`
- `3 west(-1,+0)`
- `4 east(+1,+0)`
- `6 south(+0,+1)`
- `7 southeast(+1,+1)`

This is deliberate: the ASCII view should not imply that square-grid positions
such as `northeast(+1,-1)` or `southwest(-1,+1)` are adjacent on the current
hex map. Resource, owner, city, and unit details are listed after the grid for
notable rendered tiles.

### Valid Moves

`valid-moves` exposes current movement options for one unit. It is factual
current-state data only: it does not encode past sightings, events, memory, or
recommended moves.

CLI:

```sh
python3 -m freeciv_agent.control_cli valid-moves AgentB <unit_id>
```

HTTP:

```text
GET /players/AgentB/valid-moves?unit_id=<unit_id>
```

The CLI default is a compact text view for LLM use. It prints one line per
topology-valid direction with direction id/name, target tile, terrain/resource
facts, visible blockers, and the advisory legality estimate. Full JSON remains
available with `--json` for human debugging and interface development, but is
blocked inside the baseline Codex player loop.

The result includes:

- selected unit id/type/tile/moves
- `type_source="missing"` when Freeciv has not exposed a concrete unit type id
  yet. The harness must not infer strategic unit roles from hp or tile state;
  action-specific commands such as `found-city` verify legality with Freeciv.
- current tile/map coordinates
- topology-valid direction ids and names
- target tile id and map coordinates
- target tile terrain/resource/visible unit facts, matching `local-view`
- `can_enter_known`, a deterministic current-state flag:
  - `true` when the known target terrain appears enterable by the unit
  - `false` when known terrain is impassable for the unit, such as land units
    entering ocean/deep ocean/lake
  - `null` when the tile is unknown or lacks enough decoded terrain data
- `legality`, a non-strategic order estimate:
  - `likely` when terrain is enterable and no visible target blockers are known
  - `blocked` when known terrain or visible foreign city/unit blockers would
    reject a normal non-action movement order
  - `maybe` when terrain is enterable but the harness sees non-terrain warning
    signs, such as a tile worked by a non-self or unknown city
- `known_blockers`, visible city/unit blockers on the destination tile
- `warnings`, factual caveats that Freeciv may still enforce after the command

On the current default isometric-hex topology (`topology_id=3`), valid topology
directions are `0`, `1`, `3`, `4`, `6`, and `7`. Directions `2` and `5` are not
valid for this topology and are now rejected before sending a move order.

### Native Freeciv Map Images

Freeciv itself supports server-side map image generation through the `mapimg`
server command. Source references:

- `server/commands.c` defines `mapimg` as an `ALLOW_ADMIN` command.
- `common/mapimg.c` implements `mapimg define`, `show`, `create`, `delete`, and
  `colortest`.
- `common/mapimg.h` defines map layers:
  - `a` area inside borders
  - `b` borders
  - `c` cities
  - `f` fog of war, single-player images only
  - `k` player knowledge, single-player images only
  - `t` terrain
  - `u` units

Useful map definitions:

```text
mapimg define zoom=2:map=tfkcub:show=plrid:plrid=0:format=ppm|ppm
mapimg define zoom=2:map=tfkcub:show=plrid:plrid=1:format=ppm|ppm
mapimg create 0
mapimg create 1
```

`ppm|ppm` uses the built-in PPM writer, so it does not depend on MagickWand.
PNG/GIF/JPG require a compiled image toolkit. Generated files are written to
the server save path and named from the save prefix plus the map definition,
for example `...-M...Z2P000plrid.ppm`.

Probe method:

```sh
python3 -m freeciv_agent.control_cli packet AgentA \
  '{"pid":26,"fields":[1],"message":"/mapimg show all"}'
python3 -m freeciv_agent.control_cli messages AgentA --limit 10
```

Freeciv replied:

```text
/mapimg: You are not allowed to use this command.
```

Native map images are likely the better visual artifact path than macOS
screenshots, but ordinary player sockets may lack admin command access. To use
this in the harness, start the server with a console script that grants
admin/hack access or predefines the needed `mapimg` definitions before the game
starts. Player sockets can send server commands over `PACKET_CHAT_MSG_REQ`
(`pid=26`) when the `fields` bitvector includes the message field.

### Unit Activity

Worker tasks such as road, irrigate, and mine use
`PACKET_UNIT_CHANGE_ACTIVITY` (`pid=222`) rather than a separate packet for each
task. This is the same path used by the GUI's
`request_new_unit_activity_targeted()`.

Canonical CLI:

```sh
python3 -m freeciv_agent.control_cli unit-activity AgentA <unit_id> mine
python3 -m freeciv_agent.control_cli unit-activity AgentA <unit_id> road --target Road
python3 -m freeciv_agent.control_cli unit-activity AgentA <unit_id> sentry
```

Working packet shape:

```json
{
  "pid": 222,
  "fields": [7],
  "unit_id": 1001,
  "activity": 2,
  "target": 1
}
```

Relevant activity constants:

- `ACTIVITY_IDLE = 0`
- `ACTIVITY_CULTIVATE = 1`
- `ACTIVITY_MINE = 2`
- `ACTIVITY_IRRIGATE = 3`
- `ACTIVITY_SENTRY = 5`
- `ACTIVITY_FORTIFYING = 10`
- `ACTIVITY_CLEAN = 11`
- `ACTIVITY_BASE = 12`
- `ACTIVITY_GEN_ROAD = 13`

Freeciv activities `mine`, `irrigate`, `road`, `base`, `clean`, and `pillage`
require a target extra. The harness decodes `PACKET_RULESET_EXTRA` (`pid=232`)
so agents can use target names instead of raw extra ids. Defaults are currently:

- `mine` -> `Mine`
- `irrigate` -> `Irrigation`
- `road` -> `Road`

Freeciv's JSON delta encoding omits zero-valued fields. In `civ2civ3`,
`Irrigation` is ruleset extra id `0`, so the harness must preserve omitted
ruleset object ids as `0` when decoding `PACKET_RULESET_EXTRA`. If `Irrigation`
is missing from decoded extras, irrigate commands will fail target resolution.
Agents should use decoded rule names returned by the harness rather than
inventing target IDs.

`unit-activity` defaults to a 5 second observation wait, matching `move-unit`.
It returns `before`, `after`, `applied`, `observed_changed`, `result`,
`retry_policy`, `legality`, `tile`, `wait_seconds`, and `recent_messages` like
`move-unit`. The `legality` object is advisory only: it decodes the requested
activity, target extra, terrain worker-time fields, owner relation, and obvious
warnings such as "target required" or "worker improvement on an unowned tile."
Freeciv is still authoritative after the command is sent.

Tile views decode `PACKET_TILE_INFO.extras` into `extras_info`, so existing
infrastructure such as `Road`, `Irrigation`, `Mine`, `River`, or resources can
be presented by name instead of as a raw bitvector. The raw bit ids are kept as
`extras_ids`; `extras_info` only includes extras decoded from the active
ruleset.

If the precheck finds a known blocker, such as trying to build `Road` on a tile
where the `Road` extra is already present, `unit-activity` returns
`sent=false`, `applied=false`, and `result.estimate=not_sent_known_invalid`
without sending `PACKET_UNIT_CHANGE_ACTIVITY`.

The main `result.estimate` values are:

- `already_active`: the unit was already doing the requested activity/target,
  so no packet was sent.
- `confirmed_activity`: the requested activity/target was observed after send.
- `sent_pending`: the packet was sent, but no matching activity update arrived
  before the wait timeout. This is not proof of rejection.
- `changed_without_requested_activity`: unit state changed, but not into the
  requested activity/target.
- `not_sent_known_invalid`: the harness found a known blocker and did not send.

Agents should follow `retry_policy.repeat_same_order_this_turn`. For
`already_active`, `confirmed_activity`, and `sent_pending`, the correct default
is not to repeat the same activity order during the same turn; inspect another
unit, choose a different action, or end phase unless later state/messages prove
the order failed.

Movement commands against sentried units can require extra care. A
`move-unit` order may first wake the unit from `Sentry` and return before the
movement observation is stable; a repeated command can then target the next
tile from the unit's new location. The safe loop is to read the unit state after
waking or moving a sentried unit before issuing another directional command.

## Verified Harness Behaviors

Manual two-player shakedowns have verified these reusable interface behaviors:

- With `aifill=0`, the harness can connect two controlled player clients and
  mark both ready.
- Freeciv may still create a barbarian/animal player depending on the ruleset.
- `found-city` asks Freeciv whether `Found City` is legal before sending the
  action. When legal and applied, it creates a city, removes the founding unit,
  and updates local city state. Units such as `Migrants` are rejected before a
  packet is sent.
- Explicit `phase-done` calls from all controlled players advance the turn.
  Agent turns should normally use `phase-done --intent` so the harness records
  the private end-of-turn narration artifact at the same time.
- `move-unit` sends `PACKET_UNIT_ORDERS`, observes unit movement, and reports
  whether a state change was seen.
- Production changes emit city updates and preserve decoded production facts.
- Hostile or foreign-owned tile movement can be represented by the same
  movement command; legality is determined by Freeciv and reported through the
  observed result.
- Worker activities can be sent by decoded activity and target-extra names,
  though target availability still needs better inspection.

## Production Control

`set-city-production` changes a city's current build target with decoded,
LLM-facing names:

```bash
python3 -m freeciv_agent.control_cli set-city-production AgentA <city_id> Workers --kind unit
```

REST equivalent:

```http
POST /players/AgentA/set-city-production
```

```json
{
  "city_id": 123,
  "target": "Workers",
  "kind": "unit",
  "wait": 1.0
}
```

The command sends `PACKET_CITY_CHANGE` (`pid=35`) and accepts production
targets by numeric ID, `name`, or `rule_name`. `kind` defaults to `unit`;
`unit`, `UnitType`, and `6` resolve to Freeciv universal kind `UnitType`.
`building`, `Building`, and `3` resolve to Freeciv universal kind `Building`.

The response includes the raw IDs plus decoded `production` facts, and includes
`before`, `after`, `applied`, and `observed_changed` fields.

## Economy And Research

`brief` and player state include decoded economy and research facts when the
server has sent them. The canonical commands are:

`brief` also includes decoded `PACKET_PLAYER_INFO` status under
`player_status`. This keeps raw protocol values available without making the
agent reason from protocol trivia:

- `packet_delta`: decodes the Freeciv `fields` bitvector as packet-delta
  metadata, not map/city fields.
- `flags`: decodes player flags such as `ai`, `scenario_reserved`, and
  `first_city`.
- `ai_attitudes`: decodes the `love` array into Freeciv attitude labels such as
  `Neutral`, `Hostile`, or `Helpful`.
- `wonders`: decodes the wonder ownership array when Freeciv sends a full flat
  array; compact JSON-diff shapes are labeled and preserved as raw segments.
- `style`: exposes style ids and decoded RGB/hex color when present.
- `connection`, `lifecycle`, `politics`, and `economy_packet`: expose packet
  session/life-cycle facts, mood, government ids, infrapoints, science cost,
  tech upkeep, and history.
- `visibility`: decodes `real_embassy`, `gives_shared_vision`, and
  `gives_shared_tiles` as player-slot bitvectors.
- `ai_profile`: decodes `ai_skill_level` and `barbarian_type`.
- `multipliers`: decodes ruleset multipliers/policies from
  `multip_count`, `multiplier`, `multiplier_target`, and
  `multiplier_changed`; names are filled from `PACKET_RULESET_MULTIPLIER`
  when available.

The compact `Player status:` line in CLI/MCP `brief` is intentionally a short
summary. The complete decoded player packet surface is in `player_status`,
`economy_detail`'s `Player Packet Status` section, and `player_packet_audit`.

```sh
python3 -m freeciv_agent.control_cli set-rates AgentA --tax 40 --luxury 0 --science 60
python3 -m freeciv_agent.control_cli set-research AgentA Currency
python3 -m freeciv_agent.control_cli set-tech-goal AgentA Monarchy
```

The matching REST endpoints are:

```http
POST /players/AgentA/set-rates
POST /players/AgentA/set-research
POST /players/AgentA/set-tech-goal
```

`set-rates` sends `PACKET_PLAYER_RATES` (`pid=53`). Freeciv may reject rate
combinations that exceed government limits; callers must check `applied` and
the recent messages.

`set-research` sends `PACKET_PLAYER_RESEARCH` (`pid=55`) and `set-tech-goal`
sends `PACKET_PLAYER_TECH_GOAL` (`pid=56`). Tech names are resolved against
decoded `PACKET_RULESET_TECH` data, with special values such as unset and future
tech decoded in state.

## Match Runtime Notes

Use the one-command launcher for normal fresh matches:

```sh
scripts/start-fresh-match
```

It stops old match/runtime processes, starts a fresh Freeciv server, starts the
control API, opens muted player-perspective viewers, resets per-player Codex
sessions by default, starts the Codex match loop, and prints status plus recent
match log output.

Use `scripts/start-codex-match` only when the server, control API, and viewers
are already in the desired state and only the self-play loop should be
restarted. It clears stale `runtime/run/stop-codex-match`, removes orphaned
match/turn runner processes, resets per-player Codex sessions by default, and
starts the loop in a detached `screen` named `freeciv-codex-match`.

For the current observer setup, keep the Freeciv server in `screen` so
`scripts/start-player-viewers` can send `observe` commands through the server
console. The control API can run under `launchd`; this has been more stable than
the plain `nohup` control process during game start.

Player-perspective GTK observers are launched with Freeciv sound disabled by
default via `-P none`. Override with `SOUND_PLUGIN=sdl` only if audible client
sound is explicitly wanted.

Fresh games need both controlled players marked ready before any active turn
exists. `codex_match_runner` now does that automatically unless
`--no-auto-ready` is passed.

The match runner must not infer the active player from units with movement
points. In `phasemode PLAYER`, non-active players can still have units that show
`movesleft > 0`, especially after reconnects. Active-player detection now uses
Freeciv's explicit phase packet when available. If the control API is restarted
mid-match and Freeciv does not replay that packet, the control server parses
server messages such as `Turn-blocking game play: waiting on <player> to finish
turn...` and maps the in-game player name back to the agent username from login
messages like `You are logged in as 'AgentB' connected to Pietro Badoglio.`
Only when one of those sources marks `agent_is_active_phase=true` should a Codex
player be asked to act.

To reset the control API without restarting the match:

```sh
scripts/freeciv-runtime stop-control
FREECIV_RULESETDIR=civ2civ3 scripts/freeciv-runtime start-control
python3 -m freeciv_agent.control_cli brief --json
RESET_SESSIONS=0 START_VIEWERS=0 scripts/start-codex-match
```

To enable player-authored narrative entries while keeping the rest of the
baseline file policy locked down:

```sh
NARRATIVE_LOG=1 scripts/start-codex-match
```

Fresh-match startup sweeps previous narrative logs automatically:

```sh
RESET_NARRATIVE=1 scripts/start-fresh-match
```

The resulting files are:

```text
players/AgentA/narrative.md
players/AgentB/narrative.md
```

Use `NARRATIVE_PLAYERS="AgentC AgentD"` when only selected experimental agents
should have narrative logging.

Verify that exactly one player has `phase.agent_is_active_phase=true` before
resuming the match loop.

## Current Gaps

Known interface gaps:

- reliable worker action availability and target inspection. `unit-activity`
  now includes decoded advisory legality and waits longer for observation, but
  it still cannot enumerate every server-legal worker action before sending.
- richer `query-actions` / action availability inspection parsing
- movement legality is still an estimate before command execution; hidden
  blockers, zone-of-control, combat/action requirements, and other server-only
  rules must be confirmed from `move-unit.applied` and `recent_messages`.
- sentried or sleeping unit movement can still require a read-after-wake loop if
  Freeciv wakes the unit instead of moving it on the first command.

Important open design question:

- Whether the MCP should expose low-level protocol tools, higher-level game
  actions, or both. The current HTTP/CLI control server should map cleanly to an
  MCP server: `state`, `player_state`, `found_city`, `phase_done`, and future
  named action tools.

Avoid:

- Autonomously ending turns in a loop while debugging. An earlier test
  advanced many turns accidentally. Prefer explicit one-command actions until
  the state/action loop is robust.
- Recording live-game turn notes, current board positions, or save-specific
  plans in this file. Document only reusable harness behavior, command shapes,
  protocol findings, and interface gaps.
