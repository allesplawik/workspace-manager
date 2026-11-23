"""Presentation of persistent display tabs; tmux still owns terminal processes."""

from __future__ import annotations

import hashlib

from rich.text import Text


def session_display_name(pane: dict[str, str]) -> str:
    agent = (pane.get("kind") or pane.get("command") or "shell").title()
    if name := pane.get("name"):
        return f"{agent} · {name}"
    return f"{agent} {int(pane['pane'][1:]) + 1}"


def tab_token(key: str, identity: str) -> str:
    return hashlib.sha256(f"{key}/{identity}".encode()).hexdigest()[:12]


def tab_status(tabs: dict[str, tuple[str, str]], active: str | None, width: int, left: int) -> str:
    padding = " " * left
    available = max(0, width - left)
    if available < 11:
        return padding + "#[range=user|new] + #[norange]"
    prefix = "#[range=user|new] + #[norange]#[range=user|all] ⋯ #[norange]"
    if active in tabs and active is not None:
        prefix += f"#[range=user|x{tab_token(active, tabs[active][0])}] × #[norange]"
        available -= 3
    available -= 6
    labels = {
        key: Text("".join(char for char in value if char.isprintable()))
        for key, (_, value) in tabs.items()
    }
    ordered = list(tabs)
    if active in tabs and sum(min(26, label.cell_len) + 2 for label in labels.values()) > available:
        start = ordered.index(active)
        ordered = ordered[start:] + ordered[:start]
    for key in ordered:
        if available < 6:
            break
        identity, _ = tabs[key]
        label = labels[key]
        label.truncate(min(26, available - 2), overflow="ellipsis")
        if not label:
            break
        available -= label.cell_len + 2
        style = "bg=#203149,fg=#e6edf3,bold" if key == active else "bg=#161f2c,fg=#8b949e"
        escaped = label.plain.replace("#", "##")
        prefix += f"#[{style},range=user|{tab_token(key, identity)}] {escaped} #[norange,default]"
    return padding + prefix
