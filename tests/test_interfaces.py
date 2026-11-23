"""Interface tests run when optional development dependencies are installed."""

import contextlib
import importlib.util
import json
import os
import pty
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from workspace_manager.core import Config, Error, Service, run
from workspace_manager.terminal import Tmux

HAS_UI = importlib.util.find_spec("textual") is not None
HAS_CLI = importlib.util.find_spec("typer") is not None


@unittest.skipUnless(HAS_CLI, "typer unavailable; install .[dev]")
class CLITests(unittest.TestCase):
    def test_help_and_automation_from_other_cwd(self):
        from typer.testing import CliRunner

        from workspace_manager.cli import app

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            runner = CliRunner()
            with patch("workspace_manager.cli.Service", return_value=service):
                self.assertEqual(runner.invoke(app, ["--help"]).exit_code, 0)
                created = runner.invoke(app, ["workspace", "create", "sample", "--yes"])
                self.assertEqual(created.exit_code, 0, created.output)
                selected = runner.invoke(app, ["workspace", "select", "sample", "--print-path"])
                self.assertEqual(selected.output.strip(), str(root / "work/sample"))
                status = runner.invoke(app, ["workspace", "status", "sample"])
                self.assertEqual(json.loads(status.output)["workspace"]["name"], "sample")

    def test_default_launcher_routing_preserves_classic_and_subcommands(self):
        from types import SimpleNamespace

        from workspace_manager.cli import root, split_workspace

        for stdin_tty, stdout_tty, classic, subcommand, expected in (
            (True, True, False, None, "integrated"),
            (True, True, True, None, "classic"),
            (False, True, False, None, "classic"),
            (True, False, False, None, "classic"),
            (True, True, False, "workspace", None),
        ):
            with (
                self.subTest(stdin=stdin_tty, stdout=stdout_tty, classic=classic, cmd=subcommand),
                patch("workspace_manager.cli.sys.stdin.isatty", return_value=stdin_tty),
                patch("workspace_manager.cli.sys.stdout.isatty", return_value=stdout_tty),
                patch("workspace_manager.cli.Config.load"),
                patch("workspace_manager.cli.Service"),
                patch("workspace_manager.split.Display.configured") as display,
                patch("workspace_manager.tui.Manager") as manager,
            ):
                root(SimpleNamespace(invoked_subcommand=subcommand), classic)
                self.assertEqual(display.return_value.attach.call_count, expected == "integrated")
                self.assertEqual(manager.return_value.run.call_count, expected == "classic")

        with (
            patch("workspace_manager.cli.Config.load"),
            patch("workspace_manager.split.Display.configured") as display,
        ):
            split_workspace()
            display.return_value.attach.assert_called_once_with()

    def test_repo_switch_cli_requires_confirmation(self):
        from typer.testing import CliRunner

        from workspace_manager.cli import app

        with (
            patch("workspace_manager.cli.Service") as service,
            patch("workspace_manager.cli.Git.status", return_value={"branch": "main"}),
        ):
            service.return_value.repo_target.return_value = (object(), Path("/tmp/worktree"))
            runner = CliRunner()
            args = ["repo", "switch", "workspace", "repo", "review"]
            cancelled = runner.invoke(app, args, input="n\n")
            self.assertEqual(cancelled.exit_code, 0, cancelled.output)
            service.return_value.switch_branch.assert_not_called()
            result = runner.invoke(app, [*args, "--yes"])
            self.assertEqual(result.exit_code, 0, result.output)
            service.return_value.switch_branch.assert_called_once_with(
                "workspace", "repo", "review", True
            )


@unittest.skipUnless(HAS_UI, "Textual unavailable; install .[dev]")
class UITests(unittest.IsolatedAsyncioTestCase):
    async def test_create_search_and_repo_refresh(self):
        from textual.widgets import DataTable, Input

        from workspace_manager.tui import Manager

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            workspace = service.create("sample")
            source = root / "source"
            source.mkdir()
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
            app = Manager(service)
            async with app.run_test(size=(120, 45)) as pilot:
                await app.workers.wait_for_complete()
                self.assertEqual(app.query_one("#workspaces", DataTable).row_count, 1)
                app.current = workspace.id
                service.add(workspace.id, source, "repo", "feature")
                app.action_refresh()
                await app.workers.wait_for_complete()
                self.assertEqual(app.query_one("#repos", DataTable).row_count, 1)
                app.query_one("#search", Input).value = "nonexistent"
                await pilot.pause()
                await app.workers.wait_for_complete()
                self.assertEqual(app.query_one("#workspaces", DataTable).row_count, 0)


