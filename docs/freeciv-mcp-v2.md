# Freeciv MCP v2: Rich Focused Tools

`v2` is the richer MCP interface. It includes all `v1` tools and adds
short, purpose-built factual views for common decision points: turn dashboard,
units ready, city production, research, topology, messages, and bulk state
snapshot export.

## Intended Experimental Role

Use `v2` when the question is:

```text
Does giving the model smaller, task-specific factual tools improve decision
quality and reduce wasted context?
```

This version tests whether interface design can guide the agent toward better
inspection habits without hardcoding strategy.

`v2` should not recommend actions. Its added tools are factual:

- what needs attention;
- what production names are legal/available;
- what research options exist;
- what movement directions mean;
- what messages were visible.

## Startup

Direct server:

```bash
scripts/freeciv-mcp \
  --player AgentD \
  --control-url http://127.0.0.1:8787 \
  --interface-version v2
```

Match runner:

```bash
PLAYERS="AgentA AgentB AgentC AgentD" \
MCP_PLAYERS="AgentD" \
MCP_VERSIONS="AgentD=v2" \
scripts/start-fresh-match
```

Accepted aliases:

- `v2`
- `2`
- `rich`
- `focused`
- `mcp-v2`

## Tool Inventory

`v2` exposes 26 tools.

This table is only an inventory. Concrete input/output examples for every tool
are in `docs/freeciv-mcp-tool-reference.md`.

State tools inherited from `v1`:

| Tool | Concrete output documentation | Purpose |
| --- | --- |
| `brief` | See `brief` in `docs/freeciv-mcp-tool-reference.md`. | Readable main overview. |
| `units_detail` | See `units_detail` in `docs/freeciv-mcp-tool-reference.md`. | All-unit or single-unit detail. |
| `cities_detail` | See `cities_detail` in `docs/freeciv-mcp-tool-reference.md`. | All-city or single-city detail. |
| `economy_detail` | See `economy_detail` in `docs/freeciv-mcp-tool-reference.md`. | Economy, research, ruleset, and key production summary. |
| `production_targets` | See `production_targets` in `docs/freeciv-mcp-tool-reference.md`. | Exact ruleset build targets. |
| `messages` | See `messages` in `docs/freeciv-mcp-tool-reference.md`. | Raw recent visible messages. |
| `valid_moves` | See `valid_moves` in `docs/freeciv-mcp-tool-reference.md`. | Movement facts and blockers for one unit. |
| `ascii_view` | See `ascii_view` in `docs/freeciv-mcp-tool-reference.md`. | Hex-aware local map text. |
| `local_view` | See `local_view` in `docs/freeciv-mcp-tool-reference.md`. | Structured local map facts. |

Additional `v2` state tools:

| Tool | Input | Concrete output documentation | Purpose |
| --- | --- | --- | --- |
| `turn_dashboard` | none | See `turn_dashboard` in `docs/freeciv-mcp-tool-reference.md`. | One-screen open-work dashboard. |
| `units_ready` | none | See `units_ready` in `docs/freeciv-mcp-tool-reference.md`. | Only units with moves remaining. |
| `city_production_options` | `city_id?: integer`, `all?: boolean` | See `city_production_options` in `docs/freeciv-mcp-tool-reference.md`. | Production choices, optionally city-specific. |
| `research_options` | none | See `research_options` in `docs/freeciv-mcp-tool-reference.md`. | Current, goal, known count, available techs. |
| `map_topology` | none | See `map_topology` in `docs/freeciv-mcp-tool-reference.md`. | Legal direction names and topology facts. |
| `recent_messages` | `limit?: integer` | See `recent_messages` in `docs/freeciv-mcp-tool-reference.md`. | Formatted recent messages. |
| `state_snapshot` | none | See `state_snapshot` in `docs/freeciv-mcp-tool-reference.md`. | Full decoded player-visible state snapshot. Best with artifact mode. |

Action tools are unchanged from `v0` and `v1`, including `narrative_read` and
`narrative_append` for the explicit narrative-log experiment.

## Main View: `brief`

In `v2`, `brief` is the same readable overview as `v1`.

The difference is that the agent has more focused tools available after reading
the overview. The turn prompt lists those tools explicitly:

```text
- turn_dashboard
- units_ready
- city_production_options
- research_options
- map_topology
- recent_messages
- state_snapshot
```

## `turn_dashboard`

Input: none.

Purpose: provide a single factual "what is open this turn?" view.

Output sections:

- turn and active phase;
- open unit work;
- cities and production;
- economy and research;
- counts;
- related tools.

Expected output shape:

```text
# AgentD Turn Dashboard

Turn: 7 (-3700)
Active phase: yes
Phase: Players Alternate

## Open Unit Work
- Explorer #116 at tile 823: moves 4, hp 10, activity unknown
- Workers #114 at tile 695: moves 6, hp 10, activity Idle

## Cities And Production
- Musehaven #129 at tile 668: size 1, food stock 6, shield stock 12, producing Phalanx

## Economy And Research
- Economy: gold 56, tax 40%, science 60%, luxury 0%
- Research: Pottery, cost 30, progress 12, goal Ceremonial Burial

## Counts
- Units with moves: 2
- Other units: 1
- Cities: 1

## Related Tools
- units_ready(): only units with moves.
- cities_detail(city_id optional): detailed city facts.
- city_production_options(city_id optional): exact production choices.
- research_options(): readable technology state.
- map_topology(): movement direction and wrapping facts.
```

Use this as the first read when the agent wants a concise turn checklist.

## `units_ready`

Input: none.

