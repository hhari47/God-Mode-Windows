"""Unit tests for the Global Hotkey Manager (Native Windows background triggers)."""

from unittest.mock import patch, MagicMock
import pytest
from godmode.hotkeys import (
    GlobalHotkeyManager,
    MOD_CONTROL,
    MOD_WIN,
    MOD_SHIFT,
    MOD_NOREPEAT,
    VK_SPACE,
    VK_S,
    VK_G,
    WM_HOTKEY,
)


class TestGlobalHotkeyManager:
    """Tests for registration, message routing, and lifecycle of global hotkeys."""

    @patch("godmode.hotkeys.threading.Thread")
    def test_start_and_stop_lifecycle(self, mock_thread_cls):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        manager = GlobalHotkeyManager()
        manager.start()

        assert manager._running is True
        mock_thread.start.assert_called_once()

        # Starting again should be a no-op
        manager.start()
        assert mock_thread_cls.call_count == 1

        with patch("godmode.hotkeys.user32.PostThreadMessageW") as mock_post:
            manager._thread_id = 1234
            manager.stop()
            assert manager._running is False
            mock_post.assert_called_once_with(1234, 0x0012, 0, 0)

    @patch("godmode.hotkeys.user32.RegisterHotKey")
    @patch("godmode.hotkeys.user32.UnregisterHotKey")
    def test_registration_flow(self, mock_unregister, mock_register):
        mock_register.return_value = 1

        manager = GlobalHotkeyManager()

        # Test simulate thread loop initialization
        with patch("godmode.hotkeys.ctypes.windll.kernel32.GetCurrentThreadId", return_value=5678):
            with patch("godmode.hotkeys.user32.GetMessageW", return_value=0):  # Immediate exit
                manager._running = True
                manager._msg_loop()

        # Should register 6 hotkeys (Space, S, G, X, Shift+O, Alt+O)
        assert mock_register.call_count == 6
        # Should unregister on cleanup
        assert mock_unregister.call_count == 6

    def test_trigger_silent_ocr_callback(self):
        cb_called = False

        def on_ocr():
            nonlocal cb_called
            cb_called = True

        manager = GlobalHotkeyManager(on_silent_ocr=on_ocr)
        manager._trigger_silent_ocr()

        # Allow thread to execute
        import time
        time.sleep(0.05)
        assert cb_called is True
