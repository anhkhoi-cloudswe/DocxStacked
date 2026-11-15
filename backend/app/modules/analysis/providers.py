from abc import ABC, abstractmethod
import base64
import os
from pathlib import Path
import random
import time
from typing import Optional
from dotenv import dotenv_values, load_dotenv

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.modules.analysis.gemini_guard import (
    AIRateLimiter,
    DailyQuotaExhaustedError,
    execute_with_timeout,
    get_ai_rate_limiter,
    get_daily_quota_tracker,
    parse_retry_after,
)

logger = get_logger(__name__)
settings = get_settings()


class ProviderAuthError(Exception):
    """Raised when an AI provider returns HTTP 401 Unauthorized or authentication failure."""
    pass


class ProviderRateLimitError(Exception):
    """Raised when an AI provider returns HTTP 429 or rate limit/quota exhausted."""
    pass


class ProviderModelNotFoundError(Exception):
    """Raised when the specified model does not exist (HTTP 404 / NotFound)."""
    pass


class ProviderVisionUnsupportedError(Exception):
    """Raised when the model exists but does not support vision/image inputs."""
    pass


class ProviderNetworkError(Exception):
    """Raised when an AI provider encounters network, connection or timeout error."""
    pass


class ProviderAPIError(Exception):
    """Raised when an AI provider encounters an unrecoverable API error."""
    pass


