# Freeciv MCP v0: Legacy Compact Baseline

`v0` is the baseline MCP interface. It exposes the same action authority as the
newer MCP versions, but it keeps the old compact state presentation. This makes
it useful for isolating whether typed tool calls help by themselves, without
giving the agent a much better state-reading interface.

## Intended Experimental Role

Use `v0` when the question is:

```text
If the agent has typed tools instead of CLI commands, but the state view is
still compact and somewhat hard to read, does it play better?
```

This version should be treated as the "MCP mechanics only" condition:

- It has MCP tool schemas.
- It has player scoping.
- It has the same action tools as later versions.
- It does not add focused detail tools.
- It does not try to reduce cognitive overhead much beyond wrapping CLI views.

## Startup

Direct server:

```bash
scripts/freeciv-mcp \
  --player AgentC \
  --control-url http://127.0.0.1:8787 \
  --interface-version v0
```

Match runner:

```bash
PLAYERS="AgentA AgentB AgentC AgentD" \
MCP_PLAYERS="AgentC" \
MCP_VERSIONS="AgentC=v0" \
scripts/start-fresh-match
```

Accepted aliases:

- `v0`
- `0`
- `legacy`
- `compact`
- `mcp-v0`

## Tool Inventory

`v0` exposes 16 tools.

This table is only an inventory. Concrete input/output examples for every tool
are in `docs/freeciv-mcp-tool-reference.md`.

State tools:

| Tool | Input | Concrete output documentation | Notes |
| --- | --- | --- | --- |
| `brief` | none | See `brief` in `docs/freeciv-mcp-tool-reference.md`. | Legacy main view. |
| `production_targets` | `all?: boolean` | See `production_targets` in `docs/freeciv-mcp-tool-reference.md`. | Exact build targets. |
| `messages` | `limit?: integer` | See `messages` in `docs/freeciv-mcp-tool-reference.md`. | Recent visible messages. |
| `valid_moves` | `unit_id: integer` | See `valid_moves` in `docs/freeciv-mcp-tool-reference.md`. | Movement facts and blockers. |
| `ascii_view` | `unit_id?`, `city_id?`, `tile_id?`, `radius?` | See `ascii_view` in `docs/freeciv-mcp-tool-reference.md`. | Local hex-aware map. |
| `local_view` | `unit_id?`, `city_id?`, `tile_id?`, `radius?` | See `local_view` in `docs/freeciv-mcp-tool-reference.md`. | Structured local map facts. |

Action tools:

| Tool | Required input | Optional input | Concrete output documentation |
| --- | --- | --- | --- |
| `move_unit` | `unit_id` | `direction`, `target_tile`, `dx`, `dy`, `wait` | See `move_unit` in `docs/freeciv-mcp-tool-reference.md`. |
| `unit_activity` | `unit_id`, `activity` | `target`, `wait` | See `unit_activity` in `docs/freeciv-mcp-tool-reference.md`. |
| `found_city` | none | `unit_id`, `city_name`, `wait` | See `found_city` in `docs/freeciv-mcp-tool-reference.md`. |
| `set_city_production` | `city_id`, `target` | `kind`, `wait` | See `set_city_production` in `docs/freeciv-mcp-tool-reference.md`. |
| `set_rates` | `tax`, `luxury`, `science` | `wait` | See `set_rates` in `docs/freeciv-mcp-tool-reference.md`. |
| `set_research` | `tech` | `wait` | See `set_research` in `docs/freeciv-mcp-tool-reference.md`. |
| `set_tech_goal` | `tech` | `wait` | See `set_tech_goal` in `docs/freeciv-mcp-tool-reference.md`. |
| `say` | `message` | none | See `say` in `docs/freeciv-mcp-tool-reference.md`. |
| `narrative_read` | none | `limit_chars` | See `narrative_read` in `docs/freeciv-mcp-tool-reference.md`. |
| `narrative_append` | `entry` | `turn`, `year` | See `narrative_append` in `docs/freeciv-mcp-tool-reference.md`. |
| `private_intent` | `intent` | `turn` | See `private_intent` in `docs/freeciv-mcp-tool-reference.md`. |
| `phase_done` | none | `intent`, `turn` | See `phase_done` in `docs/freeciv-mcp-tool-reference.md`. |

## Main View: `brief`

`brief` calls the control API endpoint:

```text
GET /players/<player>/brief
```

Then it formats the result with the same compact formatter used by the player
CLI. The only MCP-specific changes are replacing CLI command names with MCP
tool names.

Expected output shape:

```text
AgentC turn 7 year -3700 active_phase=True phase=Players Alternate
Ruleset: rulesetdir=civ2civ3 rules_doc=docs/freeciv-rules-for-agents.md
Key production targets: city_founding=Settlers; early_military=Warriors,Phalanx...
Economy: gold=56 tax=40 science=60 luxury=None
Research: Pottery cost=30 known_techs=1
Cities:
  129:Musehaven tile=668 size=1 food=6 shields=12 producing=Phalanx command_target=Phalanx
Units needing attention (movesleft > 0): 3
  115:Diplomat tile=668 movesleft=12 hp=10 activity=Fortified
  114:Workers tile=695 movesleft=6 hp=10 activity=Idle
Other units: 0
Inspect units with MCP tools: valid_moves(unit_id) or ascii_view(unit_id)
```

This is intentionally dense. It is useful as a baseline because it makes the
agent do more work to parse the state.

## Typical Turn Flow

Expected agent flow:

1. Call `brief`.
2. If there are no cities, call `found_city`.
3. For each unit with `movesleft > 0`, call `valid_moves` and/or `ascii_view`.
4. Execute actions with `move_unit`, `unit_activity`, production/research tools,
   or chat tools.
5. If narrative logging is enabled, call `narrative_append` once with the
   visible story entry.
6. Call `phase_done` with a private `intent`.

## Strengths

- Smallest MCP surface.
- Easy to compare against CLI because it reuses the compact CLI state view.
- Lower tool-discovery burden than later versions.
- Same action tools as the richer MCP versions.

## Weaknesses

- The main view is one dense block.
- City, unit, economy, research, and production facts are mixed together.
- `messages` and `local_view` expose raw structured payloads rather than
  readable summaries.
- There are no task-specific views such as "units ready" or "research options."
- Agents may overlook units with moves or misread production/research state.

## What v0 Should Not Do

`v0` should not grow new detail tools. If a new focused state tool is needed,
add it to `v1` or `v2`. Keeping `v0` stable matters because it is the legacy
baseline condition.

## Best Use In Experiments

Good comparisons:

- CLI vs MCP v0.
- MCP v0 vs MCP v1 with same model and victory mode.
- MCP v0 vs MCP v2 with same model and victory mode.

Avoid comparing v0 against a different model or different memory setting unless
that is the explicit experiment.
