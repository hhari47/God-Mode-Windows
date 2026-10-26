"""Unit tests for the Caps Lock Signal Coordinator (Component 7/8)."""

from unittest.mock import patch, MagicMock
import pytest
from godmode.signal import (
    get_capslock_state,
    set_capslock,
    blink_capslock,
    signal_answer,
    signal_answer_async,
)


class TestSignalCoordinator:
    """Tests for Caps Lock LED blink logic, mapping, and state management."""

    @patch("godmode.signal.user32.GetKeyState")
    def test_get_capslock_state(self, mock_get_key_state):
        mock_get_key_state.return_value = 1
        assert get_capslock_state() is True

        mock_get_key_state.return_value = 0
        assert get_capslock_state() is False

    @patch("godmode.signal._toggle_capslock")
    @patch("godmode.signal.get_capslock_state")
    def test_set_capslock_changes_when_different(self, mock_get_state, mock_toggle):
        mock_get_state.return_value = False
        set_capslock(True)
        mock_toggle.assert_called_once()

    @patch("godmode.signal._toggle_capslock")
    @patch("godmode.signal.get_capslock_state")
    def test_set_capslock_does_nothing_when_matching(self, mock_get_state, mock_toggle):
        mock_get_state.return_value = True
        set_capslock(True)
        mock_toggle.assert_not_called()

    @patch("godmode.signal.time.sleep")
    @patch("godmode.signal.set_capslock")
    @patch("godmode.signal.get_capslock_state")
    def test_blink_capslock_restores_initial_state(self, mock_get_state, mock_set, mock_sleep):
        # Initial state is True (Caps lock ON)
        mock_get_state.return_value = True

        result = blink_capslock(count=2, duration_ms=50, restore_state=True)
        assert result is True

        # Last call to set_capslock should restore initial state True
        assert mock_set.call_args[0][0] is True

    def test_blink_capslock_zero_or_negative_count(self):
        assert blink_capslock(0) is False
        assert blink_capslock(-1) is False

    @patch("godmode.signal.blink_capslock")
    def test_signal_answer_mapping(self, mock_blink):
        mock_blink.return_value = True

        # Option 1 -> 1 blink
        assert signal_answer(1, duration_ms=100) is True
        mock_blink.assert_called_with(count=1, duration_ms=100)

        # Option 2 -> 2 blinks
        signal_answer(2, duration_ms=100)
        mock_blink.assert_called_with(count=2, duration_ms=100)

        # Option 3 -> 3 blinks
        signal_answer(3, duration_ms=100)
        mock_blink.assert_called_with(count=3, duration_ms=100)

        # Option 4 -> 4 blinks
        signal_answer(4, duration_ms=100)
        mock_blink.assert_called_with(count=4, duration_ms=100)

        # Unvalidated (None or 0) -> no signal (False)
        assert signal_answer(None) is False
        assert signal_answer(0) is False

        # Option 5 (E) -> 5 blinks
        signal_answer(5, duration_ms=100)
        mock_blink.assert_called_with(count=5, duration_ms=100)

        # Out of bounds (> 10) -> rejected
        assert signal_answer(11) is False

    @patch("godmode.signal.signal_answer")
    def test_signal_answer_async(self, mock_signal):
        thread = signal_answer_async(2, duration_ms=50)
        assert thread is not None
        thread.join(timeout=1.0)

        assert signal_answer_async(None) is None
