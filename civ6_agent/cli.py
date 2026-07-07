from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .log_bridge import (
    STATE_PREFIX,
    candidate_lua_log_paths,
    civ6_status,
    enable_bridge_mod,
    latest_command_result,
    latest_state,
    wait_for_state,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Civ 6 agent bridge utility CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    paths = subparsers.add_parser("log-paths", help="Print candidate Civ 6 Lua.log paths.")

    status = subparsers.add_parser("status", help="Print Civ 6 bridge install/log status.")
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

    enable = subparsers.add_parser("enable-bridge", help="Enable the scanned bridge mod in the selected mod group.")
    enable.add_argument("--json", action="store_true")

    wait = subparsers.add_parser("wait-state", help="Wait for the bridge to emit a Civ 6 state record.")
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
        status_payload = civ6_status()
        if args.json:
            json.dump(status_payload, sys.stdout, indent=2, sort_keys=True)
            print()
        else:
            print(format_status(status_payload))
        return
    if args.command == "latest-state":
        try:
            state = latest_state(args.log)
        except Exception as exc:  # noqa: BLE001 - CLI should print concise bridge/log failures.
            print(f"Could not read Civ 6 bridge state: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if args.pretty:
            json.dump(state, sys.stdout, indent=2, sort_keys=True)
        else:
            json.dump(state, sys.stdout, separators=(",", ":"), sort_keys=True)
        print()
        return
    if args.command == "latest-command":
        try:
            result = latest_command_result(args.log)
        except Exception as exc:  # noqa: BLE001 - CLI should print concise bridge/log failures.
            print(f"Could not read Civ 6 bridge command result: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if args.pretty:
            json.dump(result, sys.stdout, indent=2, sort_keys=True)
        else:
            json.dump(result, sys.stdout, separators=(",", ":"), sort_keys=True)
        print()
        return
    if args.command == "brief":
        try:
            print(format_brief(latest_state(args.log)))
        except Exception as exc:  # noqa: BLE001 - CLI should print concise bridge/log failures.
            print(f"Could not read Civ 6 bridge state: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return
    if args.command == "enable-bridge":
        result = enable_bridge_mod()
        if args.json:
            json.dump(result, sys.stdout, indent=2, sort_keys=True)
            print()
        else:
            if result.get("ok"):
                print(
                    "Enabled Civ6AgentBridge "
                    f"mod_row_id={result.get('mod_row_id')} "
                    f"group={result.get('selected_group_name')}"
                )
            else:
                print(f"Could not enable Civ6AgentBridge: {result.get('error')}", file=sys.stderr)
                raise SystemExit(1)
        return
    if args.command == "wait-state":
        try:
            state = wait_for_state(args.log, timeout=args.timeout, interval=args.interval)
        except Exception as exc:  # noqa: BLE001 - CLI should print concise bridge/log failures.
            print(f"Could not read Civ 6 bridge state: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if args.pretty:
            json.dump(state, sys.stdout, indent=2, sort_keys=True)
        else:
            json.dump(state, sys.stdout, separators=(",", ":"), sort_keys=True)
        print()
        return
    raise AssertionError(args.command)


def format_status(status: dict[str, Any]) -> str:
    mod = status.get("mod") or {}
    log = status.get("log") or {}
    options = status.get("options") or {}
    lines = [
        f"Civ 6 app: {status.get('app_path') or 'not found'}",
        f"Steam install: {status.get('steam_install_root') or 'not found'} ({status.get('steam_install_flavor')})",
        "Steam libraries: " + ", ".join(status.get("steam_library_roots") or []),
        (
            "Steam manifest: "
            f"state_flags={(status.get('steam_appmanifest') or {}).get('StateFlags')} "
            f"build={(status.get('steam_appmanifest') or {}).get('buildid')} "
            f"path={(status.get('steam_appmanifest') or {}).get('_path')}"
        ),
        f"Support root: {status.get('support_root') or 'not found'}",
        f"Mods dir: {status.get('mods_dir') or 'not found'}",
        f"Bridge installed: {mod.get('installed')} at {mod.get('installed_path')}",
        (
            "Bridge scanned/enabled: "
            f"scanned={mod.get('scanned')} enabled_in_selected_group={mod.get('enabled_in_selected_group')}"
        ),
        (
            "AppOptions: "
            f"EnableTuner={options.get('EnableTuner')} "
            f"EnableDebugMenu={options.get('EnableDebugMenu')} "
            f"EnableAudio={options.get('EnableAudio')}"
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
    if mod.get("scanned") and not mod.get("enabled_in_selected_group"):
        lines.append("Bridge is scanned but not enabled in the selected Civ 6 mod group.")
    if not mod.get("scanned"):
        lines.append("Bridge is not scanned yet; launch Civ 6 once after installing the mod.")
    if status.get("steam_install_flavor") == "windows_depot":
        lines.append(
            "Steam install appears to be the Windows depot, not a macOS Civ6.app; "
            "the macOS Lua-log bridge cannot load in this install shape."
        )
    if status.get("steam_install_flavor") == "incomplete_or_empty":
        lines.append(
            "Steam install folder is present but contains no usable Civ 6 executable/assets yet."
        )
    candidates = status.get("steam_install_candidates") or []
    external_candidates = [
        item for item in candidates
        if str(item.get("path", "")).startswith("/Volumes/")
    ]
    if external_candidates and not any(item.get("exists") for item in external_candidates):
        lines.append("External Steam library is registered, but Civ 6 is not present there yet.")
    downloading = status.get("steam_downloading_candidates") or []
    active_downloads = [item for item in downloading if item.get("exists")]
    for item in active_downloads:
        if item.get("contains_macos_app"):
            lines.append(f"Civ 6 macOS app is currently downloading/staging at {item.get('path')}.")
        elif item.get("contains_windows_launcher"):
            lines.append(f"Civ 6 Windows payload is currently downloading/staging at {item.get('path')}.")
        else:
            lines.append(f"Civ 6 download/staging directory exists at {item.get('path')}.")
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
            f"Civ6 turn={game.get('turn')} active_player={player.get('name') or player.get('id')} "
            f"leader={player.get('leader_type')} civ={player.get('civilization_type')}"
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
                f"  {unit.get('id')}:{unit.get('type')} moves={unit.get('moves_remaining')} "
                f"damage={unit.get('damage')} at=({unit.get('x')},{unit.get('y')})"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
