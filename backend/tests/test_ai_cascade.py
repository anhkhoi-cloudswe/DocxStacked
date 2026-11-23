"""
Section C: AI Cascade Decision Table Tests
Tests every row of the cascade matrix from prompt v0.5 Section C.

Row | Community votes | AI called? | AI result    | Final status
----|----------------|------------|--------------|-------------------
1   | >= 2 agree (C)  | No         | -            | CONFIDENT (community)
2   | 1 voter, WEAK   | Yes        | AI agrees    | CONFIDENT
3   | 1 voter, WEAK   | Yes        | AI disagrees | CONFLICT
4   | 0 voters        | Yes        | AI answers   | CONFIDENT (AI)
5   | Conflict (tie)  | Yes        | AI breaks tie| CONFIDENT (AI)
6   | Conflict (tie)  | Yes        | AI agrees w/ neither | CONFLICT (3-way)
"""
import math
from unittest.mock import MagicMock

import pytest

from backend.app.db.models import AnswerStatus, Comment
from backend.app.modules.analysis.voting import tally_votes


def _make_comment(author: str, text: str, upvotes: int = 0, comment_id: str = None) -> Comment:
    """Build a minimal Comment object for voting tests."""
    c = Comment()
    c.author_hash = author
    c.raw_text = text
    c.upvotes = upvotes
    c.comment_id = comment_id or author
    c.id = hash(author + text) % 100000
    c.quoted_comment_id = None
    return c


# ---------------------------------------------------------------------------
# Row 1: >= 2 community voters agree → CONFIDENT, no AI needed
# ---------------------------------------------------------------------------

def test_cascade_row1_two_community_agree_no_ai():
    """2+ independent community voters agree → CONFIDENT, AI must not be called."""
    comments = [
        _make_comment("user_1", "B"),
        _make_comment("user_2", "B"),
    ]
    result = tally_votes(comments, ai_answer=None, ai_votes=None)
    assert result.status == AnswerStatus.CONFIDENT
    assert result.answer_set == ["B"]
    assert not result.ai_disagreed


def test_cascade_row1_three_community_agree():
    """3 independent voters agree → CONFIDENT."""
    comments = [
        _make_comment("user_1", "A"),
        _make_comment("user_2", "A"),
        _make_comment("user_3", "A"),
    ]
    result = tally_votes(comments)
    assert result.status == AnswerStatus.CONFIDENT
    assert result.answer_set == ["A"]


# ---------------------------------------------------------------------------
# Row 2: 1 voter (WEAK) + AI agrees → CONFIDENT
# ---------------------------------------------------------------------------

def test_cascade_row2_one_community_ai_agrees():
    """Rule 1: 1 community voter (WEAK alone) + AI agrees → increases confidence but remains WEAK (needs 2 real humans)."""
    comments = [_make_comment("user_1", "C")]
    ai_votes = [{"provider": "gemini", "answers": ["C"], "confidence": 0.95}]
    result = tally_votes(comments, ai_votes=ai_votes, ai_weight=1.0)
    assert result.status == AnswerStatus.WEAK
    assert result.answer_set == ["C"]
    assert not result.ai_disagreed


# ---------------------------------------------------------------------------
# Row 3: 1 voter + AI disagrees → CONFLICT
# ---------------------------------------------------------------------------

def test_cascade_row3_one_community_ai_disagrees():
    """1 community voter for B + AI says D → CONFLICT (ai_disagreement_policy=conflict)."""
    comments = [_make_comment("user_1", "B")]
    ai_votes = [{"provider": "anthropic", "answers": ["D"], "confidence": 0.90}]
    result = tally_votes(
        comments,
        ai_votes=ai_votes,
        ai_weight=1.0,
        ai_disagreement_policy="conflict",
    )
    assert result.status == AnswerStatus.CONFLICT
    assert result.ai_disagreed


# ---------------------------------------------------------------------------
# Row 4: 0 community votes, AI answers → WEAK (AI-only is always WEAK)
# ---------------------------------------------------------------------------

def test_cascade_row4_no_community_ai_answers():
    """
    Rule 1: No community votes + AI answers.
    AI-only decision is ALWAYS WEAK.
    """
    # Single AI: → WEAK
    ai_votes = [{"provider": "gemini", "answers": ["E"], "confidence": 0.92}]
    result = tally_votes([], ai_votes=ai_votes, ai_weight=1.5)
    assert result.status == AnswerStatus.WEAK
    assert result.answer_set == ["E"]

    # Two AI providers agree → still WEAK because 0 real human voters
    ai_votes_ensemble = [
        {"provider": "gemini", "answers": ["E"], "confidence": 0.92},
        {"provider": "anthropic", "answers": ["E"], "confidence": 0.90},
    ]
    result2 = tally_votes([], ai_votes=ai_votes_ensemble, ai_weight=1.5)
    assert result2.status == AnswerStatus.WEAK
    assert result2.answer_set == ["E"]


