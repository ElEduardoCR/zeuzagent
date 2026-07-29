import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from zeuzagent.config import AgentConfig, load_or_create_config
from zeuzagent.runtime import AgentRuntime


class RuntimeTests(unittest.TestCase):
    def test_runtime_starts_and_stops_the_real_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = AgentConfig(
                name="Runtime test",
                programs_dir=directory,
                host="127.0.0.1",
                port=0,
                api_token="token",
                pairing_code="123456",
                discovery=False,
            )
            runtime = AgentRuntime(config)
            runtime.start()
            try:
                self.assertTrue(runtime.running)
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{runtime.port}/v1/health",
                    timeout=3,
                ) as response:
                    payload = json.load(response)
                self.assertTrue(payload["ok"])
            finally:
                runtime.stop()
            self.assertFalse(runtime.running)

    def test_configuration_is_created_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.json"
            first, target, created = load_or_create_config(path)
            second, _, created_again = load_or_create_config(path)
            self.assertEqual(target, path)
            self.assertTrue(created)
            self.assertFalse(created_again)
            self.assertEqual(first.api_token, second.api_token)


if __name__ == "__main__":
    unittest.main()
