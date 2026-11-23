import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel

from backend.app.db.models import AnswerStatus, Comment
from backend.app.modules.analysis.parser import (
    infer_multi_choice_n_from_comments,
    normalize_no_diacritics,
    normalize_vietnamese_text,
    parse_choice_hint,
    parse_comment_text,
)


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
    ai_disagreed: bool = False


def tally_votes(
    comments: List[Comment],
    ai_answer: Optional[List[str]] = None,
    ai_confidence: Optional[float] = None,
    ai_weight: float = 1.0,
    is_multi_override: Optional[bool] = None,
    ai_votes: Optional[List[Dict[str, Any]]] = None,
    ai_disagreement_policy: str = "flag",
    multi_choice_n: Optional[int] = None,
    max_option_letter: str = "E",
    choice_hint_text: Optional[str] = None,
) -> VotingResult:
    """
    Tally votes from student comments and optional AI input.
    Supports single AI vote (ai_answer) or multi-provider ensemble (ai_votes).
    multi_choice_n: When known (e.g. from choice hint '(Choose N answers)'),
    the top-N letters are selected. Status is CONFIDENT when top-N set accounts
    for >= 70% of total weight and (N+1)-th option is significantly lower (<= 40% of N-th).
    Ties within the top-N set are NOT a conflict.
    max_option_letter: Letters beyond this letter (default 'H') are discarded.
    """
    # Check if comments or AI votes reference option E or higher
    if max_option_letter < "E":
        has_e_or_higher = False
        if ai_votes:
            for v in ai_votes:
                if any(ans.upper() >= "E" for ans in v.get("answers", [])):
                    has_e_or_higher = True
                    break
        if not has_e_or_higher and comments:
            for c in comments:
                txt = getattr(c, "raw_text", "") or ""
                if re.search(r"(?:^|[\s,;+])([eE])(?:[\s,;+.:]|$)", txt):
                    if not re.search(r"\b[eE]\s+(?:nghĩ|thấy|chon|chọn|nhé|nha|ạ|ơi|ko|không)\b", txt, re.IGNORECASE):
                        has_e_or_higher = True
                        break
        if has_e_or_higher:
            max_option_letter = "E"
    if choice_hint_text:
        hint_multi, hint_n = parse_choice_hint(choice_hint_text)
        if is_multi_override is None:
            is_multi_override = hint_multi
        if multi_choice_n is None and hint_n is not None:
            multi_choice_n = hint_n

    if is_multi_override and multi_choice_n is None:
        inferred_n = infer_multi_choice_n_from_comments(comments, max_option_letter)
        if inferred_n:
            multi_choice_n = inferred_n
    elif is_multi_override is None and multi_choice_n is None:
        inferred_n = infer_multi_choice_n_from_comments(comments, max_option_letter)
        if inferred_n and inferred_n >= 2:
            is_multi_override = True
            multi_choice_n = inferred_n

    is_multi_choice = bool(is_multi_override or multi_choice_n)

    if not comments and not ai_answer and not ai_votes:
        return VotingResult(
            answer_set=["?"],
            status=AnswerStatus.NO_DATA,
            confidence=0.0,
            total_weight=0.0,
            vote_breakdown={},
            voters_count=0,
            is_multi_choice=is_multi_choice,
            contributions=[],
        )

    # 1. Map comments by ID for quote lookups
    comment_by_id: Dict[str, Comment] = {}
    for c in comments:
        if c.id:
            comment_by_id[str(c.id)] = c
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
    ambiguous_contributions: List[Tuple[str, str]] = []  # (author_hash, raw_text) for skipped ambiguous

    for c in sorted_comments:
        author = c.author_hash or "anonymous"
        if author in seen_authors:
            continue

        parsed = parse_comment_text(
            c.raw_text,
            max_option_letter=max_option_letter,
            multi_choice_n=multi_choice_n,
            is_multi_choice=is_multi_choice,
        )

        # Skip ambiguous non-answers unless it's an agreement
        if parsed.is_ambiguous and not parsed.is_agreement:
            ambiguous_contributions.append((author, c.raw_text))
            continue

        if parsed.is_agreement:
            # Agreement: gives half vote to quoted comment's answer
            parent_c = comment_by_id.get(str(c.quoted_comment_id)) if c.quoted_comment_id else None
            parent_parsed = parse_comment_text(
                parent_c.raw_text,
                max_option_letter=max_option_letter,
                multi_choice_n=multi_choice_n,
                is_multi_choice=is_multi_choice,
            ) if parent_c else None
            if parent_parsed and parent_parsed.answers:
                parent_upvotes = parent_c.upvotes or 0
                if parent_upvotes > 1000:
                    parent_upvotes = 0
                if parent_upvotes < 0:
                    agree_weight = 0.125
                else:
                    parent_weight = 1.0 + math.log2(1.0 + min(20, max(0, parent_upvotes)))
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
            raw_upvotes = c.upvotes or 0
            if raw_upvotes == 0 and c.raw_text:
                m_neg = re.search(r"\n\s*(-\d+)\s*\n", c.raw_text)
                if m_neg:
                    raw_upvotes = int(m_neg.group(1))

            # Treat abnormal upvotes > 1000 as 0
            if raw_upvotes > 1000:
                raw_upvotes = 0

            if raw_upvotes < 0:
                weight = 0.25
            else:
                upvote_val = min(20, max(0, raw_upvotes))
                weight = round(1.0 + math.log2(1.0 + upvote_val), 3)

            seen_authors.add(author)
            contributions.append(
                VoterContribution(
                    author_hash=author,
                    comment_id=c.comment_id,
                    answers=parsed.answers,
                    upvotes=raw_upvotes,
                    weight=weight,
                    raw_text=c.raw_text,
                    is_agreement=False,
                )
            )

    # 2b. Cross-comment keyword match for content-only (ambiguous) comments
    # If comment A = "Letter. Content" and comment B has no letter but content overlaps >= 50%,
    # count B as voting for the same Letter.
    if ambiguous_contributions:
        letter_content_index: List[Tuple[str, str]] = []  # (letter, normalized_content)
        for vc in contributions:
            if not vc.is_agreement and vc.answers and len(vc.answers) == 1:
                letter = vc.answers[0]
                m = re.match(r'^[A-Da-d][.:]\s+(.+)', vc.raw_text.strip())
                if m:
                    content_norm = normalize_no_diacritics(m.group(1).strip())
                    if content_norm:
                        letter_content_index.append((letter, content_norm))

        if letter_content_index:
            for amb_author, amb_raw_text in ambiguous_contributions:
                if amb_author in seen_authors:
                    continue
                amb_cleaned = normalize_vietnamese_text(amb_raw_text)
                if not amb_cleaned:
                    continue
                amb_norm = normalize_no_diacritics(amb_cleaned)
                amb_words = set(w for w in re.split(r'\W+', amb_norm) if len(w) >= 3)
                if not amb_words:
                    continue

                best_letter = None
                best_overlap = 0.0
                for letter, content_norm in letter_content_index:
                    content_words = set(w for w in re.split(r'\W+', content_norm) if len(w) >= 3)
                    if not content_words:
                        continue
                    intersection = amb_words & content_words
                    overlap = len(intersection) / max(1, min(len(amb_words), len(content_words)))
                    if content_norm in amb_norm or overlap >= 0.5:
                        if overlap > best_overlap or (best_letter is None and content_norm in amb_norm):
                            best_overlap = overlap
                            best_letter = letter

                if best_letter:
                    seen_authors.add(amb_author)
                    contributions.append(VoterContribution(
                        author_hash=amb_author,
                        comment_id=None,
                        answers=[best_letter],
                        upvotes=0,
                        weight=1.0,
                        raw_text=amb_raw_text,
                        is_agreement=False,
                    ))

    # 3. Add AI contribution(s) if present
    # Rule 1: AI weight is strictly less than minimum weight of a single community vote (0.125 for negative agreement, 0.25 for negative direct, 1.0 for normal)
    # When community comments exist, enforce that AI total effective weight cannot exceed 0.12 or overturn community.
    community_exists = len(contributions) > 0
    min_comm_weight = min((c.weight for c in contributions), default=1.0) if community_exists else 1.0
    safe_ai_weight = min(ai_weight, round(min_comm_weight * 0.5, 3)) if community_exists else ai_weight

    if ai_votes:
        for idx, vote in enumerate(ai_votes):
            answers = vote.get("answers", [])
            provider_name = vote.get("provider", f"provider_{idx+1}")
            conf = vote.get("confidence")
            base_w = vote.get("weight", safe_ai_weight)
            if community_exists:
                base_w = min(base_w, safe_ai_weight)
            effective_w = base_w * 0.5 if (conf is not None and conf < 0.6) else base_w
            if answers:
                contributions.append(
                    VoterContribution(
                        author_hash=f"ai_{provider_name}",
                        comment_id=f"ai_{provider_name}",
                        answers=[a.upper() for a in answers],
                        upvotes=0,
                        weight=round(effective_w, 3),
                        raw_text=f"AI Analysis ({provider_name})",
                        is_agreement=False,
                    )
                )
    elif ai_answer:
        base_w = safe_ai_weight
        effective_w = base_w * 0.5 if (ai_confidence is not None and ai_confidence < 0.6) else base_w
        contributions.append(
            VoterContribution(
                author_hash="ai_agent",
                comment_id="ai_vote",
                answers=[a.upper() for a in ai_answer],
                upvotes=0,
                weight=round(effective_w, 3),
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
        is_multi = (multi_voters > (len(contributions) / 2)) or (multi_choice_n is not None and multi_choice_n >= 2)

    if is_multi and multi_choice_n is None:
        lens = [len(vc.answers) for vc in contributions if len(vc.answers) >= 2]
        if lens:
            from collections import Counter
            counts = Counter(lens)
            mode_len, _ = counts.most_common(1)[0]
            if mode_len >= 2:
                multi_choice_n = mode_len

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

    sorted_options = sorted(weights_per_option.items(), key=lambda item: (-item[1], item[0]))

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
    conflict = False
    if is_multi:
        if multi_choice_n and multi_choice_n >= 2:
            n_target = min(multi_choice_n, len(sorted_options))
            top_n = sorted_options[:n_target]
            winning_letters = [opt for opt, w in top_n]
            answer_set = sorted(winning_letters)
            
            # Confidence for multi-choice: average share of top-N options relative to total weight
            top_n_weight = sum(w for opt, w in top_n)
            denom_n = total_weight * n_target
            confidence = round(top_n_weight / denom_n, 3) if denom_n > 0 else 0.0
            # Alternatively, ratio of top-N weight to total
            set_ratio = (top_n_weight / total_weight) if total_weight > 0 else 0.0
            
            # Check margin to (N+1)-th option
            next_opt = sorted_options[n_target] if len(sorted_options) > n_target else None
            nth_weight = top_n[-1][1]
            
            if next_opt and nth_weight > 0:
                next_ratio = next_opt[1] / nth_weight
                # If next option is close (> 40% of N-th option weight) -> ambiguous boundary
                if next_ratio > 0.40:
                    conflict = True
            elif set_ratio < 0.70:
                conflict = True
        else:
            # Multi-choice fallback: every letter with >= 50% of total weight is chosen
            threshold = total_weight * 0.50
            winning_letters = [opt for opt, w in sorted_options if w >= threshold]
            if not winning_letters:
                winning_letters = sorted_options[0][0].split()
            answer_set = sorted(winning_letters)
            top_weight = sorted_options[0][1]
            confidence = round(top_weight / total_weight, 3) if total_weight > 0 else 0.0
            
            # For multi-choice without known N, check margin to next unselected option
            if len(sorted_options) > len(winning_letters):
                unselected_top = sorted_options[len(winning_letters)][1]
                if (unselected_top / top_weight) > 0.40 if top_weight > 0 else False:
                    conflict = True
    else:
        # Single choice rule: highest weight letter wins
        best_letter = sorted_options[0][0]
        top_weight = sorted_options[0][1]
        answer_set = [best_letter]
        confidence = round(top_weight / total_weight, 3) if total_weight > 0 else 0.0

        # Check top 2 options for single choice
        if len(sorted_options) >= 2:
            opt1 = sorted_options[0][0]
            opt2 = sorted_options[1][0]
            # Use human voters count for community conflict check
            comm_opt1_voters = len(set(c.author_hash for c in contributions if not c.author_hash.startswith("ai_") and opt1 in [a.upper() for a in c.answers]))
            comm_opt2_voters = len(set(c.author_hash for c in contributions if not c.author_hash.startswith("ai_") and opt2 in [a.upper() for a in c.answers]))

            opt1_voters = len(voters_per_option.get(opt1, set()))
            opt2_voters = len(voters_per_option.get(opt2, set()))

            # Rule A: If top 2 options have equal number of independent community voters -> CONFLICT
            # AI cannot break equal human community ties
            if comm_opt1_voters > 0 and comm_opt1_voters == comm_opt2_voters:
                conflict = True
            elif opt1_voters == opt2_voters:
                if sorted_options[1][1] > 0.35 * sorted_options[0][1]:
                    conflict = True
            else:
                # Rule B: Margin between weights < 15%
                top1_w = sorted_options[0][1]
                top2_w = sorted_options[1][1]
                margin = (top1_w - top2_w) / total_weight if total_weight > 0 else 0.0
                if margin < 0.15:
                    conflict = True

    # Check if AI disagreed with community consensus
    ai_contributions = [c for c in contributions if c.author_hash.startswith("ai_")]
    community_votes = [c for c in contributions if not c.author_hash.startswith("ai_")]
    ai_disagreed = False
    if ai_contributions and community_votes:
        comm_weights: Dict[str, float] = {}
        for cv in community_votes:
            for l in cv.answers:
                comm_weights[l] = comm_weights.get(l, 0.0) + cv.weight
        if comm_weights:
            comm_winner = max(comm_weights.items(), key=lambda x: x[1])[0]
            for a_contrib in ai_contributions:
                if comm_winner not in [a.upper() for a in a_contrib.answers]:
                    ai_disagreed = True
                    if ai_disagreement_policy == "conflict":
                        conflict = True
                    break

    # Rule 1.c: When unweighted majority of independent human commenters AND AI both oppose a high-weight vote:
    # Flag CONFLICT and set the answer according to the majority, not the single high-weight vote.
    comm_voters_per_opt: Dict[str, Set[str]] = {}
    for cv in community_votes:
        for l in cv.answers:
            opt = l.upper()
            if opt not in comm_voters_per_opt:
                comm_voters_per_opt[opt] = set()
            comm_voters_per_opt[opt].add(cv.author_hash)

    ai_chosen_opts: Set[str] = set()
    for ac in ai_contributions:
        ai_chosen_opts.update(a.upper() for a in ac.answers)

    if answer_set and ai_chosen_opts and comm_voters_per_opt:
        current_winner = answer_set[0]
        curr_voters_cnt = len(comm_voters_per_opt.get(current_winner, set()))
        best_alt = None
        best_alt_voters = curr_voters_cnt
        for alt_opt, voters_set in comm_voters_per_opt.items():
            if alt_opt != current_winner and alt_opt in ai_chosen_opts and current_winner not in ai_chosen_opts:
                if len(voters_set) > best_alt_voters:
                    best_alt = alt_opt
                    best_alt_voters = len(voters_set)
                elif len(voters_set) == best_alt_voters and best_alt is not None:
                    if weights_per_option.get(alt_opt, 0.0) > weights_per_option.get(best_alt, 0.0):
                        best_alt = alt_opt

        if best_alt:
            conflict = True
            answer_set = [best_alt]
            confidence = round(weights_per_option.get(best_alt, 0.0) / total_weight, 3) if total_weight > 0 else 0.0
            ai_disagreed = False

    # Rule: Negative-weight votes should not suppress real conflicts.
    # If removing negative-weight contributions would change the winner or cause a conflict, re-flag.
    # Note: For multi-choice questions (is_multi=True), ties among winning options in the top-N set
    # are completely expected and are NOT a conflict.
    neg_weight_contributions = [vc for vc in contributions if vc.upvotes < 0 and not vc.author_hash.startswith("ai_")]
    if neg_weight_contributions and not conflict and not is_multi:
        pos_contributions = [vc for vc in contributions if vc.upvotes >= 0 or vc.author_hash.startswith("ai_")]
        if pos_contributions:
            pos_weights: Dict[str, float] = {}
            pos_voters: Dict[str, Set[str]] = {}
            for vc in pos_contributions:
                for letter in vc.answers:
                    opt = letter.upper()
                    pos_weights[opt] = pos_weights.get(opt, 0.0) + vc.weight
                    if opt not in pos_voters:
                        pos_voters[opt] = set()
                    pos_voters[opt].add(vc.author_hash)
            if len(pos_weights) >= 2:
                pos_sorted = sorted(pos_weights.items(), key=lambda x: (-x[1], x[0]))
                pos_winner = pos_sorted[0][0]
                if pos_winner != answer_set[0]:
                    conflict = True
                else:
                    pos_opt1 = pos_sorted[0]
                    pos_opt2 = pos_sorted[1]
                    pos_v1 = len(pos_voters.get(pos_opt1[0], set()))
                    pos_v2 = len(pos_voters.get(pos_opt2[0], set()))
                    pos_total = sum(v for _, v in pos_sorted)
                    if pos_v1 == pos_v2:
                        if pos_opt2[1] > 0.35 * pos_opt1[1]:
                            conflict = True
                    else:
                        pos_margin = (pos_opt1[1] - pos_opt2[1]) / max(pos_total, 1.0)
                        if pos_margin < 0.15:
                            conflict = True

    winner = answer_set[0]
    # Human independent voters count for the winner (excluding AI)
    human_voters_per_opt: Dict[str, Set[str]] = {}
    for vc in contributions:
        if not vc.author_hash.startswith("ai_"):
            for letter in vc.answers:
                opt = letter.upper()
                if opt not in human_voters_per_opt:
                    human_voters_per_opt[opt] = set()
                human_voters_per_opt[opt].add(vc.author_hash)

    winner_human_voters = len(human_voters_per_opt.get(winner, set()))

    # AI can only decide answer when there are NO community votes (NO_DATA), and in that case status is ALWAYS WEAK
    if not community_exists:
        status = AnswerStatus.WEAK
    elif conflict:
        status = AnswerStatus.CONFLICT
    elif confidence >= 0.70 and winner_human_voters >= 2:
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
        ai_disagreed=ai_disagreed,
    )

