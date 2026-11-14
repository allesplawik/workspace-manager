"""Bounded handoffs shared across providers without silently losing concurrent updates."""

import concurrent.futures
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workspace_manager.core import Config, Error, Service
from workspace_manager.memory import INITIAL, MAX_CHARS, MAX_WORDS, Memory


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.service = Service(Config(self.root / "work", self.root, self.root / "state"))
        self.workspace = self.service.create("task")
        self.memory = Memory(self.workspace)

    def test_shared_file_and_instructions_survive_repeated_initialization(self):
        first = self.memory.read()
        self.memory.update(
            "# State\nDecision: use SQLite.\nNext: verify migration.\n", first["revision"]
        )
        self.service.context(self.workspace)
        self.assertIn("SQLite", Memory(self.service.get("task")).read()["content"])
        for name in ("AGENTS.md", "CLAUDE.md"):
            text = (Path(self.workspace.path) / name).read_text()
            self.assertEqual(text.count("## Shared workspace memory"), 1)
            self.assertIn(str(self.memory.path), text)
            self.assertIn("--revision", text)

    def test_limits_reject_without_truncating_or_changing_revision(self):
        first = self.memory.read()
        for content in ("x" * (MAX_CHARS + 1), "x " * (MAX_WORDS + 1), "", "a\0b"):
            with self.subTest(content_length=len(content)):
                with self.assertRaises(Error):
                    self.memory.update(content, first["revision"])
                self.assertEqual(self.memory.read(), first)
        bounded = "ą" * MAX_CHARS
        self.memory.update(bounded, first["revision"])
        self.assertEqual(self.memory.read()["content"], bounded)

    def test_only_one_concurrent_writer_wins_and_stale_writer_can_merge(self):
        revision = self.memory.read()["revision"]

        def write(text):
            try:
                Memory(self.workspace).update(text, revision)
                return True
            except Error:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["decision A", "decision B"]))
        self.assertEqual(sorted(results), [False, True])
        current = self.memory.read()
        self.memory.update(current["content"] + "\nNext: merge other finding", current["revision"])
        self.assertIn("merge other finding", self.memory.read()["content"])

    def test_atomic_failure_preserves_prior_summary(self):
        first = self.memory.read()
        with (
            patch("workspace_manager.core.os.replace", side_effect=OSError("disk error")),
            self.assertRaises(OSError),
        ):
            self.memory.update("new summary", first["revision"])
        self.assertEqual(self.memory.read(), first)

    def test_custom_instructions_and_existing_memory_are_preserved(self):
        agents = Path(self.workspace.path) / "AGENTS.md"
        agents.write_text("custom instructions")
        self.memory.path.write_text("custom summary")
        self.service.context(self.workspace)
        self.assertEqual(agents.read_text(), "custom instructions")
        self.assertEqual(self.memory.read()["content"], "custom summary")

    def test_legacy_workspace_is_upgraded_without_duplicate_instruction_blocks(self):
        for filename in ("AGENTS.md", "CLAUDE.md"):
            path = Path(self.workspace.path) / filename
            path.write_text(path.read_text().split("\n## Shared workspace memory")[0])
        self.memory.path.unlink()
        self.service.context(self.workspace)
        self.service.context(self.workspace)
        self.assertEqual(self.memory.read()["content"], INITIAL)
        for filename in ("AGENTS.md", "CLAUDE.md"):
            self.assertEqual(
                (Path(self.workspace.path) / filename)
                .read_text()
                .count("## Shared workspace memory"),
                1,
            )

    def test_symlink_refused_and_oversized_direct_edits_not_loaded(self):
        self.memory.path.unlink()
        outside = self.root / "outside"
        outside.write_text("precious")
        self.memory.path.symlink_to(outside)
        with self.assertRaises(Error):
            self.memory.read()
        self.assertEqual(outside.read_text(), "precious")
        self.memory.path.unlink()
        self.memory.path.write_text("x" * 20000)
        with self.assertRaises(Error):
            self.memory.read()
        self.assertEqual(self.memory.path.stat().st_size, 20000)

    def test_cli_json_revision_update_and_stale_write(self):
        from typer.testing import CliRunner

        from workspace_manager.cli import app

        runner = CliRunner()
        proposal = self.root / "proposal.md"
        proposal.write_text("# State\nTests passed; next: review.")
        with patch("workspace_manager.cli.Service", return_value=self.service):
            result = runner.invoke(app, ["memory", "show", "task", "--json"])
            self.assertEqual(result.exit_code, 0, result.output)
            snapshot = json.loads(result.output)
            command = [
                "memory",
                "update",
                "task",
                "--file",
                str(proposal),
                "--revision",
                snapshot["revision"],
            ]
            result = runner.invoke(app, command)
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(self.memory.read()["content"], proposal.read_text())
            self.assertNotEqual(runner.invoke(app, command).exit_code, 0)


class MemoryUITests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_shortcut_shows_workspace_summary_and_closes(self):
        from workspace_manager.tui import Manager, MemoryView

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            workspace = service.create("task")
            memory = Memory(workspace)
            memory.update("Decision: keep one shared summary.", memory.read()["revision"])
            app = Manager(service)
            async with app.run_test(size=(100, 35)) as pilot:
                await app.workers.wait_for_complete()
                app.current = workspace.id
                app.action_memory()
                for _ in range(40):
                    await pilot.pause(0.05)
                    if isinstance(app.screen, MemoryView):
                        break
                self.assertIsInstance(app.screen, MemoryView)
                self.assertIn("one shared summary", app.screen.snapshot["content"])
                await pilot.press("escape")
                self.assertNotIsInstance(app.screen, MemoryView)
