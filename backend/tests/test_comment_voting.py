import math
from pathlib import Path
import pytest

from backend.app.db.models import AnswerStatus, Comment
from backend.app.modules.analysis.parser import parse_comment_text
from backend.app.modules.analysis.voting import tally_votes

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TSV_PATH = BASE_DIR / "data" / "exports" / "comments_CSD202.tsv"


def test_parse_real_comments_from_tsv():
    """Verify that all real comments in comments_CSD202.tsv are parsed accurately."""
    assert TSV_PATH.exists(), f"TSV file not found: {TSV_PATH}"
    lines = TSV_PATH.read_text(encoding="utf-8").strip().split("\n")
    header = lines[0].split("\t")
    assert header == ["q_index", "comment_id", "author_hash", "reactions", "quoted_comment_id", "raw_text"]

    rows = lines[1:]
    assert len(rows) >= 60, f"Expected >= 60 comments, got {len(rows)}"

    parsed_count = 0
    for line in rows:
        parts = line.split("\t")
        raw_text = parts[5] if len(parts) > 5 else ""
        res = parse_comment_text(raw_text)
        assert res.answers or res.is_agreement, f"Failed to parse answer from: '{raw_text}'"
        parsed_count += 1

    assert parsed_count == len(rows)


def test_voting_on_real_q1_unanimous():
    """Q1 has two votes for A from two distinct authors."""
    c1 = Comment(id=1, question_id=1, comment_id="1238903", author_hash="e7a87b", raw_text="a", upvotes=0)
    c2 = Comment(id=2, question_id=1, comment_id="1262956", author_hash="777bfe", raw_text="Tính ổn định của thuật toán Merge Sort là gì? A", upvotes=0)

    result = tally_votes([c1, c2])
    assert result.answer_set == ["A"]
    assert result.status == AnswerStatus.CONFIDENT
    assert result.confidence == 1.0
    assert result.voters_count == 2
    assert result.total_weight == 2.0


def test_voting_on_real_q40_with_reactions():
    """Q40: author e7a87b voted 'a' with 2 reactions; author 3ca11d voted 'b' with 0 reactions.
    Since both options have 1 independent voter each, it is a CONFLICT (equal voter count).
    """
    c1 = Comment(id=51, question_id=40, comment_id="1238988", author_hash="e7a87b", raw_text="a", upvotes=2)
    c2 = Comment(id=52, question_id=40, comment_id="1276290", author_hash="3ca11d", raw_text="b", upvotes=0)

    result = tally_votes([c1, c2])
    # Weight of c1 = 1 + log2(1 + 2) = 2.585
    # Weight of c2 = 1 + log2(1 + 0) = 1.0
    # But voter count for A (1) == voter count for B (1) -> CONFLICT
    assert result.status == AnswerStatus.CONFLICT
    assert result.vote_breakdown["A"] > result.vote_breakdown["B"]


def test_one_author_one_vote_latest_wins():
    """If the same author posts multiple comments, only their latest comment is counted."""
    c_old = Comment(id=10, question_id=5, comment_id="100", author_hash="user_x", raw_text="a", upvotes=0)
    c_new = Comment(id=20, question_id=5, comment_id="200", author_hash="user_x", raw_text="b", upvotes=0)

    result = tally_votes([c_old, c_new])
    # Latest comment (id=20) is B
    assert result.answer_set == ["B"]
    assert result.voters_count == 1
    assert "A" not in result.vote_breakdown


def test_voting_agreement_inherits_half_parent_weight():
    """Agreement (+1, chuẩn) inherits half the weight of the quoted comment."""
    parent = Comment(id=1, question_id=2, comment_id="555", author_hash="author_orig", raw_text="đáp án C", upvotes=0)
    agree = Comment(id=2, question_id=2, comment_id="556", author_hash="author_agree", raw_text="+1 chuẩn luôn", quoted_comment_id=555, upvotes=0)

    result = tally_votes([parent, agree])
    assert result.answer_set == ["C"]
    assert result.voters_count == 2
    # Parent weight = 1.0, Agree weight = 0.5 -> Total = 1.5
    assert result.total_weight == 1.5
    assert result.vote_breakdown["C"] == 1.5


def test_voting_conflict_close_margin():
    """If top 2 answers have margin < 15%, mark as CONFLICT."""
    c1 = Comment(id=1, question_id=3, comment_id="1", author_hash="u1", raw_text="A", upvotes=0)
    c2 = Comment(id=2, question_id=3, comment_id="2", author_hash="u2", raw_text="B", upvotes=0)

    result = tally_votes([c1, c2])
    # 50% A vs 50% B -> margin 0% < 15% -> CONFLICT
    assert result.status == AnswerStatus.CONFLICT


def test_voting_multi_choice_threshold():
    """In multi-choice questions, letters with >= 50% total weight win."""
    c1 = Comment(id=1, question_id=4, comment_id="1", author_hash="u1", raw_text="A, C", upvotes=0)
    c2 = Comment(id=2, question_id=4, comment_id="2", author_hash="u2", raw_text="a và c", upvotes=0)
    c3 = Comment(id=3, question_id=4, comment_id="3", author_hash="u3", raw_text="C", upvotes=0)

    # 3 voters:
    # u1: A, C (w=1)
    # u2: A, C (w=1)
    # u3: C (w=1)
    # Total weight = 3.0
    # A has 2.0 (66.7% >= 50%), C has 3.0 (100% >= 50%)
    result = tally_votes([c1, c2, c3], is_multi_override=True)
    assert result.answer_set == ["A", "C"]
    assert result.is_multi_choice is True


def test_no_data_empty_comments():
    """If no comments and no AI, status is NO_DATA with '?' answer."""
    result = tally_votes([])
    assert result.answer_set == ["?"]
    assert result.status == AnswerStatus.NO_DATA
    assert result.confidence == 0.0


def test_ai_disagree_with_community_causes_conflict():
    """If AI disagrees with community majority, result follows ai_disagreement_policy."""
    c1 = Comment(id=1, question_id=1, comment_id="1", author_hash="u1", raw_text="A", upvotes=1)
    c2 = Comment(id=2, question_id=1, comment_id="2", author_hash="u2", raw_text="A", upvotes=0)

    # Policy 'flag' (default): status remains CONFIDENT, ai_disagreed is True
    res_flag = tally_votes([c1, c2], ai_answer=["B"], ai_disagreement_policy="flag")
    assert res_flag.status == AnswerStatus.CONFIDENT
    assert res_flag.ai_disagreed is True

    # Policy 'conflict': status becomes CONFLICT
    res_conflict = tally_votes([c1, c2], ai_answer=["B"], ai_disagreement_policy="conflict")
    assert res_conflict.status == AnswerStatus.CONFLICT
    assert res_conflict.ai_disagreed is True


def test_ai_supports_single_community_voter_makes_confident():
    """1 community voter + 1 AI voter for same answer = 2 independent sources >= 2 -> CONFIDENT."""
    c1 = Comment(id=1, question_id=1, comment_id="1", author_hash="u1", raw_text="A", upvotes=0)

    # Without AI: 1 voter -> WEAK
    res_no_ai = tally_votes([c1])
    assert res_no_ai.status == AnswerStatus.WEAK

    # With AI voting A: 2 voters -> CONFIDENT
    res_with_ai = tally_votes([c1], ai_answer=["A"])
    assert res_with_ai.status == AnswerStatus.CONFIDENT
    assert res_with_ai.answer_set == ["A"]


