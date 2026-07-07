# Freeciv MCP Tool Reference

This is the concrete reference for the MCP tools. It documents the data shape an
agent sees, including representative outputs. The examples are formatted the
same way the MCP server returns them: text tools return plain text, and JSON
tools return pretty-printed JSON text inside the MCP `content[0].text` field.

The outer MCP envelope always looks like this:

```json
{
  "content": [
    {
      "type": "text",
      "text": "<tool-specific text shown in the sections below>"
    }
  ],
  "isError": false
}
```

When artifact mode is enabled, the returned text is wrapped or appended with
file paths. See `docs/freeciv-mcp-artifacts.md`.

## Shared Data Objects

These objects appear in many tool results.

### Brief Unit

```json
{
  "id": 116,
  "owner": 0,
  "owner_info": {
    "id": 0,
    "name": "AgentC",
    "relation": "self"
  },
  "type": 52,
  "type_name": "Explorer",
  "type_rule_name": "Explorer",
  "type_info": {
    "id": 52,
    "known": true,
    "name": "Explorer",
    "rule_name": "Explorer",
    "build_cost": 30,
    "move_rate": 6
  },
  "tile": 823,
  "movesleft": 4,
  "hp": 10,
  "activity_tgt": -1
}
```

Important fields:

- `id`: stable unit id for commands.
- `type_rule_name`: human/ruleset name to reason about.
- `tile`: current tile id.
- `movesleft`: movement/action budget. Values above `0` should usually be
  considered before ending the phase.
- `activity_info`: decoded activity when known.
- `owner_info.relation`: usually `self`, `other`, or `unowned`.

### Brief City

```json
{
  "id": 129,
  "name": "Musehaven",
  "owner": 0,
  "owner_info": {
    "id": 0,
    "name": "AgentC",
    "relation": "self"
  },
  "tile": 668,
  "size": 1,
  "food_stock": 6,
  "shield_stock": 12,
  "production_kind": 6,
  "production_value": 5,
  "production": {
    "category": "unit",
    "kind": "UnitType",
    "kind_id": 6,
    "value_id": 5,
    "name": "Phalanx",
    "rule_name": "Phalanx",
    "command_target": "Phalanx",
    "target": {
      "id": 5,
      "known": true,
      "name": "Phalanx",
      "rule_name": "Phalanx",
      "build_cost": 20,
      "defense_strength": 2
    }
  }
}
```

Important fields:

- `id`: stable city id for production commands.
- `tile`: city tile id.
- `size`, `food_stock`, `shield_stock`: basic city development facts.
- `production.command_target`: exact string to use with production commands.
- `production_kind`: `6` means unit type, `3` means building/improvement.

### Local Tile

`local_view`, `valid_moves`, and action outputs can include local tile objects.

```json
{
  "tile": 668,
  "dx": 0,
  "dy": 0,
  "known": true,
  "terrain": 3,
  "terrain_name": "Desert",
  "terrain_rule_name": "Desert",
  "movement_cost": 2,
  "defense_bonus": 10,
  "terrain_info": {
    "id": 3,
    "known": true,
    "name": "Desert",
    "rule_name": "Desert",
    "movement_cost": 2,
    "defense_bonus": 10,
    "mining_time": 5,
    "irrigation_time": 5,
    "road_time": 3
  },
  "owner": 0,
  "owner_info": {
    "id": 0,
    "name": "AgentC",
    "relation": "self"
  },
  "extras_ids": [0],
  "extras_info": [
    {
      "id": 0,
      "known": true,
      "name": "Road",
      "rule_name": "Road",
      "buildable": true
    }
  ],
  "cities": [
    {
      "id": 129,
      "name": "Musehaven",
      "owner": 0,
      "tile": 668,
      "size": 1
    }
  ],
  "units": [
    {
      "id": 115,
      "type_rule_name": "Diplomat",
      "tile": 668,
      "movesleft": 12,
      "hp": 10
    }
  ]
}
```

Important fields:

- `dx` and `dy`: relative to the requested center tile.
- `known`: false means the player does not currently have tile facts.
- `terrain_rule_name`: terrain name to reason over.
- `extras_info`: improvements/resources/roads decoded from Freeciv extras.
- `units` and `cities`: visible entities on that tile.

### Player Status

`brief`, `economy_detail`, `state_snapshot`, and `player_packet_audit` can
include decoded `PACKET_PLAYER_INFO` status. The harness keeps raw ids for exact
debugging, but the normal reasoning surface is decoded.

Representative JSON shape:

