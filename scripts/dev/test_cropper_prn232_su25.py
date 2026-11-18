import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from backend.app.modules.export.image_cropper import crop_question_single, ImageCropConfig

def test_prn232_su25_run():
    raw_dir = Path("data/raw/PRN232/exam_194_su25")
    files = sorted(raw_dir.glob("*.webp"))
    cfg = ImageCropConfig()
    
    warnings_by_type = {}
    flagged_questions = []
    
    print(f"Running cropper on {len(files)} files of PRN232 SU25...")
    for idx, f in enumerate(files, start=1):
        res = crop_question_single(f, config=cfg)
        if res.warnings:
            flagged_questions.append((idx, res.warnings))
            for w in res.warnings:
                warnings_by_type[w] = warnings_by_type.get(w, 0) + 1
                
    print(f"\nResult:")
    print(f"Total: {len(files)}")
    print(f"Clean questions: {len(files) - len(flagged_questions)}/{len(files)}")
    print(f"Flagged questions: {len(flagged_questions)}/{len(files)}")
    print(f"Warnings by type: {warnings_by_type}")
    if flagged_questions:
        print("Flagged details:", flagged_questions[:10])

if __name__ == "__main__":
    test_prn232_su25_run()
