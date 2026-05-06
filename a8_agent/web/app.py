"""A8 Agent FastAPI app — consolidates cadence draft generation."""

from contextlib import asynccontextmanager
import os
from fastapi import FastAPI
from a8_agent.cadence_draft_handler import cadence_lifespan, router as cadence_router


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """App lifespan: initialize cadence handler."""
    async with cadence_lifespan(app) as _:
        yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI app."""
    
    # Get database URL from environment
    db_url = os.getenv(
        "A8_DATABASE_URL",
        "postgresql://localhost/a8_crm"
    )
    
    app = FastAPI(
        title="A8 Agent",
        description="Cadence draft generation and orchestration",
        version="0.1.0",
        lifespan=app_lifespan
    )
    
    # Store config in app state
    app.state.database_url = db_url
    
    # Include cadence router
    app.include_router(cadence_router, prefix="/cadence")
    
    # Health check
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "a8_agent"}
    
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8788,
        log_level="info"
    )
