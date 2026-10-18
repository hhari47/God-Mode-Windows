"""Unit tests for the Workflow Router (Component 3)."""

import pytest
from godmode.models import ParsedQuestion, Option
from godmode.router import route_question, WorkflowType


class TestWorkflowRouter:
    """Tests for routing decisions between Multiple Choice and General Text."""

    def test_routes_valid_mcq_to_multiple_choice(self):
        pq = ParsedQuestion(
            question="What is the capital of France?",
            options=[
                Option(label="A", text="Berlin"),
                Option(label="B", text="Paris"),
                Option(label="C", text="Madrid"),
                Option(label="D", text="Rome"),
            ],
            is_multiple_choice=True,
        )
        decision = route_question(pq)
        assert decision.workflow == WorkflowType.MULTIPLE_CHOICE
        assert decision.confidence == 1.0
        assert "Valid MCQ" in decision.reason

    def test_routes_two_options_mcq(self):
        pq = ParsedQuestion(
            question="Is Python dynamically typed?",
            options=[
                Option(label="A", text="Yes"),
                Option(label="B", text="No"),
            ],
            is_multiple_choice=True,
        )
        decision = route_question(pq)
        assert decision.workflow == WorkflowType.MULTIPLE_CHOICE
        assert decision.confidence == 1.0

    def test_routes_open_ended_question_to_general_text(self):
        pq = ParsedQuestion(
            question="Explain the difference between TCP and UDP in detail.",
            options=[],
            is_multiple_choice=False,
        )
        decision = route_question(pq)
        assert decision.workflow == WorkflowType.GENERAL_TEXT
        assert decision.confidence == 1.0
        assert "Open-ended question" in decision.reason

    def test_routes_single_option_to_general_text(self):
        pq = ParsedQuestion(
            question="Incomplete question?",
            options=[Option(label="A", text="Only one choice")],
            is_multiple_choice=False,
        )
        decision = route_question(pq)
        assert decision.workflow == WorkflowType.GENERAL_TEXT
        assert decision.confidence == 0.7
        assert "Insufficient MCQ" in decision.reason

    def test_routes_empty_question_with_zero_confidence(self):
        pq = ParsedQuestion(
            question="",
            options=[],
            is_multiple_choice=False,
        )
        decision = route_question(pq)
        assert decision.workflow == WorkflowType.GENERAL_TEXT
        assert decision.confidence == 0.0
