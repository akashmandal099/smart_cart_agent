from pydantic import BaseModel
from .offer import CardType


class SessionCard(BaseModel):
    bank: str           # e.g. "HDFC"
    card_name: str      # e.g. "Regalia"
    card_type: CardType = CardType.CREDIT


class UserSession(BaseModel):
    session_id: str
    saved_cards: list[SessionCard] = []
    use_all_cards: bool = True      # True when no cards saved → show all offers

    def update_cards(self, cards: list[SessionCard]) -> None:
        self.saved_cards = cards
        self.use_all_cards = len(cards) == 0
