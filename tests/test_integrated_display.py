from __future__ import annotations

import contextlib
import fcntl
import json
import os
import pty
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from workspace_manager.core import Config, Error, Service, run
from workspace_manager.session_tabs import tab_token
from workspace_manager.split import TARGET, Display
from workspace_manager.terminal import Tmux

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="requires tmux")


class Client:
    def __init__(self, env: dict[str, str], cwd: Path, command: list[str] | None = None):
        self.master, slave = pty.openpty()
        self.resize(110)
        try:
            self.process = subprocess.Popen(
                command or [sys.executable, "-c", "from workspace_manager.cli import main; main()"],
                env=env,
                cwd=cwd,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
            )
        finally:
            os.close(slave)
        os.set_blocking(self.master, False)
        self.output = bytearray()

    def resize(self, cols: int) -> None:
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 36, cols, 0, 0))

    def send(self, data: bytes) -> None:
        os.write(self.master, data)

    def shortcut(self, display: Display, key: bytes) -> None:
        # A single pasted C-b sequence can bypass the key table on tmux 3.4.
        # Wait for the prefix state before sending the second keystroke.
        time.sleep(0.01)
        self.send(b"\x02")
        self.wait(
            lambda: display.tmux("list-clients", "-F", "#{client_key_table}") == "prefix",
            "tmux prefix",
        )
        self.send(key)

    def wait(self, check, label: str) -> None:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            with contextlib.suppress(OSError):
                self.output.extend(os.read(self.master, 65536))
            if check():
                return
            time.sleep(0.04)
        pytest.fail(f"{label}: {bytes(self.output[-1000:])!r}")

    def close(self) -> None:
        os.close(self.master)
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            self.process.wait(timeout=5)


def test_home_shell_uses_environment_then_login_account(monkeypatch):
    from types import SimpleNamespace

    from workspace_manager.split import home_shell

    monkeypatch.setattr(
        "workspace_manager.split.pwd.getpwuid", lambda _: SimpleNamespace(pw_shell="/bin/bash")
    )
    monkeypatch.setenv("SHELL", "/bin/sh")
    assert home_shell() == "/bin/sh"
    monkeypatch.setenv("SHELL", "/missing/shell")
    assert home_shell() == "/bin/bash"
    monkeypatch.delenv("SHELL")
    assert home_shell() == "/bin/bash"


