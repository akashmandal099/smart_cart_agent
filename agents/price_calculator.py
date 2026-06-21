"""
Agent Node 5 — Price Calculator (fully deterministic, NO LLM)

Builds a PriceGraph per product, runs DFS to find best offer combinations,
filters offers by user's session cards, generates step-by-step instructions.
"""
from config.settings import get_settings
from models.agent_state import AgentState
from models.offer import CardType, DiscountType, Offer, OfferType
from models.price_graph import OfferCombo, PriceGraph
from models.session import UserSession

_s = get_settings()


def price_calculator_node(state: AgentState) -> AgentState:
    products   = state["raw_products"]
    all_offers = state["parsed_offers"]
    session    = state["session"]
    intent     = state["intent"]
    combos: list[OfferCombo] = []

    for product in products:
        offers     = all_offers.get(product.product_id, [])
        applicable = _filter_by_cards(offers, session)
        graph      = PriceGraph(base_price=product.base_price, offers=applicable)
        best_nodes = graph.find_best_combos(top_n=_s.top_n_combos)

        for node in best_nodes:
            steps    = _build_steps(node.applied_offers, product.product_url)
            warnings = _build_warnings(node.applied_offers, product.base_price)
            combos.append(OfferCombo(
                product_id=product.product_id,
                platform=product.platform.value,
                checkout_price=round(node.price, 2),
                cashback=round(node.cashback_total, 2),
                effective_price=round(node.effective_price, 2),
                applied_offers=node.applied_offers,
                steps=steps,
                warnings=warnings,
            ))

    product_map = {p.product_id: p for p in products}
    combos.sort(key=lambda c: c.rank_score(
        rating=product_map[c.product_id].rating or 0.0,
        reviews=product_map[c.product_id].review_count or 0,
    ))

    return {**state, "ranked_combos": combos[:intent.top_n]}


# ── helpers ───────────────────────────────────────────────────────────────────

def _filter_by_cards(offers: list[Offer], session: UserSession) -> list[Offer]:
    if session.use_all_cards or not session.saved_cards:
        return offers
    result = []
    for offer in offers:
        if offer.bank is None:
            result.append(offer)
            continue
        for card in session.saved_cards:
            if offer.applies_to_card(card.bank, card.card_type, card.card_name):
                result.append(offer)
                break
    return result


def _fmt_discount(offer: Offer) -> str:
    """Safe discount string — never crashes on None values."""
    if offer.discount_type == DiscountType.PERCENTAGE and offer.discount_value:
        cap = f" (max ₹{offer.max_discount_cap:.0f})" if offer.max_discount_cap else ""
        return f"{offer.discount_value:.1f}%{cap}"
    val = offer.discount_value or offer.flat_discount or 0
    cap = f" (max ₹{offer.max_discount_cap:.0f})" if offer.max_discount_cap else ""
    return f"₹{val:.0f}{cap}" if val else "discount"


def _build_steps(offers: list[Offer], product_url: str) -> list[str]:
    steps = [f"1. Open the product page: {product_url}"]
    step  = 2

    for offer in offers:
        bank_label = offer.bank or "bank"
        card_label = offer.card_type.value if offer.card_type else "card"

        if offer.offer_type == OfferType.COUPON:
            if offer.coupon_code and not offer.is_auto_applied:
                steps.append(
                    f"{step}. Enter coupon code **{offer.coupon_code}** "
                    "in the coupon/promo box at checkout."
                )
            else:
                steps.append(
                    f"{step}. Tick the 'Apply Coupon' checkbox on the product page "
                    "— discount applies automatically."
                )

        elif offer.offer_type == OfferType.BANK_DISCOUNT:
            steps.append(
                f"{step}. At checkout, select **{bank_label} {card_label} card**. "
                f"{_fmt_discount(offer)} discount applies automatically."
            )

        elif offer.offer_type == OfferType.CASHBACK:
            # ── FIX: guard cashback_amount being None ─────────────────────────
            cb_amt  = offer.cashback_amount or offer.flat_discount or 0
            cb_time = offer.cashback_timing or "post-purchase"
            steps.append(
                f"{step}. Pay with **{bank_label} {card_label}** — "
                f"₹{cb_amt:.0f} cashback credited ({cb_time})."
            )

        elif offer.offer_type == OfferType.EMI_BENEFIT:
            steps.append(
                f"{step}. Choose No-Cost EMI at checkout for additional savings."
            )

        elif offer.offer_type == OfferType.EXCHANGE:
            steps.append(
                f"{step}. Add your old device for exchange to get the exchange discount."
            )

        else:
            # Generic fallback for unknown offer types
            steps.append(
                f"{step}. Apply **{offer.title[:80]}** offer at checkout."
            )

        if offer.terms:
            steps.append(f"   ℹ️  T&C: {offer.terms[:180]}")
        step += 1

    steps.append(f"{step}. Review the final amount at the payment screen before confirming.")
    return steps


def _build_warnings(offers: list[Offer], base_price: float) -> list[str]:
    warnings = []
    for o in offers:
        if o.min_order_value and o.min_order_value > 0 and base_price < o.min_order_value:
            warnings.append(
                f"'{o.title[:60]}' requires minimum order ₹{o.min_order_value:.0f}. "
                f"Product at ₹{base_price:.0f} may not qualify — verify at checkout."
            )
        if o.max_discount_cap:
            warnings.append(
                f"'{o.title[:60]}' discount capped at ₹{o.max_discount_cap:.0f}."
            )
    if not offers:
        warnings.append("No additional offers found — base price applies.")
    warnings.append(
        "⚠️ Personalised / account-specific offers are not included. "
        "Always verify the final price at checkout before payment."
    )
    return warnings
