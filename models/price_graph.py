"""
PriceGraph — Directed Acyclic Graph (DAG) for offer combination finding.

Each node represents a price state after applying a subset of offers.
Each directed edge represents applying one additional offer.

Example for ₹22,999 phone with 3 offers:

  [ROOT ₹22,999]
      ├─(COUPON -500)──► [₹22,499]
      │                       └─(HDFC -1500)──► [₹20,999] ✅ BEST
      └─(HDFC -1500)──► [₹21,499]
                              └─(COUPON -500)──► [₹20,999] ✅ SAME (deduped)

DFS finds all leaf nodes → sort by effective_price → deduplicate by offer set.

Stacking rules enforced at edge creation:
  1. One BANK_DISCOUNT per order.
  2. COUPON stacks with BANK_DISCOUNT (most common valid combo).
  3. CASHBACK is always independent and stackable.
  4. EMI_BENEFIT / EXCHANGE are independent leaf offers.
  5. exclusive=True offers cannot stack with anything.
  6. min_order_value checked at the current node's price before edge is drawn.
  7. stackable_with list (from T&C) respected if non-empty.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from .offer import Offer, OfferType


@dataclass
class PriceNode:
    node_id: str
    price: float                            # running checkout price at this node
    applied_offers: list[Offer] = field(default_factory=list)
    cashback_total: float = 0.0             # accumulated post-purchase cashback
    parent_id: Optional[str] = None

    @property
    def effective_price(self) -> float:
        """True cost to user = checkout price minus post-purchase cashback."""
        return max(0.0, self.price - self.cashback_total)


@dataclass
class OfferCombo:
    """Represents the best offer path found for one product."""
    product_id: str
    platform: str
    checkout_price: float
    cashback: float
    effective_price: float
    applied_offers: list[Offer]
    steps: list[str]
    warnings: list[str] = field(default_factory=list)

    def rank_score(self, rating: float = 0.0, reviews: int = 0) -> tuple:
        """Lower effective_price wins; rating + reviews break ties."""
        return (round(self.effective_price, 2), -round(rating, 1), -reviews)


class PriceGraph:
    """
    Build a price DAG for one product and find the top-N cheapest offer combos.

    Usage:
        graph = PriceGraph(base_price=22999, offers=offer_list)
        best  = graph.find_best_combos(top_n=5)
    """

    def __init__(self, base_price: float, offers: list[Offer]):
        self.base_price = base_price
        self.offers = offers
        self._root = PriceNode(node_id="root", price=base_price)
        self._all_nodes: dict[str, PriceNode] = {"root": self._root}

    # ── public ────────────────────────────────────────────────────────────────

    def find_best_combos(self, top_n: int = 5) -> list[PriceNode]:
        """DFS → collect leaf nodes → deduplicate → sort → return top_n."""
        leaves: list[PriceNode] = []
        self._dfs(node=self._root, used_types=set(), leaves=leaves)

        # Always include root (no-offer baseline)
        if not any(n.node_id == "root" for n in leaves):
            leaves.append(self._root)

        # Deduplicate paths that apply the same set of offers in different orders
        seen: set[frozenset[str]] = set()
        unique: list[PriceNode] = []
        for node in sorted(leaves, key=lambda n: n.effective_price):
            key = frozenset(o.offer_id for o in node.applied_offers)
            if key not in seen:
                seen.add(key)
                unique.append(node)

        return unique[:top_n]

    # ── private ───────────────────────────────────────────────────────────────

    def _dfs(
        self,
        node: PriceNode,
        used_types: set[OfferType],
        leaves: list[PriceNode],
    ) -> None:
        expanded = False
        for offer in self.offers:
            if not self._can_apply(offer, node, used_types):
                continue
            child = self._apply_offer(offer, node)
            expanded = True
            self._dfs(child, used_types | {offer.offer_type}, leaves)
        if not expanded:
            leaves.append(node)

    def _can_apply(
        self,
        offer: Offer,
        node: PriceNode,
        used_types: set[OfferType],
    ) -> bool:
        # Already applied this exact offer on this path
        if any(o.offer_id == offer.offer_id for o in node.applied_offers):
            return False

        # Exclusive offer cannot stack with anything already applied
        if offer.exclusive and node.applied_offers:
            return False

        # Cannot add anything on top of an exclusive offer
        if any(o.exclusive for o in node.applied_offers):
            return False

        # Rule: only one BANK_DISCOUNT per order
        if (offer.offer_type == OfferType.BANK_DISCOUNT
                and OfferType.BANK_DISCOUNT in used_types):
            return False

        # T&C stackable_with constraint: if offer specifies what it stacks with,
        # all currently used types must be in that allowlist
        if offer.stackable_with:
            for used in used_types:
                if used != offer.offer_type and used not in offer.stackable_with:
                    return False

        # T&C minimum order value check at current node price
        if not offer.is_min_order_met(node.price):
            return False

        return True

    def _apply_offer(self, offer: Offer, parent: PriceNode) -> PriceNode:
        disc = offer.discount_amount(parent.price)
        cashback = (
            (offer.cashback_amount or 0.0)
            if offer.offer_type == OfferType.CASHBACK
            else 0.0
        )
        node_id = f"{parent.node_id}__{offer.offer_id}"
        child = PriceNode(
            node_id=node_id,
            price=parent.price - disc,
            applied_offers=parent.applied_offers + [offer],
            cashback_total=parent.cashback_total + cashback,
            parent_id=parent.node_id,
        )
        self._all_nodes[node_id] = child
        return child
