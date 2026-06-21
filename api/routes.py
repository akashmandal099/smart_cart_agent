"""
SmartCart AI — REST API Routes

POST   /api/chat              → run full agent graph, return response + structured cards
POST   /api/cards             → update session saved cards
GET    /api/cards/{session_id}→ get saved cards for a session
DELETE /api/cache             → manual on-demand cache invalidation (force refresh)
GET    /api/cache/stats       → cache stats
GET    /api/health            → health check
"""
import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from  agents.card_extractor import extract_and_update_cards
from  agents.graph import smartcart_graph
from  cache import ttl_cache as cache
from  models.agent_state import AgentState
from  models.offer import CardType
from  models.session import SessionCard, UserSession

router = APIRouter(prefix="/api")

# ── In-memory session store (session_id → UserSession) ───────────────────────
# For production: replace with Redis or database-backed sessions
_sessions: dict[str, UserSession] = {}


def _get_or_create_session(session_id: str | None) -> UserSession:
    sid = session_id or str(uuid.uuid4())
    if sid not in _sessions:
        _sessions[sid] = UserSession(session_id=sid)
    return _sessions[sid]


# ── Request / Response schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    chat_history: list[dict] = []
    force_refresh: bool = False     # True = invalidate cache and scrape fresh


class ChatResponse(BaseModel):
    session_id: str
    response: str
    structured_results: list[dict] = []
    scraped_at: str = ""


class CardRequest(BaseModel):
    session_id: str | None = None
    cards: list[dict]   # [{"bank":"HDFC","card_name":"Regalia","card_type":"credit"}]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session = _get_or_create_session(req.session_id)

    if req.force_refresh:
        cache.invalidate_all()

    # Pre-graph: detect card mentions and update session
    session = await extract_and_update_cards(req.message, session)
    _sessions[session.session_id] = session

    initial_state: AgentState = {
        "user_message":      req.message,
        "session":           session,
        "chat_history":      req.chat_history,
        "intent":            None,
        "raw_products":      [],
        "raw_offers":        {},
        "parsed_offers":     {},
        "ranked_combos":     [],
        "response_text":     "",
        "structured_results": [],
        "error":             None,
    }

    final_state = await smartcart_graph.ainvoke(initial_state)

    return ChatResponse(
        session_id=session.session_id,
        response=final_state.get("response_text", ""),
        structured_results=final_state.get("structured_results", []),
        scraped_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    )


@router.post("/cards")
async def update_cards(req: CardRequest):
    session = _get_or_create_session(req.session_id)
    session.saved_cards = [
        SessionCard(
            bank=c["bank"],
            card_name=c.get("card_name", ""),
            card_type=CardType(c.get("card_type", "credit")),
        )
        for c in req.cards
        if c.get("bank")
    ]
    session.use_all_cards = len(session.saved_cards) == 0
    _sessions[session.session_id] = session
    return {
        "session_id":  session.session_id,
        "cards_saved": len(session.saved_cards),
        "use_all_cards": session.use_all_cards,
    }


@router.get("/cards/{session_id}")
async def get_cards(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        return {"session_id": session_id, "cards": [], "use_all_cards": True}
    return {
        "session_id":    session_id,
        "cards":         [c.model_dump() for c in session.saved_cards],
        "use_all_cards": session.use_all_cards,
    }


@router.delete("/cache")
async def clear_cache():
    cache.invalidate_all()
    return {"status": "cache cleared", "cleared_at": datetime.utcnow().isoformat()}


@router.get("/cache/stats")
async def cache_stats():
    return cache.cache_stats()


@router.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
