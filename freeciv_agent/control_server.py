from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .json_client import FreecivJsonClient


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

DEFAULT_ACTIVITY_TARGETS = {
    2: "Mine",
    3: "Irrigation",
    13: "Road",
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

WATER_TERRAINS = {"Lake", "Ocean", "Deep Ocean"}


@dataclass
class PlayerState:
    name: str
    connected: bool = False
    conn_id: int | None = None
    player_no: int | None = None
    turn: int | None = None
    year: int | None = None
    map_info: dict[str, int] = field(default_factory=dict)
    tiles: dict[int, dict[str, Any]] = field(default_factory=dict)
    units: dict[int, dict[str, Any]] = field(default_factory=dict)
    cities: dict[int, dict[str, Any]] = field(default_factory=dict)
    unit_types: dict[int, dict[str, Any]] = field(default_factory=dict)
    extras: dict[int, dict[str, Any]] = field(default_factory=dict)
    terrains: dict[int, dict[str, Any]] = field(default_factory=dict)
    packet_counts: Counter[int | str] = field(default_factory=Counter)
    last_error: str | None = None

    def as_json(self) -> dict[str, Any]:
        owned_units = [
            self._enrich_unit(unit) for unit in self.units.values()
            if self.player_no is None or unit.get("owner") == self.player_no
        ]
        owned_cities = [
            city for city in self.cities.values()
            if self.player_no is None or city.get("owner") == self.player_no
        ]
        return {
            "name": self.name,
            "connected": self.connected,
            "conn_id": self.conn_id,
            "player_no": self.player_no,
            "turn": self.turn,
            "year": self.year,
            "map_info": self.map_info,
            "units": owned_units,
            "cities": owned_cities,
            "unit_types": self.unit_types,
            "extras": self.extras,
            "terrains": self.terrains,
            "packet_counts": dict(self.packet_counts.most_common(20)),
            "last_error": self.last_error,
        }

    def as_brief_json(self) -> dict[str, Any]:
        owned_units = [
            self._brief_unit(self._enrich_unit(unit))
            for unit in self.units.values()
            if self.player_no is None or unit.get("owner") == self.player_no
        ]
        owned_cities = [
            self._brief_city(city)
            for city in self.cities.values()
            if self.player_no is None or city.get("owner") == self.player_no
        ]
        return {
            "name": self.name,
            "connected": self.connected,
            "player_no": self.player_no,
            "turn": self.turn,
            "year": self.year,
            "map": self.map_info,
            "cities": owned_cities,
            "units": owned_units,
            "known_tiles": len(self.tiles),
            "last_error": self.last_error,
        }

    def _enrich_unit(self, unit: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(unit)
        unit_type = self.unit_types.get(int(unit["type"])) if "type" in unit else None
        if unit_type is not None:
            enriched["type_name"] = unit_type.get("name")
            enriched["type_rule_name"] = unit_type.get("rule_name")
            for key in ("attack_strength", "defense_strength", "move_rate", "worker"):
                if key in unit_type:
                    enriched[f"type_{key}"] = unit_type[key]
        target = self.extras.get(int(unit["activity_tgt"])) if "activity_tgt" in unit else None
        if target is not None:
            enriched["activity_target_name"] = target.get("name")
            enriched["activity_target_rule_name"] = target.get("rule_name")
        return enriched

    @staticmethod
    def _brief_unit(unit: dict[str, Any]) -> dict[str, Any]:
        return compact_packet(
            unit,
            [
                "id",
                "owner",
                "type",
                "type_name",
                "type_rule_name",
                "tile",
                "movesleft",
                "hp",
                "activity",
                "activity_tgt",
                "activity_target_name",
                "activity_target_rule_name",
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
                "tile",
                "size",
                "food_stock",
                "shield_stock",
                "production_kind",
                "production_value",
            ],
        )


class ManagedAgent:
    def __init__(self, name: str, host: str, port: int) -> None:
        self.name = name
        self.client = FreecivJsonClient(host, port, timeout=2.0)
        self.state = PlayerState(name=name)
        self._lock = threading.RLock()
        self._state_condition = threading.Condition(self._lock)
        self._actions_condition = threading.Condition(self._lock)
        self._latest_actions: dict[str, Any] | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.state.as_json()

    def brief(self) -> dict[str, Any]:
        with self._lock:
            return self.state.as_brief_json()

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
                "tiles": tiles,
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
            moves = []
            for direction in self._valid_directions():
                target_tile = self._step_tile(int(current_tile), direction)
                if target_tile is None:
                    continue
                dx, dy = self._direction_delta(direction)
                target_map = self._index_to_map_pos(target_tile)
                tile = self._local_tile(target_tile, dx, dy)
                can_enter_known = self._can_unit_enter_known_tile(unit, tile)
                moves.append(
                    {
                        "direction": direction,
                        "direction_name": DIRECTION_NAMES[direction],
                        "dx": dx,
                        "dy": dy,
                        "target_tile": target_tile,
                        "target_map": {"x": target_map[0], "y": target_map[1]},
                        "known": tile["known"],
                        "can_enter_known": can_enter_known,
                        "tile": tile,
                    }
                )
            return {
                "player": self.name,
                "turn": self.state.turn,
                "year": self.state.year,
                "unit": PlayerState._brief_unit(self.state._enrich_unit(unit)),
                "current_tile": int(current_tile),
                "current_map": {"x": current_map[0], "y": current_map[1]},
                "topology_id": self.state.map_info.get("topology_id"),
                "moves": moves,
            }

    def ready(self, is_ready: bool = True) -> dict[str, Any]:
        with self._lock:
            player_no = self.state.player_no
        if player_no is None:
            raise RuntimeError(f"{self.name} has no player_no yet")
        self.client.send_player_ready(player_no, is_ready)
        return {"ok": True, "player": self.name, "ready": is_ready}

    def phase_done(self, turn: int | None = None) -> dict[str, Any]:
        with self._lock:
            turn = self.state.turn if turn is None else turn
        if turn is None:
            raise RuntimeError(f"{self.name} does not know the current turn yet")
        self.client.send_phase_done(turn)
        return {"ok": True, "player": self.name, "turn": turn}

    def found_city(self, unit_id: int | None = None, city_name: str = "") -> dict[str, Any]:
        with self._lock:
            units = [
                unit for unit in self.state.units.values()
                if unit.get("owner") == self.state.player_no
            ]
            if unit_id is None:
                candidates = [
                    unit for unit in units
                    if unit.get("type") in (None, 0) and unit.get("tile") is not None
                ]
                if not candidates:
                    candidates = [
                        unit for unit in units
                        if unit.get("hp") == 20 and unit.get("tile") is not None
                    ]
                if not candidates:
                    raise RuntimeError(f"{self.name} has no obvious settler unit")
                unit = candidates[0]
            else:
                unit = self.state.units.get(unit_id)
                if unit is None or unit.get("owner") != self.state.player_no:
                    raise RuntimeError(f"{self.name} does not own unit {unit_id}")

            actor_id = int(unit["id"])
            target_id = int(unit["tile"])

        self.client.send_unit_do_action(
            actor_id=actor_id,
            target_id=target_id,
            sub_tgt_id=-1,
            name=city_name,
            action_type=27,
        )
        return {
            "ok": True,
            "player": self.name,
            "unit_id": actor_id,
            "target_tile": target_id,
            "city_name": city_name,
            "action_type": 27,
        }

    def move_unit(
        self,
        *,
        unit_id: int,
        target_tile: int | None = None,
        direction: int | None = None,
        dx: int = 0,
        dy: int = 0,
        wait: float = 1.0,
    ) -> dict[str, Any]:
        with self._lock:
            unit = self.state.units.get(unit_id)
            if unit is None or unit.get("owner") != self.state.player_no:
                raise RuntimeError(f"{self.name} does not own unit {unit_id}")
            current_tile = unit.get("tile")
            if current_tile is None:
                raise RuntimeError(f"{self.name} unit {unit_id} has no known tile")
            if direction is not None:
                target_tile = self._step_tile(int(current_tile), direction)
                if target_tile is None:
                    raise RuntimeError(
                        f"direction {direction} from tile {current_tile} is invalid"
                    )
            elif target_tile is None:
                target_tile = self._relative_tile(int(current_tile), dx, dy)
                direction = self._direction_to_target(int(current_tile), target_tile)
            else:
                direction = self._direction_to_target(int(current_tile), target_tile)
            before = self.state._enrich_unit(unit)

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
        return {
            "ok": True,
            "player": self.name,
            "unit_id": unit_id,
            "from_tile": current_tile,
            "target_tile": target_tile,
            "packet": "PACKET_UNIT_ORDERS",
            "direction": direction,
            "before": PlayerState._brief_unit(before),
            "after": PlayerState._brief_unit(after) if after else None,
            "applied": bool(after and after.get("tile") == target_tile),
            "observed_changed": bool(after and self._unit_changed(before, after)),
        }

    def unit_activity(
        self,
        *,
        unit_id: int,
        activity: str | int,
        target: str | int | None = None,
        wait: float = 1.0,
    ) -> dict[str, Any]:
        with self._lock:
            unit = self.state.units.get(unit_id)
            if unit is None or unit.get("owner") != self.state.player_no:
                raise RuntimeError(f"{self.name} does not own unit {unit_id}")
            before = self.state._enrich_unit(unit)
            activity_id = self._resolve_activity(activity)
            target_id = self._resolve_activity_target(activity_id, target)

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
        return {
            "ok": True,
            "player": self.name,
            "unit_id": unit_id,
            "packet": "PACKET_UNIT_CHANGE_ACTIVITY",
            "activity": activity_id,
            "target": target_id,
            "before": PlayerState._brief_unit(before),
            "after": PlayerState._brief_unit(after) if after else None,
            "applied": bool(
                after
                and after.get("activity") == activity_id
                and (target_id < 0 or after.get("activity_tgt") == target_id)
            ),
            "observed_changed": bool(after and self._unit_changed(before, after)),
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
                    return self._latest_actions
                self._actions_condition.wait(deadline - time.monotonic())
        raise TimeoutError(f"timed out waiting for actions for unit {unit_id}")

    def send_raw(self, packet: dict[str, Any]) -> dict[str, Any]:
        self.client.send_packet(packet)
        return {"ok": True, "player": self.name, "sent": packet}

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
                if enriched and (
                    enriched.get("tile") == target_tile
                    or self._unit_changed(previous, enriched)
                ):
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

    @staticmethod
    def _unit_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
        return any(
            before.get(key) != after.get(key)
            for key in ("tile", "movesleft", "hp", "activity", "activity_tgt")
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

    def _resolve_activity_target(self, activity: int, target: str | int | None) -> int:
        if isinstance(target, int):
            return target
        if target is None:
            target = DEFAULT_ACTIVITY_TARGETS.get(activity)
        if target is None or target == "":
            return -1
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
        result.update(compact_packet(tile, ["terrain", "resource", "owner", "worked", "label"]))
        terrain = self.state.terrains.get(int(tile["terrain"])) if "terrain" in tile else None
        if terrain is not None:
            result["terrain_name"] = terrain.get("name")
            result["terrain_rule_name"] = terrain.get("rule_name")
            result["movement_cost"] = terrain.get("movement_cost")
            result["defense_bonus"] = terrain.get("defense_bonus")
        resource = self.state.extras.get(int(tile["resource"])) if "resource" in tile else None
        if resource is not None:
            result["resource_name"] = resource.get("name")
            result["resource_rule_name"] = resource.get("rule_name")
        units = [
            PlayerState._brief_unit(self.state._enrich_unit(unit))
            for unit in self.state.units.values()
            if unit.get("tile") == tile_id
        ]
        cities = [
            PlayerState._brief_city(city)
            for city in self.state.cities.values()
            if city.get("tile") == tile_id
        ]
        if units:
            result["units"] = units
        if cities:
            result["cities"] = cities
        return result

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
        raise RuntimeError(
            f"target tile {target_tile} is not adjacent to {src_tile}"
        )

    def _step_tile(self, tile: int, direction: int) -> int | None:
        if direction not in self._valid_directions():
            raise RuntimeError(
                f"direction {direction} is not valid for topology "
                f"{self.state.map_info.get('topology_id')}"
            )
        dx, dy = self._direction_delta(direction)
        map_x, map_y = self._index_to_map_pos(tile)
        return self._map_pos_to_index(map_x + dx, map_y + dy)

    def _direction_delta(self, direction: int) -> tuple[int, int]:
        if direction < 0 or direction > 7:
            raise RuntimeError(f"direction {direction} is outside 0..7")
        return (
            (-1, -1),
            (0, -1),
            (1, -1),
            (-1, 0),
            (1, 0),
            (-1, 1),
            (0, 1),
            (1, 1),
        )[direction]

    def _valid_directions(self) -> list[int]:
        topology_id = self.state.map_info.get("topology_id", 0)
        is_iso = bool(topology_id & 1)
        is_hex = bool(topology_id & 2)
        if is_iso and is_hex:
            return [0, 1, 3, 4, 6, 7]
        if is_hex:
            return [1, 2, 3, 4, 5, 6]
        return list(range(8))

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
                            "terrain",
                            "resource",
                            "worked",
                            "label",
                        ],
                    )
                )
                self.state.tiles[tile_id] = current
                self._state_condition.notify_all()
            elif pid == 140 and "id" in packet:
                unit_type_id = int(packet["id"])
                self.state.unit_types[unit_type_id] = compact_packet(
                    packet,
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
                        "vision_radius_sq",
                        "transport_capacity",
                        "hp",
                        "firepower",
                        "worker",
                    ],
                )
                self._state_condition.notify_all()
            elif pid == 151 and "id" in packet:
                terrain_id = int(packet["id"])
                self.state.terrains[terrain_id] = compact_packet(
                    packet,
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
            elif pid == 232 and "id" in packet:
                extra_id = int(packet["id"])
                self.state.extras[extra_id] = compact_packet(
                    packet,
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
            elif (
                pid == 51
                and packet.get("username") == self.name
                and "playerno" in packet
            ):
                self.state.player_no = int(packet["playerno"])
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
                if "owner" not in current and self.state.player_no is not None:
                    current["owner"] = self.state.player_no
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
                            "hp",
                            "activity",
                            "activity_tgt",
                            "transported_by",
                            "packet_use",
                            "info_city_id",
                        ],
                    )
                )
                if "owner" not in current and self.state.player_no is not None:
                    current["owner"] = self.state.player_no
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
                        ],
                    )
                )
                if "owner" not in current and self.state.player_no is not None:
                    current["owner"] = self.state.player_no
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
                self._state_condition.notify_all()
            elif pid == 90:
                actions = dict(packet)
                self._latest_actions = actions
                self._actions_condition.notify_all()


