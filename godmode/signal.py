"""
Caps Lock LED Controller — Component 7/8.

Windows implementation of the HIDCapsLockSignaler.
Controls the Caps Lock LED via user32.dll keybd_event.

LED Signal Mapping (from architecture):
  Option 1 → 1 blink
  Option 2 → 2 blinks
  Option 3 → 3 blinks
  Option 4 → 4 blinks
  Unvalidated → no signal (0 blinks)
  Each blink: 200ms ON / 200ms OFF
  Restores original Caps Lock state after signaling.
"""

import ctypes
from ctypes import wintypes
import time
import logging
import threading
from typing import Optional, Callable

try:
    import winsound
except ImportError:
    winsound = None

try:
    from pynput.keyboard import Controller as PynputController, Key as PynputKey
    _pynput_ctrl = PynputController()
except Exception:
    _pynput_ctrl = None

logger = logging.getLogger(__name__)

# ─── Windows API Constants & Structures ───────────────────────────────────────

VK_CAPITAL = 0x14
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1

user32 = ctypes.windll.user32

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", INPUT_UNION),
    ]

# Duplicate signal protection
_signal_lock = threading.Lock()
_is_signaling = False


# ─── Caps Lock State Management ─────────────────────────────────────────────

def get_capslock_state() -> bool:
    """Read current Caps Lock state. Returns True if ON."""
    return bool(user32.GetKeyState(VK_CAPITAL) & 1)


