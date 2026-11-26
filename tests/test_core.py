"""Real Git integration tests; runnable with unittest as well as pytest."""

import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from workspace_manager.core import Config, Error, Git, Service, atomic, no_symlinks, run, safe_name
from workspace_manager.terminal import AI, Tmux


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.service = Service(
            Config(self.root / "work", self.root / "sources", self.root / "state")
        )
        self.source = self.root / "source with spaces"
        self.source.mkdir()
        run(["git", "init", "-b", "main", str(self.source)])
        run(["git", "-C", str(self.source), "config", "user.email", "test@example.invalid"])
        run(["git", "-C", str(self.source), "config", "user.name", "Test"])
        (self.source / "file").write_text("base\n")
        run(["git", "-C", str(self.source), "add", "file"])
        run(["git", "-C", str(self.source), "commit", "-m", "initial"])
        self.workspace = self.service.create("task")
        available = patch("workspace_manager.core.shutil_available", return_value=True)
        available.start()
        self.addCleanup(available.stop)

    def add(self, branch="task-branch", name="repo"):
        return self.service.add("task", self.source, name, branch)

    def test_create_metadata(self):
        self.assertEqual(self.service.get("task").phase, "ready")
        self.assertEqual(
            json.loads((Path(self.workspace.path) / ".wm/workspace.json").read_text())[
                "schema_version"
            ],
            1,
        )
        self.assertNotEqual(self.workspace.id, self.workspace.name)

    def test_source_unchanged_and_isolation(self):
        self.add()
        second = self.service.create("second")
        self.service.add(second.id, self.source, "repo", "different")
        (Path(self.workspace.path) / "repo/file").write_text("changed")
        self.assertEqual(Git.status(Path(second.path) / "repo")["status"], "clean")
        self.assertEqual(Git.status(self.source)["branch"], "main")
        self.assertEqual((self.source / "file").read_text(), "base\n")

    def test_second_repo_independent_branch(self):
        self.add()
        other = self.root / "other"
        run(["git", "clone", str(self.source), str(other)])
        self.service.add("task", other, "other", "independent")
        status = self.service.status("task")["repos"]
        self.assertEqual(status["repo"]["branch"], "task-branch")
        self.assertEqual(status["other"]["branch"], "independent")

    def test_occupied_branch_refused(self):
        with self.assertRaisesRegex(Error, "already"):
            self.service.add("task", self.source, "repo", "main", new=False)
        self.assertFalse((Path(self.workspace.path) / "repo").exists())

    def test_new_existing_branch_refused(self):
        with self.assertRaises(Error):
            self.add("main")
        self.assertEqual(self.service.get("task").repos[0].phase, "failed")

    def test_detached(self):
        self.add(None)
        self.assertTrue(
            self.service.status("task")["repos"]["repo"]["branch"].startswith("detached:")
        )

    def test_external_branch_change(self):
        self.add()
        path = Path(self.workspace.path) / "repo"
        run(["git", "-C", str(path), "switch", "-c", "external"])
        self.assertEqual(self.service.status("task")["repos"]["repo"]["branch"], "external")

    def test_status_dirty_untracked_missing_unknown(self):
        self.add()
        path = Path(self.workspace.path) / "repo"
        self.assertEqual(Git.status(path)["status"], "clean")
        (path / "new").write_text("untracked")
        self.assertEqual(Git.status(path)["status"], "modified")
        self.assertIn("?? new", Git.status(path)["changes"])
        (path / "file").write_text("modified")
        self.assertIn("file", Git.status(path)["changes"])
        self.assertEqual(Git.status(self.root / "absent")["status"], "missing")
        self.assertEqual(Git.status(self.root)["status"], "unknown")

    def test_error_status_never_clean(self):
        with patch("workspace_manager.core.run", side_effect=Error("permission denied")):
            self.assertEqual(Git.status(self.source)["status"], "unknown")

    def test_no_instruction_overwrite(self):
        path = Path(self.workspace.path) / "AGENTS.md"
        path.write_text("custom user content")
        self.service.context(self.workspace)
        self.assertEqual(path.read_text(), "custom user content")

    def test_existing_destination(self):
        path = self.root / "work" / "existing"
        path.mkdir()
        (path / "precious").write_text("data")
        with self.assertRaises(Error):
            self.service.create("existing")
        self.assertEqual((path / "precious").read_text(), "data")

    def test_invalid_names(self):
        for value in (
            "../escape",
            "/tmp/escape",
            "..",
            "a/b",
            "a;touch owned",
            "$(id)",
            "-flag",
            "",
        ):
            with self.subTest(value=value), self.assertRaises(Error):
                safe_name(value)

    def test_symlink_escape(self):
        link = Path(self.workspace.path) / "repo"
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(Error):
            self.add()
        with self.assertRaises(Error):
            no_symlinks(link / "file")

    def test_malicious_branch_ref(self):
        for branch in ("--force", "a;touch owned", "a/../b"):
            with self.subTest(branch=branch), self.assertRaises(Error):
                self.add(branch)
        with self.assertRaises(Error):
            self.service.add("task", self.source, "repo", "safe", ref="--help")
        self.assertFalse((self.root / "owned").exists())

    def test_atomic_failure_preserves_old(self):
        path = self.root / "atomic.json"
        atomic(path, {"old": True})
        with (
            patch("workspace_manager.core.os.replace", side_effect=PermissionError("denied")),
            self.assertRaises(PermissionError),
        ):
            atomic(path, {"new": True})
        self.assertEqual(json.loads(path.read_text()), {"old": True})
        self.assertFalse(list(self.root.glob(".wm-*")))

    def test_failed_git_journal(self):
        real_run = run

        def fail(args, cwd=None):
            if "add" in args and "worktree" in args:
                raise Error("simulated interruption")
            return real_run(args, cwd)

        with patch("workspace_manager.core.run", side_effect=fail), self.assertRaises(Error):
            self.add()
        self.assertEqual(self.service.get("task").repos[0].phase, "failed")
        self.assertEqual(self.service.status("task")["repos"]["repo"]["status"], "missing")

    def test_recovery_after_lost_index(self):
        atomic(self.service.registry, {"schema_version": 1, "workspaces": {}})
        self.assertEqual(self.service.list(), [])
        self.service.recover(Path(self.workspace.path))
        self.assertEqual(self.service.get("task").id, self.workspace.id)

    def test_recovery_reads_metadata_after_acquiring_registry_lock(self):
        from contextlib import contextmanager

        workspace = self.add()
        metadata = Path(workspace.path) / ".wm/workspace.json"
        original_lock = self.service.lock

        @contextmanager
        def lock_after_concurrent_write():
            with original_lock():
                workspace.repos[0].branch = "newer"
                atomic(metadata, workspace.encode())
                yield

        with patch.object(self.service, "lock", side_effect=lock_after_concurrent_write):
            recovered = self.service.recover(Path(workspace.path))
        self.assertEqual(recovered.repos[0].branch, "newer")
        self.assertEqual(self.service.get(workspace.id).repos[0].branch, "newer")

    def test_pending_not_claimed_ready(self):
        self.workspace.phase = "creating"
        self.service.save(self.workspace)
        self.assertEqual(self.service.get("task").phase, "creating")

    def test_unknown_schema_rejected(self):
        data = asdict(self.workspace)
        data["schema_version"] = 99
        with self.assertRaises(Error):
            type(self.workspace).decode(data)

    def test_missing_workspace(self):
        Path(self.workspace.path).rename(self.root / "moved")
        self.assertEqual(self.service.list()[0].phase, "missing")

    def test_from_arbitrary_cwd(self):
        old = Path.cwd()
        try:
            os.chdir(self.root)
            self.assertEqual(self.service.get("task").path, self.workspace.path)
            self.add()
        finally:
            os.chdir(old)

    def test_dirty_remove_blocked_and_clean_branch_retained(self):
        self.add()
        target = Path(self.workspace.path) / "repo"
        (target / "new").write_text("keep")
        with patch.object(Tmux, "list", return_value=[]):
            with self.assertRaises(Error):
                self.service.remove("task", "repo", True)
            self.assertEqual((target / "new").read_text(), "keep")
            (target / "new").unlink()
            self.service.remove("task", "repo", True)
        self.assertFalse(target.exists())
        self.assertIn("task-branch", run(["git", "-C", str(self.source), "branch", "--list"]))

    def test_active_terminal_blocks_removal(self):
        self.add()
        with (
            patch.object(Tmux, "list", return_value=[{"pane": "%1"}]),
            self.assertRaisesRegex(Error, "Active"),
        ):
            self.service.remove("task", "repo", True)

    def test_delete_requires_confirmation_and_preserves_files(self):
        with self.assertRaises(Error):
            self.service.delete("task")
        with patch.object(Tmux, "list", return_value=[]):
            self.service.delete("task", True)
        self.assertEqual(self.service.list(), [])
        self.assertTrue((Path(self.workspace.path) / "AGENTS.md").exists())

    def test_extra_files_block_delete(self):
        (Path(self.workspace.path) / "precious").write_text("preserve")
        with patch.object(Tmux, "list", return_value=[]), self.assertRaises(Error):
            self.service.delete("task", True)

    def test_missing_git(self):
        with (
            patch("workspace_manager.core.subprocess.run", side_effect=FileNotFoundError),
            self.assertRaisesRegex(Error, "Missing git"),
        ):
            Git.source(self.source)

    def test_missing_tmux(self):
        with patch("workspace_manager.terminal.shutil.which", return_value=None):
            self.assertEqual(Tmux().list(self.workspace), [])
            with self.assertRaisesRegex(Error, "tmux missing"):
                Tmux().new(self.workspace)

    def test_missing_optional_ai(self):
        with patch("workspace_manager.terminal.shutil.which", return_value=None):
            for tool in ("claude", "codex"):
                with self.assertRaisesRegex(Error, "Optional"):
                    AI().command(tool, "new")

    def test_claude_modes(self):
        with patch("workspace_manager.terminal.shutil.which", return_value="/bin/claude"):
            self.assertEqual(AI().command("claude", "new"), ["/bin/claude"])
            self.assertEqual(AI().command("claude", "resume"), ["/bin/claude", "--resume"])
            self.assertEqual(AI().command("claude", "continue"), ["/bin/claude", "--continue"])

    def test_codex_capability_detection(self):
        with (
            patch("workspace_manager.terminal.shutil.which", return_value="/bin/codex"),
            patch(
                "workspace_manager.providers.run",
                return_value="Commands:\n  resume Continue\n --last",
            ),
        ):
            self.assertEqual(AI().command("codex", "continue"), ["/bin/codex", "resume", "--last"])
            with (
                patch("workspace_manager.providers.run", return_value="no resume command"),
                self.assertRaises(Error),
            ):
                AI().command("codex", "resume")

    def test_foreign_tmux_not_adopted(self):
        import subprocess

        with (
            patch(
                "workspace_manager.terminal.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ),
            patch("workspace_manager.terminal.run", return_value="someone-else"),
            self.assertRaisesRegex(Error, "foreign"),
        ):
            Tmux().exists(self.workspace)

    def test_workspace_namespace(self):
        other = self.service.create("other")
        self.assertNotEqual(Tmux.session(other), Tmux.session(self.workspace))
        self.assertTrue(Tmux.session(other).startswith("wm-"))

    def test_ignored_files_block_removal(self):
        self.add()
        target = Path(self.workspace.path) / "repo"
        (target / ".gitignore").write_text("precious\n")
        run(["git", "-C", str(target), "add", ".gitignore"])
        run(["git", "-C", str(target), "commit", "-m", "ignore"])
        (target / "precious").write_text("must survive")
        self.assertEqual(Git.status(target)["status"], "clean")
        with patch.object(Tmux, "list", return_value=[]), self.assertRaisesRegex(Error, "Ignored"):
            self.service.remove("task", "repo", True)
        self.assertEqual((target / "precious").read_text(), "must survive")

    def test_repair_failed_entry_without_files(self):
        with self.assertRaises(Error):
            self.add("main")
        self.assertEqual(self.service.get("task").phase, "incomplete")
        self.service.repair_repo("task", "repo", True)
        self.assertEqual(self.service.get("task").repos, [])
        self.add("retry")
        self.assertEqual(self.service.get("task").phase, "ready")

    def test_repair_completed_git_before_metadata(self):
        self.add()
        workspace = self.service.get("task")
        workspace.repos[0].phase = "pending"
        workspace.phase = "incomplete"
        self.service.save(workspace)
        self.service.repair_repo("task", "repo", True)
        self.assertEqual(self.service.get("task").repos[0].phase, "ready")

    def test_switch_branch_preserves_files_and_other_worktrees(self):
        workspace = self.add()
        target = Path(workspace.path) / "repo"
        git = ["git", "-C", str(self.source)]
        run([*git, "branch", "review"])
        (target / "local").write_text("preserve")
        with self.assertRaisesRegex(Error, "Only clean"):
            self.service.switch_branch("task", "repo", "review", True)
        self.assertEqual((target / "local").read_text(), "preserve")
        (target / "local").unlink()
        with self.assertRaisesRegex(Error, "another worktree"):
            self.service.switch_branch("task", "repo", "main", True)
        with (
            patch.object(Tmux, "list", return_value=[{"pane": "%1", "dead": "0"}]),
            self.assertRaisesRegex(Error, "Active terminals"),
        ):
            self.service.switch_branch("task", "repo", "review", True)
        with self.assertRaisesRegex(Error, "confirmation"):
            self.service.switch_branch("task", "repo", "review")
        updated = self.service.switch_branch("task", "repo", "review", True)
        self.assertEqual(updated.repos[0].branch, "review")
        self.assertEqual(Git.status(target)["branch"], "review")
        self.assertEqual(Git.status(self.source)["branch"], "main")
        self.assertEqual(run([*git, "branch", "--list", "task-branch"]), "task-branch")
        reopened = Service(self.service.config)
        self.assertEqual(reopened.get("task").repos[0].branch, "review")

    def test_recovery_after_git_mutation_before_final_save(self):
        workspace = self.add()
        target = Path(workspace.path) / "repo"
        git = ["git", "-C", str(self.source)]
        run([*git, "branch", "review"])
        with (
            patch.object(self.service, "finish_repo_operation", side_effect=OSError("disk")),
            self.assertRaises(OSError),
        ):
            self.service.switch_branch("task", "repo", "review", True)
        self.assertEqual(Git.status(target)["branch"], "review")
        reopened = Service(self.service.config)
        self.assertEqual(reopened.get("task").repos[0].phase, "switching")
        repaired = reopened.repair_repo("task", "repo", True)
        self.assertEqual((repaired.phase, repaired.repos[0].branch), ("ready", "review"))

        with (
            patch.object(reopened, "finish_repo_operation", side_effect=OSError("disk")),
            self.assertRaises(OSError),
        ):
            reopened.remove("task", "repo", True)
        self.assertFalse(target.exists())
        self.assertEqual(reopened.get("task").repos[0].phase, "removing")
        self.assertEqual(reopened.repair_repo("task", "repo", True).repos, [])
        self.assertEqual(run([*git, "branch", "--list", "review"]), "review")

    def test_switch_refuses_readded_alias_using_original_confirmation(self):
        workspace = self.add()
        original = workspace.repos[0]
        self.service.remove("task", "repo", True)
        replacement = self.add("replacement")
        with self.assertRaisesRegex(Error, "changed after selection"):
            self.service.switch_branch("task", "repo", "main", True, expected_repo=original)
        with self.assertRaisesRegex(Error, "changed after selection"):
            self.service.remove("task", "repo", True, expected_repo=original)
        self.assertEqual(self.service.get("task").repos[0], replacement.repos[0])

    def test_recover_after_final_metadata_write_but_before_index(self):
        workspace = self.add()
        target = Path(workspace.path) / "repo"
        run(["git", "-C", str(self.source), "branch", "review"])

        def fail_final_index(path, data):
            if (
                path == self.service.registry
                and data["workspaces"][workspace.id]["phase"] == "ready"
            ):
                raise OSError("index write failed")
            atomic(path, data)

        with (
            patch("workspace_manager.core.atomic", side_effect=fail_final_index),
            self.assertRaisesRegex(OSError, "index write failed"),
        ):
            self.service.switch_branch("task", "repo", "review", True)
        self.assertEqual(Git.status(target)["branch"], "review")
        with self.assertRaisesRegex(Error, "workspace recover"):
            self.service.get("task").require_registered()
        self.service.recover(Path(workspace.path)).require_registered()
        self.assertEqual(self.service.get("task").repos[0].branch, "review")

    def test_tmux_permission_failure_is_not_absence(self):
        import subprocess

        result = subprocess.CompletedProcess([], 1, "", "permission denied")
        with (
            patch("workspace_manager.terminal.subprocess.run", return_value=result),
            self.assertRaisesRegex(Error, "Cannot inspect"),
        ):
            Tmux().exists(self.workspace)

    def test_untagged_tmux_pane_is_visible(self):
        with (
            patch.object(Tmux, "exists", return_value=True),
            patch("workspace_manager.terminal.shutil.which", return_value="/bin/tmux"),
            patch(
                "workspace_manager.terminal.run",
                return_value="%3\tsleep\t/work\t0\t\t\t/work\t10/20/30\twm-end",
            ),
        ):
            self.assertEqual(Tmux().list(self.workspace)[0]["kind"], "")

    def test_node_ai_process_is_reused(self):
        panes = [
            {
                "pane": "%1",
                "command": "node",
                "cwd": self.workspace.path,
                "kind": "codex",
                "dead": "0",
            }
        ]
        with patch.object(Tmux, "list", return_value=panes), patch.object(Tmux, "_new") as new:
            self.assertEqual(AI().launch(self.workspace, "codex"), "%1")
            new.assert_not_called()

    def test_nested_nonrepo_never_clean(self):
        child = self.source / "directory"
        child.mkdir()
        self.assertEqual(Git.status(child)["status"], "unknown")

    def test_remove_without_tmux_cannot_verify_safety(self):
        self.add()
        with (
            patch("workspace_manager.core.shutil_available", return_value=False),
            self.assertRaisesRegex(Error, "verify"),
        ):
            self.service.remove("task", "repo", True)

    def test_ignored_whitespace_filename_blocked(self):
        self.add()
        target = Path(self.workspace.path) / "repo"
        (target / ".gitignore").write_text("*\n")
        run(["git", "-C", str(target), "add", "-f", ".gitignore"])
        run(["git", "-C", str(target), "commit", "-m", "ignore"])
        (target / "   ").write_text("precious")
        with patch.object(Tmux, "list", return_value=[]), self.assertRaisesRegex(Error, "Ignored"):
            self.service.remove("task", "repo", True)
        self.assertEqual((target / "   ").read_text(), "precious")

    def test_assume_unchanged_modified_file_preserved(self):
        self.add()
        target = Path(self.workspace.path) / "repo"
        run(["git", "-C", str(target), "update-index", "--assume-unchanged", "file"])
        (target / "file").write_text("precious")
        self.assertEqual(Git.status(target)["status"], "clean")
        with patch.object(Tmux, "list", return_value=[]), self.assertRaisesRegex(Error, "Index"):
            self.service.remove("task", "repo", True)
        self.assertEqual((target / "file").read_text(), "precious")

    def test_create_with_repo_journals_before_git(self):
        seen = []
        actual_run = run

        def fail(args, cwd=None):
            if "worktree" in args and "add" in args:
                current = self.service.get("bundle")
                seen.append((current.phase, current.repos[0].phase))
                raise Error("simulated interruption")
            return actual_run(args, cwd)

        with patch("workspace_manager.core.run", side_effect=fail), self.assertRaises(Error):
            self.service.create(
                "bundle",
                first_repo={
                    "source": self.source,
                    "name": "repo",
                    "branch": "bundle",
                    "ref": "HEAD",
                    "new": True,
                },
            )
        self.assertEqual(seen, [("creating", "pending")])
        self.assertEqual(self.service.get("bundle").phase, "incomplete")
        self.service.repair_repo("bundle", "repo", True)
        self.assertEqual(self.service.get("bundle").repos, [])

    def test_concurrent_workspace_creates_keep_index_entries(self):
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(self.service.create, ["parallel1", "parallel2", "parallel3", "parallel4"])
            )
        self.assertEqual(len({workspace.id for workspace in results}), 4)
        self.assertEqual(len(self.service.list()), 5)


if __name__ == "__main__":
    unittest.main()
