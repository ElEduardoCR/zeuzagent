import json
import tempfile
import threading
import unittest
from dataclasses import replace
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from zeuzagent.config import AgentConfig
from zeuzagent.library import LibraryError, ProgramLibrary
from zeuzagent.machines import MachineRegistry
from zeuzagent.presetter import PresetterClients, validate_upload
from zeuzagent.server import create_server


class PresetterPresenceTests(unittest.TestCase):
    def test_presence_expires_and_registration_refreshes_only_that_client(self):
        clock = [0.0]
        clients = PresetterClients(lambda: clock[0])
        body = {"client_id": "station-a", "name": "Presetter A", "version": "0.1", "capabilities": ["simulation"]}
        clients.register(body, "192.0.2.1")
        clock[0] = 80
        clients.register(body, "192.0.2.2")
        clients.register({**body, "client_id": "station-b"}, "192.0.2.3")
        clock[0] = 160
        clients.register(body, "192.0.2.2")
        clock[0] = 171
        self.assertEqual([c["client_id"] for c in clients.list()], ["station-a"])
        self.assertEqual(clients.list()[0]["address"], "192.0.2.2")
        clock[0] = 250
        self.assertEqual(clients.list(), [])

    def test_validation_rejects_paths_controls_and_character_replacement(self):
        base = {"machine_id": "fanuc", "filename": "O9000.nc", "content": "%\r\nO9000\r\nM30\r\n%\r\n"}
        self.assertEqual(validate_upload(base)[1], "O9000.nc")
        for field, value in (("filename", "../O9000.nc"), ("filename", "C:\\O9000.nc"),
                             ("content", "\x00"), ("content", "G10 (medición)"),
                             ("content", "G10\x1b"), ("content", "A" * (512 * 1024 + 1))):
            with self.subTest(field=field, value=str(value)[:20]), self.assertRaises(LibraryError):
                validate_upload({**base, field: value})


class PresetterServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = AgentConfig(name="Taller", programs_dir=str(root / "agent"),
                                  host="127.0.0.1", port=0, api_token="presetter-test-token",
                                  pairing_code="123456", discovery=False)
        self.machines = MachineRegistry(root / "machines.json")
        self.server = create_server(self.config, ProgramLibrary(root / "agent"), self.machines)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.received = []
        self.pi_library = ProgramLibrary(root / "pi")
        owner = self

        class PiHandler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_PUT(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.received.append((self.command, self.path, self.headers.get("Authorization"), body))
                result = owner.pi_library.write(body["path"], body["content"])
                raw = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.pi = ThreadingHTTPServer(("127.0.0.1", 0), PiHandler)
        self.pi_thread = threading.Thread(target=self.pi.serve_forever, daemon=True)
        self.pi_thread.start()
        self.machine = self.machines.save({"id": "fanuc", "name": "Fanuc 0-MD", "dnc_host": "127.0.0.1", "dnc_port": self.pi.server_port})

    def tearDown(self):
        for server, thread in ((self.server, self.thread), (self.pi, self.pi_thread)):
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, body=None, *, authorized=True):
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["Authorization"] = "Bearer " + self.config.api_token
        request = urllib.request.Request(self.base + path, method=method, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.load(response)

    def test_capability_presence_and_targets_require_auth(self):
        _, info = self.request("GET", "/v1/info", authorized=False)
        self.assertEqual(info["capabilities"]["presetter_api"], 1)
        for method, route in (("GET", "targets"), ("GET", "clients"), ("POST", "register"), ("POST", "jobs")):
            with self.subTest(route=route), self.assertRaises(urllib.error.HTTPError) as error:
                self.request(method, "/v1/presetter/" + route, authorized=False)
            self.assertEqual(error.exception.code, 401)
        self.request("POST", "/v1/presetter/register", {"client_id": "station", "name": "Presetter A", "capabilities": ["simulation"]})
        _, clients = self.request("GET", "/v1/presetter/clients")
        self.assertEqual(clients["clients"][0]["name"], "Presetter A")
        self.assertEqual(clients["clients"][0]["address"], "127.0.0.1")
        _, targets = self.request("GET", "/v1/presetter/targets")
        self.assertEqual(targets["targets"], [{"id": "fanuc", "name": "Fanuc 0-MD", "dnc_host": "127.0.0.1", "dnc_port": self.pi.server_port}])

    def test_upload_reaches_selected_zeuz_and_never_calls_serial_send(self):
        body = {"machine_id": "fanuc", "filename": "offsets.txt", "content": "G10 L10 P1 R123.456\r\n", "dnc_host": "ignored.example"}
        status, result = self.request("POST", "/v1/presetter/jobs", body)
        self.assertEqual(status, 201)
        self.assertEqual(result["status"], "stored")
        self.assertIs(result["cnc_transmission_started"], False)
        self.assertEqual(result["storage_scope"], "device")
        self.assertEqual(result["library_host"], "127.0.0.1")
        self.assertEqual(result["library_port"], self.pi.server_port)
        self.assertEqual(self.received[0][:3], ("PUT", "/api/workshop/content", "Bearer presetter-test-token"))
        self.assertEqual(self.pi_library.read(result["path"])["content"], body["content"])
        self.assertFalse((Path(self.config.programs_dir) / result["path"]).exists())
        _, second = self.request("POST", "/v1/presetter/jobs", body)
        self.assertNotEqual(result["path"], second["path"])
        self.assertEqual(len(self.received), 2)
        self.assertTrue(all(call[0:2] == ("PUT", "/api/workshop/content") for call in self.received))

    def test_shared_server_receives_file_in_active_catalog_for_selected_machine(self):
        # The selected Zeuz's private library is not its catalog when the
        # workshop server is enabled. It may be offline while preparing files.
        self.machines.save({**self.machine, "dnc_host": "offline-selected.local", "dnc_port": 9})
        self.server.config = replace(self.config, program_server_host="127.0.0.1", program_server_port=self.pi.server_port)
        status, result = self.request("POST", "/v1/presetter/jobs", {
            "machine_id": "fanuc", "filename": "shared.txt", "content": "G10\r\n",
        })
        self.assertEqual(status, 201)
        self.assertEqual(result["machine_id"], "fanuc")
        self.assertEqual(result["machine_name"], "Fanuc 0-MD")
        self.assertEqual(result["storage_scope"], "workshop")
        self.assertEqual((result["library_host"], result["library_port"]), ("127.0.0.1", self.pi.server_port))
        self.assertEqual(self.pi_library.read(result["path"])["content"], "G10\r\n")
        self.assertEqual(len(self.received), 1)
        self.assertIs(result["cnc_transmission_started"], False)

    def test_invalid_target_or_content_never_reaches_any_pi(self):
        base = {"machine_id": "fanuc", "filename": "offsets.txt", "content": "G10\n"}
        for change in ({"machine_id": "missing"}, {"filename": "../offsets.txt"}, {"content": "G10\x00"}):
            with self.subTest(change=change), self.assertRaises(urllib.error.HTTPError) as error:
                self.request("POST", "/v1/presetter/jobs", {**base, **change})
            self.assertEqual(error.exception.code, 400)
        self.assertEqual(self.received, [])

    def test_missing_firmware_returns_error_without_claiming_stored(self):
        class UnsupportedProxy:
            def forward(self, *args):
                return 404, {"ok": False, "error": "Ruta no encontrada"}
        self.server.dnc_proxy = UnsupportedProxy()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("POST", "/v1/presetter/jobs", {"machine_id": "fanuc", "filename": "offsets.txt", "content": "G10\n"})
        self.assertEqual(error.exception.code, 404)
        self.assertEqual(self.received, [])


if __name__ == "__main__":
    unittest.main()
