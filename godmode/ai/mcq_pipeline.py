"""
Two-Stage MCQ Pipeline — Component 4 (Multiple Choice path).

Implements the architecture's two-stage Gemini analysis/verification pipeline:

  Stage 1: Gemini Analysis
    - Analyze question and all options
    - Return candidate answer with reasoning

  Stage 2: Gemini Verify
    - Independent verification of Stage 1's candidate
    - Cross-check with fresh analysis

  Cross Validator
    - Evaluate agreement between Stage 1 and Stage 2
    - Determine ValidationStatus
    - Produce final MultipleChoiceResult
"""

import re
import time
import logging
from typing import Optional

from godmode.models import (
    ParsedQuestion,
    MultipleChoiceResult,
    ValidationStatus,
    WorkflowFailure,
    FailureStage,
)
from godmode.ai import GeminiClient

logger = logging.getLogger(__name__)


# ─── Prompt Templates ────────────────────────────────────────────────────────

STAGE1_PROMPT = """You are an expert at answering multiple-choice questions.

Analyze the following question and options carefully. Consider each option thoroughly.

Question: {question}

Options:
{options_text}

Instructions:
1. Analyze each option against the question
2. Explain your reasoning briefly
3. On the LAST line, write ONLY: ANSWER: X
   where X is the option label (e.g., A, B, C, D or 1, 2, 3, 4)

Important: Your final line must be exactly "ANSWER: X" with the correct option label."""

STAGE2_PROMPT = """You are an independent verifier for multiple-choice answers.

A previous analysis suggested the answer to the following question is "{candidate}".
Your task is to INDEPENDENTLY verify whether this is correct.

Question: {question}

Options:
{options_text}

Instructions:
1. Analyze the question fresh, without bias toward the suggested answer
2. Evaluate each option independently
3. State whether you agree or disagree with "{candidate}" and why
4. On the LAST line, write ONLY: ANSWER: X
   where X is the option label you believe is correct (e.g., A, B, C, D or 1, 2, 3, 4)

Important: Your final line must be exactly "ANSWER: X" with the correct option label."""


# ─── Answer Extraction ───────────────────────────────────────────────────────

def _extract_answer_letter(response: str, options: Optional[list] = None) -> Optional[str]:
    """
    Extract the answer letter or number from a Gemini response.

    Robustly handles:
    - ANSWER: X (where X is A-J, 1-10)
    - **ANSWER: X**, **ANSWER:** X, **ANSWER**: X, **ANSWER**: **X**
    - ANSWER: Option X, ANSWER: (X), ANSWER: [X], ANSWER: X.
    - Markdown formatting (bold, italics, headers)
    - Line-by-line reverse scan for concluding answer statements
    - Standalone final lines: (B), [2], 2., B), etc.
    - Matching option text if letter is omitted
    - Normalizes digits (1..10) to uppercase letters (A..J)

    Returns:
        Canonical uppercase letter ("A", "B", "C", ...) or None.
    """
    if not response:
        return None

    num_to_letter = {
        "1": "A", "2": "B", "3": "C", "4": "D", "5": "E",
        "6": "F", "7": "G", "8": "H", "9": "I", "10": "J",
    }

    # Clean markdown formatting for reliable regex matching
    clean = re.sub(r"[\*_`#]", "", response).strip()

    # Strategy 1: Explicit ANSWER: pattern anywhere
    m = re.search(
        r"ANSWER\s*:\s*(?:Option\s*)?[\(\[]?([A-Ja-j]|10|[1-9])[\)\]\.\s]?",
        clean,
        re.IGNORECASE,
    )
    if m:
        ans = m.group(1).upper()
        return num_to_letter.get(ans, ans)

    # Strategy 2: Scan lines in reverse order (Gemini puts conclusion at end)
    lines = [line.strip() for line in clean.split("\n") if line.strip()]
    for line in reversed(lines):
        # Match "correct answer/option is X" or "choice X"
        m = re.search(
            r"(?:correct\s+)?(?:answer|option|choice)\s*(?:is\s*)?[:=]?\s*[\(\[]?([A-Ja-j]|10|[1-9])[\)\]\.]?",
            line,
            re.IGNORECASE,
        )
        if m:
            ans = m.group(1).upper()
            return num_to_letter.get(ans, ans)

        # Standalone letter or number on its own line: e.g. "B", "2", "(B)", "[2]", "B.", "2)"
        m = re.match(
            r"^[\(\[]?\s*(?:Option\s*)?([A-Ja-j]|10|[1-9])\s*[\)\]\.\s]*$",
            line,
            re.IGNORECASE,
        )
        if m:
            ans = m.group(1).upper()
            return num_to_letter.get(ans, ans)

    # Strategy 3: Match against option text if options are provided
    if options:
        last_section = clean[-400:] if len(clean) > 400 else clean
        for opt in options:
            opt_text = getattr(opt, "text", "")
            opt_label = getattr(opt, "label", "")
            if opt_text and len(opt_text.strip()) > 2:
                if opt_text.strip().lower() in last_section.lower():
                    ans = opt_label.upper()
                    return num_to_letter.get(ans, ans)

    return None


def _format_options(parsed: ParsedQuestion) -> str:
    """Format options for prompt insertion."""
    return "\n".join(f"{opt.label}) {opt.text}" for opt in parsed.options)


# ─── Pipeline Execution ─────────────────────────────────────────────────────

