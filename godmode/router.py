"""
Workflow Router — Component 3.

Classifies parsed questions and routes them to the appropriate execution pipeline:
- Valid MCQ (≥2 options, clear labels, reliable parsing) → Two-Stage Gemini Pipeline
- General Text (open-ended, insufficient options) → Single-Stage Gemini Pipeline
"""

import logging
from enum import Enum
from typing import Optional

from godmode.models import ParsedQuestion

logger = logging.getLogger(__name__)


class WorkflowType(Enum):
    """The two workflow paths from the architecture diagram."""
    MULTIPLE_CHOICE = "multiple_choice"
    GENERAL_TEXT = "general_text"


class RoutingDecision:
    """
    Encapsulates the routing decision with reasoning for diagnostics.
    """

    def __init__(
        self,
        workflow: WorkflowType,
        parsed_question: ParsedQuestion,
        reason: str,
        confidence: float = 1.0,
    ):
        self.workflow = workflow
        self.parsed_question = parsed_question
        self.reason = reason
        self.confidence = confidence  # 0.0–1.0

    def __repr__(self) -> str:
        return (
            f"RoutingDecision(workflow={self.workflow.value}, "
            f"reason='{self.reason}', confidence={self.confidence:.2f})"
        )


def route_question(parsed: ParsedQuestion) -> RoutingDecision:
    """
    Route a parsed question to the appropriate workflow.

    Decision criteria (from architecture diagram):
    - Multiple Choice: options.count ≥ 2, clear option labels, reliable parsing
    - General Text: open-ended questions, insufficient options

    Args:
        parsed: ParsedQuestion from the parser (Component 2).

    Returns:
        RoutingDecision indicating which pipeline to use.
    """
    # Check MCQ validity
    if parsed.is_valid_mcq:
        reason = (
            f"Valid MCQ: {parsed.option_count} options with clear labels, "
            f"question stem present ({len(parsed.question)} chars)"
        )
        confidence = 1.0

        # Slightly lower confidence if there were parse warnings
        if parsed.parse_warnings:
            confidence = 0.85
            reason += f" (with {len(parsed.parse_warnings)} parse warning(s))"

        logger.info("Routed to MCQ pipeline: %s", reason)
        return RoutingDecision(
            workflow=WorkflowType.MULTIPLE_CHOICE,
            parsed_question=parsed,
            reason=reason,
            confidence=confidence,
        )

    # Check if it was *almost* an MCQ (has some options but not enough)
    if parsed.options and not parsed.is_valid_mcq:
        reason = (
            f"Insufficient MCQ: {parsed.option_count} option(s) found "
            f"but requires ≥2 with clear labels. Routing to general text."
        )
        logger.info("Routed to general text pipeline: %s", reason)
        return RoutingDecision(
            workflow=WorkflowType.GENERAL_TEXT,
            parsed_question=parsed,
            reason=reason,
            confidence=0.7,
        )

    # Pure general text question
    if parsed.question.strip():
        reason = "Open-ended question with no MCQ options detected"
        logger.info("Routed to general text pipeline: %s", reason)
        return RoutingDecision(
            workflow=WorkflowType.GENERAL_TEXT,
            parsed_question=parsed,
            reason=reason,
            confidence=1.0,
        )

    # Edge case: empty or unparseable input
    reason = "Empty or unparseable input"
    logger.warning("Routing failed: %s", reason)
    return RoutingDecision(
        workflow=WorkflowType.GENERAL_TEXT,
        parsed_question=parsed,
        reason=reason,
        confidence=0.0,
    )
