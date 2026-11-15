"""
Test suite using Mock Vision Providers (0 API cost) verifying:
1. HTTP 429 rate limit retry with exponential backoff, jitter, and Retry-After parsing.
2. Call timeout (60s limit).
3. Malformed JSON handling & self-correction retry.
4. Answer letters outside options (e.g. outside A-D).
5. Multiple-choice questions (Choose N).
6. Decision Matrix confirmation:
   - AI is exactly 1 vote.
   - Weight is 1.0 when confidence >= 0.6, 0.5 when confidence < 0.6.
   - AI alone NEVER produces CONFIDENT status (always WEAK or NO_DATA).
"""

import json
from pathlib import Path
import time
from typing import Optional
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest

from backend.app.db.models import AnswerStatus, Comment
from backend.app.modules.analysis.ai_check import AICheckService, AIQuestionAnalysis
from backend.app.modules.analysis.gemini_guard import (
    AIRateLimiter,
    DailyQuotaExhaustedError,
    DailyQuotaTracker,
    execute_with_timeout,
    parse_retry_after,
)
from backend.app.modules.analysis.providers import (
    VisionProvider,
    ProviderRateLimitError,
    ProviderNetworkError,
    ProviderAPIError,
)
from backend.app.modules.analysis.voting import tally_votes


class MockVisionProvider(VisionProvider):
    """Custom mock provider for deterministic fault injection."""

    def __init__(
        self,
        name: str = "mock_provider",
        model: str = "mock-vision-v1",
        api_key_env: str = "MOCK_KEY",
        max_retries: int = 4,
        backoff_seconds: float = 0.01,
        timeout_seconds: float = 0.2,
    ):
        super().__init__(
            name=name,
            model=model,
            api_key_env=api_key_env,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            timeout_seconds=timeout_seconds,
            api_key="mock-valid-key",
            skip_quota_check=True,
        )
        self.call_count = 0
        self.responses = []
        self.exceptions = []

    def set_responses(self, responses):
        self.responses = list(responses)

    def set_exceptions(self, exceptions):
        self.exceptions = list(exceptions)

    def call_vision_api(self, image_path: Path, prompt: str, system_prompt: str) -> str:
        self.call_count += 1
        if self.exceptions:
            exc = self.exceptions.pop(0)
            if exc is not None:
                raise exc
        if self.responses:
            return self.responses.pop(0)
        return json.dumps({
            "answers": ["A"],
            "type": "single",
            "confidence": 0.95,
            "options": {"A": "First", "B": "Second", "C": "Third", "D": "Fourth"}
        })


def _create_dummy_image(tmp_path: Path, name: str = "test.png") -> Path:
    p = tmp_path / name
    im = Image.new("RGB", (80, 80), color=(120, 150, 180))
    im.save(p)
    return p


def _make_comment(author: str, text: str, upvotes: int = 0) -> Comment:
    c = Comment()
    c.author_hash = author
    c.raw_text = text
    c.upvotes = upvotes
    c.comment_id = author
    c.id = abs(hash(author + text)) % 100000
    c.quoted_comment_id = None
    return c


# ===========================================================================
# 1. Test 429 Rate Limit Retry with Backoff & Retry-After
# ===========================================================================

def test_mock_429_retry_success(tmp_path: Path):
    """Simulate 3 consecutive 429 errors followed by success within max 4 retries."""
    img_path = _create_dummy_image(tmp_path, "test_429.png")
    provider = MockVisionProvider(max_retries=4, backoff_seconds=0.01)
    provider.set_exceptions([
        ProviderRateLimitError("429 Too Many Requests - retry after: 0.02s"),
        ProviderRateLimitError("429 Too Many Requests - try again in 0.01s"),
        ProviderRateLimitError("RESOURCE_EXHAUSTED 429"),
    ])
    valid_resp = json.dumps({
        "answers": ["B"],
        "type": "single",
        "confidence": 0.9,
        "options": {"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"}
    })
    provider.set_responses([valid_resp])

    raw = provider.call_with_retry(img_path, "prompt", "system")
    assert provider.call_count == 4  # 1 initial + 3 retries
    assert "Beta" in raw


