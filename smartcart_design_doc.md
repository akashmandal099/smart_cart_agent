# SmartCart AI — System Design Document

**Version:** 1.0  
**Stack:** Python 3.12 · FastAPI · LangGraph · Streamlit · Pydantic · cachetools  
**LLM Providers:** Ollama (local, default) · OpenAI (cloud, optional)  
**Platforms supported:** Amazon India · Flipkart  

---

## 1. Overview

SmartCart AI is a conversational shopping assistant that helps users find the lowest
checkout price for products on Amazon India and Flipkart. Given a free-text query
(category or specific product) with an optional price range, the system:

1. Interprets the user's intent using an LLM
2. Fetches live product listings from both platforms
3. Collects available bank-card offers, coupons, cashback, and exchange deals per product
4. Deterministically calculates every valid offer combination using a price DAG
5. Returns a ranked list of products with the lowest effective checkout price, complete with
   step-by-step instructions for applying each offer at checkout

The system is designed to be **LLM-light**: the LLM is used only for natural language
understanding and response framing. All price arithmetic is handled by deterministic
Python code, ensuring accuracy and eliminating hallucinated numbers.

---

## 2. Repository Layout

```
backend/
├── main.py                        # FastAPI app entry point
├── pyproject.toml                 # uv / pip dependencies
├── .env.example                   # all configurable env vars
├── run_backend.sh                 # start uvicorn
├── run_frontend.sh                # start streamlit
├── run_all.sh                     # start both concurrently
│
├── api/
│   └── routes.py                  # REST endpoints (/api/chat, /api/session/*, /api/cache/*)
│
├── agents/
│   ├── graph.py                   # LangGraph StateGraph definition + compiled singleton
│   ├── intent_parser.py           # Node 1 — LLM: free text → QueryIntent
│   ├── product_search.py          # Node 2 — scrape product listings (cached)
│   ├── offer_fetcher.py           # Node 3 — scrape offers per product (cached)
│   ├── tc_parser.py               # Node 4 — fast/slow offer field extraction
│   ├── price_calculator.py        # Node 5 — deterministic PriceGraph DFS
│   ├── response_formatter.py      # Node 6 — LLM: format markdown + structured results
│   └── card_extractor.py          # Utility — extract card mentions from user message
│
├── models/
│   ├── agent_state.py             # LangGraph TypedDict state + QueryIntent/QueryType
│   ├── product.py                 # Product, Platform
│   ├── offer.py                   # Offer, OfferType, DiscountType, CardType
│   ├── price_graph.py             # PriceGraph, PriceNode, OfferCombo
│   └── session.py                 # UserSession, SessionCard (alias: SavedCard)
│
├── scrapers/
│   ├── base.py                    # BaseScraper ABC
│   ├── amazon.py                  # AmazonScraper
│   ├── flipkart.py                # FlipkartScraper
│   ├── flipkart_fix.py            # Flipkart HTML edge-case patches
│   ├── parse_flipkart_offers.py   # Flipkart offer card parser
│   └── utils.py                   # Shared HTTP, retry, delay helpers
│
├── config/
│   ├── settings.py                # Pydantic-settings: all env-driven config
│   └── llm_factory.py             # get_llm() — returns ChatOpenAI or ChatOllama
│
├── cache/
│   └── ttl_cache.py               # Thread-safe TTLCache for products + offers
│
├── frontend/
│   └── streamlit_app.py           # Streamlit chat UI with live status streaming
│
└── tests/
    ├── conftest.py
    ├── test_intent_parser.py
    ├── test_intent_parser_real_llm.py
    └── test_scrapers.py
```

---

## 3. Architecture

### 3.1 High-Level Data Flow

