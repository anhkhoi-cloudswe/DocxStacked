from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.auth import router as auth_router
from backend.app.api.exports import router as exports_router
from backend.app.api.health import router as health_router
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
    get_browser_manager().close()
    logger.info("Browser manager closed cleanly.")


app = FastAPI(
    title="DocxStacked — FUOverflow Exam Compiler API",
    version="0.2.0",
    description="Backend API for compiling FUOverflow exams into structured Word documents with community voted answers.",
    lifespan=lifespan,
)

# CORS Middleware - only allow frontend dev origins
origins = list(set([
    settings.FRONTEND_URL.rstrip("/"),
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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


@app.get("/")
async def root():
    return {
        "message": "Welcome to DocxStacked API",
        "docs": "/docs",
        "health": "/api/health",
    }

