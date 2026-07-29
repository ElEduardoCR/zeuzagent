import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from zeuzagent.config import AgentConfig
from zeuzagent.library import ProgramLibrary
from zeuzagent.server import create_server


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.config = AgentConfig(
            name="Prueba",
            programs_dir=self.temp.name,
            host="127.0.0.1",
            port=0,
            api_token="token-prueba",
            pairing_code="123456",
            discovery=False,
        )
        self.server = create_server(self.config, ProgramLibrary(Path(self.temp.name)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method: str, path: str, body=None, token: str | None = None):
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request) as response:
            return response.status, json.load(response)

    def test_pair_and_use_program_api(self) -> None:
        status, paired = self.request("POST", "/v1/pair", {"code": "123456"})
        self.assertEqual(status, 200)
        self.assertEqual(paired["token"], "token-prueba")

        self.request(
            "PUT",
            "/v1/programs/content",
            {"path": "O4000.nc", "content": "O4000\nM30\n"},
            token=paired["token"],
        )
        _, listing = self.request("GET", "/v1/programs?path=", token=paired["token"])
        self.assertEqual(listing["entries"][0]["name"], "O4000.nc")

    def test_private_routes_require_pairing(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("GET", "/v1/programs")
        self.assertEqual(error.exception.code, 401)

    def test_invalid_pairing_code_is_rejected(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("POST", "/v1/pair", {"code": "000000"})
        self.assertEqual(error.exception.code, 403)


if __name__ == "__main__":
    unittest.main()