def test_default_wm_shows_home_and_preserves_workspace_processes(monkeypatch):
    # The socket path must fit macOS's Unix socket limit.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="wm-it-", dir="/tmp") as temporary:
        root = Path(temporary).resolve()
        for key in ("TMUX", "TMUX_PANE", "ENV"):
            monkeypatch.delenv(key, raising=False)
        for key, name in {
            "TMUX_TMPDIR": "tmux",
            "XDG_CONFIG_HOME": "config",
            "XDG_STATE_HOME": "state",
            "CODEX_HOME": "codex",
            "HOME": "home",
        }.items():
            directory = root / name
            directory.mkdir(mode=0o700)
            monkeypatch.setenv(key, str(directory))
        checkout = Path(__file__).resolve().parents[1]
        monkeypatch.setenv("PYTHONPATH", "src")
        monkeypatch.setenv("TERM", "xterm-256color")
        monkeypatch.setenv("SHELL", "/bin/sh")
        config = Config.load()
        display = Display.configured(config)
        service = Service(config)
        workspace = service.create("integration", root / "workspaces")
        source = root / "source"
        run(["git", "init", "-b", "main", str(source)])
        run(
            [
                "git",
                "-C",
                str(source),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "initial",
            ]
        )
        service.add(workspace.id, source, "repo", "topic")
        workspace = service.get(workspace.id)
        repo = Path(workspace.path) / "repo"
        backend = Tmux()
        first = backend.new(workspace, cwd=repo, command=["/bin/sh", "-i"])
        second = backend.new(workspace, cwd=repo, command=["/bin/sh", "-i"])
        pid = run(["tmux", "display-message", "-p", "-t", first, "#{pane_pid}"])
        client = None
        other = None
        try:
            other = service.create("another", root / "workspaces")
            legacy_list = subprocess.check_output(
                [
                    sys.executable,
                    "-c",
                    "from workspace_manager.cli import main; main()",
                    "terminal",
                    "list",
                    workspace.id,
                ],
                cwd=checkout,
                env=os.environ.copy(),
                text=True,
            )
            assert set(json.loads(legacy_list)[0]) == {"pane", "command", "cwd", "dead", "kind"}
            client = Client(os.environ.copy(), checkout)
            client.wait(lambda: b"Explorer" in client.output, "default wm dashboard")
            display.tmux("set-environment", "-g", "PYTHONPATH", str(root / "absent"))
            assert list(display.tabs()) == [f"{workspace.id}/{pane}" for pane in (first, second)]
            home = display.pane("home")
            sidebar = display.pane("sidebar")
            assert display.info(home, "#{pane_current_path}") == str(Path.home().resolve())
            client.send(b"export WM_HOME=kept\n")
            client.shortcut(display, b"f")
            client.wait(lambda: display.info(sidebar, "#{pane_active}") == "1", "focus dashboard")
            assert display.info(sidebar, "#{pane_width}") == "36"
            client.shortcut(display, b"\x1b[C")
            client.wait(lambda: display.info(sidebar, "#{pane_width}") == "40", "keyboard resize")

            for columns, key in (
                (36, b"D"),
                (32, b"D"),
                (28, b"D"),
                (32, b"C"),
                (36, b"C"),
                (40, b"C"),
            ):
                client.shortcut(display, b"\x1b[" + key)
                client.wait(
                    lambda width=columns: display.info(sidebar, "#{pane_width}") == str(width),
                    f"keyboard resize to {columns} columns",
                )
            # Drag the border with real tmux mouse reporting (SGR coordinates).
            client.send(b"\x1b[<0;41;12M\x1b[<32;45;12M\x1b[<0;45;12m")
            client.wait(lambda: display.info(sidebar, "#{pane_width}") == "44", "mouse resize")

            for columns in (48, 50):
                client.shortcut(display, b"\x1b[C")
                client.wait(
                    lambda width=columns: display.info(sidebar, "#{pane_width}") == str(width),
                    f"keyboard resize to {columns} columns",
                )

            def line_containing(needle: str) -> int | None:
                capture = display.tmux("capture-pane", "-p", "-t", sidebar)
                return next(
                    (n for n, line in enumerate(capture.splitlines(), 1) if needle in line), None
                )

            def click_line(needle: str) -> None:
                client.wait(lambda: line_containing(needle) is not None, f"render {needle}")
                line = line_containing(needle)
                assert line is not None
                line += 1  # tmux draws the tabs status row above the pane.
                client.send(f"\x1b[<0;6;{line}M\x1b[<0;6;{line}m".encode())

            click_line("integration")
            client.send(b"\x1b[C")
            click_line("topic · repo")
            click_line("Shell 1 · repo")
            client.wait(lambda: display.displayed() == f"{workspace.id}/{first}", "show terminal")
            viewer = display.pane("active")
            client.wait(
                lambda: display.info(viewer, "#{pane_active}") == "1",
                "keyboard focus follows the first terminal card",
            )
            client.send(b"export WM_FIRST=alpha; printf 'visible-%s\\n' \"$WM_FIRST\"\n")
            client.wait(
                lambda: (
                    "visible-alpha" in run(["tmux", "capture-pane", "-p", "-t", first])
                    and "visible-alpha" in display.tmux("capture-pane", "-p", "-t", viewer)
                ),
                "interactive workspace shell rendered in viewer",
            )
            name = """Second shell; '"#{pane_id}"'"""
            backend.rename(workspace, second, name)
            assert (
                next(row["name"] for row in backend.list(workspace) if row["pane"] == second)
                == name
            )
            second_pid = run(["tmux", "display-message", "-p", "-t", second, "#{pane_pid}"])
            client.shortcut(display, b"f")
            client.wait(lambda: display.info(sidebar, "#{pane_active}") == "1", "focus sessions")
            client.send(b"r")
            click_line("Second shell")
            client.wait(
                lambda: display.displayed() == f"{workspace.id}/{second}",
                "second terminal selected",
            )
            second_viewer = display.pane("active")
            client.wait(
                lambda: display.info(second_viewer, "#{pane_active}") == "1",
                "keyboard focus follows the second terminal card",
            )
            client.send(b'export WM_SECOND=beta; echo second-"$WM_SECOND"\n')
            client.wait(
                lambda: (
                    "second-beta" in run(["tmux", "capture-pane", "-p", "-t", second])
                    and "second-beta" in display.tmux("capture-pane", "-p", "-t", second_viewer)
                ),
                "interactive second terminal rendered in viewer",
            )
            first_key, second_key = (f"{workspace.id}/{pane}" for pane in (first, second))
            assert list(display.tabs()) == [first_key, second_key]
            client.shortcut(display, b"p")
            client.wait(lambda: display.displayed() == first_key, "previous tab selects first")
            # The first tab follows nine control cells; the second begins after Shell 1.
            tab_col = int(display.info(sidebar, "#{pane_width}")) + 1 + 9 + len(" Shell 1 ") + 2
            client.send(f"\x1b[<0;{tab_col};1M\x1b[<0;{tab_col};1m".encode())
            client.wait(lambda: display.displayed() == second_key, "status row clicks second tab")
            client.shortcut(display, b"x")
            client.wait(lambda: second_key not in display.tabs(), "close active tab")
            assert display.displayed() is None
            display.prepare()
            assert second_key not in display.tabs()
            assert run(["tmux", "display-message", "-p", "-t", second, "#{pane_pid}"]) == second_pid
            display.present(workspace, second)
            assert second_key in display.tabs()
            display.detach_view(workspace, second)
            assert display.displayed() is None
            assert run(["tmux", "display-message", "-p", "-t", second, "#{pane_pid}"]) == second_pid
            assert {entry["pane"] for entry in backend.list(workspace)} == {first, second}
            assert run(["git", "-C", str(repo), "branch", "--show-current"]) == "topic"
            with pytest.raises(Error, match="terminal"):
                service.remove(workspace.id, "repo", confirmed=True)

            def assert_active(key: str, pane: str) -> None:
                assert display.displayed() == key
                viewer = display.pane("active")
                assert display.client_target(viewer, workspace) is not None
                assert display.client_target(viewer, workspace)[1] == pane
                assert display.info(viewer, "#{pane_active}") == "1"
                status = display.tmux("show-options", "-v", "-t", TARGET + ":", "status-format[0]")
                assert "bold,range=user|" + tab_token(key, display.identity(pane)) in status

            display.present(workspace, first)
            assert_active(first_key, first)
            active = display.pane("active")
            with (
                patch.object(display, "select_terminal", return_value=None),
                patch("workspace_manager.split.ATTACH_TIMEOUT", 0.1),
                pytest.raises(Error, match="Could not attach"),
            ):
                display.present(workspace, second)
            assert_active(first_key, first)
            assert display.pane("active") == active
            with pytest.raises(Error, match="no longer available"):
                display.present(workspace, "%9999")
            assert_active(first_key, first)

            confirm = display.confirm_view
            superseded = False

            def confirm_then_supersede(viewer, owner, pane, identity):
                nonlocal superseded
                confirm(viewer, owner, pane, identity)
                if pane == second:
                    superseded = True

            with (
                patch.object(display, "confirm_view", side_effect=confirm_then_supersede),
                pytest.raises(Error, match="superseded"),
            ):
                display.present(workspace, second, lambda: not superseded)
            assert_active(first_key, first)
            assert display.pane("active") == active

            render = display.render_tabs
            superseded = False

            def render_then_supersede():
                nonlocal superseded
                render()
                superseded = True

            with (
                patch.object(display, "render_tabs", side_effect=render_then_supersede),
                pytest.raises(Error, match="superseded"),
            ):
                display.present(workspace, second, lambda: not superseded)
            assert_active(first_key, first)
            assert list(display.tabs()) == [first_key, second_key]

            display.present(workspace, second)
            assert_active(second_key, second)
            assert display.pane("active") == active
            display.present(workspace, first)
            assert_active(first_key, first)
            for key in (b"n", b"p", b"n", b"p"):
                client.shortcut(display, key)
            client.wait(lambda: display.displayed() == first_key, "final rapid selection")
            assert_active(first_key, first)
            assert list(display.tabs()) == [first_key, second_key]
            assert run(["tmux", "display-message", "-p", "-t", first, "#{pane_pid}"]) == pid
            assert run(["tmux", "display-message", "-p", "-t", second, "#{pane_pid}"]) == second_pid
            client.wait(
                lambda: (
                    (line := line_containing("Shell 1 · repo")) is not None
                    and "connected"
                    in display.tmux("capture-pane", "-p", "-t", sidebar).splitlines()[line]
                ),
                "sidebar follows rapid selection",
            )
            third = backend.new(other, command=["/bin/sh", "-i"])
            third_identity = display.identity(third)
            with (Path(other.path) / ".wm/view.lock").open("a") as busy:
                fcntl.flock(busy, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with (
                    patch("workspace_manager.split.ATTACH_TIMEOUT", 0.25),
                    pytest.raises(Error, match="Could not attach"),
                ):
                    display.present(other, third)
                assert_active(first_key, first)
                assert display.pane("active") == active
                assert list(display.tabs()) == [first_key, second_key]
                assert len(display.tmux("list-windows", "-t", TARGET).splitlines()) == 2

            render = display.render_tabs
            render_failed = False

            def fail_render_once():
                nonlocal render_failed
                if not render_failed:
                    render_failed = True
                    raise Error("Injected status rendering failure")
                render()

            with (
                patch.object(display, "render_tabs", side_effect=fail_render_once),
                pytest.raises(Error, match="Injected status rendering failure"),
            ):
                display.present(other, third)
            assert_active(first_key, first)
            assert display.pane("active") == active
            assert list(display.tabs()) == [first_key, second_key]

            display.present(other, third)
            other_viewer = display.pane("active")
            assert display.displayed() == f"{other.id}/{third}"
            assert display.client_target(other_viewer, other)[1] == third
            assert display.identity(third) == third_identity
            client.wait(
                lambda: (
                    "WORKSPACE\nanother"
                    in "\n".join(
                        line.strip()
                        for line in display.tmux("capture-pane", "-p", "-t", sidebar).splitlines()
                    )
                ),
                "sidebar follows other workspace",
            )
            display.present(workspace, first)
            client.wait(
                lambda: line_containing("source / topic") is not None, "sidebar returns to worktree"
            )
            assert_active(first_key, first)
            active = display.pane("active")
            with display.lock():
                viewer_client = display.exclusive_client(active, workspace)
                assert viewer_client is not None
                tty, client_pid, session_id, _, _ = viewer_client
                with pytest.raises(Error, match="ownership changed"):
                    backend.select_viewer(
                        workspace,
                        second,
                        display.identity(second),
                        tty,
                        str(int(client_pid) + 1),
                        session_id,
                    )
                assert display.client_target(active, workspace)[1] == first
            with display.lock():
                external = Client(
                    os.environ.copy(), checkout, ["tmux", "attach-session", "-t", second]
                )
                try:
                    external.wait(
                        lambda: len(backend.attached_clients(workspace).splitlines()) == 2,
                        "second real tmux client",
                    )
                    assert display.client_target(active, workspace) is None
                    with pytest.raises(Error, match="already (has|in use)"):
                        backend.attach(workspace, first, create=False)
                    assert run(["tmux", "list-clients", "-F", "#{pane_id}"]).splitlines() == [
                        second,
                        second,
                    ]
                except BaseException:
                    external.close()
                    raise
            try:
                client.wait(lambda: display.displayed() is None, "reconcile external selection")
                client.wait(
                    lambda: line_containing("Terminal view disconnected") is not None,
                    "conflict message",
                )
                assert display.pane("active") == home
                assert first_key in display.tabs() and second_key in display.tabs()
                assert external.process.poll() is None
                with (
                    patch.object(backend, "attached_clients", return_value=""),
                    pytest.raises(Error, match="tmux attach failed"),
                ):
                    backend.attach(workspace, first, create=False)
                assert run(["tmux", "list-clients", "-F", "#{pane_id}"]) == second
                assert run(["tmux", "display-message", "-p", "-t", first, "#{pane_pid}"]) == pid
                assert (
                    run(["tmux", "display-message", "-p", "-t", second, "#{pane_pid}"])
                    == second_pid
                )
            finally:
                external.close()
            client.wait(lambda: backend.attached_clients(workspace) == "", "external detach")
            with (
                subprocess.Popen(
                    display.command("tab-" + tab_token(first_key, display.identity(first)))
                ) as a,
                subprocess.Popen(
                    display.command("tab-" + tab_token(second_key, display.identity(second)))
                ) as b,
            ):
                assert a.wait(timeout=10) == 0
                assert b.wait(timeout=10) == 0
            current = display.displayed()
            assert current in (first_key, second_key)
            assert_active(current, first if current == first_key else second)
            assert len(display.tabs()) == 3
            display.present(workspace, second)
            active = display.pane("active")
            client.wait(
                lambda: "second-beta" in display.tmux("capture-pane", "-p", "-t", active),
                "second terminal retained its buffer",
            )
            client.send(b"printf 'second-retained-%s\\n' \"$WM_SECOND\"\n")
            client.wait(
                lambda: "second-retained-beta" in run(["tmux", "capture-pane", "-p", "-t", second]),
                "second terminal retained its shell variable",
            )
            display.present(workspace, first)
            active = display.pane("active")
            client.shortcut(display, b"z")
            client.wait(lambda: display.info(active, "#{window_zoomed_flag}") == "1", "zoom")
            client.shortcut(display, b"z")
            client.wait(lambda: display.info(active, "#{window_zoomed_flag}") == "0", "restore")
            client.resize(58)
            # This harness deliberately has no controlling terminal, so deliver
            # SIGWINCH to its own display client after changing the kernel PTY.
            pid_text = display.tmux("list-clients", "-F", "#{client_pid}")
            os.kill(int(pid_text), signal.SIGWINCH)
            client.wait(lambda: display.info(active, "#{window_width}") == "58", "resize")
            client.wait(
                lambda: display.info(active, "#{window_zoomed_flag}") == "1", "narrow fallback"
            )
            client.shortcut(display, b"d")
            client.wait(lambda: client.process.poll() is not None, "detach")
            assert client.process.returncode == 0
            client.close()
            client = Client(os.environ.copy(), checkout)
            client.wait(lambda: b"visible-alpha" in client.output, "reattach retained buffer")
            assert display.pane("active") == active
            assert run(["tmux", "display-message", "-p", "-t", first, "#{pane_pid}"]) == pid
            client.send(b"printf 'retained-%s\\n' \"$WM_FIRST\"\n")
            client.wait(
                lambda: "retained-alpha" in run(["tmux", "capture-pane", "-p", "-t", first]),
                "retained shell variable",
            )
            sidebar_pid = display.info(sidebar, "#{pane_pid}")
            client.send(b"\x04")
            client.wait(lambda: display.pane("active") == home, "Ctrl+D returns to home")
            client.wait(lambda: first_key not in display.tabs(), "exited terminal tab disappears")
            assert second_key in display.tabs()
            assert display.info(sidebar, "#{pane_pid}") == sidebar_pid
            assert line_containing("topic · repo") is not None
            assert run(["tmux", "display-message", "-p", "-t", second, "#{pane_pid}"]) == second_pid
            client.send(b"printf 'home-%s\\n' \"$WM_HOME\"\n")
            client.wait(
                lambda: "home-kept" in display.tmux("capture-pane", "-p", "-t", home),
                "home shell preserved",
            )
            client.send(b"exit\n")
            client.wait(lambda: display.info(home, "#{pane_dead}") == "1", "home shell exited")
            display.prepare()
            client.wait(lambda: display.info(home, "#{pane_dead}") == "0", "repair home shell")
            client.send(b"printf 'repaired-%s\\n' home\n")
            client.wait(
                lambda: "repaired-home" in display.tmux("capture-pane", "-p", "-t", home),
                "repaired shell is interactive",
            )
        finally:
            if client is not None:
                client.close()
            with contextlib.suppress(Error), display.lock():
                display.check_owner()
                display.tmux("kill-session", "-t", TARGET)
            with contextlib.suppress(Error):
                run(["tmux", "kill-session", "-t", "=" + backend.session(workspace)])
            if other is not None:
                with contextlib.suppress(Error):
                    run(["tmux", "kill-session", "-t", "=" + backend.session(other)])
            shutil.rmtree(display.root, ignore_errors=True)
