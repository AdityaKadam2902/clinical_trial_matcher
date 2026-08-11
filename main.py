"""
main.py — FastAPI application entry point
Start: uvicorn main:app --reload --port 8000
"""
import os, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from loguru import logger

from core.config import settings
from core.logger import setup_logger
from core.database import create_tables, close_db
from api.routes import router

os.makedirs("logs", exist_ok=True)
setup_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Clinical Trial Matcher API...")
    await create_tables()
    logger.success("Application ready.")
    yield
    await close_db()

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Clinical Trial Matcher API",
    description="AI-powered clinical trial matching — 6-agent LangGraph pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def timing(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    response.headers["X-Process-Time"] = f"{time.time()-start:.3f}s"
    return response

app.include_router(router)

frontend_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.exists(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir,"assets")), name="assets")
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        idx = os.path.join(frontend_dir, "index.html")
        return FileResponse(idx) if os.path.exists(idx) else JSONResponse({"error":"frontend not built"})
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return {"message":"Clinical Trial Matcher API","docs":"/docs","health":"/api/v1/health"}
