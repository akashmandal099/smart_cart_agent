"""
SmartCart AI — Streamlit Chat Frontend

Includes:
  • Live node-by-node status via LangGraph astream_events
  • Fast / Slow T&C parsing toggle in the sidebar
  • Saved card management
  • Product result cards with step-by-step offer guides
"""
from __future__ import annotations

import asyncio
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

import streamlit as st

from agents.graph import build_graph
from models.session import UserSession, SavedCard
from models.offer import CardType

# ─────────────────────────────────────────────────────────────────────────────
# Per-node status labels
# ─────────────────────────────────────────────────────────────────────────────
_NODE_STATUS: dict[str, tuple[str, str]] = {
    "intent_parser":      ("🧠 Understanding your query…",             "Query understood"),
    "product_search":     ("🔍 Searching Flipkart & Amazon…",          "Products found"),
    "offer_fetcher":      ("🏷️  Fetching offers & bank deals…",        "Offers collected"),
    "tc_parser":          ("📄 Parsing terms & conditions…",           "T&C parsed"),
    "price_calculator":   ("🧮 Calculating best price combinations…",  "Prices calculated"),
    "response_formatter": ("✍️  Generating your personalised answer…", "Answer ready"),
    "error_handler":      ("❌ Something went wrong",                   "Error"),
}
_PIPELINE_ORDER = list(_NODE_STATUS.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Event-loop helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_loop() -> asyncio.AbstractEventLoop:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def _run(coro):
    return _get_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# Session bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def _init_session():
    if "chat_history"  not in st.session_state:
        st.session_state.chat_history  = []
    if "user_session"  not in st.session_state:
        st.session_state.user_session  = UserSession()
    if "graph"         not in st.session_state:
        st.session_state.graph         = build_graph()
    if "tc_parse_mode" not in st.session_state:
        st.session_state.tc_parse_mode = "fast"


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

def _render_sidebar():
    session: UserSession = st.session_state.user_session

    st.sidebar.title("🛒 SmartCart AI")

    # ── T&C Parse Mode ────────────────────────────────────────────────────────
    st.sidebar.markdown("### ⚡ Speed Mode")
    mode = st.sidebar.radio(
        label="T&C parsing",
        options=["fast", "slow"],
        index=0 if st.session_state.tc_parse_mode == "fast" else 1,
        format_func=lambda x: (
            "⚡ Fast (default) — uses offer card amounts directly"
            if x == "fast"
            else "🔍 Detailed — LLM extracts min order, caps & card variants from T&C"
        ),
        help=(
            "Fast: instant results using the ₹X off shown on each offer card.\n\n"
            "Detailed: slower (5-30s extra) but extracts minimum order values, "
            "discount caps, and specific card variants from the fine print."
        ),
    )
    st.session_state.tc_parse_mode = mode

    if mode == "slow":
        st.sidebar.info(
            "🔍 Detailed mode active — T&C parsing may take 5–30s extra per query.",
            icon="ℹ️",
        )

    st.sidebar.markdown("---")

    # ── Cards ─────────────────────────────────────────────────────────────────
    st.sidebar.markdown("### 💳 My Cards")
    use_all = st.sidebar.checkbox(
        "Assume I have ALL cards",
        value=session.use_all_cards,
        help="Shows every available offer regardless of which card you hold.",
    )
    session.use_all_cards = use_all

    if not use_all:
        to_remove = []
        for i, card in enumerate(session.saved_cards):
            c1, c2 = st.sidebar.columns([4, 1])
            c1.markdown(f"`{card.bank}` — {card.card_name} ({card.card_type.value})")
            if c2.button("✕", key=f"rm_{i}"):
                to_remove.append(i)
        for idx in reversed(to_remove):
            session.saved_cards.pop(idx)

        st.sidebar.markdown("**Add a card:**")
        with st.sidebar.form("add_card", clear_on_submit=True):
            bank  = st.text_input("Bank", placeholder="HDFC, SBI, Axis…")
            name  = st.text_input("Card name / variant", placeholder="Regalia, SimplySave…")
            ctype = st.selectbox("Type", ["credit", "debit", "all"])
            if st.form_submit_button("Add Card") and bank.strip():
                session.saved_cards.append(SavedCard(
                    bank=bank.strip().upper(),
                    card_name=name.strip() or bank.strip().upper(),
                    card_type=CardType(ctype),
                ))
                st.sidebar.success(f"✅ Added {bank.upper()} {ctype}!")

    st.sidebar.markdown("---")
    st.sidebar.caption(
        "SmartCart searches Flipkart & Amazon, fetches real-time offers, "
        "and finds the lowest checkout price after all applicable combinations."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Result cards
# ─────────────────────────────────────────────────────────────────────────────

def _render_result_cards(results: list[dict]):
    if not results:
        return
    st.markdown("---")
    st.markdown("### 🛒 Results at a Glance")
    for item in results:
        badge    = "✅ **Best Deal**" if item["rank"] == 1 else f"#{item['rank']}"
        pf_emoji = "🔵" if item["platform"] == "flipkart" else "🟠"
        with st.container():
            col_img, col_info = st.columns([1, 3])
            with col_img:
                if item.get("image_url"):
                    st.image(item["image_url"], width=120)
            with col_info:
                st.markdown(f"{badge} {pf_emoji} **{item['title']}**")
                pcols = st.columns(3)
                pcols[0].metric("Base price",     f"₹{item['base_price']:,.0f}")
                savings = item["base_price"] - item["checkout_price"]
                pcols[1].metric(
                    "Checkout price", f"₹{item['checkout_price']:,.0f}",
                    delta=f"-₹{savings:,.0f}" if savings > 0 else None,
                    delta_color="inverse",
                )
                if item["cashback"] > 0:
                    pcols[2].metric(
                        "Effective price", f"₹{item['effective_price']:,.0f}",
                        delta=f"₹{item['cashback']:,.0f} cashback",
                        delta_color="inverse",
                    )
                if item.get("rating"):
                    rev = f"  ({item['review_count']:,} reviews)" if item.get("review_count") else ""
                    st.caption(f"⭐ {item['rating']}{rev}")
                if item.get("offers"):
                    chips = " · ".join(
                        f"`{o['bank'] or ''} {o['card_type']}: ₹{o['discount']:,.0f} off`"
                        for o in item["offers"] if o.get("discount", 0) > 0
                    )
                    if chips:
                        st.markdown(f"**Offers:** {chips}")
                if item.get("product_url"):
                    st.link_button(
                        f"🛍️ Buy on {item['platform'].capitalize()}",
                        item["product_url"],
                    )
            if item.get("steps"):
                with st.expander("📋 Step-by-step offer guide"):
                    for s in item["steps"]:
                        st.markdown(s)
                    for w in item.get("warnings", []):
                        st.warning(w)
            st.divider()


# ─────────────────────────────────────────────────────────────────────────────
# Live status streaming
# ─────────────────────────────────────────────────────────────────────────────

async def _stream_graph(
    user_msg: str,
    session: UserSession,
    history: list[dict],
    tc_mode: str,
    placeholders: list,
) -> dict:
    graph = st.session_state.graph

    initial_state = {
        "user_message":       user_msg,
        "session":            session,
        "chat_history":       history,
        "tc_parse_mode":      tc_mode,
        "intent":             None,
        "raw_products":       [],
        "raw_offers":         {},
        "parsed_offers":      {},
        "ranked_combos":      [],
        "response_text":      "",
        "structured_results": [],
        "error":              None,
    }

    completed: list[str] = []
    current:   str | None = None
    final_state = dict(initial_state)

    async for event in graph.astream_events(initial_state, version="v2"):
        kind      = event.get("event", "")
        node_name = event.get("name", "")

        if kind == "on_chain_start" and node_name in _NODE_STATUS:
            current = node_name
            _redraw(placeholders, completed, current)

        elif kind == "on_chain_end" and node_name in _NODE_STATUS:
            if node_name not in completed:
                completed.append(node_name)
            current = None
            output = event.get("data", {}).get("output", {})
            if isinstance(output, dict):
                final_state.update(output)
            _redraw(placeholders, completed, current)

    return final_state


def _redraw(placeholders: list, done: list[str], current: str | None):
    for i, node in enumerate(_PIPELINE_ORDER):
        if i >= len(placeholders):
            break
        spinner_label, done_label = _NODE_STATUS[node]
        if node in done:
            placeholders[i].markdown(f"✅ {done_label}")
        elif node == current:
            placeholders[i].markdown(f"⏳ {spinner_label}")
        else:
            placeholders[i].empty()


def _run_with_status(user_msg: str, session: UserSession, history: list[dict], tc_mode: str) -> dict:
    with st.status("🛒 SmartCart is working…", expanded=True) as status_box:
        placeholders = [st.empty() for _ in _PIPELINE_ORDER]
        try:
            result = _run(_stream_graph(user_msg, session, history, tc_mode, placeholders))
            status_box.update(label="✅ Done!", state="complete", expanded=False)
        except Exception as exc:
            status_box.update(label=f"❌ Error: {exc}", state="error", expanded=True)
            result = {
                "response_text":      f"⚠️ Something went wrong: {exc}",
                "structured_results": [],
                "error":              str(exc),
            }
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="SmartCart AI", page_icon="🛒", layout="wide")
    _init_session()
    _render_sidebar()

    st.title("🛒 SmartCart AI")
    st.caption(
        "Compare prices across Flipkart & Amazon · "
        "Applies credit card / coupon offers automatically"
    )

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("structured_results"):
                _render_result_cards(msg["structured_results"])

    user_input = st.chat_input(
        "e.g. 'best 5 mobiles under ₹25,000' or 'Samsung Galaxy S25 FE price'"
    )
    if not user_input:
        return

    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.chat_history.append({"role": "user", "content": user_input})

    with st.chat_message("assistant"):
        result = _run_with_status(
            user_input,
            st.session_state.user_session,
            st.session_state.chat_history[:-1],
            st.session_state.tc_parse_mode,
        )

        response_text      = result.get("response_text", "")
        structured_results = result.get("structured_results", [])

        if response_text:
            st.markdown(response_text)
        else:
            st.warning("No results found — try rephrasing your query.")

        if structured_results:
            _render_result_cards(structured_results)

    st.session_state.chat_history.append({
        "role":               "assistant",
        "content":            response_text,
        "structured_results": structured_results,
    })


if __name__ == "__main__":
    main()
