"""Refresh keeps complete snapshots visible while status collection is pending."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import DataTable

from workspace_manager.core import Config, Error, Repo, Service
from workspace_manager.tui import Manager


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_refresh_and_details_keep_rows_and_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            first, second = service.create("first"), service.create("second")
            first.repos = [
                Repo("alpha", "source", phase="ready"),
                Repo("beta", "source", phase="ready"),
            ]
            status = "clean"

            async def states(workspace):
                return {
                    repo.name: {"branch": "main", "status": status, "changes": ""}
                    for repo in workspace.repos
                }

            panes = [
                {"pane": name, "command": "sh", "cwd": first.path, "dead": "0", "kind": "shell"}
                for name in ("%1", "%2")
            ]
            app = Manager(service)
            app.current = first.id
            with (
                patch.object(service, "list", return_value=[first, second]),
                patch.object(app, "repo_states", side_effect=states),
                patch("workspace_manager.tui.Tmux.list", return_value=panes),
            ):
                async with app.run_test(size=(120, 65)):
                    await app.workers.wait_for_complete()
                    tables = [
                        app.query_one("#" + name, DataTable)
                        for name in ("workspaces", "repos", "terminals")
                    ]
                    for table in tables:
                        table.move_cursor(row=1)
                    started, release = asyncio.Event(), asyncio.Event()

                    async def slow(workspace):
                        started.set()
                        await release.wait()
                        return await states(workspace)

                    with patch.object(app, "repo_states", side_effect=slow):
                        app.action_refresh()
                        await asyncio.wait_for(started.wait(), 2)
                        self.assertEqual([t.row_count for t in tables], [2, 2, 2])
                        self.assertEqual([t.cursor_row for t in tables], [1, 1, 1])
                        release.set()
                        await app.workers.wait_for_complete()
                        started.clear()
                        release.clear()
                        details = asyncio.create_task(app.details())
                        await asyncio.wait_for(started.wait(), 2)
                        try:
                            self.assertEqual([t.row_count for t in tables], [2, 2, 2])
                        finally:
                            release.set()
                            await details
                    with (
                        patch.object(tables[0], "clear", wraps=tables[0].clear) as workspace_clear,
                        patch.object(tables[1], "clear", wraps=tables[1].clear) as repo_clear,
                        patch.object(tables[2], "clear", wraps=tables[2].clear) as pane_clear,
                    ):
                        status = "modified"
                        app.action_refresh()
                        await app.workers.wait_for_complete()
                        workspace_clear.assert_not_called()
                        repo_clear.assert_not_called()
                        pane_clear.assert_not_called()
                        self.assertEqual(tables[0].get_row(first.id)[2], "modified")
                        self.assertEqual(tables[1].get_row("beta")[2], "modified (ready)")
                        self.assertEqual([t.cursor_row for t in tables], [1, 1, 1])
                    # Failed reads must leave the previous complete snapshot visible.
                    with patch.object(app, "repo_states", side_effect=Error("status unavailable")):
                        app.action_refresh()
                        await app.workers.wait_for_complete()
                        self.assertEqual([t.row_count for t in tables], [2, 2, 2])
                    table = tables[0]
                    app.sync_table(
                        table,
                        [
                            (second.id, tuple(table.get_row(second.id))),
                            (first.id, tuple(table.get_row(first.id))),
                        ],
                    )
                    self.assertEqual(table.ordered_rows[table.cursor_row].key.value, second.id)

    async def test_stale_details_cannot_replace_new_workspace_details(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            first, second = service.create("first"), service.create("second")
            first.repos = [Repo("alpha", "source", phase="ready")]
            second.repos = [Repo("beta", "source", phase="ready")]
            started, release = asyncio.Event(), asyncio.Event()
            block = False

            async def states(workspace):
                if block and workspace.id == first.id:
                    started.set()
                    await release.wait()
                return {
                    repo.name: {"branch": "main", "status": "clean", "changes": ""}
                    for repo in workspace.repos
                }

            app = Manager(service)
            app.current = first.id
            with (
                patch.object(service, "list", return_value=[first, second]),
                patch.object(app, "repo_states", side_effect=states),
                patch("workspace_manager.tui.Tmux.list", return_value=[]),
            ):
                async with app.run_test(size=(120, 65)):
                    await app.workers.wait_for_complete()
                    block = True
                    stale = asyncio.create_task(app.details())
                    await asyncio.wait_for(started.wait(), 2)
                    app.current = second.id
                    await app.details()
                    release.set()
                    await stale
                    table = app.query_one("#repos", DataTable)
                    self.assertEqual(table.get_row_at(0)[0], "beta")

    async def test_cache_membership_matches_snapshot_during_overlapping_refresh(self):
        from dataclasses import replace

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            first, second = service.create("first"), service.create("second")
            first.repos = [Repo("oldrepo", "source", phase="ready")]
            updated = replace(first, repos=[Repo("newrepo", "source", phase="ready")])
            started, release = asyncio.Event(), asyncio.Event()
            app = Manager(service)
            app.current = first.id
            native_states = app.repo_states
            block = False

            async def states(workspace):
                if block and workspace.id == second.id:
                    started.set()
                    await release.wait()
                return await native_states(workspace)

            with (
                patch.object(service, "list", return_value=[first, second]) as listing,
                patch.object(app, "repo_states", side_effect=states),
                patch(
                    "workspace_manager.tui.Git.status",
                    return_value={
                        "branch": "main",
                        "status": "clean",
                        "changes": "",
                    },
                ),
                patch("workspace_manager.tui.Tmux.list", return_value=[]),
            ):
                async with app.run_test(size=(120, 65)):
                    await app.workers.wait_for_complete()
                    listing.return_value = [updated, second]
                    block = True
                    app.action_refresh()
                    await asyncio.wait_for(started.wait(), 2)
                    try:
                        # Refresh has cached newrepo, but the published UI still
                        # refers to oldrepo. This read must get its matching cache.
                        await app.details()
                        self.assertEqual(
                            app.query_one("#repos", DataTable).get_row_at(0)[0], "oldrepo"
                        )
                    finally:
                        release.set()
                        await app.workers.wait_for_complete()
                    self.assertEqual(app.query_one("#repos", DataTable).get_row_at(0)[0], "newrepo")

    async def test_switch_invalidates_old_rows_and_history_before_slow_read(self):
        from workspace_manager.codex_history import Conversation, HistoryPage

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            service = Service(Config(root / "work", root, root / "state"))
            first, second = service.create("first"), service.create("second")
            first.repos = [Repo("oldrepo", "source", phase="ready")]
            second.repos = [Repo("newrepo", "source", phase="ready")]
            app = Manager(service)
            app.current = first.id
            started, release = asyncio.Event(), asyncio.Event()
            block = False

            async def states(workspace):
                if block and workspace.id == second.id:
                    started.set()
                    await release.wait()
                    raise Error("new workspace unavailable")
                return {
                    repo.name: {"branch": "main", "status": "clean", "changes": ""}
                    for repo in workspace.repos
                }

            def history(cwd, cursor=None):
                return HistoryPage(
                    [
                        Conversation(
                            "12345678-1234-1234-1234-123456789abc", "Saved", cwd, 42, "notLoaded"
                        )
                    ],
                    None,
                )

            with (
                patch.object(service, "list", return_value=[first, second]),
                patch.object(app, "repo_states", side_effect=states),
                patch(
                    "workspace_manager.tui.Tmux.list",
                    return_value=[
                        {
                            "pane": "%1",
                            "command": "sh",
                            "cwd": first.path,
                            "dead": "0",
                            "kind": "shell",
                        }
                    ],
                ),
                patch("workspace_manager.tui.CodexHistory.list", side_effect=history),
            ):
                async with app.run_test(size=(120, 65)) as pilot:
                    await app.workers.wait_for_complete()
                    app.select_history(Path(first.path))
                    await app.workers.wait_for_complete()
                    self.assertTrue(app.history_rows)
                    block = True
                    table = app.query_one("#workspaces", DataTable)
                    table.move_cursor(row=table.get_row_index(second.id))
                    table.action_select_cursor()
                    try:
                        await asyncio.wait_for(started.wait(), 2)
                        self.assertEqual(app.history_workspace, second.id)
                        self.assertEqual(app.query_one("#repos", DataTable).row_count, 0)
                        self.assertEqual(app.query_one("#terminals", DataTable).row_count, 0)
                        self.assertNotEqual(app.history_cwd, Path(first.path))
                    finally:
                        release.set()
                        await pilot.pause()
                    self.assertEqual(app.query_one("#repos", DataTable).row_count, 0)
