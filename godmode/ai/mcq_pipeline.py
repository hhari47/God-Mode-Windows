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

def _normalize_for_compare(text: str) -> str:
    """Normalize text for comparison: strip outer quotes/backticks, lowercase, collapse spaces."""
    if not text:
        return ""
    s = text.strip()
    # Strip outer single, double quotes or backticks if enclosed
    if (s.startswith('"') and s.endswith('"') and len(s) >= 2) or \
       (s.startswith("'") and s.endswith("'") and len(s) >= 2) or \
       (s.startswith("`") and s.endswith("`") and len(s) >= 2):
        s = s[1:-1].strip()
    return re.sub(r"\s+", " ", s.lower())


def _match_answer_to_option(
    answer_text: str,
    options: list,
) -> Optional[tuple[str, int]]:
    """
    Map an answer text to the correct option by comparing against option texts.

    Uses a strict matching hierarchy:
    1. Exact match (normalized)
    2. Longest matching option when unambiguous (prevents [4, 6] matching [4, 6, 8])

    Returns:
        (label, 1-based index) or None if no confident match.
    """
    if not answer_text or not options:
        return None

    answer_norm = _normalize_for_compare(answer_text)
    if not answer_norm:
        return None

    # Pass 1: Exact match (after normalization)
    exact_matches = []
    for i, opt in enumerate(options):
        opt_text = _normalize_for_compare(getattr(opt, "text", ""))
        if opt_text and opt_text == answer_norm:
            exact_matches.append((getattr(opt, "label", "").upper(), i + 1))

    if len(exact_matches) == 1:
        return exact_matches[0]
    elif len(exact_matches) > 1:
        # Ambiguous multiple exact matches
        return None

    # Pass 2: Containment match — longest matching option wins to prevent
    # e.g. "[4, 6]" matching "[4, 6, 8]" instead of "[4, 6]"
    # Only run substring match when answer has at least 2 characters (never for single letters A-Z)
    if len(answer_norm) < 2:
        return None

    matches = []
    for i, opt in enumerate(options):
        opt_text = _normalize_for_compare(getattr(opt, "text", ""))
        if not opt_text or len(opt_text) < 2:
            continue
        if opt_text == answer_norm:
            matches.append((i, len(opt_text), True))  # exact
        elif opt_text in answer_norm or answer_norm in opt_text:
            matches.append((i, len(opt_text), False))

    if not matches:
        return None

    # Prefer exact matches, then by closeness in length (prevents substring ambiguity)
    exact = [m for m in matches if m[2]]
    if exact:
        best_idx = exact[0][0]
    elif len(matches) == 1:
        best_idx = matches[0][0]
    else:
        # Multiple substring matches — pick the one whose length is closest to the answer
        matches.sort(key=lambda m: abs(m[1] - len(answer_norm)))
        # Check if the closest is unambiguous
        diff0 = abs(matches[0][1] - len(answer_norm))
        diff1 = abs(matches[1][1] - len(answer_norm))
        if diff0 < diff1:
            best_idx = matches[0][0]
        else:
            return None

    opt = options[best_idx]
    return (getattr(opt, "label", "").upper(), best_idx + 1)


