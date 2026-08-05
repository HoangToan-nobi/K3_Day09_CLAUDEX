"""Typed records shared across agents, plus the business-rule vocabulary.

These dataclasses are the contracts between agents: each agent hands the
next one an instance of one of these types instead of raw dicts, so the
handoff boundaries are explicit and testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Raw data-store records (one row of a CSV, typed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderRecord:
    order_id: str
    customer_id: Optional[str]
    order_status: Optional[str]
    order_purchase_timestamp: Optional[pd.Timestamp]
    order_approved_at: Optional[pd.Timestamp]
    order_delivered_carrier_date: Optional[pd.Timestamp]
    order_delivered_customer_date: Optional[pd.Timestamp]
    order_estimated_delivery_date: Optional[pd.Timestamp]


@dataclass(frozen=True)
class ItemRecord:
    order_id: str
    order_item_id: int
    product_id: Optional[str]
    seller_id: Optional[str]
    shipping_limit_date: Optional[pd.Timestamp]
    price: Decimal
    freight_value: Decimal

    @property
    def item_id(self) -> str:
        return f"{self.order_id}:{self.order_item_id}"


@dataclass(frozen=True)
class PaymentRecord:
    order_id: str
    payment_sequential: int
    payment_type: Optional[str]
    payment_installments: Optional[int]
    payment_value: Decimal

    @property
    def payment_ref(self) -> str:
        return f"{self.order_id}:{self.payment_sequential}"


@dataclass(frozen=True)
class SellerRecord:
    seller_id: str
    seller_zip_code_prefix: Optional[str]
    seller_city: Optional[str]
    seller_state: Optional[str]


@dataclass(frozen=True)
class CustomerRecord:
    customer_id: str
    customer_unique_id: Optional[str]
    customer_zip_code_prefix: Optional[str]
    customer_city: Optional[str]
    customer_state: Optional[str]


@dataclass(frozen=True)
class ProductRecord:
    product_id: str
    product_category_name: Optional[str]


@dataclass(frozen=True)
class ReviewRecord:
    review_id: str
    order_id: str
    review_score: Optional[int]


# ---------------------------------------------------------------------------
# Business-rule vocabulary (README section 4)
# ---------------------------------------------------------------------------

PRIMARY_ISSUE_CANCELED_ORDER_PAID = "canceled_order_paid"
PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID = "unavailable_order_paid"
PRIMARY_ISSUE_LATE_DELIVERY_SELLER = "late_delivery_seller"
PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS = "late_delivery_logistics"
PRIMARY_ISSUE_VALID_SPLIT_PAYMENT = "valid_split_payment"
PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM = "unsupported_late_claim"
# Not part of the README's 6 rules. Used only when an order genuinely has no
# evidence to satisfy any rule (e.g. no items, no payments, and delivery
# timeliness cannot be determined because required timestamps are missing).
# This is an explicit documented assumption (see architecture.md) rather
# than a silent default, and it always resolves to case_status=no_action /
# refund=0.0 so it can never fabricate a refund.
PRIMARY_ISSUE_UNCLASSIFIED = "unclassified_insufficient_evidence"

CAUSE_CODE_SELLER_HANDOFF_AFTER_LIMIT = "SELLER_HANDOFF_AFTER_LIMIT"
CAUSE_CODE_CARRIER_DELIVERED_AFTER_ESTIMATE = "CARRIER_DELIVERED_AFTER_ESTIMATE"
CAUSE_CODE_ORDER_CANCELED_AFTER_PAYMENT = "ORDER_CANCELED_AFTER_PAYMENT"
CAUSE_CODE_ORDER_UNAVAILABLE_AFTER_PAYMENT = "ORDER_UNAVAILABLE_AFTER_PAYMENT"
CAUSE_CODE_MULTIPLE_PAYMENTS_RECONCILED = "MULTIPLE_PAYMENTS_RECONCILED"
CAUSE_CODE_DELIVERY_WITHIN_ESTIMATE = "DELIVERY_WITHIN_ESTIMATE"
CAUSE_CODE_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE_FOR_POLICY_MATCH"

ACTION_ISSUE_FULL_REFUND = "issue_full_refund"
ACTION_REFUND_FREIGHT = "refund_freight"
ACTION_EXPLAIN_VALID_SPLIT_PAYMENT = "explain_valid_split_payment"
ACTION_REJECT_LATE_REFUND = "reject_late_refund"
ACTION_MANUAL_REVIEW_REQUIRED = "manual_review_required"

PARTY_TYPE_PLATFORM = "platform"
PARTY_TYPE_SELLER = "seller"
PARTY_TYPE_LOGISTICS_PROVIDER = "logistics_provider"


@dataclass(frozen=True)
class ResponsibleParty:
    party_type: str
    party_id: str


# ---------------------------------------------------------------------------
# Agent result records (handoff payloads)
# ---------------------------------------------------------------------------


@dataclass
class OrderSellerResult:
    order_id: str
    order_exists: bool
    order_record: Optional[OrderRecord]
    items: list[ItemRecord]
    seller_ids: list[str]
    item_ids: list[str]
    item_total: Decimal
    freight_total: Decimal
    warnings: list[str] = field(default_factory=list)


@dataclass
class PaymentResult:
    order_id: str
    payments: list[PaymentRecord]
    payment_ids: list[str]
    payment_row_count: int
    payment_total: Decimal
    payment_matches_order_total: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class DeliveryResult:
    order_id: str
    # True/False only when both required timestamps are present; None means
    # "cannot be determined" and must never be treated as on-time.
    delivered_late: Optional[bool]
    late_seller_ids: list[str]
    on_time_seller_ids: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class PolicyResult:
    primary_issue: str
    cause_code: str
    case_status: str
    action: str
    responsible_parties: list[ResponsibleParty]
    recommended_refund: Decimal
    confidence: float
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CaseProcessingError(Exception):
    """Base class for errors that abort processing of a single case."""


class OrderNotFoundError(CaseProcessingError):
    pass


class InvalidCaseInputError(CaseProcessingError):
    pass


class VerificationError(CaseProcessingError):
    """Raised by the Verifier Agent when output fails validation."""