```
User (Streamlit or REST client)
        │
        │ natural-language message
        ▼
┌─────────────────────────────────────────────────────┐
│                   FastAPI  /api/chat                │
│  1. card_extractor  — update session cards          │
│  2. build AgentState                                │
│  3. smartcart_graph.ainvoke(state)                  │
└───────────────────────┬─────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────┐
        │   LangGraph StateGraph    │
        │                           │
        │  intent_parser            │  LLM (json_mode)
        │       │                   │
        │  product_search ──────────┼──► AmazonScraper + FlipkartScraper
        │       │ (no results)      │    (TTLCache hit or live HTTP)
        │       │──────────────────►│  response_formatter → END
        │       │ (results)         │
        │  offer_fetcher ───────────┼──► per-product offer scrape
        │       │                   │    (TTLCache hit or live HTTP)
        │  tc_parser                │  fast: promote flat_discount
        │       │                   │  slow: LLM extracts T&C fields
        │  price_calculator         │  PriceGraph DFS (pure Python)
        │       │                   │
        │  response_formatter ──────┼──► LLM framing + structured_results
        │       │                   │
        │     END                   │
        └───────────────────────────┘
                        │
                        ▼
        ChatResponse { response_text, structured_results }
                        │
                        ▼
            Streamlit renders markdown
            + result cards + offer steps
```

### 3.2 LangGraph State

Every node reads from and returns a new `AgentState` dict. LangGraph merges outputs
between nodes automatically.

```python
class AgentState(TypedDict):
    # Inputs
    user_message:   str
    session:        UserSession
    chat_history:   list[dict]
    tc_parse_mode:  Optional[Literal["fast", "slow"]]

    # Intermediate
    intent:         Optional[QueryIntent]
    raw_products:   list[Product]
    raw_offers:     dict[str, list[Offer]]   # product_id → scraped offers
    parsed_offers:  dict[str, list[Offer]]   # product_id → structured offers

    # Outputs
    ranked_combos:      list[OfferCombo]
    response_text:      str
    structured_results: list[dict]
    error:              Optional[str]
```

### 3.3 Conditional Routing

```
intent_parser → error?         → error_handler → END
              → ok             → product_search

product_search → error?        → error_handler → END
               → 0 results     → response_formatter → END
               → has results   → offer_fetcher → tc_parser → price_calculator
                                                            → response_formatter → END
```

---

## 4. Agent Nodes (Pipeline Stages)

### Node 1 — `intent_parser`

**Role:** Translate the user's free-text message into a structured `QueryIntent`.  
**LLM used:** Yes (`temperature=0.0`, `json_mode=True`).

Parses:

| Field | Example input | Parsed output |
|---|---|---|
| `query_type` | "best mobile under 25K" | `category` |
| `product` | "Samsung Galaxy S25 FE" | `specific_product` |
| `price_min` / `price_max` | "20K–25K", "under ₹25,000", "around 20K" | `20000` / `25000` |
| `brand_hint` | "show only Samsung" | `"Samsung"` |
| `platforms` | "only on Amazon" | `["amazon"]` |
| `top_n` | "top 5 only" | `5` |

