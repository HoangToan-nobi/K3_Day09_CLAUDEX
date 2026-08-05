"""Verifier Agent.

Last stop before a case is written to `output/`. Independently re-checks
the coordinator's assembled output dict against the data store and against
a hard-coded expectation table (not the PolicyAgent's own RuleOutcome
objects), so a bug inside PolicyAgent cannot also fool the verifier.

Any failure raises `VerificationError` with a message listing every
problem found -- callers must not silently swallow it.
"""

from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from typing import Any

from app.config import (
    CASE_STATUS_ACTION_REQUIRED,
    CASE_STATUS_NO_ACTION,
    CURRENCY,
    MAX_ENTITY_IDS,
    MAX_EVIDENCE_IDS,
    MAX_RANKED_CAUSES,
    MAX_RESOLUTION_ACTIONS,
    MAX_RESPONSIBLE_PARTIES,
)
from app.data_loader import OlistDataStore
from app.schemas import (
    ACTION_EXPLAIN_VALID_SPLIT_PAYMENT,
    ACTION_ISSUE_FULL_REFUND,
    ACTION_MANUAL_REVIEW_REQUIRED,
    ACTION_REFUND_FREIGHT,
    ACTION_REJECT_LATE_REFUND,
    DeliveryResult,
    OrderSellerResult,
    PaymentResult,
    PolicyResult,
    PRIMARY_ISSUE_CANCELED_ORDER_PAID,
    PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS,
    PRIMARY_ISSUE_LATE_DELIVERY_SELLER,
    PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID,
    PRIMARY_ISSUE_UNCLASSIFIED,
    PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM,
    PRIMARY_ISSUE_VALID_SPLIT_PAYMENT,
    VerificationError,
)

EVIDENCE_ORDER_RE = re.compile(r"^order:([^:]+)$")
EVIDENCE_ITEM_RE = re.compile(r"^item:([^:]+):(\d+)$")
EVIDENCE_PAYMENT_RE = re.compile(r"^payment:([^:]+):(\d+)$")
EVIDENCE_SELLER_RE = re.compile(r"^seller:([^:]+)$")
EVIDENCE_POLICY_RE = re.compile(r"^policy:([A-Z_]+)$")

# Independent expectation table -- deliberately duplicated from policy_agent
# so a mistake in one does not automatically pass the other's check.
EXPECTED_ACTION_BY_ISSUE = {
    PRIMARY_ISSUE_CANCELED_ORDER_PAID: ACTION_ISSUE_FULL_REFUND,
    PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID: ACTION_ISSUE_FULL_REFUND,
    PRIMARY_ISSUE_LATE_DELIVERY_SELLER: ACTION_REFUND_FREIGHT,
    PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS: ACTION_REFUND_FREIGHT,
    PRIMARY_ISSUE_VALID_SPLIT_PAYMENT: ACTION_EXPLAIN_VALID_SPLIT_PAYMENT,
    PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM: ACTION_REJECT_LATE_REFUND,
    PRIMARY_ISSUE_UNCLASSIFIED: ACTION_MANUAL_REVIEW_REQUIRED,
}

EXPECTED_CASE_STATUS_BY_ISSUE = {
    PRIMARY_ISSUE_CANCELED_ORDER_PAID: CASE_STATUS_ACTION_REQUIRED,
    PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID: CASE_STATUS_ACTION_REQUIRED,
    PRIMARY_ISSUE_LATE_DELIVERY_SELLER: CASE_STATUS_ACTION_REQUIRED,
    PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS: CASE_STATUS_ACTION_REQUIRED,
    PRIMARY_ISSUE_VALID_SPLIT_PAYMENT: CASE_STATUS_NO_ACTION,
    PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM: CASE_STATUS_NO_ACTION,
    PRIMARY_ISSUE_UNCLASSIFIED: CASE_STATUS_NO_ACTION,
}

