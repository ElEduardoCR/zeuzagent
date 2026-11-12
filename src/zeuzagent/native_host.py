"""Private pipe-based companion for the SwiftUI macOS app, without Qt."""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import json
import logging
import os
import secrets
import signal
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode
from . import __version__
from .config import default_config_path, load_or_create_config
from .devices import DeviceDirectory, scan_devices
from .dnc_proxy import DNCEndpoint, ZeuzDNCProxy
from .library import LibraryError, MAX_TRANSFER_BYTES, ProgramLibrary, _looks_binary
from .machines import MachineError, MachineRegistry
from .remote_library import RemoteProgramLibrary
from .runtime import AgentRuntime
from .transfer_preparation import prepare_program_send, resolve_program_destination

LOGGER = logging.getLogger("zeuzagent")
MAX_RPC_LINE_BYTES = 1024 * 1024


class TransferUncertain(RuntimeError):
    """A start request may have reached the CNC; polling must resolve it."""
    uncertain = True


def local_addresses(port):
    values = set()
    try:
        # Interface enumeration is local and does not wait for hostname DNS.
        # ifaddr is already shipped with the Bonjour dependency.
        import ifaddr
        for adapter in ifaddr.get_adapters():
            for address in adapter.ips:
                value = address.ip
                if isinstance(value, str) and not value.startswith("127.") and value != "0.0.0.0":
                    values.add(value)
    except (ImportError, OSError):
        pass
    if not values:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect(("192.0.2.1", 9))
                value = route.getsockname()[0]
                if not value.startswith("127."):
                    values.add(value)
        except OSError:
            pass
    return [{"url": f"http://{value}:{port}"} for value in sorted(values or {"127.0.0.1"})]


class ActivityHandler(logging.Handler):
    def __init__(self, host):
        super().__init__()
        self.host = host

    def emit(self, record):
        try:
            self.host.record(record.levelname.lower(), record.getMessage())
        except Exception:
            pass