def test_mock_429_exhausted(tmp_path: Path):
    """Simulate 5 consecutive 429 errors (exceeds max 4 retries) -> raises ProviderRateLimitError."""
    img_path = _create_dummy_image(tmp_path, "test_429_exhaust.png")
    provider = MockVisionProvider(max_retries=4, backoff_seconds=0.01)
    provider.set_exceptions([
        ProviderRateLimitError("429 Rate Limit"),
        ProviderRateLimitError("429 Rate Limit"),
        ProviderRateLimitError("429 Rate Limit"),
        ProviderRateLimitError("429 Rate Limit"),
        ProviderRateLimitError("429 Rate Limit"),
    ])

    with pytest.raises(ProviderRateLimitError):
        provider.call_with_retry(img_path, "prompt", "system")
    assert provider.call_count == 5  # 1 initial + 4 retries = 5


def test_parse_retry_after_header_and_message():
    """Verify Retry-After is parsed from error messages and regex patterns."""
    err1 = ProviderRateLimitError("Please wait 15s before next request.")
    assert parse_retry_after(err1) == 15.0

    err2 = ProviderRateLimitError("Quota exceeded, retry in 8.5s.")
    assert parse_retry_after(err2) == 8.5

    err3 = ProviderRateLimitError("Too Many Requests, retry-after: 25")
    assert parse_retry_after(err3) == 25.0


# ===========================================================================
# 2. Test Call Timeout (60s simulation)
# ===========================================================================

def test_mock_call_timeout_retry(tmp_path: Path):
    """Simulate call exceeding timeout_seconds -> converted to ProviderNetworkError and retried."""
    img_path = _create_dummy_image(tmp_path, "test_timeout.png")
    provider = MockVisionProvider(max_retries=2, backoff_seconds=0.01, timeout_seconds=0.05)

    def slow_call(*args, **kwargs):
        time.sleep(0.15)  # Exceeds 0.05s timeout
        return "{}"

    provider.call_vision_api = slow_call

    with pytest.raises(ProviderNetworkError) as exc_info:
        provider.call_with_retry(img_path, "prompt", "system")
    assert "timed out" in str(exc_info.value).lower()


# ===========================================================================
# 3. Test Malformed JSON & Self-Correction Retry
# ===========================================================================

def test_mock_malformed_json_triggers_correction_retry(tmp_path: Path):
    """If provider returns malformed JSON, AICheckService prompts for correction."""
    img_path = _create_dummy_image(tmp_path, "test_malformed.png")
    svc = AICheckService()

    provider = MockVisionProvider(max_retries=4, backoff_seconds=0.01)
    provider.set_responses([
        "Sorry, I cannot output JSON for this image: here is text only.",  # 1st try: not JSON
        "{answers: ['A'], options: broken}",                             # 2nd try: bad JSON
        json.dumps({                                                     # 3rd try: valid JSON
            "answers": ["C"],
            "type": "single",
            "confidence": 0.95,
            "options": {"A": "Opt A", "B": "Opt B", "C": "Opt C", "D": "Opt D"}
        })
    ])

    svc._providers = [provider]
    analysis = svc.analyze_with_provider(provider, img_path, force_refresh=True)

    assert analysis is not None
    assert analysis.answers == ["C"]
    assert provider.call_count == 3


# ===========================================================================
# 4. Test Answers Outside A-D / Options
# ===========================================================================

def test_mock_answer_outside_options(tmp_path: Path):
    """Model returns answer 'Z' or 'E' not present in options -> rejected by validator."""
    svc = AICheckService()
    invalid_json = json.dumps({
        "answers": ["Z"],
        "type": "single",
        "confidence": 0.95,
        "options": {"A": "Apple", "B": "Banana", "C": "Cherry", "D": "Date"}
    })
    analysis, error_detail = svc._validate_and_parse_json(invalid_json)
    assert analysis is None
    assert "not found in options" in error_detail


