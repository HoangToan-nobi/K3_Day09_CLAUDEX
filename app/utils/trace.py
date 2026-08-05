"""Run trace logging.

Writes one JSON object per line to `logging/trace.jsonl`, one line per
agent event, so the handoff chain of a run can be reconstructed after the
fact. Each full pipeline run truncates the file first (`start()` opens in
write mode) -- the spec asks for the latest run's trace only, not an
ever-growing append log.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pandas as pd


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


class TraceLogger:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._fh = None

    def start(self) -> "TraceLogger":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "w", encoding="utf-8")
        return self

    def log(
        self,
        *,
        case_id: str,
        agent: str,
        event: str,
        input_summary: Optional[dict] = None,
        output_summary: Optional[dict] = None,
    ) -> None:
        if self._fh is None:
            raise RuntimeError("TraceLogger.start() must be called before log()")
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
            "agent": agent,
            "event": event,
            "input_summary": input_summary or {},
            "output_summary": output_summary or {},
        }
        self._fh.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "TraceLogger":
        return self.start()

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
