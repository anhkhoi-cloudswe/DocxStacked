from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

def check_and_migrate_legacy_db(storage_dir: Optional[Path] = None, target_db: Optional[Path] = None) -> bool:
    """Migrate legacy gomde.db to docxstacked.db if new DB does not exist."""
    dir_path = storage_dir or settings.STORAGE_DIR
    old_db = dir_path / "gomde.db"
    new_db = target_db or (dir_path / "docxstacked.db")

    if old_db.exists() and (not new_db.exists() or new_db.stat().st_size == 0):
        try:
            import shutil
            shutil.copy2(old_db, new_db)
            logger.info(f"Auto-migrated legacy database '{old_db.name}' to '{new_db.name}' successfully.")
            return True
        except Exception as e:
            logger.warning(f"Could not auto-migrate legacy database: {e}")
    return False

# Ensure sqlite parent directory exists and check for legacy database migration
if "sqlite" in settings.DATABASE_URL:
    db_path_str = settings.DATABASE_URL.split("///")[-1]
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = settings.BASE_DIR / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    check_and_migrate_legacy_db(db_path.parent, db_path)

# Async Engine for FastAPI
connect_args = {"timeout": 30} if "sqlite" in settings.DATABASE_URL else {}
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    connect_args=connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
async_session_factory = AsyncSessionLocal

# Sync Engine for worker or sync utility tasks
sync_connect_args = {"timeout": 30} if "sqlite" in settings.SYNC_DATABASE_URL else {}
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    echo=False,
    future=True,
    connect_args=sync_connect_args,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize DB schema by creating all tables if not existing."""
    from sqlalchemy import text
    from backend.app.db.models import Subject, Exam, Question, Comment, Answer, Job, Setting, User  # noqa

    logger.info("Initializing database tables...")
    async with async_engine.begin() as conn:
        if "sqlite" in settings.DATABASE_URL:
            try:
                await conn.execute(text("PRAGMA journal_mode=WAL;"))
                await conn.execute(text("PRAGMA busy_timeout=30000;"))
            except Exception:
                pass
        await conn.run_sync(Base.metadata.create_all)
        # Ensure new columns on existing SQLite tables
        try:
            await conn.execute(text("ALTER TABLE jobs ADD COLUMN config_snapshot JSON DEFAULT '{}'"))
        except Exception:
            pass  # Already exists
        try:
            await conn.execute(text("ALTER TABLE subjects ADD COLUMN last_synced_at DATETIME"))
        except Exception:
            pass  # Already exists
        try:
            await conn.execute(text("ALTER TABLE jobs ADD COLUMN username VARCHAR(100)"))
        except Exception:
            pass  # Already exists
        try:
            await conn.execute(text("ALTER TABLE jobs ADD COLUMN user_id INTEGER"))
        except Exception:
            pass  # Already exists
    logger.info("Database tables initialized successfully.")

