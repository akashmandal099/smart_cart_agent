"""
Agent Node 6 — Response Formatter

Converts ranked OfferCombo list into a structured dict (for frontend cards)
AND a markdown chat response (for the chat bubble).
LLM is used only for natural language framing — never for price calculation.
"""
import json
from datetime import datetime

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from config.llm_factory import get_llm
from  config.settings import get_settings
from  models.agent_state import AgentState

_s = get_settings()
# _llm = ChatOpenAI(
#     model=_s.llm_model,
#     temperature=0.3,
#     api_key=_s.openai_api_key,
# )
_llm = get_llm(temperature=0.0, json_mode=True)

_SYSTEM = """You are SmartCart AI — a shopping assistant for Indian e-commerce.
Present the pre-computed deal results clearly in markdown.

Rules:
- Use EXACT prices from the data — NEVER recalculate or modify any numbers
- Format: numbered list, each item = product name, platform, checkout price,
  effective price (if cashback exists), offer breakdown, buy link
- Mark ✅ on rank #1 (best deal)
- Checkout price = amount charged at checkout
- Effective price = checkout price minus post-purchase cashback (show only if cashback > 0)
- Keep it concise — one short paragraph intro, then the numbered list
- End with: "Prices scraped at {scraped_at} IST. Verify final amount at checkout."
"""

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM),
    ("human", "User asked: {user_message}\n\nResults:\n{results_json}\n\nScraped at: {scraped_at}"),
])


async def response_formatter_node(state: AgentState) -> AgentState:
    combos   = state["ranked_combos"]
    products = {p.product_id: p for p in state["raw_products"]}

    if not combos:
        return {
            **state,
            "response_text": (
                "Sorry, I couldn't find any matching products for your query. "
                "Try a different product name, broader price range, or different platform."
            ),
            "structured_results": [],
        }

    # Build structured results for frontend cards
    structured: list[dict] = []
    for i, combo in enumerate(combos, 1):
        p = products.get(combo.product_id)
        structured.append({
            "rank":           i,
            "title":          p.title if p else combo.product_id,
            "platform":       combo.platform,
            "rating":         p.rating if p else None,
            "review_count":   p.review_count if p else None,
            "image_url":      p.image_url if p else None,
            "product_url":    p.product_url if p else "",
            "base_price":     p.base_price if p else 0,
            "checkout_price": combo.checkout_price,
            "cashback":       combo.cashback,
            "effective_price":combo.effective_price,
            "offers": [
                {
                    "title":           o.title,
                    "bank":            o.bank,
                    "card_type":       o.card_type.value,
                    "discount":        round(o.discount_amount(p.base_price if p else combo.checkout_price), 2),
                    "coupon_code":     o.coupon_code,
                    "is_auto_applied": o.is_auto_applied,
                    "cashback_timing": o.cashback_timing,
                    "terms":           o.terms,
                }
                for o in combo.applied_offers
            ],
            "steps":    combo.steps,
            "warnings": combo.warnings,
        })

    scraped_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    # LLM formats the markdown response — uses structured data, never recalculates
    llm_response = await _llm.ainvoke(
        _PROMPT.format_messages(
            user_message=state["user_message"],
            results_json=json.dumps(structured, ensure_ascii=False, indent=2),
            scraped_at=scraped_at,
        )
    )

    return {
        **state,
        "response_text":      llm_response.content,
        "structured_results": structured,
    }
