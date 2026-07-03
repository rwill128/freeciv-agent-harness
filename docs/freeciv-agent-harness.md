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
cd "/Users/richardwilliams/Documents/Game AI Science/freeciv-s3_2-agent"
CFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" \
PKG_CONFIG_PATH="/opt/homebrew/Cellar/icu4c@78/78.3/lib/pkgconfig:${PKG_CONFIG_PATH}" \
meson setup build-agent-server '-Dclients=[]' '-Dfcmp=[]' '-Dtools=[]' \
  -Daudio=none -Dnls=false -Djson-protocol=true

CFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" \
PKG_CONFIG_PATH="/opt/homebrew/Cellar/icu4c@78/78.3/lib/pkgconfig:${PKG_CONFIG_PATH}" \
ninja -C build-agent-server
```

The generated server is started with:

```sh
cd "/Users/richardwilliams/Documents/Game AI Science/freeciv-s3_2-agent/build-agent-server"
./run.sh freeciv-server --Announce none -p 5560
```

The Homebrew GTK client works as a visible observer. A global observer is useful
for debugging, but it is god mode and sees the whole map:

```sh
/opt/homebrew/bin/freeciv-gtk4 -a -s 127.0.0.1 -p 5560 -n Observer
```

Use the server console to attach it as a global observer:

```text
observe Observer
```

For recording actual player fog of war, use player observers instead. Start GUI
clients with stable connection usernames:

```sh
/opt/homebrew/bin/freeciv-gtk4 -a -s 127.0.0.1 -p 5560 -n AgentAView
/opt/homebrew/bin/freeciv-gtk4 -a -s 127.0.0.1 -p 5560 -n Observer
```

Attach those GUI connections to players from the server console:

```text
observe AgentAView Matthias
observe Observer "Valdemar Sejr"
list connections
```

Confirmed connection table:

```text
Observer from localhost (player Valdemar Sejr) (observer) command access level hack
AgentA from localhost (player Matthias) command access level basic
AgentB from localhost (player Valdemar Sejr) command access level basic
AgentAView from localhost (player Matthias) (observer) command access level hack
```

This produces two visible player-perspective windows:

- `AgentAView`: observes Matthias / AgentA and sees AgentA fog of war.
- `Observer`: observes Valdemar Sejr / AgentB and sees AgentB fog of war.

The `observe <connection-name> <player-name>` server command takes Freeciv
connection names and in-game player names. The in-game player name may be the
leader name chosen by Freeciv, not the JSON agent username. Use `list` or
`list connections` to confirm the current names.

In the current Homebrew GTK4 setup, starting a third simultaneous GTK client for
`AgentBView` left disconnected local processes. Reusing the original `Observer`
window as the AgentB player observer avoided the issue and gave the desired two
recordable perspectives.

Set civilization AI fill to zero for controlled-player tests:

```text
set aifill 0
```

This removes the default `AI*` civilization players. The ruleset may still add
the Animal Kingdom barbarian player.

## Harness Commands

Start the control server:

```sh
cd "/Users/richardwilliams/Documents/Game AI Science/freeciv-agent-harness"
python3 -m freeciv_agent.control_server --players AgentA AgentB
```

The HTTP API listens on `http://127.0.0.1:8787`.

CLI examples:

```sh
python3 -m freeciv_agent.control_cli state
python3 -m freeciv_agent.control_cli player AgentA
python3 -m freeciv_agent.control_cli ready AgentA
python3 -m freeciv_agent.control_cli found-city AgentA --city-name Alpha
python3 -m freeciv_agent.control_cli query-actions AgentA 105 --dx 1
python3 -m freeciv_agent.control_cli move-unit AgentA 105 --dx 1
python3 -m freeciv_agent.control_cli phase-done AgentA
python3 -m freeciv_agent.control_cli packet AgentA '{"pid":89}'
```

HTTP endpoints currently implemented:

- `GET /state`
- `GET /players/{name}`
- `POST /players/{name}/ready`
- `POST /players/{name}/phase-done`
- `POST /players/{name}/found-city`
- `POST /players/{name}/move-unit`
- `POST /players/{name}/query-actions`
- `POST /players/{name}/packet`

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

`PACKET_MAP_INFO` provides `xsize`, `ysize`, topology, and wrap flags. In the
current rectangular maps, tile IDs match `tile = y * xsize + x`. Verified
examples: AgentA's starting tile `429` is `(15,23)` on an `18x36` map; AgentB's
starting tile `569` is `(11,31)`.

Freeciv uses delta encoding for many JSON packets. Delta packets include a
`fields` byte array bitvector. Important examples:

- Ready true first send: `{"pid":11,"fields":[3],"player_no":0}`
- Phase done first send: `{"pid":52,"fields":[1],"turn":1}`
- Unit action first send: `pid=84`, `fields:[31]`, and all five action fields.
- Unit order first send for one-step movement: `pid=73`, `fields:[103]`.

For player 0, fields with value zero may be omitted by delta encoding. The
controller must treat omitted `owner` values in owned unit/city packets as the
current player's `player_no` when reconstructing state.

