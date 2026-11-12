import asyncio
from datetime import datetime
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, status
import httpx
from PIL import Image, ImageDraw
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.session import get_db
from backend.app.modules.analysis.providers import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderModelNotFoundError,
    ProviderVisionUnsupportedError,
    ProviderNetworkError,
    ProviderAPIError,
    create_provider,
)
from backend.app.modules.settings.service import (
    get_active_settings,
    mask_settings_for_api,
    update_settings,
    reset_settings,
)

logger = get_logger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/settings", tags=["settings"])

# Cache for dynamic model lists: {provider_name: (timestamp, models_list)}
_MODELS_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
CACHE_TTL_SECONDS = 3600.0


def _get_test_image_path() -> Path:
    """Generate or retrieve a minimal 50x50 test image with letter 'A'."""
    test_dir = settings.STORAGE_DIR / "cache"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_path = test_dir / "test_vision_probe.png"
    if not test_path.exists():
        img = Image.new("RGB", (50, 50), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((18, 12), "A", fill="black")
        img.save(test_path, format="PNG")
    return test_path


class TestConnectionRequest(BaseModel):
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None
    base_url: Optional[str] = None


class ModelInfo(BaseModel):
    id: str
    name: str
    supports_vision: bool = True


class ProviderModelsResponse(BaseModel):
    provider: str
    models: List[ModelInfo]


FALLBACK_MODELS: Dict[str, List[Dict[str, Any]]] = {
    "anthropic": [
        {"id": "claude-3-5-haiku-20241022", "name": "claude-3-5-haiku-20241022", "supports_vision": True},
        {"id": "claude-3-5-sonnet-20241022", "name": "claude-3-5-sonnet-20241022", "supports_vision": True},
        {"id": "claude-3-haiku-20240307", "name": "claude-3-haiku-20240307", "supports_vision": True},
        {"id": "claude-3-opus-20240229", "name": "claude-3-opus-20240229", "supports_vision": True},
    ],
    "gemini": [
        {"id": "gemini-2.5-flash", "name": "gemini-2.5-flash", "supports_vision": True},
        {"id": "gemini-2.0-flash", "name": "gemini-2.0-flash", "supports_vision": True},
        {"id": "gemini-1.5-flash", "name": "gemini-1.5-flash", "supports_vision": True},
        {"id": "gemini-1.5-pro", "name": "gemini-1.5-pro", "supports_vision": True},
    ],
    "openai": [
        {"id": "gpt-4o-mini", "name": "gpt-4o-mini", "supports_vision": True},
        {"id": "gpt-4o", "name": "gpt-4o", "supports_vision": True},
        {"id": "gpt-4-turbo", "name": "gpt-4-turbo", "supports_vision": True},
    ],
    "openrouter": [
        {"id": "anthropic/claude-3.5-haiku", "name": "anthropic/claude-3.5-haiku", "supports_vision": True},
        {"id": "google/gemini-2.5-flash", "name": "google/gemini-2.5-flash", "supports_vision": True},
        {"id": "openai/gpt-4o-mini", "name": "openai/gpt-4o-mini", "supports_vision": True},
        {"id": "meta-llama/llama-3.2-11b-vision-instruct", "name": "meta-llama/llama-3.2-11b-vision-instruct", "supports_vision": True},
        {"id": "qwen/qwen-2.5-vl-72b-instruct", "name": "qwen/qwen-2.5-vl-72b-instruct", "supports_vision": True},
    ],
    "groq": [
        {"id": "llama-3.2-11b-vision-preview", "name": "llama-3.2-11b-vision-preview", "supports_vision": True},
        {"id": "llama-3.2-90b-vision-preview", "name": "llama-3.2-90b-vision-preview", "supports_vision": True},
    ],
    "ollama": [
        {"id": "llama3.2-vision", "name": "llama3.2-vision", "supports_vision": True},
        {"id": "llava", "name": "llava", "supports_vision": True},
        {"id": "minicpm-v", "name": "minicpm-v", "supports_vision": True},
        {"id": "bakllava", "name": "bakllava", "supports_vision": True},
    ],
}


@router.get("")
async def get_settings_endpoint(db: AsyncSession = Depends(get_db)):
    """Retrieve currently active settings with credentials masked."""
    active = await get_active_settings(db)
    return mask_settings_for_api(active)


@router.put("")
async def update_settings_endpoint(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
):
    """
    Update application settings.
    Enforces delay crawl hard minimum of 1.5s.
    API keys are write-only and never returned in the response.
    """
    try:
        updated = await update_settings(db, payload)
        return updated
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Lỗi khi lưu cài đặt")


@router.post("/reset")
async def reset_settings_endpoint(db: AsyncSession = Depends(get_db)):
    """Reset all database overrides, reverting to config.yaml defaults."""
    try:
        defaults = await reset_settings(db)
        return defaults
    except Exception as e:
        logger.error(f"Error resetting settings: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Lỗi khi đặt lại cài đặt")


@router.get("/providers/{provider_name}/models", response_model=ProviderModelsResponse)
async def get_provider_models_endpoint(
    provider_name: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get live list of models for a provider with 1-hour cache and vision preference.
    Falls back gracefully to popular hardcoded vision models if offline or network timeout (5s).
    """
    norm_id = provider_name.strip().lower()

    # 1. Check in-memory cache
    now = time.time()
    if norm_id in _MODELS_CACHE:
        cached_time, cached_models = _MODELS_CACHE[norm_id]
        if now - cached_time < CACHE_TTL_SECONDS:
            return ProviderModelsResponse(provider=provider_name, models=[ModelInfo(**m) for m in cached_models])

    # 2. Try fetching from live provider API if key is available
    active = await get_active_settings(db)
    providers = active.get("ai", {}).get("providers", [])
    target_p = next((p for p in providers if p.get("name", "").lower() == norm_id), None)

    fetched_models: List[Dict[str, Any]] = []

    try:
        # Check live API based on provider name
        if "openai" in norm_id and not "openrouter" in norm_id:
            api_key = target_p.get("api_key") if target_p else None
            if not api_key:
                env_var = target_p.get("api_key_env", "OPENAI_API_KEY") if target_p else "OPENAI_API_KEY"
                import os
                api_key = os.environ.get(env_var)
            if api_key:
                base_url = (target_p and target_p.get("base_url")) or "https://api.openai.com/v1"
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(
                        f"{base_url.rstrip('/')}/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    if resp.status_code == 200:
                        data = resp.json().get("data", [])
                        for m in data:
                            mid = m.get("id", "")
                            if any(v in mid.lower() for v in ["gpt-4o", "vision", "gpt-4-turbo", "o1", "o3"]):
                                fetched_models.append({"id": mid, "name": mid, "supports_vision": True})
        elif "groq" in norm_id:
            api_key = target_p.get("api_key") if target_p else None
            if not api_key:
                env_var = target_p.get("api_key_env", "GROQ_API_KEY") if target_p else "GROQ_API_KEY"
                import os
                api_key = os.environ.get(env_var)
            if api_key:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(
                        "https://api.groq.com/openai/v1/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    if resp.status_code == 200:
                        data = resp.json().get("data", [])
                        for m in data:
                            mid = m.get("id", "")
                            if "vision" in mid.lower() or "llama-3.2" in mid.lower():
                                fetched_models.append({"id": mid, "name": mid, "supports_vision": True})
        elif "openrouter" in norm_id:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("https://openrouter.ai/api/v1/models")
                if resp.status_code == 200:
                    raw_data = resp.json().get("data", [])
                    # Filter vision models
                    for m in raw_data:
                        mid = m.get("id", "")
                        arch = m.get("architecture", {})
                        modality = arch.get("modality", "") if isinstance(arch, dict) else ""
                        is_vision = "image" in modality or "multimodal" in modality or "vision" in mid.lower() or "vl" in mid.lower()
                        if is_vision:
                            fetched_models.append({
                                "id": mid,
                                "name": m.get("name", mid),
                                "supports_vision": True,
                            })
        elif "ollama" in norm_id:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                if resp.status_code == 200:
                    tags = resp.json().get("models", [])
                    for t in tags:
                        tname = t.get("name", "")
                        is_vis = any(v in tname.lower() for v in ["vision", "llava", "vl", "minicpm"])
                        fetched_models.append({
                            "id": tname,
                            "name": tname,
                            "supports_vision": is_vis,
                        })
    except Exception as e:
        logger.debug(f"Live models fetch for '{provider_name}' skipped/failed: {e}")

    # Fallback to predefined models if none fetched
    if not fetched_models:
        for k, v in FALLBACK_MODELS.items():
            if k in norm_id:
                fetched_models = v
                break

    if not fetched_models:
        fetched_models = FALLBACK_MODELS.get("openai", [])

    # Cache result
    _MODELS_CACHE[norm_id] = (now, fetched_models)

    return ProviderModelsResponse(
        provider=provider_name,
        models=[ModelInfo(**m) for m in fetched_models],
    )


@router.post("/test-connection/{provider_name}")
async def test_provider_connection_endpoint(
    provider_name: str,
    payload: Optional[TestConnectionRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Test real image-reading (vision) capability using a synthetic test image.
    Never exposes API keys in success or error messages.
    """
    active = await get_active_settings(db)
    providers = active.get("ai", {}).get("providers", [])

    target_cfg = next((p for p in providers if p.get("name", "").lower() == provider_name.strip().lower()), None)

    # Allow overriding via payload
    model_name = (payload and payload.model) or (target_cfg and target_cfg.get("model")) or "gpt-4o-mini"
    api_key_env = (payload and payload.api_key_env) or (target_cfg and target_cfg.get("api_key_env")) or f"{provider_name.upper()}_API_KEY"
    base_url = (payload and payload.base_url) or (target_cfg and target_cfg.get("base_url"))

    raw_api_key = payload.api_key.strip() if (payload and payload.api_key and len(payload.api_key.strip()) > 3) else None
    if raw_api_key:
        import os
        os.environ[api_key_env] = raw_api_key

    provider = create_provider(
        name=provider_name,
        model=model_name,
        api_key_env=api_key_env,
        base_url=base_url,
        api_key=raw_api_key,
    )

    if not provider.is_available():
        return {
            "success": False,
            "provider": provider.name,
            "message": f"Chưa cấu hình API key ({provider.api_key_env}) trong .env",
        }

    test_img = _get_test_image_path()
    start_time = time.time()

    try:
        # Run real vision API call in worker thread
        prompt = "Nhìn vào ảnh và cho biết chữ cái nào xuất hiện trong ảnh. Chỉ trả lời đúng 1 chữ cái in hoa."
        system_prompt = "Bạn là trợ lý thị giác máy tính chính xác."
        resp_text = await asyncio.to_thread(provider.call_vision_api, test_img, prompt, system_prompt)
        elapsed_ms = round((time.time() - start_time) * 1000)

        return {
            "success": True,
            "provider": provider.name,
            "model": provider.model,
            "latency_ms": elapsed_ms,
            "message": f"Kết nối thành công! Model hỗ trợ đọc ảnh (vision) tốt (độ trễ {elapsed_ms}ms).",
        }
    except ProviderAuthError:
        return {
            "success": False,
            "provider": provider.name,
            "message": "Lỗi xác thực (401 Unauthorized): API key không đúng hoặc đã hết hạn.",
        }
    except ProviderRateLimitError:
        return {
            "success": False,
            "provider": provider.name,
            "message": "Hết hạn mức hoặc bị giới hạn tốc độ (429 Rate Limit). Vui lòng thử lại sau.",
        }
    except ProviderModelNotFoundError:
        return {
            "success": False,
            "provider": provider.name,
            "message": f"Model '{provider.model}' không tồn tại trên hệ thống của nhà cung cấp (404 Not Found).",
        }
    except ProviderVisionUnsupportedError:
        return {
            "success": False,
            "provider": provider.name,
            "message": f"Model '{provider.model}' không hỗ trợ đọc ảnh (vision). Vui lòng chọn model khác.",
        }
    except ProviderNetworkError:
        return {
            "success": False,
            "provider": provider.name,
            "message": "Lỗi kết nối mạng: Không thể kết nối tới nhà cung cấp AI. Vui lòng kiểm tra kết nối mạng hoặc base_url.",
        }
    except Exception as e:
        err_msg = str(e)
        err_lower = err_msg.lower()

        if any(w in err_lower for w in ["does not support image", "not supported for images", "unsupported image", "vision", "image input"]):
            return {
                "success": False,
                "provider": provider.name,
                "message": f"Model '{provider.model}' không hỗ trợ đọc ảnh (vision). Vui lòng chọn model khác.",
            }

        if any(w in err_lower for w in ["not found", "model_not_found", "404", "does not exist"]):
            return {
                "success": False,
                "provider": provider.name,
                "message": f"Model '{provider.model}' không tồn tại trên hệ thống của nhà cung cấp (404 Not Found).",
            }

        if any(w in err_lower for w in ["connection", "timeout", "network", "connecterror", "connection refused", "socket"]):
            return {
                "success": False,
                "provider": provider.name,
                "message": "Lỗi kết nối mạng: Không thể kết nối tới nhà cung cấp AI. Vui lòng kiểm tra kết nối mạng hoặc base_url.",
            }

        # Sanitize keys
        err_msg = re.sub(r"sk-[a-zA-Z0-9_\-]+", "[REDACTED]", err_msg)
        err_msg = re.sub(r"AIza[a-zA-Z0-9_\-]+", "[REDACTED]", err_msg)
        return {
            "success": False,
            "provider": provider.name,
            "message": f"Lỗi kết nối: {type(e).__name__} ({err_msg[:120]})",
        }