class ControlState:
    def __init__(self, players: list[str], host: str, port: int) -> None:
        self.agents = {
            player: ManagedAgent(player, host, port)
            for player in players
        }
        for agent in self.agents.values():
            agent.start()

    def snapshot(self) -> dict[str, Any]:
        return {
            "players": {
                name: agent.snapshot()
                for name, agent in self.agents.items()
            }
        }

    def brief(self) -> dict[str, Any]:
        return {
            "players": {
                name: agent.brief()
                for name, agent in self.agents.items()
            }
        }

    def agent(self, name: str) -> ManagedAgent:
        try:
            return self.agents[name]
        except KeyError as exc:
            raise RuntimeError(f"unknown player {name!r}") from exc


def compact_packet(packet: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: packet[key] for key in keys if key in packet}


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
                if len(parts) == 2 and parts[0] == "players":
                    self._send_json(control.agent(parts[1]).snapshot())
                    return
                if len(parts) == 3 and parts[0] == "players" and parts[2] == "brief":
                    self._send_json(control.agent(parts[1]).brief())
                    return
                if len(parts) == 3 and parts[0] == "players" and parts[2] == "local-view":
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
                if len(parts) == 3 and parts[0] == "players" and parts[2] == "valid-moves":
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
                    agent = control.agent(parts[1])
                    command = parts[2]
                    if command == "ready":
                        self._send_json(agent.ready(bool(body.get("ready", True))))
                        return
                    if command == "phase-done":
                        self._send_json(agent.phase_done(body.get("turn")))
                        return
                    if command == "found-city":
                        unit_id = body.get("unit_id")
                        if unit_id is not None:
                            unit_id = int(unit_id)
                        self._send_json(
                            agent.found_city(
                                unit_id=unit_id,
                                city_name=str(body.get("city_name", "")),
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
                                wait=float(body.get("wait", 1.0)),
                            )
                        )
                        return
                    if command == "unit-activity":
                        self._send_json(
                            agent.unit_activity(
                                unit_id=int(body["unit_id"]),
                                activity=body["activity"],
                                target=body.get("target"),
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
    args = parser.parse_args()

    control = ControlState(args.players, args.freeciv_host, args.freeciv_port)
    server = ThreadingHTTPServer((args.http_host, args.http_port), make_handler(control))
    print(
        "control_server",
        f"http://{args.http_host}:{args.http_port}",
        f"players={','.join(args.players)}",
        flush=True,
    )
    server.serve_forever(poll_interval=0.25)


if __name__ == "__main__":
    main()