The control server now parses `PACKET_RULESET_UNIT` into `unit_types` and
enriches each owned unit in `/state` with `type_name`, `type_rule_name`, and
basic unit-type stats such as attack, defense, move rate, and worker flag when
present. This was needed for turn policy because the live state otherwise only
said type `52`, `48`, `2`, and `4`; decoded, those are Explorer, Diplomat,
Workers, and Warriors in the current ruleset.

## Implemented Actions

### Found City

`Found City` is action ID `27` in `common/actions.h`.

The harness sends `PACKET_UNIT_DO_ACTION`:

```json
{
  "pid": 84,
  "fields": [31],
  "actor_id": 101,
  "target_id": 429,
  "sub_tgt_id": -1,
  "name": "Alpha",
  "action_type": 27
}
```

The target is the settler unit's current tile ID. This has been verified:

- AgentA founded `Alpha`.
- AgentB founded `Beta`.
- The settler unit disappeared afterward.
- `CITY_INFO` updated the local state.

### Phase Done

The harness sends `PACKET_PLAYER_PHASE_DONE`:

```json
{
  "pid": 52,
  "fields": [1],
  "turn": 1
}
```

This has been verified to advance from turn 1 / year -4000 to turn 2 / year
-3950 when both controlled players issue it.

### Unit Move

Ordinary movement uses `PACKET_UNIT_ORDERS`, not `PACKET_UNIT_DO_ACTION`.
`Unit Move` action ID `110` exists in `common/actions.h`, but sending it via
`PACKET_UNIT_DO_ACTION` did not move units in the normal map-click case.

The working packet mirrors `client/control.c::request_unit_non_action_move`:

```json
{
  "pid": 73,
  "fields": [103],
  "unit_id": 105,
  "src_tile": 429,
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
  "dest_tile": 448
}
```

Relevant constants:

- `ORDER_MOVE = 0`
- `ACTIVITY_LAST = 16`
- `NO_TARGET = -1`
- `ACTION_NONE = 125`
- Direction enum: northwest `0`, north `1`, northeast `2`, west `3`, east `4`,
  southwest `5`, south `6`, southeast `7`

Default maps here use topology `3` (`TF_ISO | TF_HEX`) and wrap `3`
(`WRAP_X | WRAP_Y`). Do not translate relative movement with raw row-major tile
math. Freeciv movement converts native tile indexes to map coordinates, applies
`DIR_DX/DIR_DY`, and converts back. Example on the current map:

- AgentA city tile `429`, `--dx 1` / direction `4`, lands on tile `448`.
- AgentB city tile `569`, `--dx -1` / direction `3`, lands on tile `551`.

The CLI can move by target tile or relative map delta:

```sh
python3 -m freeciv_agent.control_cli move-unit AgentA 105 --dx 1
python3 -m freeciv_agent.control_cli move-unit AgentB 108 --dx -1
python3 -m freeciv_agent.control_cli move-unit AgentA 105 --direction 4
```

## Verified Two-Player Test

With `aifill=0`, starting `AgentA` and `AgentB`, marking them ready, and using
the GTK observer:

- Freeciv created `Matthias` / Austrian for `AgentA`.
- Freeciv created `Valdemar Sejr` / Danish for `AgentB`.
- Animal Kingdom barbarian player was also present.
- Starting units for AgentA included unit IDs `101`, `103`, `104`, `105`.
- Starting units for AgentB included unit IDs `102`, `106`, `107`, `108`.
- Found-city commands created city IDs `116` and `117`.
- Explicit phase-done commands advanced to turn 2.
- Verified `PACKET_UNIT_ORDERS` movement advanced all six post-city starting
  units:
  - AgentA units `105`, `104`, `103`: `429 -> 448 -> 466`.
  - AgentB units `108`, `107`, `106`: `569 -> 551 -> 532`.
- Explicit phase-done commands advanced the game through turn 4 / year `-3850`.
- AgentA produced a new city unit `118` at Alpha on turn 4, confirming
  production-related city/unit updates are entering the state cache.
- Explicit direction movement was also verified: `move-unit AgentA 118
  --direction 4` moved the unit from tile `429` to tile `448`.
- Turn 4 self-play policy used decoded unit types:
  - AgentA Explorer scouted to tile `468`; Worker and Diplomat pulled back to
    tile `448`; Warrior returned to Alpha at turn transition.
  - AgentB Explorer scouted to tile `479`; Worker and Diplomat pulled back to
    tile `551`; Beta produced Warrior `119`.
  - Explicit phase-done commands advanced both players to turn 5 / year `-3800`.

## Current Gaps

Named commands still needed:

- `fortify`
- `road`
- `irrigate`
- `mine`
- `set-city-production`
- `set-research`
- richer `query-actions` / action availability inspection parsing

Important open design question:

- Whether the MCP should expose low-level protocol tools, higher-level game
  actions, or both. The current HTTP/CLI control server should map cleanly to an
  MCP server: `state`, `player_state`, `found_city`, `phase_done`, and future
  named action tools.

Avoid:

- Autonomously ending turns in a loop while debugging. An earlier test
  advanced many turns accidentally. Prefer explicit one-command actions until
  the state/action loop is robust.
