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
from urllib.parse import urlparse

from .json_client import FreecivJsonClient


@dataclass
class PlayerState:
    name: str
    connected: bool = False
    conn_id: int | None = None
    player_no: int | None = None
    turn: int | None = None
    year: int | None = None
    units: dict[int, dict[str, Any]] = field(default_factory=dict)
    cities: dict[int, dict[str, Any]] = field(default_factory=dict)
    packet_counts: Counter[int | str] = field(default_factory=Counter)
    last_error: str | None = None

    def as_json(self) -> dict[str, Any]:
        owned_units = [
            unit for unit in self.units.values()
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
            "units": owned_units,
            "cities": owned_cities,
            "packet_counts": dict(self.packet_counts.most_common(20)),
            "last_error": self.last_error,
        }


class ManagedAgent:
    def __init__(self, name: str, host: str, port: int) -> None:
        self.name = name
        self.client = FreecivJsonClient(host, port, timeout=2.0)
        self.state = PlayerState(name=name)
        self._lock = threading.RLock()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.state.as_json()

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

    def send_raw(self, packet: dict[str, Any]) -> dict[str, Any]:
        self.client.send_packet(packet)
        return {"ok": True, "player": self.name, "sent": packet}

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
            elif (
                pid == 51
                and packet.get("username") == self.name
                and "playerno" in packet
            ):
                self.state.player_no = int(packet["playerno"])
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
                            "done_moving",
                            "homecity",
                        ],
                    )
                )
                if "owner" not in current and self.state.player_no is not None:
                    current["owner"] = self.state.player_no
                self.state.units[unit_id] = current
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
                            "transported_by",
                            "packet_use",
                            "info_city_id",
                        ],
                    )
                )
                if "owner" not in current and self.state.player_no is not None:
                    current["owner"] = self.state.player_no
                self.state.units[unit_id] = current
            elif pid == 62:
                unit_id = packet.get("unit_id", packet.get("id"))
                if unit_id is not None:
                    self.state.units.pop(int(unit_id), None)
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
            elif pid == 30:
                city_id = packet.get("id")
                if city_id is not None:
                    self.state.cities.pop(int(city_id), None)
            elif pid == 127:
                if "turn" in packet:
                    self.state.turn = int(packet["turn"])
                if "year" in packet:
                    self.state.year = int(packet["year"])


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

    def agent(self, name: str) -> ManagedAgent:
        try:
            return self.agents[name]
        except KeyError as exc:
            raise RuntimeError(f"unknown player {name!r}") from exc


def compact_packet(packet: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: packet[key] for key in keys if key in packet}


def make_handler(control: ControlState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                parsed = urlparse(self.path)
                parts = [part for part in parsed.path.split("/") if part]
                if parts == ["state"]:
                    self._send_json(control.snapshot())
                    return
                if len(parts) == 2 and parts[0] == "players":
                    self._send_json(control.agent(parts[1]).snapshot())
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
