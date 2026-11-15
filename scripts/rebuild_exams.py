"""
Rebuild Word files for all 5 target exams, bypassing all caches.
Run from project root:
    .\.venv\Scripts\python.exe scripts/rebuild_exams.py [exam_id ...]

If no exam_ids given, rebuilds all 5: 113, 109, 119, 123, 41
"""
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.db.session import SyncSessionLocal
from backend.app.db.models import Question, Exam
from backend.app.modules.export.image_cropper import crop_exam_images, CROP_ALGORITHM_VERSION
from backend.app.modules.export.docx_builder import build_exam_docx
from backend.app.core.config import get_settings

SETTINGS = get_settings()

TARGET_EXAMS = {
    113: "ITE302C",
    109: "ITE302C",
    119: "ITE302C",
    123: "ITE302C",
    41:  "PRM392",
    42:  "PRM392",
    39:  "PRM393",
}


def rebuild_exam(db, exam_id: int, subject_code: str):
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        print(f"[ERROR] exam_id={exam_id} not found in DB")
        return None

    questions = (
        db.query(Question)
        .filter(Question.exam_id == exam_id)
        .order_by(Question.index)
        .all()
    )
    print(f"\n--- exam_id={exam_id}: {exam.title!r} ({len(questions)} questions) ---")

    cropped_dir = SETTINGS.STORAGE_DIR / "cropped" / subject_code / f"exam_{exam_id}"
    version_file = cropped_dir / ".crop_version"

    # Force re-crop by deleting the version file
    if version_file.exists():
        version_file.unlink()
        print(f"  [CROP] Deleted version file → will re-crop (version={CROP_ALGORITHM_VERSION})")
    else:
        print(f"  [CROP] No version file found (first crop, version={CROP_ALGORITHM_VERSION})")

    summary = crop_exam_images(exam_id, exam.title, questions, cropped_dir)
    print(f"  [CROP] Done: {summary.clean_questions} clean, {summary.flagged_questions} flagged")

    # Count warnings
    missing_stem = sum(1 for r in summary.results if "missing_stem" in r.warnings)
    source_clipped = sum(1 for r in summary.results if "source_clipped" in r.warnings)
    print(f"  [CROP] missing_stem={missing_stem}, source_clipped={source_clipped}")

    # Update DB paths
    for q, res in zip(questions, summary.results):
        q.crop_warnings = ",".join(res.warnings) if res.warnings else ""
        if res.output_path and res.output_path.exists():
            q.cropped_image_path = str(res.output_path)
    db.commit()
    print(f"  [DB]   Updated {len(questions)} question crop paths")

    # Build Word file
    docx_path = build_exam_docx(
        subject_code=subject_code,
        exam=exam,
        questions=questions,
        cropped_dir=cropped_dir,
    )
    if docx_path and Path(docx_path).exists():
        size_kb = Path(docx_path).stat().st_size // 1024
        print(f"  [DOCX] Built: {docx_path} ({size_kb} KB)")
    else:
        print(f"  [DOCX] ERROR: build_exam_docx returned {docx_path!r}")

    return docx_path


def main():
    exam_ids = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else list(TARGET_EXAMS.keys())
    print(f"Rebuilding exam_ids: {exam_ids}")
    print(f"CROP_ALGORITHM_VERSION: {CROP_ALGORITHM_VERSION}")
    print(f"STORAGE_DIR: {SETTINGS.STORAGE_DIR}")

    db = SyncSessionLocal()
    try:
        for eid in exam_ids:
            if eid not in TARGET_EXAMS:
                print(f"[WARN] exam_id={eid} not in TARGET_EXAMS; skipping")
                continue
            rebuild_exam(db, eid, TARGET_EXAMS[eid])
    finally:
        db.close()

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
