from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from workspace_manager.core import Error, Service, run
from workspace_manager.terminal import Ownership, Tmux
from workspace_manager.tmux_backends import BackendStore, Verification, socket_directory


@pytest.fixture
def legacy_repo(monkeypatch):
    if not shutil.which("tmux"):
        pytest.skip("requires tmux")
    with tempfile.TemporaryDirectory(prefix="wm-reg-", dir="/tmp") as temporary:
        root = Path(temporary).resolve()
        for key, directory in {
            "HOME": "home",
            "TMUX_TMPDIR": "tmux",
            "XDG_CONFIG_HOME": "config",
            "XDG_STATE_HOME": "state",
        }.items():
            path = root / directory
            path.mkdir()
            monkeypatch.setenv(key, str(path))
        monkeypatch.delenv("TMUX", raising=False)
        monkeypatch.delenv("TMUX_PANE", raising=False)
        monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "src"))
        service = Service()
        workspace = service.create("legacy", root / "work")
        source = root / "source"
        run(["git", "init", "-b", "main", str(source)])
        run(
            [
                "git",
                "-C",
                str(source),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "initial",
            ]
        )
        service.add(workspace.id, source, "repo", "topic")
        yield root, service, service.get(workspace.id)


@contextlib.contextmanager
def server(args, cwd, session="raw"):
    run([*args, "-f", "/dev/null", "new-session", "-d", "-s", session, "-c", str(cwd), "sleep 90"])
    try:
        yield
    finally:
        with contextlib.suppress(Error):
            run([*args, "kill-server"])


def cli_args(*args):
    return [
        sys.executable,
        "-c",
        "from workspace_manager.cli import main; main()",
        "terminal",
        *args,
    ]


def test_legacy_arbitrary_socket_is_fail_closed_then_discovered_without_adoption(legacy_repo):
    root, service, workspace = legacy_repo
    worktree = Path(workspace.path) / "repo"
    store = BackendStore(workspace)
    store.path.unlink()  # Recreate the pre-registry schema in this test workspace.
    socket = root / "legacy.sock"
    args = ["tmux", "-S", str(socket)]
    backend = Tmux(socket)
    with server(args, worktree):
        pane = run([*args, "display-message", "-p", "-t", "raw:", "#{pane_id}"])
        pid = run([*args, "display-message", "-p", "-t", pane, "#{pane_pid}"])
        assert Tmux().verify_terminals(workspace).state == Verification.INCOMPLETE
        with pytest.raises(Error, match="inventory is incomplete"):
            service.remove(workspace.id, "repo", True)
        record = json.loads(
            subprocess.check_output(
                cli_args(
                    "backend-register", workspace.id, "--socket", str(socket), "--complete-legacy"
                ),
                input="y\n",
                text=True,
            )
        )
        restarted = Service().get(workspace.id)
        status = json.loads(
            subprocess.check_output(cli_args("backend-status", workspace.id), text=True)
        )
        assert status["complete"] is True
        assert status["backends"][0]["id"] == record["id"]
        assert Tmux().verify_terminals(restarted).state == Verification.ACTIVE
        assert backend.inspect_pane(restarted, pane).category == Ownership.EXTERNAL
        with pytest.raises(Error, match="Active terminals"):
            service.remove(workspace.id, "repo", True)
        assert worktree.is_dir()
        assert run([*args, "display-message", "-p", "-t", pane, "#{pane_pid}"]) == pid
        assert Tmux.register_backend(restarted, socket)["id"] == record["id"]
        assert len(store.read()["backends"]) == 1


def test_named_and_custom_backend_restore_owned_panes_and_no_implicit_replacement(legacy_repo):
    root, service, workspace = legacy_repo
    worktree = Path(workspace.path) / "repo"
    named = ["tmux", "-L", "named"]
    custom = root / "second.sock"
    custom_args = ["tmux", "-S", str(custom)]
    with server(named, root):
        first_record = Tmux.register_backend(workspace, None, "named")
        pane = Tmux.registered(first_record).new(workspace, cwd=worktree, command=["sleep", "90"])
        persistent = Tmux.registered(first_record).pane_identity(pane)
        with server(custom_args, root):
            second_record = Tmux.register_backend(workspace, custom)
            second = Tmux.registered(second_record).new(
                workspace, cwd=worktree, command=["sleep", "90"]
            )
            updated = Service().get(workspace.id)
            with pytest.raises(Error, match="Multiple"):
                Tmux().list(updated)
            first_binding = Tmux().scoped(updated, backend=first_record["id"])
            second_binding = Tmux().scoped(updated, backend=second_record["id"])
            assert first_binding.pane_identity(pane) == persistent
            assert first_binding.inspect_pane(updated, pane).category == Ownership.OWNED
            assert second_binding.inspect_pane(updated, second).category == Ownership.OWNED
            with Tmux().lock(updated):
                BackendStore(updated).select(second_record["id"])
            assert Tmux().scoped(updated).socket == custom
            # The old sidebar/card reference is bound to its original process.
            assert Tmux().scoped(updated, pane, persistent).socket == first_binding.socket
            assert Tmux().termination_identity(updated, pane, persistent).startswith(persistent)
            result = subprocess.check_output(
                cli_args("list", updated.id, "--backend", first_record["id"]), text=True
            )
            assert json.loads(result)[0]["pane"] == pane
        assert Tmux().verify_terminals(workspace).state == Verification.ACTIVE
        Tmux.registered(first_record).close(workspace, pane)
        assert Tmux().verify_terminals(workspace).state == Verification.INCOMPLETE
        with pytest.raises(Error, match="VERIFICATION_INCOMPLETE"):
            service.remove(workspace.id, "repo", True)
        with server(custom_args, root):
            with pytest.raises(Error, match="identity changed"):
                Tmux.register_backend(updated, custom)
            assert Tmux().verify_terminals(updated).state == Verification.INCOMPLETE
            with pytest.raises(Error, match="identity changed"):
                Tmux().scoped(updated, backend=second_record["id"])


