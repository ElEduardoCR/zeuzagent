import base64
import hashlib
import io
import json
import os
import socket
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from zeuzagent.config import AgentConfig
from zeuzagent.library import MAX_PREVIEW_BYTES
from zeuzagent.native_host import NativeHost, TransferUncertain, serve
from zeuzagent.machines import MachineError, serial_profile
from zeuzagent.runtime import AgentRuntime


def free_port():
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


class NativeHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.programs = self.root / "programs"
        self.programs.mkdir()
        self.config_path = self.root / "config.json"
        self.config = AgentConfig("Taller de pruebas", str(self.programs), host="127.0.0.1",
                                  port=free_port(), api_token="native-secret-test-token",
                                  pairing_code="053218", discovery=False)
        self.config.save(self.config_path)
        self.host = NativeHost(self.config_path, auto_start=False, background=False)

    def tearDown(self):
        self.host.close()
        self.temp.cleanup()

    def machine(self):
        return self.host.handle("machines.save", {"name": "Fadal", "id": "fadal",
                                "dnc_host": "127.0.0.1", "dnc_port": 55991})["machine"]

    def test_state_keeps_config_credentials_and_redacts_diagnostics(self):
        original = self.config_path.read_bytes()
        self.host.record("warning", "Authorization " + self.config.api_token)
        state = self.host.handle("state")
        self.assertEqual(state["pairingCode"], "053218")
        self.assertNotIn(self.config.api_token, json.dumps(state))
        self.assertNotIn("api_token", state)
        self.assertEqual(original, self.config_path.read_bytes())

    def test_list_search_preview_and_export_use_existing_library(self):
        payload = b"%\nO1234\n" + b"G1 X10.\n" * (MAX_PREVIEW_BYTES // 8 + 5)
        (self.programs / "O1234.nc").write_bytes(payload)
        (self.programs / "folder").mkdir()
        listing = self.host.handle("programs.list")
        self.assertTrue(listing["entries"][0]["isDirectory"])
        self.assertEqual(listing["source"], "local")
        self.assertEqual(self.host.handle("programs.list", {"query": "1234"})["entries"][0]["path"], "O1234.nc")
        preview = self.host.handle("programs.read", {"path": "O1234.nc"})
        self.assertTrue(preview["truncated"])
        self.assertLess(len(preview["content"]), len(payload))
        exported = self.host.handle("programs.export", {"path": "O1234.nc"})
        self.assertFalse(exported["temporary"])
        self.assertEqual(Path(exported["path"]).read_bytes(), payload)
        with self.assertRaises(Exception):
            self.host.handle("programs.read", {"path": "../config.json"})

    def test_import_preserves_full_bytes_and_never_overwrites_existing_file(self):
        outside = self.root / "O1.nc"
        raw = b"%\r\n(COMENTARIO \xf1)\r\nO1\r\nM30\r\n"
        outside.write_bytes(raw)
        (self.programs / "O1.nc").write_bytes(b"original")
        result = self.host.handle("programs.import", {"paths": [str(outside)]})
        self.assertEqual(result["paths"], ["O1 (2).nc"])
        self.assertEqual((self.programs / "O1.nc").read_bytes(), b"original")
        self.assertEqual((self.programs / "O1 (2).nc").read_bytes(), raw)
        outside.write_bytes(b"%PDF-binary")
        with self.assertRaisesRegex(ValueError, "texto CNC"):
            self.host.handle("programs.import", {"paths": [str(outside)]})

    def test_explicit_local_operations_keep_global_shared_configuration(self):
        configured = replace(self.config, program_server_host="offline-shared.invalid", program_server_port=5001)
        configured.save(self.config_path)
        self.host._config = configured
        original_configuration = self.config_path.read_bytes()
        raw = b"%\r\nO1\r\n(COMENTARIO \xf1)\r\nM30\r\n"
        (self.programs / "O1.nc").write_bytes(raw)
        incoming = self.root / "O2.nc"
        incoming.write_bytes(raw.replace(b"O1", b"O2"))
        # An offline shared server must not even be constructed for PC actions.
        with patch("zeuzagent.native_host.RemoteProgramLibrary", side_effect=AssertionError("Unexpected remote library")):
            listing = self.host.handle("programs.list", {"source": "local"})
            self.assertEqual(listing["source"], "local")
            self.assertEqual(listing["entries"][0]["path"], "O1.nc")
            preview = self.host.handle("programs.read", {"source": "local", "path": "O1.nc"})
            self.assertEqual(preview["content"].encode("latin-1"), raw)
            exported = self.host.handle("programs.export", {"source": "local", "path": "O1.nc"})
            self.assertEqual(Path(exported["path"]), (self.programs / "O1.nc").resolve())
            self.assertFalse(exported["temporary"])
            imported = self.host.handle("programs.import", {"source": "local", "paths": [str(incoming)]})
            self.assertEqual(imported["paths"], ["O2.nc"])
        self.assertEqual((self.programs / "O2.nc").read_bytes(), incoming.read_bytes())
        self.assertEqual(self.config_path.read_bytes(), original_configuration)
        self.assertIs(self.host._config, configured)

    def test_source_is_optional_but_explicit_server_requires_configuration(self):
        with self.assertRaisesRegex(ValueError, "servidor"):
            self.host.handle("programs.list", {"source": "server"})
        with self.assertRaisesRegex(ValueError, "biblioteca"):
            self.host.handle("programs.read", {"source": "invalid", "path": "O1.nc"})
        self.host._config = replace(self.config, program_server_host="shared.local")
        with patch("zeuzagent.native_host.RemoteProgramLibrary") as remote:
            remote.return_value.list.return_value = {"path": "", "entries": []}
            self.assertEqual(self.host.handle("programs.list")["source"], "server")
            self.assertEqual(self.host.handle("programs.list", {"source": "server"})["source"], "server")
            self.assertEqual(remote.call_count, 2)

    def test_injected_runtime_does_not_start_or_stop_external_owner(self):
        injected = NativeHost(self.config_path, runtime=self.host._runtime)
        try:
            self.assertFalse(injected._runtime.running)
            self.assertEqual(injected.dispatch("programs.list")["source"], "local")
            with patch.object(self.host._runtime, "stop") as stop:
                injected.close()
                stop.assert_not_called()
        finally:
            injected.close()

    def test_foreign_server_not_stopped_or_configured(self):
        self.host.close()
        original = self.config_path.read_bytes()
        external = AgentRuntime(self.config)
        external.start()
        contender = NativeHost(self.config_path, background=False)
        try:
            state = contender.state()
            self.assertFalse(state["running"])
            self.assertIn("versión anterior", state["error"])
            self.assertTrue(external.running)
            with self.assertRaisesRegex(ValueError, "otra versión"):
                contender.handle("config.save", {"name": "Change forbidden"})
            self.assertEqual(original, self.config_path.read_bytes())
            contender.close()
            self.assertTrue(external.running)
        finally:
            contender.close()
            external.stop()

    def test_local_send_stages_full_original_then_routes_once(self):
        machine = self.machine()
        raw = b"%\nO1234\n" + b"G1 X10.\n" * (MAX_PREVIEW_BYTES // 8 + 15)
        (self.programs / "O1234.nc").write_bytes(raw)
        calls = []
        def remote(method, path, body, endpoint):
            calls.append((method, path, body))
            if path == "/api/info":
                return {"service": "zeuz-dnc", "agent_configured": False}
            if path == "/api/workshop/info":
                return {"program_server": ""}
            if path == "/api/workshop/mirror":
                self.assertEqual(base64.b64decode(body["data"]), raw)
                self.assertEqual(body["sha256"], hashlib.sha256(raw).hexdigest())
                return {"ok": True, "sha256": body["sha256"]}
            self.fail(path)
        with patch.object(AgentRuntime, "running", property(lambda _: True)), \
             patch.object(self.host, "_remote", side_effect=remote), \
             patch.object(self.host, "_api", return_value={"ok": True}) as api:
            result = self.host.handle("transfer.send", {"path": "O1234.nc", "machineID": machine["id"]})
        self.assertTrue(result["path"].startswith("Agent Transfers/"))
        self.assertTrue(result["path"].endswith("/O1234.nc"))
        api.assert_called_once_with("POST", "/v1/dnc/send", {"path": result["path"], "machine_id": "fadal"})
        self.assertEqual((self.programs / "O1234.nc").read_bytes(), raw)
        self.assertEqual(calls[-1][1], "/api/workshop/mirror")

    def test_failed_staging_or_profile_preflight_never_sends(self):
        self.machine()
        (self.programs / "O1.nc").write_bytes(b"O1\nM30\n")
        with patch.object(AgentRuntime, "running", property(lambda _: True)), \
             patch.object(self.host, "_stage_destination", return_value=object()), \
             patch.object(self.host, "_remote", return_value={"ok": True, "sha256": "bad"}), \
             patch.object(self.host, "_api") as api:
            with self.assertRaisesRegex(ValueError, "archivo completo"):
                self.host.handle("transfer.send", {"path": "O1.nc", "machineID": "fadal"})
            api.assert_not_called()

    def test_explicit_local_send_stages_pc_bytes_with_global_shared_server(self):
        self.machine()
        configured = replace(self.config, program_server_host="offline-shared.invalid")
        configured.save(self.config_path)
        self.host._config = configured
        original_configuration = self.config_path.read_bytes()
        raw = b"%\r\nO1234\r\n" + b"G1 X1.\r\n" * (MAX_PREVIEW_BYTES // 8 + 10)
        (self.programs / "O1234.nc").write_bytes(raw)
        mirrored = []
        def remote(method, path, body, endpoint):
            if path == "/api/info":
                return {"service": "zeuz-dnc", "agent_configured": False}
            if path == "/api/workshop/info":
                return {"program_server": "http://actual-workshop.local:5002" if endpoint.host == "127.0.0.1" else ""}
            if path == "/api/workshop/mirror":
                self.assertEqual((endpoint.host, endpoint.port), ("actual-workshop.local", 5002))
                self.assertEqual(base64.b64decode(body["data"]), raw)
                mirrored.append(body["path"])
                return {"ok": True, "sha256": hashlib.sha256(raw).hexdigest()}
            self.fail(path)
        with patch.object(AgentRuntime, "running", property(lambda _: True)), \
             patch("zeuzagent.native_host.RemoteProgramLibrary", side_effect=AssertionError("Unexpected shared read")), \
             patch.object(self.host, "_remote", side_effect=remote), \
             patch.object(self.host, "_api", return_value={"ok": True}) as api:
            result = self.host.handle("transfer.send", {"source": "local", "path": "O1234.nc", "machineID": "fadal"})
        self.assertEqual(result["source"], "local")
        self.assertEqual(mirrored, [result["path"]])
        self.assertTrue(result["path"].startswith("Agent Transfers/"))
        api.assert_called_once_with("POST", "/v1/dnc/send", {"path": result["path"], "machine_id": "fadal"})
        self.assertIs(self.host._config, configured)
        self.assertEqual(self.config_path.read_bytes(), original_configuration)

    def test_uncertain_send_propagates_without_repeating(self):
        self.machine()
        (self.programs / "O1.nc").write_bytes(b"O1\nM30\n")
        with patch.object(AgentRuntime, "running", property(lambda _: True)), \
             patch.object(self.host, "_stage_destination", return_value=object()), \
             patch.object(self.host, "_remote", side_effect=lambda m, p, b, e: {"sha256": b["sha256"]}), \
             patch.object(self.host, "_api", side_effect=TransferUncertain("timeout")) as api:
            with self.assertRaises(TransferUncertain):
                self.host.handle("transfer.send", {"path": "O1.nc", "machineID": "fadal"})
            self.assertEqual(api.call_count, 1)

    def test_shared_server_sends_original_path_without_upload(self):
        self.machine()
        self.host._config = replace(self.config, program_server_host="shared.local")
        class Library:
            def read_bytes(self, path):
                return "O1.nc", b"O1\nM30\n"
        with patch.object(AgentRuntime, "running", property(lambda _: True)), \
             patch.object(self.host, "_library", return_value=Library()), \
             patch.object(self.host, "_remote") as remote, \
             patch.object(self.host, "_api", return_value={"ok": True}) as api:
            result = self.host.handle("transfer.send", {"path": "folder/O1.nc", "machineID": "fadal"})
        self.assertEqual(result["path"], "folder/O1.nc")
        remote.assert_not_called()
        api.assert_called_once_with("POST", "/v1/dnc/send", {"path": "folder/O1.nc", "machine_id": "fadal"})

    def test_machine_revisions_are_required_on_stale_edits(self):
        original = self.machine()
        self.host.handle("machines.save", {**original, "name": "Fadal updated"})
        with self.assertRaisesRegex(MachineError, "cambió"):
            self.host.handle("machines.save", {**original, "name": "Fadal stale"})

    def test_rpc_is_only_json_and_preserves_request_ids(self):
        input_stream = io.StringIO('{"id":"1","method":"state"}\ninvalid\n'
                                   '{"id":"2","method":"programs.read","params":{"path":"missing.nc"}}\n')
        output = io.StringIO()
        serve(self.host, input_stream, output)
        payloads = [json.loads(line) for line in output.getvalue().splitlines()]
        responses = {item["id"]: item for item in payloads}
        self.assertIn("result", responses["1"])
        self.assertIn("error", responses["2"])
        self.assertIn("error", responses[None])
        self.assertNotIn(self.config.api_token, output.getvalue())

    @unittest.skipUnless(os.name == "posix", "Standalone native helper currently ships on macOS only")
    def test_instance_lock_prevents_second_native_owner(self):
        with self.assertRaisesRegex(RuntimeError, "otra ventana"):
            NativeHost(self.config_path, auto_start=False, background=False)

    def test_loopback_end_to_end_full_local_program_and_explicit_machine(self):
        # Real HTTP from native host -> Agent v1 -> simulated ZeuzDNC. There is
        # no serial module, physical device or real network address in this test.
        staged, sends, profile = {}, [], []
        class Handler(BaseHTTPRequestHandler):
            def reply(self, value):
                raw = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def do_GET(self):
                if self.path == "/api/info":
                    return self.reply({"service": "zeuz-dnc", "agent_configured": False})
                if self.path == "/api/workshop/info":
                    return self.reply({"program_server": ""})
                if self.path == "/api/workshop/machines":
                    return self.reply(profile)
                if self.path == "/api/transfer/status":
                    return self.reply({"status": "success", "machine": "Fadal", "percent": 100})
                self.send_error(404)
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if self.path == "/api/workshop/mirror":
                    staged[body["path"]] = base64.b64decode(body["data"], validate=True)
                    return self.reply({"ok": True, "sha256": hashlib.sha256(staged[body["path"]]).hexdigest()})
                if self.path == "/api/send":
                    sends.append(body)
                    return self.reply({"ok": True})
                if self.path in {"/api/machine/select", "/api/send/cancel"}:
                    return self.reply({"ok": True})
                self.send_error(404)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            machine = self.host.handle("machines.save", {"id": "fadal", "name": "Fadal",
                "dnc_host": "127.0.0.1", "dnc_port": server.server_port})["machine"]
            profile.append(serial_profile(machine))
            original = b"%\r\nO1234\r\n" + b"G1 X1.\r\n" * (MAX_PREVIEW_BYTES // 8 + 100)
            (self.programs / "O1234.nc").write_bytes(original)
            self.assertTrue(self.host.start()["ok"])
            result = self.host.handle("transfer.send", {"path": "O1234.nc", "machineID": "fadal"})
            self.assertEqual(len(sends), 1)
            self.assertEqual(staged[sends[0]["path"]], original)
            self.assertEqual(sends[0]["machine"], serial_profile(machine))
            self.assertEqual(sends[0]["path"], result["path"])
            status = self.host.handle("transfer.status", {"machineID": "fadal"})
            self.assertEqual(status["status"], "success")
            self.host.handle("transfer.cancel", {"machineID": "fadal"})
            self.assertEqual(len(sends), 1)
        finally:
            self.host.stop()
            server.shutdown()
            server.server_close()
            thread.join()


class APIUncertaintyTests(unittest.TestCase):
    def test_actual_http_send_503_is_uncertain_and_409_is_safe(self):
        response_status = [503]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(response_status[0])
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"Fake CNC rejection"}')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            config = AgentConfig("test", temp, host="127.0.0.1", port=server.server_port,
                                 api_token="token", pairing_code="123456", discovery=False)
            config.save(path)
            host = NativeHost(path, auto_start=False, background=False)
            try:
                with patch.object(AgentRuntime, "running", property(lambda _: True)):
                    with self.assertRaises(TransferUncertain):
                        host._api("POST", "/v1/dnc/send", {"machine_id": "a", "path": "O1"})
                    response_status[0] = 409
                    with self.assertRaises(ValueError) as error:
                        host._api("POST", "/v1/dnc/send", {"machine_id": "a", "path": "O1"})
                    self.assertFalse(getattr(error.exception, "uncertain", False))
            finally:
                host.close()
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    unittest.main()
