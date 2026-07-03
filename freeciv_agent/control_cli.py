from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI for the Freeciv control API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("state")

    brief = subparsers.add_parser("brief")
    brief.add_argument("name", nargs="?")

    player_state = subparsers.add_parser("player")
    player_state.add_argument("name")

    messages = subparsers.add_parser("messages")
    messages.add_argument("name")
    messages.add_argument("--limit", default=20, type=int)

    local_view = subparsers.add_parser("local-view")
    local_view.add_argument("name")
    local_view.add_argument("--unit-id", type=int)
    local_view.add_argument("--city-id", type=int)
    local_view.add_argument("--tile-id", type=int)
    local_view.add_argument("--radius", default=2, type=int)

    ascii_view = subparsers.add_parser("ascii-view")
    ascii_view.add_argument("name")
    ascii_view.add_argument("--unit-id", type=int)
    ascii_view.add_argument("--city-id", type=int)
    ascii_view.add_argument("--tile-id", type=int)
    ascii_view.add_argument("--radius", default=3, type=int)
    ascii_view.add_argument("--text", action="store_true")

    valid_moves = subparsers.add_parser("valid-moves")
    valid_moves.add_argument("name")
    valid_moves.add_argument("unit_id", type=int)

    ready = subparsers.add_parser("ready")
    ready.add_argument("name")

    phase_done = subparsers.add_parser("phase-done")
    phase_done.add_argument("name")
    phase_done.add_argument("--turn", type=int)

    found_city = subparsers.add_parser("found-city")
    found_city.add_argument("name")
    found_city.add_argument("--unit-id", type=int)
    found_city.add_argument("--city-name", default="")

    move_unit = subparsers.add_parser("move-unit")
    move_unit.add_argument("name")
    move_unit.add_argument("unit_id", type=int)
    move_unit.add_argument("--target-tile", type=int)
    move_unit.add_argument("--direction", type=int)
    move_unit.add_argument("--dx", default=0, type=int)
    move_unit.add_argument("--dy", default=0, type=int)
    move_unit.add_argument("--wait", default=1.0, type=float)

    unit_activity = subparsers.add_parser("unit-activity")
    unit_activity.add_argument("name")
    unit_activity.add_argument("unit_id", type=int)
    unit_activity.add_argument("activity")
    unit_activity.add_argument("--target")
    unit_activity.add_argument("--wait", default=1.0, type=float)

    query_actions = subparsers.add_parser("query-actions")
    query_actions.add_argument("name")
    query_actions.add_argument("unit_id", type=int)
    query_actions.add_argument("--target-tile", type=int)
    query_actions.add_argument("--dx", default=0, type=int)
    query_actions.add_argument("--dy", default=0, type=int)

    packet = subparsers.add_parser("packet")
    packet.add_argument("name")
    packet.add_argument("json_packet")

    args = parser.parse_args()

    if args.command == "state":
        result = request("GET", f"{args.base_url}/state")
    elif args.command == "brief":
        if args.name:
            result = request("GET", f"{args.base_url}/players/{args.name}/brief")
        else:
            result = request("GET", f"{args.base_url}/brief")
    elif args.command == "player":
        result = request("GET", f"{args.base_url}/players/{args.name}")
    elif args.command == "messages":
        result = request(
            "GET",
            f"{args.base_url}/players/{args.name}/messages?"
            f"{urllib.parse.urlencode({'limit': args.limit})}",
        )
    elif args.command == "local-view":
        query = {
            "radius": args.radius,
        }
        if args.unit_id is not None:
            query["unit_id"] = args.unit_id
        if args.city_id is not None:
            query["city_id"] = args.city_id
        if args.tile_id is not None:
            query["tile_id"] = args.tile_id
        result = request(
            "GET",
            f"{args.base_url}/players/{args.name}/local-view?"
            f"{urllib.parse.urlencode(query)}",
        )
    elif args.command == "ascii-view":
        query = {
            "radius": args.radius,
        }
        if args.unit_id is not None:
            query["unit_id"] = args.unit_id
        if args.city_id is not None:
            query["city_id"] = args.city_id
        if args.tile_id is not None:
            query["tile_id"] = args.tile_id
        result = request(
            "GET",
            f"{args.base_url}/players/{args.name}/ascii-view?"
            f"{urllib.parse.urlencode(query)}",
        )
        if args.text:
            print(result["text"])
            return
    elif args.command == "valid-moves":
        result = request(
            "GET",
            f"{args.base_url}/players/{args.name}/valid-moves?"
            f"{urllib.parse.urlencode({'unit_id': args.unit_id})}",
        )
    elif args.command == "ready":
        result = request("POST", f"{args.base_url}/players/{args.name}/ready", {})
    elif args.command == "phase-done":
        body: dict[str, Any] = {}
        if args.turn is not None:
            body["turn"] = args.turn
        result = request("POST", f"{args.base_url}/players/{args.name}/phase-done", body)
    elif args.command == "found-city":
        body = {"city_name": args.city_name}
        if args.unit_id is not None:
            body["unit_id"] = args.unit_id
        result = request("POST", f"{args.base_url}/players/{args.name}/found-city", body)
    elif args.command == "move-unit":
        body = {
            "unit_id": args.unit_id,
            "dx": args.dx,
            "dy": args.dy,
            "wait": args.wait,
        }
        if args.target_tile is not None:
            body["target_tile"] = args.target_tile
        if args.direction is not None:
            body["direction"] = args.direction
        result = request("POST", f"{args.base_url}/players/{args.name}/move-unit", body)
    elif args.command == "unit-activity":
        body = {
            "unit_id": args.unit_id,
            "activity": args.activity,
            "wait": args.wait,
        }
        if args.target is not None:
            body["target"] = args.target
        result = request("POST", f"{args.base_url}/players/{args.name}/unit-activity", body)
    elif args.command == "query-actions":
        body = {
            "unit_id": args.unit_id,
            "dx": args.dx,
            "dy": args.dy,
        }
        if args.target_tile is not None:
            body["target_tile"] = args.target_tile
        result = request("POST", f"{args.base_url}/players/{args.name}/query-actions", body)
    elif args.command == "packet":
        result = request(
            "POST",
            f"{args.base_url}/players/{args.name}/packet",
            {"packet": json.loads(args.json_packet)},
        )
    else:
        raise AssertionError(args.command)

    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    print()


def request(method: str, url: str, body: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = {"error": detail or exc.reason}
        json.dump(payload, sys.stderr, indent=2, sort_keys=True)
        print(file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
