from __future__ import annotations

import json
import hmac
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__
from .config import AgentConfig
from .dnc_proxy import DNCProxyError, ZeuzDNCProxy
from .library import LibraryError, ProgramLibrary


LOGGER = logging.getLogger("zeuzagent")
MAX_REQUEST_BYTES = 4 * 1024 * 1024


class ZeuzHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], config: AgentConfig, library: ProgramLibrary) -> None:
        super().__init__(address, ZeuzRequestHandler)
        self.config = config
        self.library = library
        self.dnc_proxy = ZeuzDNCProxy()


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

        dnc_routes = {
            "/v1/dnc/machines": "/api/machines",
            "/v1/dnc/transfer/status": "/api/transfer/status",
            "/v1/dnc/device/select": "/api/device/select",
            "/v1/dnc/machine/select": "/api/machine/select",
            "/v1/dnc/machine/save": "/api/machine/save",
            "/v1/dnc/machine/delete": "/api/machine/delete",
            "/v1/dnc/send": "/api/send",
            "/v1/dnc/send/cancel": "/api/send/cancel",
        }
        if path in dnc_routes:
            body = self._body() if method in {"POST", "PUT"} else None
            try:
                status, payload = self.server.dnc_proxy.forward(method, dnc_routes[path], body)
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
        except LibraryError as exc:
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


def create_server(config: AgentConfig, library: ProgramLibrary) -> ZeuzHTTPServer:
    return ZeuzHTTPServer((config.host, config.port), config, library)
