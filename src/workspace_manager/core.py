"""Shared service layer; registry is an index, Git remains authoritative."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import subprocess
import tempfile
import time
import tomllib
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Any


class Error(Exception):
    """An actionable user-facing failure."""


def run(args: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=30, check=False
        )
    except FileNotFoundError as exc:
        raise Error(f"Missing {args[0]}; install it (brew install / apt install).") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Error(str(exc)) from exc
    if result.returncode:
        raise Error(result.stderr.strip() or result.stdout.strip() or f"Failed: {args[0]}")
    return result.stdout.strip()


def shutil_available(name: str) -> bool:
    import shutil

    return shutil.which(name) is not None


def safe_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value) or value in {".", ".."}:
        raise Error("Name must use letters, digits, dot, dash or underscore (max 80).")
    return value


def no_symlinks(path: Path) -> Path:
    path = Path(os.path.abspath(path.expanduser()))
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise Error(f"Symlink path refused: {path}")
    return path


def atomic(path: Path, data: Any) -> None:
    atomic_text(path, json.dumps(data, indent=2))


def atomic_text(path: Path, text: str) -> None:
    no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".wm-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def toml_value(value: Any) -> str:
    """Encode parsed TOML values without executing strings or dropping unknown settings."""
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (date, datetime, datetime_time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(json.dumps(key) + " = " + toml_value(item) for key, item in value.items())
            + " }"
        )
    raise Error("Unsupported TOML value; configuration not saved")


@dataclass
class Config:
    work_root: Path = field(default_factory=lambda: Path.home() / "work")
    source_root: Path = field(default_factory=lambda: Path.home() / "workspace")
    state: Path = field(
        default_factory=lambda: (
            Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
            / "workspace-manager"
        )
    )

    default_agent: str = "shell"
    agent_args: dict[str, list[str]] = field(default_factory=dict)
    conflict_policy: str = "warn"

    @staticmethod
    def path() -> Path:
        return (
            Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
            / "workspace-manager/config.toml"
        )

    def validate(self) -> None:
        if self.default_agent not in {"shell", "claude", "codex"}:
            raise Error("Default agent must be shell, claude or codex")
        if self.conflict_policy not in {"warn", "block"}:
            raise Error("Conflict policy must be warn or block")
        for provider, arguments in self.agent_args.items():
            if provider not in {"shell", "claude", "codex"} or not isinstance(arguments, list):
                raise Error("Provider args must be an array of strings for shell/claude/codex")
            if any(not isinstance(arg, str) or "\0" in arg for arg in arguments):
                raise Error("Provider arguments must be strings without NUL")

    def save(self) -> None:
        """Persist supported settings atomically, retaining unrelated parsed TOML values."""
        self.validate()
        path = no_symlinks(self.path())
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = no_symlinks(path.with_suffix(".lock"))
        with lock_path.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            document = tomllib.loads(path.read_text()) if path.exists() else {}
            for name in ("work_root", "source_root", "state"):
                document[name] = str(getattr(self, name))
            document["default_agent"] = self.default_agent
            document["conflict_policy"] = self.conflict_policy
            agents = document.setdefault("agents", {})
            for name, arguments in self.agent_args.items():
                agents.setdefault(name, {})["args"] = arguments
            atomic_text(
                path,
                "\n".join(
                    json.dumps(key) + " = " + toml_value(value) for key, value in document.items()
                )
                + "\n",
            )

    @classmethod
    def load(cls) -> Config:
        path = cls.path()
        config = cls()
        if path.exists():
            with path.open("rb") as stream:
                values = tomllib.load(stream)
            for key in ("work_root", "source_root", "state"):
                if key in values:
                    setattr(config, key, Path(values[key]).expanduser())
            config.default_agent = values.get("default_agent", "shell")
            config.conflict_policy = values.get("conflict_policy", "warn")
            config.agent_args = {
                name: settings.get("args", [])
                for name, settings in values.get("agents", {}).items()
            }
        config.validate()
        return config


@dataclass
class Repo:
    name: str
    source: str
    branch: str | None = None
    ref: str = "HEAD"
    phase: str = "pending"


@dataclass
class Workspace:
    id: str
    name: str
    path: str
    activity: float
    phase: str = "creating"
    repos: list[Repo] = field(default_factory=list)
    schema_version: int = 1
    default_agent: str | None = None
    conflict_policy: str | None = None

    @classmethod
    def decode(cls, value: dict[str, Any]) -> Workspace:
        if value.get("schema_version") != 1:
            raise Error("Unsupported metadata schema")
        value = dict(value)
        if value.get("default_agent") not in {None, "shell", "claude", "codex"}:
            raise Error("Invalid workspace default agent")
        if value.get("conflict_policy") not in {None, "warn", "block"}:
            raise Error("Invalid workspace conflict policy")
        safe_name(value["name"])
        if not re.fullmatch(r"[0-9a-f]{32}", value["id"]):
            raise Error("Invalid workspace identity")
        path = Path(value["path"])
        if not path.is_absolute():
            raise Error("Workspace path must be absolute")
        for repo in value["repos"]:
            safe_name(repo["name"])
            if not Path(repo["source"]).is_absolute():
                raise Error("Repository source must be absolute")
        value["repos"] = [Repo(**r) for r in value["repos"]]
        return cls(**value)


class Git:
    @staticmethod
    def source(path: Path) -> Path:
        path = no_symlinks(path)
        root = Path(run(["git", "-C", str(path), "rev-parse", "--show-toplevel"]))
        if root != path:
            raise Error("Select the Git repository root")
        return path

    @staticmethod
    def command(source: Path, target: Path, branch: str | None, ref: str, new: bool) -> list[str]:
        Git.source(source)
        if ref.startswith("-") or not ref or "\x00" in ref:
            raise Error("Invalid ref")
        run(
            [
                "git",
                "-C",
                str(source),
                "rev-parse",
                "--verify",
                "--end-of-options",
                ref + "^{commit}",
            ]
        )
        args = ["git", "-C", str(source), "worktree", "add"]
        if branch:
            run(["git", "check-ref-format", "--branch", branch])
            if branch.startswith("-"):
                raise Error("Invalid branch")
            if not new:
                occupied = run(["git", "-C", str(source), "worktree", "list", "--porcelain"])
                if f"branch refs/heads/{branch}\n" in occupied + "\n":
                    raise Error(
                        "Branch already in a worktree; choose another or create a new branch."
                    )
                args += [str(target), branch]
            else:
                args += ["-b", branch, str(target), ref]
        else:
            args += ["--detach", str(target), ref]
        return args

    @staticmethod
    def status(path: Path) -> dict[str, str]:
        if not path.exists():
            return {"status": "missing", "branch": "?", "changes": ""}
        try:
            no_symlinks(path)
            if Path(run(["git", "-C", str(path), "rev-parse", "--show-toplevel"])) != path:
                raise Error("Path is not a repository root")
            changes = run(
                ["git", "-C", str(path), "status", "--porcelain=v1", "--untracked-files=all"]
            )
            branch = run(["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"])
            if branch == "HEAD":
                branch = "detached:" + run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"])
            return {
                "status": "modified" if changes else "clean",
                "branch": branch,
                "changes": changes,
            }
        except Error as exc:
            return {"status": "unknown", "branch": "?", "changes": str(exc)}


class Service:
    def __init__(self, config: Config | None = None):
        self.config = config or Config.load()
        self.state = no_symlinks(self.config.state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.registry = self.state / "registry.json"

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        path = no_symlinks(self.state / "lock")
        with path.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def index(self) -> dict[str, Any]:
        if not self.registry.exists():
            return {"schema_version": 1, "workspaces": {}}
        no_symlinks(self.registry)
        data = json.loads(self.registry.read_text())
        if data.get("schema_version") != 1:
            raise Error("Unsupported registry schema")
        return data

    def list(self) -> list[Workspace]:
        result = []
        for record in self.index()["workspaces"].values():
            workspace = Workspace.decode(record)
            try:
                workspace = self.read(workspace)
            except (Error, OSError, ValueError):
                workspace.phase = "missing" if not Path(workspace.path).exists() else "unknown"
            result.append(workspace)
        return sorted(result, key=lambda w: w.activity, reverse=True)

    def get(self, key: str) -> Workspace:
        matches = [w for w in self.list() if key in (w.id, w.name)]
        if len(matches) != 1:
            raise Error("Workspace not found or ambiguous; use its ID")
        if matches[0].phase in {"missing", "unknown"}:
            raise Error(f"Workspace is {matches[0].phase}")
        return matches[0]

    def read(self, workspace: Workspace) -> Workspace:
        path = no_symlinks(Path(workspace.path) / ".wm/workspace.json")
        current = Workspace.decode(json.loads(path.read_text()))
        if current.id != workspace.id or current.path != workspace.path:
            raise Error("Metadata identity mismatch")
        return current

    def save(self, workspace: Workspace) -> None:
        atomic(Path(workspace.path) / ".wm/workspace.json", asdict(workspace))
        data = self.index()
        data["workspaces"][workspace.id] = asdict(workspace)
        atomic(self.registry, data)

    def create(
        self, name: str, location: Path | None = None, first_repo: dict[str, Any] | None = None
    ) -> Workspace:
        safe_name(name)
        path = no_symlinks((location or self.config.work_root) / name)
        repo: Repo | None = None
        command: list[str] | None = None
        if first_repo is not None:
            repo_name = safe_name(first_repo["name"])
            if repo_name in {".wm", "CLAUDE.md", "AGENTS.md"}:
                raise Error("Reserved workspace filename")
            source = Git.source(first_repo["source"])
            repo = Repo(repo_name, str(source), first_repo["branch"], first_repo["ref"])
            command = Git.command(
                source, path / repo_name, repo.branch, repo.ref, first_repo["new"]
            )
        with self.lock():
            if any(w.name == name for w in self.list()):
                raise Error("Workspace name exists")
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                path.mkdir()
            except FileExistsError as exc:
                raise Error("Destination exists; refusing overwrite") from exc
            workspace = Workspace(uuid.uuid4().hex, name, str(path), time.time())
            if repo is not None:
                workspace.repos.append(repo)
            self.save(workspace)
            try:
                self.context(workspace)
                if command is not None:
                    run(command)
                if repo is not None:
                    repo.phase = "ready"
                workspace.phase = "ready"
                self.save(workspace)
            except (Error, OSError):
                workspace.phase = "incomplete"
                if repo is not None:
                    repo.phase = "failed"
                self.save(workspace)
                raise
            return workspace

    def context(self, workspace: Workspace) -> None:
        text = (
            f"# Workspace {workspace.name}\n\n"
            "Repositories are independent Git worktrees. Never reset, clean, force or delete branches.\n"
            "Read only relevant context. Before using a repo, explicitly read its AGENTS.md and\n"
            "CLAUDE.md if present; parent-directory launch does not load those automatically.\n"
            "Verify tool access permissions for each repository. New repositories may need approval.\n"
            "Current repository paths and sources are listed in .wm/workspace.json.\n"
            "Inspect actual Git status and branch; metadata is not authoritative.\n"
        )
        for filename in ("CLAUDE.md", "AGENTS.md"):
            path = no_symlinks(Path(workspace.path) / filename)
            try:
                with path.open("x") as stream:
                    stream.write(text)
            except FileExistsError:
                pass

    def add(
        self,
        key: str,
        source: Path,
        name: str,
        branch: str | None,
        ref: str = "HEAD",
        new: bool = True,
    ) -> Workspace:
        safe_name(name)
        source = Git.source(source)
        with self.lock():
            workspace = self.get(key)
            target = no_symlinks(Path(workspace.path) / name)
            if target.exists() or any(r.name == name for r in workspace.repos):
                raise Error("Repository destination exists")
            command = Git.command(source, target, branch, ref, new)
            repo = Repo(name, str(source), branch, ref)
            workspace.repos.append(repo)
            workspace.phase = "incomplete"
            self.save(workspace)  # journal intent before Git; recovery never guesses success
            try:
                run(command)
            except Error:
                repo.phase = "failed"
                self.save(workspace)
                raise
            repo.phase = "ready"
            workspace.phase = (
                "ready" if all(r.phase == "ready" for r in workspace.repos) else "incomplete"
            )
            workspace.activity = time.time()
            self.save(workspace)
            return workspace

    def status(self, key: str) -> dict[str, Any]:
        workspace = self.get(key)
        return {
            "workspace": asdict(workspace),
            "repos": {r.name: Git.status(Path(workspace.path) / r.name) for r in workspace.repos},
        }

    def remove(self, key: str, name: str, confirmed: bool = False) -> None:
        if not confirmed:
            raise Error("Removal requires explicit confirmation")
        from .terminal import Tmux

        with self.lock():
            workspace = self.get(key)
            with Tmux().lock(workspace):
                if not shutil_available("tmux"):
                    raise Error("Install tmux to verify no active terminals before removal")
                if Tmux().list(workspace):
                    raise Error(
                        "Active terminals: detach is not termination; close them explicitly first"
                    )
                repo = next((r for r in workspace.repos if r.name == name), None)
                if repo is None:
                    raise Error("Repository not found")
                target = no_symlinks(Path(workspace.path) / safe_name(name))
                if Git.status(target)["status"] != "clean":
                    raise Error("Only clean, present worktrees may be removed")
                ignored = run(
                    [
                        "git",
                        "-C",
                        str(target),
                        "ls-files",
                        "-z",
                        "--others",
                        "--ignored",
                        "--exclude-standard",
                    ]
                )
                if ignored:
                    raise Error("Ignored files are present; preserve or move them before removal")
                flags = run(["git", "-C", str(target), "ls-files", "-v", "-z"])
                if any(
                    entry and (entry[0].islower() or entry[0] == "S") for entry in flags.split("\0")
                ):
                    raise Error(
                        "Index has assume-unchanged/skip-worktree flags; audit these files manually"
                    )
                registered = run(["git", "-C", repo.source, "worktree", "list", "--porcelain"])
                if f"worktree {target}\n" not in registered + "\n":
                    raise Error("Worktree ownership cannot be verified")
                run(["git", "-C", repo.source, "worktree", "remove", str(target)])
                workspace.repos.remove(repo)
                self.save(workspace)

    def delete(self, key: str, confirmed: bool = False) -> None:
        if not confirmed:
            raise Error("Deletion requires explicit confirmation")
        workspace = self.get(key)
        if workspace.repos:
            raise Error(
                "Remove repositories individually after reviewing status, then delete workspace"
            )
        from .terminal import Tmux

        with self.lock():
            workspace = self.get(key)
            if workspace.repos:
                raise Error("Remove repositories individually first")
            if not shutil_available("tmux"):
                raise Error("Install tmux to verify no active terminals before removal")
            if Tmux().list(workspace):
                raise Error("Close active terminals first")
            root = no_symlinks(Path(workspace.path))
            allowed = {".wm", "CLAUDE.md", "AGENTS.md"}
            if any(p.name not in allowed for p in root.iterdir()):
                raise Error("Workspace contains additional files; preserve/move them manually")
            # Retain instructions and metadata: deletion unregisters, never destroys user files.
            data = self.index()
            del data["workspaces"][workspace.id]
            atomic(self.registry, data)

    def recover(self, path: Path) -> Workspace:
        """Explicitly re-index metadata after interrupted registry write; no Git mutation."""
        path = no_symlinks(path)
        raw = json.loads((path / ".wm/workspace.json").read_text())
        workspace = Workspace.decode(raw)
        if workspace.path != str(path):
            raise Error("Recovery path mismatch")
        with self.lock():
            data = self.index()
            if any(
                w["name"] == workspace.name and w["id"] != workspace.id
                for w in data["workspaces"].values()
            ):
                raise Error("Recovery name collision")
            self.save(workspace)
        return workspace

    def repair_repo(self, key: str, name: str, confirmed: bool = False) -> Workspace:
        """Reconcile an interrupted intent, preserving all existing files and branches."""
        if not confirmed:
            raise Error("Recovery requires confirmation")
        with self.lock():
            workspace = self.get(key)
            repo = next((r for r in workspace.repos if r.name == name), None)
            if repo is None or repo.phase == "ready":
                raise Error("Select a pending or failed repository")
            source = Git.source(Path(repo.source))
            target = no_symlinks(Path(workspace.path) / safe_name(name))
            registered = run(["git", "-C", str(source), "worktree", "list", "--porcelain"])
            owned = f"worktree {target}\n" in registered + "\n"
            if not target.exists() and not owned:
                workspace.repos.remove(repo)
            elif target.is_dir() and owned:
                state = Git.status(target)
                common = Path(
                    run(
                        [
                            "git",
                            "-C",
                            str(target),
                            "rev-parse",
                            "--path-format=absolute",
                            "--git-common-dir",
                        ]
                    )
                )
                expected = Path(
                    run(
                        [
                            "git",
                            "-C",
                            str(source),
                            "rev-parse",
                            "--path-format=absolute",
                            "--git-common-dir",
                        ]
                    )
                )
                if state["status"] not in {"clean", "modified"} or common != expected:
                    raise Error("Cannot verify interrupted worktree ownership")
                repo.phase = "ready"
            else:
                raise Error(
                    "Ambiguous interrupted operation; preserve files and inspect git worktree list"
                )
            workspace.phase = (
                "ready" if all(r.phase == "ready" for r in workspace.repos) else "incomplete"
            )
            self.save(workspace)
            return workspace

    def set_agent(self, key: str, provider: str | None, conflict_policy: str | None = None) -> None:
        if provider not in {None, "shell", "claude", "codex"}:
            raise Error("Choose shell, claude or codex (or inherit)")
        if conflict_policy not in {None, "warn", "block"}:
            raise Error("Choose warn or block")
        with self.lock():
            workspace = self.get(key)
            workspace.default_agent = provider
            workspace.conflict_policy = conflict_policy
            self.save(workspace)
