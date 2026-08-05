"""Delivery Agent.

Responsibility: compare actual delivery/handoff timestamps against the
committed dates. Produces a tri-state `delivered_late` (True / False /
None) rather than defaulting missing data to "on time" -- a null
`order_delivered_customer_date` or `order_estimated_delivery_date` means
the claim cannot be verified, not that it is false.
"""

from __future__ import annotations

from typing import Optional

from app.schemas import DeliveryResult, ItemRecord, OrderRecord


class DeliveryAgent:
    def analyze(
        self,
        order_id: str,
        order_record: Optional[OrderRecord],
        items: list[ItemRecord],
    ) -> DeliveryResult:
        warnings: list[str] = []

        if order_record is None:
            return DeliveryResult(
                order_id=order_id,
                delivered_late=None,
                late_seller_ids=[],
                on_time_seller_ids=[],
                warnings=[f"order {order_id} not found; cannot assess delivery"],
            )

        delivered_late = self._assess_delivered_late(order_record, warnings)
        late_seller_ids, on_time_seller_ids = self._assess_seller_handoff(
            order_record, items, warnings
        )

        return DeliveryResult(
            order_id=order_id,
            delivered_late=delivered_late,
            late_seller_ids=late_seller_ids,
            on_time_seller_ids=on_time_seller_ids,
            warnings=warnings,
        )

    @staticmethod
    def _assess_delivered_late(order_record: OrderRecord, warnings: list[str]) -> Optional[bool]:
        customer_date = order_record.order_delivered_customer_date
        estimated_date = order_record.order_estimated_delivery_date
        if customer_date is None or estimated_date is None:
            warnings.append(
                "delivered_late undetermined: order_delivered_customer_date or "
                "order_estimated_delivery_date is null"
            )
            return None
        return bool(customer_date > estimated_date)

    @staticmethod
    def _assess_seller_handoff(
        order_record: OrderRecord,
        items: list[ItemRecord],
        warnings: list[str],
    ) -> tuple[list[str], list[str]]:
        carrier_date = order_record.order_delivered_carrier_date
        late_sellers: set[str] = set()
        on_time_sellers: set[str] = set()

        for item in items:
            if not item.seller_id:
                continue
            if carrier_date is None or item.shipping_limit_date is None:
                warnings.append(
                    f"seller_handoff_late undetermined for item {item.item_id}: "
                    "order_delivered_carrier_date or shipping_limit_date is null"
                )
                continue
            if carrier_date > item.shipping_limit_date:
                late_sellers.add(item.seller_id)
            else:
                on_time_sellers.add(item.seller_id)

        # A seller that shows up both late (on one item) and on-time (on another)
        # is still considered late for that order per README: "seller bị coi là
        # bàn giao muộn nếu order_delivered_carrier_date > shipping_limit_date
        # của item thuộc seller đó" -- any offending item is enough.
        on_time_only = on_time_sellers - late_sellers
        return sorted(late_sellers), sorted(on_time_only)
