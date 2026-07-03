# Freeciv Agent Harness

This harness is for visible Freeciv games where agents control players and a
normal GTK client stays connected as the recording view.

Detailed protocol and MCP-design notes live in
`docs/freeciv-agent-harness.md`.

## Current Working Setup

Start the JSON-capable Freeciv 3.2 server built from the local S3_2 worktree:

```sh
cd "/Users/richardwilliams/Documents/Game AI Science/freeciv-s3_2-agent/build-agent-server"
./run.sh freeciv-server --Announce none -p 5560
```

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
cd "/Users/richardwilliams/Documents/Game AI Science/freeciv-agent-harness"
python3 -m freeciv_agent.smoke_join --name AgentA --listen-seconds 5
```

The important split is:

- GTK client: visible recording/observer view, using Freeciv's normal binary protocol.
- Agent clients: structured control sockets, using Freeciv's JSON protocol on the same server.

## Status

The current Python control server keeps persistent player sockets open and
exposes a local control surface:

```sh
python3 -m freeciv_agent.control_server --players AgentA AgentB
python3 -m freeciv_agent.control_cli state
python3 -m freeciv_agent.control_cli brief
python3 -m freeciv_agent.control_cli brief AgentA
python3 -m freeciv_agent.control_cli local-view AgentA --unit-id 105 --radius 2
python3 -m freeciv_agent.control_cli ready AgentA
python3 -m freeciv_agent.control_cli phase-done AgentA
python3 -m freeciv_agent.control_cli found-city AgentA --city-name Alpha
python3 -m freeciv_agent.control_cli move-unit AgentA 105 --dx 1
python3 -m freeciv_agent.control_cli move-unit AgentA 105 --direction 4
python3 -m freeciv_agent.control_cli unit-activity AgentA 103 mine
python3 -m freeciv_agent.control_cli unit-activity AgentA 103 road --target Road
python3 -m freeciv_agent.control_cli packet AgentA '{"pid":89}'
```

Implemented commands cover join, ready, phase done, ping/pong, compact unit/city
state, local terrain/resource views, ruleset unit-type/terrain/extra decoding,
city founding, unit movement, worker activities, action queries, and a raw
packet escape hatch. Unit movement uses Freeciv `PACKET_UNIT_ORDERS` and
accounts for the default isometric-hex map topology when translating `--dx/--dy`.
`move-unit` and `unit-activity` return both the attempted command and observed
unit state after the command, so an agent can distinguish an applied command
from a sent but unapplied order.

Still-needed named commands include city production and research selection.
