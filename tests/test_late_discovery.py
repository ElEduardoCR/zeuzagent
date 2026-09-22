import json
import socket
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from zeuzagent.devices import DeviceDirectory, probe_device, scan_devices
from zeuzagent.dnc_proxy import DNCEndpoint, SERVICE_TYPE, ZeuzDNCProxy


class ReturningClientTests(unittest.TestCase):
    def setUp(self):
        ZeuzDNCProxy._addresses.clear()
        self.device = {"host": "zeuz.local", "port": 5000, "name": "fadal",
                       "address": "192.0.2.10", "hostname": "zeuz", "device_id": "orange-id",
                       "service_name": "Zeuz DNC en zeuz." + SERVICE_TYPE}
        self.info = {"service": "zeuz-dnc", "hostname": "zeuz", "device_id": "orange-id", "version": "test"}

    def test_new_agent_process_recovers_known_pi_without_ptr_or_dns_response(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "devices.json"
            DeviceDirectory(path).save([{**self.device, "online": True}])
            fresh = DeviceDirectory(path).load()
            self.assertFalse(fresh[0]["online"])
            with patch("zeuzagent.devices._addresses", side_effect=OSError("No DNS")), patch("zeuzagent.devices._info", return_value=self.info):
                found, error = scan_devices(fresh, discover=lambda **kwargs: [])
            self.assertFalse(error)
            self.assertTrue(found[0]["online"])
            self.assertEqual(found[0]["host"], "zeuz.local")
            self.assertIn("identidad verificada", found[0]["status"])
            self.assertEqual(ZeuzDNCProxy._addresses["zeuz.local"][0], "192.0.2.10")

    def test_saved_ip_reassigned_to_another_device_is_not_used(self):
        ZeuzDNCProxy.remember_address("zeuz.local", "192.0.2.10")
        with patch("zeuzagent.devices._addresses", side_effect=OSError("No DNS")), patch("zeuzagent.devices._info", return_value={**self.info, "device_id": "other-pi"}):
            result = probe_device(self.device)
        self.assertFalse(result["online"])
        self.assertIn("otro equipo", result["diagnostic"])
        self.assertNotIn("zeuz.local", ZeuzDNCProxy._addresses)

    def test_legacy_ip_only_response_is_visible_but_not_authorized_for_routing(self):
        legacy = {k: v for k, v in self.device.items() if k != "device_id"}
        with patch("zeuzagent.devices._addresses", side_effect=OSError("No DNS")), patch("zeuzagent.devices._info", return_value={"service": "zeuz-dnc", "hostname": "zeuz", "version": "0.6.0"}):
            result = probe_device(legacy)
        self.assertTrue(result["reachable"])
        self.assertFalse(result["online"])
        self.assertIn("falta confirmar", result["status"])
        self.assertNotIn("zeuz.local", ZeuzDNCProxy._addresses)

    def test_changed_ip_and_delayed_interface_recover_without_restarting_publisher(self):
        known = [{"host": "zeuz.local", "port": 5000, "name": "fadal", "device_id": "orange-id"}]
        with patch("zeuzagent.devices._addresses", side_effect=OSError("Interface unavailable")):
            missing, _ = scan_devices(known, discover=lambda **kwargs: [])
        self.assertFalse(missing[0]["online"])
        with patch("zeuzagent.devices._addresses", return_value=["192.0.2.55"]), patch("zeuzagent.devices._info", return_value=self.info):
            recovered, _ = scan_devices(missing, discover=lambda **kwargs: [])
        self.assertTrue(recovered[0]["online"])
        self.assertEqual(recovered[0]["address"], "192.0.2.55")

    def test_active_srv_resolution_uses_saved_name_when_browse_has_no_ptr(self):
        import types
        import sys
        calls = []
        class Info:
            port = 5000
            server = 'zeuz.local.'
            def parsed_scoped_addresses(self, version): return ['192.0.2.10']
        class Zeroconf:
            def __init__(self, **kwargs): pass
            def get_service_info(self, kind, name, **kwargs):
                calls.append(name)
                return Info()
            def close(self): pass
        class Browser:
            def __init__(self, *args): pass
            def cancel(self): pass
        fake = types.SimpleNamespace(IPVersion=types.SimpleNamespace(V4Only=1), Zeroconf=Zeroconf, ServiceBrowser=Browser)
        endpoint = DNCEndpoint("zeuz.local", 5000, service_name=self.device["service_name"])
        with patch.dict(sys.modules, {"zeroconf": fake}):
            values = ZeuzDNCProxy.discover_all(0, known=[endpoint])
        self.assertEqual(calls, [self.device["service_name"]])
        self.assertEqual(values[0].host, "zeuz.local")


class RealMDNSLateJoinTests(unittest.TestCase):
    def test_two_running_publishers_answer_fresh_client_after_old_ttl_expires(self):
        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf
        except ImportError:
            self.skipTest("zeroconf not installed")
        tag = uuid.uuid4().hex[:10]
        # Loopback only: these test advertisements never reach the workshop LAN.
        publisher = Zeroconf(interfaces=["127.0.0.1"], ip_version=IPVersion.V4Only)
        services = [ServiceInfo(SERVICE_TYPE, f"test-{tag}-{n}.{SERVICE_TYPE}",
                    server=f"test-{tag}-{n}.local.", addresses=[socket.inet_aton("127.0.0.1")],
                    port=5000+n, properties={"api": "1"}, host_ttl=1, other_ttl=1) for n in range(2)]
        clients = []
        def fresh_client(**kwargs):
            value = Zeroconf(interfaces=["127.0.0.1"], **kwargs)
            clients.append(value)
            return value
        try:
            for service in services:
                publisher.register_service(service)
            with patch("zeroconf.Zeroconf", side_effect=fresh_client):
                first = ZeuzDNCProxy.discover_all(1.5)
                self.assertEqual(len([e for e in first if tag in e.host]), 2)
                # The browser and its sockets were closed; the Pi-side object
                # remains running. Short TTLs model an overnight cache expiry.
                time.sleep(2)
                second = ZeuzDNCProxy.discover_all(1.5)
                self.assertEqual(len([e for e in second if tag in e.host]), 2)
            self.assertEqual(len(clients), 2)
            self.assertIsNot(clients[0], clients[1])
        finally:
            for service in services:
                publisher.unregister_service(service)
            publisher.close()