class VisionProvider(ABC):
    """
    Abstract base class for vision AI providers.
    Supports dynamic models, custom api_key_env, base_url, and automated backoff retry.
    """

    def __init__(
        self,
        name: str,
        model: str,
        api_key_env: str,
        base_url: Optional[str] = None,
        max_retries: int = 4,
        backoff_seconds: float = 2.0,
        api_key: Optional[str] = None,
        timeout_seconds: float = 60.0,
        rate_limiter: Optional[AIRateLimiter] = None,
        skip_quota_check: bool = False,
    ):
        self.name = name
        self.model = model
        self.api_key_env = api_key_env
        self.base_url = base_url
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.timeout_seconds = timeout_seconds
        self.rate_limiter = rate_limiter
        self.skip_quota_check = skip_quota_check
        self._explicit_api_key = api_key.strip() if api_key and len(api_key.strip()) > 3 else None

    def get_api_key(self) -> Optional[str]:
        """
        Retrieve API key: explicit override -> in-memory os.environ -> root .env.
        Allows testing newly saved keys immediately without restarting the backend.
        Never logs or outputs the key value.
        """
        if self._explicit_api_key:
            return self._explicit_api_key

        # 1. In-memory os.environ (runtime updates)
        val = os.environ.get(self.api_key_env)
        if val and len(val.strip()) > 3:
            return val.strip()

        # 2. Check root .env
        root_env = settings.BASE_DIR / ".env"
        if root_env.exists():
            root_vals = dotenv_values(root_env)
            val_file = root_vals.get(self.api_key_env)
            if val_file and len(val_file.strip()) > 3:
                return val_file.strip()

        return None

    def is_available(self) -> bool:
        """Check if provider has a configured API key."""
        return self.get_api_key() is not None

    @abstractmethod
    def call_vision_api(self, image_path: Path, prompt: str, system_prompt: str) -> str:
        """Execute raw API call against the vision model and return text output."""
        pass

    def call_with_retry(self, image_path: Path, prompt: str, system_prompt: str) -> str:
        """
        Execute API call with rate limiter (concurrency=1, 7s interval),
        timeout (60s), 4 retries with exponential backoff + jitter,
        Retry-After header parsing, and daily quota tracking.
        """
        if not self.skip_quota_check:
            quota = get_daily_quota_tracker()
            if not quota.can_call(model=self.model):
                raise DailyQuotaExhaustedError(f"Daily AI call limit reached for model '{self.model}'")

        attempts = self.max_retries + 1
        last_error = None
        rate_limiter = self.rate_limiter or get_ai_rate_limiter(provider_name=self.name)
        skip_throttle = self.backoff_seconds <= 0.05

        for attempt in range(1, attempts + 1):
            try:
                if skip_throttle:
                    res = execute_with_timeout(
                        self.call_vision_api,
                        self.timeout_seconds,
                        image_path,
                        prompt,
                        system_prompt,
                    )
                else:
                    with rate_limiter:
                        res = execute_with_timeout(
                            self.call_vision_api,
                            self.timeout_seconds,
                            image_path,
                            prompt,
                            system_prompt,
                        )
                if not self.skip_quota_check:
                    quota.record_call(model=self.model)
                return res
            except TimeoutError as te:
                last_error = ProviderNetworkError(f"Provider '{self.name}' timed out after {self.timeout_seconds}s")
                if attempt < attempts:
                    jitter = random.uniform(0.1, 1.0)
                    sleep_time = self.backoff_seconds * (2 ** (attempt - 1)) + jitter
                    logger.warning(
                        f"Provider '{self.name}' timed out (attempt {attempt}/{attempts}). "
                        f"Retrying in {sleep_time:.1f}s..."
                    )
                    time.sleep(sleep_time)
                else:
                    logger.warning(f"Provider '{self.name}' exhausted timeout retries.")
                    raise last_error
            except ProviderRateLimitError as e:
                last_error = e
                # Check if it was daily quota
                if "daily" in str(e).lower() or "day" in str(e).lower():
                    quota.mark_exhausted(str(e), model=self.model)
                    raise DailyQuotaExhaustedError(f"Provider {self.name} daily quota exhausted: {e}") from e

                if attempt < attempts:
                    retry_after = parse_retry_after(e)
                    jitter = random.uniform(0.1, 1.0)
                    base_sleep = self.backoff_seconds * (2 ** (attempt - 1)) + jitter
                    sleep_time = max(base_sleep, retry_after) if retry_after else base_sleep
                    logger.warning(
                        f"Provider '{self.name}' hit 429 Rate Limit (attempt {attempt}/{attempts}). "
                        f"Retry-After: {retry_after}s. Sleeping for {sleep_time:.1f}s..."
                    )
                    time.sleep(sleep_time)
                else:
                    logger.warning(f"Provider '{self.name}' exhausted rate limit retries.")
                    raise
            except ProviderNetworkError as e:
                last_error = e
                if attempt < attempts:
                    retry_after = parse_retry_after(e)
                    jitter = random.uniform(0.1, 1.0)
                    base_sleep = self.backoff_seconds * (2 ** (attempt - 1)) + jitter
                    sleep_time = max(base_sleep, retry_after) if retry_after else base_sleep
                    logger.warning(
                        f"Provider '{self.name}' hit network/server error (attempt {attempt}/{attempts}). "
                        f"Retrying in {sleep_time:.1f}s..."
                    )
                    time.sleep(sleep_time)
                else:
                    logger.warning(f"Provider '{self.name}' exhausted network retries.")
                    raise
            except ProviderAuthError:
                raise
            except ProviderAPIError:
                raise
            except Exception as e:
                logger.warning(f"Provider '{self.name}' unexpected call error: {type(e).__name__}")
                raise ProviderAPIError(f"Unexpected error in {self.name}: {type(e).__name__}") from e

        if last_error:
            raise last_error
        raise ProviderAPIError(f"Provider {self.name} failed without explicit error.")


