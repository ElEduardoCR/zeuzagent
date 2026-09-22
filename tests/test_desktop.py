import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    from zeuzagent.desktop import DesktopBackend, create_icon
except ImportError:
    QApplication = None
    DesktopBackend = None

from zeuzagent.config import AgentConfig


@unittest.skipIf(QApplication is None, "PySide6 no está instalado")
class DesktopBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @unittest.skipUnless(sys.platform == "darwin", "macOS icon appearance")
    def test_runtime_icon_keeps_macos_margin_and_rounded_corners(self):
        # Validate the pixels Qt actually supplies to the Dock, not just the
        # packaged ICNS: a full-bleed runtime PNG used to override that ICNS.
        icon = create_icon()
        self.assertFalse(icon.isNull())
        for side in (32, 64, 128):
            image = icon.pixmap(side, side).toImage()
            self.assertFalse(image.isNull())
            center = image.width() // 2
            inset = round(image.width() * .09)
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            # Stay clear of the antialiased edge at the 9% inset.
            self.assertEqual(image.pixelColor(center, image.width() // 25).alpha(), 0)
            self.assertGreater(image.pixelColor(center, inset + 2).alpha(), 240)
            self.assertEqual(image.pixelColor(inset, inset).alpha(), 0)

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
