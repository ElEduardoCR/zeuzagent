"""Atomic document writes, encoding and per-line ending preservation."""
from __future__ import annotations

import difflib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Document:
    path: Path | None = None
    text: str = ""
    encoding: str = "utf-8"
    original: bytes = b""
    original_text: str = ""
    endings: tuple[str, ...] = ()
    modified_ns: int | None = None

    @classmethod
    def read(cls, path: Path) -> "Document":
        data = path.read_bytes()
        if b"\x00" in data[:4096] or data.startswith((b"%PDF-", b"PK\x03\x04", b"\x89PNG", b"\xff\xd8\xff", b"GIF89a")):
            raise ValueError("El archivo parece binario; selecciona un programa NC de texto.")
        encoding = "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8"
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            encoding = "latin-1"
            decoded = data.decode(encoding)
        endings = tuple(line[len(line.rstrip('\r\n')):] for line in decoded.splitlines(keepends=True))
        text = decoded.replace("\r\n", "\n").replace("\r", "\n")
        return cls(path.resolve(), text, encoding, data, text, endings, path.stat().st_mtime_ns)

    def encode(self, text: str) -> bytes:
        if text == self.original_text:
            return self.original
        previous = self.original_text.splitlines(keepends=True)
        current = text.splitlines(keepends=True)
        common = max(set(self.endings or ('\n',)), key=(self.endings or ('\n',)).count) or "\n"
        endings = [common if line.endswith("\n") else "" for line in current]
        for block in difflib.SequenceMatcher(a=previous, b=current, autojunk=len(previous) > 1000).get_matching_blocks():
            for offset in range(block.size):
                if block.a + offset < len(self.endings):
                    endings[block.b + offset] = self.endings[block.a + offset]
        decoded = "".join(line.rstrip("\n") + ending for line, ending in zip(current, endings))
        return decoded.encode(self.encoding, errors="strict")

    def save(self, text: str, path: Path | None = None, *, allow_external_change: bool = False) -> None:
        target = (path or self.path)
        if target is None:
            raise ValueError("Selecciona un destino para guardar.")
        target = target.resolve()
        if target == self.path and target.exists() and self.modified_ns is not None:
            # Some filesystems report coarse timestamps; a same-tick replacement
            # must not overwrite a program changed by CAM or another editor.
            changed = target.stat().st_mtime_ns != self.modified_ns
            if not changed:
                changed = target.read_bytes() != self.original
            if changed and not allow_external_change:
                raise ValueError("El archivo cambió fuera de ZEUZ Edit. Usa Guardar como para conservar ambas versiones.")
        payload = self.encode(text)
        descriptor, temporary = tempfile.mkstemp(prefix=".zeuzedit-", dir=target.parent)
        try:
            if target.exists() and hasattr(os, "fchmod"):
                os.fchmod(descriptor, target.stat().st_mode & 0o777)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        updated = self.read(target)
        self.__dict__.update(updated.__dict__)
