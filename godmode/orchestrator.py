"""
GodMode Pipeline Orchestrator.

Connects all architecture components into a single execution flow:
  Input Ingestion → Parsing → Routing → AI Pipeline → Results → Signaling

This is the central coordinator that the UI calls to process questions.
"""

import logging
import time
from typing import Optional

from godmode.config import GodModeConfig
from godmode.models import (
    ParsedQuestion,
    MultipleChoiceResult,
    GeneralTextResult,
    WorkflowFailure,
    WorkflowResult,
    FailureStage,
    ValidationStatus,
)
from godmode.parser import parse_question
from godmode.router import route_question, WorkflowType
from godmode.ai import GeminiClient
from godmode.ai.mcq_pipeline import run_mcq_pipeline
from godmode.ai.general_pipeline import run_general_pipeline
from godmode.signal import signal_answer_async
from godmode.diagnostics import DiagnosticTracker

logger = logging.getLogger(__name__)


class GodModeOrchestrator:
    """
    Main pipeline orchestrator.

    Manages the Gemini client and coordinates the full workflow
    from raw text input through AI analysis to LED signaling.
    """

    def __init__(self, config: GodModeConfig):
        self.config = config
        self.client: Optional[GeminiClient] = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize the Gemini client if API key is configured."""
        if self.config.is_gemini_configured:
            self.client = GeminiClient(
                api_key=self.config.gemini_api_key,
                model_name=self.config.gemini_model,
            )
            logger.info("Orchestrator initialized with model: %s", self.config.gemini_model)
        else:
            logger.warning("Gemini API key not configured — AI features disabled")

    def reconfigure(self, config: GodModeConfig) -> None:
        """Reconfigure with new settings (e.g., after API key change)."""
        self.config = config
        self._initialize_client()

    def process(self, raw_text: str) -> WorkflowResult:
        """
        Execute the full GodMode pipeline on raw text input.

        Pipeline stages:
        1. Parse input → ParsedQuestion
        2. Route → MCQ or General Text workflow
        3. Execute AI pipeline
        4. Signal answer (MCQ only, if validated)
        5. Return structured result with diagnostics

        Args:
            raw_text: Raw question text from any input source.

        Returns:
            WorkflowResult with result data and diagnostics.
        """
        tracker = DiagnosticTracker()
        tracker.start_pipeline()

        result = WorkflowResult()

        # ── Stage: Capture (already done by caller, just validate) ────────
        tracker.start("Capture")
        if not raw_text or not raw_text.strip():
            tracker.fail("Capture", "Empty input received")
            tracker.finish_pipeline()
            result.failure = WorkflowFailure(
                failure_stage=FailureStage.CAPTURE,
                failure_reason="No text provided",
                recovery_suggestion="Select text, capture a screen region, or type a question",
            )
            result.total_duration_ms = tracker.total_duration_ms
            result.diagnostics_summary = tracker.summary
            return result
        tracker.complete("Capture", f"Received {len(raw_text.strip())} chars")

        # ── Stage: Parsing ────────────────────────────────────────────────
        tracker.start("Parsing")
        try:
            parsed = parse_question(raw_text)
            result.parsed_question = parsed

            if parsed.parse_warnings:
                tracker.warn("Parsing", "; ".join(parsed.parse_warnings))
            else:
                msg = (
                    f"MCQ: {parsed.option_count} options"
                    if parsed.is_multiple_choice
                    else "General text question"
                )
                tracker.complete("Parsing", msg)
        except Exception as e:
            tracker.fail("Parsing", str(e))
            tracker.finish_pipeline()
            result.failure = WorkflowFailure(
                failure_stage=FailureStage.PARSING,
                failure_reason=f"Parser error: {e}",
                recovery_suggestion="Check input format and try again",
                exception=e,
            )
            result.total_duration_ms = tracker.total_duration_ms
            result.diagnostics_summary = tracker.summary
            return result

        # ── Stage: Routing ────────────────────────────────────────────────
        tracker.start("Routing")
        routing = route_question(parsed)
        result.workflow_type = routing.workflow.value
        tracker.complete("Routing", f"{routing.workflow.value} (confidence: {routing.confidence:.0%})")

        # ── Check Gemini client ───────────────────────────────────────────
        if not self.client or not self.client.is_ready:
            stage = "Stage 1 (Analysis)" if routing.workflow == WorkflowType.MULTIPLE_CHOICE else "Stage 1 (Analysis)"
            tracker.fail(stage, "Gemini client not configured")
            tracker.finish_pipeline()
            result.failure = WorkflowFailure(
                failure_stage=FailureStage.STAGE1_ANALYSIS,
                failure_reason="Gemini API key not configured",
                recovery_suggestion="Set Gemini API key (GEMINI_API_KEY) in .env file or Settings tab",
            )
            result.total_duration_ms = tracker.total_duration_ms
            result.diagnostics_summary = tracker.summary
            return result

        result.model_used = self.client.model_name

        # ── Stage: AI Pipeline ────────────────────────────────────────────
        if routing.workflow == WorkflowType.MULTIPLE_CHOICE:
            result = self._run_mcq_workflow(parsed, tracker, result)
        else:
            result = self._run_general_workflow(parsed, tracker, result)

        tracker.finish_pipeline()
        result.total_duration_ms = tracker.total_duration_ms
        result.diagnostics_summary = tracker.summary

        logger.info("Pipeline complete in %.0fms: %s", result.total_duration_ms, result.result_summary)
        return result

    def _run_mcq_workflow(
        self,
        parsed: ParsedQuestion,
        tracker: DiagnosticTracker,
        result: WorkflowResult,
    ) -> WorkflowResult:
        """Execute the MCQ two-stage pipeline with signaling."""

        # Stage 1 & 2 are handled inside run_mcq_pipeline
        tracker.start("Stage 1 (Analysis)")
        tracker.start("Stage 2 (Verification)")

        pipeline_result = run_mcq_pipeline(self.client, parsed)

        if isinstance(pipeline_result, WorkflowFailure):
            tracker.fail("Stage 1 (Analysis)", pipeline_result.failure_reason)
            tracker.skip("Stage 2 (Verification)", "Stage 1 failed")
            tracker.skip("Validation", "Pipeline failed")
            tracker.skip("Signaling", "Pipeline failed")
            result.failure = pipeline_result
            return result

        # Pipeline succeeded
        mcq_result = pipeline_result
        result.mcq_result = mcq_result

        # Update tracker based on results
        tracker.complete("Stage 1 (Analysis)", f"Answer: {mcq_result.stage1_answer}")

        if mcq_result.stage2_answer:
            tracker.complete("Stage 2 (Verification)", f"Answer: {mcq_result.stage2_answer}")
        else:
            tracker.warn("Stage 2 (Verification)", "No answer extracted")

        # Validation
        tracker.start("Validation")
        tracker.complete("Validation", f"Status: {mcq_result.validation_status.value}")

        # Signaling
        tracker.start("Signaling")
        can_signal_fallback = (
            getattr(self.config, "allow_single_stage_signal", True)
            and mcq_result.validation_status in (ValidationStatus.SINGLE_STAGE, ValidationStatus.CONFLICT)
            and mcq_result.selected_option is not None
        )
        should_signal = (mcq_result.is_validated or can_signal_fallback)
        if should_signal and self.config.enable_led_signal:
            sig_kwargs = {}
            if getattr(self.config, "enable_sound_signal", False):
                sig_kwargs["enable_sound"] = True
            blinks = mcq_result.validated_option_number
            if blinks is None and mcq_result.selected_option:
                sel = mcq_result.selected_option.upper()
                if sel in "ABCDEFGHIJ":
                    blinks = ord(sel) - ord("A") + 1
                elif sel.isdigit():
                    blinks = int(sel)

            if blinks and blinks > 0:
                signal_thread = signal_answer_async(
                    blinks,
                    self.config.blink_duration_ms,
                    **sig_kwargs,
                )
                if signal_thread:
                    mode_str = (
                        "validated"
                        if mcq_result.is_validated
                        else ("conflict fallback" if mcq_result.validation_status == ValidationStatus.CONFLICT else "single-stage")
                    )
                    tracker.complete(
                        "Signaling",
                        f"{blinks} blink(s) for option {mcq_result.selected_option} ({mode_str})",
                    )
                else:
                    tracker.warn("Signaling", "Signal thread failed to start")
            else:
                tracker.skip("Signaling", "Could not resolve blink count for option")
        elif not should_signal:
            tracker.skip("Signaling", f"Answer not validated ({mcq_result.validation_status.value})")
        else:
            tracker.skip("Signaling", "LED signaling disabled in settings")

        return result

    def _run_general_workflow(
        self,
        parsed: ParsedQuestion,
        tracker: DiagnosticTracker,
        result: WorkflowResult,
    ) -> WorkflowResult:
        """Execute the general text single-stage pipeline."""

        tracker.start("Stage 1 (Analysis)")
        tracker.skip("Stage 2 (Verification)", "Not applicable for general text")
        tracker.skip("Validation", "Not applicable for general text")
        tracker.skip("Signaling", "Not applicable for general text")

        pipeline_result = run_general_pipeline(self.client, parsed)

        if isinstance(pipeline_result, WorkflowFailure):
            tracker.fail("Stage 1 (Analysis)", pipeline_result.failure_reason)
            result.failure = pipeline_result
            return result

        tracker.complete("Stage 1 (Analysis)", f"Response: {pipeline_result.character_count} chars")
        result.text_result = pipeline_result
        return result
