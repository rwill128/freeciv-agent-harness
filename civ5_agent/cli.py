from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .log_bridge import (
    STATE_PREFIX,
    candidate_lua_log_paths,
    civ5_status,
    latest_command_result,
    latest_state,
    wait_for_state,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Civ 5 agent bridge utility CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("log-paths", help="Print candidate Civ 5 Lua.log paths.")

    status = subparsers.add_parser("status", help="Print Civ 5 bridge install/log status.")
    status.add_argument("--json", action="store_true")

    latest = subparsers.add_parser("latest-state", help="Read the latest bridge state from Lua.log.")
    latest.add_argument("--log", type=Path, default=None)
    latest.add_argument("--pretty", action="store_true")

    latest_command = subparsers.add_parser(
        "latest-command",
        help="Read the latest bridge command result from Lua.log.",
    )
    latest_command.add_argument("--log", type=Path, default=None)
    latest_command.add_argument("--pretty", action="store_true")

    brief = subparsers.add_parser("brief", help="Print a compact active-player state summary.")
    brief.add_argument("--log", type=Path, default=None)

    wait = subparsers.add_parser("wait-state", help="Wait for the bridge to emit a Civ 5 state record.")
    wait.add_argument("--log", type=Path, default=None)
    wait.add_argument("--timeout", default=300.0, type=float)
    wait.add_argument("--interval", default=2.0, type=float)
    wait.add_argument("--pretty", action="store_true")

    args = parser.parse_args()
    if args.command == "log-paths":
        for path in candidate_lua_log_paths():
            suffix = " exists" if path.exists() else ""
            print(f"{path}{suffix}")
        return
    if args.command == "status":
        status_payload = civ5_status()
        if args.json:
            json.dump(status_payload, sys.stdout, indent=2, sort_keys=True)
            print()
        else:
            print(format_status(status_payload))
        return
    if args.command == "latest-state":
        print_json_or_exit(lambda: latest_state(args.log), args.pretty, "Civ 5 bridge state")
        return
    if args.command == "latest-command":
        print_json_or_exit(lambda: latest_command_result(args.log), args.pretty, "Civ 5 bridge command result")
        return
    if args.command == "brief":
        try:
            print(format_brief(latest_state(args.log)))
        except Exception as exc:  # noqa: BLE001 - CLI should print concise bridge/log failures.
            print(f"Could not read Civ 5 bridge state: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return
    if args.command == "wait-state":
        print_json_or_exit(
            lambda: wait_for_state(args.log, timeout=args.timeout, interval=args.interval),
            args.pretty,
            "Civ 5 bridge state",
        )
        return
    raise AssertionError(args.command)


def print_json_or_exit(callback: Any, pretty: bool, label: str) -> None:
    try:
        payload = callback()
    except Exception as exc:  # noqa: BLE001 - CLI should print concise bridge/log failures.
        print(f"Could not read {label}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if pretty:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    else:
        json.dump(payload, sys.stdout, separators=(",", ":"), sort_keys=True)
    print()


def format_status(status: dict[str, Any]) -> str:
    mod = status.get("mod") or {}
    log = status.get("log") or {}
    config = status.get("config") or {}
    manifest = status.get("steam_appmanifest") or {}
    lines = [
        f"Civ 5 app: {status.get('app_path') or 'not found'}",
        f"Steam install: {status.get('steam_install_root') or 'not found'} ({status.get('steam_install_flavor')})",
        "Steam libraries: " + ", ".join(status.get("steam_library_roots") or []),
        (
            "Steam manifest: "
            f"state_flags={manifest.get('StateFlags')} "
            f"build={manifest.get('buildid')} "
            f"path={manifest.get('_path')}"
        ),
        f"Support root: {status.get('support_root') or 'not found'}",
        f"Mods dir: {status.get('mods_dir') or 'not found'}",
        f"Bridge installed: {mod.get('installed')} at {mod.get('installed_path')}",
        (
            "Config: "
            f"EnableTuner={config.get('EnableTuner')} "
            f"EnableLuaDebugLibrary={config.get('EnableLuaDebugLibrary')} "
            f"MessageLog={config.get('MessageLog')} "
            f"DisableSidSounds={config.get('Audio.Disable Sid Sounds')} "
            f"EnableMusic={config.get('Audio.Enable music')}"
        ),
        f"Lua log: {log.get('path') or 'not found'}",
        (
            "Bridge log markers: "
            f"ready={log.get('bridge_ready')} state_records={log.get('state_records')} "
            f"command_records={log.get('command_records')} "
            f"latest_state_line={log.get('latest_state_line')} "
            f"latest_command_line={log.get('latest_command_line')}"
        ),
    ]
    if not mod.get("installed"):
        lines.append("Bridge is not installed yet; run scripts/civ5-runtime setup.")
    if log.get("path") and not log.get("state_records"):
        lines.append(f"No {STATE_PREFIX.strip()} records are present yet; start/load a game with the mod enabled.")
    return "\n".join(lines)


def format_brief(state: dict[str, Any]) -> str:
    game = state.get("game") or {}
    player = state.get("player") or {}
    units = state.get("units") or []
    cities = state.get("cities") or []
    plots = state.get("visible_plots") or []
    lines = [
        (
            f"Civ5 turn={game.get('turn')} year={game.get('year')} "
            f"active_player={player.get('name') or player.get('id')} "
            f"civ={player.get('civilization_short_description') or player.get('civilization_type')}"
        ),
        f"Visible plots={len(plots)} cities={len(cities)} units={len(units)}",
    ]
    if cities:
        lines.append("Cities:")
        for city in cities[:12]:
            lines.append(
                f"  {city.get('id')}:{city.get('name')} pop={city.get('population')} "
                f"at=({city.get('x')},{city.get('y')})"
            )
    if units:
        lines.append("Units:")
        for unit in units[:20]:
            lines.append(
                f"  {unit.get('id')}:{unit.get('type_name') or unit.get('type')} "
                f"at=({unit.get('x')},{unit.get('y')}) moves={unit.get('moves')} "
                f"hp={unit.get('damage')}"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
