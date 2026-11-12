"""Prepare an explicit desktop program for ZeuzDNC without serial side effects.

Both the native companion and the authenticated desktop-send API use this code.
Existing mobile sends keep their original path-only contract.
"""
from __future__ import annotations
import base64
import hashlib
import uuid
from urllib.parse import urlsplit

from .dnc_proxy import DNCEndpoint
from .library import LibraryError, MAX_TRANSFER_BYTES, _looks_binary


class ProgramPreparationError(LibraryError):
    """A definitive failure before any RS232 start request was made."""
    status = 422


def resolve_program_destination(machine, request):
    target = DNCEndpoint(machine["dnc_host"], int(machine["dnc_port"]))
    info = request("GET", "/api/info", None, target)
    source = request("GET", "/api/workshop/info", None, target)
    visited = set()
    for _ in range(4):
        key = (target.host, target.port)
        if key in visited:
            raise ValueError("Los servidores de programas forman un ciclo; revisa su configuración")
        visited.add(key)
        url = source.get("program_server", "")
        if not url:
            break
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in {"", "/"}):
            raise ValueError("El servidor de programas del equipo no es compatible")
        target = DNCEndpoint(parsed.hostname, parsed.port or 80)
        info = request("GET", "/api/info", None, target)
        if info.get("service") != "zeuz-dnc":
            raise ValueError("El servidor de programas no es un equipo ZeuzDNC")
        source = request("GET", "/api/workshop/info", None, target)
    else:
        raise ValueError("Hay demasiados servidores de programas enlazados")
    if "program_server" not in source and info.get("agent_configured"):
        raise ValueError("Este Zeuz usa una biblioteca Agent anterior. Selecciona su servidor de programas en Agent antes de enviar.")
    return target


def prepare_program_send(config, library, machine, path, request, *, resolve_destination=None):
    # FULL original bytes are independent of the truncated preview contract.
    name, raw = library.read_bytes(path)
    if len(raw) > MAX_TRANSFER_BYTES:
        raise ValueError("El programa excede el límite de transferencia de 128 MB")
    if _looks_binary(raw):
        raise ValueError("El archivo no es texto CNC compatible")
    if config.program_server_host:
        return path, name
    target = (resolve_destination or (lambda value: resolve_program_destination(value, request)))(machine)
    staged_path = f"Agent Transfers/{uuid.uuid4().hex}/{name}"
    digest = hashlib.sha256(raw).hexdigest()
    staged = request("POST", "/api/workshop/mirror", {
        "path": staged_path, "data": base64.b64encode(raw).decode("ascii"), "sha256": digest}, target)
    if not isinstance(staged, dict) or staged.get("sha256") != digest:
        raise ValueError("Zeuz no confirmó el archivo completo; no se inició el envío")
    return staged_path, name
