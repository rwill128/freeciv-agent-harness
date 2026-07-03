# Freeciv Agent Harness Notes

This repo contains the local control harness for visible Freeciv agent games.
Read `docs/freeciv-agent-harness.md` before changing protocol or runtime code.

## Runtime Model

- Freeciv server: JSON-capable S3_2 build, usually on port `5560`.
- Visible recorder: normal GTK client attached as a player observer when
  recording fog-of-war perspective; global observer is for debugging only.
- Controlled players: persistent Python JSON clients owned by
  `freeciv_agent.control_server`.
- Control surface: local HTTP on `127.0.0.1:8787` plus
  `freeciv_agent.control_cli`.

## Working Commands

```sh
python3 -m freeciv_agent.control_server --players AgentA AgentB
python3 -m freeciv_agent.control_cli state
python3 -m freeciv_agent.control_cli brief
python3 -m freeciv_agent.control_cli local-view AgentA --unit-id 105 --radius 2
python3 -m freeciv_agent.control_cli found-city AgentA --city-name Alpha
python3 -m freeciv_agent.control_cli move-unit AgentA 105 --dx 1
python3 -m freeciv_agent.control_cli move-unit AgentA 105 --direction 4
python3 -m freeciv_agent.control_cli unit-activity AgentA 103 mine
python3 -m freeciv_agent.control_cli unit-activity AgentA 103 road --target Road
python3 -m freeciv_agent.control_cli phase-done AgentA
```

## Development Notes

- Do not reintroduce automatic turn-ending loops for debugging. Use explicit
  one-command actions.
- Prefer named high-level commands over raw packet sends.
- Unit movement uses `PACKET_UNIT_ORDERS`, not `PACKET_UNIT_DO_ACTION`.
- Worker tasks use the generic `unit-activity` command backed by
  `PACKET_UNIT_CHANGE_ACTIVITY`; do not add separate commands for every worker
  activity unless an LLM-facing workflow clearly needs a semantic shortcut.
- `brief` is the preferred state read for an LLM agent turn; `state` is the
  full debugging payload.
- Use `local-view` around active units and cities before scout or tactical
  moves. It exposes terrain/resources and visible units/cities in a compact
  radius.
- `move-unit` reports observed `before`/`after` state plus `applied`, not just
  that the packet was sent.
- On the current isometric-hex map, diagonal movement directions such as `2`
  have failed even when the target tile was known land. Prefer cardinal
  directions until valid direction handling is decoded.
- Keep the GTK observer path working; this project is for visible recorded
  games, not headless-only play.
- For player-perspective recordings, use server console commands such as
  `observe AgentAView Matthias` and `observe Observer "Valdemar Sejr"`; this
  preserves each player's fog of war.
- Add new packet IDs, quirks, and verified command shapes to
  `docs/freeciv-agent-harness.md`.