@unittest.skipUnless(__import__("shutil").which("tmux"), "tmux unavailable")
class RealTmuxTests(unittest.TestCase):
    def test_exiting_attached_shell_returns_without_closing_other_panes(self):
        self._check_attached_shell_exit(split=False)

    def test_exiting_attached_split_returns_without_closing_other_panes(self):
        self._check_attached_shell_exit(split=True)

    def _check_attached_shell_exit(self, split):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            socket = root / "sockets"
            socket.mkdir(mode=0o700)
            with patch.dict(os.environ, {"TMUX_TMPDIR": str(socket), "TERM": "xterm-256color"}):
                os.environ.pop("TMUX", None)
                service = Service(Config(root / "work", root, root / "state"))
                workspace = service.create("exit-shell")
                tmux = Tmux()
                survivor = tmux.new(workspace, command=["sleep", "120"], kind="codex")
                master, slave = pty.openpty()
                client = None
                try:
                    shell = tmux.new(workspace, command=["/bin/sh"], split=split)
                    script = (
                        "from workspace_manager.core import Workspace; "
                        "from workspace_manager.terminal import Tmux; "
                        f"Tmux().attach(Workspace.decode({workspace.encode()!r}), {shell!r})"
                    )
                    client = subprocess.Popen(
                        [sys.executable, "-c", script],
                        stdin=slave,
                        stdout=slave,
                        stderr=slave,
                        start_new_session=True,
                    )
                    deadline = time.monotonic() + 10
                    while not run(["tmux", "list-clients", "-F", "#{client_pid}"]):
                        self.assertIsNone(client.poll(), "interactive attach exited early")
                        self.assertLess(time.monotonic(), deadline, "client failed to attach")
                        time.sleep(0.05)
                    # Ctrl+D on the actual attached terminal closes the shell.
                    os.write(master, b"\x04")
                    self.assertEqual(client.wait(timeout=10), 0)
                    remaining = tmux.list(workspace)
                    self.assertEqual([p["pane"] for p in remaining], [survivor])
                    self.assertEqual(remaining[0]["dead"], "0")
                finally:
                    if client is not None and client.poll() is None:
                        client.terminate()
                        client.wait(timeout=5)
                    os.close(master)
                    os.close(slave)
                    run(["tmux", "kill-session", "-t", "=" + tmux.session(workspace)])

    def test_close_only_private_panes_of_selected_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            sockets = root / "sockets"
            sockets.mkdir(mode=0o700)
            with patch.dict(os.environ, {"TMUX_TMPDIR": str(sockets)}):
                os.environ.pop("TMUX", None)
                service = Service(
                    Config(work_root=root / "work", source_root=root, state=root / "state")
                )
                workspace = service.create("close-terminal")
                tmux = Tmux()
                try:
                    run(
                        [
                            "tmux",
                            "-f",
                            "/dev/null",
                            "new-session",
                            "-d",
                            "-s",
                            "close-test-anchor",
                            "sleep",
                            "120",
                        ]
                    )
                    survivor = tmux.new(workspace, command=["sleep", "120"])
                    selected = tmux.new(workspace, command=["sleep", "120"], split=True)
                    foreign = run(
                        [
                            "tmux",
                            "new-session",
                            "-dP",
                            "-F",
                            "#{pane_id}",
                            "-s",
                            "foreign",
                            "sleep 120",
                        ]
                    )
                    with self.assertRaisesRegex(Error, "no longer available"):
                        tmux.close(workspace, foreign)
                    with self.assertRaisesRegex(Error, "no longer available"):
                        tmux.rename(workspace, foreign, "Foreign")
                    run(
                        [
                            "tmux",
                            "link-window",
                            "-s",
                            foreign,
                            "-t",
                            "=" + tmux.session(workspace) + ":",
                        ]
                    )
                    with self.assertRaisesRegex(Error, "no longer private"):
                        tmux.close(workspace, foreign)
                    with self.assertRaisesRegex(Error, "no longer private"):
                        tmux.rename(workspace, foreign, "Foreign")
                    tmux.close(workspace, selected)
                    self.assertEqual(
                        {pane["pane"] for pane in tmux.list(workspace)}, {survivor, foreign}
                    )
                    self.assertEqual(
                        run(["tmux", "list-panes", "-t", "foreign", "-F", "#{pane_id}"]), foreign
                    )
                finally:
                    with contextlib.suppress(Error):
                        run(["tmux", "kill-server"])

    def test_persistent_isolated_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            socket = root / "sockets"
            socket.mkdir(mode=0o700)
            # Dedicated socket directory means no interaction with user's tmux server.
            with patch.dict(os.environ, {"TMUX_TMPDIR": str(socket)}):
                service = Service(Config(root / "work", root, root / "state"))
                a, b = service.create("a"), service.create("b")
                tmux = Tmux()
                foreign = "foreign-test"
                run(["tmux", "new-session", "-d", "-s", foreign])
                try:
                    pane = tmux.new(a, command=["sleep", "120"])
                    tmux.new(b)
                    self.assertEqual(tmux.list(a)[0]["pane"], pane)
                    self.assertEqual(len(tmux.list(a)), 1)
                    # Recreate backend: server process survives manager lifetime.
                    self.assertEqual(Tmux().list(a)[0]["command"], "sleep")
                    self.assertNotEqual(tmux.list(a)[0]["pane"], tmux.list(b)[0]["pane"])
                    with self.assertRaises(Error):
                        tmux.attach(a, tmux.list(b)[0]["pane"])
                    run(["tmux", "has-session", "-t", "=" + foreign])
                finally:
                    for workspace in (a, b):
                        with contextlib.suppress(Error):
                            run(["tmux", "kill-session", "-t", "=" + tmux.session(workspace)])
                    run(["tmux", "kill-session", "-t", "=" + foreign])


