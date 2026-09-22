import sys
import types
import unittest
import urllib.error
from unittest.mock import patch

from zeuzagent.dnc_proxy import DNCEndpoint, DNCProxyError, ZeuzDNCProxy


class DiscoveryTests(unittest.TestCase):
    def test_collects_devices_arriving_after_first_answer(self):
        listener = None
        class Info:
            port = 5000
            def __init__(self, name): self.server = name + '.local.'
            def parsed_scoped_addresses(self, version): return ['192.0.2.1']
        class Zeroconf:
            def __init__(self, **kwargs): pass
            def get_service_info(self, service, name, **kwargs): return Info(name.split('.')[0])
            def close(self): pass
        class Browser:
            def __init__(self, zc, service, value):
                nonlocal listener
                listener = value
                value.add_service(zc, service, 'first._zeuz-dnc._tcp.local.')
            def cancel(self): pass
        fake = types.SimpleNamespace(IPVersion=types.SimpleNamespace(V4Only=1), Zeroconf=Zeroconf, ServiceBrowser=Browser)
        def elapsed(_): listener.add_service(None, '', 'second._zeuz-dnc._tcp.local.')
        with patch.dict(sys.modules, {'zeroconf': fake}), patch('zeuzagent.dnc_proxy.time.sleep', side_effect=elapsed):
            result = ZeuzDNCProxy.discover_all()
        self.assertEqual([item.name for item in result], ['first', 'second'])

    def test_failed_get_rediscovers_but_send_is_never_replayed(self):
        proxy = ZeuzDNCProxy(DNCEndpoint('old.local', 5000))
        with patch('zeuzagent.dnc_proxy.urllib.request.urlopen', side_effect=OSError('offline')) as urlopen, patch.object(proxy, '_discover', return_value=DNCEndpoint('new.local', 5000)) as discovery:
            with self.assertRaises(DNCProxyError): proxy.forward('GET', '/api/state')
            self.assertEqual(discovery.call_count, 1)
            self.assertEqual(urlopen.call_count, 2)
        with patch('zeuzagent.dnc_proxy.urllib.request.urlopen', side_effect=OSError('ambiguous')) as urlopen:
            with self.assertRaises(DNCProxyError): proxy.forward('POST', '/api/send', {'path': 'O1.nc'})
            self.assertEqual(urlopen.call_count, 1)
