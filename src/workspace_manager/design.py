"""Central visual tokens for the terminal dashboard; no backend dependencies."""

from textual.theme import Theme

PALETTE = {
    "bg": "#0C111B",
    "surface": "#141C2A",
    "panel": "#192338",
    "accent": "#40D8CB",
    "accent-soft": "#1D3B46",
    "text": "#D4DFEF",
    "muted": "#91A1B9",
    "disabled": "#728198",
    "border": "#2B3A50",
    "selected": "#20364B",
    "hover": "#1B2D40",
    "success": "#83D9AC",
    "warning": "#F0C47F",
    "error": "#F2969C",
    "branch": "#94B9F5",
}

WORKSPACE_THEME = Theme(
    name="workspace-ide",
    primary=PALETTE["accent"],
    secondary=PALETTE["branch"],
    accent=PALETTE["accent"],
    foreground=PALETTE["text"],
    background=PALETTE["bg"],
    surface=PALETTE["surface"],
    panel=PALETTE["panel"],
    success=PALETTE["success"],
    warning=PALETTE["warning"],
    error=PALETTE["error"],
    dark=True,
    variables={"wm-" + key: value for key, value in PALETTE.items()},
)


def rows_for_height(height: int) -> int:
    """Keep all four sections useful on small terminals; lists scroll internally."""
    if height <= 25:
        return 1
    if height <= 32:
        return 2
    return max(3, min(8, (height - 16) // 4))


def cell_style(table: str | None, column: int, value: str) -> str:
    if column == 0:
        return "bold " + PALETTE["text"]
    if table == "terminals" and column == 3:
        return PALETTE["success"] if value == "0" else PALETTE["error"]
    normalized = value.lower()
    if normalized in {"ready", "clean", "saved", "idle", "clean (ready)"}:
        return PALETTE["success"]
    if any(word in normalized for word in ("failed", "error", "missing")):
        return PALETTE["error"]
    if any(
        word in normalized for word in ("modified", "pending", "unknown", "working", "creating")
    ):
        return PALETTE["warning"]
    if (table == "repos" and column == 1) or (table == "terminals" and column == 4):
        return PALETTE["branch"]
    if (table == "workspaces" and column == 3) or (table == "terminals" and column == 2):
        return PALETTE["muted"]
    return PALETTE["muted"] if table == "conversations" and column == 1 else PALETTE["text"]


PREMIUM_PALETTE = {
    **PALETTE,
    "bg": "#0D1117",
    "surface": "#161F2C",
    "panel": "#161F2C",
    "selected": "#203149",
    "border": "#30363D",
    "text": "#E6EDF3",
    "muted": "#8B949E",
    "accent": "#8AB4F8",
    "accent-soft": "#203149",
    "branch": "#8AB4F8",
    "success": "#4ADE80",
    "warning": "#EABF77",
    "hover": "#1B2737",
}