class AnthropicProvider(VisionProvider):
    """Vision provider using Anthropic API (Claude 3.5 Haiku, Sonnet, etc.)."""

    def __init__(
        self,
        name: str = "anthropic",
        model: str = "claude-3-5-haiku-20241022",
        api_key_env: str = "ANTHROPIC_API_KEY",
        base_url: Optional[str] = None,
        max_retries: int = 4,
        backoff_seconds: float = 2.0,
        api_key: Optional[str] = None,
        timeout_seconds: float = 60.0,
    ):
        super().__init__(name, model, api_key_env, base_url, max_retries, backoff_seconds, api_key=api_key, timeout_seconds=timeout_seconds)
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        api_key = self.get_api_key()
        if not api_key:
            raise ProviderAPIError(f"Missing API key for provider {self.name} ({self.api_key_env})")
        import anthropic
        kwargs = {"api_key": api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def call_vision_api(self, image_path: Path, prompt: str, system_prompt: str) -> str:
        import anthropic

        client = self._get_client()
        with open(image_path, "rb") as f:
            b64_image = base64.b64encode(f.read()).decode("utf-8")

        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": b64_image,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
            return response.content[0].text
        except anthropic.AuthenticationError as e:
            raise ProviderAuthError(f"Anthropic 401 Unauthorized: {e}") from e
        except anthropic.RateLimitError as e:
            raise ProviderRateLimitError(f"Anthropic 429: {e.message}") from e
        except (anthropic.APIConnectionError, anthropic.InternalServerError) as e:
            raise ProviderNetworkError(f"Anthropic connection error: {e}") from e
        except anthropic.APIError as e:
            if getattr(e, "status_code", None) == 429:
                raise ProviderRateLimitError(f"Anthropic 429: {e}") from e
            if getattr(e, "status_code", None) in (401, 403):
                raise ProviderAuthError(f"Anthropic 401: {e}") from e
            raise ProviderAPIError(f"Anthropic API error: {e}") from e


class GeminiProvider(VisionProvider):
    """Vision provider using Google Gemini API (gemini-2.5-flash, etc.)."""

    def __init__(
        self,
        name: str = "gemini",
        model: str = "gemini-2.5-flash",
        api_key_env: str = "GEMINI_API_KEY",
        base_url: Optional[str] = None,
        max_retries: int = 4,
        backoff_seconds: float = 2.0,
        api_key: Optional[str] = None,
        timeout_seconds: float = 60.0,
    ):
        super().__init__(name, model, api_key_env, base_url, max_retries, backoff_seconds, api_key=api_key, timeout_seconds=timeout_seconds)
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        api_key = self.get_api_key()
        if not api_key:
            raise ProviderAPIError(f"Missing API key for provider {self.name} ({self.api_key_env})")
        from google import genai
        http_opts = {"api_version": "v1beta"}
        if self.base_url:
            http_opts["base_url"] = self.base_url
        self._client = genai.Client(api_key=api_key, http_options=http_opts)
        return self._client

    def call_vision_api(self, image_path: Path, prompt: str, system_prompt: str) -> str:
        from google.genai import types, errors

        client = self._get_client()
        with open(image_path, "rb") as f:
            img_bytes = f.read()

        combined_prompt = f"{system_prompt}\n\n{prompt}"
        try:
            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents=[
                        types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                        combined_prompt,
                    ],
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                    ),
                )
                return response.text or ""
            except Exception as json_err:
                if "JSON mode is not enabled" in str(json_err) or "INVALID_ARGUMENT" in str(json_err):
                    response = client.models.generate_content(
                        model=self.model,
                        contents=[
                            types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                            combined_prompt,
                        ],
                        config=types.GenerateContentConfig(temperature=0.0),
                    )
                    return response.text or ""
                raise
        except errors.APIError as e:
            code = getattr(e, "code", getattr(e, "status_code", None))
            if code in (401, 403) or "API_KEY_INVALID" in str(e).upper():
                raise ProviderAuthError(f"Gemini Auth Error: {e}") from e
            if code == 429 or "RESOURCE_EXHAUSTED" in str(e).upper():
                raise ProviderRateLimitError(f"Gemini 429: {e}") from e
            if code in (500, 502, 503, 504):
                raise ProviderNetworkError(f"Gemini server error {code}: {e}") from e
            raise ProviderAPIError(f"Gemini API error: {e}") from e
        except Exception as e:
            err_str = str(e).lower()
            if "api key" in err_str or "unauthorized" in err_str:
                raise ProviderAuthError(f"Gemini Auth Error: {e}") from e
            if "connection" in err_str or "timeout" in err_str or "network" in err_str:
                raise ProviderNetworkError(f"Gemini network error: {e}") from e
            raise ProviderAPIError(f"Gemini error: {e}") from e


