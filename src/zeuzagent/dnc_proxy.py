from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


SERVICE_TYPE = "_zeuz-dnc._tcp.local."


class DNCProxyError(RuntimeError):
    pass


@dataclass(frozen=True)
class DNCEndpoint:
    host: str
    port: int


class _Listener:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.found = threading.Event()

    def add_service(self, zeroconf, service_type: str, name: str) -> None:
        if name not in self.names:
            self.names.append(name)
        self.found.set()

    def update_service(self, zeroconf, service_type: str, name: str) -> None:
        self.add_service(zeroconf, service_type, name)

    def remove_service(self, zeroconf, service_type: str, name: str) -> None:
        if name in self.names:
            self.names.remove(name)


class ZeuzDNCProxy:
    """Localiza ZeuzDNC por Bonjour y retransmite su API para el iPhone."""

    def __init__(self, endpoint: DNCEndpoint | None = None) -> None:
        self._endpoint = endpoint
        self._lock = threading.Lock()

    def forward(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        for attempt in range(2):
            endpoint = self._resolve()
            url = f"http://{endpoint.host}:{endpoint.port}{path}"
            data = None if body is None else json.dumps(body).encode("utf-8")
            request = urllib.request.Request(
                url,
                data=data,
                method=method,
                headers={
                    "Accept": "application/json",
                    **({"Content-Type": "application/json"} if data is not None else {}),
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=12) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as exc:
                try:
                    payload = json.load(exc)
                except Exception:
                    payload = {"ok": False, "error": f"ZeuzDNC respondió HTTP {exc.code}"}
                return exc.code, payload
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                if attempt == 0:
                    with self._lock:
                        self._endpoint = None
                    continue
                raise DNCProxyError(f"No se pudo contactar ZeuzDNC: {exc}") from exc
        raise DNCProxyError("No se pudo contactar ZeuzDNC")

    def _resolve(self) -> DNCEndpoint:
        with self._lock:
            if self._endpoint is not None:
                return self._endpoint
            self._endpoint = self._discover()
            return self._endpoint

    @staticmethod
    def _discover() -> DNCEndpoint:
        try:
            from zeroconf import IPVersion, ServiceBrowser, Zeroconf
        except ImportError as exc:
            raise DNCProxyError("ZeuzAgent no tiene disponible el descubrimiento Bonjour") from exc

        zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        listener = _Listener()
        browser = ServiceBrowser(zeroconf, SERVICE_TYPE, listener)
        try:
            listener.found.wait(timeout=3)
            for name in listener.names:
                info = zeroconf.get_service_info(SERVICE_TYPE, name, timeout=2000)
                if not info:
                    continue
                addresses = info.parsed_scoped_addresses(IPVersion.V4Only)
                if addresses and info.port:
                    return DNCEndpoint(addresses[0], int(info.port))
        finally:
            browser.cancel()
            zeroconf.close()
        raise DNCProxyError("No se encontró ZeuzDNC en la red local")
