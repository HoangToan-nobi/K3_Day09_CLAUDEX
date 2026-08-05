from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.coordinator import CoordinatorAgent
from app.data_loader import OlistDataStore
from app.utils.trace import TraceLogger

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "mini_olist"


@pytest.fixture(scope="session")
def mini_store() -> OlistDataStore:
    return OlistDataStore.load(FIXTURES_DIR)


@pytest.fixture()
def trace_logger(tmp_path) -> TraceLogger:
    logger = TraceLogger(tmp_path / "trace.jsonl")
    logger.start()
    yield logger
    logger.close()


@pytest.fixture()
def coordinator(mini_store, trace_logger) -> CoordinatorAgent:
    return CoordinatorAgent(mini_store, trace_logger)


def make_case_input(case_id: str, claimed_order_id: str) -> dict:
    return {
        "case_id": case_id,
        "opened_at": "2018-10-18T00:00:00-03:00",
        "customer_request": {
            "language": "vi",
            "message": "test case",
            "claimed_order_id": claimed_order_id,
        },
        "policy_version": "EC_POLICY_V1",
    }
