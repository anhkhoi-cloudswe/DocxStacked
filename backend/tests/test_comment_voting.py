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


def test_ai_supports_single_community_voter_keeps_weak_rule1():
    """Rule 1: 1 community voter + 1 AI voter for same answer keeps answer but does NOT make CONFIDENT without 2 real humans."""
    c1 = Comment(id=1, question_id=1, comment_id="1", author_hash="u1", raw_text="A", upvotes=0)

    # Without AI: 1 voter -> WEAK
    res_no_ai = tally_votes([c1])
    assert res_no_ai.status == AnswerStatus.WEAK

    # With AI voting A: only 1 real human voter -> remains WEAK
    res_with_ai = tally_votes([c1], ai_answer=["A"])
    assert res_with_ai.status == AnswerStatus.WEAK
    assert res_with_ai.answer_set == ["A"]


def test_negative_reaction_score_downweighted():
    """Comments with negative reactions (e.g. -3) are downweighted to 0.25."""
    c_good1 = Comment(id=1, question_id=1, comment_id="c1", author_hash="user1", raw_text="D", upvotes=0)
    c_good2 = Comment(id=2, question_id=1, comment_id="c2", author_hash="user2", raw_text="D", upvotes=0)
    c_troll = Comment(id=3, question_id=1, comment_id="c3", author_hash="user3", raw_text="C", upvotes=-3)

    result = tally_votes([c_good1, c_good2, c_troll])
    assert result.answer_set == ["D"]
    assert result.status == AnswerStatus.CONFIDENT
    # Check that troll weight is 0.25
    troll_contrib = next(cb for cb in result.contributions if cb.author_hash == "user3")
    assert troll_contrib.weight == 0.25
    good_contrib = next(cb for cb in result.contributions if cb.author_hash == "user1")
    assert good_contrib.weight == 1.0


def test_reject_invalid_letter_h_default_abcd():
    """Answer letter is strictly bounded to choice alphabet [A-D]; 'H' is discarded."""
    c1 = Comment(id=1, question_id=1, comment_id="c1", author_hash="user1", raw_text="d", upvotes=0)
    c2 = Comment(id=2, question_id=1, comment_id="c2", author_hash="user2", raw_text="H", upvotes=0)

    result = tally_votes([c1, c2])
    assert result.answer_set == ["D"]
    assert "H" not in result.vote_breakdown


def test_b5_q25_keyword_match_content_comment():
    """B5 Q25: 'ModelStateDictionary lưu trạng...' (no letter) + 'B. ModelStateDictionary.'
    → keyword match makes first comment vote for B → 2 independent voters → CONFIDENT."""
    c1 = Comment(id=1, question_id=25, comment_id="1279307", author_hash="5170bf",
                 raw_text="ModelStateDictionary lưu trạng thái binding và các lỗi validation của model.", upvotes=0)
    c2 = Comment(id=2, question_id=25, comment_id="1280464", author_hash="850d93",
                 raw_text="B. ModelStateDictionary.", upvotes=0)
    result = tally_votes([c1, c2])
    assert result.answer_set == ["B"]
    assert result.status == AnswerStatus.CONFIDENT
    assert result.voters_count == 2


