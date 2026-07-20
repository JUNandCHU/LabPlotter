from __future__ import annotations

import ctypes
import os
import time
from io import BytesIO

from PIL import Image

from .i18n import tr


CF_DIB = 8
GMEM_MOVEABLE = 0x0002


def png_to_dib(png: bytes) -> bytes:
    """Convert PNG bytes to a CF_DIB payload (a BMP without its 14-byte file header)."""
    with Image.open(BytesIO(png)) as source:
        image = source.convert("RGB")
        output = BytesIO()
        image.save(output, "BMP")
    dib = output.getvalue()[14:]
    if len(dib) < 40:
        raise RuntimeError(tr("Could not create a Windows bitmap for the clipboard."))
    return dib


def _configure_windows_clipboard_api(kernel32, user32) -> None:
    from ctypes import wintypes

    kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = (wintypes.HGLOBAL,)
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    user32.OpenClipboard.argtypes = (wintypes.HWND,)
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = ()
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = ()
    user32.CloseClipboard.restype = wintypes.BOOL


def _windows_clipboard_api():
    """Return 64-bit-safe Win32 clipboard functions.

    ctypes otherwise assumes c_int return values. On 64-bit Windows that truncates
    the pointer returned by GlobalLock and can cause an access violation in memmove.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    _configure_windows_clipboard_api(kernel32, user32)
    return kernel32, user32


def copy_png_to_clipboard(png: bytes) -> None:
    """Copy an image as Windows CF_DIB so it pastes into Office and Origin."""
    if os.name != "nt":
        raise RuntimeError(tr("Image clipboard is currently supported on Windows builds."))
    dib = png_to_dib(png)
    kernel32, user32 = _windows_clipboard_api()
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
    if not handle:
        raise RuntimeError(tr("Could not allocate clipboard memory."))
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise RuntimeError(tr("Could not lock clipboard memory."))
    try:
        ctypes.memmove(pointer, dib, len(dib))
    finally:
        kernel32.GlobalUnlock(handle)

    opened = False
    try:
        for _attempt in range(10):
            if user32.OpenClipboard(None):
                opened = True
                break
            time.sleep(0.05)
        if not opened:
            raise RuntimeError(tr("Could not open the Windows clipboard. Close other clipboard tools and try again."))
        if not user32.EmptyClipboard():
            raise RuntimeError(tr("Could not clear the Windows clipboard."))
        if not user32.SetClipboardData(CF_DIB, handle):
            raise RuntimeError(tr("Windows rejected the bitmap clipboard data."))
        handle = None  # Windows owns the HGLOBAL after SetClipboardData succeeds.
    finally:
        if opened:
            user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)
