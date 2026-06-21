"""
Agent Node 4 — T&C Parser

Two modes (controlled by settings.tc_parse_mode):

  fast (default)
    Skips LLM completely. Uses flat_discount already on each Offer object
    (scraped directly from the offer card "₹X off" label). Sets discount_type=FLAT,
    discount_value=flat_discount. Takes <1ms per product.

  slow
    Sends offer title + T&C text to LLM → extracts structured fields:
    min_order_value, max_discount_cap, card_variants, cashback_timing, etc.
    More accurate but adds 5-30s depending on LLM provider and number of offers.

The mode can be toggled:
  • In .env:           TC_PARSE_MODE=slow
  • At runtime:        Sidebar toggle in streamlit_app.py sets
                       settings.tc_parse_mode before graph invocation
  • Per-request:       Pass tc_parse_mode in AgentState (see agent_state.py)
"""
from __future__ import annotations

import json
import re

from langchain_core.prompts import ChatPromptTemplate

from config import get_llm
from config.settings import get_settings
from models.agent_state import AgentState
from models.offer import CardType, DiscountType, Offer, OfferType

_s = get_settings()


# ─────────────────────────────────────────────────────────────────────────────
# FAST MODE — no LLM
# ─────────────────────────────────────────────────────────────────────────────

def _fast_parse(offer: Offer) -> Offer:
    """
    Promote flat_discount → discount_value without touching the LLM.
    Infers cashback_amount from flat_discount for CASHBACK offers.
    """
    update: dict = {}

    if offer.flat_discount > 0:
        if offer.offer_type == OfferType.CASHBACK:
            update["cashback_amount"] = offer.flat_discount
            update["discount_type"]   = DiscountType.FLAT
            update["discount_value"]  = offer.flat_discount
        else:
            update["discount_type"]  = DiscountType.FLAT
            update["discount_value"] = offer.flat_discount

    if not update:
        return offer
    return offer.model_copy(update=update)


# ─────────────────────────────────────────────────────────────────────────────
# SLOW MODE — LLM
# ─────────────────────────────────────────────────────────────────────────────

_llm    = get_llm(temperature=0.0, json_mode=True)
_prompt = ChatPromptTemplate.from_messages([
    ("system", """Parse Indian e-commerce offer text and T&C into a JSON array.
For each offer in the input array return a JSON object with these exact keys:

  offer_id        : string  — copy exactly from input
  offer_type      : "bank_discount" | "coupon" | "cashback" | "emi_benefit" | "exchange"
  bank            : string or null
  card_variants   : list of strings — empty list = all variants
  card_type       : "credit" | "debit" | "all"
  discount_type   : "percentage" | "flat" | null
  discount_value  : number (0 if N/A)
  max_discount_cap: number or null
  min_order_value : number (0 if not mentioned)
  coupon_code     : string or null
  is_auto_applied : boolean
  cashback_amount : number or null
  cashback_timing : "instant" | "statement_credit" | "wallet" | null
  stackable_with  : list of offer_type strings
  exclusive       : boolean
  terms_summary   : string — 1-sentence summary of key constraints

T&C extraction rules:
  "minimum cart value ₹X"             → min_order_value = X
  "maximum discount ₹X" / "up to ₹X" → max_discount_cap = X
  "cannot be clubbed/combined"        → exclusive = true
  "cashback credited in X days"       → cashback_timing = "statement_credit"

You MUST return a valid JSON array. Use offer title to infer values when T&C is empty.
Return ONLY the raw JSON array — no markdown, no explanation."""),
    ("human", "Parse these offers:\n{offers_json}"),
])


