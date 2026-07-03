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

The Homebrew GTK client works as the visible observer:

```sh
/opt/homebrew/bin/freeciv-gtk4 -a -s 127.0.0.1 -p 5560 -n Observer
```

Use the server console to attach it as a global observer:

```text
observe Observer
```

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
python3 -m freeciv_agent.control_cli phase-done AgentA
python3 -m freeciv_agent.control_cli packet AgentA '{"pid":89}'
```

HTTP endpoints currently implemented:

- `GET /state`
- `GET /players/{name}`
- `POST /players/{name}/ready`
- `POST /players/{name}/phase-done`
- `POST /players/{name}/found-city`
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
- `84`: `PACKET_UNIT_DO_ACTION`
- `88`: `PACKET_CONN_PING`
- `89`: `PACKET_CONN_PONG`
- `127`: `PACKET_NEW_YEAR`

Freeciv uses delta encoding for many JSON packets. Delta packets include a
`fields` byte array bitvector. Important examples:

- Ready true first send: `{"pid":11,"fields":[3],"player_no":0}`
- Phase done first send: `{"pid":52,"fields":[1],"turn":1}`
- Unit action first send: `pid=84`, `fields:[31]`, and all five action fields.

For player 0, fields with value zero may be omitted by delta encoding. The
controller must treat omitted `owner` values in owned unit/city packets as the
current player's `player_no` when reconstructing state.

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

## Current Gaps

Named commands still needed:

- `move-unit`
- `fortify`
- `road`
- `irrigate`
- `mine`
- `set-city-production`
- `set-research`
- `query-actions` / action availability inspection

Important open design question:

- Whether the MCP should expose low-level protocol tools, higher-level game
  actions, or both. The current HTTP/CLI control server should map cleanly to an
  MCP server: `state`, `player_state`, `found_city`, `phase_done`, and future
  named action tools.

Avoid:

- Autonomously ending turns in a loop while debugging. An earlier test
  advanced many turns accidentally. Prefer explicit one-command actions until
  the state/action loop is robust.

