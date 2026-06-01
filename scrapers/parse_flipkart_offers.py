"""
parse_flipkart_offers.py
─────────────────────────
Standalone utility that parses Flipkart offer data from a saved HTML page body.
Use this when you already have the HTML (e.g. from a Playwright snapshot) and
don't need a live browser session.

For live scraping (including T&C click-through for BHIM/Mobikwik),
use FlipkartScraper.scrape_offers() in flipkart.py instead.

Usage
─────
    python -m smartcart_backend.scrapers.parse_flipkart_offers <html_file>

    OR import directly:
        from smartcart_backend.scrapers.parse_flipkart_offers import extract_offers_from_html
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup


# ─────────────────────────────────────────────────────────────────────────────
# Data class
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ParsedOffer:
    amount_text: str            # raw string e.g. "₹1,050 off"
    flat_discount: float        # 1050.0
    bank: Optional[str]         # "Flipkart Axis", "BHIM", "Mobikwik" …
    offer_type: str             # "Credit Card • Cashback", "UPI • Cashback" …
    terms: str = ""             # populated when static T&C is present in HTML;
                                # empty when dynamic click is needed (see note above)
    requires_browser_click: bool = False  # True → use FlipkartScraper for full T&C


# ─────────────────────────────────────────────────────────────────────────────
# Inline-style helpers
#
# Flipkart's React DOM stores ALL styling as inline style attributes.
# Font families are written as  inter_bold  and  inter_regular  (underscore).
# ─────────────────────────────────────────────────────────────────────────────

def _style_has(style: str, *fragments: str) -> bool:
    """Return True if every fragment appears in the style string (case-insensitive, space-agnostic)."""
    s = re.sub(r"\s+", "", (style or "")).lower()
    return all(re.sub(r"\s+", "", f).lower() in s for f in fragments)


def _first_text(tag, **find_kwargs) -> str:
    el = tag.find(**find_kwargs) if find_kwargs else None
    return el.get_text(strip=True) if el else ""


def _rupee_to_float(text: str) -> float:
    cleaned = re.sub(r"[^\d]", "", text)
    return float(cleaned) if cleaned else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Card root detection
#
# Confirmed card root style (May 2026):
#   border-width: 1px;
#   border-radius: 12px;
#   border-color: rgb(235, 235, 235);
#   width: 220px;
# ─────────────────────────────────────────────────────────────────────────────

def _is_card_root(tag) -> bool:
    style = tag.get("style", "")
    return (
        _style_has(style, "border-width:1px")
        and _style_has(style, "border-radius:12px")
        and _style_has(style, "width:220px")
    )


# ─────────────────────────────────────────────────────────────────────────────
# T&C extraction — static HTML path
# ─────────────────────────────────────────────────────────────────────────────

_STATIC_TNC_BANKS = re.compile(
    r"flipkart\s*axis|axis|flipkart\s*sbi|sbi|icici|hdfc|kotak",
    re.I,
)
_TNC_KEYWORDS = {
    "cashback", "eligible", "applicable", "minimum transaction",
    "maximum", "statement quarter", "billing cycle",
}


def _extract_static_tnc(soup: BeautifulSoup, bank_name: str) -> str:
    """
    Walk the DOM near the bank_name text node looking for a container
    that has ≥3 T&C keywords.  Returns up to 12 bullet sentences.
    Returns "" if not found (dynamic click required).
    """
    for node in soup.find_all(string=re.compile(re.escape(bank_name), re.I)):
        container = node.parent
        for _ in range(7):
            if container is None:
                break
            all_text = container.get_text(separator=" ", strip=True).lower()
            if sum(1 for kw in _TNC_KEYWORDS if kw in all_text) >= 3:
                sentences = []
                for t in container.find_all(string=True):
                    s = str(t).strip()
                    if len(s) > 35 and not s.startswith("₹") and s not in sentences:
                        sentences.append(s)
                if len(sentences) >= 3:
                    return "\n".join(sentences[:12])
            container = container.parent

    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction function
# ─────────────────────────────────────────────────────────────────────────────

def extract_offers_from_html(html: str) -> list[ParsedOffer]:
    """
    Parse all bank/card offers from a Flipkart product page HTML string.

    Returns a deduplicated list of ParsedOffer objects.
    For offers where T&C requires a browser click (BHIM, Mobikwik, etc.),
    the `requires_browser_click` flag is set to True and `terms` is "".
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[ParsedOffer] = []

    # ── Step 1: find all offer card roots ─────────────────────────────────────
    card_roots = [tag for tag in soup.find_all("div", style=True) if _is_card_root(tag)]

    for card in card_roots:

        # ── Amount  (inter_bold + 16px) ───────────────────────────────────────
        amount_el = None
        for child in card.find_all("div", style=True):
            s = child.get("style", "")
            if _style_has(s, "inter_bold") and (
                _style_has(s, "font-size:16px") or _style_has(s, "font-size:15px")
            ):
                t = child.get_text(strip=True)
                if re.match(r"^[₹\d,]+\s*off$", t, re.I):
                    amount_el = child
                    amount_text = t
                    break

        if not amount_el:
            continue

        flat = _rupee_to_float(amount_text)
        if flat == 0:
            continue

        # ── Bank / program  (inter_regular + 14px) ────────────────────────────
        bank = ""
        for child in card.find_all("div", style=True):
            s = child.get("style", "")
            if _style_has(s, "inter_regular") and (
                _style_has(s, "font-size:14px") or _style_has(s, "font-size:12px")
            ):
                t = child.get_text(strip=True)
                if t and t != "Apply":
                    bank = t
                    break

        # ── Offer type label  (inter_bold + 14px + pre-wrap) ─────────────────
        offer_type = ""
        for child in card.find_all("div", style=True):
            s = child.get("style", "")
            if _style_has(s, "inter_bold", "14px", "pre-wrap"):
                t = child.get_text(strip=True)
                if any(kw in t for kw in [
                    "Credit Card", "Debit Card", "UPI", "Cashback", "EMI", "Coupon"
                ]):
                    offer_type = t
                    break

        # ── T&C ───────────────────────────────────────────────────────────────
        terms = ""
        needs_click = False
        if bank and _STATIC_TNC_BANKS.search(bank):
            terms = _extract_static_tnc(soup, bank)
        if not terms:
            needs_click = True  # caller should use FlipkartScraper for full T&C

        results.append(ParsedOffer(
            amount_text=amount_text,
            flat_discount=flat,
            bank=bank or None,
            offer_type=offer_type or "Bank Offer",
            terms=terms,
            requires_browser_click=needs_click,
        ))

    # ── Deduplicate by (flat_discount, bank, offer_type) ──────────────────────
    seen: set[tuple] = set()
    deduped: list[ParsedOffer] = []
    for o in results:
        key = (o.flat_discount, o.bank, o.offer_type)
        if key not in seen:
            seen.add(key)
            deduped.append(o)

    return deduped


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "paste.txt"
    with open(path, "r", encoding="utf-8") as f:
        html_body = f.read()

    offers = extract_offers_from_html(html_body)
    print(f"Found {len(offers)} offer(s):\n")
    for o in offers:
        status = "⚠ browser click needed for T&C" if o.requires_browser_click else "✓ T&C in HTML"
        print(f"  • {o.amount_text:<16}  Bank: {o.bank or '—':<22}  Type: {o.offer_type:<30}  [{status}]")
        if o.terms:
            first_line = o.terms.split("\n")[0][:90]
            print(f"    T&C[0]: {first_line}")
        print()