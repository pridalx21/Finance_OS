"""Purchases Plugin — Einkaufserfassung (Barcode + Kassenbon + Kategorisierung).

Erfasst Einkaufsvorgänge mit Kaufpositionen, Produktstammdaten, Belegen und
kontextabhängiger Kategorisierung. Verknüpft den Einkauf mit der bestehenden
Finanzbuchhaltung (eine Ausgabe pro Einkauf), verhindert Doppelbuchungen über
Idempotenzschlüssel und speichert Unsicherheiten explizit.

Fachliche Regeln
----------------
* Beträge in Rappen (Integer), Mengen/Stückpreise als Decimal.
* Ein Einkauf erzeugt höchstens eine Finanztransaktion (Ausgabe) für den
  Gesamtbetrag. Wiederholter Import mit demselben Schlüssel erzeugt keine
  zweite Buchung.
* Der Kassenbon ist die primäre Quelle für den tatsächlich bezahlten Betrag.
* Produktstandardkategorie ist nur ein Vorschlag; die konkrete Kategorisierung
  der Position hat Vorrang und historische Positionen bleiben unverändert.
* Kategorisierung ist deterministisch und ohne LLM.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    Index,
    func,
)
from sqlalchemy.orm import Session, relationship

from app.db.database import Base, get_db
from app.plugins import FinancePlugin
from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.schemas.transaction import TransactionCreate
from app.services.transaction_service import TransactionService, IdempotencyConflict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _fingerprint(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PURCHASE_STATUS_DRAFT = "DRAFT"
PURCHASE_STATUS_REVIEWED = "REVIEWED"
PURCHASE_STATUS_POSTED = "POSTED"
PURCHASE_STATUSES = (PURCHASE_STATUS_DRAFT, PURCHASE_STATUS_REVIEWED, PURCHASE_STATUS_POSTED)

PURCHASE_SOURCE_MANUAL = "MANUAL"
PURCHASE_SOURCE_BARCODE = "BARCODE"
PURCHASE_SOURCE_OCR = "OCR"
PURCHASE_SOURCE_MIXED = "MIXED"

CAT_SOURCE_MANUAL = "MANUAL"
CAT_SOURCE_RULE = "RULE"
CAT_SOURCE_PRODUCT_DEFAULT = "PRODUCT_DEFAULT"
CAT_SOURCE_SUGGESTED = "SUGGESTED"
CAT_SOURCE_UNKNOWN = "UNKNOWN"

RECEIPT_STATUS_PENDING = "PENDING"
RECEIPT_STATUS_PROCESSED = "PROCESSED"
RECEIPT_STATUS_FAILED = "FAILED"

RULE_SCOPE_PRODUCT = "PRODUCT"
RULE_SCOPE_MERCHANT = "MERCHANT"
RULE_SCOPE_TEXT = "TEXT"
RULE_SCOPE_PURPOSE = "PURPOSE"
RULE_SCOPE_PROJECT = "PROJECT"

SCOPE_RANK = {
    RULE_SCOPE_PRODUCT: 5,
    RULE_SCOPE_MERCHANT: 4,
    RULE_SCOPE_TEXT: 3,
    RULE_SCOPE_PURPOSE: 2,
    RULE_SCOPE_PROJECT: 1,
}

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Product(Base):
    __tablename__ = "plugin_purchases_products"

    id = Column(String, primary_key=True, default=_uuid)
    gtin = Column(String(32), nullable=True, unique=True)
    normalized_name = Column(String(300), nullable=False)
    brand = Column(String(200), nullable=True)
    package_size = Column(String(100), nullable=True)
    source = Column(String(60), nullable=True)
    default_category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=_utcnow)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    default_category = relationship("Category")
    items = relationship("PurchaseItem", back_populates="product")

    __table_args__ = (Index("ix_plugin_purchases_products_gtin", "gtin"),)


class Receipt(Base):
    __tablename__ = "plugin_purchases_receipts"

    id = Column(String, primary_key=True, default=_uuid)
    file_reference = Column(String(500), nullable=True)
    ocr_text = Column(Text, nullable=True)
    merchant = Column(String(200), nullable=True)
    purchased_at = Column(DateTime, nullable=True)
    total_cents = Column(Integer, nullable=True)
    currency = Column(String(3), nullable=True)
    processing_status = Column(String(20), nullable=False, default=RECEIPT_STATUS_PENDING)
    purchase_id = Column(String, nullable=True)  # soft link, no FK to avoid circular constraint
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    # purchase link is resolved via Purchase.receipt_id / receipt.purchase_id (soft)


class Purchase(Base):
    __tablename__ = "plugin_purchases_purchases"

    id = Column(String, primary_key=True, default=_uuid)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    merchant = Column(String(200), nullable=True)
    purchased_at = Column(DateTime, nullable=True)
    currency = Column(String(3), nullable=False, default="CHF")
    total_cents = Column(Integer, nullable=True)
    items_total_cents = Column(Integer, nullable=True)
    transaction_id = Column(String, ForeignKey("transactions.id"), nullable=True)
    status = Column(String(20), nullable=False, default=PURCHASE_STATUS_DRAFT)
    receipt_id = Column(String, ForeignKey("plugin_purchases_receipts.id"), nullable=True)
    source = Column(String(20), nullable=False, default=PURCHASE_SOURCE_MANUAL)
    idempotency_key = Column(String, unique=True, nullable=True)
    idempotency_fingerprint = Column(String(64), nullable=True)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    archived_at = Column(DateTime, nullable=True)

    account = relationship("Account")
    transaction = relationship("Transaction")
    receipt = relationship("Receipt", foreign_keys=[receipt_id])
    items = relationship(
        "PurchaseItem", back_populates="purchase", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_plugin_purchases_purchases_account", "account_id"),
        Index("ix_plugin_purchases_purchases_status", "status"),
    )


class PurchaseItem(Base):
    __tablename__ = "plugin_purchases_items"

    id = Column(String, primary_key=True, default=_uuid)
    purchase_id = Column(String, ForeignKey("plugin_purchases_purchases.id"), nullable=False)
    product_id = Column(String, ForeignKey("plugin_purchases_products.id"), nullable=True)
    raw_name = Column(String(300), nullable=True)
    quantity = Column(Numeric(12, 3), nullable=False, default=1)
    unit = Column(String(40), nullable=True)
    unit_price_cents = Column(Integer, nullable=True)
    discount_cents = Column(Integer, nullable=False, default=0)
    line_total_cents = Column(Integer, nullable=True)
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    categorization_source = Column(String(30), nullable=False, default=CAT_SOURCE_UNKNOWN)
    categorization_confidence = Column(Integer, nullable=True)
    purpose = Column(String(200), nullable=True)
    project_ref = Column(String(200), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    purchase = relationship("Purchase", back_populates="items")
    product = relationship("Product", back_populates="items")
    category = relationship("Category")

    __table_args__ = (Index("ix_plugin_purchases_items_purchase", "purchase_id"),)


class CategorizationRule(Base):
    __tablename__ = "plugin_purchases_rules"

    id = Column(String, primary_key=True, default=_uuid)
    scope = Column(String(20), nullable=False)
    match_value = Column(String(300), nullable=False)
    category_id = Column(String, ForeignKey("categories.id"), nullable=False)
    priority = Column(Integer, nullable=False, default=0)
    confirmed = Column(String(5), nullable=False, default="false")  # 'true'/'false' as text for simplicity
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    archived_at = Column(DateTime, nullable=True)

    category = relationship("Category")

    __table_args__ = (Index("ix_plugin_purchases_rules_scope", "scope", "match_value"),)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ProductCreate(BaseModel):
    gtin: Optional[str] = None
    normalized_name: str = Field(..., min_length=1, max_length=300)
    brand: Optional[str] = None
    package_size: Optional[str] = None
    source: Optional[str] = None
    default_category_id: Optional[str] = None


class ProductRead(BaseModel):
    id: str
    gtin: Optional[str] = None
    normalized_name: str
    brand: Optional[str] = None
    package_size: Optional[str] = None
    source: Optional[str] = None
    default_category_id: Optional[str] = None
    updated_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReceiptCreate(BaseModel):
    file_reference: Optional[str] = None
    ocr_text: Optional[str] = None
    merchant: Optional[str] = None
    purchased_at: Optional[datetime] = None
    total_cents: Optional[int] = None
    currency: Optional[str] = None
    processing_status: str = RECEIPT_STATUS_PENDING


class ReceiptRead(BaseModel):
    id: str
    file_reference: Optional[str] = None
    ocr_text: Optional[str] = None
    merchant: Optional[str] = None
    purchased_at: Optional[datetime] = None
    total_cents: Optional[int] = None
    currency: Optional[str] = None
    processing_status: str
    purchase_id: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PurchaseItemCreate(BaseModel):
    product_id: Optional[str] = None
    raw_name: Optional[str] = None
    quantity: Optional[Decimal] = Field(default=Decimal("1"))
    unit: Optional[str] = None
    unit_price_cents: Optional[int] = None
    discount_cents: Optional[int] = 0
    line_total_cents: Optional[int] = None
    category_id: Optional[str] = None
    categorization_source: Optional[str] = None
    purpose: Optional[str] = None
    project_ref: Optional[str] = None
    confidence: Optional[int] = None


class PurchaseItemRead(BaseModel):
    id: str
    purchase_id: str
    product_id: Optional[str] = None
    raw_name: Optional[str] = None
    quantity: Decimal
    unit: Optional[str] = None
    unit_price_cents: Optional[int] = None
    discount_cents: int
    line_total_cents: Optional[int] = None
    category_id: Optional[str] = None
    categorization_source: str
    categorization_confidence: Optional[int] = None
    purpose: Optional[str] = None
    project_ref: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PurchaseCreate(BaseModel):
    account_id: Optional[str] = None
    merchant: Optional[str] = None
    purchased_at: Optional[datetime] = None
    currency: str = "CHF"
    total_cents: Optional[int] = None
    receipt_id: Optional[str] = None
    source: str = PURCHASE_SOURCE_MANUAL
    note: Optional[str] = None
    idempotency_key: Optional[str] = None
    items: list[PurchaseItemCreate] = Field(default_factory=list)
    create_transaction: bool = False


class PurchaseUpdate(BaseModel):
    merchant: Optional[str] = None
    purchased_at: Optional[datetime] = None
    currency: Optional[str] = None
    total_cents: Optional[int] = None
    note: Optional[str] = None
    status: Optional[str] = None
    items: Optional[list[PurchaseItemCreate]] = None


class PurchaseRead(BaseModel):
    id: str
    account_id: Optional[str] = None
    merchant: Optional[str] = None
    purchased_at: Optional[datetime] = None
    currency: str
    total_cents: Optional[int] = None
    items_total_cents: Optional[int] = None
    transaction_id: Optional[str] = None
    status: str
    receipt_id: Optional[str] = None
    source: str
    note: Optional[str] = None
    created_at: datetime
    archived_at: Optional[datetime] = None
    items: list[PurchaseItemRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class CategorizationRuleCreate(BaseModel):
    scope: str
    match_value: str
    category_id: str
    priority: int = 0
    confirmed: bool = False


class CategorizationRuleRead(BaseModel):
    id: str
    scope: str
    match_value: str
    category_id: str
    priority: int
    confirmed: bool
    created_at: datetime
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MergeRequest(BaseModel):
    barcode_gtins: list[str] = Field(default_factory=list)
    ocr_lines: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PurchaseService:
    def __init__(self, db: Session):
        self.db = db

    # ----- products -------------------------------------------------------

    def create_product(self, data: ProductCreate) -> Product:
        if data.gtin:
            existing = (
                self.db.query(Product).filter(Product.gtin == data.gtin).first()
            )
            if existing:
                # Update mutable fields
                existing.normalized_name = data.normalized_name
                existing.brand = data.brand or existing.brand
                existing.package_size = data.package_size or existing.package_size
                existing.source = data.source or existing.source
                if data.default_category_id is not None:
                    existing.default_category_id = data.default_category_id
                existing.updated_at = _utcnow()
                self.db.commit()
                self.db.refresh(existing)
                return existing
        product = Product(
            gtin=data.gtin,
            normalized_name=data.normalized_name,
            brand=data.brand,
            package_size=data.package_size,
            source=data.source,
            default_category_id=data.default_category_id,
        )
        self.db.add(product)
        self.db.commit()
        self.db.refresh(product)
        return product

    def get_product(self, product_id: str) -> Optional[Product]:
        return self.db.query(Product).filter(Product.id == product_id).first()

    def find_product_by_gtin(self, gtin: str) -> Optional[Product]:
        return self.db.query(Product).filter(Product.gtin == gtin).first()

    def list_products(self) -> list[Product]:
        return self.db.query(Product).order_by(Product.created_at.desc()).all()

    # ----- receipts -------------------------------------------------------

    def create_receipt(self, data: ReceiptCreate) -> Receipt:
        receipt = Receipt(
            file_reference=data.file_reference,
            ocr_text=data.ocr_text,
            merchant=data.merchant,
            purchased_at=data.purchased_at,
            total_cents=data.total_cents,
            currency=data.currency,
            processing_status=data.processing_status,
        )
        self.db.add(receipt)
        self.db.commit()
        self.db.refresh(receipt)
        return receipt

    def get_receipt(self, receipt_id: str) -> Optional[Receipt]:
        return self.db.query(Receipt).filter(Receipt.id == receipt_id).first()

    # ----- rules ----------------------------------------------------------

    def create_rule(self, data: CategorizationRuleCreate) -> CategorizationRule:
        # validate category
        cat = self.db.query(Category).filter(Category.id == data.category_id).first()
        if cat is None or cat.archived_at is not None:
            raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")
        rule = CategorizationRule(
            scope=data.scope,
            match_value=data.match_value,
            category_id=data.category_id,
            priority=data.priority,
            confirmed="true" if data.confirmed else "false",
        )
        self.db.add(rule)
        self.db.commit()
        self.db.refresh(rule)
        return rule

    def list_rules(self, include_archived: bool = False) -> list[CategorizationRule]:
        q = self.db.query(CategorizationRule)
        if not include_archived:
            q = q.filter(CategorizationRule.archived_at.is_(None))
        return q.order_by(CategorizationRule.priority.desc(), CategorizationRule.created_at).all()

    def _is_confirmed(self, rule: CategorizationRule) -> bool:
        return str(rule.confirmed).lower() == "true"

    # ----- categorization resolver ---------------------------------------

    def resolve_category(
        self,
        purchase: Purchase,
        item: PurchaseItemCreate | PurchaseItem,
        product: Optional[Product],
        rules: list[CategorizationRule],
    ) -> tuple[Optional[str], str, int]:
        """Return (category_id, source, confidence)."""
        # 1. explicit confirmed decision on the item itself
        cat_id = getattr(item, "category_id", None)
        # For create payload, category_id may be set by client -> MANUAL
        if cat_id and getattr(item, "categorization_source", None) == CAT_SOURCE_MANUAL:
            return cat_id, CAT_SOURCE_MANUAL, 10000
        # If client explicitly set category_id without source, treat as manual
        if cat_id and not getattr(item, "categorization_source", None):
            return cat_id, CAT_SOURCE_MANUAL, 10000

        # 2/3. rules
        candidates: list[CategorizationRule] = []
        raw_name = (getattr(item, "raw_name", None) or "") or ""
        purpose = (getattr(item, "purpose", None) or "") or ""
        project = (getattr(item, "project_ref", None) or "") or ""
        product_id = getattr(item, "product_id", None)
        for rule in rules:
            if rule.archived_at is not None:
                continue
            matched = False
            if rule.scope == RULE_SCOPE_PRODUCT and product_id and rule.match_value == product_id:
                matched = True
            elif rule.scope == RULE_SCOPE_MERCHANT and purchase.merchant:
                if rule.match_value.strip().lower() == (purchase.merchant or "").strip().lower():
                    matched = True
            elif rule.scope == RULE_SCOPE_TEXT and raw_name:
                if rule.match_value.strip().lower() in raw_name.strip().lower():
                    matched = True
            elif rule.scope == RULE_SCOPE_PURPOSE and purpose:
                if rule.match_value.strip().lower() == purpose.strip().lower():
                    matched = True
            elif rule.scope == RULE_SCOPE_PROJECT and project:
                if rule.match_value.strip().lower() == project.strip().lower():
                    matched = True
            if matched:
                candidates.append(rule)

        if candidates:
            # confirmed first, then priority desc, then scope rank desc, then created_at asc
            def sort_key(r: CategorizationRule):
                return (
                    0 if self._is_confirmed(r) else 1,
                    -int(r.priority or 0),
                    -SCOPE_RANK.get(r.scope, 0),
                    r.created_at or _utcnow(),
                )

            candidates.sort(key=sort_key)
            chosen = candidates[0]
            conf = 9500 if self._is_confirmed(chosen) else 7500
            return chosen.category_id, CAT_SOURCE_RULE, conf

        # 4. product default category as suggestion
        if product is not None and product.default_category_id:
            return product.default_category_id, CAT_SOURCE_PRODUCT_DEFAULT, 6000

        return None, CAT_SOURCE_UNKNOWN, 0

    # ----- purchases ------------------------------------------------------

    def _compute_items_total(self, items: list[PurchaseItemCreate]) -> int:
        total = 0
        for it in items:
            if it.line_total_cents is not None:
                total += int(it.line_total_cents)
            elif it.unit_price_cents is not None and it.quantity is not None:
                q = it.quantity
                # quantity decimal -> cents
                line = int((Decimal(it.unit_price_cents) * q).to_integral_value(rounding=__import__("decimal").ROUND_HALF_UP))
                discount = int(it.discount_cents or 0)
                total += max(0, line - discount)
        return total

    def _check_idempotency(self, existing: Purchase, data: PurchaseCreate) -> None:
        if existing.idempotency_fingerprint:
            expected = self._purchase_fingerprint(data)
            if existing.idempotency_fingerprint != expected:
                raise IdempotencyConflict(
                    "Idempotenzschlüssel wurde mit abweichendem Inhalt wiederverwendet"
                )
            return
        # fallback compare
        if (
            (existing.account_id or None) != (data.account_id or None)
            or (existing.merchant or None) != (data.merchant or None)
            or existing.total_cents != (data.total_cents if data.total_cents is not None else self._compute_items_total(data.items))
        ):
            raise IdempotencyConflict(
                "Idempotenzschlüssel wurde mit abweichendem Inhalt wiederverwendet"
            )

    def _purchase_fingerprint(self, data: PurchaseCreate) -> str:
        items_fp = []
        for it in data.items:
            items_fp.append(
                {
                    "product_id": it.product_id,
                    "raw_name": it.raw_name,
                    "quantity": str(it.quantity) if it.quantity is not None else None,
                    "unit_price_cents": it.unit_price_cents,
                    "line_total_cents": it.line_total_cents,
                    "category_id": it.category_id,
                    "purpose": it.purpose,
                    "project_ref": it.project_ref,
                }
            )
        return _fingerprint(
            {
                "account_id": data.account_id,
                "merchant": data.merchant,
                "purchased_at": data.purchased_at.isoformat() if data.purchased_at else None,
                "currency": data.currency,
                "total_cents": data.total_cents,
                "items": items_fp,
                "receipt_id": data.receipt_id,
                "source": data.source,
            }
        )

    def create_purchase(self, data: PurchaseCreate) -> Purchase:
        if data.account_id:
            acc = self.db.query(Account).filter(Account.id == data.account_id).first()
            if acc is None or acc.archived_at is not None:
                raise HTTPException(status_code=404, detail="Konto nicht gefunden")

        if data.receipt_id:
            r = self.get_receipt(data.receipt_id)
            if r is None:
                raise HTTPException(status_code=404, detail="Beleg nicht gefunden")

        # idempotency
        if data.idempotency_key:
            existing = (
                self.db.query(Purchase)
                .filter(Purchase.idempotency_key == data.idempotency_key)
                .first()
            )
            if existing:
                self._check_idempotency(existing, data)
                return existing

        items_total = self._compute_items_total(data.items)
        total_cents = data.total_cents if data.total_cents is not None else (items_total if data.items else None)

        # validate categories
        for it in data.items:
            if it.category_id:
                cat = self.db.query(Category).filter(Category.id == it.category_id).first()
                if cat is None or cat.archived_at is not None:
                    raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")

        rules = self.list_rules()

        purchase = Purchase(
            account_id=data.account_id,
            merchant=data.merchant,
            purchased_at=data.purchased_at,
            currency=data.currency or "CHF",
            total_cents=total_cents,
            items_total_cents=items_total if data.items else None,
            receipt_id=data.receipt_id,
            source=data.source or PURCHASE_SOURCE_MANUAL,
            note=data.note,
            idempotency_key=data.idempotency_key,
            idempotency_fingerprint=(
                self._purchase_fingerprint(data) if data.idempotency_key else None
            ),
            status=PURCHASE_STATUS_DRAFT,
        )
        self.db.add(purchase)
        self.db.flush()

        # link receipt to purchase
        if data.receipt_id:
            r = self.get_receipt(data.receipt_id)
            if r is not None:
                r.purchase_id = purchase.id
                r.processing_status = RECEIPT_STATUS_PROCESSED

        for it in data.items:
            product = None
            if it.product_id:
                product = self.get_product(it.product_id)
            # resolve category
            cat_id = it.category_id
            source = it.categorization_source
            confidence = it.confidence
            if cat_id is None or source is None:
                rcat, rsource, rconf = self.resolve_category(purchase, it, product, rules)
                if cat_id is None:
                    cat_id = rcat
                if source is None:
                    source = rsource
                if confidence is None:
                    confidence = rconf
            if source is None:
                source = CAT_SOURCE_UNKNOWN
            qty = it.quantity if it.quantity is not None else Decimal("1")
            line_total = it.line_total_cents
            if line_total is None and it.unit_price_cents is not None:
                line_total = int(
                    (Decimal(it.unit_price_cents) * qty).to_integral_value(
                        rounding=__import__("decimal").ROUND_HALF_UP
                    )
                ) - int(it.discount_cents or 0)
            item = PurchaseItem(
                purchase_id=purchase.id,
                product_id=it.product_id,
                raw_name=it.raw_name,
                quantity=qty,
                unit=it.unit,
                unit_price_cents=it.unit_price_cents,
                discount_cents=int(it.discount_cents or 0),
                line_total_cents=line_total,
                category_id=cat_id,
                categorization_source=source,
                categorization_confidence=confidence,
                purpose=it.purpose,
                project_ref=it.project_ref,
            )
            self.db.add(item)

        # create transaction if requested
        if data.create_transaction:
            self._book_purchase(purchase, commit=False)

        self.db.commit()
        self.db.refresh(purchase)
        return purchase

    def _book_purchase(self, purchase: Purchase, *, commit: bool = True) -> Optional[Transaction]:
        if purchase.transaction_id:
            return self.db.query(Transaction).filter(Transaction.id == purchase.transaction_id).first()
        if not purchase.account_id:
            raise HTTPException(status_code=422, detail="Für die Buchung wird ein Konto benötigt")
        if purchase.total_cents is None or purchase.total_cents <= 0:
            raise HTTPException(status_code=422, detail="Gesamtbetrag muss > 0 sein")
        account = self.db.query(Account).filter(Account.id == purchase.account_id).first()
        if account is None or account.archived_at is not None:
            raise HTTPException(status_code=404, detail="Konto nicht gefunden")
        if purchase.currency and account.currency and purchase.currency != account.currency:
            raise HTTPException(
                status_code=422,
                detail=f"Währung des Einkaufs ({purchase.currency}) passt nicht zum Konto ({account.currency})",
            )
        tx_service = TransactionService(self.db)
        description = purchase.merchant or "Einkauf"
        if purchase.note:
            description = f"{description} - {purchase.note}"
        tx = tx_service.create(
            TransactionCreate(
                account_id=purchase.account_id,
                type="EXPENSE",
                amount_cents=int(purchase.total_cents),
                category_id=None,
                description=description,
                date=purchase.purchased_at,
                idempotency_key=f"purchase:{purchase.id}",
            ),
            commit=False,
        )
        purchase.transaction_id = tx.id
        purchase.status = PURCHASE_STATUS_POSTED
        if commit:
            self.db.commit()
            self.db.refresh(purchase)
        else:
            self.db.flush()
        return tx

    def post_purchase(self, purchase_id: str) -> Purchase:
        purchase = self.get_purchase(purchase_id)
        if purchase is None:
            raise HTTPException(status_code=404, detail="Einkauf nicht gefunden")
        if purchase.archived_at is not None:
            raise HTTPException(status_code=409, detail="Einkauf ist archiviert")
        if purchase.status == PURCHASE_STATUS_POSTED and purchase.transaction_id:
            return purchase
        self._book_purchase(purchase, commit=True)
        self.db.refresh(purchase)
        return purchase

    def get_purchase(self, purchase_id: str) -> Optional[Purchase]:
        return self.db.query(Purchase).filter(Purchase.id == purchase_id).first()

    def list_purchases(
        self, account_id: Optional[str] = None, status: Optional[str] = None, include_archived: bool = False
    ) -> list[Purchase]:
        q = self.db.query(Purchase)
        if account_id:
            q = q.filter(Purchase.account_id == account_id)
        if status:
            q = q.filter(Purchase.status == status)
        if not include_archived:
            q = q.filter(Purchase.archived_at.is_(None))
        return q.order_by(Purchase.created_at.desc()).all()

    def update_purchase(self, purchase_id: str, data: PurchaseUpdate) -> Purchase:
        purchase = self.get_purchase(purchase_id)
        if purchase is None:
            raise HTTPException(status_code=404, detail="Einkauf nicht gefunden")
        if purchase.status == PURCHASE_STATUS_POSTED:
            raise HTTPException(status_code=409, detail="Gebuchter Einkauf kann nicht mehr bearbeitet werden")
        if data.merchant is not None:
            purchase.merchant = data.merchant
        if data.purchased_at is not None:
            purchase.purchased_at = data.purchased_at
        if data.currency is not None:
            purchase.currency = data.currency
        if data.total_cents is not None:
            purchase.total_cents = data.total_cents
        if data.note is not None:
            purchase.note = data.note
        if data.status is not None:
            if data.status not in PURCHASE_STATUSES:
                raise HTTPException(status_code=422, detail="Ungültiger Status")
            purchase.status = data.status

        if data.items is not None:
            # replace items
            for old in list(purchase.items):
                self.db.delete(old)
            self.db.flush()
            rules = self.list_rules()
            items_total = self._compute_items_total(data.items)
            purchase.items_total_cents = items_total if data.items else None
            for it in data.items:
                product = self.get_product(it.product_id) if it.product_id else None
                cat_id = it.category_id
                source = it.categorization_source
                confidence = it.confidence
                if cat_id is None or source is None:
                    rcat, rsource, rconf = self.resolve_category(purchase, it, product, rules)
                    if cat_id is None:
                        cat_id = rcat
                    if source is None:
                        source = rsource
                    if confidence is None:
                        confidence = rconf
                if source is None:
                    source = CAT_SOURCE_UNKNOWN
                qty = it.quantity if it.quantity is not None else Decimal("1")
                line_total = it.line_total_cents
                if line_total is None and it.unit_price_cents is not None:
                    line_total = int(
                        (Decimal(it.unit_price_cents) * qty).to_integral_value(
                            rounding=__import__("decimal").ROUND_HALF_UP
                        )
                    ) - int(it.discount_cents or 0)
                item = PurchaseItem(
                    purchase_id=purchase.id,
                    product_id=it.product_id,
                    raw_name=it.raw_name,
                    quantity=qty,
                    unit=it.unit,
                    unit_price_cents=it.unit_price_cents,
                    discount_cents=int(it.discount_cents or 0),
                    line_total_cents=line_total,
                    category_id=cat_id,
                    categorization_source=source,
                    categorization_confidence=confidence,
                    purpose=it.purpose,
                    project_ref=it.project_ref,
                )
                self.db.add(item)
            if data.total_cents is None and data.items:
                purchase.total_cents = items_total

        self.db.commit()
        self.db.refresh(purchase)
        return purchase

    def archive_purchase(self, purchase_id: str) -> Purchase:
        purchase = self.get_purchase(purchase_id)
        if purchase is None:
            raise HTTPException(status_code=404, detail="Einkauf nicht gefunden")
        if purchase.transaction_id:
            # void linked transaction
            TransactionService(self.db).reverse(purchase.transaction_id, commit=False)
        purchase.archived_at = _utcnow()
        purchase.status = PURCHASE_STATUS_POSTED if purchase.status == PURCHASE_STATUS_POSTED else purchase.status
        self.db.commit()
        self.db.refresh(purchase)
        return purchase

    def set_item_category(
        self, item_id: str, category_id: Optional[str], purpose: Optional[str] = None,
        project_ref: Optional[str] = None, save_rule: bool = False, rule_scope: Optional[str] = None,
        match_value: Optional[str] = None,
    ) -> PurchaseItem:
        item = self.db.query(PurchaseItem).filter(PurchaseItem.id == item_id).first()
        if item is None:
            raise HTTPException(status_code=404, detail="Position nicht gefunden")
        if category_id is not None:
            cat = self.db.query(Category).filter(Category.id == category_id).first()
            if cat is None or cat.archived_at is not None:
                raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")
        item.category_id = category_id
        item.categorization_source = CAT_SOURCE_MANUAL
        item.categorization_confidence = 10000
        if purpose is not None:
            item.purpose = purpose
        if project_ref is not None:
            item.project_ref = project_ref

        if save_rule and category_id is not None:
            scope = rule_scope or RULE_SCOPE_PRODUCT
            if scope == RULE_SCOPE_PRODUCT and item.product_id:
                mv = item.product_id
            elif scope == RULE_SCOPE_MERCHANT:
                mv = (item.purchase.merchant or "").strip()
            elif scope == RULE_SCOPE_TEXT:
                mv = match_value or (item.raw_name or "").strip()
            else:
                mv = match_value or (item.raw_name or "").strip()
            if mv:
                rule = CategorizationRule(
                    scope=scope,
                    match_value=mv,
                    category_id=category_id,
                    priority=10,
                    confirmed="true",
                )
                self.db.add(rule)

        self.db.commit()
        self.db.refresh(item)
        return item

    # ----- merge helper ---------------------------------------------------

    def merge_sources(self, barcode_gtins: list[str], ocr_lines: list[dict]) -> list[dict]:
        """Merge barcode products with OCR lines, avoiding duplicates.

        Returns a list of merged line dicts with keys:
        product_id, gtin, raw_name, quantity, unit, unit_price_cents,
        line_total_cents, source, matched (bool), uncertain (bool).
        """
        # load products
        products_by_gtin: dict[str, Product] = {}
        for g in barcode_gtins:
            p = self.find_product_by_gtin(g)
            if p is not None:
                products_by_gtin[g] = p

        merged: list[dict] = []
        used_ocr: set[int] = set()

        # first: match barcode products to OCR lines by normalized name
        for g in barcode_gtins:
            product = products_by_gtin.get(g)
            matched_idx = None
            if product is not None:
                for i, line in enumerate(ocr_lines):
                    if i in used_ocr:
                        continue
                    name = (line.get("name") or "").strip().lower()
                    if name and product.normalized_name.strip().lower() == name:
                        matched_idx = i
                        break
                    # fuzzy: contains
                    if name and product.normalized_name.strip().lower() in name:
                        matched_idx = i
                        break
            if matched_idx is not None:
                used_ocr.add(matched_idx)
                line = ocr_lines[matched_idx]
                merged.append(
                    {
                        "product_id": product.id if product else None,
                        "gtin": g,
                        "raw_name": line.get("name") or (product.normalized_name if product else g),
                        "quantity": line.get("quantity", 1),
                        "unit": line.get("unit"),
                        "unit_price_cents": line.get("unit_price_cents"),
                        "line_total_cents": line.get("line_total_cents"),
                        "source": PURCHASE_SOURCE_MIXED,
                        "matched": True,
                        "uncertain": False,
                    }
                )
            else:
                # barcode product not found in OCR
                merged.append(
                    {
                        "product_id": product.id if product else None,
                        "gtin": g,
                        "raw_name": product.normalized_name if product else g,
                        "quantity": 1,
                        "unit": None,
                        "unit_price_cents": None,
                        "line_total_cents": None,
                        "source": PURCHASE_SOURCE_BARCODE,
                        "matched": False,
                        "uncertain": True,
                    }
                )

        # remaining OCR lines
        for i, line in enumerate(ocr_lines):
            if i in used_ocr:
                continue
            merged.append(
                {
                    "product_id": None,
                    "gtin": None,
                    "raw_name": line.get("name"),
                    "quantity": line.get("quantity", 1),
                    "unit": line.get("unit"),
                    "unit_price_cents": line.get("unit_price_cents"),
                    "line_total_cents": line.get("line_total_cents"),
                    "source": PURCHASE_SOURCE_OCR,
                    "matched": False,
                    "uncertain": bool(line.get("uncertain", False)),
                }
            )

        return merged


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/purchases", tags=["purchases"])


def _product_read(p: Product) -> ProductRead:
    return ProductRead.model_validate(p)


def _receipt_read(r: Receipt) -> ReceiptRead:
    return ReceiptRead.model_validate(r)


def _item_read(i: PurchaseItem) -> PurchaseItemRead:
    return PurchaseItemRead.model_validate(i)


def _purchase_read(p: Purchase) -> PurchaseRead:
    data = PurchaseRead.model_validate(p)
    data.items = [_item_read(i) for i in p.items]
    # confirmed bool conversion for rules not here
    return data


def _rule_read(r: CategorizationRule, svc: PurchaseService) -> CategorizationRuleRead:
    return CategorizationRuleRead(
        id=r.id,
        scope=r.scope,
        match_value=r.match_value,
        category_id=r.category_id,
        priority=r.priority,
        confirmed=svc._is_confirmed(r),
        created_at=r.created_at,
        archived_at=r.archived_at,
    )


@router.post("/products", response_model=ProductRead, status_code=201)
def create_product(data: ProductCreate, db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    return _product_read(svc.create_product(data))


@router.get("/products", response_model=list[ProductRead])
def list_products(db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    return [_product_read(p) for p in svc.list_products()]


@router.get("/products/by-gtin/{gtin}", response_model=ProductRead)
def get_product_by_gtin(gtin: str, db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    p = svc.find_product_by_gtin(gtin)
    if p is None:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    return _product_read(p)


@router.post("/receipts", response_model=ReceiptRead, status_code=201)
def create_receipt(data: ReceiptCreate, db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    return _receipt_read(svc.create_receipt(data))


@router.get("/receipts/{receipt_id}", response_model=ReceiptRead)
def get_receipt(receipt_id: str, db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    r = svc.get_receipt(receipt_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Beleg nicht gefunden")
    return _receipt_read(r)


@router.post("/rules", response_model=CategorizationRuleRead, status_code=201)
def create_rule(data: CategorizationRuleCreate, db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    r = svc.create_rule(data)
    return _rule_read(r, svc)


@router.get("/rules", response_model=list[CategorizationRuleRead])
def list_rules(include_archived: bool = Query(False), db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    return [_rule_read(r, svc) for r in svc.list_rules(include_archived=include_archived)]


@router.post("", response_model=PurchaseRead, status_code=201)
@router.post("/create", response_model=PurchaseRead, status_code=201)
def create_purchase(data: PurchaseCreate, db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    try:
        purchase = svc.create_purchase(data)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - safety net
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _purchase_read(purchase)


@router.get("", response_model=list[PurchaseRead])
@router.get("/list", response_model=list[PurchaseRead])
def list_purchases(
    account_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
):
    svc = PurchaseService(db)
    return [_purchase_read(p) for p in svc.list_purchases(account_id=account_id, status=status, include_archived=include_archived)]


@router.get("/{purchase_id}", response_model=PurchaseRead)
def get_purchase(purchase_id: str, db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    p = svc.get_purchase(purchase_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Einkauf nicht gefunden")
    return _purchase_read(p)


@router.patch("/{purchase_id}", response_model=PurchaseRead)
def update_purchase(purchase_id: str, data: PurchaseUpdate, db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    try:
        p = svc.update_purchase(purchase_id, data)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _purchase_read(p)


@router.post("/{purchase_id}/post", response_model=PurchaseRead)
def post_purchase(purchase_id: str, db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    p = svc.post_purchase(purchase_id)
    return _purchase_read(p)


@router.delete("/{purchase_id}")
def archive_purchase(purchase_id: str, db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    p = svc.archive_purchase(purchase_id)
    return {"ok": True, "id": p.id, "status": p.status}


@router.patch("/items/{item_id}/category", response_model=PurchaseItemRead)
def set_item_category(
    item_id: str,
    category_id: Optional[str] = Query(None),
    purpose: Optional[str] = Query(None),
    project_ref: Optional[str] = Query(None),
    save_rule: bool = Query(False),
    rule_scope: Optional[str] = Query(None),
    match_value: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    svc = PurchaseService(db)
    item = svc.set_item_category(
        item_id,
        category_id,
        purpose=purpose,
        project_ref=project_ref,
        save_rule=save_rule,
        rule_scope=rule_scope,
        match_value=match_value,
    )
    return _item_read(item)


@router.post("/merge", response_model=list[dict])
def merge_sources(data: MergeRequest, db: Session = Depends(get_db)):
    svc = PurchaseService(db)
    return svc.merge_sources(data.barcode_gtins, data.ocr_lines)


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------


class PurchasesPlugin(FinancePlugin):
    name = "purchases"
    version = "0.1.0"

    def register(self, app):
        engine = app.state.db_engine
        Base.metadata.create_all(
            bind=engine,
            tables=[
                Product.__table__,
                Receipt.__table__,
                Purchase.__table__,
                PurchaseItem.__table__,
                CategorizationRule.__table__,
            ],
        )
        app.include_router(router)


PLUGIN = PurchasesPlugin()