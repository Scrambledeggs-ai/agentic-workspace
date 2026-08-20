# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Agentic Workspace" — a file-based scaffolding system for an AI-agent workspace: a fixed
directory tree of markdown/JSON files that acts as persistent memory, project state, and
role/skill/tool definitions for orchestrating agents, plus a single-file interactive menu
(`generate.py`) to manage it. Zero dependencies beyond Python 3 and `git`. Upstream reference:
https://github.com/Scrambledeggs-ai/agentic-workspace. There is no other application code — the
rest of the repo is the schema (`structure.json`) and the content files it scaffolds.

## Commands

- `python3 generate.py` — opens the interactive menu (also installable as the `aw` command via
  menu option 9, which drops a wrapper at `~/.local/bin/aw`).
  - **Proyectos**: 1) create a new project (clones `projects/template_project/`, sets
    `project.md`/`state.md`) · 2) list projects with their one-line state · 3) view a project's
    `tasks/active.md` · 4) view a project's `execution/decisions.md`.
  - **Sistema**: 5) run/re-run the structure build from `structure.json` (never overwrites an
    existing file — safe to re-run) · 6/7/8) list or create entries in `agents/` / `skills/` /
    `tools/` · 9) install the `aw` command.

There is no build, lint, or test tooling in this repo.

## Architecture

`structure.json` is the single source of truth for the directory tree. `generate.py`'s `build()`
walks it recursively: every `files` entry becomes a touched file (pre-filled with a default
header when one exists in `DEFAULT_HEADERS`, otherwise empty), every `folders` map becomes a
subdirectory processed the same way. To change what the scaffold contains, edit `structure.json`
(and `DEFAULT_HEADERS` if the new file should ship with a name/description), not the recursion
logic itself.

**Capability catalog auto-discovery**: `agents/`, `skills/`, and `tools/` are not tracked by any
central index file — menu options 6/7/8 just scan the folder for `*.md` files and read a YAML-ish
header off the top of each one:

```
---
name: Coding Agent
description: Agente especializado en generación y edición de código.
---
```

Any `.md` in one of those three folders that starts with this block is picked up automatically —
nothing to register elsewhere. `read_header()` / `make_header()` in `generate.py` are the only
code that understands this format. (An earlier design had explicit `registry.md` index files in
each folder; those were removed — the header-scan replaced them.)

Top-level layout (per `structure.json`):

- `core/` — the agent runtime's own spec files (`agent.md`, `router.md`, `config.md`,
  `memory_policy.md`, `init.md`). Defines how the agent boots, routes work, and manages memory.
  Touched rarely.
- `agents/` — role definitions (`base_agent.md`, `research_agent.md`, `coding_agent.md`,
  `planning_agent.md`), discovered via the header scan above.
- `skills/` — skill definitions (`git_skill.md`, `coding_skill.md`, `web_research_skill.md`,
  `memory_skill.md`), same discovery mechanism.
- `tools/` — tool definitions (`filesystem_tool.md`, `web_tool.md`, `executor_tool.md`), same
  discovery mechanism.
- `memory/` — global, cross-project memory: `global.md`, `user_profile.md`, `preferences.md`,
  `context_index.json`, and `projects/project_index.md` indexing individual projects.
- `projects/template_project/` — the template cloned into every new project (menu option 1).
  Touched rarely — only when changing the template for all future projects.
- `projects/<name>/` — one workspace per real project, cloned from the template:
  - `project.md`, `state.md`, `memory.md`, `context_index.json` — identity/state/memory.
    `state.md`'s first non-empty line is what menu option 2 shows as the project's status.
  - `tasks/{backlog,active,done}.md` — task tracking (`active.md` is what menu option 3 shows).
  - `execution/{run_log,decisions,errors}.md` — execution history (`decisions.md` is what menu
    option 4 shows).
  - `agents/{assigned_agents,agent_context}.md` — which agents are working this project.
  - `tools/{tool_usage.md,tool_state.json}` — tool call history/state.
  - `artifacts/{outputs,code_snippets,assets_index}.md` — produced outputs.
  - `sop/{workflow,rules,conventions,README}.md` — project-specific operating procedures.
  - Touched often — this is the day-to-day working layer.
- `logs/` — `debug.md`, `current_month.md`. Excluded from git.
- `playground/` — scratch project folders (`test-landing`, `prueba-app` per `structure.json`),
  free-form sandbox space.

`.gitignore` excludes `logs/` and every `projects/*` folder except `projects/template_project/` —
individual project workspaces stay local/uncommitted while the template and schema are versioned.

## What fills itself vs. what needs writing

`generate.py` only ever creates *empty* files (or, for the 11 files listed in `DEFAULT_HEADERS`,
files with just a name/description header) — it never generates real spec content. The only thing
that's automatic is discovery (the header scan above). Everything else — the actual body of each
`core/*.md`, `agents/*.md`, `skills/*.md`, `tools/*.md`, `memory/*.md`, and each project's
`project.md`/tasks/decisions as work progresses — has to be written, by hand or by asking Claude
Code to write it. There's currently no mechanism that makes Claude Code itself read `core/*.md` at
session start; the menu is a project-management CLI for the human, not a session bootstrapper.
