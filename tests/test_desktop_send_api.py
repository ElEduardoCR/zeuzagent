"""Real loopback HTTP coverage of Edit -> Agent -> simulated ZeuzDNC."""
import base64
import hashlib
import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from zeuzagent.config import AgentConfig
from zeuzagent.library import MAX_PREVIEW_BYTES, ProgramLibrary
from zeuzagent.machines import MachineRegistry, serial_profile
from zeuzagent.server import create_server


class DesktopSendAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fake_programs = {}
        self.sends = []
        self.mirrors = []
        self.fail_mirror = False
        self.drop_send = False
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def reply(self, value, status=200):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def do_GET(self):
                from urllib.parse import parse_qs, urlsplit
                parsed = urlsplit(self.path)
                if parsed.path == "/api/info":
                    return self.reply({"service": "zeuz-dnc", "agent_configured": False})
                if parsed.path == "/api/workshop/info":
                    return self.reply({"program_server": ""})
                if parsed.path == "/api/workshop/machines":
                    return self.reply(fixture.profiles)
                if parsed.path == "/api/workshop/bytes":
                    path = parse_qs(parsed.query)["path"][0]
                    return self.reply({"data": base64.b64encode(fixture.fake_programs[path]).decode()})
                self.reply({"error": "Fixture route missing"}, 404)
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if self.path == "/api/workshop/mirror":
                    fixture.mirrors.append(body)
                    if fixture.fail_mirror:
                        return self.reply({"ok": False, "error": "No disk space in simulation"}, 500)
                    raw = base64.b64decode(body["data"], validate=True)
                    fixture.fake_programs[body["path"]] = raw
                    return self.reply({"ok": True, "sha256": hashlib.sha256(raw).hexdigest()})
                if self.path == "/api/machine/select":
                    return self.reply({"ok": True})
                if self.path == "/api/send":
                    fixture.sends.append(body)
                    if fixture.drop_send:
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.connection.close()
                        return
                    if body["path"] not in fixture.fake_programs:
                        return self.reply({"ok": False, "error": "Program not staged"}, 400)
                    return self.reply({"ok": True})
                self.reply({"error": "Fixture route missing"}, 404)
            def log_message(self, *args):
                pass
        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.fake_thread = threading.Thread(target=self.fake.serve_forever, daemon=True)
        self.fake_thread.start()
        self.machines = MachineRegistry(self.root / "machines.json")
        machine = self.machines.save({"id": "fadal", "name": "Fadal", "dnc_host": "127.0.0.1",
                                      "dnc_port": self.fake.server_port, "baudrate": 4800,
                                      "bytesize": 7, "parity": "E", "stopbits": 2,
                                      "flow_control": "xonxoff", "line_terminator": "CR"})
        self.profiles = [serial_profile(machine)]
        self.config = AgentConfig("Desktop tests", str(self.root / "programs"),
                                  host="127.0.0.1", port=0, api_token="desktop-test-token",
                                  pairing_code="123456", discovery=False)
        self.server = None
        self.start_agent(self.config)

    def start_agent(self, config):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join()
        self.server = create_server(config, ProgramLibrary(Path(config.programs_dir)), self.machines)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.fake.shutdown()
        self.fake.server_close()
        self.fake_thread.join()
        self.temp.cleanup()

    def request(self, path="/v1/dnc/program/send", body=None, token="desktop-test-token", method="POST"):
        body = body if body is not None else {"path": "O1234.nc", "machine_id": "fadal"}
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if method == "POST" else None,
                                     method=method, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def local_program(self):
        raw = b"%\r\nO1234\r\n(COMENTARIO \xf1)\r\n" + b"G1 X1.\r\n" * (MAX_PREVIEW_BYTES // 8 + 100)
        (Path(self.config.programs_dir) / "O1234.nc").write_bytes(raw)
        return raw

    def test_local_library_stages_full_bytes_and_returns_effective_path(self):
        original = self.local_program()
        code, result = self.request()
        self.assertEqual(code, 200, result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["filename"], "O1234.nc")
        self.assertEqual(result["machine_id"], "fadal")
        self.assertEqual(result["original_path"], "O1234.nc")
        self.assertTrue(result["path"].startswith("Agent Transfers/"))
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(self.fake_programs[result["path"]], original)
        self.assertEqual(self.sends[0]["path"], result["path"])
        self.assertEqual(self.sends[0]["machine"], self.profiles[0])
        self.assertEqual((Path(self.config.programs_dir) / "O1234.nc").read_bytes(), original)

    def test_shared_library_keeps_original_path_and_bytes_without_staging(self):
        original = b"%\r\nO1234\r\nM30\r\n"
        self.fake_programs["O1234.nc"] = original
        self.start_agent(replace(self.config, program_server_host="127.0.0.1", program_server_port=self.fake.server_port))
        code, result = self.request()
        self.assertEqual(code, 200, result)
        self.assertEqual(result["path"], "O1234.nc")
        self.assertEqual(self.mirrors, [])
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(self.fake_programs, {"O1234.nc": original})

    def test_authentication_required_and_explicit_machine_required(self):
        self.local_program()
        self.assertEqual(self.request(token="wrong")[0], 401)
        self.assertEqual(self.request(body={"path": "O1234.nc"})[0], 400)
        self.assertEqual(self.request(method="GET")[0], 405)
        self.assertEqual(self.mirrors, [])
        self.assertEqual(self.sends, [])

    def test_failed_staging_is_safe_422_without_send(self):
        self.local_program()
        self.fail_mirror = True
        code, result = self.request()
        self.assertEqual(code, 422, result)
        self.assertIn("No disk space", result["error"])
        self.assertFalse(result.get("uncertain", False))
        self.assertEqual(self.sends, [])

    def test_uncertain_send_returns_502_without_repeating(self):
        self.local_program()
        self.drop_send = True
        code, result = self.request()
        self.assertEqual(code, 502, result)
        self.assertTrue(result["uncertain"])
        self.assertEqual(len(self.sends), 1)

    def test_profile_conflict_rejects_before_serial_send(self):
        self.local_program()
        self.profiles[0]["baudrate"] = 19200
        code, result = self.request()
        self.assertEqual(code, 409, result)
        self.assertEqual(self.sends, [])


if __name__ == "__main__":
    unittest.main()