Price conversion rules are baked into the system prompt (K → ×1000, lakh → ×100000,
"around X" → ±15%, "under X" → min=0). Conversation history (last 6 turns) is included
for follow-up resolution ("show only Samsung" refers to the previous query's category).

**Output fields set:** `intent`

---

### Node 2 — `product_search`

**Role:** Fetch product listings from Amazon and Flipkart matching the parsed intent.  
**LLM used:** No.

- Runs both platform scrapers **concurrently** via `asyncio.gather`.
- Checks TTL cache first (key: query + platform + price range, TTL 30 min).
- Filters by `price_min` / `price_max` and optional `brand_hint` after scraping.
- Returns up to `scraper_max_per_platform` products per platform.
- Empty results route directly to `response_formatter`, skipping offer stages.

**Output fields set:** `raw_products`

---

### Node 3 — `offer_fetcher`

**Role:** Fetch raw offer text and T&C strings for each product.  
**LLM used:** No.

- Runs up to `scraper_max_concurrent` (default: 5) concurrent fetches using an
  `asyncio.Semaphore`.
- Checks offer TTL cache first (key: product_id + platform, TTL 15 min).
- Each scraper returns a list of `Offer` objects with `flat_discount` populated from
  the "₹X off" label visible on the offer card, and `terms` containing the raw T&C text.

**Output fields set:** `raw_offers`

---

### Node 4 — `tc_parser`

**Role:** Promote raw scraped offer data into structured `Offer` fields.  
**Two modes** — switchable per request via `tc_parse_mode` in `AgentState` or globally
via `TC_PARSE_MODE` in `.env`.

#### Fast Mode (default)

No LLM call. Directly promotes `flat_discount → discount_value` and
`flat_discount → cashback_amount` (for CASHBACK offers). Takes < 1ms per product.
Trade-off: `min_order_value`, `max_discount_cap`, and `card_variants` remain at their
default values (0 / null / []) unless the scraper already populated them.

#### Slow Mode

Sends `[{offer_id, title, terms}]` for all offers on a product to the LLM in a single
batch call. The LLM extracts:

- `min_order_value` — minimum cart value for the offer to apply
- `max_discount_cap` — maximum ₹ cap on percentage discounts
- `card_variants` — specific card names within the bank (e.g. "Regalia", "Infinia")
- `cashback_timing` — instant / statement_credit / wallet
- `exclusive` — whether the offer cannot be combined with others
- `stackable_with` — offer types it can legally stack with

If the LLM response is malformed or returns 0 for a discount where `flat_discount > 0`,
the fast-mode value is used as a fallback per offer.

**Output fields set:** `parsed_offers`

---

### Node 5 — `price_calculator`

**Role:** Find the best offer combinations for each product.  
**LLM used:** No — fully deterministic.

#### PriceGraph Algorithm

For each product, builds a DAG where:
- **Root node** = base price, no offers applied
- **Each directed edge** = applying one additional offer
- **Leaf nodes** = states where no more valid offers can be stacked

```
[ROOT ₹22,999]
    ├─(COUPON -₹500)──► [₹22,499]
    │                        └─(HDFC CC -₹1,500)──► [₹20,999] ← best checkout
    └─(HDFC CC -₹1,500)──► [₹21,499]
                                 └─(COUPON -₹500)──► [₹20,999] ← deduplicated
```

**Stacking rules enforced at edge creation:**

1. Only one `BANK_DISCOUNT` per order
2. `COUPON` stacks with `BANK_DISCOUNT` (most common valid combo)
3. `CASHBACK` is always independent (never deducted at checkout — tracked separately)
4. `EMI_BENEFIT` and `EXCHANGE` are independent, non-stackable leaf offers
5. `exclusive=True` offers cannot stack with anything
6. T&C `stackable_with` list respected if non-empty
7. `min_order_value` checked at the **current node price** before drawing each edge

**Price separation:**

- `checkout_price` = price actually charged at payment — what matters for the user's card/wallet
- `cashback` = post-purchase credit (tracked but not deducted at checkout)
- `effective_price` = `checkout_price − cashback` — true long-run cost

**Card filtering:** If the user has saved cards, only offers applicable to those cards are
included in the graph. `use_all_cards=True` (default) includes all offers.

**Output fields set:** `ranked_combos`

---

### Node 6 — `response_formatter`

**Role:** Convert `ranked_combos` into the final chat response.  
**LLM used:** Yes (`temperature=0.3`) — for natural language framing only.

Two outputs are produced:

**`response_text`** — Markdown string shown in the chat bubble. The LLM is given the
pre-computed `structured_results` JSON and instructed to use exact numbers verbatim.
If the LLM call fails, a plain-text fallback is generated deterministically.

**`structured_results`** — `list[dict]` consumed by the Streamlit result cards renderer.
Each entry contains: title, platform, rating, review_count, image_url, product_url,
base_price, checkout_price, cashback, effective_price, applied offers, step-by-step
instructions, and warnings.

**Deduplication:** Only the best combo per `product_id` is shown in results
(one card per product, lowest effective price).

**Output fields set:** `response_text`, `structured_results`

---

## 5. Data Models

### `Product`

| Field | Type | Description |
|---|---|---|
| `platform` | `Platform` enum | `amazon` or `flipkart` |
| `product_id` | `str` | Platform-native product identifier |
| `title` | `str` | Full product name |
| `base_price` | `float` | Current selling price (excluding all offers) |
| `mrp` | `float?` | Maximum Retail Price (for discount % display) |
| `rating` | `float?` | Star rating (0–5) |
| `review_count` | `int?` | Number of reviews |
| `product_url` | `str` | Direct buy link |
| `image_url` | `str?` | Product thumbnail |
| `in_stock` | `bool` | Availability flag |

### `Offer`

| Field | Type | Source | Description |
|---|---|---|---|
| `flat_discount` | `float` | Scraper | "₹X off" from offer card label |
| `discount_type` | `DiscountType?` | tc_parser | `percentage` or `flat` |
| `discount_value` | `float` | tc_parser | Value for the discount type |
| `max_discount_cap` | `float?` | tc_parser (slow) | Max ₹ cap on % discounts |
| `min_order_value` | `float` | tc_parser (slow) | Minimum cart total required |
| `cashback_amount` | `float?` | tc_parser | Post-purchase cashback ₹ |
| `cashback_timing` | `str?` | tc_parser (slow) | instant / statement_credit / wallet |
| `coupon_code` | `str?` | Scraper | Promo code string |
| `is_auto_applied` | `bool` | Scraper | Auto-applied vs. manual entry |
| `exclusive` | `bool` | tc_parser (slow) | Cannot be combined |
| `stackable_with` | `list[OfferType]` | tc_parser (slow) | Allowed stacking partners |

### `UserSession`

| Field | Type | Description |
|---|---|---|
| `session_id` | `str` | UUID, auto-generated if not provided |
| `saved_cards` | `list[SessionCard]` | User's credit/debit cards (bank + variant + type) |
| `use_all_cards` | `bool` | `True` = show all offers regardless of card |

Sessions are stored in-process in a `dict[str, UserSession]` in `api/routes.py`. Cards
are never persisted to disk — session state resets on server restart.

---

## 6. Scraper Layer

### Abstract Base (`scrapers/base.py`)

Both scrapers implement:

```python
class BaseScraper(ABC):
    async def search_products(intent: QueryIntent) -> list[Product]: ...
    async def scrape_offers(product: Product) -> list[Offer]: ...
```

### Rate Limiting & Retry

Shared via `scrapers/utils.py`:
- Random delay between requests: `scraper_min_delay_ms` to `scraper_max_delay_ms` (default 1–2.5s)
- Concurrency cap via `asyncio.Semaphore(scraper_max_concurrent)` in `offer_fetcher`
- Per-request timeout: `scraper_timeout_ms` (default 30s)

### Flipkart (`scrapers/flipkart.py`)

Parses Flipkart's search results and product pages via HTML scraping.
Edge cases handled in `flipkart_fix.py`. Offer card parsing isolated in
`parse_flipkart_offers.py` for maintainability (Flipkart's offer card HTML
structure changes frequently).

### Amazon (`scrapers/amazon.py`)

Parses Amazon India search results and product pages. Extracts bank offers,
coupons (including auto-apply checkbox coupons), and exchange offers from
the product detail page offer section.

---

## 7. Caching

Two separate `cachetools.TTLCache` instances, both protected by a `threading.Lock`:

| Cache | Key | TTL | Rationale |
|---|---|---|---|
| `_product_cache` | MD5(query + platform + price_min + price_max) | 30 min | Product listings change slowly |
| `_offer_cache` | MD5(product_id + platform) | 15 min | Offers (especially bank deals) refresh more often |

**Cache invalidation:**
- `DELETE /api/cache` — clears both caches immediately
- `POST /api/chat` with `force_refresh: true` — clears then re-fetches
- TTL expiry — automatic

Cache stats are exposed at `GET /api/cache/stats`.

---

## 8. LLM Configuration

### `config/llm_factory.py` — `get_llm()`

Returns either `ChatOllama` or `ChatOpenAI` based on `LLM_PROVIDER` env var.
All nodes call `get_llm()` — swapping the provider requires only a `.env` change.

```
LLM_PROVIDER=ollama  →  ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL)
LLM_PROVIDER=openai  →  ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY)
```

### LLM Usage per Node

| Node | Temperature | json_mode | Purpose |
|---|---|---|---|
| `intent_parser` | 0.0 | True | Structured JSON extraction — needs determinism |
| `card_extractor` | 0.0 | True | Structured JSON extraction |
| `tc_parser` (slow) | 0.0 | True | Structured JSON extraction |
| `response_formatter` | 0.3 | False | Natural language — slight variation acceptable |

### Cost Profile (fast mode, Ollama local)

With fast T&C mode (default), only 2 LLM calls are made per query:
`intent_parser` + `response_formatter`. At ~300–500 tokens per call, total LLM
cost on OpenAI GPT-4o-mini is approximately ₹0.05–0.10 per query.

---

## 9. REST API

Base path: `/api`  
Interactive docs: `http://localhost:8000/docs`

### `POST /api/chat`

Main query endpoint. Runs the full LangGraph pipeline.

**Request:**
```json
{
  "session_id": "optional-uuid",
  "message": "best 5 phones under 25000",
  "chat_history": [],
  "force_refresh": false
}
```

**Response:**
```json
{
  "session_id": "uuid",
  "response_text": "## Top 5 Phones Under ₹25,000\n...",
  "structured_results": [
    {
      "rank": 1,
      "title": "Samsung Galaxy M35 5G",
      "platform": "flipkart",
      "base_price": 24999,
      "checkout_price": 22499,
      "cashback": 500,
      "effective_price": 21999,
      "product_url": "https://www.flipkart.com/...",
      "offers": [...],
      "steps": ["1. Open product page...", "2. Enter coupon SAVE500..."],
      "warnings": ["Always verify at checkout"]
    }
  ],
  "scraped_at": "2026-06-05 00:00 UTC",
  "error": null
}
```

### `POST /api/session/cards`

Replace all saved cards for a session.

```json
{
  "session_id": "uuid",
  "cards": [
    { "bank": "HDFC", "card_name": "Regalia", "card_type": "credit" }
  ]
}
```

### `GET /api/session/cards/{session_id}`

Retrieve saved cards for a session.

### `DELETE /api/cache`

Clear all cached product and offer data.

### `GET /api/cache/stats`

Returns current cache sizes and max capacities.

### `GET /api/health`

Liveness check. Returns `{"status": "ok"}`.

---

## 10. Frontend — Streamlit Chat UI

### Live Status Updates

Uses LangGraph's `astream_events(version="v2")` to stream node lifecycle events.
For each `on_chain_start` / `on_chain_end` event, the UI updates a pre-allocated
`st.empty()` placeholder row in real time inside an `st.status()` box.

| Stage | Spinner | Done |
|---|---|---|
| intent_parser | ⏳ 🧠 Understanding your query… | ✅ Query understood |
| product_search | ⏳ 🔍 Searching Flipkart & Amazon… | ✅ Products found |
| offer_fetcher | ⏳ 🏷️ Fetching offers & bank deals… | ✅ Offers collected |
| tc_parser | ⏳ 📄 Parsing terms & conditions… | ✅ T&C parsed |
| price_calculator | ⏳ 🧮 Calculating best price combinations… | ✅ Prices calculated |
| response_formatter | ⏳ ✍️ Generating your personalised answer… | ✅ Answer ready |

The `st.status()` box collapses to "✅ Done!" when the pipeline completes, and turns
red with `state="error"` if any node fails.

### Sidebar Controls

- **Speed Mode radio** — ⚡ Fast (default) or 🔍 Detailed T&C parsing. Passed as
  `tc_parse_mode` in `AgentState`, overrides the global `.env` setting per request.
- **"Assume I have ALL cards" checkbox** — sets `session.use_all_cards=True`.
- **Add / remove saved cards** — bank name, card variant, credit/debit type. Stored in
  `st.session_state.user_session` (in-memory, resets on browser refresh).

### Result Cards

Each product is rendered as a two-column card:
- Left: product thumbnail
- Right: product name, platform badge, three metric columns (base price, checkout price
  with savings delta, effective price with cashback delta), rating, offer chips, and a
  direct buy link button (`st.link_button` → platform URL)
- Expandable "Step-by-step offer guide" below each card listing every action the user
  must take to achieve the quoted price, plus any warnings (minimum order, capped
  discounts, verification reminder)

---

## 11. Configuration Reference

All settings are in `config/settings.py` (Pydantic-Settings, loaded from `.env`).
Unknown `.env` keys are silently ignored (`extra="ignore"`).

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` or `openai` |
| `OLLAMA_MODEL` | `llama3.1:8b` | Ollama model tag |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OPENAI_API_KEY` | _(empty)_ | Required when provider=openai |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |
| `TC_PARSE_MODE` | `fast` | `fast` or `slow` |
| `CACHE_TTL_PRODUCTS` | `1800` | Product cache TTL in seconds |
| `CACHE_TTL_OFFERS` | `900` | Offer cache TTL in seconds |
| `CACHE_MAX_SIZE` | `500` | Max entries per cache |
| `SCRAPER_MAX_CONCURRENT` | `5` | Max concurrent offer fetches |
| `SCRAPER_MIN_DELAY_MS` | `1000` | Min inter-request delay |
| `SCRAPER_MAX_DELAY_MS` | `2500` | Max inter-request delay |
| `SCRAPER_TIMEOUT_MS` | `30000` | Per-request timeout |
| `SCRAPER_MAX_PER_PLATFORM` | `20` | Max products fetched per platform |
| `SCRAPER_MAX_OFFERS_PER_PLATFORM_PER_PRODUCT` | `5` | Max offers per product |
| `TOP_N_RESULTS` | `10` | Max results returned to user |
| `TOP_N_COMBOS` | `5` | Max offer combos per product |
| `APP_HOST` | `0.0.0.0` | Uvicorn bind host |
| `APP_PORT` | `8000` | Uvicorn bind port |

---

## 12. Running the Application

### Prerequisites

- Python 3.12
- `uv` package manager
- Ollama running locally (`ollama serve`) with `llama3.1:8b` pulled, **OR** an OpenAI API key

### Setup

```bash
# Clone and enter the backend directory
cd backend

# Install dependencies
uv sync

# Copy and edit config
cp .env.example .env
# Edit .env: set LLM_PROVIDER, OPENAI_API_KEY if needed

# Run backend API (port 8000)
./run_backend.sh
# or: uv run uvicorn main:app --reload --port 8000

# Run Streamlit frontend (port 8501)
./run_frontend.sh
# or: uv run streamlit run frontend/streamlit_app.py

# Run both together
./run_all.sh
```

### API Docs

`http://localhost:8000/docs` — Swagger UI with all endpoints and schemas.

---

## 13. Error Handling

### Node-level

Every node in `graph.py` is wrapped in `_safe_async` / `_safe_sync` decorators that
catch all exceptions, print a traceback, and set `state["error"]` instead of crashing
the pipeline. Conditional routing then sends errored states to `error_handler_node`,
which sets a user-friendly `response_text`.

### Response Formatter Fallback

If the LLM framing call in `response_formatter` fails (network error, timeout, malformed
output), a deterministic plain-text response is generated from `structured_results`
without any LLM involvement.

### tc_parser Fallback

In slow mode, if the LLM returns malformed JSON or zero-discount values where the scraper
found a non-zero `flat_discount`, the fast-mode values are used as a per-offer fallback.

### Streamlit

The `st.status()` box transitions to `state="error"` on any unhandled exception in the
async streamer, showing the exception message without crashing the UI.

---

## 14. Known Limitations and Future Improvements

| Area | Current limitation | Planned improvement |
|---|---|---|
| **Session persistence** | In-memory dict, resets on restart | Persist sessions to SQLite or Redis |
| **Offer data freshness** | TTL-based, no push invalidation | Nightly scraper warm-up job |
| **Scraper robustness** | HTML structure changes break parsers | Switch to MCP-based browser agent |
| **T&C accuracy (fast mode)** | Min order value / caps not extracted | Per-product smart mode (short T&C → fast, long → slow) |
| **Platform coverage** | Amazon India + Flipkart only | Extend to Meesho, JioMart, Croma |
| **Card offer database** | Scraped live per query | Maintain a dedicated bank-offer rules DB with nightly sync |
| **Authentication** | No user accounts | Google OAuth → persist cards + history across devices |
| **Concurrency** | Streamlit re-runs on each interaction | Migrate to FastAPI + React frontend for better state control |
