"""
Desktop Application UI Unit Tests.
"""

from unittest.mock import MagicMock, patch
import pytest

from godmode.config import GodModeConfig
from godmode.ui import GodModeApp, COLORS
from godmode.models import (
    WorkflowResult,
    ParsedQuestion,
    Option,
    MultipleChoiceResult,
    ValidationStatus,
    GeneralTextResult,
    WorkflowFailure,
    FailureStage,
)


@pytest.fixture
def mock_app():
    cfg = GodModeConfig(
        ai_provider="gemini",
        gemini_api_key="test_key",
        gemini_model="gemini-3.5-flash-lite",
        start_minimized=False,
    )
    with patch.object(GodModeApp, "_build_layout"), \
         patch.object(GodModeApp, "_set_app_icon"), \
         patch("godmode.ui._apply_dark_titlebar"), \
         patch("godmode.ui.protect_tk_window"), \
         patch("godmode.ui.SystemTrayManager"), \
         patch("godmode.ui.GlobalHotkeyManager"), \
         patch("godmode.ui.ctk.CTk"):
        app = GodModeApp(cfg)
        return app


def test_ui_format_parsed_mcq(mock_app):
    pq = ParsedQuestion(
        question="What is 2 + 2?",
        options=[Option(label="A", text="3"), Option(label="B", text="4")],
        is_multiple_choice=True,
    )
    res = WorkflowResult(parsed_question=pq)
    formatted = mock_app._format_parsed(res)
    assert "What is 2 + 2?" in formatted
    assert "[A] 3" in formatted
    assert "[B] 4" in formatted
    assert "Multiple Choice Question" in formatted


def test_ui_format_response_mcq(mock_app):
    mcq = MultipleChoiceResult(
        selected_option="B",
        validated_option_number=2,
        validation_status=ValidationStatus.VALIDATED,
        stage1_reasoning="2+2 equals 4.",
        stage2_reasoning="Verified mathematically.",
    )
    res = WorkflowResult(mcq_result=mcq)
    formatted = mock_app._format_response(res)
    assert "OPTION 2 (B)" in formatted
    assert "VALIDATED" in formatted
    assert "2 pulse(s)" in formatted or "2" in formatted
    assert "2+2 equals 4" in formatted


def test_ui_format_response_failure(mock_app):
    fail = WorkflowFailure(
        failure_stage=FailureStage.STAGE1_ANALYSIS,
        failure_reason="Network socket timeout",
        recovery_suggestion="Check your internet connection",
    )
    res = WorkflowResult(failure=fail)
    formatted = mock_app._format_response(res)
    assert "PIPELINE FAILURE AT: stage1_analysis" in formatted
    assert "Network socket timeout" in formatted
    assert "Check your internet connection" in formatted


def test_ui_format_diagnostics(mock_app):
    res = WorkflowResult(
        workflow_type="multiple_choice",
        provider="gemini",
        model_used="gemini-3.5-flash-lite",
        total_duration_ms=420.0,
    )
    diag = mock_app._format_diagnostics(res)
    assert "Workflow: multiple_choice" in diag
    assert "Provider: gemini" in diag
    assert "420 ms" in diag


def test_ui_color_palette():
    assert COLORS["bg_window"] == "#090D16"
    assert COLORS["accent_blue"] == "#38BDF8"
    assert COLORS["accent_green"] == "#10B981"
    assert COLORS["bg_sidebar"] == "#0E131F"