@unittest.skipUnless(HAS_UI, "Textual unavailable; install .[dev]")
class WizardTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_with_first_repo_and_settings(self):
        from textual.widgets import Button, DataTable, Input, Select

        from workspace_manager.tui import AddRepo, Confirm, Create, Manager, Settings

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            source = root / "source"
            source.mkdir()
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
            app = Manager(service)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "config")}):
                async with app.run_test(size=(120, 50)) as pilot:
                    await app.workers.wait_for_complete()
                    await pilot.press("n")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, Create)
                    app.screen.query_one("#name", Input).value = "wizard"
                    app.screen.query_one("#preview", Button).press()
                    await pilot.pause()
                    self.assertIsInstance(app.screen, AddRepo)
                    app.screen.query_one("#source", Input).value = str(source)
                    app.screen.query_one("#name", Input).value = "repo"
                    app.screen.query_one("#branch", Input).value = "wizard-branch"
                    app.screen.query_one("#preview", Button).press()
                    for _ in range(40):
                        await pilot.pause(0.05)
                        if isinstance(app.screen, Confirm) and app.screen.query("#confirm"):
                            break
                    self.assertIsInstance(app.screen, Confirm)
                    app.screen.query_one("#confirm", Button).press()
                    await pilot.pause()
                    await app.workers.wait_for_complete()
                    self.assertEqual(app.query_one("#repos", DataTable).row_count, 1)
                    selected_workspace = app.query_one("#workspaces", DataTable)
                    self.assertEqual(
                        selected_workspace.ordered_rows[selected_workspace.cursor_row].key.value,
                        app.current,
                    )
                    self.assertEqual(app.selected().name, "wizard")
                    self.assertEqual(
                        service.status("wizard")["repos"]["repo"]["branch"], "wizard-branch"
                    )
                    await pilot.resize_terminal(80, 24)
                    await pilot.press("s")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, Settings)
                    app.screen.query_one("#global-agent", Select).value = "codex"
                    workspace_agent = app.screen.query_one("#workspace-agent", Select)
                    workspace_agent.focus()
                    await pilot.press("enter", "up", "enter")
                    self.assertIn(workspace_agent.value, {"inherit", "shell", "claude", "codex"})
                    workspace_agent.value = "claude"
                    app.screen.query_one("#save", Button).press()
                    for _ in range(40):
                        await pilot.pause(0.05)
                        if isinstance(app.screen, Confirm) and app.screen.query("#confirm"):
                            break
                    self.assertIsInstance(app.screen, Confirm)
                    app.screen.query_one("#confirm", Button).press()
                    await pilot.pause()
                    await app.workers.wait_for_complete()
                    self.assertEqual(service.get("wizard").default_agent, "claude")
                    self.assertEqual(Config.load().default_agent, "codex")


@unittest.skipUnless(HAS_UI, "Textual unavailable; install .[dev]")
class EmptyRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_keeps_empty_repository_form_and_shows_error(self):
        from textual.widgets import Button, Input, Static

        from workspace_manager.tui import AddRepo, Manager

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            service = Service(Config(root / "work", root, root / "state"))
            app = Manager(service)
            async with app.run_test(size=(120, 50)) as pilot:
                await app.workers.wait_for_complete()
                app.push_screen(AddRepo(root))
                await pilot.pause()
                form = app.screen
                form.query_one("#source", Input).value = str(source)
                form.query_one("#name", Input).value = "repo"
                form.query_one("#branch", Input).value = "feature"
                form.query_one("#preview", Button).press()
                await pilot.pause()
                for _ in range(40):
                    await pilot.pause(0.05)
                    if "first commit" in str(form.query_one("#error", Static).render()):
                        break
                self.assertIs(app.screen, form)
                self.assertIn("first commit", str(form.query_one("#error", Static).render()))
                self.assertEqual(form.query_one("#branch", Input).value, "feature")
                self.assertEqual(service.list(), [])
                self.assertFalse((root / "work").exists())
