"""Synthetic native-terminal fixture, invoked only by isolated PTY tests."""

import json
import sys
from pathlib import Path

from textual.widgets import DataTable

from workspace_manager.core import Config, Service
from workspace_manager.dashboard import SectionHeader, SectionMenu, SectionTable
from workspace_manager.tui import Manager

root = Path(sys.argv[1]).resolve()
service = Service(Config(root / "work", root, root / "state"))
workspace = service.create("mouse-test")
for index in range(20):
    service.create("mouse-extra-" + str(index))


class Probe(Manager):
    def record(self, event):
        with (root / "events").open("a") as stream:
            stream.write(event + "\n")

    def on_mount(self):
        self.scroll_timer = self.set_interval(0.05, self.report_scroll)
        self.menu_seen = False
        self.menu_timer = self.set_interval(0.05, self.report_menu)

    def report_menu(self):
        if isinstance(self.screen, SectionMenu):
            self.menu_seen = True
            (root / "menu-open").write_text("open")
        elif self.menu_seen:
            (root / "menu-closed").write_text("closed")
            self.menu_timer.stop()

    def report_scroll(self):
        table = self.query_one("#workspaces", DataTable)
        if table.scroll_y > 0:
            self.record("wheel:workspaces")
            self.scroll_timer.stop()

    def report_geometry(self):
        table = self.query_one("#workspaces", DataTable)
        if not table.row_count or table.region.width < 30 or table.region.height < 2:
            return
        toggle = self.query_one("#workspace-toggle")
        menu = self.query_one("#workspace-menu")
        positions = {
            "row": [table.region.x + 3, table.region.y + 1],
            "toggle": [
                toggle.region.x + toggle.region.width // 2,
                toggle.region.y + toggle.region.height // 2,
            ],
            "menu": [
                menu.region.x + menu.region.width // 2,
                menu.region.y + menu.region.height // 2,
            ],
        }
        temporary = root / "geometry-next"
        temporary.write_text(json.dumps(positions))
        temporary.replace(root / "geometry")

    def select_history(self, cwd):
        # This fixture exercises terminal input, not real conversation history.
        self.history_workspace, self.history_cwd = self.current, cwd
        self.history_loading = False
        self.update_dashboard()

    async def on_section_table_chosen(self, event: SectionTable.Chosen):
        self.record("choose:" + str(event.table.id))

    def on_section_header_requested(self, event: SectionHeader.Requested):
        self.record("action:" + event.action)

    def on_key(self, event):
        self.record("key:" + event.key)
        if event.key == "f12":
            self.call_after_refresh(self.report_geometry)

    def attach(self, pane=None):
        self.record("UNEXPECTED-ATTACH")


Probe(service).run()
(root / "exited").write_text("clean exit")
