"""Unit tests for the GodMode Pipeline Orchestrator."""

from unittest.mock import MagicMock, patch
import pytest
from godmode.config import GodModeConfig
from godmode.models import ValidationStatus, FailureStage
from godmode.orchestrator import GodModeOrchestrator


class TestOrchestrator:
    """End-to-end pipeline execution tests with mock Gemini client."""

    @pytest.fixture
    def mock_config(self):
        return GodModeConfig(
            gemini_api_key="test_key_12345",
            gemini_model="gemini-2.0-flash",
            enable_led_signal=True,
            blink_duration_ms=50,
        )

    @patch("godmode.orchestrator.signal_answer_async")
    @patch("godmode.orchestrator.GeminiClient")
    def test_mcq_full_pipeline_success(self, mock_client_cls, mock_signal, mock_config):
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.model_name = "gemini-2.0-flash"
        # Stage 1 and Stage 2 both answer C
        mock_client.generate.side_effect = [
            "Reasoning...\nANSWER: C",
            "Verification confirms C.\nANSWER: C",
        ]
        mock_client_cls.return_value = mock_client

        orchestrator = GodModeOrchestrator(mock_config)

        raw_mcq = """Which planet is closest to the Sun?
A) Earth
B) Venus
C) Mercury
D) Mars"""

        result = orchestrator.process(raw_mcq)

        assert result.is_success is True
        assert result.workflow_type == "multiple_choice"
        assert result.mcq_result is not None
        assert result.mcq_result.selected_option == "C"
        assert result.mcq_result.validated_option_number == 3
        assert result.mcq_result.validation_status == ValidationStatus.VALIDATED
        assert "Option 3" in result.result_summary

        # Verify async signal was dispatched for option 3
        mock_signal.assert_called_once_with(3, 50)

    @patch("godmode.orchestrator.GeminiClient")
    def test_general_text_pipeline_success(self, mock_client_cls, mock_config):
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.model_name = "gemini-2.0-flash"
        mock_client.generate.return_value = "Entropy is a measure of randomness or disorder in a system."
        mock_client_cls.return_value = mock_client

        orchestrator = GodModeOrchestrator(mock_config)

        raw_question = "Explain entropy in thermodynamics."
        result = orchestrator.process(raw_question)

        assert result.is_success is True
        assert result.workflow_type == "general_text"
        assert result.text_result is not None
        assert "Entropy" in result.text_result.response_text
        assert result.mcq_result is None

    def test_empty_input_handled_gracefully(self, mock_config):
        orchestrator = GodModeOrchestrator(mock_config)
        result = orchestrator.process("")

        assert result.is_success is False
        assert result.failure is not None
        assert result.failure.failure_stage == FailureStage.CAPTURE

    def test_unconfigured_api_key_fails_gracefully(self):
        empty_config = GodModeConfig(gemini_api_key="")
        orchestrator = GodModeOrchestrator(empty_config)

        result = orchestrator.process("What is 2+2?\nA) 3\nB) 4")
        assert result.is_success is False
        assert result.failure is not None
        assert "API key" in result.failure.recovery_suggestion
