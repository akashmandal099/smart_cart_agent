from __future__ import annotations
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM Provider ──────────────────────────────────────────────────────────
    llm_provider: Literal["openai", "ollama"] = "ollama"

    openai_api_key: str = ""
    openai_model:   str = "gpt-4o-mini"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model:    str = "llama3.1:8b"

    llm_temperature: float = 0.0

    # ── T&C Parse Mode ────────────────────────────────────────────────────────
    # "fast" (default) — skips LLM T&C parsing entirely; uses flat_discount
    #                     directly from the scraper. Near-instant, slight loss
    #                     of detail (no min_order_value / cap from T&C text).
    # "slow"           — runs LLM on each offer's T&C text to extract structured
    #                     fields (min_order_value, max_discount_cap, card_variants,
    #                     cashback_timing etc.). More accurate, 5-30s slower.
    tc_parse_mode: Literal["fast", "slow"] = "slow"

    # ── Cache ─────────────────────────────────────────────────────────────────
    cache_ttl_products: int = 1800
    cache_ttl_offers:   int = 900
    cache_max_size:     int = 500

    # ── Scraper ───────────────────────────────────────────────────────────────
    scraper_max_concurrent: int  = 5
    scraper_min_delay_ms:   int  = 1000
    scraper_max_delay_ms:   int  = 2500
    scraper_timeout_ms:     int  = 30000
    scraper_max_per_platform: int = 5
    scraper_max_offers_per_platform_per_product: int = 5
    scraper_headless:       bool = True

    # ── App ───────────────────────────────────────────────────────────────────
    top_n_results: int = 10
    top_n_combos:  int = 5
    app_host:      str = "0.0.0.0"
    app_port:      int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    model_config = {
        "env_file":          ".env",
        "env_file_encoding": "utf-8",
        "env_ignore_empty":  True,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
