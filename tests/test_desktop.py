import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    from zeuzagent.desktop import DesktopBackend
except ImportError:
    QApplication = None
    DesktopBackend = None

from zeuzagent.config import AgentConfig


@unittest.skipIf(QApplication is None, "PySide6 no está instalado")
class DesktopBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @patch("zeuzagent.runtime.WorkshopSync.start")
    def test_desktop_controls_runtime_and_pairing(self, _sync_start) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "agent.json"
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()
            AgentConfig(
                name="Desktop test",
                programs_dir=str(root / "programs"),
                host="127.0.0.1",
                port=port,
                api_token="token",
                pairing_code="123456",
                discovery=False,
            ).save(config_path)
            backend = DesktopBackend(config_path, tray_available=False)
            backend.start()
            try:
                self.assertTrue(backend.running)
                self.assertEqual(backend.status, "Activo")
                old_code = backend.pairingCode
                backend.regeneratePairingCode()
                self.assertNotEqual(backend.pairingCode, old_code)
                self.assertTrue(backend.running)
                self.assertTrue(backend.saveMachine({
                    "name": "Torno 1",
                    "dnc_host": "zeuz-dnc-test.local",
                    "baudrate": 9600,
                    "bytesize": 8,
                    "parity": "N",
                    "stopbits": 1,
                    "flow_control": "xonxoff",
                    "line_terminator": "CRLF",
                }))
                self.assertEqual(backend.machines[0]["name"], "Torno 1")
                with patch("zeuzagent.desktop.ZeuzDNCProxy.forward", return_value=(200, [{
                    "id": "fanuc",
                    "name": "Fanuc",
                    "baudrate": 4800,
                    "bytesize": 7,
                    "parity": "E",
                    "stopbits": 2,
                    "flow_control": "xonxoff",
                    "line_terminator": "CR",
                }])):
                    backend.importMachines("zeuz-dnc-import.local", 5000)
                self.assertEqual(len(backend.machines), 2)
                self.assertEqual(backend.machines[1]["dnc_host"], "zeuz-dnc-import.local")
            finally:
                backend.stop()
            self.assertFalse(backend.running)
            backend.dispose()

    def test_reopened_agent_restores_unassigned_devices_and_rechecks_them(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "agent.json"
            AgentConfig.create(programs_dir=root / "programs").save(config)
            device = {"name": "fadal", "host": "zeuz.local", "port": 5000,
                      "address": "192.0.2.1", "device_id": "orange-id",
                      "hostname": "zeuz", "service_name": "Zeuz DNC en zeuz._zeuz-dnc._tcp.local.",
                      "online": True, "status": "Conectado"}
            first = DesktopBackend(config, tray_available=False)
            first._apply_devices([device])
            first.dispose()
            second = DesktopBackend(config, tray_available=False)
            try:
                self.assertEqual(second.machines, [])
                self.assertEqual(second.discoveredDevices[0]["name"], "fadal")
                self.assertFalse(second.discoveredDevices[0]["online"])
                with patch("zeuzagent.desktop.scan_devices", return_value=([device], "")) as scan:
                    second.discoverDevices()
                    deadline = time.monotonic() + 2
                    while second.discovering and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.01)
                    self.assertFalse(second.discovering)
                    self.assertTrue(second.discoveredDevices[0]["online"])
                    self.assertEqual(scan.call_args.args[0][0]["device_id"], "orange-id")
            finally:
                second.dispose()


if __name__ == "__main__":
    unittest.main()
