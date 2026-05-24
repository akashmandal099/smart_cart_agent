"""
Card Extractor — utility called before the graph runs.

Detects card mentions in the user's message and updates the session.
Handles both conversational ("I have HDFC Regalia") and explicit
("Add Axis Magnus credit card") mentions.
"""
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from config import get_llm
from models.offer import CardType
from models.session import SessionCard, UserSession

_llm = get_llm(temperature=0.0, json_mode=True)

_chain = ChatPromptTemplate.from_messages([
    (
        "system",
        """Extract credit/debit card mentions from text.
Return JSON: {{"cards": [{{"bank": "...", "card_name": "...", "card_type": "credit|debit"}}]}}

Valid bank names: HDFC, SBI, Axis, ICICI, Kotak, Yes Bank, RBL, IndusInd, Citibank, AmEx, IDFC
Card name examples: Regalia, SimplyCLICK, Flipkart, Millennia, Infinia, Magnus, Ace, Amazon Pay

If no cards are mentioned, return {{"cards": []}}.
Return ONLY valid JSON — no explanation."""
    ),
    ("human", "{text}"),
]) | _llm | JsonOutputParser()


async def extract_and_update_cards(text: str, session: UserSession) -> UserSession:
    result = await _chain.ainvoke({"text": text})
    print("Cards from extractor:", result)
    cards_data = result.get("cards", [])
    if not cards_data:
        return session

    new_cards = [
        SessionCard(
            bank=c["bank"],
            card_name=c.get("card_name", ""),
            card_type=CardType(c.get("card_type", "credit")),
        )
        for c in cards_data
        if c.get("bank")
    ]

    existing = {(c.bank.lower(), c.card_name.lower()): c for c in session.saved_cards}
    for c in new_cards:
        existing[(c.bank.lower(), c.card_name.lower())] = c

    session.saved_cards = list(existing.values())
    session.use_all_cards = False
    print("Updated session :", session)
    return session