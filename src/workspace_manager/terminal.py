"""tmux owns PTYs and process lifetime; no terminal emulation in Textual."""

from __future__ import annotations

import builtins
import contextlib
import fcntl
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .core import Config, Error, Service, Workspace, atomic, bounded_flock, no_symlinks, run
from .providers import provider
from .tmux_backends import (
    BackendCheck,
    BackendStore,
    Verification,
    ambient_socket,
    server_identity,
    socket_address,
    socket_directory,
)

BACKEND = ["tmux"]
PANE_IDENTITY = "#{pid}/#{session_created}/#{pane_pid}"
PANE_BIRTH = PANE_IDENTITY + "/#{session_id}/#{window_id}/#{pane_id}"


class Ownership(StrEnum):
    OWNED = "owned"
    MANAGED = "managed"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PaneOwnership:
    category: Ownership
    birth: str = ""
    identity: str = ""
    linked: bool = False


class Tmux:
    def __init__(self, socket: Path | None = None, identity: str | None = None):
        self.socket = socket
        self.server = identity
        self.last_created_identity: str | None = None
        self.args = [*BACKEND, "-S", str(socket)] if socket is not None else BACKEND

    @classmethod
    def registered(cls, entry: dict[str, Any]) -> Tmux:
        socket = Path(entry["socket"])
        identity = server_identity(socket)
        if entry["identity"] != identity:
            raise Error(f"Registered backend identity changed or is unverified: {socket}")
        return cls(socket, identity)

    def scoped(
        self,
        workspace: Workspace,
        pane: str | None = None,
        expected: str | None = None,
        *,
        backend: str | None = None,
    ) -> Tmux:
        if self.socket is not None:
            return self
        data = BackendStore(workspace).read()
        entries = data["backends"]
        if backend is not None:
            selected = [entry for entry in entries if entry["id"] == backend]
            if len(selected) != 1:
                raise Error("Unknown backend ID; run wm terminal backend-status")
            return self.registered(selected[0])
        if not entries:
            return self
        valid = []
        broken = []
        for entry in entries:
            try:
                candidate = self.registered(entry)
                if pane is None or (
                    candidate.exists(workspace)
                    and pane in {row["pane"] for row in candidate.list(workspace)}
                    and (expected is None or candidate.pane_identity(pane) == expected)
                ):
                    valid.append(candidate)
            except (Error, OSError) as exc:
                broken.append(exc)
        # An ID like %0 is local to one server. Never resolve it by list order.
        inherited = ambient_socket() if os.environ.get("TMUX") else None
        for candidate in valid:
            if inherited is not None and candidate.socket == inherited:
                return candidate
        if expected is None and data.get("preferred") is not None:
            preferred = next((entry for entry in entries if entry["id"] == data["preferred"]), None)
            if preferred is not None:
                chosen = self.registered(preferred)
                if pane is not None and not any(item.socket == chosen.socket for item in valid):
                    raise Error("Panel is not available on the selected backend")
                return chosen
        if len(valid) == 1 and (not broken or expected is not None):
            return valid[0]
        if not valid and broken:
            raise Error(str(broken[0]))
        if not valid:
            if expected is not None:
                raise Error("Terminal changed after confirmation or its backend is unavailable")
            raise Error("Panel is no longer available on a registered backend")
        raise Error("Multiple tmux backends match; select a backend ID explicitly")

    @staticmethod
    def register_backend(
        workspace: Workspace, path: Path | None, name: str | None = None, *, complete: bool = False
    ) -> dict[str, Any]:
        socket = socket_address(path, name)
        with Tmux().lock(workspace):
            workspace.require_registered()
            identity = server_identity(socket)
            store = BackendStore(workspace)
            record = store.upsert(socket, identity, "explicit", name)
            if complete:
                for entry in store.read()["backends"]:
                    Tmux.registered(entry)
                store.complete_legacy()
            return record

    def for_new(self, workspace: Workspace) -> Tmux:
        try:
            return self.scoped(workspace)
        except Error:
            if self.socket is not None:
                raise
            store = BackendStore(workspace)
            data = store.read()
            records = data["backends"]
            if len(records) != 1:
                raise
            record = records[0]
            socket = Path(record["socket"])
            if not self.socket_absent(socket) or not self.can_retire_missing(workspace, record):
                raise
            store.reset_instance(record["id"])
            return Tmux(socket)

    @staticmethod
    def socket_absent(socket: Path) -> bool:
        try:
            info = socket.lstat()
        except (FileNotFoundError, NotADirectoryError):
            return True
        except OSError:
            return False
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            return False
        try:
            server_identity(socket)
        except Error as exc:
            message = str(exc).lower()
            return message.startswith("no server running on ") or (
                message.startswith("error connecting to ")
                and message.endswith("(connection refused)")
            )
        return False

    def can_retire_missing(self, workspace: Workspace, record: dict[str, Any]) -> bool:
        if record["origin"] != "wm":
            return False
        identity = record["identity"]
        if identity is None or self.process_exists(int(identity.split("/")[0])):
            return False
        return not any(self.process_exists(pid) for pid in self.known_pids(workspace))

    def retire_backend(self, workspace: Workspace, identifier: str) -> None:
        with self.lock(workspace):
            workspace.require_registered()
            store = BackendStore(workspace)
            matches = [entry for entry in store.read()["backends"] if entry["id"] == identifier]
            if len(matches) != 1:
                raise Error("Unknown backend ID")
            record = matches[0]
            path = Path(record["socket"])
            if not self.socket_absent(path):
                backend = self.registered(record)
                if backend.list(workspace) or backend.workspace_processes(workspace):
                    raise Error("Backend still has workspace terminals")
                backend.verify_server()
            elif record["identity"] is None or not self.can_retire_missing(workspace, record):
                raise Error("Cannot prove the missing backend and its processes ended")
            # A registered legacy arbitrary socket remains significant even when empty
            # now; retirement is explicit evidence of removal from the scoped inventory.
            store.reset_instance(identifier, retire=True)

    def verify_server(self) -> None:
        if (
            self.server is not None
            and self.socket is not None
            and server_identity(self.socket) != self.server
        ):
            raise Error(f"Registered backend identity changed: {self.socket}")

    @staticmethod
    def session(workspace: Workspace) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}", workspace.id):
            raise Error("Invalid workspace ID")
        return "wm-" + workspace.id

    def exists(self, workspace: Workspace) -> bool:
        self.verify_server()
        name = self.session(workspace)
        try:
            probe = subprocess.run(
                [*self.args, "has-session", "-t", "=" + name],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Error(f"Cannot inspect tmux: {exc}") from exc
        if probe.returncode:
            message = probe.stderr.lower()
            if any(
                text in message
                for text in ("can't find session", "no server running", "no such file or directory")
            ):
                return False
            raise Error(f"Cannot inspect tmux: {probe.stderr.strip()}")
        # Option commands resolve a pane target: the colon makes =name an exact
        # session component instead of a literal session name containing "=".
        owner = run([*self.args, "show-options", "-t", "=" + name + ":", "-v", "@wm_id"])
        if owner != workspace.id:
            raise Error("tmux namespace collision; foreign session left untouched")
        return True

    def list(self, workspace: Workspace) -> builtins.list[dict[str, str]]:
        if not shutil.which("tmux"):
            return []
        try:
            selected = self.scoped(workspace)
            if selected is not self:
                return selected.list(workspace)
        except Error:
            if self.socket is None:
                entries = BackendStore(workspace).read()["backends"]
                if len(entries) == 1:
                    entry = entries[0]
                    if self.socket_absent(Path(entry["socket"])) and self.can_retire_missing(
                        workspace, entry
                    ):
                        # The final panel can shut down the server. This is an
                        # empty view; backend verification and metadata stay intact.
                        return []
            raise
        if not self.exists(workspace):
            return []
        output = run(
            [
                *self.args,
                "list-panes",
                "-s",
                "-t",
                "=" + self.session(workspace),
                "-F",
                "#{pane_id}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_dead}\t#{@wm_kind}\t#{@wm_name}\t#{pane_start_path}\t"
                + PANE_IDENTITY
                + "\twm-end",
            ]
        )
        result = []
        for line in output.splitlines():
            fields = line.split("\t")
            if len(fields) != 9 or fields[-1] != "wm-end":
                raise Error("Cannot safely parse tmux panes")
            result.append(
                dict(
                    zip(
                        ("pane", "command", "cwd", "dead", "kind", "name", "start", "identity"),
                        fields[:8],
                    )
                )
            )
        self.verify_server()
        return result

    @contextlib.contextmanager
    def lock(self, workspace: Workspace) -> Iterator[None]:
        lock_path = no_symlinks(Path(workspace.path) / ".wm/tmux.lock")
        with (
            lock_path.open("a") as stream,
            bounded_flock(stream, fcntl.LOCK_EX, "Workspace terminal operations are busy"),
        ):
            yield

    def new(
        self,
        workspace: Workspace,
        cwd: Path | None = None,
        command: builtins.list[str] | None = None,
        kind: str = "shell",
        split: bool = False,
    ) -> str:
        with self.lock(workspace):
            return self.for_new(workspace)._new(workspace, cwd, command, kind, split)

    def _new(
        self,
        workspace: Workspace,
        cwd: Path | None,
        command: builtins.list[str] | None,
        kind: str,
        split: bool,
    ) -> str:
        workspace.require_registered()
        if not shutil.which("tmux"):
            raise Error("tmux missing. macOS: brew install tmux; Ubuntu: sudo apt install tmux")
        root = no_symlinks(Path(workspace.path))
        cwd = no_symlinks(cwd or root)
        if not cwd.is_relative_to(root) or not cwd.is_dir():
            raise Error("Terminal cwd must be an existing directory within workspace")
        socket = self.socket or ambient_socket()
        store = BackendStore(workspace)
        exists = self.exists(workspace)
        if not any(entry["socket"] == str(socket) for entry in store.read()["backends"]):
            identity = None
            if socket.exists() or socket.is_symlink():
                try:
                    identity = server_identity(socket)
                except Error:
                    if not self.socket_absent(socket):
                        raise
                    # A stopped server can leave its socket behind. tmux
                    # replaces the inactive socket when starting a new server.
            store.upsert(socket, identity, "wm")
            if identity is not None and self.server is None:
                # Pin this operation, including a new session on an existing server.
                self.socket = socket
                self.server = identity
                self.args = [*BACKEND, "-S", str(socket)]
        name = self.session(workspace)
        format_line = "#{pane_id} " + PANE_BIRTH
        if exists:
            if split:
                target = run(
                    [*self.args, "display-message", "-p", "-t", "=" + name + ":", "#{pane_id}"]
                )
                state = self.inspect_pane(workspace, target)
                if state.category not in (Ownership.OWNED, Ownership.MANAGED):
                    raise Error("Cannot split an unverified or shared workspace window")
                args = ["split-window", "-t", target]
                predicate = self.pane_guard(workspace, state.birth)
            else:
                args = ["new-window", "-t", "=" + name]
                target = "=" + name + ":"
                predicate = "#{==:#{@wm_id}," + workspace.id + "}"
        else:
            args = ["new-session", "-s", name]
        args += ["-dP", "-F", format_line, "-c", str(cwd).replace("#", "##")]
        if command:
            args.append(shlex.join(command))
        if exists:
            output = self.guarded(target, predicate, args)
        elif self.server is not None:
            output = self.guarded(None, "1", args)
        else:
            output = run([*self.args, *args])
        pane, _, birth = output.partition(" ")
        if not re.fullmatch(r"%\d+", pane) or not birth:
            raise Error("Cannot verify the new terminal identity")
        if not exists:
            self.guarded(
                pane,
                "#{&&:#{==:#{session_name}," + name + "},#{==:" + PANE_BIRTH + "," + birth + "}}",
                ["set-option", "-t", pane, "@wm_id", workspace.id],
            )
        self.record_terminal(workspace, int(birth.split("/")[2]))
        store.upsert(socket, server_identity(socket), "wm")
        self.guarded(
            pane,
            self.pane_guard(workspace, birth),
            ["set-option", "-p", "-t", pane, "@wm_pane_owner", workspace.id + "/" + birth],
            ["set-option", "-p", "-t", pane, "@wm_kind", kind],
        )
        self.last_created_identity = "/".join(birth.split("/")[:3])
        return pane

    @staticmethod
    def known_pids(workspace: Workspace) -> set[int]:
        path = no_symlinks(Path(workspace.path) / ".wm/terminal-pids.json")
        if not path.exists():
            return set()
        try:
            values = json.loads(path.read_text())
            if not isinstance(values, list) or any(
                type(pid) is not int or not 0 < pid < 2**31 for pid in values
            ):
                raise ValueError
            return set(values)
        except (ValueError, OSError) as exc:
            raise Error("Workspace terminal state cannot be verified") from exc

    @staticmethod
    def process_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        try:
            state = run(["ps", "-p", str(pid), "-o", "stat="])
        except Error:
            return True
        return not state.startswith("Z")

    def record_terminal(self, workspace: Workspace, pid: int) -> None:
        live = {peer for peer in self.known_pids(workspace) if self.process_exists(peer)}
        path = no_symlinks(Path(workspace.path) / ".wm/terminal-pids.json")
        atomic(path, sorted(live | {pid}))

    def verify_terminals(self, workspace: Workspace) -> BackendCheck:
        try:
            data = BackendStore(workspace).read()
            paths = {Path(entry["socket"]): entry for entry in data["backends"]}
            candidates = set(paths)
            candidates.update(
                Path(entry["socket"])
                for entry in data.get("retired", [])
                if not self.socket_absent(Path(entry["socket"]))
            )
            directory = socket_directory()
            if directory.exists():
                candidates.update(
                    path
                    for path in no_symlinks(directory).iterdir()
                    if not path.is_symlink()
                    and path.is_socket()
                    and path.stat().st_uid == os.getuid()
                )
            ambient = ambient_socket()
            candidates.add(ambient)
            problems = []
            for path in sorted(candidates):
                try:
                    backend = self.registered(paths[path]) if path in paths else Tmux(path)
                    live = [
                        row["pane"] for row in backend.list(workspace) if row.get("dead") != "1"
                    ]
                    if not live and path.exists():
                        live = backend.workspace_processes(workspace)
                    backend.verify_server()
                    if live:
                        return BackendCheck(
                            Verification.ACTIVE, f"Active terminals on {path}: {', '.join(live)}"
                        )
                except (Error, OSError) as exc:
                    problems.append(f"{path}: {exc}")
            if any(self.process_exists(pid) for pid in self.known_pids(workspace)):
                return BackendCheck(
                    Verification.INCOMPLETE, "Recorded terminal processes may still be active"
                )
            if not data["complete"]:
                problems.append(
                    "Legacy backend inventory is incomplete; use wm terminal backend-register"
                )
            if problems:
                return BackendCheck(Verification.INCOMPLETE, "; ".join(problems))
            return BackendCheck(
                Verification.CLEAR, "No active terminals in the verified backend inventory"
            )
        except (Error, OSError) as exc:
            return BackendCheck(Verification.ERROR, str(exc))

    def workspace_processes(self, workspace: Workspace) -> builtins.list[str]:
        # External panes may also use a worktree even without the WM session marker.
        rows = run(
            [
                *self.args,
                "list-panes",
                "-a",
                "-F",
                "#{pane_id}\t#{pane_current_path}\t#{pane_start_path}\t#{pane_dead}\twm-end",
            ]
        )
        active = []
        root = Path(workspace.path)
        for line in rows.splitlines():
            fields = line.split("\t")
            if len(fields) != 5 or fields[-1] != "wm-end":
                raise Error("Cannot verify working directories on tmux backend")
            pane, cwd, start, dead, _ = fields
            if dead == "0" and any(
                path and Path(path).resolve().is_relative_to(root) for path in (cwd, start)
            ):
                active.append(pane)
        return active

    def require_no_terminals(self, workspace: Workspace) -> None:
        result = self.verify_terminals(workspace)
        if result.state != Verification.CLEAR:
            raise Error(f"{result.state}: {result.detail}")

    def has_terminals(self, workspace: Workspace) -> bool:
        return self.verify_terminals(workspace).state != Verification.CLEAR

    def inspect_pane(self, workspace: Workspace, pane: str) -> PaneOwnership:
        if not re.fullmatch(r"%\d+", pane):
            return PaneOwnership(Ownership.UNKNOWN)
        selected = self.scoped(workspace, pane)
        if selected is not self:
            return selected.inspect_pane(workspace, pane)
        name = self.session(workspace)
        fmt = (
            PANE_BIRTH + " #{session_name} #{window_linked_sessions_list} "
            "#{@wm_id} #{?@wm_pane_owner,#{@wm_pane_owner},-} #{?@wm_kind,#{@wm_kind},-} wm-end"
        )
        try:
            fields = run([*self.args, "display-message", "-p", "-t", pane, fmt]).split()
        except Error:
            return PaneOwnership(Ownership.UNKNOWN)
        if len(fields) < 3 or name not in fields[2].split(","):
            return PaneOwnership(Ownership.EXTERNAL if len(fields) >= 3 else Ownership.UNKNOWN)
        if fields[2] != name:
            return PaneOwnership(Ownership.EXTERNAL, linked=True)
        if len(fields) != 7 or fields[1] != name or fields[3] != workspace.id:
            return PaneOwnership(Ownership.UNKNOWN)
        birth, _, _, _, marker, kind, _ = fields
        if not re.fullmatch(r"\d+/\d+/\d+/\$\d+/@\d+/%\d+", birth):
            return PaneOwnership(Ownership.UNKNOWN)
        if marker == workspace.id + "/" + birth:
            category = Ownership.OWNED
        elif marker != "-":
            category = Ownership.UNKNOWN
        elif kind in {"shell", "codex", "claude"}:
            category = Ownership.MANAGED
        else:
            category = Ownership.EXTERNAL
        return PaneOwnership(category, birth, "/".join(birth.split("/")[:3]))

    def server_guard(self, predicate: str) -> str:
        if self.server is None:
            return predicate
        identity = "/".join(self.server.split("/")[:2])
        return "#{&&:" + predicate + ",#{==:#{pid}/#{start_time}," + identity + "}}"

    def guarded(self, target: str | None, predicate: str, *commands: builtins.list[str]) -> str:
        # Format checks and exact-target mutation share one server command queue.
        self.verify_server()
        predicate = self.server_guard(predicate)
        body = " ; ".join(shlex.join(command) for command in commands)
        output = run(
            [
                *self.args,
                "if-shell",
                "-F",
                *(["-t", target] if target is not None else []),
                predicate,
                body,
                "display-message -p wm-ownership-conflict",
            ]
        )
        if output == "wm-ownership-conflict":
            raise Error("Terminal is no longer private or its ownership changed")
        return output

    def pane_guard(self, workspace: Workspace, birth: str, *, owned: bool = False) -> str:
        base = (
            "#{&&:#{==:#{@wm_id}," + workspace.id + "},"
            "#{==:#{window_linked_sessions_list}," + self.session(workspace) + "}}"
        )
        current = "#{==:" + PANE_BIRTH + "," + birth + "}"
        if owned:
            current = (
                "#{&&:" + current + ",#{==:#{@wm_pane_owner}," + workspace.id + "/" + birth + "}}"
            )
        return "#{&&:" + base + "," + current + "}"

    def rename(
        self,
        workspace: Workspace,
        pane: str,
        name: str,
        *,
        expected: str | None = None,
    ) -> None:
        name = name.strip()
        if len(name) > 80 or (name and not name.isprintable()):
            raise Error("Use at most 80 printable characters for a terminal name")
        self.private_pane_command(
            workspace, pane, "set-option", "-p", "-t", pane, "@wm_name", name, expected=expected
        )

    def termination_identity(
        self,
        workspace: Workspace,
        pane: str,
        expected: str | None = None,
    ) -> str:
        state = self.scoped(workspace, pane, expected).inspect_pane(workspace, pane)
        if expected is not None and state.identity != expected:
            raise Error("Terminal changed after selection")
        if state.linked:
            raise Error("Terminal is no longer private to this workspace")
        if state.category == Ownership.MANAGED:
            raise Error("Legacy terminal. Exit it in its tab.")
        if state.category != Ownership.OWNED:
            raise Error("Panel is no longer available for termination: ownership is unverified")
        return state.birth

    def close(self, workspace: Workspace, pane: str, *, expected: str | None = None) -> None:
        with self.lock(workspace):
            identity = "/".join(expected.split("/")[:3]) if expected else None
            binding = self.scoped(workspace, pane, identity)
            birth = binding.termination_identity(workspace, pane)
            if expected is not None and expected != birth:
                raise Error("Terminal changed after confirmation")
            binding.guarded(
                pane, binding.pane_guard(workspace, birth, owned=True), ["kill-pane", "-t", pane]
            )

    def private_pane_command(
        self, workspace: Workspace, pane: str, *command: str, expected: str | None = None
    ) -> None:
        with self.lock(workspace):
            binding = self.scoped(workspace, pane, expected)
            state = binding.inspect_pane(workspace, pane)
            if expected is not None and state.identity != expected:
                raise Error("Terminal changed after selection")
            if state.linked:
                raise Error("Terminal is no longer private to this workspace")
            if state.category not in (Ownership.OWNED, Ownership.MANAGED):
                raise Error("Panel is no longer available in this workspace")
            binding.guarded(
                pane,
                binding.pane_guard(workspace, state.birth, owned=state.category == Ownership.OWNED),
                list(command),
            )

    @staticmethod
    def client_guard(tty: str, pid: str, session_id: str) -> str:
        if (
            not re.fullmatch(r"/dev/[A-Za-z0-9/_-]+", tty)
            or not pid.isdecimal()
            or not re.fullmatch(r"\$\d+", session_id)
        ):
            raise Error("Cannot verify tmux client identity")
        pid_check = "#{==:#{client_pid}," + pid + "}"
        tty_check = "#{==:#{client_tty}," + tty + "}"
        session_check = "#{==:#{session_id}," + session_id + "}"
        return "#{L:#{?#{&&:" + pid_check + ",#{&&:" + tty_check + "," + session_check + "}},1,}}"

    def select_viewer(
        self,
        workspace: Workspace,
        pane: str,
        identity: str,
        tty: str,
        pid: str,
        session_id: str,
    ) -> None:
        with self.lock(workspace):
            state = self.inspect_pane(workspace, pane)
            if (
                state.category not in (Ownership.OWNED, Ownership.MANAGED)
                or state.identity != identity
            ):
                raise Error("The terminal changed before it could be selected")
            guard = self.pane_guard(workspace, state.birth, owned=state.category == Ownership.OWNED)
            self.guarded(
                pane,
                "#{&&:"
                + guard
                + ",#{&&:#{==:#{session_attached},1},"
                + self.client_guard(tty, pid, session_id)
                + "}}",
                ["switch-client", "-c", tty, "-t", pane],
            )

    def invoking_client(self) -> tuple[str, str, str]:
        socket = os.environ["TMUX"].split(",", 1)[0]
        active_socket = run([*self.args, "display-message", "-p", "#{socket_path}"])
        if Path(socket).resolve() != Path(active_socket).resolve():
            raise Error("Invoking client belongs to another tmux socket")
        pane = os.environ.get("TMUX_PANE", "")
        rows = run(
            [
                *self.args,
                "list-clients",
                "-F",
                "#{client_tty} #{client_pid} #{session_id} #{pane_id}",
            ]
        ).splitlines()
        matches = [fields for row in rows if len(fields := row.split()) == 4 and fields[3] == pane]
        if len(matches) != 1:
            raise Error("Cannot identify a unique invoking tmux client")
        tty, pid, session_id, _ = matches[0]
        return tty, pid, session_id

    def attached_clients(self, workspace: Workspace) -> str:
        return run(
            [*self.args, "list-clients", "-t", "=" + self.session(workspace), "-F", "#{client_pid}"]
        )

    def pane_identity(self, pane: str) -> str:
        return run(
            [
                *self.args,
                "display-message",
                "-p",
                "-t",
                pane,
                "#{pid}/#{session_created}/#{pane_pid}",
            ]
        )

    def attach(
        self,
        workspace: Workspace,
        pane: str | None = None,
        *,
        create: bool = True,
        exclusive: bool = False,
        expected_identity: str | None = None,
        view_target: Callable[[], AbstractContextManager[str]] | None = None,
    ) -> None:
        selected = self.scoped(workspace, pane, expected_identity)
        if selected is not self:
            selected.attach(
                workspace,
                pane,
                create=create,
                exclusive=exclusive,
                expected_identity=expected_identity,
                view_target=view_target,
            )
            return
        # Workspace clients share tmux's selected window. An embedded viewer
        # must not compete with a classic WM client for that selection.
        path = no_symlinks(Path(workspace.path) / ".wm/view.lock")
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        with (
            path.open("a") as lock,
            bounded_flock(
                lock,
                mode,
                "This workspace is already in use by a terminal viewer",
                2 if exclusive else 0,
            ),
        ):
            if expected_identity is not None and (
                pane is None or self.pane_identity(pane) != expected_identity
            ):
                raise Error("This tab refers to a previous terminal")
            self._attach(
                workspace,
                pane,
                create=create,
                exclusive=exclusive,
                expected_identity=expected_identity,
                view_target=view_target,
            )

    def _attach(
        self,
        workspace: Workspace,
        pane: str | None,
        *,
        create: bool,
        exclusive: bool,
        expected_identity: str | None = None,
        view_target: Callable[[], AbstractContextManager[str]] | None = None,
    ) -> None:
        if not self.exists(workspace):
            if not create or pane is not None:
                raise Error("Workspace terminal is no longer available")
            self.new(workspace)
        with self.lock(workspace):
            workspace.require_registered()
            if (
                (exclusive or pane is not None)
                and not os.environ.get("TMUX")
                and self.attached_clients(workspace)
            ):
                raise Error("This workspace already has an attached tmux client")
            anchor = "=" + self.session(workspace) + ":"
            target = pane or "=" + self.session(workspace)
            guard = "#{==:#{@wm_id}," + workspace.id + "}"
            if pane:
                state = self.inspect_pane(workspace, pane)
                if state.category not in (Ownership.OWNED, Ownership.MANAGED):
                    raise Error("Pane does not belong to this workspace or is unverified")
                if expected_identity is not None and expected_identity != state.identity:
                    raise Error("This tab refers to a previous terminal")
                guard = self.pane_guard(
                    workspace, state.birth, owned=state.category == Ownership.OWNED
                )
                anchor = pane
            if pane or exclusive or os.environ.get("TMUX"):
                guard = "#{&&:" + guard + ",#{==:#{session_attached},0}}"
            if os.environ.get("TMUX"):
                tty, pid, session_id = self.invoking_client()
                self.guarded(
                    anchor,
                    "#{&&:" + guard + "," + self.client_guard(tty, pid, session_id) + "}",
                    ["switch-client", "-c", tty, "-t", target],
                )
                return
        args = [
            *self.args,
            "if-shell",
            "-F",
            "-t",
            anchor,
            self.server_guard(guard),
            shlex.join(["attach-session", "-t", target]),
            # A failing read-only tmux command returns failure to the caller.
            # run-shell errors can instead enter copy mode in another client.
            (
                "display-message -p 'Terminal ownership or client availability changed'; "
                "show-options -v wm-attach-refused"
            ),
        ]
        try:
            if pane and not os.environ.get("TMUX"):
                result = self._attach_pane(
                    args, workspace, pane, exclusive=exclusive, view_target=view_target
                )
            else:
                result = subprocess.run(args, check=False)
        except OSError as exc:
            raise Error(str(exc)) from exc
        if result.returncode:
            raise Error("tmux attach failed; run wm terminal attach from an interactive terminal")

    def _attach_pane(
        self,
        args: builtins.list[str],
        workspace: Workspace,
        pane: str,
        *,
        exclusive: bool = False,
        view_target: Callable[[], AbstractContextManager[str]] | None = None,
    ) -> subprocess.CompletedProcess:
        # Watch only the client started here. Other attached clients and persistent
        # workspace processes must survive the selected pane exiting.
        with subprocess.Popen(args) as client:
            released = False
            while True:
                try:
                    code = client.wait(timeout=0.25)
                    return subprocess.CompletedProcess(args, 0 if released else code)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    with view_target() if view_target else contextlib.nullcontext(pane) as target:
                        panes = self.list(workspace)
                        alive = any(p["pane"] == target and p["dead"] == "0" for p in panes)
                        if alive and not exclusive:
                            continue
                        clients = run(
                            [
                                *self.args,
                                "list-clients",
                                "-t",
                                "=" + self.session(workspace),
                                "-F",
                                "#{client_pid}\t#{client_name}\t#{pane_id}",
                            ]
                        )
                        rows = [row.split("\t") for row in clients.splitlines()]
                        for fields in rows:
                            if (
                                len(fields) == 3
                                and fields[0] == str(client.pid)
                                and (not alive or fields[2] != target or len(rows) != 1)
                            ):
                                client.terminate()
                                released = True
                                break
                except Error:
                    # Session/server shutdown also ends attach-session naturally.
                    # Transient inspection failures must not kill other processes.
                    continue


class AI:
    """Session orchestration shared by CLI/TUI; providers own CLI-specific semantics."""

    def __init__(
        self, config: Config | None = None, on_warning: Callable[[str], None] | None = None
    ):
        self.on_warning = on_warning
        self.config = config or Config.load()
        self.config.validate()
        self.last_warnings: builtins.list[str] = []
        self.last_identity: str | None = None

    def command(self, tool: str, mode: str) -> builtins.list[str]:
        return provider(tool).command(mode, self.config.agent_args.get(tool, []))

    def launch(
        self,
        workspace: Workspace,
        tool: str | None = None,
        mode: str = "new",
        cwd: Path | None = None,
        fresh: bool = False,
        split: bool = False,
        extra_args: builtins.list[str] | None = None,
        session_id: str | None = None,
        *,
        verify_history_location: bool = False,
    ) -> str:
        tool = tool or workspace.default_agent or self.config.default_agent
        selected = provider(tool)
        if session_id is not None:
            from .codex_history import conversation_id

            if tool != "codex" or mode != "resume":
                raise Error("A conversation ID requires Codex resume mode")
            session_id = conversation_id(session_id)
            fresh = True
        tmux = Tmux()
        desired = no_symlinks(cwd or Path(workspace.path))
        root = no_symlinks(Path(workspace.path))
        if not desired.is_dir() or not desired.is_relative_to(root):
            raise Error("Terminal cwd must be within workspace")
        self.last_warnings = []
        self.last_identity = None
        with tmux.lock(workspace):
            workspace.require_registered()
            if verify_history_location:
                current = Service(self.config).read(workspace)
                if desired != root and not any(
                    repo.phase == "ready" and root / repo.name == desired and repo in current.repos
                    for repo in workspace.repos
                ):
                    raise Error("Conversation location changed; reopen history and select it again")
            tmux = tmux.for_new(workspace)
            panes = tmux.list(workspace)
            if not fresh:
                for pane in panes:
                    if pane["kind"] == tool and pane["dead"] == "0" and pane["cwd"] == str(desired):
                        self.last_identity = pane.get("identity")
                        return pane["pane"]
            if selected.is_agent:
                # Agents can access sibling repos even when cwd differs: warn for the
                # whole shared workspace, rather than falsely infer file isolation.
                conflicts = [
                    pane
                    for pane in panes
                    if pane["dead"] == "0" and pane["kind"] in {"claude", "codex"}
                ]
                if conflicts:
                    message = (
                        "Concurrent AI sessions may modify the same files: "
                        + ", ".join(p["kind"] + " " + p["pane"] for p in conflicts)
                        + ". Coordinate changes or use separate worktrees."
                    )
                    if (workspace.conflict_policy or self.config.conflict_policy) == "block":
                        raise Error(message + " Blocked by configured conflict_policy.")
                    self.last_warnings.append(message)
                    if self.on_warning is not None:
                        self.on_warning(message)
            arguments = [*self.config.agent_args.get(tool, []), *(extra_args or [])]
            command = selected.command(mode, arguments)
            if session_id is not None:
                command.append(session_id)
            Service(self.config).context(workspace)
            pane_id = tmux._new(workspace, desired, command, tool, split)
            self.last_identity = tmux.last_created_identity
            return pane_id


def diagnostics() -> dict[str, Any]:
    return {
        "tools": {
            name: bool(shutil.which(name)) for name in ("git", "tmux", "uv", "claude", "codex")
        },
        "schema_version": 1,
    }
