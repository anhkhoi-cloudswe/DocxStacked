import json
import os
from pathlib import Path
import sqlite3
import sys
import time

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.modules.analysis.ai_check import get_ai_check_service
from backend.app.modules.analysis.voting import tally_votes
from backend.app.db.models import AnswerStatus, Comment

def run():
    db_path = BASE_DIR / "data" / "docxstacked.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    exam_id = 39

    # 1. Fetch questions
    c.execute("""
        SELECT q.id, q."index", q.file_name, q.local_image_path, q.cropped_image_path, q.crop_warnings,
               a.answer_set, a.confidence, a.status, a.vote_breakdown
        FROM questions q
        LEFT JOIN answers a ON a.question_id = q.id
        WHERE q.exam_id = ?
        ORDER BY q."index" ASC
    """, (exam_id,))
    q_rows = c.fetchall()

    print(f"Exam 39 has {len(q_rows)} questions.")

    # 2. Fetch comments per question
    c.execute("""
        SELECT id, question_id, comment_id, author_hash, raw_text, upvotes, is_reply, parent_comment_id, quoted_comment_id
        FROM comments
        WHERE question_id IN (SELECT id FROM questions WHERE exam_id = ?)
        ORDER BY id ASC
    """, (exam_id,))
    all_cmts = c.fetchall()

    comments_by_qid = {}
    for row in all_cmts:
        cid, qid, comment_id, author_hash, raw_text, upvotes, is_reply, parent_comment_id, quoted_comment_id = row
        c_obj = Comment(
            id=cid,
            question_id=qid,
            comment_id=comment_id,
            author_hash=author_hash,
            raw_text=raw_text,
            upvotes=upvotes or 0,
            is_reply=bool(is_reply),
            parent_comment_id=parent_comment_id,
            quoted_comment_id=quoted_comment_id,
        )
        comments_by_qid.setdefault(qid, []).append(c_obj)

    ai_service = get_ai_check_service()
    print("AI Service ready. Providers:", [p.name + ":" + p.model for p in ai_service.get_available_providers()])

    initial_table = []
    need_ai_list = []

    for r in q_rows:
        qid, idx, fn, local_p, crop_p, crop_warn, ans_set, conf, status, vote_bd = r
        cmts = comments_by_qid.get(qid, [])
        indep_authors = set(cmt.author_hash for cmt in cmts if cmt.author_hash)
        
        # docx_builder flag logic
        raw_warn = crop_warn
        if isinstance(raw_warn, str):
            try:
                raw_warn = json.loads(raw_warn)
            except Exception:
                raw_warn = [raw_warn]
        if raw_warn == "":
            raw_warn = []
        ans_text = ",".join(json.loads(ans_set)) if ans_set else "?"
        is_flagged = (
            status in (AnswerStatus.CONFLICT.value, AnswerStatus.WEAK.value, AnswerStatus.NO_DATA.value)
            or ans_text.startswith("?")
            or bool(raw_warn)
        )
        
        initial_table.append({
            "idx": idx,
            "qid": qid,
            "cmts_count": len(cmts),
            "indep_count": len(indep_authors),
            "status": status,
            "has_ai": False,
            "is_flagged": is_flagged,
            "crop_p": crop_p,
            "local_p": local_p,
            "crop_warn": raw_warn,
        })
        
        if status in (AnswerStatus.CONFLICT.value, AnswerStatus.WEAK.value, AnswerStatus.NO_DATA.value) or (conf and conf < 0.80):
            need_ai_list.append((qid, idx, crop_p or local_p))

    print(f"\n--- BẢNG 50 DÒNG BAN ĐẦU CỦA PRM393 - SU26 - FE ---")
    print(f"{'Câu':<5} | {'Số bình luận':<14} | {'Người độc lập':<15} | {'Trạng thái':<12} | {'Phiếu AI':<10} | {'Có cờ':<7}")
    print("-" * 75)
    init_flagged = 0
    for it in initial_table:
        if it["is_flagged"]:
            init_flagged += 1
        print(f"{it['idx']:<5} | {it['cmts_count']:<14} | {it['indep_count']:<15} | {str(it['status']):<12} | {str(it['has_ai']):<10} | {str(it['is_flagged']):<7}")
    print("-" * 75)
    print(f"Tổng số câu có cờ ban đầu: {init_flagged}/{len(initial_table)}")

    print(f"\nSố câu cần gọi AI (WEAK / CONFLICT): {len(need_ai_list)}")

    # Run AI on need_ai_list
    processed_count = 0
    ai_results_by_qid = {}

    for qid, idx, img_path_str in need_ai_list:
        processed_count += 1
        img_path = BASE_DIR / img_path_str if not Path(img_path_str).is_absolute() else Path(img_path_str)
        print(f"[{processed_count}/{len(need_ai_list)}] Calling AI for Câu {idx} ({img_path.name})...", end="", flush=True)
        
        t0 = time.time()
        analyses = ai_service.analyze_question_ensemble(img_path, job_id="prm393_ai_fix")
        elapsed = time.time() - t0
        
        if analyses:
            first = analyses[0]
            print(f" -> {first.answers} (conf: {first.confidence}) in {elapsed:.2f}s")
            ai_results_by_qid[qid] = analyses
        else:
            print(f" -> No AI response in {elapsed:.2f}s")
            ai_results_by_qid[qid] = []

        # If call was remote (>0.5s), sleep 4.2s to respect 15 RPM
        if elapsed > 0.5:
            time.sleep(4.2)

    # 3. Re-tally all questions and update DB
    print("\nCập nhật đáp án và re-tally lại trong cơ sở dữ liệu...")
    after_table = []
    after_flagged = 0

    for it in initial_table:
        qid = it["qid"]
        idx = it["idx"]
        cmts = comments_by_qid.get(qid, [])
        analyses = ai_results_by_qid.get(qid, [])
        
        ai_votes = []
        ai_options = {}
        for a in analyses:
            ai_votes.append({
                "provider": a.provider or "gemini",
                "answers": a.answers,
                "confidence": a.confidence,
            })
            if a.options:
                ai_options.update(a.options)

        voting_res = tally_votes(
            cmts,
            ai_votes=ai_votes if ai_votes else None,
            ai_weight=2.0,
            max_option_letter="D",
        )

        breakdown = dict(voting_res.vote_breakdown)
        if ai_options:
            breakdown["_options"] = ai_options
        if ai_votes:
            breakdown["_ai_votes"] = ai_votes

        # Check flag
        raw_warn = it["crop_warn"]
        ans_text = ",".join(voting_res.answer_set)
        is_flagged = (
            voting_res.status in (AnswerStatus.CONFLICT, AnswerStatus.WEAK, AnswerStatus.NO_DATA)
            or ans_text.startswith("?")
            or bool(raw_warn)
        )
        if is_flagged:
            after_flagged += 1

        has_ai = bool(ai_votes)

        after_table.append({
            "idx": idx,
            "ans_set": ans_text,
            "cmts_count": it["cmts_count"],
            "indep_count": it["indep_count"],
            "status": voting_res.status.value,
            "has_ai": has_ai,
            "is_flagged": is_flagged,
        })

        # Update DB
        ans_json = json.dumps(voting_res.answer_set)
        bd_json = json.dumps(breakdown)
        c.execute("""
            UPDATE answers
            SET answer_set = ?, confidence = ?, status = ?, valid_comments_count = ?, vote_breakdown = ?, updated_at = CURRENT_TIMESTAMP
            WHERE question_id = ?
        """, (ans_json, voting_res.confidence, voting_res.status.value, voting_res.voters_count, bd_json, qid))

    conn.commit()
    conn.close()

    print(f"\n--- BẢNG 50 DÒNG SAU KHI CHẠY AI CỦA PRM393 - SU26 - FE ---")
    print(f"{'Câu':<5} | {'Đáp án':<8} | {'Số cmt':<8} | {'Người độc lập':<14} | {'Trạng thái':<12} | {'Phiếu AI':<10} | {'Có cờ':<7}")
    print("-" * 80)
    for at in after_table:
        print(f"{at['idx']:<5} | {at['ans_set']:<8} | {at['cmts_count']:<8} | {at['indep_count']:<14} | {at['status']:<12} | {str(at['has_ai']):<10} | {str(at['is_flagged']):<7}")
    print("-" * 80)
    print(f"Tổng số câu có cờ sau khi chạy AI: {after_flagged}/{len(after_table)}")

if __name__ == "__main__":
    run()
