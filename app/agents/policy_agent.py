"""Policy Agent.

Applies EC_POLICY_V1 (README section 4) as an ordered chain of pure
functions: same inputs always produce the same outcome, no filesystem,
clock or model call involved. Each `rule_*` function is independently
testable; `evaluate_policy` is the priority chain that tries them in the
exact README order and returns the first match.

Priority order (first match wins):
  1. canceled_order_paid       (order_status == canceled, payment_total > 0)
  2. unavailable_order_paid    (order_status == unavailable, payment_total > 0)
  3. late_delivery_seller      (delivered late AND a seller missed handoff)
  4. late_delivery_logistics   (delivered late AND no seller missed handoff)
  5. valid_split_payment       (>=2 payment rows AND totals reconcile)
  6. unsupported_late_claim    (confirmed not late AND totals reconcile)

If none of the six match, we fall back to PRIMARY_ISSUE_UNCLASSIFIED. This
is not in the README table -- it is a documented assumption for cases with
insufficient evidence (e.g. missing timestamps and no payments), and it
always resolves to case_status=no_action / refund=0.0 so it can never
invent a refund the data does not support.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.config import (
    CASE_STATUS_ACTION_REQUIRED,
    CASE_STATUS_NO_ACTION,
    PARTY_LOGISTICS,
    PARTY_PLATFORM,
)
from app.schemas import (
    ACTION_EXPLAIN_VALID_SPLIT_PAYMENT,
    ACTION_ISSUE_FULL_REFUND,
    ACTION_MANUAL_REVIEW_REQUIRED,
    ACTION_REFUND_FREIGHT,
    ACTION_REJECT_LATE_REFUND,
    CAUSE_CODE_CARRIER_DELIVERED_AFTER_ESTIMATE,
    CAUSE_CODE_DELIVERY_WITHIN_ESTIMATE,
    CAUSE_CODE_INSUFFICIENT_EVIDENCE,
    CAUSE_CODE_MULTIPLE_PAYMENTS_RECONCILED,
    CAUSE_CODE_ORDER_CANCELED_AFTER_PAYMENT,
    CAUSE_CODE_ORDER_UNAVAILABLE_AFTER_PAYMENT,
    CAUSE_CODE_SELLER_HANDOFF_AFTER_LIMIT,
    DeliveryResult,
    OrderSellerResult,
    PARTY_TYPE_LOGISTICS_PROVIDER,
    PARTY_TYPE_PLATFORM,
    PARTY_TYPE_SELLER,
    PaymentResult,
    PRIMARY_ISSUE_CANCELED_ORDER_PAID,
    PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS,
    PRIMARY_ISSUE_LATE_DELIVERY_SELLER,
    PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID,
    PRIMARY_ISSUE_UNCLASSIFIED,
    PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM,
    PRIMARY_ISSUE_VALID_SPLIT_PAYMENT,
    PolicyResult,
    ResponsibleParty,
)

ORDER_STATUS_CANCELED = "canceled"
ORDER_STATUS_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PolicyInputs:
    """Pure, agent-agnostic inputs the rule chain reasons over."""

    order_status: Optional[str]
    payment_total: Decimal
    item_total: Decimal
    freight_total: Decimal
    payment_row_count: int
    payment_matches_order_total: bool
    delivered_late: Optional[bool]
    late_seller_ids: tuple[str, ...]


@dataclass(frozen=True)
class RuleOutcome:
    primary_issue: str
    cause_code: str
    case_status: str
    action: str
    responsible_parties: tuple[ResponsibleParty, ...]
    recommended_refund: Decimal
    base_confidence: float


def rule_canceled_order_paid(inputs: PolicyInputs) -> Optional[RuleOutcome]:
    if inputs.order_status == ORDER_STATUS_CANCELED and inputs.payment_total > 0:
        return RuleOutcome(
            primary_issue=PRIMARY_ISSUE_CANCELED_ORDER_PAID,
            cause_code=CAUSE_CODE_ORDER_CANCELED_AFTER_PAYMENT,
            case_status=CASE_STATUS_ACTION_REQUIRED,
            action=ACTION_ISSUE_FULL_REFUND,
            responsible_parties=(ResponsibleParty(PARTY_TYPE_PLATFORM, PARTY_PLATFORM),),
            recommended_refund=inputs.payment_total,
            base_confidence=1.0,
        )
    return None


def rule_unavailable_order_paid(inputs: PolicyInputs) -> Optional[RuleOutcome]:
    if inputs.order_status == ORDER_STATUS_UNAVAILABLE and inputs.payment_total > 0:
        return RuleOutcome(
            primary_issue=PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID,
            cause_code=CAUSE_CODE_ORDER_UNAVAILABLE_AFTER_PAYMENT,
            case_status=CASE_STATUS_ACTION_REQUIRED,
            action=ACTION_ISSUE_FULL_REFUND,
            responsible_parties=(ResponsibleParty(PARTY_TYPE_PLATFORM, PARTY_PLATFORM),),
            recommended_refund=inputs.payment_total,
            base_confidence=1.0,
        )
    return None


def rule_late_delivery_seller(inputs: PolicyInputs) -> Optional[RuleOutcome]:
    if inputs.delivered_late is True and len(inputs.late_seller_ids) > 0:
        parties = tuple(
            ResponsibleParty(PARTY_TYPE_SELLER, seller_id) for seller_id in inputs.late_seller_ids
        )
        return RuleOutcome(
            primary_issue=PRIMARY_ISSUE_LATE_DELIVERY_SELLER,
            cause_code=CAUSE_CODE_SELLER_HANDOFF_AFTER_LIMIT,
            case_status=CASE_STATUS_ACTION_REQUIRED,
            action=ACTION_REFUND_FREIGHT,
            responsible_parties=parties,
            recommended_refund=inputs.freight_total,
            base_confidence=1.0,
        )
    return None


def rule_late_delivery_logistics(inputs: PolicyInputs) -> Optional[RuleOutcome]:
    if inputs.delivered_late is True and len(inputs.late_seller_ids) == 0:
        return RuleOutcome(
            primary_issue=PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS,
            cause_code=CAUSE_CODE_CARRIER_DELIVERED_AFTER_ESTIMATE,
            case_status=CASE_STATUS_ACTION_REQUIRED,
            action=ACTION_REFUND_FREIGHT,
            responsible_parties=(ResponsibleParty(PARTY_TYPE_LOGISTICS_PROVIDER, PARTY_LOGISTICS),),
            recommended_refund=inputs.freight_total,
            base_confidence=1.0,
        )
    return None


def rule_valid_split_payment(inputs: PolicyInputs) -> Optional[RuleOutcome]:
    if inputs.payment_row_count >= 2 and inputs.payment_matches_order_total:
        return RuleOutcome(
            primary_issue=PRIMARY_ISSUE_VALID_SPLIT_PAYMENT,
            cause_code=CAUSE_CODE_MULTIPLE_PAYMENTS_RECONCILED,
            case_status=CASE_STATUS_NO_ACTION,
            action=ACTION_EXPLAIN_VALID_SPLIT_PAYMENT,
            responsible_parties=(),
            recommended_refund=Decimal("0"),
            base_confidence=1.0,
        )
    return None


def rule_unsupported_late_claim(inputs: PolicyInputs) -> Optional[RuleOutcome]:
    if inputs.delivered_late is False and inputs.payment_matches_order_total:
        return RuleOutcome(
            primary_issue=PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM,
            cause_code=CAUSE_CODE_DELIVERY_WITHIN_ESTIMATE,
            case_status=CASE_STATUS_NO_ACTION,
            action=ACTION_REJECT_LATE_REFUND,
            responsible_parties=(),
            recommended_refund=Decimal("0"),
            base_confidence=1.0,
        )
    return None


def rule_fallback_insufficient_evidence(inputs: PolicyInputs) -> RuleOutcome:
    return RuleOutcome(
        primary_issue=PRIMARY_ISSUE_UNCLASSIFIED,
        cause_code=CAUSE_CODE_INSUFFICIENT_EVIDENCE,
        case_status=CASE_STATUS_NO_ACTION,
        action=ACTION_MANUAL_REVIEW_REQUIRED,
        responsible_parties=(),
        recommended_refund=Decimal("0"),
        base_confidence=0.3,
    )


# Ordered exactly as README section 4's priority table.
RULE_CHAIN = (
    rule_canceled_order_paid,
    rule_unavailable_order_paid,
    rule_late_delivery_seller,
    rule_late_delivery_logistics,
    rule_valid_split_payment,
    rule_unsupported_late_claim,
)


def evaluate_policy(inputs: PolicyInputs) -> RuleOutcome:
    for rule in RULE_CHAIN:
        outcome = rule(inputs)
        if outcome is not None:
            return outcome
    return rule_fallback_insufficient_evidence(inputs)


class PolicyAgent:
    """Thin adapter: turns agent handoff results into `PolicyInputs`, runs
    the pure rule chain, and folds in warning-driven confidence decay."""

    def decide(
        self,
        order_result: OrderSellerResult,
        payment_result: PaymentResult,
        delivery_result: DeliveryResult,
    ) -> PolicyResult:
        order_status = order_result.order_record.order_status if order_result.order_record else None
        inputs = PolicyInputs(
            order_status=order_status,
            payment_total=payment_result.payment_total,
            item_total=order_result.item_total,
            freight_total=order_result.freight_total,
            payment_row_count=payment_result.payment_row_count,
            payment_matches_order_total=payment_result.payment_matches_order_total,
            delivered_late=delivery_result.delivered_late,
            late_seller_ids=tuple(delivery_result.late_seller_ids),
        )
        outcome = evaluate_policy(inputs)

        # Every warning is kept in the trace for transparency, but only the
        # warnings that actually bear on the rule that fired should erode
        # confidence. e.g. canceled_order_paid depends solely on
        # order_status + payment_total, so a delivery_agent warning like
        # "delivered_late undetermined" (expected for a canceled order --
        # it was never delivered) must not be treated as uncertainty about
        # the conclusion.
        all_warnings = [*order_result.warnings, *payment_result.warnings, *delivery_result.warnings]
        relevant_warnings = self._relevant_warnings(outcome.primary_issue, order_result, payment_result, delivery_result)
        if outcome.primary_issue == PRIMARY_ISSUE_UNCLASSIFIED:
            relevant_warnings = list(relevant_warnings) + [
                "policy fallback used: no README rule matched (insufficient/ambiguous evidence)"
            ]
            all_warnings = list(all_warnings) + [
                "policy fallback used: no README rule matched (insufficient/ambiguous evidence)"
            ]

        confidence = outcome.base_confidence - 0.15 * len(relevant_warnings)
        confidence = max(0.0, min(1.0, confidence))
        warnings = all_warnings

        return PolicyResult(
            primary_issue=outcome.primary_issue,
            cause_code=outcome.cause_code,
            case_status=outcome.case_status,
            action=outcome.action,
            responsible_parties=list(outcome.responsible_parties),
            recommended_refund=outcome.recommended_refund,
            confidence=confidence,
            warnings=warnings,
        )

    @staticmethod
    def _relevant_warnings(
        primary_issue: str,
        order_result: OrderSellerResult,
        payment_result: PaymentResult,
        delivery_result: DeliveryResult,
    ) -> list[str]:
        """Which agents' warnings actually bear on the fired rule's
        certainty. Kept as an explicit table (not "all warnings from all
        agents") so an agent noticing something harmless and expected --
        e.g. no delivery timestamps on a canceled order -- never dilutes
        confidence in a conclusion that never looked at delivery data."""
        if primary_issue in (PRIMARY_ISSUE_CANCELED_ORDER_PAID, PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID):
            # Rule only reads order_status + payment_total.
            return []
        if primary_issue in (PRIMARY_ISSUE_LATE_DELIVERY_SELLER, PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS):
            # Rule only reads delivery timestamps / per-item handoff dates.
            return list(delivery_result.warnings)
        if primary_issue in (PRIMARY_ISSUE_VALID_SPLIT_PAYMENT, PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM):
            # Rule reads item/freight totals (order_result) and payment
            # reconciliation (payment_result); delivery data for
            # unsupported_late_claim is only used when delivered_late is
            # already confirmed False, so no delivery warning can apply.
            return [*order_result.warnings, *payment_result.warnings]
        # Fallback: nothing matched, so every warning is genuinely relevant
        # to explaining the uncertainty.
        return [*order_result.warnings, *payment_result.warnings, *delivery_result.warnings]
