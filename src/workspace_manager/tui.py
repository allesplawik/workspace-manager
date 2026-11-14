"""Textual manager; blocking filesystem/Git/tmux work runs in worker threads."""

from __future__ import annotations

import asyncio
import json
import shlex
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

from textual import work
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import BindingType
from textual.containers import Vertical, VerticalScroll
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
            self.dismiss(
                {
                    "source": Path(self.query_one("#source", Input).value).expanduser(),
                    "name": self.query_one("#name", Input).value,
                    "branch": branch,
                    "ref": self.query_one("#ref", Input).value,
                    "new": mode != "existing",
                }
            )

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
            yield Select(
                [
                    ("New", "new"),
                    ("Native resume picker", "resume"),
                    ("Continue latest", "continue"),
                ],
                value="new",
                id="mode",
            )
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
        ("d", "delete", "Safe delete"),
        ("question_mark", "help", "Help"),
        ("slash", "search", "Search"),
    ]

    def __init__(self, service: Service):
        super().__init__()
        self.service = service
        self.values: dict[str, Workspace] = {}
        self.current: str | None = None
        self.cache: dict[str, tuple[float, dict[str, dict[str, str]]]] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="body"):
            yield Input(placeholder="Search workspace by name or path", id="search")
            yield DataTable(id="workspaces", cursor_type="row")
            yield Label("Repositories — select a row; D removes a clean worktree")
            yield DataTable(id="repos", cursor_type="row")
            yield Label("Persistent tmux terminals — Enter to attach; detach: Ctrl-b d")
            yield DataTable(id="terminals", cursor_type="row")
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
            table.clear()
            self.values = {w.id: w for w in values}
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
                table.add_row(
                    workspace.name, workspace.phase, summary, workspace.path, key=workspace.id
                )
            if self.current in self.values:
                await self.details()
        except (Error, OSError, ValueError) as exc:
            self.message(str(exc))

    async def repo_states(self, workspace: Workspace) -> dict[str, dict[str, str]]:
        cached = self.cache.get(workspace.id)
        if cached and time.monotonic() - cached[0] < 10:
            return cached[1]

        def collect() -> dict[str, dict[str, str]]:
            return {r.name: Git.status(Path(workspace.path) / r.name) for r in workspace.repos}

        states = await asyncio.to_thread(collect)
        self.cache[workspace.id] = (time.monotonic(), states)
        return states

    async def details(self) -> None:
        workspace = self.selected()
        repo_table = self.query_one("#repos", DataTable)
        repo_table.clear()
        states = await self.repo_states(workspace)
        for repo in workspace.repos:
            state = states[repo.name]
            repo_table.add_row(
                repo.name,
                state["branch"],
                state["status"] + f" ({repo.phase})",
                state["changes"],
                key=repo.name,
            )
        terminals = await asyncio.to_thread(Tmux().list, workspace)
        table = self.query_one("#terminals", DataTable)
        table.clear()
        for pane in terminals:
            table.add_row(
                *(pane[k] for k in ("pane", "command", "cwd", "dead", "kind")), key=pane["pane"]
            )

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "workspaces":
            self.current = str(event.row_key.value)
            try:
                await self.details()
            except (Error, OSError) as exc:
                self.message(str(exc))
        elif event.data_table.id == "terminals":
            self.attach(str(event.row_key.value))

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

    def action_help(self) -> None:
        self.push_screen(
            Confirm(
                "N create; A add repo; T open terminal; V new terminal; C Claude; X Codex; G status; "
                "D safe removal; S settings; Q quit. Enter selects workspace or pane.\n"
                "tmux detach: Ctrl-b then d. Terminals survive quitting wm.\n"
                "AI live processes differ from provider conversation history. "
                "Resume uses the provider's interactive picker."
            )
        )
