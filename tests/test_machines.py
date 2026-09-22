import tempfile
import unittest
from pathlib import Path

from zeuzagent.machines import MachineError, MachineRegistry, serial_profile


class MachineRegistryTests(unittest.TestCase):
    def test_crud_and_profile_routing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = MachineRegistry(Path(directory) / "machines.json")
            saved = registry.save({
                "name": "Torno Mori 1",
                "dnc_host": "http://zeuz-dnc-123.local:5000",
                "baudrate": 9600,
                "bytesize": 8,
                "parity": "N",
                "stopbits": 1,
                "flow_control": "xonxoff",
                "line_terminator": "CRLF",
            })
            self.assertEqual(saved["id"], "torno-mori-1")
            self.assertEqual(saved["dnc_host"], "zeuz-dnc-123.local")
            self.assertEqual(saved["dnc_port"], 5000)
            self.assertNotIn("dnc_host", serial_profile(saved))
            self.assertEqual(registry.get(saved["id"])["name"], "Torno Mori 1")
            registry.delete(saved["id"])
            self.assertEqual(registry.list(), [])

    def test_machine_requires_an_orange_pi(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = MachineRegistry(Path(directory) / "machines.json")
            with self.assertRaises(MachineError):
                registry.save({"name": "Sin destino"})


if __name__ == "__main__":
    unittest.main()
