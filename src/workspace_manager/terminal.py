"""tmux owns PTYs and process lifetime; no terminal emulation in Textual."""

from __future__ import annotations

import builtins
import contextlib
import fcntl
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from .core import Config, Error, Service, Workspace, no_symlinks, run
from .providers import provider


class Tmux:
    @staticmethod
    def session(workspace: Workspace) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}", workspace.id):
            raise Error("Invalid workspace ID")
        return "wm-" + workspace.id

    def exists(self, workspace: Workspace) -> bool:
        name = self.session(workspace)
        try:
            probe = subprocess.run(
                ["tmux", "has-session", "-t", "=" + name],
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
        owner = run(["tmux", "show-options", "-t", "=" + name + ":", "-v", "@wm_id"])
        if owner != workspace.id:
            raise Error("tmux namespace collision; foreign session left untouched")
        return True

    def list(self, workspace: Workspace) -> builtins.list[dict[str, str]]:
        if not shutil.which("tmux"):
            return []
        if not self.exists(workspace):
            return []
        output = run(
            [
                "tmux",
                "list-panes",
                "-s",
                "-t",
                "=" + self.session(workspace),
                "-F",
                "#{pane_id}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_dead}\t#{@wm_kind}\twm-end",
            ]
        )
        result = []
        for line in output.splitlines():
            fields = line.split("\t")
            if len(fields) != 6 or fields[-1] != "wm-end":
                raise Error("Cannot safely parse tmux panes")
            result.append(dict(zip(("pane", "command", "cwd", "dead", "kind"), fields[:5])))
        return result

    @contextlib.contextmanager
    def lock(self, workspace: Workspace) -> Iterator[None]:
        lock_path = no_symlinks(Path(workspace.path) / ".wm/tmux.lock")
        with lock_path.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def new(
        self,
        workspace: Workspace,
        cwd: Path | None = None,
        command: builtins.list[str] | None = None,
        kind: str = "shell",
        split: bool = False,
    ) -> str:
        with self.lock(workspace):
            return self._new(workspace, cwd, command, kind, split)

    def _new(
        self,
        workspace: Workspace,
        cwd: Path | None,
        command: builtins.list[str] | None,
        kind: str,
        split: bool,
    ) -> str:
        if not shutil.which("tmux"):
            raise Error("tmux missing. macOS: brew install tmux; Ubuntu: sudo apt install tmux")
        root = no_symlinks(Path(workspace.path))
        cwd = no_symlinks(cwd or root)
        if not cwd.is_relative_to(root) or not cwd.is_dir():
            raise Error("Terminal cwd must be an existing directory within workspace")
        exists = self.exists(workspace)
        if exists:
            operation = "split-window" if split else "new-window"
            args = [
                "tmux",
                operation,
                "-d",
                "-P",
                "-F",
                "#{pane_id}",
                "-t",
                "=" + self.session(workspace) + (":" if split else ""),
                "-c",
                str(cwd),
            ]
        else:
            args = [
                "tmux",
                "new-session",
                "-d",
                "-P",
                "-F",
                "#{pane_id}",
                "-s",
                self.session(workspace),
                "-c",
                str(cwd),
            ]
        if command:
            # tmux accepts one shell command; quote every argument, never interpolate raw input.
            args.append(shlex.join(command))
        pane = run(args)
        if not exists:
            run(
                [
                    "tmux",
                    "set-option",
                    "-t",
                    "=" + self.session(workspace) + ":",
                    "@wm_id",
                    workspace.id,
                ]
            )
        run(["tmux", "set-option", "-p", "-t", pane, "@wm_kind", kind])
        return pane

    def attach(self, workspace: Workspace, pane: str | None = None) -> None:
        if not self.exists(workspace):
            self.new(workspace)
        if pane:
            if pane not in {p["pane"] for p in self.list(workspace)}:
                raise Error("Pane does not belong to this workspace")
            run(["tmux", "select-pane", "-t", pane])
        args = [
            "tmux",
            "switch-client" if os.environ.get("TMUX") else "attach-session",
            "-t",
            pane or "=" + self.session(workspace),
        ]
        try:
            if pane and not os.environ.get("TMUX"):
                result = self._attach_pane(args, workspace, pane)
            else:
                result = subprocess.run(args, check=False)
        except OSError as exc:
            raise Error(str(exc)) from exc
        if result.returncode:
            raise Error("tmux attach failed; run wm terminal attach from an interactive terminal")

    def _attach_pane(
        self, args: builtins.list[str], workspace: Workspace, pane: str
    ) -> subprocess.CompletedProcess:
        # Watch only the client started here. Other attached clients and persistent
        # workspace processes must survive the selected pane exiting.
        with subprocess.Popen(args) as client:
            while True:
                try:
                    code = client.wait(timeout=0.25)
                    return subprocess.CompletedProcess(args, code)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    panes = self.list(workspace)
                    if any(p["pane"] == pane and p["dead"] == "0" for p in panes):
                        continue
                    clients = run(
                        [
                            "tmux",
                            "list-clients",
                            "-F",
                            "#{client_pid}\t#{client_name}\t#{session_name}",
                        ]
                    )
                    for row in clients.splitlines():
                        fields = row.split("\t")
                        if (
                            len(fields) == 3
                            and fields[0] == str(client.pid)
                            and fields[2] == self.session(workspace)
                        ):
                            run(["tmux", "detach-client", "-t", fields[1]])
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
        with tmux.lock(workspace):
            panes = tmux.list(workspace)
            if not fresh:
                for pane in panes:
                    if pane["kind"] == tool and pane["dead"] == "0" and pane["cwd"] == str(desired):
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
            return tmux._new(workspace, desired, command, tool, split)


def diagnostics() -> dict[str, Any]:
    return {
        "tools": {
            name: bool(shutil.which(name)) for name in ("git", "tmux", "uv", "claude", "codex")
        },
        "schema_version": 1,
    }
