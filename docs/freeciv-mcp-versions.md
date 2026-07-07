# Freeciv MCP Interface Versions

MCP design is a first-class experiment variable in this harness. The same live
Freeciv match can run different player-scoped MCP servers side by side, with
each server exposing a different interface version to its assigned agent.

This document is the index and comparison guide. The detailed version specs are:

- `docs/freeciv-mcp-v0.md`: legacy compact MCP baseline.
- `docs/freeciv-mcp-v1.md`: readable overview plus focused detail tools.
- `docs/freeciv-mcp-v2.md`: richer purpose-built factual tools.
- `docs/freeciv-mcp-tool-reference.md`: actual tool inputs, output JSON/text
  shapes, and examples.
- `docs/freeciv-mcp-artifacts.md`: filesystem artifact mode for tool results.

## Shared Architecture

Every MCP version is a thin stdio wrapper around the same local control server:

```text
Codex player session
  -> player-scoped MCP server process
     -> local control API at http://127.0.0.1:8787
        -> persistent player-scoped Freeciv JSON socket
           -> Freeciv server
```

The MCP server is started with one player name:

```bash
scripts/freeciv-mcp --player AgentC --control-url http://127.0.0.1:8787 --interface-version v1
```

Tools do not accept a `player` argument. That is intentional. A player-scoped
MCP process can only call endpoints under `/players/<that-player>/...`.

The MCP version changes presentation and tool granularity. It must not change:

- Freeciv rules.
- hidden-information boundaries.
- which player is controlled.
- action authority.
- whether an action succeeds in Freeciv.

## Version Matrix

| Version | Tool count | Core idea | Best experiment question |
| --- | ---: | --- | --- |
| `v0` | 16 | Typed tools with the old compact state text. | Does MCP tool calling help by itself? |
| `v1` | 19 | Readable main summary plus detail drill-downs. | Does clearer state formatting improve play? |
| `v2` | 26 | Short task-specific factual tools plus optional bulk state snapshot. | Does richer tool decomposition improve decisions and reduce wasted context? |

## State Tool Availability

| Tool | v0 | v1 | v2 | Purpose |
| --- | --- | --- | --- | --- |
| `brief` | yes | yes | yes | Main state entry point. Output differs by version. |
| `production_targets` | yes | yes | yes | Exact ruleset build target names. |
| `messages` | yes | yes | yes | Raw recent visible Freeciv messages; concrete JSON example in `docs/freeciv-mcp-tool-reference.md`. |
| `valid_moves` | yes | yes | yes | Movement facts and blockers for one unit. |
| `ascii_view` | yes | yes | yes | Hex-aware local map text. |
| `local_view` | yes | yes | yes | Structured local map facts; concrete JSON example in `docs/freeciv-mcp-tool-reference.md`. |
| `units_detail` | no | yes | yes | Focused unit facts, all units or one unit. |
| `cities_detail` | no | yes | yes | Focused city facts, all cities or one city. |
| `economy_detail` | no | yes | yes | Economy, research, ruleset, production summary. |
| `turn_dashboard` | no | no | yes | One-screen actionable turn dashboard. |
| `units_ready` | no | no | yes | Only units with moves remaining. |
| `city_production_options` | no | no | yes | Production targets, optionally city-specific. |
| `research_options` | no | no | yes | Readable current and available tech state. |
| `map_topology` | no | no | yes | Legal direction names and topology facts. |
| `recent_messages` | no | no | yes | Formatted recent visible messages. |
| `state_snapshot` | no | no | yes | Full decoded player-visible state snapshot. |

## Action Tool Availability

All versions expose the same action tools:

| Tool | Purpose |
| --- | --- |
| `move_unit` | Move an owned unit by direction, target tile, or relative dx/dy. |
| `unit_activity` | Start/change an owned unit activity such as road, mine, irrigate, or fortify. |
| `found_city` | Try to found a city after asking Freeciv whether Found City is legal. |
| `set_city_production` | Set a city build target using exact production target names. |
| `set_rates` | Set tax/luxury/science rates. |
| `set_research` | Set current research by exact tech name or id. |
| `set_tech_goal` | Set longer-term technology goal by exact tech name or id. |
| `say` | Send public in-game chat. |
| `narrative_read` | Read the scoped player's narrative.md story log. |
| `narrative_append` | Append one scoped player story entry to narrative.md. |
| `private_intent` | Record private narration/audit intent without ending phase. |
| `phase_done` | End the player's phase, optionally recording private intent. |

## Running Versions Side By Side

Direct MCP server examples:

```bash
scripts/freeciv-mcp --player AgentC --control-url http://127.0.0.1:8787 --interface-version v1
scripts/freeciv-mcp --player AgentD --control-url http://127.0.0.1:8787 --interface-version v2
```

Four-player match example:

```bash
PLAYERS="AgentA AgentB AgentC AgentD" \
MCP_PLAYERS="AgentC AgentD" \
MCP_VERSIONS="AgentC=v1 AgentD=v2" \
VICTORY_MODES="AgentA=conquest AgentB=spacerace AgentC=culture AgentD=score" \
MODEL=gpt-5.5 \
scripts/start-fresh-match
```

`MCP_PLAYERS` chooses which players use MCP instead of CLI. `MCP_VERSIONS`
chooses the MCP version for those players. If a player uses MCP and is not
listed in `MCP_VERSIONS`, it defaults to `v1`.

Aliases accepted by the MCP server:

- `v0`, `0`, `legacy`, `compact`, `mcp-v0`
- `v1`, `1`, `readable`, `details`, `mcp-v1`
- `v2`, `2`, `rich`, `focused`, `mcp-v2`

## Codex Prompt Integration

When a player uses MCP, the turn runner passes the selected version into the MCP
server command:

```text
--interface-version v2
```

It also tells the agent which version it is using and lists the version-specific
tools. That matters because the same player model should not have to discover
the entire interface from scratch every turn.

## Experiment Discipline

To compare MCP versions cleanly:

- Keep model, victory focus, map settings, ruleset, and turn timeout fixed.
- Start from fresh player sessions with `RESET_SESSIONS=1`.
- Assign different MCP versions symmetrically across multiple matches.
- Record `runtime/matches/latest-codex-match-history.json`; it includes the
  interface and MCP version used for each turn.
- Use `runtime/turns/*-codex-exec-transcript.json` to inspect tool use.
- Use `runtime/audit/private-intents.jsonl` for the player-stated intent at end
  of turn.
- Do not compare a stale-context player against a fresh-context player unless
  that is the intentional experiment.

## What To Measure

Useful metrics for MCP-design comparisons:

- Turn completion rate.
- Average number of tool calls per turn.
- Phase-done success rate.
- Number of illegal or rejected actions.
- Number of turns with idle units left unused.
- City founding speed.
- City production relevance.
- Research relevance.
- Military production and survival.
- Exploration coverage.
- Private intent quality and specificity.
- Match outcome: conquest, score, survival, city count, tech count, and other
  ruleset-visible outcomes.

## Implementation Pointers

Current code:

- `freeciv_agent/mcp_server.py`: MCP version registry, tools, schemas, and text
  formatters.
- `freeciv_agent/codex_turn_runner.py`: per-turn prompt and MCP config.
- `freeciv_agent/codex_match_runner.py`: per-player `MCP_VERSIONS` assignment.
- `scripts/freeciv-mcp`: stdio wrapper.
- `scripts/start-codex-match`: detached match runner startup.
- `scripts/start-fresh-match`: full fresh runtime startup.
