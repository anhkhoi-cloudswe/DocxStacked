from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.db.session import get_db

router = APIRouter(prefix="/api", tags=["health"])
settings = get_settings()


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check endpoint confirming API and DB connectivity."""
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {e}"

    return {
        "status": "ok",
        "app": "Gomde API",
        "environment": settings.ENVIRONMENT,
        "database": db_status,
        "browser_profile": settings.BROWSER_PROFILE_DIR.exists(),
    }

