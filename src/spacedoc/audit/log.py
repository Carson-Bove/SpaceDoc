"""Append-only, hash-chained audit log (SR-08).

Each line is one JSON entry. An entry's hash covers its own content plus the previous
entry's hash, so editing, deleting or reordering any entry breaks the chain from that
point on. This detects tampering; it does not prevent it, so the log should also be
copied off the machine.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def _entry_hash(entry: dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _tail(self) -> tuple[int, str]:
        """Sequence number and hash of the last entry, or (0, GENESIS) for a new log."""
        if not self.path.exists():
            return 0, GENESIS
        last = None
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
        if last is None:
            return 0, GENESIS
        entry = json.loads(last)
        return int(entry["seq"]), str(entry["hash"])

    def append(self, event: str, payload: dict[str, Any]) -> str:
        """Add one entry and return its ID (e.g. "audit-000001")."""
        with self._lock:
            seq, prev_hash = self._tail()
            entry: dict[str, Any] = {
                "seq": seq + 1,
                "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "event": event,
                "payload": payload,
                "prev_hash": prev_hash,
            }
            # Round-trip through JSON so the hash is computed over exactly what is stored.
            entry = json.loads(json.dumps(entry, default=str))
            entry["hash"] = _entry_hash(entry)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            return f"audit-{entry['seq']:06d}"

    def verify(self) -> tuple[bool, int | None]:
        """Check the whole chain.

        Returns (True, None) if intact, otherwise (False, n) where n is the sequence number
        of the first entry that fails (or its line number if the entry cannot be parsed).
        """
        if not self.path.exists():
            return True, None
        prev_hash, prev_seq = GENESIS, 0
        with self.path.open(encoding="utf-8") as f:
            lines = [line for line in f if line.strip()]
        for lineno, line in enumerate(lines, start=1):
            try:
                entry = json.loads(line)
                seq = int(entry["seq"])
                stored = entry["hash"]
            except (ValueError, KeyError, TypeError):
                return False, lineno
            if (
                seq != prev_seq + 1
                or entry.get("prev_hash") != prev_hash
                or _entry_hash(entry) != stored
            ):
                return False, seq
            prev_hash, prev_seq = stored, seq
        return True, None
