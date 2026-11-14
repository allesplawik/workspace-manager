# Workspace Manager 2.0

Independent workspace manager: Python 3.12+, Textual management UI, real persistent tmux terminals, and independent Git worktrees. No Herdr dependency. See IMPLEMENTATION_STATUS.md for actual verification and remaining release blockers.

## Install on macOS (Intel / Apple Silicon)

Install Python 3.12+, Git, tmux and uv using your package manager, for example:

```sh
brew install python@3.12 git tmux uv
cd /path/to/workspace-manager
uv tool install --python 3.12 .
wm --help
wm doctor
wm
```

## Install on Ubuntu

```sh
sudo apt update
sudo apt install git tmux python3.12 python3.12-venv pipx
pipx install uv
pipx ensurepath
# Open a fresh terminal if ~/.local/bin was not on PATH.
cd /path/to/workspace-manager
uv tool install --python 3.12 .
wm --help
wm
```

Your distribution must provide Python 3.12+; otherwise install a supported Python first. Claude and Codex are optional independent CLI dependencies. Install/authenticate them according to their providers. Workspace Manager does not inspect private conversation files or alter AI permissions.

Update after obtaining new source: `uv tool install --reinstall --python 3.12 .`.

## Use

`wm` starts the TUI from any directory. Enter selects a workspace. N opens the workspace wizard including its first repository; A adds another repository through the tree browser. Enter any accessible absolute directory to browse outside the default source root. Choose an existing branch, a new branch with a start ref/SHA, or detached HEAD; review the Git command before confirming. Each repository has its own branch.

T opens a real tmux session. C/X launch Claude/Codex with new, resume picker or continue mode and a workspace/repository cwd. Enter on a terminal row attaches to that pane. Detach with **Ctrl-b, then d** to return to the manager. Q exits only the manager. Processes remain in tmux; detach does not terminate them. Close processes/windows explicitly inside tmux before removing worktrees. A live AI process is distinct from provider conversation history. G refreshes actual Git status; S edits agent defaults and provider arguments; ? opens help. Search filters workspaces; most recently changed workspaces sort first.

Automation examples:

```sh
wm workspace create task --yes
wm repo add task --source ~/workspace/api --name api --branch task-api --ref HEAD --yes
wm repo add task --source ~/workspace/web --name web --branch task-web --yes
wm workspace list
wm workspace status task
wm terminal new task
wm terminal new task --cwd ~/work/task/api --split
wm terminal list task
wm workspace open task
wm ai launch task codex --mode resume
wm ai launch task claude --mode continue --cwd ~/work/task/api
wm workspace select task --print-path
wm repo remove task api  # explicit confirmation, clean including ignored files required
wm workspace delete task # unregister empty workspace, retain files
```

`wm workspace create` with no name and `wm repo add task` run interactive CLI wizards. Automation must specify a branch or `--detached` when adding a repo. Existing branches use `--existing`; occupied branches are refused without force. `wm workspace create NAME --source PATH --branch BRANCH --yes` creates and populates in one invocation.

Source `shell/wm.sh`, then use `wmcd task` to change the parent shell directory. Interactive selection is `wm workspace select`; pass a name/ID with `--print-path` for scripting.

## Configuration and safety

Copy `config.example.toml` to `${XDG_CONFIG_HOME:-$HOME/.config}/workspace-manager/config.toml`. Paths expand `~`. Defaults are `~/work`, `~/workspace`, and `${XDG_STATE_HOME:-$HOME/.local/state}/workspace-manager`. Registry/metadata use schema version 1, atomic replace and advisory filesystem locks. Workspace UUIDs define the tmux namespace; existing foreign sessions are never adopted. Git commands use argument arrays, and tmux commands quote each argument. Symlink paths are deliberately refused for managed/source paths.

Workspace metadata is `.wm/workspace.json`; the global registry is an index. Actual branches and dirty/untracked state come from Git. Unknown/error never means clean. No source checkout, reset, clean, branch deletion, or forced worktree operation is performed. Ignored files also block deletion. Remove worktrees individually; workspace deletion unregisters it and preserves instructions/metadata. It never recursively deletes the workspace directory.

