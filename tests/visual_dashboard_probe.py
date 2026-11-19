"""Native Textual visual-QA fixture; synthetic data, no user sessions/models."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

from workspace_manager.codex_history import Conversation, HistoryPage
from workspace_manager.core import Config, Service, run
from workspace_manager.dashboard import SectionMenu
from workspace_manager.tui import Manager

root, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
root.mkdir(parents=True, exist_ok=True)
output.mkdir(parents=True, exist_ok=True)
service = Service(Config(root / "work", root, root / "state"))
service.create("release-review")
service.create("research-lab")
workspace = service.create("platform")
source = root / "source"
run(["git", "init", "-b", "main", str(source)])
(source / "README.md").write_text("Synthetic visual QA source.\n")
run(["git", "-C", str(source), "add", "README.md"])
run(
    [
        "git",
        "-C",
        str(source),
        "-c",
        "user.name=Visual QA",
        "-c",
        "user.email=visual@example.invalid",
        "commit",
        "-m",
        "Synthetic fixture",
    ]
)
for name, branch in (
    ("bookr", "feature/checkout-flow"),
    ("orcan", "fix/cockpit-focus"),
    ("workspace-manager", "feature/modern-dashboard"),
):
    service.add(workspace.id, source, name, branch)
(Path(workspace.path) / "orcan/README.md").write_text(
    "Modified QA worktree, original source untouched.\n"
)


def history(cwd, cursor=None):
    return HistoryPage(
        [
            Conversation(
                "12345678-1234-1234-1234-123456789ab1",
                "Polish the contextual dashboard",
                cwd,
                1794918000,
                "notLoaded",
            ),
            Conversation(
                "12345678-1234-1234-1234-123456789ab2",
                "Review repository boundaries and terminal lifecycle",
                cwd,
                1794914400,
                "notLoaded",
            ),
            Conversation(
                "12345678-1234-1234-1234-123456789ab3",
                "Investigate the checkout dependency flow",
                cwd,
                1794907200,
                "idle",
            ),
        ],
        None,
    )


panes = [
    {"pane": "%1", "command": "codex", "cwd": workspace.path, "dead": "0", "kind": "codex"},
    {
        "pane": "%2",
        "command": "zsh",
        "cwd": str(Path(workspace.path) / "bookr"),
        "dead": "0",
        "kind": "shell",
    },
]


class VisualApp(Manager):
    def on_mount(self):
        self.visual_ready = False
        self.setup_timer = self.set_interval(0.05, self.when_ready)

    def when_ready(self):
        if workspace.id in self.values and not self.refresh_loading:
            self.setup_timer.stop()
            self.run_worker(self.prepare_view(), group="visual-setup")

    async def prepare_view(self):
        await self.choose_row("workspaces", workspace.id)
        while self.history_loading:
            await asyncio.sleep(0.03)
        self.focus_row("workspaces", workspace.id)
        self.visual_ready = True
        (root / "ready").write_text("ready")

    def capture(self, view):
        name = f"dashboard-{self.size.width}x{self.size.height}-{view}.svg"
        self.save_screenshot(filename=name, path=str(output))
        record = {
            "view": view,
            "columns": self.size.width,
            "rows": self.size.height,
            "file": name,
            "native_textual": True,
            "focus": self.focused.id if self.focused else None,
        }
        if isinstance(self.screen, SectionMenu):
            panel = self.screen.query_one(".section-menu")
            record["menu_bounds"] = list(panel.region)
        temporary = root / (view + "-next")
        temporary.write_text(json.dumps(record))
        temporary.replace(root / (view + "-done"))

    def later_capture(self, view):
        self.set_timer(0.15, lambda: self.call_after_refresh(self.capture, view))

    def on_key(self, event):
        if not self.visual_ready:
            return
        if event.key == "f12":
            self.call_after_refresh(self.capture, "dashboard")
        elif event.key == "f11":
            self.open_menu("workspace")
            self.later_capture("menu")
        elif event.key == "f10":
            self.action_create()
            self.later_capture("dialog")
        elif event.key == "f9":
            self.focus_row("conversations", "12345678-1234-1234-1234-123456789ab3")
            self.later_capture("scrolled")

    def attach(self, pane=None):
        raise AssertionError("Visual QA must never attach a user terminal")


with (
    patch("workspace_manager.tui.Tmux.list", return_value=panes),
    patch("workspace_manager.tui.CodexHistory.list", side_effect=history),
):
    VisualApp(service).run()
