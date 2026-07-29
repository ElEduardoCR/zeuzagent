import os
import socket
import tempfile
import unittest
from pathlib import Path

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

    def test_desktop_controls_runtime_and_pairing(self) -> None:
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
            finally:
                backend.stop()
            self.assertFalse(backend.running)
            backend.dispose()


if __name__ == "__main__":
    unittest.main()
