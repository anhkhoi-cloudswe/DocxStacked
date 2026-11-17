
# Parity and clean verification script
import asyncio
from backend.app.db.session import async_session_factory
from backend.app.db.models import Exam, Question, Subject
from sqlalchemy import select, delete, text
import os
from pathlib import Path

async def main():
    async with async_session_factory() as db:
        # Check parity tests 179, 180
        e179 = await db.get(Exam, 179)
        e180 = await db.get(Exam, 180)
        print('Exam 179 found:', e179 is not None)
        print('Exam 180 found:', e180 is not None)

asyncio.run(main())
