#!/usr/bin/env python3
"""Independent check: is input/ actually complete (EC_001..EC_050)?

This never fabricates missing input -- it only reports, in detail, which
of the 50 expected case files are present, missing, unreadable, or fail
basic schema checks (case_id, customer_request.claimed_order_id). Run it
before `python -m app.main` if you are unsure whether the official input
has been published yet.

Usage:
    python scripts/check_input.py [--input-dir input] [--expected-count 50]

Exit code is non-zero if the input directory is incomplete or invalid.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CASE_ID_PREFIX = "EC_"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check completeness of the input/ case files.")
    parser.add_argument("--input-dir", type=Path, default=Path("input"))
    parser.add_argument("--expected-count", type=int, default=50)
    return parser.parse_args(argv)


def expected_filenames(count: int) -> list[str]:
    return [f"{CASE_ID_PREFIX}{i:03d}.json" for i in range(1, count + 1)]


def check_case_file(path: Path) -> list[str]:
    """Returns a list of problems found with this one file (empty = OK)."""
    problems: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]
    except OSError as exc:
        return [f"could not read file: {exc}"]

    if not isinstance(data, dict):
        return ["top-level JSON value is not an object"]

    if not data.get("case_id"):
        problems.append("missing 'case_id'")
    elif data["case_id"] != path.stem:
        problems.append(f"case_id '{data['case_id']}' does not match filename '{path.stem}'")

    claimed_order_id = data.get("customer_request", {}).get("claimed_order_id") if isinstance(
        data.get("customer_request"), dict
    ) else None
    if not claimed_order_id:
        problems.append("missing 'customer_request.claimed_order_id'")

    return problems


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    expected = expected_filenames(args.expected_count)

    if not args.input_dir.exists():
        print(f"MISSING: input directory '{args.input_dir}' does not exist.")
        return 1

    present = {p.name for p in args.input_dir.glob("EC_*.json")}
    missing = [name for name in expected if name not in present]
    unexpected = sorted(present - set(expected))

    invalid: dict[str, list[str]] = {}
    for name in expected:
        path = args.input_dir / name
        if path.exists():
            problems = check_case_file(path)
            if problems:
                invalid[name] = problems

    print(f"Input directory: {args.input_dir}")
    print(f"Expected case files: {len(expected)} (EC_001.json .. EC_{args.expected_count:03d}.json)")
    print(f"Present: {len(present & set(expected))}/{len(expected)}")

    if missing:
        print(f"\nMISSING ({len(missing)}):")
        for name in missing:
            print(f"  - {name}")
    else:
        print("\nNo missing files.")

    if invalid:
        print(f"\nINVALID CONTENT ({len(invalid)}):")
        for name, problems in invalid.items():
            print(f"  - {name}: {'; '.join(problems)}")
    else:
        print("No schema problems found in present files.")

    if unexpected:
        print(f"\nUNEXPECTED FILES not in EC_001..EC_{args.expected_count:03d} range ({len(unexpected)}):")
        for name in unexpected:
            print(f"  - {name}")

    ok = not missing and not invalid
    print("\n" + ("INPUT COMPLETE AND VALID" if ok else "INPUT INCOMPLETE OR INVALID"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
