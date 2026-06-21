"""
Agent Node 6 — Response Formatter

Formats pre-computed ranked_combos into:
  • response_text      — markdown chat message (LLM-generated framing)
  • structured_results — list[dict] consumed by Streamlit result cards

LLM is ONLY used for natural-language framing. Prices are NEVER recalculated here.

No-results fix: combos may exist but route through response_formatter even when
product_search returned 0 products (edge case). Guard both cases explicitly.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from langchain_core.prompts import ChatPromptTemplate

from config import get_llm
from models.agent_state import AgentState

_llm    = get_llm(temperature=0.3, json_mode=False)
_prompt = ChatPromptTemplate.from_messages([
    ("system", """You are SmartCart AI, a shopping assistant for Indian e-commerce.
Present pre-computed deal results in clear markdown.

STRICT RULES:
- Use EXACT prices from the data — NEVER recalculate or change any number
- Short intro sentence, then a numbered list (one item per product)
- Each item: product name, platform emoji (🔵 Flipkart / 🟠 Amazon),
  checkout price, effective price (only if cashback > 0), applicable offer names
- Mark rank 1 with ✅ Best Deal
- Checkout price = amount charged at checkout
- Effective price = checkout price minus post-purchase cashback
- Finish with exactly one line: "Prices fetched at {scraped_at} IST. Always verify at checkout."
- No markdown code blocks, no extra commentary"""),
    ("human",
     "User asked: {user_message}\n\n"
     "Results (use these exact numbers):\n{results_json}\n\n"
     "Scraped at: {scraped_at}"),
])


async def response_formatter_node(state: AgentState) -> AgentState:
    combos   = state.get("ranked_combos") or []
    products = {p.product_id: p for p in (state.get("raw_products") or [])}

    # ── No products / no combos ───────────────────────────────────────────────
    if not combos or not products:
        return {
            **state,
            "response_text": (
                "Sorry, I couldn't find any matching products. "
                "Try a broader price range, different product name, or another platform."
            ),
            "structured_results": [],
        }

    # ── Build structured results (one entry per combo) ────────────────────────
    # Deduplicate: keep only the best combo per product_id
    seen_pids: set[str] = set()
    top_combos = []
    for c in combos:
        if c.product_id not in seen_pids:
            seen_pids.add(c.product_id)
            top_combos.append(c)

    structured: list[dict] = []
    for rank, combo in enumerate(top_combos, 1):
        p = products.get(combo.product_id)
        if p is None:
            continue

        offer_details = []
        for o in combo.applied_offers:
            disc = round(o.discount_amount(p.base_price), 2)
            offer_details.append({
                "title":           o.title,
                "bank":            o.bank,
                "card_type":       o.card_type.value,
                "discount":        disc,
                "coupon_code":     o.coupon_code,
                "is_auto_applied": o.is_auto_applied,
                "cashback_timing": o.cashback_timing,
                "terms":           o.terms,
            })

        structured.append({
            "rank":           rank,
            "title":          p.title,
            "platform":       combo.platform,
            "rating":         p.rating,
            "review_count":   p.review_count,
            "image_url":      p.image_url,
            "product_url":    p.product_url,
            "base_price":     p.base_price,
            "checkout_price": combo.checkout_price,
            "cashback":       combo.cashback,
            "effective_price":combo.effective_price,
            "offers":         offer_details,
            "steps":          combo.steps,
            "warnings":       combo.warnings,
        })

    if not structured:
        return {
            **state,
            "response_text": (
                "Products were found but could not be formatted. "
                "Please try again."
            ),
            "structured_results": [],
        }

    # ── LLM framing ───────────────────────────────────────────────────────────
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    try:
        llm_response = await _llm.ainvoke(
            _prompt.format_messages(
                user_message=state["user_message"],
                results_json=json.dumps(structured, ensure_ascii=False, indent=2),
                scraped_at=scraped_at,
            )
        )
        response_text = llm_response.content.strip()
    except Exception as exc:
        # LLM framing failed — generate a plain-text fallback instead
        print(f"[response_formatter] LLM call failed: {exc}")
        lines = [f"Here are the top deals for your query:\n"]
        for item in structured:
            best = "✅ Best Deal — " if item["rank"] == 1 else f"#{item['rank']} — "
            pf   = "🔵 Flipkart" if item["platform"] == "flipkart" else "🟠 Amazon"
            lines.append(
                f"{best}**{item['title']}** ({pf})  \n"
                f"  Checkout price: **₹{item['checkout_price']:,.0f}**"
                + (f"  |  Effective: ₹{item['effective_price']:,.0f} (after cashback)" if item["cashback"] > 0 else "")
            )
        lines.append(f"\n_Prices fetched at {scraped_at} IST. Always verify at checkout._")
        response_text = "\n".join(lines)

    return {
        **state,
        "response_text":      response_text,
        "structured_results": structured,
    }