```json
{
  "available": true,
  "source": "PACKET_PLAYER_INFO",
  "protocol": {
    "packet_id": 51,
    "packet_name": "PACKET_PLAYER_INFO"
  },
  "identity": {
    "player_no": 2,
    "name": "AgentD",
    "username": "AgentD",
    "nation_id": 177,
    "team_id": 2,
    "is_male": true,
    "was_created": true,
    "unassigned_user": false
  },
  "connection": {
    "is_connected": true,
    "is_ready": true,
    "phase_done": false
  },
  "lifecycle": {
    "turns_alive": 29,
    "is_alive": true,
    "idle_turns": 1,
    "revolution_finishes": -1
  },
  "politics": {
    "government_id": 2,
    "target_government_id": 9,
    "mood": {
      "id": 0,
      "name": "Peaceful"
    }
  },
  "economy_packet": {
    "gold": 63,
    "tax": 40,
    "science": 60,
    "luxury": 0,
    "score": 11,
    "culture": 129,
    "infrapoints": 3,
    "science_cost": 30,
    "tech_upkeep": 4,
    "tech_upkeep_source_field": "tech_upkeep_32",
    "history": 99
  },
  "visibility": {
    "real_embassy": {
      "meaning": "players for whom this player has a real embassy/contact visibility flag",
      "raw_bitvector": [10],
      "active_count": 2,
      "active_slots": [
        {
          "player_slot": 1,
          "relation": "other"
        },
        {
          "player_slot": 3,
          "relation": "other"
        }
      ]
    },
    "gives_shared_vision": {
      "active_count": 1,
      "active_slots": [
        {
          "player_slot": 2,
          "relation": "self"
        }
      ]
    },
    "gives_shared_tiles": {
      "active_count": 0,
      "active_slots": []
    }
  },
  "ai_profile": {
    "ai_skill_level": {
      "id": 3,
      "name": "Normal"
    },
    "barbarian_type": {
      "id": 0,
      "name": "None"
    }
  },
  "ai_attitudes": {
    "available": true,
    "meaning": "Freeciv AI attitude values by player slot, using love_text() thresholds; 0 and small values are Neutral",
    "range": {
      "min": -1000,
      "max": 1000
    },
    "entries": [
      {
        "player_slot": 1,
        "relation": "other",
        "value": -650,
        "attitude": "Hostile"
      },
      {
        "player_slot": 2,
        "relation": "self",
        "value": 1,
        "attitude": "Neutral"
      }
    ],
    "non_neutral_count": 1,
    "omitted_zero_neutral_slots": 510
  },
  "flags": {
    "raw_bitvector": [4],
    "active": [
      {
        "id": 2,
        "name": "first_city",
        "meaning": "player has had at least one city"
      }
    ],
    "known_flags": [
      {
        "id": 0,
        "name": "ai",
        "active": false,
        "meaning": "player is controlled by Freeciv's built-in AI"
      },
      {
        "id": 1,
        "name": "scenario_reserved",
        "active": false,
        "meaning": "player slot is reserved by the scenario/editor"
      },
      {
        "id": 2,
        "name": "first_city",
        "active": true,
        "meaning": "player has had at least one city"
      }
    ]
  },
  "wonders": {
    "available": true,
    "encoding": "flat_player_wonders_array",
    "meaning": "indexed by building/improvement id; value is city id, 0 means not built, -1 means lost",
    "built_or_lost_count": 1,
    "not_built_count": 72,
    "entries": [
      {
        "building_id": 37,
        "building_name": "Marco Polo's Embassy",
        "building_rule_name": "Marco Polo's Embassy",
        "city_id": 130,
        "status": "built",
        "meaning": "this player owns the wonder in the listed city",
        "city_name": "Capital"
      }
    ]
  },
  "multipliers": {
    "available": true,
    "meaning": "ruleset-defined player multipliers/policies; value is current, target is requested value, changed_turn is when it last changed",
    "count": 2,
    "ruleset_definitions_known": 2,
    "entries": [
      {
        "id": 0,
        "name": "Tax Policy",
        "rule_name": "TaxPolicy",
        "value": 100,
        "target": 100,
        "changed_turn": 0,
        "start": 0,
        "stop": 100,
        "step": 10,
        "def": 50,
        "offset": 0,
        "factor": 100,
        "minimum_turns": 0
      }
    ]
  },
  "style": {
    "style_id": 3,
    "music_style_id": 1,
    "autoselect_weight": 7,
    "color_valid": true,
    "color_changeable": false,
    "color_rgb": {
      "red": 12,
      "green": 34,
      "blue": 56,
      "css_hex": "#0c2238"
    }
  },
  "packet_delta": {
    "meaning": "protocol metadata: PACKET_PLAYER_INFO delta fields present in the most recent raw packet, not gameplay map fields",
    "raw_bitvector": [255, 0, 0, 0, 0, 0],
    "set_bits": [
      {
        "index": 0,
        "field": "name"
      },
      {
        "index": 1,
        "field": "username"
      }
    ]
  }
}
```

Important semantics:

- `packet_delta` decodes the Freeciv protocol bitvector named `fields`; it is
  not terrain fields or city-worked fields.
- `flags` decodes player flags such as `ai`, `scenario_reserved`, and
  `first_city`.
- `ai_attitudes` decodes the Freeciv `love` array using the same thresholds as
  Freeciv's `love_text()`.
- `wonders` decodes the player wonder array when Freeciv sends a flat list. If
  Freeciv sends a compact JSON-diff shape, the harness labels it
  `raw_json_diff_or_partial_array` and preserves the raw segments rather than
  pretending it is a full array.
- `visibility` decodes `real_embassy`, `gives_shared_vision`, and
  `gives_shared_tiles` player-slot bitvectors.
- `multipliers` decodes Freeciv ruleset multipliers/policies from
  `multip_count`, `multiplier`, `multiplier_target`, and
  `multiplier_changed`. Names are filled from `PACKET_RULESET_MULTIPLIER`
  when that ruleset packet has been observed.
- The short text line in `brief` is only a compact summary. The structured
  `player_status` object and `economy_detail`'s `Player Packet Status` section
  contain the complete decoded packet surface.

## State Tools

## `brief`

Versions:

- `v0`: compact legacy text.
- `v1` and `v2`: readable overview text.

Inputs:

```json
{}
```

Underlying control endpoint:

```text
GET /players/<player>/brief
```

Representative `v1`/`v2` result text:

```text
# AgentC Overview

Turn: 7 (-3700)
Active phase: yes
Phase mode: Players Alternate

## Current Status
- Economy: gold 56, tax 40%, science 60%, luxury 0%
- Player status: player_no 2, team 2, flags first_city, color #0c2238, style_id 3, non-neutral AI attitudes 1, wonders 1 built/lost
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

Representative `v0` result text:

```text
AgentC turn 7 year -3700 active_phase=True phase=Players Alternate
Ruleset: rulesetdir=civ2civ3 rules_doc=docs/freeciv-rules-for-agents.md
Key production targets: city_founding=Settlers; workers_and_population=Workers,Engineers,Migrants; early_military=Warriors,Phalanx,Archers,Horsemen
Economy: gold=56 tax=40 science=60 luxury=None
Research: Pottery cost=30 known_techs=1
Cities:
  129:Musehaven tile=668 size=1 food=6 shields=12 producing=Phalanx command_target=Phalanx
Units needing attention (movesleft > 0): 3
  115:Diplomat tile=668 movesleft=12 hp=10 activity=Fortified
  114:Workers tile=695 movesleft=6 hp=10 activity=Idle
  116:Explorer tile=823 movesleft=4 hp=10
Other units: 0
Inspect units with MCP tools: valid_moves(unit_id) or ascii_view(unit_id)
```

## `units_detail`

Versions: `v1`, `v2`.

Inputs:

```json
{
  "unit_id": 116
}
```

`unit_id` is optional. If omitted, all owned units are listed.

Representative result text:

```text
# AgentC Units

