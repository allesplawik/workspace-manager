"""Real SGR mouse input through PTYs, with and without an isolated tmux server."""

import contextlib
import fcntl
import json
import os
import pty
import selectors
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from workspace_manager.core import Error, run


class NativeDashboardMouseTests(unittest.TestCase):
    def exercise(self, tmux):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            sockets = root / "sockets"
            sockets.mkdir(mode=0o700)
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 110, 0, 0))
            fixture = Path(__file__).with_name("dashboard_terminal_probe.py")
            command = [sys.executable, str(fixture), str(root)]
            child = None
            output = bytearray()
            with patch.dict(os.environ, {"TERM": "xterm-256color", "TMUX_TMPDIR": str(sockets)}):
                os.environ.pop("TMUX", None)
                try:
                    if tmux:
                        run(
                            [
                                "tmux",
                                "-f",
                                "/dev/null",
                                "new-session",
                                "-d",
                                "-x",
                                "110",
                                "-y",
                                "50",
                                "-s",
                                "wm-ui-mouse",
                                shlex.join(command),
                            ]
                        )
                        run(["tmux", "set-option", "-t", "=wm-ui-mouse:", "mouse", "on"])
                        run(["tmux", "set-option", "-s", "escape-time", "0"])
                        run(
                            [
                                "tmux",
                                "set-window-option",
                                "-t",
                                "=wm-ui-mouse:",
                                "remain-on-exit",
                                "off",
                            ]
                        )
                        command = ["tmux", "attach-session", "-t", "=wm-ui-mouse"]
                    child = subprocess.Popen(
                        command, stdin=slave, stdout=slave, stderr=slave, start_new_session=True
                    )
                    os.set_blocking(master, False)
                    with selectors.DefaultSelector() as selector:
                        selector.register(master, selectors.EVENT_READ)

                        def wait_for(predicate, timeout=12, nudge=None):
                            deadline = time.monotonic() + timeout
                            next_nudge = 0
                            while not predicate():
                                if nudge is not None and time.monotonic() >= next_nudge:
                                    nudge()
                                    next_nudge = time.monotonic() + 0.25
                                if selector.select(0.03):
                                    with contextlib.suppress(OSError, BlockingIOError):
                                        output.extend(os.read(master, 65536))
                                self.assertLess(
                                    time.monotonic(),
                                    deadline,
                                    "native UI input timed out: "
                                    + output[-1500:].decode(errors="replace"),
                                )
                                self.assertIsNone(
                                    child.poll(),
                                    "native UI exited early: "
                                    + output[-1500:].decode(errors="replace"),
                                )

                        # Ask the app for geometry after actual client input and
                        # a completed render, not during detached tmux startup.
                        wait_for(
                            lambda: (root / "geometry").exists(),
                            nudge=lambda: os.write(master, b"\x1b[24~"),
                        )
                        positions = json.loads((root / "geometry").read_text())

                        def mouse(name):
                            x, y = positions[name]
                            os.write(
                                master, f"\x1b[<0;{x + 1};{y + 1}M\x1b[<0;{x + 1};{y + 1}m".encode()
                            )

                        def logged(text):
                            return (root / "events").exists() and text in (
                                root / "events"
                            ).read_text()

                        mouse("row")
                        wait_for(lambda: logged("choose:workspaces"))
                        x, y = positions["row"]
                        os.write(master, f"\x1b[<65;{x + 1};{y + 1}M".encode())
                        wait_for(lambda: logged("wheel:workspaces"))
                        mouse("toggle")
                        wait_for(lambda: logged("action:workspace-toggle"))
                        mouse("menu")
                        wait_for(lambda: logged("action:workspace-menu"))
                        wait_for(lambda: (root / "menu-open").exists())
                        os.write(master, b"\x1b")
                        # Wait for Escape to be parsed independently of q (tmux
                        # and terminal parsers buffer incomplete escape prefixes).
                        wait_for(lambda: (root / "menu-closed").exists())
                        os.write(master, b"q")
                        deadline = time.monotonic() + 8
                        while child.poll() is None and time.monotonic() < deadline:
                            if selector.select(0.03):
                                with contextlib.suppress(OSError, BlockingIOError):
                                    output.extend(os.read(master, 65536))
                        self.assertTrue(
                            (root / "exited").exists(),
                            "native app did not quit: " + (root / "events").read_text(),
                        )
                        self.assertEqual(child.wait(timeout=2), 0)
                        self.assertNotIn("UNEXPECTED-ATTACH", (root / "events").read_text())
                        self.assertIn(b"\x1b[", output)
                finally:
                    if child is not None and child.poll() is None:
                        child.terminate()
                        child.wait(timeout=5)
                    if tmux:
                        with contextlib.suppress(Error):
                            run(["tmux", "kill-session", "-t", "=wm-ui-mouse"])
                    os.close(master)
                    os.close(slave)

    def test_mouse_in_native_terminal_pty(self):
        self.exercise(tmux=False)

    @unittest.skipUnless(shutil.which("tmux"), "tmux unavailable")
    def test_mouse_through_isolated_tmux(self):
        self.exercise(tmux=True)

    @unittest.skipUnless(shutil.which("tmux"), "tmux unavailable")
    def test_ctrl_b_detach_returns_and_preserves_workspace_process(self):
        from workspace_manager.core import Config, Service
        from workspace_manager.terminal import Tmux

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            socket = root / "sockets"
            socket.mkdir(mode=0o700)
            with patch.dict(os.environ, {"TMUX_TMPDIR": str(socket), "TERM": "xterm-256color"}):
                os.environ.pop("TMUX", None)
                # Start only our temporary server without user tmux config.
                run(
                    [
                        "tmux",
                        "-f",
                        "/dev/null",
                        "new-session",
                        "-d",
                        "-s",
                        "wm-detach-anchor",
                        "sleep 120",
                    ]
                )
                service = Service(Config(root / "work", root, root / "state"))
                workspace = service.create("detach")
                tmux = Tmux()
                master, slave = pty.openpty()
                client = None
                try:
                    pane = tmux.new(workspace, command=["sleep", "120"])
                    script = (
                        "from workspace_manager.core import Workspace; "
                        "from workspace_manager.terminal import Tmux; "
                        f"Tmux().attach(Workspace.decode({workspace.encode()!r}), {pane!r})"
                    )
                    client = subprocess.Popen(
                        [sys.executable, "-c", script],
                        stdin=slave,
                        stdout=slave,
                        stderr=slave,
                        start_new_session=True,
                    )
                    deadline = time.monotonic() + 8
                    while not run(["tmux", "list-clients", "-F", "#{client_pid}"]):
                        self.assertIsNone(client.poll())
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.03)
                    os.write(master, b"\x02d")
                    self.assertEqual(client.wait(timeout=8), 0)
                    remaining = tmux.list(workspace)
                    self.assertEqual([p["pane"] for p in remaining], [pane])
                    self.assertEqual(remaining[0]["dead"], "0")
                    self.assertEqual(remaining[0]["command"], "sleep")
                finally:
                    if client is not None and client.poll() is None:
                        client.terminate()
                        client.wait(timeout=5)
                    for name in (tmux.session(workspace), "wm-detach-anchor"):
                        with contextlib.suppress(Error):
                            run(["tmux", "kill-session", "-t", "=" + name])
                    os.close(master)
                    os.close(slave)
