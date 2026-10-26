"""
Single-Stage General Text Pipeline — Component 4 (General Text path).

Handles open-ended/descriptive questions that don't have MCQ options.
Uses a single Gemini call to generate a detailed response.
"""

import logging
from typing import Optional

from godmode.models import (
    ParsedQuestion,
    GeneralTextResult,
    WorkflowFailure,
    FailureStage,
)
from godmode.ai import GeminiClient

logger = logging.getLogger(__name__)

GENERAL_PROMPT = """You are an expert AI assistant.
Answer the following question clearly, accurately, and concisely.

Important instructions:
- If this is a multiple-choice question (even if unlabeled, dot-marked, or written line-by-line):
  1. Determine the correct choice.
  2. On the FIRST line, write ONLY: ANSWER: X
     where X is the option letter (A, B, C, D...) or number (1, 2, 3...) or option text.
  3. On subsequent lines, provide your explanation.
- If this is an open-ended/descriptive question:
  Provide a clear, accurate, and well-structured response.

Question: {question}"""


def run_general_pipeline(
    client: GeminiClient,
    parsed: ParsedQuestion,
) -> GeneralTextResult | WorkflowFailure:
    """
    Execute the single-stage general text pipeline.

    Sends the question to Gemini and returns the response as GeneralTextResult.

    Args:
        client: Configured GeminiClient.
        parsed: ParsedQuestion (general text, not MCQ).

    Returns:
        GeneralTextResult on success, WorkflowFailure on error.
    """
    if not client.is_ready:
        return WorkflowFailure(
            failure_stage=FailureStage.GENERAL_RESPONSE,
            failure_reason="Gemini client not configured",
            recovery_suggestion="Set GEMINI_API_KEY in .env file",
        )

    q_text = (
        parsed.raw_input.strip()
        if getattr(parsed, "raw_input", None) and parsed.raw_input.strip()
        else parsed.question
    )
    prompt = GENERAL_PROMPT.format(question=q_text)

    logger.info("General text pipeline: sending to Gemini")
    response = client.generate(prompt, temperature=0.3)

    if not response:
        error_msg = getattr(client, "last_error", None) or "Gemini returned no response for general question"
        suggestion = "Check API key and network connection, then retry"
        if "404" in error_msg or "not found" in error_msg.lower():
            suggestion = f"The model '{client.model_name}' may be deprecated or unavailable. Try updating GEMINI_MODEL (e.g. gemini-3.8-flash) in Settings or .env"
        elif "API_KEY_INVALID" in error_msg or "400" in error_msg:
            suggestion = "Your API key appears invalid. Check GEMINI_API_KEY in Settings or .env"

        return WorkflowFailure(
            failure_stage=FailureStage.GENERAL_RESPONSE,
            failure_reason=error_msg,
            recovery_suggestion=suggestion,
        )

    logger.info("General text pipeline: received %d char response", len(response))
    return GeneralTextResult(response_text=response)
