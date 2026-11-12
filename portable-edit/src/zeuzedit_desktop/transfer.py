"""Correlate legacy firmware status without treating stale idle as completion."""
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass
class TransferTracker:
    filename: str
    request_pending: bool = True
    acknowledged: bool = False
    observed: bool = False
    cancel_acknowledged: bool = False
    phase: str = "pending"

    @property
    def active(self):
        return self.request_pending or self.phase in {"pending", "sending", "unknown"}

    def accept_status(self, status: dict) -> str:
        phase = str(status.get("status", "idle"))
        filename = PurePosixPath(str(status.get("filename", "")).replace("\\", "/")).name
        matching = bool(self.filename) and filename == self.filename
        if phase == "sending" and matching:
            self.observed = True
            self.phase = "sending"
        elif not self.request_pending and phase in {"success", "error", "cancelled"} and matching and (self.acknowledged or self.observed):
            self.phase = phase
        elif not self.request_pending and self.cancel_acknowledged and self.observed and phase == "idle":
            self.phase = "cancelled"
        else:
            self.phase = "unknown"
        return self.phase
