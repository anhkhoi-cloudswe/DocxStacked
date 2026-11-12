import json
from pathlib import Path
from PIL import Image
import pytest
from unittest.mock import MagicMock

from backend.app.modules.analysis.ai_check import AICheckService, AIQuestionAnalysis
from backend.app.modules.analysis.providers import (
    VisionProvider,
    AnthropicProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    ProviderRateLimitError,
    ProviderNetworkError,
    create_provider,
)


def test_provider_factory_and_dynamic_models():
    """Verify that providers are instantiated with custom models and api_key_env without hardcoding."""
    p_ant = create_provider(
        name="anthropic",
        model="claude-3-haiku-custom",
        api_key_env="CUSTOM_ANTHROPIC_KEY",
    )
    assert isinstance(p_ant, AnthropicProvider)
    assert p_ant.model == "claude-3-haiku-custom"
    assert p_ant.api_key_env == "CUSTOM_ANTHROPIC_KEY"

    p_gem = create_provider(
        name="gemini",
        model="gemini-2.5-flash-preview",
        api_key_env="CUSTOM_GEMINI_KEY",
    )
    assert isinstance(p_gem, GeminiProvider)
    assert p_gem.model == "gemini-2.5-flash-preview"

    p_oai = create_provider(
        name="openai_compatible",
        model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com/v1",
    )
    assert isinstance(p_oai, OpenAICompatibleProvider)
    assert p_oai.model == "deepseek-chat"
    assert p_oai.base_url == "https://api.deepseek.com/v1"


def test_ai_json_validation_valid():
    svc = AICheckService()
    valid_json = """
    {
      "answers": ["B"],
      "type": "single",
      "confidence": 0.95,
      "options": {
        "A": "GET method",
        "B": "Classes and objects",
        "C": "Layout builder",
        "D": "Hot reload"
      }
    }
    """
    res, err = svc._validate_and_parse_json(valid_json)
    assert res is not None
    assert err is None
    assert res.answers == ["B"]
    assert res.type == "single"
    assert res.confidence == 0.95
    assert res.options["B"] == "Classes and objects"


def test_ai_json_validation_markdown_fence():
    svc = AICheckService()
    fenced_json = """```json
    {
      "answers": ["A", "C"],
      "type": "multiple",
      "confidence": 0.88,
      "options": {
        "A": "First option",
        "B": "Second option",
        "C": "Third option"
      }
    }
    ```"""
    res, err = svc._validate_and_parse_json(fenced_json)
    assert res is not None
    assert err is None
    assert res.answers == ["A", "C"]
    assert res.type == "multiple"


def test_ai_json_validation_invalid_option_subset():
    svc = AICheckService()
    # 'answers' has 'Z' which is NOT in options!
    invalid_json = """
    {
      "answers": ["Z"],
      "type": "single",
      "confidence": 0.9,
      "options": {
        "A": "Option 1",
        "B": "Option 2"
      }
    }
    """
    res, err = svc._validate_and_parse_json(invalid_json)
    assert res is None
    assert "not found in options" in err


def test_ai_phash_computation(tmp_path: Path):
    svc = AICheckService()
    img_path = tmp_path / "test_phash.png"
    im = Image.new("RGB", (200, 100), (200, 200, 200))
    im.save(img_path)

    phash = svc.compute_phash(img_path)
    assert isinstance(phash, str)
    assert len(phash) == 16


def test_ai_phash_caching_with_provider_and_model(tmp_path: Path, monkeypatch):
    """Cache key must include provider and model to prevent collision."""
    svc = AICheckService()
    img_path = tmp_path / "cache_test.png"
    im = Image.new("RGB", (150, 80), (100, 150, 200))
    im.save(img_path)

    phash = svc.compute_phash(img_path)

    # Mock provider
    mock_p = AnthropicProvider(name="anthropic", model="test-claude", api_key_env="TEST_KEY")
    monkeypatch.setattr(mock_p, "is_available", lambda: True)
    svc._providers = [mock_p]

    cache_key = f"anthropic:test-claude:{phash}"
    svc._cache[cache_key] = {
        "answers": ["C"],
        "type": "single",
        "confidence": 0.99,
        "options": {"A": "Opt A", "B": "Opt B", "C": "Opt C"},
        "provider": "anthropic",
        "model": "test-claude",
    }

    # Should hit cache without making API call
    res = svc.analyze_question_image(img_path)
    assert res is not None
    assert res.answers == ["C"]
    assert res.provider == "anthropic"
    assert res.model == "test-claude"


