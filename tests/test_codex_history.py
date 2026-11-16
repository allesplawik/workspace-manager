"""Public history protocol, scoped UI and exact native resume tests."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from workspace_manager.codex_history import CodexHistory, Conversation, HistoryPage
from workspace_manager.core import Config, Error, Service, run
from workspace_manager.terminal import AI

ID_A = "12345678-1234-1234-1234-123456789abc"
ID_B = "12345678-1234-1234-1234-123456789abd"


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_filters_foreign_cwd_and_preserves_pagination(self):
        rows = [
            {"id": ID_A, "cwd": str(self.root), "name": "A\n title", "updatedAt": 42},
            {"id": ID_B, "cwd": str(self.root / "other"), "preview": "Private other project"},
        ]
        with patch.object(
            CodexHistory, "_request", return_value={"data": rows, "nextCursor": "next"}
        ) as request:
            page = CodexHistory().list(self.root)
        self.assertEqual([c.id for c in page.conversations], [ID_A])
        self.assertEqual(page.conversations[0].title, "A title")
        self.assertEqual(page.next_cursor, "next")
        params = request.call_args.args[1]
        self.assertEqual(params["cwd"], str(self.root))
        self.assertEqual(params["sortKey"], "updated_at")
        self.assertTrue(params["useStateDbOnly"])

    def test_invalid_metadata_and_repeated_cursor_fail_closed(self):
        for result in (
            {"data": "wrong"},
            {"data": [{"cwd": str(self.root), "id": "--last"}]},
            {"data": [], "nextCursor": "same"},
        ):
            with (
                self.subTest(result=result),
                patch.object(CodexHistory, "_request", return_value=result),
                self.assertRaises(Error),
            ):
                CodexHistory().list(self.root, "same")

    def stub(self, body):
        script = self.root / "codex"
        script.write_text(f"#!{sys.executable}\n" + body)
        script.chmod(0o755)
        return patch(
            "workspace_manager.codex_history.CodexProvider.executable", return_value=str(script)
        )

    def test_real_stdio_handshake_and_only_metadata_methods(self):
        log = self.root / "requests"
        body = f"""
import json, sys
for line in sys.stdin:
    message = json.loads(line)
    with open({str(log)!r}, "a") as stream:
        stream.write(json.dumps(message) + "\\n")
    if message["method"] == "initialize":
        print(json.dumps({{"id": message["id"], "result": {{}}}}), flush=True)
    elif message["method"] == "thread/list":
        print(json.dumps({{"method": "notice", "params": {{}}}}), flush=True)
        print(json.dumps({{"id": message["id"], "result": {{"data": [], "nextCursor": None}}}}), flush=True)
"""
        with self.stub(body):
            self.assertEqual(CodexHistory().list(self.root), HistoryPage([], None))
        requests = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(
            [r["method"] for r in requests], ["initialize", "initialized", "thread/list"]
        )

    def test_timeout_and_output_limit(self):
        for body, timeout, cap, message in (
            ("import time; time.sleep(30)\n", 0.1, 4096, "timed out"),
            ("import sys; sys.stdout.write('x'*8192); sys.stdout.flush()\n", 2, 1024, "size limit"),
            ("print('not json', flush=True)\n", 2, 4096, "Cannot read"),
        ):
            with self.subTest(message=message), self.stub(body):
                history = CodexHistory()
                history.timeout, history.max_bytes = timeout, cap
                with self.assertRaisesRegex(Error, message):
                    history.list(self.root)

    def test_request_write_is_included_in_deadline(self):
        body = """
import json, sys, time
request = json.loads(sys.stdin.readline())
print(json.dumps({"id": request["id"], "result": {}}), flush=True)
time.sleep(30)
"""
        with self.stub(body):
            history = CodexHistory()
            history.timeout = 0.25
            started = time.monotonic()
            with self.assertRaisesRegex(Error, "timed out"):
                history.list(self.root, "\U0010ffff" * 8192)
            self.assertLess(time.monotonic() - started, 2)

    def test_term_ignoring_descendant_is_stopped_after_success(self):
        child_pid = self.root / "child-pid"
        leader_pid = self.root / "leader-pid"
        child = (
            "import os, signal, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            f"open({str(child_pid)!r}, 'w').write(str(os.getpid())); "
            "time.sleep(60)"
        )
        body = f"""
