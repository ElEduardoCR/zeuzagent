from __future__ import annotations

import json
import hmac
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__
from .config import AgentConfig
from .dnc_proxy import DNCEndpoint, DNCProxyError, ZeuzDNCProxy
from .library import LibraryError, ProgramLibrary
from .machines import MachineError, MachineRegistry, serial_profile


LOGGER = logging.getLogger("zeuzagent")
MAX_REQUEST_BYTES = 4 * 1024 * 1024


class ZeuzHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        config: AgentConfig,
        library: ProgramLibrary,
        machines: MachineRegistry,
    ) -> None:
        super().__init__(address, ZeuzRequestHandler)
        self.config = config
        from .remote_library import RemoteProgramLibrary
        self.library = RemoteProgramLibrary(config.program_server_host, config.program_server_port) if config.program_server_host else library
        self.machines = machines
        self.dnc_proxy = ZeuzDNCProxy(token=config.api_token)
        self.workshop_sync = None
        self.selected_machine_id: str | None = None
        self.selection_lock = threading.Lock()


class ZeuzRequestHandler(BaseHTTPRequestHandler):
    server: ZeuzHTTPServer

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), fmt % args)

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Zeuz-API-Version", "1")
        self.end_headers()
        self.wfile.write(raw)

    def _bytes(self, name: str, payload: bytes) -> None:
        safe_name = name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Zeuz-API-Version", "1")
        self.end_headers()
        self.wfile.write(payload)

    def _body(self) -> dict:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise LibraryError("Content-Length inválido") from exc
        if size < 0 or size > MAX_REQUEST_BYTES:
            error = LibraryError("La solicitud excede el límite permitido")
            error.status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            raise error
        raw = self.rfile.read(size) if size else b"{}"
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LibraryError("JSON inválido") from exc
        if not isinstance(value, dict):
            raise LibraryError("El cuerpo debe ser un objeto JSON")
        return value

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.config.api_token}"
        return hmac.compare_digest(self.headers.get("Authorization", ""), expected)

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"

        if method == "GET" and path == "/v1/health":
            self._json({"ok": True, "service": "zeuzagent", "version": __version__})
            return
        if method == "GET" and path == "/v1/info":
            self._json(
                {
                    "name": self.server.config.name,
                    "service": "zeuzagent",
                    "version": __version__,
                    "api_version": 1,
                    "pairing_required": True,
                }
            )
            return
        if method == "POST" and path == "/v1/pair":
            body = self._body()
            supplied = str(body.get("code", "")).strip()
            if not hmac.compare_digest(supplied, self.server.config.pairing_code):
                self._json({"ok": False, "error": "Código de emparejamiento inválido"}, 403)
                return
            self._json(
                {
                    "ok": True,
                    "token": self.server.config.api_token,
                    "agent_name": self.server.config.name,
                    "api_version": 1,
                }
            )
            return

        if not self._authorized():
            self._json({"ok": False, "error": "Emparejamiento requerido"}, 401)
            return

        if path == "/v1/workshop" and method == "GET":
            host = self.server.config.program_server_host
            port = self.server.config.program_server_port
            # Advertise fallback only after the Pi acknowledges the same credential.
            ready = False
            if host:
                import urllib.request
                request = urllib.request.Request(f"http://{host}:{port}/v1/programs?path=", headers={"Authorization": f"Bearer {self.server.config.api_token}"})
                try:
                    with urllib.request.urlopen(request, timeout=3) as response:
                        ready = response.status == 200
                except OSError:
                    pass
            self._json({"server_url": f"http://{host}:{port}" if ready else ""})
            return

        if path.startswith("/v1/dnc/update/"):
            body = self._body() if method == "POST" else {}
            machine_id = body.pop("machine_id", None) or _first(query, "machine_id")
            machine = self.server.machines.get(machine_id)
            if not machine:
                raise MachineError("Máquina no encontrada")
            endpoint = DNCEndpoint(machine["dnc_host"], int(machine["dnc_port"]))
            status, payload = self.server.dnc_proxy.forward(method, path.replace("/v1/dnc/", "/api/"), body if method == "POST" else None, endpoint)
            if status == 404:
                payload = {"supported": False, "phase": "unsupported", "error": "Este equipo requiere la instalación inicial de firmware compatible con actualización remota"}
                status = 200
            self._json(payload, status)
            return

        if path == "/v1/dnc/machines" and method == "GET":
            self._json(self.server.machines.list())
            return
        if path == "/v1/dnc/machine/save" and method == "POST":
            saved = self.server.machines.save(self._body())
            if self.server.workshop_sync:
                self.server.workshop_sync.mark_dirty()
            self._json({"ok": True, "machine": saved})
            return
        if path == "/v1/dnc/machine/delete" and method == "POST":
            body = self._body()
            self.server.machines.delete(str(body.get("id", "")))
            if self.server.workshop_sync:
                self.server.workshop_sync.mark_dirty()
            with self.server.selection_lock:
                if self.server.selected_machine_id == body.get("id"):
                    self.server.selected_machine_id = None
            self._json({"ok": True})
            return
        if path == "/v1/dnc/machine/select" and method == "POST":
            machine_id = str(self._body().get("id", ""))
            if not self.server.machines.get(machine_id):
                raise MachineError("Máquina no encontrada en Zeuz Agent")
            with self.server.selection_lock:
                self.server.selected_machine_id = machine_id
            self._json({"ok": True})
            return
        if path == "/v1/dnc/device/select" and method == "POST":
            self._body()
            self._json({"ok": True, "deprecated": True})
            return
        if path in {"/v1/dnc/transfer/status", "/v1/dnc/send", "/v1/dnc/send/cancel"}:
            body = self._body() if method in {"POST", "PUT"} else None
            requested_machine_id = str(
                (body or {}).get("machine_id") or _first(query, "machine_id") or ""
            )
            with self.server.selection_lock:
                selected_machine_id = self.server.selected_machine_id
            machine = self.server.machines.get(requested_machine_id or selected_machine_id)
            if not machine:
                raise MachineError("Selecciona una máquina antes de enviar")
            endpoint = DNCEndpoint(str(machine["dnc_host"]), int(machine["dnc_port"]), machine["name"])
            dnc_path = {
                "/v1/dnc/transfer/status": "/api/transfer/status",
                "/v1/dnc/send": "/api/send",
                "/v1/dnc/send/cancel": "/api/send/cancel",
            }[path]
            if path == "/v1/dnc/send":
                status, profiles = self.server.dnc_proxy.forward("GET", "/api/workshop/machines", endpoint=endpoint)
                if status == 200 and not isinstance(profiles, list):
                    raise MachineError("Respuesta de perfiles inválida")
                if status == 200:
                    remote = next((item for item in profiles if item.get("id") == serial_profile(machine)["id"]), None)
                    if remote is None or serial_profile(remote) != serial_profile(machine):
                        self._json({"ok": False, "error": "El perfil aún no está sincronizado. Revisa la máquina en Agent antes de enviar."}, 409)
                        return
                body = {**(body or {}), "machine": serial_profile(machine)}
                # Compatibility with Orange Pi images that still expect a
                # locally selected profile. Imported profiles preserve their
                # legacy id, while current images simply ignore this best-effort
                # selection and use the supplied profile below.
                try:
                    self.server.dnc_proxy.forward(
                        "POST", "/api/machine/select", {"id": serial_profile(machine)["id"]}, endpoint
                    )
                except DNCProxyError:
                    pass
            try:
                status, payload = self.server.dnc_proxy.forward(method, dnc_path, body, endpoint)
            except DNCProxyError as exc:
                self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            else:
                self._json(payload, status)
            return

        library = self.server.library
        if method == "GET" and path == "/v1/programs":
            self._json(library.list(_first(query, "path")))
        elif method == "GET" and path == "/v1/programs/content":
            self._json(library.read(_first(query, "path")))
        elif method == "GET" and path == "/v1/programs/download":
            name, payload = library.read_bytes(_first(query, "path"))
            self._bytes(name, payload)
        elif method == "GET" and path == "/v1/programs/search":
            self._json({"results": library.search(_first(query, "q"))})
        elif method == "GET" and path == "/v1/changes":
            since = _integer(query, "since", 0)
            timeout = float(_first(query, "timeout") or "0")
            if self.server.config.program_server_host:
                library.tracker.bump()
            version = library.tracker.wait_for_change(since, timeout)
            self._json({"version": version, "changed": version > since})
        elif method == "PUT" and path == "/v1/programs/content":
            body = self._body()
            expected = body.get("expected_modified")
            self._json(
                library.write(
                    str(body.get("path", "")),
                    str(body.get("content", "")),
                    expected_modified=float(expected) if expected is not None else None,
                )
            )
        elif method == "POST" and path == "/v1/programs":
            body = self._body()
            self._json(
                library.create(
                    str(body.get("directory", "")),
                    str(body.get("name", "")),
                    kind=str(body.get("kind", "file")),
                ),
                HTTPStatus.CREATED,
            )
        elif method == "DELETE" and path == "/v1/programs/content":
            self._json(library.delete(_first(query, "path")))
        else:
            self._json({"ok": False, "error": "Ruta no encontrada"}, 404)

    def _handle(self, method: str) -> None:
        try:
            self._dispatch(method)
        except (LibraryError, MachineError) as exc:
            self._json({"ok": False, "error": str(exc)}, getattr(exc, "status", 400))
        except (TypeError, ValueError):
            self._json({"ok": False, "error": "Parámetro inválido"}, 400)
        except Exception:
            LOGGER.exception("Error no controlado")
            self._json({"ok": False, "error": "Error interno del agente"}, 500)

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_DELETE(self) -> None:
        self._handle("DELETE")


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [""])
    return values[0] if values else ""


def _integer(query: dict[str, list[str]], key: str, default: int) -> int:
    value = _first(query, key)
    return int(value) if value else default


def create_server(
    config: AgentConfig,
    library: ProgramLibrary,
    machines: MachineRegistry | None = None,
) -> ZeuzHTTPServer:
    registry = machines or MachineRegistry(Path(config.programs_dir).parent / "machines.json")
    return ZeuzHTTPServer((config.host, config.port), config, library, registry)
