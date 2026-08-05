"""Writes `logging/metadata.json` describing how the run was produced.

No model is called anywhere in this pipeline -- every agent is a
deterministic Python function over the Olist CSVs. That is recorded
explicitly here per README section 9.4.
"""

from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import DATA_FILES, FRAMEWORK_NAME, MODEL_NAME, MODEL_PARAMETER_SIZE


def build_metadata(data_dir: Path | str) -> dict:
    return {
        "model": MODEL_NAME,
        "parameter_size": MODEL_PARAMETER_SIZE,
        "framework": FRAMEWORK_NAME,
        "runtime": platform.platform(),
        "python_version": sys.version.split()[0],
        "data_files": sorted(DATA_FILES.values()),
        "data_dir": str(Path(data_dir)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
