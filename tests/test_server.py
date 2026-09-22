import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from zeuzagent.config import AgentConfig
from zeuzagent.library import ProgramLibrary
from zeuzagent.machines import MachineRegistry
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
        self.machines = MachineRegistry(Path(self.temp.name) / "machines.json")
        self.server = create_server(
            self.config, ProgramLibrary(Path(self.temp.name)), self.machines
        )
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

    def test_machines_are_owned_by_agent_and_send_is_routed(self) -> None:
        class FakeProxy:
            def __init__(self):
                self.calls = []

            def forward(self, method, path, body=None, endpoint=None):
                self.calls.append((method, path, body, endpoint))
                if path == "/api/workshop/machines":
                    return 200, [machine]
                return 200, {"ok": True}

        proxy = FakeProxy()
        self.server.dnc_proxy = proxy
        machine = self.machines.save({
            "id": "fanuc",
            "name": "Fanuc",
            "dnc_host": "zeuz-dnc-a1.local",
            "dnc_port": 5000,
            "baudrate": 4800,
            "bytesize": 7,
            "parity": "E",
            "stopbits": 2,
            "flow_control": "xonxoff",
            "line_terminator": "CR",
        })
        status, machines = self.request(
            "GET",
            "/v1/dnc/machines",
            token="token-prueba",
        )
        self.assertEqual(status, 200)
        self.assertEqual(machines[0]["id"], "fanuc")
        self.assertEqual(proxy.calls, [])

        self.request(
            "POST", "/v1/dnc/machine/select", {"id": machine["id"]}, token="token-prueba"
        )
        self.request(
            "POST", "/v1/dnc/send", {"path": "O4000.nc"}, token="token-prueba"
        )
        self.assertEqual(proxy.calls[0][1], "/api/workshop/machines")
        self.assertEqual(proxy.calls[1][1], "/api/machine/select")
        method, path, body, endpoint = proxy.calls[2]
        self.assertEqual((method, path), ("POST", "/api/send"))
        self.assertEqual(body["machine"]["baudrate"], 4800)
        self.assertEqual(endpoint.host, "zeuz-dnc-a1.local")

    def test_dnc_proxy_requires_pairing(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("GET", "/v1/dnc/machines")
        self.assertEqual(error.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
