"""Public CLI adapters. Conversation history stays entirely with its provider."""

from __future__ import annotations

import os
import re
import shutil
from abc import ABC, abstractmethod
from collections.abc import Sequence

from .core import Error, run

PROVIDERS = ("shell", "claude", "codex")
MODES = ("new", "resume", "continue")


class AgentProvider(ABC):
    name: str
    is_agent = True

    def executable(self) -> str:
        result = shutil.which(self.name)
        if not result:
            raise Error(
                f"Optional AI tool {self.name} is not installed or not in PATH; choose another provider or Shell"
            )
        return result

    def available(self) -> bool:
        try:
            self.executable()
        except Error:
            return False
        return True

    def validate(self, mode: str, arguments: Sequence[str]) -> None:
        if mode not in MODES:
            raise Error("Mode must be new, resume or continue")
        if any(not isinstance(arg, str) or "\0" in arg for arg in arguments):
            raise Error("Arguments must be strings without NUL")

    @abstractmethod
    def command(self, mode: str = "new", arguments: Sequence[str] = ()) -> list[str]:
        """Return argv for the provider's native interactive CLI, never a shell string."""


class ClaudeProvider(AgentProvider):
    name = "claude"

    def command(self, mode: str = "new", arguments: Sequence[str] = ()) -> list[str]:
        self.validate(mode, arguments)
        command = [self.executable(), *arguments]
        if mode != "new":
            command.append("--" + mode)
        return command


class CodexProvider(AgentProvider):
    name = "codex"

    def command(self, mode: str = "new", arguments: Sequence[str] = ()) -> list[str]:
        self.validate(mode, arguments)
        executable = self.executable()
        command = [executable, *arguments]
        if mode != "new":
            help_text = run([executable, "--help"])
            if not re.search(r"(?m)^\s+resume\b", help_text):
                raise Error(
                    "Installed Codex does not advertise resume support; use new or update Codex"
                )
            command.append("resume")
            if mode == "continue":
                if "--last" not in run([executable, "resume", "--help"]):
                    raise Error(
                        "Installed Codex does not advertise resume --last; use resume picker"
                    )
                command.append("--last")
        return command


class ShellProvider(AgentProvider):
    name = "shell"
    is_agent = False

    def executable(self) -> str:
        requested = os.environ.get("SHELL") or "/bin/sh"
        result = shutil.which(requested)
        if not result:
            raise Error(f"Shell not installed or executable: {requested}")
        return result

    def command(self, mode: str = "new", arguments: Sequence[str] = ()) -> list[str]:
        self.validate(mode, arguments)
        if mode != "new":
            raise Error("Shell has no conversation history; attach a live pane or start new")
        return [self.executable(), *arguments]


def provider(name: str) -> AgentProvider:
    classes: dict[str, type[AgentProvider]] = {
        "claude": ClaudeProvider,
        "codex": CodexProvider,
        "shell": ShellProvider,
    }
    if name not in classes:
        raise Error("Provider must be claude, codex or shell")
    return classes[name]()
