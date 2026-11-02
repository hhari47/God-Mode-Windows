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
VK_INSERT = 0x2D
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


try:
    from pynput.keyboard import Controller as PynputController, Key as PynputKey
    _pynput_kbd = PynputController()
except Exception:
    _pynput_kbd = None


def _wait_for_keys_released(timeout: float = 0.8) -> None:
    """Wait until user has released ALL physical modifier keys (Ctrl, Alt, Win, Space, Shift)."""
    start = time.time()
    while time.time() - start < timeout:
        ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        alt = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        shift = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
        space = bool(user32.GetAsyncKeyState(VK_SPACE) & 0x8000)
        win = bool((user32.GetAsyncKeyState(VK_LWIN) | user32.GetAsyncKeyState(VK_RWIN)) & 0x8000)
        if not (ctrl or alt or shift or space or win):
            break
        time.sleep(0.02)


def _simulate_ctrl_c() -> None:
    """Simulate Ctrl+C keystroke to copy selection to clipboard."""
    _wait_for_keys_released(timeout=0.8)
    # Release ALL lingering virtual key states including Ctrl
    for vk in (VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN, VK_SHIFT, VK_SPACE):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.06)

    # Double-check modifiers are truly released before sending Ctrl+C
    for vk in (VK_CONTROL, VK_MENU, VK_SHIFT, VK_SPACE):
        if user32.GetAsyncKeyState(vk) & 0x8000:
            logger.debug("Modifier vk=0x%02X still held after release, waiting extra", vk)
            time.sleep(0.15)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.04)

    if _pynput_kbd is not None:
        try:
            with _pynput_kbd.pressed(PynputKey.ctrl):
                time.sleep(0.03)
                _pynput_kbd.press('c')
                time.sleep(0.04)
                _pynput_kbd.release('c')
                time.sleep(0.03)
            return
        except Exception as e:
            logger.debug("pynput Ctrl+C simulation failed: %s", e)

    # Fallback to keybd_event with proper keydown/keyup timing
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_C, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _simulate_ctrl_insert() -> None:
    """Simulate Ctrl+Insert keystroke (Windows alternative copy shortcut).

    Many browser-based exam and test environments specifically intercept
    or block 'c' / 'Ctrl+C' events, but neglect 'Ctrl+Insert'.
    """
    _wait_for_keys_released(timeout=0.4)
    for vk in (VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN, VK_SHIFT, VK_SPACE):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.04)

    if _pynput_kbd is not None:
        try:
            with _pynput_kbd.pressed(PynputKey.ctrl):
                time.sleep(0.03)
                _pynput_kbd.press(PynputKey.insert)
                time.sleep(0.04)
                _pynput_kbd.release(PynputKey.insert)
                time.sleep(0.03)
            return
        except Exception as e:
            logger.debug("pynput Ctrl+Insert simulation failed: %s", e)

    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_INSERT, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(VK_INSERT, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


# ─── UI Automation Approach (macOS AXUIElement Equivalent) ───────────────────

def _try_ui_automation() -> Optional[str]:
    """
    Attempt to read selected text via Windows UI Automation COM interface.
    This is the direct Windows equivalent of macOS AXUIElementCopyAttributeValue.
    It reads selected text directly from the application's accessibility tree
    without sending any synthetic keystrokes and without touching the clipboard.
    Works silently and seamlessly across browsers, documents, and testing environments.
    """
    try:
        import comtypes
        import comtypes.client

        co_init = False
        try:
            comtypes.CoInitialize()
            co_init = True
        except Exception:
            pass

        try:
            IUIAutomation = comtypes.client.GetModule("UIAutomationCore.dll")
            uia = comtypes.client.CreateObject(
                "{ff48dba4-60ef-4201-aa87-54103eef594e}",
                interface=IUIAutomation.IUIAutomation,
            )

            UIA_TextPatternId = 10014
            UIA_TextPattern2Id = 10024

            def _get_selection_from_pattern(elem) -> Optional[str]:
                if not elem or not bool(elem):
                    return None
                for pid in (UIA_TextPatternId, UIA_TextPattern2Id):
                    try:
                        pattern = elem.GetCurrentPattern(pid)
                        if pattern and bool(pattern):
                            text_pattern = pattern.QueryInterface(IUIAutomation.IUIAutomationTextPattern)
                            selection = text_pattern.GetSelection()
                            if selection and selection.Length > 0:
                                text_range = selection.GetElement(0)
                                selected_text = text_range.GetText(-1)
                                if selected_text and selected_text.strip():
                                    return selected_text.strip()
                    except Exception:
                        pass
                return None

            # 1. Check focused element directly
            focused = None
            try:
                focused = uia.GetFocusedElement()
            except Exception as e:
                logger.debug("UIA GetFocusedElement error: %s", e)

            if focused and bool(focused):
                text = _get_selection_from_pattern(focused)
                if text:
                    logger.info("Text captured via UI Automation (focused element, %d chars)", len(text))
                    return text

                # 2. Walk up ancestor tree (in web browsers, selection is often on Document parent)
                try:
                    walker = uia.ControlViewWalker
                    curr = focused
                    for _ in range(6):
                        parent = walker.GetParentElement(curr)
                        if not parent or not bool(parent):
                            break
                        text = _get_selection_from_pattern(parent)
                        if text:
                            logger.info("Text captured via UI Automation (ancestor element, %d chars)", len(text))
                            return text
                        curr = parent
                except Exception as e:
                    logger.debug("UIA ancestor walk error: %s", e)

            # 3. Check active foreground window and its text descendants
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                try:
                    fg_elem = uia.ElementFromHandle(ctypes.c_void_p(hwnd))
                    if fg_elem and bool(fg_elem):
                        text = _get_selection_from_pattern(fg_elem)
                        if text:
                            logger.info("Text captured via UI Automation (foreground window, %d chars)", len(text))
                            return text

                        # Search descendants of foreground window for element with TextPattern
                        # 30040 = UIA_IsTextPatternAvailablePropertyId, 7 = TreeScope_Subtree
                        cond = uia.CreatePropertyCondition(30040, True)
                        text_elem = fg_elem.FindFirst(7, cond)
                        if text_elem and bool(text_elem):
                            text = _get_selection_from_pattern(text_elem)
                            if text:
                                logger.info("Text captured via UI Automation (text descendant, %d chars)", len(text))
                                return text
                except Exception as e:
                    logger.debug("UIA foreground window inspection error: %s", e)

            return None
        finally:
            if co_init:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

    except ImportError:
        logger.debug("comtypes not available for UI Automation")
        return None
    except Exception as e:
        logger.debug("UI Automation failed: %s", e)
        return None


# ─── Win32 Native Message Selection ──────────────────────────────────────────

def _try_win32_edit_selection() -> Optional[str]:
    """
    Try reading selected text from standard Windows Edit or RichEdit controls
    via Win32 messages (EM_GETSEL / WM_GETTEXT) without touching the clipboard.
    """
    try:
        hwnd_fg = user32.GetForegroundWindow()
        if not hwnd_fg:
            return None

        tid = user32.GetWindowThreadProcessId(hwnd_fg, None)
        if not tid:
            return None

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("flags", ctypes.wintypes.DWORD),
                ("hwndActive", ctypes.wintypes.HWND),
                ("hwndFocus", ctypes.wintypes.HWND),
                ("hwndCapture", ctypes.wintypes.HWND),
                ("hwndMenuOwner", ctypes.wintypes.HWND),
                ("hwndMoveSize", ctypes.wintypes.HWND),
                ("hwndCaret", ctypes.wintypes.HWND),
                ("rcCaret", ctypes.wintypes.RECT),
            ]

        gti = GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(GUITHREADINFO)
        target_hwnd = hwnd_fg
        if user32.GetGUIThreadInfo(tid, ctypes.byref(gti)) and gti.hwndFocus:
            target_hwnd = gti.hwndFocus

        # EM_GETSEL = 0x00B0
        start = ctypes.wintypes.DWORD()
        end = ctypes.wintypes.DWORD()
        if user32.SendMessageW(target_hwnd, 0x00B0, ctypes.byref(start), ctypes.byref(end)):
            s, e = start.value, end.value
            if e > s and (e - s) < 100000:
                txt_len = user32.SendMessageW(target_hwnd, 0x000E, 0, 0)  # WM_GETTEXTLENGTH
                if txt_len > 0:
                    buf = ctypes.create_unicode_buffer(txt_len + 1)
                    user32.SendMessageW(target_hwnd, 0x000D, txt_len + 1, buf)  # WM_GETTEXT
                    val = buf.value[s:e].strip()
                    if val:
                        logger.info("Text captured via Win32 EM_GETSEL (%d chars)", len(val))
                        return val
    except Exception as e:
        logger.debug("Win32 edit selection query failed: %s", e)
    return None