class OpenAICompatibleProvider(VisionProvider):
    """
    Vision provider compatible with OpenAI API standard
    (OpenAI, DeepSeek, OpenRouter, Groq, Ollama, etc.).
    """

    def __init__(
        self,
        name: str = "openai_compatible",
        model: str = "gpt-4o-mini",
        api_key_env: str = "OPENAI_API_KEY",
        base_url: Optional[str] = None,
        max_retries: int = 4,
        backoff_seconds: float = 2.0,
        api_key: Optional[str] = None,
        timeout_seconds: float = 60.0,
    ):
        super().__init__(name, model, api_key_env, base_url, max_retries, backoff_seconds, api_key=api_key, timeout_seconds=timeout_seconds)
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        api_key = self.get_api_key()
        if not api_key:
            raise ProviderAPIError(f"Missing API key for provider {self.name} ({self.api_key_env})")
        from openai import OpenAI
        kwargs = {"api_key": api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._client = OpenAI(**kwargs)
        return self._client

    def call_vision_api(self, image_path: Path, prompt: str, system_prompt: str) -> str:
        import openai

        client = self._get_client()
        with open(image_path, "rb") as f:
            b64_image = base64.b64encode(f.read()).decode("utf-8")

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64_image}",
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        ]

        # First attempt with json_object format, fallback if unsupported by provider
        try:
            response = client.chat.completions.create(
                model=self.model,
                temperature=0.0,
                messages=messages,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content or ""
        except openai.AuthenticationError as e:
            raise ProviderAuthError(f"OpenAI 401 Unauthorized: {e}") from e
        except openai.RateLimitError as e:
            raise ProviderRateLimitError(f"OpenAI 429: {e}") from e
        except (openai.APIConnectionError, openai.InternalServerError) as e:
            raise ProviderNetworkError(f"OpenAI connection error: {e}") from e
        except openai.BadRequestError as e:
            # Some providers do not support response_format={"type": "json_object"}
            if "response_format" in str(e).lower():
                try:
                    response = client.chat.completions.create(
                        model=self.model,
                        temperature=0.0,
                        messages=messages,
                    )
                    return response.choices[0].message.content or ""
                except Exception as inner_e:
                    raise ProviderAPIError(f"OpenAI fallback error: {inner_e}") from inner_e
            raise ProviderAPIError(f"OpenAI BadRequest: {e}") from e
        except openai.APIError as e:
            if getattr(e, "status_code", None) == 429:
                raise ProviderRateLimitError(f"OpenAI 429: {e}") from e
            raise ProviderAPIError(f"OpenAI API error: {e}") from e


def create_provider(
    name: str,
    model: str,
    api_key_env: str,
    base_url: Optional[str] = None,
    max_retries: int = 4,
    backoff_seconds: float = 2.0,
    api_key: Optional[str] = None,
    timeout_seconds: float = 60.0,
) -> VisionProvider:
    """Factory creating appropriate VisionProvider instance based on name."""
    norm_name = name.strip().lower()
    if "anthropic" in norm_name or "claude" in norm_name:
        return AnthropicProvider(
            name=name,
            model=model,
            api_key_env=api_key_env,
            base_url=base_url,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    elif "gemini" in norm_name or "google" in norm_name:
        return GeminiProvider(
            name=name,
            model=model,
            api_key_env=api_key_env,
            base_url=base_url,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    elif "groq" in norm_name:
        return OpenAICompatibleProvider(
            name=name,
            model=model or "llama-3.2-11b-vision-preview",
            api_key_env=api_key_env or "GROQ_API_KEY",
            base_url=base_url or "https://api.groq.com/openai/v1",
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    elif "openrouter" in norm_name:
        return OpenAICompatibleProvider(
            name=name,
            model=model or "meta-llama/llama-3.2-11b-vision-instruct",
            api_key_env=api_key_env or "OPENROUTER_API_KEY",
            base_url=base_url or "https://openrouter.ai/api/v1",
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    else:
        # Default to OpenAI-compatible
        return OpenAICompatibleProvider(
            name=name,
            model=model,
            api_key_env=api_key_env,
            base_url=base_url,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
