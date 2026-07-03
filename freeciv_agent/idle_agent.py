from __future__ import annotations

import argparse
import socket
import time
from collections import Counter
from dataclasses import dataclass, field

from .json_client import FreecivJsonClient


@dataclass
class AgentState:
    player_no: int | None = None
    current_turn: int | None = None
    current_year: int | None = None
    units: dict[int, dict[str, object]] = field(default_factory=dict)
    cities: dict[int, dict[str, object]] = field(default_factory=dict)

    def summary(self) -> str:
        turn = "?" if self.current_turn is None else str(self.current_turn)
        year = "?" if self.current_year is None else str(self.current_year)
        return (
            f"turn={turn} year={year} "
            f"units={len(self.units)} cities={len(self.cities)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Keep a Freeciv JSON agent online.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5560, type=int)
    parser.add_argument("--name", required=True)
    parser.add_argument("--ready", action="store_true")
    parser.add_argument(
        "--auto-end-turn",
        action="store_true",
        help="Immediately send turn done whenever a turn number is observed.",
    )
    parser.add_argument(
        "--max-auto-turns",
        default=1,
        type=int,
        help="Maximum turns to auto-end; use 0 for unlimited.",
    )
    parser.add_argument("--status-interval", default=10.0, type=float)
    args = parser.parse_args()

    with FreecivJsonClient(args.host, args.port, timeout=2.0) as client:
        reply = client.join(args.name)
        print(
            "joined",
            f"name={args.name}",
            f"conn_id={reply.get('conn_id')}",
            f"message={reply.get('message')!r}",
            flush=True,
        )

        state = AgentState()
        ended_turns: set[int] = set()
        ready_sent = False
        counts: Counter[int | str] = Counter()
        next_status = time.monotonic() + args.status_interval

        while True:
            try:
                packet = client.read_packet()
            except socket.timeout:
                packet = None

            if packet is not None:
                pid = packet.get("pid", "unknown")
                counts[pid] += 1
                if pid == 88:
                    client.send_pong()
                elif (
                    pid == 51
                    and packet.get("username") == args.name
                    and "playerno" in packet
                ):
                    state.player_no = int(packet["playerno"])
                    print(f"player_no={state.player_no}", flush=True)
                elif pid == 16:
                    if "turn" in packet:
                        state.current_turn = int(packet["turn"])
                    if "year" in packet:
                        state.current_year = int(packet["year"])
                elif pid == 31 and packet.get("owner") == state.player_no:
                    state.cities[int(packet["id"])] = packet
                elif pid == 30:
                    city_id = packet.get("id")
                    if city_id is not None:
                        state.cities.pop(int(city_id), None)
                elif pid == 63 and packet.get("owner") == state.player_no:
                    state.units[int(packet["id"])] = packet
                elif pid == 62:
                    unit_id = packet.get("unit_id", packet.get("id"))
                    if unit_id is not None:
                        state.units.pop(int(unit_id), None)
                elif pid == 127 and "turn" in packet:
                    state.current_turn = int(packet["turn"])
                    if "year" in packet:
                        state.current_year = int(packet["year"])
                    print(f"turn={state.current_turn}", flush=True)

            if args.ready and state.player_no is not None and not ready_sent:
                client.send_player_ready(state.player_no, True)
                ready_sent = True
                print(f"ready player_no={state.player_no}", flush=True)

            if (
                args.auto_end_turn
                and state.current_turn is not None
                and state.current_turn not in ended_turns
                and (args.max_auto_turns == 0 or len(ended_turns) < args.max_auto_turns)
            ):
                client.send_phase_done(state.current_turn)
                ended_turns.add(state.current_turn)
                print(f"phase_done turn={state.current_turn}", flush=True)

            if time.monotonic() >= next_status:
                summary = " ".join(
                    f"{pid}:{count}" for pid, count in counts.most_common(8)
                )
                print(f"alive {state.summary()} packets={summary}", flush=True)
                next_status = time.monotonic() + args.status_interval


if __name__ == "__main__":
    main()
