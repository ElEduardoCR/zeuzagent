from __future__ import annotations

import logging
import threading
from dataclasses import replace
from pathlib import Path

from .config import AgentConfig
from .discovery import DiscoveryPublisher
from .library import PollingWatcher, ProgramLibrary
from .server import ZeuzHTTPServer, create_server


LOGGER = logging.getLogger("zeuzagent")


class AgentRuntime:
    """Owns the HTTP server, watcher and mDNS publisher for CLI and desktop use."""

    def __init__(self, config: AgentConfig) -> None:
        self._lock = threading.RLock()
        self._config = config
        self._server: ZeuzHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._watcher: PollingWatcher | None = None
        self._discovery: DiscoveryPublisher | None = None
        self._discovery_active = False

    @property
    def config(self) -> AgentConfig:
        with self._lock:
            return self._config

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._server_thread and self._server_thread.is_alive())

    @property
    def discovery_active(self) -> bool:
        with self._lock:
            return self._discovery_active

    @property
    def port(self) -> int:
        with self._lock:
            if self._server:
                return int(self._server.server_port)
            return self._config.port

    def replace_config(self, **changes: object) -> AgentConfig:
        with self._lock:
            self._config = replace(self._config, **changes)
            return self._config

    def start(self) -> None:
        with self._lock:
            if self._server_thread and self._server_thread.is_alive():
                return
            config = self._config
            library = ProgramLibrary(Path(config.programs_dir))
            watcher = PollingWatcher(library)
            discovery = DiscoveryPublisher(config.name, config.port)
            server = create_server(config, library)
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.25},
                name="zeuzagent-http",
                daemon=True,
            )

            self._server = server
            self._server_thread = thread
            self._watcher = watcher
            self._discovery = discovery

            watcher.start()
            thread.start()
            try:
                self._discovery_active = bool(config.discovery and discovery.start())
            except Exception:  # noqa: BLE001 - mDNS must never prevent the API
                LOGGER.exception("No se pudo publicar Zeuz Agent por mDNS")
                self._discovery_active = False
            LOGGER.info(
                "%s activo en el puerto %s · carpeta: %s",
                config.name,
                server.server_port,
                config.programs_dir,
            )

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._server_thread
            watcher = self._watcher
            discovery = self._discovery
            self._server = None
            self._server_thread = None
            self._watcher = None
            self._discovery = None
            self._discovery_active = False

        if server:
            server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=3)
        if discovery:
            discovery.stop()
        if watcher:
            watcher.stop()
        if server or thread:
            LOGGER.info("Zeuz Agent detenido")

    def restart(self) -> None:
        self.stop()
        self.start()
