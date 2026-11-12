"""
backend/app/worker.py - Background Worker process for Gomde.
Pulls jobs from the jobs table and runs crawl + analysis + export pipeline.
"""

import asyncio
import time
from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger, setup_logging
from backend.app.db.session import init_db

settings = get_settings()
setup_logging(settings.LOG_LEVEL)
logger = get_logger("worker")


async def run_worker_loop():
    logger.info("Initializing worker process...")
    await init_db()
    logger.info("Worker database initialized. Waiting for jobs...")

    # Worker polling loop
    try:
        while True:
            # Jobs queue polling logic will be executed here in Phase 2+
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        logger.info("Worker loop cancelled, shutting down...")


def main():
    try:
        asyncio.run(run_worker_loop())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")


if __name__ == "__main__":
    main()

