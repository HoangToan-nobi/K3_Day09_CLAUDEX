"""Output formatting layer.

Turns the four agents' typed results into the exact output schema from
README section 6. This is pure data shaping: no business decision is made
here, only truncation to the published limits and deterministic ordering
(sorted IDs, not sets, not CSV row order) so re-running the pipeline on
the same data always yields byte-identical output.
"""

from __future__ import annotations

from app.config import (
    CURRENCY,
    MAX_ENTITY_IDS,
    MAX_EVIDENCE_IDS,
    MAX_RANKED_CAUSES,
    MAX_RESOLUTION_ACTIONS,
    MAX_RESPONSIBLE_PARTIES,
)
from app.schemas import (
    DeliveryResult,
    OrderSellerResult,
    PaymentResult,
    PolicyResult,
    PRIMARY_ISSUE_CANCELED_ORDER_PAID,
    PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS,
    PRIMARY_ISSUE_LATE_DELIVERY_SELLER,
    PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID,
    PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM,
    PRIMARY_ISSUE_VALID_SPLIT_PAYMENT,
)
from app.utils.money import round_money


def _scope_affected_items_and_sellers(
    order_result: OrderSellerResult, policy_result: PolicyResult
) -> tuple[list[str], list[str]]:
    """Which items/sellers count as "affected" for this case.

    For every rule except late_delivery_seller, fault (or its absence) is
    uniform across the whole order -- there is no single item/seller the
    complaint singles out, so the full order context is reported.

    late_delivery_seller is the one rule where README ties the root cause
    to specific items ("seller bị coi là bàn giao muộn nếu ... của item
    thuộc seller đó"): only the seller(s) actually named in
    `responsible_parties` -- and the items they shipped -- are the ones
    the dispute is actually about. An on-time seller sharing the same
    order is not part of what this case is affected by.
    """
    if policy_result.primary_issue == PRIMARY_ISSUE_LATE_DELIVERY_SELLER:
        responsible_seller_ids = {party.party_id for party in policy_result.responsible_parties}
        scoped_items = [item for item in order_result.items if item.seller_id in responsible_seller_ids]
        if scoped_items:
            item_ids = [item.item_id for item in scoped_items]
            seller_ids = sorted({item.seller_id for item in scoped_items})
            return item_ids, seller_ids
    return order_result.item_ids, order_result.seller_ids


# Which entity families actually substantiate each conclusion. Evidence is
# meant to be the proof of the finding, not an inventory of the order:
# a canceled-order refund is proven by the order status plus the payment
# rows, and dragging in the item/seller lines adds no probative value.
#
#   issue -> (include items, include payments, include sellers)
EVIDENCE_SCOPE_BY_ISSUE = {
    # Proven by order_status + the payments that must be returned.
    PRIMARY_ISSUE_CANCELED_ORDER_PAID: (True, True, True),
    PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID: (False, True, False),
    # Proven by the item lines whose shipping_limit_date was missed, and
    # by the seller answering for them.
    # The README's canonical late-delivery evidence includes the payment
    # row as well as the order/item/seller facts.  Keep that payment proof:
    # it anchors the freight amount being refunded.
    PRIMARY_ISSUE_LATE_DELIVERY_SELLER: (True, True, True),
    # Seller met every handoff deadline, so no seller line is probative;
    # the item lines carry the freight being refunded.
    PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS: (True, True, False),
    # Reconciliation claims need both sides of the arithmetic.
    PRIMARY_ISSUE_VALID_SPLIT_PAYMENT: (True, True, False),
    PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM: (True, True, False),
}


def _build_evidence_ids(
    order_id: str,
    primary_issue: str,
    item_ids: list[str],
    payment_ids: list[str],
    seller_ids: list[str],
    cause_code: str,
) -> list[str]:
    evidence = [f"order:{order_id}"]
    # Evidence ids always use the README section 5 form, independent of how
    # affected_entities.payment_ids happens to be formatted.
    bare_payment_ids = [
        pid[len("payment:"):] if pid.startswith("payment:") else pid for pid in payment_ids
    ]
    # Unknown/fallback conclusions keep every available id: with no rule
    # established there is nothing to call irrelevant.
    use_items, use_payments, use_sellers = EVIDENCE_SCOPE_BY_ISSUE.get(
        primary_issue, (True, True, True)
    )
    pool = (
        ([f"item:{item_id}" for item_id in item_ids] if use_items else [])
        + ([f"payment:{payment_id}" for payment_id in bare_payment_ids] if use_payments else [])
        + ([f"seller:{seller_id}" for seller_id in seller_ids] if use_sellers else [])
    )
    remaining = max(MAX_EVIDENCE_IDS - 2, 0)  # reserve slots for order + policy
    evidence.extend(pool[:remaining])
    evidence.append(f"policy:{cause_code}")
    return evidence[:MAX_EVIDENCE_IDS]


def build_output(
    case_id: str,
    order_result: OrderSellerResult,
    payment_result: PaymentResult,
    delivery_result: DeliveryResult,
    policy_result: PolicyResult,
) -> dict:
    scoped_item_ids, scoped_seller_ids = _scope_affected_items_and_sellers(order_result, policy_result)

    order_ids = [order_result.order_id][:MAX_ENTITY_IDS]
    item_ids = scoped_item_ids[:MAX_ENTITY_IDS]
    seller_ids = scoped_seller_ids[:MAX_ENTITY_IDS]
    payment_ids = payment_result.payment_ids[:MAX_ENTITY_IDS]

    ranked_causes = [{"cause_code": policy_result.cause_code, "rank": 1}][:MAX_RANKED_CAUSES]
    responsible_parties = [
        {"party_type": party.party_type, "party_id": party.party_id}
        for party in policy_result.responsible_parties[:MAX_RESPONSIBLE_PARTIES]
    ]

    evidence_ids = _build_evidence_ids(
        order_result.order_id,
        policy_result.primary_issue,
        item_ids,
        payment_ids,
        seller_ids,
        policy_result.cause_code,
    )

    resolution_actions = [policy_result.action][:MAX_RESOLUTION_ACTIONS]

    return {
        "case_id": case_id,
        "assessment": {
            "primary_issue": policy_result.primary_issue,
            "case_status": policy_result.case_status,
            "confidence": round(policy_result.confidence, 2),
        },
        "affected_entities": {
            "order_ids": order_ids,
            "item_ids": item_ids,
            "seller_ids": seller_ids,
            "payment_ids": payment_ids,
        },
        "root_cause_analysis": {
            "ranked_causes": ranked_causes,
            "responsible_parties": responsible_parties,
        },
        "evidence_ids": evidence_ids,
        "financial_resolution": {
            "currency": CURRENCY,
            "item_total_brl": round_money(order_result.item_total),
            "freight_total_brl": round_money(order_result.freight_total),
            "payment_total_brl": round_money(payment_result.payment_total),
            "recommended_refund_brl": round_money(policy_result.recommended_refund),
        },
        "resolution_actions": resolution_actions,
    }
