import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from zeuzagent.config import AgentConfig
from zeuzagent.devices import DeviceDirectory
from zeuzagent.dnc_proxy import DNCEndpoint, DNCProxyError, ZeuzDNCProxy
from zeuzagent.machines import MachineRegistry
from zeuzagent.workshop import WorkshopSync


class PeerProgramServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = AgentConfig("Workshop", str(self.root / "programs"),
                                  program_server_host="programs.local", program_server_port=5000)
        self.registry = MachineRegistry(self.root / "machines.json")
        self.registry.save({"id": "fadal", "name": "Fadal", "dnc_host": "orange.local"})
        self.server = DNCEndpoint("programs.local", 5000)
        self.directory = DeviceDirectory(self.root / "devices.json")
        self.directory.save([{"host": self.server.host, "port": self.server.port,
                              "hostname": "programs", "device_id": "server-identity",
                              "address": "192.0.2.76"}])
        self.proxy = ZeuzDNCProxy()
        self.sync = WorkshopSync(self.config, self.registry, self.proxy)
        self.info = {"service": "zeuz-dnc", "hostname": "programs", "device_id": "server-identity"}
        self.addCleanup(ZeuzDNCProxy.forget_address, self.server.host)

    def test_cycle_publishes_verified_ip_without_changing_canonical_assignment(self):
        original_registry = self.registry.path.read_bytes()
        original_inventory = self.directory.path.read_bytes()
        with patch("zeuzagent.devices._addresses", return_value=["192.0.2.77"]), \
                patch("zeuzagent.devices._info", return_value=self.info) as info, \
                patch.object(self.sync, "sync_machines"), \
                patch.object(self.sync, "sync_programs") as programs, \
                patch.object(self.proxy, "forward", return_value=(200, {"ok": True})) as forward:
            self.sync.cycle()
        info.assert_called_once_with("192.0.2.77", 5000)
        programs.assert_called_once_with(self.server)
        forward.assert_called_once_with("POST", "/api/workshop/configure",
                                        {"program_server": "http://192.0.2.77:5000"},
                                        DNCEndpoint("orange.local", 5000))
        self.assertEqual(self.config.program_server_host, "programs.local")
        self.assertEqual(self.registry.path.read_bytes(), original_registry)
        self.assertEqual(self.directory.path.read_bytes(), original_inventory)

    def test_dhcp_change_is_rechecked_instead_of_reusing_old_address(self):
        with patch("zeuzagent.devices._addresses", side_effect=[["192.0.2.77"], ["192.0.2.88"]]), \
                patch("zeuzagent.devices._info", return_value=self.info):
            first = self.sync.peer_program_server_url(self.server)
            second = self.sync.peer_program_server_url(self.server)
        self.assertEqual(first, "http://192.0.2.77:5000")
        self.assertEqual(second, "http://192.0.2.88:5000")

    def test_server_referenced_by_verified_ip_is_not_configured_as_its_own_peer(self):
        self.registry.save({"id": "server-cnc", "name": "Server CNC", "dnc_host": "192.0.2.77"})
        with patch("zeuzagent.devices._addresses", return_value=["192.0.2.77"]), \
                patch("zeuzagent.devices._info", return_value=self.info), \
                patch.object(self.sync, "sync_machines"), \
                patch.object(self.sync, "sync_programs"), \
                patch.object(self.proxy, "forward", return_value=(200, {"ok": True})) as forward:
            self.sync.cycle()
        forward.assert_called_once_with("POST", "/api/workshop/configure",
                                        {"program_server": "http://192.0.2.77:5000"},
                                        DNCEndpoint("orange.local", 5000))

    def test_reassigned_address_does_not_replace_server_identity(self):
        wrong = {**self.info, "device_id": "different-device"}
        with patch("zeuzagent.devices._addresses", return_value=["192.0.2.77"]), \
                patch("zeuzagent.devices._info", return_value=wrong):
            with self.assertRaises(DNCProxyError):
                self.sync.peer_program_server_url(self.server)

    def test_saved_address_requires_matching_identity_when_dns_is_unavailable(self):
        with patch("zeuzagent.devices._addresses", side_effect=OSError("DNS unavailable")), \
                patch("zeuzagent.devices._info", return_value=self.info):
            self.assertEqual(self.sync.peer_program_server_url(self.server), "http://192.0.2.76:5000")
        self.directory.save([{"host": self.server.host, "port": self.server.port,
                              "hostname": "programs", "address": "192.0.2.76"}])
        with patch("zeuzagent.devices._addresses", side_effect=OSError("DNS unavailable")), \
                patch("zeuzagent.devices._info", return_value=self.info):
            with self.assertRaises(DNCProxyError):
                self.sync.peer_program_server_url(self.server)

    def test_first_discovery_requires_matching_hostname(self):
        self.directory.path.unlink()
        with patch("zeuzagent.devices._addresses", return_value=["192.0.2.77"]), \
                patch("zeuzagent.devices._info", return_value={**self.info, "hostname": "other"}):
            with self.assertRaises(DNCProxyError):
                self.sync.peer_program_server_url(self.server)
        with patch("zeuzagent.devices._addresses", return_value=["192.0.2.77"]), \
                patch("zeuzagent.devices._info", return_value=self.info):
            self.assertEqual(self.sync.peer_program_server_url(self.server), "http://192.0.2.77:5000")

    def test_unavailable_or_invalid_inventory_keeps_existing_peer_configuration(self):
        with patch("zeuzagent.devices._addresses", side_effect=OSError("DNS unavailable")), \
                patch("zeuzagent.devices._info", side_effect=OSError("offline")), \
                patch.object(self.sync, "sync_machines"), \
                patch.object(self.sync, "sync_programs"), \
                patch.object(self.proxy, "forward") as forward:
            self.sync.cycle()
        forward.assert_not_called()
        self.assertIn("Pendiente", self.sync.status)
        self.directory.path.write_text("invalid json")
        with patch("zeuzagent.workshop.probe_device") as probe:
            with self.assertRaises(DNCProxyError):
                self.sync.peer_program_server_url(self.server)
        probe.assert_not_called()

    def test_custom_transport_keeps_hostname_without_extra_network(self):
        sync = WorkshopSync(self.config, self.registry, proxy=Mock())
        with patch("zeuzagent.workshop.probe_device") as probe:
            self.assertEqual(sync.peer_program_server_url(self.server), "http://programs.local:5000")
        probe.assert_not_called()


