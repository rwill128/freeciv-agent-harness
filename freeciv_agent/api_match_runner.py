from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .codex_match_runner import (
    active_players_from_brief,
    fetch_json,
    game_over_from_brief,
    mcp_artifact_mode_for_player,
    mcp_version_for_player,
    narrative_log_for_player,
    parse_mcp_artifact_modes,
    parse_mcp_versions,
    parse_victory_modes,
    player_active_check,
    ready_players,
    start_viewers,
    wait_for_control,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run repeated API/MCP Freeciv turns.")
    parser.add_argument("--players", nargs="+", default=["AgentA", "AgentB"])
    parser.add_argument("--model", default="gpt-5.4-nano")
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        default="low",
    )
    parser.add_argument("--max-rounds", default=0, type=int)
    parser.add_argument("--turn-timeout", default=180, type=int)
    parser.add_argument("--turn-retries", default=1, type=int)
    parser.add_argument("--retry-sleep", default=10.0, type=float)
    parser.add_argument("--control-url", default="http://127.0.0.1:8787")
    parser.add_argument("--sleep", default=1.0, type=float)
    parser.add_argument("--startup-timeout", default=60.0, type=float)
    parser.add_argument("--idle-sleep", default=5.0, type=float)
    parser.add_argument(
        "--stop-file",
        default=str(ROOT / "runtime" / "run" / "stop-api-match"),
    )
    parser.add_argument("--clear-stop-file", action="store_true")
    parser.add_argument("--no-viewers", action="store_true")
    parser.add_argument("--reset-sessions", action="store_true")
    parser.add_argument("--reset-narrative", action="store_true")
    parser.add_argument("--reset-mcp-artifacts", action="store_true")
    parser.add_argument("--narrative-log", action="store_true")
    parser.add_argument("--narrative-players", nargs="*", default=[])
    parser.add_argument("--public-turn-message", action="store_true")
    parser.add_argument("--victory-modes", nargs="*", default=[], metavar="PLAYER=MODE")
    parser.add_argument("--mcp-versions", nargs="*", default=[], metavar="PLAYER=VERSION")
    parser.add_argument(
        "--mcp-artifact-mode",
        default="off",
        choices=["off", "mirror", "file-only"],
    )
    parser.add_argument("--mcp-artifact-modes", nargs="*", default=[], metavar="PLAYER=MODE")
    parser.add_argument("--mcp-artifact-preview-chars", default=800, type=int)
    parser.add_argument("--max-tool-iterations", default=24, type=int)
    parser.add_argument("--max-output-tokens", default=4096, type=int)
    parser.add_argument("--no-auto-ready", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    victory_modes = parse_victory_modes(args.victory_modes)
    mcp_versions = parse_mcp_versions(args.mcp_versions)
    mcp_artifact_modes = parse_mcp_artifact_modes(args.mcp_artifact_modes)

    if args.reset_sessions:
        reset_api_player_state(
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

    if not args.dry_run:
        wait_for_control(args.control_url, args.startup_timeout)
        if not args.no_auto_ready:
            ready_players(args.control_url, args.players)
        if not args.no_viewers:
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

        brief = (
            {"players": {name: {"phase": {"agent_is_active_phase": True}} for name in args.players}}
            if args.dry_run
            else fetch_json(f"{args.control_url.rstrip('/')}/brief")
        )
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
                "sleep": args.idle_sleep,
            }
            history.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
            write_history(history)
            time.sleep(args.idle_sleep)
            continue

        print(
            json.dumps(
                {
                    "round": round_no,
                    "players": active_players,
                    "turns": {
                        name: brief["players"].get(name, {}).get("turn")
                        for name in args.players
                    },
                },
                sort_keys=True,
            ),
            flush=True,
        )
        for player in active_players:
            event = run_turn_with_retries(
                player=player,
                round_no=round_no,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                turn_timeout=args.turn_timeout,
                control_url=args.control_url,
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
                max_tool_iterations=args.max_tool_iterations,
                max_output_tokens=args.max_output_tokens,
                dry_run=args.dry_run,
                retries=args.turn_retries,
                retry_sleep=args.retry_sleep,
            )
            history.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
            write_history(history)
            if event["returncode"] != 0:
                sys.stderr.write(event.get("stderr") or "")
                raise SystemExit(event["returncode"])
            time.sleep(args.sleep)
        round_no += 1
    write_history(history)


def run_turn_with_retries(
    *,
    player: str,
    round_no: int,
    model: str,
    reasoning_effort: str,
    turn_timeout: int,
    control_url: str,
    mcp_version: str,
    mcp_artifact_mode: str,
    mcp_artifact_preview_chars: int,
    narrative_log: bool,
    public_turn_message: bool,
    victory_mode: str,
    max_tool_iterations: int,
    max_output_tokens: int,
    dry_run: bool,
    retries: int,
    retry_sleep: float,
) -> dict[str, Any]:
    attempts = []
    for attempt_no in range(1, max(1, retries) + 1):
        active_check = None if dry_run else player_active_check(control_url, player)
        if active_check is not None and not active_check["active"]:
            return {
                "round": round_no,
                "player": player,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "mcp_version": mcp_version,
                "mcp_artifact_mode": mcp_artifact_mode,
                "returncode": 0,
                "attempts": attempts,
                "stdout": "",
                "stderr": "",
                "skipped": True,
                "skip_reason": "player_no_longer_active",
                "active_check": active_check,
            }
        command = [
            str(ROOT / "scripts" / "run-api-turn"),
            player,
            "--model",
            model,
            "--reasoning-effort",
            reasoning_effort,
            "--timeout",
            str(turn_timeout),
            "--control-url",
            control_url,
            "--mcp-version",
            mcp_version,
            "--mcp-artifact-mode",
            mcp_artifact_mode,
            "--mcp-artifact-preview-chars",
            str(mcp_artifact_preview_chars),
            "--victory-mode",
            victory_mode,
            "--max-tool-iterations",
            str(max_tool_iterations),
            "--max-output-tokens",
            str(max_output_tokens),
        ]
        if narrative_log:
            command.append("--narrative-log")
        if public_turn_message:
            command.append("--public-turn-message")
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
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        attempts.append(attempt)
        if result.returncode == 0:
            return {
                "round": round_no,
                "player": player,
                "model": model,
                "reasoning_effort": reasoning_effort,
                "mcp_version": mcp_version,
                "mcp_artifact_mode": mcp_artifact_mode,
                "narrative_log": narrative_log,
                "public_turn_message": public_turn_message,
                "victory_mode": victory_mode,
                "returncode": 0,
                "attempts": attempts,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "usage": parse_turn_usage(result.stdout),
            }
        if attempt_no < retries:
            time.sleep(retry_sleep)
    last = attempts[-1]
    return {
        "round": round_no,
        "player": player,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "mcp_version": mcp_version,
        "mcp_artifact_mode": mcp_artifact_mode,
        "narrative_log": narrative_log,
        "public_turn_message": public_turn_message,
        "victory_mode": victory_mode,
        "returncode": last["returncode"],
        "attempts": attempts,
        "stdout": last["stdout"],
        "stderr": last["stderr"],
    }


def parse_turn_usage(stdout: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("usage"), dict):
        return payload["usage"]
    return None


def reset_api_player_state(
    players: list[str],
    *,
    reset_narrative: bool,
    reset_mcp_artifacts: bool,
) -> None:
    for player in players:
        workspace = ROOT / "players" / player
        (workspace / ".api-agent-session.json").unlink(missing_ok=True)
        if reset_narrative:
            (workspace / "narrative.md").unlink(missing_ok=True)
        if reset_mcp_artifacts:
            shutil.rmtree(workspace / "mcp-artifacts", ignore_errors=True)


def reset_narrative_logs(players: list[str]) -> None:
    for player in players:
        (ROOT / "players" / player / "narrative.md").unlink(missing_ok=True)


def reset_mcp_artifacts(players: list[str]) -> None:
    for player in players:
        shutil.rmtree(ROOT / "players" / player / "mcp-artifacts", ignore_errors=True)


def write_history(history: list[dict[str, Any]]) -> None:
    out_dir = ROOT / "runtime" / "matches"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "latest-api-match-history.json"
    path.write_text(json.dumps(history, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