def test_prn232_sp26_fe_q11_and_q29_weight_cap_and_majority_conflict():
    """PRN232 SP26 FE:
    Q11: author cuongdz had upvotes=112 (weight 7.82 capped to 5.392) voting A.
         3 independent commenters (giakhanh123, TC2003, AnhTommy) and AI vote D.
         Expected outcome: answer D, status CONFLICT.
    Q29: author cuongdz had upvotes=90504 (abnormal > 1000 reset to 0, or capped) voting B.
         4 independent commenters (TC2003, Hoang Hai Quan, Gia Huy, AnhTommy) and AI vote C.
         Expected outcome: answer C.
    """
    # Q11 test with real comments + AI
    q11_comments = [
        Comment(id=1, comment_id="1147800", author_hash="cuongdz", raw_text="a", upvotes=112),
        Comment(id=2, comment_id="1151922", author_hash="giakhanh123", raw_text="câu này d nhé cường dz", upvotes=0),
        Comment(id=3, comment_id="1186424", author_hash="TC2003", raw_text="d", upvotes=0),
        Comment(id=4, comment_id="1227674", author_hash="AnhTommy", raw_text="D", upvotes=0),
    ]
    ai_q11 = [{"provider": "gemini", "answers": ["D"], "confidence": 1.0}]
    res_q11 = tally_votes(q11_comments, ai_votes=ai_q11)
    assert res_q11.answer_set == ["D"], f"Expected D, got {res_q11.answer_set}"
    assert res_q11.status == AnswerStatus.CONFLICT, f"Expected CONFLICT, got {res_q11.status}"

    # Q29 test with real comments + AI
    q29_comments = [
        Comment(id=10, comment_id="1147828", author_hash="cuongdz", raw_text="b", upvotes=90504),
        Comment(id=11, comment_id="1187037", author_hash="TC2003", raw_text="c", upvotes=0),
        Comment(id=12, comment_id="1200029", author_hash="Hoang Hai Quan DE180071", raw_text="C", upvotes=0),
        Comment(id=13, comment_id="1203328", author_hash="Gia Huy", raw_text="c", upvotes=0),
        Comment(id=14, comment_id="1227907", author_hash="AnhTommy", raw_text="C", upvotes=0),
    ]
    ai_q29 = [{"provider": "gemini", "answers": ["C"], "confidence": 0.98}]
    res_q29 = tally_votes(q29_comments, ai_votes=ai_q29)
    assert res_q29.answer_set == ["C"], f"Expected C, got {res_q29.answer_set}"


def test_filler_particles_and_ite302c_su25_re_q47():
    """
    Test leading letter with filler particles: 'b chứ', 'b mà?', 'a nhé', 'c đó'.
    Test that dilemma 'a hay b' is ambiguous / not counted.
    Test real comments of ITE302c - SU25 - RE Q47:
      - 9 voters for B ('b chứ', 'b mà?', 'b', 'B', ...)
      - 6 voters for A
      - Ondelay10 initially voted A, but changed mind to B -> only latest vote B counts.
      - namcoiy2 voted 'a hay b' -> not counted.
      - Expected outcome: B wins with 9 voters vs A with 6 voters.
    """
    from backend.app.modules.crawler.comments import parse_comments_from_html
    from pathlib import Path

    fixture_path = Path("data/raw/ITE302C/exam_119_SU25/comments/q047_109917.html")
    assert fixture_path.exists(), "q047_109917.html must exist"

    raw_html = fixture_path.read_text(encoding="utf-8")
    parsed = parse_comments_from_html(raw_html, question_id=547)

    # Convert to VoteComment with sequential ids reflecting order
    vote_comms = [
        Comment(
            id=i + 1,
            comment_id=c.comment_id,
            author_hash=c.author_hash,
            raw_text=c.raw_text,
            upvotes=c.upvotes or 0,
        )
        for i, c in enumerate(parsed)
    ]

    res = tally_votes(vote_comms)
    assert res.answer_set == ["B"]
    assert res.voters_count == 15

    a_voters = [c for c in res.contributions if "A" in c.answers]
    b_voters = [c for c in res.contributions if "B" in c.answers]

    assert len(a_voters) == 6, f"Expected 6 voters for A, got {len(a_voters)}"
    assert len(b_voters) == 9, f"Expected 9 voters for B, got {len(b_voters)}"

    # Ondelay10 must only vote B
    ondelay_contrib = [c for c in res.contributions if c.author_hash == "f3c2fdd85b39c3e1"]
    assert len(ondelay_contrib) == 1
    assert ondelay_contrib[0].answers == ["B"]




