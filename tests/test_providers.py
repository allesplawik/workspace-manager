"""Provider and session integration using real executable CLI stubs."""

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fake_cli import make_cli

from workspace_manager.core import Config, Error, Service, Workspace, run
from workspace_manager.providers import ClaudeProvider, CodexProvider, ShellProvider, provider
from workspace_manager.terminal import AI, Tmux


class ProviderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("claude", "codex"):
            make_cli(self.bin, name)
        env = patch.dict(
            os.environ,
            {
                "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                "XDG_CONFIG_HOME": str(self.root / "config"),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.config = Config(self.root / "work", self.root, self.root / "state")
        self.service = Service(self.config)
        self.workspace = self.service.create("agents")

    def test_both_native_mechanisms_with_real_cli_stubs(self):
        expected = {
            "claude": {"new": [], "resume": ["--resume"], "continue": ["--continue"]},
            "codex": {"new": [], "resume": ["resume"], "continue": ["resume", "--last"]},
        }
        for name, modes in expected.items():
            for mode, tail in modes.items():
                with self.subTest(name=name, mode=mode):
                    command = provider(name).command(mode, ["--model", "test model"])
                    result = subprocess.run(
                        command, cwd=self.workspace.path, capture_output=True, text=True, check=True
                    )
                    data = json.loads(
                        result.stdout.removeprefix("\x1b[31m").strip().removesuffix("\x1b[0m")
                    )
                    self.assertEqual(data["argv"], ["--model", "test model", *tail])
                    self.assertEqual(data["cwd"], self.workspace.path)

    def test_availability_is_independent(self):
        (self.bin / "claude").unlink()
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            self.assertFalse(ClaudeProvider().available())
            self.assertTrue(CodexProvider().available())
            self.assertTrue(ShellProvider().available())
            with self.assertRaisesRegex(Error, "claude.*not installed"):
                ClaudeProvider().command()

    def test_provider_arguments_are_literal(self):
        dangerous = "$(touch owned); ' `touch owned`"
        result = subprocess.run(
            ClaudeProvider().command(arguments=[dangerous]),
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("touch owned", result.stdout)
        self.assertFalse((self.root / "owned").exists())

    def test_shell_has_no_fake_resume(self):
        with self.assertRaisesRegex(Error, "no conversation history"):
            ShellProvider().command("resume")

    def test_config_roundtrip_preserves_unrelated_values(self):
        path = Config.path()
        path.parent.mkdir(parents=True)
        path.write_text('unrelated = { values = [1, "two"] }\n')
        self.config.default_agent = "codex"
        self.config.agent_args = {
            "claude": ["--model", "claude-test"],
            "codex": ["--model", "codex-test"],
        }
        self.config.save()
        loaded = Config.load()
        self.assertEqual(loaded.default_agent, "codex")
        self.assertEqual(loaded.agent_args, self.config.agent_args)
        import tomllib

        self.assertEqual(tomllib.loads(path.read_text())["unrelated"], {"values": [1, "two"]})

    def test_invalid_config_arguments_rejected(self):
        self.config.agent_args = {"claude": "--model nope"}
        with self.assertRaises(Error):
            self.config.validate()

    def test_workspace_override_and_backwards_metadata(self):
        self.service.set_agent("agents", "claude", "warn")
        workspace = self.service.get("agents")
        self.assertEqual(workspace.default_agent, "claude")
        data = json.loads((Path(workspace.path) / ".wm/workspace.json").read_text())
        del data["default_agent"]
        del data["conflict_policy"]
        self.assertIsNone(Workspace.decode(data).default_agent)

    def test_parallel_sessions_warn_and_explicit_block(self):
        panes = [{"pane": "%1", "kind": "claude", "cwd": self.workspace.path, "dead": "0"}]
        launcher = AI(self.config)
        with (
            patch.object(Tmux, "list", return_value=panes),
            patch.object(Tmux, "_new", return_value="%2"),
        ):
            self.assertEqual(launcher.launch(self.workspace, "codex"), "%2")
            self.assertTrue(launcher.last_warnings)
            self.config.conflict_policy = "block"
            with self.assertRaisesRegex(Error, "Blocked"):
                launcher.launch(self.workspace, "codex")
            # Reattaching live sessions remains possible even with block configured.
            self.assertEqual(launcher.launch(self.workspace, "claude"), "%1")

    def test_fresh_allows_multiple_same_provider(self):
        panes = [{"pane": "%1", "kind": "claude", "cwd": self.workspace.path, "dead": "0"}]
        launcher = AI(self.config)
        with (
            patch.object(Tmux, "list", return_value=panes),
            patch.object(Tmux, "_new", return_value="%2") as new,
        ):
            self.assertEqual(launcher.launch(self.workspace, "claude"), "%1")
            new.assert_not_called()
            self.assertEqual(launcher.launch(self.workspace, "claude", fresh=True), "%2")
            self.assertTrue(launcher.last_warnings)

    def test_default_resolution_and_separate_argv(self):
        self.config.default_agent = "codex"
        self.config.agent_args = {"claude": ["--model", "A"], "codex": ["--model", "B"]}
        launcher = AI(self.config)
        with (
            patch.object(Tmux, "list", return_value=[]),
            patch.object(Tmux, "_new", return_value="%1") as new,
        ):
            launcher.launch(self.workspace)
            self.assertEqual(new.call_args.args[2][1:], ["--model", "B"])
            self.workspace.default_agent = "claude"
            launcher.launch(self.workspace)
            self.assertEqual(new.call_args.args[2][1:], ["--model", "A"])
            launcher.launch(self.workspace, "shell")
            self.assertEqual(new.call_args.args[3], "shell")

    def test_sibling_cwds_still_warn_before_spawn(self):
        first = Path(self.workspace.path) / "frontend"
        second = Path(self.workspace.path) / "backend"
        first.mkdir()
        second.mkdir()
        events = []
        panes = [{"pane": "%1", "kind": "claude", "cwd": str(first), "dead": "0"}]
        launcher = AI(self.config, on_warning=lambda message: events.append("warning"))
        with (
            patch.object(Tmux, "list", return_value=panes),
            patch.object(Tmux, "_new", side_effect=lambda *args: events.append("spawn") or "%2"),
        ):
            launcher.launch(self.workspace, "codex", cwd=second)
        self.assertEqual(events, ["warning", "spawn"])


@unittest.skipUnless(shutil.which("tmux"), "tmux unavailable")
class ProviderTmuxTests(unittest.TestCase):
    def test_both_providers_real_ptys_reconnect_resize_input_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            binaries = root / "bin"
            binaries.mkdir()
            logs = root / "logs"
            logs.mkdir()
            sockets = root / "sockets"
            sockets.mkdir(mode=0o700)
            for name in ("claude", "codex"):
                make_cli(binaries, name)
            env = {
                "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                "TMUX_TMPDIR": str(sockets),
                "WM_STUB_LOG": str(logs),
                "WM_STUB_HOLD": "1",
            }
            with patch.dict(os.environ, env):
                config = Config(root / "work", root, root / "state")
                workspace = Service(config).create("agents")
                launcher = AI(config)
                tmux = Tmux()
                try:
                    claude = launcher.launch(workspace, "claude", "resume")
                    codex = launcher.launch(workspace, "codex", "continue")
                    for name in ("claude", "codex"):
                        self.wait_for(logs / (name + ".json"))
                    self.assertTrue(json.loads((logs / "claude.json").read_text())["tty"])
                    self.assertEqual(
                        json.loads((logs / "codex.json").read_text())["argv"], ["resume", "--last"]
                    )
                    self.assertEqual(AI(config).launch(workspace, "claude"), claude)
                    self.assertEqual(len(tmux.list(workspace)), 2)
                    run(["tmux", "send-keys", "-t", codex, "hello", "Enter"])
                    run(
                        [
                            "tmux",
                            "resize-window",
                            "-t",
                            codex,
                            "-x",
                            "100",
                            "-y",
                            "40",
                        ]
                    )
                    self.wait_for(logs / "codex.resize")
                    capture = run(["tmux", "capture-pane", "-p", "-e", "-t", codex])
                    self.assertIn("echo:hello", capture)
                    self.assertIn("\x1b[", capture)
                    run(["tmux", "send-keys", "-t", claude, "exit", "Enter"])
                    deadline = time.monotonic() + 5
                    while (
                        any(p["pane"] == claude for p in tmux.list(workspace))
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.05)
                    resumed = AI(config).launch(workspace, "claude", "continue")
                    self.assertNotEqual(resumed, claude)
                finally:
                    with contextlib.suppress(Error):
                        run(["tmux", "kill-session", "-t", "=" + tmux.session(workspace)])

    def wait_for(self, path):
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(path.exists(), str(path))
