"""
Agent Node 5 — Price Calculator (fully deterministic, NO LLM)

Builds a PriceGraph per product, runs DFS to find best offer combinations,
filters offers by user's session cards, generates step-by-step instructions.
"""
from  config.settings import get_settings
from  models.agent_state import AgentState
from  models.offer import CardType, Offer, OfferType
from  models.price_graph import OfferCombo, PriceGraph
from  models.session import UserSession

_s = get_settings()


def price_calculator_node(state: AgentState) -> AgentState:
    products      = state["raw_products"]
    all_offers    = state["parsed_offers"]
    session       = state["session"]
    intent        = state["intent"]
    combos: list[OfferCombo] = []

    for product in products:
        offers      = all_offers.get(product.product_id, [])
        applicable  = _filter_by_cards(offers, session)
        graph       = PriceGraph(base_price=product.base_price, offers=applicable)
        best_nodes  = graph.find_best_combos(top_n=_s.top_n_combos)

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

    # Sort: lowest effective_price → highest rating → highest reviews
    product_map = {p.product_id: p for p in products}
    combos.sort(key=lambda c: c.rank_score(
        rating=product_map[c.product_id].rating or 0.0,
        reviews=product_map[c.product_id].review_count or 0,
    ))
    print(f"5. Calculated and ranked offer combos for {len(combos)} product(s): {combos[:intent.top_n]}")
    return {**state, "ranked_combos": combos[:intent.top_n]}


# ── helpers ───────────────────────────────────────────────────────────────────

def _filter_by_cards(offers: list[Offer], session: UserSession) -> list[Offer]:
    """Keep only offers applicable to the user's saved cards.
    If no cards saved (use_all_cards=True), return all offers unchanged."""
    if session.use_all_cards or not session.saved_cards:
        return offers
    result = []
    for offer in offers:
        if offer.bank is None:  # non-bank offers (coupons, exchange) always included
            result.append(offer)
            continue
        for card in session.saved_cards:
            if offer.applies_to_card(card.bank, card.card_type, card.card_name):
                result.append(offer)
                break
    return result


def _build_steps(offers: list[Offer], product_url: str) -> list[str]:
    """Human-readable step-by-step offer application guide."""
    steps = [f"1. Open the product page: {product_url}"]
    step = 2
    for offer in offers:
        if offer.offer_type == OfferType.COUPON:
            if offer.coupon_code and not offer.is_auto_applied:
                steps.append(f"{step}. Enter coupon code **{offer.coupon_code}** in the coupon/promo box at checkout.")
            else:
                steps.append(f"{step}. Tick the 'Apply Coupon' checkbox on the product page — discount applies automatically.")
        elif offer.offer_type == OfferType.BANK_DISCOUNT:
            disc_str = (
                f"{offer.discount_value}%"
                if offer.discount_type and offer.discount_type.value == "percentage"
                else f"₹{offer.discount_value:.0f}"
            )
            cap_str = f" (max ₹{offer.max_discount_cap:.0f})" if offer.max_discount_cap else ""
            steps.append(
                f"{step}. At checkout, select **{offer.bank} {offer.card_type.value} card**. "
                f"{disc_str} discount{cap_str} applies automatically."
            )
        elif offer.offer_type == OfferType.CASHBACK:
            steps.append(
                f"{step}. Pay with the applicable card — "
                f"₹{offer.cashback_amount:.0f} cashback will be credited "
                f"({offer.cashback_timing or 'post-purchase'})."
            )
        elif offer.offer_type == OfferType.EMI_BENEFIT:
            steps.append(f"{step}. Choose No-Cost EMI option at checkout for additional savings.")
        elif offer.offer_type == OfferType.EXCHANGE:
            steps.append(f"{step}. Add your old device for exchange to get the exchange discount.")

        if offer.terms:
            steps.append(f"   ℹ️  T&C: {offer.terms[:180]}")
        step += 1

    steps.append(f"{step}. Review the final amount at the payment screen before confirming.")
    return steps


def _build_warnings(offers: list[Offer], base_price: float) -> list[str]:
    warnings = []
    for o in offers:
        if o.min_order_value > 0 and base_price < o.min_order_value:
            warnings.append(
                f"'{o.title[:60]}' requires minimum order ₹{o.min_order_value:.0f}. "
                f"This product at ₹{base_price:.0f} may not qualify — verify at checkout."
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