def _send_input_toggle() -> bool:
    """Attempt SendInput toggle with standard scan code 0x3A."""
    try:
        inp_down = INPUT(type=INPUT_KEYBOARD)
        inp_down.u.ki = KEYBDINPUT(wVk=VK_CAPITAL, wScan=0x3A, dwFlags=0, time=0, dwExtraInfo=0)
        inp_up = INPUT(type=INPUT_KEYBOARD)
        inp_up.u.ki = KEYBDINPUT(wVk=VK_CAPITAL, wScan=0x3A, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
        inputs = (INPUT * 2)(inp_down, inp_up)
        ret = user32.SendInput(2, inputs, ctypes.sizeof(INPUT))
        return ret == 2
    except Exception as e:
        logger.debug("SendInput toggle error: %s", e)
        return False


def _keybd_event_toggle() -> None:
    """Toggle Caps Lock using keybd_event with hardware scan code 0x3A (non-extended)."""
    user32.keybd_event(VK_CAPITAL, 0x3A, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(VK_CAPITAL, 0x3A, KEYEVENTF_KEYUP, 0)
    time.sleep(0.01)


def _toggle_capslock() -> None:
    """
    Toggle Caps Lock simulating a key press and release.
    Uses native Windows keybd_event with scan code 0x3A.
    Executes exactly ONE method per toggle to prevent double-tap cancellation.
    """
    try:
        _keybd_event_toggle()
        return
    except Exception as e:
        logger.debug("keybd_event toggle failed: %s", e)

    if _send_input_toggle():
        return

    if _pynput_ctrl is not None:
        try:
            _pynput_ctrl.tap(PynputKey.caps_lock)
        except Exception:
            pass


def set_capslock(desired_state: bool, current_hint: Optional[bool] = None) -> bool:
    """
    Set Caps Lock to a specific state (ON or OFF).

    Args:
        desired_state: True for ON, False for OFF.
        current_hint: Optional known state for threads without message pumps.

    Returns:
        The resulting Caps Lock state (bool).
    """
    current = get_capslock_state() if current_hint is None else current_hint
    if current != desired_state:
        _toggle_capslock()
        time.sleep(0.05)
        return desired_state
    return current


# ─── Blink Pattern Engine ───────────────────────────────────────────────────

def blink_capslock(
    count: int,
    duration_ms: int = 250,
    restore_state: bool = True,
    enable_sound: bool = False,
    blink_callback: Optional[Callable[[int, bool], None]] = None,
) -> bool:
    """
    Blink the Caps Lock LED a specified number of times.

    Implements the architecture's signal pattern:
    - Each blink = duration_ms ON, duration_ms OFF
    - Restores original Caps Lock state after completion
    - Duplicate signal protection (thread-safe)
    - Optional sound beep for laptops without physical Caps Lock LED
    - Optional callback for UI synchronization

    Args:
        count: Number of blinks (0 = no signal).
        duration_ms: Duration of each ON/OFF phase in milliseconds.
        restore_state: If True, restore original Caps Lock state after.
        enable_sound: If True, play an audio beep alongside each blink.
        blink_callback: Optional callable(blink_index, is_on) for UI feedback.

    Returns:
        True if signaling completed, False if skipped or failed.
    """
    global _is_signaling

    if count <= 0:
        logger.info("No signal: blink count is %d", count)
        return False

    if count > 10:
        logger.warning("Blink count %d exceeds maximum (10), clamping", count)
        count = 10

    # Duplicate signal protection
    if not _signal_lock.acquire(blocking=False):
        logger.warning("Signal already in progress — skipping duplicate")
        return False

    original_state = None
    current_state = None
    try:
        _is_signaling = True

        # Save original state
        original_state = get_capslock_state()
        current_state = original_state
        duration_s = max(duration_ms, 50) / 1000.0

        logger.info(
            "Signaling: %d blink(s) at %dms intervals (original state: %s)",
            count, duration_ms, "ON" if original_state else "OFF",
        )

        # Ensure LED is OFF before starting blink sequence
        current_state = set_capslock(False, current_hint=current_state)
        time.sleep(duration_s)

        for i in range(count):
            blink_idx = i + 1

            if blink_callback:
                try:
                    blink_callback(blink_idx, True)
                except Exception:
                    pass

            # Play audible beep for ON phase if sound is enabled
            if enable_sound and winsound:
                try:
                    beep_dur = min(120, int(duration_ms * 0.5))
                    winsound.Beep(1200, beep_dur)
                except Exception:
                    pass

            # ON phase
            current_state = set_capslock(True, current_hint=current_state)
            time.sleep(duration_s)

            if blink_callback:
                try:
                    blink_callback(blink_idx, False)
                except Exception:
                    pass

            # OFF phase
            current_state = set_capslock(False, current_hint=current_state)
            time.sleep(duration_s)

        logger.info("Signal complete: %d blink(s)", count)
        return True

    except Exception as e:
        logger.error("Signaling failed: %s", e)
        return False

    finally:
        # Guarantee state restoration on success, failure, and cancellation
        if restore_state and original_state is not None:
            try:
                set_capslock(original_state, current_hint=current_state)
                logger.info("Caps Lock restored to: %s", "ON" if original_state else "OFF")
            except Exception:
                pass
        _is_signaling = False
        _signal_lock.release()


def signal_answer(
    option_number: Optional[int],
    duration_ms: int = 250,
    enable_sound: bool = False,
    blink_callback: Optional[Callable[[int, bool], None]] = None,
) -> bool:
    """
    Signal a validated MCQ answer via Caps Lock LED blinks.

    Args:
        option_number: 1-4 for options A-D. None or 0 for no signal.
        duration_ms: Blink duration in milliseconds.
        enable_sound: Whether to beep synchronously with blinks.
        blink_callback: Optional UI callback on each blink state change.

    Returns:
        True if signal was sent, False otherwise.
    """
    if option_number is None or option_number <= 0:
        logger.info("No signal: answer not validated")
        return False

    if option_number > 10:
        logger.warning("Option number %d out of range (1-10)", option_number)
        return False

    kwargs = {}
    if enable_sound:
        kwargs["enable_sound"] = True
    if blink_callback is not None:
        kwargs["blink_callback"] = blink_callback

    return blink_capslock(
        count=option_number,
        duration_ms=duration_ms,
        **kwargs,
    )


def signal_answer_async(
    option_number: Optional[int],
    duration_ms: int = 250,
    enable_sound: bool = False,
    blink_callback: Optional[Callable[[int, bool], None]] = None,
) -> Optional[threading.Thread]:
    """
    Signal answer in a background thread (non-blocking).

    Returns the thread object for optional joining.
    """
    if option_number is None or option_number <= 0:
        return None

    thread = threading.Thread(
        target=signal_answer,
        args=(option_number, duration_ms, enable_sound, blink_callback),
        name="capslock-signal",
        daemon=True,
    )
    thread.start()
    return thread
