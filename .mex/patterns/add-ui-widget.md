---
name: add-ui-widget
description: Add a new UI widget, view, or overlay component to the main window
triggers:
  - "add widget"
  - "new UI feature"
  - "overlay component"
  - "add view"
edges:
  - target: context/conventions.md
    condition: when understanding class naming and structure patterns
  - target: context/architecture.md
    condition: when understanding how widgets integrate with MainWindow
  - target: context/stack.md
    condition: when understanding PySide6-specific patterns and constraints
  - target: patterns/track-session-progress.md
    condition: when a widget needs to update or display session state
grounds_to: []
last_updated: 2026-08-16
---

# Add UI Widget

## Context

All UI components are PySide6-based and live in `interview_prep_recall/ui/`. The [`MainWindow`](mex://class:069d69e10655afbd2725a6920ee0f59d) is the composition root that owns all widgets and connects them to the `Application` instance. New widgets are instantiated in the main window and wired to session/settings callbacks.

Patterns:
- Each major widget/view is its own file (e.g., `editor.py`, `checklist.py`, `overlay.py`)
- Widgets receive `Application` and relevant data/callbacks via constructor
- Qt signals propagate state changes back to Application
- No widget owns multiple major concerns; split if growing beyond ~300 lines

## Steps

1. Create the widget class in a new file under `interview_prep_recall/ui/`, e.g. `interview_prep_recall/ui/my_widget.py`
   - Inherit from appropriate Qt base class (`QWidget`, `QDialog`, etc.)
   - Define `__init__` with `Application` parameter and any callbacks
   - Declare Qt signals for events that affect session state (use `Signal` from PySide6.QtCore)
   - Do not store mutable application state; only read-only access to Application properties

2. Add widget instantiation to `MainWindow.__init__()` in `interview_prep_recall/ui/main_window.py`
   - Instantiate with `Application` instance and wire signals to callbacks
   - Add to layout if visible; otherwise keep reference for programmatic show/hide

3. Wire state changes:
   - Connect widget signals → Application methods if the change affects session/findings
   - Connect Application state changes → widget slots if the widget displays that state
   - Use Qt's signal/slot mechanism; avoid direct imperative updates

4. Add tests in `tests/test_ui_<my_widget>.py`
   - Instantiate widget with a test Application and tmp_path for notes store
   - Test signal emissions and slot reactions
   - Do not test Qt rendering; only state changes and signal flow

## Gotchas

- **Don't put business logic in widgets** — keep widgets as view-only; use Application methods for changes
- **Don't store mutable state in widgets** — read from Application, emit signals for changes
- **Qt signal connections are implicit** — verify signal names match exactly (typos create silent failures)
- **MainWindow owns lifecycle** — don't keep extra references to widgets in tests that outlive the window
- **Test QApplication availability** — use `qapp` fixture from conftest.py; tests mark with `@pytest.mark.skip` if PySide6 not installed

## Verify

- [ ] New widget class is in `interview_prep_recall/ui/<name>.py` with PascalCase name
- [ ] `__init__` receives `Application` as parameter, no global imports of Application
- [ ] All state-changing operations emit signals or call Application methods
- [ ] Widget has no `@property` methods that write to Application state directly
- [ ] MainWindow instantiates the widget and wires signals
- [ ] Tests pass: `pytest tests/test_ui_<name>.py`
- [ ] No print/logging in widget code; use exceptions with context if something fails

## Debug

If widget does not update when state changes: check that Application state change actually invokes the widget's slot. Trace the signal chain: Application → signal → widget slot.

If widget signals don't propagate back to Application: verify signal is declared with `Signal()`, emitted with `self.signal.emit(args)`, and connected in MainWindow with `.connect()`.

If tests fail due to missing QApplication: ensure test file imports `qapp` fixture or runs under `QT_QPA_PLATFORM=offscreen`.

## Update Scaffold

- [ ] Update `.mex/ROUTER.md` "Current Project State" if a new UI subsystem was added
- [ ] If this widget represents a new category of UI patterns, create a domain file: `.mex/context/ui-patterns.md`
- [ ] Update this pattern if gotchas discovered
