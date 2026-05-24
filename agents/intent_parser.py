"""
Agent Node 1 — Intent Parser

Converts free-form user message into a structured QueryIntent using LLM JSON mode.
Also resolves follow-up queries using conversation history (last 3 turns).
"""
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from  config.settings import get_settings
from  models.agent_state import AgentState, QueryIntent, QueryType
from  models.product import Platform
from config import get_llm

_s = get_settings()
# _llm = ChatOpenAI(
#     model=_s.llm_model,
#     temperature=_s.llm_temperature,
#     api_key=_s.openai_api_key,
# )
_llm = get_llm(temperature=0.0, json_mode=True)

_SYSTEM = """You are a shopping intent parser for Indian e-commerce (Amazon India, Flipkart).
Extract a JSON object with exactly these keys:

  query_type  : "category" or "specific_product"
  product     : string — best search query to use (e.g. "mobile phone", "Samsung Galaxy M35 5G")
  brand_hint  : string or null — e.g. "Samsung", "Boat"
  price_min   : number — 0 if not mentioned price_min or price_max, otherwise take 20% less than price_max (e.g. "around 20K" → price_max=20000, price_min=16000)
  price_max   : number — 99999999 if not mentioned price_max or price_min, otherwise take 20% more than price_min (e.g. "between 20K-25K" → price_min=20000, price_max=25000)
  platforms   : list from ["amazon","flipkart"] — both if not specified
  top_n       : number — default 10

Conversion rules:
  "1 lakh" = 100000 | "1k" / "1K" = 1000 | "20K" / "20k" = 20000
  "under ₹25K"       → price_min=0,     price_max=25000
  "between 20K-25K"  → price_min=20000, price_max=25000
  "around 20K"       → price_min=17000, price_max=23000

Follow-up rules (use conversation history):
  "show only Samsung"   → same query, brand_hint="Samsung"
  "only Amazon"         → platforms=["amazon"]
  "refresh"             → same intent as last query
  "top 5 only"          → top_n=5

Return only the JSON object — no explanation."""

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM),
    ("human", "Conversation so far:\n{history}\n\nUser: {message}"),
])
_chain = _PROMPT | _llm | JsonOutputParser()


async def intent_parser_node(state: AgentState) -> AgentState:
    history = "\n".join(
        f"{m['role'].title()}: {m['content']}"
        for m in state["chat_history"][-6:]   # last 3 turns = 6 messages
    )
    raw = await _chain.ainvoke({
        "history": history or "None",
        "message": state["user_message"],
    })
    print("1. Parsed intent:", raw)
    intent = QueryIntent(
        query_type=QueryType(raw.get("query_type", "category")),
        product=raw.get("product", state["user_message"]),
        brand_hint=raw.get("brand_hint"),
        price_min=float(raw.get("price_min", 0)),
        price_max=float(raw.get("price_max", 99_999_999)),
        platforms=[Platform(p) for p in raw.get("platforms", ["amazon", "flipkart"])],
        top_n=int(raw.get("top_n", 10)),
    )
    return {**state, "intent": intent, "error": None}
