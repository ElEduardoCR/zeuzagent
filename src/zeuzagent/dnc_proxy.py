from __future__ import annotations

import json
import threading
import time
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
    name: str = "Equipo Zeuz"
    address: str = ""
    service_name: str = ""


class _Listener:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.found = threading.Event()
        self.lock = threading.Lock()

    def add_service(self, zeroconf, service_type: str, name: str) -> None:
        with self.lock:
            if name not in self.names:
                self.names.append(name)
        self.found.set()

    def update_service(self, zeroconf, service_type: str, name: str) -> None:
        self.add_service(zeroconf, service_type, name)

    def remove_service(self, zeroconf, service_type: str, name: str) -> None:
        with self.lock:
            if name in self.names:
                self.names.remove(name)


class ZeuzDNCProxy:
    """Localiza ZeuzDNC por Bonjour y retransmite su API para el iPhone."""

    _addresses: dict[str, tuple[str, float]] = {}
    _addresses_lock = threading.Lock()

    def __init__(self, endpoint: DNCEndpoint | None = None, *, token: str = "") -> None:
        self.token = token
        self._endpoint = endpoint
        self._lock = threading.Lock()

    @classmethod
    def remember_address(cls, host, address):
        with cls._addresses_lock:
            cls._addresses[host] = (address, time.monotonic())

    @classmethod
    def forget_address(cls, host):
        with cls._addresses_lock:
            cls._addresses.pop(host, None)

    def forward(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        endpoint: DNCEndpoint | None = None,
    ) -> tuple[int, Any]:
        for attempt in range(2):
            target = endpoint or self._resolve()
            with self._addresses_lock:
                cached = self._addresses.get(target.host)
            address = cached[0] if cached and time.monotonic() - cached[1] < 90 else target.host
            url = f"http://{address}:{target.port}{path}"
            data = None if body is None else json.dumps(body).encode("utf-8")
            request = urllib.request.Request(
                url,
                data=data,
                method=method,
                headers={
                    "Accept": "application/json",
                    **({"Authorization": "Bearer " + self.token} if self.token else {}),
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
                if attempt == 0 and method == "GET":
                    if endpoint is None:
                        with self._lock:
                            self._endpoint = None
                        continue
                    if target.host.endswith(".local"):
                        # Refresh only the same named device; never route a CNC
                        # command to the first unrelated Bonjour answer.
                        candidates = self.discover_all()
                        if any(item.host == target.host and item.port == target.port for item in candidates):
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
        endpoints = ZeuzDNCProxy.discover_all()
        if endpoints:
            return endpoints[0]
        raise DNCProxyError("No se encontró ZeuzDNC en la red local")

    @staticmethod
    def discover_all(timeout: float = 2.5, *, known=()) -> list[DNCEndpoint]:
        try:
            from zeroconf import IPVersion, ServiceBrowser, Zeroconf
        except ImportError as exc:
            raise DNCProxyError("ZeuzAgent no tiene disponible el descubrimiento Bonjour") from exc

        zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        listener = _Listener()
        browser = ServiceBrowser(zeroconf, SERVICE_TYPE, listener)
        try:
            # Keep the entire observation window: the first answer is not the complete network.
            time.sleep(max(0, timeout))
            endpoints: list[DNCEndpoint] = []
            with listener.lock:
                names = list(listener.names)
            # Resolve saved SRV/TXT names actively even if a browse PTR answer
            # was lost. A returning client must not need a new startup announcement.
            for endpoint in known:
                if endpoint.service_name.endswith(SERVICE_TYPE) and endpoint.service_name not in names:
                    names.append(endpoint.service_name)
            for name in names:
                info = zeroconf.get_service_info(SERVICE_TYPE, name, timeout=2000)
                if not info:
                    continue
                addresses = info.parsed_scoped_addresses(IPVersion.V4Only)
                if addresses and info.port:
                    stable_host = (info.server or "").rstrip(".") or addresses[0]
                    display_name = name.split("._zeuz-dnc", 1)[0].replace("Zeuz DNC en ", "")
                    ZeuzDNCProxy.remember_address(stable_host, addresses[0])
                    endpoints.append(DNCEndpoint(stable_host, int(info.port), display_name, addresses[0], name))
            return sorted(endpoints, key=lambda item: item.name.casefold())
        finally:
            browser.cancel()
            zeroconf.close()
