"""Retryable workshop synchronization, with a durable three-way merge baseline."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from .dnc_proxy import DNCEndpoint, DNCProxyError, ZeuzDNCProxy
from .machines import MachineRegistry, serial_profile

LOGGER = logging.getLogger("zeuzagent")


def profile(value):
    return serial_profile(value) if value else None


def describe(value):
    if not value:
        return "Perfil eliminado"
    return (f"{value['name']} · {value['baudrate']} {value['bytesize']}{value['parity']}{value['stopbits']} · "
            f"{value['flow_control']} · {value['line_terminator']} · DTR {int(value.get('dtr', False))} · "
            f"RTS {int(value.get('rts', False))} · Goteo {int(value.get('dripfeed', False))}")


class WorkshopSync:
    def __init__(self, config, registry: MachineRegistry, proxy=None):
        self.config = config
        self.registry = registry
        self.proxy = proxy or ZeuzDNCProxy(token=config.api_token)
        self.path = registry.path.with_name("workshop-sync.json")
        try:
            self.ledger = json.loads(self.path.read_text())
        except FileNotFoundError:
            self.ledger = {}
        self.status = "Pendiente de sincronizar"
        self.conflicts: list[dict] = []
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._cycle_lock = threading.Lock()
        self._thread = None
        self._generation = 0

    def request(self, method, path, body=None, endpoint=None):
        if self._stop.is_set():
            raise DNCProxyError("Sincronización en pausa")
        status, payload = self.proxy.forward(method, path, body, endpoint)
        if self._stop.is_set():
            raise DNCProxyError("Sincronización en pausa")
        if status >= 300 or (isinstance(payload, dict) and payload.get("ok") is False):
            raise DNCProxyError(str(payload.get("error", "Actualiza ZeuzDNC para sincronizar") if isinstance(payload, dict) else payload))
        return payload

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="zeuz-workshop-sync")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=15)

    def wake(self):
        self._wake.set()

    def mark_dirty(self):
        self._generation += 1
        self.status = "Pendiente · confirmando los cambios con los equipos"
        self.wake()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.cycle()
            except Exception as exc:
                self.status = f"Pendiente · {exc}"
                LOGGER.warning("Sincronización pendiente: %s", exc)
            self._wake.wait(10)
            self._wake.clear()

    def persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.ledger, ensure_ascii=False, indent=2))
        os.replace(temporary, self.path)

    def cycle(self):
        with self._cycle_lock:
            generation = self._generation
            failures = []
            self.conflicts = []
            self.status = "Sincronizando…"
            machines = self.registry.list()
            destinations = {(m["dnc_host"], m["dnc_port"]) for m in machines}
            destinations.update((key.rsplit(":", 1)[0], int(key.rsplit(":", 1)[1])) for key in self.ledger.get("machines", {}))
            for host, port in sorted(destinations):
                if self._stop.is_set():
                    return
                endpoint = DNCEndpoint(host, port)
                try:
                    self.sync_machines(endpoint)
                except Exception as exc:
                    failures.append(f"{host}: {exc}")
            if self.config.program_server_host and not self._stop.is_set():
                try:
                    server = DNCEndpoint(self.config.program_server_host, self.config.program_server_port)
                    self.sync_programs(server)
                    url = f"http://{server.host}:{server.port}"
                    for host, port in sorted(destinations):
                        if (host, port) == (server.host, server.port):
                            continue
                        try:
                            self.request("POST", "/api/workshop/configure", {"program_server": url}, DNCEndpoint(host, port))
                        except Exception as exc:
                            failures.append(f"{host}: servidor pendiente · {exc}")
                except Exception as exc:
                    failures.append(f"Programas: {exc}")
            if self._stop.is_set():
                return
            self.persist()
            if self.conflicts:
                failures.insert(0, f"{len(self.conflicts)} perfiles con cambios simultáneos: revisa las máquinas")
            self.status = "Pendiente · " + " · ".join(failures) if failures else "Sincronizado · última confirmación " + datetime.now().strftime("%H:%M:%S") if self.config.program_server_host else "Perfiles sincronizados · servidor de programas sin seleccionar"
            if self._generation != generation:
                self.status = "Pendiente · hay cambios nuevos por confirmar"
                self.wake()

    def sync_machines(self, endpoint):
        if not self.registry.path.exists() and self.ledger.get("machines"):
            raise ValueError("Falta el archivo de perfiles; no se propagarán borrados")
        remote = self.request("GET", "/api/workshop/machines", endpoint=endpoint)
        if not isinstance(remote, list):
            raise ValueError("Respuesta de perfiles inválida")
        key = f"{endpoint.host}:{endpoint.port}"
        baseline = self.ledger.setdefault("machines", {}).setdefault(key, {})
        local = {m.get("dnc_machine_id") or m["id"]: m for m in self.registry.list() if (m["dnc_host"], m["dnc_port"]) == (endpoint.host, endpoint.port)}
        remote = {m["id"]: m for m in remote}
        # New profiles created on the touchscreen are adopted automatically.
        for machine_id, value in remote.items():
            if machine_id not in local and machine_id not in baseline:
                catalog_id = machine_id
                if self.registry.get(catalog_id):
                    catalog_id += "-" + hashlib.sha256(key.encode()).hexdigest()[:8]
                saved = self.registry.save({**profile(value), "id": catalog_id, "dnc_machine_id": machine_id, "dnc_host": endpoint.host, "dnc_port": endpoint.port})
                local[machine_id] = saved
                baseline[machine_id] = profile(value)
        for machine_id in set(local) | set(baseline):
            current = local.get(machine_id)
            other = remote.get(machine_id)
            left, right = profile(current), profile(other)
            base = baseline.get(machine_id)
            if left == right:
                baseline[machine_id] = left
                continue
            if left == base:
                # Pull only if no edit raced with the network request.
                if other:
                    if current:
                        self.registry.save({**current, **right, "id": current["id"], "revision": current.get("revision", 0)})
                    else:
                        catalog_id = machine_id
                        if self.registry.get(catalog_id):
                            catalog_id += "-" + hashlib.sha256(key.encode()).hexdigest()[:8]
                        self.registry.save({**right, "id": catalog_id, "dnc_machine_id": machine_id, "dnc_host": endpoint.host, "dnc_port": endpoint.port})
                elif current:
                    with self.registry._lock:
                        if self.registry.get(current["id"]) != current:
                            raise ValueError("El perfil cambió durante la sincronización")
                        self.registry.delete(current["id"])
                baseline[machine_id] = right
            elif right == base:
                self.request("POST", "/api/workshop/machine", {
                    "machine": left or {"id": machine_id},
                    "delete": left is None,
                    "expected_revision": other.get("revision", 0) if other else None,
                }, endpoint)
                baseline[machine_id] = left
            else:
                self.conflicts.append({"id": current["id"] if current else machine_id, "device_id": machine_id, "name": (current or other)["name"], "host": endpoint.host, "port": endpoint.port, "reason": "Agent y pantalla táctil tienen cambios", "agent_summary": describe(current), "device_summary": describe(other)})

    def resolve(self, machine_id, host, port, use_device):
        # Explicit user choice. The losing version remains in the durable journal.
        with self._cycle_lock:
            endpoint = DNCEndpoint(host, port)
            remote = self.request("GET", "/api/workshop/machines", endpoint=endpoint)
            current = self.registry.get(machine_id)
            conflict = next((c for c in self.conflicts if c["id"] == machine_id and c["host"] == host and c["port"] == port), {})
            device_id = (current or {}).get("dnc_machine_id") or conflict.get("device_id") or machine_id
            other = next((m for m in remote if m["id"] == device_id), None)
            if current and (current["dnc_host"], current["dnc_port"]) != (host, port):
                raise ValueError("Importa este perfil con un ID diferente desde el equipo")
            self.ledger.setdefault("conflict_history", []).append({"local": current, "device": other})
            self.persist()
            chosen = profile(other if use_device else current)
            if use_device:
                if other:
                    self.registry.save({**(current or {}), **chosen, "id": machine_id, "dnc_machine_id": device_id, "dnc_host": host, "dnc_port": port})
                elif current:
                    self.registry.delete(machine_id)
            else:
                self.request("POST", "/api/workshop/machine", {"machine": chosen or {"id": device_id}, "delete": chosen is None, "expected_revision": other.get("revision", 0) if other else None}, endpoint)
            self.ledger.setdefault("machines", {}).setdefault(f"{host}:{port}", {})[device_id] = chosen
            self.persist()
        self.wake()

    def sync_programs(self, endpoint):
        groups = {}
        for machine in self.registry.list():
            key = (machine["dnc_host"], machine["dnc_port"])
            groups.setdefault(key, []).append({**serial_profile(machine), "catalog_id": machine["id"]})
        routes = [{"host": host, "port": port, "local": (host, port) == (endpoint.host, endpoint.port), "machines": values} for (host, port), values in groups.items()]
        self.request("POST", "/api/workshop/configure", {"program_server": "", "mobile_token": self.config.api_token, "machine_routes": routes}, endpoint)
        manifest = self.request("GET", "/api/workshop/manifest", endpoint=endpoint)
        root = Path(self.config.programs_dir).resolve()
        if not root.is_dir():
            raise ValueError("La carpeta de programas no está disponible")
        key = f"{endpoint.host}:{endpoint.port}|{root}"
        hashes = self.ledger.setdefault("programs", {}).setdefault(key, {})
        count = 0
        for path in sorted(root.rglob("*")):
            if self._stop.is_set():
                return
            relative = path.relative_to(root)
            if any(part.startswith(".") or part in {"Thumbs.db", "desktop.ini"} for part in relative.parts):
                continue
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            if path.stat().st_size > 128 * 1024 * 1024:
                raise ValueError(f"{relative}: excede 128 MB")
            before = path.stat()
            raw = path.read_bytes()
            after = path.stat()
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise ValueError(f"{relative}: escritura en curso; se reintentará")
            digest = hashlib.sha256(raw).hexdigest()
            name = relative.as_posix()
            if hashes.get(name) == digest and name in manifest:
                continue
            self.request("POST", "/api/workshop/mirror", {"path": name, "data": base64.b64encode(raw).decode(), "sha256": digest}, endpoint)
            hashes[name] = digest
            count += 1
        if count:
            LOGGER.info("%s programas actualizados en %s", count, endpoint.host)
