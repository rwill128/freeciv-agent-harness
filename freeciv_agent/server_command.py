from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from typing import Any

from .json_client import FreecivJsonClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send Freeciv server commands through a temporary hack-level JSON connection."
    )
    parser.add_argument("commands", nargs="+", help="Server command text, with or without a leading slash.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5560, type=int)
    parser.add_argument("--name", default="HarnessAdmin")
    parser.add_argument("--wait", default=1.0, type=float)
    parser.add_argument("--json", action="store_true", help="Emit observed chat packets as JSON.")
    args = parser.parse_args()

    with FreecivJsonClient(host=args.host, port=args.port, timeout=10) as client:
        reply = client.join(args.name)
        challenge_file = reply.get("challenge_file")
        if not challenge_file:
            raise SystemExit("server join reply did not include challenge_file")
        if not client.request_hack_access(challenge_file=challenge_file):
            raise SystemExit("server did not grant hack access")

        for command in args.commands:
            command = command if command.startswith("/") else f"/{command}"
            client.send_chat_message(command)

        messages = read_messages(client, args.wait)

    if args.json:
        json.dump(messages, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        for message in messages:
            text = message.get("message")
            if text:
                print(text)


def read_messages(client: FreecivJsonClient, wait: float) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    deadline = time.monotonic() + wait
    if client._sock is not None:
        client._sock.settimeout(0.2)
    while time.monotonic() < deadline:
        try:
            packet = client.read_packet()
        except socket.timeout:
            continue
        except Exception:
            break
        if packet.get("pid") == 25:
            messages.append(packet)
    return messages


if __name__ == "__main__":
    main()
