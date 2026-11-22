"""
test_ai_uncertainty_priority.py
Verifies that AI calls are prioritized strictly by uncertainty:
1. WEAK questions are selected FIRST (sorted by lowest confidence & fewest voters).
2. CONFLICT questions are selected NEXT.
3. NO_DATA questions are selected AFTER that.
4. CONFIDENT questions (e.g. unanimous voters) are NEVER called in only_uncertain mode.
5. When quota limit is reached (e.g. 20 calls), weakest questions are guaranteed to be served.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import pytest
from backend.app.db.models import AnswerStatus


@dataclass
class MockAnswer:
    status: AnswerStatus
    confidence: float
    valid_comments_count: int
    answer_set: List[str] = field(default_factory=lambda: ["A"])


@dataclass
class MockQuestion:
    id: int
    index: int
    answer: Optional[MockAnswer] = None
    crop_warnings: List[str] = field(default_factory=list)
    local_image_path: str = "q.webp"


def select_questions_for_ai(questions: List[MockQuestion], max_calls: int = 20, ai_mode: str = "only_uncertain") -> List[MockQuestion]:
    """
    Implements the exact prioritization algorithm from _run_background_ai_refinement:
    WEAK (cat=0) -> CONFLICT (cat=1) -> NO_DATA (cat=2) -> OTHER (cat=3).
    Within each category, sorted by lowest confidence, fewest voters, then question index.
    """
    candidates = []
    for q in questions:
        has_missing_options = "missing_options" in (q.crop_warnings or [])
        if has_missing_options:
            continue

        need_ai = False
        if ai_mode == "all":
            need_ai = True
        elif ai_mode == "off":
            need_ai = False
        else: # only_uncertain
            # Questions already CONFIDENT by comments (without AI) must NEVER be included
            if not q.answer or q.answer.status in (AnswerStatus.CONFLICT, AnswerStatus.WEAK, AnswerStatus.NO_DATA):
                need_ai = True
            elif q.answer.status == AnswerStatus.CONFIDENT:
                need_ai = False

        if need_ai:
            st = q.answer.status if q.answer else AnswerStatus.NO_DATA
            conf = q.answer.confidence if q.answer else 0.0
            voters = q.answer.valid_comments_count if q.answer else 0
            if st == AnswerStatus.WEAK:
                cat = 0
            elif st == AnswerStatus.CONFLICT:
                cat = 1
            else:
                cat = 2
            candidates.append((cat, conf, voters, q.index, q))

    # Sort strictly by weakness priority: WEAK (cat=0) -> CONFLICT (cat=1) -> NO_DATA (cat=2)
    candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

    # Pick up to max_calls
    selected = [c[4] for c in candidates[:max_calls]]
    return selected


def test_50_questions_simulated_ai_priority():
    """
    Simulate an exam of 50 questions reflecting B5 structure:
    - 19 WEAK questions (including Q45, Q49 with conf 0.25)
    - 1 CONFLICT question (Q33)
    - CONFIDENT questions (including Q25, Q37 with 2 independent commenters each)

    Quota limit: 20 calls.
    Verification:
    - Exactly 20 calls made.
    - All 19 WEAK questions MUST be served first (including Q45 and Q49)!
    - 1 call goes to CONFLICT question (Q33).
    - Q25 and Q37 (CONFIDENT) NEVER enter candidates.
    """
    questions = []
    weak_indices = {5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 17, 18, 19, 20, 28, 41, 44, 45, 49}
    conflict_indices = {33}
    confident_indices = {i for i in range(1, 51)} - weak_indices - conflict_indices

    for i in range(1, 51):
        if i in weak_indices:
            conf_val = 0.25 if i in (28, 49) else 1.0
            ans = MockAnswer(status=AnswerStatus.WEAK, confidence=conf_val, valid_comments_count=1)
        elif i in conflict_indices:
            ans = MockAnswer(status=AnswerStatus.CONFLICT, confidence=1.0, valid_comments_count=2)
        else:
            # Confident by comments (e.g. Q25, Q37 with 2 unanimous voters, conf=1.0)
            ans = MockAnswer(status=AnswerStatus.CONFIDENT, confidence=1.0, valid_comments_count=2)

        questions.append(MockQuestion(id=i, index=i, answer=ans))

    max_calls = 20
    selected = select_questions_for_ai(questions, max_calls=max_calls)

    print(f"\n[Test Output] Total questions: {len(questions)}")
    print(f"[Test Output] AI Quota Limit: {max_calls} calls")
    print(f"[Test Output] Questions selected for AI ({len(selected)} questions):")
    selected_indices = [q.index for q in selected]
    print("  " + ", ".join(f"Q{q:02d}" for q in selected_indices))

    # Assertions
    assert len(selected) == 20

    # Q45 and Q49 MUST be among selected
    assert 45 in selected_indices, "Weak question Q45 must be prioritized for AI!"
    assert 49 in selected_indices, "Weak question Q49 must be prioritized for AI!"

    # Q25 and Q37 MUST NEVER be selected
    assert 25 not in selected_indices, "Confident question Q25 must NEVER be selected for AI!"
    assert 37 not in selected_indices, "Confident question Q37 must NEVER be selected for AI!"

    # All 19 WEAK questions MUST be the first 19
    first_19 = set(selected_indices[:19])
    assert first_19 == weak_indices, "First 19 calls must strictly be the 19 WEAK questions!"

    # The 20th question must be CONFLICT (Q33)
    assert selected_indices[19] == 33


def test_real_b5_ai_selection():
    """
    Test using real B5 comments from docxstacked.db (Exam 195):
    - Without AI, tallies real comments for each question.
    - Confirms Q25 and Q37 are CONFIDENT (voters=2) and NOT selected.
    - Confirms Q45 and Q49 are WEAK (voters=1) and ARE selected.
    """
    import sqlite3
    from backend.app.db.models import Comment
    from backend.app.modules.analysis.voting import tally_votes
    from pathlib import Path

    db_path = Path(__file__).resolve().parent.parent.parent / "data" / "docxstacked.db"
    if not db_path.exists():
        pytest.skip("docxstacked.db not available")

    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute('SELECT id, "index" FROM questions WHERE exam_id = 195 ORDER BY "index"')
    q_rows = c.fetchall()
    if len(q_rows) < 50:
        pytest.skip("Exam 195 not in database")

    mock_questions = []
    for qid, qidx in q_rows:
        c.execute('SELECT id, comment_id, author_hash, raw_text, upvotes, quoted_comment_id, is_reply FROM comments WHERE question_id = ?', (qid,))
        c_rows = c.fetchall()
        comments = [
            Comment(
                id=r[0],
                comment_id=r[1],
                author_hash=r[2],
                raw_text=r[3],
                upvotes=r[4],
                quoted_comment_id=r[5],
                is_reply=bool(r[6]),
            )
            for r in c_rows
        ]
        vr = tally_votes(comments)
        ans = MockAnswer(
            status=vr.status,
            confidence=vr.confidence,
            valid_comments_count=vr.voters_count,
            answer_set=vr.answer_set,
        )
        mock_questions.append(MockQuestion(id=qid, index=qidx, answer=ans))

    selected = select_questions_for_ai(mock_questions, max_calls=20)
    selected_indices = [q.index for q in selected]

    print("\n[Real B5 Test] Top 20 selected questions for AI:")
    print("  " + ", ".join(f"Q{q:02d}" for q in selected_indices))

    # Assertions for B5
    assert 25 not in selected_indices, "B5 Q25 is CONFIDENT from comments alone and must NOT be selected"
    assert 37 not in selected_indices, "B5 Q37 is CONFIDENT from comments alone and must NOT be selected"
    assert 45 in selected_indices, "B5 Q45 is WEAK and MUST be selected"
    assert 49 in selected_indices, "B5 Q49 is WEAK and MUST be selected"
    assert len(selected) in (19, 20)
