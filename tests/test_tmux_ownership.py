from __future__ import annotations

import contextlib
import fcntl
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from workspace_manager.core import Config, Error, Service, bounded_flock, run
from workspace_manager.terminal import BACKEND, Ownership, Tmux


@pytest.fixture
def owned_server(tmp_path, monkeypatch):
    if not shutil.which("tmux"):
        pytest.skip("requires tmux")
    # macOS has a short Unix socket path limit.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="wm-own-", dir="/tmp") as path:
        root = Path(path).resolve()
        monkeypatch.setenv("TMUX_TMPDIR", str(root))
        monkeypatch.delenv("TMUX", raising=False)
        monkeypatch.delenv("TMUX_PANE", raising=False)
        service = Service(Config(tmp_path / "work", tmp_path, tmp_path / "state"))
        backend = Tmux()
        workspace = service.create("ownership")
        try:
            yield service, backend, workspace
        finally:
            with contextlib.suppress(Error):
                run([*BACKEND, "kill-server"])


def test_owned_managed_external_and_replaced_panels(owned_server):
    _, backend, workspace = owned_server
    first = backend.new(workspace, command=["sleep", "120"])
    second = backend.new(workspace, command=["sleep", "120"])
    third = backend.new(workspace, command=["sleep", "120"])
    first_birth = backend.termination_identity(workspace, first)
    second_birth = backend.termination_identity(workspace, second)
    assert backend.inspect_pane(workspace, first).category == Ownership.OWNED
    run([*BACKEND, "set-option", "-pu", "-t", second, "@wm_pane_owner"])
    assert backend.inspect_pane(workspace, second).category == Ownership.MANAGED
    backend.rename(workspace, second, "Legacy observation")
    with pytest.raises(Error, match="ownership"):
        backend.close(workspace, second, expected=second_birth)

    external = run(
        [
            *BACKEND,
            "new-window",
            "-dP",
            "-F",
            "#{pane_id}",
            "-t",
            "=" + backend.session(workspace),
            "sleep 120",
        ]
    )
    assert backend.inspect_pane(workspace, external).category == Ownership.EXTERNAL
    with pytest.raises(Error, match="ownership"):
        backend.close(workspace, external)
    run([*BACKEND, "respawn-pane", "-k", "-t", third, "sleep 120"])
    assert backend.inspect_pane(workspace, third).category == Ownership.UNKNOWN
    with pytest.raises(Error, match="ownership"):
        backend.close(workspace, third)

    with pytest.raises(Error, match="changed after confirmation"):
        backend.close(workspace, first, expected=second_birth)
    assert backend.termination_identity(workspace, first) == first_birth
    backend.close(workspace, first, expected=first_birth)
    assert {row["pane"] for row in backend.list(workspace)} == {second, third, external}


def test_namespace_is_not_ownership_and_stale_workspace_cannot_spawn(owned_server):
    service, backend, workspace = owned_server
    run([*BACKEND, "new-session", "-d", "-s", "anchor", "sleep 120"])
    foreign = run(
        [
            *BACKEND,
            "new-session",
            "-dP",
            "-F",
            "#{pane_id}",
            "-s",
            backend.session(workspace),
            "sleep 120",
        ]
    )
    for operation in (lambda: backend.new(workspace), lambda: backend.close(workspace, foreign)):
        with pytest.raises(Error):
            operation()
    assert run([*BACKEND, "display-message", "-p", "-t", foreign, "#{pane_dead}"]) == "0"
    run([*BACKEND, "kill-session", "-t", "=" + backend.session(workspace)])
    service.delete(workspace.id, confirmed=True)
    with pytest.raises(Error, match="registration"):
        backend.new(workspace)


def test_termination_rechecks_link_in_server_queue(owned_server):
    _, backend, workspace = owned_server
    pane = backend.new(workspace, command=["sleep", "120"])
    expected = backend.termination_identity(workspace, pane)
    run([*BACKEND, "new-session", "-d", "-s", "external", "sleep 120"])
    guarded = Tmux.guarded

    def link_then_run(binding, *args):
        run([*BACKEND, "link-window", "-s", pane, "-t", "=external:"])
        return guarded(binding, *args)

    with (
        patch.object(Tmux, "guarded", autospec=True, side_effect=link_then_run),
        pytest.raises(Error, match="no longer private"),
    ):
        backend.close(workspace, pane, expected=expected)
    assert run([*BACKEND, "display-message", "-p", "-t", pane, "#{pane_dead}"]) == "0"


def test_lock_timeout_cleanup_and_crash_release(tmp_path):
    path = tmp_path / "lock"
    code = (
        "import fcntl,sys,time; f=open(sys.argv[1],'a'); "
        "fcntl.flock(f,fcntl.LOCK_EX); print('ready',flush=True); time.sleep(120)"
    )
    with subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE) as child:
        try:
            assert child.stdout is not None
            assert child.stdout.readline() == b"ready\n"
            with (
                path.open("a") as stream,
                pytest.raises(Error, match="busy"),
                bounded_flock(stream, fcntl.LOCK_EX, "busy", 0.05),
            ):
                pytest.fail("overlapping lock")
        finally:
            child.kill()
            child.wait(timeout=5)
    with path.open("a") as stream:
        with pytest.raises(KeyboardInterrupt), bounded_flock(stream, fcntl.LOCK_EX, "busy", 0):
            raise KeyboardInterrupt
        with bounded_flock(stream, fcntl.LOCK_EX, "busy", 0):
            pass


def test_missing_backend_with_live_known_process_blocks_unregister(owned_server):
    service, backend, workspace = owned_server
    with subprocess.Popen(["sleep", "120"]) as marker:
        try:
            backend.record_terminal(workspace, marker.pid)
            assert not backend.exists(workspace)
            with pytest.raises(Error, match="VERIFICATION_INCOMPLETE"):
                service.delete(workspace.id, confirmed=True)
        finally:
            marker.terminate()
            marker.wait(timeout=5)
    service.delete(workspace.id, confirmed=True)


def test_named_legacy_socket_blocks_unregister_from_default(owned_server):
    service, backend, workspace = owned_server
    custom = ["tmux", "-L", "legacy"]
    run([*custom, "new-session", "-d", "-s", backend.session(workspace), "sleep 120"])
    try:
        run(
            [
                *custom,
                "set-option",
                "-t",
                "=" + backend.session(workspace) + ":",
                "@wm_id",
                workspace.id,
            ]
        )
        assert not backend.exists(workspace)
        with pytest.raises(Error, match="VERIFIED_ACTIVE_SESSIONS"):
            service.delete(workspace.id, confirmed=True)
    finally:
        run([*custom, "kill-session", "-t", "=" + backend.session(workspace)])
