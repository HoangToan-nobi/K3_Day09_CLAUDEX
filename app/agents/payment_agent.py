"""Payment Agent.

Responsibility: reconcile payment rows against the item + freight totals
handed off by the Order/Seller Agent. Never re-derives item/freight totals
itself -- those are an input, not something this agent should recompute.
"""

from __future__ import annotations

from decimal import Decimal

from app.config import PAYMENT_ID_PREFIX, PAYMENT_RECONCILIATION_TOLERANCE
from app.data_loader import OlistDataStore
from app.schemas import PaymentResult


class PaymentAgent:
    def __init__(self, store: OlistDataStore):
        self.store = store

    def analyze(self, order_id: str, item_total: Decimal, freight_total: Decimal) -> PaymentResult:
        payments = self.store.get_payments(order_id)  # already sorted by payment_sequential
        warnings: list[str] = []
        if not payments:
            warnings.append(f"order {order_id} has no order_payments rows")

        payment_total = sum((payment.payment_value for payment in payments), Decimal("0"))
        payment_ids = [f"{PAYMENT_ID_PREFIX}{payment.payment_ref}" for payment in payments]

        expected_total = item_total + freight_total
        matches = abs(payment_total - expected_total) <= PAYMENT_RECONCILIATION_TOLERANCE

        return PaymentResult(
            order_id=order_id,
            payments=payments,
            payment_ids=payment_ids,
            payment_row_count=len(payments),
            payment_total=payment_total,
            payment_matches_order_total=matches,
            warnings=warnings,
        )
