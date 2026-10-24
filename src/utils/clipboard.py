"""
Буфер обмена напрямую через Win32 API.

Внутренний буфер Tk (clipboard_get / clipboard_clear) на Windows иногда «залипает»: после
clipboard_clear приложение считает себя владельцем буфера и перестаёт видеть текст, скопированный
в других программах. Поэтому чтение, запись и очистка идут через системные вызовы; на других
системах функции возвращают None, и приложение использует запасной путь через Tk.
"""
import ctypes
import sys
import time

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

_WIN = sys.platform == "win32"

if _WIN:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]


def _open(retries: int = 15) -> bool:
    """Буфер может быть кратко занят другой программой — пробуем несколько раз."""
    for _ in range(retries):
        if _user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def get_text() -> str | None:
    """Текст из буфера: строка (пустая, если там не текст) или None, если буфер недоступен."""
    if not _WIN or not _open():
        return None
    try:
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()


def set_text(text: str) -> bool:
    """Кладёт текст в буфер. False, если не получилось (не Windows или буфер занят)."""
    if not _WIN or not _open():
        return False
    try:
        data = (text + "\0").encode("utf-16-le")
        handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            _kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(pointer, data, len(data))
        _kernel32.GlobalUnlock(handle)
        _user32.EmptyClipboard()
        if not _user32.SetClipboardData(CF_UNICODETEXT, handle):
            _kernel32.GlobalFree(handle)
            return False
        return True  # владение памятью перешло системе
    finally:
        _user32.CloseClipboard()


def clear() -> bool:
    """Очищает буфер (например, после захвата токена). False, если не получилось."""
    if not _WIN or not _open():
        return False
    try:
        return bool(_user32.EmptyClipboard())
    finally:
        _user32.CloseClipboard()
