import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid
from PIL import Image, ImageDraw
import imagehash
from pydantic import BaseModel, Field

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.modules.analysis.gemini_guard import (
    DailyQuotaExhaustedError,
    get_daily_quota_tracker,
)
from backend.app.modules.analysis.providers import (
    VisionProvider,
    AnthropicProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderModelNotFoundError,
    ProviderVisionUnsupportedError,
    ProviderNetworkError,
    ProviderAPIError,
    create_provider,
)

logger = get_logger(__name__)
settings = get_settings()

PROMPT_VERSION = "v1.0"


class AIQuestionAnalysis(BaseModel):
    answers: List[str] = Field(..., description="List of uppercase correct answer letters, e.g. ['B']")
    type: str = Field(default="single", description="'single' or 'multiple'")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    options: Dict[str, str] = Field(
        default_factory=dict,
        description="Short keywords for each option, e.g. {'A': 'GET', 'B': 'POST'}",
    )
    provider: Optional[str] = Field(default=None, description="Name of provider that generated this analysis")
    model: Optional[str] = Field(default=None, description="Model used")


SYSTEM_PROMPT = (
    "You are an expert exam solver. You analyze multiple choice question images and identify "
    "the correct answer(s). Output ONLY valid JSON."
)

BASE_PROMPT = """Analyze this question image and identify the correct answer.
Rules:
1. Determine all correct answer letters (e.g. ["B"], or ["A", "C"] if multiple).
2. For each option present in the image (A, B, C, D...), extract a short summary keyword/phrase (maximum 6 words, keep technical terms intact).
3. Return ONLY a valid JSON object in the following format:
{
  "answers": ["B"],
  "type": "single",
  "confidence": 0.95,
  "options": {
    "A": "keyword for A",
    "B": "keyword for B",
    "C": "keyword for C",
    "D": "keyword for D"
  }
}
Do NOT include any explanations, markdown code fences, or text outside the JSON."""

CORRECTION_PROMPT_TEMPLATE = """Your previous response was not valid JSON or violated the schema:
Error: {error_detail}

Please re-analyze the image and return ONLY a valid JSON object matching:
{{
  "answers": ["B"],
  "type": "single",
  "confidence": 0.95,
  "options": {{
    "A": "keyword for A",
    "B": "keyword for B",
    "C": "keyword for C",
    "D": "keyword for D"
  }}
}}
Make sure every letter in "answers" is present in "options". Output only JSON."""


BATCH_SYSTEM_PROMPT = (
    "You are an expert exam solver. You analyze a composite image containing multiple multiple-choice questions "
    "labeled ITEM_1, ITEM_2, etc., and extract the correct answer(s) for each item. Output ONLY valid JSON."
)

BATCH_BASE_PROMPT = """The provided image contains multiple exam questions vertically stacked, each separated by a header labeled ITEM_1, ITEM_2, etc.
For EACH item:
1. Determine all correct answer letters (e.g. ["B"], or ["A", "C"] if multiple).
2. For each option present in that question (A, B, C, D...), extract a short summary keyword/phrase (maximum 6 words, keep technical terms intact).
3. Determine a confidence score from 0.0 to 1.0.

Return ONLY a valid JSON object in the following format:
{
  "ITEM_1": {
    "answers": ["A"],
    "type": "single",
    "confidence": 0.95,
    "options": {
      "A": "keyword A",
      "B": "keyword B",
      "C": "keyword C",
      "D": "keyword D"
    }
  },
  "ITEM_2": {
    "answers": ["B", "C"],
    "type": "multiple",
    "confidence": 0.90,
    "options": {
      "A": "keyword A",
      "B": "keyword B",
      "C": "keyword C",
      "D": "keyword D"
    }
  }
}
Do NOT include any explanations, markdown code fences, or text outside the JSON."""