Turn: 7 (-3700)
Focused unit: 116

## Units With Moves (1)
- Explorer #116
  - Tile: 823
  - Moves left: 4
  - Hit points: 10
  - Activity: unknown
  - Unit build cost: 30
  - Type move rate: 6

## Other Units (0)
- None.

## Related Tools
- valid_moves(unit_id): movement facts for a specific unit.
- ascii_view(unit_id, radius optional): hex-aware local map around a unit.
- local_view(unit_id, radius optional): structured local map facts.
- move_unit(unit_id, direction/target_tile/dx/dy): execute movement.
- unit_activity(unit_id, activity): start work, fortify, or other activity.
```

## `cities_detail`

Versions: `v1`, `v2`.

Inputs:

```json
{
  "city_id": 129
}
```

`city_id` is optional. If omitted, all owned cities are listed.

Representative result text:

```text
# AgentC Cities

Turn: 7 (-3700)
Focused city: 129

## Cities (1)
- Musehaven #129
  - Tile: 668
  - Size: 1
  - Food stock: 6
  - Shield stock: 12
  - Producing: Phalanx
  - Production command target: Phalanx
  - Current target build cost: 20

## Related Tools
- production_targets(all optional): exact build target names.
- set_city_production(city_id, target, kind optional): change production.
- ascii_view(city_id, radius optional): hex-aware local map around a city.
- local_view(city_id, radius optional): structured local map facts.
```

## `economy_detail`

Versions: `v1`, `v2`.

Inputs:

```json
{}
```

Representative result text:

```text
# AgentC Economy And Rules

Turn: 7 (-3700)

## Economy
- gold 56, tax 40%, science 60%, luxury 0%
- Player status: player_no 2, team 2, flags first_city, color #0c2238, style_id 3, non-neutral AI attitudes 1, wonders 1 built/lost

## Player Packet Status
- Identity: player_no 2, nation_id 177, team_id 2, username AgentC
- Session: connected yes, ready yes, phase_done no, unassigned_user no
- Lifecycle: alive yes, turns_alive 29, idle_turns 1, revolution_finishes -1
- Politics: government_id 2, target_government_id 9, mood Peaceful (0)
- Packet economy: score 11, culture 129, infrapoints 3, science_cost 30, tech_upkeep 4, history 99
- AI/barbarian: skill Normal (3), barbarian_type None (0)
- Flags: first_city
- Real embassies: 2 active slots (1, 3)
- Gives shared vision: 1 active slots (2)
- Gives shared tiles: 0 active slots
- AI attitudes: 1 non-neutral entries
- Wonders: 1 built/lost, 72 not built
- Multipliers: 2 values, 2 ruleset definitions known
  - TaxPolicy: value 100, target 100, changed_turn 0

## Research
- Current: Pottery, cost 30, progress 12, goal Ceremonial Burial
- Bulbs researched: 12
- Total bulbs per turn: 2
- Known technologies: 1
- Available technologies: 7

## Ruleset
- rulesetdir: civ2civ3
- rules doc: docs/freeciv-rules-for-agents.md

## Key Production Targets
- city_founding: Settlers
- workers_and_population: Workers, Engineers, Migrants
- early_military: Warriors, Phalanx, Archers, Horsemen
- diplomacy_trade_exploration: Diplomat, Explorer, Caravan, Spy, Freight

## Full Production List
- Units: 57
- Buildings: 73
- Use production_targets(all=true) for exact decoded target names.
```

## `turn_dashboard`

Versions: `v2`.

Inputs:

```json
{}
```

Representative result text:

```text
# AgentD Turn Dashboard

Turn: 7 (-3700)
Active phase: yes
Phase: Players Alternate

## Open Unit Work
- Workers #114 at tile 695: moves 6, hp 10, activity Idle
- Explorer #116 at tile 823: moves 4, hp 10, activity unknown

## Cities And Production
- Musehaven #129 at tile 668: size 1, food stock 6, shield stock 12, producing Phalanx

## Economy And Research
- Economy: gold 56, tax 40%, science 60%, luxury 0%
- Research: Pottery, cost 30, progress 12, goal Ceremonial Burial

## Counts
- Units with moves: 2
- Other units: 1
- Cities: 1
```

## `units_ready`

Versions: `v2`.

Inputs:

```json
{}
```

Representative result text:

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

## `production_targets`

Versions: `v0`, `v1`, `v2`.

Inputs:

```json
{
  "all": false
}
```

Underlying endpoint:

```text
GET /players/<player>/production-targets
```

The MCP result is formatted text, but it is generated from JSON with this
underlying shape:

```json
{
  "usage": {
    "unit": "bin/game set-city-production <city_id> <target> --kind unit",
    "building": "bin/game set-city-production <city_id> <target> --kind building",
    "target_rule": "Use the exact target value from this list..."
  },
  "key_unit_targets": {
    "city_founding": [
      {
        "id": 0,
        "kind": "unit",
        "target": "Settlers",
        "name": "Settlers",
        "rule_name": "Settlers",
        "build_cost": 30,
        "pop_cost": 2,
        "roles": ["city founder", "worker", "costs population"],
        "can_found_city": true,
        "defense_strength": 1
      }
    ],
    "workers_and_population": [
      {
        "id": 2,
        "kind": "unit",
        "target": "Workers",
        "build_cost": 20,
        "pop_cost": 0,
        "roles": ["worker"]
      },
      {
        "id": 1,
        "kind": "unit",
        "target": "Migrants",
        "build_cost": 10,
        "pop_cost": 1,
        "roles": ["population transfer", "worker-style utility", "costs population"],
        "can_found_city": false,
        "note": "Migrants cannot found cities in civ2civ3.",
        "build_requirements": [
          {
            "kind": "Tech",
            "value": 63,
            "value_name": "Pottery",
            "known": false
          }
        ]
      }
    ]
  },
  "common_unit_targets": [
    {"id": 0, "kind": "unit", "target": "Settlers"},
    {"id": 2, "kind": "unit", "target": "Workers"}
  ],
  "counts": {
    "unit": 57,
    "building": 73
  },
  "unit_targets": ["only present in full non-summary response"],
  "building_targets": ["only present in full non-summary response"]
}
```

Representative MCP text:

```text
Production targets use exact ruleset names.
Use the exact target value from this list. For this ruleset, Settlers are city founders. Migrants are population/settler-class utility units but cannot found cities.
Unit command: bin/game set-city-production <city_id> <target> --kind unit
Building command: bin/game set-city-production <city_id> <target> --kind building
Key unit targets by role:
  city_founding:
    Settlers id=0 kind=unit cost=30 pop_cost=2 roles=city founder,worker,costs population can_found_city=true def=1
  workers_and_population:
    Workers id=2 kind=unit cost=20 roles=worker
    Migrants id=1 kind=unit cost=10 pop_cost=1 roles=population transfer,worker-style utility,costs population can_found_city=false note=Migrants cannot found cities in civ2civ3. requires=Tech:Pottery
