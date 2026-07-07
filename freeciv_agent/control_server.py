from __future__ import annotations

import argparse
import json
import re
import socket
import threading
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .json_client import FreecivJsonClient


ROOT = Path(__file__).resolve().parents[1]
COMMAND_AUDIT_PATH = ROOT / "runtime" / "audit" / "commands.jsonl"
PRIVATE_INTENT_PATH = ROOT / "runtime" / "audit" / "private-intents.jsonl"
DEFAULT_RULESETDIR = "civ2civ3"


FREECIV_COLOR_TAG_RE = re.compile(r"\[/?c(?:\s+[^\]]*)?\]")
LOGIN_MESSAGE_RE = re.compile(
    r"You are logged in as '(?P<username>[^']+)' connected to (?P<player>[^.]+)\."
)
WAITING_ON_PLAYER_RE = re.compile(
    r"Turn-blocking game play: waiting on (?P<player>.+?) to finish turn"
)

REQ_KIND_NAMES = {
    1: "Tech",
    2: "Government",
    3: "Building",
    4: "Terrain",
    5: "Nation",
    6: "UnitType",
    12: "MinSize",
}

REQ_RANGE_NAMES = {
    0: "Local",
    1: "Tile",
    2: "Adjacent",
    3: "CAdjacent",
    4: "City",
    5: "TradeRoute",
    6: "Continent",
    7: "Player",
    8: "Team",
    9: "Alliance",
    10: "World",
}


def plain_server_message(message: Any) -> str:
    return FREECIV_COLOR_TAG_RE.sub("", str(message or "")).strip()


def display_label(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if ":" in text and text.startswith("?"):
        return text.split(":", 1)[1]
    return urllib.parse.unquote(text) if "%" in text else text


def ascii_city_name_token(value: str) -> str:
    ascii_text = value.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]", "", ascii_text)


ACTIVITY_IDS = {
    "idle": 0,
    "cultivate": 1,
    "mine": 2,
    "irrigate": 3,
    "fortified": 4,
    "sentry": 5,
    "pillage": 6,
    "goto": 7,
    "explore": 8,
    "transform": 9,
    "fortify": 10,
    "fortifying": 10,
    "clean": 11,
    "base": 12,
    "road": 13,
    "gen-road": 13,
    "gen_road": 13,
    "convert": 14,
    "plant": 15,
}

ACTIVITY_NAMES = {
    0: "Idle",
    1: "Cultivate",
    2: "Mine",
    3: "Irrigate",
    4: "Fortified",
    5: "Sentry",
    6: "Pillage",
    7: "Goto",
    8: "Explore",
    9: "Transform",
    10: "Fortifying",
    11: "Clean",
    12: "Base",
    13: "Road",
    14: "Convert",
    15: "Plant",
}

ACTION_NAMES = {
    27: "Found City",
    28: "Join City",
    39: "Disband Unit",
    45: "Attack",
    61: "Fortify",
    62: "Cultivate",
    63: "Plant",
    64: "Transform Terrain",
    65: "Build Road",
    66: "Build Irrigation",
    67: "Build Mine",
    68: "Build Base",
    69: "Pillage",
}

ACTION_IDS = {name.lower().replace(" ", "-"): action_id for action_id, name in ACTION_NAMES.items()}
ACTION_IDS.update({name.lower().replace(" ", "_"): action_id for action_id, name in ACTION_NAMES.items()})

DEFAULT_ACTIVITY_TARGETS = {
    2: "Mine",
    3: "Irrigation",
    13: "Road",
}

ACTIVITIES_REQUIRING_TARGET = {
    2,
    3,
    6,
    11,
    12,
    13,
}

WORKER_IMPROVEMENT_ACTIVITIES = {
    1,
    2,
    3,
    9,
    12,
    13,
    15,
}

ACTIVITY_TERRAIN_TIME_FIELDS = {
    1: "cultivate_time",
    2: "mining_time",
    3: "irrigation_time",
    9: "transform_time",
    13: "road_time",
}

DIRECTION_NAMES = {
    0: "northwest",
    1: "north",
    2: "northeast",
    3: "west",
    4: "east",
    5: "southwest",
    6: "south",
    7: "southeast",
}

DIRECTION_DELTAS = {
    0: (-1, -1),
    1: (0, -1),
    2: (1, -1),
    3: (-1, 0),
    4: (1, 0),
    5: (-1, 1),
    6: (0, 1),
    7: (1, 1),
}

PHASE_MODE_NAMES = {
    0: "Concurrent",
    1: "Players Alternate",
    2: "Teams Alternate",
}

PHASE_MODE_RULE_NAMES = {
    0: "ALL",
    1: "PLAYER",
    2: "TEAM",
}

PHASE_MODE_MEANINGS = {
    0: "all players may act during the same turn phase",
    1: "one player acts at a time; the current phase number is the active player number",
    2: "one team acts at a time; the current phase number is the active team number",
}

PLAYER_INFO_DELTA_FIELD_NAMES = [
    "name",
    "username",
    "unassigned_user",
    "score",
    "is_male",
    "was_created",
    "government",
    "target_government",
    "real_embassy",
    "mood",
    "style",
    "music_style",
    "nation",
    "team",
    "is_ready",
    "phase_done",
    "nturns_idle",
    "turns_alive",
    "is_alive",
    "autoselect_weight",
    "gold",
    "tax",
    "science",
    "luxury",
    "infrapoints",
    "tech_upkeep",
    "science_cost",
    "is_connected",
    "revolution_finishes",
    "ai_skill_level",
    "barbarian_type",
    "gives_shared_vision",
    "gives_shared_tiles",
    "history",
    "culture",
    "love",
    "color_valid",
    "color_changeable",
    "color_red",
    "color_green",
    "color_blue",
    "flags",
    "wonders",
    "multip_count",
    "multiplier",
    "multiplier_target",
    "multiplier_changed",
]

PLAYER_STATUS_PACKET_FIELDS = {
    "playerno",
    "fields",
    "tech_upkeep_16",
    "tech_upkeep_32",
    *PLAYER_INFO_DELTA_FIELD_NAMES,
}

PLAYER_FLAG_NAMES = {
    0: "ai",
    1: "scenario_reserved",
    2: "first_city",
}

PLAYER_FLAG_MEANINGS = {
    "ai": "player is controlled by Freeciv's built-in AI",
    "scenario_reserved": "player slot is reserved by the scenario/editor",
    "first_city": "player has had at least one city",
}

AI_LEVEL_NAMES = {
    0: "Restricted",
    1: "Novice",
    2: "Easy",
    3: "Normal",
    4: "Hard",
    5: "Cheating",
    6: "Away or Experimental",
    7: "Away",
}

BARBARIAN_TYPE_NAMES = {
    0: "None",
    1: "Land",
    2: "Sea",
    3: "Animal",
    4: "LandAndSea",
}

MOOD_NAMES = {
    0: "Peaceful",
    1: "Combat",
}

MAX_AI_LOVE = 1000
WONDER_LOST = -1
WONDER_NOT_BUILT = 0


def bitvector_ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    ids: list[int] = []
    for byte_index, item in enumerate(value):
        if not isinstance(item, int):
            continue
        for bit_index in range(8):
            if item & (1 << bit_index):
                ids.append(byte_index * 8 + bit_index)
    return ids


def love_attitude(value: int) -> str:
    if value <= -MAX_AI_LOVE * 90 // 100:
        return "Genocidal"
    if value <= -MAX_AI_LOVE * 70 // 100:
        return "Belligerent"
    if value <= -MAX_AI_LOVE * 50 // 100:
        return "Hostile"
    if value <= -MAX_AI_LOVE * 25 // 100:
        return "Uncooperative"
    if value <= -MAX_AI_LOVE * 10 // 100:
        return "Uneasy"
    if value <= MAX_AI_LOVE * 10 // 100:
        return "Neutral"
    if value <= MAX_AI_LOVE * 25 // 100:
        return "Respectful"
    if value <= MAX_AI_LOVE * 50 // 100:
        return "Helpful"
    if value <= MAX_AI_LOVE * 70 // 100:
        return "Enthusiastic"
    if value <= MAX_AI_LOVE * 90 // 100:
        return "Admiring"
    return "Worshipful"

UNIVERSAL_KIND_NAMES = {
    0: "None",
    1: "Tech",
    2: "Government",
    3: "Building",
    4: "Terrain",
    5: "Nation",
    6: "UnitType",
    7: "UnitFlag",
    8: "UnitClass",
    9: "UnitClassFlag",
    10: "OutputType",
    11: "Specialist",
    12: "MinSize",
    13: "AI",
    14: "TerrainClass",
    15: "MinYear",
    16: "TerrainAlter",
}

WATER_TERRAINS = {"Lake", "Ocean", "Deep Ocean"}

TERRAIN_ASCII = {
    "Arctic": "a",
    "Desert": "d",
    "Forest": "f",
    "Grassland": "g",
    "Hills": "h",
    "Jungle": "j",
    "Lake": "~",
    "Mountains": "m",
    "Ocean": "~",
    "Deep Ocean": "~",
    "Plains": "p",
    "Swamp": "s",
    "Tundra": "t",
}

TECH_STATE_NAMES = {
    "0": "unknown",
    "1": "prerequisites known",
    "2": "known",
    0: "unknown",
    1: "prerequisites known",
    2: "known",
}

MAX_NUM_ADVANCES = 400
A_LAST = MAX_NUM_ADVANCES + 1
A_FUTURE = A_LAST + 1
A_UNSET = A_LAST + 2
A_UNKNOWN = A_LAST + 3


def valid_direction_ids(topology_id: int | None) -> list[int]:
    topology_id = topology_id or 0
    is_iso = bool(topology_id & 1)
    is_hex = bool(topology_id & 2)
    if is_iso and is_hex:
        return [0, 1, 3, 4, 6, 7]
    if is_hex:
        return [1, 2, 3, 4, 5, 6]
    return list(range(8))


def direction_info(direction: int, topology_id: int | None = None) -> dict[str, Any]:
    dx, dy = DIRECTION_DELTAS[direction]
    result: dict[str, Any] = {
        "id": direction,
        "name": DIRECTION_NAMES[direction],
        "dx": dx,
        "dy": dy,
    }
    if topology_id is not None:
        result["valid_for_topology"] = direction in valid_direction_ids(topology_id)
    return result


def topology_info(map_info: dict[str, int]) -> dict[str, Any]:
    topology_id = map_info.get("topology_id")
    wrap_id = map_info.get("wrap_id", 0)
    is_isometric = bool((topology_id or 0) & 1)
    is_hex = bool((topology_id or 0) & 2)
    if is_isometric and is_hex:
        topology_name = "isometric hex"
    elif is_hex:
        topology_name = "hex"
    elif is_isometric:
        topology_name = "isometric square"
    else:
        topology_name = "square"
    wrap_x = bool(wrap_id & 1)
    wrap_y = bool(wrap_id & 2)
    if wrap_x and wrap_y:
        wrap_name = "wraps east-west and north-south"
    elif wrap_x:
        wrap_name = "wraps east-west"
    elif wrap_y:
        wrap_name = "wraps north-south"
    else:
        wrap_name = "does not wrap"
    valid = valid_direction_ids(topology_id)
    return {
        "id": topology_id,
        "name": topology_name,
        "is_isometric": is_isometric,
        "is_hex": is_hex,
        "wrap": {
            "id": wrap_id,
            "name": wrap_name,
            "wrap_x": wrap_x,
            "wrap_y": wrap_y,
        },
        "valid_directions": [
            direction_info(direction)
            for direction in valid
        ],
        "invalid_directions": [
            direction_info(direction)
            for direction in DIRECTION_NAMES
            if direction not in valid
        ],
        "xsize": map_info.get("xsize"),
        "ysize": map_info.get("ysize"),
        "north_latitude": map_info.get("north_latitude"),
        "south_latitude": map_info.get("south_latitude"),
    }


def format_valid_directions(topology_id: int | None) -> str:
    return ", ".join(
        f"{direction}:{DIRECTION_NAMES[direction]}"
        for direction in valid_direction_ids(topology_id)
    )


