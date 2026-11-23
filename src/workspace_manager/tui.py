"""Textual manager; blocking filesystem/Git/tmux work runs in worker threads."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from functools import wraps
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Select,
    Static,
    Tree,
)
from textual.worker import Worker, WorkerCancelled

from .codex_history import CodexHistory, Conversation
from .context_views import GlobalSessions, HistoryBrowser, HistoryScope
from .conversation_titles import ConversationTitles
from .core import Error, Git, Repo, Service, Workspace, run
from .dashboard import (
    ActionButton,
    DashboardSection,
    ExplorerTree,
    Information,
    SectionAction,
    SectionHeader,
    SectionMenu,
    SectionTable,
    SessionCard,
    SessionCards,
    WorkspaceExplorer,
)
from .design import PALETTE, PREMIUM_PALETTE, WORKSPACE_THEME, rows_for_height
from .providers import PROVIDERS, provider
from .session_tabs import session_display_name
from .terminal import AI, Tmux


class Confirm(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    def __init__(self, message: str, *, focus_cancel: bool = False):
        super().__init__()
        self.message = message
        self.focus_cancel = focus_cancel

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Static(self.message, markup=False)
            yield Button("Confirm", id="confirm", variant="warning")
            yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        if self.focus_cancel:
            self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class MemoryView(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "close", "Close")]

    def __init__(self, snapshot: dict[str, str]):
        super().__init__()
        self.snapshot = snapshot

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Label("Shared workspace memory — max 400 words / 4000 characters")
            yield Static(self.snapshot["path"], markup=False)
            yield Static(self.snapshot["content"], markup=False)
            yield Button("Close", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class RenameSession(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    def __init__(self, name: str, *, conversation: bool = False, branch: bool = False):
        super().__init__()
        self.session_name = name
        self.conversation = conversation
        self.branch = branch

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            if self.branch:
                yield Label("Switch branch")
                yield Input(placeholder="Existing local branch")
                yield Button("Continue", id="save")
                return
            yield Label("Rename conversation" if self.conversation else "Rename session")
            yield Input(
                self.session_name,
                placeholder="Empty restores the original title"
                if self.conversation
                else "Empty restores the agent name",
                max_length=120 if self.conversation else 80,
            )
            yield Button("Save", id="save")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.query_one(Input).value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Create(ModalScreen[dict[str, str] | None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    def __init__(self, root: Path):
        super().__init__()
        self.root = root

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Create workspace — next: choose first repository")
            yield Input(placeholder="Workspace name", id="name")
            yield Input(str(self.root), id="location")
            yield Button("Preview", id="preview")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self.dismiss({key: self.query_one(f"#{key}", Input).value for key in ("name", "location")})

    def action_cancel(self) -> None:
        self.dismiss(None)


class AddRepo(ModalScreen[dict[str, Any] | None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    def __init__(self, root: Path):
        super().__init__()
        self.root = root if root.is_dir() else Path.home()

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Label("Browse directories; enter a path to browse elsewhere")
            yield Input(str(self.root), id="source")
            yield Button("Browse path", id="browse")
            yield DirectoryTree(self.root, id="tree")
            yield Input(placeholder="Worktree directory name", id="name")
            yield Select(
                [
                    ("New branch", "new"),
                    ("Existing branch", "existing"),
                    ("Detached HEAD", "detached"),
                ],
                value="new",
                id="mode",
            )
            yield Select([], prompt="Existing branches (choose repository first)", id="branches")
            yield Input(placeholder="New branch name", id="branch")
            yield Input("HEAD", placeholder="Start ref / SHA", id="ref")
            yield Static("", id="error", markup=False)
            yield Button("Preview", id="preview")
            yield Button("Cancel", id="cancel")

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self.query_one("#source", Input).value = str(event.path)
        self.load_branches(event.path)

    @work(exclusive=True)
    async def load_branches(self, path: Path) -> None:
        try:
            source = await asyncio.to_thread(Git.source, path)
            output = await asyncio.to_thread(
                run,
                [
                    "git",
                    "-C",
                    str(source),
                    "for-each-ref",
                    "--format=%(refname:short)",
                    "refs/heads/",
                ],
            )
            self.query_one("#branches", Select).set_options([(b, b) for b in output.splitlines()])
            self.query_one("#name", Input).value = source.name
            self.query_one("#error", Static).update("")
        except Error as exc:
            self.query_one("#error", Static).update(str(exc))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "browse":
            path = Path(self.query_one("#source", Input).value).expanduser()
            self.query_one("#tree", DirectoryTree).path = path
            self.load_branches(path)
        elif event.button.id == "preview":
            mode = str(self.query_one("#mode", Select).value)
            branch: str | None = self.query_one("#branch", Input).value
            if mode == "existing":
                selected = self.query_one("#branches", Select).value
                if selected == Select.BLANK:
                    self.query_one("#error", Static).update("Select an existing branch")
                    return
                branch = str(selected)
            if mode == "detached":
                branch = None
            self.preview_repository(branch, mode)

    @work(exclusive=True, group="repo-preview")
    async def preview_repository(self, branch: str | None, mode: str) -> None:
        from .core import safe_name

        result: dict[str, Any] = {
            "source": Path(self.query_one("#source", Input).value).expanduser(),
            "name": self.query_one("#name", Input).value,
            "branch": branch,
            "ref": self.query_one("#ref", Input).value,
            "new": mode != "existing",
        }
        try:
            safe_name(result["name"])
            if mode == "new" and not branch:
                raise Error("Enter a new branch name")
            await asyncio.to_thread(
                Git.command,
                result["source"],
                result["source"].parent / result["name"],
                branch,
                result["ref"],
                result["new"],
            )
        except (Error, OSError, ValueError) as exc:
            self.query_one("#error", Static).update(str(exc))
            self.notify(str(exc), severity="error", timeout=10)
            return
        self.dismiss(result)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Launch(ModalScreen[dict[str, Any] | None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    def __init__(
        self, workspace: Workspace, tool: str, fresh: bool = False, *, cwd: str | None = None
    ):
        super().__init__()
        self.workspace = workspace
        self.tool = tool
        self.fresh = fresh
        self.cwd = cwd or workspace.path

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Label("Terminal provider — all sessions use real tmux PTYs")
            choices = [
                (name.title() + ("" if provider(name).available() else " (not installed)"), name)
                for name in PROVIDERS
            ]
            yield Select(choices, value=self.tool, id="provider")
            yield Select(self.mode_choices(self.tool), value="new", id="mode")
            paths = [("Workspace", self.workspace.path)] + [
                (r.name, str(Path(self.workspace.path) / r.name)) for r in self.workspace.repos
            ]
            yield Select(paths, value=self.cwd, id="cwd")
            yield Select(
                [("Window", "window"), ("Split pane", "split")], value="window", id="layout"
            )
            yield Checkbox(
                "Create another session instead of reusing a live match",
                value=self.fresh,
                id="fresh",
            )
            yield Label(
                "Concurrent AI sessions may edit the same files. Coordinate changes or use separate worktrees."
            )
            yield Button("Launch / attach", id="launch")
            yield Button("Cancel", id="cancel")

    @staticmethod
    def mode_choices(tool: str) -> list[tuple[str, str]]:
        choices = [("New", "new")]
        if tool == "claude":
            choices.append(("Native resume picker", "resume"))
        if tool != "shell":
            choices.append(("Continue latest", "continue"))
        return choices

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "provider" or event.value == Select.BLANK:
            return
        choices = self.mode_choices(str(event.value))
        mode = self.query_one("#mode", Select)
        previous = mode.value
        mode.set_options(choices)
        mode.value = previous if previous in {value for _, value in choices} else "new"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(
            None
            if event.button.id == "cancel"
            else {
                "tool": str(self.query_one("#provider", Select).value),
                "mode": str(self.query_one("#mode", Select).value),
                "cwd": str(self.query_one("#cwd", Select).value),
                "fresh": self.query_one("#fresh", Checkbox).value,
                "split": self.query_one("#layout", Select).value == "split",
            }
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class Settings(ModalScreen[dict[str, Any] | None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    def __init__(self, workspace: Workspace, service: Service):
        super().__init__()
        self.workspace = workspace
        self.service = service

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Label("Global defaults and provider arguments (JSON arrays)")
            choices = [(name.title(), name) for name in PROVIDERS]
            yield Select(
                choices,
                value=self.service.config.default_agent,
                allow_blank=False,
                id="global-agent",
            )
            yield Select(
                [("Warn about parallel agents", "warn"), ("Block additional agents", "block")],
                value=self.service.config.conflict_policy,
                allow_blank=False,
                id="global-policy",
            )
            for name in PROVIDERS:
                yield Label(name.title() + " arguments")
                yield Input(
                    json.dumps(self.service.config.agent_args.get(name, [])), id="args-" + name
                )
            yield Label("Workspace overrides")
            yield Select(
                [("Inherit global provider", "inherit"), *choices],
                value=self.workspace.default_agent or "inherit",
                allow_blank=False,
                id="workspace-agent",
            )
            yield Select(
                [("Inherit policy", "inherit"), ("Warn", "warn"), ("Block", "block")],
                value=self.workspace.conflict_policy or "inherit",
                allow_blank=False,
                id="workspace-policy",
            )
            yield Static("", id="error", markup=False)
            yield Button("Preview settings", id="save")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        try:
            arguments = {
                name: json.loads(self.query_one("#args-" + name, Input).value) for name in PROVIDERS
            }
            config = replace(
                self.service.config,
                default_agent=str(self.query_one("#global-agent", Select).value),
                conflict_policy=str(self.query_one("#global-policy", Select).value),
                agent_args=arguments,
            )
            config.validate()
            self.dismiss(
                {
                    "config": config,
                    "agent": str(self.query_one("#workspace-agent", Select).value),
                    "policy": str(self.query_one("#workspace-policy", Select).value),
                }
            )
        except (Error, ValueError) as exc:
            self.query_one("#error", Static).update(str(exc))

    def action_cancel(self) -> None:
        self.dismiss(None)


def ui_operation(method: Callable[..., Any]) -> Callable[..., Any]:
    """Claim wizard ownership synchronously, before scheduling a worker."""

    @wraps(method)
    def begin(self: Manager, *args: Any, **kwargs: Any) -> Any:
        if self.dialog_busy or self.history_resuming or len(self.screen_stack) > 1:
            return None
        self.dialog_busy = True
        focus = self.focused
        self.update_dashboard()
        return self.run_operation(method, focus, args, kwargs)

    return begin


class Manager(App[None]):
    TITLE = "Workspace Manager 2.0"
    CSS_PATH = Path(__file__).with_name("dashboard.tcss")
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("enter", "open", "Open"),
        Binding("q", "quit", "Quit"),
        *[
            Binding(key, action, label, show=False)
            for key, action, label in (
                ("n", "create", "New workspace"),
                ("a", "add", "Add repo"),
                ("t", "terminal", "Open terminal"),
                ("v", "new_terminal", "New terminal"),
                ("c", "claude", "Claude"),
                ("x", "codex", "Codex"),
                ("g", "refresh", "Git status"),
                ("r", "refresh", "Refresh"),
                ("s", "settings", "Settings"),
                ("m", "memory", "Workspace memory"),
                ("d", "delete", "Safe delete"),
                ("slash", "search", "Search"),
            )
        ],
    ]

    def __init__(
        self,
        service: Service,
        *,
        presenter: Callable[..., None] | None = None,
        displayed: Callable[[], str | None] | None = None,
        detach_view: Callable[..., None] | None = None,
        tab_request: Callable[[], str] | None = None,
        tab_names: Callable[[dict[str, list[dict[str, str]]]], None] | None = None,
    ):
        super().__init__()
        self.presenter = presenter
        self.displayed = displayed
        self.detach_view = detach_view
        self.tab_request = tab_request
        self.tab_names = tab_names
        self.tab_polling = False
        self.presentation_lock = asyncio.Lock()
        self.presentation_cancel = threading.Event()
        self.active_view: str | None = None
        self.last_sidebar_warning: str | None = None
        self.sidebar_message_details: str | None = None
        self.session_rows: dict[str, dict[str, str]] = {}
        self.selected_worktree: tuple[str, str] | None = None
        self.workspace_sessions: dict[str, list[dict[str, str]]] = {}
        self.compact_snapshots: dict[str, object] = {}
        self.explorer_expansion: dict[tuple[str, str | None], bool] = {}
        self.explorer = WorkspaceExplorer() if presenter else None
        self.sessions = SessionCards() if presenter else None
        self.conversations = ExplorerTree("conversation-list") if presenter else None
        self.menu_key = os.environ.get("WM_EXPLORER_MENU_KEY", "f10")
        if presenter:
            self.title = "Workspace Manager 3.0"
            self.bind(self.menu_key, "context_menu", description="Menu", show=False)
        self.register_theme(WORKSPACE_THEME)
        self.theme = WORKSPACE_THEME.name
        self.service = service
        self.dialog_busy = False
        self.refresh_loading = False
        self.refresh_epoch = 0
        self.refresh_worker: Worker[None] | None = None
        self.history_loading = False
        self._restore_focus = True
        self.values: dict[str, Workspace] = {}
        self.history_cwd: Path | None = None
        self.history_workspace: str | None = None
        self.history_rows: dict[str, Conversation] = {}
        self.custom_titles: dict[str, str] = {}
        self.history_cursor: str | None = None
        self.history_resuming = False
        self.history_revision = 0
        self.history_lock = asyncio.Lock()
        self.current: str | None = None
        self.details_workspace: str | None = None
        self.cache: dict[str, tuple[float, tuple[str, ...], dict[str, dict[str, str]]]] = {}

    def get_css_variables(self) -> dict[str, str]:
        # Keep project tokens available if the built-in command palette switches
        # the surrounding Textual theme; no unresolved TCSS variables on refresh.
        return {
            **super().get_css_variables(),
            **{
                "wm-" + key: value
                for key, value in (
                    PREMIUM_PALETTE if getattr(self, "presenter", None) else PALETTE
                ).items()
            },
        }

    def compose(self) -> ComposeResult:
        if self.explorer:
            with Horizontal(id="sidebar-heading"):
                yield Static("Workspace Manager", id="sidebar-title")
                yield Button("⋯", id="sidebar-menu", tooltip="Workspace Manager actions")
        else:
            yield Header(icon="●")
        with VerticalScroll(id="body", classes="workspace-sidebar" if self.explorer else None):
            if self.explorer:
                with Horizontal(classes="sidebar-search"):
                    yield Static("⌕", classes="search-icon")
                    yield Input(placeholder="Search...", id="search")
            else:
                yield Input(placeholder="Search workspace by name or path", id="search")
            yield DashboardSection(
                "workspace",
                "Explorer" if self.explorer else "Workspaces",
                "workspaces",
                (
                    SectionAction(
                        "workspace-new",
                        "+ New",
                        "+",
                        "Create a workspace using the existing wizard",
                    ),
                    SectionAction(
                        "workspace-refresh", "Refresh", "↻", "Refresh workspace list and Git status"
                    ),
                ),
                "No workspaces"
                if self.explorer
                else "No workspaces. Use + New or N to create one.",
                tree=self.explorer,
            )
            yield DashboardSection(
                "repo",
                "Repositories",
                "repos",
                (
                    SectionAction(
                        "repo-add",
                        "+ Add repo",
                        "+",
                        "Add a Git worktree to the selected workspace",
                        True,
                    ),
                    SectionAction(
                        "repo-refresh", "Refresh", "↻", "Refresh repositories and Git status", True
                    ),
                ),
                "Select a workspace to see its repositories.",
            )
            if self.explorer:
                yield Static("Select a worktree", id="worktree-context", markup=False)
            yield DashboardSection(
                "terminal",
                "Sessions" if self.explorer else "Terminals",
                "terminals",
                (
                    SectionAction(
                        "terminal-new", "+ New", "+", "Choose Claude, Codex or Shell", True
                    ),
                    SectionAction(
                        "terminal-attach",
                        "Attach",
                        "↵",
                        "Attach selected terminal; detach with Ctrl-b then d",
                        True,
                    ),
                ),
                "No sessions"
                if self.sessions
                else "No terminals. Create one with + New; existing processes are preserved.",
                tree=self.sessions,
            )
            yield DashboardSection(
                "history",
                "Recent conversations" if self.explorer else "Conversations",
                "conversations",
                (
                    SectionAction(
                        "history-refresh", "Refresh", "↻", "Refresh saved Codex conversations", True
                    ),
                    SectionAction(
                        "history-native",
                        "Resume picker",
                        "Resume",
                        "Open native Codex conversation picker",
                        True,
                    ),
                ),
                "No conversations"
                if self.explorer
                else "No saved conversations for the selected directory.",
                tree=self.conversations,
                collapsed=False,
            )
            if self.explorer:
                yield ActionButton("All sessions", id="all-sessions", classes="context-action")
                yield ActionButton(
                    "View all conversations", id="all-conversations", classes="context-action"
                )
                yield ActionButton("Workspace Memory", id="memory-open", classes="context-action")
            yield Static("", id="message", markup=False)
        if self.explorer:
            yield Static("0 sessions · ^b z", id="session-status", markup=False)
        else:
            yield Footer()

    def on_mount(self) -> None:
        if self.explorer:
            try:
                self.custom_titles = ConversationTitles(self.service).read()
            except (Error, OSError) as exc:
                self.message(str(exc))
        self.query_one("#workspaces", DataTable).add_columns("Name", "Phase", "Status", "Path")
        self.query_one("#repos", DataTable).add_columns(
            "Repository", "Branch / HEAD", "Status", "Changes"
        )
        self.query_one("#terminals", DataTable).add_columns(
            "Pane", "Process", "Directory", "State", "Kind"
        )
        self.query_one("#conversations", DataTable).add_columns("Conversation", "Updated", "State")
        if self.explorer is None:
            self.query_one("#workspaces", DataTable).focus()
        else:
            self.explorer.focus()
        if self.explorer:
            self.query_one("#repo-section").display = False
            for selector in (
                "#workspace-refresh",
                "#terminal-attach",
                "#history-refresh",
                "#history-native",
                "#workspace-menu",
                "#terminal-menu",
                "#history-menu",
            ):
                self.query_one(selector).display = False
            self.set_interval(1, self.refresh_active_view)
        self.action_refresh()
        self.set_interval(15, self.action_refresh)
        self.update_dashboard()

    def selected_key(self, table_id: str) -> str | None:
        table = self.query_one("#" + table_id, DataTable)
        return table.ordered_rows[table.cursor_row].key.value if table.row_count else None

    def focus_row(self, table_id: str, key: str) -> None:
        table = self.query_one("#" + table_id, DataTable)
        section = table.parent.parent if table.parent is not None else None
        if isinstance(section, DashboardSection) and section.collapsed:
            section.toggle()
        if any(row.key.value == key for row in table.ordered_rows):
            table.move_cursor(row=table.get_row_index(key), scroll=True)
            if self.explorer is not None and table_id in {"workspaces", "repos"}:
                explorer = self.explorer
                data = (key, None) if table_id == "workspaces" else (self.current, key)
                node = next((item for item in explorer.nodes() if item.data == data), None)
                if node is not None:
                    parent = node.parent
                    while parent is not None:
                        parent.expand()
                        parent = parent.parent
                    explorer.call_after_refresh(explorer.move_cursor, node)
                explorer.focus()
                explorer.scroll_visible(animate=False)
            else:
                table.focus()
                table.scroll_visible(animate=False)
            self._restore_focus = False

    def section_actions(self, section: str) -> tuple[SectionAction, ...]:
        workspace = self.values.get(str(self.current))
        has_workspace = workspace is not None
        idle = not self.dialog_busy and not self.history_resuming
        has_repo = (
            has_workspace
            and self.details_workspace == self.current
            and self.selected_key("repos") is not None
        )
        if self.explorer:
            has_repo = has_repo and self.selected_worktree == (
                self.current,
                self.selected_key("repos"),
            )
        has_pane = has_workspace and self.selected_key("terminals") is not None
        if has_pane:
            table = self.query_one("#terminals", DataTable)
            has_pane = table.get_row_at(table.cursor_row)[3] == "0"
        has_history = (
            has_workspace
            and self.history_workspace == self.current
            and self.history_cwd is not None
        )
        has_conversation = has_history and self.selected_key("conversations") in self.history_rows

        def action(key: str, label: str, enabled: bool, description: str) -> SectionAction:
            return SectionAction(key, label, label, description, not enabled)

        if section == "workspace":
            has_workspace_row = self.selected_key("workspaces") is not None
            return (
                action("workspace-new", "New workspace", idle, "Create a workspace"),
                action(
                    "workspace-refresh",
                    "Refresh",
                    not self.refresh_loading,
                    "Refreshing Git status..."
                    if self.refresh_loading
                    else "Refresh workspace list and Git status",
                ),
                action(
                    "workspace-open",
                    "Open workspace",
                    has_workspace_row and idle,
                    "Open selected workspace" if has_workspace_row else "Select a workspace first",
                ),
                action(
                    "workspace-memory",
                    "Workspace memory",
                    has_workspace and idle,
                    "Read selected workspace memory",
                ),
                action(
                    "workspace-settings",
                    "Settings",
                    has_workspace and idle,
                    "Configure selected workspace",
                ),
                action(
                    "workspace-delete",
                    "Delete workspace",
                    has_workspace and idle,
                    "Confirm unregistering workspace; repositories must be removed first",
                ),
            )
        if section == "repo":
            return (
                action(
                    "repo-add",
                    "Add repo",
                    has_workspace and idle,
                    "Select a workspace, then add a worktree",
                ),
                action(
                    "repo-refresh",
                    "Refresh",
                    has_workspace and not self.refresh_loading,
                    "Refresh Git status without changing worktrees",
                ),
                action(
                    "repo-status",
                    "Git status",
                    bool(has_repo) and idle,
                    "Read selected repository status",
                ),
                action(
                    "repo-switch",
                    "Switch branch",
                    bool(has_repo) and idle,
                    "Switch the selected clean worktree to an existing local branch",
                ),
                action(
                    "repo-remove",
                    "Remove worktree",
                    bool(has_repo) and idle,
                    "Confirm removal; dirty, untracked and ignored files are protected",
                ),
            )
        if section == "terminal":
            actions = [
                action(
                    "terminal-new",
                    "New terminal",
                    has_workspace and idle,
                    "Choose a provider and terminal directory",
                ),
                action(
                    "terminal-attach",
                    "Open / Focus" if self.sessions else "Attach",
                    bool(has_pane) and idle,
                    "Select a live terminal first; detach with Ctrl-b then d",
                ),
                action(
                    "terminal-close",
                    "Terminate" if self.sessions else "Close selected terminal",
                    has_workspace
                    and self.details_workspace == self.current
                    and self.selected_key("terminals") is not None
                    and idle,
                    "Close the selected panel after confirmation",
                ),
            ]
            if self.sessions:
                key = self.selected_key("terminals")
                actions += [
                    action("terminal-rename", "Rename", idle and bool(has_pane), "Set a title"),
                    action(
                        "terminal-detach",
                        "Detach",
                        idle
                        and self.detach_view is not None
                        and self.active_view == f"{self.current}/{key}",
                        "Return to the home shell and keep the process running",
                    ),
                    action(
                        "terminal-details",
                        "Details",
                        idle and key is not None,
                        "Show session details",
                    ),
                ]
            for name in ("claude", "codex", "shell"):
                installed = provider(name).available()
                actions.append(
                    action(
                        "terminal-" + name,
                        "New " + name.title() + " terminal",
                        has_workspace and idle and installed,
                        "Choose terminal options"
                        if installed
                        else name.title() + " is not installed or not in PATH",
                    )
                )
            return tuple(actions)
        if section == "memory":
            return (
                action(
                    "memory-open",
                    "Open workspace memory",
                    has_workspace and idle,
                    "Read the selected workspace memory",
                ),
            )
        if section == "history":
            installed = provider("codex").available()
            ready = bool(has_history) and idle and not self.history_loading
            return (
                action(
                    "history-refresh",
                    "Refresh history",
                    ready,
                    "Select a workspace/repository; wait for history loading to finish",
                ),
                action(
                    "history-native",
                    "Resume picker",
                    ready and installed,
                    "Open Codex native picker"
                    if installed
                    else "Codex is not installed or not in PATH",
                ),
                *(
                    ()
                    if self.explorer
                    else (
                        action(
                            "history-more",
                            "Load older",
                            ready and self.history_cursor is not None,
                            "Load another page; disabled when no older page is available",
                        ),
                    )
                ),
                action(
                    "history-resume",
                    "Resume selected",
                    ready and bool(has_conversation) and installed,
                    "Select a conversation to resume its exact ID"
                    if installed
                    else "Codex is not installed or not in PATH",
                ),
                *(
                    (
                        action(
                            "history-rename",
                            "Rename",
                            idle and bool(has_conversation),
                            "Set or restore the local title",
                        ),
                    )
                    if self.explorer
                    else ()
                ),
                action(
                    "history-details",
                    "Details",
                    idle and bool(has_conversation),
                    "Read saved conversation metadata",
                ),
            )
        return ()

    def update_dashboard(self) -> None:
        if not self.is_running or not self.query(DashboardSection):
            return
        self.screen_stack[0].set_class(self.size.height <= 30, "-compact")
        maximum_rows = rows_for_height(self.size.height)
        if self.explorer:
            self.refresh_compact_sidebar()
        for section in self.query(DashboardSection):
            section.refresh_layout(maximum_rows)
            loading = (
                self.refresh_loading
                if section.section in {"workspace", "repo"}
                else self.history_loading or self.history_resuming
                if section.section == "history"
                else False
            )
            section.query_one(SectionHeader).set_loading(loading)
            actions = {action.id: action for action in self.section_actions(section.section)}
            for button in section.query(SectionHeader).first().query(Button):
                if button.id in actions:
                    action = actions[str(button.id)]
                    button.disabled = action.disabled
                    button.tooltip = action.description
            section.query_one("#" + section.section + "-toggle", Button).disabled = self.dialog_busy
            section.query_one("#" + section.section + "-menu", Button).disabled = (
                self.dialog_busy or self.history_resuming
            )

    def on_resize(self) -> None:
        self.update_dashboard()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "memory-open":
            self.dispatch("memory-open")
        elif event.button.id == "all-sessions":
            self.action_all_sessions()
        elif event.button.id == "all-conversations":
            self.action_all_conversations()
        elif event.button.id == "sidebar-menu":
            self.open_sidebar_menu()

    def on_section_header_requested(self, event: SectionHeader.Requested) -> None:
        event.stop()
        self.dispatch(event.action)

    def dispatch(self, action: str) -> None:
        section = action.split("-", 1)[0]
        if action.endswith("-toggle"):
            if not self.dialog_busy:
                self.query_one("#" + section + "-section", DashboardSection).toggle()
            return
        if action.endswith("-menu"):
            self.open_menu(section)
            return
        entry = next((item for item in self.section_actions(section) if item.id == action), None)
        if entry is None or entry.disabled:
            if entry is not None:
                self.message(entry.description)
            return
        handlers: dict[str, Callable[[], Any]] = {
            "workspace-new": self.action_create,
            "workspace-refresh": self.action_refresh,
            "workspace-open": self.action_open_workspace,
            "workspace-memory": self.action_memory,
            "memory-open": self.action_memory,
            "workspace-settings": self.action_settings,
            "workspace-delete": lambda: self.action_delete("workspace"),
            "repo-add": self.action_add,
            "repo-refresh": self.action_refresh,
            "repo-status": self.action_repo_status,
            "repo-switch": self.action_repo_switch,
            "repo-remove": lambda: self.action_delete("repo"),
            "terminal-new": self.action_new_terminal,
            "terminal-attach": lambda: self.attach(self.selected_key("terminals")),
            "terminal-close": self.action_close_terminal,
            "terminal-rename": self.action_rename_session,
            "terminal-details": self.action_session_details,
            "terminal-detach": self.action_detach_session,
            "terminal-claude": lambda: self.launch_ai("claude", True),
            "terminal-codex": lambda: self.launch_ai("codex", True),
            "terminal-shell": lambda: self.launch_ai("shell", True),
            "history-refresh": lambda: (
                self.select_history(self.history_cwd) if self.history_cwd else None
            ),
            "history-native": lambda: self.resume_history(None),
            "history-more": lambda: self.load_history(self.history_revision, True),
            "history-resume": lambda: self.resume_history(self.selected_key("conversations")),
            "history-details": self.action_history_details,
            "history-rename": self.action_rename_conversation,
        }
        handlers[action]()

    def open_sidebar_menu(self) -> None:
        if self.dialog_busy or self.history_resuming or len(self.screen_stack) > 1:
            return
        entries = (
            ("workspace-menu", "Explorer actions"),
            ("terminal-menu", "Session actions"),
            ("all-sessions", "All sessions"),
            ("all-conversations", "View all conversations"),
            ("history-menu", "Conversation actions"),
            ("memory-open", "Read workspace memory"),
            ("workspace-refresh", "Refresh workspace"),
            ("sidebar-help", "Help"),
        )
        actions = [
            SectionAction(
                key,
                label,
                label,
                label,
                key == "memory-open"
                and self.current is None
                or key == "workspace-refresh"
                and self.refresh_loading,
            )
            for key, label in entries
        ]
        if self.last_sidebar_warning:
            actions.append(SectionAction("sidebar-warning", "Last warning", "", ""))

        if self.sidebar_message_details:
            actions.append(SectionAction("sidebar-message", "Last message", "", ""))

        def chosen(key: str | None) -> None:
            if key == "sidebar-message":
                self.push_screen(Information("Last message", self.sidebar_message_details or ""))
            elif key == "all-sessions":
                self.action_all_sessions()
            elif key == "all-conversations":
                self.action_all_conversations()
            elif key == "sidebar-help":
                self.action_help()
            elif key == "sidebar-warning":
                self.push_screen(Information("Last warning", self.last_sidebar_warning or ""))
            elif key:
                self.dispatch(key)

        self.push_screen(
            SectionMenu(
                "Workspace Manager", tuple(actions), self.query_one("#sidebar-menu", Button)
            ),
            chosen,
        )

    def open_menu(self, section: str) -> None:
        if self.dialog_busy or self.history_resuming:
            return
        if isinstance(self.screen, SectionMenu):
            self.pop_screen()
        elif len(self.screen_stack) > 1:
            return

        def selection(action: str) -> tuple[object, ...]:
            if action == "workspace-open":
                return (self.selected_key("workspaces"),)
            if action in {"repo-status", "repo-remove", "repo-switch"}:
                return (self.current, self.selected_key("repos"))
            if action in {
                "terminal-attach",
                "terminal-close",
                "terminal-rename",
                "terminal-details",
                "terminal-detach",
            }:
                return (self.current, self.selected_key("terminals"))
            if action in {"history-resume", "history-details", "history-rename"}:
                return (self.history_revision, self.selected_key("conversations"))
            if section == "history":
                return (self.history_revision,)
            if action.endswith("-refresh"):
                return ()
            return (self.current,)

        actions = self.section_actions(section)
        if section == "workspace" and self.explorer:
            actions += self.section_actions("repo")
        snapshots = {action.id: selection(action.id) for action in actions}

        def chosen(action: str | None) -> None:
            if action is None:
                return
            if selection(action) != snapshots[action]:
                self.message("Selection changed; reopen the menu for the current context.")
                return
            self.dispatch(action)

        anchor = self.query_one(
            "#sidebar-menu" if self.explorer else "#" + section + "-menu", Button
        )
        self.push_screen(SectionMenu(section.title(), actions, anchor), chosen)

    def action_open(self) -> None:
        focused = self.focused
        if isinstance(focused, SessionCards):
            focused.action_select()
        elif isinstance(focused, (SectionTable, ExplorerTree)):
            focused.action_select_cursor()
        else:
            self.action_open_workspace()

    def action_open_workspace(self) -> None:
        key = self.selected_key("workspaces")
        if key is not None:
            self.open_workspace(key)

    @work(exclusive=True, group="workspace-open")
    async def open_workspace(self, key: str) -> None:
        try:
            await self.choose_row("workspaces", key)
            self.message(f"Opened workspace {self.selected().name}.")
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    @work(group="dialog-operation")
    async def run_operation(
        self, method: Callable[..., Any], focus: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        self._restore_focus = True
        try:
            await method(self, *args, **kwargs)
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))
        finally:
            self.dialog_busy = False
            self.update_dashboard()
            if (
                self._restore_focus
                and focus is not None
                and focus.is_mounted
                and len(self.screen_stack) == 1
            ):
                focus.focus()

    @ui_operation
    async def action_repo_switch(self) -> None:
        try:
            workspace = self.selected()
            name = self.selected_key("repos")
            if name is None or self.details_workspace != workspace.id:
                raise Error("Select a repository first")
            repo, path = self.service.repo_target(workspace, name)
            expected_head = (await asyncio.to_thread(Git.status, path))["branch"]
            branch = await self.push_screen_wait(RenameSession("", branch=True))
            if not branch:
                return
            confirmation = Confirm(f"Switch {name} to local branch {branch}?", focus_cancel=True)
            if await self.push_screen_wait(confirmation):
                await asyncio.to_thread(
                    self.service.switch_branch,
                    workspace.id,
                    name,
                    branch,
                    True,
                    expected_repo=repo,
                    expected_head=expected_head,
                )
                await self.refresh_after_operation()
                self.message(f"Worktree {name} switched to {branch}.")
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    @ui_operation
    async def action_repo_status(self) -> None:
        workspace = self.selected()
        name = self.selected_key("repos")
        if name is None or self.details_workspace != workspace.id:
            raise Error("Select a repository first")
        path = Path(workspace.path) / name
        status = await asyncio.to_thread(Git.status, path)
        details = await asyncio.to_thread(
            run, ["git", "-C", str(path), "status", "--short", "--untracked-files=all"]
        )
        await self.push_screen_wait(
            Information(
                "Git status — " + name,
                f"{path}\nBranch: {status['branch']}\nStatus: {status['status']}\n{details or 'No changes'}",
            )
        )

    @ui_operation
    async def action_history_details(self) -> None:
        key = self.selected_key("conversations")
        if key not in self.history_rows:
            raise Error("Select a saved conversation first")
        conversation = self.history_rows[key]
        await self.push_screen_wait(
            Information(
                "Conversation details",
                (
                    f"{conversation.title}\nProvider: Codex\nID: {conversation.id}\n"
                    f"Directory: {conversation.cwd}\nUpdated: {conversation.updated_at}\n"
                    "Saved metadata does not prove a conversation has ended in another terminal."
                ),
            )
        )

    def message(self, value: str) -> None:
        widget = self.query_one("#message", Static)
        if self.explorer:
            blocked = value.endswith("Blocked by configured conflict_policy.")
            first_line = "Launch blocked by policy" if blocked else " ".join(value.splitlines())
            rendered = Text(first_line, no_wrap=True, overflow="ellipsis")
            self.sidebar_message_details = value or None
            widget.update(rendered)
        else:
            widget.update(value)

    def launch_warning(self, message: str) -> None:
        if self.explorer:
            self.last_sidebar_warning = message
            self.notify(
                "Other agents are running in this workspace. See Last warning.",
                severity="warning",
                timeout=5,
            )
        else:
            self.message("Warning: " + message)
            self.notify(message, severity="warning", timeout=10)

    def selected(self) -> Workspace:
        if self.current not in self.values:
            raise Error("Select a workspace first")
        return self.values[str(self.current)]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.action_refresh(False)

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_refresh(self, force: bool = True) -> Worker[None]:
        worker = self.refresh_snapshot(force)
        self.refresh_worker = worker
        return worker

    async def refresh_after_operation(self) -> None:
        worker = self.action_refresh()
        while True:
            try:
                await worker.wait()
                return
            except WorkerCancelled:
                latest = self.refresh_worker
                task = asyncio.current_task()
                if latest is None or latest is worker or (task is not None and task.cancelling()):
                    raise asyncio.CancelledError from None
                worker = latest

    @work(exclusive=True, group="refresh")
    async def refresh_snapshot(self, force: bool = True) -> None:
        self.refresh_epoch += 1
        epoch = self.refresh_epoch
        self.refresh_loading = True
        self.update_dashboard()
        try:
            values = await asyncio.to_thread(self.service.list)
            query = self.query_one("#search", Input).value.lower()
            table = self.query_one("#workspaces", DataTable)
            rows = []
            if force:
                self.cache.clear()
            for workspace in values:
                terms = [workspace.name, workspace.path]
                if self.explorer:
                    terms.extend(
                        f"{repo.name} {repo.source} {repo.branch}" for repo in workspace.repos
                    )
                if query not in " ".join(terms).lower():
                    continue
                states = await self.repo_states(workspace)
                statuses = [state["status"] for state in states.values()]
                summary = next(
                    (s for s in ("unknown", "missing", "modified") if s in statuses), "clean"
                )
                if workspace.phase != "ready":
                    summary = workspace.phase
                rows.append(
                    (
                        workspace.id,
                        (
                            workspace.name,
                            workspace.phase,
                            summary,
                            workspace.path,
                        ),
                    )
                )
            # Collect first: no empty/partial table is painted while Git is pending.
            if query != self.query_one("#search", Input).value.lower():
                return
            self.values = {w.id: w for w in values}
            if self.explorer:
                await self.refresh_session_markers(values, epoch)
                if epoch != self.refresh_epoch:
                    return
            self.sync_table(table, rows)

            visible = {key for key, _ in rows}
            if self.current is not None and self.current not in visible and visible:
                self.selected_worktree = None
                self.current = self.selected_key("workspaces")
                if self.current is not None:
                    self.select_history(Path(self.selected().path))
            if self.current in visible:
                await self.details()
            elif self.current is not None:
                self.selected_worktree = None
                self.current = self.details_workspace = None
                self.history_workspace = None
                self.history_cwd = None
                self.history_revision += 1
                self.history_rows.clear()
                self.history_cursor = None
                self.history_loading = False
                for table_id in ("repos", "terminals", "conversations"):
                    self.query_one("#" + table_id, DataTable).clear()
                self.query_one("#history-label", Label).update("Select a workspace or repository")
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))
        finally:
            if epoch == self.refresh_epoch:
                self.refresh_loading = False
                self.update_dashboard()

    async def refresh_session_markers(self, workspaces: list[Workspace], epoch: int) -> None:
        def collect() -> dict[str, list[dict[str, str]]]:
            result = {}
            for workspace in workspaces:
                if workspace.phase != "ready" or workspace.id == self.current:
                    continue
                try:
                    result[workspace.id] = Tmux().list(workspace)
                except (Error, OSError):
                    continue
            return result

        result = await asyncio.to_thread(collect)
        if epoch == self.refresh_epoch:
            key = self.current
            if key is not None and key in self.workspace_sessions:
                result[key] = self.workspace_sessions[key]
            self.workspace_sessions = result

    @work(group="active-display")
    async def refresh_active_view(self) -> None:
        if self.displayed is None or self.tab_polling:
            return
        self.tab_polling = True
        try:
            active = await asyncio.to_thread(self.displayed)
            if active != self.active_view:
                if active and self.tab_request is not None:
                    owner, pane = active.split("/", 1)
                    workspace = self.values.get(owner)
                    if workspace is None:
                        return  # Initial registry refresh may still be running.
                    peers = await asyncio.to_thread(Tmux().list, workspace)
                    if await asyncio.to_thread(self.displayed) != active:
                        return
                    row = next((item for item in peers if item["pane"] == pane), None)
                    if row is not None:
                        repo = self.session_worktree(workspace, row.get("start") or row["cwd"])
                        worktree = repo.name if repo else None
                        if self.current != owner or self.selected_worktree != (
                            (owner, worktree) if worktree else None
                        ):
                            table = self.query_one("#workspaces", DataTable)
                            if owner not in {row.key.value for row in table.ordered_rows}:
                                with self.prevent(Input.Changed):
                                    self.query_one("#search", Input).value = ""
                                await self.refresh_after_operation()
                            if await asyncio.to_thread(self.displayed) != active:
                                return
                            self.active_view = active
                            await self.activate_explorer((owner, worktree))
                            if await asyncio.to_thread(self.displayed) != active:
                                return
                            if self.explorer is not None:
                                node = next(
                                    (
                                        node
                                        for node in self.explorer.nodes()
                                        if node.data == (owner, worktree)
                                    ),
                                    None,
                                )
                                if node is not None:
                                    parent = node.parent
                                    while parent is not None:
                                        parent.expand()
                                        parent = parent.parent
                                    self.explorer.call_after_refresh(
                                        self.explorer.move_cursor, node
                                    )
                self.active_view = active
                self.update_dashboard()
                if active is None:
                    self.action_refresh(False)
                if active and self.sessions is not None:
                    pane = active.split("/", 1)[1]
                    if any(option.id == pane for option in self.sessions.options):
                        self.sessions.highlighted = self.sessions.get_option_index(pane)
            if self.tab_names is not None:
                await asyncio.to_thread(self.tab_names, self.workspace_sessions.copy())
            if (
                self.tab_request is not None
                and not self.dialog_busy
                and len(self.screen_stack) == 1
            ):
                request = await asyncio.to_thread(self.tab_request)
                if request == "new":
                    self.action_new_terminal()
                elif request == "all":
                    self.action_all_sessions()
                elif request.startswith("error:"):
                    self.message(request[6:])
        except (Error, OSError, ValueError) as exc:
            if self.is_running:
                self.message(str(exc))
        finally:
            self.tab_polling = False

    def worktree_path(self, workspace: Workspace) -> Path | None:
        key = self.selected_worktree
        if (
            key is not None
            and key[0] == workspace.id
            and any(repo.name == key[1] for repo in workspace.repos)
        ):
            return Path(workspace.path) / key[1]
        return None

    def conversation_title(self, item: Conversation) -> str:
        return self.custom_titles.get(f"codex:{item.id}", item.title)

    async def rename_conversation(self, item: Conversation) -> None:
        title = await self.push_screen_wait(
            RenameSession(
                self.custom_titles.get(f"codex:{item.id}", ""),
                conversation=True,
            )
        )
        if title is not None:
            store = ConversationTitles(self.service)
            await asyncio.to_thread(store.set, "codex", item.id, title)
            self.custom_titles = await asyncio.to_thread(store.read)
            self.update_dashboard()

    @ui_operation
    async def action_rename_conversation(self) -> None:
        item = self.history_rows.get(self.selected_key("conversations") or "")
        if item is not None and self.history_scope_matches(item):
            await self.rename_conversation(item)

    def history_scope_matches(self, item: Conversation) -> bool:
        return (
            item.cwd is not None
            and self.history_cwd is not None
            and (item.cwd.resolve() == self.history_cwd.resolve())
        )

    @ui_operation
    async def action_all_sessions(self) -> None:
        def collect() -> list[tuple[Workspace, dict[str, str]]]:
            result: list[tuple[Workspace, dict[str, str]]] = []
            for workspace in self.service.list():
                if workspace.phase == "ready":
                    try:
                        result.extend((workspace, item) for item in Tmux().list(workspace))
                    except (Error, OSError):
                        continue
            return result

        sessions = await asyncio.to_thread(collect)
        targets = {f"{owner.id}/{item['pane']}": (owner, item) for owner, item in sessions}
        rows = []
        for key, (owner, pane) in targets.items():
            repo = self.session_worktree(owner, pane.get("start") or pane["cwd"])
            kind = (pane["kind"] or pane["command"]).title()
            location = (
                f"{owner.name} / {Path(repo.source).name} / {repo.name}" if repo else owner.name
            )
            state = (
                "ended"
                if pane["dead"] == "1"
                else "connected"
                if key == self.active_view
                else "live"
            )
            active = "● " if state == "connected" else ""
            name = pane.get("name")
            label = f"{active}{kind} {pane['pane']} · {state}\n{location}"
            rows.append((key, f"{label} · {name}" if name else label))
        key = await self.push_screen_wait(GlobalSessions(rows))
        if key is not None and key in targets:
            owner, pane = targets[key]
            if pane["dead"] == "1":
                self.message("Session ended")
            elif self.presenter is not None:
                self.present_terminal(owner, pane["pane"], expected=pane.get("identity"))

    @ui_operation
    async def action_all_conversations(self) -> None:
        owners_by_path: dict[Path, set[str]] = {}
        scope_options = []
        for workspace in await asyncio.to_thread(self.service.list):
            if workspace.phase != "ready":
                continue
            root = Path(workspace.path)
            locations = {root}
            sources: dict[str, set[Path]] = {}
            for repo in workspace.repos:
                if repo.phase != "ready":
                    continue
                path = root / repo.name
                locations.add(path)
                sources.setdefault(repo.source, set()).add(path)
                scope_options.append(
                    HistoryScope(
                        str(path), f"{workspace.name} / {repo.name}", frozenset({path}), path
                    )
                )
            for source, paths in sources.items():
                if len(paths) > 1:
                    scope_options.append(
                        HistoryScope(
                            f"{workspace.id}/{source}",
                            f"{workspace.name} / {Path(source).name} (repo)",
                            frozenset(paths),
                        )
                    )
            scope_options.append(
                HistoryScope(
                    workspace.id, f"{workspace.name} (workspace)", frozenset(locations), root
                )
            )
            for path in locations:
                owners_by_path.setdefault(path, set()).add(workspace.id)
        selected_workspace = self.values.get(self.current or "")
        context = self.worktree_path(selected_workspace) if selected_workspace else None
        active_location = (context or Path(selected_workspace.path)) if selected_workspace else None
        while True:
            choice = await self.push_screen_wait(
                HistoryBrowser(scope_options, self.conversation_title, context, active_location)
            )
            if choice is None:
                return
            if choice.action == "rename" and choice.item is not None:
                await self.rename_conversation(choice.item)
                continue
            if choice.action == "claude":
                cwd = choice.cwd
                owners = owners_by_path.get(cwd, set()) if cwd is not None else set()
                if cwd is None or len(owners) != 1:
                    self.message("Select a registered location for the Claude picker")
                    return
                self.history_resuming = True
                self.launch_history(next(iter(owners)), cwd, None, "claude", True)
                return
            if choice.item is None:
                return
            item = choice.item
            owners = (
                owners_by_path.get(item.cwd, set())
                if item.cwd is not None and item.cwd.is_dir()
                else set()
            )
            if len(owners) == 1 and item.cwd is not None:
                cwd, owner = item.cwd, next(iter(owners))
            else:
                workspace = self.selected()
                cwd = context or Path(workspace.path)
                owner = workspace.id
                if not await self.push_screen_wait(
                    Confirm(
                        f"Original location is unavailable. Resume in {cwd}?", focus_cancel=True
                    )
                ):
                    continue
            self.history_resuming = True
            self.launch_history(owner, cwd, item.id, "codex", True)
            return

    def refresh_compact_sidebar(self) -> None:
        assert self.explorer is not None and self.sessions is not None
        assert self.conversations is not None
        workspace_table = self.query_one("#workspaces", DataTable)
        workspace_rows = [
            self.values.get(row.key.value or "") for row in workspace_table.ordered_rows
        ]
        explorer_rows: list[tuple[int, tuple[str, str | None], str | Text, bool]] = []
        for workspace in workspace_rows:
            if workspace is None:
                continue
            states = self.cache.get(workspace.id, (0, (), {}))[2]
            sessions = self.workspace_sessions.get(workspace.id, [])
            groups: dict[str, list[tuple[str, str, bool, bool]]] = {}
            for repo in workspace.repos:
                path = Path(workspace.path) / repo.name
                live_panes = [
                    pane["pane"]
                    for pane in sessions
                    if pane["dead"] == "0"
                    and Path(pane.get("start") or pane["cwd"]).is_relative_to(path)
                ]
                current = any(self.active_view == f"{workspace.id}/{pane}" for pane in live_panes)
                branch = states.get(repo.name, {}).get("branch") or repo.branch or repo.name
                groups.setdefault(repo.source, []).append(
                    (repo.name, branch, bool(live_panes), current)
                )
            explorer_rows.append(
                (
                    0,
                    (workspace.id, None),
                    Text.assemble(
                        (self.explorer.type_icon(0) + " ", PREMIUM_PALETTE["accent"]),
                        (
                            workspace.name,
                            "bold underline"
                            if workspace.id == self.current and self.selected_worktree is None
                            else "bold",
                        ),
                    ),
                    workspace.id == self.current,
                )
            )
            for source, worktrees in groups.items():
                repository_label = Text.assemble(
                    (self.explorer.type_icon(1) + " ", PREMIUM_PALETTE["muted"]),
                    Path(source).name,
                )
                explorer_rows.append((1, (workspace.id, source), repository_label, True))
                for name, branch, live, current in worktrees:
                    selected = self.selected_worktree == (workspace.id, name)
                    color = PREMIUM_PALETTE["accent" if current else "muted"]
                    label = Text.assemble(
                        (self.explorer.type_icon(2) + " ", color),
                        (branch, f"{color} underline" if selected else color),
                    )
                    if name != Path(source).name and name != branch:
                        label.append(f" · {name}", style=PREMIUM_PALETTE["muted"])
                    if live:
                        label.append(" •", style=PREMIUM_PALETTE["success"])
                    explorer_rows.append((2, (workspace.id, name), label, False))
        workspace = self.values.get(self.current or "")
        context = self.worktree_path(workspace) if workspace else None
        context_text = "Select a worktree"
        if context is not None and workspace is not None:
            repo = next(repo for repo in workspace.repos if repo.name == context.name)
            branch = (
                self.cache.get(workspace.id, (0, (), {}))[2].get(repo.name, {}).get("branch")
                or repo.branch
                or repo.name
            )
            context_text = f"SELECTED WORKTREE\n{Path(repo.source).name} / {branch}"
        elif workspace is not None:
            context_text = f"WORKSPACE\n{workspace.name}"
        context_label = Text(context_text, no_wrap=True, overflow="ellipsis")
        context_label.stylize(
            PREMIUM_PALETTE["muted"],
            0,
            context_text.find("\n") if "\n" in context_text else len(context_text),
        )
        self.query_one("#worktree-context", Static).update(context_label)
        self.query_one("#history-section", DashboardSection).display = context is not None
        self.sync_tree(self.explorer, explorer_rows)
        terminals = self.query_one("#terminals", DataTable)
        pane_rows = []
        for row in terminals.ordered_rows:
            pane, command, cwd, dead, kind = terminals.get_row(row.key)
            active = self.active_view == f"{self.current}/{pane}" and dead == "0"
            metadata = self.session_rows.get(pane, {})
            repo_name, branch = self.session_context(metadata.get("start") or cwd)
            name = session_display_name(
                metadata or {"kind": kind, "command": command, "pane": pane, "cwd": cwd},
            )
            state = "ended" if dead == "1" else "connected" if active else "live"
            pane_rows.append(SessionCard(pane, name, repo_name, branch, state, active))
        self.sessions.show_cards(tuple(pane_rows))
        self.sync_tree(
            self.conversations,
            [
                (0, ("history", key), "· " + self.conversation_title(item), False)
                for key, item in self.history_rows.items()
                if self.history_scope_matches(item)
            ][:4],
        )
        self.query_one("#session-status", Static).update(
            f"{len(pane_rows)} {'session' if len(pane_rows) == 1 else 'sessions'}  ·  Hide ^b {os.environ.get('WM_SPLIT_TOGGLE_KEY', 'z')}"
        )
        self.query_one("#memory-open", Button).disabled = self.current is None or self.dialog_busy

    @staticmethod
    def session_worktree(workspace: Workspace, cwd: str) -> Repo | None:
        root = Path(workspace.path)
        return next(
            (repo for repo in workspace.repos if Path(cwd).is_relative_to(root / repo.name)), None
        )

    def session_context(self, cwd: str) -> tuple[str, str]:
        workspace = self.values.get(self.current or "")
        if workspace is not None:
            repo = self.session_worktree(workspace, cwd)
            if repo is not None:
                state = self.cache.get(workspace.id, (0, (), {}))[2].get(repo.name, {})
                return repo.name, state.get("branch") or repo.branch or ""
            return workspace.name, ""
        return Path(cwd).name, ""

    def sync_tree(
        self,
        tree: ExplorerTree,
        rows: Sequence[tuple[int, tuple[str, str | None], str | Text, bool]],
    ) -> None:
        key = str(tree.id)
        if self.compact_snapshots.get(key) == rows:
            return
        self.compact_snapshots[key] = rows
        states = {node.data: node.is_expanded for node in tree.nodes()}
        if tree is self.explorer:
            self.explorer_expansion.update(
                {data: value for data, value in states.items() if data is not None}
            )
            states.update(self.explorer_expansion.items())
        cursor = tree.cursor_node.data if tree.cursor_node is not None else None
        tree.clear()
        tree.root.expand()
        parents = [tree.root]
        for depth, data, label, expand in rows:
            node = parents[depth].add(
                label
                if isinstance(label, Text)
                else Text(label, no_wrap=True, overflow="ellipsis"),
                data=data,
                expand=states.get(data, expand),
                allow_expand=tree is self.explorer and depth < 2,
            )
            parents[depth + 1 :] = [node]
            if cursor == data:
                tree.call_after_refresh(tree.move_cursor, node)

    async def activate_explorer(self, data: tuple[str, str | None]) -> None:
        workspace, repo = data
        if repo is not None and Path(repo).is_absolute():
            repo = None
        table = self.query_one("#workspaces", DataTable)
        if not any(row.key.value == workspace for row in table.ordered_rows):
            return
        table.move_cursor(row=table.get_row_index(workspace), scroll=False)
        self.selected_worktree = None
        if self.current != workspace or self.details_workspace != workspace or repo is None:
            await self.choose_row("workspaces", workspace)
        if repo is not None:
            repos = self.query_one("#repos", DataTable)
            if any(row.key.value == repo for row in repos.ordered_rows):
                repos.move_cursor(row=repos.get_row_index(repo), scroll=False)
                self.selected_worktree = (workspace, repo)
                await self.choose_row("repos", repo)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[tuple[str, str | None]]) -> None:
        if event.control is not self.conversations or event.node.data is None:
            return
        try:
            self.select_compact_row("history", event.node.data[1])
        except Error:
            return

    async def on_tree_node_selected(self, event: Tree.NodeSelected[tuple[str, str | None]]) -> None:
        data = event.node.data
        if data is None:
            return
        try:
            if event.control is self.explorer:
                await self.activate_explorer(data)
            elif event.control is self.conversations:
                self.select_compact_row("history", data[1])
                self.dispatch("history-resume")
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list is self.sessions:
            try:
                self.select_compact_row("terminal", event.option_id)
            except Error:
                return

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list is self.sessions:
            try:
                self.select_compact_row("terminal", event.option_id)
                self.dispatch("terminal-attach")
            except Error as exc:
                self.message(str(exc))

    def select_compact_row(self, section: str, key: str | None) -> None:
        table_id = "terminals" if section == "terminal" else "conversations"
        table = self.query_one("#" + table_id, DataTable)
        if key is None or not any(row.key.value == key for row in table.ordered_rows):
            raise Error("Selection is no longer available")
        table.move_cursor(row=table.get_row_index(key), scroll=False)

    async def action_context_menu(self) -> None:
        focused = self.focused
        if isinstance(focused, SessionCards):
            option = focused.highlighted_option
            if option is not None:
                try:
                    self.select_compact_row("terminal", option.id)
                    self.open_menu("terminal")
                except Error as exc:
                    self.message(str(exc))
        elif isinstance(focused, ExplorerTree) and focused.cursor_node is not None:
            data = focused.cursor_node.data
            if data is None:
                return
            try:
                if focused is self.explorer:
                    await self.activate_explorer(data)
                    self.open_menu("workspace")
                else:
                    self.select_compact_row("history", data[1])
                    self.open_menu("history")
            except (Error, OSError, ValueError) as exc:
                self.message(str(exc))

    async def repo_states(self, workspace: Workspace) -> dict[str, dict[str, str]]:
        signature = (workspace.path, *sorted(repo.name for repo in workspace.repos))
        cached = self.cache.get(workspace.id)
        if cached and cached[1] == signature and time.monotonic() - cached[0] < 10:
            return cached[2]

        def collect() -> dict[str, dict[str, str]]:
            return {r.name: Git.status(Path(workspace.path) / r.name) for r in workspace.repos}

        states = await asyncio.to_thread(collect)
        self.cache[workspace.id] = (time.monotonic(), signature, states)
        return states

    def sync_table(self, table: DataTable, rows: Sequence[tuple[str, tuple[str, ...]]]) -> None:
        """Publish a complete snapshot without resetting unchanged rows or selection."""
        old_keys = [row.key.value for row in table.ordered_rows]
        new_keys = [key for key, _ in rows]
        selected = old_keys[table.cursor_row] if old_keys else None
        cursor = table.cursor_row
        scroll = table.scroll_offset
        with self.batch_update():
            if old_keys == new_keys:
                columns = list(table.columns)
                for key, cells in rows:
                    for column, old, new in zip(columns, table.get_row(key), cells):
                        if old != new:
                            table.update_cell(key, column, new, update_width=True)
                self.update_dashboard()
                return
            # Membership/order changed: rebuild synchronously, with no await that
            # could expose an empty intermediate state to the terminal renderer.
            table.clear()
            for key, cells in rows:
                table.add_row(*cells, key=key)
            if rows:
                row = (
                    new_keys.index(selected) if selected in new_keys else min(cursor, len(rows) - 1)
                )
                table.move_cursor(row=row, scroll=False)
                table.scroll_to(x=scroll.x, y=scroll.y, animate=False, force=True)
        self.update_dashboard()

    async def details(self) -> None:
        workspace = self.selected()
        if self.details_workspace != workspace.id:
            # Keep old snapshots only within one scope. Never expose another
            # workspace's rows as targets for repo/pane actions during loading.
            with self.batch_update():
                self.sync_table(self.query_one("#repos", DataTable), [])
                self.sync_table(self.query_one("#terminals", DataTable), [])
            self.details_workspace = workspace.id
            self.session_rows.clear()
        root = Path(workspace.path)
        if self.history_workspace is not None and (
            self.history_workspace != workspace.id
            or self.history_cwd not in {root, *(root / repo.name for repo in workspace.repos)}
        ):
            self.select_history(root)
        states = await self.repo_states(workspace)
        terminals = await asyncio.to_thread(Tmux().list, workspace)
        if self.current != workspace.id or self.values.get(workspace.id) != workspace:
            return
        repos = []
        for repo in workspace.repos:
            state = states[repo.name]
            repos.append(
                (
                    repo.name,
                    (
                        repo.name,
                        state["branch"],
                        state["status"] + f" ({repo.phase})",
                        state["changes"],
                    ),
                )
            )
        with self.batch_update():
            self.sync_table(self.query_one("#repos", DataTable), repos)
            if self.explorer:
                self.workspace_sessions[workspace.id] = terminals
            self.publish_sessions(workspace, terminals)

    def publish_sessions(self, workspace: Workspace, terminals: list[dict[str, str]]) -> None:
        context = self.worktree_path(workspace) if self.explorer else None
        if context is not None:
            terminals = [
                pane
                for pane in terminals
                if Path(pane.get("start") or pane["cwd"]).is_relative_to(context)
            ]
        self.session_rows = {pane["pane"]: pane for pane in terminals}
        self.sync_table(
            self.query_one("#terminals", DataTable),
            [
                (
                    pane["pane"],
                    tuple(pane[key] for key in ("pane", "command", "cwd", "dead", "kind")),
                )
                for pane in terminals
            ],
        )

    async def choose_row(self, table_id: str, key: str) -> None:
        if table_id == "workspaces":
            if key not in self.values:
                return
            changed = self.current != key
            self.selected_worktree = None
            self.current = key
            cwd = Path(self.selected().path)
            if changed or self.history_workspace != key or self.history_cwd != cwd:
                self.select_history(cwd)
            await self.details()
        elif table_id == "repos":
            workspace = self.selected()
            if self.details_workspace == workspace.id and key in {r.name for r in workspace.repos}:
                cwd = Path(workspace.path) / key
                if self.history_cwd != cwd:
                    self.select_history(cwd)
                if self.explorer:
                    self.publish_sessions(workspace, self.workspace_sessions.get(workspace.id, []))
        self.update_dashboard()

    async def on_section_table_chosen(self, event: SectionTable.Chosen) -> None:
        event.stop()
        try:
            await self.choose_row(str(event.table.id), event.key)
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        try:
            table_id = str(event.data_table.id)
            key = str(event.row_key.value)
            if self.selected_key(table_id) != key:
                return
            await self.choose_row(table_id, key)
            if event.data_table.id == "terminals":
                self.dispatch("terminal-attach")
            elif event.data_table.id == "conversations":
                self.dispatch("history-resume")
            elif event.data_table.id == "repos":
                self.dispatch("repo-status")
            elif event.data_table.id == "workspaces":
                self.message(f"Opened workspace {self.selected().name}.")
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    def select_history(self, cwd: Path) -> None:
        same_scope = self.history_workspace == self.current and self.history_cwd == cwd
        self.history_workspace = self.selected().id
        self.history_cwd = cwd
        self.history_revision += 1
        self.history_cursor = None
        if not same_scope:
            self.history_rows.clear()
            self.query_one("#conversations", DataTable).clear()
        self.history_loading = True
        scope_label = self.query_one("#history-label", Label)
        scope_label.tooltip = Text(str(cwd)) if not self.explorer else None
        if self.explorer:
            scope_label.display = True
        scope_label.update(Text(f"Codex · {cwd.name}", overflow="ellipsis", no_wrap=True))
        self.update_dashboard()
        self.load_history(self.history_revision)

    @work(group="history")
    async def load_history(self, revision: int, older: bool = False) -> None:
        # Serialize native services. Rapid selection changes skip queued stale work.
        async with self.history_lock:
            if revision != self.history_revision or self.history_cwd is None:
                return
            cwd = self.history_cwd
            cursor = self.history_cursor if older else None
            self.history_loading = True
            self.update_dashboard()
            self.query_one("#history-label", Label).update(
                Text(
                    "Loading…" if self.explorer else f"Codex · {cwd.name} · Loading history…",
                    overflow="ellipsis",
                    no_wrap=True,
                )
            )
            try:
                page = await asyncio.to_thread(CodexHistory().list, cwd, cursor)
                if revision != self.history_revision:
                    return
                table = self.query_one("#conversations", DataTable)
                selected = self.selected_key("conversations")
                if not older:
                    table.clear()
                    self.history_rows.clear()
                from datetime import datetime

                for conversation in page.conversations:
                    if conversation.id in self.history_rows:
                        continue
                    self.history_rows[conversation.id] = conversation
                    try:
                        updated = datetime.fromtimestamp(conversation.updated_at).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                    except (ValueError, OSError, OverflowError):
                        updated = "Unknown"
                    table.add_row(
                        Text(conversation.title),
                        updated,
                        {
                            "notLoaded": "Saved",
                            "idle": "Idle",
                            "active": "Working",
                            "systemError": "Error",
                        }.get(conversation.status, "Saved"),
                        key=conversation.id,
                    )
                if selected in self.history_rows:
                    table.move_cursor(row=table.get_row_index(selected), scroll=False)
                self.history_cursor = page.next_cursor
                if self.explorer:
                    self.query_one("#history-label", Label).display = False
                note = "Enter to resume" if self.history_rows else "No saved conversations"
                self.query_one("#history-label", Label).update(
                    Text(f"Codex · {cwd.name} · {note}", overflow="ellipsis", no_wrap=True)
                )
            except (Error, OSError, ValueError) as exc:
                if revision == self.history_revision:
                    label = self.query_one("#history-label", Label)
                    label.update(Text("History unavailable" if self.explorer else str(exc)))
                    if self.explorer:
                        label.tooltip = Text(str(exc))
                        label.display = True

            finally:
                if revision == self.history_revision:
                    self.history_loading = False
                    self.update_dashboard()

    def resume_history(self, identifier: str | None) -> None:
        if self.history_resuming or self.dialog_busy or self.history_loading:
            return
        workspace_id, cwd = self.history_workspace, self.history_cwd
        if workspace_id is None or cwd is None:
            return
        if identifier is not None and identifier not in self.history_rows:
            return
        self.history_resuming = True
        self.update_dashboard()
        self.launch_history(workspace_id, cwd, identifier)

    @work(group="history-resume")
    async def launch_history(
        self,
        workspace_id: str,
        cwd: Path,
        identifier: str | None,
        tool: str = "codex",
        global_resume: bool = False,
    ) -> None:
        try:
            workspace = await asyncio.to_thread(self.service.get, workspace_id)

            def warn(message: str) -> None:
                self.call_from_thread(self.launch_warning, message)

            launcher = AI(self.service.config, on_warning=warn)
            pane = await asyncio.to_thread(
                launcher.launch,
                workspace,
                tool,
                "resume",
                cwd,
                True,
                session_id=identifier,
            )
            if global_resume and self.presenter is not None:
                self.present_terminal(workspace, pane, expected=launcher.last_identity)
                return
            if self.current != workspace.id or self.dialog_busy or len(self.screen_stack) > 1:
                self.message("Conversation started in its workspace; select it to attach.")
                return
            if launcher.last_identity is None:
                self.attach(pane)
            else:
                self.attach(pane, expected=launcher.last_identity)
            if launcher.last_warnings and not self.explorer:
                self.message("Warning: " + " ".join(launcher.last_warnings))
            if self.history_workspace == workspace_id and self.history_cwd == cwd:
                self.select_history(cwd)
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))
        finally:
            self.history_resuming = False
            self.update_dashboard()

    @ui_operation
    async def action_create(self) -> None:
        result = await self.push_screen_wait(Create(self.service.config.work_root))
        if not result:
            self.message("Workspace creation cancelled.")
            return
        try:
            repo = await self.push_screen_wait(AddRepo(self.service.config.source_root))
            if not repo:
                self.message("Workspace creation cancelled.")
                return
            from .core import no_symlinks, safe_name

            safe_name(result["name"])
            safe_name(repo["name"])
            root = no_symlinks(Path(result["location"]).expanduser() / result["name"])
            command = await asyncio.to_thread(
                Git.command,
                repo["source"],
                root / repo["name"],
                repo["branch"],
                repo["ref"],
                repo["new"],
            )
            if not await self.push_screen_wait(Confirm(f"Create {root}\n" + shlex.join(command))):
                self.message("Workspace creation cancelled.")
                return
            self.message("Creating workspace...")
            workspace = await asyncio.to_thread(
                self.service.create, result["name"], Path(result["location"]), repo
            )
            self.current = workspace.id
            with self.prevent(Input.Changed):
                self.query_one("#search", Input).value = ""
            await self.refresh_after_operation()
            if self.current == workspace.id:
                self.focus_row("workspaces", workspace.id)
                self.select_history(Path(workspace.path))
            self.message("Workspace and first worktree created.")
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))
            self.action_refresh()

    @ui_operation
    async def action_add(self) -> None:
        try:
            workspace = self.selected()
            result = await self.push_screen_wait(AddRepo(self.service.config.source_root))
            if not result:
                self.message("Add repository cancelled.")
                return
            command = await asyncio.to_thread(
                Git.command,
                result["source"],
                Path(workspace.path) / result["name"],
                result["branch"],
                result["ref"],
                result["new"],
            )
            if await self.push_screen_wait(Confirm(shlex.join(command))):
                self.message("Adding repository...")
                await asyncio.to_thread(self.service.add, workspace.id, **result)
                self.message(
                    "Repository added. Existing AI processes may need access approval for its path."
                )
                await self.refresh_after_operation()
                if self.current == workspace.id:
                    if self.explorer is not None:
                        self.selected_worktree = (workspace.id, result["name"])
                        self.update_dashboard()
                    self.focus_row("repos", result["name"])
                    self.select_history(Path(workspace.path) / result["name"])
            else:
                self.message("Add repository cancelled.")
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    def action_terminal(self) -> None:
        self.launch_ai(None)

    def action_new_terminal(self) -> None:
        self.launch_ai(None, True)

    def present_terminal(
        self, workspace: Workspace, pane: str, *, expected: str | None = None
    ) -> None:
        self.presentation_cancel.set()
        self.presentation_cancel = threading.Event()
        self.apply_presentation(workspace, pane, self.presentation_cancel, expected)

    @work(group="present-terminal")
    async def apply_presentation(
        self, workspace: Workspace, pane: str, cancelled: threading.Event, expected: str | None
    ) -> None:
        presenter = self.presenter
        if presenter is None:
            return
        async with self.presentation_lock:
            if cancelled.is_set():
                return
            try:
                options = {"expected": expected} if expected is not None else {}
                await asyncio.to_thread(
                    presenter, workspace, pane, lambda: not cancelled.is_set(), **options
                )
            except (Error, OSError) as exc:
                if not cancelled.is_set():
                    self.message(str(exc))
            if not cancelled.is_set():
                self.refresh_active_view()

    def attach(self, pane: str | None = None, *, expected: str | None = None) -> None:
        try:
            workspace = self.selected()
            if pane is not None and expected is None and self.details_workspace == workspace.id:
                expected = self.session_rows.get(pane, {}).get("identity")
            if self.presenter is not None and pane is not None:
                self.present_terminal(workspace, pane, expected=expected)
                return
            else:
                # Classic mode restores the real terminal for native tmux I/O.
                with self.suspend():
                    Tmux().attach(workspace, pane, expected_identity=expected)
            self.action_refresh()
        except (Error, OSError, SuspendNotSupported) as exc:
            self.message(str(exc))

    @ui_operation
    async def action_rename_session(self) -> None:
        try:
            workspace = self.selected()
            key = self.selected_key("terminals")
            if key is None or self.details_workspace != workspace.id:
                raise Error("Select a terminal first")
            row = self.session_rows[key]
            name = await self.push_screen_wait(RenameSession(row.get("name", "")))
            if name is not None:
                await asyncio.to_thread(
                    Tmux().rename, workspace, key, name, expected=row.get("identity")
                )
                await self.details()
        except (Error, OSError, KeyError, ValueError) as exc:
            self.message(str(exc))

    @ui_operation
    async def action_session_details(self) -> None:
        key = self.selected_key("terminals")
        session = self.session_rows.get(key or "")
        if session is None or self.details_workspace != self.current:
            self.message("Select a terminal first")
            return
        repo, branch = self.session_context(session.get("start") or session["cwd"])
        await self.push_screen_wait(
            Information(
                session.get("name") or (session["kind"] or session["command"]).title(),
                f"{repo} · {branch}\n{session['cwd']}\n"
                f"{session['pane']} · {session['command']} · "
                + ("Ended" if session["dead"] == "1" else "Live"),
            )
        )

    def action_detach_session(self) -> None:
        try:
            workspace = self.selected()
            key = self.selected_key("terminals")
            if (
                self.detach_view is not None
                and key is not None
                and self.details_workspace == workspace.id
            ):
                self.detach_view(
                    workspace, key, expected=self.session_rows.get(key, {}).get("identity")
                )
                self.refresh_active_view()
        except (Error, OSError) as exc:
            self.message(str(exc))

    @ui_operation
    async def action_close_terminal(self) -> None:
        try:
            workspace = self.selected()
            pane = self.selected_key("terminals")
            if pane is None or self.details_workspace != workspace.id:
                raise Error("Select a terminal first")
            backend = Tmux()
            selected = await asyncio.to_thread(
                backend.termination_identity,
                workspace,
                pane,
                self.session_rows.get(pane, {}).get("identity"),
            )
            confirm = Confirm(
                f"Close terminal {pane} in {workspace.name}? "
                "This terminates the process running in that panel.",
                focus_cancel=True,
            )
            if await self.push_screen_wait(confirm):
                await asyncio.to_thread(backend.close, workspace, pane, expected=selected)
                await self.refresh_after_operation()
                self.message(f"Terminal {pane} closed.")
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    @ui_operation
    async def launch_ai(self, tool: str | None, fresh: bool = False) -> None:
        try:
            workspace = self.selected()
            tool = tool or workspace.default_agent or self.service.config.default_agent
            selected = self.selected_worktree
            cwd = (
                str(Path(workspace.path) / selected[1])
                if (
                    selected is not None
                    and selected[0] == workspace.id
                    and any(repo.name == selected[1] for repo in workspace.repos)
                )
                else None
            )
            options = await self.push_screen_wait(Launch(workspace, tool, fresh, cwd=cwd))
            if options:

                def warn(message: str) -> None:
                    self.call_from_thread(self.launch_warning, message)

                launcher = AI(self.service.config, on_warning=warn)
                self.message("Opening terminal...")
                pane = await asyncio.to_thread(
                    launcher.launch,
                    workspace,
                    options["tool"],
                    options["mode"],
                    Path(options["cwd"]),
                    options["fresh"],
                    options["split"],
                )
                if self.current != workspace.id or len(self.screen_stack) > 1:
                    self.message(
                        f"Terminal started in {workspace.name}; select that workspace to attach."
                    )
                    await self.refresh_after_operation()
                    return
                self.message("")
                if launcher.last_identity is None:
                    self.attach(pane)
                else:
                    self.attach(pane, expected=launcher.last_identity)
                if launcher.last_warnings and not self.explorer:
                    self.message("Warning: " + " ".join(launcher.last_warnings))
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    def action_claude(self) -> None:
        self.launch_ai("claude")

    def action_codex(self) -> None:
        self.launch_ai("codex")

    @ui_operation
    async def action_delete(self, scope: str | None = None) -> None:
        try:
            workspace = self.selected()
            focused = self.focused
            repo_table = self.query_one("#repos", DataTable)
            if scope is None and self.explorer is not None:
                node = self.explorer.cursor_node if focused is self.explorer else None
                if node is not None and node.data == (workspace.id, None):
                    scope = "workspace"
                elif node is not None and node.data == self.selected_worktree:
                    scope = "repo"
                else:
                    raise Error("Activate the workspace or worktree before removing it")
            options = {}
            if scope == "repo" or (
                scope is None and focused is repo_table and repo_table.row_count
            ):
                name = self.selected_key("repos")
                if name is None or self.details_workspace != workspace.id:
                    raise Error("Select a repository first")
                message = (
                    f"Remove {name}? Only a clean worktree can be removed. Branch is retained."
                )
                repo, _ = self.service.repo_target(workspace, name)
                options["expected_repo"] = repo
                operation: Callable[..., Any] = self.service.remove
                args: tuple[Any, ...] = (workspace.id, name, True)
            else:
                message = (
                    f"Unregister {workspace.name}? Remove repositories first. Files are retained."
                )
                operation = self.service.delete
                args = (workspace.id, True)
            if await self.push_screen_wait(Confirm(message)):
                self.message("Removing selected item...")
                await asyncio.to_thread(operation, *args, **options)
                await self.refresh_after_operation()
            else:
                self.message("Removal cancelled.")
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    @ui_operation
    async def action_settings(self) -> None:
        try:
            workspace = self.selected()
            options = await self.push_screen_wait(Settings(workspace, self.service))
            if not options:
                self.message("Settings cancelled.")
                return
            config = options["config"]
            preview = (
                f"Global provider: {config.default_agent}; policy: {config.conflict_policy}\n"
                f"Workspace provider: {options['agent']}; policy: {options['policy']}\n"
                "Save provider arguments and settings? Config formatting/comments will be normalized."
            )
            if await self.push_screen_wait(Confirm(preview)):
                await asyncio.to_thread(config.save)
                self.service.config = config
                try:
                    await asyncio.to_thread(
                        self.service.set_agent,
                        workspace.id,
                        None if options["agent"] == "inherit" else options["agent"],
                        None if options["policy"] == "inherit" else options["policy"],
                    )
                except (Error, OSError, ValueError) as exc:
                    self.message(f"Global settings saved. Workspace settings failed: {exc}")
                    return
                await self.refresh_after_operation()
                self.message("Global and workspace agent settings saved.")
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    @ui_operation
    async def action_memory(self) -> None:
        from .memory import Memory

        try:
            workspace = self.selected()
            await asyncio.to_thread(self.service.context, workspace)
            snapshot = await asyncio.to_thread(Memory(workspace).read)
            await self.push_screen_wait(MemoryView(snapshot))
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    @ui_operation
    async def action_help(self) -> None:
        await self.push_screen_wait(
            Information(
                "Workspace Manager help",
                (
                    "Click selects; Enter/Space opens the selected row. Tab/Shift+Tab moves focus.\n"
                    "Arrows move through rows and menus. Escape closes menus and dialogs.\n"
                    "N New workspace; A Add repo; T Open/reuse terminal; V New terminal;\n"
                    "C Claude; X Codex; G/R Refresh Git status; S Settings; M Workspace memory;\n"
                    "/ Search by workspace name/path; ? Help; Q Quit.\n"
                    "Ctrl-b then d detaches tmux; detach and quitting WM preserve running processes.\n"
                    + (
                        f"Header ⋯ opens actions. {self.menu_key.upper()} opens the selected row’s menu.\n"
                        "D removes the activated workspace or worktree after confirmation.\n"
                        "Ctrl+b then f changes focus, z hides the sidebar, Left/Right resizes, h returns home.\n"
                        if self.presenter is not None
                        else "Section ⋯ opens actions. D removes the selected workspace or repository.\n"
                    )
                    + "Conversations are saved Codex history for the displayed directory; they may still be open elsewhere."
                ),
            )
        )