Full list: 57 unit targets and 73 building targets. Run `bin/game production-targets --all` to print them.
```

## `city_production_options`

Versions: `v2`.

Inputs:

```json
{
  "city_id": 129,
  "all": false
}
```

This is a v2 convenience wrapper around `production_targets`. When `city_id` is
present, the underlying response includes city-specific advisory legality:

```json
{
  "city_id": 129,
  "city": {
    "id": 129,
    "name": "Musehaven",
    "size": 1,
    "production": {
      "command_target": "Phalanx"
    }
  },
  "city_specific_legality": "advisory; Freeciv server is authoritative. Known blockers are hidden server no-ops if sent.",
  "key_unit_targets": {
    "city_founding": [
      {
        "target": "Settlers",
        "legality": {
          "estimate": "known_blocked",
          "can_send": false,
          "known_blockers": [
            "requires city size at least 2"
          ],
          "warnings": []
        }
      }
    ]
  }
}
```

## `messages`

Versions: `v0`, `v1`, `v2`.

Inputs:

```json
{
  "limit": 10
}
```

Output JSON text:

```json
{
  "player": "AgentC",
  "messages": [
    {
      "turn": 7,
      "message": "Game: The Romans have finished building a new city.",
      "event": 16
    },
    {
      "turn": 7,
      "message": "Game: Waiting for AgentC to finish turn.",
      "event": 22
    }
  ]
}
```

Message field names depend on Freeciv packet fields available at decode time.
When in doubt, inspect the whole object, not only `message`.

## `recent_messages`

Versions: `v2`.

Inputs:

```json
{
  "limit": 10
}
```

Representative result text:

```text
# Recent Freeciv Messages

Requested limit: 10
Messages returned: 2

- turn 7: Game: The Romans have finished building a new city.
- turn 7: Game: Waiting for AgentC to finish turn.
```

## `local_view`

Versions: `v0`, `v1`, `v2`.

Inputs:

Exactly one of `unit_id`, `city_id`, or `tile_id` must be supplied.

```json
{
  "unit_id": 116,
  "radius": 1
}
```

Underlying endpoint:

```text
GET /players/<player>/local-view?unit_id=116&radius=1
```

Output JSON text:

```json
{
  "player": "AgentC",
  "turn": 7,
  "year": -3700,
  "center_tile": 823,
  "center_map": {
    "x": 17,
    "y": 31
  },
  "radius": 1,
  "map": {
    "xsize": 26,
    "ysize": 52,
    "topology_id": 3,
    "topology": {
      "id": 3,
      "name": "isometric hex",
      "is_isometric": true,
      "is_hex": true,
      "valid_directions": [
        {"id": 0, "name": "northwest", "dx": -1, "dy": -1},
        {"id": 1, "name": "north", "dx": 0, "dy": -1},
        {"id": 3, "name": "west", "dx": -1, "dy": 0},
        {"id": 4, "name": "east", "dx": 1, "dy": 0},
        {"id": 6, "name": "south", "dx": 0, "dy": 1},
        {"id": 7, "name": "southeast", "dx": 1, "dy": 1}
      ]
    }
  },
  "tiles": [
    {
      "tile": 796,
      "dx": -1,
      "dy": -1,
      "known": true,
      "terrain": 4,
      "terrain_name": "Forest",
      "terrain_rule_name": "Forest",
      "movement_cost": 2,
      "defense_bonus": 50,
      "extras_ids": [0],
      "extras_info": [
        {"id": 0, "name": "Road", "rule_name": "Road", "known": true}
      ]
    },
    {
      "tile": 823,
      "dx": 0,
      "dy": 0,
      "known": true,
      "terrain": 8,
      "terrain_name": "Plains",
      "terrain_rule_name": "Plains",
      "movement_cost": 1,
      "defense_bonus": 10,
      "units": [
        {
          "id": 116,
          "type_rule_name": "Explorer",
          "tile": 823,
          "movesleft": 4,
          "hp": 10
        }
      ]
    },
    {
      "tile": 850,
      "dx": 1,
      "dy": 1,
      "known": false
    }
  ]
}
```

Important details:

- `tiles` is not a square-grid guarantee. On an isometric hex map, use
  `map.topology.valid_directions` or `valid_moves` for actual adjacency.
- Unknown tiles still appear with `known: false` and may omit terrain fields.
- `units` and `cities` are only included when visible on that tile.

## `ascii_view`

Versions: `v0`, `v1`, `v2`.

Inputs:

```json
{
  "unit_id": 116,
  "radius": 2
}
```

The underlying control API returns JSON:

```json
{
  "player": "AgentC",
  "turn": 7,
  "year": -3700,
  "center_tile": 823,
  "center_map": {"x": 17, "y": 31},
  "radius": 2,
  "topology_id": 3,
  "topology": {
    "id": 3,
    "name": "isometric hex",
    "is_hex": true,
    "is_isometric": true
  },
  "format": "freeciv-agent-ascii-view-v2",
  "text": "freeciv-agent-ascii-view-v2\nplayer=AgentC turn=7 year=-3700 ..."
}
```

The MCP tool returns only the `text` field:

```text
freeciv-agent-ascii-view-v2
player=AgentC turn=7 year=-3700 center=unit:116 tile=823 map=(17,31) radius=2 topology=isometric hex topology_id=3
cell=terrain+marker; dx/dy are relative to center
terrain: ? unknown, ~=water, a=arctic, d=desert, f=forest, g=grassland, h=hills, j=jungle, m=mountains, p=plains, s=swamp, t=tundra
marker: .=none, uppercase=own unit, lowercase=other unit, @=own city, &=other city, *=multiple visible entities
layout=iso-hex; hex_distance=(abs(dx)+abs(dy)+abs(dx-dy))/2; omitted cells are outside hex radius
valid neighbor directions: 0 northwest(-1,-1), 1 north(+0,-1), 3 west(-1,+0), 4 east(+1,+0), 6 south(+0,+1), 7 southeast(+1,+1)

