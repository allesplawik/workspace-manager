"""Small reusable contextual dashboard widgets; backend operations stay in Manager."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import ClassVar

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, OptionList, Static, Tree
from textual.widgets._data_table import RowKey, RowRenderables
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from .design import PREMIUM_PALETTE, cell_style


@dataclass(frozen=True)
class SectionAction:
    id: str
    label: str
    short: str
    description: str
    disabled: bool = False


class ActionButton(Button):
    BINDINGS: ClassVar[list[BindingType]] = [("space", "press", "Activate")]


class SectionHeader(Horizontal):
    class Requested(Message):
        def __init__(self, section: str, action: str) -> None:
            super().__init__()
            self.section, self.action = section, action

    def __init__(self, section: str, title: str, actions: tuple[SectionAction, ...]):
        super().__init__(id=section + "-header")
        self.section, self.title, self.actions = section, title, actions
        self.count = 0
        self.collapsed = False

    def compose(self) -> ComposeResult:
        yield ActionButton(
            "▸" if self.collapsed else "▾",
            id=self.section + "-toggle",
            tooltip="Collapse / expand section",
            classes="icon-action",
        )
        yield Static(self.title, id=self.section + "-title", classes="section-title")
        yield Static("0", id=self.section + "-count", classes="section-count")
        yield Static("", classes="section-spacer")
        for index, action in enumerate(self.actions):
            yield ActionButton(
                action.label,
                id=action.id,
                tooltip=action.description,
                disabled=action.disabled,
                classes="section-action primary-action" if index == 0 else "section-action",
            )
        yield ActionButton(
            "⋯", id=self.section + "-menu", tooltip="More section actions", classes="icon-action"
        )

    def on_resize(self) -> None:
        for action in self.actions:
            button = self.query_one("#" + action.id, Button)
            if self.size.width < 54:
                button.label = (
                    "↵" if action.id in {"history-native", "terminal-attach"} else action.short
                )
                button.styles.width = 3
                button.styles.padding = 0
            else:
                button.label = action.short if self.size.width < 74 else action.label
                button.styles.width = "auto"
                button.styles.padding = (0, 1)

    def update_count(self, count: int) -> None:
        self.count = count
        badge = self.query_one("#" + self.section + "-count", Static)
        value = str(count) + (" …" if self.has_class("-loading") else "")
        if str(badge.render()) != value:
            badge.update(value)

    def set_loading(self, loading: bool) -> None:
        self.set_class(loading, "-loading")
        self.update_count(self.count)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.post_message(self.Requested(self.section, str(event.button.id)))


class SectionTable(DataTable):
    """Single click chooses a row; double click or Enter/Space activates it."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("space", "select_cursor", "Open", show=False)]

    class Chosen(Message):
        def __init__(self, table: SectionTable, key: str) -> None:
            super().__init__()
            self.table, self.key = table, key

    _mouse_selecting = False
    _first_left_click: RowKey | None = None

    def fit_columns(self) -> None:
        if self.size.width < 24 or not self.columns:
            return
        available = self.size.width - int(self.show_vertical_scrollbar)
        widths = {
            "workspaces": [18, 7, 9, max(12, available - 42)],
            "repos": [20, max(16, available - 58), 18, 12],
            "terminals": [4, 10, max(18, available - 37), 6, 7],
            "conversations": [max(20, available - 30), 17, 7],
        }.get(str(self.id))
        if widths is None:
            return
        changed = False
        for column, width in zip(self.ordered_columns, widths):
            if column.width != width or column.auto_width:
                column.width, column.auto_width = width, False
                changed = True
        if changed and self.row_count:
            # Public cell update invalidates the render/dimension cache without
            # changing raw data, row keys, cursor, or conversation/workspace scope.
            row = self.ordered_rows[0].key
            column_key = self.ordered_columns[0].key
            self.update_cell(row, column_key, self.get_cell(row, column_key), update_width=True)

    def on_resize(self) -> None:
        self.fit_columns()

    def _compute_row_renderables(self, row_index: int) -> RowRenderables:
        rendered = super()._compute_row_renderables(row_index)
        if row_index < 0:
            return rendered
        values = self.get_row_at(row_index)
        cells = []
        for column, cell in enumerate(rendered.cells):
            if isinstance(cell, Text):
                cell = cell.copy()
                raw = str(values[column])
                is_path = (self.id == "workspaces" and column == 3) or (
                    self.id == "terminals" and column == 2
                )
                width = self.ordered_columns[column].width
                if is_path and len(raw) > width and "/" in raw:
                    cell = Text("…/" + "/".join(raw.rstrip("/").split("/")[-2:]))
                elif self.id == "terminals" and column == 3:
                    cell = Text("Live" if raw == "0" else "Ended")
                cell.stylize(cell_style(self.id, column, raw))
                cell.no_wrap = True
                cell.overflow = "ellipsis"
            cells.append(cell)
        return RowRenderables(rendered.label, cells)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        row, column = event.style.meta.get("row", -1), event.style.meta.get("column", -1)
        if 0 <= row < self.row_count and 0 <= column < len(self.columns):
            value = str(self.get_row_at(row)[column])
            width = self.ordered_columns[column].width
            self.tooltip = Text(value) if len(value) > min(22, width) else None
        else:
            self.tooltip = None

    def choose(self) -> None:
        if self.row_count:
            key = self.ordered_rows[self.cursor_row].key.value
            if key is not None:
                self.post_message(self.Chosen(self, key))

    async def _on_click(self, event: events.Click) -> None:
        # Textual otherwise also dispatches the inherited handler after this one.
        # We invoke it explicitly while activation suppression is in effect.
        event.prevent_default()
        self._mouse_selecting = True
        try:
            await super()._on_click(event)
            row = event.style.meta.get("row", -1)
            if 0 <= row < self.row_count:
                self.focus()
                self.choose()
        finally:
            self._mouse_selecting = False
        if self.id in {"terminals", "conversations"}:
            key = (
                self.ordered_rows[row].key
                if event.button == 1 and 0 <= row < self.row_count
                else None
            )
            if key is not None and event.chain == 2 and key == self._first_left_click:
                self._post_selected_message()
            self._first_left_click = key if event.chain == 1 else None

    def _post_selected_message(self) -> None:
        if not self._mouse_selecting:
            super()._post_selected_message()

    def action_cursor_up(self) -> None:
        super().action_cursor_up()
        self.choose()

    def action_cursor_down(self) -> None:
        super().action_cursor_down()
        self.choose()

    def action_page_up(self) -> None:
        super().action_page_up()
        self.choose()

    def action_page_down(self) -> None:
        super().action_page_down()
        self.choose()

    def action_scroll_top(self) -> None:
        super().action_scroll_top()
        self.choose()

    def action_scroll_bottom(self) -> None:
        super().action_scroll_bottom()
        self.choose()