# ===========================================================================
# 5. Test Multiple Choice (Choose N)
# ===========================================================================

def test_mock_multiple_choice_choose_n():
    """Verify multiple-choice answers ['A', 'C'] are parsed and validated properly."""
    svc = AICheckService()
    mc_json = json.dumps({
        "answers": ["A", "C"],
        "type": "multiple",
        "confidence": 0.92,
        "options": {
            "A": "Encapsulation",
            "B": "Procedural",
            "C": "Polymorphism",
            "D": "Monolithic"
        }
    })
    analysis, error_detail = svc._validate_and_parse_json(mc_json)
    assert analysis is not None
    assert analysis.answers == ["A", "C"]
    assert analysis.type == "multiple"
    assert analysis.confidence == 0.92


# ===========================================================================
# 6. Decision Matrix Confirmation
# ===========================================================================

def test_decision_matrix_ai_alone_never_confident():
    """
    Rule: AI alone has winner_independent_voters = 1 (< 2 required for CONFIDENT).
    Must NEVER produce CONFIDENT, even with confidence=1.0 and weight=1.0.
    """
    # Test with ai_answer
    res1 = tally_votes(comments=[], ai_answer=["B"], ai_confidence=0.99, ai_weight=1.0)
    assert res1.status != AnswerStatus.CONFIDENT
    assert res1.status == AnswerStatus.WEAK
    assert res1.answer_set == ["B"]

    # Test with ai_votes
    ai_votes = [{"provider": "gemini", "answers": ["B"], "confidence": 0.99, "weight": 1.0}]
    res2 = tally_votes(comments=[], ai_votes=ai_votes)
    assert res2.status != AnswerStatus.CONFIDENT
    assert res2.status == AnswerStatus.WEAK
    assert res2.answer_set == ["B"]


def test_decision_matrix_ai_weight_adjustment():
    """
    Rule: AI vote weight is 1.0 when confidence >= 0.6;
    reduced to 0.5 when confidence < 0.6.
    """
    # High confidence (0.85 >= 0.6) -> weight remains 1.0
    res_high = tally_votes(
        comments=[],
        ai_votes=[{"provider": "gemini", "answers": ["A"], "confidence": 0.85, "weight": 1.0}]
    )
    assert res_high.total_weight == 1.0

    # Low confidence (0.45 < 0.6) -> weight is halved to 0.5
    res_low = tally_votes(
        comments=[],
        ai_votes=[{"provider": "gemini", "answers": ["A"], "confidence": 0.45, "weight": 1.0}]
    )
    assert res_low.total_weight == 0.5

    # With ai_answer parameter:
    res_high_param = tally_votes(comments=[], ai_answer=["A"], ai_confidence=0.9, ai_weight=1.0)
    assert res_high_param.total_weight == 1.0

    res_low_param = tally_votes(comments=[], ai_answer=["A"], ai_confidence=0.4, ai_weight=1.0)
    assert res_low_param.total_weight == 0.5


def test_decision_matrix_community_plus_ai_agreement():
    """
    1 community voter (WEAK) + 1 AI voter agreeing -> 2 independent voters -> CONFIDENT.
    """
    comments = [_make_comment("user_1", "A")]
    ai_votes = [{"provider": "gemini", "answers": ["A"], "confidence": 0.9, "weight": 1.0}]

    res = tally_votes(comments, ai_votes=ai_votes)
    assert res.status == AnswerStatus.CONFIDENT
    assert res.answer_set == ["A"]
    assert not res.ai_disagreed


def test_decision_matrix_ai_cannot_override_majority():
    """
    Community has 2 agreeing voters for B (CONFIDENT) + AI votes D.
    AI must NOT override community majority (B remains winner).
    """
    comments = [
        _make_comment("user_1", "B"),
        _make_comment("user_2", "B"),
    ]
    ai_votes = [{"provider": "gemini", "answers": ["D"], "confidence": 0.95, "weight": 1.0}]

    res = tally_votes(comments, ai_votes=ai_votes, ai_disagreement_policy="flag")
    assert res.answer_set == ["B"]
    assert res.ai_disagreed is True


