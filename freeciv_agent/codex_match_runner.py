from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run repeated Codex Freeciv turns.")
    parser.add_argument("--players", nargs="+", default=["AgentA", "AgentB"])
    parser.add_argument("--model", help="Codex model to use. Omit to use Codex default.")
    parser.add_argument(
        "--reasoning-effort",
        choices=["minimal", "low", "medium", "high"],
        help="Codex model reasoning effort config for every player turn.",
    )
    parser.add_argument(
        "--fallback-model",
        action="append",
        default=[],
        help='Fallback model to try when a turn fails. Use "default" to omit --model.',
    )
    parser.add_argument(
        "--max-rounds",
        default=0,
        type=int,
        help="Maximum active-player turns to run. Use 0 for no limit.",
    )
    parser.add_argument("--turn-timeout", default=600, type=int)
    parser.add_argument("--turn-retries", default=2, type=int)
    parser.add_argument(
        "--interface",
        default="cli",
        choices=["cli", "mcp"],
        help="Default game interface exposed to Codex players.",
    )
    parser.add_argument(
        "--mcp-players",
        nargs="*",
        default=[],
        help="Players that should use MCP even when --interface is cli.",
    )
    parser.add_argument(
        "--mcp-versions",
        nargs="*",
        default=[],
        metavar="PLAYER=VERSION",
        help="Per-player MCP interface version, e.g. AgentC=v1 AgentD=v2.",
    )
    parser.add_argument(
        "--mcp-artifact-mode",
        default="off",
        choices=["off", "mirror", "file-only"],
        help="MCP result file mode for MCP players.",
    )
    parser.add_argument(
        "--mcp-artifact-modes",
        nargs="*",
        default=[],
        metavar="PLAYER=MODE",
        help="Per-player MCP artifact mode, e.g. AgentD=file-only.",
    )
    parser.add_argument(
        "--mcp-artifact-preview-chars",
        default=800,
        type=int,
        help="Preview characters returned for MCP file-only mode.",
    )
    parser.add_argument(
        "--narrative-log",
        action="store_true",
        help="Enable player-authored narrative.md entries for every player.",
    )
    parser.add_argument(
        "--narrative-players",
        nargs="*",
        default=[],
        help="Players allowed/instructed to maintain narrative.md, even without --narrative-log.",
    )
    parser.add_argument(
        "--public-turn-message",
        action="store_true",
        help="Require every player to send one public in-game chat message each turn.",
    )
    parser.add_argument("--retry-sleep", default=15.0, type=float)
    parser.add_argument("--control-url", default="http://127.0.0.1:8787")
    parser.add_argument("--sleep", default=1.0, type=float)
    parser.add_argument(
        "--startup-timeout",
        default=60.0,
        type=float,
        help="Seconds to wait for the control API before starting the match loop.",
    )
    parser.add_argument(
        "--idle-sleep",
        default=5.0,
        type=float,
        help="Seconds to wait when no active player can be determined.",
    )
    parser.add_argument(
        "--stop-file",
        default=str(ROOT / "runtime" / "run" / "stop-codex-match"),
        help="If this file exists, stop the match loop cleanly.",
    )
    parser.add_argument(
        "--clear-stop-file",
        action="store_true",
        help="Remove the stop file before entering the match loop.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-viewers",
        action="store_true",
        help="Do not start player-perspective GTK observer clients before round 1.",
    )
    parser.add_argument(
        "--reset-sessions",
        action="store_true",
        help="Delete stored per-player Codex session ids and baseline note files before round 1.",
    )
    parser.add_argument(
        "--reset-narrative",
        action="store_true",
        help="Delete per-player narrative.md files before round 1.",
    )
    parser.add_argument(
        "--reset-mcp-artifacts",
        action="store_true",
        help="Delete per-player mcp-artifacts directories before round 1.",
    )
    parser.add_argument(
        "--victory-modes",
        nargs="*",
        default=[],
        metavar="PLAYER=MODE",
        help="Per-player strategic focus, e.g. AgentA=conquest AgentB=spacerace.",
    )
    parser.add_argument(
        "--no-auto-ready",
        action="store_true",
        help="Do not mark players ready before entering the match loop.",
    )
    args = parser.parse_args()

    victory_modes = parse_victory_modes(args.victory_modes)
    mcp_versions = parse_mcp_versions(args.mcp_versions)
    mcp_artifact_modes = parse_mcp_artifact_modes(args.mcp_artifact_modes)

    if args.dry_run:
        history = []
        for player in args.players:
            event = run_turn_with_retries(
                player=player,
                round_no=1,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                fallback_models=args.fallback_model,
                turn_timeout=args.turn_timeout,
                control_url=args.control_url,
                interface=interface_for_player(
                    player,
                    default=args.interface,
                    mcp_players=args.mcp_players,
                ),
                mcp_version=mcp_version_for_player(player, mcp_versions),
                mcp_artifact_mode=mcp_artifact_mode_for_player(
                    player,
                    default=args.mcp_artifact_mode,
                    modes=mcp_artifact_modes,
                ),
                mcp_artifact_preview_chars=args.mcp_artifact_preview_chars,
                narrative_log=narrative_log_for_player(
                    player,
                    all_players=args.narrative_log,
                    narrative_players=args.narrative_players,
                ),
                public_turn_message=args.public_turn_message,
                victory_mode=victory_modes.get(player, "balanced"),
                dry_run=True,
                retries=1,
                retry_sleep=args.retry_sleep,
            )
            history.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
        write_history(history, dry_run=True)
        return

    if args.reset_sessions:
        reset_player_state(
            args.players,
            reset_narrative=(
                args.reset_narrative
                or args.narrative_log
                or bool(args.narrative_players)
            ),
            reset_mcp_artifacts=args.reset_mcp_artifacts,
        )
    else:
        if args.reset_narrative:
            reset_narrative_logs(args.players)
        if args.reset_mcp_artifacts:
            reset_mcp_artifacts(args.players)

    stop_file = Path(args.stop_file)
    if args.clear_stop_file:
        stop_file.unlink(missing_ok=True)

    wait_for_control(args.control_url, args.startup_timeout)

    if not args.no_auto_ready and not args.dry_run:
        ready_players(args.control_url, args.players)

    if not args.no_viewers and not args.dry_run:
        start_viewers(args.control_url, args.players)

    history: list[dict[str, Any]] = []
    round_no = 1
    while args.max_rounds <= 0 or round_no <= args.max_rounds:
        if stop_file.exists():
            event = {
                "event": "stop_file_detected",
                "round": round_no,
                "stop_file": str(stop_file),
            }
            history.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
            write_history(history)
            break

        brief = fetch_json(f"{args.control_url.rstrip('/')}/brief")
        game_over = game_over_from_brief(brief, args.players)
        if game_over["game_over"]:
            event = {
                "event": "game_over_detected",
                "round": round_no,
                "game_over": game_over,
                "turns": {
                    name: brief["players"].get(name, {}).get("turn")
                    for name in args.players
                },
            }
            history.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
            write_history(history)
            break

        active_players = active_players_from_brief(brief, args.players)
        if not active_players:
            event = {
                "event": "no_active_player_detected",
                "round": round_no,
                "phase": {
                    name: brief["players"].get(name, {}).get("phase")
                    for name in args.players
                },
                "turns": {
                    name: brief["players"].get(name, {}).get("turn")
                    for name in args.players
                },
                "sleep": args.idle_sleep,
            }
            history.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
            write_history(history)
            time.sleep(args.idle_sleep)
            continue

        players = active_players
        print(
            json.dumps(
                {
                    "round": round_no,
                    "players": players,
                    "active_players_detected": active_players,
                    "turns": {
                        name: brief["players"].get(name, {}).get("turn")
                        for name in args.players
                    },
                },
                sort_keys=True,
            ),
            flush=True,
        )
        for player in players:
            if stop_file.exists():
                event = {
                    "event": "stop_file_detected",
                    "round": round_no,
                    "stop_file": str(stop_file),
                }
                history.append(event)
                print(json.dumps(event, sort_keys=True), flush=True)
                write_history(history)
                return
            event = run_turn_with_retries(
                player=player,
                round_no=round_no,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                fallback_models=args.fallback_model,
                turn_timeout=args.turn_timeout,
                control_url=args.control_url,
                interface=interface_for_player(
                    player,
                    default=args.interface,
                    mcp_players=args.mcp_players,
                ),
                mcp_version=mcp_version_for_player(player, mcp_versions),
                mcp_artifact_mode=mcp_artifact_mode_for_player(
                    player,
                    default=args.mcp_artifact_mode,
                    modes=mcp_artifact_modes,
                ),
                mcp_artifact_preview_chars=args.mcp_artifact_preview_chars,
                narrative_log=narrative_log_for_player(
                    player,
                    all_players=args.narrative_log,
                    narrative_players=args.narrative_players,
                ),
                public_turn_message=args.public_turn_message,
                victory_mode=victory_modes.get(player, "balanced"),
                dry_run=args.dry_run,
                retries=args.turn_retries,
                retry_sleep=args.retry_sleep,
            )
            history.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
            write_history(history)
            if event["returncode"] != 0:
                write_history(history)
                sys.stderr.write(event["stderr"])
                raise SystemExit(event["returncode"])
            time.sleep(args.sleep)
        round_no += 1
    write_history(history)


