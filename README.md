# Workspace Manager 2.0

Independent workspace manager: Python 3.12+, Textual management UI, real persistent tmux terminals, and independent Git worktrees. No Herdr dependency.

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

T opens a real tmux session. C/X launch Claude/Codex with new, resume picker or continue mode and a workspace/repository cwd. Enter on a terminal row attaches to that pane. Detach with **Ctrl-b, then d** to return to the manager. When WM runs outside tmux and attaches to a selected pane, exiting that pane (for example Ctrl-D in a shell) also returns to WM; other panes and processes remain running. WM started inside tmux retains native switch-client behavior. Q exits only the manager. Processes remain in tmux; detach does not terminate them. Close processes/windows explicitly inside tmux before removing worktrees. A live AI process is distinct from provider conversation history. G refreshes actual Git status; S edits agent defaults and provider arguments; ? opens help. Search filters workspaces; most recently changed workspaces sort first.

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

## Saved Codex conversations

Click a workspace row (or press Enter) to show saved Codex conversations whose working directory is the workspace root. Click a repository row to show conversations for that repository's worktree directory. Select a conversation with a click or Enter to resume that exact conversation in tmux; a different live Codex pane is not reused. Existing conflict warnings/policies still apply.

The history panel shows titles, last update and runtime state. Use **Load older** for earlier conversations or **Refresh history** after closing a session. Saved conversations may still be open in another terminal; the list is not proof that a process has ended. Archived conversations are excluded. Directory matching is exact, so workspace-root history and repository history stay separate.

History uses the public local Codex app-server `thread/list` API, with bounded requests and no model turns. WM does not parse Codex rollout files or private databases, and does not copy conversation transcripts into workspace metadata. If history loading fails or the installed Codex does not support the API, a **Native resume picker** fallback button appears for the selected directory. It stays hidden when history loads successfully. The new-terminal dialog offers Codex New/Continue latest; select a saved conversation from the history panel to resume it. Claude retains its native resume picker because this history list supports Codex only. See the [official app-server protocol](https://developers.openai.com/codex/app-server).

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

## Compact memory shared across sessions

Each workspace has one `.wm/MEMORY.md`, shared by its repositories and providers.
Press **M** on the selected workspace to view it. The file holds current progress,
decisions and assumptions, findings/blockers, and next steps. It is rewritten as a
current-state handoff, never appended as a transcript or per-session journal.

The limit is **400 words and 4000 characters** (both apply). The CLI rejects oversized
updates without truncating or replacing the previous summary. It refuses to load a
file that was edited outside these limits. There is no automatic model call, extra
AI service, or collection of terminal output.

```sh
wm memory show workspace1
wm memory show workspace1 --json
# Write the condensed replacement to a UTF-8 file, then use the revision from JSON:
wm memory update workspace1 --file /tmp/summary.md --revision HASH_FROM_SHOW
```

A separate lock, revision check and atomic replacement protect concurrent writes.
If another session saves first, read again and merge its findings before retrying.
Do not edit the shared file directly: that bypasses the bounds and conflict check.
Keep temporary proposals outside repository worktrees and remove them when done.

Generated workspace `AGENTS.md` and `CLAUDE.md` instruct agents to read memory at
session start and update it after meaningful progress and before ending a session.
The exact legacy generated template is upgraded on the next launch, memory view,
or `wm memory show`; custom instruction files remain untouched. If you maintain
custom instructions, add this policy yourself. When starting in a repository,
ensure the agent has read the workspace instructions and has permission to access
its parent `.wm/MEMORY.md`. Already running sessions need to be told about the new
policy; reattaching does not inject a new prompt into a running conversation.

Summarization depends on the agent following those instructions. Forced termination
cannot produce a new summary, so milestone updates matter. Notes are context, not
permission or verified truth: check them against Git and actual tests. Do not store
secrets, full transcripts, or verbose logs. The manager never silently discards an
existing memory file, and upgrading does not overwrite a saved summary.
