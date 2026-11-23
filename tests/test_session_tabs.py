from workspace_manager.session_tabs import session_display_name, tab_status, tab_token


def test_duplicate_names_have_independent_identity_and_active_tab_survives_overflow():
    first = {"pane": "%4", "kind": "codex", "start": "/example"}
    second = {**first, "pane": "%9"}
    assert session_display_name(first) == "Codex 5"
    assert session_display_name(second) == "Codex 10"
    first["name"] = second["name"] = "#{pane_id} long duplicate label"
    assert session_display_name(first) == session_display_name(second)

    tabs = {f"owner/%{number}": ("identity", session_display_name(first)) for number in range(50)}
    selected = "owner/%49"
    result = tab_status(tabs, selected, width=73, left=36)
    assert result.startswith(" " * 36)
    assert f"range=user|{tab_token(selected, 'identity')}" in result
    assert f"range=user|{tab_token('owner/%0', 'identity')}" not in result
    assert "##{pane_id}" in result


def test_tabs_keep_order_when_both_fit():
    tabs = {"a": ("identity", "Codex 1"), "b": ("identity", "Codex 2")}
    result = tab_status(tabs, "b", width=80, left=36)
    assert result.index("Codex 1") < result.index("Codex 2")
    assert f"range=user|x{tab_token('b', 'identity')}" in result


def test_unreachable_backend_only_drops_confirmed_exited_process(monkeypatch, tmp_path):
    from workspace_manager.core import Error
    from workspace_manager.split import Display

    def missing_server(*_args):
        raise Error("no server running")

    def check_process(pid, signal):
        assert signal == 0
        if pid == 42:
            raise ProcessLookupError

    monkeypatch.setattr("workspace_manager.split.run", missing_server)
    monkeypatch.setattr("workspace_manager.split.os.kill", check_process)
    alive = ("100/200/43", "Shell 2")
    assert Display(tmp_path).live_tabs(
        {
            "owner/%0": ("100/200/42", "Shell 1"),
            "owner/%1": alive,
        }
    ) == {"owner/%1": alive}


def test_replacement_backend_keeps_tab_if_recorded_process_may_be_alive(monkeypatch, tmp_path):
    from workspace_manager.split import Display

    monkeypatch.setattr("workspace_manager.split.run", lambda *_: "%0 100/901/902 0 900")
    monkeypatch.setattr("workspace_manager.split.os.kill", lambda *_: None)
    old = {"owner/%0": ("100/200/300", "Shell")}
    assert Display(tmp_path).live_tabs(old) == old
