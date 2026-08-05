"""Loads the Olist CSV extract and exposes it as lookup indices.

This is the only module allowed to touch `data/*.csv`. Every agent talks to
an `OlistDataStore` instance instead of pandas directly, so the parsing
rules (timestamp coercion, Decimal money, dedup/sort of unordered CSV rows)
live in exactly one place.

Two ways to build a store:

- `OlistDataStore.load(data_dir)` reads the real CSV files.
- `OlistDataStore.from_dataframes(...)` builds the same indices from
  in-memory DataFrames, which is what the unit tests use to exercise edge
  cases (multi-seller orders, null timestamps, missing payments, ...)
  without needing the full Olist dataset.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import pandas as pd

from app.config import DATA_FILES
from app.schemas import (
    CustomerRecord,
    ItemRecord,
    OrderRecord,
    PaymentRecord,
    ProductRecord,
    ReviewRecord,
    SellerRecord,
)

ORDER_TIMESTAMP_COLUMNS = [
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]


def _clean_str(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _to_decimal(value: object) -> Decimal:
    text = _clean_str(value)
    if text is None:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0")


def _to_int(value: object) -> Optional[int]:
    text = _clean_str(value)
    if text is None:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _none_if_nat(value: object) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _read_csv(data_dir: Path, filename: str) -> pd.DataFrame:
    path = data_dir / filename
    return pd.read_csv(path, dtype=str, keep_default_na=True)


@dataclass
class OlistDataStore:
    orders: dict[str, OrderRecord] = field(default_factory=dict)
    items_by_order: dict[str, list[ItemRecord]] = field(default_factory=dict)
    payments_by_order: dict[str, list[PaymentRecord]] = field(default_factory=dict)
    sellers: dict[str, SellerRecord] = field(default_factory=dict)
    # Loaded per README section 1 ("Tạo index theo ... customer_id") and
    # kept available via join-oriented accessors below. Not consumed by the
    # policy rule chain (which only needs orders/items/payments/sellers),
    # but present so evidence/analysis can be extended without touching the
    # data-access layer again.
    customers: dict[str, CustomerRecord] = field(default_factory=dict)
    products: dict[str, ProductRecord] = field(default_factory=dict)
    reviews_by_order: dict[str, list[ReviewRecord]] = field(default_factory=dict)
    category_translation: dict[str, str] = field(default_factory=dict)
    load_warnings: list[str] = field(default_factory=list)

    # -- construction ------------------------------------------------------

    @classmethod
    def load(cls, data_dir: Path | str) -> "OlistDataStore":
        data_dir = Path(data_dir)
        orders_df = _read_csv(data_dir, DATA_FILES["orders"])
        items_df = _read_csv(data_dir, DATA_FILES["order_items"])
        payments_df = _read_csv(data_dir, DATA_FILES["order_payments"])
        sellers_df = _read_csv(data_dir, DATA_FILES["sellers"])
        customers_df = _read_csv(data_dir, DATA_FILES["customers"])
        products_df = _read_csv(data_dir, DATA_FILES["products"])
        reviews_df = _read_csv(data_dir, DATA_FILES["order_reviews"])
        category_df = _read_csv(data_dir, DATA_FILES["product_category_name_translation"])
        return cls.from_dataframes(
            orders_df,
            items_df,
            payments_df,
            sellers_df,
            customers_df=customers_df,
            products_df=products_df,
            reviews_df=reviews_df,
            category_df=category_df,
        )

    @classmethod
    def from_dataframes(
        cls,
        orders_df: pd.DataFrame,
        items_df: pd.DataFrame,
        payments_df: pd.DataFrame,
        sellers_df: pd.DataFrame,
        customers_df: Optional[pd.DataFrame] = None,
        products_df: Optional[pd.DataFrame] = None,
        reviews_df: Optional[pd.DataFrame] = None,
        category_df: Optional[pd.DataFrame] = None,
    ) -> "OlistDataStore":
        warnings: list[str] = []
        orders = cls._build_orders_index(orders_df, warnings)
        items_by_order = cls._build_items_index(items_df, warnings)
        payments_by_order = cls._build_payments_index(payments_df, warnings)
        sellers = cls._build_sellers_index(sellers_df, warnings)
        customers = cls._build_customers_index(customers_df, warnings) if customers_df is not None else {}
        products = cls._build_products_index(products_df) if products_df is not None else {}
        reviews_by_order = cls._build_reviews_index(reviews_df) if reviews_df is not None else {}
        category_translation = (
            cls._build_category_translation(category_df) if category_df is not None else {}
        )
        return cls(
            orders=orders,
            items_by_order=items_by_order,
            payments_by_order=payments_by_order,
            customers=customers,
            products=products,
            reviews_by_order=reviews_by_order,
            category_translation=category_translation,
            sellers=sellers,
            load_warnings=warnings,
        )

    @staticmethod
    def _build_orders_index(df: pd.DataFrame, warnings: list[str]) -> dict[str, OrderRecord]:
        df = df.copy()
        for col in ORDER_TIMESTAMP_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        index: dict[str, OrderRecord] = {}
        for rec in df.to_dict(orient="records"):
            order_id = _clean_str(rec.get("order_id"))
            if not order_id:
                warnings.append("orders: skipped row with empty order_id")
                continue
            if order_id in index:
                warnings.append(f"orders: duplicate order_id={order_id}, kept first occurrence")
                continue
            index[order_id] = OrderRecord(
                order_id=order_id,
                customer_id=_clean_str(rec.get("customer_id")),
                order_status=_clean_str(rec.get("order_status")),
                order_purchase_timestamp=_none_if_nat(rec.get("order_purchase_timestamp")),
                order_approved_at=_none_if_nat(rec.get("order_approved_at")),
                order_delivered_carrier_date=_none_if_nat(rec.get("order_delivered_carrier_date")),
                order_delivered_customer_date=_none_if_nat(rec.get("order_delivered_customer_date")),
                order_estimated_delivery_date=_none_if_nat(rec.get("order_estimated_delivery_date")),
            )
        return index

    @staticmethod
    def _build_items_index(df: pd.DataFrame, warnings: list[str]) -> dict[str, list[ItemRecord]]:
        df = df.copy()
        if "shipping_limit_date" in df.columns:
            df["shipping_limit_date"] = pd.to_datetime(df["shipping_limit_date"], errors="coerce")
        grouped: dict[str, list[ItemRecord]] = defaultdict(list)
        for rec in df.to_dict(orient="records"):
            order_id = _clean_str(rec.get("order_id"))
            order_item_id = _to_int(rec.get("order_item_id"))
            if not order_id or order_item_id is None:
                warnings.append("order_items: skipped row with missing order_id/order_item_id")
                continue
            grouped[order_id].append(
                ItemRecord(
                    order_id=order_id,
                    order_item_id=order_item_id,
                    product_id=_clean_str(rec.get("product_id")),
                    seller_id=_clean_str(rec.get("seller_id")),
                    shipping_limit_date=_none_if_nat(rec.get("shipping_limit_date")),
                    price=_to_decimal(rec.get("price")),
                    freight_value=_to_decimal(rec.get("freight_value")),
                )
            )
        result: dict[str, list[ItemRecord]] = {}
        for order_id, items in grouped.items():
            items.sort(key=lambda item: item.order_item_id)
            result[order_id] = items
        return result

    @staticmethod
    def _build_payments_index(df: pd.DataFrame, warnings: list[str]) -> dict[str, list[PaymentRecord]]:
        grouped: dict[str, list[PaymentRecord]] = defaultdict(list)
        for rec in df.to_dict(orient="records"):
            order_id = _clean_str(rec.get("order_id"))
            payment_sequential = _to_int(rec.get("payment_sequential"))
            if not order_id or payment_sequential is None:
                warnings.append("order_payments: skipped row with missing order_id/payment_sequential")
                continue
            grouped[order_id].append(
                PaymentRecord(
                    order_id=order_id,
                    payment_sequential=payment_sequential,
                    payment_type=_clean_str(rec.get("payment_type")),
                    payment_installments=_to_int(rec.get("payment_installments")),
                    payment_value=_to_decimal(rec.get("payment_value")),
                )
            )
        result: dict[str, list[PaymentRecord]] = {}
        for order_id, payments in grouped.items():
            payments.sort(key=lambda payment: payment.payment_sequential)
            result[order_id] = payments
        return result

    @staticmethod
    def _build_sellers_index(df: pd.DataFrame, warnings: list[str]) -> dict[str, SellerRecord]:
        index: dict[str, SellerRecord] = {}
        for rec in df.to_dict(orient="records"):
            seller_id = _clean_str(rec.get("seller_id"))
            if not seller_id:
                warnings.append("sellers: skipped row with empty seller_id")
                continue
            if seller_id in index:
                warnings.append(f"sellers: duplicate seller_id={seller_id}, kept first occurrence")
                continue
            index[seller_id] = SellerRecord(
                seller_id=seller_id,
                seller_zip_code_prefix=_clean_str(rec.get("seller_zip_code_prefix")),
                seller_city=_clean_str(rec.get("seller_city")),
                seller_state=_clean_str(rec.get("seller_state")),
            )
        return index

    @staticmethod
    def _build_customers_index(df: pd.DataFrame, warnings: list[str]) -> dict[str, CustomerRecord]:
        index: dict[str, CustomerRecord] = {}
        for rec in df.to_dict(orient="records"):
            customer_id = _clean_str(rec.get("customer_id"))
            if not customer_id:
                warnings.append("customers: skipped row with empty customer_id")
                continue
            if customer_id in index:
                warnings.append(f"customers: duplicate customer_id={customer_id}, kept first occurrence")
                continue
            index[customer_id] = CustomerRecord(
                customer_id=customer_id,
                customer_unique_id=_clean_str(rec.get("customer_unique_id")),
                customer_zip_code_prefix=_clean_str(rec.get("customer_zip_code_prefix")),
                customer_city=_clean_str(rec.get("customer_city")),
                customer_state=_clean_str(rec.get("customer_state")),
            )
        return index

    @staticmethod
    def _build_products_index(df: pd.DataFrame) -> dict[str, ProductRecord]:
        index: dict[str, ProductRecord] = {}
        for rec in df.to_dict(orient="records"):
            product_id = _clean_str(rec.get("product_id"))
            if not product_id or product_id in index:
                continue
            index[product_id] = ProductRecord(
                product_id=product_id,
                product_category_name=_clean_str(rec.get("product_category_name")),
            )
        return index

    @staticmethod
    def _build_reviews_index(df: pd.DataFrame) -> dict[str, list[ReviewRecord]]:
        grouped: dict[str, list[ReviewRecord]] = defaultdict(list)
        for rec in df.to_dict(orient="records"):
            order_id = _clean_str(rec.get("order_id"))
            review_id = _clean_str(rec.get("review_id"))
            if not order_id or not review_id:
                continue
            grouped[order_id].append(
                ReviewRecord(
                    review_id=review_id,
                    order_id=order_id,
                    review_score=_to_int(rec.get("review_score")),
                )
            )
        return dict(grouped)

    @staticmethod
    def _build_category_translation(df: pd.DataFrame) -> dict[str, str]:
        translation: dict[str, str] = {}
        for rec in df.to_dict(orient="records"):
            name_pt = _clean_str(rec.get("product_category_name"))
            name_en = _clean_str(rec.get("product_category_name_english"))
            if name_pt:
                translation[name_pt] = name_en or name_pt
        return translation

    # -- accessors -----------------------------------------------------

    def order_exists(self, order_id: str) -> bool:
        return order_id in self.orders

    def get_order(self, order_id: str) -> Optional[OrderRecord]:
        return self.orders.get(order_id)

    def get_items(self, order_id: str) -> list[ItemRecord]:
        return list(self.items_by_order.get(order_id, []))

    def item_exists(self, order_id: str, order_item_id: int) -> bool:
        return any(item.order_item_id == order_item_id for item in self.items_by_order.get(order_id, []))

    def get_payments(self, order_id: str) -> list[PaymentRecord]:
        return list(self.payments_by_order.get(order_id, []))

    def payment_exists(self, order_id: str, payment_sequential: int) -> bool:
        return any(
            payment.payment_sequential == payment_sequential
            for payment in self.payments_by_order.get(order_id, [])
        )

    def get_seller(self, seller_id: str) -> Optional[SellerRecord]:
        return self.sellers.get(seller_id)

    def seller_exists(self, seller_id: str) -> bool:
        return seller_id in self.sellers

    def get_customer(self, customer_id: str) -> Optional[CustomerRecord]:
        return self.customers.get(customer_id)

    def get_product(self, product_id: str) -> Optional[ProductRecord]:
        return self.products.get(product_id)

    def get_reviews(self, order_id: str) -> list[ReviewRecord]:
        return list(self.reviews_by_order.get(order_id, []))

    def translate_category(self, category_name_pt: str) -> Optional[str]:
        return self.category_translation.get(category_name_pt)
