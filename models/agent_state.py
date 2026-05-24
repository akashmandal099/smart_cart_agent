from __future__ import annotations
from typing import Optional, Any
from typing_extensions import TypedDict
from enum import Enum
from pydantic import BaseModel
from .product import Product, Platform
from .offer import Offer
from .price_graph import OfferCombo
from .session import UserSession


class QueryType(str, Enum):
    CATEGORY = "category"
    SPECIFIC  = "specific_product"


class QueryIntent(BaseModel):
    query_type: QueryType
    product: str
    brand_hint: Optional[str] = None
    price_min: float = 0.0
    price_max: float = 99_999_999.0
    platforms: list[Platform] = [Platform.AMAZON, Platform.FLIPKART]
    top_n: int = 10


# LangGraph requires TypedDict for graph state
class AgentState(TypedDict):
    # ── inputs ────────────────────────────────────────────────────────────────
    user_message: str
    session: UserSession
    chat_history: list[dict]

    # ── intermediate ──────────────────────────────────────────────────────────
    intent: Optional[QueryIntent]
    raw_products: list[Product]
    raw_offers: dict[str, list[Offer]]      # product_id → raw scraped offers
    parsed_offers: dict[str, list[Offer]]   # product_id → T&C-parsed offers

    # ── output ────────────────────────────────────────────────────────────────
    ranked_combos: list[OfferCombo]
    response_text: str
    structured_results: list[dict]          # for frontend result cards
    error: Optional[str]
