"""Persistent workflow state for resumable runs.

State file lives at data/state/workflow_state.json. Each step writes a small
record when it finishes so re-running the orchestrator skips finished work.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import CONFIG

_STEPS = (
    "browser_opened",
    "logged_in",
    "navigated_to_search",
    "form_filled",
    "search_submitted",
    "table_extracted",
    "csv_exported",
)


@dataclass
class State:
    completed: dict[str, bool] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    search_params: dict[str, Any] = field(default_factory=dict)

    def mark(self, step: str) -> None:
        self.completed[step] = True
        self.save()

    def is_done(self, step: str) -> bool:
        return bool(self.completed.get(step))

    def record(self, key: str, value: str) -> None:
        self.artifacts[key] = value
        self.save()

    def save(self) -> None:
        CONFIG.paths.state_file.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "State":
        if not CONFIG.paths.state_file.exists():
            return cls()
        try:
            data = json.loads(CONFIG.paths.state_file.read_text())
        except Exception:
            return cls()
        return cls(
            completed=data.get("completed", {}),
            artifacts=data.get("artifacts", {}),
            search_params=data.get("search_params", {}),
        )

    def reset(self) -> None:
        self.completed.clear()
        self.artifacts.clear()
        self.save()

    def status(self) -> str:
        return ", ".join(s for s in _STEPS if self.completed.get(s)) or "(nothing yet)"
