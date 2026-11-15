"""
Automated AI Audit & Testing Suite (Script + Report) for DocxStacked
Target exams:
- ITE302c SU26 FE (id 113)
- ITE302c SU26 RE (id 109)
- ITE302c FA 2024 RE (id 123)
- ITE302c SU25 RE (id 119)
- PRM392 SP24 FE (id 42)
- PRM392 SP24 RE (id 41)
- PRM393 SU26 FE (id 39)

Features:
A. Gemini rate limiting:
   - Concurrency = 1 and configurable minimum delay (default 7.0s).
   - 60s timeout per call.
   - 4 retries on 429/503/timeout with exponential backoff + jitter and Retry-After header respect.
   - Multi-key cache: (crop_hash, provider, model, prompt_version) + legacy phash.
   - Daily quota counter: marks remaining questions as ai_pending without failing job.
   - Checkpoint persistence for resume.
B. Verified with mock provider tests.
C. Real Gemini execution in 3 steps:
   1. Smoke test 5 questions
   2. All weak/conflict/no_data questions
   3. Sample 30 confident questions (fixed seed)
D. Automatic reporting to CSV, MD, and Contact Sheet image mosaic.
"""

import argparse
import csv
from datetime import datetime, date
import json
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

# Set up project root
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Answer, AnswerStatus, Comment, Exam, Question
from backend.app.db.session import SyncSessionLocal
from backend.app.modules.analysis.ai_check import (
    AICheckService,
    AIQuestionAnalysis,
    PROMPT_VERSION,
    get_ai_check_service,
)
from backend.app.modules.analysis.gemini_guard import (
    AIRateLimiter,
    CheckpointManager,
    DailyQuotaExhaustedError,
    DailyQuotaTracker,
    get_ai_rate_limiter,
    get_daily_quota_tracker,
)
from backend.app.modules.analysis.providers import (
    GeminiProvider,
    ProviderRateLimitError,
    ProviderNetworkError,
    ProviderAPIError,
)
from backend.app.modules.analysis.voting import tally_votes

logger = get_logger(__name__)
settings = get_settings()

TARGET_EXAM_IDS = [39, 41, 42, 109, 113, 119, 123]