def run_mcq_pipeline(
    client: GeminiClient,
    parsed: ParsedQuestion,
) -> MultipleChoiceResult | WorkflowFailure:
    """
    Execute the two-stage MCQ pipeline.

    Stage 1: Analysis → candidate answer
    Stage 2: Independent verification → confirmed answer
    Cross-validation: Compare results → final decision

    Args:
        client: Configured GeminiClient.
        parsed: ParsedQuestion with valid MCQ data.

    Returns:
        MultipleChoiceResult on success, WorkflowFailure on error.
    """
    if not client.is_ready:
        return WorkflowFailure(
            failure_stage=FailureStage.STAGE1_ANALYSIS,
            failure_reason="Gemini client not configured",
            recovery_suggestion="Set GEMINI_API_KEY in .env file",
        )

    options_text = _format_options(parsed)

    # Comprehensive mapping for all option representations
    # (letters A-Z, numbers 1-99, and original labels)
    label_to_number: dict[str, int] = {}
    for i, opt in enumerate(parsed.options):
        idx = i + 1
        label_to_number[opt.label] = idx
        label_to_number[opt.label.upper()] = idx
        label_to_number[str(idx)] = idx
        letter = chr(ord("A") + i) if i < 26 else str(idx)
        label_to_number[letter] = idx

    def _resolve_option_num(ans: Optional[str]) -> Optional[int]:
        if not ans:
            return None
        return (
            label_to_number.get(ans)
            or label_to_number.get(str(ans))
            or label_to_number.get(ans.upper())
        )

    # ── Stage 1: Gemini Analysis ──────────────────────────────────────────

    logger.info("Stage 1: Gemini Analysis starting")
    stage1_prompt = STAGE1_PROMPT.format(
        question=parsed.question,
        options_text=options_text,
    )

    stage1_response = client.generate(stage1_prompt, temperature=0.1)
    if not stage1_response:
        error_msg = getattr(client, "last_error", None) or "Gemini returned no response for Stage 1 analysis"
        suggestion = "Check API key and network connection, then retry"
        if "404" in error_msg or "not found" in error_msg.lower():
            suggestion = f"The model '{client.model_name}' may be deprecated or unavailable. Try updating GEMINI_MODEL (e.g. gemini-3.8-flash) in Settings or .env"
        elif "API_KEY_INVALID" in error_msg or "400" in error_msg:
            suggestion = "Your API key appears invalid. Check GEMINI_API_KEY in Settings or .env"

        return WorkflowFailure(
            failure_stage=FailureStage.STAGE1_ANALYSIS,
            failure_reason=error_msg,
            recovery_suggestion=suggestion,
        )

    stage1_answer = _extract_answer_letter(stage1_response, parsed.options)
    if not stage1_answer:
        return WorkflowFailure(
            failure_stage=FailureStage.STAGE1_ANALYSIS,
            failure_reason="Could not extract answer letter from Stage 1 response",
            recovery_suggestion="The question may be ambiguous. Try rephrasing.",
        )

    logger.info("Stage 1 complete: candidate answer = %s", stage1_answer)

    # ── Stage 2: Gemini Verify ────────────────────────────────────────────

    logger.info("Stage 2: Gemini Verification starting")
    stage2_prompt = STAGE2_PROMPT.format(
        candidate=stage1_answer,
        question=parsed.question,
        options_text=options_text,
    )

    stage2_response = client.generate(stage2_prompt, temperature=0.1)
    if not stage2_response:
        # Stage 2 failed but Stage 1 succeeded — return with SINGLE_STAGE status
        logger.warning("Stage 2 failed — returning Stage 1 result as single-stage")
        opt_num = _resolve_option_num(stage1_answer)
        return MultipleChoiceResult(
            selected_option=stage1_answer,
            validated_option_number=opt_num,
            validation_status=ValidationStatus.SINGLE_STAGE,
            stage1_answer=stage1_answer,
            stage1_reasoning=stage1_response,
        )

    stage2_answer = _extract_answer_letter(stage2_response, parsed.options)
    if not stage2_answer:
        logger.warning("Stage 2 answer extraction failed — returning as single-stage")
        opt_num = _resolve_option_num(stage1_answer)
        return MultipleChoiceResult(
            selected_option=stage1_answer,
            validated_option_number=opt_num,
            validation_status=ValidationStatus.SINGLE_STAGE,
            stage1_answer=stage1_answer,
            stage1_reasoning=stage1_response,
            stage2_reasoning=stage2_response,
        )

    logger.info("Stage 2 complete: verification answer = %s", stage2_answer)

    # ── Cross Validation ──────────────────────────────────────────────────

    if stage1_answer == stage2_answer:
        # Both stages agree — VALIDATED
        validation_status = ValidationStatus.VALIDATED
        final_answer = stage1_answer
        opt_num = _resolve_option_num(final_answer)
        logger.info("Cross-validation: VALIDATED (both stages agree on %s)", final_answer)
    else:
        # Stages disagree — CONFLICT
        validation_status = ValidationStatus.CONFLICT
        final_answer = stage1_answer  # Default to Stage 1
        opt_num = None  # Conflict is unvalidated
        logger.warning(
            "Cross-validation: CONFLICT (Stage 1=%s, Stage 2=%s). "
            "Defaulting to Stage 1.",
            stage1_answer, stage2_answer,
        )

    return MultipleChoiceResult(
        selected_option=final_answer,
        validated_option_number=opt_num,
        validation_status=validation_status,
        stage1_answer=stage1_answer,
        stage1_reasoning=stage1_response,
        stage2_answer=stage2_answer,
        stage2_reasoning=stage2_response,
    )