def run_turn_with_retries(
    *,
    player: str,
    round_no: int,
    model: str | None,
    reasoning_effort: str | None,
    fallback_models: list[str],
    turn_timeout: int,
    control_url: str,
    interface: str,
    mcp_version: str,
    mcp_artifact_mode: str,
    mcp_artifact_preview_chars: int,
    narrative_log: bool,
    public_turn_message: bool,
    victory_mode: str,
    dry_run: bool,
    retries: int,
    retry_sleep: float,
) -> dict[str, Any]:
    model_attempts: list[str | None] = [model]
    for fallback in fallback_models:
        model_attempts.append(None if fallback == "default" else fallback)
    model_attempts = dedupe_models(model_attempts)

    attempts = []
    for attempt_no in range(1, max(1, retries) + 1):
        for attempt_model in model_attempts:
            active_check = None if dry_run else player_active_check(control_url, player)
            if active_check is not None and not active_check["active"]:
                return {
                    "round": round_no,
                    "player": player,
                    "interface": interface,
                    "mcp_version": mcp_version if interface == "mcp" else None,
                    "mcp_artifact_mode": mcp_artifact_mode if interface == "mcp" else None,
                    "narrative_log": narrative_log,
                    "public_turn_message": public_turn_message,
                    "victory_mode": victory_mode,
                    "returncode": 0,
                    "model": attempt_model or "default",
                    "reasoning_effort": reasoning_effort,
                    "attempts": attempts,
                    "stdout": "",
                    "stderr": "",
                    "skipped": True,
                    "skip_reason": "player_no_longer_active",
                    "active_check": active_check,
                }
            command = [
                str(ROOT / "scripts" / "run-codex-turn"),
                player,
                "--timeout",
                str(turn_timeout),
                "--control-url",
                control_url,
                "--interface",
                interface,
                "--mcp-version",
                mcp_version,
                "--mcp-artifact-mode",
                mcp_artifact_mode,
                "--mcp-artifact-preview-chars",
                str(mcp_artifact_preview_chars),
                "--victory-mode",
                victory_mode,
            ]
            if reasoning_effort:
                command.extend(["--reasoning-effort", reasoning_effort])
            if narrative_log:
                command.append("--narrative-log")
            if public_turn_message:
                command.append("--public-turn-message")
            if attempt_model:
                command.extend(["--model", attempt_model])
            if dry_run:
                command.append("--dry-run")
            result = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            attempt = {
                "attempt": attempt_no,
                "model": attempt_model or "default",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            attempts.append(attempt)
            if result.returncode == 0:
                return {
                    "round": round_no,
                    "player": player,
                    "interface": interface,
                    "mcp_version": mcp_version if interface == "mcp" else None,
                    "mcp_artifact_mode": mcp_artifact_mode if interface == "mcp" else None,
                    "narrative_log": narrative_log,
                    "public_turn_message": public_turn_message,
                    "victory_mode": victory_mode,
                    "returncode": 0,
                    "model": attempt_model or "default",
                    "reasoning_effort": reasoning_effort,
                    "attempts": attempts,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            if is_usage_limit_error(result.stdout, result.stderr):
                continue
        if attempt_no < retries:
            time.sleep(retry_sleep)
    last = attempts[-1]
    return {
        "round": round_no,
        "player": player,
        "interface": interface,
        "mcp_version": mcp_version if interface == "mcp" else None,
        "mcp_artifact_mode": mcp_artifact_mode if interface == "mcp" else None,
        "narrative_log": narrative_log,
        "public_turn_message": public_turn_message,
        "victory_mode": victory_mode,
        "returncode": last["returncode"],
        "model": last["model"],
        "reasoning_effort": reasoning_effort,
        "attempts": attempts,
        "stdout": last["stdout"],
        "stderr": last["stderr"],
    }


def interface_for_player(player: str, *, default: str, mcp_players: list[str]) -> str:
    return "mcp" if player in set(mcp_players) else default


def dedupe_models(models: list[str | None]) -> list[str | None]:
    result: list[str | None] = []
    seen: set[str] = set()
    for model in models:
        key = model or "default"
        if key in seen:
            continue
        seen.add(key)
        result.append(model)
    return result


def mcp_version_for_player(player: str, versions: dict[str, str]) -> str:
    return versions.get(player, "v1")


def mcp_artifact_mode_for_player(player: str, *, default: str, modes: dict[str, str]) -> str:
    return modes.get(player, default)


def narrative_log_for_player(
    player: str,
    *,
    all_players: bool,
    narrative_players: list[str],
) -> bool:
    return all_players or player in set(narrative_players)


def parse_victory_modes(items: list[str]) -> dict[str, str]:
    modes: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"invalid --victory-modes entry {item!r}; expected PLAYER=MODE")
        player, mode = item.split("=", 1)
        player = player.strip()
        mode = mode.strip()
        if not player or not mode:
            raise SystemExit(f"invalid --victory-modes entry {item!r}; expected PLAYER=MODE")
        modes[player] = mode
    return modes


def parse_mcp_versions(items: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    aliases = {
        "0": "v0",
        "legacy": "v0",
        "compact": "v0",
        "1": "v1",
        "readable": "v1",
        "details": "v1",
        "2": "v2",
        "rich": "v2",
        "focused": "v2",
    }
    for item in items:
        if "=" not in item:
            raise SystemExit(f"invalid --mcp-versions entry {item!r}; expected PLAYER=VERSION")
        player, version = item.split("=", 1)
        player = player.strip()
        version = version.strip().lower().replace("_", "-")
        version = aliases.get(version, version)
        if not player or version not in {"v0", "v1", "v2"}:
            raise SystemExit(
                f"invalid --mcp-versions entry {item!r}; expected PLAYER=v0|v1|v2"
            )
        versions[player] = version
    return versions


def parse_mcp_artifact_modes(items: list[str]) -> dict[str, str]:
    modes: dict[str, str] = {}
    valid = {"off", "mirror", "file-only"}
    aliases = {
        "0": "off",
        "none": "off",
        "disabled": "off",
        "file": "file-only",
        "filesystem": "file-only",
        "files": "file-only",
    }
    for item in items:
        if "=" not in item:
            raise SystemExit(f"invalid --mcp-artifact-modes entry {item!r}; expected PLAYER=MODE")
        player, mode = item.split("=", 1)
        player = player.strip()
        mode = mode.strip().lower().replace("_", "-")
        mode = aliases.get(mode, mode)
        if not player or mode not in valid:
            raise SystemExit(
                f"invalid --mcp-artifact-modes entry {item!r}; expected PLAYER=off|mirror|file-only"
            )
        modes[player] = mode
    return modes


def reset_player_state(
    players: list[str],
    *,
    reset_narrative: bool = False,
    reset_mcp_artifacts: bool = False,
) -> None:
    for player in players:
        workspace = ROOT / "players" / player
        (workspace / ".codex-session.json").unlink(missing_ok=True)
        for filename in ("memory.md", "plan.md", "notes.md"):
            (workspace / filename).unlink(missing_ok=True)
        if reset_narrative:
            (workspace / "narrative.md").unlink(missing_ok=True)
        if reset_mcp_artifacts:
            shutil.rmtree(workspace / "mcp-artifacts", ignore_errors=True)


def reset_narrative_logs(players: list[str]) -> None:
    for player in players:
        workspace = ROOT / "players" / player
        (workspace / "narrative.md").unlink(missing_ok=True)


def reset_mcp_artifacts(players: list[str]) -> None:
    for player in players:
        workspace = ROOT / "players" / player
        shutil.rmtree(workspace / "mcp-artifacts", ignore_errors=True)


def is_usage_limit_error(stdout: str, stderr: str) -> bool:
    text = f"{stdout}\n{stderr}".lower()
    return "usage limit" in text or "try again at" in text


def fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode())
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object from {url}")
    return payload


def post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode())
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object from {url}")
    return payload


