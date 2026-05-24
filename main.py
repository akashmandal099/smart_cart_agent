"""
SmartCart AI — FastAPI application entrypoint.

Run:
    python -m  main
    or
    uvicorn  main:app --reload --port 8000
"""
# import uvicorn
# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware

# from api.routes import router
# from config.settings import get_settings

# _s = get_settings()

# app = FastAPI(
#     title="SmartCart AI",
#     description="AI-powered product price comparison with offer intelligence for Amazon & Flipkart India.",
#     version="1.0.0",
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=_s.cors_origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# app.include_router(router)


# if __name__ == "__main__":
#     uvicorn.run(
#         " main:app",
#         host=_s.app_host,
#         port=_s.app_port,
#         reload=True,
#     )


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