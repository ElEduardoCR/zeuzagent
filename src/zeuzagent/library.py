from __future__ import annotations

import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


IGNORED_NAMES = {"Thumbs.db", "desktop.ini"}
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_TRANSFER_BYTES = 128 * 1024 * 1024


class LibraryError(Exception):
    status = 400


class InvalidPath(LibraryError):
    pass


class NotFound(LibraryError):
    status = 404


class Conflict(LibraryError):
    status = 409


class UnsupportedFile(LibraryError):
    status = 415


def _ignored(name: str) -> bool:
    return name.startswith(".") or name in IGNORED_NAMES


def _looks_binary(data: bytes) -> bool:
    sample = data[:4096]
    if b"\x00" in sample:
        return True
    signatures = (
        b"%PDF-",
        b"PK\x03\x04",
        b"Rar!\x1a\x07",
        b"\x37\x7a\xbc\xaf\x27\x1c",
        b"\xff\xd8\xff",
        b"GIF87a",
        b"GIF89a",
    )
    return any(sample.startswith(signature) for signature in signatures)


def _valid_name(name: str) -> bool:
    return bool(
        name
        and name not in {".", ".."}
        and not name.startswith(".")
        and "/" not in name
        and "\\" not in name
    )


@dataclass
class ChangeTracker:
    version: int = 1

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

    def bump(self) -> int:
        with self._condition:
            self.version += 1
            self._condition.notify_all()
            return self.version

    def wait_for_change(self, since: int, timeout: float) -> int:
        timeout = max(0.0, min(timeout, 25.0))
        with self._condition:
            if self.version <= since:
                self._condition.wait(timeout)
            return self.version


