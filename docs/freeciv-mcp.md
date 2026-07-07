# Freeciv MCP Interface

The harness exposes a dependency-free MCP server over stdio:

```bash
scripts/freeciv-mcp --player AgentA --control-url http://127.0.0.1:8787
scripts/freeciv-mcp --player AgentB --control-url http://127.0.0.1:8787
scripts/freeciv-mcp --player AgentC --control-url http://127.0.0.1:8787 --interface-version v1
scripts/freeciv-mcp --player AgentD --control-url http://127.0.0.1:8787 --interface-version v2
```

Run one MCP server per player. The server is player-scoped: tools do not accept
a `player` argument, so an AgentA MCP process cannot casually query or control
AgentB through the same connection.

## Why This Is Useful

The CLI interface tests whether agents can use a small command-line game API.
The MCP interface tests a different variable: same game state and action
surface, but presented as explicit typed tools. That makes it a useful
experiment condition for the video:

- CLI-only player: uses `bin/game` commands.
- MCP player: uses typed tools such as `brief`, `valid_moves`, and
  `move_unit`.
- MCP plus memory player: uses the same tools plus a note-taking mechanism.
- MCP plus structured-turn prompt: uses the same tools with stricter turn
  procedure.

The MCP server intentionally wraps the existing control server instead of
duplicating Freeciv protocol logic. Fixes to movement, production, city founding,
chat, intent logging, or ruleset decoding should happen in the control server
first, then appear through both CLI and MCP.

MCP interface design is versioned so it can be tested as its own experimental
variable. See:

- `docs/freeciv-mcp-versions.md`: overview, comparison matrix, and experiment
  guidance.
- `docs/freeciv-mcp-tool-reference.md`: concrete tool inputs, output shapes,
  JSON examples, and text examples.
- `docs/freeciv-mcp-v0.md`: legacy compact baseline.
- `docs/freeciv-mcp-v1.md`: readable detail split.
- `docs/freeciv-mcp-v2.md`: rich focused tools.
- `docs/freeciv-mcp-artifacts.md`: filesystem artifact mode for MCP tool
  results.

## Codex Config Snippet

For a player-specific Codex config, add one server entry:

```toml
[mcp_servers.freeciv]
command = "/Users/richardwilliams/Game AI Science/freeciv-agent-harness/scripts/freeciv-mcp"
args = ["--player", "AgentA", "--control-url", "http://127.0.0.1:8787", "--interface-version", "v1"]
startup_timeout_sec = 10
```

Use a separate isolated Codex config/workspace for AgentB with `AgentB` in the
args. Do not attach both players' MCP servers to the same player session unless
the experiment is intentionally testing omniscient or referee behavior.

## Match Runner Mode

The standard match runner can expose either the CLI or MCP interface:

```bash
INTERFACE=cli MODEL=gpt-5.5 scripts/start-codex-match
INTERFACE=mcp MODEL=gpt-5.5 scripts/start-codex-match
```

`INTERFACE=cli` keeps the current `bin/game` command surface. `INTERFACE=mcp`
passes a player-scoped MCP server into each Codex turn with config overrides,
then tells the player to use only MCP tools. In MCP mode, the turn runner rejects
shell command execution and file edits by baseline players.

Mixed MCP version example:

```bash
PLAYERS="AgentA AgentB AgentC AgentD" \
MCP_PLAYERS="AgentC AgentD" \
MCP_VERSIONS="AgentC=v1 AgentD=v2" \
MODEL=gpt-5.5 \
scripts/start-codex-match
```

## Tools

Read-only state tools are listed below, but the real schema/examples live in
`docs/freeciv-mcp-tool-reference.md`. Do not treat one-line transport labels as
the documentation; they only describe how the MCP transport returns the payload.

- `brief`: factual state summary for the scoped player. In `v0` this is the
  legacy compact block; in `v1` and `v2` this is a readable overview.
- `units_detail`: `v1+` focused unit detail view.
- `cities_detail`: `v1+` focused city detail view.
- `economy_detail`: `v1+` economy, research, ruleset, and key production view.
- `turn_dashboard`: `v2` one-screen turn dashboard.
- `units_ready`: `v2` units with moves remaining.
- `city_production_options`: `v2` readable production options and optional
  city-specific legality.
- `research_options`: `v2` readable research options.
- `map_topology`: `v2` topology, wrapping, and legal direction names.
- `recent_messages`: `v2` formatted recent messages.
- `state_snapshot`: `v2` full decoded player-visible state snapshot. Best used
  with MCP artifact mode.
- `production_targets`: exact city production names. In `civ2civ3`,
  `Settlers` are city founders; `Migrants` are not valid for `found_city`.
- `messages`: recent Freeciv messages visible to the scoped player.
- `valid_moves`: movement directions and blockers for one unit.
- `ascii_view`: deterministic hex-aware ASCII map around a unit, city, or tile.
- `local_view`: structured local map facts around a unit, city, or tile.

Action tools:

- `move_unit`
- `unit_activity`
- `found_city`
- `set_city_production`
- `set_rates`
- `set_research`
- `set_tech_goal`
- `say`
- `narrative_read`
- `narrative_append`
- `private_intent`
- `phase_done`

When narrative-log mode is enabled, `narrative_append` should be called exactly
once near the end of the turn before `phase_done`. The `phase_done` tool should
be the final action of a normal player turn. Pass an `intent` string to preserve
private narration/audit data for the match.

## Smoke Test

With the control server running:

```bash
python3 -m py_compile freeciv_agent/mcp_server.py
scripts/freeciv-mcp --player AgentA
```

The second command waits for MCP JSON-RPC messages on stdin. A real MCP client
should send `initialize`, then `tools/list`, then `tools/call`.