def test_processes_register_distinct_backends_without_overwrite(legacy_repo):
    root, _, workspace = legacy_repo
    paths = [root / "a.sock", root / "b.sock"]
    with (
        server(["tmux", "-S", str(paths[0])], root),
        server(["tmux", "-S", str(paths[1])], root),
        subprocess.Popen(
            cli_args("backend-register", workspace.id, "--socket", str(paths[0])),
            stdout=subprocess.PIPE,
        ) as first,
        subprocess.Popen(
            cli_args("backend-register", workspace.id, "--socket", str(paths[1])),
            stdout=subprocess.PIPE,
        ) as second,
    ):
        first_output = first.communicate(timeout=15)[0]
        second_output = second.communicate(timeout=15)[0]
        assert first.returncode == second.returncode == 0
        assert {json.loads(data)["socket"] for data in (first_output, second_output)} == set(
            map(str, paths)
        )
        assert len(BackendStore(workspace).read()["backends"]) == 2
        assert Tmux().verify_terminals(workspace).state == Verification.CLEAR


def test_invalid_and_corrupt_metadata_refuse_before_git_mutation(legacy_repo):
    root, service, workspace = legacy_repo
    with pytest.raises(Error, match="absolute"):
        Tmux.register_backend(workspace, Path("relative.sock"))
    with pytest.raises(Error, match="valid tmux"):
        Tmux.register_backend(workspace, None, "../escape")
    path = root / "not-a-socket"
    path.touch()
    with pytest.raises(Error, match="not a socket"):
        Tmux.register_backend(workspace, path)
    shortcut = root / "shortcut"
    shortcut.symlink_to(socket_directory() / "default")
    with pytest.raises(Error, match="non-symlink"):
        Tmux.register_backend(workspace, shortcut)
    store = BackendStore(workspace)
    store.path.write_text("{truncated")
    assert Tmux().verify_terminals(workspace).state == Verification.ERROR
    with pytest.raises(Error, match="VERIFICATION_ERROR"):
        service.remove(workspace.id, "repo", True)
    assert (Path(workspace.path) / "repo").exists()


def test_failed_atomic_write_preserves_unknown_fields_and_old_records(legacy_repo):
    root, _, workspace = legacy_repo
    socket = root / "failure.sock"
    store = BackendStore(workspace)
    original = {**store.read(), "future_extension": {"kept": True}}
    store.path.write_text(json.dumps(original))
    with (
        server(["tmux", "-S", str(socket)], root),
        patch("workspace_manager.tmux_backends.atomic", side_effect=OSError("disk unavailable")),
        pytest.raises(OSError, match="disk unavailable"),
    ):
        Tmux.register_backend(workspace, socket)
    assert store.read() == original


def test_explicit_creation_after_clean_server_exit_preserves_backend_id(legacy_repo):
    import time

    _, _, workspace = legacy_repo
    tmux = Tmux()
    first = tmux.new(workspace, command=["sleep", "90"])
    store = BackendStore(workspace)
    before = store.read()["backends"][0]
    binding = Tmux.registered(before)
    pid = int(binding.pane_identity(first).rsplit("/", 1)[1])
    tmux.close(workspace, first)
    for _ in range(150):
        if tmux.socket_absent(Path(before["socket"])) and not tmux.process_exists(pid):
            break
        time.sleep(0.03)
    assert tmux.verify_terminals(workspace).state == Verification.INCOMPLETE
    try:
        second = Tmux().new(workspace, command=["sleep", "90"])
        after = store.read()["backends"][0]
        assert after["id"] == before["id"]
        assert after["identity"] != before["identity"]
        assert after["previous_identities"] == [before["identity"]]
        assert Tmux().inspect_pane(workspace, second).category == Ownership.OWNED
    finally:
        with contextlib.suppress(Error):
            run(["tmux", "-S", before["socket"], "kill-server"])


def test_interrupted_pending_record_requires_explicit_live_backend_verification(legacy_repo):
    root, _, workspace = legacy_repo
    path = socket_directory() / "default"
    with (
        patch("workspace_manager.terminal.run", side_effect=Error("interrupted before spawn")),
        pytest.raises(Error, match="interrupted"),
    ):
        Tmux().new(workspace, command=["sleep", "90"])
    store = BackendStore(workspace)
    pending = store.read()["backends"][0]
    assert pending["identity"] is None
    assert Tmux().verify_terminals(workspace).state == Verification.INCOMPLETE
    with pytest.raises(Error):
        Tmux().new(workspace, command=["sleep", "90"])
    path.parent.mkdir(mode=0o700, exist_ok=True)
    with server(["tmux", "-S", str(path)], root):
        rebound = Tmux.register_backend(workspace, path)
        assert rebound["id"] == pending["id"]
        assert rebound["identity"]
        assert Tmux().verify_terminals(workspace).state == Verification.CLEAR