class AIAuditRunner:
    def __init__(
        self,
        min_interval: float = 7.0,
        timeout: float = 60.0,
        daily_limit: int = 1500,
        force_refresh: bool = False,
        seed: int = 42,
        output_dir: Optional[Path] = None,
        max_calls: Optional[int] = None,
    ):
        self.min_interval = min_interval
        self.timeout = timeout
        self.daily_limit = daily_limit
        self.force_refresh = force_refresh
        self.seed = seed
        self.max_calls = max_calls
        self.output_dir = output_dir or (settings.BASE_DIR / "data" / "eval")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.ai_service = get_ai_check_service()
        self.rate_limiter = get_ai_rate_limiter(min_interval=min_interval)
        self.rate_limiter.min_interval_seconds = min_interval
        self.quota_tracker = get_daily_quota_tracker(default_limit=daily_limit)
        self.checkpoint_manager = CheckpointManager(self.output_dir / "ai_audit_checkpoint.json")

        self.calls_made_this_run = 0
        self.cache_hits_this_run = 0
        self.timeouts_429_count = 0
        self.start_time = 0.0
        self.end_time = 0.0

        # Detailed record collections for report
        self.question_records: List[Dict[str, Any]] = []
        self.mismatches: List[Dict[str, Any]] = []

    def _get_active_gemini_provider(self) -> Optional[GeminiProvider]:
        for p in self.ai_service.get_available_providers():
            if isinstance(p, GeminiProvider) and p.is_available():
                p.timeout_seconds = self.timeout
                p.rate_limiter = self.rate_limiter
                return p
        # If not in default list, create one
        gem = GeminiProvider(
            name="gemini",
            model="gemini-2.5-flash",
            api_key_env="GEMINI_API_KEY",
            max_retries=4,
            backoff_seconds=2.0,
            timeout_seconds=self.timeout,
        )
        gem.rate_limiter = self.rate_limiter
        if gem.is_available():
            return gem
        return None

    def evaluate_single_question(
        self,
        db,
        question: Question,
        exam: Exam,
        step_name: str,
    ) -> Dict[str, Any]:
        """
        Evaluate a single question:
        1. Measure community vote before AI.
        2. Call Gemini AI (or hit cache), respecting rate limiter and quota.
        3. Tally votes with AI.
        4. Update DB record.
        5. Return structured audit dict.
        """
        img_path = None
        if question.cropped_image_path and os.path.exists(question.cropped_image_path):
            img_path = Path(question.cropped_image_path)
        elif question.local_image_path and os.path.exists(question.local_image_path):
            img_path = Path(question.local_image_path)

        # Baseline community tally before AI
        prelim_res = tally_votes(question.comments, ai_weight=1.0)
        status_before = prelim_res.status
        answer_before = prelim_res.answer_set

        ai_called = False
        ai_success = False
        ai_timed_out_or_429 = False
        ai_answer = None
        ai_confidence = 0.0
        ai_options = {}
        ai_latency = 0.0
        cache_hit = False

        gemini_provider = self._get_active_gemini_provider()

        if img_path and gemini_provider:
            # Check cache first
            cached_res = self.ai_service._lookup_cache(gemini_provider, img_path)
            if cached_res and not self.force_refresh:
                cache_hit = True
                self.cache_hits_this_run += 1
                ai_success = True
                ai_answer = cached_res.answers
                ai_confidence = cached_res.confidence
                ai_options = cached_res.options
            else:
                # Need live API call
                if self.max_calls is not None and self.calls_made_this_run >= self.max_calls:
                    logger.warning(f"Reached max calls limit ({self.max_calls}) for this run.")
                elif not self.quota_tracker.can_call():
                    logger.warning("Daily AI quota exhausted. Marking question as ai_pending.")
                else:
                    ai_called = True
                    t0 = time.time()
                    try:
                        analysis = self.ai_service.analyze_with_provider(
                            gemini_provider,
                            img_path,
                            force_refresh=self.force_refresh,
                        )
                        ai_latency = round(time.time() - t0, 2)
                        self.calls_made_this_run += 1
                        if analysis:
                            ai_success = True
                            ai_answer = analysis.answers
                            ai_confidence = analysis.confidence
                            ai_options = analysis.options
                    except (ProviderRateLimitError, ProviderNetworkError, TimeoutError) as net_err:
                        self.timeouts_429_count += 1
                        ai_timed_out_or_429 = True
                        logger.warning(f"AI call failed for Q{question.id}: {net_err}")
                    except DailyQuotaExhaustedError:
                        logger.warning(f"Daily quota exhausted while processing Q{question.id}")
                    except Exception as err:
                        logger.warning(f"Unexpected error calling AI for Q{question.id}: {err}")

        # Tally final vote
        ai_votes = []
        if ai_success and ai_answer:
            ai_votes.append({
                "provider": "gemini",
                "answers": ai_answer,
                "confidence": ai_confidence,
                "weight": 1.0,
            })

        final_res = tally_votes(
            question.comments,
            ai_votes=ai_votes if ai_votes else None,
            ai_weight=1.0,
        )

        status_after = final_res.status
        answer_after = final_res.answer_set
        status_changed = (status_before != status_after)

        # Check agreement
        ai_agreed_with_community = None
        ai_disagreed_with_community = False
        if ai_success and ai_answer and status_before != AnswerStatus.NO_DATA:
            ai_agreed_with_community = (set(ai_answer) == set(answer_before))
            ai_disagreed_with_community = not ai_agreed_with_community

        # Update DB Answer record
        breakdown = dict(final_res.vote_breakdown)
        if ai_options:
            breakdown["_options"] = ai_options
        if ai_votes:
            breakdown["_ai_votes"] = ai_votes
        if not ai_success and (not self.quota_tracker.can_call() or (self.max_calls and self.calls_made_this_run >= self.max_calls)):
            breakdown["_ai_status"] = "ai_pending"

        if not question.answer:
            ans = Answer(
                question_id=question.id,
                answer_set=final_res.answer_set,
                status=final_res.status,
                confidence=final_res.confidence,
                valid_comments_count=final_res.voters_count,
                vote_breakdown=breakdown,
            )
            db.add(ans)
            question.answer = ans
        else:
            question.answer.answer_set = final_res.answer_set
            question.answer.status = final_res.status
            question.answer.confidence = final_res.confidence
            question.answer.valid_comments_count = final_res.voters_count
            question.answer.vote_breakdown = breakdown
        db.commit()

        rec = {
            "step": step_name,
            "exam_id": exam.id,
            "exam_title": exam.title,
            "question_id": question.id,
            "question_index": question.index,
            "image_path": str(img_path) if img_path else "",
            "comments_count": len(question.comments),
            "status_before": status_before.value,
            "answer_before": answer_before,
            "ai_called": ai_called,
            "ai_cache_hit": cache_hit,
            "ai_success": ai_success,
            "ai_timeout_429": ai_timed_out_or_429,
            "ai_answer": ai_answer,
            "ai_confidence": ai_confidence,
            "ai_latency_sec": ai_latency,
            "status_after": status_after.value,
            "answer_after": answer_after,
            "status_changed": status_changed,
            "ai_agreed": ai_agreed_with_community,
            "ai_disagreed": ai_disagreed_with_community,
            "voters_count": final_res.voters_count,
            "vote_breakdown": final_res.vote_breakdown,
        }
        self.question_records.append(rec)

        if ai_disagreed_with_community and img_path:
            self.mismatches.append(rec)

        return rec

    def run_step1_smoke(self, db, target_exams: List[Exam]) -> List[Dict[str, Any]]:
        """
        Step 1: Smoke test 5 questions.
        Prints detailed AI log, DB answer record, AI vote in voting table, before/after status.
        """
        print("\n" + "=" * 80)
        print("BƯỚC 1: SMOKE TEST 5 CÂU (Kiểm tra kết nối Gemini, DB, Bỏ phiếu, Trước/Sau)")
        print("=" * 80)

        # Pick 5 questions from diverse exams
        sample_questions = []
        for e in target_exams:
            qs = db.query(Question).filter(Question.exam_id == e.id).order_by(Question.index).all()
            if qs:
                # Pick 1 from each until 5
                sample_questions.append((qs[0], e))
                if len(sample_questions) == 5:
                    break

        smoke_results = []
        for idx, (q, exam) in enumerate(sample_questions, 1):
            print(f"\n--- [Smoke #{idx}/5] Đề: {exam.title} | Câu {q.index} (Q{q.id}) ---")
            rec = self.evaluate_single_question(db, q, exam, step_name="smoke")
            smoke_results.append(rec)

            print(f"  * Trạng thái cộng đồng TRƯỚC AI : {rec['status_before'].upper()} (Đáp án: {rec['answer_before']})")
            print(f"  * Gọi AI ({'CACHE HIT' if rec['ai_cache_hit'] else 'LIVE API'}):")
            print(f"      - Đã gọi       : {rec['ai_called']}")
            print(f"      - Thành công   : {rec['ai_success']}")
            print(f"      - Đáp án AI    : {rec['ai_answer']} (Độ tin cậy: {rec['ai_confidence']:.2f})")
            if rec['ai_latency_sec'] > 0:
                print(f"      - Thời gian    : {rec['ai_latency_sec']}s")
            print(f"  * Bản ghi DB Answer:")
            print(f"      - answer_set   : {q.answer.answer_set}")
            print(f"      - status       : {q.answer.status.value.upper()}")
            print(f"      - confidence   : {q.answer.confidence:.2f}")
            print(f"      - ai_votes     : {q.answer.vote_breakdown.get('_ai_votes')}")
            print(f"  * Trạng thái SAU AI           : {rec['status_after'].upper()} (Đáp án: {rec['answer_after']})")
            print(f"  * Thay đổi trạng thái          : {'ĐÃ ĐỔI -> ' + rec['status_after'].upper() if rec['status_changed'] else 'Giữ nguyên'}")

        print("\n=> Hoàn thành Bước 1 Smoke test 5 câu thành công.")
        return smoke_results

    def run_step2_uncertain(self, db, target_exams: List[Exam]) -> List[Dict[str, Any]]:
        """
        Step 2: Evaluate all weak/conflict/no_data questions of the target exams.
        """
        print("\n" + "=" * 80)
        print("BƯỚC 2: CHẠY TOÀN BỘ CÂU WEAK / CONFLICT / NO_DATA CỦA 7 ĐỀ")
        print("=" * 80)

        # Identify all questions with weak/conflict/no_data
        uncertain_pairs: List[Tuple[Question, Exam]] = []
        for e in target_exams:
            qs = db.query(Question).filter(Question.exam_id == e.id).order_by(Question.index).all()
            for q in qs:
                # Preliminary check
                prelim = tally_votes(q.comments, ai_weight=1.0)
                if prelim.status in (AnswerStatus.WEAK, AnswerStatus.CONFLICT, AnswerStatus.NO_DATA):
                    uncertain_pairs.append((q, e))

        # Sort by priority: conflict (1) > no_data (2) > weak with 1 voter (3) > other weak (4)
        def get_question_priority(q: Question) -> int:
            prelim = tally_votes(q.comments, ai_weight=1.0)
            if prelim.status == AnswerStatus.CONFLICT:
                return 1
            if prelim.status == AnswerStatus.NO_DATA:
                return 2
            if prelim.status == AnswerStatus.WEAK:
                voter_count = len([c for c in q.comments if c.raw_text and c.raw_text.strip()])
                return 3 if voter_count <= 1 else 4
            return 5

        uncertain_pairs.sort(key=lambda pair: (get_question_priority(pair[0]), pair[1].id, pair[0].index))

        p_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for q, _ in uncertain_pairs:
            p_counts[get_question_priority(q)] += 1

        print(
            f"Tìm thấy tổng cộng {len(uncertain_pairs)} câu hỏi cần đánh giá. "
            f"Phân loại ưu tiên: {p_counts[1]} conflict, {p_counts[2]} no_data, "
            f"{p_counts[3]} weak (1 phiếu), {p_counts[4]} weak khác."
        )

        processed_ids = set(self.checkpoint_manager.load().get("completed_question_ids", []))
        results = []
        warned_quota = False

        for idx, (q, exam) in enumerate(uncertain_pairs, 1):
            if q.id in processed_ids and not self.force_refresh:
                continue

            can_call_ai = self.quota_tracker.can_call()
            img_p = Path(q.cropped_image_path or q.local_image_path or "")
            is_cached = (self.ai_service._lookup_cache(self._get_active_gemini_provider(), img_p) is not None) if img_p.exists() else False

            if not can_call_ai and not is_cached:
                if not warned_quota:
                    print(f"[!] Hết hạn mức gọi AI trong ngày ({self.daily_limit}). Đánh dấu các câu còn lại ai_pending, job vẫn chạy tiếp theo số đông.")
                    warned_quota = True
                rec = self.evaluate_single_question(db, q, exam, step_name="uncertain_pending")
                results.append(rec)
                self.checkpoint_manager.mark_processed(q.id, {"status": "ai_pending"})
                if idx % 20 == 0 or idx == len(uncertain_pairs):
                    print(f"  -> Đang xử lý pending {idx}/{len(uncertain_pairs)} câu...")
                    sys.stdout.flush()
                continue

            rec = self.evaluate_single_question(db, q, exam, step_name="uncertain")
            results.append(rec)
            self.checkpoint_manager.mark_processed(q.id, {
                "exam": exam.title,
                "index": q.index,
                "status_after": rec["status_after"],
                "answer_after": rec["answer_after"],
            })

            if idx % 10 == 0 or idx == len(uncertain_pairs):
                print(f"  -> Tiến độ Bước 2: {idx}/{len(uncertain_pairs)} câu | Gọi mới: {self.calls_made_this_run} | Cache hits: {self.cache_hits_this_run}")

        print(f"=> Hoàn thành Bước 2. Đã xử lý {len(results)} câu.")
        return results

    def run_step3_confident_sample(self, db, target_exams: List[Exam]) -> List[Dict[str, Any]]:
        """
        Step 3: Sample 30 confident questions (fixed seed) to measure AI agreement with majority.
        """
        print("\n" + "=" * 80)
        print("BƯỚC 3: MẪU 30 CÂU CONFIDENT (Seed=42) ĐỂ ĐO ĐỘ ĐỒNG Ý CỦA AI VỚI SỐ ĐÔNG")
        print("=" * 80)

        # Collect all confident questions
        confident_pairs: List[Tuple[Question, Exam]] = []
        for e in target_exams:
            qs = db.query(Question).filter(Question.exam_id == e.id).order_by(Question.index).all()
            for q in qs:
                prelim = tally_votes(q.comments, ai_weight=1.0)
                if prelim.status == AnswerStatus.CONFIDENT:
                    confident_pairs.append((q, e))

        print(f"Tổng số câu confident trong 7 đề: {len(confident_pairs)}")

        # Random sample with fixed seed
        rng = random.Random(self.seed)
        sample_count = min(30, len(confident_pairs))
        sampled_pairs = rng.sample(confident_pairs, sample_count)

        print(f"Đã chọn ngẫu nhiên {sample_count} câu với seed={self.seed}.")

        results = []
        agreed_count = 0
        disagreed_count = 0

        for idx, (q, exam) in enumerate(sampled_pairs, 1):
            rec = self.evaluate_single_question(db, q, exam, step_name="sample_confident")
            results.append(rec)

            if rec["ai_agreed"] is True:
                agreed_count += 1
            elif rec["ai_disagreed"] is True:
                disagreed_count += 1

            if idx % 10 == 0 or idx == sample_count:
                print(f"  -> Tiến độ Bước 3: {idx}/{sample_count} câu | Đồng ý: {agreed_count} | Khác: {disagreed_count}")

        agreement_rate = (agreed_count / max(1, agreed_count + disagreed_count)) * 100.0
        print(f"=> Kết quả mẫu 30 câu: AI đồng ý: {agreed_count}/{agreed_count + disagreed_count} ({agreement_rate:.1f}%), Khác số đông: {disagreed_count}")
        return results

    def generate_contact_sheet(self, mismatches: List[Dict[str, Any]], output_path: Path) -> Optional[Path]:
        """
        Generate a mosaic contact sheet image of question crops where AI disagreed with community.
        Annotates question index, community answer, AI answer, and votes.
        """
        if not mismatches:
            print("Không có câu nào AI khác số đông để tạo contact sheet.")
            return None

        print(f"\nĐang tạo contact sheet cho {len(mismatches)} câu AI khác số đông...")

        cards = []
        card_w = 480
        card_h = 320
        banner_h = 48

        for m in mismatches:
            img_file = Path(m["image_path"])
            if not img_file.exists():
                continue

            card = Image.new("RGB", (card_w, card_h), (245, 247, 250))
            draw = ImageDraw.Draw(card)

            # Draw banner
            draw.rectangle([(0, 0), (card_w, banner_h)], fill=(220, 53, 69))
            title_text = f"[{m['exam_title'][:15]}.. Q{m['question_index']}] Maj: {m['answer_before']} | AI: {m['ai_answer']} ({m['ai_confidence']*100:.0f}%)"
            sub_text = f"Votes: {m['voters_count']} | QID: {m['question_id']}"

            font = ImageFont.load_default()
            draw.text((10, 8), title_text, fill=(255, 255, 255), font=font)
            draw.text((10, 26), sub_text, fill=(255, 240, 240), font=font)

            # Open and paste thumbnail crop
            try:
                with Image.open(img_file) as im:
                    im_ratio = im.width / max(1, im.height)
                    avail_w = card_w - 16
                    avail_h = card_h - banner_h - 16
                    target_ratio = avail_w / avail_h

                    if im_ratio > target_ratio:
                        new_w = avail_w
                        new_h = int(new_w / im_ratio)
                    else:
                        new_h = avail_h
                        new_w = int(new_h * im_ratio)

                    thumb = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    x_offset = 8 + (avail_w - new_w) // 2
                    y_offset = banner_h + 8 + (avail_h - new_h) // 2
                    card.paste(thumb, (x_offset, y_offset))
            except Exception as e:
                logger.warning(f"Error thumbnailing {img_file}: {e}")

            # Border
            draw.rectangle([(0, 0), (card_w - 1, card_h - 1)], outline=(200, 205, 215), width=2)
            cards.append(card)

        if not cards:
            return None

        # Arrange in grid (columns = 2 or 3)
        cols = 2 if len(cards) <= 4 else 3
        rows = (len(cards) + cols - 1) // cols
        sheet_w = cols * card_w + (cols + 1) * 16
        sheet_h = rows * card_h + (rows + 1) * 16

        sheet = Image.new("RGB", (sheet_w, sheet_h), (230, 235, 242))
        for idx, c in enumerate(cards):
            r = idx // cols
            col = idx % cols
            x = 16 + col * (card_w + 16)
            y = 16 + r * (card_h + 16)
            sheet.paste(c, (x, y))

        sheet.save(output_path, quality=90)
        print(f"Contact sheet đã lưu tại: {output_path}")
        return output_path

    def compile_and_save_reports(
        self,
        db,
        target_exams: List[Exam],
        cmd_string: str,
    ) -> Tuple[Path, Path, Optional[Path]]:
        """
        Generate CSV and Markdown reports from real DB numbers, and contact sheet.
        """
        local_now = datetime.now().astimezone()
        tz_offset = local_now.strftime("%z")
        tz_str = f"GMT{tz_offset[:3]}:{tz_offset[3:]}" if tz_offset else "Local"
        
        # When --max-calls 0, append hour/min/sec to avoid overwriting previous audit reports
        if self.max_calls == 0:
            file_suffix = local_now.strftime("%Y%m%d_%H%M%S")
        else:
            file_suffix = local_now.strftime("%Y%m%d")

        csv_path = self.output_dir / f"ai_audit_{file_suffix}.csv"
        md_path = self.output_dir / f"ai_audit_{file_suffix}.md"
        contact_sheet_path = self.output_dir / f"ai_contact_sheet_{file_suffix}.png"

        total_duration = round(self.end_time - self.start_time, 2)
        provider = self._get_active_gemini_provider()
        model_name = provider.model if provider else "gemini-2.5-flash"
        model_stat = self.quota_tracker.get_model_status(model_name)
        model_limit = model_stat.get("daily_limit", self.daily_limit)
        remaining_quota = self.quota_tracker.remaining_calls(model=model_name)

        # Build stats per exam from actual DB
        exam_stats = []
        for e in target_exams:
            qs = db.query(Question).filter(Question.exam_id == e.id).all()
            q_ids = [q.id for q in qs]

            # Count statuses in DB
            c_conf = sum(1 for q in qs if q.answer and q.answer.status == AnswerStatus.CONFIDENT)
            c_weak = sum(1 for q in qs if q.answer and q.answer.status == AnswerStatus.WEAK)
            c_conflict = sum(1 for q in qs if q.answer and q.answer.status == AnswerStatus.CONFLICT)
            c_no_data = sum(1 for q in qs if not q.answer or q.answer.status == AnswerStatus.NO_DATA)

            # Sub-records from audit runs
            recs = [r for r in self.question_records if r["exam_id"] == e.id]
            ai_called = sum(1 for r in recs if r["ai_called"])
            ai_answered = sum(1 for r in recs if r["ai_success"])
            timeout_429 = sum(1 for r in recs if r["ai_timeout_429"])
            ai_agreed = sum(1 for r in recs if r["ai_agreed"] is True)
            ai_disagreed = sum(1 for r in recs if r["ai_disagreed"] is True)
            status_changed = sum(1 for r in recs if r["status_changed"])

            exam_stats.append({
                "exam_id": e.id,
                "exam_title": e.title,
                "total_questions": len(qs),
                "confident": c_conf,
                "weak": c_weak,
                "conflict": c_conflict,
                "no_data": c_no_data,
                "ai_called": ai_called,
                "ai_answered": ai_answered,
                "timeout_429": timeout_429,
                "ai_agreed": ai_agreed,
                "ai_disagreed": ai_disagreed,
                "status_changed": status_changed,
            })

        # Save CSV
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["--- BANG TONG HOP THEO DE ---"])
            writer.writerow([
                "exam_id", "exam_title", "total_questions", "confident", "weak",
                "conflict", "no_data", "ai_called", "ai_answered", "timeout_429",
                "ai_agreed", "ai_disagreed", "status_changed"
            ])
            for st in exam_stats:
                writer.writerow([
                    st["exam_id"], st["exam_title"], st["total_questions"],
                    st["confident"], st["weak"], st["conflict"], st["no_data"],
                    st["ai_called"], st["ai_answered"], st["timeout_429"],
                    st["ai_agreed"], st["ai_disagreed"], st["status_changed"],
                ])

            writer.writerow([])
            writer.writerow(["--- DANH SACH CAU AI KHAC SO DONG ---"])
            writer.writerow([
                "exam_title", "question_index", "community_majority", "ai_answer",
                "ai_confidence", "voters_count", "cropped_image_path"
            ])
            for m in self.mismatches:
                writer.writerow([
                    m["exam_title"], m["question_index"], "".join(m["answer_before"]),
                    "".join(m["ai_answer"] or []), f"{m['ai_confidence']:.2f}",
                    m["voters_count"], m["image_path"],
                ])

        # Generate contact sheet
        cs_result = self.generate_contact_sheet(self.mismatches, contact_sheet_path)

        # Save Markdown Report
        md_lines = []
        md_lines.append(f"# BÁO CÁO KIỂM THỬ AI TỰ ĐỘNG (AI AUDIT REPORT)")
        md_lines.append(f"**Ngày thực hiện:** {local_now.strftime('%Y-%m-%d %H:%M:%S')} ({tz_str})")
        md_lines.append(f"**Lệnh đã chạy:** `{cmd_string}`\n")

        md_lines.append("## 1. Dòng tổng kết")
        md_lines.append(f"- **Số lượt gọi thật (Live API calls):** {self.calls_made_this_run}")
        md_lines.append(f"- **Số lượt lấy từ cache (Cache hits):** {self.cache_hits_this_run}")
        md_lines.append(f"- **Số lần lỗi 429 / Timeout:** {self.timeouts_429_count}")
        md_lines.append(f"- **Thời gian chạy:** {total_duration:.1f} giây ({total_duration/60:.1f} phút)")
        md_lines.append(f"- **Hạn mức AI theo model ({model_name}):** {remaining_quota} lượt còn lại (Hạn mức model: {model_limit}/ngày)")
        md_lines.append(f"- **Số câu AI khác số đông:** {len(self.mismatches)}\n")

        md_lines.append("## 2. Bảng thống kê theo đề")
        md_lines.append("| ID | Tên đề | Tổng câu | Confident | Weak | Conflict | No Data | Đã gọi AI | AI trả lời | 429/Timeout | AI đồng ý | AI khác | Đổi trạng thái |")
        md_lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for st in exam_stats:
            md_lines.append(
                f"| {st['exam_id']} | {st['exam_title']} | {st['total_questions']} | {st['confident']} | {st['weak']} | "
                f"{st['conflict']} | {st['no_data']} | {st['ai_called']} | {st['ai_answered']} | {st['timeout_429']} | "
                f"{st['ai_agreed']} | {st['ai_disagreed']} | {st['status_changed']} |"
            )

        md_lines.append("\n## 3. Danh sách câu AI khác số đông (Cần kiểm tay)")
        if self.mismatches:
            md_lines.append("| Đề thi | Câu # | Số đông | AI | Độ tin cậy AI | Phiếu CĐ | Đường dẫn ảnh crop |")
            md_lines.append("|---|---|---|---|---|---|---|")
            for m in self.mismatches:
                crop_rel = os.path.relpath(m["image_path"], settings.BASE_DIR) if m["image_path"] else "N/A"
                md_lines.append(
                    f"| {m['exam_title']} | Q{m['question_index']} | **{','.join(m['answer_before'])}** | "
                    f"**{','.join(m['ai_answer'] or ['?'])}** | {m['ai_confidence']*100:.0f}% | "
                    f"{m['voters_count']} | `{crop_rel}` |"
                )
        else:
            md_lines.append("*Không có câu nào AI khác với số đông cộng đồng.*")

        md_lines.append("\n## 4. Tấm Contact Sheet ảnh crop kiểm tay")
        if cs_result:
            cs_rel = os.path.relpath(cs_result, self.output_dir)
            md_lines.append(f"![Contact Sheet]({cs_rel})\n")
            md_lines.append(f"*File ảnh contact sheet: `{cs_result}`*")
        else:
            md_lines.append("*Không có ảnh khác biệt để tạo contact sheet.*")

        md_path.write_text("\n".join(md_lines), encoding="utf-8")

        print("\n" + "=" * 80)
        print("KẾT THÚC BÁO CÁO")
        print(f"CSV đã lưu : {csv_path}")
        print(f"MD đã lưu  : {md_path}")
        if cs_result:
            print(f"Contact Sheet: {contact_sheet_path}")
        print("=" * 80)

        return csv_path, md_path, cs_result


