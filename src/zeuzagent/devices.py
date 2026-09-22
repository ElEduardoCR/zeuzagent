"""Durable discovery inventory for a client returning to an already running Pi.

Remembered addresses are candidates, not authority: validate identity before
routing through them. Legacy devices without a stable ID remain read-only
candidates if only their old IP answers and hostname resolution is unavailable.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .dnc_proxy import DNCEndpoint, ZeuzDNCProxy


class DeviceDirectory:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()

    def load(self):
        with self.lock:
            try:
                value = json.loads(self.path.read_text())
            except FileNotFoundError:
                return []
            if not isinstance(value, dict) or not isinstance(value.get("devices", []), list):
                raise ValueError("Inventario de dispositivos inválido")
            return [{**d, "name": d.get("name") or d["host"], "online": False, "status": "Comprobando conexión"}
                    for d in value.get("devices", [])
                    if isinstance(d, dict) and isinstance(d.get("host"), str) and d["host"]
                    and isinstance(d.get("port"), int) and 1 <= d["port"] <= 65535]

    def save(self, devices):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            # Reachability and monotonic TTLs do not survive a process restart.
            keys = ("host", "port", "name", "address", "service_name", "device_id", "hostname", "version")
            tmp.write_text(json.dumps({"devices": [{k: d[k] for k in keys if d.get(k) is not None} for d in devices]}, indent=2))
            os.replace(tmp, self.path)


def _addresses(host):
    return sorted({item[4][0] for item in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)})


def _info(address, port):
    request = urllib.request.Request(f"http://{address}:{port}/api/info", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        value = json.load(response)
    if not isinstance(value, dict) or value.get("service") != "zeuz-dnc":
        raise ValueError("La dirección no corresponde a ZeuzDNC")
    return value


def probe_device(device, *, announced=False):
    result = dict(device)
    host, port = device["host"], device["port"]
    candidates = []
    if announced and device.get("address"):
        candidates.append((device["address"], True))
    try:
        candidates.extend((address, True) for address in _addresses(host))
    except OSError:
        pass
    if device.get("address"):
        candidates.append((device["address"], False))
    seen = set()
    last_error = "No respondió Bonjour ni la dirección guardada"
    for address, resolved in candidates:
        if address in seen:
            continue
        seen.add(address)
        try:
            ipaddress.IPv4Address(address)
            info = _info(address, port)
            expected_id = device.get("device_id")
            if expected_id and info.get("device_id") != expected_id:
                raise ValueError("La IP responde con la identidad de otro equipo")
            hostname = str(info.get("hostname", "")).rstrip(".").casefold()
            expected_hostname = str(device.get("hostname") or host.removesuffix(".local")).rstrip(".").casefold()
            if not expected_id and not announced and hostname != expected_hostname:
                # Numeric destinations have no DNS name to compare on first use.
                try:
                    ipaddress.IPv4Address(host)
                except ValueError:
                    raise ValueError("La IP responde con un hostname diferente")
                if device.get("hostname"):
                    raise ValueError("La IP responde con un hostname diferente")
            stable_match = bool(expected_id and info.get("device_id") == expected_id)
            result.update(capabilities=info.get("capabilities", {}), update={**device.get("update", {}), **info.get("update", {})}, update_paired=info.get("update_paired", False), address=address, hostname=info.get("hostname"), version=info.get("version"),
                          name=info.get("name") or device.get("name") or info.get("hostname") or host,
                          reachable=True, online=bool(resolved or stable_match))
            # A saved IP alone cannot establish a new stable identity.
            if resolved or stable_match:
                if info.get("device_id"):
                    result["device_id"] = info["device_id"]
                ZeuzDNCProxy.remember_address(host, address)
                result["status"] = "Conectado" if resolved else "Conectado · identidad verificada en dirección guardada"
            else:
                ZeuzDNCProxy.forget_address(host)
                result["status"] = f"Responde en {address} · falta confirmar {host} por Bonjour"
            return result
        except (OSError, ValueError) as exc:
            last_error = str(exc)
    # Do not leave a previously cached address available for CNC routing.
    ZeuzDNCProxy.forget_address(host)
    result.update(online=False, reachable=False, status="Sin conexión · reintentando", diagnostic=last_error)
    return result


def scan_devices(known, *, discover=None):
    discover = discover or ZeuzDNCProxy.discover_all
    inventory = {(d["host"], d["port"]): dict(d) for d in known}
    announced = set()
    error = ""
    try:
        hints = [DNCEndpoint(d["host"], d["port"], d.get("name", "Equipo Zeuz"), d.get("address", ""), d.get("service_name", "")) for d in inventory.values()]
        for endpoint in discover(known=hints):
            key = (endpoint.host, endpoint.port)
            previous = inventory.get(key, {})
            inventory[key] = {**previous, "name": previous.get("name") or endpoint.name,
                              "host": endpoint.host, "port": endpoint.port, "address": endpoint.address,
                              "service_name": endpoint.service_name}
            announced.add(key)
    except Exception as exc:
        error = str(exc)
    # Probes of one sleeping/unreachable device cannot hold up the other Pi.
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(probe_device, d, announced=key in announced) for key, d in inventory.items()]
        devices = [future.result() for future in futures]
    return sorted(devices, key=lambda d: d["name"].casefold()), error
