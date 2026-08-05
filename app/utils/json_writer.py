"""JSON output writing, including safe cleanup of previously generated
case output files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Matches only files the pipeline itself generates (EC_<digits>.json), so
# cleanup never touches unrelated files a user may have placed in output/.
CASE_OUTPUT_FILENAME_RE = re.compile(r"^EC_\d+\.json$")


def write_json(path: Path | str, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def clean_case_outputs(output_dir: Path | str) -> list[str]:
    """Remove previously generated EC_*.json files so a fresh run never
    leaves behind stale output for a case that no longer exists in input.
    Returns the list of filenames removed."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    removed = []
    for entry in sorted(output_dir.iterdir()):
        if entry.is_file() and CASE_OUTPUT_FILENAME_RE.match(entry.name):
            entry.unlink()
            removed.append(entry.name)
    return removed
