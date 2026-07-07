from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from freeciv_agent.api_turn_runner import (
    api_session_context_prompt,
    load_api_memory,
    update_api_memory,
)


class ApiTurnRunnerMemoryTests(unittest.TestCase):
    def test_rolling_memory_truncates_and_prompts_compactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".api-agent-memory.json"
            payload: dict[str, object] = {}

            for turn in range(1, 5):
                update_api_memory(
                    path,
                    payload,
                    turn_result={
                        "player": "AgentA",
                        "turn": turn,
                        "turn_summary": f"summary {turn}",
                        "private_intent": f"intent {turn}",
                        "public_message": f"message {turn}",
                        "actions_taken": [f"action {turn}"],
                        "errors": [],
                    },
                    max_turns=2,
                )
                payload = load_api_memory(path)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["player"], "AgentA")
            self.assertEqual(
                [turn["turn"] for turn in saved["recent_turns"]],
                [3, 4],
            )

            prompt = api_session_context_prompt("rolling-summary", saved)
            self.assertIn("Session mode: rolling-summary", prompt)
            self.assertNotIn("summary 2", prompt)
            self.assertIn("summary 3", prompt)
            self.assertIn("summary 4", prompt)

    def test_turn_fresh_prompt_declares_no_prior_context(self) -> None:
        prompt = api_session_context_prompt("turn-fresh", {})
        self.assertIn("do not have prior-turn conversation context", prompt)


if __name__ == "__main__":
    unittest.main()
