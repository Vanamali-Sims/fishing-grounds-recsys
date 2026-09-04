"""Persist ingest/clean run metrics (row counts, repairs, peak RSS)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.paths import REPORTS_DIR


def write_report(payload: dict[str, Any], path: Path | None = None) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = path or (REPORTS_DIR / "a1_pipeline.json")
    dest.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return dest


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
