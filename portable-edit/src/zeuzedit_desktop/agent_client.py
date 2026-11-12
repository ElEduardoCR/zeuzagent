"""Agent API v1 client. Send requests are never automatically retried."""
from __future__ import annotations

import json
import re
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class AgentError(Exception):
    pass


class TransferUncertain(AgentError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AgentError("Agent redirigió la solicitud; verifica su dirección.")


class AgentClient:
    def __init__(self, endpoint: str, token: str = "", timeout: float = 10):
        endpoint = endpoint.strip().rstrip("/")
        if "://" not in endpoint:
            endpoint = "http://" + endpoint
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise AgentError("Usa la dirección de Agent, por ejemplo http://192.168.1.10:47820")
        self.endpoint, self.token, self.timeout = endpoint, token, timeout
        self.opener = build_opener(NoRedirect())

    def request(self, method: str, route: str, body=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = None if body is None else json.dumps(body).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.endpoint + route, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            if route == "/v1/dnc/program/send" and exc.code == 404:
                raise AgentError("Actualiza Zeuz Agent: esta versión no admite el envío de programas desde Edit. No se inició ningún envío ni se usó una ruta anterior.") from None
            try:
                message = json.load(exc).get("error", f"Agent respondió {exc.code}")
            except (ValueError, AttributeError):
                message = f"Agent respondió {exc.code}"
            error_type = TransferUncertain if route == "/v1/dnc/program/send" and exc.code >= 500 else AgentError
            raise error_type(str(message)) from None
        except (URLError, OSError, ValueError) as exc:
            if method == "POST" and route == "/v1/dnc/program/send":
                raise TransferUncertain("No se confirmó el envío. Consulta el estado de la máquina antes de volver a enviar; no se repitió la orden.") from None
            raise AgentError("No se pudo comunicar con Agent. Verifica que esté activo y la dirección sea correcta.") from None

    def pair(self, code: str):
        result = self.request("POST", "/v1/pair", {"code": code.replace(" ", "")})
        self.token = result["token"]
        return result.get("agent_name", "Zeuz Agent")

    def machines(self):
        return self.request("GET", "/v1/dnc/machines")

    def upload(self, name: str, content: str):
        # The API writes Latin-1. Reject lossy conversion before creating a file.
        content.encode("latin-1", errors="strict")
        if len(json.dumps({"path": "x" * 100, "content": content}).encode("utf-8")) > 4 * 1024 * 1024:
            raise AgentError("El programa excede el límite de carga de Agent. Guárdalo directamente en su biblioteca y envíalo desde Agent.")
        stem = re.sub(r"[^\w.-]+", "_", name.rsplit(".", 1)[0])[:70] or "Programa"
        remote_name = f"ZEUZEdit-{stem}-{uuid.uuid4().hex[:10]}.nc"
        created = self.request("POST", "/v1/programs", {"directory": "", "name": remote_name, "kind": "file"})
        path = created.get("path", remote_name)
        result = self.request("PUT", "/v1/programs/content", {"path": path, "content": content, "expected_modified": created.get("modified")})
        return result["path"]

    def send(self, path: str, machine_id: str):
        if not machine_id:
            raise AgentError("Selecciona una máquina antes de enviar.")
        return self.request("POST", "/v1/dnc/program/send", {"path": path, "machine_id": machine_id})

    def status(self, machine_id: str):
        return self.request("GET", "/v1/dnc/transfer/status?" + urlencode({"machine_id": machine_id}))

    def cancel(self, machine_id: str):
        return self.request("POST", "/v1/dnc/send/cancel", {"machine_id": machine_id})
