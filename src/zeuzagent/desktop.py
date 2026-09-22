from __future__ import annotations

import argparse
import logging
import secrets
import hashlib
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
import sys
from collections import deque
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QStyle,
    QSystemTrayIcon,
)

from . import __version__
from . import autostart
from .config import AgentConfig, default_config_path, load_or_create_config
from .devices import DeviceDirectory, scan_devices
from .dnc_proxy import DNCEndpoint, DNCProxyError, ZeuzDNCProxy
from .machines import MachineError, MachineRegistry
from .runtime import AgentRuntime


LOGGER = logging.getLogger("zeuzagent")


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            value = info[4][0]
            if value and not value.startswith("127."):
                addresses.add(value)
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("192.0.2.1", 9))
        value = probe.getsockname()[0]
        if value and not value.startswith("127."):
            addresses.add(value)
        probe.close()
    except OSError:
        pass
    return sorted(addresses)


class LogEmitter(QObject):
    message = Signal(str, str)


class QtLogHandler(logging.Handler):
    def __init__(self, emitter: LogEmitter) -> None:
        super().__init__()
        self.emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emitter.message.emit(record.levelname.lower(), self.format(record))
        except Exception:
            self.handleError(record)


class DesktopBackend(QObject):
    stateChanged = Signal()
    configChanged = Signal()
    activityChanged = Signal()
    autostartChanged = Signal()
    machinesChanged = Signal()
    devicesChanged = Signal()
    syncChanged = Signal()
    _devicesFound = Signal(object)
    _backgroundError = Signal(str)
    _updateFound = Signal(str, int, object)

    def __init__(self, config_path: Path, tray_available: bool | None = None) -> None:
        super().__init__()
        config, self._config_path, created = load_or_create_config(config_path)
        self._config = config
        self._machines_path = self._config_path.with_name("machines.json")
        self._machines = MachineRegistry(self._machines_path)
        self._runtime = AgentRuntime(config, self._machines_path)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="zeuz-desktop")
        self._discovering = False
        self._devicesFound.connect(self._apply_devices)
        self._updateFound.connect(self._apply_update)
        self._backgroundError.connect(lambda error: self._record("error", error))
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(2000)
        self._sync_timer.timeout.connect(self._refresh_workshop)
        self._sync_timer.start()
        self._discovery_timer = QTimer(self)
        self._discovery_timer.setInterval(30000)
        self._discovery_timer.timeout.connect(self.discoverDevices)
        self._discovery_timer.start()
        self._update_polling = False
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(4000)
        self._update_timer.timeout.connect(self.refreshUpdates)
        self._update_timer.start()
        self._machine_snapshot = []
        self._device_directory = DeviceDirectory(self._config_path.with_name("devices.json"))
        try:
            self._devices = self._device_directory.load()
        except (OSError, ValueError):
            self._devices = []
        self._activity: deque[dict[str, str]] = deque(maxlen=150)
        self._status = "Detenido"
        self._error = ""
        self._machine_error = ""
        self._quitting = False
        self._disposed = False
        self._tray_available = (
            QSystemTrayIcon.isSystemTrayAvailable()
            if tray_available is None
            else tray_available
        )
        self._notified_tray = False

        self._log_emitter = LogEmitter(self)
        self._log_emitter.message.connect(self._append_activity)
        self._log_handler = QtLogHandler(self._log_emitter)
        self._log_handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(self._log_handler)
        LOGGER.setLevel(logging.INFO)

        if created:
            self._record("info", f"Configuración creada en {self._config_path}")
        self._record("info", f"Zeuz Agent {__version__} listo")

    @Property(bool, notify=stateChanged)
    def running(self) -> bool:
        return self._runtime.running

    @Property(str, notify=stateChanged)
    def status(self) -> str:
        return self._status

    @Property(str, notify=stateChanged)
    def error(self) -> str:
        return self._error

    @Property(str, notify=configChanged)
    def agentName(self) -> str:
        return self._config.name

    @Property(str, notify=configChanged)
    def programsDir(self) -> str:
        return self._config.programs_dir

    @Property(str, notify=configChanged)
    def pairingCode(self) -> str:
        code = self._config.pairing_code
        return f"{code[:3]} {code[3:]}" if len(code) == 6 else code

    @Property(int, notify=configChanged)
    def port(self) -> int:
        return self._config.port

    @Property("QVariantList", notify=stateChanged)
    def addresses(self) -> list[dict[str, str]]:
        port = self._runtime.port
        values = local_ipv4_addresses()
        if not values:
            values = ["127.0.0.1"]
        return [{"url": f"http://{address}:{port}"} for address in values]

    @Property("QVariantList", notify=machinesChanged)
    def machines(self) -> list[dict[str, object]]:
        return self._machines.list()

    @Property("QVariantList", notify=devicesChanged)
    def discoveredDevices(self) -> list[dict[str, object]]:
        return self._devices

    @Property(str, notify=stateChanged)
    def discoveryStatus(self) -> str:
        if not self.running:
            return "Detenido"
        return "Bonjour activo" if self._runtime.discovery_active else "Bonjour no disponible"

    @Property("QVariantList", notify=activityChanged)
    def activity(self) -> list[dict[str, str]]:
        return list(self._activity)

    @Property(bool, notify=autostartChanged)
    def startsWithComputer(self) -> bool:
        return autostart.is_enabled()

    @Property(bool, constant=True)
    def trayAvailable(self) -> bool:
        return self._tray_available

    @Property(bool, notify=stateChanged)
    def quitting(self) -> bool:
        return self._quitting

    @Property(str, constant=True)
    def version(self) -> str:
        return __version__

    def _record(self, level: str, message: str) -> None:
        self._activity.appendleft(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "message": message,
            }
        )
        self.activityChanged.emit()

    @Slot(str, str)
    def _append_activity(self, level: str, message: str) -> None:
        self._record(level, message)

    def _save_config(self, config: AgentConfig, restart: bool = True) -> None:
        was_running = self._runtime.running
        if was_running and restart:
            self._runtime.stop()
        Path(config.programs_dir).mkdir(parents=True, exist_ok=True)
        config.save(self._config_path)
        self._config = config
        self._runtime = AgentRuntime(config, self._machines_path)
        self.configChanged.emit()
        if was_running and restart:
            self.start()
        else:
            self.stateChanged.emit()

    @Slot()
    def start(self) -> None:
        if self._runtime.running:
            return
        self._status = "Iniciando…"
        self._error = ""
        self.stateChanged.emit()
        try:
            self._runtime.start()
        except OSError as exc:
            self._status = "Error"
            self._error = str(exc)
            self._record("error", f"No se pudo iniciar: {exc}")
        except Exception as exc:  # noqa: BLE001 - surfaced to the desktop operator
            self._status = "Error"
            self._error = str(exc)
            LOGGER.exception("No se pudo iniciar Zeuz Agent")
        else:
            self._status = "Activo"
        self.stateChanged.emit()

    @Slot()
    def stop(self) -> None:
        self._status = "Deteniendo…"
        self.stateChanged.emit()
        self._runtime.stop()
        self._status = "Detenido"
        self._error = ""
        self.stateChanged.emit()

    @Slot()
    def restart(self) -> None:
        self.stop()
        self.start()

    @Slot(str, int)
    def saveIdentity(self, name: str, port: int) -> None:
        clean_name = name.strip()
        if not clean_name:
            self._record("error", "El nombre del agente no puede estar vacío")
            return
        if not 1024 <= port <= 65535:
            self._record("error", "El puerto debe estar entre 1024 y 65535")
            return
        self._save_config(replace(self._config, name=clean_name, port=port))
        self._record("info", "Configuración guardada")

    @Property(str, notify=machinesChanged)
    def machineError(self):
        return self._machine_error

    @Slot()
    def beginMachineEdit(self):
        self._machine_error = ""
        self.machinesChanged.emit()

    @Slot("QVariantMap", result=bool)
    def saveMachine(self, value) -> bool:
        try:
            saved = self._machines.save(dict(value))
        except MachineError as exc:
            self._machine_error = str(exc)
            self.machinesChanged.emit()
            self._record("error", str(exc))
            return False
        self._machine_error = ""
        if self._runtime._sync:
            self._runtime._sync.mark_dirty()
        self.syncChanged.emit()
        self.machinesChanged.emit()
        self._record("info", f"Máquina guardada: {saved['name']}")
        return True

    @Slot(str)
    def deleteMachine(self, machine_id: str) -> None:
        machine = self._machines.get(machine_id)
        try:
            self._machines.delete(machine_id)
        except MachineError as exc:
            self._record("error", str(exc))
            return
        if self._runtime._sync:
            self._runtime._sync.mark_dirty()
        self.syncChanged.emit()
        self.machinesChanged.emit()
        self._record("warning", f"Máquina eliminada: {(machine or {}).get('name', machine_id)}")

    @Property(str, notify=configChanged)
    def programServer(self):
        return self._config.program_server_host

    @Property(int, notify=configChanged)
    def programServerPort(self):
        return self._config.program_server_port

    @Property(str, notify=syncChanged)
    def syncStatus(self):
        sync = self._runtime._sync
        return sync.status if sync else "Agent detenido · sincronización en pausa"

    @Property("QVariantList", notify=syncChanged)
    def syncConflicts(self):
        sync = self._runtime._sync
        return list(sync.conflicts) if sync else []

    @Property(bool, notify=devicesChanged)
    def discovering(self):
        return self._discovering

    def _refresh_workshop(self):
        values = self._machines.list()
        if values != self._machine_snapshot:
            self._machine_snapshot = values
            if self._runtime._sync:
                self._runtime._sync.mark_dirty()
            self.machinesChanged.emit()
        self.syncChanged.emit()

    @Slot(str, int)
    def selectProgramServer(self, host, port):
        host = host.strip()
        if not host or any(character in host for character in "/ :\\") or not 1 <= port <= 65535:
            self._record("error", "Usa el hostname o IPv4 del servidor y un puerto válido")
            return
        self._save_config(replace(self._config, program_server_host=host, program_server_port=port))
        self._record("info", f"Servidor de programas: {host}. Se conservarán los archivos borrados de la computadora.")
        self.syncChanged.emit()

    @Slot()
    def syncNow(self):
        if self._runtime._sync:
            self._runtime._sync.wake()

    @Slot(str, str, int, bool)
    def resolveMachineConflict(self, machine_id, host, port, use_device):
        sync = self._runtime._sync
        if sync:
            self._background(lambda: sync.resolve(machine_id, host, port, use_device))

    def _background(self, work):
        def run():
            try:
                work()
            except Exception as exc:
                self._backgroundError.emit(str(exc))
        self._executor.submit(run)

    @Slot(str, int, str)
    def renameDevice(self, host, port, name):
        def rename():
            status, payload = ZeuzDNCProxy(token=self._config.api_token).forward("POST", "/api/workshop/configure", {"name": name}, DNCEndpoint(host, port))
            if status != 200:
                raise ValueError(payload.get("error", "Actualiza ZeuzDNC para cambiar el nombre"))
            self._devicesFound.emit([{**device, "name": name.strip()} if device["host"] == host and device["port"] == port else device for device in self._devices])
        self._background(rename)

    @Slot(str, int, object)
    def _apply_update(self, host, port, value):
        if self._disposed: return
        for device in self._devices:
            if device["host"] == host and device["port"] == port:
                device["update"] = value
        self.devicesChanged.emit()

    def _update_request(self, host, port, action, body=None):
        device = next((d for d in self._devices if d["host"] == host and d["port"] == port), None)
        if not device: raise ValueError("Equipo no encontrado")
        status, value = ZeuzDNCProxy(token=self._config.api_token).forward(
            "GET" if action == "status" else "POST", "/api/update/" + action, body, DNCEndpoint(host, port))
        if status != 200:
            raise ValueError(value.get("error", "No se pudo administrar la actualización"))
        self._updateFound.emit(host, port, value)

    @Slot()
    def refreshUpdates(self):
        if self._update_polling or self._disposed: return
        devices = [dict(d) for d in self._devices if d.get("online") and d.get("capabilities", {}).get("remote_update")]
        if not devices: return
        self._update_polling = True
        def work():
            try:
                for device in devices:
                    try: self._update_request(device["host"], device["port"], "status")
                    except Exception as exc:
                        self._updateFound.emit(device["host"], device["port"], {**device.get("update", {}), "connection_error": str(exc)})
            finally: self._update_polling = False
        self._background(work)

    @Slot(str, int)
    def checkDeviceUpdate(self, host, port):
        self._background(lambda: self._update_request(host, port, "check", {}))

    @Slot(str, int, str)
    def installDeviceUpdate(self, host, port, revision):
        import uuid
        self._background(lambda: self._update_request(host, port, "install", {"revision": revision, "request_id": str(uuid.uuid4())}))

    @Slot(str, int, bool)
    def setAutoUpdate(self, host, port, enabled):
        self._background(lambda: self._update_request(host, port, "policy", {"auto_install": enabled}))

    @Slot(str, int)
    def pairUpdateDevice(self, host, port):
        def work():
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect((host, port))
                local_address = route.getsockname()[0]
            url = f"http://{local_address}:{self._config.port}"
            status, value = ZeuzDNCProxy(token=self._config.api_token).forward("POST", "/api/agent/pair",
                {"url": url, "code": self._config.pairing_code, "management_only": True}, DNCEndpoint(host, port))
            if status != 200: raise ValueError(value.get("error", "No se pudo vincular el equipo"))
            self._update_request(host, port, "status")
        self._background(work)

    @Slot(object)
    def _apply_devices(self, devices):
        if self._disposed:
            return
        self._devices = devices
        try:
            self._device_directory.save(devices)
        except OSError as exc:
            self._record("error", f"No se pudo guardar el inventario de equipos: {exc}")
        self._discovering = False
        self.devicesChanged.emit()

    @Slot()
    def discoverDevices(self) -> None:
        if self._discovering or self._disposed:
            return
        self._discovering = True
        self.devicesChanged.emit()
        known = {(d["host"], d["port"]): dict(d) for d in self._devices}
        for machine in self._machines.list():
            known.setdefault((machine["dnc_host"], machine["dnc_port"]), {"name": machine["dnc_host"], "host": machine["dnc_host"], "port": machine["dnc_port"]})
        if self.programServer:
            known.setdefault((self.programServer, self.programServerPort), {"name": self.programServer, "host": self.programServer, "port": self.programServerPort})
        def discover():
            try:
                devices, error = scan_devices(list(known.values()))
                if error:
                    self._backgroundError.emit(f"Bonjour: {error}. Se comprobaron también los equipos guardados.")
                self._devicesFound.emit(devices)
            except Exception as exc:
                self._backgroundError.emit(f"No se pudo completar la búsqueda: {exc}")
                self._devicesFound.emit(list(known.values()))
        self._executor.submit(discover)

    @Slot(str, int)
    def importMachines(self, host: str, port: int) -> None:
        endpoint = DNCEndpoint(host.strip(), port)
        try:
            status, profiles = ZeuzDNCProxy().forward(
                "GET", "/api/machines", endpoint=endpoint
            )
            if status != 200 or not isinstance(profiles, list):
                raise MachineError("La Orange Pi no devolvió perfiles compatibles")
            existing = self._machines.list()
            imported = 0
            for profile in profiles:
                if not isinstance(profile, dict):
                    continue
                match = next(
                    (
                        machine for machine in existing
                        if machine.get("dnc_host") == endpoint.host
                        and str(machine.get("name", "")).casefold()
                        == str(profile.get("name", "")).casefold()
                    ),
                    None,
                )
                candidate = {
                    **profile,
                    "id": (match or {}).get("id", profile.get("id", "")),
                    "dnc_host": endpoint.host,
                    "dnc_port": endpoint.port,
                    "dnc_machine_id": profile.get("id", ""),
                }
                collision = self._machines.get(str(candidate["id"]))
                if collision and (collision["dnc_host"], collision["dnc_port"]) != (endpoint.host, endpoint.port):
                    candidate["id"] += "-" + hashlib.sha256(f"{endpoint.host}:{endpoint.port}".encode()).hexdigest()[:8]
                    collision = self._machines.get(candidate["id"])
                candidate.pop("revision", None)
                if collision:
                    candidate["revision"] = collision.get("revision", 0)
                saved = self._machines.save(candidate)
                existing.append(saved)
                imported += 1
        except (DNCProxyError, MachineError, OSError, ValueError) as exc:
            self._record("error", f"No se pudieron importar máquinas: {exc}")
            return
        self.machinesChanged.emit()
        self._record("info", f"Se importaron {imported} perfiles desde {endpoint.host}")

    @Slot()
    def selectProgramsDirectory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            None,
            "Seleccionar carpeta de programas CNC",
            self._config.programs_dir,
        )
        if not selected:
            return
        self._save_config(replace(self._config, programs_dir=str(Path(selected).resolve())))
        self._record("info", f"Carpeta cambiada a {selected}")

    @Slot()
    def openProgramsDirectory(self) -> None:
        Path(self._config.programs_dir).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._config.programs_dir))

    @Slot()
    def regeneratePairingCode(self) -> None:
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._save_config(replace(self._config, pairing_code=code))
        self._record("info", "Se generó un nuevo código de emparejamiento")

    @Slot()
    def revokeAllDevices(self) -> None:
        config = replace(
            self._config,
            api_token=secrets.token_urlsafe(32),
            pairing_code=f"{secrets.randbelow(1_000_000):06d}",
        )
        self._save_config(config)
        self._record("warning", "Se revocaron todos los accesos y se cambió el código")

    @Slot(str)
    def copyText(self, value: str) -> None:
        QApplication.clipboard().setText(value)
        self._record("info", "Copiado al portapapeles")

    @Slot(bool)
    def setStartsWithComputer(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError as exc:
            self._record("error", f"No se pudo cambiar el inicio automático: {exc}")
        self.autostartChanged.emit()

    @Slot()
    def clearActivity(self) -> None:
        self._activity.clear()
        self.activityChanged.emit()

    @Slot()
    def notifyStillRunning(self) -> None:
        if not self._notified_tray:
            self._record("info", "La ventana se ocultó; Zeuz Agent continúa en la bandeja")
            self._notified_tray = True

    @Slot()
    def quitApplication(self) -> None:
        self._quitting = True
        self.stateChanged.emit()
        self.dispose()
        QApplication.quit()

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._sync_timer.stop()
        self._discovery_timer.stop()
        self._update_timer.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._runtime.stop()
        LOGGER.removeHandler(self._log_handler)


def create_icon(size: int = 128) -> QIcon:
    # macOS does not mask a QIcon supplied at runtime. Use the same inset,
    # rounded artwork as the app bundle instead of overriding it with the
    # full-bleed PNG intended for other surfaces.
    filename = "AppIcon.icns" if sys.platform == "darwin" else "app.png"
    return QIcon(str(Path(__file__).resolve().parent / "assets" / filename))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Zeuz Agent Desktop")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Zeuz Agent")
    app.setOrganizationName("Zeuz")
    app.setApplicationVersion(__version__)
    icon = create_icon()
    app.setWindowIcon(icon)

    tray_enabled = not args.no_tray and QSystemTrayIcon.isSystemTrayAvailable()
    backend = DesktopBackend(args.config, tray_available=tray_enabled)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        return 1
    window = engine.rootObjects()[0]

    tray: QSystemTrayIcon | None = None
    if tray_enabled:
        app.setQuitOnLastWindowClosed(False)
        tray = QSystemTrayIcon(icon, app)
        menu = QMenu()
        show_action = menu.addAction("Abrir Zeuz Agent")
        show_action.triggered.connect(lambda: (window.show(), window.raise_(), window.requestActivate()))
        menu.addSeparator()
        start_action = menu.addAction("Iniciar")
        start_action.triggered.connect(backend.start)
        stop_action = menu.addAction("Detener")
        stop_action.triggered.connect(backend.stop)
        menu.addSeparator()
        quit_action = menu.addAction("Salir")
        quit_action.triggered.connect(backend.quitApplication)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: (
                (window.show(), window.raise_(), window.requestActivate())
                if reason == QSystemTrayIcon.Trigger
                else None
            )
        )
        tray.show()

    QTimer.singleShot(0, backend.start)
    QTimer.singleShot(1000, backend.discoverDevices)
    if args.minimized and tray:
        window.hide()
    else:
        window.show()
    exit_code = app.exec()
    if not backend.quitting:
        backend.quitApplication()
    if tray:
        tray.hide()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