class ComputerServerTests(unittest.TestCase):
    """With the computer as the workshop server, no Pi keeps a server role."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = AgentConfig("Workshop", str(self.root / "programs"))
        self.registry = MachineRegistry(self.root / "machines.json")
        self.registry.save({"id": "hardinge", "name": "Hardinge", "dnc_host": "raspberry.local"})
        self.registry.save({"id": "fadal", "name": "Fadal", "dnc_host": "orange.local"})
        self.proxy = ZeuzDNCProxy()
        self.sync = WorkshopSync(self.config, self.registry, self.proxy)
        self.offline = set()

    def forward(self, method, path, body=None, endpoint=None, **kwargs):
        if endpoint.host in self.offline:
            raise DNCProxyError("No se pudo contactar ZeuzDNC: timed out")
        if path == "/api/workshop/info":
            old_routes = [{"host": "orange.local", "port": 5000, "machines": [{"id": "fadal", "baudrate": 38400}]}]
            return 200, {"ok": True, "program_server": "",
                         "machine_routes": old_routes if endpoint.host == "raspberry.local" else []}
        return 200, {"ok": True}

    def test_old_pi_server_routes_are_cleared_once(self):
        with patch.object(self.sync, "sync_machines"), \
                patch.object(self.proxy, "forward", side_effect=self.forward) as calls:
            self.sync.cycle()
            self.sync.cycle()
        configured = [c for c in calls.call_args_list if c.args[1] == "/api/workshop/configure"]
        self.assertEqual(len(configured), 1)
        self.assertEqual(configured[0].args[3].host, "raspberry.local")
        self.assertEqual(configured[0].args[2], {"program_server": "", "machine_routes": []})
        checks = [c for c in calls.call_args_list if c.args[1] == "/api/workshop/info"]
        self.assertEqual(len(checks), 2, "Each Pi is checked once per run, not every cycle")

    def test_offline_pi_is_released_when_it_returns(self):
        self.offline.add("raspberry.local")
        with patch.object(self.sync, "sync_machines"), \
                patch.object(self.proxy, "forward", side_effect=self.forward) as calls:
            self.sync.cycle()
            self.offline.clear()
            self.sync.cycle()
        configured = [c.args[3].host for c in calls.call_args_list if c.args[1] == "/api/workshop/configure"]
        self.assertEqual(configured, ["raspberry.local"])

    def test_configured_pi_server_is_left_alone(self):
        config = AgentConfig("Workshop", str(self.root / "programs"),
                             program_server_host="raspberry.local", program_server_port=5000)
        sync = WorkshopSync(config, self.registry, self.proxy)
        with patch.object(sync, "release_pi_servers") as release, \
                patch.object(sync, "sync_machines"), patch.object(sync, "sync_programs"), \
                patch.object(sync, "peer_program_server_url", return_value="http://raspberry.local:5000"), \
                patch.object(self.proxy, "forward", return_value=(200, {"ok": True})):
            sync.cycle()
        release.assert_not_called()


if __name__ == "__main__":
    unittest.main()
