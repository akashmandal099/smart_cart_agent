"""
Agent Node 4 — T&C Parser (LLM)

Reads raw scraped offer title + T&C text and extracts structured fields.
This is the ONLY place the LLM touches offer data.
Price calculations always happen deterministically AFTER this node.

One LLM call per product (batches all offers for that product) to minimise cost.
"""
import json

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from config.llm_factory import get_llm
from  config.settings import get_settings
from  models.agent_state import AgentState
from  models.offer import CardType, DiscountType, Offer, OfferType

_s = get_settings()
# _llm = ChatOpenAI(
#     model=_s.llm_model,
#     temperature=0.0,
#     api_key=_s.openai_api_key,
# )
_llm = get_llm(temperature=0.0, json_mode=True)

_SYSTEM = """You parse Indian e-commerce offer text and T&C into structured JSON.
For each offer in the input array, return a JSON object with these keys:

  offer_id        : string  — same as input, do not change
  offer_type      : one of ["bank_discount","coupon","cashback","emi_benefit","exchange"]
  bank            : string or null   — e.g. "HDFC", "SBI", "Axis", "ICICI", "Kotak"
  card_variants   : list of strings  — specific variants e.g. ["Regalia","Millennia"]
                    empty list if offer applies to ALL variants of that bank
  card_type       : "credit" | "debit" | "all"
  discount_type   : "percentage" | "flat" | null
  discount_value  : number  — percentage value OR flat ₹ amount (0 if N/A)
  max_discount_cap: number or null  — maximum ₹ discount allowed (from T&C)
  min_order_value : number  — minimum cart value ₹ required (0 if not mentioned)
  coupon_code     : string or null
  is_auto_applied : boolean — true if offer auto-applies (checkbox/automatic)
  cashback_amount : number or null
  cashback_timing : "instant" | "statement_credit" | "wallet" | null
  stackable_with  : list of offer_types this CAN stack with per T&C
                    (e.g. ["coupon"] means this bank_discount stacks with coupons)
                    empty list = default stacking rules apply
  exclusive       : boolean — true ONLY if T&C explicitly says "cannot be combined"
                    or "not valid with other offers" or similar
  terms_summary   : string — 1-sentence plain English summary of key constraints

KEY T&C RULES TO EXTRACT:
- "minimum cart/order value ₹X"      → min_order_value = X
- "maximum discount ₹X" / "up to ₹X" → max_discount_cap = X
- "cannot be clubbed/combined"        → exclusive = true
- "valid with bank offers"            → add "bank_discount" to stackable_with
- Same bank can have multiple offers that stack — detect from T&C explicitly
- "cashback credited in X days"       → cashback_timing = "statement_credit"

Return a JSON array in the same order as input. No explanation, only valid JSON."""

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM),
    ("human", "Parse these offers:\n{offers_json}"),
])
_chain = _PROMPT | _llm | JsonOutputParser()


async def tc_parser_node(state: AgentState) -> AgentState:
    raw_offers = state["raw_offers"]
    parsed_offers: dict[str, list[Offer]] = {}

    for product_id, offers in raw_offers.items():
        if not offers:
            parsed_offers[product_id] = []
            continue

        # Batch all offers for this product into one LLM call
        input_list = [
            {
                "offer_id": o.offer_id,
                "title":    o.title,
                "terms":    o.terms[:500],  # truncate to control tokens
            }
            for o in offers
        ]

        try:
            parsed_list = await _chain.ainvoke(
                {"offers_json": json.dumps(input_list, ensure_ascii=False)}
            )
        except Exception:
            # Fallback: use raw offers as-is (no structured fields)
            parsed_offers[product_id] = offers
            continue

        # Map LLM output back onto original Offer objects (offer_id as key)
        offer_map = {o.offer_id: o for o in offers}
        updated: list[Offer] = []

        for p in parsed_list:
            oid = p.get("offer_id", "")
            base = offer_map.get(oid)
            if not base:
                continue
            try:
                updated.append(
                    base.model_copy(update={
                        "offer_type":       OfferType(p.get("offer_type", "bank_discount")),
                        "bank":             p.get("bank"),
                        "card_variants":    p.get("card_variants", []),
                        "card_type":        CardType(p.get("card_type", "all")),
                        "discount_type":    (
                            DiscountType(p["discount_type"])
                            if p.get("discount_type") else None
                        ),
                        "discount_value":   float(p.get("discount_value", 0)),
                        "max_discount_cap": (
                            float(p["max_discount_cap"])
                            if p.get("max_discount_cap") else None
                        ),
                        "min_order_value":  float(p.get("min_order_value", 0)),
                        "coupon_code":      p.get("coupon_code"),
                        "is_auto_applied":  bool(p.get("is_auto_applied", False)),
                        "cashback_amount":  (
                            float(p["cashback_amount"])
                            if p.get("cashback_amount") else None
                        ),
                        "cashback_timing":  p.get("cashback_timing"),
                        "stackable_with":   [
                            OfferType(x) for x in p.get("stackable_with", [])
                            if x in OfferType._value2member_map_
                        ],
                        "exclusive":        bool(p.get("exclusive", False)),
                        "terms":            p.get("terms_summary", base.terms)[:300],
                    })
                )
            except Exception:
                updated.append(base)  # fallback to raw if merge fails

        parsed_offers[product_id] = updated

    return {**state, "parsed_offers": parsed_offers}
