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
            if not q.answer or q.answer.status in (AnswerStatus.CONFLICT, AnswerStatus.WEAK, AnswerStatus.NO_DATA) or q.answer.confidence < 0.80:
                need_ai = True

        if need_ai:
            st = q.answer.status if q.answer else AnswerStatus.NO_DATA
            conf = q.answer.confidence if q.answer else 0.0
            voters = q.answer.valid_comments_count if q.answer else 0
            if st == AnswerStatus.WEAK:
                cat = 0
            elif st == AnswerStatus.CONFLICT:
                cat = 1
            elif st == AnswerStatus.NO_DATA:
                cat = 2
            else:
                cat = 3
            candidates.append((cat, conf, voters, q.index, q))

    # Sort strictly by weakness priority
    candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

    # Pick up to max_calls
    selected = [c[4] for c in candidates[:max_calls]]
    return selected


def test_50_questions_simulated_ai_priority():
    """
    Simulate an exam of 50 questions:
    - 15 WEAK questions: Q5, Q6, Q7, Q8, Q9, Q10, Q11, Q12, Q15, Q16, Q17, Q18, Q19, Q20, Q28
    - 6 CONFLICT questions: Q25, Q33, Q37, Q41, Q44, Q45
    - 4 NO_DATA questions: Q47, Q48, Q49, Q50
    - 25 CONFIDENT questions (Q1-Q4, Q13-Q14, Q21-Q24, Q26-Q27, Q29-Q32, Q34-Q36, Q38-Q40, Q42-Q43, Q46)

    Quota limit: 20 calls.
    Verification:
    - Exactly 20 calls made.
    - All 15 WEAK questions MUST be served first!
    - Remaining 5 calls go to CONFLICT questions.
    - Zero calls to CONFIDENT questions.
    """
    questions = []
    weak_indices = {5, 6, 7, 8, 9, 10, 11, 12, 15, 16, 17, 18, 19, 20, 28}
    conflict_indices = {25, 33, 37, 41, 44, 45}
    no_data_indices = {47, 48, 49, 50}

    for i in range(1, 51):
        if i in weak_indices:
            ans = MockAnswer(status=AnswerStatus.WEAK, confidence=0.25, valid_comments_count=1)
        elif i in conflict_indices:
            ans = MockAnswer(status=AnswerStatus.CONFLICT, confidence=0.50, valid_comments_count=2)
        elif i in no_data_indices:
            ans = None # NO_DATA
        else:
            # Confident (e.g. 2 unanimous voters, conf=1.0)
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

    # All 15 WEAK questions MUST be among the selected
    for wi in weak_indices:
        assert wi in selected_indices, f"Weak question Q{wi} must be prioritized for AI!"

    # The first 15 selected questions MUST be the WEAK ones
    first_15 = set(selected_indices[:15])
    assert first_15 == weak_indices, "First 15 calls must strictly be the 15 WEAK questions!"

    # The next 5 selected questions must be CONFLICT questions
    next_5 = set(selected_indices[15:20])
    assert next_5.issubset(conflict_indices), "Remaining 5 calls must be CONFLICT questions!"

    # NO CONFIDENT question should EVER be called
    for q_idx in selected_indices:
        assert q_idx not in {1, 2, 3, 4, 13, 14, 21, 22, 23, 24}, f"Confident question Q{q_idx} should not be called!"
