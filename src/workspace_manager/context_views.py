"""Compact pickers for global terminal and conversation navigation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Select
from textual.widgets.option_list import Option

from .codex_history import CodexHistory, Conversation
from .core import Error


class GlobalSessions(ModalScreen[str]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Close")]

    def __init__(self, rows: list[tuple[str, str]]):
        super().__init__()
        self.rows = rows

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Label("All sessions")
            yield OptionList(
                *(
                    Option(Text(label, no_wrap=True, overflow="ellipsis"), id=key)
                    for key, label in self.rows
                ),
                compact=True,
                id="global-sessions",
            )
            if not self.rows:
                yield Label("No sessions")
            yield Button("Close", id="close")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


@dataclass(frozen=True)
class HistoryChoice:
    action: str
    item: Conversation | None = None
    cwd: Path | None = None


@dataclass(frozen=True)
class HistoryScope:
    key: str
    label: str
    locations: frozenset[Path]
    target: Path | None = None


class HistoryBrowser(ModalScreen[HistoryChoice | None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "cancel", "Close")]

    def __init__(
        self,
        scopes: list[HistoryScope],
        title_for: Callable[[Conversation], str],
        context: Path | None = None,
        active_location: Path | None = None,
    ):
        super().__init__()
        self.scopes = {scope.key: scope.locations for scope in scopes}
        self.targets = {scope.key: scope.target for scope in scopes}
        self.locations = {scope.target: scope.label for scope in scopes if scope.target is not None}
        self.active_location = active_location
        self.scope_options = [
            ("All locations", ""),
            *((scope.label, scope.key) for scope in scopes),
        ]
        self.title_for = title_for
        self.context = str(context) if str(context) in self.scopes else ""
        self.items: dict[str, Conversation] = {}
        self.cursor: str | None = None
        self.loading = False
        self.load_failed = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Label("Conversation history")
            yield Input(placeholder="Search titles…", id="history-search")
            yield Select(
                [("All agents", "all"), ("Codex", "codex"), ("Claude Code", "claude")],
                value="all",
                allow_blank=False,
                id="history-agent",
            )
            yield Select(
                self.scope_options, value=self.context, allow_blank=False, id="history-scope"
            )
            yield Label("", id="browser-status")
            yield OptionList(compact=True, id="browser-rows")
            with Horizontal(classes="history-buttons"):
                yield Button("Rename", id="browser-rename")
                yield Button("More", id="browser-more")
            yield Button("Claude picker", id="browser-claude")
            yield Button("Close", id="browser-close")

    def on_mount(self) -> None:
        self.load()

    @work(group="history-browser")
    async def load(self) -> None:
        if self.loading:
            return
        self.loading = True
        self.load_failed = False
        self.refresh_rows()
        try:
            page = await asyncio.to_thread(CodexHistory().list, None, self.cursor)
            self.items.update((item.id, item) for item in page.conversations)
            self.cursor = page.next_cursor
        except (Error, OSError, ValueError):
            self.load_failed = True
        finally:
            self.loading = False
        if self.is_mounted and self.app.screen is self:
            self.refresh_rows()

    def refresh_rows(self) -> None:
        listing = self.query_one("#browser-rows", OptionList)
        selected = listing.highlighted_option
        scope = self.scopes.get(str(self.query_one("#history-scope", Select).value))
        agent = self.query_one("#history-agent", Select).value
        term = self.query_one("#history-search", Input).value.casefold()
        results = [
            item
            for item in self.items.values()
            if agent != "claude"
            and (scope is None or item.cwd in scope)
            and (term in self.title_for(item).casefold() or term in item.title.casefold())
        ]
        listing.set_options(Option(self.render_item(item), id=item.id) for item in results)
        if selected and selected.id in [item.id for item in results]:
            listing.highlighted = listing.get_option_index(selected.id)
        elif results:
            listing.highlighted = 0
        self.query_one("#browser-rename", Button).disabled = not results
        self.query_one("#browser-more", Button).disabled = self.loading or (
            self.cursor is None and not self.load_failed
        )
        claude = self.query_one("#browser-claude", Button)
        claude.display = agent in {"all", "claude"}
        claude.disabled = self.claude_location() is None
        status = (
            ("Use the Claude picker" if not claude.disabled else "Select a workspace or worktree")
            if agent == "claude"
            else "Loading…"
            if self.loading
            else "Codex history unavailable"
            if self.load_failed
            else ""
            if results
            else "No matching conversations"
        )
        self.query_one("#browser-status", Label).update(status)

    def render_item(self, item: Conversation) -> Text:
        location = self.locations.get(item.cwd) if item.cwd is not None else None
        if location is None:
            location = "Unassigned" if item.cwd is None else item.cwd.name or "Other location"
        try:
            updated = datetime.fromtimestamp(item.updated_at).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError, OverflowError):
            updated = ""
        # This is the full browser; the sidebar independently renders only short titles.
        return Text(self.title_for(item) + "\n", no_wrap=True, overflow="ellipsis").append(
            f"{updated} · {location}" if updated else location, style="dim"
        )

    def claude_location(self) -> Path | None:
        key = str(self.query_one("#history-scope", Select).value)
        return self.targets.get(key) if key else self.active_location

    def on_input_changed(self) -> None:
        self.refresh_rows()

    def on_select_changed(self) -> None:
        if self.is_mounted:
            self.refresh_rows()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id in self.items:
            self.dismiss(HistoryChoice("resume", self.items[event.option_id]))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "browser-close":
            self.dismiss(None)
        elif event.button.id == "browser-more":
            self.load()
        elif event.button.id == "browser-claude":
            location = self.claude_location()
            if location is not None:
                self.dismiss(HistoryChoice("claude", cwd=location))
        else:
            selected = self.query_one("#browser-rows", OptionList).highlighted_option
            if selected and selected.id in self.items:
                self.dismiss(HistoryChoice("rename", self.items[selected.id]))

    def action_cancel(self) -> None:
        self.dismiss(None)
