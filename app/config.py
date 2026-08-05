"""Central configuration and constants for the dispute-resolution pipeline.

Nothing here reads the filesystem or the clock at import time (besides the
plain constant `BASE_DIR` computation) so this module stays safe to import
from tests without side effects.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_DATA_DIR = BASE_DIR / "data"
DEFAULT_INPUT_DIR = BASE_DIR / "input"
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"
DEFAULT_LOGGING_DIR = BASE_DIR / "logging"

DATA_FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "product_category_name_translation": "product_category_name_translation.csv",
}

# Reconciliation tolerance between payment_total and (item_total + freight_total).
PAYMENT_RECONCILIATION_TOLERANCE = Decimal("0.10")

CURRENCY = "BRL"

# Output list-size limits (README section 6 / "Giới hạn").
MAX_ENTITY_IDS = 5
MAX_EVIDENCE_IDS = 10
MAX_RANKED_CAUSES = 3
MAX_RESPONSIBLE_PARTIES = 3
MAX_RESOLUTION_ACTIONS = 5

CASE_STATUS_ACTION_REQUIRED = "action_required"
CASE_STATUS_NO_ACTION = "no_action"

# Format of entries in affected_entities.payment_ids.
#
# The spec is self-contradictory here: the README section 6 example shows
# `"payment_ids": ["<order_id>:1"]` (bare), while the task brief describes
# payment ids as `payment:<order_id>:<payment_sequential>` (prefixed).
# Evidence ids are unambiguously prefixed (README section 5) and are built
# separately, so this switch only affects affected_entities.payment_ids.
# Set via the EC_PAYMENT_ID_PREFIX env var to A/B the two readings without
# touching code.
PAYMENT_ID_PREFIX = os.environ.get("EC_PAYMENT_ID_PREFIX", "")

PARTY_PLATFORM = "OLIST_PLATFORM"
PARTY_LOGISTICS = "LOGISTICS_PROVIDER"

# Every agent in this pipeline is deterministic Python -- no LLM decides
# amounts or root causes. Kept here (not in .env) per README section 9.4:
# "Tên model sử dụng phải được khai báo rõ trong source code".
MODEL_NAME = "deterministic-python-rules"
MODEL_PARAMETER_SIZE = "0"
FRAMEWORK_NAME = "Python (pandas + stdlib)"