def test_batch_image_stitching_and_analysis(tmp_path):
    """
    Test B.1: Vertical crop stitching and batch JSON parsing into individual question results.
    """
    from PIL import Image, ImageDraw
    from backend.app.modules.analysis.ai_check import stitch_crop_images, AICheckService

    # 1. Create 3 small synthetic crop images
    crops = []
    for i in range(1, 4):
        p = tmp_path / f"crop_{i}.png"
        img = Image.new("RGB", (200, 100), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((10, 30), f"Question {i}: Option A or B?", fill="black")
        img.save(p)
        crops.append(p)

    items = [
        {"label": "ITEM_1", "image_path": crops[0], "hint": "Question 1"},
        {"label": "ITEM_2", "image_path": crops[1], "hint": "Question 2"},
        {"label": "ITEM_3", "image_path": crops[2], "hint": "Question 3"},
    ]

    composite_path = tmp_path / "composite.png"
    stitch_crop_images(items, composite_path)
    assert composite_path.exists()
    comp_img = Image.open(composite_path)
    assert comp_img.width >= 200
    assert comp_img.height > 300

    # 2. Mock batch provider response
    batch_json_resp = json.dumps({
        "ITEM_1": {"answers": ["A"], "type": "single", "confidence": 0.95, "options": {"A": "First", "B": "Second"}},
        "ITEM_2": {"answers": ["B", "C"], "type": "multiple", "confidence": 0.88, "options": {"B": "Opt B", "C": "Opt C"}},
        "ITEM_3": {"answers": ["D"], "type": "single", "confidence": 0.70, "options": {"D": "Opt D"}},
    })

    mock_provider = MockVisionProvider("gemini", "gemini-2.5-flash")
    mock_provider.set_responses([batch_json_resp])
    mock_provider.skip_quota_check = True

    service = AICheckService()
    service._providers = [mock_provider]
    service._cache_file = tmp_path / "cache.json"

    batch_input = [
        {"question_id": 101, "image_path": crops[0], "q_num": 1},
        {"question_id": 102, "image_path": crops[1], "q_num": 2, "multi_choice_n": 2},
        {"question_id": 103, "image_path": crops[2], "q_num": 3},
    ]

    results = service.batch_analyze_questions(batch_input, provider=mock_provider, batch_size=5)
    assert len(results) == 3
    assert results[101].answers == ["A"]
    assert results[101].confidence == 0.95
    assert results[102].answers == ["B", "C"]
    assert results[102].type == "multiple"
    assert results[103].answers == ["D"]

    # Verify individual results were saved to cache
    crop1_hash = service.compute_crop_hash(crops[0])
    v1_key = service._get_cache_key(mock_provider, crop1_hash, "v1.0")
    assert v1_key in service._cache
    assert service._cache[v1_key]["answers"] == ["A"]


def test_per_model_daily_quota_cascade(tmp_path):
    """
    Test B.3: Per-model quota tracking: gemini-2.5-flash (20 limit) exhaustion
    does not block gemini-1.5-flash (1500 limit).
    """
    from backend.app.modules.analysis.gemini_guard import DailyQuotaTracker

    quota_file = tmp_path / "model_quota.json"
    tracker = DailyQuotaTracker(quota_file=quota_file)

    # Initialize model limits
    status_25 = tracker.get_model_status("gemini-2.5-flash")
    status_15 = tracker.get_model_status("gemini-1.5-flash")
    assert status_25["daily_limit"] == 20
    assert status_15["daily_limit"] == 1500

    # Exhaust gemini-2.5-flash
    tracker.mark_exhausted("Hit 20 RPD free tier limit", model="gemini-2.5-flash")

    assert tracker.can_call(model="gemini-2.5-flash") is False
    assert tracker.remaining_calls(model="gemini-2.5-flash") == 0

    # gemini-1.5-flash must still be available
    assert tracker.can_call(model="gemini-1.5-flash") is True
    assert tracker.remaining_calls(model="gemini-1.5-flash") == 1500