class NativeHost:
    def __init__(self, config_path=None, *, auto_start=True, discovery=True, background=True, runtime=None):
        self._lock = threading.RLock()
        self._activity_lock = threading.Lock()
        self._mutations = threading.RLock()
        self._closed = threading.Event()
        self._discovery_enabled = discovery
        self._discovering = self._update_polling = False
        self._activity = deque(maxlen=150)
        self._status, self._error = "Detenido", ""
        self._config, self._config_path, _ = load_or_create_config(config_path)
        self._owns_runtime = runtime is None
        self._instance_file = self._acquire_instance_lock() if self._owns_runtime else None
        self._machines_path = self._config_path.with_name("machines.json")
        self._machines = MachineRegistry(self._machines_path)
        self._runtime = runtime or AgentRuntime(self._config, self._machines_path)
        if runtime is not None:
            self._config = runtime.config
        self._device_directory = DeviceDirectory(self._config_path.with_name("devices.json"))
        try:
            self._devices = self._device_directory.load()
        except (OSError, ValueError):
            self._devices = []
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="zeuz-native-background")
        self._log_handler = ActivityHandler(self) if self._owns_runtime else None
        if self._log_handler:
            LOGGER.addHandler(self._log_handler)
            LOGGER.setLevel(logging.INFO)
        self._scheduler = None
        if auto_start and self._owns_runtime:
            self.start()
        if background and self._owns_runtime:
            self._scheduler = threading.Thread(target=self._schedule, name="zeuz-native-discovery", daemon=True)
            self._scheduler.start()

    def _acquire_instance_lock(self):
        handle = self._config_path.with_name("native-host.lock").open("a+")
        if os.name == "posix":
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                raise RuntimeError("Ya hay otra ventana nativa de Zeuz Agent usando esta configuración") from exc
        return handle

    def record(self, level, message):
        for secret in (self._config.api_token, self._config.pairing_code):
            if secret:
                message = message.replace(secret, "[oculto]")
        with self._activity_lock:
            self._activity.appendleft({"time": datetime.now().strftime("%H:%M:%S"),
                                       "level": level, "message": message})

    def _schedule(self):
        next_discovery = next_updates = 0.0
        while not self._closed.wait(1):
            now = time.monotonic()
            if now >= next_discovery:
                if self._discovery_enabled:
                    self.discover()
                next_discovery = now + 30
            if now >= next_updates:
                self._refresh_updates()
                next_updates = now + 4

    def state(self):
        # Never hold the host lock while entering runtime/registry locks or doing
        # address lookup. Runtime and HTTP threads can log while holding their
        # own locks; activity uses its own independent, leaf-only mutex.
        with self._lock:
            config, runtime = self._config, self._runtime
            status, error = self._status, self._error
            devices, discovering = copy.deepcopy(self._devices), self._discovering
        sync = runtime._sync
        running = runtime.running
        addresses = local_addresses(runtime.port)
        discovery_active = runtime.discovery_active
        machines = self._machines.list()
        presetter_clients = runtime.presetter_clients
        with self._activity_lock:
            activity = list(self._activity)
        return {
            "name": config.name, "programsDir": config.programs_dir,
            "pairingCode": config.pairing_code, "running": running,
            "status": status, "error": error, "addresses": addresses,
            "discoveryStatus": ("Bonjour activo" if discovery_active else "Bonjour no disponible")
                               if running else "Detenido",
            "machines": machines, "devices": devices,
            "presetterClients": presetter_clients, "activity": activity,
            "syncStatus": sync.status if sync else "Agent detenido · sincronización en pausa",
            "syncConflicts": copy.deepcopy(sync.conflicts) if sync else [],
            "serverHost": config.program_server_host, "serverPort": config.program_server_port,
            "version": __version__, "discovering": discovering,
        }

    def start(self):
        with self._mutations:
            if self._runtime.running:
                return {"ok": True}
            self._status, self._error = "Iniciando…", ""
            try:
                self._runtime.start()
            except OSError as exc:
                self._error = ("El puerto de Zeuz Agent está ocupado. Cierra la versión anterior de Agent "
                               "y vuelve a presionar Iniciar; esta ventana no detuvo el otro servidor."
                               if exc.errno in {48, 98, 10048} or getattr(exc, "winerror", None) in {10013, 10048} else str(exc))
                self._status = "Error"
                self.record("error", self._error)
                return {"ok": False, "error": self._error}
            except Exception as exc:
                self._status, self._error = "Error", str(exc)
                self.record("error", self._error)
                return {"ok": False, "error": self._error}
            self._status = "Activo"
            return {"ok": True}

    def stop(self):
        with self._mutations:
            self._runtime.stop()
            self._status, self._error = "Detenido", ""
            return {"ok": True}

    def _assert_no_foreign_server(self):
        if self._runtime.running:
            return
        host = self._config.host
        host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
        try:
            with socket.create_connection((host, self._config.port), timeout=0.3):
                pass
        except OSError:
            return
        raise ValueError("Cierra la otra versión de Agent antes de cambiar esta configuración")

    def _save_config(self, value):
        self._assert_no_foreign_server()
        was_running = self._runtime.running
        self._runtime.stop()
        try:
            Path(value.programs_dir).mkdir(parents=True, exist_ok=True)
            value.save(self._config_path)
        except Exception:
            if was_running:
                self.start()
            raise
        runtime = AgentRuntime(value, self._machines_path)
        with self._lock:
            self._config = value
            self._runtime = runtime
        if was_running and not self.start()["ok"]:
            raise ValueError(self._error)
        self.record("info", "Configuración guardada")
        return {"ok": True}

    def _library_source(self, source=None):
        if source not in (None, "local", "server"):
            raise ValueError("Selecciona la biblioteca local o el servidor del taller")
        selected = source or ("server" if self._config.program_server_host else "local")
        if selected == "server" and not self._config.program_server_host:
            raise ValueError("Selecciona un servidor de programas en Configuración")
        return selected

    def _library(self, source=None):
        config = self._config
        return (RemoteProgramLibrary(config.program_server_host, config.program_server_port)
                if self._library_source(source) == "server" else ProgramLibrary(Path(config.programs_dir)))

    def _api(self, method, path, body=None):
        if not self._runtime.running:
            raise ValueError("Inicia Zeuz Agent antes de enviar o consultar una transferencia")
        host = self._config.host
        host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
        request = urllib.request.Request(
            f"http://{host}:{self._runtime.port}{path}",
            data=None if body is None else json.dumps(body).encode(), method=method,
            headers={"Authorization": "Bearer " + self._config.api_token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=50) as response:
                value = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.load(exc).get("error", "Agent rechazó la operación")
            except (ValueError, OSError):
                detail = f"Agent respondió HTTP {exc.code}"
            error_type = TransferUncertain if path == "/v1/dnc/send" and exc.code >= 500 else ValueError
            raise error_type(detail) from exc
        except (OSError, ValueError) as exc:
            error_type = TransferUncertain if path == "/v1/dnc/send" else ValueError
            raise error_type("Se perdió la comunicación con Agent. Consulta el estado antes de volver a enviar.") from exc
        if isinstance(value, dict) and value.get("ok") is False:
            raise ValueError(value.get("error", "Agent rechazó la operación"))
        return value

    def _remote(self, method, path, body, endpoint):
        status, value = ZeuzDNCProxy(token=self._config.api_token).forward(method, path, body, endpoint)
        if status >= 300 or (isinstance(value, dict) and value.get("ok") is False):
            raise ValueError(value.get("error", "Zeuz no confirmó la operación") if isinstance(value, dict)
                             else "Zeuz devolvió una respuesta inválida")
        return value

    def discover(self):
        with self._lock:
            if self._discovering or self._closed.is_set():
                return {"ok": True, "discovering": self._discovering}
            self._discovering = True
            known = {(d["host"], d["port"]): dict(d) for d in self._devices}
            config = self._config
        for machine in self._machines.list():
            known.setdefault((machine["dnc_host"], machine["dnc_port"]),
                             {"host": machine["dnc_host"], "port": machine["dnc_port"], "name": machine["dnc_host"]})
        if config.program_server_host:
            host, port = config.program_server_host, config.program_server_port
            known.setdefault((host, port), {"host": host, "port": port, "name": host})

        def work():
            try:
                devices, error = scan_devices(list(known.values()))
                if not self._closed.is_set():
                    self._device_directory.save(devices)
                    with self._lock:
                        self._devices = devices
                    if error:
                        self.record("warning", "Bonjour: " + error)
            except Exception as exc:
                self.record("error", "No se pudo completar la búsqueda: " + str(exc))
            finally:
                with self._lock:
                    self._discovering = False
        self._executor.submit(work)
        return {"ok": True, "discovering": True}

    def _refresh_updates(self):
        with self._lock:
            if self._update_polling or self._closed.is_set():
                return
            devices = [dict(d) for d in self._devices if d.get("online") and d.get("capabilities", {}).get("remote_update")]
            if not devices:
                return
            self._update_polling = True

        def work():
            try:
                for device in devices:
                    if self._closed.is_set():
                        break
                    try:
                        self._update(device, "status", None)
                    except Exception as exc:
                        with self._lock:
                            for current in self._devices:
                                if (current["host"], current["port"]) == (device["host"], device["port"]):
                                    current["update"] = {**current.get("update", {}), "connection_error": str(exc)}
            finally:
                with self._lock:
                    self._update_polling = False
        self._executor.submit(work)

    def _update(self, params, action, body):
        host, port = str(params["host"]), int(params.get("port", 5000))
        with self._lock:
            device = next((d for d in self._devices if (d["host"], d["port"]) == (host, port)), None)
        if not device:
            raise ValueError("Equipo no encontrado")
        value = self._remote("GET" if action == "status" else "POST", "/api/update/" + action,
                             body, DNCEndpoint(host, port))
        with self._lock:
            for current in self._devices:
                if (current["host"], current["port"]) == (host, port):
                    current["update"] = value
        return value

    def _stage_destination(self, machine):
        return resolve_program_destination(machine, self._remote)

    def _send(self, params):
        path, machine_id = str(params.get("path", "")), str(params.get("machineID", ""))
        machine = self._machines.get(machine_id)
        if not machine:
            raise MachineError("Selecciona una máquina antes de enviar")
        if not self._runtime.running:
            raise ValueError("Inicia Zeuz Agent antes de enviar")
        sync = self._runtime._sync
        if sync and any(item.get("id") == machine_id for item in sync.conflicts):
            raise ValueError("Resuelve los cambios simultáneos de esta máquina antes de enviar")
        source = self._library_source(params.get("source"))
        # Desktop browsing does not change the shared library used by iZeuz.
        # A local selection must still stage its original bytes when the global
        # workshop library happens to be a configured (or offline) server.
        preparation_config = replace(self._config, program_server_host="") if source == "local" else self._config
        send_path, name = prepare_program_send(preparation_config, self._library(source), machine, path,
                                                self._remote, resolve_destination=self._stage_destination)
        # ONLY this request starts RS232. Never repeat an uncertain request.
        try:
            result = self._api("POST", "/v1/dnc/send", {"path": send_path, "machine_id": machine_id})
        except TransferUncertain as exc:
            self.record("warning", f"No se confirmó el envío a {machine['name']}; consulta su estado")
            raise TransferUncertain(str(exc) + ". Consulta el estado de la máquina antes de volver a enviar.") from exc
        self.record("info", f"Envío solicitado: {name} → {machine['name']}")
        return {**result, "path": send_path, "originalPath": path, "machineID": machine_id, "source": source}

    def _export(self, params):
        path, library = str(params.get("path", "")), self._library(params.get("source"))
        if isinstance(library, ProgramLibrary):
            target = library.resolve(path, must_exist=True)
            if not target.is_file():
                raise ValueError("Selecciona un programa")
            return {"ok": True, "path": str(target), "temporary": False}
        name, raw = library.read_bytes(path)
        cache = Path.home() / "Library" / "Caches" / "com.zeuz.agent" / "Edit" / uuid.uuid4().hex
        cache.mkdir(parents=True)
        target = cache / Path(name).name
        target.write_bytes(raw)
        return {"ok": True, "path": str(target), "temporary": True}

    def _import(self, params):
        paths = params.get("paths", [])
        if not isinstance(paths, list) or not paths or len(paths) > 200:
            raise ValueError("Selecciona de 1 a 200 programas")
        folder, library = str(params.get("folder", "")), self._library(params.get("source"))
        library.list(folder)
        imported = []
        for value in paths:
            source = Path(str(value)).expanduser()
            if not source.is_absolute() or not source.is_file():
                raise ValueError("El programa seleccionado ya no está disponible")
            before = source.stat()
            if before.st_size > MAX_TRANSFER_BYTES:
                raise ValueError(f"{source.name}: excede 128 MB")
            raw = source.read_bytes()
            after = source.stat()
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise ValueError(f"{source.name}: el archivo cambió durante la importación")
            if _looks_binary(raw):
                raise ValueError(f"{source.name}: el archivo no es texto CNC compatible")
            for suffix in range(1, 10001):
                name = source.name if suffix == 1 else f"{source.stem} ({suffix}){source.suffix}"
                path = (PurePosixPath(folder) / name).as_posix()
                if isinstance(library, ProgramLibrary):
                    destination = library.resolve(path)
                    fd, temp_name = tempfile.mkstemp(prefix=".zeuz-import-", dir=destination.parent)
                    try:
                        with os.fdopen(fd, "wb") as handle:
                            handle.write(raw)
                            handle.flush()
                            os.fsync(handle.fileno())
                        try:
                            os.link(temp_name, destination)
                        except FileExistsError:
                            continue
                    finally:
                        os.unlink(temp_name)
                    library.tracker.bump()
                else:
                    try:
                        library.create(folder, name)
                    except LibraryError as exc:
                        if exc.status == 409:
                            continue
                        raise
                    digest = hashlib.sha256(raw).hexdigest()
                    value = self._remote("POST", "/api/workshop/mirror", {
                        "path": path, "data": base64.b64encode(raw).decode("ascii"), "sha256": digest}, library.endpoint)
                    if value.get("sha256") != digest:
                        raise ValueError(f"{name}: el servidor no confirmó el archivo completo")
                imported.append(path)
                break
            else:
                raise ValueError("No se pudo asignar un nombre disponible al programa")
        self.record("info", f"Se importaron {len(imported)} programas")
        return {"ok": True, "paths": imported}

    def _import_machines(self, params):
        endpoint = DNCEndpoint(str(params["host"]), int(params.get("port", 5000)))
        profiles = self._remote("GET", "/api/machines", None, endpoint)
        if not isinstance(profiles, list):
            raise ValueError("El equipo no devolvió perfiles compatibles")
        saved_values = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            match = next((m for m in self._machines.list()
                          if (m["dnc_host"], m["dnc_port"]) == (endpoint.host, endpoint.port)
                          and str(m["name"]).casefold() == str(profile.get("name", "")).casefold()), None)
            candidate = {**profile, "id": (match or {}).get("id", profile.get("id", "")),
                         "dnc_host": endpoint.host, "dnc_port": endpoint.port, "dnc_machine_id": profile.get("id", "")}
            collision = self._machines.get(str(candidate["id"]))
            if collision and (collision["dnc_host"], collision["dnc_port"]) != (endpoint.host, endpoint.port):
                candidate["id"] += "-" + hashlib.sha256(f"{endpoint.host}:{endpoint.port}".encode()).hexdigest()[:8]
                collision = self._machines.get(candidate["id"])
            candidate.pop("revision", None)
            if collision:
                candidate["revision"] = collision.get("revision", 0)
            saved_values.append(self._machines.save(candidate))
        if self._runtime._sync:
            self._runtime._sync.mark_dirty()
        return {"ok": True, "machines": saved_values}

    def handle(self, method, params=None):
        params = params or {}
        if not isinstance(params, dict):
            raise ValueError("Los parámetros deben ser un objeto")
        if self._closed.is_set():
            raise ValueError("Zeuz Agent se está cerrando")
        if method == "state":
            return self.state()
        if method == "programs.list":
            path, query = str(params.get("path", "")), str(params.get("query", "")).strip()
            source = self._library_source(params.get("source"))
            library = self._library(source)
            listing = {"entries": library.search(query), "path": path} if query else library.list(path)
            return {**listing, "source": source,
                    "entries": [{**item, "isDirectory": item.get("kind") == "directory"} for item in listing["entries"]]}
        if method == "programs.read":
            return self._library(params.get("source")).read(str(params.get("path", "")))
        if method == "programs.export":
            return self._export(params)
        if method == "transfer.status":
            machine_id = str(params.get("machineID", ""))
            if not self._machines.get(machine_id):
                raise MachineError("Máquina no encontrada")
            return self._api("GET", "/v1/dnc/transfer/status?" + urlencode({"machine_id": machine_id}))
        if method == "discover":
            return self.discover()
        if method == "activity.clear":
            with self._activity_lock:
                self._activity.clear()
            return {"ok": True}
        with self._mutations:
            if method == "start":
                return self.start()
            if method == "stop":
                return self.stop()
            self._assert_no_foreign_server()
            if method == "config.save":
                values = {}
                if "name" in params:
                    name = str(params["name"]).strip()
                    if not name or len(name) > 80:
                        raise ValueError("Usa un nombre de 1 a 80 caracteres")
                    values["name"] = name
                if "programsDir" in params:
                    value = Path(str(params["programsDir"])).expanduser()
                    if not value.is_absolute():
                        raise ValueError("Selecciona una carpeta de programas válida")
                    values["programs_dir"] = str(value.resolve())
                if "serverHost" in params:
                    host = str(params["serverHost"]).strip()
                    if any(c in host for c in "/ :\\\t\r\n"):
                        raise ValueError("Usa el hostname o IPv4 del servidor")
                    values["program_server_host"] = host
                if "serverPort" in params:
                    port = int(params["serverPort"])
                    if not 1 <= port <= 65535:
                        raise ValueError("El puerto debe estar entre 1 y 65535")
                    values["program_server_port"] = port
                return self._save_config(replace(self._config, **values))
            if method in {"pairing.renew", "pairing.revoke"}:
                values = {"pairing_code": f"{secrets.randbelow(1000000):06d}"}
                if method == "pairing.revoke":
                    values["api_token"] = secrets.token_urlsafe(32)
                return self._save_config(replace(self._config, **values))
            if method == "machines.save":
                machine = self._machines.save(params.get("machine", params))
                if self._runtime._sync:
                    self._runtime._sync.mark_dirty()
                return {"ok": True, "machine": machine}
            if method == "machines.delete":
                self._machines.delete(str(params.get("id", params.get("machineID", ""))))
                if self._runtime._sync:
                    self._runtime._sync.mark_dirty()
                return {"ok": True}
            if method == "machines.import":
                return self._import_machines(params)
            if method == "sync.now":
                if self._runtime._sync:
                    self._runtime._sync.wake()
                return {"ok": True}
            if method == "conflict.resolve":
                sync = self._runtime._sync
                if not sync:
                    raise ValueError("Inicia Agent para resolver los cambios")
                sync.resolve(str(params.get("id", params.get("machineID", ""))), str(params["host"]),
                             int(params.get("port", 5000)), bool(params.get("useDevice", False)))
                return {"ok": True}
            if method == "devices.rename":
                name = str(params.get("name", "")).strip()
                if not name or len(name) > 80:
                    raise ValueError("Usa un nombre de 1 a 80 caracteres")
                host, port = str(params["host"]), int(params.get("port", 5000))
                self._remote("POST", "/api/workshop/configure", {"name": name}, DNCEndpoint(host, port))
                with self._lock:
                    self._devices = [{**d, "name": name} if (d["host"], d["port"]) == (host, port)
                                     else d for d in self._devices]
                    devices = copy.deepcopy(self._devices)
                self._device_directory.save(devices)
                return {"ok": True}
            if method.startswith("devices.update."):
                action = method.rsplit(".", 1)[-1]
                if action == "pair":
                    endpoint = DNCEndpoint(str(params["host"]), int(params.get("port", 5000)))
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                        route.connect((endpoint.host, endpoint.port))
                        local = route.getsockname()[0]
                    self._remote("POST", "/api/agent/pair", {
                        "url": f"http://{local}:{self._runtime.port}", "code": self._config.pairing_code,
                        "management_only": True}, endpoint)
                    return self._update(params, "status", None)
                bodies = {"status": None, "check": {}, "install": {
                    "revision": str(params.get("revision", "")), "request_id": str(uuid.uuid4())},
                    "policy": {"auto_install": bool(params.get("enabled", False))}}
                if action not in bodies:
                    raise ValueError("Acción de actualización no reconocida")
                return self._update(params, action, bodies[action])
            if method == "programs.import":
                return self._import(params)
            if method == "transfer.send":
                return self._send(params)
            if method == "transfer.cancel":
                machine_id = str(params.get("machineID", ""))
                if not self._machines.get(machine_id):
                    raise MachineError("Máquina no encontrada")
                return self._api("POST", "/v1/dnc/send/cancel", {"machine_id": machine_id})
        raise ValueError("Acción no reconocida: " + method)

    def dispatch(self, method, params=None):
        return self.handle(method, params)

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        if self._owns_runtime:
            self._runtime.stop()
        if self._scheduler:
            self._scheduler.join(timeout=2)
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._log_handler:
            LOGGER.removeHandler(self._log_handler)
        if self._instance_file:
            self._instance_file.close()


def serve(host, input_stream, output_stream):
    output_lock = threading.Lock()

    def respond(request):
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            if not isinstance(request, dict) or not isinstance(request_id, str) or not isinstance(request.get("method"), str):
                raise ValueError("Solicitud inválida")
            result = host.handle(request["method"], request.get("params", {}))
            payload = {"id": request_id, "result": result}
        except Exception as exc:
            message = str(exc).replace(host._config.api_token, "[oculto]")
            payload = {"id": request_id, "error": message, "uncertain": bool(getattr(exc, "uncertain", False))}
        with output_lock:
            output_stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            output_stream.flush()

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="zeuz-native-rpc") as executor:
        while not host._closed.is_set():
            line = input_stream.readline(MAX_RPC_LINE_BYTES + 1)
            if not line:
                break
            if len(line.encode("utf-8")) > MAX_RPC_LINE_BYTES:
                with output_lock:
                    output_stream.write('{"id":null,"error":"Solicitud demasiado grande"}\n')
                    output_stream.flush()
                break
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                with output_lock:
                    output_stream.write('{"id":null,"error":"JSON inválido"}\n')
                    output_stream.flush()
                continue
            executor.submit(respond, value)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Servicio privado de Zeuz Agent para macOS")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--no-discovery", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(message)s")
    host = NativeHost(args.config, auto_start=not args.no_start, discovery=not args.no_discovery)
    def terminate(signum, frame):
        host.close()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        serve(host, sys.stdin, sys.stdout)
    finally:
        host.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
