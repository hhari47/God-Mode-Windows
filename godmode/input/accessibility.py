"""
Windows Accessibility Text Capture — Component 1a.

Replaces macOS AXSelectedTextProbe with Windows UI Automation.

Strategy (in order of reliability):
1. UI Automation ITextPattern — proper API for reading selected text
2. Clipboard simulation fallback — Ctrl+C with clipboard save/restore

Privacy: Captured text is held only in memory and never logged to disk.
"""

import ctypes
import ctypes.wintypes
import time
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Windows API Constants ───────────────────────────────────────────────────

VK_CONTROL = 0x11
VK_C = 0x43
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_SPACE = 0x20
VK_MENU = 0x12
VK_SHIFT = 0x10
KEYEVENTF_KEYUP = 0x0002
CF_UNICODETEXT = 13

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 64-bit Windows API type declarations (prevents 64-bit handle truncation)
user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
user32.OpenClipboard.restype = ctypes.wintypes.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = ctypes.wintypes.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = ctypes.wintypes.BOOL
user32.GetClipboardData.argtypes = [ctypes.wintypes.UINT]
user32.GetClipboardData.restype = ctypes.wintypes.HANDLE
user32.SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
user32.SetClipboardData.restype = ctypes.wintypes.HANDLE

kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL

# SendInput structures
INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


# ─── Clipboard Helpers ──────────────────────────────────────────────────────

def _read_clipboard() -> Optional[str]:
    """Read unicode text from Windows clipboard."""
    try:
        if not user32.OpenClipboard(0):
            return None
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception as e:
        logger.debug("Clipboard read error: %s", e)
        return None


def _save_clipboard() -> Optional[str]:
    """Save current clipboard text content."""
    return _read_clipboard()


def _restore_clipboard(text: Optional[str]) -> None:
    """Restore text to clipboard. If text is None, clear clipboard."""
    try:
        if not user32.OpenClipboard(0):
            return
        try:
            user32.EmptyClipboard()
            if text is not None:
                encoded = text.encode("utf-16le") + b"\x00\x00"
                size = len(encoded)
                handle = kernel32.GlobalAlloc(0x0002, size)  # GMEM_MOVEABLE
                if handle:
                    ptr = kernel32.GlobalLock(handle)
                    if ptr:
                        ctypes.memmove(ptr, encoded, size)
                        kernel32.GlobalUnlock(handle)
                        user32.SetClipboardData(CF_UNICODETEXT, handle)
        finally:
            user32.CloseClipboard()
    except Exception as e:
        logger.debug("Clipboard restore error: %s", e)


# ─── Keyboard Simulation ────────────────────────────────────────────────────

def _send_key(vk: int, up: bool = False) -> None:
    """Send a single key event via SendInput."""
    ki = KEYBDINPUT()
    ki.wVk = vk
    ki.wScan = 0
    ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    ki.time = 0
    ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))

    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = ki

    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _release_modifiers() -> None:
    """Release any modifier keys that may currently be physically or virtually held down."""
    for vk in (VK_LWIN, VK_RWIN, VK_MENU, VK_SHIFT, VK_SPACE):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def _simulate_ctrl_c() -> None:
    """Simulate Ctrl+C keystroke to copy selection to clipboard."""
    _release_modifiers()
    time.sleep(0.04)
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_C, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


# ─── UI Automation Approach ──────────────────────────────────────────────────

def _try_ui_automation() -> Optional[str]:
    """
    Attempt to read selected text via Windows UI Automation COM interface.

    Uses IUIAutomation -> GetFocusedElement -> TextPattern -> GetSelection.
    Returns None if UI Automation is unavailable or no text is selected.
    """
    try:
        import comtypes
        import comtypes.client

        # Create UIAutomation instance
        uia = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",  # CUIAutomation CLSID
            interface=None,
        )

        # IUIAutomation interface
        IUIAutomation = comtypes.client.GetModule("UIAutomationCore.dll")

        # Get focused element
        focused = uia.GetFocusedElement()
        if not focused:
            return None

        # Try to get TextPattern
        UIA_TextPatternId = 10014
        pattern = focused.GetCurrentPattern(UIA_TextPatternId)
        if not pattern:
            return None

        # Get text pattern interface
        text_pattern = pattern.QueryInterface(IUIAutomation.IUIAutomationTextPattern)
        selection = text_pattern.GetSelection()

        if selection and selection.Length > 0:
            text_range = selection.GetElement(0)
            selected_text = text_range.GetText(-1)  # -1 = get all text
            if selected_text and selected_text.strip():
                return selected_text.strip()

        return None

    except ImportError:
        logger.debug("comtypes not available for UI Automation")
        return None
    except Exception as e:
        logger.debug("UI Automation failed: %s", e)
        return None


# ─── Public API ──────────────────────────────────────────────────────────────

_capture_lock = threading.Lock()


def capture_selected_text() -> Optional[str]:
    """
    Capture currently selected text from the active window.

    Tries UI Automation first, then falls back to clipboard simulation.
    Thread-safe. Never logs captured content (privacy).

    Returns:
        Selected text string, or None if nothing is selected.
    """
    with _capture_lock:
        # Strategy 1: UI Automation (non-intrusive)
        text = _try_ui_automation()
        if text:
            logger.info("Text captured via UI Automation (%d chars)", len(text))
            return text

        # Strategy 2: Clipboard simulation (more reliable fallback)
        logger.debug("UI Automation unavailable, falling back to clipboard simulation")

        # Save current clipboard
        original_clipboard = _save_clipboard()

        try:
            # Clear clipboard first to detect fresh copy
            if user32.OpenClipboard(0):
                user32.EmptyClipboard()
                user32.CloseClipboard()

            # Release any modifier keys and simulate Ctrl+C
            _simulate_ctrl_c()

            # Poll for clipboard update (up to 400ms)
            for _ in range(8):
                time.sleep(0.05)
                text = _read_clipboard()
                if text and text.strip():
                    logger.info("Text captured via clipboard (%d chars)", len(text))
                    return text.strip()

            # Strategy 3: Fallback to existing clipboard content if simulation didn't copy anything new
            if original_clipboard and original_clipboard.strip():
                logger.info("Falling back to existing clipboard content (%d chars)", len(original_clipboard))
                return original_clipboard.strip()

            logger.info("No text selected or capture failed")
            return None

        finally:
            # Always restore original clipboard if we replaced it
            if original_clipboard is not None:
                _restore_clipboard(original_clipboard)