On interrupted add, pending/failed metadata remains visible. Inspect `git worktree list` and `git status` manually; do not retry into an existing directory. `wm workspace recover /absolute/workspace/path` reindexes known metadata after a registry failure without modifying Git or promoting an interrupted operation to ready. Existing worktrees cannot be automatically imported/migrated; audit them before any manual move. Unknown Herdr scripts are not migrated.

Generated CLAUDE.md/AGENTS.md are short and never overwritten. Repository instruction files are not guaranteed to load from a parent cwd: read them explicitly after checking access permissions. Adding a repository leaves AI processes running; inform the agent of the new path and approve access separately when requested.

`wm doctor` exports only tool availability booleans and schema version, with no environment values, paths or conversation content. Command errors are printed locally; no telemetry.

## Development and verification

```sh
uv sync --extra dev
uv run pytest -v
uv run ruff check src tests
uv run mypy src
uv tool install .
wm --help
# In an interactive terminal:
wm
```

Tests create temporary repositories, including repos without origin. Real tmux integration uses a dedicated temporary socket directory and never kills the user's server. CI is configured for macOS and Ubuntu. Without dependencies, core checks can run with `PYTHONPATH=src python3 -m unittest discover -s tests -v`; skipped interface/tmux checks are not evidence of acceptance. This UI manages terminals; it does not embed or emulate a terminal. P2 Graphify, knowledge commands, GitHub PR agent, desktop GUI and terminal embedding are outside MVP.

## Equal agent providers (P0)

Claude Code, OpenAI Codex CLI and Shell implement the same `AgentProvider` interface. Each provider owns its argv and native resume semantics; tmux owns terminals and lifetime. No private history format is inspected. Shell is the initial default, and all three choices appear in the terminal creation dialog. T opens/reuses a matching session; V requests a new session; C/X preselect Claude/Codex. Choose a workspace or repository cwd and window or split pane.

```sh
wm providers
wm config set-default codex
wm config set-default claude --workspace task
wm config set-default inherit --workspace task
wm config set-args claude --arg=--model --arg=your-claude-model
wm config set-args codex --arg=--model --arg=your-codex-model
wm terminal new task --provider shell
wm terminal new task --provider claude --mode resume
wm terminal new task --provider codex --mode continue --split
wm ai launch task codex --fresh --no-attach
wm ai launch task claude --no-attach
wm terminal list task
wm terminal attach task --pane %1
```

`terminal new` always creates another session. `ai launch` reuses a live match by provider and cwd unless `--fresh` is supplied. Omit the provider to use the workspace override or global default. New sessions may use per-call `--arg=...` in addition to provider-specific config. Claude resume uses `--resume`/`--continue`; Codex checks its installed help for `resume` and `--last`. Unsupported modes return a readable error. Missing optional CLIs do not disable the others.

Multiple AI sessions may modify the same files, including files outside their initial cwd. The launcher warns about other live agents in the workspace, and the TUI also warns in the launch dialog. Coordinate work or create separate worktrees. Warnings do not prevent work. Opt in to blocking additional agent sessions with `wm config conflict-policy block` or add `--workspace task`; `warn` restores nonblocking behavior, and workspace policy `inherit` uses the global setting. Reattachment remains available even when additional sessions are blocked.

Global TOML uses `default_agent`, `conflict_policy`, and `[agents.claude]`, `[agents.codex]`, `[agents.shell]` tables with `args = ["..."]`. Config commands preserve unrelated parsed values but normalize formatting/comments; back up hand-formatted config before using them. Workspace defaults are optional fields in schema 1, preserving compatibility with earlier metadata. Configuration is changed only by explicit CLI commands or confirmed TUI Settings actions.

For interrupted repository creation, `wm repo recover task repo` reconciles the journal: if the directory and registration are absent it forgets only the failed intent; if both exist and ownership is verified it marks the repo ready. It never removes files or branches. Ignored files (including whitespace names), assume-unchanged and skip-worktree flags block removal until manually audited.