def wait_for_control(control_url: str, timeout: float) -> None:
    url = f"{control_url.rstrip('/')}/brief"
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            fetch_json(url)
            return
        except Exception as exc:  # noqa: BLE001 - startup polling should report last failure.
            last_error = exc
            time.sleep(1.0)
    raise RuntimeError(f"control API did not become ready at {url}: {last_error}")


def ready_players(control_url: str, players: list[str]) -> None:
    base = control_url.rstrip("/")
    for player in players:
        post_json(f"{base}/players/{player}/ready", {"ready": True})


def active_players_from_brief(brief: dict[str, Any], configured: list[str]) -> list[str]:
    players = brief.get("players", {})
    active = []
    for name in configured:
        info = players.get(name, {})
        phase = info.get("phase", {})
        if phase.get("agent_is_active_phase") is True:
            active.append(name)
    if active:
        return active
    movement_candidates = players_with_known_moves(brief, configured)
    return movement_candidates if len(movement_candidates) == 1 else []


def player_active_check(control_url: str, player: str) -> dict[str, Any]:
    brief = fetch_json(f"{control_url.rstrip('/')}/brief")
    info = (brief.get("players") or {}).get(player, {})
    phase = info.get("phase") or {}
    movement_candidates = players_with_known_moves(brief, list((brief.get("players") or {}).keys()))
    return {
        "active": (
            phase.get("agent_is_active_phase") is True
            or (
                phase.get("agent_is_active_phase") is None
                and movement_candidates == [player]
            )
        ),
        "turn": info.get("turn"),
        "phase": phase,
        "movement_active_fallback": movement_candidates == [player],
    }


