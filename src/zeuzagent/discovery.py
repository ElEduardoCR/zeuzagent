from __future__ import annotations

import socket


SERVICE_TYPE = "_zeuz-agent._tcp.local."


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
            properties={
                "api": "1",
                "path": "/v1",
                "pairing": "required",
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

