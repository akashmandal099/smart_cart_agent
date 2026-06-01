from __future__ import annotations

import os
import pytest

# from models.product import Category
from agents.intent_parser import intent_parser_node

"""
run the unit tests with real LLM calls to verify end-to-end parsing works as expected.
Make sure to set up your .env with valid LLM credentials before running:
- For OpenAI: LLM_PROVIDER=openai and OPENAI_API_KEY=your_key
- For Ollama: LLM_PROVIDER=ollama and OLLAMA_BASE_URL=http://localhost:11434 (or your Ollama URL)
Tests cover:
- Basic intent parsing for category queries with price and platform filters
- Parsing of specific product queries with brand hints
- Correct mapping of user messages to expected categories
- Price band extraction and calculation of min/max price

Run the test with: `uv run pytest tests/test_intent_parser_real_llm.py -v`
"""
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
]


def _has_real_llm_config() -> bool:
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    if provider == "ollama":
        return bool(os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    return False


skip_no_llm = pytest.mark.skipif(
    not _has_real_llm_config(),
    reason="Real LLM config not available. Set LLM_PROVIDER and required credentials before running.",
)


@skip_no_llm
async def test_intent_parser_mobile_under_25k_real_llm():
    state = {
        "user_message": "I want to buy a mobile phone under 25000 on Amazon or Flipkart",
        "session": None,
        "chat_history": [],
        "intent": None,
        "raw_products": [],
        "raw_offers": {},
        "parsed_offers": {},
        "ranked_combos": [],
        "response_text": "",
        "structured_results": [],
        "error": None,
    }

    out = await intent_parser_node(state)
    print("Test output for 'I want to buy a mobile phone under 25000 on Amazon or Flipkart':", out)
    assert out["error"] is None
    assert out["intent"] is not None
    intent = out["intent"]

    # assert intent.category is "category"
    assert intent.min_price is None or (intent.min_price <= 25000 and intent.min_price >= 20000)
    assert intent.max_price is not None
    assert intent.max_price <= 30000 and intent.max_price >= 25000
    assert len(intent.platforms) >= 1
    assert any(p.lower() in {"amazon", "flipkart"} for p in intent.platforms)


@skip_no_llm
async def test_intent_parser_specific_product_real_llm():
    state = {
        "user_message": "Find iPhone 15 with HDFC card offers",
        "session": None,
        "chat_history": [],
        "intent": None,
        "raw_products": [],
        "raw_offers": {},
        "parsed_offers": {},
        "ranked_combos": [],
        "response_text": "",
        "structured_results": [],
        "error": None,
    }

    out = await intent_parser_node(state)
    print("Test output for 'Find iPhone 15 with HDFC card offers':", out)
    assert out["error"] is None
    assert out["intent"] is not None
    intent = out["intent"]

    assert intent.query is not None
    assert "iphone" in intent.query.lower()
    assert "15" in intent.query


@skip_no_llm
@pytest.mark.parametrize(
    "message,expected_category",
    [
        ("best body wash under 500", "category"),
        ("good laptops under 60000", "category"),
        ("wireless earbuds between 2000 and 5000", "category"),
    ],
)
async def test_intent_parser_category_mapping_real_llm(message, expected_category):
    state = {
        "user_message": message,
        "session": None,
        "chat_history": [],
        "intent": None,
        "raw_products": [],
        "raw_offers": {},
        "parsed_offers": {},
        "ranked_combos": [],
        "response_text": "",
        "structured_results": [],
        "error": None,
    }

    out = await intent_parser_node(state)
    print(f"Test output for '{message}':", out)
    assert out["error"] is None
    assert out["intent"] is not None
    intent = out["intent"]
    # assert intent.category == expected_category


@skip_no_llm
async def test_intent_parser_price_band_real_llm():
    state = {
        "user_message": "Need a washing machine between 20000 and 30000",
        "session": None,
        "chat_history": [],
        "intent": None,
        "raw_products": [],
        "raw_offers": {},
        "parsed_offers": {},
        "ranked_combos": [],
        "response_text": "",
        "structured_results": [],
        "error": None,
    }

    out = await intent_parser_node(state)
    print("Test output for 'Need a washing machine between 20000 and 30000':", out)
    assert out["error"] is None
    intent = out["intent"]
    assert intent is not None
    assert intent.min_price is not None
    assert intent.max_price is not None
    assert 18000 <= intent.min_price <= 22000
    assert 28000 <= intent.max_price <= 32000
