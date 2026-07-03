from __future__ import annotations

import argparse
import socket
import time
from collections import Counter

from .json_client import FreecivJsonClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Join a Freeciv server over JSON.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5560, type=int)
    parser.add_argument("--name", default="AgentA")
    parser.add_argument(
        "--listen-seconds",
        default=0.0,
        type=float,
        help="After joining, log incoming packet IDs for this many seconds.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every packet while listening instead of a compact summary.",
    )
    args = parser.parse_args()

    with FreecivJsonClient(args.host, args.port) as client:
        reply = client.join(args.name)
        print(
            "joined",
            f"name={args.name}",
            f"conn_id={reply.get('conn_id')}",
            f"message={reply.get('message')!r}",
        )

        if args.listen_seconds <= 0:
            return

        deadline = time.monotonic() + args.listen_seconds
        packet_counts: Counter[int | str] = Counter()
        while time.monotonic() < deadline:
            try:
                packet = client.read_packet()
            except socket.timeout:
                continue
            pid = packet.get("pid", "unknown")
            if pid == 88:
                client.send_pong()
            packet_counts[pid] += 1
            if args.verbose:
                print(f"packet pid={pid} keys={','.join(sorted(packet))}")

        if packet_counts:
            summary = " ".join(
                f"{pid}:{count}" for pid, count in packet_counts.most_common(20)
            )
            print(f"packet_counts {summary}")


if __name__ == "__main__":
    main()
