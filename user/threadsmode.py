"""Per-room "threads mode" switch, persisted per agent account.

One small JSON file next to the poll state (``threads-mode-<acct>.json`` under
``<hermes home>/nctalk``, or ``NEXTCLOUD_TALK_STATE_DIR``). The account hash is
the same ``server|user`` hash the poll state uses, so two profiles on a
multiplexed gateway (different Talk accounts) never share a file. A stored
``false`` is an explicit OFF that beats the ``NEXTCLOUD_TALK_THREADS_MODE_ROOMS``
seed. Stdlib only.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

STATE_DIR_ENV = "NEXTCLOUD_TALK_STATE_DIR"


def hermes_home() -> str:
    """The profile's Hermes home, resolved through Hermes when it is importable.

    Call this while the adapter is being built (the profile scope is bound
    then), not per message.
    """
    try:
        from hermes_constants import get_hermes_home

        return str(get_hermes_home())
    except Exception:
        return os.getenv("HERMES_HOME", "").strip() or os.path.expanduser("~/.hermes")


def state_path(server: str, user: str, home: Optional[str] = None) -> Path:
    base = os.getenv(STATE_DIR_ENV, "").strip()
    if not base:
        base = os.path.join(home or hermes_home(), "nctalk")
    acct = hashlib.sha256(f"{server.rstrip('/')}|{user.lower()}".encode()).hexdigest()[:12]
    return Path(base) / f"threads-mode-{acct}.json"


def parse_rooms(raw: Any) -> frozenset:
    """``"tok1,tok2"`` (or a list) to a set of room tokens."""
    if isinstance(raw, (list, tuple, set, frozenset)):
        items = raw
    else:
        items = str(raw or "").split(",")
    return frozenset(str(s).strip() for s in items if str(s).strip())


def load(path: Path) -> Dict[str, bool]:
    try:
        data = json.loads(Path(path).read_text() or "{}")
    except (OSError, ValueError):
        return {}
    rooms = data.get("rooms") if isinstance(data, dict) else None
    if not isinstance(rooms, dict):
        return {}
    return {str(k): bool(v) for k, v in rooms.items()}


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def set_room(path: Path, token: str, on: bool) -> None:
    """Record the room's switch (read-modify-write under a lock, atomic replace)."""
    path = Path(path)
    with _locked(path):
        rooms = load(path)
        rooms[token] = bool(on)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"rooms": rooms}, indent=1))
        os.replace(tmp, path)
