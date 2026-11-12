"""Hash-chained audit log. Each entry stores the hash of the previous entry, so editing any past line breaks the chain."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone

GENESIS = "0" * 64
_lock = threading.Lock()


def _digest(prev_hash: str, body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def default_path() -> str:
    return os.environ.get("RISKDESK_AUDIT_PATH", os.path.join("data", "audit", "audit.jsonl"))


def _last_hash(path: str) -> str:
    if not os.path.exists(path):
        return GENESIS
    last = GENESIS
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last = json.loads(line)["hash"]
    return last


def append(event: str, payload: dict, actor: str = "riskdesk", path: str | None = None) -> dict:
    path = path or default_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with _lock:
        prev = _last_hash(path)
        body = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "actor": actor,
            "event": event,
            "payload": payload,
        }
        entry = {**body, "prev_hash": prev, "hash": _digest(prev, body)}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
    return entry


def verify(path: str | None = None) -> tuple[bool, int]:
    """Returns (ok, number of entries). ok is False at the first broken link or altered entry."""
    path = path or default_path()
    if not os.path.exists(path):
        return True, 0
    prev = GENESIS
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            body = {k: e[k] for k in ("ts", "actor", "event", "payload")}
            if e["prev_hash"] != prev or _digest(prev, body) != e["hash"]:
                return False, n
            prev = e["hash"]
            n += 1
    return True, n