def test_provider_fallback_on_rate_limit(tmp_path: Path, monkeypatch):
    """When Provider 1 encounters 429 rate limit, service falls back to Provider 2."""
    svc = AICheckService()
    img_path = tmp_path / "fallback_429.png"
    im = Image.new("RGB", (100, 100), (255, 255, 255))
    im.save(img_path)

    p1 = AnthropicProvider(name="anthropic", model="m1", api_key_env="K1", max_retries=1, backoff_seconds=0.01)
    p2 = GeminiProvider(name="gemini", model="m2", api_key_env="K2", max_retries=1, backoff_seconds=0.01)

    monkeypatch.setattr(p1, "is_available", lambda: True)
    monkeypatch.setattr(p2, "is_available", lambda: True)

    # p1 always raises 429
    def mock_p1_call(*args, **kwargs):
        raise ProviderRateLimitError("Quota 429 reached")

    # p2 returns valid response
    def mock_p2_call(*args, **kwargs):
        return json.dumps({
            "answers": ["A"],
            "type": "single",
            "confidence": 0.92,
            "options": {"A": "Fallback answer", "B": "Other"}
        })

    monkeypatch.setattr(p1, "call_vision_api", mock_p1_call)
    monkeypatch.setattr(p2, "call_vision_api", mock_p2_call)

    svc._providers = [p1, p2]

    res = svc.analyze_question_image(img_path, force_refresh=True)
    assert res is not None
    assert res.provider == "gemini"
    assert res.answers == ["A"]


def test_provider_fallback_on_network_error(tmp_path: Path, monkeypatch):
    """When Provider 1 encounters network failure, service falls back to Provider 2."""
    svc = AICheckService()
    img_path = tmp_path / "fallback_net.png"
    im = Image.new("RGB", (100, 100), (100, 100, 100))
    im.save(img_path)

    p1 = AnthropicProvider(name="anthropic", model="m1", api_key_env="K1", max_retries=1, backoff_seconds=0.01)
    p2 = OpenAICompatibleProvider(name="openai_compatible", model="m3", api_key_env="K3", max_retries=1, backoff_seconds=0.01)

    monkeypatch.setattr(p1, "is_available", lambda: True)
    monkeypatch.setattr(p2, "is_available", lambda: True)

    def mock_p1_fail(*args, **kwargs):
        raise ProviderNetworkError("Connection timed out")

    def mock_p2_success(*args, **kwargs):
        return json.dumps({
            "answers": ["D"],
            "type": "single",
            "confidence": 0.85,
            "options": {"A": "X", "B": "Y", "C": "Z", "D": "Target"}
        })

    monkeypatch.setattr(p1, "call_vision_api", mock_p1_fail)
    monkeypatch.setattr(p2, "call_vision_api", mock_p2_success)

    svc._providers = [p1, p2]

    res = svc.analyze_question_image(img_path, force_refresh=True)
    assert res is not None
    assert res.provider == "openai_compatible"
    assert res.answers == ["D"]


def test_ai_ensemble_mode_returns_two_providers(tmp_path: Path, monkeypatch):
    """When ai.ensemble is True, service queries top 2 providers for joint voting."""
    svc = AICheckService()
    img_path = tmp_path / "ensemble_test.png"
    im = Image.new("RGB", (100, 100), (50, 50, 50))
    im.save(img_path)

    p1 = AnthropicProvider(name="anthropic", model="m1", api_key_env="K1")
    p2 = GeminiProvider(name="gemini", model="m2", api_key_env="K2")

    monkeypatch.setattr(p1, "is_available", lambda: True)
    monkeypatch.setattr(p2, "is_available", lambda: True)

    monkeypatch.setattr(
        p1,
        "call_vision_api",
        lambda *args, **kwargs: json.dumps({
            "answers": ["B"],
            "type": "single",
            "confidence": 0.9,
            "options": {"A": "A", "B": "B"}
        }),
    )
    monkeypatch.setattr(
        p2,
        "call_vision_api",
        lambda *args, **kwargs: json.dumps({
            "answers": ["B"],
            "type": "single",
            "confidence": 0.88,
            "options": {"A": "A", "B": "B"}
        }),
    )

    svc._providers = [p1, p2]

    # Monkeypatch config ai.ensemble to True
    class MockAIConfig:
        enabled = True
        ensemble = True
        max_ai_calls = 100

    class MockYamlConfig:
        ai = MockAIConfig()
        analysis = MockAIConfig()

    monkeypatch.setattr(svc, "get_available_providers", lambda: [p1, p2])
    monkeypatch.setattr("backend.app.core.config.Settings.yaml_config", MockYamlConfig())

    results = svc.analyze_question_ensemble(img_path, force_refresh=True)
    assert len(results) == 2
    assert results[0].provider == "anthropic"
    assert results[0].answers == ["B"]
    assert results[1].provider == "gemini"
    assert results[1].answers == ["B"]
