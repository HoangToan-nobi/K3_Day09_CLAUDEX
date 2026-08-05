"""CLI entry point.

    python -m app.main --input-dir input --output-dir output

Runs every `EC_*.json` case in --input-dir through the Coordinator, writes
one matching JSON file per case into --output-dir, rewrites
logging/trace.jsonl for this run, and writes logging/metadata.json.

Never fabricates output for a case it could not process: a failing case is
reported (stdout + trace) and skipped, the rest of the batch continues, and
the process exits non-zero if anything failed or if there was no input to
process at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.agents.coordinator import CoordinatorAgent
from app.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_INPUT_DIR,
    DEFAULT_LOGGING_DIR,
    DEFAULT_OUTPUT_DIR,
)
from app.data_loader import OlistDataStore
from app.schemas import CaseProcessingError
from app.utils.json_writer import clean_case_outputs, write_json
from app.utils.metadata_writer import build_metadata
from app.utils.trace import TraceLogger

CASE_FILE_GLOB = "EC_*.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the multi-agent e-commerce dispute resolution pipeline."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--logging-dir", type=Path, default=DEFAULT_LOGGING_DIR)
    return parser.parse_args(argv)


def discover_case_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.glob(CASE_FILE_GLOB))


def load_case_input(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.data_dir.exists():
        print(f"ERROR: data directory not found: {args.data_dir}", file=sys.stderr)
        return 2
    try:
        store = OlistDataStore.load(args.data_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: missing required Olist CSV file under {args.data_dir}: {exc}", file=sys.stderr)
        return 2

    if store.load_warnings:
        print(f"Data load warnings ({len(store.load_warnings)}):")
        for warning in store.load_warnings[:20]:
            print(f"  - {warning}")
        if len(store.load_warnings) > 20:
            print(f"  ... and {len(store.load_warnings) - 20} more")

    if not args.input_dir.exists():
        print(f"ERROR: input directory not found: {args.input_dir}", file=sys.stderr)
        return 2

    case_files = discover_case_files(args.input_dir)
    if not case_files:
        print(
            f"No input case files ('{CASE_FILE_GLOB}') found in {args.input_dir}.\n"
            "Run `python scripts/check_input.py` for a detailed report on what is "
            "missing. No output was written and no fake results were generated."
        )
        return 1

    removed = clean_case_outputs(args.output_dir)
    if removed:
        print(f"Removed {len(removed)} stale output file(s) from a previous run.")

    trace_path = args.logging_dir / "trace.jsonl"
    trace = TraceLogger(trace_path)
    trace.start()

    coordinator = CoordinatorAgent(store, trace)

    successes = 0
    failures: list[tuple[str, str]] = []

    try:
        for case_path in case_files:
            case_id_for_report = case_path.stem
            try:
                case_input = load_case_input(case_path)
            except (json.JSONDecodeError, OSError) as exc:
                message = f"could not read/parse {case_path.name}: {exc}"
                failures.append((case_id_for_report, message))
                trace.log(
                    case_id=case_id_for_report,
                    agent="coordinator",
                    event="case_failed",
                    input_summary={"file": case_path.name},
                    output_summary={"error": message},
                )
                print(f"FAIL {case_path.name}: {message}")
                continue

            if isinstance(case_input, dict) and case_input.get("case_id"):
                case_id_for_report = case_input["case_id"]

            try:
                output = coordinator.process_case(case_input)
            except CaseProcessingError as exc:
                message = str(exc)
                failures.append((case_id_for_report, message))
                trace.log(
                    case_id=case_id_for_report,
                    agent="coordinator",
                    event="case_failed",
                    output_summary={"error": message},
                )
                print(f"FAIL {case_id_for_report}: {message}")
                continue

            output_path = args.output_dir / f"{output['case_id']}.json"
            write_json(output_path, output)
            successes += 1
            print(
                f"OK   {output['case_id']} -> {output_path.name} "
                f"({output['assessment']['primary_issue']})"
            )
    finally:
        trace.close()

    metadata_path = args.logging_dir / "metadata.json"
    write_json(metadata_path, build_metadata(args.data_dir))

    total = len(case_files)
    print("-" * 60)
    print(f"Processed {total} case file(s): {successes} succeeded, {len(failures)} failed.")
    if failures:
        print("Failed cases:")
        for case_id, message in failures:
            print(f"  - {case_id}: {message}")
    print(f"Trace written to {trace_path}")
    print(f"Metadata written to {metadata_path}")

    return 0 if not failures else 1


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
