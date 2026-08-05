"""Tests for Order/Seller, Payment and Delivery agents against the
tests/fixtures/mini_olist mini dataset. These exercise real CSV parsing
(pandas.to_datetime coercion, Decimal money) instead of hand-built
PolicyInputs, covering: multi-seller orders, multi-payment orders, the
0.09/0.10/0.11 BRL reconciliation boundary, null timestamps, and the
exact-equality boundary for both delivery comparisons (`>` semantics).
"""

from __future__ import annotations

from decimal import Decimal

from app.agents.delivery_agent import DeliveryAgent
from app.agents.order_seller_agent import OrderSellerAgent
from app.agents.payment_agent import PaymentAgent


def test_order_seller_agent_unknown_order_reports_not_exists(mini_store):
    result = OrderSellerAgent(mini_store).analyze("DOES_NOT_EXIST")
    assert result.order_exists is False
    assert result.items == []
    assert result.item_total == Decimal("0")


def test_order_seller_agent_multi_seller_order_sorted_and_unique(mini_store):
    result = OrderSellerAgent(mini_store).analyze("ORD_LATE_SELLER")
    assert result.order_exists is True
    assert result.seller_ids == ["SELLER_A", "SELLER_B"]
    assert result.item_ids == ["ORD_LATE_SELLER:1", "ORD_LATE_SELLER:2"]
    assert result.item_total == Decimal("150.00")
    assert result.freight_total == Decimal("18.00")


def test_order_seller_agent_empty_items_gives_zero_totals(mini_store):
    result = OrderSellerAgent(mini_store).analyze("ORD_EMPTY_ITEMS")
    assert result.order_exists is True
    assert result.items == []
    assert result.seller_ids == []
    assert result.item_ids == []
    assert result.item_total == Decimal("0")
    assert result.freight_total == Decimal("0")
    assert any("no order_items" in w for w in result.warnings)


def test_payment_agent_multi_payment_row_sums_all_rows(mini_store):
    result = PaymentAgent(mini_store).analyze("ORD_SPLIT_PAYMENT", Decimal("90.00"), Decimal("10.00"))
    assert result.payment_row_count == 2
    assert result.payment_total == Decimal("100.00")
    assert result.payment_matches_order_total is True
    assert result.payment_ids == ["ORD_SPLIT_PAYMENT:1", "ORD_SPLIT_PAYMENT:2"]


def test_payment_agent_tolerance_boundary_within(mini_store):
    # payment_total - (item+freight) == 0.09 <= 0.10 tolerance -> matches
    result = PaymentAgent(mini_store).analyze("ORD_TOL_09", Decimal("90.00"), Decimal("10.00"))
    assert result.payment_total == Decimal("100.09")
    assert result.payment_matches_order_total is True


def test_payment_agent_tolerance_boundary_exact(mini_store):
    # diff == 0.10, tolerance is <= 0.10 so it must still match
    result = PaymentAgent(mini_store).analyze("ORD_TOL_10", Decimal("90.00"), Decimal("10.00"))
    assert result.payment_total == Decimal("100.10")
    assert result.payment_matches_order_total is True


def test_payment_agent_tolerance_boundary_exceeded(mini_store):
    # diff == 0.11 > 0.10 tolerance -> must not match
    result = PaymentAgent(mini_store).analyze("ORD_TOL_11", Decimal("90.00"), Decimal("10.00"))
    assert result.payment_total == Decimal("100.11")
    assert result.payment_matches_order_total is False


def test_payment_agent_no_payments_gives_zero_total_and_no_match(mini_store):
    result = PaymentAgent(mini_store).analyze("ORD_ZERO_PAYMENT", Decimal("30.00"), Decimal("5.00"))
    assert result.payment_row_count == 0
    assert result.payment_total == Decimal("0")
    assert result.payment_matches_order_total is False


def test_delivery_agent_null_customer_date_is_undetermined_not_on_time(mini_store):
    order = mini_store.get_order("ORD_NULL_TIMESTAMP")
    items = mini_store.get_items("ORD_NULL_TIMESTAMP")
    result = DeliveryAgent().analyze("ORD_NULL_TIMESTAMP", order, items)
    assert result.delivered_late is None
    assert any("undetermined" in w for w in result.warnings)


def test_delivery_agent_seller_late_only_flags_violating_seller(mini_store):
    order = mini_store.get_order("ORD_LATE_SELLER")
    items = mini_store.get_items("ORD_LATE_SELLER")
    result = DeliveryAgent().analyze("ORD_LATE_SELLER", order, items)
    assert result.delivered_late is True
    assert result.late_seller_ids == ["SELLER_A"]
    assert result.on_time_seller_ids == ["SELLER_B"]


def test_delivery_agent_no_seller_late_for_logistics_case(mini_store):
    order = mini_store.get_order("ORD_LATE_LOGISTICS")
    items = mini_store.get_items("ORD_LATE_LOGISTICS")
    result = DeliveryAgent().analyze("ORD_LATE_LOGISTICS", order, items)
    assert result.delivered_late is True
    assert result.late_seller_ids == []


def test_delivery_agent_equal_estimate_date_is_not_late(mini_store):
    """customer_date == estimated_date must NOT count as late: the README
    condition is strictly '>'."""
    order = mini_store.get_order("ORD_EQUAL_ESTIMATE")
    items = mini_store.get_items("ORD_EQUAL_ESTIMATE")
    result = DeliveryAgent().analyze("ORD_EQUAL_ESTIMATE", order, items)
    assert result.delivered_late is False


def test_delivery_agent_equal_shipping_limit_is_not_seller_late(mini_store):
    """carrier_date == shipping_limit_date must NOT count as seller late:
    the README condition is strictly '>'."""
    order = mini_store.get_order("ORD_EQUAL_LIMIT")
    items = mini_store.get_items("ORD_EQUAL_LIMIT")
    result = DeliveryAgent().analyze("ORD_EQUAL_LIMIT", order, items)
    assert result.delivered_late is True  # still late overall (customer_date > estimate)
    assert result.late_seller_ids == []  # but this seller met the exact boundary
