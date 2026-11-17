import asyncio
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.abspath('.'))

from backend.app.db.session import async_session_factory
from backend.app.db.models import Exam, Question, Subject, Answer
from sqlalchemy import select, delete, text

async def cleanup_and_fix():
    async with async_session_factory() as db:
        # 1. Clean exam 179 and 180
        for eid in [179, 180]:
            exam = await db.get(Exam, eid)
            if exam:
                print(f'Deleting Exam {eid}: {exam.title}')
                # Delete answers, questions, exam
                q_ids_res = await db.execute(select(Question.id).where(Question.exam_id == eid))
                q_ids = q_ids_res.scalars().all()
                if q_ids:
                    await db.execute(delete(Answer).where(Answer.question_id.in_(q_ids)))
                    await db.execute(delete(Question).where(Question.id.in_(q_ids)))
                await db.delete(exam)
                await db.commit()
                print(f'Exam {eid} deleted successfully.')

        # Remove any files associated with PARITY_TEST or 179/180
        for root, dirs, files in os.walk('data'):
            if 'PARITY' in root or '179' in root or '180' in root:
                print('Found parity dir:', root)

        # 2. Fix Exam 136 cropped_image_path
        # Map: data/cropped/TEST/exam_136/q001.png -> data/cropped/MLN122/exam_136/q001.png
        # Check if files exist
        q_res = await db.execute(select(Question).where(Question.exam_id == 136).order_by(Question.index))
        qs = q_res.scalars().all()
        print(f'Exam 136 total questions: {len(qs)}')
        updated = 0
        for q in qs:
            old_crop = q.cropped_image_path or ''
            if 'TEST' in old_crop:
                # Replace TEST with MLN122
                new_crop = old_crop.replace('\\TEST\\', '\\MLN122\\').replace('/TEST/', '/MLN122/')
                q.cropped_image_path = new_crop
                updated += 1
        if updated > 0:
            await db.commit()
            print(f'Updated {updated} question paths for Exam 136.')

        # 3. Query count of exam/subject with TEST or PARITY remaining
        exams_all = (await db.execute(select(Exam))).scalars().all()
        subjects_all = (await db.execute(select(Subject))).scalars().all()
        
        test_parity_exams = [e for e in exams_all if 'TEST' in (e.title or '') or 'PARITY' in (e.title or '')]
        test_parity_subjects = [s for s in subjects_all if 'TEST' in (s.name or '') or 'TEST' in (s.code or '') or 'PARITY' in (s.name or '') or 'PARITY' in (s.code or '')]

        print(f'Remaining TEST/PARITY exams: {len(test_parity_exams)}')
        for e in test_parity_exams:
            print(f'  Exam {e.id}: {e.title}')
        print(f'Remaining TEST/PARITY subjects: {len(test_parity_subjects)}')
        for s in test_parity_subjects:
            print(f'  Subject {s.code}: {s.name}')

        # 4. Verify all 60 questions of Exam 136 have existing raw and crop images
        q_res2 = await db.execute(select(Question).where(Question.exam_id == 136).order_by(Question.index))
        qs2 = q_res2.scalars().all()
        raw_missing = []
        crop_missing = []
        for q in qs2:
            raw_p = Path(q.local_image_path) if q.local_image_path else None
            crop_p = Path(q.cropped_image_path) if q.cropped_image_path else None
            if not raw_p or not raw_p.exists():
                raw_missing.append((q.index, q.local_image_path))
            if not crop_p or not crop_p.exists():
                crop_missing.append((q.index, q.cropped_image_path))

        print(f'Exam 136 raw images missing: {len(raw_missing)}')
        print(f'Exam 136 crop images missing: {len(crop_missing)}')
        if len(raw_missing) == 0 and len(crop_missing) == 0:
            print('VERIFICATION SUCCESS: All 60 raw and cropped images exist on disk!')

asyncio.run(cleanup_and_fix())