import json, os, subprocess, sys, time
from pathlib import Path
Path({str(leader_pid)!r}).write_text(str(os.getpid()))
subprocess.Popen([sys.executable, "-c", {child!r}])
while not Path({str(child_pid)!r}).exists():
    time.sleep(.01)
for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "initialize":
        print(json.dumps({{"id": request["id"], "result": {{}}}}), flush=True)
    elif request["method"] == "thread/list":
        print(json.dumps({{"id": request["id"], "result": {{"data": [], "nextCursor": None}}}}), flush=True)
"""
        try:
            with self.stub(body):
                self.assertEqual(CodexHistory().list(self.root), HistoryPage([], None))
            pid = int(child_pid.read_text())
            # An orphan may briefly remain as a zombie on CI; it must not execute.
            deadline = time.monotonic() + 2
            while True:
                state = subprocess.run(
                    ["ps", "-o", "stat=", "-p", str(pid)],
                    check=False,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                if not state or state.startswith("Z"):
                    break
                self.assertLess(time.monotonic(), deadline, "history descendant still running")
                time.sleep(0.02)
        finally:
            if leader_pid.exists():
                try:
                    os.killpg(int(leader_pid.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_resume_specific_conversation_never_reuses_arbitrary_live_pane(self):
        service = Service(Config(self.root / "work", self.root, self.root / "state"))
        workspace = service.create("sample")
        live = [{"pane": "%1", "kind": "codex", "cwd": workspace.path, "dead": "0"}]
        with (
            patch("workspace_manager.terminal.Tmux.list", return_value=live),
            patch("workspace_manager.terminal.Tmux._new", return_value="%2") as new,
            patch(
                "workspace_manager.providers.CodexProvider.command",
                return_value=["codex", "resume"],
            ),
        ):
            pane = AI(service.config).launch(workspace, "codex", "resume", session_id=ID_A)
        self.assertEqual(pane, "%2")
        self.assertEqual(new.call_args.args[2], ["codex", "resume", ID_A])
        with self.assertRaises(Error):
            AI(service.config).launch(workspace, "codex", "resume", session_id="--last")


class HistoryUITests(unittest.IsolatedAsyncioTestCase):
    async def test_workspace_repo_selection_and_click_to_resume(self):
        from textual.widgets import DataTable, Label

        from workspace_manager.tui import Manager

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            workspace = service.create("sample")
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
            service.add(workspace.id, source, "repo", "feature")
            workspace = service.get("sample")
            seen = []

            def history(cwd, cursor=None):
                seen.append((cwd, cursor))
                return HistoryPage(
                    [Conversation(ID_A, "Saved discussion", cwd, 42, "notLoaded")], None
                )

            app = Manager(service)
            with (
                patch("workspace_manager.tui.CodexHistory.list", side_effect=history),
                patch("workspace_manager.tui.AI.launch", return_value="%7") as launch,
                patch.object(app, "attach") as attach,
            ):
                async with app.run_test(size=(120, 65)) as pilot:
                    await app.workers.wait_for_complete()
                    table = app.query_one("#workspaces", DataTable)
                    table.scroll_visible(animate=False)
                    await pilot.pause()
                    await pilot.click("#workspaces", offset=(3, 1))
                    await app.workers.wait_for_complete()
                    self.assertEqual(seen[-1][0], Path(workspace.path))
                    self.assertEqual(app.query_one("#conversations", DataTable).row_count, 1)
                    from textual.widgets import Button

                    self.assertFalse(app.query_one("#history-native", Button).display)
                    repos = app.query_one("#repos", DataTable)
                    repos.scroll_visible(animate=False)
                    await pilot.pause()
                    await pilot.click("#repos", offset=(3, 1))
                    await app.workers.wait_for_complete()
                    self.assertEqual(seen[-1][0], Path(workspace.path) / "repo")
                    app.query_one("#conversations", DataTable).focus()
                    await pilot.press("enter")
                    await app.workers.wait_for_complete()
                    self.assertEqual(launch.call_args.kwargs["session_id"], ID_A)
                    self.assertEqual(launch.call_args.args[3], Path(workspace.path) / "repo")
                    attach.assert_called_once_with("%7")
                    self.assertIn("repo", str(app.query_one("#history-label", Label).render()))

    async def test_slow_old_scope_cannot_replace_new_scope(self):
        import asyncio
        import threading

        from workspace_manager.tui import Manager

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            first, second = service.create("first"), service.create("second")
            started, release = threading.Event(), threading.Event()
            seen = []

            def history(cwd, cursor=None):
                seen.append(cwd)
                if cwd == Path(first.path):
                    started.set()
                    release.wait(5)
                identifier = ID_A if cwd == Path(first.path) else ID_B
                return HistoryPage([Conversation(identifier, cwd.name, cwd, 42, "notLoaded")], None)

            app = Manager(service)
            with patch("workspace_manager.tui.CodexHistory.list", side_effect=history):
                async with app.run_test(size=(80, 24)):
                    await app.workers.wait_for_complete()
                    app.current = first.id
                    app.select_history(Path(first.path))
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    app.current = second.id
                    app.select_history(Path(second.path))
                    release.set()
                    await app.workers.wait_for_complete()
                    self.assertEqual(list(app.history_rows), [ID_B])
                    self.assertEqual(seen, [Path(first.path), Path(second.path)])

    async def test_pagination_failure_fallback_and_duplicate_resume(self):
        import asyncio
        import threading

        from textual.widgets import Button, DataTable, Label

        from workspace_manager.tui import Manager

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            workspace = service.create("sample")
            cwd = Path(workspace.path)
            pages = [
                HistoryPage([Conversation(ID_A, "One", cwd, 42, "notLoaded")], "older"),
                HistoryPage([Conversation(ID_B, "Two", cwd, 41, "notLoaded")], None),
            ]
            started, release = threading.Event(), threading.Event()

            def launch(*args, **kwargs):
                started.set()
                release.wait(5)
                return "%9"

            app = Manager(service)
            with (
                patch("workspace_manager.tui.CodexHistory.list", side_effect=pages) as history,
                patch("workspace_manager.tui.AI.launch", side_effect=launch) as resume,
                patch.object(app, "attach"),
            ):
                async with app.run_test(size=(120, 65)) as pilot:
                    await app.workers.wait_for_complete()
                    app.current = workspace.id
                    app.select_history(cwd)
                    await app.workers.wait_for_complete()
                    app.query_one("#history-more", Button).press()
                    await pilot.pause()
                    await app.workers.wait_for_complete()
                    self.assertEqual(history.call_args.args, (cwd, "older"))
                    self.assertEqual(app.query_one("#conversations", DataTable).row_count, 2)
                    self.assertTrue(app.query_one("#history-more", Button).disabled)
                    history.side_effect = Error("Unavailable: native picker available")
                    app.query_one("#history-refresh", Button).press()
                    await pilot.pause()
                    await app.workers.wait_for_complete()
                    self.assertIn(
                        "Unavailable", str(app.query_one("#history-label", Label).render())
                    )
                    self.assertFalse(app.query_one("#history-native", Button).disabled)
                    self.assertTrue(app.query_one("#history-native", Button).display)
                    app.resume_history(None)
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    app.resume_history(None)
                    release.set()
                    await app.workers.wait_for_complete()
                    self.assertEqual(resume.call_count, 1)
                    self.assertIsNone(resume.call_args.kwargs["session_id"])
                    history.side_effect = None
                    history.return_value = HistoryPage([], None)
                    app.select_history(cwd)
                    await app.workers.wait_for_complete()
                    self.assertFalse(app.query_one("#history-native", Button).display)
                    self.assertTrue(app.query_one("#history-native", Button).disabled)

    async def test_native_picker_modes_follow_provider(self):
        from textual.widgets import Select
        from textual.widgets._select import InvalidSelectValueError

        from workspace_manager.tui import Launch, Manager

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            workspace = service.create("sample")
            app = Manager(service)
            async with app.run_test(size=(120, 65)) as pilot:
                await app.workers.wait_for_complete()
                app.push_screen(Launch(workspace, "codex", True))
                await pilot.pause()
                mode = app.screen.query_one("#mode", Select)
                tool = app.screen.query_one("#provider", Select)
                with self.assertRaises(InvalidSelectValueError):
                    mode.value = "resume"
                mode.value = "continue"
                tool.value = "claude"
                await pilot.pause()
                mode.value = "resume"
                tool.value = "codex"
                await pilot.pause()
                self.assertEqual(mode.value, "new")
                with self.assertRaises(InvalidSelectValueError):
                    mode.value = "resume"
                tool.value = "shell"
                await pilot.pause()
                with self.assertRaises(InvalidSelectValueError):
                    mode.value = "continue"
