"""Tests for the Verifier Agent and the full Coordinator handoff chain,
using the mini_olist fixture data (tests/fixtures/mini_olist).

Two kinds of tests:
1. End-to-end: run every fixture order through the real Coordinator and
   check it lands on the expected primary_issue (also exercises
   Order/Seller -> Payment -> Delivery -> Policy -> Verifier handoff).
2. Verifier-only: build one known-good output, then corrupt exactly one
   field at a time and assert `VerifierAgent.verify` raises
   `VerificationError` with a message describing that specific problem.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal

import pytest

from app.agents.delivery_agent import DeliveryAgent
from app.agents.order_seller_agent import OrderSellerAgent
from app.agents.payment_agent import PaymentAgent
from app.agents.policy_agent import PolicyAgent
from app.agents.verifier_agent import VerifierAgent
from app.schemas import (
    CaseProcessingError,
    InvalidCaseInputError,
    OrderNotFoundError,
    PRIMARY_ISSUE_CANCELED_ORDER_PAID,
    PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS,
    PRIMARY_ISSUE_LATE_DELIVERY_SELLER,
    PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID,
    PRIMARY_ISSUE_UNCLASSIFIED,
    PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM,
    PRIMARY_ISSUE_VALID_SPLIT_PAYMENT,
    VerificationError,
)
from app.utils.output_builder import build_output
from tests.conftest import make_case_input


# -- End-to-end: every fixture scenario through the real Coordinator --------


@pytest.mark.parametrize(
    "order_id,expected_primary_issue",
    [
        ("ORD_CANCELED", PRIMARY_ISSUE_CANCELED_ORDER_PAID),
        ("ORD_UNAVAILABLE", PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID),
        ("ORD_LATE_SELLER", PRIMARY_ISSUE_LATE_DELIVERY_SELLER),
        ("ORD_LATE_LOGISTICS", PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS),
        ("ORD_SPLIT_PAYMENT", PRIMARY_ISSUE_VALID_SPLIT_PAYMENT),
        ("ORD_UNSUPPORTED_CLAIM", PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM),
        ("ORD_NULL_TIMESTAMP", PRIMARY_ISSUE_UNCLASSIFIED),
        ("ORD_ZERO_PAYMENT", PRIMARY_ISSUE_UNCLASSIFIED),
        ("ORD_EMPTY_ITEMS", PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM),
        ("ORD_TOL_09", PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM),
        ("ORD_TOL_10", PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM),
        ("ORD_TOL_11", PRIMARY_ISSUE_UNCLASSIFIED),
        ("ORD_EQUAL_ESTIMATE", PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM),
        ("ORD_EQUAL_LIMIT", PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS),
    ],
)
def test_coordinator_end_to_end(coordinator, order_id, expected_primary_issue):
    case_input = make_case_input(f"EC_TEST_{order_id}", order_id)
    output = coordinator.process_case(case_input)
    assert output["assessment"]["primary_issue"] == expected_primary_issue
    # A case that reached this point already passed the Verifier inside
    # process_case; re-serializing must also succeed.
    json.dumps(output)


def test_empty_items_order_has_empty_ids_and_zero_totals(coordinator):
    output = coordinator.process_case(make_case_input("EC_EMPTY", "ORD_EMPTY_ITEMS"))
    assert output["affected_entities"]["item_ids"] == []
    assert output["affected_entities"]["seller_ids"] == []
    assert output["financial_resolution"]["item_total_brl"] == 0.0
    assert output["financial_resolution"]["freight_total_brl"] == 0.0


def test_order_not_found_raises(coordinator):
    with pytest.raises(OrderNotFoundError):
        coordinator.process_case(make_case_input("EC_MISSING", "DOES_NOT_EXIST_ORDER"))


def test_late_delivery_seller_narrows_affected_entities_to_violating_seller(coordinator):
    """ORD_LATE_SELLER has 2 items/2 sellers: SELLER_A missed its handoff
    window, SELLER_B did not. The dispute is about SELLER_A's item, so
    affected_entities must not drag in SELLER_B's on-time item just
    because it shares the same order."""
    output = coordinator.process_case(make_case_input("EC_LATE_SELLER", "ORD_LATE_SELLER"))
    assert output["affected_entities"]["seller_ids"] == ["SELLER_A"]
    assert output["affected_entities"]["item_ids"] == ["ORD_LATE_SELLER:1"]
    # Financial totals must still reflect the WHOLE order (README: freight
    # refund is the sum over every item), not just the violating seller's.
    assert output["financial_resolution"]["freight_total_brl"] == 18.0
    assert output["financial_resolution"]["item_total_brl"] == 150.0


def test_late_delivery_logistics_keeps_full_order_context(coordinator):
    """No seller is at fault here, so there's no item/seller to single out
    -- the full order context is the correct affected_entities."""
    output = coordinator.process_case(make_case_input("EC_LATE_LOGISTICS", "ORD_LATE_LOGISTICS"))
    assert output["affected_entities"]["seller_ids"] == ["SELLER_C"]
    assert output["affected_entities"]["item_ids"] == ["ORD_LATE_LOGISTICS:1"]


def test_missing_claimed_order_id_raises_invalid_input(coordinator):
    bad_input = {"case_id": "EC_BAD", "customer_request": {}, "policy_version": "v1"}
    with pytest.raises(InvalidCaseInputError):
        coordinator.process_case(bad_input)


def test_missing_case_id_raises_invalid_input(coordinator):
    bad_input = {"customer_request": {"claimed_order_id": "ORD_CANCELED"}}
    with pytest.raises(InvalidCaseInputError):
        coordinator.process_case(bad_input)


def test_all_case_processing_errors_share_common_base():
    assert issubclass(OrderNotFoundError, CaseProcessingError)
    assert issubclass(InvalidCaseInputError, CaseProcessingError)
    assert issubclass(VerificationError, CaseProcessingError)


# -- Verifier-only: build one valid output, then corrupt one field ----------


@pytest.fixture()
def valid_bundle(mini_store):
    order_result = OrderSellerAgent(mini_store).analyze("ORD_LATE_SELLER")
    payment_result = PaymentAgent(mini_store).analyze(
        "ORD_LATE_SELLER", order_result.item_total, order_result.freight_total
    )
    delivery_result = DeliveryAgent().analyze(
        "ORD_LATE_SELLER", order_result.order_record, order_result.items
    )
    policy_result = PolicyAgent().decide(order_result, payment_result, delivery_result)
    case_input = make_case_input("EC_LATE_SELLER", "ORD_LATE_SELLER")
    output = build_output("EC_LATE_SELLER", order_result, payment_result, delivery_result, policy_result)
    return {
        "verifier": VerifierAgent(mini_store),
        "case_input": case_input,
        "output": output,
        "order_result": order_result,
        "payment_result": payment_result,
        "delivery_result": delivery_result,
        "policy_result": policy_result,
    }


def _verify(bundle, output):
    bundle["verifier"].verify(
        bundle["case_input"],
        output,
        bundle["order_result"],
        bundle["payment_result"],
        bundle["delivery_result"],
        bundle["policy_result"],
    )


def test_valid_output_passes_verification(valid_bundle):
    _verify(valid_bundle, valid_bundle["output"])  # must not raise


def test_verifier_rejects_case_id_mismatch(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["case_id"] = "EC_WRONG"
    with pytest.raises(VerificationError, match="case_id mismatch"):
        _verify(valid_bundle, output)


def test_verifier_rejects_unknown_order_id(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["affected_entities"]["order_ids"] = ["ORDER_THAT_DOES_NOT_EXIST"]
    with pytest.raises(VerificationError, match="unknown order"):
        _verify(valid_bundle, output)


def test_verifier_rejects_unknown_item_id(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["affected_entities"]["item_ids"] = ["ORD_LATE_SELLER:99"]
    with pytest.raises(VerificationError, match="unknown item"):
        _verify(valid_bundle, output)


def test_verifier_rejects_unknown_payment_id(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["affected_entities"]["payment_ids"] = ["ORD_LATE_SELLER:99"]
    with pytest.raises(VerificationError, match="unknown payment"):
        _verify(valid_bundle, output)


def test_verifier_rejects_unknown_seller_id(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["affected_entities"]["seller_ids"] = ["SELLER_GHOST"]
    with pytest.raises(VerificationError, match="unknown seller"):
        _verify(valid_bundle, output)


def test_verifier_rejects_malformed_evidence(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["evidence_ids"] = ["not-a-valid-evidence-id"]
    with pytest.raises(VerificationError, match="invalid format"):
        _verify(valid_bundle, output)


def test_verifier_rejects_evidence_for_nonexistent_item(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["evidence_ids"] = ["item:ORD_LATE_SELLER:99"]
    with pytest.raises(VerificationError, match="unknown item"):
        _verify(valid_bundle, output)


def test_verifier_rejects_policy_evidence_with_wrong_cause_code(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["evidence_ids"] = [e for e in output["evidence_ids"] if not e.startswith("policy:")]
    output["evidence_ids"].append("policy:DELIVERY_WITHIN_ESTIMATE")
    with pytest.raises(VerificationError, match="does not match the actual conclusion"):
        _verify(valid_bundle, output)


def test_verifier_rejects_refund_mismatch(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["financial_resolution"]["recommended_refund_brl"] = 999.99
    with pytest.raises(VerificationError, match="recommended_refund_brl"):
        _verify(valid_bundle, output)


def test_verifier_rejects_action_mismatch(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["resolution_actions"] = ["reject_late_refund"]
    with pytest.raises(VerificationError, match="missing expected action"):
        _verify(valid_bundle, output)


def test_verifier_rejects_case_status_mismatch(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["assessment"]["case_status"] = "no_action"
    with pytest.raises(VerificationError, match="case_status"):
        _verify(valid_bundle, output)


def test_verifier_rejects_confidence_out_of_range(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["assessment"]["confidence"] = 1.5
    with pytest.raises(VerificationError, match="out of range"):
        _verify(valid_bundle, output)


def test_verifier_rejects_too_many_entity_ids(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["affected_entities"]["seller_ids"] = ["SELLER_A", "SELLER_B", "SELLER_C", "X", "Y", "Z"]
    with pytest.raises(VerificationError, match="exceeds max"):
        _verify(valid_bundle, output)


def test_verifier_rejects_too_many_evidence_ids(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["evidence_ids"] = output["evidence_ids"] + ["order:ORD_LATE_SELLER"] * 10
    with pytest.raises(VerificationError, match="evidence_ids exceeds max"):
        _verify(valid_bundle, output)


def test_verifier_rejects_non_json_serializable_output(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["financial_resolution"]["recommended_refund_brl"] = Decimal("1.00")
    with pytest.raises(VerificationError):
        _verify(valid_bundle, output)


def test_verifier_rejects_missing_top_level_field(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    del output["evidence_ids"]
    with pytest.raises(VerificationError, match="missing top-level field"):
        _verify(valid_bundle, output)


def test_verifier_rejects_wrong_currency(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["financial_resolution"]["currency"] = "USD"
    with pytest.raises(VerificationError, match="currency"):
        _verify(valid_bundle, output)


def test_verifier_rejects_financial_total_mismatch(valid_bundle):
    output = copy.deepcopy(valid_bundle["output"])
    output["financial_resolution"]["item_total_brl"] = 1.23
    with pytest.raises(VerificationError, match="item_total_brl"):
        _verify(valid_bundle, output)