def stitch_crop_images(
    items: List[Dict[str, Any]],
    output_path: Path,
) -> Path:
    """
    Stitches multiple question crops vertically with clearly labeled banners.
    Each item in items has: 'label', 'image_path', and optional 'hint'.
    """
    opened = []
    for item in items:
        p = Path(item["image_path"])
        img = Image.open(p).convert("RGB")
        opened.append((item, img))

    max_width = max(max(img.width for _, img in opened), 600)
    banner_height = 36
    item_spacing = 16

    total_height = sum(banner_height + img.height + item_spacing for _, img in opened)
    composite = Image.new("RGB", (max_width, total_height), color="white")
    draw = ImageDraw.Draw(composite)

    current_y = 0
    for item, img in opened:
        label = item.get("label", "ITEM")
        hint = item.get("hint", "")
        banner_text = f"=== [{label}] {hint} ==="

        draw.rectangle(
            [0, current_y, max_width, current_y + banner_height],
            fill=(235, 240, 248),
            outline=(180, 200, 220),
        )
        draw.text((16, current_y + 10), banner_text, fill=(20, 30, 60))
        current_y += banner_height

        offset_x = (max_width - img.width) // 2
        composite.paste(img, (offset_x, current_y))
        current_y += img.height + item_spacing

    output_path.parent.mkdir(parents=True, exist_ok=True)
    composite.save(output_path, format="PNG")
    return output_path


