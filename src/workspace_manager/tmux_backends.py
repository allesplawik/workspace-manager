"""Persistent workspace-to-socket associations. Registration grants no pane permissions."""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .core import Error, Workspace, atomic, no_symlinks, run


class Verification(StrEnum):
    CLEAR = "VERIFIED_NO_ACTIVE_SESSIONS"
    ACTIVE = "VERIFIED_ACTIVE_SESSIONS"
    INCOMPLETE = "VERIFICATION_INCOMPLETE"
    ERROR = "VERIFICATION_ERROR"


@dataclass(frozen=True)
class BackendCheck:
    state: Verification
    detail: str


def socket_directory() -> Path:
    return Path(os.environ.get("TMUX_TMPDIR") or "/tmp").resolve() / f"tmux-{os.getuid()}"


def socket_address(path: Path | None, name: str | None = None) -> Path:
    if name is not None:
        if path is not None or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in {".", ".."}:
            raise Error("Specify an absolute socket path or a valid tmux -L name")
        path = socket_directory() / name
    if path is None or not path.is_absolute() or ".." in path.parts or path.is_symlink():
        raise Error("An absolute, non-symlink tmux socket path is required")
    return path.resolve()


def ambient_socket() -> Path:
    inherited = os.environ.get("TMUX")
    return (
        socket_address(Path(inherited.rsplit(",", 2)[0]))
        if inherited
        else socket_address(None, "default")
    )


def server_identity(path: Path) -> str:
    try:
        before = path.lstat()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise Error(f"Backend socket unavailable: {path}") from exc
    if not stat.S_ISSOCK(before.st_mode) or before.st_uid != os.getuid():
        raise Error(f"Backend path is not a socket owned by this user: {path}")
    details = run(["tmux", "-S", str(path), "display-message", "-p", "#{pid}/#{start_time}"])
    after = path.lstat()
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise Error(f"Backend socket changed during verification: {path}")
    if not re.fullmatch(r"[1-9]\d*/[1-9]\d*", details):
        raise Error(f"Invalid tmux server identity: {path}")
    return f"{details}/{before.st_dev}/{before.st_ino}"


class BackendStore:
    def __init__(self, workspace: Workspace):
        self.path = no_symlinks(Path(workspace.path) / ".wm/terminal-backends.json")

    def initialize(self) -> None:
        atomic(self.path, {"schema_version": 1, "complete": True, "backends": []})

    def read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return {"schema_version": 1, "complete": False, "backends": []}
        except (OSError, ValueError) as exc:
            raise Error("Cannot read the workspace backend registry") from exc
        if (
            not isinstance(data, dict)
            or data.get("schema_version") != 1
            or type(data.get("complete")) is not bool
            or not isinstance(data.get("backends"), list)
            or not isinstance(data.get("retired", []), list)
        ):
            raise Error("Invalid or unsupported workspace backend registry")
        for record in data.get("retired", []):
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("socket"), str)
                or not Path(record["socket"]).is_absolute()
                or ".." in Path(record["socket"]).parts
            ):
                raise Error("Invalid retired workspace backend record")
        seen_ids, seen_paths = set(), set()
        for record in data["backends"]:
            if not isinstance(record, dict):
                raise Error("Invalid workspace backend record")
            key, raw, identity = (record.get(key) for key in ("id", "socket", "identity"))
            if (
                not isinstance(key, str)
                or not re.fullmatch(r"[0-9a-f]{32}", key)
                or not isinstance(raw, str)
                or not Path(raw).is_absolute()
                or ".." in Path(raw).parts
                or (
                    identity is not None
                    and (
                        not isinstance(identity, str)
                        or not re.fullmatch(r"\d+/\d+/\d+/\d+", identity)
                    )
                )
                or record.get("origin") not in ("wm", "explicit")
                or record.get("address") not in ("named", "path")
                or record.get("scope") != "observe"
                or not isinstance(record.get("previous_identities", []), list)
                or key in seen_ids
                or raw in seen_paths
            ):
                raise Error("Invalid or duplicate workspace backend record")
            seen_ids.add(key)
            seen_paths.add(raw)
        if data.get("preferred") is not None and (
            not isinstance(data["preferred"], str) or data["preferred"] not in seen_ids
        ):
            raise Error("Invalid preferred workspace backend")
        return data

    def upsert(
        self, path: Path, identity: str | None, source: str, name: str | None = None
    ) -> dict[str, Any]:
        # Callers hold the existing workspace terminal lock for read/modify/write.
        data = self.read()
        record = next((entry for entry in data["backends"] if entry["socket"] == str(path)), None)
        if record is None:
            record = {
                "id": uuid.uuid4().hex,
                "socket": str(path),
                "name": name,
                "address": "named" if name is not None else "path",
                "origin": source,
                "scope": "observe",
                "identity": identity,
            }
            data["backends"].append(record)
        elif record["identity"] is not None and record["identity"] != identity:
            raise Error(f"Registered tmux server identity changed: {path}")
        elif identity is not None:
            record["identity"] = identity
        atomic(self.path, data)
        return record

    def select(self, identifier: str) -> None:
        data = self.read()
        if not any(record["id"] == identifier for record in data["backends"]):
            raise Error("Unknown tmux backend ID")
        data["preferred"] = identifier
        atomic(self.path, data)

    def reset_instance(self, identifier: str, *, retire: bool = False) -> None:
        data = self.read()
        record = next(entry for entry in data["backends"] if entry["id"] == identifier)
        if retire:
            data["backends"].remove(record)
            data.setdefault("retired", []).append(record)
            if data.get("preferred") == identifier:
                data.pop("preferred")
        else:
            if record["identity"] is not None:
                record.setdefault("previous_identities", []).append(record["identity"])
            record["identity"] = None
        atomic(self.path, data)

    def complete_legacy(self) -> None:
        data = self.read()
        if not data["backends"]:
            raise Error("Register and verify the legacy socket inventory first")
        data["complete"] = True
        atomic(self.path, data)