class ProgramLibrary:
    def __init__(self, root: Path, tracker: ChangeTracker | None = None) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.tracker = tracker or ChangeTracker()

    def resolve(self, relative_path: str | None, *, must_exist: bool = False) -> Path:
        raw = (relative_path or "").strip().replace("\\", "/").lstrip("/")
        if any(part == ".." for part in Path(raw).parts):
            raise InvalidPath("La ruta no puede salir de la carpeta de programas")
        candidate = (self.root / raw).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise InvalidPath("La ruta no puede salir de la carpeta de programas") from exc
        if must_exist and not candidate.exists():
            raise NotFound("Programa o carpeta no encontrado")
        return candidate

    def relative(self, path: Path) -> str:
        value = path.relative_to(self.root).as_posix()
        return "" if value == "." else value

    def list(self, relative_path: str = "") -> dict:
        directory = self.resolve(relative_path, must_exist=True)
        if not directory.is_dir():
            raise NotFound("Carpeta no encontrada")
        entries: list[dict] = []
        try:
            children: Iterable[Path] = sorted(
                directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold())
            )
            for child in children:
                if _ignored(child.name):
                    continue
                resolved = child.resolve(strict=False)
                try:
                    resolved.relative_to(self.root)
                except ValueError:
                    continue
                stat = child.stat()
                entries.append(
                    {
                        "name": child.name,
                        "path": self.relative(child),
                        "kind": "directory" if child.is_dir() else "file",
                        "size": 0 if child.is_dir() else stat.st_size,
                        "modified": stat.st_mtime,
                    }
                )
        except OSError as exc:
            raise LibraryError(str(exc)) from exc
        current = self.relative(directory)
        parent = None if not current else Path(current).parent.as_posix()
        if parent == ".":
            parent = ""
        return {
            "path": current,
            "parent": parent,
            "entries": entries,
            "version": self.tracker.version,
        }

    def read(self, relative_path: str) -> dict:
        target = self.resolve(relative_path, must_exist=True)
        if not target.is_file():
            raise NotFound("Programa no encontrado")
        try:
            with target.open("rb") as handle:
                raw = handle.read(MAX_PREVIEW_BYTES + 1)
        except OSError as exc:
            raise LibraryError(str(exc)) from exc
        truncated = len(raw) > MAX_PREVIEW_BYTES
        raw = raw[:MAX_PREVIEW_BYTES]
        if _looks_binary(raw):
            raise UnsupportedFile("El archivo no es texto CNC compatible")
        stat = target.stat()
        return {
            "name": target.name,
            "path": self.relative(target),
            "content": raw.decode("latin-1"),
            "truncated": truncated,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "version": self.tracker.version,
        }

    def read_bytes(self, relative_path: str) -> tuple[str, bytes]:
        """Lee el archivo completo para transmitirlo sin truncar la vista previa."""
        target = self.resolve(relative_path, must_exist=True)
        if not target.is_file():
            raise NotFound("Programa no encontrado")
        try:
            size = target.stat().st_size
            if size > MAX_TRANSFER_BYTES:
                raise LibraryError("El programa excede el límite de transferencia de 128 MB")
            return target.name, target.read_bytes()
        except OSError as exc:
            raise LibraryError(str(exc)) from exc

    def write(self, relative_path: str, content: str, *, expected_modified: float | None = None) -> dict:
        target = self.resolve(relative_path)
        if target.exists() and target.is_dir():
            raise InvalidPath("La ruta pertenece a una carpeta")
        if not _valid_name(target.name):
            raise InvalidPath("Nombre de programa inválido")
        target.parent.mkdir(parents=True, exist_ok=True)
        if expected_modified is not None and target.exists():
            actual = target.stat().st_mtime
            if abs(actual - expected_modified) > 0.000001:
                raise Conflict("El programa cambió en otra computadora; vuelve a abrirlo")
        payload = content.encode("latin-1", errors="replace")
        try:
            descriptor, temp_name = tempfile.mkstemp(prefix=".zeuz-", dir=target.parent)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except OSError as exc:
            try:
                os.unlink(temp_name)
            except (OSError, UnboundLocalError):
                pass
            raise LibraryError(str(exc)) from exc
        version = self.tracker.bump()
        stat = target.stat()
        return {
            "ok": True,
            "path": self.relative(target),
            "modified": stat.st_mtime,
            "size": stat.st_size,
            "version": version,
        }

    def create(self, directory: str, name: str, *, kind: str = "file") -> dict:
        name = name.strip()
        if not _valid_name(name):
            raise InvalidPath("Nombre inválido")
        parent = self.resolve(directory, must_exist=True)
        if not parent.is_dir():
            raise InvalidPath("Carpeta inválida")
        target = self.resolve((Path(directory) / name).as_posix())
        if target.exists():
            raise Conflict("Ya existe un elemento con ese nombre")
        try:
            if kind == "directory":
                target.mkdir()
            elif kind == "file":
                target.touch(exist_ok=False)
            else:
                raise InvalidPath("Tipo de elemento inválido")
        except OSError as exc:
            raise LibraryError(str(exc)) from exc
        version = self.tracker.bump()
        return {"ok": True, "path": self.relative(target), "kind": kind, "version": version}

    def delete(self, relative_path: str) -> dict:
        target = self.resolve(relative_path, must_exist=True)
        if target == self.root:
            raise InvalidPath("No se puede eliminar la carpeta raíz")
        try:
            if target.is_dir():
                target.rmdir()
            else:
                target.unlink()
        except OSError as exc:
            raise Conflict("La carpeta debe estar vacía" if target.is_dir() else str(exc)) from exc
        return {"ok": True, "version": self.tracker.bump()}

    def search(self, query: str, limit: int = 250) -> list[dict]:
        needle = query.strip().casefold()
        if len(needle) < 2:
            return []
        results: list[dict] = []
        for path in self.root.rglob("*"):
            if len(results) >= limit:
                break
            if not path.is_file() or _ignored(path.name) or needle not in path.name.casefold():
                continue
            try:
                resolved = path.resolve()
                resolved.relative_to(self.root)
                stat = resolved.stat()
            except (OSError, ValueError):
                continue
            results.append(
                {
                    "name": path.name,
                    "path": self.relative(path),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )
        results.sort(key=lambda item: item["path"].casefold())
        return results


class PollingWatcher:
    """Detector portátil de cambios externos sin depender del sistema operativo."""

    def __init__(self, library: ProgramLibrary, interval: float = 1.5) -> None:
        self.library = library
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._signature = self._snapshot()

    def _snapshot(self) -> tuple:
        rows = []
        try:
            for path in self.library.root.rglob("*"):
                if _ignored(path.name):
                    continue
                stat = path.stat()
                rows.append((self.library.relative(path), path.is_dir(), stat.st_mtime_ns, stat.st_size))
        except OSError:
            pass
        return tuple(sorted(rows))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="zeuzagent-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            signature = self._snapshot()
            if signature != self._signature:
                self._signature = signature
                self.library.tracker.bump()
