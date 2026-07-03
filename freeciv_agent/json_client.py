from __future__ import annotations

import json
import socket
import struct
import time
from dataclasses import dataclass
from typing import Any


DEFAULT_CAPABILITY = "+Freeciv-3.2-network ownernull16 unignoresync tu32 hap2clnt"


@dataclass
class FreecivVersion:
    major: int = 3
    minor: int = 2
    patch: int = 4
    label: str = "+"


class FreecivJsonClient:
    """Minimal Freeciv JSON protocol client.

    Freeciv JSON packets use the same framing as normal packets:
    a two-byte big-endian length followed by a NUL-terminated JSON payload.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5560,
        *,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None

    def connect(self) -> None:
        if self._sock is not None:
            return
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._sock = sock

    def close(self) -> None:
        if self._sock is None:
            return
        self._sock.close()
        self._sock = None

    def __enter__(self) -> "FreecivJsonClient":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def send_packet(self, packet: dict[str, Any]) -> None:
        sock = self._require_socket()
        payload = json.dumps(packet, separators=(",", ":"), ensure_ascii=True).encode()
        frame = struct.pack("!H", len(payload) + 3) + payload + b"\0"
        sock.sendall(frame)

    def read_packet(self) -> dict[str, Any]:
        sock = self._require_socket()
        header = self._recv_exact(sock, 2)
        (length,) = struct.unpack("!H", header)
        if length < 3:
            raise ValueError(f"invalid Freeciv packet length: {length}")

        raw = self._recv_exact(sock, length - 2)
        payload = raw[:-1] if raw.endswith(b"\0") else raw
        return json.loads(payload.decode())

    def join(
        self,
        username: str,
        *,
        capability: str = DEFAULT_CAPABILITY,
        version: FreecivVersion | None = None,
        reply_timeout: float = 10.0,
    ) -> dict[str, Any]:
        version = version or FreecivVersion()
        self.connect()
        self.send_packet(
            {
                "pid": 4,
                "username": username,
                "capability": capability,
                "version_label": version.label,
                "major_version": version.major,
                "minor_version": version.minor,
                "patch_version": version.patch,
            }
        )
        deadline = time.monotonic() + reply_timeout
        reply: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            packet = self.read_packet()
            if packet.get("pid") == 5:
                reply = packet
                break
        if reply is None:
            raise TimeoutError("timed out waiting for PACKET_SERVER_JOIN_REPLY")
        if not reply.get("you_can_join"):
            raise RuntimeError(f"Freeciv rejected join: {reply.get('message')}")
        return reply

    def send_player_ready(self, player_no: int, is_ready: bool = True) -> None:
        fields = _bitvector_bytes(2, [0] + ([1] if is_ready else []))
        packet: dict[str, Any] = {
            "pid": 11,
            "fields": fields,
            "player_no": player_no,
        }
        self.send_packet(packet)

    def send_phase_done(self, turn: int) -> None:
        self.send_packet(
            {
                "pid": 52,
                "fields": _bitvector_bytes(1, [0]),
                "turn": turn,
            }
        )

    def send_pong(self) -> None:
        self.send_packet({"pid": 89})

    def send_nation_select(
        self,
        *,
        player_no: int,
        nation_no: int,
        leader_name: str,
        style: int = 0,
        is_male: bool = True,
    ) -> None:
        set_bits = [0, 1, 3, 4]
        if is_male:
            set_bits.append(2)
        self.send_packet(
            {
                "pid": 10,
                "fields": _bitvector_bytes(5, set_bits),
                "player_no": player_no,
                "nation_no": nation_no,
                "name": leader_name,
                "style": style,
            }
        )

    def send_unit_do_action(
        self,
        *,
        actor_id: int,
        target_id: int,
        action_type: int,
        sub_tgt_id: int = -1,
        name: str = "",
    ) -> None:
        self.send_packet(
            {
                "pid": 84,
                "fields": _bitvector_bytes(5, [0, 1, 2, 3, 4]),
                "actor_id": actor_id,
                "target_id": target_id,
                "sub_tgt_id": sub_tgt_id,
                "name": name,
                "action_type": action_type,
            }
        )

    def send_unit_get_actions(
        self,
        *,
        actor_unit_id: int,
        target_tile_id: int,
        target_unit_id: int = 0,
        target_extra_id: int = -1,
        request_kind: int = 0,
    ) -> None:
        self.send_packet(
            {
                "pid": 87,
                "fields": _bitvector_bytes(5, [0, 1, 2, 3, 4]),
                "actor_unit_id": actor_unit_id,
                "target_unit_id": target_unit_id,
                "target_tile_id": target_tile_id,
                "target_extra_id": target_extra_id,
                "request_kind": request_kind,
            }
        )

    def send_unit_move_order(
        self,
        *,
        unit_id: int,
        src_tile: int,
        dest_tile: int,
        direction: int,
    ) -> None:
        self.send_packet(
            {
                "pid": 73,
                "fields": _bitvector_bytes(7, [0, 1, 2, 5, 6]),
                "unit_id": unit_id,
                "src_tile": src_tile,
                "length": 1,
                "orders": [
                    {
                        "order": 0,
                        "activity": 16,
                        "target": -1,
                        "sub_target": -1,
                        "action": 125,
                        "dir": direction,
                    }
                ],
                "dest_tile": dest_tile,
            }
        )

    def send_unit_change_activity(
        self,
        *,
        unit_id: int,
        activity: int,
        target: int = -1,
    ) -> None:
        self.send_packet(
            {
                "pid": 222,
                "fields": _bitvector_bytes(3, [0, 1, 2]),
                "unit_id": unit_id,
                "activity": activity,
                "target": target,
            }
        )

    def _require_socket(self) -> socket.socket:
        if self._sock is None:
            raise RuntimeError("client is not connected")
        return self._sock

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ConnectionError("Freeciv connection closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def _bitvector_bytes(bits: int, set_bits: list[int]) -> list[int]:
    values = [0] * (((bits - 1) // 8) + 1)
    for bit in set_bits:
        values[bit // 8] |= 1 << (bit & 7)
    return values
