import base64
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
try:
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QSignalSpy
    from zeuzagent.desktop import DesktopBackend
except ImportError:
    QApplication = None

from zeuzagent.config import AgentConfig
from zeuzagent.library import MAX_PREVIEW_BYTES


def free_port():
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


@unittest.skipIf(QApplication is None, "PySide6 no está instalado")
class DesktopProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.programs = self.root / "programs"
        self.programs.mkdir()
        self.config_path = self.root / "config.json"
        AgentConfig("Prueba Qt", str(self.programs), host="127.0.0.1", port=free_port(),
                    api_token="qt-test-token", pairing_code="012345", discovery=False).save(self.config_path)
        self.sync_patch = patch("zeuzagent.runtime.WorkshopSync.start")
        self.sync_patch.start()
        self.backend = DesktopBackend(self.config_path, tray_available=False)
        self.backend._discovery_timer.stop()
        self.backend._update_timer.stop()
        self.backend._transfer_timer.stop()
        self.wait_until(lambda: not self.backend.programBusy)
        self.fake = None

    def tearDown(self):
        self.backend.dispose()
        self.backend._program_executor.shutdown(wait=True, cancel_futures=True)
        if self.fake:
            self.fake.shutdown()
            self.fake.server_close()
        self.app.processEvents()
        self.sync_patch.stop()
        self.temp.cleanup()

    def wait_until(self, condition, timeout=8):
        # Drain the real Qt signal queue; no test changes GUI state from a worker.
        deadline = time.monotonic() + timeout
        self.app.processEvents()
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(condition(), "La operación Qt no terminó")

    def fake_zeuz(self):
        self.calls = []
        self.staged = {}
        self.send_mode = "normal"
        self.status_mode = "normal"
        self.remote_transfer = {"status": "idle", "percent": 0, "bytes_sent": 0, "total_bytes": 0, "message": ""}
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def result(self, value, status=200):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/api/info":
                    self.result({"service": "zeuz-dnc", "agent_configured": False})
                elif self.path == "/api/workshop/info":
                    self.result({"program_server": ""})
                elif self.path == "/api/workshop/machines":
                    self.result([fixture.machine])
                elif self.path == "/api/transfer/status":
                    self.result({"error": "Estado no disponible"}, 503) if fixture.status_mode == "fail" else self.result(fixture.remote_transfer)
                else:
                    self.result({"error": "Ruta simulada no disponible"}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                fixture.calls.append((self.path, body))
                if self.path == "/api/workshop/mirror":
                    fixture.staged[body["path"]] = base64.b64decode(body["data"])
                    self.result({"ok": True, "sha256": body["sha256"]})
                elif self.path == "/api/send":
                    fixture.remote_transfer = {"status": "sending", "filename": Path(body["path"]).name,
                                               "machine": fixture.machine["name"], "percent": 42,
                                               "bytes_sent": 42, "total_bytes": 100, "message": "Enviando"}
                    if fixture.send_mode == "drop":
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.connection.close()
                    else:
                        self.result({"ok": True})
                elif self.path == "/api/send/cancel":
                    fixture.remote_transfer = {**fixture.remote_transfer, "status": "cancelled", "message": "Envío cancelado"}
                    self.result({"ok": True})
                else:
                    self.result({"ok": True})

        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.fake.serve_forever, daemon=True).start()
        self.machine = self.backend._machines.save({"id": "fadal", "name": "Fadal de prueba", "dnc_host": "127.0.0.1", "dnc_port": self.fake.server_port})
        self.backend._machines.save({"id": "other", "name": "Otra CNC", "dnc_host": "other.invalid", "dnc_port": 5000})
        self.backend.start()
        self.backend.setSendMachine("fadal")

    def test_browse_search_preview_and_import_full_program(self):
        (self.programs / "Folder").mkdir()
        (self.programs / "Folder" / "O7.nc").write_bytes(b"O7\n(COMENTARIO \xf1)\nM30\n")
        self.backend.browsePrograms("", "O7")
        self.wait_until(lambda: not self.backend.programBusy)
        self.assertEqual(self.backend.programEntries[0]["path"], "Folder/O7.nc")
        self.backend.previewProgram("Folder/O7.nc")
        self.wait_until(lambda: not self.backend.programBusy)
        self.assertIn("ñ", self.backend.selectedProgram["content"])
        outside = self.root / "O8.nc"
        raw = b"%\r\nO8\r\n" + b"G1 X1.\r\n" * (MAX_PREVIEW_BYTES // 8 + 10)
        outside.write_bytes(raw)
        self.backend.browsePrograms("Folder", "")
        self.wait_until(lambda: not self.backend.programBusy)
        self.backend.importProgramPaths([str(outside)])
        self.wait_until(lambda: not self.backend.programBusy)
        self.assertEqual((self.programs / "Folder" / "O8.nc").read_bytes(), raw)
        self.backend.previewProgram("Folder/O8.nc")
        self.wait_until(lambda: not self.backend.programBusy)
        self.assertTrue(self.backend.selectedProgram["truncated"])

    def test_local_programs_remain_available_with_offline_shared_server(self):
        (self.programs / "O9.nc").write_bytes(b"O9\nM30\n")
        config = replace(self.backend._config, program_server_host="unavailable.invalid")
        original_server = config.program_server_host
        with patch("zeuzagent.remote_library.RemoteProgramLibrary.request", side_effect=AssertionError("Local browser contacted the shared server")):
            self.assertTrue(self.backend._save_config(config))
            self.wait_until(lambda: not self.backend.programBusy)
            self.assertEqual(self.backend.programScope, "local")
            self.assertEqual(self.backend.programEntries[0]["path"], "O9.nc")
            self.backend.previewProgram("O9.nc")
            self.wait_until(lambda: not self.backend.programBusy)
            self.assertEqual(self.backend.selectedProgram["content"], "O9\nM30\n")
            outside = self.root / "O10.nc"
            outside.write_bytes(b"O10\nM30\n")
            self.backend.importProgramPaths([str(outside)])
            self.wait_until(lambda: not self.backend.programBusy)
            self.assertEqual((self.programs / "O10.nc").read_bytes(), outside.read_bytes())
        self.assertEqual(AgentConfig.load(self.config_path).program_server_host, original_server)

    def test_late_server_response_cannot_replace_new_local_browser(self):
        (self.programs / "LOCAL.nc").write_bytes(b"O1\nM30\n")
        self.backend._save_config(replace(self.backend._config, program_server_host="unavailable.invalid"))
        self.wait_until(lambda: not self.backend.programBusy)
        service = self.backend._program_service()
        original_dispatch = service.dispatch
        entered, release = threading.Event(), threading.Event()
        results = QSignalSpy(self.backend._programResult)
        def dispatch(method, params):
            if method == "programs.list" and params.get("source") == "server":
                entered.set()
                release.wait(5)
                return {"entries": [{"name": "REMOTE.nc", "path": "REMOTE.nc", "isDirectory": False, "size": 1, "modified": 0}]}
            return original_dispatch(method, params)
        with patch.object(service, "dispatch", side_effect=dispatch):
            try:
                self.backend.setProgramScope("server")
                self.wait_until(entered.is_set)
                self.backend.setProgramScope("local")
                self.wait_until(lambda: not self.backend.programBusy)
                release.set()
                self.wait_until(lambda: results.count() >= 2)
                self.assertEqual(self.backend.programScope, "local")
                self.assertEqual([item["name"] for item in self.backend.programEntries], ["LOCAL.nc"])
                self.assertEqual(self.backend.programError, "")
            finally:
                release.set()

    def test_full_program_send_pins_machine_then_cancels_same_target(self):
        self.fake_zeuz()
        raw = b"O1\n" + b"G1 X1.\n" * (MAX_PREVIEW_BYTES // 7 + 10)
        (self.programs / "O1.nc").write_bytes(raw)
        self.backend.previewProgram("O1.nc")
        self.wait_until(lambda: not self.backend.programBusy)
        self.assertTrue(self.backend.selectedProgram["truncated"])
        self.backend.sendProgram("O1.nc", "fadal")
        self.wait_until(lambda: not self.backend._transfer_pending and not self.backend.transferPolling)
        self.assertTrue(self.backend.transferBusy)
        self.assertEqual(next(iter(self.staged.values())), raw)
        self.backend.setSendMachine("other")
        self.backend.sendProgram("O1.nc", "fadal")
        self.assertEqual(self.backend.sendMachineId, "fadal")
        self.assertEqual(len([call for call in self.calls if call[0] == "/api/send"]), 1)
        self.assertFalse(self.backend.saveMachine({**self.machine, "name": "Changed while sending"}))
        self.backend.cancelTransfer()
        self.wait_until(lambda: not self.backend.transferPolling and not self.backend.transferBusy)
        self.assertEqual(self.backend.transfer["status"], "cancelled")
        self.assertEqual(len([call for call in self.calls if call[0] == "/api/send/cancel"]), 1)
        self.backend.setSendMachine("other")
        self.assertEqual(self.backend.sendMachineId, "other")

    def test_confirmed_local_source_survives_browser_switch_without_changing_shared_server(self):
        self.backend._save_config(replace(self.backend._config, program_server_host="unavailable.invalid"))
        self.wait_until(lambda: not self.backend.programBusy)
        self.fake_zeuz()
        raw = b"O1\nG21 G90\nM30\n"
        (self.programs / "O1.nc").write_bytes(raw)
        self.backend.previewProgram("O1.nc")
        self.wait_until(lambda: not self.backend.programBusy)
        confirmed_source = self.backend.programScope
        service = self.backend._program_service()
        dispatch = service.dispatch
        def read_empty_server(method, params):
            if method == "programs.list" and params.get("source") == "server":
                return {"entries": []}
            return dispatch(method, params)
        with patch.object(service, "dispatch", side_effect=read_empty_server):
            self.backend.setProgramScope("server")
            self.wait_until(lambda: not self.backend.programBusy)
            self.backend.sendProgram("O1.nc", "fadal", confirmed_source)
            self.wait_until(lambda: not self.backend._transfer_pending and not self.backend.transferPolling)
        self.assertEqual(next(iter(self.staged.values())), raw)
        self.assertFalse(self.backend.canChangeProgramScope)
        self.backend.setProgramScope("local")
        self.assertEqual(self.backend.programScope, "server")
        self.assertEqual(AgentConfig.load(self.config_path).program_server_host, "unavailable.invalid")

    def test_uncertain_send_and_failed_status_never_repeat_command(self):
        self.fake_zeuz()
        self.send_mode = "drop"
        self.status_mode = "fail"
        (self.programs / "O1.nc").write_bytes(b"O1\nM30\n")
        self.backend.previewProgram("O1.nc")
        self.wait_until(lambda: not self.backend.programBusy)
        self.backend.sendProgram("O1.nc", "fadal")
        self.wait_until(lambda: not self.backend._transfer_pending and not self.backend.transferPolling)
        self.assertTrue(self.backend.transferUncertain)
        self.backend.sendProgram("O1.nc", "fadal")
        self.backend.setSendMachine("other")
        self.assertEqual(self.backend.sendMachineId, "fadal")
        self.assertEqual(len([call for call in self.calls if call[0] == "/api/send"]), 1)
        self.status_mode = "normal"
        sending = dict(self.remote_transfer)
        self.remote_transfer = {**sending, "status": "idle", "filename": None}
        self.backend.refreshTransfer()
        self.wait_until(lambda: not self.backend.transferPolling)
        self.assertTrue(self.backend.transferUncertain)
        self.assertFalse(self.backend.canSendProgram)
        self.remote_transfer = {**sending, "status": "success", "filename": "previous.nc", "percent": 100}
        self.backend.refreshTransfer()
        self.wait_until(lambda: not self.backend.transferPolling)
        self.assertTrue(self.backend.transferUncertain)
        self.remote_transfer = sending
        self.backend.refreshTransfer()
        self.wait_until(lambda: not self.backend.transferPolling)
        self.assertTrue(self.backend.transferBusy)
        self.remote_transfer = {**self.remote_transfer, "status": "success", "percent": 100, "message": "Completado"}
        self.backend.refreshTransfer()
        self.wait_until(lambda: not self.backend.transferPolling)
        self.assertFalse(self.backend.transferUncertain)
        self.assertTrue(self.backend.canSendProgram)

    def test_safe_rejection_remains_correctable(self):
        self.fake_zeuz()
        self.backend.sendProgram("missing.nc", "fadal")
        self.wait_until(lambda: not self.backend._transfer_pending)
        self.assertFalse(self.backend.transferUncertain)
        self.assertFalse(self.backend.transferBusy)
        self.assertEqual(len([call for call in self.calls if call[0] == "/api/send"]), 0)
        self.assertIn("encontrado", self.backend.programError)

    def test_qml_programs_and_workshop_load_at_minimum_width(self):
        import zeuzagent.desktop as desktop
        engine = QQmlApplicationEngine()
        errors = []
        engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
        engine.rootContext().setContextProperty("backend", self.backend)
        engine.load(QUrl.fromLocalFile(str(Path(desktop.__file__).parent / "qml" / "Main.qml")))
        self.assertTrue(engine.rootObjects(), errors)
        window = engine.rootObjects()[0]
        window.setWidth(820)
        window.setHeight(600)
        self.wait_until(lambda: not self.backend.programBusy)
        self.app.processEvents()
        self.assertFalse(errors, errors)
        window.close()
        del engine


if __name__ == "__main__":
    unittest.main()
