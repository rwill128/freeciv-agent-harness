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
python3 -m freeciv_agent.control_cli found-city AgentA --city-name Alpha
python3 -m freeciv_agent.control_cli move-unit AgentA 105 --dx 1
python3 -m freeciv_agent.control_cli move-unit AgentA 105 --direction 4
python3 -m freeciv_agent.control_cli phase-done AgentA
```

## Development Notes

- Do not reintroduce automatic turn-ending loops for debugging. Use explicit
  one-command actions.
- Prefer named high-level commands over raw packet sends.
- Unit movement uses `PACKET_UNIT_ORDERS`, not `PACKET_UNIT_DO_ACTION`.
- Keep the GTK observer path working; this project is for visible recorded
  games, not headless-only play.
- For player-perspective recordings, use server console commands such as
  `observe AgentAView Matthias` and `observe Observer "Valdemar Sejr"`; this
  preserves each player's fog of war.
- Add new packet IDs, quirks, and verified command shapes to
  `docs/freeciv-agent-harness.md`.