def test_cascade_row4_no_community_no_ai():
    """No votes at all → NO_DATA."""
    result = tally_votes([])
    assert result.status == AnswerStatus.NO_DATA
    assert result.answer_set == ["?"]


# ---------------------------------------------------------------------------
# Row 5: Community tie (CONFLICT) + AI
# ---------------------------------------------------------------------------

def test_cascade_row5_conflict_ai_cannot_override_tie():
    """
    Rule 1: Equal community split (A vs B) + AI picks A.
    AI cannot break tie to make it confident or change community equality: remains CONFLICT or WEAK.
    """
    comments = [
        _make_comment("user_1", "A"),
        _make_comment("user_2", "B"),
    ]
    ai_votes = [{"provider": "gemini", "answers": ["A"], "confidence": 0.88}]
    result = tally_votes(
        comments,
        ai_votes=ai_votes,
        ai_weight=1.5,
        ai_disagreement_policy="flag",
    )
    # Both A and B have 1 community voter; margin is small -> CONFLICT
    assert result.status == AnswerStatus.CONFLICT


# ---------------------------------------------------------------------------
# Row 6: Community tie + AI picks a 3rd option → still CONFLICT
# ---------------------------------------------------------------------------

def test_cascade_row6_conflict_ai_adds_third_option():
    """Equal split A vs B + AI picks C (3-way) → CONFLICT."""
    comments = [
        _make_comment("user_1", "A"),
        _make_comment("user_2", "B"),
    ]
    ai_votes = [{"provider": "anthropic", "answers": ["C"], "confidence": 0.85}]
    result = tally_votes(
        comments,
        ai_votes=ai_votes,
        ai_weight=1.0,
        ai_disagreement_policy="conflict",
    )
    # A=1.0, B=1.0, C=1.0 → three-way tie → CONFLICT
    assert result.status == AnswerStatus.CONFLICT


# ---------------------------------------------------------------------------
# Multi-choice cascade: multi_choice_n=2, community provides 2 picks
# ---------------------------------------------------------------------------

def test_cascade_multi_choice_n2_community_agree():
    """Multi-choice N=2: two voters both pick A,C → CONFIDENT multi."""
    comments = [
        _make_comment("user_1", "A, C"),
        _make_comment("user_2", "A, C"),
    ]
    result = tally_votes(comments, multi_choice_n=2)
    assert result.status == AnswerStatus.CONFIDENT
    assert sorted(result.answer_set) == ["A", "C"]
    assert result.is_multi_choice


def test_cascade_multi_choice_ai_fills_missing():
    """
    Multi-choice N=2: 0 community votes.
    Rule 1: AI only is always WEAK.
    """
    # Single AI provider → WEAK (1 source)
    ai_votes = [{"provider": "gemini", "answers": ["B", "E"], "confidence": 0.91}]
    result = tally_votes([], ai_votes=ai_votes, multi_choice_n=2)
    assert result.status == AnswerStatus.WEAK
    assert sorted(result.answer_set) == ["B", "E"]

    # Two AI providers both agree → still WEAK because 0 real human voters
    ai_votes_ensemble = [
        {"provider": "gemini", "answers": ["B", "E"], "confidence": 0.91},
        {"provider": "anthropic", "answers": ["B", "E"], "confidence": 0.89},
    ]
    result2 = tally_votes([], ai_votes=ai_votes_ensemble, multi_choice_n=2)
    assert result2.status == AnswerStatus.WEAK
    assert sorted(result2.answer_set) == ["B", "E"]


# ---------------------------------------------------------------------------
# Edge case: community WEAK (single voter, low confidence) with no AI
# ---------------------------------------------------------------------------

def test_cascade_single_community_no_ai_weak():
    """Single community voter without AI → WEAK (not CONFIDENT, not CONFLICT)."""
    comments = [_make_comment("user_1", "D")]
    result = tally_votes(comments, ai_answer=None, ai_votes=None)
    # 1 voter, weight=1.0, confidence=1.0 but only 1 independent voter → WEAK
    assert result.status == AnswerStatus.WEAK
    assert result.answer_set == ["D"]
