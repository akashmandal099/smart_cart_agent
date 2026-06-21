"""
SmartCart AI — FastAPI application entrypoint.

Run:
    python -m  main
    or
    uvicorn  main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import get_settings

settings = get_settings()
app = FastAPI(title="SmartCart AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health check — stops the 404 on GET / ─────────────────────────────────
@app.get("/")
async def root():
    return {
        "status": "ok",
        "app": "SmartCart AI",
        "docs": "/docs",
        "provider": settings.llm_provider,
        "model": settings.ollama_model if settings.llm_provider == "ollama" else settings.openai_model,
    }

# ── Include your API router ────────────────────────────────────────────────
from api.routes import router
app.include_router(router)

# # quick test for debugging for flipkart scraper
# if __name__ == "__main__":
#     import asyncio
#     # from scrapers.amazon import AmazonScraper
#     from scrapers.flipkart import FlipkartScraper

#     async def test():
#         # scraper = AmazonScraper()
#         scraper = FlipkartScraper()
#         products = await scraper.search_products(
#             query="mobile phones",
#             price_min=16000,
#             price_max=25000,
#             max_results=1,
#         )
#         for p in products:
#             print(p)
#             offers = await scraper.scrape_offers(p)
#             for o in offers:
#                 print(" Offer ==> ", o)

#     asyncio.run(test())