# Which financial basis each primary_issue's refund must equal: "payment",
# "freight" or "zero".
EXPECTED_REFUND_BASIS_BY_ISSUE = {
    PRIMARY_ISSUE_CANCELED_ORDER_PAID: "payment",
    PRIMARY_ISSUE_UNAVAILABLE_ORDER_PAID: "payment",
    PRIMARY_ISSUE_LATE_DELIVERY_SELLER: "freight",
    PRIMARY_ISSUE_LATE_DELIVERY_LOGISTICS: "freight",
    PRIMARY_ISSUE_VALID_SPLIT_PAYMENT: "zero",
    PRIMARY_ISSUE_UNSUPPORTED_LATE_CLAIM: "zero",
    PRIMARY_ISSUE_UNCLASSIFIED: "zero",
}

MONEY_TOLERANCE = 0.005


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class VerifierAgent:
    def __init__(self, store: OlistDataStore):
        self.store = store

    def verify(
        self,
        case_input: dict,
        output: dict,
        order_result: OrderSellerResult,
        payment_result: PaymentResult,
        delivery_result: DeliveryResult,
        policy_result: PolicyResult,
    ) -> None:
        errors: list[str] = []

        self._check_schema(output, errors)
        if errors:
            # Structural failures make every later check unreliable (missing
            # keys would raise KeyError), so stop here with what we found.
            raise VerificationError("; ".join(errors))

        self._check_case_id(case_input, output, errors)
        self._check_entity_existence(output, errors)
        self._check_limits(output, errors)
        self._check_evidence(output, policy_result, errors)
        self._check_financials(output, order_result, payment_result, errors)
        self._check_refund_and_action(output, policy_result, errors)
        self._check_confidence(output, errors)
        self._check_json_serializable(output, errors)

        if errors:
            raise VerificationError("; ".join(errors))

    # -- individual checks --------------------------------------------

    @staticmethod
    def _check_schema(output: dict, errors: list[str]) -> None:
        required_top = {
            "case_id": str,
            "assessment": dict,
            "affected_entities": dict,
            "root_cause_analysis": dict,
            "evidence_ids": list,
            "financial_resolution": dict,
            "resolution_actions": list,
        }
        for key, expected_type in required_top.items():
            if key not in output:
                errors.append(f"missing top-level field '{key}'")
            elif not isinstance(output[key], expected_type):
                errors.append(f"field '{key}' has wrong type: expected {expected_type.__name__}")
        if errors:
            return

        assessment_fields = {"primary_issue": str, "case_status": str, "confidence": (int, float)}
        for key, expected_type in assessment_fields.items():
            if key not in output["assessment"]:
                errors.append(f"missing assessment.{key}")
            elif not isinstance(output["assessment"][key], expected_type):
                errors.append(f"assessment.{key} has wrong type")

        entity_fields = ["order_ids", "item_ids", "seller_ids", "payment_ids"]
        for key in entity_fields:
            if key not in output["affected_entities"]:
                errors.append(f"missing affected_entities.{key}")
            elif not isinstance(output["affected_entities"][key], list):
                errors.append(f"affected_entities.{key} must be a list")

        if "ranked_causes" not in output["root_cause_analysis"]:
            errors.append("missing root_cause_analysis.ranked_causes")
        if "responsible_parties" not in output["root_cause_analysis"]:
            errors.append("missing root_cause_analysis.responsible_parties")

        financial_fields = [
            "currency",
            "item_total_brl",
            "freight_total_brl",
            "payment_total_brl",
            "recommended_refund_brl",
        ]
        for key in financial_fields:
            if key not in output["financial_resolution"]:
                errors.append(f"missing financial_resolution.{key}")
        for key in financial_fields[1:]:
            value = output["financial_resolution"].get(key)
            if value is not None and not _is_number(value):
                errors.append(f"financial_resolution.{key} must be a number, got {type(value).__name__}")

    @staticmethod
    def _check_case_id(case_input: dict, output: dict, errors: list[str]) -> None:
        expected = case_input.get("case_id")
        actual = output.get("case_id")
        if actual != expected:
            errors.append(f"case_id mismatch: input={expected!r} output={actual!r}")

    def _check_entity_existence(self, output: dict, errors: list[str]) -> None:
        entities = output["affected_entities"]
        for order_id in entities.get("order_ids", []):
            if not self.store.order_exists(order_id):
                errors.append(f"affected_entities.order_ids references unknown order '{order_id}'")

        for item_ref in entities.get("item_ids", []):
            order_id, item_id = self._split_item_ref(item_ref, errors, "affected_entities.item_ids")
            if order_id is not None and not self.store.item_exists(order_id, item_id):
                errors.append(f"affected_entities.item_ids references unknown item '{item_ref}'")

        for seller_id in entities.get("seller_ids", []):
            if not self.store.seller_exists(seller_id):
                errors.append(f"affected_entities.seller_ids references unknown seller '{seller_id}'")

        for payment_ref in entities.get("payment_ids", []):
            # Accept either spec reading (see config.PAYMENT_ID_PREFIX); the
            # underlying order_id/sequential must still resolve to a real row.
            bare_ref = payment_ref[len("payment:"):] if payment_ref.startswith("payment:") else payment_ref
            order_id, seq = self._split_item_ref(bare_ref, errors, "affected_entities.payment_ids")
            if order_id is not None and not self.store.payment_exists(order_id, seq):
                errors.append(f"affected_entities.payment_ids references unknown payment '{payment_ref}'")

    @staticmethod
    def _split_item_ref(ref: str, errors: list[str], field_name: str) -> tuple[str | None, int | None]:
        parts = ref.split(":")
        if len(parts) != 2 or not parts[1].isdigit():
            errors.append(f"{field_name} entry '{ref}' is not in '<order_id>:<n>' format")
            return None, None
        return parts[0], int(parts[1])

    @staticmethod
    def _check_limits(output: dict, errors: list[str]) -> None:
        entities = output["affected_entities"]
        for key in ("order_ids", "item_ids", "seller_ids", "payment_ids"):
            if len(entities.get(key, [])) > MAX_ENTITY_IDS:
                errors.append(f"affected_entities.{key} exceeds max of {MAX_ENTITY_IDS}")
        if len(output["evidence_ids"]) > MAX_EVIDENCE_IDS:
            errors.append(f"evidence_ids exceeds max of {MAX_EVIDENCE_IDS}")
        if len(output["root_cause_analysis"]["ranked_causes"]) > MAX_RANKED_CAUSES:
            errors.append(f"ranked_causes exceeds max of {MAX_RANKED_CAUSES}")
        if len(output["root_cause_analysis"]["responsible_parties"]) > MAX_RESPONSIBLE_PARTIES:
            errors.append(f"responsible_parties exceeds max of {MAX_RESPONSIBLE_PARTIES}")
        if len(output["resolution_actions"]) > MAX_RESOLUTION_ACTIONS:
            errors.append(f"resolution_actions exceeds max of {MAX_RESOLUTION_ACTIONS}")

    def _check_evidence(self, output: dict, policy_result: PolicyResult, errors: list[str]) -> None:
        for evidence_id in output["evidence_ids"]:
            if m := EVIDENCE_ORDER_RE.match(evidence_id):
                if not self.store.order_exists(m.group(1)):
                    errors.append(f"evidence '{evidence_id}' references unknown order")
            elif m := EVIDENCE_ITEM_RE.match(evidence_id):
                if not self.store.item_exists(m.group(1), int(m.group(2))):
                    errors.append(f"evidence '{evidence_id}' references unknown item")
            elif m := EVIDENCE_PAYMENT_RE.match(evidence_id):
                if not self.store.payment_exists(m.group(1), int(m.group(2))):
                    errors.append(f"evidence '{evidence_id}' references unknown payment")
            elif m := EVIDENCE_SELLER_RE.match(evidence_id):
                if not self.store.seller_exists(m.group(1)):
                    errors.append(f"evidence '{evidence_id}' references unknown seller")
            elif m := EVIDENCE_POLICY_RE.match(evidence_id):
                if m.group(1) != policy_result.cause_code:
                    errors.append(
                        f"evidence '{evidence_id}' cause_code does not match "
                        f"the actual conclusion '{policy_result.cause_code}'"
                    )
            else:
                errors.append(f"evidence '{evidence_id}' has invalid format")

    @staticmethod
    def _check_financials(
        output: dict,
        order_result: OrderSellerResult,
        payment_result: PaymentResult,
        errors: list[str],
    ) -> None:
        financial = output["financial_resolution"]
        if financial.get("currency") != CURRENCY:
            errors.append(f"financial_resolution.currency must be '{CURRENCY}'")

        expected_item_total = round(float(order_result.item_total), 2)
        expected_freight_total = round(float(order_result.freight_total), 2)
        expected_payment_total = round(float(payment_result.payment_total), 2)

        checks = [
            ("item_total_brl", expected_item_total),
            ("freight_total_brl", expected_freight_total),
            ("payment_total_brl", expected_payment_total),
        ]
        for field_name, expected in checks:
            actual = financial.get(field_name)
            if not _is_number(actual) or not math.isclose(actual, expected, abs_tol=MONEY_TOLERANCE):
                errors.append(
                    f"financial_resolution.{field_name}={actual!r} does not match computed value {expected!r}"
                )

    @staticmethod
    def _check_refund_and_action(output: dict, policy_result: PolicyResult, errors: list[str]) -> None:
        primary_issue = output["assessment"]["primary_issue"]
        case_status = output["assessment"]["case_status"]
        refund = output["financial_resolution"].get("recommended_refund_brl")
        actions = output["resolution_actions"]

        expected_action = EXPECTED_ACTION_BY_ISSUE.get(primary_issue)
        expected_status = EXPECTED_CASE_STATUS_BY_ISSUE.get(primary_issue)
        expected_basis = EXPECTED_REFUND_BASIS_BY_ISSUE.get(primary_issue)

        if expected_action is None:
            errors.append(f"primary_issue '{primary_issue}' is not a recognized policy outcome")
            return

        if case_status != expected_status:
            errors.append(
                f"case_status '{case_status}' inconsistent with primary_issue '{primary_issue}' "
                f"(expected '{expected_status}')"
            )
        if expected_action not in actions:
            errors.append(
                f"resolution_actions {actions} missing expected action '{expected_action}' "
                f"for primary_issue '{primary_issue}'"
            )

        if not _is_number(refund):
            errors.append("financial_resolution.recommended_refund_brl must be a number")
            return

        if expected_basis == "zero":
            if not math.isclose(refund, 0.0, abs_tol=MONEY_TOLERANCE):
                errors.append(f"recommended_refund_brl should be 0.0 for '{primary_issue}', got {refund}")
        elif expected_basis == "payment":
            expected_refund = round(float(policy_result.recommended_refund), 2)
            if not math.isclose(refund, expected_refund, abs_tol=MONEY_TOLERANCE):
                errors.append(
                    f"recommended_refund_brl={refund} does not match payment_total-based refund {expected_refund}"
                )
        elif expected_basis == "freight":
            expected_refund = round(float(policy_result.recommended_refund), 2)
            if not math.isclose(refund, expected_refund, abs_tol=MONEY_TOLERANCE):
                errors.append(
                    f"recommended_refund_brl={refund} does not match freight_total-based refund {expected_refund}"
                )

    @staticmethod
    def _check_confidence(output: dict, errors: list[str]) -> None:
        confidence = output["assessment"]["confidence"]
        if not _is_number(confidence) or not (0.0 <= float(confidence) <= 1.0):
            errors.append(f"confidence {confidence!r} is out of range [0, 1]")

    @staticmethod
    def _check_json_serializable(output: dict, errors: list[str]) -> None:
        try:
            json.dumps(output)
        except (TypeError, ValueError) as exc:
            errors.append(f"output is not JSON-serializable: {exc}")
