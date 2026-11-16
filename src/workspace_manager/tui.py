"""Textual manager; blocking filesystem/Git/tmux work runs in worker threads."""

from __future__ import annotations

import asyncio
import json
import shlex
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import BindingType
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
    Select,
    Static,
)

from .codex_history import CodexHistory, Conversation
from .core import Error, Git, Service, Workspace, run
from .providers import PROVIDERS, provider
from .terminal import AI, Tmux


class Confirm(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Cancel")]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Static(self.message, markup=False)
            yield Button("Confirm", id="confirm", variant="warning")
            yield Button("Cancel", id="cancel")

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

    def __init__(self, workspace: Workspace, tool: str, fresh: bool = False):
        super().__init__()
        self.workspace = workspace
        self.tool = tool
        self.fresh = fresh

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
            yield Select(paths, value=self.workspace.path, id="cwd")
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
            yield Select(choices, value=self.service.config.default_agent, id="global-agent")
            yield Select(
                [("Warn about parallel agents", "warn"), ("Block additional agents", "block")],
                value=self.service.config.conflict_policy,
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
                id="workspace-agent",
            )
            yield Select(
                [("Inherit policy", "inherit"), ("Warn", "warn"), ("Block", "block")],
                value=self.workspace.conflict_policy or "inherit",
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


class Manager(App[None]):
    TITLE = "Workspace Manager 2.0"
    CSS = """
    #search { height: 3; }
    #workspaces { height: 9; }
    #repos { height: 9; }
    #terminals { height: 7; }
    #conversations { height: 8; }
    #history-actions { height: 3; }
    .dialog { width: 85%; height: 90%; border: round $accent; padding: 1 2; background: $surface; }
    ModalScreen { align: center middle; }
    DirectoryTree { height: 12; }
    #message { height: auto; max-height: 6; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
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
        ("question_mark", "help", "Help"),
        ("slash", "search", "Search"),
    ]

    def __init__(self, service: Service):
        super().__init__()
        self.service = service
        self.values: dict[str, Workspace] = {}
        self.history_cwd: Path | None = None
        self.history_workspace: str | None = None
        self.history_rows: dict[str, Conversation] = {}
        self.history_cursor: str | None = None
        self.history_resuming = False
        self.history_revision = 0
        self.history_lock = asyncio.Lock()
        self.current: str | None = None
        self.details_workspace: str | None = None
        self.cache: dict[str, tuple[float, tuple[str, ...], dict[str, dict[str, str]]]] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="body"):
            yield Input(placeholder="Search workspace by name or path", id="search")
            yield DataTable(id="workspaces", cursor_type="row")
            yield Label("Repositories — select a row; D removes a clean worktree")
            yield DataTable(id="repos", cursor_type="row")
            yield Label("Persistent tmux terminals — Enter to attach; detach: Ctrl-b d")
            yield DataTable(id="terminals", cursor_type="row")
            yield Label(
                "Saved Codex conversations — select a workspace or repository", id="history-label"
            )
            yield DataTable(id="conversations", cursor_type="row")
            with Horizontal(id="history-actions"):
                yield Button("Refresh history", id="history-refresh", disabled=True)
                yield Button("Load older", id="history-more", disabled=True)
                yield Button("Native resume picker", id="history-native", disabled=True)
            yield Static("", id="message", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#workspaces", DataTable).add_columns("Name", "Phase", "Status", "Path")
        self.query_one("#repos", DataTable).add_columns(
            "Repository", "Branch / HEAD", "Status", "Changes"
        )
        self.query_one("#terminals", DataTable).add_columns(
            "Pane", "Process", "Cwd", "Dead", "Kind"
        )
        self.query_one("#conversations", DataTable).add_columns("Conversation", "Updated", "State")
        self.query_one("#history-native", Button).display = False
        self.query_one("#workspaces", DataTable).focus()
        self.action_refresh()
        self.set_interval(15, self.action_refresh)

    def message(self, value: str) -> None:
        self.query_one("#message", Static).update(value)

    def selected(self) -> Workspace:
        if self.current not in self.values:
            raise Error("Select a workspace first")
        return self.values[str(self.current)]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.action_refresh(False)

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    @work(exclusive=True, group="refresh")
    async def action_refresh(self, force: bool = True) -> None:
        try:
            values = await asyncio.to_thread(self.service.list)
            query = self.query_one("#search", Input).value.lower()
            table = self.query_one("#workspaces", DataTable)
            rows = []
            if force:
                self.cache.clear()
            for workspace in values:
                if query not in (workspace.name + workspace.path).lower():
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
            self.sync_table(table, rows)
            if self.current in self.values:
                await self.details()
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

    async def details(self) -> None:
        workspace = self.selected()
        if self.details_workspace != workspace.id:
            # Keep old snapshots only within one scope. Never expose another
            # workspace's rows as targets for repo/pane actions during loading.
            with self.batch_update():
                self.sync_table(self.query_one("#repos", DataTable), [])
                self.sync_table(self.query_one("#terminals", DataTable), [])
            self.details_workspace = workspace.id
            if self.history_workspace is not None and self.history_workspace != workspace.id:
                self.select_history(Path(workspace.path))
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
        panes = [
            (pane["pane"], tuple(pane[k] for k in ("pane", "command", "cwd", "dead", "kind")))
            for pane in terminals
        ]
        with self.batch_update():
            self.sync_table(self.query_one("#repos", DataTable), repos)
            self.sync_table(self.query_one("#terminals", DataTable), panes)

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "workspaces":
            self.current = str(event.row_key.value)
            try:
                self.select_history(Path(self.selected().path))
                await self.details()
            except (Error, OSError) as exc:
                self.message(str(exc))
        elif event.data_table.id == "repos":
            try:
                workspace = self.selected()
                name = str(event.row_key.value)
                if name in {repo.name for repo in workspace.repos}:
                    self.select_history(Path(workspace.path) / name)
            except Error as exc:
                self.message(str(exc))
        elif event.data_table.id == "conversations":
            identifier = str(event.row_key.value)
            if identifier in self.history_rows:
                self.resume_history(identifier)
        elif event.data_table.id == "terminals":
            self.attach(str(event.row_key.value))

    def select_history(self, cwd: Path) -> None:
        self.history_workspace = self.selected().id
        self.history_cwd = cwd
        self.history_revision += 1
        self.history_cursor = None
        self.history_rows.clear()
        self.query_one("#conversations", DataTable).clear()
        self.query_one("#conversations", DataTable).scroll_visible(animate=False)
        self.query_one("#history-native", Button).display = False
        self.query_one("#history-native", Button).disabled = True
        self.query_one("#history-label", Label).update(Text(f"Saved Codex conversations — {cwd}"))
        self.load_history(self.history_revision)

    @work(group="history")
    async def load_history(self, revision: int, older: bool = False) -> None:
        # Serialize native services. Rapid selection changes skip queued stale work.
        async with self.history_lock:
            if revision != self.history_revision or self.history_cwd is None:
                return
            cwd = self.history_cwd
            cursor = self.history_cursor if older else None
            self.query_one("#history-refresh", Button).disabled = True
            self.query_one("#history-more", Button).disabled = True
            self.query_one("#history-native", Button).display = False
            self.query_one("#history-native", Button).disabled = True
            self.query_one("#history-label", Label).update(Text(f"Loading Codex history — {cwd}"))
            try:
                page = await asyncio.to_thread(CodexHistory().list, cwd, cursor)
                if revision != self.history_revision:
                    return
                table = self.query_one("#conversations", DataTable)
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
                self.history_cursor = page.next_cursor
                note = "Enter/click to resume" if self.history_rows else "No saved conversations"
                self.query_one("#history-label", Label).update(
                    Text(f"Saved Codex conversations — {cwd} — {note}")
                )
            except (Error, OSError, ValueError) as exc:
                if revision == self.history_revision:
                    self.query_one("#history-label", Label).update(Text(str(exc)))
                    self.query_one("#history-native", Button).display = True
                    self.query_one("#history-native", Button).disabled = False
            finally:
                if revision == self.history_revision:
                    self.query_one("#history-refresh", Button).disabled = False
                    self.query_one("#history-more", Button).disabled = self.history_cursor is None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "history-refresh" and self.history_cwd is not None:
            self.select_history(self.history_cwd)
        elif event.button.id == "history-more" and self.history_cursor is not None:
            self.load_history(self.history_revision, True)
        elif event.button.id == "history-native":
            self.resume_history(None)

    def resume_history(self, identifier: str | None) -> None:
        if self.history_resuming:
            return
        workspace_id, cwd = self.history_workspace, self.history_cwd
        if workspace_id is None or cwd is None:
            return
        if identifier is not None and identifier not in self.history_rows:
            return
        self.history_resuming = True
        self.launch_history(workspace_id, cwd, identifier)

    @work(group="history-resume")
    async def launch_history(self, workspace_id: str, cwd: Path, identifier: str | None) -> None:
        try:
            workspace = await asyncio.to_thread(self.service.get, workspace_id)

            def warn(message: str) -> None:
                self.call_from_thread(self.message, "Warning: " + message)
                self.call_from_thread(self.notify, message, severity="warning", timeout=10)

            launcher = AI(self.service.config, on_warning=warn)
            pane = await asyncio.to_thread(
                launcher.launch,
                workspace,
                "codex",
                "resume",
                cwd,
                True,
                session_id=identifier,
            )
            if self.current != workspace.id:
                self.message("Conversation started in its workspace; select it to attach.")
                return
            self.attach(pane)
            if launcher.last_warnings:
                self.message("Warning: " + " ".join(launcher.last_warnings))
            if self.history_workspace == workspace_id and self.history_cwd == cwd:
                self.select_history(cwd)
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))
        finally:
            self.history_resuming = False

    @work
    async def action_create(self) -> None:
        result = await self.push_screen_wait(Create(self.service.config.work_root))
        if not result:
            return
        try:
            repo = await self.push_screen_wait(AddRepo(self.service.config.source_root))
            if not repo:
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
                return
            workspace = await asyncio.to_thread(
                self.service.create, result["name"], Path(result["location"]), repo
            )
            self.current = workspace.id
            await self.action_refresh().wait()
            self.message("Workspace and first worktree created.")
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))
            self.action_refresh()

    @work
    async def action_add(self) -> None:
        try:
            workspace = self.selected()
            result = await self.push_screen_wait(AddRepo(self.service.config.source_root))
            if not result:
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
                await asyncio.to_thread(self.service.add, workspace.id, **result)
                self.message(
                    "Repository added. Existing AI processes may need access approval for its path."
                )
                self.action_refresh()
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    def action_terminal(self) -> None:
        self.launch_ai(None)

    def action_new_terminal(self) -> None:
        self.launch_ai(None, True)

    def attach(self, pane: str | None = None) -> None:
        try:
            workspace = self.selected()
            # suspend restores the real terminal; tmux performs interactive I/O directly.
            with self.suspend():
                Tmux().attach(workspace, pane)
            self.action_refresh()
        except (Error, OSError, SuspendNotSupported) as exc:
            self.message(str(exc))

    @work
    async def launch_ai(self, tool: str | None, fresh: bool = False) -> None:
        try:
            workspace = self.selected()
            tool = tool or workspace.default_agent or self.service.config.default_agent
            options = await self.push_screen_wait(Launch(workspace, tool, fresh))
            if options:

                def warn(message: str) -> None:
                    self.call_from_thread(self.message, "Warning: " + message)
                    self.call_from_thread(self.notify, message, severity="warning", timeout=10)

                launcher = AI(self.service.config, on_warning=warn)
                pane = await asyncio.to_thread(
                    launcher.launch,
                    workspace,
                    options["tool"],
                    options["mode"],
                    Path(options["cwd"]),
                    options["fresh"],
                    options["split"],
                )
                self.attach(pane)
                if launcher.last_warnings:
                    self.message("Warning: " + " ".join(launcher.last_warnings))
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    def action_claude(self) -> None:
        self.launch_ai("claude")

    def action_codex(self) -> None:
        self.launch_ai("codex")

    @work
    async def action_delete(self) -> None:
        try:
            workspace = self.selected()
            focused = self.focused
            if isinstance(focused, DataTable) and focused.id == "repos" and focused.row_count:
                name = str(focused.get_row_at(focused.cursor_row)[0])
                message = (
                    f"Remove {name}? Only a clean worktree can be removed. Branch is retained."
                )
                operation: Callable[..., Any] = self.service.remove
                args: tuple[Any, ...] = (workspace.id, name, True)
            else:
                message = (
                    f"Unregister {workspace.name}? Remove repositories first. Files are retained."
                )
                operation = self.service.delete
                args = (workspace.id, True)
            if await self.push_screen_wait(Confirm(message)):
                await asyncio.to_thread(operation, *args)
                self.action_refresh()
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    @work
    async def action_settings(self) -> None:
        try:
            workspace = self.selected()
            options = await self.push_screen_wait(Settings(workspace, self.service))
            if not options:
                return
            config = options["config"]
            preview = (
                f"Global provider: {config.default_agent}; policy: {config.conflict_policy}\n"
                f"Workspace provider: {options['agent']}; policy: {options['policy']}\n"
                "Save provider arguments and settings? Config formatting/comments will be normalized."
            )
            if await self.push_screen_wait(Confirm(preview)):
                await asyncio.to_thread(config.save)
                await asyncio.to_thread(
                    self.service.set_agent,
                    workspace.id,
                    None if options["agent"] == "inherit" else options["agent"],
                    None if options["policy"] == "inherit" else options["policy"],
                )
                self.service.config = config
                self.message("Global and workspace agent settings saved.")
                self.action_refresh()
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    @work
    async def action_memory(self) -> None:
        from .memory import Memory

        try:
            workspace = self.selected()
            await asyncio.to_thread(self.service.context, workspace)
            snapshot = await asyncio.to_thread(Memory(workspace).read)
            self.push_screen(MemoryView(snapshot))
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    def action_help(self) -> None:
        self.push_screen(
            Confirm(
                "N create; A add repo; T open terminal; V new terminal; C Claude; X Codex; G status; "
                "D safe removal; S settings; M workspace memory; Q quit. Enter selects workspace or pane.\n"
                "tmux detach: Ctrl-b then d. Terminals survive quitting wm.\n"
                "AI live processes differ from provider conversation history. "
                "Resume uses the provider's interactive picker."
            )
        )
