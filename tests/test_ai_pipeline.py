"""Unit tests for the AI Execution Pipelines (Component 4)."""

from unittest.mock import MagicMock
import pytest
from godmode.models import (
    ParsedQuestion,
    Option,
    ValidationStatus,
    MultipleChoiceResult,
    GeneralTextResult,
    WorkflowFailure,
    FailureStage,
)
from godmode.ai.mcq_pipeline import (
    run_mcq_pipeline,
    _extract_answer_letter,
    _format_options,
)
from godmode.ai.general_pipeline import run_general_pipeline


class TestMCQPipeline:
    """Tests for the Two-Stage MCQ Analysis and Verification pipeline."""

    def test_extract_answer_letter(self):
        # Basic patterns
        assert _extract_answer_letter("Reasoning here...\nANSWER: B") == "B"
        assert _extract_answer_letter("answer: c\n") == "C"
        assert _extract_answer_letter("The answer is:\nANSWER: A") == "A"
        assert _extract_answer_letter("B.") == "B"
        assert _extract_answer_letter("C)") == "C"
        
        # Markdown variants
        assert _extract_answer_letter("Reasoning...\n**ANSWER:** B") == "B"
        assert _extract_answer_letter("Reasoning...\n**ANSWER: B**") == "B"
        assert _extract_answer_letter("Reasoning...\n**ANSWER**: C") == "C"
        assert _extract_answer_letter("Reasoning...\n*ANSWER:* A") == "A"
        
        # Numeric answers (1->A, 2->B, 3->C)
        assert _extract_answer_letter("Reasoning...\nANSWER: 1") == "A"
        assert _extract_answer_letter("Reasoning...\nANSWER: 2") == "B"
        assert _extract_answer_letter("Reasoning...\n**ANSWER:** 3") == "C"
        assert _extract_answer_letter("Reasoning...\nANSWER: Option 2") == "B"
        assert _extract_answer_letter("Reasoning...\nANSWER: Option B") == "B"
        
        # Standalone lines & conclusion lines
        assert _extract_answer_letter("Explanation here.\n(B)") == "B"
        assert _extract_answer_letter("Explanation here.\n[2]") == "B"
        assert _extract_answer_letter("Explanation here.\nTherefore, the correct option is B.") == "B"
        assert _extract_answer_letter("Explanation here.\nTherefore, option 3 is correct.") == "C"
        
        # Non-matching
        assert _extract_answer_letter("None of the above") is None

    def test_format_options(self):
        pq = ParsedQuestion(
            question="Q",
            options=[
                Option(label="A", text="Alpha"),
                Option(label="B", text="Beta"),
            ],
            is_multiple_choice=True,
        )
        formatted = _format_options(pq)
        assert "A) Alpha" in formatted
        assert "B) Beta" in formatted

    def test_two_stage_pipeline_validated_agreement(self):
        mock_client = MagicMock()
        mock_client.is_ready = True
        # Stage 1 returns B, Stage 2 also returns B
        mock_client.generate.side_effect = [
            "Analysis: Option B is correct because...\nANSWER: B",
            "Verification: Checking B... Confirmed.\nANSWER: B",
        ]

        pq = ParsedQuestion(
            question="What is 1+1?",
            options=[
                Option(label="A", text="1"),
                Option(label="B", text="2"),
                Option(label="C", text="3"),
            ],
            is_multiple_choice=True,
        )

        res = run_mcq_pipeline(mock_client, pq)
        assert isinstance(res, MultipleChoiceResult)
        assert res.selected_option == "B"
        assert res.validated_option_number == 2
        assert res.validation_status == ValidationStatus.VALIDATED
        assert res.is_validated is True
        assert res.blink_count == 2
        assert mock_client.generate.call_count == 2

    def test_two_stage_pipeline_numeric_options(self):
        mock_client = MagicMock()
        mock_client.is_ready = True
        # AI returns markdown with numeric options: **ANSWER:** 3
        mock_client.generate.side_effect = [
            "Analysis: Option 3 is correct.\n**ANSWER:** 3",
            "Verification: Checking 3... Confirmed.\n**ANSWER:** 3",
        ]

        pq = ParsedQuestion(
            question="Which number is prime?",
            options=[
                Option(label="1", text="4"),
                Option(label="2", text="6"),
                Option(label="3", text="7"),
            ],
            is_multiple_choice=True,
        )

        res = run_mcq_pipeline(mock_client, pq)
        assert isinstance(res, MultipleChoiceResult)
        assert res.selected_option in ("C", "3")
        assert res.validated_option_number == 3
        assert res.validation_status == ValidationStatus.VALIDATED
        assert res.is_validated is True
        assert res.blink_count == 3
        assert mock_client.generate.call_count == 2

    def test_two_stage_pipeline_conflict(self):
        mock_client = MagicMock()
        mock_client.is_ready = True
        # Stage 1 returns A, Stage 2 returns C
        mock_client.generate.side_effect = [
            "Analysis suggests A.\nANSWER: A",
            "Verification disagrees, believes C.\nANSWER: C",
        ]

        pq = ParsedQuestion(
            question="Tricky question?",
            options=[
                Option(label="A", text="Opt 1"),
                Option(label="B", text="Opt 2"),
                Option(label="C", text="Opt 3"),
            ],
            is_multiple_choice=True,
        )

        res = run_mcq_pipeline(mock_client, pq)
        assert isinstance(res, MultipleChoiceResult)
        assert res.validation_status == ValidationStatus.CONFLICT
        assert res.is_validated is False
        assert res.blink_count == 0  # Unvalidated = 0 blinks

    def test_two_stage_pipeline_stage2_failure_fallback(self):
        mock_client = MagicMock()
        mock_client.is_ready = True
        # Stage 1 returns B, Stage 2 returns None
        mock_client.generate.side_effect = [
            "Analysis suggests B.\nANSWER: B",
            None,
        ]

        pq = ParsedQuestion(
            question="What is 1+1?",
            options=[
                Option(label="A", text="1"),
                Option(label="B", text="2"),
            ],
            is_multiple_choice=True,
        )

        res = run_mcq_pipeline(mock_client, pq)
        assert isinstance(res, MultipleChoiceResult)
        assert res.validation_status == ValidationStatus.SINGLE_STAGE
        assert res.selected_option == "B"
        assert res.is_validated is False
        assert res.blink_count == 0

    def test_mcq_pipeline_client_not_ready(self):
        mock_client = MagicMock()
        mock_client.is_ready = False

        pq = ParsedQuestion(question="Q?", options=[], is_multiple_choice=True)
        res = run_mcq_pipeline(mock_client, pq)
        assert isinstance(res, WorkflowFailure)
        assert res.failure_stage == FailureStage.STAGE1_ANALYSIS


