"""Coordinator Agent.

Owns the end-to-end handoff chain for a single case:

    input case -> Order/Seller Agent -> Payment Agent -> Delivery Agent
                -> Policy Agent -> (output formatting) -> Verifier Agent

Every handoff is logged to the trace. Any failure (bad input, unknown
order, failed verification) is raised as a `CaseProcessingError` subclass
-- the coordinator itself never decides "unknown -> treat as success"; it
is the CLI's job to catch these per-case and keep going.
"""

from __future__ import annotations

from app.agents.delivery_agent import DeliveryAgent
from app.agents.order_seller_agent import OrderSellerAgent
from app.agents.payment_agent import PaymentAgent
from app.agents.policy_agent import PolicyAgent
from app.agents.verifier_agent import VerifierAgent
from app.data_loader import OlistDataStore
from app.schemas import InvalidCaseInputError, OrderNotFoundError
from app.utils.output_builder import build_output
from app.utils.trace import TraceLogger


class CoordinatorAgent:
    def __init__(self, store: OlistDataStore, trace: TraceLogger):
        self.store = store
        self.trace = trace
        self.order_agent = OrderSellerAgent(store)
        self.payment_agent = PaymentAgent(store)
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent()
        self.verifier = VerifierAgent(store)

    def process_case(self, case_input: dict) -> dict:
        case_id = self._extract_case_id(case_input)
        claimed_order_id = self._extract_claimed_order_id(case_input, case_id)

        self.trace.log(
            case_id=case_id,
            agent="coordinator",
            event="case_received",
            input_summary={"claimed_order_id": claimed_order_id},
        )

        order_result = self.order_agent.analyze(claimed_order_id)
        self.trace.log(
            case_id=case_id,
            agent="order_seller_agent",
            event="handoff_to_payment_agent",
            input_summary={"order_id": claimed_order_id},
            output_summary={
                "order_exists": order_result.order_exists,
                "order_status": (
                    order_result.order_record.order_status if order_result.order_record else None
                ),
                "item_count": len(order_result.items),
                "seller_ids": order_result.seller_ids,
                "item_total": str(order_result.item_total),
                "freight_total": str(order_result.freight_total),
                "warnings": order_result.warnings,
            },
        )

        if not order_result.order_exists:
            raise OrderNotFoundError(
                f"case {case_id}: claimed_order_id '{claimed_order_id}' does not exist in orders dataset"
            )

        payment_result = self.payment_agent.analyze(
            claimed_order_id, order_result.item_total, order_result.freight_total
        )
        self.trace.log(
            case_id=case_id,
            agent="payment_agent",
            event="handoff_to_delivery_agent",
            input_summary={
                "item_total": str(order_result.item_total),
                "freight_total": str(order_result.freight_total),
            },
            output_summary={
                "payment_row_count": payment_result.payment_row_count,
                "payment_total": str(payment_result.payment_total),
                "payment_matches_order_total": payment_result.payment_matches_order_total,
                "warnings": payment_result.warnings,
            },
        )

        delivery_result = self.delivery_agent.analyze(
            claimed_order_id, order_result.order_record, order_result.items
        )
        self.trace.log(
            case_id=case_id,
            agent="delivery_agent",
            event="handoff_to_policy_agent",
            output_summary={
                "delivered_late": delivery_result.delivered_late,
                "late_seller_ids": delivery_result.late_seller_ids,
                "warnings": delivery_result.warnings,
            },
        )

        policy_result = self.policy_agent.decide(order_result, payment_result, delivery_result)
        self.trace.log(
            case_id=case_id,
            agent="policy_agent",
            event="handoff_to_verifier_agent",
            output_summary={
                "primary_issue": policy_result.primary_issue,
                "cause_code": policy_result.cause_code,
                "case_status": policy_result.case_status,
                "action": policy_result.action,
                "recommended_refund": str(policy_result.recommended_refund),
                "confidence": policy_result.confidence,
            },
        )

        output = build_output(case_id, order_result, payment_result, delivery_result, policy_result)

        self.verifier.verify(
            case_input, output, order_result, payment_result, delivery_result, policy_result
        )
        self.trace.log(
            case_id=case_id,
            agent="verifier_agent",
            event="verified_ok",
            output_summary={"primary_issue": output["assessment"]["primary_issue"]},
        )

        return output

    @staticmethod
    def _extract_case_id(case_input: dict) -> str:
        case_id = case_input.get("case_id")
        if not case_id or not isinstance(case_id, str):
            raise InvalidCaseInputError("case input missing required string field 'case_id'")
        return case_id

    @staticmethod
    def _extract_claimed_order_id(case_input: dict, case_id: str) -> str:
        try:
            claimed_order_id = case_input["customer_request"]["claimed_order_id"]
        except (KeyError, TypeError) as exc:
            raise InvalidCaseInputError(
                f"case {case_id}: missing customer_request.claimed_order_id"
            ) from exc
        if not claimed_order_id or not isinstance(claimed_order_id, str):
            raise InvalidCaseInputError(f"case {case_id}: claimed_order_id must be a non-empty string")
        return claimed_order_id
