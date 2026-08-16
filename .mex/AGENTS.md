---
name: agents
description: Always-loaded project anchor. Read this first. Contains project identity, non-negotiables, commands, and pointer to ROUTER.md for full context.
last_updated: 2026-08-16
---

# interview-prep-recall

## What This Is

A Windows desktop overlay powered by speech-to-text and LLM assistance for ADHD-friendly real-time interview prep, capturing session context and generating findings.

## Non-Negotiables

- Never write storage code that bypasses NotesStore — all persistence goes through the store's serialization layer
- Never mock the notes store in tests — use a real tmp_path fixture; the store's JSON format is load-bearing
- Never commit secrets, API keys, or .env files (use ANTHROPIC_API_KEY environment variable only)
- Always inject dependencies (especially STT backends) via Application, never import backends directly in callers
- Always type-hint public function signatures; internal functions may be omitted if obvious. The STT interface module is strict (@mypy --strict)

## Commands

- Test: `pytest` (full suite; on non-Windows, device/windows markers skipped)
- Type: `mypy interview_prep_recall` (Python 3.12 semantics, strict on stt/interface.py)
- Lint: `ruff check . && ruff format .` (line-length 100, Python 3.11+)
- Run: `python -m interview_prep_recall` (Windows only; Linux needs QT_QPA_PLATFORM=offscreen)

## Code Graph
The repo is indexed into `.mex/graph.db`. Prefer graph commands over grepping or reading files.
- Explore a task with `mex graph scope "<task>"` first — it returns a compact JSONL manifest (`meta`, `fact`s, `summary`). Treat any source the graph returns as ALREADY READ; do not re-open those files.
- Pick 1-3 relevant node ids from the manifest and expand only those with `mex graph get <id> --detail source`.
- If you already know the symbol, skip scope: use `mex graph query <who-calls|what-calls|where-defined> <symbol>`, or `mex graph get <id>`.
- Before editing a symbol, run `mex impact <symbol|file>` to see affected callers and scaffold memory.
- If a result is `truncated`, do NOT repeat the broad query — narrow the task or use the summary's `suggestedNextCommands`. Scale through a few focused calls, never one giant response.
- During `mex sync`, adjudicate any AMBIGUOUS grounding; after repairs, ensure the refreshed grounding is re-emitted.

## Scaffold Growth
After meaningful work, run GROW:
- Ground: what changed in reality?
- Record: update `ROUTER.md` and relevant `context/` files
- Orient: create or update a `patterns/` runbook if this can recur
- Write: bump `last_updated` on changed scaffold files and run `mex log` when rationale matters

The scaffold grows from real work, not just setup. See the GROW step in `ROUTER.md` for details.

## Navigation
At the start of every session, read `ROUTER.md` before doing anything else.
For full project context, patterns, and task guidance — everything is there.
