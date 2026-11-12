from __future__ import annotations

import socket


SERVICE_TYPE = "_zeuz-agent._tcp.local."


def local_ipv4_addresses() -> list[bytes]:
    """Publish reachable A records as well as SRV for Windows without Bonjour DNS."""
    addresses: set[str] = set()
    try:
        addresses.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    return [socket.inet_aton(address) for address in sorted(addresses) if not address.startswith("127.") and address != "0.0.0.0"]


class DiscoveryPublisher:
    def __init__(self, name: str, port: int) -> None:
        self.name = name
        self.port = port
        self._zeroconf = None
        self._info = None

    def start(self) -> bool:
        try:
            from zeroconf import IPVersion, ServiceInfo, Zeroconf
        except ImportError:
            return False

        hostname = socket.gethostname().strip() or "zeuz-agent"
        service_name = f"{self.name}.{SERVICE_TYPE}"
        self._info = ServiceInfo(
            SERVICE_TYPE,
            service_name,
            port=self.port,
            addresses=local_ipv4_addresses(),
            properties={
                "api": "1",
                "path": "/v1",
                "pairing": "required",
                "presetter": "1",
                "presetter_upload": "library_only",
            },
            server=f"{hostname}.local.",
        )
        self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        self._zeroconf.register_service(self._info)
        return True

    def stop(self) -> None:
        if self._zeroconf and self._info:
            self._zeroconf.unregister_service(self._info)
            self._zeroconf.close()
        self._zeroconf = None
        self._info = None

