"""
GodMode Pipeline Orchestrator.

Connects all architecture components into a single execution flow:
  Input Ingestion → Parsing → Routing → AI Pipeline → Results → Signaling

This is the central coordinator that the UI calls to process questions.
"""

import logging
import time
import re
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
from godmode.ai.mcq_pipeline import run_mcq_pipeline, _extract_answer_letter
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
        """Initialize the AI client if API key is configured."""
        if self.config.is_ai_configured:
            from godmode.ai.providers import ProviderRegistry, GeminiProvider, GrokProvider
            registry = ProviderRegistry()
            registry.register(GeminiProvider(api_key=self.config.gemini_api_key, model_name=self.config.gemini_model))
            registry.register(GrokProvider(api_key=self.config.grok_api_key, model_name=self.config.grok_model))

            active_key = self.config.active_api_key
            active_model = self.config.active_model
            self.client = GeminiClient(
                provider_name=self.config.ai_provider,
                api_key=active_key,
                model_name=active_model,
                registry=registry,
            )
            logger.info("Orchestrator initialized with provider: %s, model: %s", self.config.ai_provider, active_model)
        else:
            self.client = None
            logger.warning("AI provider '%s' not configured — AI features disabled", self.config.ai_provider)

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

        # ── Check AI client ───────────────────────────────────────────────
        if not self.client or not self.client.is_ready:
            stage = "Stage 1 (Analysis)" if routing.workflow == WorkflowType.MULTIPLE_CHOICE else "Stage 1 (Analysis)"
            prov_name = "xAI Grok" if self.config.ai_provider.lower() == "grok" else "Gemini"
            key_var = "GROK_API_KEY" if self.config.ai_provider.lower() == "grok" else "GEMINI_API_KEY"
            tracker.fail(stage, f"{prov_name} client not configured")
            tracker.finish_pipeline()
            result.failure = WorkflowFailure(
                failure_stage=FailureStage.STAGE1_ANALYSIS,
                failure_reason=f"{prov_name} API key not configured",
                recovery_suggestion=f"Set {prov_name} API key ({key_var}) in .env file or Settings tab",
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

            # Strict safety clamp: never exceed option count (or 5 for fallback)
            max_allowed = len(parsed.options) if (parsed and parsed.options) else 5
            if blinks and (blinks < 1 or blinks > max_allowed):
                logger.warning("Blink count %d exceeds options count %d; suppressing invalid signal", blinks, max_allowed)
                blinks = None

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

        # ── Print the Key Prominently ──────────────────────────────────────
        opt_lbl = mcq_result.selected_option or "?"
        opt_num = mcq_result.validated_option_number or (blinks if 'blinks' in locals() and blinks else None)
        opt_text = ""
        if parsed and parsed.options:
            for opt in parsed.options:
                if opt.label.upper() == opt_lbl.upper() or (opt_num and opt.label == str(opt_num)):
                    opt_text = opt.text
                    break

        print("\n" + "=" * 62, flush=True)
        print(f" [GOD MODE MCQ KEY] >>> OPTION {opt_num or opt_lbl} ({opt_lbl}): {opt_text} <<<", flush=True)
        print(f" Status: {mcq_result.validation_status.value.upper()} | Blinks: {blinks if 'blinks' in locals() and blinks else (opt_num or 0)}", flush=True)
        print("=" * 62 + "\n", flush=True)

        return result

    def _run_general_workflow(
        self,
        parsed: ParsedQuestion,
        tracker: DiagnosticTracker,
        result: WorkflowResult,
    ) -> WorkflowResult:
        """Execute the general text single-stage pipeline with fail-safe MCQ detection."""

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

        # ── Fail-Safe: Check if Gemini detected an MCQ in the input ─────────
        options_to_check = parsed.options if (parsed and parsed.options) else None
        extracted_ans = _extract_answer_letter(pipeline_result.response_text, options_to_check)
        opt_num = None

        if not extracted_ans and pipeline_result.response_text and getattr(parsed, "raw_input", None):
            first_line = pipeline_result.response_text.strip().split("\n")[0]
            m_ans = re.match(r"(?i)^ANSWER:\s*(.+)$", first_line)
            if m_ans:
                ans_content = m_ans.group(1).strip()
                # 1. Match against parsed options if present
                if parsed and parsed.options:
                    for i, opt in enumerate(parsed.options):
                        if ans_content.lower() in opt.text.lower() or opt.text.lower() in ans_content.lower():
                            opt_num = i + 1
                            extracted_ans = opt.label
                            break

                # 2. Match against labeled lines in raw_input
                raw_lines = [l.strip() for l in parsed.raw_input.split("\n") if l.strip()]
                if not opt_num:
                    for line in raw_lines:
                        m_lbl = re.match(r"^\s*[\(\[]?\s*([A-Ja-j]|[1-9]|10)\s*[\)\]\.:\-\/]\s*(.+)", line)
                        if m_lbl:
                            lbl_char, text_content = m_lbl.group(1).upper(), m_lbl.group(2).strip()
                            if ans_content.lower() in text_content.lower() or text_content.lower() in ans_content.lower():
                                extracted_ans = lbl_char if lbl_char.isalpha() else chr(ord("A") + int(lbl_char) - 1)
                                opt_num = ord(extracted_ans) - ord("A") + 1
                                break

                # 3. Match against tail options in raw_lines (e.g. last 2-5 lines of the input)
                if not opt_num and len(raw_lines) >= 3:
                    for k in (4, 3, 5, 2):
                        if len(raw_lines) >= k + 1:
                            tail = raw_lines[-k:]
                            for tail_idx, line in enumerate(tail):
                                if ans_content.lower() in line.lower() or line.lower() in ans_content.lower():
                                    opt_num = tail_idx + 1
                                    extracted_ans = chr(ord("A") + tail_idx)
                                    break
                            if opt_num:
                                break

        if extracted_ans:
            if opt_num is None:
                if extracted_ans.upper() in "ABCDEFGHIJ":
                    opt_num = ord(extracted_ans.upper()) - ord("A") + 1
                elif extracted_ans.isdigit():
                    opt_num = int(extracted_ans)

            # Strict safety clamp: never exceed option count (or 5 for fallback)
            max_allowed = len(parsed.options) if (parsed and parsed.options) else 5
            if opt_num is not None and (opt_num < 1 or opt_num > max_allowed):
                logger.warning("opt_num %d exceeds max options %d; discarding invalid signal", opt_num, max_allowed)
                opt_num = None
                extracted_ans = None

        if extracted_ans and opt_num:
            opt_text = ""
            if parsed and parsed.options:
                for opt in parsed.options:
                    if opt.label.upper() == extracted_ans.upper() or (opt_num and opt.label == str(opt_num)):
                        opt_text = opt.text
                        break

            mcq_res = MultipleChoiceResult(
                selected_option=extracted_ans,
                validated_option_number=opt_num,
                validation_status=ValidationStatus.SINGLE_STAGE,
                stage1_answer=extracted_ans,
                stage1_reasoning=pipeline_result.response_text,
            )
            result.mcq_result = mcq_res
            result.workflow_type = "multiple_choice"

            # Print the key
            print("\n" + "=" * 62, flush=True)
            print(f" [GOD MODE MCQ KEY] >>> OPTION {opt_num or extracted_ans} ({extracted_ans}): {opt_text} <<<", flush=True)
            print(f" Status: SINGLE_STAGE (from General Fallback) | Blinks: {opt_num or 0}", flush=True)
            print("=" * 62 + "\n", flush=True)

            # Signal if configured
            if self.config.enable_led_signal and opt_num and opt_num > 0:
                sig_kwargs = {}
                if getattr(self.config, "enable_sound_signal", False):
                    sig_kwargs["enable_sound"] = True
                signal_answer_async(opt_num, self.config.blink_duration_ms, **sig_kwargs)

        return result