class ExplorerTree(Tree[tuple[str, str | None]]):
    """Compact tree shared by the explorer and its flat lists."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "collapse_or_parent", show=False),
        Binding("right", "expand_or_child", show=False),
    ]

    def action_collapse_or_parent(self) -> None:
        node = self.cursor_node
        if node is not None and node.is_expanded:
            node.collapse()
        elif node is not None and node.parent is not self.root:
            self.move_cursor(node.parent)

    def action_expand_or_child(self) -> None:
        node = self.cursor_node
        if node is not None and node.children:
            if node.is_expanded:
                self.move_cursor(node.children[0])
            else:
                node.expand()

    def __init__(self, widget_id: str):
        super().__init__("", id=widget_id, classes="explorer-tree")
        self.show_root = False
        self.guide_depth = 3
        self.root.expand()

    def nodes(self) -> Iterator[TreeNode[tuple[str, str | None]]]:
        pending = list(self.root.children)
        while pending:
            node = pending.pop()
            yield node
            pending.extend(node.children)

    @property
    def visible_rows(self) -> int:
        pending = list(self.root.children)
        count = 0
        while pending:
            node = pending.pop()
            count += 1
            if node.is_expanded:
                pending.extend(node.children)
        return count

    def render_label(
        self, node: TreeNode[tuple[str, str | None]], base_style: Style, style: Style
    ) -> Text:
        label = super().render_label(node, base_style, style)
        depth, parent = 0, node.parent
        while parent is not None and parent is not self.root:
            depth += 1
            parent = parent.parent
        width = max(1, self.scrollable_content_region.width - self.guide_depth * depth - 2)
        marker = label[-2:] if label.plain.endswith(" •") and label.cell_len > width else None
        if marker and width > 3:
            label = label[:-2]
            label.truncate(width - 2, overflow="ellipsis")
            label.append_text(marker)
        else:
            label.truncate(width, overflow="ellipsis")
        return label

    def on_tree_node_expanded(self) -> None:
        self.refresh_sidebar_height()

    def on_tree_node_collapsed(self) -> None:
        self.refresh_sidebar_height()

    def refresh_sidebar_height(self) -> None:
        self.styles.height = min(self.visible_rows or 1, max(3, self.app.size.height // 3))

    def on_mouse_move(self, event: events.MouseMove) -> None:
        line = event.style.meta.get("line")
        node = self.get_node_at_line(line) if isinstance(line, int) else None
        self.tooltip = None
        if node is not None:
            full = Text(str(node.label))
            if self.render_label(node, Style(), Style()).cell_len < full.cell_len:
                full.truncate(52, overflow="ellipsis")
                self.tooltip = full

    def on_leave(self) -> None:
        self.tooltip = None


class WorkspaceExplorer(ExplorerTree):
    """Presentation of workspace groups on the existing Textual tree."""

    def __init__(self) -> None:
        super().__init__("workspace-explorer")
        self.auto_expand = False
        self.output_encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        self.guide_depth = 2
        self.show_guides = False

    def type_icon(self, depth: int) -> str:
        glyph = ("◫", "◇", "⑂")[depth]
        try:
            glyph.encode(self.output_encoding)
        except UnicodeEncodeError:
            return ("W", "R", "Y")[depth]
        return glyph

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        line = y + self.scroll_offset.y
        node = self.get_node_at_line(line)
        if node is None:
            return strip
        if self.has_focus and line == self.cursor_line:
            background = PREMIUM_PALETTE["selected"]
        elif node.parent is self.root:
            background = PREMIUM_PALETTE["surface"]
        else:
            return strip
        # Preserve Textual's click and disclosure metadata on all segments.
        return Strip(
            Segment.apply_style(strip, post_style=Style(bgcolor=background)),
            strip.cell_length,
        )


@dataclass(frozen=True)
class SessionCard:
    pane: str
    agent: str
    repository: str
    branch: str
    state: str
    active: bool
    workspace: str | None = None
    identity: str | None = None


class SessionCards(OptionList):
    """Two lines per option, with native Textual keyboard and pointer handling."""

    class MenuRequested(Message):
        def __init__(self, card: SessionCard, screen_y: int) -> None:
            super().__init__()
            self.card, self.screen_y = card, screen_y

    def __init__(self) -> None:
        super().__init__(id="session-list", compact=True)
        self.cards: tuple[SessionCard, ...] = ()

    def show_cards(self, cards: tuple[SessionCard, ...]) -> None:
        if self.cards != cards:
            selected = self.highlighted_option
            self.cards = cards
            self.set_options(Option(self.card_prompt(card), id=card.pane) for card in cards)
            keys = [card.pane for card in cards]
            if selected is not None and selected.id in keys:
                self.highlighted = keys.index(selected.id)
            elif cards:
                self.highlighted = 0
        self.styles.height = min(len(cards) * 2 or 2, max(2, self.app.size.height // 4 * 2))

    def card_prompt(self, card: SessionCard) -> Text:
        palette = PREMIUM_PALETTE
        active = card.active
        width = max(1, self.scrollable_content_region.width)
        title = Text(" ", style=palette["accent"])
        agent = Text(card.agent, style="bold")
        agent.truncate(max(4, width - 19), overflow="ellipsis")
        title.append_text(agent)
        title.append(f" · {card.repository}", style=palette["text"])
        title.truncate(max(1, width - 3 - (2 if active else 0)), overflow="ellipsis")
        if active:
            title.append(" ●", style=palette["success"])
        if width >= 6:
            title.truncate(width - 2, overflow="ellipsis", pad=True)
            title.append(
                "⋯ ",
                Style(
                    color=palette["accent"],
                    meta={"session_menu": (card.workspace, card.pane, card.identity)},
                ),
            )
        detail = Text("  ", style=palette["muted"])
        if card.branch:
            branch = Text(card.branch, style=palette["muted"])
            branch.truncate(max(1, width - len(card.state) - 5), overflow="ellipsis")
            detail.append_text(branch)
            detail.append(" · ")
        detail.append(card.state, style=palette["muted"])
        for line in (title, detail):
            line.truncate(width, overflow="ellipsis", pad=active)
            if active:
                line.stylize_before(f"on {palette['selected']}")
        return Text("\n", no_wrap=True, overflow="ellipsis").join((title, detail))

    def on_click(self, event: events.Click) -> None:
        target = event.style.meta.get("session_menu")
        if event.button == 1 and isinstance(target, tuple):
            event.prevent_default()
            event.stop()
            index = event.style.meta.get("option")
            if isinstance(index, int) and 0 <= index < len(self.cards):
                card = self.cards[index]
                if target == (card.workspace, card.pane, card.identity):
                    self.highlighted = index
                    self.post_message(self.MenuRequested(card, event.screen_y))

    def on_resize(self) -> None:
        for index, card in enumerate(self.cards):
            self.replace_option_prompt_at_index(index, self.card_prompt(card))


class DashboardSection(Vertical):
    def __init__(
        self,
        section: str,
        title: str,
        table_id: str,
        actions: tuple[SectionAction, ...],
        empty: str,
        tree: ExplorerTree | SessionCards | None = None,
        *,
        collapsed: bool = False,
    ):
        super().__init__(id=section + "-section", classes="dashboard-section")
        self.section, self.title, self.table_id = section, title, table_id
        self.actions, self.empty = actions, empty
        self.collapsed = collapsed
        self.explorer = tree

    def compose(self) -> ComposeResult:
        header = SectionHeader(self.section, self.title, self.actions)
        header.collapsed = self.collapsed
        yield header
        with Vertical(id=self.section + "-content", classes="section-content"):
            if self.section == "history":
                yield Label("Select a workspace or repository", id="history-label")
            yield Static(
                self.empty, id=self.section + "-empty", classes="empty-state", markup=False
            )
            yield SectionTable(id=self.table_id, cursor_type="row")
            if self.explorer is not None:
                yield self.explorer

    def refresh_layout(self, maximum_rows: int) -> None:
        table = self.query_one(SectionTable)
        table.fit_columns()
        self.query_one(SectionHeader).update_count(table.row_count)
        table.display = bool(table.row_count) and self.explorer is None
        if self.explorer is not None:
            self.explorer.display = bool(table.row_count)
            if isinstance(self.explorer, ExplorerTree):
                self.explorer.refresh_sidebar_height()
        # Reserve a line for horizontal scrolling of paths/commands. Otherwise
        # the scrollbar can replace the last data row in compact tables.
        table.styles.height = min(table.row_count + 1, maximum_rows + 1) + 1
        history_status = (
            self.section == "history"
            and self.explorer is not None
            and self.query_one("#history-label", Label).display
        )
        self.query_one("#" + self.section + "-empty", Static).display = (
            not table.row_count and not history_status
        )
        self.query_one("#" + self.section + "-content").display = not self.collapsed

    def toggle(self) -> None:
        self.collapsed = not self.collapsed
        header = self.query_one(SectionHeader)
        header.collapsed = self.collapsed
        button = header.query_one("#" + self.section + "-toggle", Button)
        button.label = "▸" if self.collapsed else "▾"
        button.tooltip = "Expand section" if self.collapsed else "Collapse section"
        self.query_one("#" + self.section + "-content").display = not self.collapsed


class SectionMenu(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Close"),
        Binding("down", "next", "Next", show=False),
        Binding("up", "previous", "Previous", show=False),
    ]

    def __init__(
        self,
        title: str,
        actions: tuple[SectionAction, ...],
        anchor: Widget | None = None,
        *,
        row_y: int | None = None,
    ):
        super().__init__()
        self.title, self.actions, self.anchor_widget = title, actions, anchor
        self.row_y = row_y

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="section-menu"):
            yield Label(self.title or "")
            for action in self.actions:
                yield ActionButton(
                    action.label, id=action.id, disabled=action.disabled, tooltip=action.description
                )
            yield ActionButton("Close", id="menu-close")

    def on_mount(self) -> None:
        self.action_next()
        self.call_after_refresh(self.position_menu)

    def on_resize(self) -> None:
        self.call_after_refresh(self.position_menu)

    def position_menu(self) -> None:
        panel = self.query_one(".section-menu")
        width, height = panel.outer_size
        viewport = self.app.size
        if self.anchor_widget is not None and self.anchor_widget.is_mounted:
            region = self.anchor_widget.region
            x = region.right - width
            below, above = (
                (self.row_y + 1, self.row_y - height)
                if self.row_y is not None
                else (region.bottom, region.y - height)
            )
            y = below if below + height <= viewport.height else above
        else:
            x, y = (viewport.width - width) // 2, (viewport.height - height) // 2
        panel.styles.offset = (
            max(0, min(x, viewport.width - width)),
            max(0, min(y, viewport.height - height)),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None if event.button.id == "menu-close" else event.button.id)

    def on_click(self, event: events.Click) -> None:
        panel = self.query_one(".section-menu")
        if panel.region.contains(event.screen_x, event.screen_y):
            return
        event.stop()
        # A left click on a different section's overflow switches menus rather
        # than opening a second modal. Other outside clicks simply dismiss.
        base = self.app.screen_stack[-2]
        widget, _ = base.get_widget_at(event.screen_x, event.screen_y)
        self.dismiss(None)
        if (
            isinstance(widget, Button)
            and str(widget.id).endswith("-menu")
            and not (widget is self.anchor_widget and widget.id == "sidebar-menu")
        ):
            self.app.call_after_refresh(widget.press)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_next(self) -> None:
        self.focus_next()

    def action_previous(self) -> None:
        self.focus_previous()


class Information(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "close", "Close")]

    def __init__(self, title: str, content: str):
        super().__init__()
        self.title, self.content = title, content

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog"):
            yield Label(self.title or "")
            yield Static(Text(self.content), id="info-content")
            yield ActionButton("Close", id="info-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