def _safe_parse_llm_output(raw) -> list[dict]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        for v in raw.values():
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return []
    if isinstance(raw, str):
        text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, dict)]
            if isinstance(parsed, dict):
                for v in parsed.values():
                    if isinstance(v, list):
                        return [x for x in v if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
    return []


def _merge_llm_result(base: Offer, p: dict) -> Offer:
    """Merge one LLM-parsed dict back onto the scraped Offer."""
    def _ot(v):
        try: return OfferType(v) if v else base.offer_type
        except ValueError: return base.offer_type

    def _ct(v):
        try: return CardType(v) if v else base.card_type
        except ValueError: return base.card_type

    def _dt(v):
        try: return DiscountType(v) if v else None
        except ValueError: return None

    disc_val  = float(p.get("discount_value") or 0)
    disc_type = _dt(p.get("discount_type"))

    # If LLM returned 0 discount but scraper found flat_discount, keep scraper value
    if disc_val == 0 and base.flat_discount > 0:
        disc_val  = base.flat_discount
        disc_type = disc_type or DiscountType.FLAT

    cb_amt = float(p["cashback_amount"]) if p.get("cashback_amount") else None
    # For CASHBACK offers: if LLM didn't return cashback_amount, fall back to flat_discount
    if cb_amt is None and _ot(p.get("offer_type")) == OfferType.CASHBACK and base.flat_discount > 0:
        cb_amt = base.flat_discount

    return base.model_copy(update={
        "offer_type":       _ot(p.get("offer_type")),
        "bank":             p.get("bank") or base.bank,
        "card_variants":    p.get("card_variants") or [],
        "card_type":        _ct(p.get("card_type")),
        "discount_type":    disc_type,
        "discount_value":   disc_val,
        "max_discount_cap": float(p["max_discount_cap"]) if p.get("max_discount_cap") else None,
        "min_order_value":  float(p.get("min_order_value") or 0),
        "coupon_code":      p.get("coupon_code"),
        "is_auto_applied":  bool(p.get("is_auto_applied", False)),
        "cashback_amount":  cb_amt,
        "cashback_timing":  p.get("cashback_timing"),
        "stackable_with":   [
            OfferType(x) for x in (p.get("stackable_with") or [])
            if x in OfferType._value2member_map_
        ],
        "exclusive":        bool(p.get("exclusive", False)),
        "terms":            str(p.get("terms_summary") or base.terms)[:300],
    })


async def _slow_parse_product(product_id: str, offers: list[Offer]) -> list[Offer]:
    """Run LLM on all offers for one product. Falls back per-offer on failure."""
    input_list = [
        {"offer_id": o.offer_id, "title": o.title, "terms": (o.terms or "")[:500]}
        for o in offers
    ]
    raw_output = None
    try:
        chain    = _prompt | _llm
        response = await chain.ainvoke({"offers_json": json.dumps(input_list, ensure_ascii=False)})
        raw_output = response.content if hasattr(response, "content") else response
    except Exception as exc:
        print(f"[tc_parser/slow] LLM call failed for {product_id}: {exc}")

    parsed_list = _safe_parse_llm_output(raw_output) if raw_output is not None else []
    if not parsed_list:
        print(f"[tc_parser/slow] Fallback to fast mode for {product_id}")
        return [_fast_parse(o) for o in offers]

    offer_map     = {o.offer_id: o for o in offers}
    returned_ids  = set()
    updated: list[Offer] = []

    for p in parsed_list:
        if not isinstance(p, dict):
            continue
        oid  = p.get("offer_id", "")
        base = offer_map.get(oid)
        if not base:
            continue
        returned_ids.add(oid)
        try:
            updated.append(_merge_llm_result(base, p))
        except Exception as exc:
            print(f"[tc_parser/slow] Merge failed for {oid}: {exc}")
            updated.append(_fast_parse(base))

    # Any offers LLM skipped → fast fallback
    for o in offers:
        if o.offer_id not in returned_ids:
            updated.append(_fast_parse(o))

    return updated


# ─────────────────────────────────────────────────────────────────────────────
# Node entry point
# ─────────────────────────────────────────────────────────────────────────────

async def tc_parser_node(state: AgentState) -> AgentState:
    # Mode can be overridden per-request via state, otherwise use global setting
    mode = state.get("tc_parse_mode") or _s.tc_parse_mode
    parsed_offers: dict[str, list[Offer]] = {}

    for product_id, offers in state["raw_offers"].items():
        if not offers:
            parsed_offers[product_id] = []
            continue

        if mode == "fast":
            parsed_offers[product_id] = [_fast_parse(o) for o in offers]
        else:
            parsed_offers[product_id] = await _slow_parse_product(product_id, offers)

    return {**state, "parsed_offers": parsed_offers}
