"""Private tmux display for the dashboard and native workspace clients."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import pwd
import re
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from .core import Config, Error, Service, Workspace, bounded_flock, run
from .session_tabs import session_display_name, tab_status, tab_token
from .terminal import BACKEND, Ownership, Tmux
from .tmux_backends import BackendStore

MODULE = "workspace_manager.split"
SESSION = "wm-display"
TARGET = "=" + SESSION
WINDOW = TARGET + ":workspace"
MIN_LEFT, MAX_LEFT, MIN_RIGHT = 28, 50, 40
ATTACH_TIMEOUT = 2


class Display:
    def __init__(self, root: Path):
        self.root = root
        self.socket = root / "display.sock"
        self.args = ["tmux", "-S", str(self.socket)]

    @classmethod
    def configured(cls, config: Config) -> Display:
        identity = f"{config.state.resolve()}\0{os.environ.get('TMUX_TMPDIR', '')}"
        key = hashlib.sha256(identity.encode()).hexdigest()[:16]
        return cls(Path("/tmp").resolve() / f"wm-display-{os.getuid()}-{key}")

    def tmux(self, *args: str) -> str:
        return run([*self.args, *args])

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        self.root.mkdir(mode=0o700, exist_ok=True)
        info = self.root.lstat()
        if self.root.is_symlink() or not self.root.is_dir() or info.st_uid != os.getuid():
            raise Error("Display directory is not owned by the current user")
        if info.st_mode & 0o077:
            raise Error("Display directory must be private")
        if self.socket.is_symlink() or (self.socket.exists() and not self.socket.is_socket()):
            raise Error("Invalid display socket")
        flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
        with (
            os.fdopen(os.open(self.root / "lock", flags, 0o600), "w") as lock,
            bounded_flock(lock, fcntl.LOCK_EX, "Terminal display is busy"),
        ):
            yield

    def get(self, key: str) -> str:
        return self.tmux("show-options", "-qv", "-t", TARGET + ":", "@wm_display_" + key)

    def set(self, key: str, value: str) -> None:
        self.tmux("set-option", "-t", TARGET + ":", "@wm_display_" + key, value)

    def check_owner(self) -> None:
        marker = self.root / "owner"
        if marker.is_symlink() or not marker.is_file():
            raise Error("Missing display owner marker")
        nonce = marker.read_text().strip()
        if not re.fullmatch(r"[a-f0-9]{32}", nonce) or self.get("owner") != nonce:
            raise Error("The display session has a different owner")

    @staticmethod
    def package_root() -> str:
        return str(Path(__file__).resolve().parents[1])

    def command(self, *args: str) -> list[str]:
        return [
            "env",
            f"PYTHONPATH={self.package_root()}",
            sys.executable,
            "-m",
            MODULE,
            str(self.root),
            *args,
        ]

    def prepare(self) -> None:
        self.shortcut_keys()
        with self.lock():
            # A stale Unix socket is normal after a server exits. A live server
            # without our exact session/marker is never adopted.
            if self.socket.exists():
                probe = subprocess.run(
                    [*self.args, "list-sessions"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if probe.returncode == 0:
                    self.check_owner()
                    self.bindings()
                    self.initialize_tabs()
                    self.repair()
                    return
                if not any(
                    message in probe.stderr
                    for message in ("no server running", "Connection refused")
                ):
                    raise Error(probe.stderr.strip())
            marker = self.root / "owner"
            if marker.is_symlink() or (marker.exists() and not marker.is_file()):
                raise Error("Invalid display owner marker")
            nonce = secrets.token_hex(16)
            marker.write_text(nonce + "\n")
            sidebar = self.tmux(
                "-f",
                "/dev/null",
                "new-session",
                "-dP",
                "-F",
                "#{pane_id}",
                "-s",
                SESSION,
                "-n",
                "workspace",
                "-x",
                "110",
                "-y",
                "36",
                *self.command("sidebar"),
            )
            try:
                self.set("owner", nonce)
                self.set("sidebar", sidebar)
                self.set("hidden", "0")
                self.set("preferred", "36")
                self.tmux("set-option", "-g", "mouse", "on")

                self.tmux("set-option", "-gw", "remain-on-exit", "on")
                self.tmux("set-option", "-gw", "window-size", "latest")
                home = self.tmux(
                    "split-window",
                    "-hdP",
                    "-F",
                    "#{pane_id}",
                    "-t",
                    sidebar,
                    "-c",
                    str(Path.home()).replace("#", "##"),
                    *self.command("home-shell"),
                )
                self.set("home", home)
                self.set("active", home)
                self.bindings()
                self.initialize_tabs()
                self.tmux("select-pane", "-t", home)
                self.reflow()
            except BaseException:
                with contextlib.suppress(Error):
                    self.check_owner()
                    self.tmux(
                        "if-shell",
                        "-F",
                        "-t",
                        sidebar,
                        "#{==:#{@wm_display_owner}," + nonce + "}",
                        "kill-session -t " + TARGET,
                    )
                raise

    @staticmethod
    def shortcut_keys() -> dict[str, str]:
        keys = {
            action: os.environ.get(f"WM_SPLIT_{setting}_KEY", default)
            for action, setting, default in (
                ("focus", "FOCUS", "f"),
                ("toggle", "TOGGLE", "z"),
                ("narrower", "NARROWER", "Left"),
                ("wider", "WIDER", "Right"),
                ("home", "HOME", "h"),
            )
        }
        if not all(
            re.fullmatch(r"[a-zA-Z0-9]|F(?:[1-9]|1[0-2])|Left|Right|Up|Down", key)
            for key in keys.values()
        ):
            raise Error("Invalid split shortcut: use a letter, digit, arrow or F1–F12")
        if len(set(keys.values())) != len(keys) or "d" in keys.values():
            raise Error("Split shortcuts must be unique; d is reserved for detach")
        return keys

    def bindings(self) -> None:
        keys = self.shortcut_keys()
        self.tmux("set-option", "-s", "focus-events", "on")
        self.tmux("unbind-key", "-a", "-T", "prefix")
        self.tmux("bind-key", "C-b", "send-prefix")
        self.tmux("bind-key", "d", "detach-client")
        self.tmux("set-option", "-t", TARGET + ":", "status", "on")
        self.tmux("set-option", "-t", TARGET + ":", "status-position", "top")
        self.tmux("set-option", "-t", TARGET + ":", "status-style", "bg=#0d1117,fg=#8b949e")

        for key, value in zip(
            ("PYTHON", "PYTHONPATH", "MODULE", "ROOT"),
            (sys.executable, self.package_root(), MODULE, str(self.root)),
        ):
            self.tmux("set-environment", "-g", "WM_DISPLAY_" + key, value)
        cmd = (
            'exec env PYTHONPATH="$WM_DISPLAY_PYTHONPATH" '
            '"$WM_DISPLAY_PYTHON" -m "$WM_DISPLAY_MODULE" "$WM_DISPLAY_ROOT"'
        )
        for action, key in keys.items():
            self.tmux("bind-key", key, "run-shell", "-b", f"{cmd} {action}")
        self.tmux(
            "bind-key",
            "-T",
            "root",
            "MouseDragEnd1Border",
            "run-shell",
            "-b",
            f"{cmd} save-width",
        )
        for button, verb in (("MouseDown1Status", "tab-"), ("MouseDown2Status", "tab-remove-")):
            self.tmux(
                "bind-key",
                "-T",
                "root",
                button,
                "run-shell",
                f"{cmd} {verb}#{{mouse_status_range}}",
            )
        for key, action in {"n": "next", "p": "previous", "x": "close", "+": "new"}.items():
            if key not in keys.values():
                self.tmux("bind-key", key, "run-shell", f"{cmd} tab-{action}")
        self.tmux("set-hook", "-t", SESSION, "client-resized", f"run-shell -b '{cmd} reflow'")

    def initialize_tabs(self) -> None:
        if self.get("tabs_initialized") == "1":
            return
        tabs = self.tabs()
        backend = Tmux()
        for workspace in Service().list():
            try:
                binding = backend.scoped(workspace)
                peers = binding.list(workspace)
                for row in peers:
                    if row["dead"] == "0":
                        pane = row["pane"]
                        key = f"{workspace.id}/{pane}"
                        if key not in tabs:
                            tabs[key] = (binding.pane_identity(pane), session_display_name(row))
            except (Error, OSError):
                continue
        self.save_tabs(tabs)
        self.set("tabs_initialized", "1")

    def tabs(self) -> dict[str, tuple[str, str]]:
        return {
            key: (identity, title) for key, identity, title in json.loads(self.get("tabs") or "[]")
        }

    def save_tabs(self, tabs: dict[str, tuple[str, str]]) -> None:
        self.set("tabs", json.dumps([(key, *value) for key, value in tabs.items()]))

    @staticmethod
    def identity(pane: str) -> str:
        return Tmux().pane_identity(pane)

    def live_tabs(self, tabs: dict[str, tuple[str, str]]) -> dict[str, tuple[str, str]]:
        if not tabs:
            return tabs
        sources = [BACKEND]
        # A missing registered backend remains ambiguous for old viewer state.
        for owner in {key.partition("/")[0] for key in tabs}:
            if not re.fullmatch(r"[0-9a-f]{32}", owner):
                continue
            with contextlib.suppress(Error, OSError):
                workspace = Service().get(owner)
                for entry in BackendStore(workspace).read()["backends"]:
                    with contextlib.suppress(Error, OSError):
                        sources.append(Tmux.registered(entry).args)
        lines = []
        for args in {tuple(source) for source in sources}:
            with contextlib.suppress(Error, OSError):
                lines.extend(
                    run(
                        [
                            *args,
                            "list-panes",
                            "-a",
                            "-F",
                            "#{pane_id} #{pid}/#{session_created}/#{pane_pid} #{pane_dead}",
                        ]
                    ).splitlines()
                )
        living: set[tuple[str, str]] = set()
        ended: set[tuple[str, str]] = set()
        servers = set()
        for line in lines:
            fields = line.split()
            if len(fields) != 3 or fields[2] not in {"0", "1"}:
                continue
            pane, identity, dead = fields
            servers.add(identity.split("/", 1)[0])
            (living if dead == "0" else ended).add((pane, identity))

        retained = {}
        for key, data in tabs.items():
            identity = data[0]
            pane = key.rsplit("/", 1)[1]
            if (pane, identity) in living:
                retained[key] = data
            elif (pane, identity) not in ended and identity.split("/", 1)[0] not in servers:
                # A replacement server is as ambiguous as a missing socket.
                try:
                    pid = int(identity.rsplit("/", 1)[1])
                    if pid > 0:
                        os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                except (IndexError, OSError, ValueError):
                    pass
                retained[key] = data
        return retained

    def render_tabs(self) -> None:
        sidebar = self.pane("sidebar")
        active = self.pane("active")
        total, zoom, width = map(
            int, self.info(sidebar, "#{window_width} #{window_zoomed_flag} #{pane_width}").split()
        )
        left = 0 if zoom else min(total, width + 1)
        content = tab_status(
            self.tabs(), self.info(active, "#{@wm_display_view}") or None, total, left
        )
        self.tmux("set-option", "-t", TARGET + ":", "status-format[0]", content)

    def update_tab_names(self, snapshots: dict[str, list[dict[str, str]]]) -> None:
        with self.lock():
            self.check_owner()
            tabs = self.tabs()
            updated = self.live_tabs(tabs)
            for key, (identity, name) in tuple(updated.items()):
                owner, pane = key.split("/")
                peers = snapshots.get(owner, [])
                row = next((item for item in peers if item["pane"] == pane), None)
                if row and row.get("dead") == "0":
                    title = session_display_name(row)
                    if title != name:
                        with contextlib.suppress(Error, OSError):
                            workspace = Service().get(owner)
                            if (
                                Tmux().scoped(workspace, pane, identity).pane_identity(pane)
                                == identity
                            ):
                                updated[key] = (identity, title)
            if updated != tabs:
                self.save_tabs(updated)
                self.render_tabs()

    def take_tab_request(self) -> str:
        with self.lock():
            self.check_owner()
            queued = self.get("tab_request")
            if queued:
                self.set("tab_request", "")
            return queued

    def tab_action(self, action: str) -> None:
        with self.lock():
            self.check_owner()
            tabs = self.tabs()
            active = self.info(self.pane("active"), "#{@wm_display_view}")
            if (
                action == "close"
                or action.startswith("remove-")
                or re.fullmatch(r"x[0-9a-f]{12}", action)
            ):
                closing = (
                    active
                    if action == "close"
                    else next(
                        (
                            key
                            for key, (identity, _) in tabs.items()
                            if tab_token(key, identity)
                            == (action[7:] if action.startswith("remove-") else action[1:])
                        ),
                        "",
                    )
                )
                if closing in tabs:
                    if closing == active:
                        self.replace(self.pane("home"))
                    del tabs[closing]
                    self.save_tabs(tabs)
                    self.render_tabs()
                return
            if action in {"new", "all"}:
                self.set("tab_request", action)
                self.tmux("select-pane", "-Z", "-t", self.pane("sidebar"))
                return
            if action in {"next", "previous"}:
                keys = list(tabs)
                if not keys:
                    return
                index = keys.index(active) if active in tabs else (-1 if action == "next" else 0)
                key = keys[(index + (1 if action == "next" else -1)) % len(keys)]
            else:
                key = next(
                    (
                        candidate
                        for candidate, (identity, _) in tabs.items()
                        if tab_token(candidate, identity) == action
                    ),
                    "",
                )
            if not key:
                return
            workspace, pane = key.split("/")
            expected, _ = tabs[key]
            try:
                self._present_locked(Service().get(workspace), pane, expected)
            except (Error, OSError) as exc:
                self.set("tab_request", f"error:{exc}")

    def pane(self, key: str) -> str:
        pane = self.get(key)
        ids = self.tmux("list-panes", "-s", "-t", TARGET, "-F", "#{pane_id}").splitlines()
        if not re.fullmatch(r"%\d+", pane) or pane not in ids:
            raise Error(f"Display panel unavailable: {key}")
        return pane

    def info(self, pane: str, fmt: str) -> str:
        return self.tmux("display-message", "-p", "-t", pane, fmt)

    def repair(self) -> None:
        sidebar = self.pane("sidebar")
        home = self.pane("home")
        if self.info(sidebar, "#{pane_dead}") == "1":
            self.tmux("respawn-pane", "-t", sidebar, *self.command("sidebar"))
        if self.info(home, "#{pane_dead}") == "1":
            self.tmux(
                "respawn-pane",
                "-t",
                home,
                "-c",
                str(Path.home()).replace("#", "##"),
                *self.command("home-shell"),
            )
        active = self.pane("active")
        if active != home and (
            self.info(active, "#{pane_dead}") == "1"
            or not self.info(active, "#{@wm_display_identity}")
        ):
            self.replace(home)
        self.reflow()

    def replace(
        self,
        target: str,
        *,
        confirm: Callable[[], None] | None = None,
        publish: Callable[[], None] | None = None,
    ) -> None:
        old = self.pane("active")
        sidebar, home = self.pane("sidebar"), self.pane("home")
        visible = self.tmux("list-panes", "-t", WINDOW, "-F", "#{pane_id}").splitlines()
        if len(visible) != 2 or set(visible) != {sidebar, old}:
            raise Error("The display window layout has changed")
        if any(
            self.info(pane, "#{window_linked_sessions_list}") != SESSION for pane in (old, target)
        ):
            raise Error("The display window is shared with another session")
        if (old != home and not self.info(old, "#{@wm_display_view}")) or target == sidebar:
            raise Error("Refusing to move an unknown display panel")
        if target != home and not self.info(target, "#{@wm_display_view}"):
            raise Error("Refusing to show an unknown display panel")
        if old == target:
            self.tmux("select-pane", "-Z", "-t", target)
            return
        focused = old if self.info(old, "#{pane_active}") == "1" else sidebar
        self.tmux("swap-pane", "-dZ", "-s", target, "-t", old)
        try:
            self.tmux("select-pane", "-Z", "-t", target)
            if self.info(target, "#{pane_active} #{window_name}") != "1 workspace":
                raise Error("Could not focus the requested display panel")
            if confirm is not None:
                confirm()
            self.set("active", target)
            (publish or self.render_tabs)()
        except Error:
            self.tmux("swap-pane", "-dZ", "-s", old, "-t", target)
            self.set("active", old)
            self.tmux("select-pane", "-Z", "-t", focused)
            with contextlib.suppress(Error):
                self.render_tabs()
            raise
        if old != home:
            with contextlib.suppress(Error):
                self.kill_viewer(old)

    def kill_viewer(self, viewer: str, pid: str | None = None) -> None:
        birth = pid or self.info(viewer, "#{@wm_display_viewer_pid}")
        if not re.fullmatch(r"\d+", birth or ""):
            return
        self.tmux(
            "if-shell",
            "-F",
            "-t",
            viewer,
            "#{&&:#{==:#{pane_pid}," + birth + "},"
            "#{==:#{window_linked_sessions_list}," + SESSION + "}}",
            "kill-pane -t " + viewer,
        )

    def viewer_target(self, viewer: str) -> str:
        return self.info(viewer, "#{@wm_display_view}")

    @contextlib.contextmanager
    def watched_target(self, viewer: str, fallback: str) -> Iterator[str]:
        # Hold the same lock across the watchdog's inspection and detach so it
        # cannot mistake an in-flight switch for an external client change.
        with self.lock():
            yield self.viewer_target(viewer).partition("/")[2] or fallback

    def exclusive_client(
        self, viewer: str, workspace: Workspace, binding: Tmux | None = None
    ) -> tuple[str, str, str, str, str] | None:
        tty = self.info(viewer, "#{pane_tty}")
        if not tty:
            return None
        session = Tmux.session(workspace)
        binding = binding or Tmux().scoped(workspace)
        clients = run(
            [
                *binding.args,
                "list-clients",
                "-t",
                "=" + session,
                "-F",
                "#{client_tty} #{session_name} #{client_pid} #{session_id} #{window_id} #{pane_id}",
            ]
        ).splitlines()
        if len(clients) == 1:
            fields = clients[0].split()
            if len(fields) == 6 and fields[:2] == [tty, session]:
                _, _, pid, session_id, window, pane = fields
                return tty, pid, session_id, window, pane
        return None

    def client_target(self, viewer: str, workspace: Workspace) -> tuple[str, str] | None:
        client = self.exclusive_client(viewer, workspace)
        return (client[3], client[4]) if client else None

    def confirm_view(self, viewer: str, workspace: Workspace, pane: str, identity: str) -> None:
        binding = Tmux().scoped(workspace, pane, identity)
        window = run([*binding.args, "display-message", "-p", "-t", pane, "#{window_id}"])
        deadline = time.monotonic() + ATTACH_TIMEOUT
        while True:
            if (
                (client := self.exclusive_client(viewer, workspace, binding)) is not None
                and client[3:] == (window, pane)
                and binding.pane_identity(pane) == identity
                and run([*binding.args, "display-message", "-p", "-t", pane, "#{pane_dead}"]) == "0"
            ):
                return
            if self.info(viewer, "#{pane_dead}") == "1" or time.monotonic() >= deadline:
                raise Error("Could not attach the requested terminal")
            time.sleep(0.03)

    def select_terminal(self, workspace: Workspace, viewer: str, pane: str, identity: str) -> None:
        binding = Tmux().scoped(workspace, pane, identity)
        client = self.exclusive_client(viewer, workspace, binding)
        if client is None:
            raise Error("Terminal view lost exclusive access to its workspace")
        tty, pid, session_id, _, _ = client
        binding.select_viewer(workspace, pane, identity, tty, pid, session_id)

    def present(
        self,
        workspace: Workspace,
        pane: str,
        is_current: Callable[[], bool] | None = None,
        *,
        expected: str | None = None,
    ) -> None:
        if not re.fullmatch(r"%\d+", pane):
            raise Error("Invalid workspace panel identifier")
        with self.lock():
            self.check_owner()
            self._present_locked(workspace, pane, expected, is_current)

    def _present_locked(
        self,
        workspace: Workspace,
        pane: str,
        expected: str | None,
        is_current: Callable[[], bool] | None = None,
    ) -> None:
        def check_request() -> None:
            if is_current is not None and not is_current():
                raise Error("Terminal selection was superseded")

        check_request()
        binding = Tmux().scoped(workspace, pane, expected)
        peers = binding.list(workspace)
        row = next((row for row in peers if row["pane"] == pane and row["dead"] == "0"), None)
        if row is None:
            raise Error("Workspace terminal is no longer available")
        ownership = binding.inspect_pane(workspace, pane)
        if ownership.category not in (Ownership.OWNED, Ownership.MANAGED):
            raise Error("Terminal cannot be opened: ownership is unverified")
        identity = ownership.identity
        if expected is not None and expected != identity:
            raise Error("This tab refers to a previous terminal")
        key = f"{workspace.id}/{pane}"
        tabs = self.tabs()
        updated = {**tabs, key: (identity, session_display_name(row))}

        def publish() -> None:
            check_request()
            try:
                self.save_tabs(updated)
                self.render_tabs()
                check_request()
            except Error:
                with contextlib.suppress(Error):
                    self.save_tabs(tabs)
                raise

        active = self.pane("active")
        previous_key = self.viewer_target(active)
        previous_owner, _, previous_pane = previous_key.partition("/")
        previous_identity = self.info(active, "#{@wm_display_identity}")
        if previous_owner == workspace.id and self.exclusive_client(active, workspace, binding):
            focused = active if self.info(active, "#{pane_active}") == "1" else self.pane("sidebar")
            try:
                self.select_terminal(workspace, active, pane, identity)
                self.confirm_view(active, workspace, pane, identity)
                self.tmux("select-pane", "-Z", "-t", active)
                if self.info(active, "#{pane_active}") != "1":
                    raise Error("Could not focus the requested display panel")
                check_request()
                self.mark_view(active, key, identity)
                publish()
            except Error:
                try:
                    self.select_terminal(workspace, active, previous_pane, previous_identity)
                    self.confirm_view(active, workspace, previous_pane, previous_identity)
                    self.mark_view(active, previous_key, previous_identity)
                    self.tmux("select-pane", "-Z", "-t", focused)
                except Error:
                    self.replace(self.pane("home"))
                with contextlib.suppress(Error):
                    self.render_tabs()
                raise
        else:
            created = self.tmux(
                "new-window",
                "-dP",
                "-F",
                "#{pane_id} #{pane_pid}",
                "-t",
                TARGET + ":",
                "-n",
                "viewer",
                *self.command("view", workspace.id, pane, identity),
            )
            viewer, _, birth = created.partition(" ")
            if not re.fullmatch(r"%\d+", viewer) or not birth.isdecimal():
                raise Error("Cannot verify the terminal viewer identity")
            try:
                self.tmux(
                    "if-shell",
                    "-F",
                    "-t",
                    viewer,
                    "#{==:#{pane_pid}," + birth + "}",
                    f"set-option -p -t {viewer} @wm_display_viewer_pid {birth}",
                )
                self.mark_view(viewer, key, identity)
                self.confirm_view(viewer, workspace, pane, identity)
                check_request()
                self.replace(
                    viewer,
                    confirm=lambda: self.confirm_view(viewer, workspace, pane, identity),
                    publish=publish,
                )
            except Error:
                if self.pane("active") != viewer:
                    with contextlib.suppress(Error):
                        self.kill_viewer(viewer, birth)
                raise

    def mark_view(self, viewer: str, key: str, identity: str) -> None:
        self.tmux(
            "set-option",
            "-p",
            "-t",
            viewer,
            "@wm_display_view",
            key,
            ";",
            "set-option",
            "-p",
            "-t",
            viewer,
            "@wm_display_identity",
            identity,
        )

    def displayed(self) -> str | None:
        with self.lock():
            self.check_owner()
            viewer = self.pane("active")
            key = self.viewer_target(viewer)
            if not key:
                return None
            owner, target = key.split("/")
            if self.info(viewer, "#{window_name}") != "workspace":
                return None
            expected = self.info(viewer, "#{@wm_display_identity}")
            try:
                workspace = Service().get(owner)
                binding = Tmux().scoped(workspace, target, expected)
                actual = self.exclusive_client(viewer, workspace, binding)
                state = binding.inspect_pane(workspace, target)
                matches = (
                    self.info(viewer, "#{@wm_display_viewer_pid}")
                    == self.info(viewer, "#{pane_pid}")
                    and actual is not None
                    and actual[4] == target
                    and state.identity == expected
                    and state.category in (Ownership.OWNED, Ownership.MANAGED)
                )
            except (Error, OSError):
                matches = False
            if matches and self.info(viewer, "#{pane_dead}") == "0":
                return key
            self.release_view(viewer)
            return None

    def release_view(self, viewer: str) -> None:
        key = self.viewer_target(viewer)
        retained = self.live_tabs(self.tabs())
        if retained != self.tabs():
            self.save_tabs(retained)
        self.replace(self.pane("home"))
        if key in retained:
            self.set("tab_request", "error:Terminal view disconnected; open its tab to retry.")

    def detach_view(self, workspace: Workspace, pane: str, *, expected: str | None = None) -> None:
        with self.lock():
            self.check_owner()
            viewer = self.pane("active")
            if self.viewer_target(viewer) != f"{workspace.id}/{pane}" or (
                expected is not None and self.info(viewer, "#{@wm_display_identity}") != expected
            ):
                raise Error("Selected terminal is not displayed")
            self.replace(self.pane("home"))

    def finish_view(self, pane: str | None) -> None:
        with self.lock():
            self.check_owner()
            if pane and pane == self.pane("active") and self.viewer_target(pane):
                self.release_view(pane)

    def reflow(self) -> None:
        sidebar = self.pane("sidebar")
        active = self.pane("active")
        total, zoom = map(int, self.info(sidebar, "#{window_width} #{window_zoomed_flag}").split())
        hidden = self.get("hidden") == "1" or total < MIN_LEFT + 1 + MIN_RIGHT
        if hidden and not zoom:
            self.tmux("select-pane", "-t", active)
            self.tmux("resize-pane", "-Z", "-t", active)
        if not hidden:
            if zoom:
                self.tmux("resize-pane", "-Z", "-t", active)
            preferred = int(self.get("preferred"))
            self.tmux(
                "resize-pane", "-t", sidebar, "-x", str(min(preferred, total - 1 - MIN_RIGHT))
            )
        self.render_tabs()

    def action(self, action: str) -> None:
        if action.startswith("tab-"):
            self.tab_action(action[4:])
            return
        with self.lock():
            self.check_owner()
            sidebar, active = self.pane("sidebar"), self.pane("active")
            total, zoom, width, focused = map(
                int,
                self.info(
                    sidebar, "#{window_width} #{window_zoomed_flag} #{pane_width} #{pane_active}"
                ).split(),
            )
            if action == "home":
                self.replace(self.pane("home"))
            elif action == "toggle" and total >= MIN_LEFT + 1 + MIN_RIGHT:
                if not zoom:
                    self.set("preferred", str(max(MIN_LEFT, min(MAX_LEFT, width))))
                self.set("hidden", "0" if zoom else "1")
            elif action == "focus" and total >= MIN_LEFT + 1 + MIN_RIGHT:
                if zoom:
                    self.set("hidden", "0")
                    self.reflow()
                self.tmux("select-pane", "-t", active if focused else sidebar)
                return
            elif action == "save-width" and not zoom:
                self.set("preferred", str(max(MIN_LEFT, min(MAX_LEFT, width))))
            elif action in {"narrower", "wider"} and total >= MIN_LEFT + 1 + MIN_RIGHT:
                base = int(self.get("preferred")) if zoom else width
                step = -4 if action == "narrower" else 4
                self.set(
                    "preferred",
                    str(max(MIN_LEFT, min(MAX_LEFT, total - 1 - MIN_RIGHT, base + step))),
                )
            self.reflow()

    def attach(self) -> None:
        tmux = os.environ.get("TMUX")
        in_home = os.environ.get("WM_DISPLAY_HOME") == str(self.root)
        if tmux and Path(tmux.split(",", 1)[0]).resolve() != self.socket:
            raise Error("Run wm outside this tmux server, or use wm --classic here")
        self.prepare()
        if tmux or in_home:
            self.tmux("select-window", "-t", WINDOW)
            self.tmux("select-pane", "-Z", "-t", self.pane("sidebar"))
        elif subprocess.call([*self.args, "attach-session", "-t", TARGET]):
            raise Error("Could not attach to the workspace display")


def home_shell() -> str:
    configured = os.environ.get("SHELL")
    if configured and (executable := shutil.which(configured)):
        return executable
    try:
        account_shell = pwd.getpwuid(os.getuid()).pw_shell
    except KeyError:
        account_shell = ""
    return shutil.which(account_shell) or "/bin/sh"


def main() -> None:
    root, action, *args = sys.argv[1:]
    display = Display(Path(root))
    # The display socket is always explicit; workspace operations use the usual server.
    os.environ.pop("TMUX", None)
    viewer = os.environ.pop("TMUX_PANE", None)
    if action in {"sidebar", "view", "home-shell"}:
        if action == "home-shell":
            os.environ["WM_DISPLAY_HOME"] = str(display.root)
            shell = home_shell()
            os.execv(shell, [shell, "-il"])
        elif action == "sidebar":
            from .tui import Manager

            Manager(
                Service(),
                presenter=display.present,
                displayed=display.displayed,
                detach_view=display.detach_view,
                tab_request=display.take_tab_request,
                tab_names=display.update_tab_names,
            ).run()
        else:
            workspace, pane, *identity = args
            try:
                owner = Service().get(workspace)
                Tmux().attach(
                    owner,
                    pane,
                    create=False,
                    exclusive=True,
                    expected_identity=identity[0] if identity else None,
                    view_target=(lambda: display.watched_target(viewer, pane)) if viewer else None,
                )
            finally:
                display.finish_view(viewer)
    else:
        display.action(action)


if __name__ == "__main__":
    try:
        main()
    except (Error, OSError, ValueError) as exc:
        print(f"Workspace display: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
