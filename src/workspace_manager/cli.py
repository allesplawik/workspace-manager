"""Automation interface and interactive prompts using the shared service."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Annotated

import typer

from .core import Config, Error, Git, Service, Workspace
from .providers import PROVIDERS, provider
from .terminal import AI, Tmux, diagnostics

app = typer.Typer(no_args_is_help=False)
workspace_app = typer.Typer()
repo_app = typer.Typer()
terminal_app = typer.Typer()
ai_app = typer.Typer()
config_app = typer.Typer()
memory_app = typer.Typer()
app.add_typer(workspace_app, name="workspace")
app.add_typer(repo_app, name="repo")
app.add_typer(terminal_app, name="terminal")
app.add_typer(ai_app, name="ai")
app.add_typer(config_app, name="config")
app.add_typer(memory_app, name="memory")


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    """Manage independent Git workspaces and persistent tmux terminals."""
    if ctx.invoked_subcommand is None:
        from .tui import Manager

        Manager(Service()).run()


def choose(service: Service) -> Workspace:
    values = service.list()
    if not values:
        raise Error("No workspaces; use wm workspace create")
    for i, item in enumerate(values, 1):
        typer.echo(f"{i}. {item.name} [{item.phase}] {item.path}", err=True)
    number = typer.prompt("Workspace number", type=int, err=True)
    if not 1 <= number <= len(values):
        raise Error("Invalid selection")
    return service.get(values[number - 1].id)


def browse(start: Path) -> Path:
    """Directory tree browser with parent navigation and arbitrary absolute paths."""
    current = start.expanduser().absolute()
    while True:
        typer.echo(f"\nDirectory: {current}")
        try:
            children = sorted(p for p in current.iterdir() if p.is_dir() and not p.is_symlink())
        except OSError as exc:
            typer.echo(str(exc))
            children = []
        for i, child in enumerate(children, 1):
            typer.echo(f"{i}. {child.name}/")
        answer = typer.prompt("Number, .., absolute path, or . to select", default=".")
        if answer == ".":
            return Git.source(current)
        if answer == "..":
            current = current.parent
        elif answer.isdigit() and 1 <= int(answer) <= len(children):
            current = children[int(answer) - 1]
        elif Path(answer).expanduser().is_absolute():
            current = Path(answer).expanduser()
        else:
            typer.echo("Invalid directory")


def repo_wizard(
    service: Service,
    key: str,
    source: Path | None = None,
    name: str | None = None,
    branch: str | None = None,
    ref: str = "HEAD",
    existing: bool = False,
    yes: bool = False,
    detached: bool = False,
) -> None:
    workspace = service.get(key)
    source = Git.source(source) if source else browse(service.config.source_root)
    name = name or typer.prompt("Repository directory", default=source.name)
    if not yes and not detached and branch is None:
        typer.echo(Git_branches(source))
        existing = typer.confirm("Use existing branch?", default=False)
        branch = typer.prompt("Branch name")
        if not existing:
            ref = typer.prompt("Start ref or SHA", default=ref)
    if not detached and branch is None:
        raise Error("Specify --branch or --detached")
    command = Git.command(source, Path(workspace.path) / name, branch, ref, not existing)
    typer.echo(shlex.join(command))
    if yes or typer.confirm("Add this worktree?", default=False):
        service.add(key, source, name, branch, ref, not existing)


def Git_branches(source: Path) -> str:
    from .core import run

    return run(["git", "-C", str(source), "branch", "--list"])


@workspace_app.command("list")
def list_workspaces() -> None:
    for workspace in Service().list():
        typer.echo(f"{workspace.id}\t{workspace.name}\t{workspace.phase}\t{workspace.path}")


@workspace_app.command("create")
def create(
    name: Annotated[str | None, typer.Argument()] = None,
    location: Path | None = None,
    source: Path | None = None,
    branch: str | None = None,
    ref: str = "HEAD",
    yes: bool = False,
) -> None:
    service = Service()
    interactive = name is None
    name = name or typer.prompt("Workspace name")
    if interactive:
        location = Path(typer.prompt("Parent location", default=str(service.config.work_root)))
    first_repo = None
    if source or (interactive and typer.confirm("Add a repository?", default=True)):
        source = Git.source(source) if source else browse(service.config.source_root)
        existing = False
        if branch is None:
            if yes:
                raise Error("Specify --branch when creating with --source --yes")
            typer.echo(Git_branches(source))
            existing = typer.confirm("Use existing branch?", default=False)
            branch = typer.prompt("Branch name")
            if not existing:
                ref = typer.prompt("Start ref or SHA", default=ref)
        first_repo = {
            "source": source,
            "name": source.name,
            "branch": branch,
            "ref": ref,
            "new": not existing,
        }
        command = Git.command(
            source,
            (location or service.config.work_root).expanduser() / name / source.name,
            branch,
            ref,
            not existing,
        )
        typer.echo(shlex.join(command))
    typer.echo(f"Create {name} in {location or service.config.work_root}")
    if not yes and not typer.confirm("Create workspace?", default=False):
        raise typer.Exit()
    workspace = service.create(name, location, first_repo)
    typer.echo(workspace.path)


@workspace_app.command("status")
def status(workspace: str) -> None:
    typer.echo(json.dumps(Service().status(workspace), indent=2))


@workspace_app.command("open")
def open_workspace(workspace: str) -> None:
    Tmux().attach(Service().get(workspace))


@workspace_app.command("delete")
def delete(workspace: str, yes: bool = False) -> None:
    service = Service()
    typer.echo(json.dumps(service.status(workspace), indent=2))
    if yes or typer.confirm("Unregister workspace, retaining all files?", default=False):
        service.delete(workspace, True)


@workspace_app.command("select")
def select(
    workspace: Annotated[str | None, typer.Argument()] = None, print_path: bool = False
) -> None:
    service = Service()
    value = service.get(workspace) if workspace else choose(service)
    typer.echo(value.path if print_path else value.id)


@workspace_app.command("recover")
def recover(path: Path) -> None:
    typer.echo(Service().recover(path).id)


@repo_app.command("add")
def add(
    workspace: str,
    source: Path | None = None,
    name: str | None = None,
    branch: str | None = None,
    ref: str = "HEAD",
    existing: bool = False,
    yes: bool = False,
    detached: bool = False,
) -> None:
    repo_wizard(Service(), workspace, source, name, branch, ref, existing, yes, detached)


@repo_app.command("remove")
def remove(workspace: str, name: str, yes: bool = False) -> None:
    service = Service()
    typer.echo(json.dumps(service.status(workspace), indent=2))
    if yes or typer.confirm(f"Remove clean worktree {name}, preserving branch?", default=False):
        service.remove(workspace, name, True)


@repo_app.command("recover")
def recover_repo(workspace: str, name: str, yes: bool = False) -> None:
    """Reconcile interrupted add; never remove files or branches."""
    if yes or typer.confirm(
        "Reconcile interrupted repository metadata, preserving files?", default=False
    ):
        Service().repair_repo(workspace, name, True)


@terminal_app.command("list")
def terminals(workspace: str) -> None:
    typer.echo(json.dumps(Tmux().list(Service().get(workspace)), indent=2))


@terminal_app.command("new")
def new_terminal(
    workspace: str,
    cwd: Path | None = None,
    split: bool = False,
    provider_name: Annotated[str | None, typer.Option("--provider")] = None,
    mode: str = "new",
    extra_args: Annotated[list[str] | None, typer.Option("--arg")] = None,
) -> None:
    service = Service()
    launcher = AI(
        service.config, on_warning=lambda message: typer.echo("Warning: " + message, err=True)
    )
    pane = launcher.launch(
        service.get(workspace),
        provider_name,
        mode,
        cwd,
        fresh=True,
        split=split,
        extra_args=extra_args,
    )
    typer.echo(pane)


@terminal_app.command("attach")
def attach(workspace: str, pane: str | None = None) -> None:
    Tmux().attach(Service().get(workspace), pane)


@ai_app.command("launch")
def launch(
    workspace: str,
    tool: Annotated[str | None, typer.Argument()] = None,
    mode: str = "new",
    cwd: Path | None = None,
    attach: bool = True,
    fresh: bool = False,
    extra_args: Annotated[list[str] | None, typer.Option("--arg")] = None,
) -> None:
    service = Service()
    value = service.get(workspace)
    launcher = AI(
        service.config, on_warning=lambda message: typer.echo("Warning: " + message, err=True)
    )
    pane = launcher.launch(value, tool, mode, cwd, fresh=fresh, extra_args=extra_args)
    typer.echo(pane)
    if attach:
        Tmux().attach(value, pane)


@app.command("providers")
def providers() -> None:
    """Report each provider independently; optional tools never disable other providers."""
    typer.echo(
        json.dumps(
            {name: {"available": provider(name).available()} for name in PROVIDERS}, indent=2
        )
    )


@config_app.command("set-default")
def set_default(agent: str, workspace: str | None = None) -> None:
    """Set shell/claude/codex globally or per workspace; 'inherit' clears the local override."""
    service = Service()
    if workspace:
        current = service.get(workspace)
        service.set_agent(workspace, None if agent == "inherit" else agent, current.conflict_policy)
    else:
        service.config.default_agent = agent
        service.config.save()


@config_app.command("set-args")
def set_args(
    agent: str, arguments: Annotated[list[str] | None, typer.Option("--arg")] = None
) -> None:
    """Replace provider-specific argv; use --arg=--flag for arguments beginning with dash."""
    config = Config.load()
    provider(agent)
    config.agent_args[agent] = arguments or []
    config.save()


@config_app.command("conflict-policy")
def conflict_policy(policy: str, workspace: str | None = None) -> None:
    service = Service()
    if workspace:
        current = service.get(workspace)
        service.set_agent(workspace, current.default_agent, None if policy == "inherit" else policy)
    else:
        service.config.conflict_policy = policy
        service.config.save()


@memory_app.command("show")
def memory_show(
    workspace: str,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Read the compact shared handoff (JSON includes its revision for safe updates)."""
    from .memory import Memory

    service = Service()
    current = service.get(workspace)
    service.context(current)
    snapshot = Memory(current).read()
    typer.echo(json.dumps(snapshot, ensure_ascii=False) if as_json else snapshot["content"])


@memory_app.command("update")
def memory_update(
    workspace: str,
    file: Annotated[Path, typer.Option("--file")],
    revision: Annotated[str, typer.Option("--revision")],
) -> None:
    """Replace the summary; reject oversized text and changes based on stale revisions."""
    from .memory import MAX_BYTES, Memory

    with file.expanduser().open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise Error("Proposed memory is too large; condense it before saving")
    typer.echo(Memory(Service().get(workspace)).update(data.decode("utf-8"), revision))


@app.command("doctor")
def doctor() -> None:
    """Print a diagnostic report containing no paths, prompts, environment or secrets."""
    typer.echo(json.dumps(diagnostics(), indent=2))


def main() -> None:
    try:
        app()
    except (Error, OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from exc