# ─── Public API ──────────────────────────────────────────────────────────────

_capture_lock = threading.Lock()


def capture_selected_text() -> Optional[str]:
    """
    Capture currently selected text from the active window.

    Strategy Pipeline:
    1. Windows UI Automation (macOS AXUIElement equivalent — non-intrusive, no keys, no clipboard)
    2. Win32 Native Control Selection (EM_GETSEL — direct message, no clipboard)
    3. Hardware Keystroke Simulation (Ctrl+C and Ctrl+Insert fallback)

    Thread-safe. Never logs captured content (privacy).

    Returns:
        Selected text string, or None if nothing is selected.
    """
    with _capture_lock:
        # Strategy 1: UI Automation (non-intrusive, matches macOS Accessibility)
        text = _try_ui_automation()
        if text:
            return text

        # Strategy 2: Win32 Edit control message query
        text = _try_win32_edit_selection()
        if text:
            return text

        # Strategy 3: Keystroke simulation (Ctrl+C and Ctrl+Insert fallback)
        logger.debug("Direct accessibility unavailable, attempting keystroke simulation")

        # Save current clipboard
        original_clipboard = _save_clipboard()
        captured_text = None

        try:
            # Clear clipboard first to detect fresh copy
            if user32.OpenClipboard(0):
                user32.EmptyClipboard()
                user32.CloseClipboard()
            time.sleep(0.03)

            # Attempt 1: Release any modifier keys and simulate Ctrl+C
            _simulate_ctrl_c()

            # Poll for clipboard update (up to 600ms)
            for _ in range(12):
                time.sleep(0.05)
                text = _read_clipboard()
                if text and text.strip():
                    logger.info("Text captured via clipboard (%d chars)", len(text))
                    captured_text = text.strip()
                    return captured_text

            # Attempt 2: Try Ctrl+Insert (alternative copy shortcut that bypasses tests blocking Ctrl+C)
            logger.debug("First Ctrl+C attempt failed, trying Ctrl+Insert fallback...")
            if user32.OpenClipboard(0):
                user32.EmptyClipboard()
                user32.CloseClipboard()
            time.sleep(0.05)
            _simulate_ctrl_insert()

            for _ in range(12):
                time.sleep(0.05)
                text = _read_clipboard()
                if text and text.strip():
                    logger.info("Text captured via Ctrl+Insert (%d chars)", len(text))
                    captured_text = text.strip()
                    return captured_text

            # Do NOT fall back to old clipboard content — that causes the
            # "stuck on old question" bug where a previous question's text
            # gets reused instead of the newly-selected text.
            logger.info("No text selected or Ctrl+C capture failed after 2 attempts")
            return None

        finally:
            # Restore original clipboard if capture failed completely
            if captured_text is None and original_clipboard is not None:
                _restore_clipboard(original_clipboard)

