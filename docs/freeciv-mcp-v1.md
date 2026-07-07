# Freeciv MCP v1: Readable Detail Split

`v1` is the default MCP interface. It keeps the same action tools as `v0`, but
changes the state-reading experience: the main `brief` becomes a readable
overview, and the agent gets focused detail tools for units, cities, and
economy/research.

## Intended Experimental Role

Use `v1` when the question is:

```text
Does a clearer, well-sectioned MCP state view make the same model play better?
```

This version tests presentation and decomposition, not more game authority.

Compared with `v0`, `v1` adds:

- readable overview formatting;
- explicit section headers;
- dedicated unit detail view;
- dedicated city detail view;
- dedicated economy/research/ruleset detail view.

## Startup

Direct server:

```bash
scripts/freeciv-mcp \
  --player AgentC \
  --control-url http://127.0.0.1:8787 \
  --interface-version v1
```

Match runner:

```bash
PLAYERS="AgentA AgentB AgentC AgentD" \
MCP_PLAYERS="AgentC" \
MCP_VERSIONS="AgentC=v1" \
scripts/start-fresh-match
```

Accepted aliases:

- `v1`
- `1`
- `readable`
- `details`
- `mcp-v1`

If a player uses MCP and no version is supplied, the default is `v1`.

## Tool Inventory

`v1` exposes 19 tools.

This table is only an inventory. Concrete input/output examples for every tool
are in `docs/freeciv-mcp-tool-reference.md`.

State tools:

| Tool | Input | Concrete output documentation | Notes |
| --- | --- | --- | --- |
| `brief` | none | See `brief` in `docs/freeciv-mcp-tool-reference.md`. | Main overview. |
| `units_detail` | `unit_id?: integer` | See `units_detail` in `docs/freeciv-mcp-tool-reference.md`. | All units or one unit. |
| `cities_detail` | `city_id?: integer` | See `cities_detail` in `docs/freeciv-mcp-tool-reference.md`. | All cities or one city. |
| `economy_detail` | none | See `economy_detail` in `docs/freeciv-mcp-tool-reference.md`. | Economy, research, ruleset, production summary. |
| `production_targets` | `all?: boolean` | See `production_targets` in `docs/freeciv-mcp-tool-reference.md`. | Exact build targets. |
| `messages` | `limit?: integer` | See `messages` in `docs/freeciv-mcp-tool-reference.md`. | Recent visible messages. |
| `valid_moves` | `unit_id: integer` | See `valid_moves` in `docs/freeciv-mcp-tool-reference.md`. | Movement facts and blockers. |
| `ascii_view` | `unit_id?`, `city_id?`, `tile_id?`, `radius?` | See `ascii_view` in `docs/freeciv-mcp-tool-reference.md`. | Local hex-aware map. |
| `local_view` | `unit_id?`, `city_id?`, `tile_id?`, `radius?` | See `local_view` in `docs/freeciv-mcp-tool-reference.md`. | Structured local map facts. |

Action tools are unchanged from `v0`, including `narrative_read` and
`narrative_append` for the explicit narrative-log experiment.

## Main View: `brief`

`brief` calls:

```text
GET /players/<player>/brief
```

Then it emits a readable factual overview.

Expected output shape:

```text
# AgentC Overview

Turn: 7 (-3700)
Active phase: yes
Phase mode: Players Alternate

## Current Status
- Economy: gold 56, tax 40%, science 60%, luxury 0%
- Research: Pottery, cost 30, progress 12, goal Ceremonial Burial
- Known map tiles: 115

## Cities (1)
- Musehaven #129 at tile 668: size 1, food stock 6, shield stock 12, producing Phalanx

## Units Needing Attention (3)
- Diplomat #115 at tile 668: moves 12, hp 10, activity Fortified
- Workers #114 at tile 695: moves 6, hp 10, activity Idle
- Explorer #116 at tile 823: moves 4, hp 10, activity unknown
Other units: 0

## Detail Tools
- units_detail(unit_id optional): unit list or one unit's factual details.
- cities_detail(city_id optional): city list or one city's factual details.
- economy_detail(): economy, research, ruleset, and key production targets.
- valid_moves(unit_id): legal/blocked movement facts for one unit.
- ascii_view(unit_id/city_id/tile_id, radius optional): hex-aware local map text.
- production_targets(all optional): exact build target names.
```

The design goal is that the agent can understand the turn at a glance without
remembering Freeciv protocol field names.

## `units_detail`

Input:

```json
{
  "unit_id": 115
}
```

`unit_id` is optional. If omitted, all owned visible units are listed. If
provided, only that unit is shown.

Output sections:

- player and turn;
- focused unit id, if supplied;
- `Units With Moves`;
- `Other Units`;
- related tools.

Per-unit facts can include:

- unit type and id;
- tile id;
- moves left;
- hit points;
- current activity;
- build cost when known;
- attack/defense values when known;
- type move rate when known;
- type notes and type source when present.

Use this tool when `brief` identifies a unit with moves and the agent needs
more detail before acting.

## `cities_detail`

Input:

```json
{
  "city_id": 129
}
```

`city_id` is optional. If omitted, all owned visible cities are listed. If
provided, only that city is shown.

Output facts:

- city name and id;
- tile id;
- size;
- food stock;
- shield stock;
- current production name;
- exact production command target;
- current target build cost when known;
- related tools.

Use this tool when choosing production, checking city growth/progress, or
deciding where to inspect the local map.

## `economy_detail`

Input: none.

Output sections:

- economy rates and gold;
- current research;
- bulbs researched;
- bulbs per turn;
- known and available technology counts;
- ruleset directory;
- rules document path;
- key production target groups;
- full production target counts.

Use this tool when deciding research, economy rates, or high-level build
direction.

## Typical Turn Flow

Expected agent flow:

1. Call `brief`.
2. If active phase is `no`, do not act.
3. If there are no cities, call `found_city`.
4. Call `units_detail` if any units need attention.
5. Call `valid_moves` or `ascii_view` for units that need movement.
6. Call `cities_detail` and/or `economy_detail` before changing production,
   rates, or research.
7. Execute actions.
8. Call `phase_done` with private `intent`.

## Strengths

- Much more readable than `v0`.
- Separates core turn state from detail views.
- Makes units with moves highly salient.
- Gives exact production target guidance through `economy_detail` and
  `production_targets`.
- Keeps tool count moderate.

## Weaknesses

- Still has some raw JSON tools (`messages`, `local_view`).
- `brief` can still grow if a player owns many cities and units.
- The agent must choose which detail view to call.
- Research options are summarized by count, not listed in a dedicated readable
  tool. That is handled in `v2`.

## Best Use In Experiments

Good comparisons:

- MCP v0 vs MCP v1.
- MCP v1 vs MCP v2.
- CLI vs MCP v1.

`v1` is the reasonable default when the experiment is not specifically about
MCP design.
