# Agentic Workspace

> **Note:** aw is written in Spanish. The menu, command output, templates and the protocol it gives Claude Code
> are all in Spanish. This page only explains what it is; the full manual is the [Spanish README](Readme.md).

A workspace for working with AI agents in [Claude Code](https://claude.com/claude-code). Every project keeps its
tasks, decisions and history in plain Markdown files, and Claude Code hooks read and write them automatically.
One Python file, standard library only, no dependencies.

## What it does

- **Session start:** a hook gives the model a short digest of the project: tasks in progress, next tasks, the last
  decision and recent activity. Each session starts knowing where the work stands.
- **While working:** hooks record commits (read from the git reflog, not from the command text), tool failures
  (first line only, with secrets masked) and a summary of each session.
- **What needs judgement** goes through fixed-format commands: `aw task add|start|done`, `aw decide "title" --why
  "reason"` (a decision without a reason is rejected) and `aw log "note"`.
- **Maintenance:** `aw sync` brings existing projects up to date with the template without overwriting anything,
  `aw doctor` reports what is missing, and `aw project import` / `aw unsync` migrate an existing folder and undo it.

## Quick start

```bash
git clone https://github.com/Scrambledeggs-ai/agentic-workspace.git && cd agentic-workspace
python3 generate.py init                       # create the workspace
python3 generate.py project new my-project     # create a project
cd projects/my-project && claude               # open Claude Code inside the project
```

Requires Python 3.10+, git and Claude Code. Tested on Linux and macOS.

## License

MIT. See [LICENSE](LICENSE).
