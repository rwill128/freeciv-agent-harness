from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from freeciv_agent.codex_turn_runner import validate_tool_use


class CodexTurnRunnerValidationTests(unittest.TestCase):
    def test_file_only_mcp_phase_done_reads_player_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            artifact_dir = workspace / "mcp-artifacts"
            artifact_dir.mkdir()
            phase_done_path = artifact_dir / "phase_done.txt"
            phase_done_path.write_text(
                json.dumps({"ok": True, "applied": True}) + "\n",
                encoding="utf-8",
            )
            stdout = "\n".join(
                json.dumps(event)
                for event in [
                    mcp_event("turn_dashboard", "# dashboard"),
                    mcp_event("say", '{"ok": true, "sent": true}'),
                    mcp_event("narrative_append", '{"ok": true, "appended": true}'),
                    mcp_event(
                        "phase_done",
                        "\n".join(
                            [
                                "# MCP Result Written To File",
                                "",
                                "Tool: phase_done",
                                f"Full result file: {phase_done_path}",
                                "Bytes: 28",
                                "",
                                "## Preview",
                                '{"ok": true,',
                            ]
                        ),
                    ),
                ]
            )

            evidence = validate_tool_use(
                stdout,
                interface="mcp",
                workspace=workspace,
                narrative_log=True,
                public_turn_message=True,
                mcp_artifact_mode="file-only",
            )

            self.assertEqual(
                evidence,
                {
                    "narrative_observed": True,
                    "public_message_observed": True,
                    "phase_done_observed": True,
                    "non_terminal_game_call_observed": True,
                },
            )


def mcp_event(tool: str, text: str) -> dict[str, object]:
    return {
        "item": {
            "type": "mcp_tool_call",
            "tool": tool,
            "status": "completed",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": text,
                    }
                ],
                "isError": False,
            },
        }
    }


if __name__ == "__main__":
    unittest.main()
