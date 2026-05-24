from __future__ import annotations
import uuid
import requests
import streamlit as st

API_BASE = "http://localhost:8000/api"

st.set_page_config(page_title="SmartCart AI", page_icon="🛒", layout="wide")


def init_state() -> None:
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Hi! Ask me for a product or category like 'best mobile under 25000' or 'iPhone 15 with HDFC card'.",
            }
        ]
    if "saved_cards" not in st.session_state:
        st.session_state.saved_cards = []
    if "last_results" not in st.session_state:
        st.session_state.last_results = []


def api_post(path: str, payload: dict):
    return requests.post(f"{API_BASE}{path}", json=payload, timeout=180)


def render_sidebar() -> None:
    st.sidebar.header("Settings")
    st.sidebar.caption(f"Session: {st.session_state.session_id[:8]}")

    st.sidebar.subheader("Saved Cards")
    with st.sidebar.form("card_form", clear_on_submit=True):
        bank = st.selectbox("Bank", ["HDFC", "SBI", "Axis", "ICICI", "Kotak", "Yes Bank", "RBL", "IndusInd", "AmEx"])
        card_name = st.text_input("Card name", placeholder="Regalia / Millennia / SimplyCLICK")
        card_type = st.selectbox("Card type", ["credit", "debit"])
        add_btn = st.form_submit_button("Add card")
        if add_btn:
            st.session_state.saved_cards.append({
                "bank": bank,
                "card_name": card_name.strip(),
                "card_type": card_type,
            })
            resp = api_post("/session/cards", {
                "session_id": st.session_state.session_id,
                "cards": st.session_state.saved_cards,
            })
            if resp.ok:
                st.sidebar.success("Card saved")
            else:
                st.sidebar.error(resp.text)


def render_results(results: list[dict]) -> None:
    if not results:
        return
    st.subheader("Top Results")
    for item in results:
        with st.expander(f"#{item.get('rank', '?')} {item.get('title', 'Product')} — ₹{item.get('checkout_price', 0):,.0f}", expanded=item.get("rank") == 1):
            c1, c2, c3 = st.columns(3)
            c1.metric("Base Price", f"₹{item.get('base_price', 0):,.0f}")
            c2.metric("Checkout", f"₹{item.get('checkout_price', 0):,.0f}")
            c3.metric("Effective", f"₹{item.get('effective_price', 0):,.0f}")
            if item.get("product_url"):
                st.link_button("Open Product", item["product_url"])


init_state()
st.title("🛒 SmartCart AI")
st.caption("Compare Amazon and Flipkart prices after offers, coupons, and cashback.")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Ask: best mobile under 25000")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Searching products and offers..."):
            resp = api_post("/chat", {
                "session_id": st.session_state.session_id,
                "message": prompt,
                "chat_history": st.session_state.messages[:-1],
            })
            if resp.ok:
                data = resp.json()
                answer = data.get("response_text", "No response")
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
                st.session_state.last_results = data.get("structured_results", [])
            else:
                err = f"Error: {resp.status_code} - {resp.text}"
                st.error(err)
                st.session_state.messages.append({"role": "assistant", "content": err})

render_sidebar()
render_results(st.session_state.last_results)