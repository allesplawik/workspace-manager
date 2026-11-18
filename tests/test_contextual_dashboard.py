"""UX-01..12 mouse/keyboard acceptance on the real Textual widget tree."""

import asyncio
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from textual import events
from textual.widgets import Button, DataTable, Footer, Input, Static

from workspace_manager.codex_history import Conversation, HistoryPage
from workspace_manager.core import Config, Error, Service, run
from workspace_manager.dashboard import DashboardSection, Information, SectionHeader, SectionMenu
from workspace_manager.tui import AddRepo, Confirm, Create, Launch, Manager

ID = "12345678-1234-1234-1234-123456789abc"


@asynccontextmanager
async def dashboard(*, filled=True, size=(110, 60), extra=0):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        service = Service(Config(root / "work", root, root / "state"))
        workspace = service.create("sample")
        if filled:
            source = root / "source"
            run(["git", "init", "-b", "main", str(source)])
            (source / "seed").write_text("original source\n")
            run(["git", "-C", str(source), "add", "seed"])
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
                    "-m",
                    "initial",
                ]
            )
            service.add(workspace.id, source, "alpha", "alpha-branch")
            service.add(workspace.id, source, "beta", "beta-branch")
            workspace = service.get(workspace.id)
        for index in range(extra):
            service.create("extra-" + str(index))
        panes = (
            [
                {"pane": pane, "command": "sh", "cwd": workspace.path, "dead": "0", "kind": "shell"}
                for pane in ("%1", "%2")
            ]
            if filled
            else []
        )

        def history(cwd, cursor=None):
            return (
                HistoryPage([Conversation(ID, "Saved discussion", cwd, 42, "notLoaded")], None)
                if filled
                else HistoryPage([], None)
            )

        app = Manager(service)
        with (
            patch("workspace_manager.tui.Tmux.list", return_value=panes),
            patch("workspace_manager.tui.CodexHistory.list", side_effect=history),
            patch("workspace_manager.providers.AgentProvider.available", return_value=True),
            patch.object(app, "attach") as attach,
        ):
            async with app.run_test(size=size) as pilot:
                await app.workers.wait_for_complete()
                yield app, pilot, service, workspace, attach


async def click(pilot, app, selector, offset=None):
    app.query_one(selector).scroll_visible(animate=False)
    await pilot.pause()
    if offset is None:
        await pilot.click(selector)
    else:
        await pilot.click(selector, offset=offset)
    await pilot.pause()


async def select_workspace(app, workspace):
    table = app.query_one("#workspaces", DataTable)
    table.move_cursor(row=table.get_row_index(workspace.id))
    await app.choose_row("workspaces", workspace.id)
    await app.workers.wait_for_complete()


class ContextualDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_headers_counts_empty_and_context(self):
        async with dashboard() as (app, _pilot, _service, workspace, attach):
            self.assertEqual(len(app.query(SectionHeader)), 4)
            self.assertTrue(app.query_one("#repo-add", Button).disabled)
            await select_workspace(app, workspace)
            self.assertEqual([h.count for h in app.query(SectionHeader)], [1, 2, 2, 1])
            self.assertFalse(app.query_one("#repo-add", Button).disabled)
            self.assertFalse(app.query_one("#terminal-attach", Button).disabled)
            self.assertTrue(app.query_one("#history-native", Button).display)
            attach.assert_not_called()
        async with dashboard(filled=False) as (app, _pilot, _service, workspace, attach):
            await select_workspace(app, workspace)
            self.assertFalse(app.query_one("#conversations", DataTable).display)
            self.assertTrue(app.query_one("#history-empty", Static).display)
            self.assertLessEqual(app.query_one("#history-section").size.height, 6)

    async def test_mouse_only_selects_rows_enter_and_space_activate(self):
        async with dashboard() as (app, pilot, _service, workspace, attach):
            await click(pilot, app, "#workspaces", (3, 1))
            await app.workers.wait_for_complete()
            self.assertEqual(app.current, workspace.id)
            await click(pilot, app, "#repos", (3, 2))
            await app.workers.wait_for_complete()
            self.assertEqual(app.history_cwd, Path(workspace.path) / "beta")
            self.assertEqual(len(app.screen_stack), 1)
            await click(pilot, app, "#terminals", (3, 2))
            await click(pilot, app, "#terminals", (3, 2))
            attach.assert_not_called()
            self.assertEqual(app.focused.id if app.focused else None, "terminals")
            await pilot.press("enter")
            attach.assert_called_once_with("%2")
            with patch.object(app, "resume_history") as resume:
                await click(pilot, app, "#conversations", (3, 1))
                resume.assert_not_called()
                await pilot.press("space")
                resume.assert_called_once_with(ID)

    async def test_queued_terminal_activation_does_not_attach_replacement_row(self):
        async with dashboard() as (app, pilot, _service, workspace, attach):
            await select_workspace(app, workspace)
            table = app.query_one("#terminals", DataTable)
            table.move_cursor(row=0)
            table.action_select_cursor()
            table.move_cursor(row=1)
            await pilot.pause()
            attach.assert_not_called()

    async def test_double_click_activates_terminal_and_conversation_once(self):
        async with dashboard() as (app, pilot, _service, workspace, attach):
            await select_workspace(app, workspace)
            table = app.query_one("#terminals")
            table.scroll_visible()
            await pilot.pause()
            await pilot.click("#terminals", offset=(3, 2), times=3)
            await pilot.pause()
            attach.assert_called_once_with("%2")
            with patch.object(app, "resume_history") as resume:
                app.query_one("#conversations").scroll_visible()
                await pilot.pause()
                await pilot.click("#conversations", offset=(3, 1), times=2)
                await pilot.pause()
                resume.assert_called_once_with(ID)

    async def test_right_then_left_click_does_not_activate_terminal(self):
        async with dashboard() as (app, pilot, _service, workspace, attach):
            await select_workspace(app, workspace)
            table = app.query_one("#terminals", DataTable)
            table.scroll_visible(animate=False)
            await pilot.pause()
            x, y = table.region.x + 3, table.region.y + 1
            for button in (3, 1):
                for event in (events.MouseDown, events.MouseUp):
                    await app.on_event(event(None, x, y, 0, 0, button, False, False, False))
                await pilot.pause()
            attach.assert_not_called()

    async def test_double_click_header_does_not_activate(self):
        async with dashboard() as (app, pilot, _service, workspace, attach):
            await select_workspace(app, workspace)
            app.query_one("#terminals").scroll_visible()
            await pilot.pause()
            await pilot.click("#terminals", offset=(3, 0), times=2)
            await pilot.pause()
            attach.assert_not_called()

    async def test_workspace_click_restores_root_history_after_repository(self):
        async with dashboard() as (app, pilot, _service, workspace, attach):
            root = Path(workspace.path)

            def history(cwd, cursor=None):
                return HistoryPage(
                    [Conversation(ID, "Workspace discussion", cwd, 42, "notLoaded")]
                    if cwd == root
                    else [],
                    None,
                )

            with patch("workspace_manager.tui.CodexHistory.list", side_effect=history) as listing:
                await click(pilot, app, "#workspaces", (3, 1))
                await app.workers.wait_for_complete()
                self.assertEqual(app.history_cwd, root)
                self.assertEqual(app.query_one("#conversations", DataTable).row_count, 1)
                for repo_row in (1, 2):
                    await click(pilot, app, "#repos", (3, repo_row))
                    await app.workers.wait_for_complete()
                    self.assertNotEqual(app.history_cwd, root)
                    self.assertEqual(app.query_one("#conversations", DataTable).row_count, 0)
                    await click(pilot, app, "#workspaces", (3, 1))
                    await app.workers.wait_for_complete()
                    self.assertEqual(app.history_cwd, root)
                    self.assertEqual(app.query_one("#conversations", DataTable).row_count, 1)
                    self.assertEqual(app.history_rows[ID].title, "Workspace discussion")
                self.assertEqual(listing.call_count, 5)
                attach.assert_not_called()

    async def test_buttons_and_existing_shortcuts_share_actions(self):
        async with dashboard() as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            button = app.query_one("#workspace-new", Button)
            button.scroll_visible(animate=False)
            await pilot.pause()
            await pilot.hover("#workspace-new")
            self.assertTrue(button.is_mouse_over)
            self.assertIsNotNone(button.tooltip)
            with patch.object(app, "action_create") as create:
                await click(pilot, app, "#workspace-new")
                await pilot.press("n")
                self.assertEqual(create.call_count, 2)
            with patch.object(app, "launch_ai") as launch:
                await click(pilot, app, "#terminal-new")
                await pilot.press("t", "v", "c", "x")
                self.assertEqual(launch.call_count, 5)
                self.assertEqual(launch.call_args.args, ("codex",))
            keys = {binding.key for binding in Manager.BINDINGS}
            self.assertTrue(set("natvcxgsmdq").issubset(keys))
            footer = app.query_one(Footer)
            self.assertLessEqual(footer.size.height, 1)
            shown = [b.key for b in Manager.BINDINGS if b.show]
            self.assertEqual(shown, ["question_mark", "enter", "q"])

    async def test_close_terminal_requires_confirmation(self):
        async with dashboard() as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            with patch("workspace_manager.tui.Tmux.close") as close:
                for response in ("escape", "confirm"):
                    app.open_menu("terminal")
                    await pilot.pause()
                    await pilot.click("#terminal-close")
                    await pilot.pause()
                    close.assert_not_called()
                    self.assertEqual(app.focused.id, "cancel")
                    if response == "escape":
                        await pilot.press("escape")
                    else:
                        await pilot.click("#confirm")
                    await app.workers.wait_for_complete()
                close.assert_called_once_with(workspace, app.selected_key("terminals"))

    async def test_close_survives_refresh_replacement(self):
        async with dashboard() as (app, pilot, service, workspace, _attach):
            await select_workspace(app, workspace)
            started, release = threading.Event(), threading.Event()
            original_list = service.list

            def list_workspaces():
                if not started.is_set():
                    started.set()
                    release.wait(5)
                return original_list()

            with (
                patch.object(service, "list", side_effect=list_workspaces),
                patch("workspace_manager.tui.Tmux.close") as close,
            ):
                try:
                    app.dispatch("terminal-close")
                    await pilot.pause()
                    await pilot.click("#confirm")
                    self.assertTrue(await asyncio.to_thread(started.wait, 3))
                    first_refresh = app.refresh_worker
                    await pilot.press("r")
                    self.assertIsNot(app.refresh_worker, first_refresh)
                    await app.workers.wait_for_complete()
                    close.assert_called_once_with(workspace, "%1")
                    self.assertFalse(app.dialog_busy)
                    self.assertTrue(app.is_running)
                finally:
                    release.set()

    async def test_create_preserves_history_scope_if_new_workspace_is_filtered_out(self):
        async with dashboard() as (app, _pilot, service, workspace, _attach):
            await select_workspace(app, workspace)
            refresh = app.refresh_after_operation

            async def refresh_with_filter():
                with app.prevent(Input.Changed):
                    app.query_one("#search", Input).value = workspace.name
                await refresh()

            repo = {
                "source": service.config.source_root / "source",
                "name": "fresh-repo",
                "branch": "fresh-branch",
                "ref": "HEAD",
                "new": True,
            }
            with (
                patch.object(
                    app,
                    "push_screen_wait",
                    side_effect=[
                        {"name": "fresh", "location": service.config.work_root},
                        repo,
                        True,
                    ],
                ),
                patch.object(app, "refresh_after_operation", side_effect=refresh_with_filter),
            ):
                app.action_create()
                await app.workers.wait_for_complete()

            self.assertEqual(service.get("fresh").repos[0].name, "fresh-repo")
            self.assertEqual(app.current, workspace.id)
            self.assertEqual(app.history_cwd, Path(workspace.path))

    async def test_workspace_menu_can_open_initial_highlight(self):
        async with dashboard() as (app, pilot, _service, workspace, _attach):
            self.assertIsNone(app.current)
            app.open_menu("workspace")
            await pilot.pause()
            await pilot.click("#workspace-open")
            await app.workers.wait_for_complete()
            self.assertEqual(app.current, workspace.id)

    async def test_terminal_menu_survives_unrelated_history_refresh(self):
        async with dashboard() as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            app.open_menu("terminal")
            await pilot.pause()
            app.select_history(Path(workspace.path) / "alpha")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.click("#terminal-close")
            await pilot.pause()
            self.assertIsInstance(app.screen, Confirm)
            await pilot.press("escape")
            await app.workers.wait_for_complete()

    async def test_menu_mouse_keyboard_disabled_and_single_menu(self):
        async with dashboard() as (app, pilot, _service, workspace, _attach):
            await click(pilot, app, "#repo-menu")
            self.assertIsInstance(app.screen, SectionMenu)
            self.assertTrue(app.screen.query_one("#repo-remove", Button).disabled)
            await pilot.click("#repo-remove")
            self.assertIsInstance(app.screen, SectionMenu)
            await pilot.press("escape")
            self.assertEqual(len(app.screen_stack), 1)
            await select_workspace(app, workspace)
            app.open_menu("workspace")
            await pilot.pause()
            # The anchored workspace popover may cover the repo header; use
            # another visible overflow button rather than clicking through it.
            button = app.query_one("#history-menu", Button)
            await pilot.click(
                offset=(
                    button.region.x + button.region.width // 2,
                    button.region.y + button.region.height // 2,
                )
            )
            await pilot.pause()
            self.assertEqual(len(app.screen_stack), 2)
            self.assertIsInstance(app.screen, SectionMenu)
            self.assertFalse(app.screen.query_one("#history-details", Button).disabled)
            await pilot.press("down", "up", "tab", "shift+tab", "escape")
            self.assertEqual(len(app.screen_stack), 1)
            app.open_menu("history")
            await pilot.pause()
            await pilot.click("#history-details")
            await pilot.pause()
            self.assertIsInstance(app.screen, Information)
            self.assertIn(ID, str(app.screen.query_one("#info-content", Static).render()))
            await pilot.press("escape")
            await app.workers.wait_for_complete()

    async def test_cancel_focus_and_duplicate_wizard_gate(self):
        async with dashboard() as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            button = app.query_one("#workspace-new", Button)
            button.scroll_visible(animate=False)
            button.focus()
            await pilot.pause()
            await pilot.press("space")
            app.action_create()
            app.action_add()
            await pilot.pause()
            self.assertIsInstance(app.screen, Create)
            self.assertEqual(len(app.screen_stack), 2)
            await pilot.press("escape")
            await app.workers.wait_for_complete()
            self.assertIs(app.focused, button)
            self.assertEqual(app.current, workspace.id)
            self.assertFalse(app.dialog_busy)
            await click(pilot, app, "#repo-add")
            self.assertIsInstance(app.screen, AddRepo)
            await pilot.press("escape")
            await app.workers.wait_for_complete()
            self.assertEqual(app.current, workspace.id)
            self.assertIs(app.focused, app.query_one("#repo-add"))

    async def test_repo_menu_remove_has_confirmation_and_dirty_safety(self):
        async with dashboard() as (app, pilot, service, workspace, attach):
            await select_workspace(app, workspace)
            repo = Path(workspace.path) / "alpha"
            (repo / "untracked").write_text("keep me")
            original = (service.config.source_root / "source/seed").read_text()
            app.open_menu("repo")
            await pilot.pause()
            await pilot.click("#repo-remove")
            await pilot.pause()
            self.assertIsInstance(app.screen, Confirm)
            with patch("workspace_manager.terminal.Tmux.list", return_value=[]):
                await pilot.click("#confirm")
                await app.workers.wait_for_complete()
            self.assertTrue((repo / "untracked").exists())
            self.assertEqual((service.config.source_root / "source/seed").read_text(), original)
            self.assertEqual(len(service.get(workspace.id).repos), 2)
            attach.assert_not_called()

    async def test_removing_scoped_repo_restores_workspace_history(self):
        async with dashboard() as (app, pilot, service, workspace, _attach):
            await select_workspace(app, workspace)
            await app.choose_row("repos", "alpha")
            await app.workers.wait_for_complete()
            self.assertEqual(app.history_cwd, Path(workspace.path) / "alpha")
            with patch("workspace_manager.terminal.Tmux.list", return_value=[]):
                app.open_menu("repo")
                await pilot.pause()
                await pilot.click("#repo-remove")
                await pilot.pause()
                await pilot.click("#confirm")
                await app.workers.wait_for_complete()
            self.assertEqual([repo.name for repo in service.get(workspace.id).repos], ["beta"])
            self.assertEqual(app.history_cwd, Path(workspace.path))

    async def test_resize_scroll_collapse_and_selection_retained(self):
        async with dashboard(extra=18, size=(100, 45)) as (
            app,
            pilot,
            _service,
            _workspace,
            _attach,
        ):
            table = app.query_one("#workspaces", DataTable)
            table.move_cursor(row=12)
            key = table.ordered_rows[table.cursor_row].key.value
            table.focus()
            await pilot.pause()
            await pilot.resize_terminal(48, 24)
            await pilot.pause()
            self.assertEqual(table.ordered_rows[table.cursor_row].key.value, key)
            self.assertGreater(table.max_scroll_y, 0)
            await pilot.press("pagedown")
            await pilot.pause()
            await app.workers.wait_for_complete()
            self.assertGreaterEqual(table.cursor_row, 12)
            for header in app.query(SectionHeader):
                for button in header.query(Button):
                    self.assertLessEqual(button.region.right, app.size.width)
            for section in app.query(DashboardSection):
                section.toggle()
                self.assertFalse(section.query_one("#" + section.section + "-content").display)
            app.action_refresh()
            await app.workers.wait_for_complete()
            self.assertTrue(all(section.collapsed for section in app.query(DashboardSection)))
            await pilot.resize_terminal(120, 65)
            await pilot.pause()
            for section in app.query(DashboardSection):
                section.toggle()
            self.assertTrue(table.display)

    async def test_keyboard_navigation_help_and_missing_provider(self):
        async with dashboard() as (app, pilot, _service, workspace, attach):
            await select_workspace(app, workspace)
            app.query_one("#workspaces", DataTable).focus()
            before = app.focused
            await pilot.press("tab")
            self.assertIsNot(app.focused, before)
            await pilot.press("shift+tab")
            self.assertIs(app.focused, before)
            await pilot.press("question_mark")
            await pilot.pause()
            self.assertIsInstance(app.screen, Information)
            await pilot.press("escape")
            await app.workers.wait_for_complete()
            with patch("workspace_manager.providers.CodexProvider.available", return_value=False):
                app.open_menu("terminal")
                await pilot.pause()
                self.assertTrue(app.screen.query_one("#terminal-codex", Button).disabled)
                self.assertIn(
                    "not installed", str(app.screen.query_one("#terminal-codex", Button).tooltip)
                )
                await pilot.press("escape")
                await pilot.press("x")
                await pilot.pause()
                self.assertIsInstance(app.screen, Launch)
                with patch(
                    "workspace_manager.providers.CodexProvider.executable",
                    side_effect=Error("Optional AI tool codex is not installed"),
                ):
                    app.screen.query_one("#launch", Button).press()
                    await pilot.pause()
                    await app.workers.wait_for_complete()
                self.assertIn("not installed", str(app.query_one("#message", Static).render()))
            attach.assert_not_called()

    async def test_add_repo_selects_new_worktree_and_cancel_keeps_selection(self):
        async with dashboard() as (app, pilot, service, workspace, _attach):
            await select_workspace(app, workspace)
            app.focus_row("repos", "beta")
            await click(pilot, app, "#repo-add")
            app.screen.query_one("#source", Input).value = str(
                service.config.source_root / "source"
            )
            app.screen.query_one("#name", Input).value = "gamma"
            app.screen.query_one("#branch", Input).value = "gamma-branch"
            app.screen.query_one("#preview", Button).press()
            for _ in range(40):
                await pilot.pause(0.05)
                if isinstance(app.screen, Confirm):
                    break
            self.assertIsInstance(app.screen, Confirm)
            app.screen.query_one("#confirm", Button).press()
            await pilot.pause()
            await app.workers.wait_for_complete()
            table = app.query_one("#repos", DataTable)
            self.assertEqual(table.ordered_rows[table.cursor_row].key.value, "gamma")
            self.assertEqual(app.history_cwd, Path(workspace.path) / "gamma")
            await click(pilot, app, "#repo-add")
            await pilot.press("escape")
            await app.workers.wait_for_complete()
            self.assertEqual(table.ordered_rows[table.cursor_row].key.value, "gamma")
            self.assertEqual(len(service.get(workspace.id).repos), 3)

    async def test_refresh_keeps_history_selection_and_handles_removed_workspace(self):
        async with dashboard() as (app, _pilot, service, workspace, _attach):
            await select_workspace(app, workspace)
            section = app.query_one("#history-section", DashboardSection)
            section.toggle()
            app.dispatch("history-refresh")
            await app.workers.wait_for_complete()
            self.assertEqual(app.selected_key("conversations"), ID)
            self.assertTrue(section.collapsed)
            with patch.object(service, "list", return_value=[]):
                app.action_refresh()
                await app.workers.wait_for_complete()
            self.assertIsNone(app.current)
            self.assertEqual(
                [
                    app.query_one("#" + name, DataTable).row_count
                    for name in ("workspaces", "repos", "terminals", "conversations")
                ],
                [0, 0, 0, 0],
            )
            self.assertTrue(app.query_one("#terminal-attach", Button).disabled)

    async def test_filter_reconciles_action_scope_with_visible_workspace(self):
        from workspace_manager.tui import Settings

        async with dashboard(extra=2) as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            app.query_one("#search", Input).value = "extra-1"
            await pilot.pause()
            await app.workers.wait_for_complete()
            key = app.selected_key("workspaces")
            self.assertEqual(app.current, key)
            self.assertEqual(app.selected().name, "extra-1")
            self.assertEqual(app.details_workspace, key)
            self.assertEqual(app.history_workspace, key)
            app.dispatch("workspace-settings")
            await pilot.pause()
            self.assertIsInstance(app.screen, Settings)
            self.assertEqual(app.screen.workspace.id, key)
            await pilot.press("escape")
            await app.workers.wait_for_complete()
            app.query_one("#search", Input).value = "no matching workspace"
            await pilot.pause()
            await app.workers.wait_for_complete()
            self.assertIsNone(app.current)
            self.assertEqual(app.query_one("#repos", DataTable).row_count, 0)
            self.assertTrue(app.query_one("#terminal-new", Button).disabled)

    async def test_ctrl_home_end_keep_workspace_and_repo_scope_in_sync(self):
        async with dashboard(extra=3) as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            table = app.query_one("#workspaces", DataTable)
            table.focus()
            for key in ("ctrl+home", "ctrl+end"):
                await pilot.press(key)
                await pilot.pause()
                await app.workers.wait_for_complete()
                self.assertEqual(app.current, app.selected_key("workspaces"))
                self.assertEqual(app.history_workspace, app.current)
            await select_workspace(app, workspace)
            repos = app.query_one("#repos", DataTable)
            repos.focus()
            for key in ("ctrl+end", "ctrl+home"):
                await pilot.press(key)
                await pilot.pause()
                await app.workers.wait_for_complete()
                self.assertEqual(app.history_cwd, Path(workspace.path) / app.selected_key("repos"))

    async def test_resuming_disables_keyboard_wizards_and_menus(self):
        import asyncio
        import threading

        async with dashboard() as (app, _pilot, _service, workspace, attach):
            await select_workspace(app, workspace)
            started, release = threading.Event(), threading.Event()

            def launch(*args, **kwargs):
                started.set()
                release.wait(5)
                return "%3"

            with patch("workspace_manager.tui.AI.launch", side_effect=launch):
                app.resume_history(ID)
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                try:
                    self.assertTrue(app.history_resuming)
                    self.assertIsNone(app.action_create())
                    self.assertIsNone(app.action_add())
                    self.assertIsNone(app.launch_ai("codex"))
                    app.open_menu("workspace")
                    self.assertEqual(len(app.screen_stack), 1)
                    self.assertFalse(app.dialog_busy)
                finally:
                    release.set()
                    await app.workers.wait_for_complete()
                attach.assert_called_once_with("%3")

    async def test_terminal_launch_does_not_attach_after_workspace_switch(self):
        import asyncio
        import threading

        async with dashboard(extra=1) as (app, pilot, _service, workspace, attach):
            await select_workspace(app, workspace)
            started, release = threading.Event(), threading.Event()

            def launch(*args, **kwargs):
                started.set()
                release.wait(5)
                return "%created-in-original"

            with patch("workspace_manager.tui.AI.launch", side_effect=launch):
                app.launch_ai("shell", True)
                await pilot.pause()
                app.screen.query_one("#launch", Button).press()
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                try:
                    other = next(key for key in app.values if key != workspace.id)
                    await app.choose_row("workspaces", other)
                finally:
                    release.set()
                    await app.workers.wait_for_complete()
                attach.assert_not_called()
                self.assertEqual(app.current, other)
                self.assertIn(
                    "Terminal started in sample", str(app.query_one("#message", Static).render())
                )

    async def test_missing_codex_disables_resume_but_preserves_details(self):
        async with dashboard() as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            with patch("workspace_manager.providers.CodexProvider.available", return_value=False):
                app.open_menu("history")
                await pilot.pause()
                resume = app.screen.query_one("#history-resume", Button)
                self.assertTrue(resume.disabled)
                self.assertIn("not installed", str(resume.tooltip))
                self.assertFalse(app.screen.query_one("#history-details", Button).disabled)
                await pilot.press("escape")
