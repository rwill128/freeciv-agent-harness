from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from civ5_agent.log_bridge import (
    COMMAND_PREFIX,
    STATE_PREFIX,
    latest_command_result,
    latest_state,
    log_status,
)


class Civ5LogBridgeTests(unittest.TestCase):
    def test_latest_state_and_command_read_framed_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "Lua.log"
            log.write_text(
                "\n".join(
                    [
                        "ordinary Lua output",
                        f'{STATE_PREFIX}{{"schema":"civ5-agent-state-v0","game":{{"turn":1}}}}',
                        f'{COMMAND_PREFIX}{{"schema":"civ5-agent-command-result-v0","ok":true}}',
                        f'{STATE_PREFIX}{{"schema":"civ5-agent-state-v0","game":{{"turn":2}}}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            self.assertEqual(latest_state(log)["game"]["turn"], 2)
            self.assertTrue(latest_command_result(log)["ok"])
            status = log_status(log)
            self.assertEqual(status["state_records"], 2)
            self.assertEqual(status["command_records"], 1)


if __name__ == "__main__":
    unittest.main()
