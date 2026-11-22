import asyncio
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time

from docx import Document
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.main import app
from backend.app.db.session import init_db, async_session_factory
from backend.app.db.models import Job, Question, Answer
from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Approved key for PRM393 - SU26 - B5 - FE
APPROVED_KEY_B5 = [
    "C", "B", "B", "C", "B", "B", "B", "B", "B", "B",
    "B", "B", "B", "C", "B", "B", "C", "B", "C", "B",
    "C", "B", "C", "B", "B", "C", "B", "C", "B", "B",
    "B", "C", "B", "B", "B", "B", "B", "B", "B", "B",
    "B", "C", "B", "C", "B", "B", "C", "B", "B", "C"
]

def extract_docx_answers(docx_path: Path):
    doc = Document(docx_path)
    extracted = []
    q_counter = 1
    total_imgs = 0

    # Count inline shapes / blips (images) in document body
    for rel in doc.part.rels.values():
        if "image" in rel.target_ref:
            total_imgs += 1

    for p in doc.paragraphs:
        txt = p.text.strip()
        is_ans = False
        for run in p.runs:
            if run.font.size and run.font.size.pt == 20 and run.font.bold:
                is_ans = True
                break
        if is_ans and txt:
            extracted.append((q_counter, txt))
            q_counter += 1

    return extracted, total_imgs

async def main():
    print("=" * 70)
    print("  CHẠY PIPELINE THẬT SOẠN ĐỀ: PRM393 - SU26 - B5 - FE (Thread 1174)")
    print("=" * 70)

    # 1. Khởi tạo DB
    await init_db()

    # 2. Tạo client gọi API thật
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        payload = {
            "platform": "fuexam",
            "subject_code": "PRM393",
            "exam_type": "FE",
            "limit": 1,
            "exam_ids": [1174],
            "force_refresh": False,
        }
        print(f"\n[1] Gửi request POST /api/jobs:")
        print(json.dumps(payload, indent=2))

        t0 = time.time()
        resp = await client.post("/api/jobs", json=payload)
        print(f"Status code: {resp.status_code}")
        if resp.status_code != 200:
            print("Error:", resp.text)
            return

        job_data = resp.json()
        job_id = job_data["job_id"]
        print(f"[✓] Đã tạo Job ID: {job_id}")

        # 3. Theo dõi tiến trình qua GET /api/jobs/{job_id}
        print(f"\n[2] Theo dõi tiến trình Job {job_id} qua API thật:")
        status = job_data.get("status")
        last_step = ""

        while status in ("pending", "running", "init"):
            await asyncio.sleep(1.0)
            st_resp = await client.get(f"/api/jobs/{job_id}")
            if st_resp.status_code == 200:
                st_data = st_resp.json()
                status = st_data.get("status")
                step = st_data.get("current_step")
                prog = st_data.get("progress_percentage", 0.0)
                if step != last_step:
                    print(f"  [{time.strftime('%H:%M:%S')}] Tiến độ: {prog:4.1f}% | Bước: {step}")
                    last_step = step

        t1 = time.time()
        print(f"\n[✓] Job kết thúc với trạng thái: '{status.upper()}' sau {t1 - t0:.2f} giây")

        if status != "completed":
            print(f"[X] Job thất bại: {st_data.get('error_message')}")
            return

        # 4. In log job
        from backend.app.modules.jobs.orchestrator import get_orchestrator
        orch = get_orchestrator()
        history = orch._event_history.get(job_id, [])
        print(f"\n[3] LOG TIẾN TRÌNH THẬT CỦA JOB ({len(history)} sự kiện):")
        for ev in history:
            tp = ev.get("type")
            msg = ev.get("message", "")
            step = ev.get("step", "")
            prog = ev.get("progress", "")
            prog_str = f"({prog}%)" if prog != "" else ""
            print(f"  - [{tp.upper():14s}] {step:20s} {prog_str:6s}: {msg}")

        # 5. Kiểm tra file .docx thực tế trên đĩa
        out_dir = PROJECT_ROOT / "data" / "output" / "fuexam" / "PRM393"
        docx_file = out_dir / "PRM393 - SU26 - B5 - FE.docx"
        if not docx_file.exists():
            docx_file = PROJECT_ROOT / "data" / "output" / "fuexam" / "PRM393 - SU26 - B5 - FE.docx"

        assert docx_file.exists(), f"Tệp .docx không tồn tại: {docx_file}"

        file_bytes = docx_file.read_bytes()
        file_size_bytes = len(file_bytes)
        file_size_kb = file_size_bytes / 1024.0
        file_sha256 = hashlib.sha256(file_bytes).hexdigest()

        answers, total_images = extract_docx_answers(docx_file)

        # 6. Đọc nguồn từng câu hỏi từ DB thật
        async with async_session_factory() as db:
            q_stmt = select(Question).where(Question.exam_id == 1174).options(selectinload(Question.answer)).order_by(Question.index)
            q_res = await db.execute(q_stmt)
            db_questions = q_res.scalars().all()

        q_sources = {}
        for q in db_questions:
            src = "unknown"
            if q.answer and q.answer.vote_breakdown:
                src = q.answer.vote_breakdown.get("_source", "image")
            q_sources[q.index] = src

        print("\n" + "=" * 70)
        print("  BẰNG CHỨNG KIỂM ĐỊNH TỪ FILE .DOCX THẬT ĐÃ XUẤT:")
        print("=" * 70)
        print(f"- Đường dẫn tuyệt đối: {docx_file.resolve()}")
        print(f"- Kích thước:          {file_size_bytes:,} bytes ({file_size_kb:.2f} KB)")
        print(f"- Mã băm SHA-256:      {file_sha256}")
        print(f"- Số ảnh trong docx:   {total_images} ảnh")
        print(f"- Số câu hỏi:          {len(answers)} câu")

        # 7. In bảng đáp án đầy đủ kèm nguồn từng câu và so với bảng đã duyệt
        print("\n" + "-" * 70)
        print(f"{'Câu':<5} | {'Đáp án .docx':<14} | {'Bảng đã duyệt':<14} | {'Nguồn':<12} | {'Trạng thái':<10}")
        print("-" * 70)

        match_count = 0
        ans_letters_only = []

        for q_num, ans_text in answers:
            # Extract letter (e.g. 'C' from 'C' or 'C. Text')
            m_letter = ans_text[0].upper()
            ans_letters_only.append(m_letter)
            approved = APPROVED_KEY_B5[q_num - 1] if q_num - 1 < len(APPROVED_KEY_B5) else "?"
            source = q_sources.get(q_num, "image")
            is_match = (m_letter == approved)
            if is_match:
                match_count += 1
            match_str = "TRÙNG [✓]" if is_match else "LỆCH [X]"
            print(f"Q{q_num:02d}  | {ans_text:<14} | {approved:<14} | {source:<12} | {match_str:<10}")

        print("-" * 70)
        print(f"Chuỗi đáp án 50 câu: {','.join(ans_letters_only)}")
        print(f"Chuỗi đã duyệt:      {','.join(APPROVED_KEY_B5)}")
        pct = (match_count / len(answers)) * 100.0 if answers else 0.0
        print(f"Tỷ lệ khớp bảng duyệt: {match_count}/{len(answers)} ({pct:.1f}%)")
        print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
