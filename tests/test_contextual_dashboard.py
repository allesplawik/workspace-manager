"""UX-01..12 mouse/keyboard acceptance on the real Textual widget tree."""

import asyncio
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from rich.style import Style
from textual import events
from textual.css.query import NoMatches
from textual.widgets import Button, DataTable, Footer, Input, OptionList, Select, Static

from workspace_manager.codex_history import CodexHistory, Conversation, HistoryPage
from workspace_manager.context_views import GlobalSessions, HistoryBrowser, HistoryChoice
from workspace_manager.conversation_titles import ConversationTitles
from workspace_manager.core import Config, Error, Service, run
from workspace_manager.dashboard import (
    DashboardSection,
    ExplorerTree,
    Information,
    SectionHeader,
    SectionMenu,
    SessionCards,
    WorkspaceExplorer,
)
from workspace_manager.terminal import AI, Tmux
from workspace_manager.tui import AddRepo, Confirm, Create, Launch, Manager

ID = "12345678-1234-1234-1234-123456789abc"


@asynccontextmanager
async def dashboard(*, filled=True, size=(110, 60), extra=0, integrated=False, many_sessions=False):
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

        if integrated:
            panes[0].update(cwd=str(Path(workspace.path) / "alpha"), kind="codex")
            panes[1].update(cwd=str(Path(workspace.path) / "beta"), kind="claude", dead="1")
        if many_sessions:
            panes[0]["name"] = "a-very-long-custom-name"
            panes.extend(
                {
                    "pane": f"%{index}",
                    "command": "sh",
                    "cwd": workspace.path,
                    "dead": "0",
                    "kind": "shell",
                }
                for index in range(3, 10)
            )
        app = Manager(service, presenter=(lambda *_: None) if integrated else None)
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
    async def test_integrated_explorer_and_sessions_at_28_columns(self):
        async with dashboard(integrated=True, size=(28, 34)) as (
            app,
            pilot,
            _service,
            workspace,
            attach,
        ):
            explorer = app.query_one("#workspace-explorer", ExplorerTree)
            sessions = app.query_one("#session-list", SessionCards)
            self.assertFalse(app.query_one("#repo-section").display)
            self.assertFalse(app.query_one("#history-section", DashboardSection).display)
            self.assertTrue(app.query_one("#memory-open", Button).display)
            self.assertFalse(app.query_one("#history-menu", Button).display)
            self.assertTrue(app.query_one("#sidebar-menu", Button).display)
            self.assertFalse(app.query_one("#terminals", DataTable).display)
            workspace_node = explorer.root.children[0]
            source_node = workspace_node.children[0]
            worktree_node = source_node.children[0]
            self.assertIn("sample", workspace_node.label.plain)
            self.assertIn("source", source_node.label.plain)
            self.assertIn("alpha-branch", worktree_node.label.plain)
            explorer.move_cursor(workspace_node)
            explorer.focus()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.current, workspace.id)
            self.assertEqual(explorer.visible_rows, 1)
            await pilot.press("right")
            await pilot.pause()
            self.assertEqual(explorer.visible_rows, 4)
            await pilot.click("#workspace-explorer", offset=(8, 1))
            await pilot.pause()
            self.assertEqual(explorer.visible_rows, 4)
            self.assertEqual(explorer.cursor_node.data, source_node.data)
            explorer.move_cursor(explorer.root.children[0])
            branch = run(
                ["git", "-C", str(Path(workspace.path) / "alpha"), "branch", "--show-current"]
            )
            await pilot.press("down", "down", "enter")
            await pilot.pause()
            self.assertEqual(app.selected_worktree, (workspace.id, "alpha"))
            self.assertEqual(
                run(["git", "-C", str(Path(workspace.path) / "alpha"), "branch", "--show-current"]),
                branch,
            )
            node = explorer.root.children[0].children[0]
            self.assertIn("•", node.children[0].label.plain)
            explorer.move_cursor(node)
            await pilot.press("d")
            await app.workers.wait_for_complete()
            self.assertNotIsInstance(app.screen, Confirm)
            self.assertIn("Activate the workspace", str(app.query_one("#message", Static).render()))
            explorer.move_cursor(node)
            await pilot.press("left")
            await pilot.pause()
            self.assertEqual(explorer.visible_rows, 2)
            self.assertEqual(explorer.size.height, 2)
            await pilot.press("right")
            await pilot.pause()
            root = explorer.root.children[0]
            source = root.children[0]
            leaf = source.children[0]
            for node, name in (
                (root, "long-workspace-" * 8),
                (source, "long-repository-" * 8 + " •"),
                (leaf, "long-branch-" * 8 + " •"),
            ):
                node.set_label(name)
                label = explorer.render_label(node, Style(), Style())
                self.assertIn("…", label.plain)
                if name.endswith(" •"):
                    self.assertTrue(label.plain.endswith(" •"))
                self.assertGreater(node.label.cell_len, label.cell_len)
            self.assertEqual([card.pane for card in sessions.cards], ["%1"])
            await select_workspace(app, workspace)
            await pilot.pause()
            self.assertEqual(sessions.cards[0].agent, "Codex 2")
            self.assertEqual(sessions.cards[0].repository, "alpha")
            self.assertEqual(sessions.cards[0].branch, "alpha-branch")
            self.assertEqual(sessions.cards[1].state, "ended")
            sessions.focus()
            sessions.highlighted = 0
            await pilot.press("enter")
            attach.assert_called_once_with("%1")
            await pilot.hover("#session-list", offset=(5, 2))
            self.assertIsNone(sessions.tooltip)
            self.assertEqual(sessions.highlighted_option.id, "%1")
            await pilot.hover("#search")
            self.assertIsNone(sessions.tooltip)
            await pilot.press("down", "enter")
            attach.assert_called_once()
            await pilot.press("f10")
            await pilot.pause()
            self.assertIsInstance(app.screen, SectionMenu)
            self.assertTrue(app.screen.query_one("#terminal-attach", Button).disabled)
            self.assertFalse(app.screen.query_one("#terminal-details", Button).disabled)
            self.assertEqual(
                app.screen.query_one("#terminal-close", Button).label.plain, "Terminate"
            )

    async def test_integrated_add_focuses_new_worktree_and_launch_uses_it(self):
        async with dashboard(integrated=True, size=(36, 34)) as (
            app,
            pilot,
            service,
            workspace,
            _attach,
        ):
            await select_workspace(app, workspace)
            repo = {
                "source": service.config.source_root / "source",
                "name": "gamma",
                "branch": "gamma-branch",
                "ref": "HEAD",
                "new": True,
            }
            with patch.object(app, "push_screen_wait", side_effect=[repo, True]):
                app.action_add()
                await app.workers.wait_for_complete()
                await pilot.pause()
            explorer = app.query_one("#workspace-explorer", ExplorerTree)
            self.assertIs(app.focused, explorer)
            self.assertEqual(explorer.cursor_node.data, (workspace.id, "gamma"))
            self.assertEqual(app.selected_worktree, (workspace.id, "gamma"))
            cwd = Path(workspace.path) / "gamma"
            self.assertEqual(app.history_cwd, cwd)
            with patch.object(app, "push_screen_wait", return_value=None) as launch:
                app.action_new_terminal()
                await app.workers.wait_for_complete()
            dialog = launch.call_args.args[0]
            self.assertIsInstance(dialog, Launch)
            self.assertEqual(dialog.cwd, str(cwd))
            app.dispatch("workspace-open")
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIsNone(app.selected_worktree)
            self.assertEqual(app.history_cwd, Path(workspace.path))
            group = explorer.root.children[0].children[0]
            explorer.move_cursor(group.children[-1])
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsNotNone(app.selected_worktree)
            explorer.move_cursor(group)
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsNone(app.selected_worktree)
            self.assertEqual(app.history_cwd, Path(workspace.path))

    async def test_session_card_menu_targets_clicked_row_without_opening_terminal(self):
        async with dashboard(integrated=True, size=(28, 48)) as (app, pilot, _, workspace, attach):
            await select_workspace(app, workspace)
            cards = app.query_one(SessionCards)
            cards.scroll_visible(animate=False)
            await pilot.pause()
            menu_column = cards.scrollable_content_region.width - 2
            await pilot.click("#session-list", offset=(menu_column, 2))
            await pilot.pause()
            self.assertEqual(app.selected_key("terminals"), "%2")
            self.assertEqual(cards.highlighted_option.id, "%2")
            self.assertTrue(app.screen.query_one("#terminal-details", Button).is_mounted)
            attach.assert_not_called()
            app.session_rows["%2"] = {**app.session_rows["%2"], "identity": "replacement"}
            with patch.object(app, "dispatch") as dispatch:
                app.screen.query_one("#terminal-details", Button).press()
                await pilot.pause()
                dispatch.assert_not_called()
            self.assertIn("Selection changed", str(app.query_one("#message", Static).render()))
            await pilot.click("#session-list", offset=(2, 0))
            await pilot.pause()
            attach.assert_called_once_with("%1")

    async def test_premium_cards_resize_and_keep_visible_state(self):
        async with dashboard(integrated=True, size=(50, 18), many_sessions=True) as (
            app,
            pilot,
            _service,
            workspace,
            _attach,
        ):
            sessions = app.query_one("#session-list", SessionCards)
            self.assertFalse(sessions.display)
            branch = "feature/branch-name-that-does-not-fit"
            with patch.object(
                app, "session_context", return_value=("important-repository", branch)
            ):
                app.active_view = f"{workspace.id}/%1"
                await select_workspace(app, workspace)
                await pilot.pause()
                sessions.focus()
                await pilot.press("down")
                self.assertEqual(sessions.highlighted_option.id, "%2")
                self.assertEqual(sessions.size.height % 2, 0)
                for width in (36, 28, 50):
                    await pilot.resize_terminal(width, 18)
                    await pilot.pause()
                    prompt = sessions.get_option("%1").prompt
                    self.assertEqual(len(prompt.plain.splitlines()), 2)
                    self.assertIn("important", prompt.plain.splitlines()[0])
                    self.assertIn("connected", prompt.plain.splitlines()[1])
                    self.assertTrue(
                        all(
                            line.cell_len <= sessions.scrollable_content_region.width
                            for line in prompt.split()
                        )
                    )
                    self.assertEqual(sessions.highlighted_option.id, "%2")
                    self.assertEqual(app.query_one("#session-status").region.bottom, 18)
                await pilot.press("end")
                self.assertEqual(sessions.highlighted_option.id, "%9")
                self.assertEqual(sessions.cards[-1].branch, branch)

    async def test_minimal_sidebar_keeps_actions_and_warning_accessible(self):
        async with dashboard(integrated=True, size=(28, 34)) as (
            app,
            pilot,
            _service,
            workspace,
            _attach,
        ):
            await select_workspace(app, workspace)
            self.assertEqual(app.query_one("#search", Input).placeholder, "Search...")
            for key in ("workspace-refresh", "terminal-attach", "history-native"):
                self.assertFalse(app.query_one("#" + key, Button).display)
            self.assertFalse(app.query_one("#history-label").display)
            self.assertEqual(app.query_one("#memory-open", Button).label.plain, "Workspace Memory")
            with patch.object(app, "notify") as notify:
                app.launch_warning(
                    "Concurrent AI sessions may modify the same files: first", workspace.id
                )
                app.launch_warning(
                    "Concurrent AI sessions may modify the same files: example", workspace.id
                )
                notify.assert_called_once()
                app.launch_warning(
                    "Concurrent AI sessions may modify the same files: other", "other"
                )
                self.assertEqual(notify.call_count, 2)
                app.launch_warning(
                    "Concurrent AI sessions may modify the same files: example", workspace.id
                )
                self.assertEqual(notify.call_count, 2)
            self.assertNotIn("Concurrent AI", str(app.query_one("#message", Static).render()))
            app.clear_notifications()
            await pilot.click("#sidebar-menu")
            await pilot.pause()
            self.assertIsInstance(app.screen, SectionMenu)
            app.screen.query_one("#terminal-menu", Button).press()
            await pilot.pause()
            self.assertFalse(app.screen.query_one("#terminal-details", Button).disabled)
            await pilot.press("escape")
            await pilot.click("#sidebar-menu")
            await pilot.pause()
            app.screen.query_one("#sidebar-warning", Button).press()
            await pilot.pause()
            self.assertIsInstance(app.screen, Information)
            self.assertIn("files: example", app.screen.content)
            await pilot.press("escape")
            full = "Concurrent AI sessions may modify the same files. Blocked by configured conflict_policy."
            app.message(full)
            message = app.query_one("#message", Static)
            self.assertIn("Launch blocked by policy", str(message.render()))
            self.assertIsNone(message.tooltip)
            await pilot.click("#sidebar-menu")
            await pilot.pause()
            app.screen.query_one("#sidebar-message", Button).press()
            await pilot.pause()
            self.assertEqual(app.screen.content, full)

    async def test_minimal_history_failure_does_not_claim_history_is_empty(self):
        async with dashboard(integrated=True, size=(28, 32)) as (
            app,
            pilot,
            _service,
            workspace,
            _attach,
        ):
            await select_workspace(app, workspace)
            with patch("workspace_manager.tui.CodexHistory.list", side_effect=Error("Test error")):
                await app.activate_explorer((workspace.id, "alpha"))
                await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertTrue(app.query_one("#history-label").display)
            self.assertFalse(app.query_one("#history-empty").display)
            anchor = app.query_one("#sidebar-menu", Button)
            await pilot.click("#sidebar-menu")
            await pilot.pause()
            self.assertIsInstance(app.screen, SectionMenu)
            await pilot.click(offset=(anchor.region.x + 1, anchor.region.y))
            await pilot.pause()
            self.assertNotIsInstance(app.screen, SectionMenu)

    async def test_explorer_distinguishes_equal_names_and_state_after_resize(self):
        async with dashboard(integrated=True, size=(28, 34)) as (
            app,
            pilot,
            service,
            workspace,
            _attach,
        ):
            identical = service.create("source")
            service.add(identical.id, service.config.source_root / "source", "source", "source")
            await app.refresh_after_operation()
            explorer = app.query_one("#workspace-explorer", WorkspaceExplorer)
            group = next(node for node in explorer.root.children if node.data[0] == identical.id)
            repo = group.children[0]
            leaf = repo.children[0]
            self.assertEqual(
                [node.label.plain for node in (group, repo, leaf)],
                ["◫ source", "◇ source", "⑂ source"],
            )
            with patch("workspace_manager.dashboard.sys.stdout") as output:
                output.encoding = "ascii"
                fallback = WorkspaceExplorer()
                self.assertEqual(
                    [fallback.type_icon(level) for level in (0, 1, 2)], ["W", "R", "Y"]
                )
            self.assertFalse(leaf.allow_expand)
            await select_workspace(app, workspace)
            group = next(node for node in explorer.root.children if node.data[0] == workspace.id)
            group.expand()
            await pilot.pause()
            alpha, beta = group.children[0].children
            await app.activate_explorer(beta.data)
            app.active_view = f"{workspace.id}/%1"
            app.update_dashboard()
            await pilot.pause()
            group = next(node for node in explorer.root.children if node.data[0] == workspace.id)
            alpha, beta = group.children[0].children
            self.assertIn("•", alpha.label.plain)
            self.assertEqual(
                alpha.label.get_style_at_offset(app.console, 2).color.triplet.hex, "#8ab4f8"
            )
            self.assertTrue(beta.label.get_style_at_offset(app.console, 2).underline)
            explorer.focus()
            explorer.move_cursor(group)
            await pilot.pause()
            for columns in (28, 36, 50):
                await pilot.resize_terminal(columns, 34)
                await pilot.pause()
                self.assertEqual(explorer.cursor_node.data, group.data)
                strip = explorer.render_line(explorer.cursor_line - explorer.scroll_offset.y)
                self.assertEqual(
                    {segment.style.bgcolor.triplet.hex for segment in strip}, {"#203149"}
                )
                self.assertLessEqual(explorer.virtual_size.width, explorer.size.width)

    async def test_context_worktree_and_global_sessions_keep_separate_targets(self):
        async with dashboard(integrated=True, size=(28, 28)) as (
            app,
            pilot,
            service,
            workspace,
            _attach,
        ):
            await app.activate_explorer((workspace.id, "alpha"))
            await app.workers.wait_for_complete()
            sessions = app.query_one("#session-list", SessionCards)
            self.assertEqual([card.pane for card in sessions.cards], ["%1"])
            self.assertIn("source / alpha-branch", str(app.query_one("#worktree-context").render()))
            self.assertTrue(app.query_one("#history-section").display)
            await app.activate_explorer((workspace.id, "beta"))
            await app.workers.wait_for_complete()
            self.assertEqual(
                [(card.pane, card.state) for card in sessions.cards], [("%2", "ended")]
            )
            other = service.create("other")
            pane = {"pane": "%1", "kind": "shell", "command": "sh", "cwd": other.path, "dead": "0"}
            with (
                patch(
                    "workspace_manager.tui.Tmux.list",
                    side_effect=lambda owner: (
                        [pane, {**pane, "pane": "%2", "name": "Named"}] if owner == other else []
                    ),
                ),
                patch.object(app, "presenter") as present,
            ):
                app.action_all_sessions()
                await pilot.pause()
                self.assertIsInstance(app.screen, GlobalSessions)
                self.assertEqual(app.screen.rows[0][0], f"{other.id}/%1")
                self.assertIn("Shell %1", app.screen.rows[0][1])
                self.assertIn("Shell %2", app.screen.rows[1][1])
                self.assertIn("Named", app.screen.rows[1][1])
                app.screen.query_one("#global-sessions").focus()
                await pilot.press("enter")
                await app.workers.wait_for_complete()
                present.assert_called_once()
                owner, target, is_current = present.call_args.args
                self.assertEqual((owner, target), (other, "%1"))
                self.assertTrue(is_current())
            self.assertEqual(app.selected_worktree, (workspace.id, "beta"))

    async def test_conversation_titles_and_unassigned_history(self):
        async with dashboard(integrated=True, size=(36, 32)) as (
            app,
            pilot,
            service,
            workspace,
            _attach,
        ):
            first = Conversation(ID, "Same title", Path(workspace.path) / "alpha", 42, "idle")
            second = Conversation("other", "Same title", None, 40, "idle")
            store = ConversationTitles(service)
            store.set("codex", first.id, "A local title")
            store.set("claude", first.id, "Different provider")
            app.custom_titles = ConversationTitles(service).read()
            self.assertEqual(app.conversation_title(first), "A local title")
            self.assertEqual(app.conversation_title(second), "Same title")
            with patch(
                "workspace_manager.context_views.CodexHistory.list",
                return_value=HistoryPage([first, second], None),
            ):
                app.action_all_conversations()
                await pilot.pause()
                self.assertIsInstance(app.screen, HistoryBrowser)
                browser = app.screen
                listing = browser.query_one("#browser-rows")
                for _ in range(20):
                    if listing.option_count == 2:
                        break
                    await pilot.pause(0.05)
                self.assertEqual(listing.option_count, 2)
                browser.query_one("#history-search", Input).value = "local"
                await pilot.pause()
                self.assertEqual(listing.option_count, 1)
                self.assertEqual(listing.get_option_at_index(0).id, ID)
                await pilot.press("escape")
                await app.workers.wait_for_complete()
            store.set("codex", first.id, "")
            self.assertEqual(
                ConversationTitles(service).read(), {"claude:" + first.id: "Different provider"}
            )
            self.assertEqual(first.title, "Same title")

    async def test_global_history_filters_two_pages_without_dropping_unassigned(self):
        list_history = CodexHistory.list
        async with dashboard(integrated=True) as (app, pilot, _service, workspace, _attach):
            alpha = Path(workspace.path) / "alpha"
            beta = Path(workspace.path) / "beta"
            first = {"id": ID, "cwd": str(alpha), "name": "Alpha"}
            second = {"id": ID[:-1] + "d", "cwd": str(beta), "name": "Beta"}
            unknown = {"id": ID[:-1] + "e", "cwd": None, "name": "Unassigned"}
            with (
                patch.object(CodexHistory, "list", list_history),
                patch(
                    "workspace_manager.context_views.CodexHistory._request",
                    side_effect=[
                        {"data": [first, unknown], "nextCursor": "next"},
                        {"data": [first, second], "nextCursor": None},
                    ],
                ) as request,
            ):
                app.action_all_conversations()
                await pilot.pause()
                browser = app.screen
                scope = browser.query_one("#history-scope", Select)
                scope.value = ""
                listing = browser.query_one("#browser-rows")
                for _ in range(20):
                    if listing.option_count == 2:
                        break
                    await pilot.pause(0.05)
                self.assertEqual(listing.option_count, 2)
                browser.query_one("#browser-more", Button).press()
                for _ in range(20):
                    if listing.option_count == 3:
                        break
                    await pilot.pause(0.05)
                self.assertEqual(listing.option_count, 3)
                self.assertEqual(
                    [call.args[1]["cursor"] for call in request.call_args_list], [None, "next"]
                )
                for path, row in ((alpha, first), (beta, second)):
                    scope.value = str(path)
                    await pilot.pause()
                    self.assertEqual(listing.option_count, 1)
                    self.assertEqual(listing.get_option_at_index(0).id, row["id"])
                scope.value = ""
                await pilot.pause()
                self.assertEqual(listing.option_count, 3)
                self.assertIsNotNone(listing.get_option(unknown["id"]))
                await pilot.press("escape")
                await app.workers.wait_for_complete()

    async def test_global_resume_keeps_original_id_after_rename(self):
        async with dashboard(integrated=True) as (app, _pilot, service, workspace, _attach):
            target = Path(workspace.path) / "beta"
            item = Conversation(ID, "Original", target, 42, "idle")
            with (
                patch.object(
                    app,
                    "push_screen_wait",
                    side_effect=[
                        HistoryChoice("rename", item),
                        "pinned title",
                        HistoryChoice("resume", item),
                    ],
                ),
                patch.object(app, "launch_history") as launch,
            ):
                app.action_all_conversations()
                await app.workers.wait_for_complete()
                launch.assert_called_once_with(workspace, target, ID, "codex", True)
            self.assertEqual(ConversationTitles(service).read()["codex:" + ID], "pinned title")

    async def test_cancel_unassigned_or_missing_codex_location_does_not_launch(self):
        async with dashboard(integrated=True) as (app, _pilot, _service, workspace, _attach):
            fallback = Path(workspace.path) / "alpha"
            await app.activate_explorer((workspace.id, "alpha"))
            for cwd in (None, Path(workspace.path) / "missing"):
                item = Conversation(ID, "Original", cwd, 42, "idle")
                with (
                    patch.object(
                        app,
                        "push_screen_wait",
                        side_effect=[HistoryChoice("resume", item), False, None],
                    ) as prompt,
                    patch.object(app, "launch_history") as launch,
                ):
                    app.action_all_conversations()
                    await app.workers.wait_for_complete()
                    confirmation = prompt.call_args_list[1].args[0]
                    self.assertIsInstance(confirmation, Confirm)
                    self.assertIn(str(fallback), confirmation.message)
                    launch.assert_not_called()

    async def test_claude_picker_refuses_missing_registered_location(self):
        async with dashboard(integrated=True) as (app, _pilot, _service, workspace, _attach):
            target = Path(workspace.path) / "beta"
            target.rename(target.with_name("moved-beta"))
            with (
                patch.object(
                    app, "push_screen_wait", return_value=HistoryChoice("claude", cwd=target)
                ),
                patch.object(app, "launch_history") as launch,
                patch.object(app, "message") as message,
            ):
                app.action_all_conversations()
                await app.workers.wait_for_complete()
                launch.assert_not_called()
                message.assert_called_once()

    async def test_history_refuses_worktree_replaced_while_browser_is_open(self):
        async with dashboard(integrated=True) as (app, _pilot, service, workspace, _attach):
            target = Path(workspace.path) / "beta"
            changed = replace(
                workspace,
                repos=[
                    replace(repo, generation="replacement") if repo.name == "beta" else repo
                    for repo in workspace.repos
                ],
            )
            with (
                patch.object(service, "get", return_value=changed),
                patch.object(
                    app, "push_screen_wait", return_value=HistoryChoice("claude", cwd=target)
                ),
                patch.object(app, "launch_history") as launch,
                patch.object(app, "message") as message,
            ):
                app.action_all_conversations()
                await app.workers.wait_for_complete()
                launch.assert_not_called()
                message.assert_called_once_with(
                    "Conversation location changed; reopen history and select it again"
                )

    async def test_launcher_refuses_replaced_history_target_before_allocating_pane(self):
        async with dashboard(integrated=True) as (_app, _pilot, service, workspace, _attach):
            target = Path(workspace.path) / "beta"
            stale = replace(
                workspace,
                repos=[
                    replace(repo, generation="stale") if repo.name == "beta" else repo
                    for repo in workspace.repos
                ],
            )
            with (
                patch.object(Tmux, "_new") as new,
                self.assertRaisesRegex(Error, "Conversation location changed"),
            ):
                AI(service.config).launch(
                    stale, "claude", "resume", target, verify_history_location=True
                )
            new.assert_not_called()

    async def test_claude_picker_uses_location_selected_in_history(self):
        async with dashboard(integrated=True) as (app, pilot, _service, workspace, _attach):
            await app.activate_explorer((workspace.id, "alpha"))
            with (
                patch(
                    "workspace_manager.context_views.CodexHistory.list",
                    return_value=HistoryPage([], None),
                ),
                patch.object(app, "launch_history") as launch,
            ):
                app.action_all_conversations()
                await pilot.pause()
                target = Path(workspace.path) / "beta"
                app.screen.query_one("#history-scope", Select).value = str(target)
                app.screen.query_one("#history-agent", Select).value = "claude"
                await pilot.pause()
                app.screen.query_one("#browser-claude", Button).press()
                await app.workers.wait_for_complete()
                launch.assert_called_once_with(workspace, target, None, "claude", True)

    async def test_closing_history_during_load_keeps_dashboard_running(self):
        async with dashboard(integrated=True) as (app, pilot, _service, _workspace, _attach):
            loading = threading.Event()
            release = threading.Event()

            def load(*_):
                loading.set()
                release.wait(timeout=3)
                return HistoryPage([], None)

            try:
                with patch("workspace_manager.context_views.CodexHistory.list", side_effect=load):
                    app.action_all_conversations()
                    for _ in range(20):
                        if loading.is_set():
                            break
                        await pilot.pause(0.05)
                    self.assertTrue(loading.is_set())
                    await pilot.press("escape")
                    await pilot.pause()
                    self.assertTrue(app.is_running)
                    self.assertNotIsInstance(app.screen, HistoryBrowser)
            finally:
                release.set()

    async def test_switching_displayed_tab_syncs_context_and_keeps_selection_independent(self):
        async with dashboard(integrated=True) as (app, _pilot, _service, workspace, _attach):
            await app.activate_explorer((workspace.id, "alpha"))
            app.tab_request = lambda: ""
            app.displayed = lambda: f"{workspace.id}/%2"
            await app.refresh_active_view().wait()
            self.assertEqual(app.selected_worktree, (workspace.id, "beta"))
            self.assertEqual(app.history_cwd, Path(workspace.path) / "beta")
            await app.activate_explorer((workspace.id, "alpha"))
            await app.refresh_active_view().wait()
            self.assertEqual(app.selected_worktree, (workspace.id, "alpha"))
            self.assertEqual(app.active_view, f"{workspace.id}/%2")
            # A highlight may be queued before the backing table is unmounted.
            cards = app.query_one(SessionCards)
            event = OptionList.OptionHighlighted(cards, cards.get_option_at_index(0), 0)
            with patch.object(app, "query_one", side_effect=NoMatches("#terminals")):
                app.on_option_list_option_highlighted(event)

    async def test_failed_presentation_preserves_observed_session_and_allows_retry(self):
        async with dashboard(integrated=True) as (app, _pilot, _service, workspace, _attach):
            first = f"{workspace.id}/%1"
            second = f"{workspace.id}/%2"
            observed = first
            app.displayed = lambda: observed
            await app.refresh_active_view().wait()

            with patch.object(app, "presenter", side_effect=Error("Attach failed")):
                app.present_terminal(workspace, "%2")
                await app.workers.wait_for_complete()
            self.assertEqual(app.active_view, first)
            self.assertIn("Attach failed", str(app.query_one("#message", Static).render()))

            def present(*_):
                nonlocal observed
                observed = second

            with patch.object(app, "presenter", side_effect=present):
                app.present_terminal(workspace, "%2")
                await app.workers.wait_for_complete()
            await app.refresh_active_view().wait()
            self.assertEqual(app.active_view, second)

    async def test_presentation_worker_drops_superseded_pending_requests(self):
        async with dashboard(integrated=True) as (app, _pilot, _service, workspace, _attach):
            entered, release = threading.Event(), threading.Event()
            seen = []

            committed = []

            def present(_workspace, pane, is_current):
                seen.append(pane)
                if len(seen) == 1:
                    entered.set()
                    release.wait(3)
                if is_current():
                    committed.append(pane)

            with patch.object(app, "presenter", side_effect=present):
                app.present_terminal(workspace, "%1")
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    for pane in ("%2", "%1", "%2", "%1"):
                        app.present_terminal(workspace, pane)
                finally:
                    release.set()
                await app.workers.wait_for_complete()
            self.assertEqual(seen, ["%1", "%1"])
            self.assertEqual(committed, ["%1"])

    async def test_terminal_opening_message_clears_after_launch_result(self):
        async with dashboard(integrated=True) as (app, pilot, _service, workspace, attach):
            await select_workspace(app, workspace)
            for outcome in ("%3", Error("Launch failed")):
                entered, release = threading.Event(), threading.Event()

                def launch(*_args, started=entered, ready=release, result=outcome, **_kwargs):
                    started.set()
                    ready.wait(3)
                    if isinstance(result, Error):
                        raise result
                    return result

                with patch("workspace_manager.tui.AI.launch", side_effect=launch):
                    app.launch_ai("shell", True)
                    await pilot.pause()
                    app.screen.query_one("#launch", Button).press()
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                        self.assertEqual(app.sidebar_message_details, "Opening terminal...")
                    finally:
                        release.set()
                    await app.workers.wait_for_complete()
                expected = str(outcome) if isinstance(outcome, Error) else None
                self.assertEqual(app.sidebar_message_details, expected)
            attach.assert_called_once_with("%3")

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
            target = app.selected_key("terminals")
            with (
                patch("workspace_manager.tui.Tmux.close") as close,
                patch("workspace_manager.tui.Tmux.termination_identity", return_value="birth"),
            ):
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
                close.assert_called_once_with(workspace, target, expected="birth")

    async def test_session_card_terminate_confirms_and_uses_the_selected_panel(self):
        async with dashboard(integrated=True, size=(36, 48)) as (app, pilot, _, workspace, _):
            await select_workspace(app, workspace)
            cards = app.query_one(SessionCards)
            cards.scroll_visible(animate=False)
            await pilot.pause()
            with (
                patch("workspace_manager.tui.Tmux.close") as close,
                patch(
                    "workspace_manager.tui.Tmux.termination_identity", return_value="birth"
                ) as verify,
            ):
                await pilot.click(
                    "#session-list", offset=(cards.scrollable_content_region.width - 2, 0)
                )
                await pilot.click("#terminal-close")
                await pilot.pause()
                self.assertIsInstance(app.screen, Confirm)
                self.assertEqual(app.focused.id, "cancel")
                verify.assert_called_once_with(workspace, "%1", None)
                close.assert_not_called()
                await pilot.click("#confirm")
                await app.workers.wait_for_complete()
                close.assert_called_once_with(workspace, "%1", expected="birth")

    async def test_terminated_session_disappears_even_when_backend_refresh_fails(self):
        async with dashboard(integrated=True) as (app, pilot, _, workspace, _):
            await select_workspace(app, workspace)
            with (
                patch("workspace_manager.tui.Tmux.close"),
                patch("workspace_manager.tui.Tmux.termination_identity", return_value="birth"),
                patch.object(
                    app, "refresh_after_operation", side_effect=Error("Backend unavailable")
                ),
            ):
                app.dispatch("terminal-close")
                await pilot.pause()
                await pilot.click("#confirm")
                await app.workers.wait_for_complete()
                self.assertEqual([card.pane for card in app.query_one(SessionCards).cards], ["%2"])
                self.assertEqual([r["pane"] for r in app.workspace_sessions[workspace.id]], ["%2"])

    async def test_close_refuses_unverified_pane_without_opening_confirmation(self):
        async with dashboard() as (app, _pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            with (
                patch("workspace_manager.tui.Tmux.close") as close,
                patch(
                    "workspace_manager.tui.Tmux.termination_identity",
                    side_effect=Error("Ownership is unverified"),
                ),
            ):
                app.dispatch("terminal-close")
                await app.workers.wait_for_complete()
                close.assert_not_called()
                self.assertEqual(len(app.screen_stack), 1)
                self.assertIn(
                    "Ownership is unverified", str(app.query_one("#message", Static).render())
                )

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
                patch("workspace_manager.tui.Tmux.termination_identity", return_value="birth"),
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
                    close.assert_called_once_with(workspace, "%1", expected="birth")
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

    async def test_switch_branch_from_explorer_requires_confirmation_and_refreshes_head(self):
        async with dashboard(integrated=True) as (app, pilot, service, workspace, _attach):
            repo = next(repo for repo in workspace.repos if repo.name == "alpha")
            run(["git", "-C", repo.source, "branch", "review"])
            await app.activate_explorer((workspace.id, "alpha"))
            self.assertEqual(
                service.status(workspace.id)["repos"]["alpha"]["branch"], "alpha-branch"
            )
            with patch("workspace_manager.terminal.Tmux.require_no_terminals"):
                for approve in (False, True):
                    app.dispatch("repo-switch")
                    await pilot.pause()
                    app.screen.query_one(Input).value = "review"
                    await pilot.press("enter")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, Confirm)
                    if approve:
                        await pilot.click("#confirm")
                    else:
                        await pilot.press("escape")
                    await app.workers.wait_for_complete()
                    expected = "review" if approve else "alpha-branch"
                    self.assertEqual(
                        service.status(workspace.id)["repos"]["alpha"]["branch"], expected
                    )
            self.assertIn("review", str(app.query_one("#worktree-context").render()))

    async def test_terminal_menu_survives_unrelated_history_refresh(self):
        async with dashboard() as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            app.open_menu("terminal")
            await pilot.pause()
            app.select_history(Path(workspace.path) / "alpha")
            await app.workers.wait_for_complete()
            await pilot.pause()
            with patch("workspace_manager.tui.Tmux.termination_identity", return_value="birth"):
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
                if isinstance(app.screen, Confirm) and app.screen.query("#confirm"):
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
