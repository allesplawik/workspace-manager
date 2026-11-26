"""Workspace Manager titles keyed by provider and original thread ID."""

import json
from pathlib import Path

from .core import Error, Service, atomic, no_symlinks


class ConversationTitles:
    def __init__(self, service: Service):
        self.service = service
        self.path: Path = service.state / "conversation-titles.json"

    def read(self) -> dict[str, str]:
        path = no_symlinks(self.path)
        if not path.exists():
            return {}
        try:
            document = json.loads(path.read_text())
        except ValueError as exc:
            raise Error("Invalid conversation title metadata") from exc
        if not isinstance(document, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in document.items()
        ):
            raise Error("Invalid conversation title metadata")
        return document

    def set(self, agent: str, identifier: str, title: str) -> None:
        title = title.strip()
        if len(title) > 120 or (title and not title.isprintable()):
            raise Error("Use at most 120 printable characters")
        with self.service.lock():
            values = self.read()
            key = f"{agent}:{identifier}"
            if title:
                values[key] = title
            else:
                values.pop(key, None)
            atomic(self.path, values)