def main():
    parser = argparse.ArgumentParser(description="DocxStacked AI Automated Audit & Testing Suite")
    parser.add_argument("--step", choices=["smoke", "uncertain", "sample", "all"], default="all",
                        help="Bước chạy: smoke (5 câu), uncertain (toàn bộ weak/conflict/no_data), sample (30 confident), all (cả 3 bước)")
    parser.add_argument("--interval", type=float, default=7.0, help="Khoảng cách tối thiểu giữa 2 lần gọi (giây, mặc định 7.0)")
    parser.add_argument("--timeout", type=float, default=60.0, help="Hết thời gian chờ mỗi lần gọi (giây, mặc định 60.0)")
    parser.add_argument("--daily-limit", type=int, default=1500, help="Hạn mức số lượt gọi trong ngày (mặc định 1500)")
    parser.add_argument("--max-calls", type=int, default=None, help="Giới hạn tối đa số lượt gọi trong phiên chạy này")
    parser.add_argument("--force-refresh", action="store_true", help="Bỏ qua cache pHash/sha256, bắt buộc gọi lại API")
    parser.add_argument("--seed", type=int, default=42, help="Hạt giống ngẫu nhiên cho mẫu 30 câu confident")
    args = parser.parse_args()

    cmd_string = "python " + " ".join(sys.argv)

    db = SyncSessionLocal()
    try:
        target_exams = db.query(Exam).filter(Exam.id.in_(TARGET_EXAM_IDS)).order_by(Exam.id).all()
        if not target_exams:
            print(f"Không tìm thấy đề thi mục tiêu trong DB: {TARGET_EXAM_IDS}")
            return

        runner = AIAuditRunner(
            min_interval=args.interval,
            timeout=args.timeout,
            daily_limit=args.daily_limit,
            force_refresh=args.force_refresh,
            seed=args.seed,
            max_calls=args.max_calls,
        )

        runner.start_time = time.time()

        if args.step in ("smoke", "all"):
            runner.run_step1_smoke(db, target_exams)

        if args.step in ("uncertain", "all"):
            runner.run_step2_uncertain(db, target_exams)

        if args.step in ("sample", "all"):
            runner.run_step3_confident_sample(db, target_exams)

        runner.end_time = time.time()

        csv_p, md_p, cs_p = runner.compile_and_save_reports(db, target_exams, cmd_string)

        # Print summary lines to stdout
        print("\n" + "#" * 80)
        print("TỔNG KẾT PHIÊN AUDIT AI:")
        print(f"  * Lệnh đã chạy             : {cmd_string}")
        print(f"  * Số lượt gọi API thực tế   : {runner.calls_made_this_run}")
        print(f"  * Số lượt lấy từ cache      : {runner.cache_hits_this_run}")
        print(f"  * Số lần lỗi 429/Timeout    : {runner.timeouts_429_count}")
        print(f"  * Thời gian chạy            : {runner.end_time - runner.start_time:.1f}s")
        print(f"  * Số lượt còn lại trong ngày: {runner.quota_tracker.remaining_calls()} / {runner.daily_limit}")
        print(f"  * File CSV                  : {csv_p}")
        print(f"  * File Markdown             : {md_p}")
        if cs_p:
            print(f"  * Contact Sheet Image       : {cs_p}")
        print("#" * 80 + "\n")

    finally:
        db.close()


if __name__ == "__main__":
    main()
