import re
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.auth import router as auth_router
from backend.app.api.exports import router as exports_router
from backend.app.api.health import router as health_router
from backend.app.api.ingest import router as ingest_router
from backend.app.api.jobs import router as jobs_router
from backend.app.api.settings import router as settings_router
from backend.app.api.subjects import router as subjects_router
from backend.app.api.user import router as user_router
from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger, setup_logging
from backend.app.db.models import Job, JobStatus
from backend.app.db.session import async_session_factory, init_db
from backend.app.modules.crawler.browser import get_browser_manager
from sqlalchemy import select

settings = get_settings()
setup_logging(settings.LOG_LEVEL)
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup:
    logger.info("Starting DocxStacked Backend API...")
    await init_db()
    logger.info("Database initialized.")

    # Mark any previously stuck RUNNING/PENDING jobs as FAILED with resume prompt
    try:
        async with async_session_factory() as db:
            stmt = select(Job).where(Job.status.in_([JobStatus.RUNNING, JobStatus.PENDING]))
            res = await db.execute(stmt)
            stuck_jobs = res.scalars().all()
            for j in stuck_jobs:
                j.status = JobStatus.FAILED
                j.error_message = (
                    "Tiến trình bị gián đoạn do máy chủ khởi động lại hoặc mất mạng. "
                    "Bấm 'Chạy tiếp' để tiếp tục từ điểm dừng."
                )
            if stuck_jobs:
                await db.commit()
                logger.info(f"Marked {len(stuck_jobs)} interrupted jobs as FAILED (ready for resume).")
    except Exception as cleanup_err:
        logger.warning(f"Could not check interrupted jobs on startup: {cleanup_err}")

    yield
    # Shutdown:
    logger.info("Shutting down DocxStacked Backend API...")
    try:
        from backend.app.modules.crawler.browser import _default_browser_manager
        if _default_browser_manager is not None:
            _default_browser_manager.close()
    except Exception as e:
        logger.debug(f"Error closing browser manager: {e}")
    logger.info("DocxStacked Backend API shutdown completed.")


app = FastAPI(
    title="DocxStacked — FUOverflow Exam Compiler API",
    version="0.2.0",
    description="Backend API for compiling FUOverflow exams into structured Word documents with community voted answers.",
    lifespan=lifespan,
)

# CORS Middleware - only allow frontend dev origins and configured chrome extension
origins = list(set([
    settings.FRONTEND_URL.rstrip("/"),
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]))

# If EXTENSION_ID is set (e.g. 'abcdefghijklmnop...'), strictly allow that extension ID.
# Otherwise allow any local chrome-extension:// origin for local unpack development.
ext_id = (settings.EXTENSION_ID or "").strip()
if ext_id:
    allow_ext_regex = rf"^(chrome-extension://{re.escape(ext_id)}|http://(localhost|127\.0\.0\.1)(:\d+)?)"
else:
    allow_ext_regex = r"^(chrome-extension://[a-z]{32}|http://(localhost|127\.0\.0\.1)(:\d+)?)"

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=allow_ext_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(subjects_router)
app.include_router(jobs_router)
app.include_router(exports_router)
app.include_router(settings_router)
app.include_router(user_router)
app.include_router(ingest_router)


@app.get("/")
async def root():
    return {
        "message": "Welcome to DocxStacked API",
        "docs": "/docs",
        "health": "/api/health",
    }

