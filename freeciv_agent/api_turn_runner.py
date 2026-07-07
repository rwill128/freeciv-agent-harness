from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from .codex_turn_runner import (
    DEFAULT_SCHEMA,
    load_session_payload,
    mcp_artifact_prompt,
    narrative_log_prompt,
    public_turn_message_prompt,
    save_session_id,
    validate_minimal_result,
    victory_mode_prompt,
)


ROOT = Path(__file__).resolve().parents[1]
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
FINAL_TOOL_NAME = "submit_turn_result"
PHASE_DONE_READY_UNIT_WARNING_THRESHOLD = 2


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one API-model-controlled Freeciv turn through MCP tools."
    )
    parser.add_argument("player")
    parser.add_argument("--model", default="gpt-5.4-nano")
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        default="low",
    )
    parser.add_argument("--timeout", default=180, type=int)
    parser.add_argument("--control-url", default="http://127.0.0.1:8787")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--mcp-version", default="v2")
    parser.add_argument(
        "--mcp-artifact-mode",
        default="off",
        choices=["off", "mirror", "file-only"],
    )
    parser.add_argument("--mcp-artifact-preview-chars", default=800, type=int)
    parser.add_argument("--victory-mode", default="balanced")
    parser.add_argument("--narrative-log", action="store_true")
    parser.add_argument("--public-turn-message", action="store_true")
    parser.add_argument("--max-tool-iterations", default=24, type=int)
    parser.add_argument("--max-output-tokens", default=4096, type=int)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--reset-session", action="store_true")
    parser.add_argument("--allow-model-switch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    workspace = ROOT / "players" / args.player
    if not workspace.is_dir():
        raise SystemExit(f"missing player workspace: {workspace}")

    session_path = workspace / ".api-agent-session.json"
    if args.reset_session:
        session_path.unlink(missing_ok=True)
    session_payload = load_session_payload(session_path)
    previous_response_id = response_id_from_payload(session_payload, session_path)
    stored_model = session_payload.get("model")
    if (
        previous_response_id
        and isinstance(stored_model, str)
        and stored_model != args.model
        and not args.allow_model_switch
    ):
        raise SystemExit(
            f"refusing to resume {args.player} API session {previous_response_id} "
            f"with model {args.model!r}; session was created/resumed with "
            f"{stored_model!r}. Reset the session or pass --allow-model-switch."
        )

    schema = load_json_schema(Path(args.schema))
    prompt = build_api_prompt(
        args.player,
        args.control_url,
        victory_mode=args.victory_mode,
        mcp_version=args.mcp_version,
        mcp_artifact_mode=args.mcp_artifact_mode,
        narrative_log=args.narrative_log,
        public_turn_message=args.public_turn_message,
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "runtime" / "turns"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{stamp}-{args.player}-api-turn-result.json"
    transcript_path = out_dir / f"{stamp}-{args.player}-api-transcript.json"

    if args.dry_run:
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": True,
                    "player": args.player,
                    "model": args.model,
                    "previous_response_id": previous_response_id,
                    "mcp_version": args.mcp_version,
                    "mcp_artifact_mode": args.mcp_artifact_mode,
                    "tools": "loaded at runtime from scripts/freeciv-mcp",
                    "result_file": str(output_path),
                    "transcript_file": str(transcript_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(
            f"{args.api_key_env} is not set. Export an API key before running API players."
        )

    with McpClient(
        player=args.player,
        control_url=args.control_url,
        mcp_version=args.mcp_version,
        artifact_mode=args.mcp_artifact_mode,
        artifact_preview_chars=args.mcp_artifact_preview_chars,
    ) as mcp:
        mcp_tools = mcp.list_tools()
        api_tools = openai_tools_from_mcp(mcp_tools)
        api_tools.append(final_result_tool(schema))
        runner = ResponsesRunner(
            api_key=api_key,
            organization=os.environ.get("OPENAI_ORG_ID")
            or os.environ.get("OPENAI_ORGANIZATION"),
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            max_output_tokens=args.max_output_tokens,
            timeout=args.timeout,
            tools=api_tools,
        )
        result = run_turn_loop(
            runner=runner,
            mcp=mcp,
            prompt=prompt,
            previous_response_id=previous_response_id,
            max_tool_iterations=args.max_tool_iterations,
            transcript_path=transcript_path,
        )

    payload = result["turn_result"]
    normalize_api_turn_result(payload, tool_calls=result["tool_calls"])
    validate_api_turn_result(
        payload,
        args.player,
        tool_calls=result["tool_calls"],
        narrative_log=args.narrative_log,
        public_turn_message=args.public_turn_message,
    )
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    save_session_id(
        session_path,
        {
            "response_id": result["last_response_id"],
            "player": args.player,
            "model": args.model,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    json.dump(
        {
            "ok": True,
            "player": args.player,
            "model": args.model,
            "result_file": str(output_path),
            "session_file": str(session_path),
            "response_id": result["last_response_id"],
            "transcript_file": str(transcript_path),
            "usage": result["usage"],
            "result": payload,
        },
        sys.stdout,
        indent=2,
        sort_keys=True,
    )
    print()


def build_api_prompt(
    player: str,
    control_url: str,
    *,
    victory_mode: str,
    mcp_version: str,
    mcp_artifact_mode: str,
    narrative_log: bool,
    public_turn_message: bool,
) -> str:
    victory_section = victory_mode_prompt(victory_mode)
    narrative_section = narrative_log_prompt(narrative_log, interface="mcp")
    public_message_section = public_turn_message_prompt(
        public_turn_message,
        interface="mcp",
    )
    artifact_section = mcp_artifact_prompt(mcp_version, mcp_artifact_mode)
    # Reuse the Codex MCP prompt body where possible, but remove Codex-only
    # tool_search/shell language. Keeping the turn flow aligned makes Codex vs
    # API comparisons cleaner.
    return f"""Play exactly one Freeciv turn as {player}.

{victory_section}

Use only the provided Freeciv MCP tools to inspect and act. The tools are
already scoped to {player}; do not try to inspect or control any other player.
Do not write memory/plan/notes files.
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
the referenced artifact file only if the preview is not enough.
{artifact_section}

Suggested turn flow:
1. Call `brief` or, for v2, `turn_dashboard`.
2. If you have no cities, call `found_city` immediately with no `unit_id`.
3. For v2, call `research_options` before making research claims. If changing
   research helps the assigned victory focus, call `set_research` with an exact
   available technology name.
4. Inspect `units_ready`, `valid_moves`, `ascii_view`, `local_view`, or city
   details as needed.
5. Issue useful legal actions quickly.
6. If public turn message mode is enabled, call `say` exactly once with a
   public in-game message summarizing your turn stance or intent.
7. Call `phase_done` with an `intent` string describing what you tried to do and why.
8. Finish by calling `{FINAL_TOOL_NAME}` with the final turn result JSON.

Do not repeat the same inspection tool with the same arguments unless the
previous action changed the relevant state. This is a real match turn, not a
minimal smoke test: prefer to act with every strategically useful unit listed
by `turn_dashboard` or `units_ready` before ending phase. You may leave a ready
unit unused only when moving or assigning it would be strategically harmful,
redundant, or illegal; if so, mention that briefly in `private_intent`. Once
you have handled the important ready units, send the public message if
required, call `phase_done`, then call `{FINAL_TOOL_NAME}`.

For `unit_activity`, read `result.estimate` and `retry_policy`. If the result is
`already_active` or `sent_pending`, do not repeat the same activity order during
this turn; inspect or act with another unit, choose a different action, or end
phase.

Control server behind MCP: {control_url}

Return no ordinary prose. Your final response for the turn must be the
`{FINAL_TOOL_NAME}` tool call. Use `turn_summary` to briefly summarize the turn
for the match log; do not write or update memory, plan, or notes files. Set
`phase_done` to true only if the `phase_done` MCP tool succeeded. Set
`private_intent` to the same private note you submitted through the
`phase_done` tool. If public turn message mode is enabled, set `public_message`
to the exact public chat message you sent with `say`. In `actions_taken`,
`turn_summary`, narrative entries, `public_message`, and `private_intent`, do
not claim you performed an action unless you actually called the corresponding
MCP tool successfully during this invocation.
"""


def load_json_schema(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON schema {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"invalid JSON schema {path}: expected object")
    return payload


def response_id_from_payload(payload: dict[str, Any], path: Path) -> str | None:
    response_id = payload.get("response_id")
    if response_id is None:
        return None
    if not isinstance(response_id, str) or not response_id.strip():
        raise SystemExit(f"invalid response_id in {path}")
    return response_id.strip()


class McpClient:
    def __init__(
        self,
        *,
        player: str,
        control_url: str,
        mcp_version: str,
        artifact_mode: str,
        artifact_preview_chars: int,
    ) -> None:
        self.player = player
        self.control_url = control_url
        self.mcp_version = mcp_version
        self.artifact_mode = artifact_mode
        self.artifact_preview_chars = artifact_preview_chars
        self.proc: subprocess.Popen[bytes] | None = None
        self.next_id = 1

    def __enter__(self) -> McpClient:
        command = [
            str(ROOT / "scripts" / "freeciv-mcp"),
            "--player",
            self.player,
            "--control-url",
            self.control_url,
            "--interface-version",
            self.mcp_version,
            "--artifact-mode",
            self.artifact_mode,
            "--artifact-preview-chars",
            str(self.artifact_preview_chars),
        ]
        self.proc = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "freeciv-api-agent", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized", {})
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=2)

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise RuntimeError("MCP tools/list did not return a tools list")
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self.write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        response = self.read()
        if response.get("id") != request_id:
            raise RuntimeError(f"MCP response id mismatch: {response}")
        if "error" in response:
            raise RuntimeError(f"MCP {method} failed: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"MCP {method} returned non-object result")
        return result

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self.write({"jsonrpc": "2.0", "method": method, "params": params})

    def write(self, message: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("MCP process is not running")
        self.proc.stdin.write(json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n")
        self.proc.stdin.flush()

    def read(self) -> dict[str, Any]:
        if self.proc is None or self.proc.stdout is None:
            raise RuntimeError("MCP process is not running")
        line = self.proc.stdout.readline()
        if not line:
            stderr = ""
            if self.proc.stderr is not None:
                try:
                    stderr = self.proc.stderr.read().decode("utf-8", errors="replace")
                except OSError:
                    stderr = ""
            raise RuntimeError(f"MCP process exited before response. stderr={stderr}")
        payload = json.loads(line.decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("MCP response was not a JSON object")
        return payload


class ResponsesRunner:
    def __init__(
        self,
        *,
        api_key: str,
        organization: str | None,
        model: str,
        reasoning_effort: str | None,
        max_output_tokens: int,
        timeout: int,
        tools: list[dict[str, Any]],
    ) -> None:
        self.api_key = api_key
        self.organization = organization
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout
        self.tools = tools

    def create(self, *, input_data: Any, previous_response_id: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_data,
            "tools": self.tools,
            "max_output_tokens": self.max_output_tokens,
        }
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        request = urllib.request.Request(
            OPENAI_RESPONSES_URL,
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI Responses API HTTP {exc.code}: {body}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("OpenAI Responses API returned non-object JSON")
        return result


def openai_tools_from_mcp(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tools = []
    for tool in mcp_tools:
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            continue
        tools.append(
            {
                "type": "function",
                "name": name,
                "description": str(tool.get("description") or ""),
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            }
        )
    return tools


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def final_result_tool(schema: dict[str, Any]) -> dict[str, Any]:
    parameters = dict(schema)
    parameters.pop("$schema", None)
    parameters.pop("title", None)
    return {
        "type": "function",
        "name": FINAL_TOOL_NAME,
        "description": "Submit the final validated Freeciv turn result after phase_done succeeds.",
        "parameters": parameters,
    }


def run_turn_loop(
    *,
    runner: ResponsesRunner,
    mcp: McpClient,
    prompt: str,
    previous_response_id: str | None,
    max_tool_iterations: int,
    transcript_path: Path,
) -> dict[str, Any]:
    transcript: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": runner.model,
        "previous_response_id": previous_response_id,
        "responses": [],
        "tool_calls": [],
        "usage": zero_usage(),
    }
    input_data: Any = prompt
    last_response_id = previous_response_id
    final_payload: dict[str, Any] | None = None
    phase_done_deferred_for_ready_units = False

    for iteration in range(1, max_tool_iterations + 1):
        response = runner.create(input_data=input_data, previous_response_id=last_response_id)
        last_response_id = str(response.get("id") or "")
        usage = normalize_usage(response.get("usage") or {})
        add_usage(transcript["usage"], usage)
        response_record = {
            "iteration": iteration,
            "id": last_response_id,
            "status": response.get("status"),
            "usage": usage,
            "output": response.get("output"),
        }
        transcript["responses"].append(response_record)
        transcript_path.write_text(
            json.dumps(transcript, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        function_calls = extract_function_calls(response)
        if not function_calls:
            message_text = extract_message_text(response)
            raise RuntimeError(
                "model returned no function call; expected MCP tool call or "
                f"{FINAL_TOOL_NAME}. text={message_text!r}"
            )

        tool_outputs = []
        for call in function_calls:
            name = call["name"]
            arguments = parse_arguments(call["arguments"], name)
            if name == FINAL_TOOL_NAME:
                final_payload = arguments
                transcript["tool_calls"].append(
                    {
                        "iteration": iteration,
                        "name": name,
                        "arguments": arguments,
                        "final": True,
                    }
                )
                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": json.dumps(
                            {
                                "ok": True,
                                "accepted": True,
                                "message": "turn result recorded",
                            },
                            sort_keys=True,
                        ),
                    }
                )
                continue
            if name == "phase_done" and not phase_done_deferred_for_ready_units:
                defer_result = maybe_defer_phase_done_for_ready_units(mcp)
                if defer_result is not None:
                    phase_done_deferred_for_ready_units = True
                    output_text = mcp_result_to_text(defer_result)
                    transcript["tool_calls"].append(
                        {
                            "iteration": iteration,
                            "name": name,
                            "arguments": arguments,
                            "result": defer_result,
                            "final": False,
                            "deferred": True,
                        }
                    )
                    tool_outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call["call_id"],
                            "output": output_text,
                        }
                    )
                    continue
            mcp_result = mcp.call_tool(name, arguments)
            output_text = mcp_result_to_text(mcp_result)
            transcript["tool_calls"].append(
                {
                    "iteration": iteration,
                    "name": name,
                    "arguments": arguments,
                    "result": mcp_result,
                    "final": False,
                }
            )
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": output_text,
                }
            )
        transcript_path.write_text(
            json.dumps(transcript, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if final_payload is not None:
            if not last_response_id:
                raise RuntimeError("final response did not include a response id")
            last_response_id = close_final_function_call(
                runner=runner,
                input_data=tool_outputs,
                previous_response_id=last_response_id,
                transcript=transcript,
            )
            transcript["turn_result"] = final_payload
            transcript["last_response_id"] = last_response_id
            transcript_path.write_text(
                json.dumps(transcript, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return {
                "turn_result": final_payload,
                "last_response_id": last_response_id,
                "tool_calls": transcript["tool_calls"],
                "usage": transcript["usage"],
            }
        if not tool_outputs:
            raise RuntimeError("model made only non-final calls with no tool outputs")
        remaining_iterations = max_tool_iterations - iteration
        if remaining_iterations <= 4:
            tool_outputs.append(
                {
                    "role": "user",
                    "content": (
                        f"You have only {remaining_iterations} tool-call rounds left. "
                        "Stop optional inspections. If public-turn-message mode is enabled "
                        "and you have not sent chat, call say now. Then call phase_done and "
                        f"finish with {FINAL_TOOL_NAME}."
                    ),
                }
            )
        input_data = tool_outputs

    raise RuntimeError(
        f"model exceeded max tool iterations ({max_tool_iterations}) without "
        f"calling {FINAL_TOOL_NAME}"
    )


def maybe_defer_phase_done_for_ready_units(mcp: McpClient) -> dict[str, Any] | None:
    try:
        ready_result = mcp.call_tool("units_ready", {})
    except RuntimeError:
        return None
    ready_text = mcp_result_to_text(ready_result)
    ready_count = parse_units_ready_count(ready_text)
    if ready_count < PHASE_DONE_READY_UNIT_WARNING_THRESHOLD:
        return None
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    "phase_done was not executed yet because multiple owned units "
                    f"still appear ready ({ready_count}). Act with the strategically "
                    "useful units first. If specific ready units should intentionally "
                    "remain unused, call phase_done again with a private intent naming "
                    "those units and the reason.\n\n"
                    f"{ready_text}"
                ),
            }
        ],
        "isError": True,
    }


def parse_units_ready_count(text: str) -> int:
    match = re.search(r"Units with moves remaining:\s*(\d+)", text)
    if not match:
        return 0
    return int(match.group(1))


def close_final_function_call(
    *,
    runner: ResponsesRunner,
    input_data: list[dict[str, Any]],
    previous_response_id: str,
    transcript: dict[str, Any],
) -> str:
    """Acknowledge submit_turn_result so the saved response id can be resumed."""
    last_response_id = previous_response_id
    pending_outputs = input_data
    for ack_iteration in range(1, 4):
        response = runner.create(
            input_data=pending_outputs,
            previous_response_id=last_response_id,
        )
        last_response_id = str(response.get("id") or "")
        usage = normalize_usage(response.get("usage") or {})
        add_usage(transcript["usage"], usage)
        transcript["responses"].append(
            {
                "iteration": f"final_ack_{ack_iteration}",
                "id": last_response_id,
                "status": response.get("status"),
                "usage": usage,
                "output": response.get("output"),
            }
        )
        function_calls = extract_function_calls(response)
        if not function_calls:
            return last_response_id

        pending_outputs = []
        for call in function_calls:
            name = call["name"]
            transcript["tool_calls"].append(
                {
                    "iteration": f"final_ack_{ack_iteration}",
                    "name": name,
                    "arguments": parse_arguments(call["arguments"], name),
                    "result": {
                        "ignored": True,
                        "reason": "turn_result_already_submitted",
                    },
                    "final": name == FINAL_TOOL_NAME,
                }
            )
            pending_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": json.dumps(
                        {
                            "ok": False,
                            "ignored": True,
                            "error": "turn_result_already_submitted",
                        },
                        sort_keys=True,
                    ),
                }
            )

    raise RuntimeError("model kept making tool calls after submit_turn_result")


def extract_function_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    output = response.get("output")
    if not isinstance(output, list):
        return calls
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "function_call":
            continue
        name = item.get("name")
        call_id = item.get("call_id")
        if not isinstance(name, str) or not isinstance(call_id, str):
            continue
        calls.append(
            {
                "name": name,
                "call_id": call_id,
                "arguments": item.get("arguments") or "{}",
            }
        )
    return calls


def extract_message_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    output = response.get("output")
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return "\n".join(chunks)


def parse_arguments(raw: Any, name: str) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise RuntimeError(f"{name} arguments were not JSON text")
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} arguments were invalid JSON: {raw}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{name} arguments must decode to an object")
    return payload


def mcp_result_to_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list):
        texts = [
            item.get("text")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        if texts:
            return "\n".join(texts)
    return json.dumps(result, sort_keys=True)


def validate_api_turn_result(
    payload: dict[str, Any],
    expected_player: str,
    *,
    tool_calls: list[dict[str, Any]],
    narrative_log: bool,
    public_turn_message: bool,
) -> None:
    validate_minimal_result(
        payload,
        expected_player,
        public_turn_message=public_turn_message,
    )
    if not payload["phase_done"]:
        raise SystemExit(f"{expected_player} result reported phase_done=false")

    completed = [
        call
        for call in tool_calls
        if not call.get("final") and mcp_call_ok(call.get("result"))
    ]
    if not completed:
        raise SystemExit("turn contains no successful MCP inspection/control tool call")
    if not any(call.get("name") == "phase_done" for call in completed):
        raise SystemExit("turn did not successfully call phase_done")
    if public_turn_message and not any(call.get("name") == "say" for call in completed):
        raise SystemExit("public turn message mode is enabled but say was not called")
    if narrative_log and not any(call.get("name") == "narrative_append" for call in completed):
        raise SystemExit("narrative log mode is enabled but narrative_append was not called")


def mcp_call_ok(result: Any) -> bool:
    return isinstance(result, dict) and result.get("isError") is not True


def normalize_api_turn_result(
    payload: dict[str, Any],
    *,
    tool_calls: list[dict[str, Any]],
) -> None:
    actions = payload.get("actions_taken")
    if not isinstance(actions, list):
        return
    for call in tool_calls:
        if call.get("final") or not mcp_call_ok(call.get("result")):
            continue
        summary = action_summary_from_call(call)
        if summary is None or action_already_listed(summary, actions, call):
            continue
        actions.append(summary)


def action_summary_from_call(call: dict[str, Any]) -> str | None:
    name = call.get("name")
    args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    if name == "move_unit":
        result_payload = mcp_result_json_payload(call.get("result"))
        after = result_payload.get("after") if isinstance(result_payload.get("after"), dict) else {}
        unit_id = args.get("unit_id")
        target = after.get("tile") or result_payload.get("target_tile") or args.get("target_tile")
        unit_name = after.get("type_rule_name") or after.get("type_name") or "unit"
        direction = args.get("direction")
        if target is not None:
            return f"move_unit: {unit_name} #{unit_id} to tile {target}"
        return f"move_unit: unit {unit_id} direction {direction}"
    if name == "unit_activity":
        return f"unit_activity: unit {args.get('unit_id')} {args.get('activity')}"
    if name == "found_city":
        city_name = args.get("city_name") or "(auto name)"
        return f"found_city: {city_name}"
    if name == "set_city_production":
        return f"set_city_production: city {args.get('city_id')} -> {args.get('target')}"
    if name == "set_research":
        return f"set_research: {args.get('technology') or args.get('tech')}"
    if name == "set_tech_goal":
        return f"set_tech_goal: {args.get('technology') or args.get('tech')}"
    if name == "set_rates":
        return (
            "set_rates: "
            f"tax={args.get('tax')} science={args.get('science')} luxury={args.get('luxury')}"
        )
    if name == "say":
        return f"say: {args.get('message')}"
    if name == "narrative_append":
        return "narrative_append: wrote turn narrative"
    if name == "phase_done":
        return f"phase_done: {args.get('intent')}"
    return None


def action_already_listed(
    summary: str,
    actions: list[Any],
    call: dict[str, Any],
) -> bool:
    name = str(call.get("name") or "")
    args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    existing = [str(action) for action in actions]
    if name == "move_unit":
        result_payload = mcp_result_json_payload(call.get("result"))
        after = result_payload.get("after") if isinstance(result_payload.get("after"), dict) else {}
        unit_id = str(args.get("unit_id"))
        target = str(after.get("tile") or result_payload.get("target_tile") or args.get("target_tile"))
        return any("move" in action.lower() and unit_id in action and target in action for action in existing)
    return any(name in action for action in existing) or summary in existing


def mcp_result_json_payload(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    text = mcp_result_to_text(result)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def zero_usage() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
    }


def normalize_usage(usage: dict[str, Any]) -> dict[str, int]:
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    cached = int(
        usage.get("cached_input_tokens")
        or input_details.get("cached_tokens")
        or input_details.get("cached_input_tokens")
        or 0
    )
    reasoning = int(
        usage.get("reasoning_output_tokens")
        or output_details.get("reasoning_tokens")
        or output_details.get("reasoning_output_tokens")
        or 0
    )
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "uncached_input_tokens": max(0, input_tokens - cached),
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning,
        "total_tokens": total_tokens,
    }


def add_usage(total: dict[str, int], usage: dict[str, int]) -> None:
    for key, value in usage.items():
        total[key] = int(total.get(key, 0)) + int(value)


if __name__ == "__main__":
    main()
