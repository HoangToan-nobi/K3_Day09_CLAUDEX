#!/usr/bin/env python3
"""Independent output validator -- does NOT re-run the pipeline.

Reads every `output/EC_*.json` file as-is and re-checks it against the
Olist CSVs in `data/` (and, where available, the matching `input/EC_*.json`
case) using the same VerifierAgent the pipeline itself uses before
writing a file, plus a couple of submission-level checks (README section
8: output/ must contain exactly EC_001.json..EC_050.json, nothing else).

This is meant to be run on a clean checkout of `output/` -- e.g. right
before zipping it for submission -- to catch a stale or hand-edited file
the pipeline never actually produced.

Usage:
    python scripts/validate_outputs.py [--output-dir output] [--input-dir input] [--data-dir data]

Exit code is non-zero if any file is missing, malformed, or fails
verification.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.delivery_agent import DeliveryAgent  # noqa: E402
from app.agents.order_seller_agent import OrderSellerAgent  # noqa: E402
from app.agents.payment_agent import PaymentAgent  # noqa: E402
from app.agents.policy_agent import PolicyAgent  # noqa: E402
from app.agents.verifier_agent import VerifierAgent  # noqa: E402
from app.data_loader import OlistDataStore  # noqa: E402
from app.schemas import VerificationError  # noqa: E402

EXPECTED_COUNT = 50


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate output/*.json without re-running the pipeline.")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--input-dir", type=Path, default=Path("input"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--expected-count", type=int, default=EXPECTED_COUNT)
    return parser.parse_args(argv)


def recompute_agent_results(store: OlistDataStore, order_id: str):
    order_result = OrderSellerAgent(store).analyze(order_id)
    payment_result = PaymentAgent(store).analyze(order_id, order_result.item_total, order_result.freight_total)
    delivery_result = DeliveryAgent().analyze(order_id, order_result.order_record, order_result.items)
    policy_result = PolicyAgent().decide(order_result, payment_result, delivery_result)
    return order_result, payment_result, delivery_result, policy_result


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.data_dir.exists():
        print(f"ERROR: data directory not found: {args.data_dir}", file=sys.stderr)
        return 2
    store = OlistDataStore.load(args.data_dir)
    verifier = VerifierAgent(store)

    expected_names = [f"EC_{i:03d}.json" for i in range(1, args.expected_count + 1)]

    if not args.output_dir.exists():
        print(f"MISSING: output directory '{args.output_dir}' does not exist.")
        return 1

    present_files = sorted(args.output_dir.glob("*.json"))
    present_names = {p.name for p in present_files}

    missing = [name for name in expected_names if name not in present_names]
    unexpected = sorted(present_names - set(expected_names))

    failures: list[tuple[str, str]] = []
    successes = 0

    for name in expected_names:
        path = args.output_dir / name
        if not path.exists():
            continue  # already reported under `missing`

        try:
            output = load_json(path)
        except (json.JSONDecodeError, OSError) as exc:
            failures.append((name, f"could not read/parse: {exc}"))
            continue

        if not isinstance(output, dict) or "case_id" not in output:
            failures.append((name, "output is not a JSON object with a 'case_id'"))
            continue

        order_ids = output.get("affected_entities", {}).get("order_ids", [])
        if not order_ids:
            failures.append((name, "affected_entities.order_ids is empty; cannot re-derive expected values"))
            continue
        order_id = order_ids[0]

        input_path = args.input_dir / name
        if input_path.exists():
            try:
                case_input = load_json(input_path)
            except (json.JSONDecodeError, OSError) as exc:
                failures.append((name, f"matching input file exists but failed to parse: {exc}"))
                continue
        else:
            # No matching input on disk (e.g. validating a standalone
            # output/ folder) -- fall back to just checking case_id
            # consistency against the output itself.
            case_input = {"case_id": output.get("case_id")}

        try:
            order_result, payment_result, delivery_result, policy_result = recompute_agent_results(
                store, order_id
            )
            verifier.verify(case_input, output, order_result, payment_result, delivery_result, policy_result)
        except VerificationError as exc:
            failures.append((name, str(exc)))
            continue

        successes += 1

    print(f"Output directory: {args.output_dir}")
    print(f"Expected: {len(expected_names)} files (EC_001.json .. EC_{args.expected_count:03d}.json)")
    print(f"Verified OK: {successes}")
    print(f"Failed verification: {len(failures)}")
    print(f"Missing: {len(missing)}")
    print(f"Unexpected extra files: {len(unexpected)}")

    if missing:
        print("\nMISSING:")
        for name in missing:
            print(f"  - {name}")

    if unexpected:
        print("\nUNEXPECTED (not part of EC_001..EC_{:03d}, would break the submission zip):".format(
            args.expected_count
        ))
        for name in unexpected:
            print(f"  - {name}")

    if failures:
        print("\nFAILED:")
        for name, message in failures:
            print(f"  - {name}: {message}")

    ok = not missing and not unexpected and not failures and successes == len(expected_names)
    print("\n" + ("ALL OUTPUTS VALID" if ok else "VALIDATION FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
