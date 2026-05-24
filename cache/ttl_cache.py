"""
Thread-safe TTL cache using cachetools.
Two separate caches:
  _product_cache  — TTL 30 min (product listings)
  _offer_cache    — TTL 15 min (offer data changes faster)

On-demand refresh: call invalidate_all() or per-key invalidators.
Future nightly batch warm-up can call set_products() / set_offers() directly.
"""
import hashlib
import json
import threading

from cachetools import TTLCache
from  config.settings import get_settings

_s = get_settings()
_lock = threading.Lock()

_product_cache: TTLCache = TTLCache(
    maxsize=_s.cache_max_size,
    ttl=_s.cache_ttl_products,
)
_offer_cache: TTLCache = TTLCache(
    maxsize=_s.cache_max_size,
    ttl=_s.cache_ttl_offers,
)


# ── key helpers ───────────────────────────────────────────────────────────────

def _key(data: dict) -> str:
    return hashlib.md5(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()


# ── Products ──────────────────────────────────────────────────────────────────

def get_products(query: str, platform: str, price_min: float, price_max: float):
    k = _key({"q": query, "pl": platform, "mn": price_min, "mx": price_max})
    with _lock:
        return _product_cache.get(k)


def set_products(
    query: str, platform: str, price_min: float, price_max: float, data
) -> None:
    k = _key({"q": query, "pl": platform, "mn": price_min, "mx": price_max})
    with _lock:
        _product_cache[k] = data


def invalidate_products(
    query: str, platform: str, price_min: float, price_max: float
) -> None:
    k = _key({"q": query, "pl": platform, "mn": price_min, "mx": price_max})
    with _lock:
        _product_cache.pop(k, None)


# ── Offers ────────────────────────────────────────────────────────────────────

def get_offers(product_id: str, platform: str):
    k = _key({"pid": product_id, "pl": platform})
    with _lock:
        return _offer_cache.get(k)


def set_offers(product_id: str, platform: str, data) -> None:
    k = _key({"pid": product_id, "pl": platform})
    with _lock:
        _offer_cache[k] = data


def invalidate_offers(product_id: str, platform: str) -> None:
    k = _key({"pid": product_id, "pl": platform})
    with _lock:
        _offer_cache.pop(k, None)


# ── Global ────────────────────────────────────────────────────────────────────

def invalidate_all() -> None:
    """Called on manual refresh request from user."""
    with _lock:
        _product_cache.clear()
        _offer_cache.clear()


def cache_stats() -> dict:
    with _lock:
        return {
            "product_cache_size": len(_product_cache),
            "offer_cache_size": len(_offer_cache),
            "product_cache_maxsize": _product_cache.maxsize,
            "offer_cache_maxsize": _offer_cache.maxsize,
        }
