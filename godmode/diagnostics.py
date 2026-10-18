"""
Pipeline Diagnostics Tracker — Component 9.

Tracks each stage of the pipeline with timestamps, status, and details.
Provides structured diagnostic output for the Result Presentation UI.

Diagnostic checkpoints (from architecture):
  Capture → Parsing → Stage 1 → Stage 2 → Validation → Signaling
"""

import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class DiagnosticEntry:
    """A single diagnostic checkpoint."""
    stage: str
    status: StageStatus = StageStatus.PENDING
    message: str = ""
    duration_ms: float = 0.0
    start_time: float = 0.0

    @property
    def status_icon(self) -> str:
        icons = {
            StageStatus.PENDING: "⏳",
            StageStatus.RUNNING: "🔄",
            StageStatus.SUCCESS: "✅",
            StageStatus.WARNING: "⚠️",
            StageStatus.FAILED: "❌",
            StageStatus.SKIPPED: "⏭️",
        }
        return icons.get(self.status, "❓")


@dataclass
class DiagnosticTracker:
    """
    Tracks pipeline execution diagnostics across all stages.

    Usage:
        tracker = DiagnosticTracker()
        tracker.start("Capture")
        # ... do work ...
        tracker.complete("Capture", "Captured 150 chars via clipboard")
    """
    entries: dict[str, DiagnosticEntry] = field(default_factory=dict)
    pipeline_start: float = 0.0
    pipeline_end: float = 0.0

    # Stage definitions matching the architecture
    STAGES = [
        "Capture",
        "Parsing",
        "Routing",
        "Stage 1 (Analysis)",
        "Stage 2 (Verification)",
        "Validation",
        "Signaling",
    ]

    def __post_init__(self):
        # Pre-create all stage entries
        for stage in self.STAGES:
            self.entries[stage] = DiagnosticEntry(stage=stage)

    def start_pipeline(self) -> None:
        """Mark the start of the pipeline."""
        self.pipeline_start = time.time()

    def start(self, stage: str) -> None:
        """Mark a stage as running."""
        if stage not in self.entries:
            self.entries[stage] = DiagnosticEntry(stage=stage)

        entry = self.entries[stage]
        entry.status = StageStatus.RUNNING
        entry.start_time = time.time()
        logger.debug("Stage '%s' started", stage)

    def complete(self, stage: str, message: str = "") -> None:
        """Mark a stage as successfully completed."""
        if stage in self.entries:
            entry = self.entries[stage]
            entry.status = StageStatus.SUCCESS
            entry.message = message
            if entry.start_time:
                entry.duration_ms = (time.time() - entry.start_time) * 1000
            logger.debug(
                "Stage '%s' complete (%.1fms): %s",
                stage, entry.duration_ms, message,
            )

    def warn(self, stage: str, message: str = "") -> None:
        """Mark a stage with a warning."""
        if stage in self.entries:
            entry = self.entries[stage]
            entry.status = StageStatus.WARNING
            entry.message = message
            if entry.start_time:
                entry.duration_ms = (time.time() - entry.start_time) * 1000
            logger.warning("Stage '%s' warning: %s", stage, message)

    def fail(self, stage: str, message: str = "") -> None:
        """Mark a stage as failed."""
        if stage in self.entries:
            entry = self.entries[stage]
            entry.status = StageStatus.FAILED
            entry.message = message
            if entry.start_time:
                entry.duration_ms = (time.time() - entry.start_time) * 1000
            logger.error("Stage '%s' failed: %s", stage, message)

    def skip(self, stage: str, message: str = "") -> None:
        """Mark a stage as skipped."""
        if stage in self.entries:
            entry = self.entries[stage]
            entry.status = StageStatus.SKIPPED
            entry.message = message
            logger.debug("Stage '%s' skipped: %s", stage, message)

    def finish_pipeline(self) -> None:
        """Mark the pipeline as complete."""
        self.pipeline_end = time.time()

    @property
    def total_duration_ms(self) -> float:
        """Total pipeline duration in milliseconds."""
        if self.pipeline_start and self.pipeline_end:
            return (self.pipeline_end - self.pipeline_start) * 1000
        return 0.0

    @property
    def has_failures(self) -> bool:
        return any(e.status == StageStatus.FAILED for e in self.entries.values())

    @property
    def summary(self) -> str:
        """Formatted diagnostic summary for display."""
        lines = ["─── Pipeline Diagnostics ───"]
        for stage in self.STAGES:
            entry = self.entries.get(stage)
            if entry:
                duration = f" ({entry.duration_ms:.0f}ms)" if entry.duration_ms else ""
                msg = f" — {entry.message}" if entry.message else ""
                lines.append(f"  {entry.status_icon} {entry.stage}{duration}{msg}")
        lines.append(f"  ⏱ Total: {self.total_duration_ms:.0f}ms")
        return "\n".join(lines)
