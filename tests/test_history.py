"""
Unit tests for HistoryManager.
"""

import tempfile
from pathlib import Path
import pytest

from godmode.history import HistoryManager, HistoryEntry
from godmode.models import (
    WorkflowResult,
    ParsedQuestion,
    Option,
    MultipleChoiceResult,
    ValidationStatus,
    WorkflowFailure,
    FailureStage,
)


def test_history_empty_and_stats():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(tmpdir) / "test_history.json"
        mgr = HistoryManager(storage_path=storage)

        stats = mgr.get_statistics()
        assert stats["total_queries"] == 0
        assert stats["validation_rate_pct"] == 0.0
        assert mgr.get_entries() == []


def test_history_add_and_retrieve():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(tmpdir) / "test_history.json"
        mgr = HistoryManager(storage_path=storage)

        pq = ParsedQuestion(
            question="What is the capital of France?",
            options=[
                Option(label="A", text="London"),
                Option(label="B", text="Paris"),
            ],
            is_multiple_choice=True,
        )
        mcq_res = MultipleChoiceResult(
            selected_option="B",
            validated_option_number=2,
            validation_status=ValidationStatus.VALIDATED,
            answer_text="Paris",
        )
        wf_res = WorkflowResult(
            workflow_type="multiple_choice",
            provider="gemini",
            model_used="gemini-3.5-flash-lite",
            total_duration_ms=450.0,
            parsed_question=pq,
            mcq_result=mcq_res,
        )

        entry = mgr.add_result(wf_res)
        assert entry.selected_option == "B"
        assert entry.option_number == 2
        assert entry.blink_count == 2
        assert entry.is_success is True

        entries = mgr.get_entries()
        assert len(entries) == 1
        assert entries[0].id == entry.id
        assert entries[0].question_text == "What is the capital of France?"

        # Persistence check: reload from disk
        mgr2 = HistoryManager(storage_path=storage)
        entries2 = mgr2.get_entries()
        assert len(entries2) == 1
        assert entries2[0].selected_option == "B"


def test_history_search_and_filters():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(tmpdir) / "test_history.json"
        mgr = HistoryManager(storage_path=storage)

        # 1. Success MCQ
        r1 = WorkflowResult(
            workflow_type="multiple_choice",
            provider="gemini",
            model_used="gemini-flash",
            total_duration_ms=200.0,
            parsed_question=ParsedQuestion(question="Python list comprehension?", is_multiple_choice=True),
            mcq_result=MultipleChoiceResult(selected_option="A", validation_status=ValidationStatus.VALIDATED),
        )
        # 2. Failed General
        r2 = WorkflowResult(
            workflow_type="general_text",
            provider="grok",
            model_used="grok-2",
            total_duration_ms=500.0,
            parsed_question=ParsedQuestion(question="Explain quantum mechanics", is_multiple_choice=False),
            failure=WorkflowFailure(failure_stage=FailureStage.STAGE1_ANALYSIS, failure_reason="Rate limit exceeded"),
        )

        mgr.add_result(r1)
        mgr.add_result(r2)

        assert len(mgr.get_entries(filter_type="all")) == 2
        assert len(mgr.get_entries(filter_type="mcq")) == 1
        assert len(mgr.get_entries(filter_type="general")) == 1
        assert len(mgr.get_entries(filter_type="errors")) == 1
        assert len(mgr.get_entries(search_query="Python")) == 1
        assert len(mgr.get_entries(search_query="quantum")) == 1
        assert len(mgr.get_entries(search_query="nonexistent")) == 0


def test_history_export_and_clear():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = Path(tmpdir) / "test_history.json"
        mgr = HistoryManager(storage_path=storage)

        r = WorkflowResult(
            workflow_type="multiple_choice",
            provider="gemini",
            model_used="gemini-flash",
            total_duration_ms=300.0,
            parsed_question=ParsedQuestion(question="Sample query", is_multiple_choice=True),
            mcq_result=MultipleChoiceResult(selected_option="C", validation_status=ValidationStatus.VALIDATED),
        )
        mgr.add_result(r)

        json_out = Path(tmpdir) / "export.json"
        md_out = Path(tmpdir) / "export.md"

        assert mgr.export_to_json(json_out) is True
        assert json_out.exists()

        assert mgr.export_to_markdown(md_out) is True
        assert md_out.exists()
        assert "Sample query" in md_out.read_text(encoding="utf-8")

        mgr.clear()
        assert len(mgr.get_entries()) == 0