def players_with_known_moves(brief: dict[str, Any], configured: list[str]) -> list[str]:
    players = brief.get("players", {})
    active = []
    for name in configured:
        info = players.get(name, {})
        if has_units_with_known_moves(info):
            active.append(name)
    return active


def has_units_with_known_moves(player_info: dict[str, Any]) -> bool:
    units = player_info.get("units", [])
    if not isinstance(units, list):
        return False
    for unit in units:
        if not isinstance(unit, dict):
            continue
        movesleft = unit.get("movesleft")
        if isinstance(movesleft, (int, float)) and movesleft > 0:
            return True
    return False


def game_over_from_brief(brief: dict[str, Any], configured: list[str]) -> dict[str, Any]:
    players = brief.get("players", {})
    alive = []
    dead = []
    unknown = []
    for name in configured:
        info = players.get(name, {})
        economy = info.get("economy") or {}
        is_alive = economy.get("is_alive")
        if is_alive is True:
            alive.append(name)
        elif is_alive is False:
            dead.append(name)
        else:
            unknown.append(name)
    return {
        "game_over": len(alive) == 1 and not unknown,
        "alive": alive,
        "dead": dead,
        "unknown": unknown,
    }


def write_history(history: list[dict[str, Any]], *, dry_run: bool = False) -> None:
    out_dir = ROOT / "runtime" / "matches"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        "latest-codex-match-dry-run-history.json"
        if dry_run
        else "latest-codex-match-history.json"
    )
    path = out_dir / filename
    path.write_text(json.dumps(history, indent=2, sort_keys=True), encoding="utf-8")


def start_viewers(control_url: str, players: list[str]) -> None:
    if len(players) < 2:
        raise RuntimeError("player-perspective viewers require at least two players")
    env = {
        **dict(os.environ),
        "CONTROL_URL": control_url,
        "PLAYER_A": players[0],
        "PLAYER_B": players[1],
    }
    result = subprocess.run(
        [str(ROOT / "scripts" / "start-player-viewers")],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
