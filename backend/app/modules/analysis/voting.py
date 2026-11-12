import math
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel

from backend.app.db.models import AnswerStatus, Comment
from backend.app.modules.analysis.parser import parse_comment_text


class VoterContribution(BaseModel):
    author_hash: str
    comment_id: Optional[str] = None
    answers: List[str] = []
    upvotes: int = 0
    weight: float = 0.0
    raw_text: str = ""
    is_agreement: bool = False
    quoted_comment_id: Optional[int] = None


class VotingResult(BaseModel):
    answer_set: List[str]
    status: AnswerStatus
    confidence: float
    total_weight: float
    vote_breakdown: Dict[str, float]
    voters_count: int
    is_multi_choice: bool = False
    contributions: List[VoterContribution] = []


def tally_votes(
    comments: List[Comment],
    ai_answer: Optional[List[str]] = None,
    ai_confidence: Optional[float] = None,
    ai_weight: float = 1.0,
    is_multi_override: Optional[bool] = None,
    ai_votes: Optional[List[Dict[str, Any]]] = None,
) -> VotingResult:
    """
    Tally votes from student comments and optional AI input.
    Supports single AI vote (ai_answer) or multi-provider ensemble (ai_votes).
    Rules:
      1. One author, one vote: Each author_hash gets at most 1 vote (newest comment with answer).
      2. Weight per comment: 1.0 + log2(1.0 + upvotes).
      3. Agreement comment (+1, chuẩn): half the weight of quoted parent comment.
      4. Single vs multiple choice: inferred from answers or override.
      5. Status: confident (>=70% and >=2 sources), conflict (top-2 diff < 15%), weak, no_data.
    """
    if not comments and not ai_answer and not ai_votes:
        return VotingResult(
            answer_set=["?"],
            status=AnswerStatus.NO_DATA,
            confidence=0.0,
            total_weight=0.0,
            vote_breakdown={},
            voters_count=0,
            is_multi_choice=False,
            contributions=[],
        )

    # 1. Map comments by ID for quote lookups
    comment_by_id: Dict[str, Comment] = {}
    for c in comments:
        if c.comment_id:
            comment_by_id[str(c.comment_id)] = c

    # 2. Group comments by author_hash and keep the newest valid comment per author
    # Order: assume comments passed in or sorted by ID/timestamp
    # Sort descending so first seen per author is newest
    sorted_comments = sorted(
        comments,
        key=lambda c: (c.id or 0),
        reverse=True,
    )

    seen_authors: Set[str] = set()
    contributions: List[VoterContribution] = []

    for c in sorted_comments:
        author = c.author_hash or "anonymous"
        if author in seen_authors:
            continue

        parsed = parse_comment_text(c.raw_text)

        # Skip ambiguous non-answers unless it's an agreement
        if parsed.is_ambiguous and not parsed.is_agreement:
            continue

        if parsed.is_agreement:
            # Agreement: gives half vote to quoted comment's answer
            parent_c = comment_by_id.get(str(c.quoted_comment_id)) if c.quoted_comment_id else None
            parent_parsed = parse_comment_text(parent_c.raw_text) if parent_c else None
            if parent_parsed and parent_parsed.answers:
                parent_weight = 1.0 + math.log2(1.0 + (parent_c.upvotes or 0))
                agree_weight = round(parent_weight * 0.5, 3)
                seen_authors.add(author)
                contributions.append(
                    VoterContribution(
                        author_hash=author,
                        comment_id=c.comment_id,
                        answers=parent_parsed.answers,
                        upvotes=c.upvotes or 0,
                        weight=agree_weight,
                        raw_text=c.raw_text,
                        is_agreement=True,
                        quoted_comment_id=c.quoted_comment_id,
                    )
                )
        elif parsed.answers:
            # Direct answer
            weight = round(1.0 + math.log2(1.0 + (c.upvotes or 0)), 3)
            seen_authors.add(author)
            contributions.append(
                VoterContribution(
                    author_hash=author,
                    comment_id=c.comment_id,
                    answers=parsed.answers,
                    upvotes=c.upvotes or 0,
                    weight=weight,
                    raw_text=c.raw_text,
                    is_agreement=False,
                )
            )

    # 3. Add AI contribution(s) if present
    if ai_votes:
        for idx, vote in enumerate(ai_votes):
            answers = vote.get("answers", [])
            provider_name = vote.get("provider", f"provider_{idx+1}")
            weight = vote.get("weight", ai_weight)
            if answers:
                contributions.append(
                    VoterContribution(
                        author_hash=f"ai_{provider_name}",
                        comment_id=f"ai_{provider_name}",
                        answers=[a.upper() for a in answers],
                        upvotes=0,
                        weight=round(weight, 3),
                        raw_text=f"AI Analysis ({provider_name})",
                        is_agreement=False,
                    )
                )
    elif ai_answer:
        contributions.append(
            VoterContribution(
                author_hash="ai_agent",
                comment_id="ai_vote",
                answers=[a.upper() for a in ai_answer],
                upvotes=0,
                weight=round(ai_weight, 3),
                raw_text="AI Analysis",
                is_agreement=False,
            )
        )

    if not contributions:
        return VotingResult(
            answer_set=["?"],
            status=AnswerStatus.NO_DATA,
            confidence=0.0,
            total_weight=0.0,
            vote_breakdown={},
            voters_count=0,
            is_multi_choice=False,
            contributions=[],
        )

    # 4. Check if multi-choice
    multi_voters = sum(1 for vc in contributions if len(vc.answers) > 1)
    if is_multi_override is not None:
        is_multi = is_multi_override
    else:
        is_multi = multi_voters > (len(contributions) / 2)

    # 5. Tally weights and distinct voters per option
    weights_per_option: Dict[str, float] = {}
    voters_per_option: Dict[str, Set[str]] = {}
    total_weight = 0.0

    for vc in contributions:
        total_weight += vc.weight
        for letter in vc.answers:
            opt = letter.upper()
            weights_per_option[opt] = weights_per_option.get(opt, 0.0) + vc.weight
            if opt not in voters_per_option:
                voters_per_option[opt] = set()
            voters_per_option[opt].add(vc.author_hash)

    # Round weights for display
    weights_per_option = {k: round(v, 3) for k, v in weights_per_option.items()}
    total_weight = round(total_weight, 3)

    sorted_options = sorted(weights_per_option.items(), key=lambda item: item[1], reverse=True)

    if not sorted_options:
        return VotingResult(
            answer_set=["?"],
            status=AnswerStatus.NO_DATA,
            confidence=0.0,
            total_weight=0.0,
            vote_breakdown={},
            voters_count=len(contributions),
            is_multi_choice=is_multi,
            contributions=contributions,
        )

    voters_count = len(contributions)

    # 6. Select winning answers
    if is_multi:
        # Multi-choice rule: every letter with >= 50% of total weight is chosen
        threshold = total_weight * 0.50
        winning_letters = [opt for opt, w in sorted_options if w >= threshold]
        if not winning_letters:
            winning_letters = sorted_options[0][0].split()
        answer_set = sorted(winning_letters)
        top_weight = sorted_options[0][1]
        confidence = round(top_weight / max(total_weight, 1.0), 3)
    else:
        # Single choice rule: highest weight letter wins
        best_letter = sorted_options[0][0]
        top_weight = sorted_options[0][1]
        answer_set = [best_letter]
        confidence = round(top_weight / max(total_weight, 1.0), 3)

    # 7. Determine status: CONFIDENT, CONFLICT, WEAK, NO_DATA
    conflict = False

    # Check top 2 options
    if len(sorted_options) >= 2:
        opt1 = sorted_options[0][0]
        opt2 = sorted_options[1][0]
        opt1_voters = len(voters_per_option.get(opt1, set()))
        opt2_voters = len(voters_per_option.get(opt2, set()))

        # Rule A: If top 2 options have equal number of independent voters -> CONFLICT regardless of reactions
        if opt1_voters == opt2_voters:
            conflict = True
        else:
            # Rule B: Margin between weights < 15%
            top1_w = sorted_options[0][1]
            top2_w = sorted_options[1][1]
            margin = (top1_w - top2_w) / max(total_weight, 1.0)
            if margin < 0.15:
                conflict = True

    # Check if AI disagreed with community consensus
    ai_contributions = [c for c in contributions if c.author_hash.startswith("ai_")]
    community_votes = [c for c in contributions if not c.author_hash.startswith("ai_")]
    if ai_contributions and community_votes:
        comm_weights: Dict[str, float] = {}
        for cv in community_votes:
            for l in cv.answers:
                comm_weights[l] = comm_weights.get(l, 0.0) + cv.weight
        if comm_weights:
            comm_winner = max(comm_weights.items(), key=lambda x: x[1])[0]
            for a_contrib in ai_contributions:
                if comm_winner not in [a.upper() for a in a_contrib.answers]:
                    conflict = True
                    break

    winner = answer_set[0]
    winner_independent_voters = len(voters_per_option.get(winner, set()))

    if conflict:
        status = AnswerStatus.CONFLICT
    elif confidence >= 0.70 and winner_independent_voters >= 2:
        status = AnswerStatus.CONFIDENT
    else:
        status = AnswerStatus.WEAK

    return VotingResult(
        answer_set=answer_set,
        status=status,
        confidence=confidence,
        total_weight=total_weight,
        vote_breakdown=weights_per_option,
        voters_count=voters_count,
        is_multi_choice=is_multi,
        contributions=contributions,
    )

