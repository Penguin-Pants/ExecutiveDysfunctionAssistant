"""DPAPI cipher, bound to the current Windows user (FR82).

Windows-only and unverifiable in the Linux dev container, which is why `Cipher` is a
Protocol and every other test injects its own. This module is the one part of T11.2 that
genuinely needs the target machine.

`CryptProtectData` with no entropy and no flags binds the blob to the current user
account on the current machine, which is exactly FR82's requirement: a session file
copied to another profile or another machine must not open.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char)))


def _to_blob(data: bytes) -> _Blob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _from_blob(blob: _Blob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


class DpapiCipher:
    """Satisfies `report.store.Cipher`."""

    def encrypt(self, plaintext: bytes) -> bytes:
        out = _Blob()
        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        if not crypt32.CryptProtectData(
            ctypes.byref(_to_blob(plaintext)), None, None, None, None, 0, ctypes.byref(out)
        ):
            raise OSError("CryptProtectData failed")
        try:
            return _from_blob(out)
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)  # type: ignore[attr-defined]

    def decrypt(self, ciphertext: bytes) -> bytes:
        out = _Blob()
        crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
        if not crypt32.CryptUnprotectData(
            ctypes.byref(_to_blob(ciphertext)), None, None, None, None, 0, ctypes.byref(out)
        ):
            # Also the expected outcome on another account or machine, which is the
            # property FR82 is actually asserting.
            raise OSError("CryptUnprotectData failed — wrong user, wrong machine, or corrupt")
        try:
            return _from_blob(out)
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)  # type: ignore[attr-defined]
