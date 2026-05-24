from __future__ import annotations
from pydantic import BaseModel
from enum import Enum
from typing import Optional
from datetime import datetime


class OfferType(str, Enum):
    BANK_DISCOUNT = "bank_discount"
    COUPON        = "coupon"
    CASHBACK      = "cashback"
    EMI_BENEFIT   = "emi_benefit"
    EXCHANGE      = "exchange"


class DiscountType(str, Enum):
    PERCENTAGE = "percentage"
    FLAT       = "flat"


class CardType(str, Enum):
    CREDIT = "credit"
    DEBIT  = "debit"
    ALL    = "all"


class Offer(BaseModel):
    offer_id: str
    product_id: str
    platform: str
    offer_type: OfferType
    title: str          # raw scraped text
    terms: str = ""     # full T&C — read by LLM tc_parser node

    # Bank / card targeting
    bank: Optional[str] = None              # e.g. "HDFC", "SBI", "Axis"
    card_variants: list[str] = []           # empty = all variants of that bank
    card_type: CardType = CardType.ALL

    # Discount numbers — populated by tc_parser (LLM), used by price_calculator (deterministic)
    discount_type: Optional[DiscountType] = None
    discount_value: float = 0.0
    max_discount_cap: Optional[float] = None    # max ₹ cap
    min_order_value: float = 0.0                # minimum cart value from T&C

    # Coupon
    coupon_code: Optional[str] = None
    is_auto_applied: bool = False

    # Cashback — post-purchase; NOT deducted at checkout
    cashback_amount: Optional[float] = None
    cashback_timing: Optional[str] = None   # "instant" | "statement_credit" | "wallet"

    # Stacking rules — parsed from T&C by LLM
    stackable_with: list[OfferType] = []    # offer types this CAN stack with
    exclusive: bool = False                 # True = cannot combine with anything

    valid_until: Optional[datetime] = None
    scraped_at: datetime = datetime.utcnow()

    # ── helpers ───────────────────────────────────────────────────────────────

    def applies_to_card(self, bank: str, card_type: CardType, variant: str = "") -> bool:
        """Return True if this offer is applicable for the given card."""
        if self.bank and self.bank.lower() != bank.lower():
            return False
        if self.card_type not in (CardType.ALL, card_type):
            return False
        if self.card_variants and variant:
            return any(v.lower() in variant.lower() for v in self.card_variants)
        return True

    def is_min_order_met(self, price: float) -> bool:
        """T&C constraint: minimum cart value check."""
        return price >= self.min_order_value

    def discount_amount(self, price: float) -> float:
        """
        Deterministic ₹ discount after cap.
        LLM is NEVER used here — only the values it populated earlier.
        """
        if not self.is_min_order_met(price):
            return 0.0
        if self.discount_type == DiscountType.PERCENTAGE:
            raw = price * self.discount_value / 100.0
        elif self.discount_type == DiscountType.FLAT:
            raw = self.discount_value
        else:
            raw = self.cashback_amount or 0.0
        if self.max_discount_cap is not None:
            return min(raw, self.max_discount_cap)
        return raw
