from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Any, Callable

from .player_cli import (
    DEFAULT_BASE_URL,
    format_brief as format_cli_brief,
    format_production_targets,
    format_valid_moves,
    quoted,
    request,
)


PROTOCOL_VERSION = "2024-11-05"
ROOT = Path(__file__).resolve().parents[1]
ACTION_ENDPOINTS = {
    "move-unit",
    "unit-activity",
    "found-city",
    "set-city-production",
    "set-rates",
    "set-research",
    "set-tech-goal",
    "phase-done",
}


class ToolActionFailed(RuntimeError):
    def __init__(self, endpoint: str, payload: dict[str, Any]) -> None:
        self.endpoint = endpoint
        self.payload = payload
        super().__init__(
            f"{endpoint} returned ok=false:\n"
            + json.dumps(payload, indent=2, sort_keys=True)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Player-scoped Freeciv MCP server.")
    parser.add_argument(
        "--player",
        default=os.environ.get("FREECIV_PLAYER_NAME"),
        help="Freeciv player name this MCP server is allowed to control.",
    )
    parser.add_argument(
        "--control-url",
        default=os.environ.get("FREECIV_CONTROL_URL", DEFAULT_BASE_URL),
        help="Freeciv control server URL.",
    )
    parser.add_argument(
        "--interface-version",
        "--mcp-version",
        default=os.environ.get("FREECIV_MCP_VERSION", "v1"),
        help="MCP interface version: v0=legacy compact, v1=readable detail split, v2=rich focused tools.",
    )
    parser.add_argument(
        "--artifact-mode",
        choices=["off", "mirror", "file-only"],
        default=os.environ.get("FREECIV_MCP_ARTIFACT_MODE", "off"),
        help=(
            "Write MCP tool results to player-local files. off=normal MCP only; "
            "mirror=return normal result plus file path; file-only=return path "
            "and preview instead of the full result."
        ),
    )
    parser.add_argument(
        "--artifact-dir",
        default=os.environ.get("FREECIV_MCP_ARTIFACT_DIR"),
        help="Directory for MCP artifacts. Defaults to players/<player>/mcp-artifacts.",
    )
    parser.add_argument(
        "--artifact-preview-chars",
        default=int(os.environ.get("FREECIV_MCP_ARTIFACT_PREVIEW_CHARS", "800")),
        type=int,
        help="Preview characters returned in file-only artifact mode.",
    )
    args = parser.parse_args()
    if not args.player:
        raise SystemExit("--player or FREECIV_PLAYER_NAME is required")

    interface_version = normalize_interface_version(args.interface_version)
    startup_debug(
        args.player,
        {
            "base_url": args.control_url.rstrip("/"),
            "interface_version": interface_version,
            "artifact_mode": args.artifact_mode,
            "artifact_dir": args.artifact_dir,
        },
    )
    server = FreecivMcpServer(
        player=args.player,
        base_url=args.control_url.rstrip("/"),
        interface_version=interface_version,
        artifact_mode=args.artifact_mode,
        artifact_dir=Path(args.artifact_dir) if args.artifact_dir else None,
        artifact_preview_chars=max(0, args.artifact_preview_chars),
    )
    server.run()


def startup_debug(player: str, payload: dict[str, Any]) -> None:
    if os.environ.get("FREECIV_MCP_DEBUG", "1") == "0":
        return
    try:
        path = ROOT / "runtime" / "logs" / f"freeciv-mcp-{player}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "ts": time.time(),
                        "direction": "startup",
                        "payload": payload,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    except OSError:
        pass


class FreecivMcpServer:
    def __init__(
        self,
        *,
        player: str,
        base_url: str,
        interface_version: str,
        artifact_mode: str,
        artifact_dir: Path | None,
        artifact_preview_chars: int,
    ) -> None:
        self.player = player
        self.base_url = base_url
        self.interface_version = interface_version
        self.artifact_mode = artifact_mode
        self.artifact_dir = artifact_dir or ROOT / "players" / player / "mcp-artifacts"
        self.artifact_preview_chars = artifact_preview_chars
        self.artifact_seq = 0
        self.tools = build_tools(interface_version)
        self.framing = "content-length"

    def run(self) -> None:
        while True:
            read_result = read_message(sys.stdin.buffer)
            if read_result is None:
                return
            message, framing = read_result
            self.framing = framing
            response = self.handle_message(message)
            if response is not None:
                write_message(sys.stdout.buffer, response, framing=self.framing)

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        self.debug("in", message)
        method = message.get("method")
        request_id = message.get("id")
        try:
            if method == "initialize":
                params = message.get("params") or {}
                protocol_version = params.get("protocolVersion") or PROTOCOL_VERSION
                return self.response(
                    request_id,
                    {
                        "protocolVersion": protocol_version,
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": f"freeciv-agent-harness-{self.interface_version}",
                            "version": "0.1.0",
                        },
                    },
                )
            if method == "notifications/initialized":
                return None
            if method == "ping":
                return self.response(request_id, {})
            if method == "tools/list":
                return self.response(
                    request_id,
                    {"tools": [tool.schema for tool in self.tools.values()]},
                )
            if method == "tools/call":
                params = message.get("params") or {}
                return self.response(
                    request_id,
                    self.call_tool(
                        name=str(params.get("name")),
                        arguments=params.get("arguments") or {},
                    ),
                )
            if request_id is None:
                return None
            return self.error(request_id, -32601, f"unknown method {method!r}")
        except Exception as exc:
            if request_id is None:
                print(f"MCP notification failed: {exc}", file=sys.stderr)
                return None
            return self.error(request_id, -32000, str(exc))

    def call_tool(self, *, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            return tool_error(f"unknown tool {name!r}")
        try:
            text = tool.handler(self, arguments)
            text = self.maybe_write_artifact(name=name, arguments=arguments, text=text)
            return tool_text(text)
        except SystemExit as exc:
            return tool_error(f"{name} failed with exit code {exc.code}")
        except Exception as exc:
            return tool_error(str(exc))

    def get(self, endpoint: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/players/{quoted(self.player)}/{endpoint}"
        if query:
            clean_query = {
                key: value
                for key, value in query.items()
                if value is not None
            }
            if clean_query:
                url = f"{url}?{urllib.parse.urlencode(clean_query)}"
        return request("GET", url)

    def post(self, endpoint: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        result = request(
            "POST",
            f"{self.base_url}/players/{quoted(self.player)}/{endpoint}",
            body or {},
        )
        if endpoint in ACTION_ENDPOINTS and isinstance(result, dict) and result.get("ok") is False:
            raise ToolActionFailed(endpoint, result)
        return result

    def response(self, request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        message = {"jsonrpc": "2.0", "id": request_id, "result": result}
        self.debug("out", message)
        return message

    def error(
        self,
        request_id: Any,
        code: int,
        message: str,
        data: Any | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
        if data is not None:
            payload["error"]["data"] = data
        self.debug("out", payload)
        return payload

    def debug(self, direction: str, payload: Any) -> None:
        if os.environ.get("FREECIV_MCP_DEBUG", "1") == "0":
            return
        try:
            path = ROOT / "runtime" / "logs" / f"freeciv-mcp-{self.player}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "ts": time.time(),
                            "direction": direction,
                            "payload": payload,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
        except OSError:
            pass

    def maybe_write_artifact(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        text: str,
    ) -> str:
        if self.artifact_mode == "off":
            return text
        artifact = self.write_artifact(name=name, arguments=arguments, text=text)
        if self.artifact_mode == "mirror":
            return (
                f"{text}\n\n"
                "## MCP Artifact\n"
                f"- Full result file: {artifact['text_path']}\n"
                f"- Metadata file: {artifact['metadata_path']}\n"
                f"- Bytes: {artifact['bytes']}\n"
            )
        preview = text[: self.artifact_preview_chars]
        omitted = max(0, len(text) - len(preview))
        lines = [
            "# MCP Result Written To File",
            "",
            f"Tool: {name}",
            f"Full result file: {artifact['text_path']}",
            f"Metadata file: {artifact['metadata_path']}",
            f"Bytes: {artifact['bytes']}",
        ]
        if preview:
            lines.extend(["", "## Preview", preview])
        if omitted:
            lines.append(f"\nPreview omitted {omitted} additional characters.")
        return "\n".join(lines)

    def write_artifact(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        text: str,
    ) -> dict[str, Any]:
        self.artifact_seq += 1
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.artifact_dir.chmod(0o700)
        except OSError:
            pass
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S.%fZ")
        safe_name = safe_filename(name)
        base = f"{stamp}-{self.artifact_seq:04d}-{safe_name}"
        text_path = self.artifact_dir / f"{base}.txt"
        metadata_path = self.artifact_dir / f"{base}.metadata.json"
        text_path.write_text(text, encoding="utf-8")
        metadata = {
            "player": self.player,
            "tool": name,
            "arguments": arguments,
            "interface_version": self.interface_version,
            "artifact_mode": self.artifact_mode,
            "created_at": stamp,
            "text_path": str(text_path),
            "bytes": len(text.encode("utf-8")),
        }
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            "text_path": str(text_path),
            "metadata_path": str(metadata_path),
            "bytes": metadata["bytes"],
        }


class Tool:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[[FreecivMcpServer, dict[str, Any]], str],
    ) -> None:
        self.handler = handler
        self.schema = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        }


def build_tools(interface_version: str = "v1") -> dict[str, Tool]:
    if interface_version == "v0":
        state_tools = [
            Tool(
                name="brief",
                description="Legacy compact factual state summary for this player.",
                input_schema=object_schema(),
                handler=handle_legacy_brief,
            ),
        ]
    else:
        state_tools = [
            Tool(
                name="brief",
                description="Readable main factual overview for this player.",
                input_schema=object_schema(),
                handler=handle_brief,
            ),
            Tool(
                name="units_detail",
                description="Focused factual details about this player's units, optionally one unit.",
                input_schema=object_schema({"unit_id": int_schema("Optional owned unit id to focus on.")}),
                handler=handle_units_detail,
            ),
            Tool(
                name="cities_detail",
                description="Focused factual details about this player's cities, optionally one city.",
                input_schema=object_schema({"city_id": int_schema("Optional owned city id to focus on.")}),
                handler=handle_cities_detail,
            ),
            Tool(
                name="economy_detail",
                description="Focused factual details about economy, research, ruleset, and production targets.",
                input_schema=object_schema(),
                handler=handle_economy_detail,
            ),
        ]
        if interface_version == "v2":
            state_tools.extend(
                [
                    Tool(
                        name="turn_dashboard",
                        description="One-screen factual turn dashboard: active status, open unit/city work, and current research.",
                        input_schema=object_schema(),
                        handler=handle_turn_dashboard,
                    ),
                    Tool(
                        name="units_ready",
                        description="Concise list of owned units with moves remaining.",
                        input_schema=object_schema(),
                        handler=handle_units_ready,
                    ),
                    Tool(
                        name="city_production_options",
                        description="City production facts, including city-specific legality when city_id is supplied.",
                        input_schema=object_schema(
                            {
                                "city_id": int_schema("Optional city id for city-specific production legality."),
                                "all": bool_schema("Include every decoded production target."),
                            }
                        ),
                        handler=handle_city_production_options,
                    ),
                    Tool(
                        name="research_options",
                        description="Readable current research, goal, known tech count, and available technologies.",
                        input_schema=object_schema(),
                        handler=handle_research_options,
                    ),
                    Tool(
                        name="map_topology",
                        description="Readable map topology, wrapping, and legal movement direction names.",
                        input_schema=object_schema(),
                        handler=handle_map_topology,
                    ),
                    Tool(
                        name="recent_messages",
                        description="Formatted recent Freeciv messages visible to this player.",
                        input_schema=object_schema({"limit": int_schema("Message count.", default=10, minimum=1)}),
                        handler=handle_recent_messages,
                    ),
                    Tool(
                        name="state_snapshot",
                        description=(
                            "Full decoded player-visible state snapshot as JSON text. "
                            "Best used with artifact mode mirror or file-only."
                        ),
                        input_schema=object_schema(),
                        handler=handle_state_snapshot,
                    ),
                    Tool(
                        name="player_packet_audit",
                        description=(
                            "Diagnostic raw PACKET_PLAYER_INFO audit: raw fields, structured fields, "
                            "and fields not yet promoted into normal MCP views."
                        ),
                        input_schema=object_schema(),
                        handler=handle_player_packet_audit,
                    ),
                ]
            )

    common_tools = [
        Tool(
            name="production_targets",
            description="Exact ruleset production names for city build choices.",
            input_schema=object_schema({"all": bool_schema("Include every decoded unit and building target.")}),
            handler=handle_production_targets,
        ),
        Tool(
            name="messages",
            description="Recent Freeciv messages visible to this player.",
            input_schema=object_schema({"limit": int_schema("Message count.", default=10, minimum=1)}),
            handler=lambda server, args: json_text(server.get("messages", {"limit": args.get("limit", 10)})),
        ),
        Tool(
            name="valid_moves",
            description="Legal or blocked movement directions for one unit.",
            input_schema=object_schema({"unit_id": int_schema("Owned unit id.")}, required=["unit_id"]),
            handler=lambda server, args: format_valid_moves(server.get("valid-moves", {"unit_id": args["unit_id"]})),
        ),
        Tool(
            name="ascii_view",
            description="Deterministic hex-aware ASCII map around a unit, city, or tile.",
            input_schema=view_schema(),
            handler=handle_ascii_view,
        ),
        Tool(
            name="local_view",
            description="Structured local map facts around a unit, city, or tile.",
            input_schema=view_schema(),
            handler=lambda server, args: json_text(server.get("local-view", args)),
        ),
        Tool(
            name="narrative_read",
            description="Read this player's private narrative.md story log.",
            input_schema=object_schema(
                {
                    "limit_chars": int_schema(
                        "Maximum characters to return from the end of the log.",
                        default=6000,
                        minimum=1,
                    ),
                }
            ),
            handler=handle_narrative_read,
        ),
    ]

    action_tools = [
        Tool(
            name="narrative_append",
            description=(
                "Append one Markdown entry to this player's narrative.md story log. "
                "Use once at end of turn when narrative logging is enabled."
            ),
            input_schema=object_schema(
                {
                    "entry": string_schema(
                        "Markdown narrative entry. Include what happened, actions taken, and next intent."
                    ),
                    "turn": int_schema("Optional turn number."),
                    "year": string_schema("Optional game year label, e.g. -4000 or 4000 BCE."),
                },
                required=["entry"],
            ),
            handler=handle_narrative_append,
        ),
        Tool(
            name="move_unit",
            description="Move an owned unit by direction, target tile, or dx/dy.",
            input_schema=object_schema(
                {
                    "unit_id": int_schema("Owned unit id."),
                    "direction": int_schema("Direction id from valid_moves.", minimum=0),
                    "target_tile": int_schema("Exact destination tile id."),
                    "dx": int_schema("Relative dx.", default=0),
                    "dy": int_schema("Relative dy.", default=0),
                    "wait": number_schema("Seconds to wait for observation.", default=5.0),
                },
                required=["unit_id"],
            ),
            handler=lambda server, args: json_text(server.post("move-unit", args)),
        ),
        Tool(
            name="unit_activity",
            description=(
                "Start or change an owned unit activity such as mine, road, irrigate, "
                "or fortify. Results include retry_policy; already_active and "
                "sent_pending mean do not repeat the same activity order this turn."
            ),
            input_schema=object_schema(
                {
                    "unit_id": int_schema("Owned unit id."),
                    "activity": string_schema("Activity name, e.g. mine, road, irrigate, fortify."),
                    "target": string_schema("Optional target extra name."),
                    "wait": number_schema("Seconds to wait for observation.", default=5.0),
                },
                required=["unit_id", "activity"],
            ),
            handler=lambda server, args: json_text(server.post("unit-activity", args)),
        ),
        Tool(
            name="found_city",
            description=(
                "Try to found a city with an owned unit. Prefer omitting unit_id; "
                "the tool will ask Freeciv which owned unit can legally perform "
                "Found City and use that unit. If unit_id is supplied, the tool "
                "tries only that specific unit; if it cannot found a city, no "
                "packet is sent and the response lists legal founding units when "
                "known."
            ),
            input_schema=object_schema(
                {
                    "unit_id": int_schema("Optional owned unit id to try; omit unless targeting a specific unit.", minimum=1),
                    "city_name": string_schema("City name.", default=""),
                    "wait": number_schema("Seconds to wait for observation.", default=5.0),
                },
            ),
            handler=lambda server, args: json_text(server.post("found-city", args)),
        ),
        Tool(
            name="set_city_production",
            description="Set a city production target using exact names from production_targets.",
            input_schema=object_schema(
                {
                    "city_id": int_schema("Owned city id."),
                    "target": string_schema("Exact target name, e.g. Migrants or Workers."),
                    "kind": string_schema("unit or building.", default="unit"),
                    "wait": number_schema("Seconds to wait for observation.", default=1.0),
                },
                required=["city_id", "target"],
            ),
            handler=lambda server, args: json_text(server.post("set-city-production", args)),
        ),
        Tool(
            name="set_rates",
            description="Set tax/luxury/science rates; values must sum to 100.",
            input_schema=object_schema(
                {
                    "tax": int_schema("Tax percent.", minimum=0, maximum=100),
                    "luxury": int_schema("Luxury percent.", minimum=0, maximum=100),
                    "science": int_schema("Science percent.", minimum=0, maximum=100),
                    "wait": number_schema("Seconds to wait for observation.", default=1.0),
                },
                required=["tax", "luxury", "science"],
            ),
            handler=lambda server, args: json_text(server.post("set-rates", args)),
        ),
        Tool(
            name="set_research",
            description="Set current research by exact technology name or id.",
            input_schema=object_schema(
                {
                    "tech": string_schema("Technology name or id."),
                    "wait": number_schema("Seconds to wait for observation.", default=1.0),
                },
                required=["tech"],
            ),
            handler=lambda server, args: json_text(server.post("set-research", args)),
        ),
        Tool(
            name="set_tech_goal",
            description="Set longer-term technology goal by exact technology name or id.",
            input_schema=object_schema(
                {
                    "tech": string_schema("Technology name or id."),
                    "wait": number_schema("Seconds to wait for observation.", default=1.0),
                },
                required=["tech"],
            ),
            handler=lambda server, args: json_text(server.post("set-tech-goal", args)),
        ),
        Tool(
            name="say",
            description="Send a public in-game chat message visible to other players.",
            input_schema=object_schema({"message": string_schema("Public chat message.")}, required=["message"]),
            handler=lambda server, args: json_text(server.post("say", args)),
        ),
        Tool(
            name="private_intent",
            description="Record private turn intent for narration/audit; not sent to opponent.",
            input_schema=object_schema(
                {
                    "intent": string_schema("Private intent note."),
                    "turn": int_schema("Optional turn number."),
                },
                required=["intent"],
            ),
            handler=lambda server, args: json_text(server.post("private-intent", args)),
        ),
        Tool(
            name="phase_done",
            description="End this player's phase, optionally recording private intent.",
            input_schema=object_schema(
                {
                    "intent": string_schema("Private intent note."),
                    "turn": int_schema("Optional turn number."),
                },
            ),
            handler=lambda server, args: json_text(server.post("phase-done", args)),
        ),
    ]
    tools = state_tools + common_tools + action_tools
    return {str(tool.schema["name"]): tool for tool in tools}


def normalize_interface_version(value: str) -> str:
    version = value.strip().lower().replace("_", "-")
    aliases = {
        "0": "v0",
        "legacy": "v0",
        "compact": "v0",
        "mcp-v0": "v0",
        "1": "v1",
        "readable": "v1",
        "details": "v1",
        "mcp-v1": "v1",
        "2": "v2",
        "rich": "v2",
        "focused": "v2",
        "mcp-v2": "v2",
    }
    version = aliases.get(version, version)
    if version not in {"v0", "v1", "v2"}:
        raise SystemExit(
            f"unknown MCP interface version {value!r}; expected v0, v1, or v2"
        )
    return version


def safe_filename(value: str) -> str:
    safe = []
    for char in value:
        if char.isalnum() or char in {"-", "_"}:
            safe.append(char)
        else:
            safe.append("-")
    result = "".join(safe).strip("-")
    return result or "tool"


def handle_production_targets(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    result = server.get("production-targets")
    return format_production_targets(result, show_all=bool(args.get("all", False)))


def handle_legacy_brief(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    text = format_cli_brief(server.get("brief"))
    return text.replace(
        "Inspect units with: bin/game valid-moves <unit_id> or "
        "bin/game ascii-view --unit-id <unit_id> --text",
        "Inspect units with MCP tools: valid_moves(unit_id) or ascii_view(unit_id)",
    ).replace(
        "Full exact list: bin/game production-targets",
        "Full exact list: production_targets",
    )


def handle_brief(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    return format_mcp_brief(server.get("brief"))


def handle_units_detail(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    return format_mcp_units_detail(server.get("brief"), unit_id=args.get("unit_id"))


def handle_cities_detail(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    return format_mcp_cities_detail(server.get("brief"), city_id=args.get("city_id"))


def handle_economy_detail(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    return format_mcp_economy_detail(server.get("brief"))


def handle_turn_dashboard(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    return format_turn_dashboard(server.get("brief"))


def handle_units_ready(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    return format_units_ready(server.get("brief"))


def handle_city_production_options(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    query = {"city_id": args.get("city_id")} if args.get("city_id") is not None else None
    result = server.get("production-targets", query)
    return format_production_targets(result, show_all=bool(args.get("all", False)))


def handle_research_options(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    return format_research_options(server.get("brief"))


def handle_map_topology(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    return format_map_topology(server.get("brief"))


def handle_recent_messages(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    return format_recent_messages(
        server.get("messages", {"limit": args.get("limit", 10)}),
        limit=args.get("limit", 10),
    )


def handle_state_snapshot(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    return json_text(server.get(""))


def handle_player_packet_audit(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    return json_text(server.get("player-packet-audit"))


def handle_narrative_read(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    limit_chars = int(args.get("limit_chars") or 6000)
    limit_chars = max(1, min(limit_chars, 50000))
    path = narrative_path(server.player)
    if not path.exists():
        return (
            "# Narrative Log\n\n"
            f"Player: {server.player}\n"
            f"Path: {path}\n"
            "Status: no narrative.md exists yet."
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    omitted = max(0, len(text) - limit_chars)
    if omitted:
        text = text[-limit_chars:]
    prefix = [
        "# Narrative Log",
        "",
        f"Player: {server.player}",
        f"Path: {path}",
        f"Characters returned: {len(text)}",
    ]
    if omitted:
        prefix.append(f"Characters omitted from start: {omitted}")
    prefix.extend(["", "## Content", text.rstrip()])
    return "\n".join(prefix).rstrip() + "\n"


def handle_narrative_append(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    entry = str(args.get("entry") or "").strip()
    if not entry:
        raise ValueError("entry is required")
    if len(entry) > 6000:
        raise ValueError("entry is too long; keep narrative entries under 6000 characters")
    path = narrative_path(server.player)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
    else:
        existing = ""

    header = narrative_header(args)
    block = f"{header}\n{entry}\n"
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not existing.endswith("\n\n"):
        existing += "\n"
    path.write_text(existing + block, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return json_text(
        {
            "ok": True,
            "player": server.player,
            "path": str(path),
            "appended_chars": len(block),
            "entry_count_hint": count_narrative_entries(path),
        }
    )


def narrative_path(player: str) -> Path:
    return ROOT / "players" / player / "narrative.md"


def narrative_header(args: dict[str, Any]) -> str:
    turn = args.get("turn")
    year = args.get("year")
    if turn is not None and year:
        return f"## Turn {turn} ({year})"
    if turn is not None:
        return f"## Turn {turn}"
    if year:
        return f"## {year}"
    return "## Narrative Entry"


def count_narrative_entries(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    return sum(1 for line in text.splitlines() if line.startswith("## "))


def handle_ascii_view(server: FreecivMcpServer, args: dict[str, Any]) -> str:
    result = server.get("ascii-view", args)
    return str(result.get("text") or json_text(result))


def format_mcp_brief(result: dict[str, Any]) -> str:
    phase = result.get("phase") or {}
    active = phase.get("agent_is_active_phase")
    lines = [
        f"# {result.get('name')} Overview",
        "",
        f"Turn: {result.get('turn')} ({result.get('year')})",
        f"Active phase: {yes_no(active)}",
        f"Phase mode: {phase.get('mode_name') or 'unknown'}",
    ]
    if active is False:
        lines.append("Status: Not this player's active phase. Do not act until active.")
    lines.extend(
        [
            "",
            "## Current Status",
            f"- Economy: {format_economy(result.get('economy') or {})}",
            f"- Player status: {format_player_status(result.get('player_status') or {})}",
            f"- Research: {format_research_line(result.get('research') or {})}",
            f"- Known map tiles: {result.get('known_tiles')}",
        ]
    )

    cities = result.get("cities") or []
    lines.extend(["", f"## Cities ({len(cities)})"])
    if cities:
        for city in sorted(cities, key=lambda item: int(item.get("id", 0))):
            lines.append(f"- {format_city_summary(city)}")
    else:
        lines.append("- None.")

    units = result.get("units") or []
    actionable, inactive = split_units_by_moves(units)
    lines.extend(["", f"## Units Needing Attention ({len(actionable)})"])
    if actionable:
        for unit in actionable:
            lines.append(f"- {format_unit_summary(unit)}")
    else:
        lines.append("- None.")
    lines.append(f"Other units: {len(inactive)}")

    lines.extend(
        [
            "",
            "## Detail Tools",
            "- units_detail(unit_id optional): unit list or one unit's factual details.",
            "- cities_detail(city_id optional): city list or one city's factual details.",
            "- economy_detail(): economy, research, ruleset, and key production targets.",
            "- valid_moves(unit_id): legal/blocked movement facts for one unit.",
            "- ascii_view(unit_id/city_id/tile_id, radius optional): hex-aware local map text.",
            "- production_targets(all optional): exact build target names.",
            "",
            "## Action Tools",
            "- move_unit(unit_id, direction/target_tile/dx/dy): move one owned unit.",
            "- unit_activity(unit_id, activity): start work, fortify, or other activity.",
            "- found_city(city_name optional): found a city; omit unit_id so the harness selects a legal founder.",
            "- set_city_production(city_id, target): change city production using exact target names.",
            "- set_research(tech): set current research by exact technology name.",
            "- say(message): send public in-game chat.",
            "",
            "## Turn Completion Tools",
            "- narrative_append(entry, turn optional, year optional): append the visible narrative log entry.",
            "- private_intent(intent, turn optional): record private intent without ending phase.",
            "- phase_done(intent optional, turn optional): end this player's phase.",
        ]
    )
    return "\n".join(lines)


def format_mcp_units_detail(result: dict[str, Any], *, unit_id: Any = None) -> str:
    units = result.get("units") or []
    selected = filter_by_id(units, unit_id)
    if unit_id is not None and not selected:
        return f"No owned unit with id {unit_id} is visible in the current brief."

    actionable, inactive = split_units_by_moves(selected if unit_id is not None else units)
    lines = [
        f"# {result.get('name')} Units",
        "",
        f"Turn: {result.get('turn')} ({result.get('year')})",
    ]
    if unit_id is not None:
        lines.append(f"Focused unit: {unit_id}")
    lines.extend(["", f"## Units With Moves ({len(actionable)})"])
    if actionable:
        for unit in actionable:
            lines.extend(format_unit_detail_block(unit))
    else:
        lines.append("- None.")
    lines.extend(["", f"## Other Units ({len(inactive)})"])
    if inactive:
        for unit in inactive:
            lines.extend(format_unit_detail_block(unit))
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Related Tools",
            "- valid_moves(unit_id): movement facts for a specific unit.",
            "- ascii_view(unit_id, radius optional): hex-aware local map around a unit.",
            "- local_view(unit_id, radius optional): structured local map facts.",
            "- move_unit(unit_id, direction/target_tile/dx/dy): execute movement.",
            "- unit_activity(unit_id, activity): start work, fortify, or other activity.",
        ]
    )
    return "\n".join(lines)


def format_mcp_cities_detail(result: dict[str, Any], *, city_id: Any = None) -> str:
    cities = result.get("cities") or []
    selected = filter_by_id(cities, city_id)
    if city_id is not None and not selected:
        return f"No owned city with id {city_id} is visible in the current brief."

    lines = [
        f"# {result.get('name')} Cities",
        "",
        f"Turn: {result.get('turn')} ({result.get('year')})",
    ]
    if city_id is not None:
        lines.append(f"Focused city: {city_id}")
    lines.extend(["", f"## Cities ({len(selected)})"])
    if selected:
        for city in sorted(selected, key=lambda item: int(item.get("id", 0))):
            lines.extend(format_city_detail_block(city))
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Related Tools",
            "- production_targets(all optional): exact build target names.",
            "- set_city_production(city_id, target, kind optional): change production.",
            "- ascii_view(city_id, radius optional): hex-aware local map around a city.",
            "- local_view(city_id, radius optional): structured local map facts.",
        ]
    )
    return "\n".join(lines)


def format_mcp_economy_detail(result: dict[str, Any]) -> str:
    research = result.get("research") or {}
    ruleset = result.get("ruleset") or {}
    production_targets = result.get("production_targets") or {}
    lines = [
        f"# {result.get('name')} Economy And Rules",
        "",
        f"Turn: {result.get('turn')} ({result.get('year')})",
        "",
        "## Economy",
        f"- {format_economy(result.get('economy') or {})}",
        f"- Player status: {format_player_status(result.get('player_status') or {})}",
        "",
        "## Player Packet Status",
        *format_player_status_detail(result.get("player_status") or {}),
        "",
        "## Research",
        f"- Current: {format_research_line(research)}",
        f"- Bulbs researched: {research.get('bulbs_researched')}",
        f"- Total bulbs per turn: {research.get('total_bulbs_prod')}",
        f"- Known technologies: {len(research.get('known') or [])}",
        f"- Available technologies: {len(research.get('available') or [])}",
        "",
        "## Ruleset",
        f"- rulesetdir: {ruleset.get('rulesetdir')}",
        "- rules doc: docs/freeciv-rules-for-agents.md",
        "",
        "## Key Production Targets",
    ]
    key_units = production_targets.get("key_unit_targets") or {}
    if key_units:
        for role, targets in key_units.items():
            names = ", ".join(
                str(target.get("target"))
                for target in targets
                if target.get("target")
            )
            lines.append(f"- {role}: {names or 'none'}")
    else:
        lines.append("- No key production target summary available.")
    counts = production_targets.get("counts") or {}
    lines.extend(
        [
            "",
            "## Full Production List",
            f"- Units: {counts.get('unit')}",
            f"- Buildings: {counts.get('building')}",
            "- Use production_targets(all=true) for exact decoded target names.",
        ]
    )
    return "\n".join(lines)


def format_turn_dashboard(result: dict[str, Any]) -> str:
    phase = result.get("phase") or {}
    units = result.get("units") or []
    actionable, inactive = split_units_by_moves(units)
    cities = result.get("cities") or []
    lines = [
        f"# {result.get('name')} Turn Dashboard",
        "",
        f"Turn: {result.get('turn')} ({result.get('year')})",
        f"Active phase: {yes_no(phase.get('agent_is_active_phase'))}",
        f"Phase: {phase.get('mode_name') or 'unknown'}",
        "",
        "## Open Unit Work",
    ]
    if actionable:
        for unit in actionable:
            lines.append(f"- {format_unit_summary(unit)}")
    else:
        lines.append("- No owned units currently show moves left.")
    lines.extend(["", "## Cities And Production"])
    if cities:
        for city in sorted(cities, key=lambda item: int(item.get("id", 0))):
            lines.append(f"- {format_city_summary(city)}")
    else:
        lines.append("- No owned cities visible.")
    lines.extend(
        [
            "",
            "## Economy And Research",
            f"- Economy: {format_economy(result.get('economy') or {})}",
            f"- Research: {format_research_line(result.get('research') or {})}",
            "",
            "## Counts",
            f"- Units with moves: {len(actionable)}",
            f"- Other units: {len(inactive)}",
            f"- Cities: {len(cities)}",
            "",
            "## Related Tools",
            "- units_ready(): only units with moves.",
            "- cities_detail(city_id optional): detailed city facts.",
            "- city_production_options(city_id optional): exact production choices.",
            "- research_options(): readable technology state.",
            "- map_topology(): movement direction and wrapping facts.",
        ]
    )
    return "\n".join(lines)


def format_units_ready(result: dict[str, Any]) -> str:
    actionable, _inactive = split_units_by_moves(result.get("units") or [])
    lines = [
        f"# {result.get('name')} Units Ready",
        "",
        f"Turn: {result.get('turn')} ({result.get('year')})",
        f"Units with moves remaining: {len(actionable)}",
    ]
    if actionable:
        lines.append("")
        for unit in actionable:
            lines.append(f"- {format_unit_summary(unit)}")
    else:
        lines.append("")
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Per-Unit Tools",
            "- valid_moves(unit_id): movement facts.",
            "- ascii_view(unit_id, radius optional): local hex map.",
            "- unit_activity(unit_id, activity): work/fortify/activity order.",
            "- move_unit(unit_id, direction/target_tile/dx/dy): movement order.",
        ]
    )
    return "\n".join(lines)


def format_research_options(result: dict[str, Any]) -> str:
    research = result.get("research") or {}
    current = research.get("researching_info") or {}
    goal = research.get("tech_goal_info") or {}
    available = research.get("available") or []
    known = research.get("known") or []
    lines = [
        f"# {result.get('name')} Research",
        "",
        f"Current research: {clean_label(current.get('rule_name') or current.get('name') or research.get('researching'))}",
        f"Current cost: {research.get('researching_cost')}",
        f"Progress bulbs: {research.get('bulbs_researched')}",
        f"Bulbs per turn: {research.get('total_bulbs_prod')}",
        f"Current goal: {clean_label(goal.get('rule_name') or goal.get('name') or research.get('tech_goal'))}",
        f"Known technologies: {len(known)}",
        "",
        "## How To Change Research",
        "- To change current research this turn, call set_research(tech) with one exact name from Available Technologies.",
        "- If you do not call set_research successfully, say research was left unchanged; do not say you set or aligned it.",
        "- To set a longer-term goal instead of current research, call set_tech_goal(tech).",
        "",
        f"## Available Technologies ({len(available)})",
    ]
    if available:
        for tech in sorted(available, key=lambda item: str(item.get("rule_name") or item.get("name") or "")):
            name = clean_label(tech.get("rule_name") or tech.get("name") or tech.get("id"))
            cost = tech.get("cost")
            state = tech.get("state")
            detail = f"- {name} #{tech.get('id')}"
            if cost is not None:
                detail += f", cost {cost}"
            if state:
                detail += f", state {state}"
            lines.append(detail)
    else:
        lines.append("- None visible.")
    lines.extend(
        [
            "",
            "## Related Tools",
            "- set_research(tech): set current research by exact name or id from Available Technologies.",
            "- set_tech_goal(tech): set longer-term technology goal by exact name or id.",
        ]
    )
    return "\n".join(lines)


def format_map_topology(result: dict[str, Any]) -> str:
    game_map = result.get("map") or {}
    topology = game_map.get("topology") or {}
    wrap = topology.get("wrap") or {}
    lines = [
        f"# {result.get('name')} Map Topology",
        "",
        f"Map size: {game_map.get('xsize')} x {game_map.get('ysize')}",
        f"Topology: {topology.get('name') or game_map.get('topology_id')}",
        f"Is hex: {yes_no(topology.get('is_hex'))}",
        f"Is isometric: {yes_no(topology.get('is_isometric'))}",
        f"Wrap: {wrap.get('name') or game_map.get('wrap_id')}",
        "",
        "## Valid Movement Directions",
    ]
    valid = topology.get("valid_directions") or []
    if valid:
        for direction in valid:
            lines.append(
                f"- {direction.get('id')}: {direction.get('name')} "
                f"(dx {direction.get('dx')}, dy {direction.get('dy')})"
            )
    else:
        lines.append("- Unknown.")
    invalid = topology.get("invalid_directions") or []
    lines.extend(["", "## Invalid Direction Names For This Topology"])
    if invalid:
        for direction in invalid:
            lines.append(
                f"- {direction.get('id')}: {direction.get('name')} "
                f"(not adjacent on this topology)"
            )
    else:
        lines.append("- None reported.")
    return "\n".join(lines)


def format_recent_messages(result: dict[str, Any], *, limit: Any) -> str:
    messages = result.get("messages") if isinstance(result, dict) else None
    if messages is None and isinstance(result, list):
        messages = result
    if not isinstance(messages, list):
        messages = []
    lines = [
        "# Recent Freeciv Messages",
        "",
        f"Requested limit: {limit}",
        f"Messages returned: {len(messages)}",
        "",
    ]
    if messages:
        for message in messages:
            if isinstance(message, dict):
                text = (
                    message.get("text")
                    or message.get("message")
                    or message.get("event")
                    or json.dumps(message, sort_keys=True)
                )
                turn = message.get("turn")
                prefix = f"- turn {turn}: " if turn is not None else "- "
                lines.append(prefix + str(text))
            else:
                lines.append(f"- {message}")
    else:
        lines.append("- None.")
    return "\n".join(lines)


def split_units_by_moves(units: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    actionable = [
        unit for unit in units
        if isinstance(unit.get("movesleft"), int) and int(unit.get("movesleft", 0)) > 0
    ]
    inactive = [unit for unit in units if unit not in actionable]
    return (
        sorted(actionable, key=lambda item: (-int(item.get("movesleft", 0)), int(item.get("id", 0)))),
        sorted(inactive, key=lambda item: int(item.get("id", 0))),
    )


def filter_by_id(items: list[dict[str, Any]], wanted_id: Any) -> list[dict[str, Any]]:
    if wanted_id is None:
        return items
    try:
        numeric_id = int(wanted_id)
    except (TypeError, ValueError):
        return []
    return [item for item in items if int(item.get("id", -1)) == numeric_id]


def format_player_status(status: dict[str, Any]) -> str:
    if not status or not status.get("available"):
        return "PACKET_PLAYER_INFO status unavailable"
    identity = status.get("identity") or {}
    connection = status.get("connection") or {}
    lifecycle = status.get("lifecycle") or {}
    flags = status.get("flags") or {}
    style = status.get("style") or {}
    visibility = status.get("visibility") or {}
    attitudes = status.get("ai_attitudes") or {}
    wonders = status.get("wonders") or {}
    multipliers = status.get("multipliers") or {}

    parts = [
        f"player_no {identity.get('player_no')}",
        f"team {identity.get('team_id')}",
    ]
    if connection.get("is_connected") is not None:
        parts.append(f"connected {yes_no(connection.get('is_connected'))}")
    if connection.get("phase_done") is not None:
        parts.append(f"phase_done {yes_no(connection.get('phase_done'))}")
    if lifecycle.get("is_alive") is not None:
        parts.append(f"alive {yes_no(lifecycle.get('is_alive'))}")
    active_flags = [
        str(item.get("name"))
        for item in flags.get("active") or []
        if item.get("name")
    ]
    parts.append(f"flags {', '.join(active_flags) if active_flags else 'none'}")
    visibility_counts = []
    for key, label in (
        ("real_embassy", "embassies"),
        ("gives_shared_vision", "shared vision"),
        ("gives_shared_tiles", "shared tiles"),
    ):
        item = visibility.get(key) or {}
        if item.get("active_count"):
            visibility_counts.append(f"{label} {item.get('active_count')}")
    if visibility_counts:
        parts.append("; ".join(visibility_counts))
    color = style.get("color_rgb") or {}
    if color.get("css_hex"):
        parts.append(f"color {color.get('css_hex')}")
    if style.get("style_id") is not None:
        parts.append(f"style_id {style.get('style_id')}")
    if attitudes.get("available"):
        parts.append(f"non-neutral AI attitudes {attitudes.get('non_neutral_count', 0)}")
    if wonders.get("available"):
        parts.append(
            f"wonders {wonders.get('built_or_lost_count', 0)} built/lost"
            if wonders.get("encoding") == "flat_player_wonders_array"
            else f"wonders {wonders.get('encoding')}"
        )
    if multipliers.get("available"):
        parts.append(f"multipliers {multipliers.get('count', 0)}")
    return ", ".join(parts)


def format_player_status_detail(status: dict[str, Any]) -> list[str]:
    if not status or not status.get("available"):
        return ["- PACKET_PLAYER_INFO status unavailable."]
    identity = status.get("identity") or {}
    connection = status.get("connection") or {}
    lifecycle = status.get("lifecycle") or {}
    politics = status.get("politics") or {}
    economy = status.get("economy_packet") or {}
    visibility = status.get("visibility") or {}
    ai_profile = status.get("ai_profile") or {}
    attitudes = status.get("ai_attitudes") or {}
    flags = status.get("flags") or {}
    wonders = status.get("wonders") or {}
    multipliers = status.get("multipliers") or {}

    mood = politics.get("mood") or {}
    ai_skill = ai_profile.get("ai_skill_level") or {}
    barbarian = ai_profile.get("barbarian_type") or {}
    lines = [
        (
            f"- Identity: player_no {identity.get('player_no')}, "
            f"nation_id {identity.get('nation_id')}, team_id {identity.get('team_id')}, "
            f"username {identity.get('username')}"
        ),
        (
            f"- Session: connected {yes_no(connection.get('is_connected'))}, "
            f"ready {yes_no(connection.get('is_ready'))}, "
            f"phase_done {yes_no(connection.get('phase_done'))}, "
            f"unassigned_user {yes_no(identity.get('unassigned_user'))}"
        ),
        (
            f"- Lifecycle: alive {yes_no(lifecycle.get('is_alive'))}, "
            f"turns_alive {lifecycle.get('turns_alive')}, "
            f"idle_turns {lifecycle.get('idle_turns')}, "
            f"revolution_finishes {lifecycle.get('revolution_finishes')}"
        ),
        (
            f"- Politics: government_id {politics.get('government_id')}, "
            f"target_government_id {politics.get('target_government_id')}, "
            f"mood {mood.get('name')} ({mood.get('id')})"
        ),
        (
            f"- Packet economy: score {economy.get('score')}, culture {economy.get('culture')}, "
            f"infrapoints {economy.get('infrapoints')}, science_cost {economy.get('science_cost')}, "
            f"tech_upkeep {economy.get('tech_upkeep')}, history {economy.get('history')}"
        ),
        (
            f"- AI/barbarian: skill {ai_skill.get('name')} ({ai_skill.get('id')}), "
            f"barbarian_type {barbarian.get('name')} ({barbarian.get('id')})"
        ),
    ]
    active_flags = [
        str(item.get("name"))
        for item in flags.get("active") or []
        if item.get("name")
    ]
    lines.append(f"- Flags: {', '.join(active_flags) if active_flags else 'none'}")
    for key, label in (
        ("real_embassy", "Real embassies"),
        ("gives_shared_vision", "Gives shared vision"),
        ("gives_shared_tiles", "Gives shared tiles"),
    ):
        item = visibility.get(key) or {}
        slots = ", ".join(str(slot.get("player_slot")) for slot in item.get("active_slots") or [])
        lines.append(f"- {label}: {item.get('active_count', 0)} active slots" + (f" ({slots})" if slots else ""))
    if attitudes.get("available"):
        lines.append(f"- AI attitudes: {attitudes.get('non_neutral_count', 0)} non-neutral entries")
    if wonders.get("available"):
        if wonders.get("encoding") == "flat_player_wonders_array":
            lines.append(
                f"- Wonders: {wonders.get('built_or_lost_count', 0)} built/lost, "
                f"{wonders.get('not_built_count')} not built"
            )
        else:
            lines.append(f"- Wonders: {wonders.get('encoding')}")
    if multipliers.get("available"):
        entries = multipliers.get("entries") or []
        lines.append(
            f"- Multipliers: {multipliers.get('count', 0)} values, "
            f"{multipliers.get('ruleset_definitions_known', 0)} ruleset definitions known"
        )
        for entry in entries[:8]:
            name = clean_label(entry.get("rule_name") or entry.get("name") or f"multiplier {entry.get('id')}")
            lines.append(
                f"  - {name}: value {entry.get('value')}, target {entry.get('target')}, "
                f"changed_turn {entry.get('changed_turn')}"
            )
        if len(entries) > 8:
            lines.append(f"  - {len(entries) - 8} more multipliers omitted from text; use player_packet_audit for full JSON.")
    return lines


def format_economy(economy: dict[str, Any]) -> str:
    parts = [
        f"gold {economy.get('gold')}",
        f"tax {economy.get('tax')}%",
        f"science {economy.get('science')}%",
        f"luxury {economy.get('luxury', 0)}%",
    ]
    if economy.get("score") is not None:
        parts.append(f"score {economy.get('score')}")
    if economy.get("culture") is not None:
        parts.append(f"culture {economy.get('culture')}")
    if economy.get("mood") is not None:
        parts.append(f"mood_id {economy.get('mood')}")
    if economy.get("nturns_idle") is not None:
        parts.append(f"idle_turns {economy.get('nturns_idle')}")
    if economy.get("government") is not None:
        parts.append(f"government_id {economy.get('government')}")
    if economy.get("target_government") is not None:
        parts.append(f"target_government_id {economy.get('target_government')}")
    return ", ".join(parts)


def format_research_line(research: dict[str, Any]) -> str:
    researching = research.get("researching_info") or {}
    goal = research.get("tech_goal_info") or {}
    name = clean_label(researching.get("rule_name") or researching.get("name") or research.get("researching"))
    parts = [str(name or "none")]
    if research.get("researching_cost") is not None:
        parts.append(f"cost {research.get('researching_cost')}")
    if research.get("bulbs_researched") is not None:
        parts.append(f"progress {research.get('bulbs_researched')}")
    goal_name = clean_label(goal.get("rule_name") or goal.get("name"))
    if goal_name:
        parts.append(f"goal {goal_name}")
    return ", ".join(parts)


def format_city_summary(city: dict[str, Any]) -> str:
    production = city.get("production") or {}
    return (
        f"{city.get('name')} #{city.get('id')} at tile {city.get('tile')}: "
        f"size {city.get('size')}, food stock {city.get('food_stock')}, "
        f"shield stock {city.get('shield_stock')}, "
        f"producing {clean_label(production.get('command_target') or production.get('rule_name') or production.get('name'))}"
    )


def format_city_detail_block(city: dict[str, Any]) -> list[str]:
    production = city.get("production") or {}
    target = production.get("target") or {}
    lines = [
        f"- {city.get('name')} #{city.get('id')}",
        f"  - Tile: {city.get('tile')}",
        f"  - Size: {city.get('size')}",
        f"  - Food stock: {city.get('food_stock')}",
        f"  - Shield stock: {city.get('shield_stock')}",
        f"  - Producing: {clean_label(production.get('rule_name') or production.get('name'))}",
        f"  - Production command target: {production.get('command_target')}",
    ]
    if target:
        build_cost = target.get("build_cost")
        if build_cost is not None:
            lines.append(f"  - Current target build cost: {build_cost}")
    return lines


def format_unit_summary(unit: dict[str, Any]) -> str:
    return (
        f"{unit_label(unit)} #{unit.get('id')} at tile {unit.get('tile')}: "
        f"moves {unit.get('movesleft')}, hp {unit.get('hp')}, "
        f"activity {activity_label(unit)}"
    )


def format_unit_detail_block(unit: dict[str, Any]) -> list[str]:
    type_info = unit.get("type_info") or {}
    lines = [
        f"- {unit_label(unit)} #{unit.get('id')}",
        f"  - Tile: {unit.get('tile')}",
        f"  - Moves left: {unit.get('movesleft')}",
        f"  - Hit points: {unit.get('hp')}",
        f"  - Activity: {activity_label(unit)}",
    ]
    build_cost = type_info.get("build_cost")
    if build_cost is not None:
        lines.append(f"  - Unit build cost: {build_cost}")
    combat = []
    if type_info.get("attack_strength") is not None:
        combat.append(f"attack {type_info.get('attack_strength')}")
    if type_info.get("defense_strength") is not None:
        combat.append(f"defense {type_info.get('defense_strength')}")
    if combat:
        lines.append("  - Combat: " + ", ".join(combat))
    move_rate = type_info.get("move_rate")
    if move_rate is not None:
        lines.append(f"  - Type move rate: {move_rate}")
    notes = unit.get("type_notes") or []
    if notes:
        lines.append("  - Notes: " + " ".join(str(note) for note in notes))
    if unit.get("type_source"):
        lines.append(f"  - Type source: {unit.get('type_source')}")
    return lines


def unit_label(unit: dict[str, Any]) -> str:
    return str(clean_label(unit.get("type_rule_name") or unit.get("type_name") or "unknown unit"))


def activity_label(unit: dict[str, Any]) -> str:
    activity = unit.get("activity_info") or {}
    name = clean_label(activity.get("name") or "unknown")
    target = activity.get("target")
    if isinstance(target, dict) and target.get("name"):
        return f"{name}({clean_label(target.get('name'))})"
    return str(name)


def yes_no(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def clean_label(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("?") and ":" in value:
        return value.split(":", 1)[1]
    return value


def tool_text(text: str) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ],
        "isError": False,
    }


def tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": message,
            }
        ],
        "isError": True,
    }


def json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def object_schema(
    properties: dict[str, Any] | None = None,
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


def view_schema() -> dict[str, Any]:
    return object_schema(
        {
            "unit_id": int_schema("Center on this unit id."),
            "city_id": int_schema("Center on this city id."),
            "tile_id": int_schema("Center on this tile id."),
            "radius": int_schema("Tile radius.", default=3, minimum=1),
        }
    )


def string_schema(description: str, *, default: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "description": description}
    if default is not None:
        schema["default"] = default
    return schema


def int_schema(
    description: str,
    *,
    default: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "integer", "description": description}
    if default is not None:
        schema["default"] = default
    if minimum is not None:
        schema["minimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    return schema


def number_schema(description: str, *, default: float | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "number", "description": description}
    if default is not None:
        schema["default"] = default
    return schema


def bool_schema(description: str) -> dict[str, Any]:
    return {"type": "boolean", "description": description}


def read_message(stream: Any) -> tuple[dict[str, Any], str] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if line == b"":
            return None
        line = line.rstrip(b"\r\n")
        stripped = line.strip()
        if not headers and stripped.startswith(b"{"):
            return json.loads(stripped.decode("utf-8")), "json-line"
        if line == b"":
            break
        key, _, value = line.decode("ascii").partition(":")
        headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    payload = stream.read(length)
    if not payload:
        return None
    return json.loads(payload.decode("utf-8")), "content-length"


def write_message(stream: Any, message: dict[str, Any], *, framing: str) -> None:
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if framing == "json-line":
        stream.write(payload + b"\n")
        stream.flush()
        return
    stream.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
    stream.write(payload)
    stream.flush()


if __name__ == "__main__":
    main()