def _extract_answer_letter(response: str, options: Optional[list] = None) -> Optional[str]:
    """
    Extract the answer letter or number from an AI response.
    """
    if not response:
        return None

    num_to_letter = {
        "1": "A", "2": "B", "3": "C", "4": "D", "5": "E",
        "6": "F", "7": "G", "8": "H", "9": "I", "10": "J",
    }

    # Clean markdown formatting for reliable regex matching
    clean = re.sub(r"[\*_`#]", "", response).strip()

    valid_labels: set[str] = set()
    valid_numbers: set[str] = set()
    if options:
        for i, opt in enumerate(options):
            lbl = getattr(opt, "label", "").upper()
            if lbl:
                valid_labels.add(lbl)
            valid_numbers.add(str(i + 1))

    # Pattern for single option label (A-J, 1-10, with optional parens/brackets/prefix)
    label_re = re.compile(
        r"^(?:\((?:Option\s*)?([A-Ja-j]|10|[1-9])\)|\[(?:Option\s*)?([A-Ja-j]|10|[1-9])\]|(?:Option\s+)?([A-Ja-j]|10|[1-9]))[\)\]\.\s]*$",
        re.IGNORECASE,
    )

    def _is_valid_choice(cand: str) -> bool:
        """Check if candidate letter or number is within valid options."""
        if not options:
            return True
        c = cand.upper()
        if c in valid_labels:
            return True
        mapped = num_to_letter.get(c)
        if mapped and mapped in valid_labels:
            return True
        return False

    # Strategy 1: Explicit line or phrase with ANSWER / KEY
    m_ans = re.search(
        r"^\s*(?:ANSWER\s*KEY|ANSWER|KEY|CORRECT\s*ANSWER|CORRECT\s*OPTION|CORRECT\s*CHOICE)\s*[:=]\s*(.+)$",
        clean,
        re.MULTILINE | re.IGNORECASE,
    )
    if not m_ans:
        m_ans = re.search(
            r"\b(?:ANSWER\s*KEY|ANSWER|KEY|CORRECT\s*ANSWER|CORRECT\s*OPTION|CORRECT\s*CHOICE)\s*[:=]\s*(.+)$",
            clean,
            re.IGNORECASE,
        )
    if m_ans:
        ans_content = m_ans.group(1).strip()
        # 1. First check if ans_content is a single valid option label (e.g. B, 2, Option B)
        m_lbl = label_re.match(ans_content)
        if m_lbl:
            ans = (m_lbl.group(1) or m_lbl.group(2) or m_lbl.group(3)).upper()
            if _is_valid_choice(ans):
                return num_to_letter.get(ans, ans)

        # 2. If not a valid label, check if ans_content matches an option's text (e.g. [4, 6], "object", "10")
        if options:
            match = _match_answer_to_option(ans_content, options)
            if match:
                label, _ = match
                return num_to_letter.get(label, label)

    # Strategy 2: Scan lines in reverse order (Gemini puts conclusion at end)
    lines = [line.strip() for line in clean.split("\n") if line.strip()]
    for line in reversed(lines):
        # Match "correct answer/option is X" or "choice X"
        m = re.search(
            r"(?:correct\s+)?(?:answer|option|choice|key)\s*(?:is\s*)?[:=]?\s*(?:\((?:Option\s*)?([A-Ja-j]|10|[1-9])\)|\[(?:Option\s*)?([A-Ja-j]|10|[1-9])\]|(?:Option\s+)?([A-Ja-j]|10|[1-9]))(?!\s*[,\]])\b",
            line,
            re.IGNORECASE,
        )
        if not m:
            m = re.search(
                r"(?:option|choice)\s*[\(\[]?\s*([A-Ja-j]|10|[1-9])[\)\]]?\s+is\s+correct\b",
                line,
                re.IGNORECASE,
            )
        if m:
            ans = (m.group(1) or (m.group(2) if len(m.groups()) >= 2 else None) or (m.group(3) if len(m.groups()) >= 3 else None) or m.group(1)).upper()
            if _is_valid_choice(ans):
                return num_to_letter.get(ans, ans)

        # Standalone letter or number on its own line: e.g. "B", "2", "(B)", "[2]", "B.", "2)", "C)"
        m = label_re.match(line)
        if m:
            ans = (m.group(1) or m.group(2) or m.group(3)).upper()
            if _is_valid_choice(ans):
                return num_to_letter.get(ans, ans)

    # Strategy 3: Match against option text if options are provided
    # Use robust matching that avoids substring ambiguity
    if options:
        last_section = clean[-800:] if len(clean) > 800 else clean
        match = _match_answer_to_option(last_section, options)
        if match:
            label, _ = match
            res_lbl = num_to_letter.get(label, label)
            if _is_valid_choice(res_lbl):
                return res_lbl

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

    def _build_mcq_result(
        final_ans: str,
        val_status: ValidationStatus,
        st1_ans: str,
        st1_reason: str,
        st2_ans: Optional[str] = None,
        st2_reason: str = "",
    ) -> MultipleChoiceResult:
        opt_n = _resolve_option_num(final_ans)
        ans_t = None
        if opt_n and 1 <= opt_n <= len(parsed.options):
            ans_t = parsed.options[opt_n - 1].text

        return MultipleChoiceResult(
            question=parsed.question,
            options=parsed.options,
            selected_option=final_ans,
            validated_option_number=opt_n,
            validation_status=val_status,
            answer_text=ans_t,
            option_index=(opt_n - 1) if opt_n is not None else None,
            option_label=final_ans,
            explanation=st1_reason,
            mapping_status="validated" if val_status == ValidationStatus.VALIDATED else val_status.value,
            stage1_answer=st1_ans,
            stage1_reasoning=st1_reason,
            stage2_answer=st2_ans,
            stage2_reasoning=st2_reason,
        )

    stage2_response = client.generate(stage2_prompt, temperature=0.1)
    if not stage2_response:
        # Stage 2 failed but Stage 1 succeeded — return with SINGLE_STAGE status
        logger.warning("Stage 2 failed — returning Stage 1 result as single-stage")
        return _build_mcq_result(
            stage1_answer,
            ValidationStatus.SINGLE_STAGE,
            stage1_answer,
            stage1_response,
        )

    stage2_answer = _extract_answer_letter(stage2_response, parsed.options)
    if not stage2_answer:
        logger.warning("Stage 2 answer extraction failed — returning as single-stage")
        return _build_mcq_result(
            stage1_answer,
            ValidationStatus.SINGLE_STAGE,
            stage1_answer,
            stage1_response,
            None,
            stage2_response,
        )

    logger.info("Stage 2 complete: verification answer = %s", stage2_answer)

    # ── Cross Validation ──────────────────────────────────────────────────

    if stage1_answer == stage2_answer:
        # Both stages agree — VALIDATED
        validation_status = ValidationStatus.VALIDATED
        final_answer = stage1_answer
        logger.info("Cross-validation: VALIDATED (both stages agree on %s)", final_answer)
    else:
        # Stages disagree — CONFLICT
        validation_status = ValidationStatus.CONFLICT
        final_answer = stage1_answer  # Default to Stage 1
        logger.warning(
            "Cross-validation: CONFLICT (Stage 1=%s, Stage 2=%s). "
            "Defaulting to Stage 1.",
            stage1_answer, stage2_answer,
        )

    return _build_mcq_result(
        final_answer,
        validation_status,
        stage1_answer,
        stage1_response,
        stage2_answer,
        stage2_response,
    )