Purpose: prevent the model from overlooking units with remaining moves.

Output includes:

- turn;
- count of units with moves;
- one concise line per ready unit;
- per-unit related tools.

Expected output shape:

```text
# AgentD Units Ready

Turn: 7 (-3700)
Units with moves remaining: 2

- Workers #114 at tile 695: moves 6, hp 10, activity Idle
- Explorer #116 at tile 823: moves 4, hp 10, activity unknown

## Per-Unit Tools
- valid_moves(unit_id): movement facts.
- ascii_view(unit_id, radius optional): local hex map.
- unit_activity(unit_id, activity): work/fortify/activity order.
- move_unit(unit_id, direction/target_tile/dx/dy): movement order.
```

This tool does not say what the unit should do. It only makes unfinished unit
work hard to miss.

## `city_production_options`

Input:

```json
{
  "city_id": 129,
  "all": false
}
```

Both fields are optional.

Behavior:

- With no `city_id`, it returns the standard production target summary.
- With `city_id`, it asks the control API for city-specific production facts.
- With `all=true`, it includes every decoded unit and building target.

Use this before calling `set_city_production`. The output uses exact command
target names, so the agent should copy the `target` value exactly.

## `research_options`

Input: none.

Purpose: give the model a readable research menu instead of making it infer
research choices from raw JSON.

Output includes:

- current research;
- current cost;
- progress bulbs;
- bulbs per turn;
- current goal;
- known technology count;
- available technologies with ids, costs, and states;
- related tools.

Expected output shape:

```text
# AgentD Research

Current research: Pottery
Current cost: 30
Progress bulbs: 12
Bulbs per turn: 2
Current goal: Ceremonial Burial
Known technologies: 1

## Available Technologies (7)
- Alphabet #2, cost 10.0, state prerequisites known
- Currency #20, cost 20.0, state prerequisites known
- Horseback Riding #35, cost 10.0, state prerequisites known

## Related Tools
- set_research(tech): set current research by exact name or id.
- set_tech_goal(tech): set longer-term technology goal by exact name or id.
```

## `map_topology`

Input: none.

Purpose: decode Freeciv topology and direction ids into language.

Output includes:

- map size;
- topology name;
- whether the map is hex;
- whether the map is isometric;
- wrapping;
- valid movement direction ids/names/dx/dy;
- invalid direction names for this topology.

Expected output shape:

```text
# AgentD Map Topology

Map size: 26 x 52
Topology: isometric hex
Is hex: yes
Is isometric: yes
Wrap: wraps east-west and north-south

## Valid Movement Directions
- 0: northwest (dx -1, dy -1)
- 1: north (dx 0, dy -1)
- 3: west (dx -1, dy 0)
- 4: east (dx 1, dy 0)
- 6: south (dx 0, dy 1)
- 7: southeast (dx 1, dy 1)

## Invalid Direction Names For This Topology
- 2: northeast (not adjacent on this topology)
- 5: southwest (not adjacent on this topology)
```

Use this when an agent is confused about direction ids, hex adjacency, or why a
direction is invalid.

## `recent_messages`

Input:

```json
{
  "limit": 10
}
```

Purpose: provide recent messages in readable text. The older `messages` tool is
still available and returns the raw message object shape documented in
`docs/freeciv-mcp-tool-reference.md`.

Output includes:

- requested limit;
- messages returned;
- one line per message.

## `state_snapshot`

Input: none.

Purpose: export the full decoded player-visible state that the control server
currently has for this player.

This tool is intentionally bulky. Use it with MCP artifact mode `mirror` or
`file-only` unless you explicitly want to flood the context with the full JSON.

It calls:

```text
GET /players/<player>
```

The result can include:

- player identity and connection state;
- ruleset summary;
- map topology;
- all known tiles for this player;
- owned/visible units and cities;
- decoded unit type table;
- decoded building table;
- decoded terrain table;
- decoded extras table;
- decoded technology table;
- research state;
- recent visible messages;
- packet counts and last error.

This is the best current tool for the "filesystem-resident bulk data" experiment
described in `docs/freeciv-mcp-artifacts.md`.

## Typical Turn Flow

A reasonable `v2` turn flow:

1. Call `turn_dashboard`.
2. If no cities are visible, call `found_city`.
3. Call `units_ready` to make sure every unit with moves is considered.
4. For a selected unit, call `valid_moves` and/or `ascii_view`.
5. For production choices, call `city_production_options(city_id=...)`.
6. For research choices, call `research_options`.
7. If movement direction ids are confusing, call `map_topology`.
8. If bulk state analysis is needed and artifact mode is enabled, call
   `state_snapshot` and inspect the written file.
9. Execute actions.
10. Call `phase_done` with private `intent`.

This is not a hardcoded policy. It is an inspection pattern.

## Strengths

- Makes unfinished unit actions very salient.
- Reduces need to parse large JSON blobs.
- Gives research and production their own interfaces.
- Provides direction/topology decoding without requiring protocol knowledge.
- Keeps tools factual rather than strategic.

## Weaknesses

- Larger tool surface can increase tool-choice overhead.
- Agents may over-inspect if the prompt does not encourage timely action.
- More tools means more interface behavior to document and test.
- `local_view` still exists as raw JSON for cases where structured map facts are
  useful.

## Best Use In Experiments

Good comparisons:

- MCP v1 vs MCP v2 with identical model, victory focus, and prompt style.
- MCP v2 with and without memory.
- MCP v2 with normal prompt vs structured turn prompt.

Avoid making `v2` silently smarter than other versions. It should expose facts
better, not choose strategy for the player.
