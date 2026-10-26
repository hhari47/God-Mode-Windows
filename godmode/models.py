"""
Data models for parsed questions and results.

These dataclasses form the Typed Result Layer (Architecture Component 5)
and the ParsedQuestion structure from Normalization & Parsing (Component 2).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ─── Parsed Question Models (Component 2) ───────────────────────────────────


@dataclass
class Option:
    """A single MCQ option with its label and text."""
    label: str          # e.g., "A", "B", "1", "2"
    text: str           # The option content
    original_raw: str = ""  # Original unparsed text for diagnostics
    option_id: str = ""     # Unique identifier (defaults to label)
    original_label: str = ""  # Raw label before normalization (e.g. "1", "(A)")

    def __post_init__(self):
        if not self.option_id:
            self.option_id = self.label
        if not self.original_label:
            self.original_label = self.label

    def __str__(self) -> str:
        return f"{self.label}. {self.text}"


@dataclass
class ParsedQuestion:
    """
    Structured representation of a parsed question.

    Produced by MultipleChoiceProcessor (Component 2).
    Consumed by WorkflowRouter (Component 3).
    """
    question: str                          # The question stem
    options: list[Option] = field(default_factory=list)
    is_multiple_choice: bool = False       # True if valid MCQ detected
    raw_input: str = ""                    # Original raw text (for diagnostics only)
    parse_warnings: list[str] = field(default_factory=list)
    question_type: str = "multiple_choice" # "multiple_choice" or "general_text"
    extraction_confidence: float = 1.0     # 0.0 to 1.0
    source_reference: str = ""

    @property
    def option_count(self) -> int:
        return len(self.options)

    @property
    def is_valid_mcq(self) -> bool:
        """MCQ requires ≥2 options with clear labels and a question stem."""
        return (
            self.is_multiple_choice
            and self.option_count >= 2
            and bool(self.question.strip())
            and all(opt.label and opt.text.strip() for opt in self.options)
        )


# ─── Result Models (Component 5 — Typed Result Layer) ───────────────────────


class ValidationStatus(Enum):
    """Status of cross-validation between Gemini Stage 1 and Stage 2."""
    VALIDATED = "validated"         # Both stages agree
    CONFLICT = "conflict"           # Stages disagree
    SINGLE_STAGE = "single_stage"   # Only one stage completed
    FAILED = "failed"               # Validation could not complete


@dataclass
class MultipleChoiceResult:
    """Result from the two-stage MCQ pipeline (Component 4)."""
    selected_option: Optional[str] = None       # e.g., "B"
    validated_option_number: Optional[int] = None  # e.g., 2
    validation_status: ValidationStatus = ValidationStatus.FAILED

    # Structured internal result fields
    question: str = ""
    options: list[Option] = field(default_factory=list)
    answer_text: Optional[str] = None
    option_index: Optional[int] = None          # 0-based index or None
    option_label: Optional[str] = None          # e.g., "B" or None
    explanation: str = ""
    mapping_status: str = "unresolved"

    # Stage details for diagnostics
    stage1_answer: Optional[str] = None
    stage1_reasoning: str = ""
    stage2_answer: Optional[str] = None
    stage2_reasoning: str = ""

    @property
    def is_validated(self) -> bool:
        return self.validation_status == ValidationStatus.VALIDATED

    @property
    def blink_count(self) -> int:
        """Number of LED blinks. 0 means no signal (unvalidated)."""
        if self.is_validated and self.validated_option_number:
            return self.validated_option_number
        return 0


@dataclass
class GeneralTextResult:
    """Result from the single-stage general text pipeline (Component 4)."""
    response_text: str = ""
    character_count: int = 0

    def __post_init__(self):
        self.character_count = len(self.response_text)


class FailureStage(Enum):
    """Which pipeline stage failed."""
    CAPTURE = "capture"
    PARSING = "parsing"
    STAGE1_ANALYSIS = "stage1_analysis"
    STAGE2_VERIFICATION = "stage2_verification"
    VALIDATION = "validation"
    SIGNALING = "signaling"
    GENERAL_RESPONSE = "general_response"


@dataclass
class WorkflowFailure:
    """Structured error from any pipeline stage (Component 5)."""
    failure_stage: FailureStage
    failure_reason: str
    recovery_suggestion: str = ""
    exception: Optional[Exception] = None

    def __str__(self) -> str:
        msg = f"[{self.failure_stage.value}] {self.failure_reason}"
        if self.recovery_suggestion:
            msg += f"\n  Suggestion: {self.recovery_suggestion}"
        return msg


# ─── Workflow Result Union ───────────────────────────────────────────────────

@dataclass
class WorkflowResult:
    """
    Top-level result wrapper combining typed results with diagnostics.

    Exactly one of mcq_result, text_result, or failure will be set.
    """
    mcq_result: Optional[MultipleChoiceResult] = None
    text_result: Optional[GeneralTextResult] = None
    failure: Optional[WorkflowFailure] = None

    # Diagnostics
    workflow_type: str = ""          # "mcq" or "general_text"
    provider: str = "gemini"
    model_used: str = ""
    total_duration_ms: float = 0.0
    parsed_question: Optional[ParsedQuestion] = None
    diagnostics_summary: str = ""

    @property
    def is_success(self) -> bool:
        return self.failure is None

    @property
    def result_summary(self) -> str:
        if self.mcq_result:
            r = self.mcq_result
            opt_text = ""
            opt_num = r.validated_option_number
            if self.parsed_question and r.selected_option:
                for opt in self.parsed_question.options:
                    if opt.label.upper() == r.selected_option.upper():
                        opt_text = f": {opt.text}"
                        break
            if opt_num is None and r.selected_option:
                sel = r.selected_option.upper()
                if sel in "ABCDEFGHIJ":
                    opt_num = ord(sel) - ord("A") + 1
                elif sel.isdigit():
                    opt_num = int(sel)

            num_str = f" (Option {opt_num})" if opt_num else ""
            if r.is_validated:
                return f"Answer: {r.selected_option}{num_str}{opt_text} — Validated ✓"
            return f"Answer: {r.selected_option or 'Unknown'}{num_str}{opt_text} — {r.validation_status.value}"
        if self.text_result:
            preview = self.text_result.response_text[:100].replace("\n", " ")
            return f"Response ({self.text_result.character_count} chars): {preview}..."
        if self.failure:
            return str(self.failure)
        return "No result"
