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

Start a visible GTK client for recording:

```sh
/opt/homebrew/bin/freeciv-gtk4 -a -s 127.0.0.1 -p 5560 -n Observer
```

In the server console, make that GUI connection a global observer:

```text
observe Observer
```

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
python3 -m freeciv_agent.control_cli ready AgentA
python3 -m freeciv_agent.control_cli phase-done AgentA
python3 -m freeciv_agent.control_cli found-city AgentA --city-name Alpha
python3 -m freeciv_agent.control_cli packet AgentA '{"pid":89}'
```

Implemented commands cover join, ready, phase done, ping/pong, compact unit/city
state, and a raw packet escape hatch. The next layer should add named commands
for unit movement, city production, and city founding instead of requiring raw
packet IDs.
