"""Order & Seller Agent.

Responsibility: given an order_id, resolve the order record, its item
lines and the sellers involved. Computes item_total / freight_total from
the item rows. Deliberately does NOT look at payments or delivery
timestamps -- those belong to the Payment Agent and Delivery Agent, and
mixing them in here would blur the agent boundary the lab asks for.
"""

from __future__ import annotations

from decimal import Decimal

from app.data_loader import OlistDataStore
from app.schemas import OrderSellerResult


class OrderSellerAgent:
    def __init__(self, store: OlistDataStore):
        self.store = store

    def analyze(self, order_id: str) -> OrderSellerResult:
        order_record = self.store.get_order(order_id)
        if order_record is None:
            return OrderSellerResult(
                order_id=order_id,
                order_exists=False,
                order_record=None,
                items=[],
                seller_ids=[],
                item_ids=[],
                item_total=Decimal("0"),
                freight_total=Decimal("0"),
                warnings=[f"order_id {order_id!r} not found in orders dataset"],
            )

        items = self.store.get_items(order_id)  # already sorted by order_item_id
        warnings: list[str] = []
        if not items:
            warnings.append(f"order {order_id} has no order_items rows")

        item_total = sum((item.price for item in items), Decimal("0"))
        freight_total = sum((item.freight_value for item in items), Decimal("0"))

        seller_ids = sorted({item.seller_id for item in items if item.seller_id})
        item_ids = [item.item_id for item in items]

        return OrderSellerResult(
            order_id=order_id,
            order_exists=True,
            order_record=order_record,
            items=items,
            seller_ids=seller_ids,
            item_ids=item_ids,
            item_total=item_total,
            freight_total=freight_total,
            warnings=warnings,
        )
