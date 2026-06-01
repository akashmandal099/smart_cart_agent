from .amazon import AmazonScraper
from .flipkart import FlipkartScraper
from .parse_flipkart_offers import ParsedOffer, extract_offers_from_html
from .utils import parse_price, random_delay, random_ua, safe_attr, safe_text

__all__ = [
    "AmazonScraper",
    "FlipkartScraper",
    "ParsedOffer",
    "extract_offers_from_html",
    "parse_price",
    "random_delay",
    "random_ua",
    "safe_attr",
    "safe_text",
]