center-neighbors:
  northwest dx=-1 dy=-1 f. tile=796
  north     dx=+0 dy=-1 h. tile=797
  west      dx=-1 dy=+0 p. tile=822
  center    dx=+0 dy=+0 pE tile=823
  east      dx=+1 dy=+0 ??. tile=824
  south     dx=+0 dy=+1 g. tile=849
  southeast dx=+1 dy=+1 ?? tile=850

hex-grid:
dy=-2 dx=-2..+0 h.  f.  ??
dy=-1 dx=-2..+1   p.  f.  h.  ??
dy=+0 dx=-2..+2     g.  p.  pE  ??.  ??
dy=+1 dx=-1..+2       p.  g.  ??  ??
dy=+2 dx=+0..+2         ??.  ??  ??

details:
  dx=+0 dy=+0 tile=823 map=(17,31) terrain=Plains units=[Explorer#116 owner=self hp=10 moves=4]
```

## `valid_moves`

Versions: `v0`, `v1`, `v2`.

Inputs:

```json
{
  "unit_id": 116
}
```

Underlying endpoint:

```text
GET /players/<player>/valid-moves?unit_id=116
```

Underlying JSON shape:

```json
{
  "player": "AgentC",
  "turn": 7,
  "year": -3700,
  "authority": "harness estimate only; Freeciv is authoritative when move-unit is sent",
  "directions_are_filtered": false,
  "guidance": "These are topology-valid neighboring directions with local heuristic estimates...",
  "unit": {
    "id": 116,
    "type_rule_name": "Explorer",
    "tile": 823,
    "movesleft": 4,
    "hp": 10
  },
  "actionability": {
    "can_act_now": true,
    "reason": "unit has movement points and it is this player's phase"
  },
  "current_tile": 823,
  "current_map": {"x": 17, "y": 31},
  "topology_id": 3,
  "topology": {
    "id": 3,
    "name": "isometric hex",
    "is_hex": true,
    "is_isometric": true
  },
  "moves": [
    {
      "direction": 0,
      "direction_name": "northwest",
      "direction_info": {
        "id": 0,
        "name": "northwest",
        "dx": -1,
        "dy": -1,
        "valid": true
      },
      "dx": -1,
      "dy": -1,
      "target_tile": 796,
      "target_map": {"x": 16, "y": 30},
      "known": true,
      "can_enter_known": true,
      "enterability": {
        "can_enter": true,
        "reason": "known tile appears enterable by this unit"
      },
      "legality": {
        "estimate": "likely",
        "reason": "known terrain is enterable and no visible target blockers were found",
        "terrain_enterable": true,
        "known_blockers": [],
        "warnings": []
      },
      "known_blockers": [],
      "warnings": [],
      "tile": {
        "tile": 796,
        "dx": -1,
        "dy": -1,
        "known": true,
        "terrain_rule_name": "Forest",
        "movement_cost": 2
      }
    },
    {
      "direction": 4,
      "direction_name": "east",
      "target_tile": 824,
      "known": true,
      "can_enter_known": true,
      "legality": {
        "estimate": "blocked",
        "reason": "known visible blocker on target tile",
        "terrain_enterable": true,
        "known_blockers": [
          {
            "kind": "unit",
            "id": 201,
            "type": "Warriors",
            "owner": 1,
            "relation": "other",
            "reason": "non-action move orders cannot move through a visible foreign unit"
          }
        ],
        "warnings": []
      }
    }
  ]
}
```

The MCP returns a compact text rendering:

```text
AgentC turn 7: unit 116 (Explorer) at tile 823 map=(17,31) movesleft=4
Authority: advisory local estimates; `move-unit` sends topology-valid orders to Freeciv, which is final.
Can act now: True (unit has movement points and it is this player's phase)
Moves:
  0:northwest; target=796(16,30); known; Forest; move_cost=2; estimate=likely - known terrain is enterable and no visible target blockers were found
  4:east; target=824(18,31); known; Plains; blockers=unit:Warriors(other); estimate=blocked - known visible blocker on target tile
```

## `research_options`

Versions: `v2`.

Inputs:

```json
{}
```

Representative result text:

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
- Ceremonial Burial #10, state prerequisites known
- Currency #20, cost 20.0, state prerequisites known
- Horseback Riding #35, cost 10.0, state prerequisites known
- Masonry #46, cost 10.0, state prerequisites known
- Pottery #63, cost 10.0, state prerequisites known
- Warrior Code #86, cost 10.0, state prerequisites known

## Related Tools
- set_research(tech): set current research by exact name or id.
- set_tech_goal(tech): set longer-term technology goal by exact name or id.
```

## `map_topology`

Versions: `v2`.

Inputs:

```json
{}
```

Representative result text:

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

## `state_snapshot`

Versions: `v2`.

Inputs:

```json
{}
```

Underlying endpoint:

```text
GET /players/<player>
```

Output JSON text. This is intentionally large and should normally be used with
artifact mode. Top-level shape:

```json
{
  "name": "AgentD",
  "connected": true,
  "conn_id": 3,
  "player_no": 1,
  "turn": 7,
  "year": -3700,
  "display_player_name": "AgentD",
  "phase": {
    "id": 1,
    "mode_id": 1,
    "mode_name": "Players Alternate",
    "mode_rule_name": "PLAYER",
    "active_player_no": 1,
    "active_scope": "single player",
    "agent_is_active_phase": true,
    "meaning": "one player acts at a time; the current phase number is the active player number"
  },
  "ruleset": {
    "rulesetdir": "civ2civ3",
    "path": "/Users/richardwilliams/Game AI Science/freeciv-s3_2-agent/data/civ2civ3",
    "game_ruleset": "/Users/richardwilliams/Game AI Science/freeciv-s3_2-agent/data/civ2civ3/game.ruleset"
  },
  "map_info": {
    "xsize": 26,
    "ysize": 52,
    "topology_id": 3,
    "wrap_id": 3
  },
  "map": {
    "xsize": 26,
    "ysize": 52,
    "topology_id": 3,
    "topology": {
      "id": 3,
      "name": "isometric hex",
      "is_hex": true,
      "is_isometric": true,
      "valid_directions": [
        {"id": 0, "name": "northwest", "dx": -1, "dy": -1}
      ]
    }
  },
  "units": [
    {
      "id": 116,
      "type_rule_name": "Explorer",
      "tile": 823,
      "movesleft": 4,
      "hp": 10
    }
  ],
  "cities": [
    {
      "id": 129,
      "name": "Musehaven",
      "tile": 668,
      "size": 1,
      "production": {
        "command_target": "Phalanx"
      }
    }
  ],
  "unit_types": {
    "0": {
      "id": 0,
      "name": "Settlers",
      "rule_name": "Settlers",
      "build_cost": 30,
      "pop_cost": 2
    }
  },
  "buildings": {
    "0": {
      "id": 0,
      "name": "Airport",
      "rule_name": "Airport",
      "build_cost": 120
    }
  },
  "extras": {
    "0": {
      "id": 0,
      "name": "Road",
      "rule_name": "Road",
      "buildable": true
    }
  },
  "terrains": {
    "8": {
      "id": 8,
      "name": "Plains",
      "rule_name": "Plains",
      "movement_cost": 1,
      "defense_bonus": 10
    }
  },
  "techs": {
    "63": {
      "id": 63,
      "name": "Pottery",
      "rule_name": "Pottery"
    }
  },
  "research": {
    "researching": 63,
    "researching_info": {
      "id": 63,
      "name": "Pottery",
      "rule_name": "Pottery"
    },
    "researching_cost": 30,
    "bulbs_researched": 12,
    "total_bulbs_prod": 2,
    "known": [],
    "available": []
  },
  "recent_messages": [],
  "packet_counts": {
    "77": 22,
    "140": 57,
    "151": 12
  },
  "last_error": null
}
```

## Action Tools

The action tools all return JSON text. The fields to read first are:

- `ok`: whether the harness considers the command successful enough at the API
  level.
- `sent` or `packet_sent`: whether a Freeciv packet was sent.
- `applied`: whether the intended change was observed.
- `result` or `result.estimate`: semantic result classification.
- `before` and `after`: observed state around the command.
- `recent_messages`: relevant server messages near the command, when included.

## `move_unit`

Inputs:

```json
{
  "unit_id": 116,
  "direction": 4,
  "wait": 5.0
}
```

Alternative targeting:

```json
{"unit_id": 116, "target_tile": 824}
```

```json
{"unit_id": 116, "dx": 1, "dy": 0}
```

Representative output:

```json
{
  "ok": true,
  "player": "AgentC",
  "unit_id": 116,
  "from_tile": 823,
  "target_tile": 824,
  "packet": "PACKET_UNIT_ORDERS",
  "sent": true,
  "direction": 4,
  "direction_info": {
    "id": 4,
    "name": "east",
    "dx": 1,
    "dy": 0,
    "valid": true
  },
  "before": {
    "id": 116,
    "type_rule_name": "Explorer",
    "tile": 823,
    "movesleft": 4,
    "hp": 10
  },
  "after": {
    "id": 116,
    "type_rule_name": "Explorer",
    "tile": 824,
    "movesleft": 3,
    "hp": 10
  },
  "applied": true,
  "reached_target": true,
  "observed_changed": true,
  "result": "confirmed_move",
  "result_explanation": "unit was observed on the requested target tile",
  "actionability": {
    "can_act_now": true,
    "reason": "unit has movement points and it is this player's phase"
  },
  "legality": {
    "estimate": "likely",
    "reason": "known terrain is enterable and no visible target blockers were found",
    "terrain_enterable": true,
    "known_blockers": [],
    "warnings": []
  },
  "precheck_authority": "advisory only; command was still sent to Freeciv",
  "wait_seconds": 5.0,
  "recent_messages": []
}
```

Known-invalid movement can return `sent: false` but `ok: true` because the tool
handled the request without sending a doomed Freeciv packet:

```json
{
  "ok": true,
  "sent": false,
  "applied": false,
  "result": "not_sent_known_invalid",
  "result_explanation": "known visible blocker on target tile",
  "legality": {
    "estimate": "blocked",
    "known_blockers": [
      {"kind": "unit", "id": 201, "type": "Warriors", "relation": "other"}
    ]
  }
}
```

## `unit_activity`

Inputs:

```json
{
  "unit_id": 114,
  "activity": "road",
  "target": "Road",
  "wait": 5.0
}
```

Representative output:

```json
{
  "ok": true,
  "player": "AgentC",
  "unit_id": 114,
  "packet": "PACKET_UNIT_CHANGE_ACTIVITY",
  "sent": true,
  "activity": 13,
  "activity_info": {
    "id": 13,
    "name": "Road",
    "target": {
      "id": 0,
      "name": "Road",
      "rule_name": "Road"
    }
  },
  "target": 0,
  "target_info": {
    "id": 0,
    "name": "Road",
    "rule_name": "Road",
    "buildable": true
  },
  "before": {
    "id": 114,
    "type_rule_name": "Workers",
    "tile": 695,
    "movesleft": 6,
    "activity_info": {"id": 0, "name": "Idle"}
  },
  "after": {
    "id": 114,
    "type_rule_name": "Workers",
    "tile": 695,
    "movesleft": 6,
    "activity_info": {"id": 13, "name": "Road"}
  },
  "applied": true,
  "observed_changed": true,
  "result": {
    "estimate": "confirmed_activity",
    "reason": "requested activity and target were observed on the unit"
  },
  "retry_policy": {
    "repeat_same_order_this_turn": false,
    "next_step": "do not repeat; inspect another unit or end phase"
  },
  "legality": {
    "authority": "advisory only; Freeciv is authoritative after the command is sent",
    "estimate": "no_known_problem",
    "known_blockers": [],
    "warnings": []
  },
  "tile": {
    "tile": 695,
    "known": true,
    "terrain_rule_name": "Plains"
  },
  "recent_messages": []
}
```

Important `result.estimate` values:

- `already_active`: no packet sent; do not repeat same order.
- `not_sent_known_invalid`: no packet sent because precheck found a blocker.
- `confirmed_activity`: requested activity observed.
- `sent_pending`: packet sent but no matching update observed before timeout.

## `found_city`

Inputs:

```json
{
  "city_name": "Alpha",
  "wait": 5.0
}
```

Optional explicit unit:

```json
{
  "unit_id": 101,
  "city_name": "Alpha"
}
```

Omit `unit_id` for normal opening turns. The tool asks Freeciv which owned unit
can legally perform `Found City` on its current tile and uses that unit. If an
agent supplies `unit_id`, the tool treats that as an explicit command to try
only that unit. If the requested unit cannot found a city, no packet is sent and
the response lists known legal founding units when any are found.

Representative success:

```json
{
  "ok": true,
  "player": "AgentA",
  "packet": "PACKET_UNIT_DO_ACTION",
  "sent": true,
  "unit_id": 101,
  "target_tile": 512,
  "city_name": "Alpha",
  "action": {
    "id": 27,
    "name": "Found City"
  },
  "sub_target": 0,
  "action_probability": {
    "action_id": 27,
    "action_name": "Found City",
    "min": 200,
    "max": 200,
    "possible": true
  },
  "before": {
    "id": 101,
    "type_rule_name": "Settlers",
    "tile": 512
  },
  "after": null,
  "founded_city": {
    "id": 130,
    "name": "Alpha",
    "tile": 512,
    "size": 1
  },
  "applied": true,
  "observed_changed": true,
  "result": {
    "estimate": "confirmed_city_founded",
    "reason": "a new owned city was observed on the target tile"
  },
  "wait_seconds": 5.0
}
```

Representative rejection for a bad explicit unit:

```json
{
  "ok": false,
  "player": "AgentD",
  "packet": "PACKET_UNIT_DO_ACTION",
  "sent": false,
  "requested_unit_id": 111,
  "unit_id": 111,
  "target_tile": 669,
  "city_name": "AgentD1",
  "action": {
    "id": 27,
    "name": "Found City"
  },
  "action_checks": [
    {
      "unit_id": 111,
      "target_tile": 669,
      "unit": {
        "id": 111,
        "type_rule_name": "Diplomat",
        "tile": 669
      },
      "action_probability": {
        "action_id": 27,
        "action_name": "Found City",
        "min": 0,
        "max": 0,
        "possible": false
      }
    }
  ],
  "legal_found_city_units": [
    {
      "id": 108,
      "type_rule_name": "Settlers",
      "tile": 642
    }
  ],
  "rejected_requested_unit": {
    "unit_id": 111,
    "target_tile": 669,
    "unit": {
      "id": 111,
      "type_rule_name": "Diplomat",
      "tile": 669
    },
    "reason": "requested unit cannot found a city on its current tile"
  },
  "result": {
    "estimate": "not_sent_requested_unit_cannot_found_city",
    "reason": "The command named a specific unit_id, but Freeciv reports Found City is not legal for that unit on its current tile. No action was sent. Omit unit_id if you want the harness to choose a legal founder."
  },
  "applied": false,
  "observed_changed": false
}
```

Representative auto-selection when `unit_id` is omitted:

```json
{
  "ok": true,
  "player": "AgentD",
  "packet": "PACKET_UNIT_DO_ACTION",
  "sent": true,
  "requested_unit_id": null,
  "unit_id": 108,
  "target_tile": 642,
  "city_name": "AgentD1",
  "action": {
    "id": 27,
    "name": "Found City"
  },
  "action_checks": [
    {
      "unit_id": 108,
      "target_tile": 642,
      "unit": {
        "id": 108,
        "type_rule_name": "Settlers",
        "tile": 642
      },
      "action_probability": {
        "action_id": 27,
        "action_name": "Found City",
        "min": 200,
        "max": 200,
        "possible": true
      }
    }
  ],
  "founded_city": {
    "id": 130,
    "name": "AgentD1",
    "tile": 642,
    "size": 1
  },
  "applied": true,
  "observed_changed": true
}
```

Representative no-legal-founder result:

```json
{
  "ok": false,
  "player": "AgentA",
  "city_name": "Alpha",
  "packet": "PACKET_UNIT_DO_ACTION",
  "sent": false,
  "action": {
    "id": 27,
    "name": "Found City"
  },
  "action_checks": [
    {
      "unit_id": 102,
      "target_tile": 540,
      "action_probability": {
        "action_id": 27,
        "action_name": "Found City",
        "min": 0,
        "max": 0,
        "possible": false
      },
      "possible_actions": []
    }
  ],
  "applied": false,
  "observed_changed": false,
  "result": {
    "estimate": "not_sent_no_legal_found_city_unit",
    "reason": "No owned unit currently reports Found City as legal on its tile..."
  }
}
```

## `set_city_production`

Inputs:

```json
{
  "city_id": 129,
  "target": "Warriors",
  "kind": "unit",
  "wait": 1.0
}
```

Representative success:

```json
{
  "ok": true,
  "player": "AgentC",
  "city_id": 129,
  "packet": "PACKET_CITY_CHANGE",
  "packet_sent": true,
  "production_kind": 6,
  "production_kind_name": "UnitType",
  "production_value": 4,
  "production": {
    "kind_id": 6,
    "kind": "UnitType",
    "value_id": 4,
    "category": "unit",
    "name": "Warriors",
    "rule_name": "Warriors",
    "command_target": "Warriors"
  },
  "before": {
    "id": 129,
    "name": "Musehaven",
    "production": {
      "command_target": "Phalanx"
    }
  },
  "after": {
    "id": 129,
    "name": "Musehaven",
    "production": {
      "command_target": "Warriors"
    }
  },
  "applied": true,
  "observed_changed": true,
  "result": {
    "estimate": "confirmed_applied",
    "reason": "Freeciv sent a city update with the requested production target"
  },
  "legality": {
    "estimate": "legal",
    "can_send": true,
    "known_blockers": [],
    "warnings": []
  },
  "recent_messages": []
}
```

Representative blocked result:

```json
{
  "ok": false,
  "packet_sent": false,
  "applied": false,
  "result": {
    "estimate": "not_sent_known_invalid",
    "reason": "requires Pottery tech, which is available to research but not known"
  },
  "legality": {
    "estimate": "known_blocked",
    "can_send": false,
    "known_blockers": [
      "requires Pottery tech, which is available to research but not known"
    ],
    "warnings": []
  }
}
```

## `set_rates`

Inputs:

```json
{
  "tax": 40,
  "luxury": 0,
  "science": 60,
  "wait": 1.0
}
```

Output:

```json
{
  "ok": true,
  "player": "AgentC",
  "packet": "PACKET_PLAYER_RATES",
  "requested": {
    "tax": 40,
    "luxury": 0,
    "science": 60
  },
  "before": {
    "gold": 56,
    "tax": 50,
    "luxury": 0,
    "science": 50
  },
  "after": {
    "gold": 56,
    "tax": 40,
    "luxury": 0,
    "science": 60
  },
  "applied": true
}
```

## `set_research`

Inputs:

```json
{
  "tech": "Pottery",
  "wait": 1.0
}
```

Output:

```json
{
  "ok": true,
  "player": "AgentC",
  "packet": "PACKET_PLAYER_RESEARCH",
  "tech": {
    "id": 63,
    "name": "Pottery",
    "rule_name": "Pottery",
    "known": true,
    "state": "prerequisites known"
  },
  "before": {
    "researching": 10,
    "researching_info": {
      "id": 10,
      "name": "Ceremonial Burial"
    }
  },
  "after": {
    "researching": 63,
    "researching_info": {
      "id": 63,
      "name": "Pottery",
      "rule_name": "Pottery"
    },
    "researching_cost": 30
  },
  "applied": true
}
```

## `set_tech_goal`

Inputs:

```json
{
  "tech": "Ceremonial Burial",
  "wait": 1.0
}
```

Output is the same shape as `set_research`, except:

```json
{
  "packet": "PACKET_PLAYER_TECH_GOAL",
  "applied": true,
  "after": {
    "tech_goal": 10,
    "tech_goal_info": {
      "id": 10,
      "name": "Ceremonial Burial",
      "rule_name": "Ceremonial Burial"
    }
  }
}
```

## `say`

Inputs:

```json
{
  "message": "AgentD proposes peace while it builds infrastructure."
}
```

Output:

```json
{
  "ok": true,
  "player": "AgentD",
  "message": "AgentD proposes peace while it builds infrastructure."
}
```

The chat message is public in-game communication.

## `narrative_read`

Inputs:

```json
{
  "limit_chars": 6000
}
```

Output when no log exists:

```text
# Narrative Log

Player: AgentC
Path: /Users/richardwilliams/Game AI Science/freeciv-agent-harness/players/AgentC/narrative.md
Status: no narrative.md exists yet.
```

Output when a log exists:

```text
# Narrative Log

Player: AgentC
Path: /Users/richardwilliams/Game AI Science/freeciv-agent-harness/players/AgentC/narrative.md
Characters returned: 119

## Content
## Turn 1 (-4000)
- Founded Berlin and started Warriors.
- Explorer moved north to reveal hills.
- Next: scout for enemy contact and build pressure.
```

`limit_chars` returns the end of the narrative log, not the beginning, so later
turns remain visible when the file grows.

## `narrative_append`

Inputs:

```json
{
  "turn": 1,
  "year": "-4000",
  "entry": "- Founded Berlin and started Warriors.\n- Explorer moved north to reveal hills.\n- Next: scout for enemy contact and build pressure."
}
```

Output:

```json
{
  "ok": true,
  "player": "AgentC",
  "path": "/Users/richardwilliams/Game AI Science/freeciv-agent-harness/players/AgentC/narrative.md",
  "appended_chars": 142,
  "entry_count_hint": 1
}
```

The written file becomes:

```markdown
## Turn 1 (-4000)
- Founded Berlin and started Warriors.
- Explorer moved north to reveal hills.
- Next: scout for enemy contact and build pressure.
```

This is the canonical MCP mechanism for the narrative-log experiment. MCP
agents should use this tool instead of shell commands or direct file edits.

## `private_intent`

Inputs:

```json
{
  "intent": "Scout east with Explorer; keep city on Phalanx for defense.",
  "turn": 7
}
```

Output:

```json
{
  "ok": true,
  "player": "AgentC",
  "turn": 7,
  "private_intent": {
    "ok": true,
    "path": "/Users/richardwilliams/Game AI Science/freeciv-agent-harness/runtime/audit/private-intents.jsonl"
  }
}
```

This does not end the turn.

## `phase_done`

Inputs:

```json
{
  "intent": "Moved Explorer east, started road with Workers, kept production on Phalanx.",
  "turn": 7
}
```

Output:

```json
{
  "ok": true,
  "player": "AgentC",
  "turn": 7,
  "private_intent": {
    "ok": true,
    "path": "/Users/richardwilliams/Game AI Science/freeciv-agent-harness/runtime/audit/private-intents.jsonl"
  }
}
```

This should be the final action in a normal turn.

## Artifact Mode Result Wrapper

When `--artifact-mode mirror` is active, the tool returns its normal full text
plus:

```text
## MCP Artifact
- Full result file: /Users/richardwilliams/Game AI Science/freeciv-agent-harness/players/AgentD/mcp-artifacts/20260705T171212.123456Z-0003-state_snapshot.txt
- Metadata file: /Users/richardwilliams/Game AI Science/freeciv-agent-harness/players/AgentD/mcp-artifacts/20260705T171212.123456Z-0003-state_snapshot.metadata.json
- Bytes: 48122
```

When `--artifact-mode file-only` is active, the tool returns:

```text
# MCP Result Written To File

Tool: state_snapshot
Full result file: /Users/richardwilliams/Game AI Science/freeciv-agent-harness/players/AgentD/mcp-artifacts/20260705T171212.123456Z-0003-state_snapshot.txt
Metadata file: /Users/richardwilliams/Game AI Science/freeciv-agent-harness/players/AgentD/mcp-artifacts/20260705T171212.123456Z-0003-state_snapshot.metadata.json
Bytes: 48122

## Preview
{
  "buildings": {
    "0": {
      "build_cost": 120,

Preview omitted 47322 additional characters.
```