class AICheckService:
    """
    Multi-provider Vision AI service to read cropped question images, solve answers,
    and extract option keywords using priority fallback or ensemble voting.

    Features:
      - Multi-provider support (Anthropic, Gemini, OpenAI-compatible).
      - Priority-ordered fallback with backoff on 429 and network errors.
      - Ensemble mode (ai.ensemble: true): top 2 providers vote together.
      - pHash cache keyed by f"{provider}:{model}:{phash}".
      - Retry on invalid JSON format up to 2 times.
      - Strict JSON validation: answers must belong to options.keys().
      - Job max_ai_calls cap.
      - API keys strictly from environment / .env, never logged.
    """

    def __init__(self):
        self._cache: Dict[str, dict] = {}
        self._cache_file: Path = settings.STORAGE_DIR / "cache" / "ai_vision_cache.json"
        self._job_call_counts: Dict[str, int] = {}
        self._disabled_providers: Set[str] = set()
        self._load_cache()
        self._providers: List[VisionProvider] = []
        self._init_providers()

    def _init_providers(self):
        """Initialize provider list from YAML config in priority order."""
        yaml_cfg = settings.yaml_config
        ai_cfg = getattr(yaml_cfg, "ai", None)

        configured_providers = getattr(ai_cfg, "providers", []) if ai_cfg else []
        backoff_sec = getattr(ai_cfg, "backoff_seconds", 2.0) if ai_cfg else 2.0
        max_retries = getattr(ai_cfg, "max_retries", 2) if ai_cfg else 2

        self._providers = []
        for p_cfg in configured_providers:
            provider = create_provider(
                name=p_cfg.name,
                model=p_cfg.model,
                api_key_env=p_cfg.api_key_env,
                base_url=p_cfg.base_url,
                max_retries=max_retries,
                backoff_seconds=backoff_sec,
            )
            self._providers.append(provider)

        # Fallback default if no providers configured in yaml
        if not self._providers:
            self._providers = [
                AnthropicProvider(
                    name="anthropic",
                    model="claude-3-5-haiku-20241022",
                    api_key_env="ANTHROPIC_API_KEY",
                    max_retries=max_retries,
                    backoff_seconds=backoff_sec,
                ),
                GeminiProvider(
                    name="gemini",
                    model="gemini-2.5-flash",
                    api_key_env="GEMINI_API_KEY",
                    max_retries=max_retries,
                    backoff_seconds=backoff_sec,
                ),
                OpenAICompatibleProvider(
                    name="openai_compatible",
                    model="gpt-4o-mini",
                    api_key_env="OPENAI_API_KEY",
                    base_url="https://api.openai.com/v1",
                    max_retries=max_retries,
                    backoff_seconds=backoff_sec,
                ),
            ]

    def get_providers(self) -> List[VisionProvider]:
        """Return all configured providers."""
        return list(self._providers)

    def get_available_providers(self) -> List[VisionProvider]:
        """Return configured providers that have non-empty API keys in environment and are not disabled."""
        return [
            p for p in self._providers
            if p.is_available()
            and p.name not in self._disabled_providers
            and f"{p.name}:{p.model}" not in self._disabled_providers
        ]

    def is_available(self) -> bool:
        """Return True if at least one provider has an active API key."""
        return len(self.get_available_providers()) > 0

    def _load_cache(self):
        """Load pHash cache from disk."""
        if self._cache_file.exists():
            try:
                data = json.loads(self._cache_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._cache = data
                    logger.debug(f"Loaded {len(self._cache)} cached AI vision entries.")
            except Exception as e:
                logger.warning(f"Could not load AI vision cache: {e}")

    def _save_cache(self):
        """Persist pHash cache to disk."""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save AI vision cache: {e}")

    def compute_crop_hash(self, image_path: Path) -> str:
        """Compute SHA256 hash of the cropped image file."""
        with open(image_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]

    def compute_phash(self, image_path: Path) -> str:
        """Compute perceptual hash for an image."""
        with Image.open(image_path) as im:
            return str(imagehash.phash(im.convert("RGB")))

    def _get_cache_key(self, provider: VisionProvider, crop_hash: str, prompt_version: str = PROMPT_VERSION) -> str:
        """Generate provider, model, prompt_version and crop_hash specific cache key."""
        return f"{provider.name}:{provider.model}:{prompt_version}:{crop_hash}"

    def _lookup_cache(self, provider: VisionProvider, image_path: Path) -> Optional[AIQuestionAnalysis]:
        """Look up analysis in cache by (crop_hash, prompt_version) or legacy phash."""
        try:
            crop_hash = self.compute_crop_hash(image_path)
            key_v1 = self._get_cache_key(provider, crop_hash, PROMPT_VERSION)
            if key_v1 in self._cache:
                res = AIQuestionAnalysis.model_validate(self._cache[key_v1])
                res.provider = provider.name
                res.model = provider.model
                return res
        except Exception:
            pass

        try:
            phash = self.compute_phash(image_path)
            legacy_key = f"{provider.name}:{provider.model}:{phash}"
            if legacy_key in self._cache:
                res = AIQuestionAnalysis.model_validate(self._cache[legacy_key])
                res.provider = provider.name
                res.model = provider.model
                return res
        except Exception:
            pass

        return None

    def _validate_and_parse_json(self, response_text: str) -> Tuple[Optional[AIQuestionAnalysis], Optional[str]]:
        """Validate and parse provider JSON output. Returns (analysis, error_detail)."""
        cleaned = response_text.strip()
        # Remove markdown fences if model returned them
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            data = json.loads(cleaned)
        except Exception as e:
            return None, f"JSON decode error: {e}"

        if not isinstance(data, dict):
            return None, "Root element is not a JSON object"

        raw_answers = data.get("answers", [])
        if not isinstance(raw_answers, list) or not raw_answers:
            return None, "'answers' field is missing or empty list"

        answers = [str(a).strip().upper() for a in raw_answers]
        options = data.get("options", {})
        if not isinstance(options, dict) or not options:
            return None, "'options' dictionary is missing or empty"

        normalized_options = {k.strip().upper(): str(v).strip() for k, v in options.items()}

        # Validation: every letter in answers must be in options
        for a in answers:
            if a not in normalized_options:
                return None, f"Answer letter '{a}' not found in options: {list(normalized_options.keys())}"

        q_type = str(data.get("type", "single")).lower()
        if q_type not in ("single", "multiple"):
            q_type = "multiple" if len(answers) > 1 else "single"

        conf = float(data.get("confidence", 0.9))
        conf = max(0.0, min(1.0, conf))

        return (
            AIQuestionAnalysis(
                answers=answers,
                type=q_type,
                confidence=conf,
                options=normalized_options,
            ),
            None,
        )

    def _query_provider_with_format_retries(
        self,
        provider: VisionProvider,
        image_path: Path,
    ) -> Optional[AIQuestionAnalysis]:
        """
        Execute API call on a specific provider, validating JSON and retrying
        up to 2 times if JSON is malformed or invalid.
        """
        prompt = BASE_PROMPT
        max_format_retries = 2

        for attempt in range(max_format_retries + 1):
            raw_text = provider.call_with_retry(
                image_path=image_path,
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
            )
            analysis, error_detail = self._validate_and_parse_json(raw_text)
            if analysis:
                analysis.provider = provider.name
                analysis.model = provider.model
                return analysis

            # If format was invalid and we have retries left, prompt for correction
            if attempt < max_format_retries:
                logger.debug(
                    f"Provider '{provider.name}' returned invalid JSON ({error_detail}). "
                    f"Prompting for correction (retry {attempt + 1}/{max_format_retries})..."
                )
                prompt = CORRECTION_PROMPT_TEMPLATE.format(error_detail=error_detail)

        logger.warning(f"Provider '{provider.name}' failed JSON validation after {max_format_retries} retries.")
        return None

    def analyze_with_provider(
        self,
        provider: VisionProvider,
        image_path: Path,
        force_refresh: bool = False,
    ) -> Optional[AIQuestionAnalysis]:
        """
        Analyze an image directly using a specified provider, honoring cache.
        Useful for individual provider accuracy evaluation.
        """
        if not provider.is_available():
            logger.warning(f"Provider '{provider.name}' is not available (missing {provider.api_key_env}).")
            return None

        if not image_path.exists():
            logger.warning(f"Image not found: {image_path}")
            return None

        if not force_refresh:
            cached_res = self._lookup_cache(provider, image_path)
            if cached_res:
                return cached_res

        try:
            analysis = self._query_provider_with_format_retries(provider, image_path)
            if analysis:
                crop_hash = self.compute_crop_hash(image_path)
                v1_key = self._get_cache_key(provider, crop_hash, PROMPT_VERSION)
                self._cache[v1_key] = analysis.model_dump()
                try:
                    phash = self.compute_phash(image_path)
                    self._cache[f"{provider.name}:{provider.model}:{phash}"] = analysis.model_dump()
                except Exception:
                    pass
                self._save_cache()
                return analysis
        except DailyQuotaExhaustedError as e:
            logger.warning(f"Provider '{provider.name}' daily quota exhausted: {e}")
            return None
        except ProviderAuthError as e:
            logger.warning(f"Provider '{provider.name}' auth error (401/Invalid Key): {e}. Disabling provider.")
            self._disabled_providers.add(provider.name)
            return None
        except (ProviderModelNotFoundError, ProviderVisionUnsupportedError) as e:
            logger.warning(f"Provider '{provider.name}' configuration error: {e}. Disabling provider.")
            self._disabled_providers.add(provider.name)
            return None
        except Exception as e:
            logger.warning(f"Provider '{provider.name}' evaluation error: {type(e).__name__}")
            return None

        return None

    def analyze_question_image(
        self,
        image_path: Path,
        job_id: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Optional[AIQuestionAnalysis]:
        """
        Analyze a cropped question image using available providers in priority order.
        If a provider encounters 429, network failure, or unrecoverable error,
        it automatically falls back to the next provider in the configured priority list.
        """
        analyses = self.analyze_question_ensemble(image_path, job_id=job_id, force_refresh=force_refresh)
        return analyses[0] if analyses else None

    def analyze_question_ensemble(
        self,
        image_path: Path,
        job_id: Optional[str] = None,
        force_refresh: bool = False,
    ) -> List[AIQuestionAnalysis]:
        """
        Analyze image according to config:
        - If ai.ensemble is False: queries the highest priority provider (with fallback).
        - If ai.ensemble is True: queries top 2 available providers, returning both analyses
          for independent ensemble voting.
        """
        yaml_cfg = settings.yaml_config
        ai_cfg = getattr(yaml_cfg, "ai", None)

        is_enabled = getattr(ai_cfg, "enabled", True) if ai_cfg else True
        legacy_use_ai = getattr(yaml_cfg.analysis, "use_ai", True)
        if not (is_enabled and legacy_use_ai):
            logger.debug("AI analysis is disabled in config.")
            return []

        if not image_path.exists():
            logger.warning(f"Image not found for AI check: {image_path}")
            return []

        # Check job cap
        if job_id:
            max_calls = getattr(ai_cfg, "max_ai_calls", 100) if ai_cfg else getattr(yaml_cfg.analysis, "max_ai_calls", 100)
            curr_calls = self._job_call_counts.get(job_id, 0)
            if curr_calls >= max_calls:
                logger.warning(f"Job {job_id} reached max AI calls cap ({max_calls}). Skipping AI.")
                return []

        is_ensemble = getattr(ai_cfg, "ensemble", False) if ai_cfg else False
        target_count = 2 if is_ensemble else 1

        available_providers = self.get_available_providers()
        if not available_providers:
            logger.warning("No AI providers available (missing API keys). Skipping AI.")
            return []

        results: List[AIQuestionAnalysis] = []
        used_providers = set()

        for provider in available_providers:
            if len(results) >= target_count:
                break
            if provider.name in used_providers:
                continue

            # Check cache first
            if not force_refresh:
                cached_res = self._lookup_cache(provider, image_path)
                if cached_res:
                    results.append(cached_res)
                    used_providers.add(provider.name)
                    logger.debug(f"AI Check cache HIT ({provider.name}:{provider.model}) for {image_path.name}")
                    continue

            # Make API Call with fallback handling
            try:
                analysis = self._query_provider_with_format_retries(provider, image_path)
                if analysis:
                    crop_hash = self.compute_crop_hash(image_path)
                    v1_key = self._get_cache_key(provider, crop_hash, PROMPT_VERSION)
                    self._cache[v1_key] = analysis.model_dump()
                    try:
                        phash = self.compute_phash(image_path)
                        self._cache[f"{provider.name}:{provider.model}:{phash}"] = analysis.model_dump()
                    except Exception:
                        pass
                    self._save_cache()
                    results.append(analysis)
                    used_providers.add(provider.name)
                    if job_id:
                        self._job_call_counts[job_id] = self._job_call_counts.get(job_id, 0) + 1
                else:
                    logger.warning(f"Provider '{provider.name}' failed to produce valid result. Falling back to next...")
            except DailyQuotaExhaustedError as e:
                logger.warning(f"AI daily quota exhausted for {provider.name}:{provider.model} ({e}). Falling back to next provider...")
                self._disabled_providers.add(f"{provider.name}:{provider.model}")
                self._disabled_providers.add(provider.name)
                continue
            except ProviderAuthError as e:
                logger.warning(f"Provider '{provider.name}' auth failed (401/Invalid Key): {e}. Disabling provider for this session.")
                self._disabled_providers.add(provider.name)
                self._disabled_providers.add(f"{provider.name}:{provider.model}")
            except (ProviderModelNotFoundError, ProviderVisionUnsupportedError) as e:
                logger.warning(f"Provider '{provider.name}' configuration error: {e}. Disabling provider for this session.")
                self._disabled_providers.add(provider.name)
            except (ProviderRateLimitError, ProviderNetworkError, ProviderAPIError) as e:
                logger.warning(f"Provider '{provider.name}' failed ({type(e).__name__}). Falling back to next provider...")
            except Exception as e:
                logger.warning(f"Unexpected error in provider '{provider.name}': {type(e).__name__}. Falling back...")

        return results

    def batch_analyze_questions(
        self,
        items: List[Dict[str, Any]],
        provider: Optional[VisionProvider] = None,
        batch_size: int = 5,
        force_refresh: bool = False,
    ) -> Dict[int, Optional[AIQuestionAnalysis]]:
        """
        Batches multiple question crops (5-8 crops) into composite images to maximize
        free tier quota efficiency (e.g. 5 questions per 1 API call).
        
        items: list of dicts with:
            'question_id': int,
            'image_path': Path,
            'multi_choice_n': Optional[int],
            'q_num': Optional[int],
        
        Returns:
            Dict mapping question_id -> AIQuestionAnalysis (or None if failed)
        """
        results: Dict[int, Optional[AIQuestionAnalysis]] = {}
        active_provider = provider
        if active_provider is None:
            available = [p for p in self._providers if p.is_available() and p.name not in self._disabled_providers]
            if not available:
                logger.warning("No vision AI providers available for batch analysis.")
                return {item["question_id"]: None for item in items}
            active_provider = available[0]

        to_call_items = []
        for item in items:
            q_id = item["question_id"]
            img_path = Path(item["image_path"])
            if not img_path.exists():
                results[q_id] = None
                continue

            if not force_refresh:
                cached = self._lookup_cache(active_provider, img_path)
                if cached:
                    results[q_id] = cached
                    continue

            to_call_items.append(item)

        if not to_call_items:
            return results

        # Process non-cached items in batches
        for chunk_idx in range(0, len(to_call_items), batch_size):
            chunk = to_call_items[chunk_idx : chunk_idx + batch_size]

            if len(chunk) == 1:
                item = chunk[0]
                q_id = item["question_id"]
                ans = self.analyze_with_provider(active_provider, Path(item["image_path"]), force_refresh=force_refresh)
                results[q_id] = ans
                continue

            batch_manifest = []
            for i, item in enumerate(chunk):
                label = f"ITEM_{i + 1}"
                q_num = item.get("q_num", item["question_id"])
                hint = f"Question {q_num}"
                if item.get("multi_choice_n") and item["multi_choice_n"] > 1:
                    hint += f" (Choose {item['multi_choice_n']})"
                batch_manifest.append({
                    "label": label,
                    "image_path": Path(item["image_path"]),
                    "hint": hint,
                    "item_data": item,
                })

            cache_dir = settings.STORAGE_DIR / "cache"
            composite_path = cache_dir / f"batch_composite_{uuid.uuid4().hex[:8]}.png"

            try:
                stitch_crop_images(batch_manifest, composite_path)
                logger.info(
                    f"Sending batch of {len(chunk)} questions to {active_provider.name}:{active_provider.model}..."
                )
                raw_response = active_provider.call_with_retry(
                    composite_path,
                    BATCH_BASE_PROMPT,
                    BATCH_SYSTEM_PROMPT,
                )

                clean_json = raw_response.strip()
                if clean_json.startswith("```"):
                    clean_json = re.sub(r"^```[a-zA-Z]*\n?", "", clean_json)
                    clean_json = re.sub(r"\n?```$", "", clean_json)
                parsed_batch = json.loads(clean_json)

                for entry in batch_manifest:
                    lbl = entry["label"]
                    item_data = entry["item_data"]
                    q_id = item_data["question_id"]
                    img_p = Path(item_data["image_path"])

                    if lbl in parsed_batch and isinstance(parsed_batch[lbl], dict):
                        try:
                            item_dict = parsed_batch[lbl]
                            ans_list = item_dict.get("answers", [])
                            if isinstance(ans_list, str):
                                ans_list = [ans_list.strip().upper()]
                            else:
                                ans_list = [str(a).strip().upper() for a in ans_list]

                            ans_list = [a for a in ans_list if re.match(r"^[A-Z]$", a)]
                            opts = item_dict.get("options", {})
                            conf = float(item_dict.get("confidence", 0.9))
                            q_type = str(item_dict.get("type", "single" if len(ans_list) <= 1 else "multiple"))

                            analysis = AIQuestionAnalysis(
                                answers=ans_list,
                                type=q_type,
                                confidence=conf,
                                options=opts,
                                provider=active_provider.name,
                                model=active_provider.model,
                            )
                            crop_hash = self.compute_crop_hash(img_p)
                            v1_key = self._get_cache_key(active_provider, crop_hash, PROMPT_VERSION)
                            self._cache[v1_key] = analysis.model_dump()
                            try:
                                phash = self.compute_phash(img_p)
                                self._cache[f"{active_provider.name}:{active_provider.model}:{phash}"] = analysis.model_dump()
                            except Exception:
                                pass

                            results[q_id] = analysis
                        except Exception as parse_err:
                            logger.warning(f"Failed to parse item {lbl}: {parse_err}")
                            results[q_id] = None
                    else:
                        results[q_id] = None

                self._save_cache()

            except DailyQuotaExhaustedError as e:
                logger.warning(f"Batch analysis quota exhausted: {e}")
                for entry in batch_manifest:
                    q_id = entry["item_data"]["question_id"]
                    if q_id not in results:
                        results[q_id] = None
                break
            except Exception as e:
                logger.warning(f"Batch vision call failed: {e}. Falling back to single-question calls...")
                for entry in batch_manifest:
                    item_data = entry["item_data"]
                    q_id = item_data["question_id"]
                    try:
                        ans = self.analyze_with_provider(active_provider, Path(item_data["image_path"]), force_refresh=force_refresh)
                        results[q_id] = ans
                    except Exception:
                        results[q_id] = None
            finally:
                if composite_path.exists():
                    composite_path.unlink(missing_ok=True)

        return results



_ai_service_instance: Optional[AICheckService] = None


def get_ai_check_service() -> AICheckService:
    global _ai_service_instance
    if _ai_service_instance is None:
        _ai_service_instance = AICheckService()
    return _ai_service_instance
