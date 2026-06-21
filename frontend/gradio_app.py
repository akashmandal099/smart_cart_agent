from __future__ import annotations
import uuid
import requests
import gradio as gr

API_BASE = "http://localhost:8000/api"
SESSION_ID = str(uuid.uuid4())
SAVED_CARDS: list[dict] = []


def save_cards(bank: str, card_name: str, card_type: str):
    if bank:
        SAVED_CARDS.append({
            "bank": bank,
            "card_name": card_name.strip(),
            "card_type": card_type,
        })
        r = requests.post(f"{API_BASE}/session/cards", json={
            "session_id": SESSION_ID,
            "cards": SAVED_CARDS,
        }, timeout=20)
        if r.ok:
            return "\n".join([f"- {c['bank']} {c['card_name'] or '(all variants)'} ({c['card_type']})" for c in SAVED_CARDS])
        return f"Failed to save cards: {r.text}"
    return "No card added"


def chat_fn(message: str, history: list):
    payload_history = []
    for pair in history:
        if len(pair) >= 2:
            if pair[0]:
                payload_history.append({"role": "user", "content": pair[0]})
            if pair[1]:
                payload_history.append({"role": "assistant", "content": pair[1]})

    r = requests.post(f"{API_BASE}/chat", json={
        "session_id": SESSION_ID,
        "message": message,
        "chat_history": payload_history,
    }, timeout=180)
    if not r.ok:
        return f"Error: {r.status_code} - {r.text}"

    data = r.json()
    return data.get("response_text", "No response")


with gr.Blocks(title="SmartCart AI") as demo:
    gr.Markdown("# 🛒 SmartCart AI")
    gr.Markdown("Compare Amazon and Flipkart prices after bank offers, coupons, and cashback.")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("## Saved Cards")
            bank = gr.Dropdown(["HDFC", "SBI", "Axis", "ICICI", "Kotak", "Yes Bank", "RBL", "IndusInd", "AmEx"], label="Bank")
            card_name = gr.Textbox(label="Card name", placeholder="Regalia / Millennia / SimplyCLICK")
            card_type = gr.Dropdown(["credit", "debit"], value="credit", label="Card type")
            add_btn = gr.Button("Add card")
            cards_box = gr.Markdown("No cards saved. Backend will assume all cards are allowed.")
            add_btn.click(save_cards, inputs=[bank, card_name, card_type], outputs=[cards_box])

        with gr.Column(scale=3):
            gr.ChatInterface(
                fn=chat_fn,
                type="tuples",
                title="Deal Finder",
                description="Ask things like: best mobile under 25000, iPhone 15 with HDFC card",
            )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)