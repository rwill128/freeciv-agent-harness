# Freeciv Agent Harness Notes

This repo contains the local control harness for visible Freeciv agent games.
Read `docs/freeciv-agent-harness.md` before changing protocol or runtime code.
Read `docs/freeciv-rules-for-agents.md` before changing agent prompts,
ruleset-facing views, or strategic game-state summaries.
For the Civ 6 adapter track, read `docs/civ6-agent-bridge.md` before changing
`civ6_agent/`, `civ6_mods/`, or Civ 6 bridge scripts.

## Runtime Model

- Freeciv server: JSON-capable S3_2 build, usually on port `5560`.
- Visible recorder: normal GTK client attached as a player observer when
  recording fog-of-war perspective; global observer is for debugging only.
- Controlled players: persistent Python JSON clients owned by
  `freeciv_agent.control_server`.
- Control surface: local HTTP on `127.0.0.1:8787` plus
  `freeciv_agent.control_cli`.
- Turn semantics: use Freeciv `set phasemode PLAYER` for isolated LLM games so
  only the active player can move during a phase. The harness views decode
  `phase_mode` and report whether the current agent is in the active phase.

## Working Commands

```sh
scripts/freeciv-runtime start
scripts/freeciv-runtime status
scripts/freeciv-runtime logs
scripts/freeciv-runtime stop
python3 -m freeciv_agent.control_server --players AgentA AgentB
python3 -m freeciv_agent.control_cli state
python3 -m freeciv_agent.control_cli ruleset
python3 -m freeciv_agent.control_cli brief
python3 -m freeciv_agent.control_cli messages AgentA --limit 20
python3 -m freeciv_agent.control_cli local-view AgentA --unit-id <unit_id> --radius 2
python3 -m freeciv_agent.control_cli ascii-view AgentA --unit-id <unit_id> --radius 3 --text
python3 -m freeciv_agent.control_cli valid-moves AgentA <unit_id>
python3 -m freeciv_agent.control_cli found-city AgentA --city-name ExampleCity
python3 -m freeciv_agent.control_cli move-unit AgentA <unit_id> --dx 1
python3 -m freeciv_agent.control_cli move-unit AgentA <unit_id> --direction 4
python3 -m freeciv_agent.control_cli unit-activity AgentA <unit_id> mine
python3 -m freeciv_agent.control_cli unit-activity AgentA <unit_id> road --target Road
python3 -m freeciv_agent.control_cli say AgentA "public message"
python3 -m freeciv_agent.control_cli phase-done AgentA --intent "private turn intent"
```

## Development Notes

- Do not reintroduce automatic turn-ending loops for debugging. Use explicit
  one-command actions.
- Prefer `scripts/freeciv-runtime start` for durable local runs. It detaches the
  Freeciv server and control server from the Codex tool session and writes logs
  under `runtime/logs`.
- Do not run isolated LLM players under Freeciv concurrent phase mode
  (`phasemode ALL`). Use `phasemode PLAYER` unless the experiment explicitly
  studies simultaneous play.
- Prefer named high-level commands over raw packet sends.
- Public diplomacy/chat uses `say`. Private turn narration uses
  `phase-done --intent` or `private-intent`; it is written to harness artifacts
  and must not be treated as player memory.
- Player-authored `narrative.md` files are allowed only when the explicit
  narrative-log experiment is enabled. They live under `players/<Agent>/` and
  are runtime artifacts, not project documentation.
- Unit movement uses `PACKET_UNIT_ORDERS`, not `PACKET_UNIT_DO_ACTION`.
- Worker tasks use the generic `unit-activity` command backed by
  `PACKET_UNIT_CHANGE_ACTIVITY`; do not add separate commands for every worker
  activity unless an LLM-facing workflow clearly needs a semantic shortcut.
- `brief` is the preferred state read for an LLM agent turn; `state` is the
  full debugging payload.
- Use `messages` to inspect recent Freeciv server replies after raw packet or
  server-command probes.
- Use `local-view` around active units and cities before scout or tactical
  moves. It exposes terrain/resources and visible units/cities in a compact
  radius.
- Use `ascii-view --text` when an agent needs the same local facts as a stable
  spatial prompt artifact. It is a rendering of current state only.
- Use `valid-moves` before moving a unit. It exposes current legal topology
  directions and known target terrain, without recording history or making
  recommendations.
- `move-unit` reports observed `before`/`after` state plus `applied`, not just
  that the packet was sent.
- Keep the GTK viewer path working; this project is for visible recorded games,
  not headless-only play.
- Launch GTK clients in detached `screen` sessions. Plain background `nohup`
  launches can die when the launching shell exits.
- Observer mode needs extra localhost connection capacity. Fresh-match startup
  sets `maxconnectionsperhost 16`; four controlled players plus four
  `Agent*View` observers will fail against Freeciv's default per-host limit of
  4.
- `scripts/start-player-viewers` defaults to `VIEWER_MODE=player`, which logs
  GUI clients in as `AgentA`, `AgentB`, etc. This gives each window that
  player's fog of war and avoids `observe` leader-name encoding problems.
- `VIEWER_MODE=observer` keeps protocol clients as the player owners and logs
  GUI clients in as `AgentAView`, `AgentBView`, etc., then runs `observe`.
  That mode is currently reliable only when the in-game leader names are ASCII
  or when the observe command is sent through a UTF-8-safe admin path; the
  `screen` console mangles non-ASCII leader names.
- Add new packet IDs, quirks, and verified command shapes to
  `docs/freeciv-agent-harness.md`.
- Do not record live-game turn notes, current board positions, or save-specific
  plans in project docs. Keep docs about the harness and interface.
