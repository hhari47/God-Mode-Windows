"""
Global Hotkey Manager for Windows — Background Native Triggers.

Uses Windows native user32.RegisterHotKey API to register system-wide hotkeys
that work across all applications without requiring elevated/admin permissions.

Exclusive Hotkeys:
  - Ctrl + Alt + X: Silent capture selected text & execute pipeline (LED signal output)
  - Ctrl + Alt + O: Silent background Screen OCR & solve (Clean display, zero popups)
"""

import ctypes
import ctypes.wintypes
import threading
import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32

# Modifiers for RegisterHotKey
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# Virtual Key codes
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_SPACE = 0x20
VK_G = 0x47
VK_O = 0x4F
VK_Q = 0x51
VK_S = 0x53
VK_X = 0x58
VK_LWIN = 0x5B
VK_RWIN = 0x5C

WM_HOTKEY = 0x0312
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class GlobalHotkeyManager:
    """
    Manages native Windows global hotkeys in a dedicated message-pump thread.
    """

    def __init__(
        self,
        on_capture_text: Optional[Callable[[], None]] = None,
        on_capture_snip: Optional[Callable[[], None]] = None,
        on_toggle_ui: Optional[Callable[[], None]] = None,
        on_silent_ocr: Optional[Callable[[], None]] = None,
    ):
        self.on_capture_text = on_capture_text
        self.on_capture_snip = on_capture_snip
        self.on_toggle_ui = on_toggle_ui
        self.on_silent_ocr = on_silent_ocr

        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._running = False
        self._registered_ids: set[int] = set()
        self._hook = None
        self._hook_cb = None
        self._space_down = False
        self._o_down = False
        self._last_capture_time = 0.0
        self._last_ocr_time = 0.0

    def _trigger_capture_text(self) -> None:
        """Debounced trigger for capture_text callback."""
        now = time.time()
        if now - self._last_capture_time < 0.5:
            return
        self._last_capture_time = now
        if self.on_capture_text:
            threading.Thread(target=self.on_capture_text, daemon=True).start()

    def _trigger_silent_ocr(self) -> None:
        """Debounced trigger for silent_ocr callback."""
        now = time.time()
        if now - self._last_ocr_time < 0.5:
            return
        self._last_ocr_time = now
        if self.on_silent_ocr:
            threading.Thread(target=self.on_silent_ocr, daemon=True).start()

    def _hook_proc(self, nCode: int, wParam: int, lParam: int) -> int:
        """Low-level keyboard hook for responsive intercept of shortcuts."""
        if nCode >= 0:
            try:
                kb = KBDLLHOOKSTRUCT.from_address(lParam)
                if kb.vkCode == VK_X:
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                        alt = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
                        if ctrl and alt:
                            if not self._space_down:
                                self._space_down = True
                                logger.info("Triggered via low-level hook: Ctrl + Alt + X (Solve Selected)")
                                self._trigger_capture_text()
                    elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                        self._space_down = False
                elif kb.vkCode == VK_O:
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                        alt = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
                        if ctrl and alt:
                            if not self._o_down:
                                self._o_down = True
                                logger.info("Triggered via low-level hook: Ctrl + Alt + O (Screen OCR)")
                                self._trigger_silent_ocr()
                    elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                        self._o_down = False
            except Exception as e:
                logger.debug("Hook error: %s", e)
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def start(self) -> None:
        """Start listening for global hotkeys in a background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._msg_loop, daemon=True, name="godmode-hotkeys")
        self._thread.start()
        logger.info("Global hotkeys listener thread started")

    def stop(self) -> None:
        """Stop listening and unregister hotkeys."""
        self._running = False
        if self._thread_id:
            # Post WM_QUIT to terminate GetMessage loop
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        logger.info("Global hotkeys listener stopped")

    def _msg_loop(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        # Install low-level hook for instant response
        self._hook_cb = HOOKPROC(self._hook_proc)
        try:
            self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_cb, 0, 0)
            if self._hook:
                logger.info("Low-level hook installed for global hotkeys")
        except Exception as e:
            logger.debug("Could not install low-level hook: %s", e)

        # Register exclusively the two main hotkeys:
        # ID 1: Ctrl + Alt + X (Solve Selected)
        # ID 2: Ctrl + Alt + O (Screen OCR & Solve)
        hotkeys = [
            (1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_X, "Ctrl+Alt+X (Solve Selected)"),
            (2, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_O, "Ctrl+Alt+O (Screen OCR)"),
        ]

        for hk_id, mod, vk, desc in hotkeys:
            res = user32.RegisterHotKey(None, hk_id, mod, vk)
            if res:
                self._registered_ids.add(hk_id)
                logger.info("Registered global hotkey: %s", desc)
            else:
                logger.warning("Could not register hotkey %s (may be in use by another app)", desc)

        msg = ctypes.wintypes.MSG()
        try:
            while self._running:
                # GetMessage blocks until a message arrives
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:  # WM_QUIT or error
                    break

                if msg.message == WM_HOTKEY:
                    hk_id = msg.wParam
                    logger.debug("Received WM_HOTKEY: %d", hk_id)
                    if hk_id == 1:
                        self._trigger_capture_text()
                    elif hk_id == 2:
                        self._trigger_silent_ocr()

                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook:
                try:
                    user32.UnhookWindowsHookEx(self._hook)
                    logger.info("Unhooked low-level keyboard hook")
                except Exception:
                    pass
                self._hook = None

            # Unregister all
            for hk_id in list(self._registered_ids):
                user32.UnregisterHotKey(None, hk_id)
            self._registered_ids.clear()
            logger.info("Unregistered all global hotkeys")
