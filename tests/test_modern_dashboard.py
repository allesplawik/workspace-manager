"""UX-13..18 visual contracts that protect behavior at terminal sizes."""

import unittest

from test_contextual_dashboard import dashboard, select_workspace
from textual.widgets import Button, DataTable, Static

from workspace_manager.dashboard import DashboardSection, SectionHeader, SectionMenu
from workspace_manager.tui import Create


class ModernDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_palette_and_separate_title_counter_loading(self):
        async with dashboard(size=(120, 40)) as (app, _pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            self.assertEqual(app.screen.styles.background.hex, "#0C111B")
            section = app.query_one("#workspace-section", DashboardSection)
            self.assertEqual(section.styles.background.hex, "#141C2A")
            title = app.query_one("#workspace-title", Static)
            badge = app.query_one("#workspace-count", Static)
            self.assertEqual(str(title.render()), "Workspaces")
            self.assertEqual(str(badge.render()), "1")
            header = section.query_one(SectionHeader)
            header.set_loading(True)
            self.assertIn("…", str(badge.render()))
            header.set_loading(False)
            self.assertEqual(str(badge.render()), "1")
            self.assertTrue(app.query_one("#workspace-new", Button).has_class("primary-action"))

    async def test_resize_and_cell_styling_preserve_raw_data_and_scope(self):
        async with dashboard(size=(120, 40)) as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            app.focus_row("repos", "beta")
            await app.choose_row("repos", "beta")
            await app.workers.wait_for_complete()
            terminals = app.query_one("#terminals", DataTable)
            raw = terminals.get_row_at(0).copy()
            rendered = terminals._compute_row_renderables(0)
            self.assertEqual(str(rendered.cells[3]), "Live")
            self.assertEqual(raw[3], "0")
            for size in ((100, 30), (80, 24), (120, 40)):
                await pilot.resize_terminal(*size)
                await pilot.pause()
                self.assertEqual(terminals.get_row_at(0), raw)
                self.assertEqual(app.current, workspace.id)
                self.assertEqual(app.selected_key("repos"), "beta")
                self.assertEqual(app.history_cwd.name, "beta")
                conversations = app.query_one("#conversations", DataTable)
                self.assertLessEqual(
                    sum(c.get_render_width(conversations) for c in conversations.ordered_columns),
                    conversations.size.width,
                )
                self.assertTrue(app.query_one("#history-native", Button).display)

    async def test_anchored_menus_fit_and_keep_keyboard_activation(self):
        for size in ((120, 40), (100, 30), (80, 24)):
            with self.subTest(size=size):
                async with dashboard(size=size) as (app, pilot, _service, workspace, _attach):
                    await select_workspace(app, workspace)
                    app.open_menu("workspace")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, SectionMenu)
                    panel = app.screen.query_one(".section-menu")
                    self.assertGreaterEqual(panel.region.x, 0)
                    self.assertGreaterEqual(panel.region.y, 0)
                    self.assertLessEqual(panel.region.right, size[0])
                    self.assertLessEqual(panel.region.bottom, size[1])
                    self.assertLessEqual(panel.region.height, 12)
                    self.assertEqual(panel.styles.background.hex, "#192338")
                    app.screen.query_one("#workspace-open", Button).focus()
                    await pilot.press("space")
                    await app.workers.wait_for_complete()
                    self.assertEqual(len(app.screen_stack), 1)
                    self.assertEqual(app.current, workspace.id)

    async def test_compact_create_dialog_and_popover_reposition_after_resize(self):
        async with dashboard(size=(120, 40)) as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            app.open_menu("history")
            await pilot.pause()
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            panel = app.screen.query_one(".section-menu")
            self.assertLessEqual(panel.region.right, 80)
            self.assertLessEqual(panel.region.bottom, 24)
            await pilot.press("escape")
            app.action_create()
            await pilot.pause()
            self.assertIsInstance(app.screen, Create)
            dialog = app.screen.query_one(".dialog")
            self.assertLess(dialog.region.height, 24)
            self.assertLessEqual(dialog.region.right, 80)
            self.assertLessEqual(
                app.screen.query_one("#cancel", Button).region.bottom, dialog.region.bottom
            )
            await pilot.press("escape")
            await app.workers.wait_for_complete()
            self.assertFalse(app.dialog_busy)

    async def test_builtin_theme_switch_keeps_dashboard_tokens_valid(self):
        async with dashboard(size=(100, 30)) as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            app.theme = "textual-dark"
            await pilot.pause()
            self.assertEqual(app.screen.styles.background.hex, "#0C111B")
            app.open_menu("repo")
            await pilot.pause()
            self.assertIsInstance(app.screen, SectionMenu)
            await pilot.press("escape")

    async def test_narrow_headers_keep_actions_visible_even_while_loading(self):
        async with dashboard(size=(48, 24), extra=18) as (app, pilot, _service, workspace, _attach):
            await select_workspace(app, workspace)
            for header in app.query(SectionHeader):
                header.set_loading(True)
            await pilot.pause()
            for header in app.query(SectionHeader):
                for button in header.query(Button):
                    self.assertGreaterEqual(button.region.x, 0)
                    self.assertLessEqual(button.region.right, app.size.width)
            await pilot.resize_terminal(120, 40)
            await pilot.pause()
            self.assertEqual(str(app.query_one("#history-native", Button).label), "Resume picker")
