"""Unit tests for the pure policy rule chain in app/agents/policy_agent.py.

These tests never touch the filesystem or the Olist CSVs: PolicyInputs is
built by hand for each scenario, so the rule chain's own correctness is
verified independently of data loading, and each rule can be pinned down
in isolation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agents.policy_agent import (
    PolicyInputs,
    evaluate_policy,
    rule_canceled_order_paid,
    rule_late_delivery_logistics,
    rule_late_delivery_seller,
    rule_unavailable_order_paid,
    rule_unsupported_late_claim,
    rule_valid_split_payment,
)
from app.schemas import (
    CAUSE_CODE_CARRIER_DELIVERED_AFTER_ESTIMATE,
    CAUSE_CODE_DELIVERY_WITHIN_ESTIMATE,
    CAUSE_CODE_MULTIPLE_PAYMENTS_RECONCILED,
    CAUSE_CODE_ORDER_CANCELED_AFTER_PAYMENT,
    CAUSE_CODE_ORDER_UNAVAILABLE_AFTER_PAYMENT,
    CAUSE_CODE_SELLER_HANDOFF_AFTER_LIMIT,
    PRIMARY_ISSUE_CANCELED_ORDER_PAID,
    PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS,
    PRIMARY_ISSUE_LATE_DELIVERY_SELLER,
    PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID,
    PRIMARY_ISSUE_UNCLASSIFIED,
    PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM,
    PRIMARY_ISSUE_VALID_SPLIT_PAYMENT,
)


def make_inputs(**overrides) -> PolicyInputs:
    base = dict(
        order_status="delivered",
        payment_total=Decimal("0"),
        item_total=Decimal("0"),
        freight_total=Decimal("0"),
        payment_row_count=0,
        payment_matches_order_total=False,
        delivered_late=None,
        late_seller_ids=(),
    )
    base.update(overrides)
    return PolicyInputs(**base)


# -- Rule 1: canceled_order_paid -------------------------------------------


def test_canceled_order_paid_fires_when_paid():
    inputs = make_inputs(order_status="canceled", payment_total=Decimal("50.00"))
    outcome = rule_canceled_order_paid(inputs)
    assert outcome is not None
    assert outcome.primary_issue == PRIMARY_ISSUE_CANCELED_ORDER_PAID
    assert outcome.cause_code == CAUSE_CODE_ORDER_CANCELED_AFTER_PAYMENT
    assert outcome.recommended_refund == Decimal("50.00")


def test_canceled_order_not_paid_does_not_fire():
    inputs = make_inputs(order_status="canceled", payment_total=Decimal("0"))
    assert rule_canceled_order_paid(inputs) is None


def test_canceled_status_but_not_canceled_word_does_not_fire():
    inputs = make_inputs(order_status="delivered", payment_total=Decimal("50.00"))
    assert rule_canceled_order_paid(inputs) is None


# -- Rule 2: unavailable_order_paid -----------------------------------------


def test_unavailable_order_paid_fires_when_paid():
    inputs = make_inputs(order_status="unavailable", payment_total=Decimal("80.00"))
    outcome = rule_unavailable_order_paid(inputs)
    assert outcome is not None
    assert outcome.primary_issue == PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID
    assert outcome.cause_code == CAUSE_CODE_ORDER_UNAVAILABLE_AFTER_PAYMENT
    assert outcome.recommended_refund == Decimal("80.00")


def test_unavailable_order_not_paid_does_not_fire():
    inputs = make_inputs(order_status="unavailable", payment_total=Decimal("0"))
    assert rule_unavailable_order_paid(inputs) is None


# -- Rule 3: late_delivery_seller -------------------------------------------


def test_late_delivery_seller_fires_with_violating_seller():
    inputs = make_inputs(
        delivered_late=True,
        late_seller_ids=("SELLER_A",),
        freight_total=Decimal("18.00"),
    )
    outcome = rule_late_delivery_seller(inputs)
    assert outcome is not None
    assert outcome.primary_issue == PRIMARY_ISSUE_LATE_DELIVERY_SELLER
    assert outcome.cause_code == CAUSE_CODE_SELLER_HANDOFF_AFTER_LIMIT
    assert outcome.recommended_refund == Decimal("18.00")
    assert [p.party_id for p in outcome.responsible_parties] == ["SELLER_A"]


def test_late_delivery_seller_supports_multiple_sellers():
    inputs = make_inputs(delivered_late=True, late_seller_ids=("SELLER_A", "SELLER_B"))
    outcome = rule_late_delivery_seller(inputs)
    assert outcome is not None
    assert [p.party_id for p in outcome.responsible_parties] == ["SELLER_A", "SELLER_B"]


def test_late_delivery_seller_does_not_fire_when_not_late():
    inputs = make_inputs(delivered_late=False, late_seller_ids=("SELLER_A",))
    assert rule_late_delivery_seller(inputs) is None


def test_late_delivery_seller_does_not_fire_when_unknown():
    inputs = make_inputs(delivered_late=None, late_seller_ids=("SELLER_A",))
    assert rule_late_delivery_seller(inputs) is None


# -- Rule 4: late_delivery_logistics -----------------------------------------


def test_late_delivery_logistics_fires_when_no_seller_at_fault():
    inputs = make_inputs(delivered_late=True, late_seller_ids=(), freight_total=Decimal("20.00"))
    outcome = rule_late_delivery_logistics(inputs)
    assert outcome is not None
    assert outcome.primary_issue == PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS
    assert outcome.cause_code == CAUSE_CODE_CARRIER_DELIVERED_AFTER_ESTIMATE
    assert outcome.recommended_refund == Decimal("20.00")
    assert [p.party_type for p in outcome.responsible_parties] == ["logistics_provider"]


def test_late_delivery_logistics_does_not_fire_when_seller_at_fault():
    inputs = make_inputs(delivered_late=True, late_seller_ids=("SELLER_A",))
    assert rule_late_delivery_logistics(inputs) is None


# -- Rule 5: valid_split_payment ---------------------------------------------


def test_valid_split_payment_fires_with_two_rows_matching():
    inputs = make_inputs(payment_row_count=2, payment_matches_order_total=True)
    outcome = rule_valid_split_payment(inputs)
    assert outcome is not None
    assert outcome.primary_issue == PRIMARY_ISSUE_VALID_SPLIT_PAYMENT
    assert outcome.cause_code == CAUSE_CODE_MULTIPLE_PAYMENTS_RECONCILED
    assert outcome.recommended_refund == Decimal("0")
    assert outcome.responsible_parties == ()


def test_valid_split_payment_requires_at_least_two_rows():
    inputs = make_inputs(payment_row_count=1, payment_matches_order_total=True)
    assert rule_valid_split_payment(inputs) is None


def test_valid_split_payment_requires_reconciliation():
    inputs = make_inputs(payment_row_count=3, payment_matches_order_total=False)
    assert rule_valid_split_payment(inputs) is None


# -- Rule 6: unsupported_late_claim ------------------------------------------


def test_unsupported_late_claim_fires_when_confirmed_on_time_and_matches():
    inputs = make_inputs(delivered_late=False, payment_matches_order_total=True)
    outcome = rule_unsupported_late_claim(inputs)
    assert outcome is not None
    assert outcome.primary_issue == PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM
    assert outcome.cause_code == CAUSE_CODE_DELIVERY_WITHIN_ESTIMATE
    assert outcome.recommended_refund == Decimal("0")


def test_unsupported_late_claim_does_not_fire_when_unknown():
    inputs = make_inputs(delivered_late=None, payment_matches_order_total=True)
    assert rule_unsupported_late_claim(inputs) is None


def test_unsupported_late_claim_does_not_fire_when_payment_mismatched():
    inputs = make_inputs(delivered_late=False, payment_matches_order_total=False)
    assert rule_unsupported_late_claim(inputs) is None


# -- Priority chain -----------------------------------------------------------


def test_canceled_paid_wins_over_late_delivery():
    """Even if the order also looks late, cancellation-with-payment must win
    (rule 1 is checked before rules 3/4)."""
    inputs = make_inputs(
        order_status="canceled",
        payment_total=Decimal("100.00"),
        delivered_late=True,
        late_seller_ids=("SELLER_A",),
    )
    outcome = evaluate_policy(inputs)
    assert outcome.primary_issue == PRIMARY_ISSUE_CANCELED_ORDER_PAID


def test_unavailable_paid_wins_over_late_delivery():
    inputs = make_inputs(
        order_status="unavailable",
        payment_total=Decimal("100.00"),
        delivered_late=True,
        late_seller_ids=(),
    )
    outcome = evaluate_policy(inputs)
    assert outcome.primary_issue == PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID


def test_late_delivery_wins_over_valid_split_payment():
    """A late order with >=2 matching payments must be classified as late
    delivery, not as a benign split payment (rule 3/4 before rule 5)."""
    inputs = make_inputs(
        delivered_late=True,
        late_seller_ids=("SELLER_A",),
        payment_row_count=2,
        payment_matches_order_total=True,
    )
    outcome = evaluate_policy(inputs)
    assert outcome.primary_issue == PRIMARY_ISSUE_LATE_DELIVERY_SELLER


def test_valid_split_payment_wins_over_unsupported_late_claim():
    inputs = make_inputs(
        delivered_late=False,
        payment_row_count=2,
        payment_matches_order_total=True,
    )
    outcome = evaluate_policy(inputs)
    assert outcome.primary_issue == PRIMARY_ISSUE_VALID_SPLIT_PAYMENT


def test_exactly_one_primary_issue_is_ever_returned():
    """evaluate_policy must never be ambiguous: exactly one RuleOutcome,
    never a list, and it must be one of the 7 known primary_issue values."""
    known = {
        PRIMARY_ISSUE_CANCELED_ORDER_PAID,
        PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID,
        PRIMARY_ISSUE_LATE_DELIVERY_SELLER,
        PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS,
        PRIMARY_ISSUE_VALID_SPLIT_PAYMENT,
        PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM,
        PRIMARY_ISSUE_UNCLASSIFIED,
    }
    inputs = make_inputs()
    outcome = evaluate_policy(inputs)
    assert outcome.primary_issue in known


def test_fallback_used_when_no_rule_matches():
    """No order status match, delivery timeliness unknown, single payment
    that does not reconcile -- nothing in the README table applies."""
    inputs = make_inputs(
        order_status="delivered",
        delivered_late=None,
        payment_row_count=1,
        payment_matches_order_total=False,
    )
    outcome = evaluate_policy(inputs)
    assert outcome.primary_issue == PRIMARY_ISSUE_UNCLASSIFIED
    assert outcome.recommended_refund == Decimal("0")


def test_evaluate_policy_is_pure_and_deterministic():
    inputs = make_inputs(order_status="canceled", payment_total=Decimal("42.00"))
    first = evaluate_policy(inputs)
    second = evaluate_policy(inputs)
    assert first == second


@pytest.mark.parametrize(
    "order_status,payment_total,delivered_late,late_sellers,expected",
    [
        ("canceled", Decimal("10.00"), None, (), PRIMARY_ISSUE_CANCELED_ORDER_PAID),
        ("unavailable", Decimal("10.00"), None, (), PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID),
        ("delivered", Decimal("0"), True, ("SELLER_X",), PRIMARY_ISSUE_LATE_DELIVERY_SELLER),
        ("delivered", Decimal("0"), True, (), PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS),
    ],
)
def test_rule_table_matrix(order_status, payment_total, delivered_late, late_sellers, expected):
    inputs = make_inputs(
        order_status=order_status,
        payment_total=payment_total,
        delivered_late=delivered_late,
        late_seller_ids=late_sellers,
    )
    assert evaluate_policy(inputs).primary_issue == expected