@dataclass
class PlayerState:
    name: str
    ruleset: dict[str, Any] = field(default_factory=dict)
    connected: bool = False
    conn_id: int | None = None
    player_no: int | None = None
    turn: int | None = None
    year: int | None = None
    phase: int | None = None
    phase_mode: int | None = None
    display_player_name: str | None = None
    inferred_active_player_name: str | None = None
    map_info: dict[str, int] = field(default_factory=dict)
    tiles: dict[int, dict[str, Any]] = field(default_factory=dict)
    units: dict[int, dict[str, Any]] = field(default_factory=dict)
    cities: dict[int, dict[str, Any]] = field(default_factory=dict)
    unit_types: dict[int, dict[str, Any]] = field(default_factory=dict)
    buildings: dict[int, dict[str, Any]] = field(default_factory=dict)
    extras: dict[int, dict[str, Any]] = field(default_factory=dict)
    terrains: dict[int, dict[str, Any]] = field(default_factory=dict)
    techs: dict[int, dict[str, Any]] = field(default_factory=dict)
    multipliers: dict[int, dict[str, Any]] = field(default_factory=dict)
    researches: dict[int, dict[str, Any]] = field(default_factory=dict)
    player_info: dict[str, Any] = field(default_factory=dict)
    last_player_packet: dict[str, Any] = field(default_factory=dict)
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    packet_counts: Counter[int | str] = field(default_factory=Counter)
    last_error: str | None = None

    def as_json(self) -> dict[str, Any]:
        owned_units = [
            self._enrich_unit(unit) for unit in self.units.values()
            if self.player_no is None or unit.get("owner") == self.player_no
        ]
        owned_cities = [
            self._enrich_city(city) for city in self.cities.values()
            if self.player_no is None or city.get("owner") == self.player_no
        ]
        return {
            "name": self.name,
            "connected": self.connected,
            "conn_id": self.conn_id,
            "player_no": self.player_no,
            "turn": self.turn,
            "year": self.year,
            "display_player_name": self.display_player_name,
            "phase": self._phase_view(),
            "ruleset": self.ruleset,
            "map_info": self.map_info,
            "map": self._map_view(),
            "units": owned_units,
            "cities": owned_cities,
            "unit_types": self.unit_types,
            "buildings": self.buildings,
            "extras": self.extras,
            "terrains": self.terrains,
            "techs": self.techs,
            "multipliers": self.multipliers,
            "researches": self.researches,
            "player_info": self.player_info,
            "player_status": self._player_packet_status(),
            "economy": self._economy_view(),
            "research": self._research_view(),
            "recent_messages": self.recent_messages[-20:],
            "packet_counts": dict(self.packet_counts.most_common(20)),
            "last_error": self.last_error,
        }

    def player_packet_audit(self) -> dict[str, Any]:
        raw_fields = sorted(self.last_player_packet)
        stored_fields = sorted(self.player_info)
        economy_fields = sorted(self._economy_view())
        represented_fields = sorted(
            field for field in raw_fields if field in PLAYER_STATUS_PACKET_FIELDS
        )
        return {
            "name": self.name,
            "turn": self.turn,
            "year": self.year,
            "player_no": self.player_no,
            "packet": {
                "type_id": 51,
                "type_name": "PACKET_PLAYER_INFO",
                "raw": self.last_player_packet,
                "raw_fields": raw_fields,
                "decoded": self._player_packet_status(),
            },
            "stored_player_info": {
                "data": self.player_info,
                "fields": stored_fields,
            },
            "structured_economy": {
                "data": self._economy_view(),
                "fields": economy_fields,
            },
            "structured_player_status": {
                "data": self._player_packet_status(),
                "represented_raw_fields": represented_fields,
            },
            "unexposed_packet_fields": [
                field for field in raw_fields if field not in PLAYER_STATUS_PACKET_FIELDS
            ],
            "raw_fields_not_stored_in_player_info": [
                field for field in raw_fields if field not in self.player_info
            ],
            "not_in_economy_view": [
                field for field in raw_fields if field not in economy_fields
            ],
        }

    def as_brief_json(self) -> dict[str, Any]:
        owned_units = [
            self._brief_unit(self._enrich_unit(unit))
            for unit in self.units.values()
            if self.player_no is None or unit.get("owner") == self.player_no
        ]
        owned_cities = [
            self._brief_city(self._enrich_city(city))
            for city in self.cities.values()
            if self.player_no is None or city.get("owner") == self.player_no
        ]
        return {
            "name": self.name,
            "connected": self.connected,
            "player_no": self.player_no,
            "turn": self.turn,
            "year": self.year,
            "display_player_name": self.display_player_name,
            "phase": self._phase_view(),
            "ruleset": self.ruleset,
            "map": self._map_view(),
            "economy": self._economy_view(),
            "player_status": self._player_packet_status(compact=True),
            "research": self._research_view(),
            "production_targets": self.production_targets(summary=True),
            "cities": owned_cities,
            "units": owned_units,
            "known_tiles": len(self.tiles),
            "last_error": self.last_error,
        }

    def production_targets(
        self,
        *,
        summary: bool = False,
        city_id: int | None = None,
    ) -> dict[str, Any]:
        city = self.cities.get(city_id) if city_id is not None else None
        enriched_city = self._enrich_city(city) if city is not None else None
        unit_targets = [
            self._production_target_entry(
                unit_type_id,
                unit_type,
                category="unit",
                city=enriched_city,
            )
            for unit_type_id, unit_type in self.unit_types.items()
        ]
        building_targets = [
            self._production_target_entry(
                building_id,
                building,
                category="building",
                city=enriched_city,
            )
            for building_id, building in self.buildings.items()
        ]
        unit_targets.sort(key=_production_sort_key)
        building_targets.sort(key=_production_sort_key)
        key_units = self._key_unit_targets(unit_targets)
        common_units = [
            target
            for group in key_units.values()
            for target in group
        ]
        result: dict[str, Any] = {
            "usage": {
                "unit": "bin/game set-city-production <city_id> <target> --kind unit",
                "building": "bin/game set-city-production <city_id> <target> --kind building",
                "target_rule": (
                    "Use the exact target value from this list. For this ruleset, "
                    "Settlers are city founders. Migrants are population/settler-class "
                    "utility units but cannot found cities."
                ),
            },
            "key_unit_targets": key_units,
            "common_unit_targets": common_units,
            "counts": {
                "unit": len(unit_targets),
                "building": len(building_targets),
            },
        }
        if city_id is not None:
            result["city_id"] = city_id
            result["city"] = self._brief_city(enriched_city) if enriched_city else None
            result["city_specific_legality"] = (
                "advisory; Freeciv server is authoritative. Known blockers are "
                "hidden server no-ops if sent."
            )
        if summary:
            return result
        result["unit_targets"] = unit_targets
        result["building_targets"] = building_targets
        return result

    def _production_target_entry(
        self,
        item_id: int,
        item: dict[str, Any],
        *,
        category: str,
        city: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rule_name = display_label(item.get("rule_name"))
        name = display_label(item.get("name"))
        target = rule_name or name or str(item_id)
        entry: dict[str, Any] = {
            "id": int(item_id),
            "kind": category,
            "target": target,
            "name": name,
            "rule_name": rule_name,
            "build_cost": item.get("build_cost"),
        }
        if category == "unit":
            unit_rule_name = target
            noncombat_rules = {
                "Settlers",
                "Migrants",
                "Workers",
                "Engineers",
                "Caravan",
                "Freight",
                "Diplomat",
                "Spy",
                "Explorer",
            }
            for key in (
                "pop_cost",
                "attack_strength",
                "defense_strength",
                "move_rate",
                "hp",
                "worker",
                "transport_capacity",
            ):
                if key in item:
                    entry[key] = item[key]
            if item.get("build_reqs"):
                entry["build_requirements"] = [
                    self._requirement_info(req)
                    for req in item.get("build_reqs") or []
                ]
            roles: list[str] = []
            if unit_rule_name == "Settlers":
                roles.extend(["city founder", "worker"])
                entry["can_found_city"] = True
            elif unit_rule_name == "Migrants":
                roles.extend(["population transfer", "worker-style utility"])
                entry["can_found_city"] = False
                entry["note"] = "Migrants cannot found cities in civ2civ3."
            elif unit_rule_name in {"Workers", "Engineers"}:
                roles.append("worker")
            elif unit_rule_name == "Explorer":
                roles.append("explorer")
            elif unit_rule_name in {"Caravan", "Freight"}:
                roles.append("trade")
            elif unit_rule_name in {"Diplomat", "Spy"}:
                roles.append("diplomacy")
            if item.get("pop_cost"):
                roles.append("costs population")
            if item.get("worker") and "worker" not in roles:
                roles.append("worker")
            has_combat_stats = bool(item.get("attack_strength") or item.get("defense_strength"))
            if has_combat_stats and unit_rule_name not in noncombat_rules:
                roles.append("military")
            if item.get("transport_capacity"):
                roles.append("transport")
            if roles:
                entry["roles"] = roles
        else:
            for key in ("upkeep", "genus"):
                if key in item:
                    entry[key] = item[key]
            if item.get("reqs"):
                entry["build_requirements"] = [
                    self._requirement_info(req)
                    for req in item.get("reqs") or []
                ]
        if city is not None:
            kind_id = 6 if category == "unit" else 3
            entry["legality"] = self._production_target_legality(
                city=city,
                kind_id=kind_id,
                value_id=int(item_id),
                item=item,
            )
        return entry

    def _production_target_legality(
        self,
        *,
        city: dict[str, Any],
        kind_id: int,
        value_id: int,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        blockers: list[str] = []
        warnings: list[str] = []
        current = city.get("production") or {}
        current_kind = city.get("production_kind")
        current_value = city.get("production_value")
        if current_kind == kind_id and current_value == value_id:
            blockers.append("city is already producing this target")
        if city.get("did_buy"):
            blockers.append("city bought production this turn and Freeciv blocks production changes after buying")
        if kind_id == 3 and value_id in self._bitvector_ids(city.get("improvements")):
            blockers.append("city already has this building")
        evaluated_req_ids: set[int] = set()
        if kind_id == 6:
            pop_cost = item.get("pop_cost")
            size = city.get("size")
            if isinstance(pop_cost, int) and isinstance(size, int) and pop_cost > 0:
                warnings.append(
                    f"unit costs {pop_cost} population from city size {size}; Freeciv may reject or shrink the city"
                )
            evaluated_req_ids.update(
                self._evaluate_production_requirements(
                    reqs=item.get("build_reqs") or [],
                    city=city,
                    blockers=blockers,
                    warnings=warnings,
                )
            )
            if item.get("build_reqs_count") and len(evaluated_req_ids) < int(item.get("build_reqs_count") or 0):
                warnings.append("unit has build requirements that this harness only partially decodes")
        if kind_id == 3:
            evaluated_req_ids.update(
                self._evaluate_production_requirements(
                    reqs=item.get("reqs") or [],
                    city=city,
                    blockers=blockers,
                    warnings=warnings,
                )
            )
            if item.get("reqs_count") and len(evaluated_req_ids) < int(item.get("reqs_count") or 0):
                warnings.append("building has requirements that this harness only partially decodes")
        estimate = "known_blocked" if blockers else "no_known_blocker"
        return {
            "estimate": estimate,
            "can_send": not blockers,
            "known_blockers": blockers,
            "warnings": warnings,
            "current_production": {
                "kind_id": current_kind,
                "value_id": current_value,
                "name": current.get("name"),
                "command_target": current.get("command_target"),
            },
        }

    def _evaluate_production_requirements(
        self,
        *,
        reqs: list[Any],
        city: dict[str, Any],
        blockers: list[str],
        warnings: list[str],
    ) -> set[int]:
        evaluated: set[int] = set()
        known_tech_ids = self._known_tech_ids()
        available_tech_ids = {item["id"] for item in self._available_research(self._own_research() or {})}
        for index, req in enumerate(reqs):
            if not isinstance(req, dict):
                continue
            kind = req.get("kind")
            value = req.get("value")
            present = bool(req.get("present", True))
            if kind == 1 and isinstance(value, int):
                evaluated.add(index)
                tech = self._tech_info(value)
                tech_name = display_label(tech.get("rule_name")) or display_label(tech.get("name")) or f"tech {value}"
                known = value in known_tech_ids
                if present and not known:
                    if value in available_tech_ids:
                        blockers.append(f"requires {tech_name} tech, which is available to research but not known")
                    else:
                        blockers.append(f"requires {tech_name} tech, which is not known")
                elif not present and known:
                    blockers.append(f"requires not having {tech_name} tech, but it is known")
            elif kind == 12 and isinstance(value, int):
                evaluated.add(index)
                size = city.get("size")
                if isinstance(size, int):
                    if present and size < value:
                        blockers.append(f"requires city size at least {value}; city size is {size}")
                    elif not present and size >= value:
                        blockers.append(f"requires city size below {value}; city size is {size}")
                else:
                    warnings.append(f"requires city size condition {value}, but city size is unknown")
        return evaluated

    def _requirement_info(self, req: Any) -> dict[str, Any]:
        if not isinstance(req, dict):
            return {"raw": req, "decoded": False}
        kind = req.get("kind")
        value = req.get("value")
        result = {
            "kind_id": kind,
            "kind": REQ_KIND_NAMES.get(kind, f"RequirementKind {kind}"),
            "range_id": req.get("range"),
            "range": REQ_RANGE_NAMES.get(req.get("range"), f"Range {req.get('range')}"),
            "present": req.get("present"),
            "value": value,
            "quiet": req.get("quiet"),
            "survives": req.get("survives"),
        }
        if kind == 1 and isinstance(value, int):
            tech = self._tech_info(value)
            result["value_name"] = display_label(tech.get("rule_name")) or display_label(tech.get("name"))
            result["known"] = value in self._known_tech_ids()
        elif kind == 3 and isinstance(value, int):
            building = self.buildings.get(value)
            result["value_name"] = (
                display_label(building.get("rule_name")) or display_label(building.get("name"))
                if building
                else None
            )
        elif kind == 6 and isinstance(value, int):
            unit = self.unit_types.get(value)
            result["value_name"] = (
                display_label(unit.get("rule_name")) or display_label(unit.get("name"))
                if unit
                else None
            )
        return result

    def _known_tech_ids(self) -> set[int]:
        research = self._own_research()
        if research is None:
            return set()
        return {item["id"] for item in self._known_techs(research)}

    @staticmethod
    def _bitvector_ids(value: Any) -> set[int]:
        if not isinstance(value, list):
            return set()
        ids: set[int] = set()
        for byte_index, item in enumerate(value):
            if not isinstance(item, int):
                continue
            for bit_index in range(8):
                if item & (1 << bit_index):
                    ids.add(byte_index * 8 + bit_index)
        return ids

    @staticmethod
    def _key_unit_targets(unit_targets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        by_name = {
            str(target.get("target")): target
            for target in unit_targets
            if target.get("target")
        }
        groups = {
            "city_founding": ["Settlers"],
            "workers_and_population": ["Workers", "Engineers", "Migrants"],
            "early_military": ["Warriors", "Phalanx", "Archers", "Horsemen"],
            "diplomacy_trade_exploration": ["Diplomat", "Explorer", "Caravan", "Spy", "Freight"],
        }
        return {
            group: [by_name[name] for name in names if name in by_name]
            for group, names in groups.items()
        }

    def _map_view(self) -> dict[str, Any]:
        result = dict(self.map_info)
        result["topology"] = topology_info(self.map_info)
        return result

    def _phase_view(self) -> dict[str, Any]:
        mode = self.phase_mode
        phase = self.phase
        team = self.player_info.get("team")
        result: dict[str, Any] = {
            "id": phase,
            "mode_id": mode,
            "mode_name": PHASE_MODE_NAMES.get(mode, f"unknown phase mode {mode}"),
            "mode_rule_name": PHASE_MODE_RULE_NAMES.get(mode),
            "meaning": PHASE_MODE_MEANINGS.get(mode),
            "agent_is_active_phase": None,
        }
        if mode == 0:
            result["active_scope"] = "all players"
            result["agent_is_active_phase"] = True
        elif mode == 1:
            result["active_scope"] = "single player"
            result["active_player_no"] = phase
            if phase is not None and self.player_no is not None:
                result["agent_is_active_phase"] = int(phase) == int(self.player_no)
            elif self.inferred_active_player_name:
                result["active_player_name"] = self.inferred_active_player_name
                result["active_player_source"] = "recent_server_message"
                result["agent_display_player_name"] = self.display_player_name
                if self.display_player_name:
                    result["agent_is_active_phase"] = (
                        self.inferred_active_player_name == self.display_player_name
                    )
        elif mode == 2:
            result["active_scope"] = "single team"
            result["active_team_no"] = phase
            result["agent_team_no"] = team
            if phase is not None and team is not None:
                result["agent_is_active_phase"] = int(phase) == int(team)
        return result

    def _economy_view(self) -> dict[str, Any]:
        fields = compact_packet(
            self.player_info,
            [
                "gold",
                "tax",
                "science",
                "luxury",
                "score",
                "culture",
                "mood",
                "nturns_idle",
                "government",
                "target_government",
                "science_cost",
                "tech_upkeep_16",
                "tech_upkeep_32",
                "phase_done",
                "is_alive",
            ],
        )
        if "tech_upkeep_32" in fields:
            fields["tech_upkeep"] = fields["tech_upkeep_32"]
        elif "tech_upkeep_16" in fields:
            fields["tech_upkeep"] = fields["tech_upkeep_16"]
        fields.setdefault("luxury", 0)
        return fields

    def _player_packet_status(self, *, compact: bool = False) -> dict[str, Any]:
        packet = dict(self.player_info)
        packet.update(self.last_player_packet)
        if not packet:
            return {
                "available": False,
                "source": "PACKET_PLAYER_INFO has not been received yet",
            }

        result: dict[str, Any] = {
            "available": True,
            "source": "PACKET_PLAYER_INFO",
            "protocol": {
                "packet_id": 51,
                "packet_name": "PACKET_PLAYER_INFO",
            },
            "identity": {
                "player_no": packet.get("playerno", self.player_no),
                "name": packet.get("name", self.display_player_name or self.name),
                "username": packet.get("username"),
                "nation_id": packet.get("nation"),
                "team_id": packet.get("team"),
                "is_male": packet.get("is_male"),
                "was_created": packet.get("was_created"),
                "unassigned_user": packet.get("unassigned_user"),
            },
            "connection": {
                "is_connected": packet.get("is_connected"),
                "is_ready": packet.get("is_ready"),
                "phase_done": packet.get("phase_done"),
            },
            "lifecycle": {
                "turns_alive": packet.get("turns_alive"),
                "is_alive": packet.get("is_alive"),
                "idle_turns": packet.get("nturns_idle"),
                "revolution_finishes": packet.get("revolution_finishes"),
            },
            "politics": self._decode_politics(packet),
            "economy_packet": self._decode_economy_packet(packet),
            "visibility": self._decode_visibility(packet),
            "ai_profile": self._decode_ai_profile(packet),
            "ai_attitudes": self._decode_love(packet.get("love")),
            "flags": self._decode_player_flags(packet.get("flags")),
            "wonders": self._decode_wonders(packet.get("wonders")),
            "multipliers": self._decode_multipliers(packet),
            "style": self._decode_style(packet),
            "packet_delta": self._decode_player_info_fields(packet.get("fields")),
        }
        if compact:
            result["packet_delta"].pop("raw_bitvector", None)
        return result

    @staticmethod
    def _decode_politics(packet: dict[str, Any]) -> dict[str, Any]:
        mood_id = packet.get("mood")
        return {
            "government_id": packet.get("government"),
            "target_government_id": packet.get("target_government"),
            "mood": {
                "id": mood_id,
                "name": MOOD_NAMES.get(mood_id, f"unknown mood {mood_id}")
                if mood_id is not None
                else None,
            },
        }

    @staticmethod
    def _decode_economy_packet(packet: dict[str, Any]) -> dict[str, Any]:
        tech_upkeep = packet.get("tech_upkeep_32")
        tech_upkeep_field = "tech_upkeep_32"
        if tech_upkeep is None:
            tech_upkeep = packet.get("tech_upkeep_16")
            tech_upkeep_field = "tech_upkeep_16"
        return {
            "gold": packet.get("gold"),
            "tax": packet.get("tax"),
            "science": packet.get("science"),
            "luxury": packet.get("luxury"),
            "score": packet.get("score"),
            "culture": packet.get("culture"),
            "infrapoints": packet.get("infrapoints"),
            "science_cost": packet.get("science_cost"),
            "tech_upkeep": tech_upkeep,
            "tech_upkeep_source_field": tech_upkeep_field if tech_upkeep is not None else None,
            "history": packet.get("history"),
        }

    def _decode_visibility(self, packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "real_embassy": self._decode_player_slot_bitvector(
                packet.get("real_embassy"),
                "players for whom this player has a real embassy/contact visibility flag",
            ),
            "gives_shared_vision": self._decode_player_slot_bitvector(
                packet.get("gives_shared_vision"),
                "players receiving shared vision from this player",
            ),
            "gives_shared_tiles": self._decode_player_slot_bitvector(
                packet.get("gives_shared_tiles"),
                "players receiving shared tile visibility from this player",
            ),
        }

    @staticmethod
    def _decode_ai_profile(packet: dict[str, Any]) -> dict[str, Any]:
        ai_skill = packet.get("ai_skill_level")
        barbarian_type = packet.get("barbarian_type")
        return {
            "ai_skill_level": {
                "id": ai_skill,
                "name": AI_LEVEL_NAMES.get(ai_skill, f"unknown AI level {ai_skill}")
                if ai_skill is not None
                else None,
            },
            "barbarian_type": {
                "id": barbarian_type,
                "name": BARBARIAN_TYPE_NAMES.get(
                    barbarian_type,
                    f"unknown barbarian type {barbarian_type}",
                )
                if barbarian_type is not None
                else None,
            },
        }

    def _decode_player_slot_bitvector(self, raw: Any, meaning: str) -> dict[str, Any]:
        slots = bitvector_ids(raw)
        return {
            "meaning": meaning,
            "raw_bitvector": raw,
            "active_count": len(slots),
            "active_slots": [
                {
                    "player_slot": slot,
                    "relation": "self"
                    if self.player_no is not None and slot == self.player_no
                    else "other",
                }
                for slot in slots
            ],
        }

    def _decode_player_info_fields(self, raw: Any) -> dict[str, Any]:
        indexes = bitvector_ids(raw)
        return {
            "meaning": (
                "protocol metadata: PACKET_PLAYER_INFO delta fields present in "
                "the most recent raw packet, not gameplay map fields"
            ),
            "raw_bitvector": raw,
            "set_bits": [
                {
                    "index": index,
                    "field": (
                        PLAYER_INFO_DELTA_FIELD_NAMES[index]
                        if index < len(PLAYER_INFO_DELTA_FIELD_NAMES)
                        else f"unknown_field_{index}"
                    ),
                }
                for index in indexes
            ],
        }

    def _decode_player_flags(self, raw: Any) -> dict[str, Any]:
        active_ids = bitvector_ids(raw)
        active = []
        for flag_id in active_ids:
            name = PLAYER_FLAG_NAMES.get(flag_id, f"unknown_flag_{flag_id}")
            active.append(
                {
                    "id": flag_id,
                    "name": name,
                    "meaning": PLAYER_FLAG_MEANINGS.get(name),
                }
            )
        known = []
        for flag_id, name in PLAYER_FLAG_NAMES.items():
            known.append(
                {
                    "id": flag_id,
                    "name": name,
                    "active": flag_id in active_ids,
                    "meaning": PLAYER_FLAG_MEANINGS.get(name),
                }
            )
        return {
            "raw_bitvector": raw,
            "active": active,
            "known_flags": known,
        }

    def _decode_love(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, list):
            return {
                "available": False,
                "meaning": "AI attitude values by player slot; absent from latest stored packet",
            }
        entries: list[dict[str, Any]] = []
        omitted_zero_slots = 0
        for slot, value in enumerate(raw):
            if not isinstance(value, int):
                continue
            relation = "self" if self.player_no is not None and slot == self.player_no else "other"
            if value == 0 and relation != "self":
                omitted_zero_slots += 1
                continue
            entries.append(
                {
                    "player_slot": slot,
                    "relation": relation,
                    "value": value,
                    "attitude": love_attitude(value),
                }
            )
        return {
            "available": True,
            "meaning": (
                "Freeciv AI attitude values by player slot, using love_text() thresholds; "
                "0 and small values are Neutral"
            ),
            "range": {"min": -MAX_AI_LOVE, "max": MAX_AI_LOVE},
            "entries": entries,
            "non_neutral_count": sum(
                1
                for item in raw
                if isinstance(item, int) and love_attitude(item) != "Neutral"
            ),
            "omitted_zero_neutral_slots": omitted_zero_slots,
        }

    def _decode_wonders(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, list):
            return {
                "available": False,
                "meaning": "wonder ownership/build-city array; absent from latest stored packet",
            }
        if all(isinstance(item, int) for item in raw):
            entries = []
            not_built = 0
            for building_id, city_id in enumerate(raw):
                if city_id == WONDER_NOT_BUILT:
                    not_built += 1
                    continue
                building = self.buildings.get(building_id, {})
                entry: dict[str, Any] = {
                    "building_id": building_id,
                    "building_name": display_label(building.get("name")) if building else None,
                    "building_rule_name": display_label(building.get("rule_name")) if building else None,
                    "city_id": city_id,
                }
                if city_id == WONDER_LOST:
                    entry["status"] = "lost"
                    entry["meaning"] = "this player once had the wonder but lost it"
                elif city_id > 0:
                    city = self.cities.get(city_id)
                    entry["status"] = "built"
                    entry["meaning"] = "this player owns the wonder in the listed city"
                    if city:
                        entry["city_name"] = city.get("name")
                else:
                    entry["status"] = "unknown"
                    entry["meaning"] = "unrecognized Freeciv wonder city marker"
                entries.append(entry)
            return {
                "available": True,
                "encoding": "flat_player_wonders_array",
                "meaning": (
                    "indexed by building/improvement id; value is city id, "
                    "0 means not built, -1 means lost"
                ),
                "built_or_lost_count": len(entries),
                "not_built_count": not_built,
                "entries": entries,
            }

        return {
            "available": True,
            "encoding": "raw_json_diff_or_partial_array",
            "meaning": (
                "Freeciv marked wonders as a diff array; the harness preserves this "
                "raw shape because it is not a normal full building-id -> city-id list"
            ),
            "raw": raw,
            "segments": [
                {
                    "index": index,
                    "values": item,
                    "note": "raw Freeciv JSON array segment; not normalized",
                }
                for index, item in enumerate(raw)
            ],
        }

    def _decode_multipliers(self, packet: dict[str, Any]) -> dict[str, Any]:
        count = packet.get("multip_count")
        values = packet.get("multiplier")
        targets = packet.get("multiplier_target")
        changed = packet.get("multiplier_changed")
        if count is None and values is None and targets is None and changed is None:
            return {
                "available": False,
                "meaning": "ruleset multiplier values; absent from latest stored packet",
            }
        if not isinstance(count, int):
            count = max(
                len(values) if isinstance(values, list) else 0,
                len(targets) if isinstance(targets, list) else 0,
                len(changed) if isinstance(changed, list) else 0,
            )
        entries: list[dict[str, Any]] = []
        for index in range(max(0, int(count or 0))):
            rule = self.multipliers.get(index, {})
            entry: dict[str, Any] = {
                "id": index,
                "name": display_label(rule.get("name")) if rule else None,
                "rule_name": display_label(rule.get("rule_name")) if rule else None,
                "value": values[index] if isinstance(values, list) and index < len(values) else None,
                "target": targets[index] if isinstance(targets, list) and index < len(targets) else None,
                "changed_turn": changed[index] if isinstance(changed, list) and index < len(changed) else None,
            }
            for key in ("start", "stop", "step", "def", "offset", "factor", "minimum_turns"):
                if key in rule:
                    entry[key] = rule[key]
            if rule.get("reqs"):
                entry["requirements"] = [
                    self._requirement_info(req)
                    for req in rule.get("reqs") or []
                ]
            entries.append(entry)
        return {
            "available": True,
            "meaning": (
                "ruleset-defined player multipliers/policies; value is current, "
                "target is requested value, changed_turn is when it last changed"
            ),
            "count": count,
            "ruleset_definitions_known": len(self.multipliers),
            "entries": entries,
            "raw": {
                "multip_count": packet.get("multip_count"),
                "multiplier": values,
                "multiplier_target": targets,
                "multiplier_changed": changed,
            },
        }

    @staticmethod
    def _decode_style(packet: dict[str, Any]) -> dict[str, Any]:
        color_keys = ("color_red", "color_green", "color_blue")
        color_available = all(key in packet for key in color_keys)
        result: dict[str, Any] = {
            "style_id": packet.get("style"),
            "music_style_id": packet.get("music_style"),
            "autoselect_weight": packet.get("autoselect_weight"),
            "color_valid": packet.get("color_valid"),
            "color_changeable": packet.get("color_changeable"),
        }
        if color_available:
            red = packet.get("color_red")
            green = packet.get("color_green")
            blue = packet.get("color_blue")
            result["color_rgb"] = {
                "red": red,
                "green": green,
                "blue": blue,
                "css_hex": f"#{int(red):02x}{int(green):02x}{int(blue):02x}"
                if all(isinstance(item, int) for item in (red, green, blue))
                else None,
            }
        return result

    def _research_view(self) -> dict[str, Any] | None:
        research = self._own_research()
        if research is None:
            return None
        result = compact_packet(
            research,
            [
                "id",
                "techs_researched",
                "future_tech",
                "researching",
                "researching_cost",
                "bulbs_researched",
                "tech_goal",
                "total_bulbs_prod",
            ],
        )
        if "researching" in result:
            result["researching_info"] = self._tech_info(result["researching"], research)
        if "tech_goal" in result:
            result["tech_goal_info"] = self._tech_info(result["tech_goal"], research)
        available = self._available_research(research)
        if available:
            result["available"] = available
        known = self._known_techs(research)
        if known:
            result["known"] = known
        return result

    def _own_research(self) -> dict[str, Any] | None:
        if self.player_no is None:
            return None
        if self.player_no in self.researches:
            return self.researches[self.player_no]
        if len(self.researches) == 1:
            return next(iter(self.researches.values()))
        return None

    def _tech_info(
        self,
        tech_id: Any,
        research: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tech_key = int(tech_id)
        special = self._special_tech_info(tech_key, research)
        if special is not None:
            return special
        tech = self.techs.get(tech_key)
        if tech is None:
            return {
                "id": tech_key,
                "name": f"unknown tech {tech_key}",
                "rule_name": None,
                "known": False,
            }
        return {
            "id": tech_key,
            "name": tech.get("name"),
            "rule_name": tech.get("rule_name"),
            "known": True,
            "removed": tech.get("removed"),
            "cost": tech.get("cost"),
            "root_req": tech.get("root_req"),
        }

    def _special_tech_info(
        self,
        tech_id: int,
        research: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        specials = {
            0: "None",
            A_LAST: "last regular tech sentinel",
            A_FUTURE: "Future Tech",
            A_UNSET: "unset - choose a research target",
            A_UNKNOWN: "unknown to this client",
        }
        if tech_id in specials:
            return {
                "id": tech_id,
                "name": specials[tech_id],
                "rule_name": None,
                "known": True,
                "special": True,
            }
        if tech_id == 0:
            return {
                "id": 0,
                "name": "None",
                "rule_name": None,
                "known": True,
                "special": True,
            }
        return None

    def _available_research(self, research: dict[str, Any]) -> list[dict[str, Any]]:
        return self._techs_by_invention_state(research, {"1", 1, "TECH_PREREQS_KNOWN"})

    def _known_techs(self, research: dict[str, Any]) -> list[dict[str, Any]]:
        return self._techs_by_invention_state(research, {"2", 2, "TECH_KNOWN"})

    def _techs_by_invention_state(
        self,
        research: dict[str, Any],
        states: set[Any],
    ) -> list[dict[str, Any]]:
        inventions = research.get("inventions")
        if isinstance(inventions, str):
            state_items: list[Any] = list(inventions)
        elif isinstance(inventions, list):
            state_items = inventions
        else:
            return []
        result = []
        for tech_id, state in enumerate(state_items):
            if state not in states:
                continue
            if tech_id == 0:
                continue
            info = self._tech_info(tech_id, research)
            if not info.get("removed"):
                info["state"] = TECH_STATE_NAMES.get(state, str(state))
                result.append(info)
        return result

    def _owner_info(self, owner_id: Any) -> dict[str, Any]:
        if owner_id is None:
            return {
                "id": None,
                "name": "unknown",
                "relation": "unknown",
            }
        owner = int(owner_id)
        if owner == 65535:
            return {
                "id": owner,
                "name": "unowned",
                "relation": "unowned",
            }
        if self.player_no is not None and owner == self.player_no:
            return {
                "id": owner,
                "name": self.name,
                "relation": "self",
            }
        return {
            "id": owner,
            "name": f"player {owner}",
            "relation": "other",
        }

    def _unit_type_info(self, unit_type_id: Any) -> dict[str, Any]:
        type_id = int(unit_type_id)
        unit_type = self.unit_types.get(type_id)
        if unit_type is None:
            return {
                "id": type_id,
                "name": f"unknown unit type {type_id}",
                "rule_name": None,
                "known": False,
            }
        return {
            "id": type_id,
            "name": unit_type.get("name"),
            "rule_name": unit_type.get("rule_name"),
            "known": True,
            "attack_strength": unit_type.get("attack_strength"),
            "defense_strength": unit_type.get("defense_strength"),
            "move_rate": unit_type.get("move_rate"),
            "hp": unit_type.get("hp"),
            "build_cost": unit_type.get("build_cost"),
            "worker": unit_type.get("worker"),
        }

    def _terrain_info(self, terrain_id: Any) -> dict[str, Any]:
        terrain_key = int(terrain_id)
        terrain = self.terrains.get(terrain_key)
        if terrain is None:
            return {
                "id": terrain_key,
                "name": f"unknown terrain {terrain_key}",
                "rule_name": None,
                "known": False,
            }
        return {
            "id": terrain_key,
            "name": terrain.get("name"),
            "rule_name": terrain.get("rule_name"),
            "known": True,
            "movement_cost": terrain.get("movement_cost"),
            "defense_bonus": terrain.get("defense_bonus"),
            "output": terrain.get("output"),
            "resources": terrain.get("resources"),
            "base_time": terrain.get("base_time"),
            "road_time": terrain.get("road_time"),
            "cultivate_result": terrain.get("cultivate_result"),
            "cultivate_time": terrain.get("cultivate_time"),
            "irrigation_food_incr": terrain.get("irrigation_food_incr"),
            "irrigation_time": terrain.get("irrigation_time"),
            "mining_shield_incr": terrain.get("mining_shield_incr"),
            "mining_time": terrain.get("mining_time"),
            "transform_result": terrain.get("transform_result"),
            "transform_time": terrain.get("transform_time"),
        }

    def _extra_info(self, extra_id: Any) -> dict[str, Any] | None:
        extra_key = int(extra_id)
        if extra_key < 0:
            return None
        if extra_key >= 250:
            return {
                "id": extra_key,
                "name": "none",
                "rule_name": None,
                "known": True,
                "meaning": "no extra/resource present",
            }
        extra = self.extras.get(extra_key)
        if extra is None:
            return {
                "id": extra_key,
                "name": f"unknown extra {extra_key}",
                "rule_name": None,
                "known": False,
            }
        return {
            "id": extra_key,
            "name": extra.get("name"),
            "rule_name": extra.get("rule_name"),
            "known": True,
            "category": extra.get("category"),
            "buildable": extra.get("buildable"),
            "generated": extra.get("generated"),
            "build_time": extra.get("build_time"),
            "removal_time": extra.get("removal_time"),
        }

    def _activity_info(self, activity_id: Any, target_id: Any = None) -> dict[str, Any]:
        activity = int(activity_id)
        target = self._extra_info(target_id) if target_id is not None else None
        return {
            "id": activity,
            "name": ACTIVITY_NAMES.get(activity, f"unknown activity {activity}"),
            "target": target,
        }

    @staticmethod
    def _extra_ids_from_bitvector(value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        result: list[int] = []
        for byte_index, item in enumerate(value):
            if not isinstance(item, int):
                continue
            for bit_index in range(8):
                if item & (1 << bit_index):
                    result.append(byte_index * 8 + bit_index)
        return result

    def _extras_info(self, value: Any) -> list[dict[str, Any]]:
        return [
            info
            for extra_id in self._extra_ids_from_bitvector(value)
            if (info := self._extra_info(extra_id)) is not None and info.get("known") is True
        ]

    def _production_info(self, city: dict[str, Any]) -> dict[str, Any] | None:
        if "production_kind" not in city or "production_value" not in city:
            return None
        kind_id = int(city["production_kind"])
        value_id = int(city["production_value"])
        kind_name = UNIVERSAL_KIND_NAMES.get(kind_id, f"unknown universal kind {kind_id}")
        result: dict[str, Any] = {
            "kind_id": kind_id,
            "kind": kind_name,
            "value_id": value_id,
        }
        if kind_id == 6:
            target = self._unit_type_info(value_id)
            result.update(
                {
                    "category": "unit",
                    "name": display_label(target.get("name")),
                    "rule_name": display_label(target.get("rule_name")),
                    "command_target": display_label(target.get("rule_name"))
                    or display_label(target.get("name")),
                    "target": target,
                }
            )
        elif kind_id == 3:
            building = self.buildings.get(value_id)
            result.update(
                {
                    "category": "building",
                    "name": display_label(building.get("name")) if building else f"unknown building {value_id}",
                    "rule_name": display_label(building.get("rule_name")) if building else None,
                    "command_target": (
                        display_label(building.get("rule_name"))
                        or display_label(building.get("name"))
                        if building
                        else None
                    ),
                    "target": building if building else None,
                }
            )
        else:
            result["category"] = "unknown"
            result["name"] = f"{kind_name} {value_id}"
        return result

    def _enrich_unit(self, unit: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(unit)
        if "owner" in unit:
            enriched["owner_info"] = self._owner_info(unit.get("owner"))
        unit_type = self.unit_types.get(int(unit["type"])) if "type" in unit else None
        if unit_type is not None:
            enriched["type_name"] = unit_type.get("name")
            enriched["type_rule_name"] = unit_type.get("rule_name")
            enriched["type_info"] = self._unit_type_info(unit["type"])
            unit_rule_name = display_label(unit_type.get("rule_name")) or display_label(unit_type.get("name"))
            if unit_rule_name == "Migrants":
                enriched["type_notes"] = [
                    "Migrants cannot found cities in civ2civ3; found-city will reject them.",
                    "Use Migrants for legal worker-style actions or population utility, not expansion founding.",
                ]
            elif unit_rule_name == "Settlers":
                enriched["type_notes"] = [
                    "Settlers are the civ2civ3 city-founder unit; use found-city on suitable tiles.",
                ]
            for key in ("attack_strength", "defense_strength", "move_rate", "worker"):
                if key in unit_type:
                    enriched[f"type_{key}"] = unit_type[key]
        elif "type" in unit:
            enriched["type_info"] = self._unit_type_info(unit["type"])
        else:
            enriched.update(self._missing_unit_type_info(unit))
        if "activity" in unit:
            enriched["activity_info"] = self._activity_info(
                unit["activity"],
                unit.get("activity_tgt"),
            )
        target = self.extras.get(int(unit["activity_tgt"])) if "activity_tgt" in unit else None
        if target is not None:
            enriched["activity_target_name"] = target.get("name")
            enriched["activity_target_rule_name"] = target.get("rule_name")
            enriched["activity_target_info"] = self._extra_info(unit["activity_tgt"])
        return enriched

    def _missing_unit_type_info(self, unit: dict[str, Any]) -> dict[str, Any]:
        return {
            "type_source": "missing",
            "type_info": {
                "known": False,
                "reason": (
                    "Freeciv has not exposed a concrete unit type id for this "
                    "visible unit yet. Do not infer unit role from hp or tile "
                    "state; use query-actions or the specific command result "
                    "to verify legal actions."
                ),
            },
        }

    def _enrich_city(self, city: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(city)
        if "name" in enriched:
            enriched["name"] = display_label(enriched.get("name"))
        if "owner" in city:
            enriched["owner_info"] = self._owner_info(city.get("owner"))
        production = self._production_info(city)
        if production is not None:
            enriched["production"] = production
        return enriched

    @staticmethod
    def _brief_unit(unit: dict[str, Any]) -> dict[str, Any]:
        return compact_packet(
            unit,
            [
                "id",
                "owner",
                "owner_info",
                "type",
                "type_name",
                "type_rule_name",
                "type_source",
                "type_info",
                "type_notes",
                "tile",
                "movesleft",
                "hp",
                "activity",
                "activity_info",
                "activity_tgt",
                "activity_target_name",
                "activity_target_rule_name",
                "activity_target_info",
                "done_moving",
                "homecity",
            ],
        )

    @staticmethod
    def _brief_city(city: dict[str, Any]) -> dict[str, Any]:
        return compact_packet(
            city,
            [
                "id",
                "name",
                "owner",
                "owner_info",
                "tile",
                "size",
                "food_stock",
                "shield_stock",
                "production_kind",
                "production_value",
                "production",
                "did_buy",
            ],
        )


class ManagedAgent:
    def __init__(self, name: str, host: str, port: int, ruleset: dict[str, Any]) -> None:
        self.name = name
        self.client = FreecivJsonClient(host, port, timeout=2.0)
        self.state = PlayerState(name=name, ruleset=ruleset)
        self._lock = threading.RLock()
        self._state_condition = threading.Condition(self._lock)
        self._actions_condition = threading.Condition(self._lock)
        self._latest_actions: dict[str, Any] | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def set_inferred_active_player_name(self, name: str | None) -> None:
        with self._lock:
            self.state.inferred_active_player_name = name

    def _observe_server_message(self, message: Any) -> None:
        text = plain_server_message(message)
        login = LOGIN_MESSAGE_RE.search(text)
        if login and login.group("username") == self.name:
            self.state.display_player_name = login.group("player").strip()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.state.as_json()

    def brief(self) -> dict[str, Any]:
        with self._lock:
            return self.state.as_brief_json()

    def player_packet_audit(self) -> dict[str, Any]:
        with self._lock:
            return self.state.player_packet_audit()

    def production_targets(self, *, city_id: int | None = None) -> dict[str, Any]:
        with self._lock:
            return self.state.production_targets(summary=False, city_id=city_id)

    def messages(self, limit: int = 20) -> dict[str, Any]:
        with self._lock:
            return {
                "player": self.name,
                "messages": self.state.recent_messages[-limit:],
            }

    def local_view(
        self,
        *,
        unit_id: int | None = None,
        city_id: int | None = None,
        tile_id: int | None = None,
        radius: int = 2,
    ) -> dict[str, Any]:
        with self._lock:
            center_tile = self._resolve_center_tile(
                unit_id=unit_id,
                city_id=city_id,
                tile_id=tile_id,
            )
            center_map = self._index_to_map_pos(center_tile)
            tiles = []
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    target_tile = self._map_pos_to_index(center_map[0] + dx, center_map[1] + dy)
                    if target_tile is None:
                        continue
                    tiles.append(self._local_tile(target_tile, dx, dy))
            return {
                "player": self.name,
                "turn": self.state.turn,
                "year": self.state.year,
                "center_tile": center_tile,
                "center_map": {"x": center_map[0], "y": center_map[1]},
                "radius": radius,
                "map": self.state._map_view(),
                "tiles": tiles,
            }

    def ascii_view(
        self,
        *,
        unit_id: int | None = None,
        city_id: int | None = None,
        tile_id: int | None = None,
        radius: int = 3,
    ) -> dict[str, Any]:
        view = self.local_view(
            unit_id=unit_id,
            city_id=city_id,
            tile_id=tile_id,
            radius=radius,
        )
        with self._lock:
            text = self._render_ascii_view(
                view,
                unit_id=unit_id,
                city_id=city_id,
                tile_id=tile_id,
            )
        return {
            "player": view["player"],
            "turn": view["turn"],
            "year": view["year"],
            "center_tile": view["center_tile"],
            "center_map": view["center_map"],
            "radius": view["radius"],
            "topology_id": self.state.map_info.get("topology_id"),
            "topology": topology_info(self.state.map_info),
            "format": "freeciv-agent-ascii-view-v2",
            "text": text,
        }

    def valid_moves(self, *, unit_id: int) -> dict[str, Any]:
        with self._lock:
            unit = self.state.units.get(unit_id)
            if unit is None or unit.get("owner") != self.state.player_no:
                raise RuntimeError(f"{self.name} does not own unit {unit_id}")
            current_tile = unit.get("tile")
            if current_tile is None:
                raise RuntimeError(f"{self.name} unit {unit_id} has no known tile")
            current_map = self._index_to_map_pos(int(current_tile))
            actionability = self._unit_actionability_info(unit)
            moves = []
            for direction in self._valid_directions():
                target_tile = self._step_tile(int(current_tile), direction)
                if target_tile is None:
                    continue
                dx, dy = self._direction_delta(direction)
                target_map = self._index_to_map_pos(target_tile)
                tile = self._local_tile(target_tile, dx, dy)
                can_enter_known = self._can_unit_enter_known_tile(unit, tile)
                legality = self._movement_legality_info(
                    unit=unit,
                    tile=tile,
                    can_enter_known=can_enter_known,
                    actionability=actionability,
                )
                moves.append(
                    {
                        "direction": direction,
                        "direction_info": direction_info(
                            direction,
                            self.state.map_info.get("topology_id"),
                        ),
                        "direction_name": DIRECTION_NAMES[direction],
                        "dx": dx,
                        "dy": dy,
                        "target_tile": target_tile,
                        "target_map": {"x": target_map[0], "y": target_map[1]},
                        "known": tile["known"],
                        "can_enter_known": can_enter_known,
                        "enterability": self._enterability_info(can_enter_known, tile),
                        "legality": legality,
                        "actionability": actionability,
                        "known_blockers": legality["known_blockers"],
                        "warnings": legality["warnings"],
                        "tile": tile,
                    }
                )
            return {
                "player": self.name,
                "turn": self.state.turn,
                "year": self.state.year,
                "authority": "harness estimate only; Freeciv is authoritative when move-unit is sent",
                "directions_are_filtered": False,
                "guidance": (
                    "These are topology-valid neighboring directions with local heuristic estimates. "
                    "Do not treat a blocked/maybe estimate as proof that Freeciv will reject the move."
                ),
                "unit": PlayerState._brief_unit(self.state._enrich_unit(unit)),
                "actionability": actionability,
                "current_tile": int(current_tile),
                "current_map": {"x": current_map[0], "y": current_map[1]},
                "topology_id": self.state.map_info.get("topology_id"),
                "topology": topology_info(self.state.map_info),
                "moves": moves,
            }

    def ready(self, is_ready: bool = True) -> dict[str, Any]:
        with self._lock:
            player_no = self.state.player_no
        if player_no is None:
            raise RuntimeError(f"{self.name} has no player_no yet")
        self.client.send_player_ready(player_no, is_ready)
        return {"ok": True, "player": self.name, "ready": is_ready}

    def say(self, message: str) -> dict[str, Any]:
        message = message.strip()
        if not message:
            raise RuntimeError("chat message cannot be empty")
        self.client.send_chat_message(message)
        response = {
            "ok": True,
            "player": self.name,
            "packet": "PACKET_CHAT_MSG_REQ",
            "visibility": "public_freeciv_chat",
            "message": message,
        }
        self._audit_command("say", response)
        return response

    def private_intent(self, intent: str, *, turn: int | None = None) -> dict[str, Any]:
        intent = intent.strip()
        if not intent:
            raise RuntimeError("private intent cannot be empty")
        with self._lock:
            turn = self.state.turn if turn is None else turn
            year = self.state.year
            phase = self.state.phase
            player_no = self.state.player_no
        if turn is None:
            raise RuntimeError(f"{self.name} does not know the current turn yet")
        entry = {
            "ts": time.time(),
            "schema": "freeciv-agent-private-intent-v0",
            "visibility": "private_harness_log_only",
            "player": self.name,
            "player_no": player_no,
            "turn": turn,
            "year": year,
            "phase": phase,
            "intent": intent,
        }
        try:
            PRIVATE_INTENT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with PRIVATE_INTENT_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
        except OSError as exc:
            with self._lock:
                self.state.last_error = f"private intent write failed: {exc}"
            raise RuntimeError(f"private intent write failed: {exc}") from exc
        return {
            "ok": True,
            "player": self.name,
            "turn": turn,
            "year": year,
            "visibility": "private_harness_log_only",
            "artifact": str(PRIVATE_INTENT_PATH),
        }

    def phase_done(
        self,
        turn: int | None = None,
        intent: str | None = None,
        wait: float = 2.0,
    ) -> dict[str, Any]:
        with self._lock:
            phase_before = self.state._phase_view()
        if phase_before.get("agent_is_active_phase") is False:
            response = {
                "ok": False,
                "player": self.name,
                "turn": turn,
                "packet": "PACKET_PLAYER_PHASE_DONE",
                "sent": False,
                "applied": False,
                "phase_before": phase_before,
                "result": {
                    "estimate": "blocked_player_not_active",
                    "reason": (
                        "This player is not the active player. Do not report "
                        "phase_done success unless the phase_done command was "
                        "sent while this player was active."
                    ),
                },
            }
            self._audit_command("phase-done", response)
            return response
        opening_blocker = self._phase_done_opening_city_blocker()
        if opening_blocker is not None:
            response = {
                "ok": False,
                "player": self.name,
                "turn": opening_blocker.get("turn"),
                "packet": "PACKET_PLAYER_PHASE_DONE",
                "sent": False,
                "applied": False,
                "result": {
                    "estimate": "blocked_opening_city_not_founded",
                    "reason": opening_blocker["reason"],
                },
                "required_action": opening_blocker["required_action"],
                "city_founding_units": opening_blocker["city_founding_units"],
                "legal_found_city_units": opening_blocker["legal_found_city_units"],
            }
            self._audit_command("phase-done", response)
            return response
        intent_result = None
        if intent is not None and intent.strip():
            intent_result = self.private_intent(intent, turn=turn)
        with self._lock:
            turn = self.state.turn if turn is None else turn
            before = dict(self.state.player_info)
        if turn is None:
            raise RuntimeError(f"{self.name} does not know the current turn yet")
        self.client.send_phase_done(turn)
        after, phase_after = self._wait_for_phase_done(
            previous=before,
            phase_before=phase_before,
            wait=wait,
        )
        phase_done_flag = bool(after and after.get("phase_done") is True)
        phase_advanced = phase_after.get("agent_is_active_phase") is False
        applied = bool(phase_done_flag or phase_advanced)
        response = {
            "ok": applied,
            "player": self.name,
            "turn": turn,
            "private_intent": intent_result,
            "packet": "PACKET_PLAYER_PHASE_DONE",
            "sent": True,
            "applied": applied,
            "before": compact_packet(before, ["phase_done", "is_alive"]),
            "after": compact_packet(after or {}, ["phase_done", "is_alive"]),
            "phase_before": phase_before,
            "phase_after": phase_after,
            "result": {
                "estimate": "confirmed_phase_done" if applied else "sent_but_not_observed",
                "reason": (
                    "Freeciv reported this player phase as done or advanced to another player"
                    if applied
                    else "phase-done packet was sent, but neither phase_done=true nor phase advancement was observed before timeout"
                ),
            },
            "wait_seconds": wait,
        }
        self._audit_command("phase-done", response)
        return response

    def _phase_done_opening_city_blocker(self) -> dict[str, Any] | None:
        with self._lock:
            if self.state.cities:
                return None
            own_units = [
                dict(unit)
                for unit in self.state.units.values()
                if unit.get("owner") == self.state.player_no
            ]
            turn = self.state.turn
        city_founders = []
        legal_founders = []
        action_checks = []
        for unit in own_units:
            enriched = self.state._enrich_unit(unit)
            type_info = enriched.get("type_info") or {}
            unit_type = (
                enriched.get("type_rule_name")
                or enriched.get("type_name")
                or type_info.get("rule_name")
                or type_info.get("name")
            )
            if str(unit_type).lower() != "settlers":
                continue
            brief_unit = PlayerState._brief_unit(enriched)
            city_founders.append(brief_unit)
            try:
                actions = self.query_actions(
                    unit_id=int(unit["id"]),
                    target_tile=int(unit["tile"]),
                    timeout=1.0,
                )
                found_probability = self._action_probability(actions, 27)
                action_checks.append(
                    {
                        "unit_id": int(unit["id"]),
                        "target_tile": int(unit["tile"]),
                        "action_probability": found_probability,
                    }
                )
                if self._action_probability_possible(found_probability):
                    legal_founders.append(brief_unit)
            except Exception as exc:
                action_checks.append(
                    {
                        "unit_id": int(unit.get("id", -1)),
                        "target_tile": unit.get("tile"),
                        "error": str(exc),
                    }
                )
        if not city_founders:
            return None
        if not legal_founders:
            mobile_founders = [
                founder
                for founder in city_founders
                if int(founder.get("movesleft") or 0) > 0
            ]
            if not mobile_founders:
                return None
            return {
                "turn": turn,
                "city_founding_units": city_founders,
                "legal_found_city_units": [],
                "mobile_city_founding_units": mobile_founders,
                "action_checks": action_checks,
                "reason": (
                    "This player has no cities and still owns at least one Settlers "
                    "unit with movement remaining. Do not end phase with zero cities "
                    "while a city founder can still act. If founding is not currently "
                    "legal, inspect local terrain and move the Settlers toward a legal "
                    "city site instead of reporting phase_done."
                ),
                "required_action": (
                    "Do not call phase_done while this player has zero cities and "
                    "an owned Settlers unit with movement remaining. Found a city "
                    "first, or move the Settlers toward a legal founding tile if "
                    "founding is impossible."
                ),
            }
        return {
            "turn": turn,
            "city_founding_units": city_founders,
            "legal_found_city_units": legal_founders,
            "action_checks": action_checks,
            "reason": (
                "This player has no cities and at least one Settlers unit can legally "
                "found a city on its current tile. Found a city before ending phase."
            ),
            "required_action": "Call found_city with no unit_id, or with one of the legal_found_city_units.",
        }

    def found_city(
        self,
        unit_id: int | None = None,
        city_name: str = "",
        wait: float = 5.0,
    ) -> dict[str, Any]:
        action_checks: list[dict[str, Any]] = []
        actions: dict[str, Any] | None = None
        requested_unit_id = unit_id
        requested_city_name = city_name
        city_name, city_name_info = self._resolve_found_city_name(city_name)
        rejected_requested_unit: dict[str, Any] | None = None

        def owned_candidates(skip_unit_ids: set[int] | None = None) -> list[dict[str, Any]]:
            skip_unit_ids = skip_unit_ids or set()
            with self._lock:
                return sorted(
                    [
                        dict(unit) for unit in self.state.units.values()
                        if (
                            unit.get("owner") == self.state.player_no
                            and unit.get("tile") is not None
                            and int(unit.get("id", -1)) not in skip_unit_ids
                        )
                    ],
                    key=lambda unit: (
                        0 if unit.get("type") == 0 else 1,
                        int(unit.get("id", 0)),
                    ),
                )

        def check_found_city_candidate(candidate: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
            candidate_id = int(candidate["id"])
            candidate_tile = int(candidate["tile"])
            try:
                candidate_actions = self.query_actions(
                    unit_id=candidate_id,
                    target_tile=candidate_tile,
                    timeout=2.0,
                )
                candidate_probability = self._action_probability(candidate_actions, 27)
                candidate_possible = self._action_probability_possible(candidate_probability)
                action_checks.append(
                    {
                        "unit_id": candidate_id,
                        "target_tile": candidate_tile,
                        "unit": PlayerState._brief_unit(self.state._enrich_unit(candidate)),
                        "action_probability": candidate_probability,
                        "possible_actions": self._possible_actions(candidate_actions),
                    }
                )
                return candidate_possible, candidate_actions
            except Exception as exc:
                fallback_actions = self._fallback_found_city_actions(candidate, str(exc))
                action_checks.append(
                    {
                        "unit_id": candidate_id,
                        "target_tile": candidate_tile,
                        "unit": PlayerState._brief_unit(self.state._enrich_unit(candidate)),
                        "error": str(exc),
                        "fallback_action_probability": (
                            self._action_probability(fallback_actions, 27)
                            if fallback_actions is not None
                            else None
                        ),
                        "fallback_reason": (
                            "action query timed out, but this is a decoded Settlers unit; "
                            "the harness will send Found City and verify by observation"
                            if fallback_actions is not None
                            else None
                        ),
                    }
                )
                return fallback_actions is not None, fallback_actions

        def legal_found_city_units(skip_unit_ids: set[int] | None = None) -> list[dict[str, Any]]:
            legal_units: list[dict[str, Any]] = []
            for candidate in owned_candidates(skip_unit_ids):
                candidate_possible, _ = check_found_city_candidate(candidate)
                if candidate_possible:
                    legal_units.append(
                        PlayerState._brief_unit(self.state._enrich_unit(candidate))
                    )
            return legal_units

        if unit_id is not None:
            with self._lock:
                requested_unit = self.state.units.get(unit_id)
                if requested_unit is not None:
                    requested_unit = dict(requested_unit)
            if requested_unit is None or requested_unit.get("owner") != self.state.player_no:
                rejected_requested_unit = {
                    "unit_id": unit_id,
                    "reason": f"{self.name} does not own unit {unit_id}.",
                }
                action_checks.append(rejected_requested_unit)
                response = {
                    "ok": False,
                    "player": self.name,
                    "requested_unit_id": requested_unit_id,
                    "requested_city_name": requested_city_name,
                    "city_name": city_name,
                    "city_name_info": city_name_info,
                    "packet": "PACKET_UNIT_DO_ACTION",
                    "sent": False,
                    "action": {
                        "id": 27,
                        "name": ACTION_NAMES[27],
                    },
                    "action_checks": action_checks,
                    "legal_found_city_units": legal_found_city_units(
                        {int(requested_unit_id)} if requested_unit_id is not None else set()
                    ),
                    "rejected_requested_unit": rejected_requested_unit,
                    "applied": False,
                    "observed_changed": False,
                    "result": {
                        "estimate": "not_sent_requested_unit_not_owned",
                        "reason": (
                            "The command named a specific unit_id, but that unit is not owned by this player. "
                            "No action was sent. Omit unit_id if you want the harness to choose a legal founder."
                        ),
                    },
                }
                self._audit_command("found-city", response)
                return response
            else:
                possible, candidate_actions = check_found_city_candidate(requested_unit)
                if possible:
                    actions = candidate_actions
                else:
                    rejected_requested_unit = {
                        "unit_id": int(requested_unit["id"]),
                        "target_tile": int(requested_unit["tile"]),
                        "unit": PlayerState._brief_unit(self.state._enrich_unit(requested_unit)),
                        "reason": (
                            "requested unit cannot found a city on its current tile"
                        ),
                    }
                    response = {
                        "ok": False,
                        "player": self.name,
                        "requested_unit_id": requested_unit_id,
                        "unit_id": int(requested_unit["id"]),
                        "target_tile": int(requested_unit["tile"]),
                        "requested_city_name": requested_city_name,
                        "city_name": city_name,
                        "city_name_info": city_name_info,
                        "packet": "PACKET_UNIT_DO_ACTION",
                        "sent": False,
                        "action": {
                            "id": 27,
                            "name": ACTION_NAMES[27],
                        },
                        "action_checks": action_checks,
                        "legal_found_city_units": legal_found_city_units({int(requested_unit["id"])}),
                        "rejected_requested_unit": rejected_requested_unit,
                        "applied": False,
                        "observed_changed": False,
                        "result": {
                            "estimate": "not_sent_requested_unit_cannot_found_city",
                            "reason": (
                                "The command named a specific unit_id, but Freeciv reports Found City is not "
                                "legal for that unit on its current tile. No action was sent. Omit unit_id if "
                                "you want the harness to choose a legal founder."
                            ),
                        },
                    }
                    self._audit_command("found-city", response)
                    return response

        if unit_id is None:
            candidates = owned_candidates()
            for candidate in candidates:
                candidate_id = int(candidate["id"])
                candidate_possible, candidate_actions = check_found_city_candidate(candidate)
                if candidate_possible:
                    unit_id = candidate_id
                    actions = candidate_actions
                    break
            if unit_id is None:
                response = {
                    "ok": False,
                    "player": self.name,
                    "requested_unit_id": requested_unit_id,
                    "requested_city_name": requested_city_name,
                    "city_name": city_name,
                    "city_name_info": city_name_info,
                    "packet": "PACKET_UNIT_DO_ACTION",
                    "sent": False,
                    "action": {
                        "id": 27,
                        "name": ACTION_NAMES[27],
                    },
                    "action_checks": action_checks,
                    "rejected_requested_unit": rejected_requested_unit,
                    "applied": False,
                    "observed_changed": False,
                    "result": {
                        "estimate": "not_sent_no_legal_found_city_unit",
                        "reason": (
                            "No owned unit currently reports Found City as legal "
                            "on its tile. The harness did not infer city-founder "
                            "status from unit hp or other heuristics."
                        ),
                    },
                }
                self._audit_command("found-city", response)
                return response

        with self._lock:
            unit = self.state.units.get(unit_id)
            if unit is None or unit.get("owner") != self.state.player_no:
                raise RuntimeError(f"{self.name} does not own unit {unit_id}")
            actor_id = int(unit["id"])
            target_id = int(unit["tile"])
            before = self.state._enrich_unit(unit)
            before_city_ids = set(self.state.cities)

        if actions is None:
            actions = self.query_actions(
                unit_id=actor_id,
                target_tile=target_id,
                timeout=2.0,
            )
        found_probability = self._action_probability(actions, 27)
        possible_actions = self._possible_actions(actions)
        if not self._action_probability_possible(found_probability):
            response = {
                "ok": False,
                "player": self.name,
                "unit_id": actor_id,
                "target_tile": target_id,
                "requested_city_name": requested_city_name,
                "city_name": city_name,
                "city_name_info": city_name_info,
                "packet": "PACKET_UNIT_DO_ACTION",
                "sent": False,
                "action": {
                    "id": 27,
                    "name": ACTION_NAMES[27],
                },
                "action_probability": found_probability,
                "possible_actions": possible_actions,
                "action_checks": action_checks or None,
                "before": PlayerState._brief_unit(before),
                "after": PlayerState._brief_unit(before),
                "applied": False,
                "observed_changed": False,
                "result": {
                    "estimate": "not_sent_action_not_legal",
                    "reason": (
                        "Freeciv reports Found City is not legal for this unit on this tile. "
                        "In the civ2civ3 ruleset, Migrants are not city-founding units; "
                        "they are not a valid target for found-city."
                    ),
                },
            }
            self._audit_command("found-city", response)
            return response

        self.client.send_unit_do_action(
            actor_id=actor_id,
            target_id=target_id,
            sub_tgt_id=0,
            name=city_name,
            action_type=27,
        )
        founded_city, after_unit = self._wait_for_found_city_update(
            unit_id=actor_id,
            target_tile=target_id,
            before_city_ids=before_city_ids,
            wait=wait,
        )
        applied = founded_city is not None
        observed_changed = bool(applied or after_unit is None or self._unit_changed(before, after_unit))
        response = {
            "ok": applied,
            "player": self.name,
            "packet": "PACKET_UNIT_DO_ACTION",
            "sent": True,
            "requested_unit_id": requested_unit_id,
            "unit_id": actor_id,
            "target_tile": target_id,
            "requested_city_name": requested_city_name,
            "city_name": city_name,
            "city_name_info": city_name_info,
            "action": {
                "id": 27,
                "name": ACTION_NAMES[27],
            },
            "sub_target": 0,
            "action_probability": found_probability,
            "possible_actions": possible_actions,
            "action_checks": action_checks or None,
            "before": PlayerState._brief_unit(before),
            "after": PlayerState._brief_unit(after_unit) if after_unit else None,
            "founded_city": PlayerState._brief_city(founded_city) if founded_city else None,
            "applied": applied,
            "observed_changed": observed_changed,
            "result": {
                "estimate": "confirmed_city_founded" if applied else "sent_but_not_observed",
                "reason": (
                    "a new owned city was observed on the target tile"
                    if applied
                    else "Found City was legal and packet was sent, but no new city was observed before timeout"
                ),
            },
            "wait_seconds": wait,
        }
        self._audit_command("found-city", response)
        return response

    def _fallback_found_city_actions(
        self,
        unit: dict[str, Any],
        query_error: str,
    ) -> dict[str, Any] | None:
        if not self._is_city_founding_unit(unit):
            return None
        probabilities = [{"min": 0, "max": 0} for _ in range(28)]
        probabilities[27] = {
            "min": 200,
            "max": 200,
            "source": "decoded_unit_type_fallback",
            "query_error": query_error,
        }
        return {
            "actor_unit_id": int(unit["id"]),
            "target_tile_id": int(unit["tile"]),
            "action_probabilities": probabilities,
            "fallback": {
                "source": "decoded_unit_type",
                "unit_type": self.state._enrich_unit(unit).get("type_rule_name")
                or self.state._enrich_unit(unit).get("type_name"),
                "query_error": query_error,
                "authority": (
                    "Freeciv action query timed out; the command is sent because "
                    "the ruleset identifies this unit as Settlers, and the result "
                    "is still judged by observed city creation."
                ),
            },
        }

    def _is_city_founding_unit(self, unit: dict[str, Any]) -> bool:
        enriched = self.state._enrich_unit(unit)
        type_info = enriched.get("type_info") or {}
        unit_type = (
            enriched.get("type_rule_name")
            or enriched.get("type_name")
            or type_info.get("rule_name")
            or type_info.get("name")
        )
        return str(unit_type).lower() == "settlers"

    def _resolve_found_city_name(self, requested_name: str) -> tuple[str, dict[str, Any]]:
        requested_name = str(requested_name or "")
        token = ascii_city_name_token(requested_name)
        generated = False
        normalized = token != requested_name
        with self._lock:
            existing_names = {
                str(city.get("name"))
                for city in self.state.cities.values()
                if city.get("owner") == self.state.player_no and city.get("name")
            }
            next_index = len(existing_names) + 1
        if not token:
            token = f"{ascii_city_name_token(self.name) or 'City'}{next_index}"
            generated = True
            normalized = True
        base = token[:24] or f"{ascii_city_name_token(self.name) or 'City'}{next_index}"
        candidate = base
        suffix = next_index
        while candidate in existing_names:
            suffix_text = str(suffix)
            candidate = f"{base[: max(1, 24 - len(suffix_text))]}{suffix_text}"
            suffix += 1
        return candidate, {
            "requested": requested_name,
            "actual": candidate,
            "generated_default": generated,
            "normalized_for_freeciv": normalized or candidate != requested_name,
            "rule": "ASCII letters and digits only; empty or unsafe names are converted before sending PACKET_UNIT_DO_ACTION.",
        }

    def move_unit(
        self,
        *,
        unit_id: int,
        target_tile: int | None = None,
        direction: int | None = None,
        dx: int = 0,
        dy: int = 0,
        wait: float = 5.0,
    ) -> dict[str, Any]:
        with self._lock:
            unit = self.state.units.get(unit_id)
            if unit is None or unit.get("owner") != self.state.player_no:
                raise RuntimeError(f"{self.name} does not own unit {unit_id}")
            current_tile = unit.get("tile")
            if current_tile is None:
                raise RuntimeError(f"{self.name} unit {unit_id} has no known tile")
            requested_target_tile = target_tile
            requested_relative = dx != 0 or dy != 0
            if direction is not None:
                direction_target = self._step_tile(int(current_tile), direction)
                if direction_target is None:
                    return self._move_unit_argument_error(
                        unit_id=unit_id,
                        current_tile=int(current_tile),
                        target_tile=target_tile,
                        direction=direction,
                        message=f"direction {direction} from tile {current_tile} is invalid",
                    )
                if (
                    requested_target_tile is not None
                    and int(requested_target_tile) != direction_target
                ):
                    return self._move_unit_argument_error(
                        unit_id=unit_id,
                        current_tile=int(current_tile),
                        target_tile=int(requested_target_tile),
                        direction=direction,
                        message=(
                            "conflicting move_unit arguments: "
                            f"direction {direction} from tile {current_tile} resolves to "
                            f"tile {direction_target}, but target_tile was "
                            f"{requested_target_tile}"
                        ),
                    )
                if requested_relative:
                    relative_target = self._relative_tile(int(current_tile), dx, dy)
                    if relative_target != direction_target:
                        return self._move_unit_argument_error(
                            unit_id=unit_id,
                            current_tile=int(current_tile),
                            target_tile=relative_target,
                            direction=direction,
                            message=(
                                "conflicting move_unit arguments: "
                                f"direction {direction} from tile {current_tile} resolves "
                                f"to tile {direction_target}, but dx={dx}, dy={dy} "
                                f"resolves to tile {relative_target}"
                            ),
                        )
                target_tile = direction_target
            elif target_tile is None:
                target_tile = self._relative_tile(int(current_tile), dx, dy)
                direction = self._direction_to_target(int(current_tile), target_tile)
            else:
                if requested_relative:
                    relative_target = self._relative_tile(int(current_tile), dx, dy)
                    if relative_target != target_tile:
                        return self._move_unit_argument_error(
                            unit_id=unit_id,
                            current_tile=int(current_tile),
                            target_tile=int(target_tile),
                            direction=None,
                            message=(
                                "conflicting move_unit arguments: "
                                f"target_tile was {target_tile}, but dx={dx}, dy={dy} "
                                f"from tile {current_tile} resolves to tile "
                                f"{relative_target}"
                            ),
                        )
                direction = self._direction_to_target(int(current_tile), target_tile)
            before = self.state._enrich_unit(unit)
            actionability = self._unit_actionability_info(unit)
            dx, dy = self._direction_delta(direction)
            target_tile_view = self._local_tile(target_tile, dx, dy)
            can_enter_known = self._can_unit_enter_known_tile(unit, target_tile_view)
            precheck = self._movement_legality_info(
                unit=unit,
                tile=target_tile_view,
                can_enter_known=can_enter_known,
                actionability=actionability,
            )

        if precheck.get("estimate") == "blocked":
            with self._lock:
                recent_messages = list(self.state.recent_messages[-5:])
            response = {
                "ok": False,
                "player": self.name,
                "unit_id": unit_id,
                "from_tile": current_tile,
                "target_tile": target_tile,
                "packet": "PACKET_UNIT_ORDERS",
                "sent": False,
                "direction": direction,
                "direction_info": direction_info(
                    direction,
                    self.state.map_info.get("topology_id"),
                ),
                "before": PlayerState._brief_unit(before),
                "after": PlayerState._brief_unit(before),
                "applied": False,
                "reached_target": False,
                "observed_changed": False,
                "result": "not_sent_known_invalid",
                "result_explanation": precheck.get("reason", "known invalid move"),
                "actionability": actionability,
                "legality": precheck,
                "precheck_authority": "advisory precheck blocked sending the command",
                "wait_seconds": 0,
                "recent_messages": recent_messages,
            }
            self._audit_command("move-unit", response)
            return response

        self.client.send_unit_move_order(
            unit_id=unit_id,
            src_tile=int(current_tile),
            dest_tile=target_tile,
            direction=direction,
        )

        after = self._wait_for_unit_observation(
            unit_id=unit_id,
            previous=before,
            target_tile=target_tile,
            wait=wait,
        )
        with self._lock:
            recent_messages = list(self.state.recent_messages[-5:])
        observed_changed = bool(after and self._unit_changed(before, after))
        reached_target = bool(after and after.get("tile") == target_tile)
        moved = bool(after and after.get("tile") != before.get("tile"))
        if reached_target:
            result = "confirmed_move"
            result_explanation = "unit was observed on the requested target tile"
        elif moved:
            result = "confirmed_moved_elsewhere"
            result_explanation = (
                "unit changed tile but was not observed on the requested target tile; "
                "inspect after/recent_messages"
            )
        elif observed_changed:
            result = "changed_without_moving"
            result_explanation = (
                "unit state changed but tile did not change; move may have been blocked, "
                "woke the unit, or consumed/changed movement state"
            )
        else:
            result = "not_observed"
            result_explanation = (
                "no unit state change was observed before the wait timeout; this is not "
                "proof that Freeciv rejected the order"
            )
        response = {
            "ok": moved,
            "player": self.name,
            "unit_id": unit_id,
            "from_tile": current_tile,
            "target_tile": target_tile,
            "packet": "PACKET_UNIT_ORDERS",
            "sent": True,
            "direction": direction,
            "direction_info": direction_info(
                direction,
                self.state.map_info.get("topology_id"),
            ),
            "before": PlayerState._brief_unit(before),
            "after": PlayerState._brief_unit(after) if after else None,
            "applied": moved,
            "reached_target": reached_target,
            "observed_changed": observed_changed,
            "result": result,
            "result_explanation": result_explanation,
            "actionability": actionability,
            "legality": precheck,
            "precheck_authority": "advisory only; command was still sent to Freeciv",
            "wait_seconds": wait,
            "recent_messages": recent_messages,
        }
        self._audit_command("move-unit", response)
        return response

    def _move_unit_argument_error(
        self,
        *,
        unit_id: int,
        current_tile: int,
        target_tile: int | None,
        direction: int | None,
        message: str,
    ) -> dict[str, Any]:
        response = {
            "ok": False,
            "player": self.name,
            "unit_id": unit_id,
            "from_tile": current_tile,
            "target_tile": target_tile,
            "packet": "PACKET_UNIT_ORDERS",
            "sent": False,
            "direction": direction,
            "direction_info": (
                direction_info(direction, self.state.map_info.get("topology_id"))
                if direction is not None
                else None
            ),
            "applied": False,
            "reached_target": False,
            "observed_changed": False,
            "result": "invalid_arguments",
            "result_explanation": message,
            "error": message,
            "precheck_authority": "harness rejected inconsistent move_unit arguments before sending",
            "wait_seconds": 0,
        }
        self._audit_command("move-unit", response)
        return response

    def unit_activity(
        self,
        *,
        unit_id: int,
        activity: str | int,
        target: str | int | None = None,
        wait: float = 5.0,
    ) -> dict[str, Any]:
        with self._lock:
            unit = self.state.units.get(unit_id)
            if unit is None or unit.get("owner") != self.state.player_no:
                raise RuntimeError(f"{self.name} does not own unit {unit_id}")
            before = self.state._enrich_unit(unit)
            activity_id = self._resolve_activity(activity)
            target_id = self._resolve_activity_target(activity_id, target)
            current_tile_id = before.get("tile")
            precheck_tile = (
                self._local_tile(int(current_tile_id), 0, 0)
                if current_tile_id is not None
                else None
            )
            precheck = self._unit_activity_legality_info(
                unit=before,
                activity_id=activity_id,
                target_id=target_id,
                tile=precheck_tile,
            )

        already_active = self._unit_has_activity(before, activity_id, target_id)
        if already_active:
            response_tile_id = before.get("tile")
            with self._lock:
                recent_messages = list(self.state.recent_messages[-5:])
                tile = (
                    self._local_tile(int(response_tile_id), 0, 0)
                    if response_tile_id is not None
                    else None
                )
            response = {
                "ok": True,
                "player": self.name,
                "unit_id": unit_id,
                "packet": "PACKET_UNIT_CHANGE_ACTIVITY",
                "sent": False,
                "activity": activity_id,
                "activity_info": self.state._activity_info(activity_id, target_id),
                "target": target_id,
                "target_info": self.state._extra_info(target_id),
                "before": PlayerState._brief_unit(before),
                "after": PlayerState._brief_unit(before),
                "applied": True,
                "observed_changed": False,
                "result": {
                    "estimate": "already_active",
                    "reason": (
                        "the unit was already doing the requested activity and target "
                        "before this command, so no packet was sent"
                    ),
                },
                "retry_policy": self._unit_activity_retry_policy("already_active"),
                "legality": precheck,
                "precheck_authority": "not sent because the requested activity was already active",
                "wait_seconds": 0,
                "tile": tile,
                "recent_messages": recent_messages,
            }
            self._audit_command("unit-activity", response)
            return response

        known_blockers = precheck.get("known_blockers", [])
        if known_blockers:
            response_tile_id = before.get("tile")
            with self._lock:
                recent_messages = list(self.state.recent_messages[-5:])
                tile = (
                    self._local_tile(int(response_tile_id), 0, 0)
                    if response_tile_id is not None
                    else None
                )
            response = {
                "ok": False,
                "player": self.name,
                "unit_id": unit_id,
                "packet": "PACKET_UNIT_CHANGE_ACTIVITY",
                "sent": False,
                "activity": activity_id,
                "activity_info": self.state._activity_info(activity_id, target_id),
                "target": target_id,
                "target_info": self.state._extra_info(target_id),
                "before": PlayerState._brief_unit(before),
                "after": PlayerState._brief_unit(before),
                "applied": False,
                "observed_changed": False,
                "result": {
                    "estimate": "not_sent_known_invalid",
                    "reason": " ".join(str(item) for item in known_blockers),
                },
                "retry_policy": self._unit_activity_retry_policy("not_sent_known_invalid"),
                "legality": precheck,
                "precheck_authority": "advisory precheck blocked sending the command",
                "wait_seconds": 0,
                "tile": tile,
                "recent_messages": recent_messages,
            }
            self._audit_command("unit-activity", response)
            return response

        self.client.send_unit_change_activity(
            unit_id=unit_id,
            activity=activity_id,
            target=target_id,
        )

        after = self._wait_for_unit_update(
            unit_id=unit_id,
            previous=before,
            wait=wait,
        )
        applied = bool(
            after
            and after.get("activity") == activity_id
            and (target_id < 0 or after.get("activity_tgt") == target_id)
        )
        observed_changed = bool(after and self._unit_changed(before, after))
        response_tile_id = None
        if after and after.get("tile") is not None:
            response_tile_id = int(after["tile"])
        elif before.get("tile") is not None:
            response_tile_id = int(before["tile"])
        with self._lock:
            recent_messages = list(self.state.recent_messages[-5:])
            tile = (
                self._local_tile(response_tile_id, 0, 0)
                if response_tile_id is not None
                else None
            )
        if applied:
            result_estimate = "confirmed_activity"
            result_reason = "requested activity and target were observed on the unit"
        elif observed_changed:
            result_estimate = "changed_without_requested_activity"
            result_reason = (
                "unit state changed, but the requested activity/target was not observed; "
                "Freeciv may have rejected, replaced, or interrupted the activity"
            )
        else:
            result_estimate = "sent_pending"
            result_reason = (
                "the activity packet was sent, but no matching unit activity update was "
                "observed before the wait timeout; this is not proof that Freeciv rejected "
                "the order, so treat it as pending for this turn"
            )
        advisory_notes = precheck.get("known_blockers", []) + precheck.get("warnings", [])
        if not applied and advisory_notes:
            result_reason = f"{result_reason}. Advisory checks: {' '.join(advisory_notes)}"
        response = {
            "ok": True,
            "player": self.name,
            "unit_id": unit_id,
            "packet": "PACKET_UNIT_CHANGE_ACTIVITY",
            "sent": True,
            "activity": activity_id,
            "activity_info": self.state._activity_info(activity_id, target_id),
            "target": target_id,
            "target_info": self.state._extra_info(target_id),
            "before": PlayerState._brief_unit(before),
            "after": PlayerState._brief_unit(after) if after else None,
            "applied": applied,
            "observed_changed": observed_changed,
            "result": {
                "estimate": result_estimate,
                "reason": result_reason,
            },
            "retry_policy": self._unit_activity_retry_policy(result_estimate),
            "legality": precheck,
            "precheck_authority": "advisory only; command was still sent to Freeciv",
            "wait_seconds": wait,
            "tile": tile,
            "recent_messages": recent_messages,
        }
        self._audit_command("unit-activity", response)
        return response

    def set_city_production(
        self,
        *,
        city_id: int,
        target: str | int,
        kind: str | int | None = None,
        wait: float = 1.0,
    ) -> dict[str, Any]:
        with self._lock:
            city = self.state.cities.get(city_id)
            if city is None or city.get("owner") != self.state.player_no:
                raise RuntimeError(f"{self.name} does not own city {city_id}")
            before = self.state._enrich_city(city)
            production_kind, production_value = self._resolve_production_target(target, kind)
            target_info = self._production_target_info(production_kind, production_value)
            legality = self.state._production_target_legality(
                city=before,
                kind_id=production_kind,
                value_id=production_value,
                item=self._production_target_ruleset_item(production_kind, production_value),
            )
            already_current = (
                before.get("production_kind") == production_kind
                and before.get("production_value") == production_value
            )

        if already_current:
            response = {
                "ok": True,
                "player": self.name,
                "city_id": city_id,
                "packet": "PACKET_CITY_CHANGE",
                "packet_sent": False,
                "production_kind": production_kind,
                "production_kind_name": UNIVERSAL_KIND_NAMES.get(
                    production_kind,
                    f"unknown universal kind {production_kind}",
                ),
                "production_value": production_value,
                "production": target_info,
                "before": PlayerState._brief_city(before),
                "after": PlayerState._brief_city(before),
                "applied": True,
                "observed_changed": False,
                "result": {
                    "estimate": "already_current",
                    "reason": "city is already producing the requested target; no packet was sent",
                },
                "legality": legality,
            }
            self._audit_command("set-city-production", response)
            return response

        if not legality.get("can_send", True):
            response = {
                "ok": False,
                "player": self.name,
                "city_id": city_id,
                "packet": "PACKET_CITY_CHANGE",
                "packet_sent": False,
                "production_kind": production_kind,
                "production_kind_name": UNIVERSAL_KIND_NAMES.get(
                    production_kind,
                    f"unknown universal kind {production_kind}",
                ),
                "production_value": production_value,
                "production": target_info,
                "before": PlayerState._brief_city(before),
                "after": PlayerState._brief_city(before),
                "applied": False,
                "observed_changed": False,
                "result": {
                    "estimate": "not_sent_known_invalid",
                    "reason": "; ".join(legality.get("known_blockers") or ["known production blocker"]),
                },
                "legality": legality,
            }
            self._audit_command("set-city-production", response)
            return response

        self.client.send_city_change(
            city_id=city_id,
            production_kind=production_kind,
            production_value=production_value,
        )

        after = self._wait_for_city_update(
            city_id=city_id,
            previous=before,
            wait=wait,
        )
        applied = bool(
            after
            and after.get("production_kind") == production_kind
            and after.get("production_value") == production_value
        )
        observed_changed = bool(after and self._city_changed(before, after))
        if applied:
            result_estimate = "confirmed_applied"
            result_reason = "Freeciv sent a city update with the requested production target"
            ok = True
        elif observed_changed:
            result_estimate = "changed_without_requested_production"
            result_reason = "city changed, but not to the requested production target"
            ok = False
        else:
            result_estimate = "rejected_or_not_buildable_or_unobserved"
            result_reason = (
                "Freeciv did not send an observed production change. The server silently "
                "ignores city production targets that can_city_build_now() rejects."
            )
            ok = False
        response = {
            "ok": ok,
            "player": self.name,
            "city_id": city_id,
            "packet": "PACKET_CITY_CHANGE",
            "packet_sent": True,
            "production_kind": production_kind,
            "production_kind_name": UNIVERSAL_KIND_NAMES.get(
                production_kind,
                f"unknown universal kind {production_kind}",
            ),
            "production_value": production_value,
            "production": target_info,
            "before": PlayerState._brief_city(before),
            "after": PlayerState._brief_city(after) if after else None,
            "applied": applied,
            "observed_changed": observed_changed,
            "result": {
                "estimate": result_estimate,
                "reason": result_reason,
            },
            "legality": legality,
            "recent_messages": self.state.recent_messages[-5:],
        }
        self._audit_command("set-city-production", response)
        return response

    def set_rates(
        self,
        *,
        tax: int,
        luxury: int,
        science: int,
        wait: float = 1.0,
    ) -> dict[str, Any]:
        rates = {"tax": tax, "luxury": luxury, "science": science}
        for name, value in rates.items():
            if value < 0 or value > 100:
                raise RuntimeError(f"{name} must be between 0 and 100")
        if tax + luxury + science != 100:
            raise RuntimeError("tax + luxury + science must equal 100")
        with self._lock:
            before = dict(self.state.player_info)

        self.client.send_player_rates(tax=tax, luxury=luxury, science=science)
        after = self._wait_for_player_info(
            previous=before,
            wait=wait,
            predicate=lambda info: all(
                self._normalize_rates(info).get(key) == value
                for key, value in rates.items()
            ),
            return_on_change=False,
        )
        normalized_after = self._normalize_rates(after or {})
        applied = bool(after and all(normalized_after.get(key) == value for key, value in rates.items()))
        return {
            "ok": applied,
            "player": self.name,
            "packet": "PACKET_PLAYER_RATES",
            "requested": rates,
            "before": compact_packet(before, ["gold", "tax", "luxury", "science"]),
            "after": compact_packet(normalized_after, ["gold", "tax", "luxury", "science"]),
            "applied": applied,
        }

    def set_research(
        self,
        *,
        tech: str | int,
        wait: float = 1.0,
    ) -> dict[str, Any]:
        with self._lock:
            before = self.state._research_view()
            tech_id = self._resolve_tech(tech)
            tech_info = self.state._tech_info(tech_id, self.state._own_research())

        self.client.send_player_research(tech=tech_id)
        after = self._wait_for_research(
            previous=before,
            wait=wait,
            predicate=lambda research: research.get("researching") == tech_id,
            return_on_change=False,
        )
        applied = bool(after and after.get("researching") == tech_id)
        return {
            "ok": applied,
            "player": self.name,
            "packet": "PACKET_PLAYER_RESEARCH",
            "tech": tech_info,
            "before": before,
            "after": self.state._research_view(),
            "applied": applied,
        }

    def set_tech_goal(
        self,
        *,
        tech: str | int,
        wait: float = 1.0,
    ) -> dict[str, Any]:
        with self._lock:
            before = self.state._research_view()
            tech_id = self._resolve_tech(tech)
            tech_info = self.state._tech_info(tech_id, self.state._own_research())

        self.client.send_player_tech_goal(tech=tech_id)
        after = self._wait_for_research(
            previous=before,
            wait=wait,
            predicate=lambda research: research.get("tech_goal") == tech_id,
            return_on_change=False,
        )
        applied = bool(after and after.get("tech_goal") == tech_id)
        return {
            "ok": applied,
            "player": self.name,
            "packet": "PACKET_PLAYER_TECH_GOAL",
            "tech": tech_info,
            "before": before,
            "after": self.state._research_view(),
            "applied": applied,
        }

    def query_actions(
        self,
        *,
        unit_id: int,
        target_tile: int | None = None,
        dx: int = 0,
        dy: int = 0,
        timeout: float = 2.0,
    ) -> dict[str, Any]:
        with self._actions_condition:
            unit = self.state.units.get(unit_id)
            if unit is None or unit.get("owner") != self.state.player_no:
                raise RuntimeError(f"{self.name} does not own unit {unit_id}")
            current_tile = unit.get("tile")
            if current_tile is None:
                raise RuntimeError(f"{self.name} unit {unit_id} has no known tile")
            if target_tile is None:
                target_tile = self._relative_tile(int(current_tile), dx, dy)
            self._latest_actions = None

        self.client.send_unit_get_actions(
            actor_unit_id=unit_id,
            target_tile_id=target_tile,
            target_unit_id=0,
            target_extra_id=-1,
            request_kind=0,
        )

        deadline = time.monotonic() + timeout
        with self._actions_condition:
            while time.monotonic() < deadline:
                if (
                    self._latest_actions is not None
                    and self._latest_actions.get("actor_unit_id") == unit_id
                    and self._latest_actions.get("target_tile_id") == target_tile
                ):
                    actions = dict(self._latest_actions)
                    actions["possible_actions"] = self._possible_actions(actions)
                    return actions
                self._actions_condition.wait(deadline - time.monotonic())
        raise TimeoutError(f"timed out waiting for actions for unit {unit_id}")

    def _wait_for_found_city_update(
        self,
        *,
        unit_id: int,
        target_tile: int,
        before_city_ids: set[int],
        wait: float,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        deadline = time.monotonic() + wait
        with self._state_condition:
            while True:
                founded_city: dict[str, Any] | None = None
                for city_id, city in self.state.cities.items():
                    if city_id in before_city_ids:
                        continue
                    if city.get("owner") == self.state.player_no and city.get("tile") == target_tile:
                        founded_city = self.state._enrich_city(city)
                        break
                current_unit = self.state.units.get(unit_id)
                after_unit = self.state._enrich_unit(current_unit) if current_unit else None
                if founded_city is not None:
                    return founded_city, after_unit
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None, after_unit
                self._state_condition.wait(remaining)

    @staticmethod
    def _action_probability(actions: dict[str, Any], action_id: int) -> dict[str, Any]:
        probabilities = actions.get("action_probabilities") or []
        if 0 <= action_id < len(probabilities) and isinstance(probabilities[action_id], dict):
            probability = dict(probabilities[action_id])
        else:
            probability = {"min": 0, "max": 0}
        probability["action_id"] = action_id
        probability["action_name"] = ACTION_NAMES.get(action_id, f"unknown action {action_id}")
        probability["possible"] = ManagedAgent._action_probability_possible(probability)
        return probability

    @staticmethod
    def _action_probability_possible(probability: dict[str, Any]) -> bool:
        try:
            return int(probability.get("max", 0)) > 0
        except (TypeError, ValueError):
            return False

    def _possible_actions(self, actions: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        probabilities = actions.get("action_probabilities") or []
        for action_id, probability in enumerate(probabilities):
            if not isinstance(probability, dict):
                continue
            if not self._action_probability_possible(probability):
                continue
            result.append(
                {
                    "id": action_id,
                    "name": ACTION_NAMES.get(action_id, f"unknown action {action_id}"),
                    "probability": {
                        "min": probability.get("min"),
                        "max": probability.get("max"),
                    },
                }
            )
        return result

    def do_action(
        self,
        *,
        unit_id: int,
        target_id: int,
        action: str | int,
        sub_target: int = -1,
        name: str = "",
        wait: float = 1.0,
    ) -> dict[str, Any]:
        action_id = self._resolve_action(action)
        if action_id == 27 and sub_target == -1:
            sub_target = 0
        with self._lock:
            unit = self.state.units.get(unit_id)
            if unit is None or unit.get("owner") != self.state.player_no:
                raise RuntimeError(f"{self.name} does not own unit {unit_id}")
            before = self.state._enrich_unit(unit)

        self.client.send_unit_do_action(
            actor_id=unit_id,
            target_id=target_id,
            sub_tgt_id=sub_target,
            name=name,
            action_type=action_id,
        )
        after = self._wait_for_unit_update(unit_id=unit_id, previous=before, wait=wait)

        applied = bool(after and self._unit_changed(before, after))
        response = {
            "ok": applied,
            "player": self.name,
            "packet": "PACKET_UNIT_DO_ACTION",
            "sent": True,
            "unit_id": unit_id,
            "target_id": target_id,
            "sub_target": sub_target,
            "action": {
                "id": action_id,
                "name": ACTION_NAMES.get(action_id, f"unknown action {action_id}"),
            },
            "before": PlayerState._brief_unit(before),
            "after": PlayerState._brief_unit(after) if after else None,
            "applied": applied,
        }
        self._audit_command("do-action", response)
        return response

    def send_raw(self, packet: dict[str, Any]) -> dict[str, Any]:
        self.client.send_packet(packet)
        response = {"ok": True, "player": self.name, "sent": packet}
        self._audit_command("packet", response)
        return response

    def _audit_command(self, command: str, response: dict[str, Any]) -> None:
        entry = {
            "ts": time.time(),
            "player": self.name,
            "command": command,
            "response": response,
        }
        try:
            COMMAND_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with COMMAND_AUDIT_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
        except OSError as exc:
            with self._lock:
                self.state.last_error = f"command audit write failed: {exc}"

    def _wait_for_unit_observation(
        self,
        *,
        unit_id: int,
        previous: dict[str, Any],
        target_tile: int,
        wait: float,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + wait
        with self._state_condition:
            while True:
                current = self.state.units.get(unit_id)
                enriched = self.state._enrich_unit(current) if current else None
                if enriched and enriched.get("tile") == target_tile:
                    return enriched
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return enriched
                self._state_condition.wait(remaining)

    def _wait_for_unit_update(
        self,
        *,
        unit_id: int,
        previous: dict[str, Any],
        wait: float,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + wait
        with self._state_condition:
            while True:
                current = self.state.units.get(unit_id)
                enriched = self.state._enrich_unit(current) if current else None
                if enriched and self._unit_changed(previous, enriched):
                    return enriched
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return enriched
                self._state_condition.wait(remaining)

    def _wait_for_city_update(
        self,
        *,
        city_id: int,
        previous: dict[str, Any],
        wait: float,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + wait
        with self._state_condition:
            while True:
                current = self.state.cities.get(city_id)
                enriched = self.state._enrich_city(current) if current else None
                if enriched and self._city_changed(previous, enriched):
                    return enriched
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return enriched
                self._state_condition.wait(remaining)

    def _wait_for_player_info(
        self,
        *,
        previous: dict[str, Any],
        wait: float,
        predicate: Any,
        return_on_change: bool = True,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + wait
        with self._state_condition:
            while True:
                current = dict(self.state.player_info)
                if current and (predicate(current) or (return_on_change and current != previous)):
                    return current
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return current if current else None
                self._state_condition.wait(remaining)

    def _wait_for_phase_done(
        self,
        *,
        previous: dict[str, Any],
        phase_before: dict[str, Any],
        wait: float,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        deadline = time.monotonic() + wait
        with self._state_condition:
            while True:
                current = dict(self.state.player_info)
                phase = self.state._phase_view()
                phase_advanced = (
                    phase_before.get("agent_is_active_phase") is True
                    and phase.get("agent_is_active_phase") is False
                )
                if current.get("phase_done") is True or phase_advanced:
                    return current, phase
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return (current if current else None), phase
                self._state_condition.wait(remaining)

    def _wait_for_research(
        self,
        *,
        previous: dict[str, Any] | None,
        wait: float,
        predicate: Any,
        return_on_change: bool = True,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + wait
        with self._state_condition:
            while True:
                research = self.state._own_research()
                current = dict(research) if research else None
                if current and (
                    predicate(current)
                    or (return_on_change and self.state._research_view() != previous)
                ):
                    return current
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return current
                self._state_condition.wait(remaining)

    @staticmethod
    def _unit_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
        return any(
            before.get(key) != after.get(key)
            for key in ("tile", "movesleft", "hp", "activity", "activity_tgt")
        )

    @staticmethod
    def _unit_has_activity(unit: dict[str, Any], activity_id: int, target_id: int) -> bool:
        try:
            unit_activity = int(unit.get("activity"))
        except (TypeError, ValueError):
            return False
        if unit_activity != activity_id:
            return False
        if target_id < 0:
            return True
        try:
            unit_target = int(unit.get("activity_tgt"))
        except (TypeError, ValueError):
            return False
        return unit_target == target_id

    @staticmethod
    def _unit_activity_retry_policy(result_estimate: str) -> dict[str, Any]:
        if result_estimate == "not_sent_known_invalid":
            return {
                "repeat_same_order_this_turn": False,
                "next_step": (
                    "choose a different action or inspect the tile/unit; the harness "
                    "found a known blocker before sending"
                ),
            }
        if result_estimate == "sent_pending":
            return {
                "repeat_same_order_this_turn": False,
                "next_step": (
                    "treat this order as pending for this turn; inspect another unit, "
                    "choose a different action, or end phase unless later state/messages "
                    "prove failure"
                ),
            }
        if result_estimate == "changed_without_requested_activity":
            return {
                "repeat_same_order_this_turn": False,
                "next_step": (
                    "do not immediately repeat the same order; inspect current state, "
                    "messages, and tile facts before choosing a different command"
                ),
            }
        return {
            "repeat_same_order_this_turn": False,
            "next_step": "the requested activity is already active or confirmed; act elsewhere or end phase",
        }

    @staticmethod
    def _city_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
        return any(
            before.get(key) != after.get(key)
            for key in (
                "size",
                "food_stock",
                "shield_stock",
                "production_kind",
                "production_value",
            )
        )

    def _resolve_activity(self, activity: str | int) -> int:
        if isinstance(activity, int):
            return activity
        text = activity.strip().lower()
        if text.isdigit():
            return int(text)
        try:
            return ACTIVITY_IDS[text]
        except KeyError as exc:
            raise RuntimeError(f"unknown activity {activity!r}") from exc

    def _resolve_action(self, action: str | int) -> int:
        if isinstance(action, int):
            return action
        text = str(action).strip().lower()
        if text.isdigit():
            return int(text)
        normalized = text.replace(" ", "-")
        try:
            return ACTION_IDS[normalized]
        except KeyError as exc:
            raise RuntimeError(f"unknown action {action!r}") from exc

    def _resolve_activity_target(self, activity: int, target: str | int | None) -> int:
        if isinstance(target, int):
            return target
        if target is None:
            target = DEFAULT_ACTIVITY_TARGETS.get(activity)
        if target is None or target == "":
            return -1
        if isinstance(target, (tuple, list)):
            last_error: RuntimeError | None = None
            for candidate in target:
                try:
                    return self._resolve_activity_target(activity, candidate)
                except RuntimeError as exc:
                    last_error = exc
            if last_error is not None:
                raise last_error
        text = str(target).strip().lower()
        if text.lstrip("-").isdigit():
            return int(text)
        for extra_id, extra in self.state.extras.items():
            names = (
                str(extra.get("name", "")).lower(),
                str(extra.get("rule_name", "")).lower(),
            )
            if text in names:
                return extra_id
        raise RuntimeError(f"unknown extra target {target!r}")

    def _unit_activity_legality_info(
        self,
        *,
        unit: dict[str, Any],
        activity_id: int,
        target_id: int,
        tile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        activity_name = ACTIVITY_NAMES.get(activity_id, f"unknown activity {activity_id}")
        target_info = self.state._extra_info(target_id)
        facts: dict[str, Any] = {
            "activity": self.state._activity_info(activity_id, target_id),
            "target_required": activity_id in ACTIVITIES_REQUIRING_TARGET,
            "unit": {
                "id": unit.get("id"),
                "movesleft": unit.get("movesleft"),
                "activity": self.state._activity_info(
                    unit.get("activity", 0),
                    unit.get("activity_tgt", -1),
                ),
            },
        }
        warnings: list[str] = []
        known_blockers: list[str] = []

        if tile is not None:
            facts["tile"] = {
                "tile": tile.get("tile"),
                "known": tile.get("known"),
                "owner_info": tile.get("owner_info"),
                "extras_owner_info": tile.get("extras_owner_info"),
                "terrain_info": tile.get("terrain_info"),
                "resource_info": tile.get("resource_info"),
                "extras_info": tile.get("extras_info"),
                "placing_info": tile.get("placing_info"),
            }
            present_extra_ids = {
                int(extra["id"])
                for extra in tile.get("extras_info", [])
                if isinstance(extra, dict) and extra.get("id") is not None
            }
            if target_id in present_extra_ids:
                known_blockers.append(
                    f"{activity_name} target {target_info.get('name') if target_info else target_id} "
                    "is already present on this tile."
                )
            placing_info = tile.get("placing_info")
            if isinstance(placing_info, dict) and placing_info.get("id") == target_id:
                warnings.append(
                    f"{activity_name} target {placing_info.get('name')} is already being built on this tile."
                )
            owner_relation = tile.get("owner_info", {}).get("relation")
            if owner_relation == "unowned" and activity_id in WORKER_IMPROVEMENT_ACTIVITIES:
                warnings.append(
                    f"{activity_name} is a worker improvement on an unowned tile; "
                    "some Freeciv rulesets reject improvements outside borders or away from cities."
                )
            terrain_info = tile.get("terrain_info")
            time_field = ACTIVITY_TERRAIN_TIME_FIELDS.get(activity_id)
            if isinstance(terrain_info, dict) and time_field:
                terrain_time = terrain_info.get(time_field)
                facts["terrain_activity_time_field"] = {
                    "field": time_field,
                    "value": terrain_time,
                }
                if isinstance(terrain_time, (int, float)) and terrain_time <= 0:
                    warnings.append(
                        f"{activity_name} has {time_field}={terrain_time} on this terrain; "
                        "Freeciv may reject or ignore this worker activity here."
                    )
        else:
            warnings.append("The unit's current tile is not known, so local activity legality could not be checked.")

        if activity_id in ACTIVITIES_REQUIRING_TARGET and target_id < 0:
            known_blockers.append(
                f"{activity_name} normally requires a target extra such as Road, Mine, or Irrigation."
            )
        if target_info is not None:
            facts["target"] = target_info
            if target_info.get("known") is False:
                warnings.append(
                    f"The target extra id {target_id} is not decoded in the current ruleset data."
                )
            if target_info.get("buildable") is False and activity_id in WORKER_IMPROVEMENT_ACTIVITIES:
                warnings.append(
                    f"Target extra {target_info.get('name')} is marked buildable=false in the ruleset."
                )
        elif target_id >= 0:
            warnings.append(f"The target extra id {target_id} could not be decoded.")

        movesleft = unit.get("movesleft")
        if isinstance(movesleft, (int, float)) and movesleft <= 0 and activity_id != 0:
            warnings.append(
                "The unit has no movement points left; Freeciv may not start a new activity until a later turn."
            )

        if known_blockers:
            estimate = "likely_invalid"
        elif warnings:
            estimate = "uncertain"
        else:
            estimate = "no_known_problem"

        return {
            "authority": "advisory only; Freeciv is authoritative after the command is sent",
            "estimate": estimate,
            "known_blockers": known_blockers,
            "warnings": warnings,
            "facts": facts,
        }

    def _resolve_production_target(
        self,
        target: str | int,
        kind: str | int | None,
    ) -> tuple[int, int]:
        kind_id = self._resolve_production_kind(kind)
        if isinstance(target, int):
            return kind_id, target
        text = str(target).strip().lower()
        if text.isdigit():
            return kind_id, int(text)
        if kind_id == 6:
            for unit_type_id, unit_type in self.state.unit_types.items():
                names = (
                    str(unit_type.get("name", "")).lower(),
                    str(unit_type.get("rule_name", "")).lower(),
                )
                if text in names:
                    return kind_id, unit_type_id
            raise RuntimeError(
                f"unknown unit production target {target!r}; "
                "run `bin/game production-targets` and use an exact unit target; "
                f"known unit production targets include {self._known_unit_type_names()}"
            )
        if kind_id == 3:
            for building_id, building in self.state.buildings.items():
                names = (
                    str(building.get("name", "")).lower(),
                    str(building.get("rule_name", "")).lower(),
                )
                if text in names:
                    return kind_id, building_id
            raise RuntimeError(
                f"unknown building production target {target!r}; "
                "run `bin/game production-targets` and use an exact building target; "
                f"known building production targets include {self._known_building_names()}"
            )
        raise RuntimeError(
            f"production kind {kind_id} ({UNIVERSAL_KIND_NAMES.get(kind_id, 'unknown')}) "
            "is not supported by this command yet"
        )

    def _known_unit_type_names(self) -> str:
        return self._format_known_names(self.state.unit_types.values())

    def _known_building_names(self) -> str:
        return self._format_known_names(self.state.buildings.values())

    @staticmethod
    def _format_known_names(items: Any) -> str:
        names: list[str] = []
        seen: set[str] = set()
        for item in items:
            for key in ("rule_name", "name"):
                value = item.get(key) if isinstance(item, dict) else None
                if not value or str(value).startswith("?"):
                    continue
                text = display_label(value) or str(value)
                if text not in seen:
                    seen.add(text)
                    names.append(text)
        return ", ".join(names) if names else "none decoded"

    def _resolve_tech(self, tech: str | int) -> int:
        if isinstance(tech, int):
            return tech
        text = str(tech).strip().lower()
        if text.isdigit():
            return int(text)
        research = self.state._own_research()
        for tech_id, tech_info in self.state.techs.items():
            names = (
                str(tech_info.get("name", "")).lower(),
                str(tech_info.get("rule_name", "")).lower(),
            )
            if text in names:
                return tech_id
        if text in {"none", "a_none"}:
            return 0
        if text in {"future", "future tech", "future-tech", "a_future"}:
            return A_FUTURE
        if text in {"unset", "choose", "no research", "none selected", "a_unset"}:
            return A_UNSET
        raise RuntimeError(f"unknown tech {tech!r}")

    @staticmethod
    def _normalize_rates(info: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(info)
        for key in ("tax", "luxury", "science"):
            normalized.setdefault(key, 0)
        return normalized

    def _resolve_production_kind(self, kind: str | int | None) -> int:
        if kind is None:
            return 6
        if isinstance(kind, int):
            return kind
        text = str(kind).strip().lower()
        if text.isdigit():
            return int(text)
        if text in {"unit", "unittype", "unit_type", "units"}:
            return 6
        if text in {"building", "improvement", "improvements"}:
            return 3
        for kind_id, name in UNIVERSAL_KIND_NAMES.items():
            if text == name.lower():
                return kind_id
        raise RuntimeError(f"unknown production kind {kind!r}")

    def _production_target_info(self, kind_id: int, value_id: int) -> dict[str, Any]:
        return {
            "kind_id": kind_id,
            "kind": UNIVERSAL_KIND_NAMES.get(kind_id, f"unknown universal kind {kind_id}"),
            "value_id": value_id,
            **(
                self.state._production_info(
                    {
                        "production_kind": kind_id,
                        "production_value": value_id,
                    }
                )
                or {}
            ),
        }

    def _production_target_ruleset_item(self, kind_id: int, value_id: int) -> dict[str, Any]:
        if kind_id == 6:
            return self.state.unit_types.get(value_id, {})
        if kind_id == 3:
            return self.state.buildings.get(value_id, {})
        return {}

    def _resolve_center_tile(
        self,
        *,
        unit_id: int | None,
        city_id: int | None,
        tile_id: int | None,
    ) -> int:
        selectors = [value is not None for value in (unit_id, city_id, tile_id)]
        if sum(selectors) != 1:
            raise RuntimeError("provide exactly one of unit_id, city_id, or tile_id")
        if unit_id is not None:
            unit = self.state.units.get(unit_id)
            if unit is None or unit.get("owner") != self.state.player_no:
                raise RuntimeError(f"{self.name} does not own unit {unit_id}")
            if unit.get("tile") is None:
                raise RuntimeError(f"{self.name} unit {unit_id} has no known tile")
            return int(unit["tile"])
        if city_id is not None:
            city = self.state.cities.get(city_id)
            if city is None or city.get("owner") != self.state.player_no:
                raise RuntimeError(f"{self.name} does not own city {city_id}")
            if city.get("tile") is None:
                raise RuntimeError(f"{self.name} city {city_id} has no known tile")
            return int(city["tile"])
        if tile_id is None:
            raise AssertionError("tile_id unexpectedly absent")
        return tile_id

    def _local_tile(self, tile_id: int, dx: int, dy: int) -> dict[str, Any]:
        tile = self.state.tiles.get(tile_id, {})
        result: dict[str, Any] = {
            "tile": tile_id,
            "dx": dx,
            "dy": dy,
            "known": bool(tile),
        }
        result.update(
            compact_packet(
                tile,
                [
                    "terrain",
                    "resource",
                    "owner",
                    "extras_owner",
                    "extras",
                    "placing",
                    "place_turn",
                    "worked",
                    "label",
                    "spec_sprite",
                ],
            )
        )
        if "owner" in tile:
            result["owner_info"] = self.state._owner_info(tile.get("owner"))
        if "extras_owner" in tile:
            result["extras_owner_info"] = self.state._owner_info(tile.get("extras_owner"))
        terrain = self.state.terrains.get(int(tile["terrain"])) if "terrain" in tile else None
        if terrain is not None:
            result["terrain_name"] = terrain.get("name")
            result["terrain_rule_name"] = terrain.get("rule_name")
            result["movement_cost"] = terrain.get("movement_cost")
            result["defense_bonus"] = terrain.get("defense_bonus")
            result["terrain_info"] = self.state._terrain_info(tile["terrain"])
        elif "terrain" in tile:
            result["terrain_info"] = self.state._terrain_info(tile["terrain"])
        resource = self.state.extras.get(int(tile["resource"])) if "resource" in tile else None
        if resource is not None:
            result["resource_name"] = resource.get("name")
            result["resource_rule_name"] = resource.get("rule_name")
            result["resource_info"] = self.state._extra_info(tile["resource"])
        elif "resource" in tile and self.state._extra_info(tile["resource"]) is not None:
            result["resource_info"] = self.state._extra_info(tile["resource"])
        if "extras" in tile:
            result["extras_ids"] = self.state._extra_ids_from_bitvector(tile.get("extras"))
            result["extras_info"] = self.state._extras_info(tile.get("extras"))
        placing_info = self.state._extra_info(tile.get("placing")) if "placing" in tile else None
        if placing_info is not None:
            result["placing_info"] = placing_info
        units = [
            PlayerState._brief_unit(self.state._enrich_unit(unit))
            for unit in self.state.units.values()
            if unit.get("tile") == tile_id
        ]
        cities = [
            PlayerState._brief_city(self.state._enrich_city(city))
            for city in self.state.cities.values()
            if city.get("tile") == tile_id
        ]
        if units:
            result["units"] = units
        if cities:
            result["cities"] = cities
        return result

    def _render_ascii_view(
        self,
        view: dict[str, Any],
        *,
        unit_id: int | None,
        city_id: int | None,
        tile_id: int | None,
    ) -> str:
        radius = int(view["radius"])
        center_map = view["center_map"]
        tiles_by_delta = self._tiles_by_delta(view["tiles"])
        selector = "tile"
        selector_id = view["center_tile"]
        if unit_id is not None:
            selector = "unit"
            selector_id = unit_id
        elif city_id is not None:
            selector = "city"
            selector_id = city_id
        elif tile_id is not None:
            selector = "tile"
            selector_id = tile_id

        lines = [
            "freeciv-agent-ascii-view-v2",
            (
                f"player={self.name} turn={view['turn']} year={view['year']} "
                f"center={selector}:{selector_id} tile={view['center_tile']} "
                f"map=({center_map['x']},{center_map['y']}) radius={radius} "
                f"topology={topology_info(self.state.map_info)['name']} "
                f"topology_id={self.state.map_info.get('topology_id')}"
            ),
            "cell=terrain+marker; dx/dy are relative to center",
            (
                "terrain: ? unknown, ~=water, a=arctic, d=desert, f=forest, "
                "g=grassland, h=hills, j=jungle, m=mountains, p=plains, "
                "s=swamp, t=tundra"
            ),
            (
                "marker: .=none, uppercase=own unit, lowercase=other unit, "
                "@=own city, &=other city, *=multiple visible entities"
            ),
        ]

        topology_id = self.state.map_info.get("topology_id", 0)
        if bool(topology_id & 1) and bool(topology_id & 2):
            render_tiles = self._render_iso_hex_ascii_grid(lines, tiles_by_delta, radius)
        else:
            render_tiles = self._render_square_ascii_grid(lines, tiles_by_delta, radius)

        notable_lines = self._ascii_notable_lines(render_tiles)
        if notable_lines:
            lines.extend(["", "details:"])
            lines.extend(notable_lines)
        return "\n".join(lines)

    @staticmethod
    def _tiles_by_delta(tiles: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
        return {
            (int(tile["dx"]), int(tile["dy"])): tile
            for tile in tiles
        }

    def _render_iso_hex_ascii_grid(
        self,
        lines: list[str],
        tiles_by_delta: dict[tuple[int, int], dict[str, Any]],
        radius: int,
    ) -> list[dict[str, Any]]:
        lines.extend(
            [
                (
                    "layout=iso-hex; hex_distance=(abs(dx)+abs(dy)+"
                    "abs(dx-dy))/2; omitted cells are outside hex radius"
                ),
                (
                    "valid neighbor directions: 0 northwest(-1,-1), "
                    "1 north(+0,-1), 3 west(-1,+0), 4 east(+1,+0), "
                    "6 south(+0,+1), 7 southeast(+1,+1)"
                ),
                "",
                "center-neighbors:",
            ]
        )
        neighbor_specs = [
            ("northwest", -1, -1),
            ("north", 0, -1),
            ("west", -1, 0),
            ("center", 0, 0),
            ("east", 1, 0),
            ("south", 0, 1),
            ("southeast", 1, 1),
        ]
        for name, dx, dy in neighbor_specs:
            tile = tiles_by_delta.get((dx, dy))
            lines.append(
                f"  {name:<9} dx={dx:+d} dy={dy:+d} {self._ascii_cell(tile)} "
                f"tile={tile.get('tile') if tile else 'outside'}"
            )

        lines.extend(["", "hex-grid:"])
        render_tiles = []
        for dy in range(-radius, radius + 1):
            row_tiles = []
            for dx in range(-radius, radius + 1):
                if self._iso_hex_distance(dx, dy) <= radius:
                    tile = tiles_by_delta.get((dx, dy))
                    row_tiles.append((dx, tile))
                    if tile is not None:
                        render_tiles.append(tile)
            if not row_tiles:
                continue
            min_dx = row_tiles[0][0]
            max_dx = row_tiles[-1][0]
            indent = " " * ((min_dx + radius) * 2)
            cells = "  ".join(self._ascii_cell(tile) for _dx, tile in row_tiles)
            lines.append(f"dy={dy:+d} dx={min_dx:+d}..{max_dx:+d} {indent}{cells}")
        return render_tiles

    def _render_square_ascii_grid(
        self,
        lines: list[str],
        tiles_by_delta: dict[tuple[int, int], dict[str, Any]],
        radius: int,
    ) -> list[dict[str, Any]]:
        lines.extend(
            [
                "layout=square-or-unknown-topology; rows=dy; columns=dx",
                "",
                "      " + " ".join(f"{dx:+2d}" for dx in range(-radius, radius + 1)),
            ]
        )
        render_tiles = []
        for dy in range(-radius, radius + 1):
            row = [f"{dy:+3d} "]
            for dx in range(-radius, radius + 1):
                tile = tiles_by_delta.get((dx, dy))
                if tile is not None:
                    render_tiles.append(tile)
                row.append(self._ascii_cell(tile))
            lines.append(" ".join(row))
        return render_tiles

    @staticmethod
    def _iso_hex_distance(dx: int, dy: int) -> int:
        return (abs(dx) + abs(dy) + abs(dx - dy)) // 2

    def _ascii_cell(self, tile: dict[str, Any] | None) -> str:
        if tile is None or not tile.get("known"):
            return "??"
        terrain = TERRAIN_ASCII.get(str(tile.get("terrain_rule_name")), "?")
        marker = self._ascii_marker(tile)
        return f"{terrain}{marker}"

    def _ascii_marker(self, tile: dict[str, Any]) -> str:
        units = tile.get("units", [])
        cities = tile.get("cities", [])
        if len(units) + len(cities) > 1:
            return "*"
        if cities:
            return "@" if tile.get("owner") == self.state.player_no else "&"
        if units:
            return self._ascii_unit_marker(units[0])
        return "."

    def _ascii_unit_marker(self, unit: dict[str, Any]) -> str:
        rule_name = str(unit.get("type_rule_name") or unit.get("type_name") or "Unit")
        marker = next((char for char in rule_name if char.isalpha()), "U")
        if unit.get("owner") == self.state.player_no:
            return marker.upper()
        return marker.lower()

    def _ascii_notable_lines(self, tiles: list[dict[str, Any]]) -> list[str]:
        lines = []
        for tile in sorted(tiles, key=lambda item: (item["dy"], item["dx"], item["tile"])):
            if not tile.get("known"):
                continue
            notable = (
                tile.get("units")
                or tile.get("cities")
                or tile.get("resource_name")
                or tile.get("owner") == self.state.player_no
            )
            if not notable:
                continue
            map_x, map_y = self._index_to_map_pos(int(tile["tile"]))
            parts = [
                f"dx={tile['dx']:+d}",
                f"dy={tile['dy']:+d}",
                f"tile={tile['tile']}",
                f"map=({map_x},{map_y})",
                f"terrain={tile.get('terrain_rule_name', 'unknown')}",
            ]
            if "resource_name" in tile:
                parts.append(f"resource={tile['resource_name']}")
            if tile.get("owner") == self.state.player_no:
                parts.append("owner=self")
            elif tile.get("owner") not in (None, 65535):
                parts.append(f"owner={tile['owner']}")
            if tile.get("cities"):
                parts.append(
                    "cities=["
                    + ", ".join(
                        f"{city.get('name')}#{city.get('id')}"
                        for city in tile["cities"]
                    )
                    + "]"
                )
            if tile.get("units"):
                parts.append(
                    "units=["
                    + ", ".join(self._ascii_unit_detail(unit) for unit in tile["units"])
                    + "]"
                )
            lines.append("  " + " ".join(parts))
        return lines

    def _ascii_unit_detail(self, unit: dict[str, Any]) -> str:
        owner = "self" if unit.get("owner") == self.state.player_no else str(unit.get("owner"))
        type_name = unit.get("type_rule_name") or unit.get("type_name") or "Unit"
        return (
            f"{type_name}#{unit.get('id')} owner={owner} "
            f"hp={unit.get('hp')} moves={unit.get('movesleft')}"
        )

    def _relative_tile(self, tile: int, dx: int, dy: int) -> int:
        map_x, map_y = self._index_to_map_pos(tile)
        target_tile = self._map_pos_to_index(map_x + dx, map_y + dy)
        if target_tile is None:
            raise RuntimeError(
                f"target map position {map_x + dx},{map_y + dy} is outside the map"
            )
        return target_tile

    def _direction_to_target(self, src_tile: int, target_tile: int) -> int:
        for direction in self._valid_directions():
            if self._step_tile(src_tile, direction) == target_tile:
                return direction
        topology_id = self.state.map_info.get("topology_id")
        raise RuntimeError(
            f"target tile {target_tile} is not adjacent to {src_tile} on "
            f"topology_id {topology_id} ({topology_info(self.state.map_info)['name']}); "
            f"valid directions are {format_valid_directions(topology_id)}"
        )

    def _step_tile(self, tile: int, direction: int) -> int | None:
        if direction not in self._valid_directions():
            topology_id = self.state.map_info.get("topology_id")
            direction_name = DIRECTION_NAMES.get(direction, f"unknown direction {direction}")
            raise RuntimeError(
                f"direction {direction} ({direction_name}) is not valid for "
                f"topology_id {topology_id} ({topology_info(self.state.map_info)['name']}); "
                f"valid directions are {format_valid_directions(topology_id)}"
            )
        dx, dy = self._direction_delta(direction)
        map_x, map_y = self._index_to_map_pos(tile)
        return self._map_pos_to_index(map_x + dx, map_y + dy)

    def _direction_delta(self, direction: int) -> tuple[int, int]:
        try:
            return DIRECTION_DELTAS[direction]
        except KeyError as exc:
            raise RuntimeError(
                f"direction {direction} is outside 0..7; known directions are "
                + ", ".join(
                    f"{item}:{name}"
                    for item, name in DIRECTION_NAMES.items()
                )
            ) from exc

    def _valid_directions(self) -> list[int]:
        return valid_direction_ids(self.state.map_info.get("topology_id"))

    def _can_unit_enter_known_tile(
        self,
        unit: dict[str, Any],
        tile: dict[str, Any],
    ) -> bool | None:
        if not tile.get("known"):
            return None
        terrain = tile.get("terrain_rule_name")
        if terrain is None:
            return None
        unit_type = self.state.unit_types.get(int(unit["type"])) if "type" in unit else None
        unit_class_id = unit_type.get("unit_class_id") if unit_type else None
        is_land_unit = unit_class_id not in (5, 6)
        if is_land_unit and terrain in WATER_TERRAINS:
            return False
        return True

    def _enterability_info(self, can_enter: bool | None, tile: dict[str, Any]) -> dict[str, Any]:
        if can_enter is True:
            return {
                "can_enter": True,
                "reason": "known tile appears enterable by this unit",
            }
        if can_enter is None:
            return {
                "can_enter": None,
                "reason": "tile is unknown or lacks enough terrain data",
            }
        terrain = tile.get("terrain_rule_name") or "unknown terrain"
        return {
            "can_enter": False,
            "reason": f"land unit cannot enter {terrain}",
        }

    def _movement_legality_info(
        self,
        *,
        unit: dict[str, Any],
        tile: dict[str, Any],
        can_enter_known: bool | None,
        actionability: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        blockers: list[dict[str, Any]] = []
        warnings: list[str] = []
        if actionability and actionability.get("can_act_now") is False:
            return {
                "estimate": "blocked",
                "reason": actionability["reason"],
                "terrain_enterable": can_enter_known,
                "known_blockers": blockers,
                "warnings": warnings,
            }
        if actionability and actionability.get("can_act_now") is None:
            warnings.append(actionability["reason"])

        if can_enter_known is False:
            return {
                "estimate": "blocked",
                "reason": self._enterability_info(can_enter_known, tile)["reason"],
                "terrain_enterable": False,
                "known_blockers": blockers,
                "warnings": warnings,
            }
        if can_enter_known is None:
            warnings.append("tile is unknown or lacks enough terrain data")

        for city in tile.get("cities", []):
            relation = city.get("owner_info", {}).get("relation")
            if relation != "self":
                blockers.append(
                    {
                        "kind": "city",
                        "id": city.get("id"),
                        "name": city.get("name"),
                        "owner": city.get("owner"),
                        "relation": relation or "other",
                        "reason": "non-action move orders cannot enter a visible foreign city",
                    }
                )

        for target_unit in tile.get("units", []):
            if target_unit.get("id") == unit.get("id"):
                continue
            relation = target_unit.get("owner_info", {}).get("relation")
            if relation != "self":
                blockers.append(
                    {
                        "kind": "unit",
                        "id": target_unit.get("id"),
                        "type": target_unit.get("type_rule_name") or target_unit.get("type_name"),
                        "owner": target_unit.get("owner"),
                        "relation": relation or "other",
                        "reason": "non-action move orders cannot move through a visible foreign unit",
                    }
                )

        worked = tile.get("worked")
        if worked is not None:
            worked_city = self.state.cities.get(int(worked))
            worked_relation = None
            if worked_city is not None:
                worked_relation = self.state._owner_info(worked_city.get("owner")).get("relation")
            if worked_relation != "self":
                warnings.append(
                    f"tile is worked by city {worked}; it may contain or border city/units "
                    "that Freeciv can block even when terrain is enterable"
                )

        if blockers:
            return {
                "estimate": "blocked",
                "reason": "known visible blocker on target tile",
                "terrain_enterable": can_enter_known,
                "known_blockers": blockers,
                "warnings": warnings,
            }
        if warnings:
            return {
                "estimate": "maybe",
                "reason": "terrain appears enterable, but non-terrain rules may block movement",
                "terrain_enterable": can_enter_known,
                "known_blockers": blockers,
                "warnings": warnings,
            }
        return {
            "estimate": "likely",
            "reason": "known terrain is enterable and no visible target blockers were found",
            "terrain_enterable": can_enter_known,
            "known_blockers": blockers,
            "warnings": warnings,
        }

    def _unit_actionability_info(self, unit: dict[str, Any]) -> dict[str, Any]:
        phase = self.state._phase_view()
        movesleft = unit.get("movesleft")
        done_moving = unit.get("done_moving")
        active = phase.get("agent_is_active_phase")
        result: dict[str, Any] = {
            "can_act_now": True,
            "reason": "player phase is active and the unit is not known to be out of moves",
            "phase": phase,
            "movesleft": movesleft,
            "done_moving": done_moving,
        }
        if active is False:
            result["can_act_now"] = False
            result["reason"] = "this player is not the active player in Players Alternate phase mode"
            return result
        if done_moving is True:
            result["can_act_now"] = False
            result["reason"] = "unit is marked done_moving"
            return result
        if movesleft is not None:
            try:
                if int(movesleft) <= 0:
                    result["can_act_now"] = False
                    result["reason"] = "unit has no movement points left"
                    return result
            except (TypeError, ValueError):
                pass
            if active is None:
                result["can_act_now"] = None
                result["reason"] = (
                    "current movement points are known, but the active player phase is unknown "
                    "after control reconnect"
                )
            return result
        if active is None:
            result["can_act_now"] = None
            result["reason"] = "active player phase is unknown after control reconnect"
            return result
        result["can_act_now"] = None
        result["reason"] = (
            "current movement points are unknown from decoded Freeciv state; "
            "the target tile may be legal, but the harness cannot prove the unit can move now"
        )
        return result

    def _index_to_map_pos(self, tile: int) -> tuple[int, int]:
        xsize = self.state.map_info.get("xsize")
        if not xsize:
            raise RuntimeError(f"{self.name} does not know map dimensions yet")
        nat_x = tile % xsize
        nat_y = tile // xsize
        if self._is_isometric():
            map_x = (nat_y + (nat_y & 1)) // 2 + nat_x
            map_y = nat_y - map_x + xsize
            return map_x, map_y
        return nat_x, nat_y

    def _map_pos_to_index(self, map_x: int, map_y: int) -> int | None:
        xsize = self.state.map_info.get("xsize")
        ysize = self.state.map_info.get("ysize")
        wrap_id = self.state.map_info.get("wrap_id", 0)
        if not xsize or not ysize:
            raise RuntimeError(f"{self.name} does not know map dimensions yet")
        if self._is_isometric():
            nat_y = map_x + map_y - xsize
            nat_x = int((2 * map_x - nat_y - (nat_y & 1)) / 2)
        else:
            nat_x = map_x
            nat_y = map_y

        if wrap_id & 1:
            nat_x %= xsize
        elif nat_x < 0 or nat_x >= xsize:
            return None

        if wrap_id & 2:
            nat_y %= ysize
        elif nat_y < 0 or nat_y >= ysize:
            return None
        return nat_y * xsize + nat_x

    def _is_isometric(self) -> bool:
        return bool(self.state.map_info.get("topology_id", 0) & 1)

    def _run(self) -> None:
        try:
            with self.client:
                reply = self.client.join(self.name)
                with self._lock:
                    self.state.connected = True
                    self.state.conn_id = reply.get("conn_id")
                    self.state.last_error = None

                while True:
                    try:
                        packet = self.client.read_packet()
                    except socket.timeout:
                        continue

                    self._handle_packet(packet)
        except Exception as exc:
            with self._lock:
                self.state.connected = False
                self.state.last_error = repr(exc)

    @staticmethod
    def _is_ruleset_object_packet(packet: dict[str, Any]) -> bool:
        return "id" in packet or "name" in packet or "rule_name" in packet

    def _handle_packet(self, packet: dict[str, Any]) -> None:
        pid = packet.get("pid", "unknown")
        if pid == 88:
            self.client.send_pong()

        with self._lock:
            self.state.packet_counts[pid] += 1

            if pid == 16:
                if "turn" in packet:
                    self.state.turn = int(packet["turn"])
                if "year" in packet:
                    self.state.year = int(packet["year"])
                if "phase" in packet:
                    self.state.phase = int(packet["phase"])
                if "phase_mode" in packet:
                    self.state.phase_mode = int(packet["phase_mode"])
                self._state_condition.notify_all()
            elif pid == 17:
                self.state.map_info.update(
                    {
                        key: int(packet[key])
                        for key in (
                            "xsize",
                            "ysize",
                            "topology_id",
                            "wrap_id",
                            "north_latitude",
                            "south_latitude",
                        )
                        if key in packet
                    }
                )
            elif pid == 15 and "tile" in packet:
                tile_id = int(packet["tile"])
                current = self.state.tiles.get(tile_id, {})
                current.update(
                    compact_packet(
                        packet,
                        [
                            "tile",
                            "continent",
                            "known",
                            "owner",
                            "extras_owner",
                            "terrain",
                            "resource",
                            "extras",
                            "placing",
                            "place_turn",
                            "worked",
                            "label",
                            "spec_sprite",
                        ],
                    )
                )
                self.state.tiles[tile_id] = current
                self._state_condition.notify_all()
            elif pid == 140 and self._is_ruleset_object_packet(packet):
                unit_type_id, ruleset_packet = ruleset_packet_with_id(packet)
                self.state.unit_types[unit_type_id] = compact_packet(
                    ruleset_packet,
                    [
                        "id",
                        "name",
                        "rule_name",
                        "unit_class_id",
                        "build_cost",
                        "pop_cost",
                        "attack_strength",
                        "defense_strength",
                        "move_rate",
                        "build_reqs_count",
                        "build_reqs",
                        "vision_radius_sq",
                        "transport_capacity",
                        "hp",
                        "firepower",
                        "city_size",
                        "city_slots",
                        "obsoleted_by",
                        "worker",
                    ],
                )
                self._state_condition.notify_all()
            elif pid == 144 and self._is_ruleset_object_packet(packet):
                tech_id, ruleset_packet = ruleset_packet_with_id(packet)
                self.state.techs[tech_id] = compact_packet(
                    ruleset_packet,
                    [
                        "id",
                        "root_req",
                        "research_reqs_count",
                        "research_reqs",
                        "tclass",
                        "removed",
                        "flags",
                        "cost",
                        "num_reqs",
                        "name",
                        "rule_name",
                    ],
                )
                self._state_condition.notify_all()
            elif pid == 150 and self._is_ruleset_object_packet(packet):
                building_id, ruleset_packet = ruleset_packet_with_id(packet)
                self.state.buildings[building_id] = compact_packet(
                    ruleset_packet,
                    [
                        "id",
                        "name",
                        "rule_name",
                        "genus",
                        "build_cost",
                        "upkeep",
                        "sabotage",
                        "reqs_count",
                        "reqs",
                        "obs_count",
                        "obs_reqs",
                    ],
                )
                self._state_condition.notify_all()
            elif pid == 151 and self._is_ruleset_object_packet(packet):
                terrain_id, ruleset_packet = ruleset_packet_with_id(packet)
                self.state.terrains[terrain_id] = compact_packet(
                    ruleset_packet,
                    [
                        "id",
                        "name",
                        "rule_name",
                        "tclass",
                        "movement_cost",
                        "defense_bonus",
                        "output",
                        "resources",
                        "base_time",
                        "road_time",
                        "cultivate_result",
                        "cultivate_time",
                        "irrigation_food_incr",
                        "irrigation_time",
                        "mining_shield_incr",
                        "mining_time",
                        "transform_result",
                        "transform_time",
                    ],
                )
                self._state_condition.notify_all()
            elif pid == 232 and self._is_ruleset_object_packet(packet):
                extra_id, ruleset_packet = ruleset_packet_with_id(packet)
                self.state.extras[extra_id] = compact_packet(
                    ruleset_packet,
                    [
                        "id",
                        "name",
                        "rule_name",
                        "category",
                        "causes",
                        "rmcauses",
                        "buildable",
                        "generated",
                        "build_time",
                        "build_time_factor",
                        "removal_time",
                        "removal_time_factor",
                    ],
                )
                self._state_condition.notify_all()
            elif pid == 243 and self._is_ruleset_object_packet(packet):
                multiplier_id, ruleset_packet = ruleset_packet_with_id(packet)
                self.state.multipliers[multiplier_id] = compact_packet(
                    ruleset_packet,
                    [
                        "id",
                        "name",
                        "rule_name",
                        "start",
                        "stop",
                        "step",
                        "def",
                        "offset",
                        "factor",
                        "minimum_turns",
                        "reqs_count",
                        "reqs",
                        "helptext",
                    ],
                )
                self._state_condition.notify_all()
            elif (
                pid == 51
                and packet.get("username") == self.name
                and "playerno" in packet
            ):
                self.state.player_no = int(packet["playerno"])
                self.state.last_player_packet = dict(packet)
                self.state.player_info.update(
                    compact_packet(
                        packet,
                        [
                            "playerno",
                            "name",
                            "username",
                            "nation",
                            "team",
                            "is_ready",
                            "phase_done",
                            "turns_alive",
                            "is_alive",
                            "government",
                            "target_government",
                            "gold",
                            "tax",
                            "science",
                            "luxury",
                            "score",
                            "culture",
                            "mood",
                            "nturns_idle",
                            "infrapoints",
                            "tech_upkeep_16",
                            "tech_upkeep_32",
                            "science_cost",
                            "revolution_finishes",
                        ],
                    )
                )
                self._state_condition.notify_all()
            elif (
                pid == 51
                and self.state.player_no is not None
                and packet.get("playerno") == self.state.player_no
            ):
                self.state.last_player_packet.update(packet)
                self.state.player_info.update(
                    compact_packet(
                        packet,
                        [
                            "playerno",
                            "name",
                            "username",
                            "nation",
                            "team",
                            "is_ready",
                            "phase_done",
                            "turns_alive",
                            "is_alive",
                            "government",
                            "target_government",
                            "gold",
                            "tax",
                            "science",
                            "luxury",
                            "score",
                            "culture",
                            "mood",
                            "nturns_idle",
                            "infrapoints",
                            "tech_upkeep_16",
                            "tech_upkeep_32",
                            "science_cost",
                            "revolution_finishes",
                        ],
                    )
                )
                self._state_condition.notify_all()
            elif pid == 60 and "id" in packet:
                research_id = int(packet["id"])
                current = self.state.researches.get(research_id, {})
                current.update(
                    compact_packet(
                        packet,
                        [
                            "id",
                            "techs_researched",
                            "future_tech",
                            "researching",
                            "researching_cost",
                            "bulbs_researched",
                            "tech_goal",
                            "total_bulbs_prod",
                            "inventions",
                        ],
                    )
                )
                self.state.researches[research_id] = current
                self._state_condition.notify_all()
            elif pid == 63 and "id" in packet:
                unit_id = int(packet["id"])
                current = self.state.units.get(unit_id, {})
                current.update(
                    compact_packet(
                        packet,
                        [
                            "id",
                            "owner",
                            "tile",
                            "type",
                            "movesleft",
                            "hp",
                            "activity",
                            "activity_tgt",
                            "done_moving",
                            "homecity",
                        ],
                    )
                )
                if "owner" not in current:
                    current["owner"] = 0
                if "type" not in current:
                    current["type"] = 0
                self.state.units[unit_id] = current
                self._state_condition.notify_all()
            elif pid == 64 and "id" in packet:
                unit_id = int(packet["id"])
                current = self.state.units.get(unit_id, {})
                current.update(
                    compact_packet(
                        packet,
                        [
                            "id",
                            "owner",
                            "tile",
                            "type",
                            "movesleft",
                            "hp",
                            "activity",
                            "activity_tgt",
                            "done_moving",
                            "homecity",
                            "transported_by",
                            "packet_use",
                            "info_city_id",
                        ],
                    )
                )
                if "owner" not in current:
                    current["owner"] = 0
                if "type" not in current:
                    current["type"] = 0
                self.state.units[unit_id] = current
                self._state_condition.notify_all()
            elif pid == 62:
                unit_id = packet.get("unit_id", packet.get("id"))
                if unit_id is not None:
                    self.state.units.pop(int(unit_id), None)
                    self._state_condition.notify_all()
            elif pid == 31 and "id" in packet:
                city_id = int(packet["id"])
                current = self.state.cities.get(city_id, {})
                current.update(
                    compact_packet(
                        packet,
                        [
                            "id",
                            "owner",
                            "tile",
                            "name",
                            "size",
                            "food_stock",
                            "shield_stock",
                            "production_kind",
                            "production_value",
                            "did_buy",
                            "did_sell",
                            "improvements",
                            "worklist",
                        ],
                    )
                )
                if "owner" not in current:
                    current["owner"] = 0
                self.state.cities[city_id] = current
                self._state_condition.notify_all()
            elif pid == 30:
                city_id = packet.get("id")
                if city_id is not None:
                    self.state.cities.pop(int(city_id), None)
                    self._state_condition.notify_all()
            elif pid == 127:
                if "turn" in packet:
                    self.state.turn = int(packet["turn"])
                if "year" in packet:
                    self.state.year = int(packet["year"])
                if "phase" in packet:
                    self.state.phase = int(packet["phase"])
                self._state_condition.notify_all()
            elif pid == 90:
                actions = dict(packet)
                self._latest_actions = actions
                self._actions_condition.notify_all()
            elif pid in (25, 27, 28):
                self._observe_server_message(packet.get("message"))
                self.state.recent_messages.append(
                    compact_packet(
                        packet,
                        ["pid", "message", "event", "turn", "phase", "conn_id", "tile"],
                    )
                )
                del self.state.recent_messages[:-50]
                self._state_condition.notify_all()


class ControlState:
    def __init__(
        self,
        players: list[str],
        host: str,
        port: int,
        *,
        rulesetdir: str,
        data_dir: str | None = None,
    ) -> None:
        self.ruleset = ruleset_view(rulesetdir=rulesetdir, data_dir=data_dir)
        self.agents = {
            player: ManagedAgent(player, host, port, self.ruleset)
            for player in players
        }
        for agent in self.agents.values():
            agent.start()

    def refresh_phase_inference(self) -> str | None:
        active_player_name = self._infer_active_player_name()
        for agent in self.agents.values():
            agent.set_inferred_active_player_name(active_player_name)
        return active_player_name

    def _infer_active_player_name(self) -> str | None:
        messages: list[dict[str, Any]] = []
        for agent in self.agents.values():
            with agent._lock:
                messages.extend(agent.state.recent_messages[-20:])
        for message in reversed(messages):
            text = plain_server_message(message.get("message"))
            waiting = WAITING_ON_PLAYER_RE.search(text)
            if waiting:
                return waiting.group("player").strip()
        return None

    def snapshot(self) -> dict[str, Any]:
        self.refresh_phase_inference()
        return {
            "ruleset": self.ruleset,
            "players": {
                name: agent.snapshot()
                for name, agent in self.agents.items()
            }
        }

    def brief(self) -> dict[str, Any]:
        self.refresh_phase_inference()
        return {
            "ruleset": self.ruleset,
            "players": {
                name: agent.brief()
                for name, agent in self.agents.items()
            }
        }

    def player_snapshot(self, name: str) -> dict[str, Any]:
        self.refresh_phase_inference()
        return self.agent(name).snapshot()

    def player_brief(self, name: str) -> dict[str, Any]:
        self.refresh_phase_inference()
        return self.agent(name).brief()

    def player_production_targets(self, name: str, *, city_id: int | None = None) -> dict[str, Any]:
        return self.agent(name).production_targets(city_id=city_id)

    def player_packet_audit(self, name: str) -> dict[str, Any]:
        return self.agent(name).player_packet_audit()

    def agent(self, name: str) -> ManagedAgent:
        try:
            return self.agents[name]
        except KeyError as exc:
            raise RuntimeError(f"unknown player {name!r}") from exc


def ruleset_view(*, rulesetdir: str, data_dir: str | None = None) -> dict[str, Any]:
    rulesetdir = rulesetdir or DEFAULT_RULESETDIR
    data_path = Path(data_dir).expanduser() if data_dir else None
    ruleset_path = data_path / rulesetdir if data_path else None
    return {
        "rulesetdir": rulesetdir,
        "data_dir": str(data_path) if data_path else None,
        "path": str(ruleset_path) if ruleset_path else None,
        "game_ruleset": str(ruleset_path / "game.ruleset") if ruleset_path else None,
        "source": "control-server-startup-argument",
    }


def compact_packet(packet: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: packet[key] for key in keys if key in packet}


def ruleset_packet_with_id(packet: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Freeciv JSON deltas omit zero-valued fields, including ruleset id 0."""
    if "id" in packet:
        return int(packet["id"]), packet
    packet_with_id = dict(packet)
    packet_with_id["id"] = 0
    return 0, packet_with_id


def _production_sort_key(target: dict[str, Any]) -> tuple[int, int, str]:
    cost = target.get("build_cost")
    normalized_cost = int(cost) if isinstance(cost, int) else 999999
    return (normalized_cost, int(target.get("id") or 0), str(target.get("target") or ""))


def _optional_int(query: dict[str, list[str]], key: str) -> int | None:
    values = query.get(key)
    if not values or values[0] == "":
        return None
    return int(values[0])


def make_handler(control: ControlState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                parsed = urlparse(self.path)
                parts = [part for part in parsed.path.split("/") if part]
                if parts == ["state"]:
                    self._send_json(control.snapshot())
                    return
                if parts == ["brief"]:
                    self._send_json(control.brief())
                    return
                if parts == ["ruleset"]:
                    self._send_json(control.ruleset)
                    return
                if len(parts) == 2 and parts[0] == "players":
                    self._send_json(control.player_snapshot(parts[1]))
                    return
                if len(parts) == 3 and parts[0] == "players" and parts[2] == "brief":
                    self._send_json(control.player_brief(parts[1]))
                    return
                if len(parts) == 3 and parts[0] == "players" and parts[2] == "production-targets":
                    query = parse_qs(parsed.query)
                    self._send_json(
                        control.player_production_targets(
                            parts[1],
                            city_id=_optional_int(query, "city_id"),
                        )
                    )
                    return
                if len(parts) == 3 and parts[0] == "players" and parts[2] == "player-packet-audit":
                    self._send_json(control.player_packet_audit(parts[1]))
                    return
                if len(parts) == 3 and parts[0] == "players" and parts[2] == "messages":
                    query = parse_qs(parsed.query)
                    self._send_json(
                        control.agent(parts[1]).messages(
                            limit=int(query.get("limit", ["20"])[0]),
                        )
                    )
                    return
                if len(parts) == 3 and parts[0] == "players" and parts[2] == "local-view":
                    control.refresh_phase_inference()
                    query = parse_qs(parsed.query)
                    self._send_json(
                        control.agent(parts[1]).local_view(
                            unit_id=_optional_int(query, "unit_id"),
                            city_id=_optional_int(query, "city_id"),
                            tile_id=_optional_int(query, "tile_id"),
                            radius=int(query.get("radius", ["2"])[0]),
                        )
                    )
                    return
                if len(parts) == 3 and parts[0] == "players" and parts[2] == "ascii-view":
                    control.refresh_phase_inference()
                    query = parse_qs(parsed.query)
                    self._send_json(
                        control.agent(parts[1]).ascii_view(
                            unit_id=_optional_int(query, "unit_id"),
                            city_id=_optional_int(query, "city_id"),
                            tile_id=_optional_int(query, "tile_id"),
                            radius=int(query.get("radius", ["3"])[0]),
                        )
                    )
                    return
                if len(parts) == 3 and parts[0] == "players" and parts[2] == "valid-moves":
                    control.refresh_phase_inference()
                    query = parse_qs(parsed.query)
                    unit_id = _optional_int(query, "unit_id")
                    if unit_id is None:
                        raise RuntimeError("valid-moves requires unit_id")
                    self._send_json(control.agent(parts[1]).valid_moves(unit_id=unit_id))
                    return
                self._send_json({"error": "not found"}, status=404)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)

        def do_POST(self) -> None:
            try:
                parsed = urlparse(self.path)
                parts = [part for part in parsed.path.split("/") if part]
                body = self._read_body()
                if len(parts) == 3 and parts[0] == "players":
                    control.refresh_phase_inference()
                    agent = control.agent(parts[1])
                    command = parts[2]
                    if command == "ready":
                        self._send_json(agent.ready(bool(body.get("ready", True))))
                        return
                    if command == "say":
                        self._send_json(agent.say(str(body.get("message", ""))))
                        return
                    if command == "private-intent":
                        self._send_json(
                            agent.private_intent(
                                str(body.get("intent", "")),
                                turn=(int(body["turn"]) if body.get("turn") is not None else None),
                            )
                        )
                        return
                    if command == "phase-done":
                        self._send_json(
                            agent.phase_done(
                                body.get("turn"),
                                intent=(
                                    str(body["intent"])
                                    if body.get("intent") is not None
                                    else None
                                ),
                                wait=float(body.get("wait", 2.0)),
                            )
                        )
                        return
                    if command == "found-city":
                        unit_id = body.get("unit_id")
                        if unit_id is not None:
                            unit_id = int(unit_id)
                        self._send_json(
                            agent.found_city(
                                unit_id=unit_id,
                                city_name=str(body.get("city_name", "")),
                                wait=float(body.get("wait", 5.0)),
                            )
                        )
                        return
                    if command == "move-unit":
                        self._send_json(
                            agent.move_unit(
                                unit_id=int(body["unit_id"]),
                                target_tile=(
                                    int(body["target_tile"])
                                    if body.get("target_tile") is not None
                                    else None
                                ),
                                direction=(
                                    int(body["direction"])
                                    if body.get("direction") is not None
                                    else None
                                ),
                                dx=int(body.get("dx", 0)),
                                dy=int(body.get("dy", 0)),
                                wait=float(body.get("wait", 5.0)),
                            )
                        )
                        return
                    if command == "unit-activity":
                        self._send_json(
                            agent.unit_activity(
                                unit_id=int(body["unit_id"]),
                                activity=body["activity"],
                                target=body.get("target"),
                                wait=float(body.get("wait", 5.0)),
                            )
                        )
                        return
                    if command == "set-city-production":
                        self._send_json(
                            agent.set_city_production(
                                city_id=int(body["city_id"]),
                                target=body["target"],
                                kind=body.get("kind"),
                                wait=float(body.get("wait", 1.0)),
                            )
                        )
                        return
                    if command == "set-rates":
                        self._send_json(
                            agent.set_rates(
                                tax=int(body["tax"]),
                                luxury=int(body["luxury"]),
                                science=int(body["science"]),
                                wait=float(body.get("wait", 1.0)),
                            )
                        )
                        return
                    if command == "set-research":
                        self._send_json(
                            agent.set_research(
                                tech=body["tech"],
                                wait=float(body.get("wait", 1.0)),
                            )
                        )
                        return
                    if command == "set-tech-goal":
                        self._send_json(
                            agent.set_tech_goal(
                                tech=body["tech"],
                                wait=float(body.get("wait", 1.0)),
                            )
                        )
                        return
                    if command == "query-actions":
                        self._send_json(
                            agent.query_actions(
                                unit_id=int(body["unit_id"]),
                                target_tile=(
                                    int(body["target_tile"])
                                    if body.get("target_tile") is not None
                                    else None
                                ),
                                dx=int(body.get("dx", 0)),
                                dy=int(body.get("dy", 0)),
                            )
                        )
                        return
                    if command == "do-action":
                        self._send_json(
                            agent.do_action(
                                unit_id=int(body["unit_id"]),
                                target_id=int(body["target_id"]),
                                action=body["action"],
                                sub_target=int(body.get("sub_target", -1)),
                                name=str(body.get("name", "")),
                                wait=float(body.get("wait", 1.0)),
                            )
                        )
                        return
                    if command == "packet":
                        packet = body.get("packet")
                        if not isinstance(packet, dict):
                            raise RuntimeError("expected JSON body with object field 'packet'")
                        self._send_json(agent.send_raw(packet))
                        return
                self._send_json({"error": "not found"}, status=404)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _read_body(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length", "0"))
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode())

        def _send_json(self, value: dict[str, Any], status: int = 200) -> None:
            payload = json.dumps(value, indent=2, sort_keys=True).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeciv multi-player control API.")
    parser.add_argument("--freeciv-host", default="127.0.0.1")
    parser.add_argument("--freeciv-port", default=5560, type=int)
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", default=8787, type=int)
    parser.add_argument("--players", nargs="+", required=True)
    parser.add_argument(
        "--rulesetdir",
        default=DEFAULT_RULESETDIR,
        help="Freeciv ruleset directory selected for this match.",
    )
    parser.add_argument(
        "--data-dir",
        help="Freeciv data directory containing ruleset directories.",
    )
    args = parser.parse_args()

    control = ControlState(
        args.players,
        args.freeciv_host,
        args.freeciv_port,
        rulesetdir=args.rulesetdir,
        data_dir=args.data_dir,
    )
    server = ThreadingHTTPServer((args.http_host, args.http_port), make_handler(control))
    print(
        "control_server",
        f"http://{args.http_host}:{args.http_port}",
        f"players={','.join(args.players)}",
        f"rulesetdir={args.rulesetdir}",
        flush=True,
    )
    server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()
