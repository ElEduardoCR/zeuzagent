"""Repair a paired Pi's clock before its HTTPS update check, never a CNC send."""
from __future__ import annotations

import time
import uuid

from .dnc_proxy import DNCProxyError


MAX_CLOCK_SKEW_SECONDS = 120
CLOCK_SYNC_BUDGET_SECONDS = 8


def synchronize_clock(proxy, endpoint):
    """Use the optional authenticated clock API and confirm the applied time.

    Older firmware returns 404 and retains its existing update behavior. A
    clock correction is submitted once; polling only reads its result.
    """
    deadline = time.monotonic() + CLOCK_SYNC_BUDGET_SECONDS

    def request(method, path, body=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DNCProxyError("El equipo no confirmó el ajuste del reloj. Vuelve a comprobar la actualización.")
        status, value = proxy.forward(method, path, body, endpoint,
                                      timeout=min(2.0, remaining), retry_reads=False)
        if status == 404 and method == "GET" and path == "/api/system/clock/status":
            return None
        if status >= 300 or not isinstance(value, dict) or value.get("ok") is False:
            detail = value.get("error") if isinstance(value, dict) else None
            raise DNCProxyError(detail or "No se pudo comprobar el reloj del equipo antes de actualizar")
        return value

    def aligned(value):
        instant = value.get("utc_unix")
        if not isinstance(instant, int) or isinstance(instant, bool):
            raise DNCProxyError("El equipo devolvió una hora inválida; no se inició la actualización")
        return abs(time.time() - instant) <= MAX_CLOCK_SKEW_SECONDS

    initial = request("GET", "/api/system/clock/status")
    if initial is None or aligned(initial):
        return
    if initial.get("supported") is not True:
        raise DNCProxyError("El reloj del equipo está desajustado y necesita habilitar su reparación remota")

    request_id = str(uuid.uuid4())
    result = request("POST", "/api/system/clock/sync",
                     {"utc_unix": int(time.time()), "request_id": request_id})
    while True:
        if result is None or result.get("request_id") != request_id:
            raise DNCProxyError("No se pudo confirmar la solicitud de ajuste del reloj")
        phase = result.get("phase")
        if phase == "succeeded":
            if not aligned(result):
                raise DNCProxyError("El reloj sigue desajustado después del ajuste; no se inició la actualización")
            return
        if phase == "failed":
            raise DNCProxyError(result.get("error") or "No se pudo ajustar el reloj del equipo")
        if phase != "pending":
            raise DNCProxyError("El equipo no confirmó el ajuste del reloj")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DNCProxyError("El equipo no confirmó el ajuste del reloj. Vuelve a comprobar la actualización.")
        time.sleep(min(0.25, remaining))
        result = request("GET", "/api/system/clock/status")
