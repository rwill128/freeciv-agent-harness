from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "turn-result.schema.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Codex-controlled Freeciv turn.")
    parser.add_argument("player")
    parser.add_argument("--model", help="Codex model to use. Omit to use Codex default.")
    parser.add_argument(
        "--reasoning-effort",
        choices=["minimal", "low", "medium", "high"],
        help="Codex model reasoning effort config for this turn.",
    )
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--timeout", default=600, type=int)
    parser.add_argument("--control-url", default="http://127.0.0.1:8787")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument(
        "--interface",
        default="cli",
        choices=["cli", "mcp"],
        help="Game interface exposed to the Codex player.",
    )
    parser.add_argument(
        "--sandbox",
        default="danger-full-access",
        choices=["read-only", "workspace-write", "danger-full-access"],
        help="Sandbox mode for the initial Codex session. Use danger-full-access for localhost game control.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--reset-session",
        action="store_true",
        help="Delete the stored Codex session id before running this turn.",
    )
    parser.add_argument(
        "--victory-mode",
        default="balanced",
        help="Assigned strategic victory focus for this player.",
    )
    parser.add_argument(
        "--mcp-version",
        default="v1",
        help="MCP interface version when --interface=mcp: v0, v1, or v2.",
    )
    parser.add_argument(
        "--mcp-artifact-mode",
        default="off",
        choices=["off", "mirror", "file-only"],
        help="MCP result file mode: off, mirror, or file-only.",
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
        help="Allow and instruct this player to append one end-of-turn entry to narrative.md.",
    )
    parser.add_argument(
        "--public-turn-message",
        action="store_true",
        help="Require one public in-game chat message during this turn.",
    )
    args = parser.parse_args()

    workspace = ROOT / "players" / args.player
    if not workspace.is_dir():
        raise SystemExit(f"missing player workspace: {workspace}")
    session_path = workspace / ".codex-session.json"
    if args.reset_session:
        session_path.unlink(missing_ok=True)

    out_dir = ROOT / "runtime" / "turns"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = out_dir / f"{stamp}-{args.player}-turn-result.json"

    prompt = build_prompt(
        args.player,
        args.control_url,
        interface=args.interface,
        victory_mode=args.victory_mode,
        mcp_version=args.mcp_version,
        mcp_artifact_mode=args.mcp_artifact_mode,
        narrative_log=args.narrative_log,
        public_turn_message=args.public_turn_message,
    )
    session_payload = load_session_payload(session_path)
    session_id = session_id_from_payload(session_payload, session_path)
    requested_model = args.model or "default"
    stored_model = session_payload.get("model")
    if session_id and isinstance(stored_model, str) and stored_model != requested_model:
        raise SystemExit(
            f"refusing to resume {args.player} session {session_id} with model "
            f"{requested_model!r}; session was created/resumed with "
            f"{stored_model!r}. Reset the session for a fresh context or keep "
            "the same MODEL for the match."
        )
    command = build_codex_command(
        codex_bin=args.codex_bin,
        workspace=workspace,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        schema=Path(args.schema),
        sandbox=args.sandbox,
        output_path=output_path,
        prompt=prompt,
        session_id=session_id,
        player=args.player,
        control_url=args.control_url,
        interface=args.interface,
        mcp_version=args.mcp_version,
        mcp_artifact_mode=args.mcp_artifact_mode,
        mcp_artifact_preview_chars=args.mcp_artifact_preview_chars,
    )

    if args.dry_run:
        print(" ".join(shell_quote(part) for part in command))
        return

    result = subprocess.run(
        command,
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=args.timeout,
        check=False,
    )
    write_transcript(out_dir, stamp, args.player, result)

    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    try:
        transcript_evidence = validate_tool_use(
            result.stdout,
            interface=args.interface,
            workspace=workspace,
            narrative_log=args.narrative_log,
            public_turn_message=args.public_turn_message,
            mcp_artifact_mode=args.mcp_artifact_mode,
        )
    except SystemExit:
        quarantine_rejected_result(output_path)
        raise

    new_session_id = extract_session_id(result.stdout)
    if new_session_id:
        save_session_id(
            session_path,
            {
                "session_id": new_session_id,
                "player": args.player,
                "model": requested_model,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
    elif session_id is None:
        raise SystemExit(
            "Codex completed but no session id was found in --json output; "
            f"see transcript in {out_dir}"
        )

    try:
        payload = load_result(output_path)
        if args.narrative_log and transcript_evidence["narrative_observed"]:
            normalize_narrative_result(payload)
            output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validate_minimal_result(payload, args.player, public_turn_message=args.public_turn_message)
        if not payload["phase_done"]:
            raise SystemExit(
                f"{args.player} result reported phase_done=false; "
                f"see {output_path}"
            )
    except SystemExit:
        quarantine_rejected_result(output_path)
        raise
    json.dump(
        {
            "ok": True,
            "player": args.player,
            "result_file": str(output_path),
            "session_file": str(session_path),
            "session_id": new_session_id or session_id,
            "result": payload,
        },
        sys.stdout,
        indent=2,
        sort_keys=True,
    )
    print()


def build_prompt(
    player: str,
    control_url: str,
    *,
    interface: str = "cli",
    victory_mode: str = "balanced",
    mcp_version: str = "v1",
    mcp_artifact_mode: str = "off",
    narrative_log: bool = False,
    public_turn_message: bool = False,
) -> str:
    victory_section = victory_mode_prompt(victory_mode)
    narrative_section = narrative_log_prompt(narrative_log, interface=interface)
    public_message_section = public_turn_message_prompt(public_turn_message, interface=interface)
    if interface == "mcp":
        artifact_section = mcp_artifact_prompt(mcp_version, mcp_artifact_mode)
        extra_tools = ""
        if mcp_version in {"v1", "v2"}:
            extra_tools = """- `units_detail`
- `cities_detail`
- `economy_detail`
"""
        if mcp_version == "v2":
            extra_tools += """- `turn_dashboard`
- `units_ready`
- `city_production_options`
- `research_options`
- `map_topology`
- `recent_messages`
- `state_snapshot`
"""
        return f"""Play exactly one Freeciv turn as {player}.

{victory_section}

First call `tool_search` for Freeciv/freeciv MCP tools so the Freeciv tools are
loaded. Then use only the Freeciv MCP tools to inspect and act. The MCP server
is already scoped to {player}; do not try to inspect or control any other
player.
Do not use shell commands. Do not write memory/plan/notes files.
{narrative_section}
{public_message_section}

Hard opening rule: if `brief` or any other state view shows you have zero
cities and an owned Settlers unit, you must call `found_city` before any
research change, movement, worker activity, narrative entry, or `phase_done`.
Call `found_city` with no `unit_id` unless there is a specific reason to choose
a listed legal founder. A turn with zero cities cannot be completed by
`phase_done`.

MCP interface version: {mcp_version}
MCP artifact mode: {mcp_artifact_mode}
If artifact mode is `mirror` or `file-only`, MCP tool results are also written
under this player's workspace in `mcp-artifacts/`. In `file-only` mode, read
the referenced artifact file when you need the full result.
{artifact_section}

Useful MCP tools:
- `brief`
{extra_tools}- `production_targets`
- `messages`
- `valid_moves`
- `ascii_view`
- `local_view`
- `narrative_read` if narrative log mode is enabled and you need prior story context
- `narrative_append` exactly once at the end if narrative log mode is enabled
- `move_unit`
- `unit_activity`
- `found_city`
- `set_city_production`
- `set_rates`
- `set_research`
- `set_tech_goal`
- `say` if you want to communicate publicly
- `phase_done`

Suggested turn flow:
1. Call `brief`.
2. If you have no cities, call `found_city` immediately with no `unit_id`.
   It will choose a legal founding unit by asking Freeciv whether Found City is
   legal; do not spend the opening turn moving the founding unit or assigning it
   worker activity first.
3. For v2, call `research_options` before making research claims. If changing
   research helps the assigned victory focus, call `set_research` with an exact
   available technology name. If you do not call `set_research`, describe the
   research as "kept current research on X" or "left research unchanged", not
   as something you set, changed, or aligned this turn.
4. Inspect local views or valid moves for units that need action.
5. Issue useful legal actions quickly.
6. If public turn message mode is enabled, call `say` exactly once with a
   public in-game message summarizing your turn stance or intent.
7. Call `phase_done` with an `intent` string describing what you tried to do and why.

This is a real match turn, not a minimal smoke test. Prefer to act with every
strategically useful unit listed by `turn_dashboard`, `units_ready`, or `brief`
before ending phase. You may leave a ready unit unused only when moving or
assigning it would be strategically harmful, redundant, or illegal; if so,
mention that briefly in the private phase-done intent.

For `unit_activity`, read `result.estimate` and `retry_policy`. If the result is
`already_active` or `sent_pending`, do not repeat the same activity order during
this turn; inspect or act with another unit, choose a different action, or end
phase.

Control server behind MCP: {control_url}

Return only JSON matching the provided schema. Use `turn_summary` to briefly
summarize the turn for the match log; do not write or update memory, plan, or
notes files. Set `phase_done` to true only if the `phase_done` MCP tool
succeeded. Set `private_intent` to the same private note you submitted through
the `phase_done` tool. If public turn message mode is enabled, set
`public_message` to the exact public chat message you sent with `say`. In
`actions_taken`, `turn_summary`, narrative entries, `public_message`, and
`private_intent`, do not claim you performed an action unless you actually
called the corresponding MCP tool successfully during this invocation.
"""

    return f"""Play exactly one Freeciv turn as {player}.

{victory_section}

Use only the local `bin/game` command to inspect and act. The command is already
scoped to {player}; do not try to inspect or control any other player.
Do not use shell pipes, redirects, `bin/game state`, or `--json` on compact
views. The baseline player is intentionally limited to concise canonical views.
Do not write memory/plan/notes files.
{narrative_section}
{public_message_section}

Hard opening rule: if `bin/game brief` or any other state view shows you have
zero cities and an owned Settlers unit, you must run `bin/game found-city`
before any research change, movement, worker activity, narrative entry, or
`bin/game phase-done`. A turn with zero cities cannot be completed by
phase-done.

Useful inspection commands:
- `bin/game brief`
- `bin/game ruleset`
- `bin/game production-targets`
- `bin/game messages --limit 10`
- `bin/game say "message to all players"` when public turn message mode is enabled
- `bin/game narrative "markdown entry"` when narrative log mode is enabled
- `bin/game found-city --city-name <name>`
- `bin/game valid-moves <unit_id>`
- `bin/game ascii-view --unit-id <unit_id> --text`
- `bin/game local-view --unit-id <unit_id>`

Suggested turn flow:
1. Run `bin/game brief`.
2. If you have no cities, run `bin/game found-city --city-name <name>`
   immediately with no `--unit-id`. The command asks Freeciv whether Found City
   is legal and can choose a legal founding unit; do not spend the opening turn
   moving the founding unit or assigning it worker activity first.
3. Inspect local views or valid moves for units that need action.
4. Issue useful legal actions quickly.
5. If public turn message mode is enabled, run `bin/game say "public message"` exactly once.
6. Run `bin/game phase-done --intent "private note about what you tried to do and why"`.

This is a real match turn, not a minimal smoke test. Prefer to act with every
strategically useful unit listed by `bin/game brief` before ending phase. You
may leave a ready unit unused only when moving or assigning it would be
strategically harmful, redundant, or illegal; if so, mention that briefly in
the private phase-done intent.

For `bin/game unit-activity`, read the printed Result and Repeat lines. If the
result is `already_active` or `sent_pending`, do not repeat the same activity
order during this turn; inspect or act with another unit, choose a different
action, or end phase.

If prior context says localhost or `bin/game` was blocked with "Operation not
permitted", re-check with `bin/game brief` anyway. That was a runner sandbox
configuration issue and may have been fixed for this invocation.

Control server: {control_url}

Return only JSON matching the provided schema. Use `turn_summary` to briefly
summarize the turn for the match log; do not write or update memory, plan, or
notes files. Set `phase_done` to true only if `bin/game phase-done` succeeded.
Set `private_intent` to the same private note you submitted with
`phase-done --intent`. If public turn message mode is enabled, set
`public_message` to the exact public chat message you sent with `bin/game say`.
"""


def narrative_log_prompt(enabled: bool, *, interface: str) -> str:
    if not enabled:
        return "Do not edit files."
    if interface == "mcp":
        return """Narrative log mode is enabled. At the end of this turn, you must call
the `narrative_append` MCP tool exactly once before your final JSON answer. The
turn validator rejects the turn if this tool call is omitted. This
writes a visible story entry to `narrative.md` for post-game analysis; it is not
hidden chain-of-thought. Keep it concise and include only:
- turn/year if known
- what changed this turn
- actions you took
- what you are trying to set up next

Use `narrative_read` only if you need to inspect the existing story log. Do not
edit `narrative.md` directly. Do not use shell commands for narrative logging."""
    return """Narrative log mode is enabled. At the end of this turn, append exactly one
Markdown entry by running `bin/game narrative "..."` before your final JSON
answer. The turn validator rejects the turn if this command is omitted. This writes a visible story entry to `narrative.md` for post-game
analysis; it is not hidden chain-of-thought. Keep it concise and include only:
- turn/year if known
- what changed this turn
- actions you took
- what you are trying to set up next

Do not edit `narrative.md` directly. Use only `bin/game narrative` for narrative
logging."""


def public_turn_message_prompt(enabled: bool, *, interface: str) -> str:
    if not enabled:
        return ""
    if interface == "mcp":
        return """Public turn message mode is enabled. During every turn, you must call the
`say` MCP tool exactly once with a short public in-game chat message. The turn
validator rejects the turn if this tool call is omitted. This message is visible
to other players, so it may be strategic, diplomatic, threatening, misleading,
or factual, but it must not reveal hidden chain-of-thought. Put the exact same
text in the final JSON field `public_message`."""
    return """Public turn message mode is enabled. During every turn, you must run
`bin/game say "..."` exactly once with a short public in-game chat message. The
turn validator rejects the turn if this command is omitted. This message is
visible to other players, so it may be strategic, diplomatic, threatening,
misleading, or factual, but it must not reveal hidden chain-of-thought. Put the
exact same text in the final JSON field `public_message`."""


def mcp_artifact_prompt(mcp_version: str, mcp_artifact_mode: str) -> str:
    if mcp_version == "v2" and mcp_artifact_mode == "file-only":
        return """Bulk filesystem-artifact condition: call `state_snapshot` once near the start of
the turn so the full decoded current-state payload is written to
`mcp-artifacts/`. Use the returned artifact path as the bulk reference file;
read only the parts you need for the decision."""
    return ""


def victory_mode_prompt(victory_mode: str) -> str:
    mode = victory_mode.strip().lower().replace("_", "-")
    prompts = {
        "conquest": (
            "Assigned victory focus: CONQUEST. Play aggressively for military "
            "dominance: expand enough to support production, build and preserve "
            "attack/defense units, scout enemy locations, defend cities, and "
            "look for opportunities to capture enemy cities or cripple enemy "
            "expansion. Do not drift into passive economy-only play."
        ),
        "spacerace": (
            "Assigned victory focus: SPACERACE. Play aggressively for long-run "
            "science and production: expand, improve high-trade/high-shield "
            "tiles, prioritize research and infrastructure, keep enough defense "
            "to survive, and choose technologies/builds that accelerate a future "
            "spaceship path. Do not ignore expansion or defense."
        ),
        "culture": (
            "Assigned victory focus: CULTURE. Play aggressively for cultural and "
            "city-development dominance if the running server enables culture, "
            "while still pursuing conquest defense if culture is unavailable. "
            "Favor growth, wonders, happiness/science infrastructure, and city "
            "survival. Verify active victory settings when the interface exposes "
            "them; do not assume culture is active."
        ),
        "score": (
            "Assigned victory focus: SCORE / ENDTURN FALLBACK. Maximize empire "
            "strength across cities, population, technology, production, wonders, "
            "and survival. Expand and improve aggressively, avoid losing cities, "
            "and build enough military to deter conquest while accumulating the "
            "strongest overall position."
        ),
        "allied": (
            "Assigned victory focus: ALLIED / DIPLOMATIC. Pursue survival, "
            "communication, and mutually beneficial diplomacy where tools allow "
            "it, while building enough economy and defense not to be conquered. "
            "If treaty tools are unavailable, use public chat strategically and "
            "play a strong backup empire game."
        ),
        "balanced": (
            "Assigned victory focus: BALANCED. Pursue the strongest practical "
            "position from current state: expansion, defense, economy, research, "
            "and tactical opportunities."
        ),
    }
    return prompts.get(mode, f"Assigned victory focus: {victory_mode}. Interpret this as the primary strategic objective for every turn while still defending your civilization and keeping the empire functional.")


def build_codex_command(
    *,
    codex_bin: str,
    workspace: Path,
    model: str | None,
    reasoning_effort: str | None,
    schema: Path,
    sandbox: str,
    output_path: Path,
    prompt: str,
    session_id: str | None,
    player: str,
    control_url: str,
    interface: str,
    mcp_version: str,
    mcp_artifact_mode: str,
    mcp_artifact_preview_chars: int,
) -> list[str]:
    config_args = interface_config_args(
        interface=interface,
        player=player,
        control_url=control_url,
        mcp_version=mcp_version,
        mcp_artifact_mode=mcp_artifact_mode,
        mcp_artifact_preview_chars=mcp_artifact_preview_chars,
    )
    if session_id is not None:
        command = [
            codex_bin,
            "exec",
            "resume",
            "--dangerously-bypass-approvals-and-sandbox",
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(output_path),
            "--json",
        ]
        command.extend(config_args)
        if reasoning_effort:
            command.extend(["--config", f"model_reasoning_effort={json.dumps(reasoning_effort)}"])
        if model:
            command.extend(["--model", model])
        command.extend([session_id, prompt])
        return command

    command = [
        codex_bin,
        "exec",
        "-C",
        str(workspace),
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(output_path),
        "--json",
    ]
    if interface == "mcp":
        command.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        command.extend(["--sandbox", sandbox])
    command.extend(config_args)
    if reasoning_effort:
        command.extend(["--config", f"model_reasoning_effort={json.dumps(reasoning_effort)}"])
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    return command


def interface_config_args(
    *,
    interface: str,
    player: str,
    control_url: str,
    mcp_version: str = "v1",
    mcp_artifact_mode: str = "off",
    mcp_artifact_preview_chars: int = 800,
) -> list[str]:
    if interface != "mcp":
        return []
    command = str(ROOT / "scripts" / "freeciv-mcp")
    args = [
        "--player",
        player,
        "--control-url",
        control_url,
        "--interface-version",
        mcp_version,
        "--artifact-mode",
        mcp_artifact_mode,
        "--artifact-preview-chars",
        str(mcp_artifact_preview_chars),
    ]
    return [
        "--config",
        f"mcp_servers.freeciv.command={json.dumps(command)}",
        "--config",
        "mcp_servers.freeciv.args=" + json.dumps(args),
        "--config",
        "mcp_servers.freeciv.startup_timeout_sec=10",
    ]


def load_session_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid session file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid session file {path}: expected JSON object")
    return payload


def session_id_from_payload(payload: dict[str, Any], path: Path) -> str | None:
    session_id = payload.get("session_id")
    if session_id is None:
        return None
    if not isinstance(session_id, str) or not session_id.strip():
        raise SystemExit(f"invalid session_id in {path}")
    return session_id.strip()


def save_session_id(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def extract_session_id(stdout: str) -> str | None:
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        found = find_session_id(event)
        if found:
            return found
    return None


def find_session_id(value: Any) -> str | None:
    uuid_pattern = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    session_keys = {
        "session_id",
        "sessionId",
        "conversation_id",
        "conversationId",
        "thread_id",
        "threadId",
    }
    if isinstance(value, dict):
        for key in session_keys:
            item = value.get(key)
            if isinstance(item, str) and uuid_pattern.match(item):
                return item
        for item in value.values():
            found = find_session_id(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_session_id(item)
            if found:
                return found
    return None


def write_transcript(
    out_dir: Path,
    stamp: str,
    player: str,
    result: subprocess.CompletedProcess[str],
) -> None:
    transcript = {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    path = out_dir / f"{stamp}-{player}-codex-exec-transcript.json"
    path.write_text(json.dumps(transcript, indent=2, sort_keys=True), encoding="utf-8")


def load_result(output_path: Path) -> dict[str, Any]:
    if not output_path.exists():
        raise SystemExit(f"Codex did not write result file: {output_path}")
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Codex result was not valid JSON: {output_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Codex result must be a JSON object: {output_path}")
    return payload


def quarantine_rejected_result(output_path: Path) -> None:
    if not output_path.exists():
        return
    rejected_dir = output_path.parent / "rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    destination = rejected_dir / output_path.name
    if destination.exists():
        stem = output_path.stem
        suffix = output_path.suffix
        index = 2
        while True:
            candidate = rejected_dir / f"{stem}.{index}{suffix}"
            if not candidate.exists():
                destination = candidate
                break
            index += 1
    output_path.rename(destination)


def validate_minimal_result(
    payload: dict[str, Any],
    expected_player: str,
    *,
    public_turn_message: bool = False,
) -> None:
    required = {
        "player": str,
        "phase_done": bool,
        "actions_taken": list,
        "turn_summary": str,
        "private_intent": str,
        "public_message": str,
        "errors": list,
    }
    for key, kind in required.items():
        if key not in payload:
            raise SystemExit(f"Codex result missing required field: {key}")
        if not isinstance(payload[key], kind):
            raise SystemExit(f"Codex result field {key!r} has wrong type")
    if payload["player"] != expected_player:
        raise SystemExit(
            f"Codex result player {payload['player']!r} did not match {expected_player!r}"
        )
    if public_turn_message:
        message = payload.get("public_message")
        if not isinstance(message, str) or not message.strip():
            raise SystemExit("Codex result missing non-empty public_message")


def validate_tool_use(
    stdout: str,
    *,
    interface: str,
    workspace: Path,
    narrative_log: bool = False,
    public_turn_message: bool = False,
    mcp_artifact_mode: str = "off",
) -> dict[str, bool]:
    violations: list[str] = []
    narrative_observed = False
    public_message_observed = False
    phase_done_observed = False
    non_terminal_game_call_observed = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if (
            narrative_log
            and interface == "mcp"
            and item_type == "mcp_tool_call"
            and item.get("tool") == "narrative_append"
            and item.get("status") == "completed"
            and not item.get("error")
        ):
            narrative_observed = True
        if item_type == "mcp_tool_call":
            tool_name = item.get("tool")
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            mcp_call_ok = (
                item.get("status") == "completed"
                and not item.get("error")
                and result.get("isError") is not True
            )
            if mcp_call_ok:
                if tool_name == "phase_done":
                    phase_done_observed = mcp_phase_done_applied(result, workspace=workspace)
                elif tool_name == "say":
                    public_message_observed = True
                    non_terminal_game_call_observed = True
                elif isinstance(tool_name, str) and tool_name not in {
                    "narrative_append",
                    "narrative_read",
                }:
                    non_terminal_game_call_observed = True
        if item_type == "file_change":
            if not is_allowed_file_change(item, workspace=workspace, narrative_log=narrative_log):
                changes = item.get("changes")
                violations.append(
                    "file changes are disabled except narrative.md when "
                    f"narrative log mode is enabled: {changes}"
                )
        elif item_type == "command_execution":
            command = item.get("command")
            completed = item.get("status") == "completed" and item.get("exit_code") == 0
            game_subcommand = bin_game_subcommand(command) if isinstance(command, str) else None
            if completed and game_subcommand == "phase-done":
                phase_done_observed = True
            elif completed and game_subcommand == "say":
                public_message_observed = True
                non_terminal_game_call_observed = True
            elif completed and game_subcommand and game_subcommand != "narrative":
                non_terminal_game_call_observed = True
            if (
                narrative_log
                and isinstance(command, str)
                and is_allowed_narrative_command(command, workspace)
            ):
                narrative_observed = True
                continue
            if (
                interface == "mcp"
                and mcp_artifact_mode != "off"
                and isinstance(command, str)
                and is_allowed_artifact_read_command(command, workspace)
            ):
                continue
            if interface == "mcp":
                violations.append(
                    "shell commands are disabled for MCP players: "
                    f"{command}"
                )
            elif isinstance(command, str) and not is_allowed_game_command(command):
                violations.append(
                    "non-canonical or overly verbose command is disabled: "
                    f"{command}"
                )
    if not non_terminal_game_call_observed:
        violations.append(
            "turn transcript contains no completed game inspection/control call "
            "from this invocation"
        )
    if not phase_done_observed:
        if interface == "mcp":
            violations.append(
                "result claimed phase_done but no successful phase_done MCP call was observed"
            )
        else:
            violations.append(
                "result claimed phase_done but no successful bin/game phase-done command was observed"
            )
    if narrative_log and not narrative_observed:
        if interface == "mcp":
            violations.append(
                "narrative log mode is enabled but no successful narrative_append MCP call was observed"
            )
        else:
            violations.append(
                "narrative log mode is enabled but no bin/game narrative command was observed"
            )
    if public_turn_message and not public_message_observed:
        if interface == "mcp":
            violations.append(
                "public turn message mode is enabled but no successful say MCP call was observed"
            )
        else:
            violations.append(
                "public turn message mode is enabled but no bin/game say command was observed"
            )
    if violations:
        detail = "\n".join(f"- {violation}" for violation in violations)
        raise SystemExit(f"baseline player violated tool-use policy:\n{detail}")
    return {
        "narrative_observed": narrative_observed,
        "public_message_observed": public_message_observed,
        "phase_done_observed": phase_done_observed,
        "non_terminal_game_call_observed": non_terminal_game_call_observed,
    }


def normalize_narrative_result(payload: dict[str, Any]) -> None:
    actions = payload.get("actions_taken")
    if isinstance(actions, list) and not any("narrative" in str(action).lower() for action in actions):
        actions.append("Appended the required narrative log entry.")
    errors = payload.get("errors")
    if isinstance(errors, list):
        payload["errors"] = [
            error for error in errors
            if "narrative_append" not in str(error)
        ]


def mcp_phase_done_applied(result: dict[str, Any], *, workspace: Path) -> bool:
    payload = mcp_result_json_payload(result, workspace=workspace)
    if payload is None:
        return False
    return payload.get("ok") is True and payload.get("applied") is True


def mcp_result_json_payload(result: dict[str, Any], *, workspace: Path) -> dict[str, Any] | None:
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        payload = parse_json_object_from_text(text)
        if isinstance(payload, dict):
            return payload
        artifact_payload = parse_mcp_artifact_payload(text, workspace=workspace)
        if isinstance(artifact_payload, dict):
            return artifact_payload
    return None


def parse_mcp_artifact_payload(text: str, *, workspace: Path) -> dict[str, Any] | None:
    match = re.search(r"^Full result file:\s*(.+)$", text, flags=re.MULTILINE)
    if not match:
        return None
    path = Path(match.group(1).strip())
    try:
        resolved_path = path.resolve()
        artifact_root = (workspace / "mcp-artifacts").resolve()
        resolved_path.relative_to(artifact_root)
    except (OSError, ValueError):
        return None
    if not resolved_path.is_file():
        return None
    try:
        artifact_text = resolved_path.read_text(encoding="utf-8")
    except OSError:
        return None
    payload = parse_json_object_from_text(artifact_text)
    return payload if isinstance(payload, dict) else None


def parse_json_object_from_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def is_allowed_file_change(item: dict[str, Any], *, workspace: Path, narrative_log: bool) -> bool:
    if not narrative_log:
        return False
    paths = sorted(extract_file_change_paths(item))
    if not paths:
        return False
    for path in paths:
        if not is_narrative_path(path, workspace):
            return False
    return True


def extract_file_change_paths(value: Any) -> set[str]:
    keys = {"path", "file", "filename", "uri"}
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str):
                paths.add(item)
            paths.update(extract_file_change_paths(item))
    elif isinstance(value, list):
        for item in value:
            paths.update(extract_file_change_paths(item))
    return paths


def is_narrative_path(path_text: str, workspace: Path) -> bool:
    path_text = path_text.removeprefix("file://")
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = workspace / path
    try:
        resolved = path.resolve()
        workspace_resolved = workspace.resolve()
        resolved.relative_to(workspace_resolved)
    except (OSError, ValueError):
        return False
    return resolved.name == "narrative.md" and resolved.parent == workspace_resolved


def is_allowed_narrative_command(command: str, workspace: Path) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if (
        len(parts) >= 3
        and parts[0] in {"/bin/zsh", "/bin/bash", "zsh", "bash"}
        and parts[1] in {"-c", "-lc"}
    ):
        inner_command = parts[2].strip()
        compound_match = re.fullmatch(
            r"test -f narrative\.md && tail -n ([0-9]{1,3}) narrative\.md \|\| true",
            inner_command,
        )
        if compound_match and 1 <= int(compound_match.group(1)) <= 200:
            return True
        try:
            parts = shlex.split(parts[2])
        except ValueError:
            return False

    def is_local_narrative_path(text: str) -> bool:
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = workspace / path
        try:
            resolved = path.resolve()
            workspace_resolved = workspace.resolve()
            resolved.relative_to(workspace_resolved)
        except (OSError, ValueError):
            return False
        return resolved == workspace_resolved / "narrative.md"

    if parts in (["ls", "narrative.md"], ["ls", "-l", "narrative.md"]):
        return True
    if len(parts) >= 3 and parts[0] == "bin/game" and parts[1] == "narrative":
        return True
    if parts == ["pwd"]:
        return True
    if len(parts) == 2 and parts[0] == "cat" and is_local_narrative_path(parts[1]):
        return True
    if len(parts) == 3 and parts[:2] == ["test", "-f"] and is_local_narrative_path(parts[2]):
        return True
    if len(parts) == 4 and parts[:2] == ["tail", "-n"] and is_local_narrative_path(parts[3]):
        return parts[2].isdigit() and 1 <= int(parts[2]) <= 200
    return False


def is_allowed_artifact_read_command(command: str, workspace: Path) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    if (
        len(parts) >= 3
        and parts[0] in {"/bin/zsh", "/bin/bash", "zsh", "bash"}
        and parts[1] in {"-c", "-lc"}
    ):
        try:
            parts = shlex.split(parts[2])
        except ValueError:
            return False
    if not parts:
        return False
    if any(part in {">", ">>", "<", "2>", "2>>", "&", "&&", ";"} for part in parts):
        return False
    if "|" in parts:
        pipe_index = parts.index("|")
        left = parts[:pipe_index]
        right = parts[pipe_index + 1 :]
        return is_allowed_artifact_read_parts(left, workspace) and is_allowed_head_parts(right)
    return is_allowed_artifact_read_parts(parts, workspace)


def is_allowed_artifact_read_parts(parts: list[str], workspace: Path) -> bool:
    if not parts:
        return False
    command_name = Path(parts[0]).name
    path_arg: str | None = None
    if command_name == "cat" and len(parts) == 2:
        path_arg = parts[1]
    elif command_name == "sed" and len(parts) == 4 and parts[1] == "-n":
        path_arg = parts[3]
    elif command_name in {"head", "tail"} and len(parts) == 4 and parts[1] == "-n":
        path_arg = parts[3]
    elif command_name == "wc" and len(parts) == 3 and parts[1] == "-l":
        path_arg = parts[2]
    elif command_name == "rg" and len(parts) == 4 and parts[1] == "-n":
        path_arg = parts[3]
    if path_arg is None:
        return False
    return is_artifact_path(path_arg, workspace)


def is_allowed_head_parts(parts: list[str]) -> bool:
    return len(parts) == 3 and Path(parts[0]).name == "head" and parts[1] == "-n" and parts[2].isdigit()


def is_artifact_path(path_text: str, workspace: Path) -> bool:
    path_text = path_text.removeprefix("file://")
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = workspace / path
    try:
        resolved = path.resolve()
        artifact_dir = (workspace / "mcp-artifacts").resolve()
        resolved.relative_to(artifact_dir)
    except (OSError, ValueError):
        return False
    return resolved.parent == artifact_dir or artifact_dir in resolved.parents


def is_allowed_game_command(command: str) -> bool:
    parts = bin_game_parts(command)
    if parts is None:
        return False
    return is_allowed_bin_game_args(parts)


def bin_game_subcommand(command: str) -> str | None:
    parts = bin_game_parts(command)
    if parts is None or len(parts) < 2:
        return None
    return parts[1]


def bin_game_parts(command: str) -> list[str] | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts:
        return None
    if (
        len(parts) >= 3
        and parts[0] in {"/bin/zsh", "/bin/bash", "zsh", "bash"}
        and parts[1] in {"-c", "-lc"}
    ):
        try:
            parts = shlex.split(parts[2])
        except ValueError:
            return None
    if not parts or parts[0] != "bin/game":
        return None
    return parts


def is_allowed_bin_game_args(parts: list[str]) -> bool:
    if not parts or parts[0] != "bin/game" or len(parts) < 2:
        return False
    if any(part in {"|", ">", ">>", "<", "2>", "2>>", "&", "&&", ";"} for part in parts):
        return False
    subcommand = parts[1]
    if subcommand == "state":
        return False
    if subcommand == "brief" and "--json" in parts[2:]:
        return False
    if subcommand == "valid-moves" and "--json" in parts[2:]:
        return False
    if subcommand == "ascii-view" and "--text" not in parts[2:]:
        return False
    return True


def shell_quote(text: str) -> str:
    if not text:
        return "''"
    if all(ch.isalnum() or ch in "/._-:=," for ch in text):
        return text
    return "'" + text.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    main()
