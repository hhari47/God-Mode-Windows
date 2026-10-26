"""
History & Activity Tracking Manager for GodMode.

Maintains a persistent, privacy-preserving query log of processed questions,
AI answers, validation statuses, and Caps Lock blink counts.

All data is stored locally on the user's machine (never uploaded).
Sensitive API keys are NEVER logged.
"""

from __future__ import annotations
import os
import json
import time
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional, List, Dict, Any

from godmode.models import WorkflowResult, ValidationStatus

logger = logging.getLogger(__name__)


@dataclass
class HistoryEntry:
    """A single record of a processed question."""
    id: str
    timestamp: str                     # ISO-formatted or human-readable
    created_at: float                  # Epoch timestamp for sorting
    question_text: str
    question_type: str                 # "multiple_choice" or "general_text"
    options_count: int = 0
    selected_option: Optional[str] = None
    option_number: Optional[int] = None
    answer_text: Optional[str] = None
    validation_status: str = "failed"
    blink_count: int = 0
    provider: str = "gemini"
    model: str = ""
    duration_ms: float = 0.0
    is_success: bool = False
    failure_stage: Optional[str] = None
    failure_reason: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HistoryEntry":
        # Handle backward compatibility if keys are missing
        valid_fields = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


class HistoryManager:
    """
    Manages local history persistence, search, filtering, and export.
    Thread-safe and bounds storage to prevent excessive disk/memory usage.
    """

    DEFAULT_MAX_ENTRIES = 100

    def __init__(self, storage_path: Optional[Path | str] = None, max_entries: int = DEFAULT_MAX_ENTRIES):
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: List[HistoryEntry] = []

        if storage_path:
            self.storage_file = Path(storage_path)
        else:
            self.storage_file = self._resolve_default_storage_path()

        self._load()

    def _resolve_default_storage_path(self) -> Path:
        """Resolve persistent storage path in user's AppData or project directory."""
        appdata = os.getenv("APPDATA")
        if appdata:
            dir_path = Path(appdata) / "GodMode"
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                return dir_path / "history.json"
            except Exception as e:
                logger.warning("Could not create AppData/GodMode directory: %s", e)

        # Fallback to project root directory
        return Path(__file__).parent.parent / "godmode_history.json"

    def _load(self) -> None:
        """Load history entries from disk."""
        with self._lock:
            if not self.storage_file.exists():
                self._entries = []
                return

            try:
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._entries = [
                            HistoryEntry.from_dict(item) for item in data if isinstance(item, dict)
                        ]
                        # Sort newest first
                        self._entries.sort(key=lambda e: e.created_at, reverse=True)
                        if len(self._entries) > self.max_entries:
                            self._entries = self._entries[:self.max_entries]
            except Exception as e:
                logger.warning("Failed to load history from %s: %s", self.storage_file, e)
                self._entries = []

    def _save(self) -> None:
        """Persist history entries to disk."""
        try:
            self.storage_file.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(entry) for entry in self._entries]
            temp_file = self.storage_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.storage_file)
        except Exception as e:
            logger.error("Failed to save history to %s: %s", self.storage_file, e)

    def add_result(self, result: WorkflowResult) -> HistoryEntry:
        """
        Create and record a history entry from a WorkflowResult.
        Thread-safe and auto-saves to disk.
        """
        now = time.time()
        dt_str = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
        entry_id = f"solv_{int(now * 1000)}"

        question_text = ""
        q_type = result.workflow_type or "unknown"
        opt_count = 0
        if result.parsed_question:
            question_text = result.parsed_question.question
            opt_count = result.parsed_question.option_count
            if result.parsed_question.is_multiple_choice:
                q_type = "multiple_choice"

        selected_opt = None
        opt_num = None
        ans_text = None
        val_status = "failed"
        blink_cnt = 0

        if result.mcq_result:
            r = result.mcq_result
            selected_opt = r.selected_option
            opt_num = r.validated_option_number
            ans_text = r.answer_text
            val_status = r.validation_status.value if hasattr(r.validation_status, "value") else str(r.validation_status)
            blink_cnt = r.blink_count
        elif result.text_result:
            ans_text = result.text_result.response_text[:300]
            val_status = "completed"

        fail_stage = None
        fail_reason = None
        if result.failure:
            fail_stage = result.failure.failure_stage.value if hasattr(result.failure.failure_stage, "value") else str(result.failure.failure_stage)
            fail_reason = result.failure.failure_reason

        entry = HistoryEntry(
            id=entry_id,
            timestamp=dt_str,
            created_at=now,
            question_text=question_text or (result.parsed_question.raw_input[:100] if result.parsed_question else ""),
            question_type=q_type,
            options_count=opt_count,
            selected_option=selected_opt,
            option_number=opt_num,
            answer_text=ans_text,
            validation_status=val_status,
            blink_count=blink_cnt,
            provider=result.provider or "gemini",
            model=result.model_used or "",
            duration_ms=round(result.total_duration_ms, 1),
            is_success=result.is_success,
            failure_stage=fail_stage,
            failure_reason=fail_reason,
        )

        with self._lock:
            self._entries.insert(0, entry)
            if len(self._entries) > self.max_entries:
                self._entries = self._entries[:self.max_entries]
            self._save()

        return entry

    def get_entries(
        self,
        limit: int = 50,
        filter_type: str = "all",
        search_query: str = "",
    ) -> List[HistoryEntry]:
        """
        Retrieve filtered and searched history entries.

        Args:
            limit: Maximum entries to return.
            filter_type: "all", "mcq", "general", "validated", or "errors".
            search_query: Optional case-insensitive text match in question/answer.
        """
        with self._lock:
            entries = list(self._entries)

        filtered = []
        q = search_query.strip().lower()

        for e in entries:
            # Filter type check
            if filter_type == "mcq" and e.question_type != "multiple_choice":
                continue
            elif filter_type == "general" and e.question_type == "multiple_choice":
                continue
            elif filter_type == "validated" and e.validation_status != "validated":
                continue
            elif filter_type == "errors" and e.is_success:
                continue

            # Search query check
            if q:
                match_question = q in e.question_text.lower()
                match_answer = e.answer_text and q in e.answer_text.lower()
                match_provider = q in e.provider.lower() or q in e.model.lower()
                if not (match_question or match_answer or match_provider):
                    continue

            filtered.append(e)

        return filtered[:limit]

    def get_entry_by_id(self, entry_id: str) -> Optional[HistoryEntry]:
        """Find an entry by its unique ID."""
        with self._lock:
            for e in self._entries:
                if e.id == entry_id:
                    return e
        return None

    def clear(self) -> None:
        """Clear all history entries and wipe disk file."""
        with self._lock:
            self._entries.clear()
            self._save()

    def get_statistics(self) -> Dict[str, Any]:
        """Compute aggregate statistics for the dashboard."""
        with self._lock:
            entries = list(self._entries)

        total = len(entries)
        if total == 0:
            return {
                "total_queries": 0,
                "mcq_count": 0,
                "general_count": 0,
                "validated_count": 0,
                "validation_rate_pct": 0.0,
                "avg_duration_ms": 0.0,
                "last_active": "No queries yet",
            }

        mcq_count = sum(1 for e in entries if e.question_type == "multiple_choice")
        general_count = total - mcq_count
        validated_count = sum(1 for e in entries if e.validation_status == "validated")
        val_rate = round((validated_count / mcq_count * 100), 1) if mcq_count > 0 else 100.0
        avg_dur = round(sum(e.duration_ms for e in entries) / total, 1)

        return {
            "total_queries": total,
            "mcq_count": mcq_count,
            "general_count": general_count,
            "validated_count": validated_count,
            "validation_rate_pct": val_rate,
            "avg_duration_ms": avg_dur,
            "last_active": entries[0].timestamp if entries else "None",
        }

    def export_to_json(self, filepath: Path | str) -> bool:
        """Export history entries to an external JSON file."""
        try:
            with self._lock:
                data = [asdict(entry) for entry in self._entries]
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error("Failed to export history to JSON: %s", e)
            return False

    def export_to_markdown(self, filepath: Path | str) -> bool:
        """Export history entries as a formatted Markdown report."""
        try:
            with self._lock:
                entries = list(self._entries)
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)

            lines = [
                "# GodMode Solved Questions Report",
                f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"Total Entries: {len(entries)}",
                "",
                "---",
                "",
            ]

            for i, e in enumerate(entries, 1):
                status_icon = "✅" if e.is_success else "❌"
                lines.extend([
                    f"## {i}. {status_icon} {e.timestamp} — {e.question_type.upper()}",
                    f"**Question:** {e.question_text}",
                    f"- **Provider:** {e.provider.title()} ({e.model})",
                    f"- **Latency:** {e.duration_ms}ms",
                    f"- **Validation:** {e.validation_status.title()}",
                ])
                if e.selected_option:
                    lines.append(f"- **Answer:** Option {e.option_number or e.selected_option} ({e.selected_option})")
                if e.answer_text:
                    lines.append(f"- **Answer Detail:** {e.answer_text}")
                if e.blink_count:
                    lines.append(f"- **Caps Lock Blinks:** {e.blink_count}")
                if e.failure_reason:
                    lines.append(f"- **Error:** {e.failure_reason}")
                lines.append("")

            with open(p, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return True
        except Exception as e:
            logger.error("Failed to export history to Markdown: %s", e)
            return False
