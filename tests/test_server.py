import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import time
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
                if path == "/api/info":
                    return 200, {"service": "zeuz-dnc", "agent_configured": False}
                if path == "/api/workshop/info":
                    return 200, {"program_server": ""}
                if path == "/api/workshop/mirror":
                    return 200, {"ok": True, "sha256": body["sha256"]}
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
        (Path(self.temp.name) / "O4000.nc").write_bytes(b"O4000\r\nM30\r\n")
        self.request(
            "POST", "/v1/dnc/send", {"path": "O4000.nc"}, token="token-prueba"
        )
        self.assertEqual([call[1] for call in proxy.calls], [
            "/api/info", "/api/workshop/info", "/api/workshop/mirror",
            "/api/workshop/machines", "/api/machine/select", "/api/send",
        ])
        method, path, body, endpoint = proxy.calls[-1]
        self.assertEqual((method, path), ("POST", "/api/send"))
        self.assertEqual(body["path"], proxy.calls[2][2]["path"])
        self.assertEqual(body["machine"]["baudrate"], 4800)
        self.assertEqual(endpoint.host, "zeuz-dnc-a1.local")

    def test_dnc_proxy_requires_pairing(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("GET", "/v1/dnc/machines")
        self.assertEqual(error.exception.code, 401)

    def test_update_check_waits_for_clock_sync_before_starting_check(self):
        class Proxy:
            def __init__(self): self.calls = []
            def forward(self, method, path, body=None, endpoint=None, **options):
                self.calls.append((method, path, body))
                if path == "/api/system/clock/status":
                    return 200, {"supported": True, "utc_unix": int(time.time()) - 86400, "phase": "idle"}
                if path == "/api/system/clock/sync":
                    return 200, {"supported": True, "utc_unix": int(time.time()), "phase": "succeeded",
                                 "request_id": body["request_id"]}
                return 200, {"phase": "checking"}
        self.machines.save({"id": "fadal", "name": "Fadal", "dnc_host": "orange.invalid"})
        proxy = Proxy()
        self.server.dnc_proxy = proxy
        _, result = self.request("POST", "/v1/dnc/update/check", {"machine_id": "fadal"}, token="token-prueba")
        self.assertEqual(result["phase"], "checking")
        self.assertEqual([call[:2] for call in proxy.calls], [
            ("GET", "/api/system/clock/status"), ("POST", "/api/system/clock/sync"),
            ("POST", "/api/update/check")])

    def test_update_check_legacy_clock_is_optional_but_real_failure_stops_check(self):
        self.machines.save({"id": "fadal", "name": "Fadal", "dnc_host": "orange.invalid"})
        class Proxy:
            def __init__(self, status): self.status, self.calls = status, []
            def forward(self, method, path, body=None, endpoint=None, **options):
                self.calls.append((method, path))
                if path == "/api/system/clock/status":
                    return self.status, {"error": "Reloj no disponible"}
                return 200, {"phase": "checking"}
        legacy = Proxy(404)
        self.server.dnc_proxy = legacy
        self.request("POST", "/v1/dnc/update/check", {"machine_id": "fadal"}, token="token-prueba")
        self.assertEqual(legacy.calls[-1], ("POST", "/api/update/check"))
        failed = Proxy(403)
        self.server.dnc_proxy = failed
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.request("POST", "/v1/dnc/update/check", {"machine_id": "fadal"}, token="token-prueba")
        self.assertEqual(failure.exception.code, 502)
        self.assertIn("Reloj no disponible", failure.exception.read().decode())
        self.assertEqual(failed.calls, [("GET", "/api/system/clock/status")])


if __name__ == "__main__":
    unittest.main()