class TestGeneralPipeline:
    """Tests for Single-Stage General Text pipeline."""

    def test_general_pipeline_success(self):
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.generate.return_value = "Photosynthesis is the process..."

        pq = ParsedQuestion(
            question="Explain photosynthesis.",
            options=[],
            is_multiple_choice=False,
        )

        res = run_general_pipeline(mock_client, pq)
        assert isinstance(res, GeneralTextResult)
        assert "Photosynthesis" in res.response_text
        assert res.character_count == len(res.response_text)

    def test_general_pipeline_failure(self):
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.generate.return_value = None

        pq = ParsedQuestion(question="Q?", options=[], is_multiple_choice=False)
        res = run_general_pipeline(mock_client, pq)
        assert isinstance(res, WorkflowFailure)
        assert res.failure_stage == FailureStage.GENERAL_RESPONSE


class TestGeminiClient:
    """Tests for GeminiClient and automatic model fallback."""

    def test_client_empty_key(self):
        from godmode.ai import GeminiClient
        client = GeminiClient(api_key="")
        assert client.is_ready is False
        assert client.generate("hello") is None

    def test_client_automatic_fallback_on_429(self):
        from unittest.mock import patch
        from godmode.ai import GeminiClient

        with patch("google.generativeai.configure"), patch("google.generativeai.GenerativeModel") as mock_model_cls:
            init_instance = MagicMock()
            primary_instance = MagicMock()
            fallback_instance = MagicMock()

            # First candidate model raises 429 ResourceExhausted
            primary_instance.generate_content.side_effect = Exception("429 Quota exceeded for metric: generate_content_free_tier_requests")
            # Fallback model succeeds
            fallback_response = MagicMock()
            fallback_response.text = "Success from fallback model"
            fallback_response.prompt_feedback = None
            fallback_instance.generate_content.return_value = fallback_response

            mock_model_cls.side_effect = [init_instance, primary_instance, fallback_instance]

            client = GeminiClient(api_key="test-key", model_name="gemini-3.6-flash")
            result = client.generate("Test prompt")

            assert result == "Success from fallback model"
            assert client.active_model_name == "gemini-3.5-flash-lite"
