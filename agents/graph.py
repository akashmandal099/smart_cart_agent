"""
LangGraph Graph Definition — SmartCart AI

Flow:
  START
    → intent_parser       Node 1: LLM parses user message → QueryIntent
    → product_search      Node 2: Scrape product listings (parallel, cached)
    → offer_fetcher       Node 3: Scrape offer+T&C per product (parallel, cached)
    → tc_parser           Node 4: LLM reads T&C → structured Offer fields
    → price_calculator    Node 5: PriceGraph DFS → OfferCombo ranking (deterministic)
    → response_formatter  Node 6: LLM formats markdown response
  END

Conditional edges:
  - intent_parser  error     → error_handler → END
  - product_search no results → response_formatter (skip offer steps) → END
  - product_search error      → error_handler → END

All nodes wrapped in error-catching decorators for resilience.
"""
import traceback

from langgraph.graph import END, START, StateGraph

from models.agent_state import AgentState
from .intent_parser      import intent_parser_node
from .offer_fetcher      import offer_fetcher_node
from .price_calculator   import price_calculator_node
from .product_search     import product_search_node
from .response_formatter import response_formatter_node


# ── error handler ─────────────────────────────────────────────────────────────

def error_handler_node(state: AgentState) -> AgentState:
    err = state.get("error") or "Unknown error"
    return {
        **state,
        "response_text": (
            f"❌ Something went wrong: {err}\n\n"
            "Please try again or rephrase your query. "
            "If the issue persists, try clicking 🔄 to refresh."
        ),
        "structured_results": [],
    }


# ── routing functions ─────────────────────────────────────────────────────────

def _route_after_intent(state: AgentState) -> str:
    if state.get("error"):
        return "error_handler"
    return "product_search"


def _route_after_search(state: AgentState) -> str:
    if state.get("error"):
        return "error_handler"
    if not state.get("raw_products"):
        return "response_formatter"   # skip offer steps for empty results
    return "offer_fetcher"


# ── node wrappers with error catching ─────────────────────────────────────────

def _safe_async(async_fn):
    """Wrap an async node — catches exceptions and sets state["error"]."""
    async def wrapper(state: AgentState) -> AgentState:
        try:
            return await async_fn(state)
        except Exception as e:
            traceback.print_exc()
            return {**state, "error": str(e)}
    wrapper.__name__ = async_fn.__name__
    return wrapper


def _safe_sync(fn):
    """Wrap a sync node — catches exceptions and sets state["error"]."""
    def wrapper(state: AgentState) -> AgentState:
        try:
            return fn(state)
        except Exception as e:
            traceback.print_exc()
            return {**state, "error": str(e)}
    wrapper.__name__ = fn.__name__
    return wrapper


# ── graph construction ────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("intent_parser",      _safe_async(intent_parser_node))
    g.add_node("product_search",     _safe_async(product_search_node))
    g.add_node("offer_fetcher",      _safe_async(offer_fetcher_node))
    g.add_node("tc_parser",          _safe_async(tc_parser_node_import()))
    g.add_node("price_calculator",   _safe_sync(price_calculator_node))
    g.add_node("response_formatter", _safe_async(response_formatter_node))
    g.add_node("error_handler",      error_handler_node)

    g.add_edge(START, "intent_parser")
    g.add_conditional_edges("intent_parser",  _route_after_intent)
    g.add_conditional_edges("product_search", _route_after_search)
    g.add_edge("offer_fetcher",      "tc_parser")
    g.add_edge("tc_parser",          "price_calculator")
    g.add_edge("price_calculator",   "response_formatter")
    g.add_edge("response_formatter", END)
    g.add_edge("error_handler",      END)

    return g.compile()


def tc_parser_node_import():
    # Lazy import to avoid circular at module load time
    from .tc_parser import tc_parser_node
    return tc_parser_node


# Singleton compiled graph — imported by API routes
smartcart_graph = build_graph()
