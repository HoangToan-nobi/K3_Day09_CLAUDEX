"""Decimal money helpers.

Sums are kept as `Decimal` all the way through the pipeline; rounding to
2 decimal places happens exactly once, at the output boundary.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")


def round_money(value: Decimal) -> float:
    quantized = value.quantize(CENTS, rounding=ROUND_HALF_UP)
    return float(quantized)
