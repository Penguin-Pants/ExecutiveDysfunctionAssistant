---
name: track-session-progress
description: Track user progress during interview, update findings, and generate reports
triggers:
  - "session tracking"
  - "update findings"
  - "add note to session"
  - "session progress"
  - "report generation"
edges:
  - target: context/architecture.md
    condition: when understanding how session state flows to report generation
  - target: context/conventions.md
    condition: when implementing data models for session context
  - target: context/decisions.md
    condition: when understanding why file-based storage was chosen
  - target: patterns/add-ui-widget.md
    condition: when building UI that displays session progress or findings
grounds_to: []
last_updated: 2026-08-16
---

# Track Session Progress

## Context

Session progress tracking involves three main data structures:

- **Application** — holds active session, manages pause/resume
- **ContextSet** — in-memory context with notes, decisions, and findings; the working copy during a session
- **NotesStore** — persistent JSON storage; serializes ContextSet at session end

The flow is: interview happens → notes added via UI → ContextSet updated → at session end, ContextSet serialized and stored → later, stored sessions restored and displayed in report view.

## Steps

### Updating Session Findings

1. In the UI widget (e.g., editor, checklist), collect user input
2. Call `Application` method to record the finding:
   ```python
   app.context.add_note(Note(kind=NoteKind.FINDING, text=user_text, timestamp=now))
   ```
3. Emit a signal or call a callback so the UI updates (e.g., report view refreshes)
4. On session pause/end, call `Application.save_session()` which serializes to NotesStore

### Generating a Report

1. Load a session from NotesStore: `store.load(session_id)`
2. Pass the ContextSet to ReportGenerator: `generator.generate(context_set)`
3. ReportGenerator iterates over notes, groups by kind, formats findings
4. Display report in UI or serialize to HTML

### Restoring a Session

1. User clicks "Restore Session" in UI
2. Prompt NotesStore: `stored_session = store.restore(session_id)`
3. Create new ContextSet from stored_session.context
4. Instantiate new Application with restored context
5. UI reads Application state and refreshes views

## Gotchas

- **Don't mutate ContextSet directly** — go through Application methods so state is consistent
- **Notes are immutable** — create new Note, don't edit existing. Old notes stay in history.
- **Timestamps matter** — always include timestamp when adding notes; use `time.time()` (not datetime, which doesn't serialize cleanly)
- **Serialization must be reversible** — test that ContextSet → JSON → ContextSet round-trips without loss
- **No concurrent sessions** — only one Application instance per process; don't try to manage multiple sessions at once

## Verify

- [ ] New findings are added via Application method, not direct ContextSet mutation
- [ ] Each note includes a timestamp
- [ ] Report generation iterates over notes correctly (no duplicates, all kinds handled)
- [ ] Session save/restore round-trip: save → load → compare ContextSet (should be identical)
- [ ] NotesStore call includes error handling (file not found, corruption, permission denied)
- [ ] Tests use tmp_path fixture for NotesStore, not mocking
- [ ] No print statements in session tracking code; use exceptions with context

## Debug

If report shows wrong findings: check that notes were added with correct kind. Trace ContextSet mutations: is Application method actually being called?

If session restore fails: check NotesStore file exists and is valid JSON. Log the error context (which session id, what operation failed).

If findings disappear after close/restore: verify that Application.save_session() is called before exit. Check that ContextSet is serialized completely (no fields skipped).

## Update Scaffold

- [ ] Update `.mex/ROUTER.md` "Current Project State" if a new tracking capability was added
- [ ] If new note kinds introduced, document in `.mex/context/architecture.md` "Key Components"
