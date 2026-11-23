"""Read saved conversation metadata through the public Codex app-server protocol.

No rollout files or private database schemas are read, and no model turn is started.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from .core import Error
from .providers import CodexProvider


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    cwd: Path | None
    updated_at: int
    status: str


@dataclass(frozen=True)
class HistoryPage:
    conversations: list[Conversation]
    next_cursor: str | None


def conversation_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise Error("Invalid Codex conversation ID") from exc


class CodexHistory:
    timeout = 15.0
    max_bytes = 4 * 1024 * 1024

    def list(self, cwd: Path | None, cursor: str | None = None) -> HistoryPage:
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 8192):
            raise Error("Invalid Codex history cursor")
        cwd = cwd.resolve(strict=True) if cwd is not None else None
        result = self._request(
            cwd or Path.home(),
            {
                **({"cwd": str(cwd)} if cwd is not None else {}),
                "cursor": cursor,
                "limit": 50,
                "sortKey": "updated_at",
                "sortDirection": "desc",
                "modelProviders": [],
                "archived": False,
                "useStateDbOnly": True,
            },
        )
        data = result.get("data")
        next_cursor = result.get("nextCursor")
        if (
            not isinstance(data, list)
            or len(data) > 50
            or (
                next_cursor is not None
                and (not isinstance(next_cursor, str) or len(next_cursor) > 8192)
            )
        ):
            raise Error("Codex returned an invalid history page")
        conversations = []
        for row in data:
            if not isinstance(row, dict):
                raise Error("Codex returned invalid conversation metadata")
            raw_cwd = row.get("cwd")
            location = None
            if isinstance(raw_cwd, str) and Path(raw_cwd).is_absolute():
                try:
                    location = Path(raw_cwd).resolve()
                except (OSError, RuntimeError, ValueError):
                    pass
            # Scope must match locally even if the server ignores the filter.
            if cwd is not None and location != cwd:
                continue
            identifier = row.get("id")
            if not isinstance(identifier, str):
                raise Error("Codex returned an invalid conversation ID")
            title = row.get("name") or row.get("preview") or "Untitled conversation"
            status = row.get("status", {})
            updated = row.get("updatedAt", 0)
            if (
                not isinstance(title, str)
                or not isinstance(updated, (int, float))
                or not math.isfinite(updated)
            ):
                raise Error("Codex returned invalid conversation metadata")
            conversations.append(
                Conversation(
                    conversation_id(identifier),
                    "".join(c for c in " ".join(title.split()) if c.isprintable())[:160],
                    cwd or location,
                    int(updated),
                    str(status.get("type", "unknown")) if isinstance(status, dict) else "unknown",
                )
            )
        if cursor is not None and next_cursor == cursor:
            raise Error("Codex returned a repeated history cursor")
        return HistoryPage(conversations, next_cursor)

    def _request(self, cwd: Path, params: dict[str, Any]) -> dict[str, Any]:
        executable = CodexProvider().executable()
        try:
            process = subprocess.Popen(
                [executable, "app-server"],
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                bufsize=0,
            )
        except OSError as exc:
            raise Error("Cannot start Codex history service; use the native resume picker") from exc
        assert process.stdin is not None and process.stdout is not None
        stdin, stdout = process.stdin, process.stdout
        os.set_blocking(stdin.fileno(), False)
        deadline = time.monotonic() + self.timeout
        pending = bytearray()
        received = 0
        selector = selectors.DefaultSelector()
        try:
            selector.register(stdout, selectors.EVENT_READ)

            def send(message: dict[str, Any]) -> None:
                data = memoryview(json.dumps(message).encode() + b"\n")
                with selectors.DefaultSelector() as writer:
                    writer.register(stdin, selectors.EVENT_WRITE)
                    while data:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not writer.select(max(0, remaining)):
                            raise Error("Codex history timed out while sending a request")
                        try:
                            count = os.write(stdin.fileno(), data)
                        except BlockingIOError:
                            continue
                        data = data[count:]

            def response(identifier: int) -> dict[str, Any]:
                nonlocal received
                while True:
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending[:] = rest
                        if not line.strip():
                            continue
                        message = json.loads(line)
                        if not isinstance(message, dict):
                            raise Error("Invalid Codex history protocol response")
                        if message.get("id") != identifier:
                            continue
                        if "error" in message:
                            raise Error(
                                "Codex history API unavailable; use the native resume picker "
                                "or update Codex"
                            )
                        result = message.get("result")
                        if not isinstance(result, dict):
                            raise Error("Invalid Codex history response")
                        return result
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(max(0, remaining)):
                        raise Error("Codex history timed out; try Refresh or the native picker")
                    chunk = os.read(stdout.fileno(), 65536)
                    if not chunk:
                        raise Error("Codex history service stopped; use the native resume picker")
                    received += len(chunk)
                    if received > self.max_bytes:
                        raise Error("Codex history response exceeded the size limit")
                    pending.extend(chunk)

            send(
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "workspace_manager", "version": "2.0.0"},
                    },
                }
            )
            response(1)
            send({"method": "initialized", "params": {}})
            send({"id": 2, "method": "thread/list", "params": params})
            return response(2)
        except (OSError, ValueError) as exc:
            raise Error("Cannot read Codex history; use the native resume picker") from exc
        finally:
            selector.close()
            with contextlib.suppress(OSError):
                stdin.close()
            # The private short-lived service must not outlive this metadata request.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
            # A leader can exit before descendants that ignore TERM. Escalate for
            # the whole private group even when the leader was already reaped.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            stdout.close()
