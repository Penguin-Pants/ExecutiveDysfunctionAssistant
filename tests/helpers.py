"""Doubles shared by more than one test module.

Imported as bare `helpers`, never `tests.helpers`: `tests/` has no `__init__.py`, so
pytest puts the test directory on `sys.path` while the repo root only lands there under
`python -m pytest`, which adds the cwd. CI runs the `pytest` console script, which does
not. This broke CI once, was recorded in the progress doc, and was then written the wrong
way again in the very next milestone — which is why the pre-push check runs under
`PYTHONSAFEPATH=1`.

Imported as bare `helpers`, never `tests.helpers`: `tests/` has no `__init__.py`, so
pytest puts the test directory on `sys.path` and the repo root only appears there under
`python -m pytest`, which adds the cwd. CI runs the `pytest` console script, which does
not. Recorded in the progress doc after it broke CI once — and then written the wrong way
again in the very next milestone, which is why the pre-push check runs `PYTHONSAFEPATH=1`.

Extracted when `test_app.py` needed the same cipher and model client `test_report.py`
already had. Two copies of a double drift, and the divergence shows up as one suite
passing against behaviour the other has already ruled out.
"""

from __future__ import annotations


class ReversingCipher:
    """Obviously not encryption, so no test can accidentally depend on it being one.
    Satisfies the same Protocol the real DPAPI cipher does."""

    def encrypt(self, plaintext: bytes) -> bytes:
        return plaintext[::-1]

    def decrypt(self, ciphertext: bytes) -> bytes:
        return ciphertext[::-1]


def tool_response(payload: dict):  # type: ignore[no-untyped-def]
    """Shaped like a real forced-tool reply: a `tool_use` block carrying parsed input.

    The generator forces `tool_choice`, so this is the only response shape it can
    legitimately receive. A double returning a text block would test a path the API is
    configured never to take.
    """

    class _Block:
        type = "tool_use"
        input = payload

    class _Response:
        content = [_Block()]

    return _Response()


class ScriptedClient:
    """Returns a canned response and records what it was sent."""

    def __init__(self, payload: dict | None = None, boom: Exception | None = None) -> None:
        self.payload = payload if payload is not None else {"findings": []}
        self.boom = boom
        self.requests: list[dict] = []

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.requests.append(kwargs)
        if self.boom is not None:
            raise self.boom
        return tool_response(self.payload)
