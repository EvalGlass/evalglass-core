"""Shared helper: write a recorded async-trace file for the async-observation lane tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_async_recording(
    tmp_path: Path, spans: list[dict[str, Any]], *, name: str = "rec.json"
) -> str:
    """Write ``{"spans": [...]}`` to ``tmp_path/name`` and return the relative recording path."""
    (tmp_path / name).write_text(json.dumps({"spans": spans}), encoding="utf-8")
    return name
