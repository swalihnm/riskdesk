"""Approval gate. Every investigation report and every limit-change proposal waits here for a named human.

Storage is a JSON file so the queue survives restarts. Every state change is written to the audit log.
Agents can create items and read them. Only `decide()` changes status, and it requires a reviewer name.
"""

from __future__ import annotations

import json
import os
import threading
import uuid

from riskdesk import audit
from riskdesk.guardrails.schemas import ApprovalItem


_LOCK = threading.RLock()  # the queue is a JSON file; concurrent graph runs share this process


def _load(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path: str, items: list[dict]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, default=str)


def submit(path: str, kind: str, desk: str, payload: dict, audit_path: str | None = None) -> ApprovalItem:
    item = ApprovalItem(id=uuid.uuid4().hex[:12], kind=kind, desk=desk, payload=payload)
    with _LOCK:
        items = _load(path)
        items.append(item.model_dump())
        _save(path, items)
    audit.append("approval.submitted", {"id": item.id, "kind": kind, "desk": desk}, path=audit_path)
    return item


def pending(path: str) -> list[dict]:
    return [i for i in _load(path) if i["status"] == "pending"]


from riskdesk.config import REVIEWERS_PATH  # noqa: E402


def allowed_reviewers(path: str = REVIEWERS_PATH) -> set[str] | None:
    """Named reviewers allowed to decide items. None means no allowlist file exists."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return set(json.load(f)["reviewers"])


def decide(path: str, item_id: str, reviewer: str, approve: bool, note: str = "",
           audit_path: str | None = None, reviewers_path: str = REVIEWERS_PATH) -> ApprovalItem:
    if not reviewer or reviewer.strip().lower() in {"agent", "system", "riskdesk", "assistant", "bot"}:
        raise PermissionError("A named human reviewer is required to decide an item")
    allow = allowed_reviewers(reviewers_path)
    if allow is not None and reviewer not in allow:
        raise PermissionError(f"'{reviewer}' is not on the reviewer allowlist ({reviewers_path})")
    with _LOCK:
        return _decide_locked(path, item_id, reviewer, approve, note, audit_path)


def _decide_locked(path, item_id, reviewer, approve, note, audit_path):
    items = _load(path)
    for it in items:
        if it["id"] == item_id:
            if it["status"] != "pending":
                raise ValueError(f"item {item_id} is already {it['status']}")
            it["status"] = "approved" if approve else "rejected"
            it["decided_by"] = reviewer
            it["note"] = note
            _save(path, items)
            audit.append("approval.decided", {"id": item_id, "status": it["status"], "reviewer": reviewer},
                         actor=reviewer, path=audit_path)
            return ApprovalItem(**it)
    raise KeyError(item_id)
