import copy
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from dotenv import dotenv_values, load_dotenv
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Setting

logger = get_logger(__name__)
app_settings = get_settings()


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override dictionary into base dictionary."""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def get_default_settings() -> Dict[str, Any]:
    """Load default settings directly from config.yaml."""
    yaml_cfg = app_settings.yaml_config

    ai_cfg = getattr(yaml_cfg, "ai", None)
    providers_list = []
    if ai_cfg and getattr(ai_cfg, "providers", None):
        for p in ai_cfg.providers:
            providers_list.append({
                "name": p.name,
                "model": p.model,
                "api_key_env": p.api_key_env,
                "base_url": p.base_url,
            })
    else:
        providers_list = [
            {"name": "anthropic", "model": "claude-3-5-haiku-20241022", "api_key_env": "ANTHROPIC_API_KEY", "base_url": None},
            {"name": "gemini", "model": "gemini-2.5-flash", "api_key_env": "GEMINI_API_KEY", "base_url": None},
            {"name": "openai_compatible", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY", "base_url": "https://api.openai.com/v1"},
        ]

    return {
        "export": {
            "formats": list(getattr(yaml_cfg.export, "formats", ["docx"])),
            "image_width_cm": float(getattr(yaml_cfg.export, "image_width_cm", 16.51)),
            "image_zoom_percent": int(getattr(yaml_cfg.export, "image_zoom_percent", 100)),
            "highlight_low_confidence": bool(getattr(yaml_cfg.export, "highlight_low_confidence", True)),
            "answer_format": "letter_keyword",  # 'letter' or 'letter_keyword'
            "show_question_number": True,  # 'Câu 1:', 'Câu 2:' prefix
            "show_separator_line": True,  # '===' double border divider
            "page_size": "letter",  # Standard Letter 8.5 x 11 inch
            "merge": False,  # whether to merge multiple exams into one docx
        },
        "ai": {
            "enabled": bool(getattr(ai_cfg, "enabled", True) if ai_cfg else getattr(yaml_cfg.analysis, "use_ai", True)),
            "ensemble": bool(getattr(ai_cfg, "ensemble", False) if ai_cfg else False),
            "max_ai_calls": int(getattr(ai_cfg, "max_ai_calls", 300) if ai_cfg else 300),
            "backoff_seconds": float(getattr(ai_cfg, "backoff_seconds", 2.0) if ai_cfg else 2.0),
            "max_retries": int(getattr(ai_cfg, "max_retries", 2) if ai_cfg else 2),
            "providers": providers_list,
        },
        "voting": {
            "confident_min_ratio": float(getattr(yaml_cfg.analysis, "confident_min_ratio", 0.7)),
            "confident_min_voters": int(getattr(yaml_cfg.analysis, "confident_min_comments", 2)),
            "multi_choice_threshold": float(getattr(yaml_cfg.analysis, "multi_choice_threshold", 0.5)),
            "vote_weight": str(getattr(yaml_cfg.analysis, "vote_weight", "log_upvotes")),
            "ai_weight": 1.0,
        },
        "crawl": {
            "delay_seconds": list(getattr(yaml_cfg.crawl, "delay_seconds", [1.5, 4.0])),
            "concurrency": int(getattr(yaml_cfg.crawl, "concurrency", 1)),
            "headless": bool(getattr(yaml_cfg.crawl, "headless", False)),
            "max_retries": int(getattr(yaml_cfg.crawl, "max_retries", 3)),
            "default_count": int(getattr(yaml_cfg.exam, "default_count", 4)),
        },
    }


async def get_db_settings(db: AsyncSession) -> Dict[str, Any]:
    """Retrieve saved settings overrides from SQLite settings table."""
    result = await db.execute(select(Setting))
    rows = result.scalars().all()
    overrides: Dict[str, Any] = {}
    for r in rows:
        overrides[r.key] = r.value
    return overrides


async def get_active_settings(
    db: Optional[AsyncSession] = None,
    job_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Get active settings using the strict priority hierarchy:
      1. Default (config.yaml)
      2. Saved settings (database settings table)
      3. Job-specific options (job snapshot)
    """
    settings_dict = get_default_settings()

    if db is not None:
        try:
            db_overrides = await get_db_settings(db)
            if db_overrides:
                settings_dict = _deep_merge(settings_dict, db_overrides)
        except Exception as e:
            logger.warning(f"Could not load settings from DB: {e}")

    if job_options:
        settings_dict = _deep_merge(settings_dict, job_options)

    return settings_dict


def validate_settings(settings_data: Dict[str, Any]) -> None:
    """
    Strict validation of settings with hard limits.
    Specifically enforces crawl delay >= 1.5s to protect against bot detection.
    """
    # 1. Crawl Validations
    if "crawl" in settings_data:
        crawl = settings_data["crawl"]
        if "delay_seconds" in crawl:
            delays = crawl["delay_seconds"]
            if not isinstance(delays, (list, tuple)) or len(delays) < 2:
                raise ValueError("Tốc độ cào (delay_seconds) phải gồm 2 giá trị [min_seconds, max_seconds]")
            min_d = float(delays[0])
            max_d = float(delays[1])
            if min_d < 1.5:
                raise ValueError(
                    f"Giới hạn tối thiểu cứng của tốc độ cào là 1.5s (bạn đang đặt {min_d}s). "
                    "Không được đặt dưới 1.5s để tránh bị Cloudflare / XenForo chặn bot."
                )
            if max_d < min_d:
                raise ValueError(f"Độ trễ tối đa ({max_d}s) không được nhỏ hơn độ trễ tối thiểu ({min_d}s)")

        if "concurrency" in crawl and int(crawl["concurrency"]) < 1:
            raise ValueError("Số luồng cào đồng thời (concurrency) tối thiểu phải là 1")

    # 2. Voting Validations
    if "voting" in settings_data:
        v = settings_data["voting"]
        if "confident_min_ratio" in v:
            ratio = float(v["confident_min_ratio"])
            if not (0.0 < ratio <= 1.0):
                raise ValueError("Tỷ lệ tự tin (confident_min_ratio) phải nằm trong khoảng (0.0, 1.0]")
        if "confident_min_voters" in v and int(v["confident_min_voters"]) < 1:
            raise ValueError("Số người bỏ phiếu tối thiểu để tự tin phải >= 1")
        if "multi_choice_threshold" in v:
            m_thresh = float(v["multi_choice_threshold"])
            if not (0.1 <= m_thresh <= 1.0):
                raise ValueError("Ngưỡng tính nhiều đáp án (multi_choice_threshold) phải từ 0.1 đến 1.0")

    # 3. AI Validations
    if "ai" in settings_data:
        ai = settings_data["ai"]
        if "max_ai_calls" in ai and int(ai["max_ai_calls"]) < 1:
            raise ValueError("Trần số lượt gọi AI (max_ai_calls) phải >= 1")
        if "backoff_seconds" in ai and float(ai["backoff_seconds"]) < 0.1:
            raise ValueError("Thời gian chờ backoff phải >= 0.1s")

    # 4. Export Validations
    if "export" in settings_data:
        exp = settings_data["export"]
        if "image_width_cm" in exp:
            w = float(exp["image_width_cm"])
            if not (5.0 <= w <= 25.0):
                raise ValueError("Chiều rộng ảnh trong Word phải nằm trong khoảng 5.0cm đến 25.0cm")


def save_api_key_to_env(env_var_name: str, key_value: str) -> None:
    """
    Persist API key securely to the single root .env file without logging or printing.
    """
    clean_val = key_value.strip()
    root_env = app_settings.BASE_DIR / ".env"

    try:
        if not root_env.exists():
            root_env.write_text(f"{env_var_name}={clean_val}\n", encoding="utf-8")
        else:
            content = root_env.read_text(encoding="utf-8")
            pattern = re.compile(rf"^{re.escape(env_var_name)}=.*$", re.MULTILINE)
            if pattern.search(content):
                new_content = pattern.sub(f"{env_var_name}={clean_val}", content)
            else:
                new_content = content.rstrip() + f"\n{env_var_name}={clean_val}\n"
            root_env.write_text(new_content, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not update .env file: {e}")

    # Update in-memory os.environ
    os.environ[env_var_name] = clean_val


def mask_settings_for_api(settings_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mask all sensitive credentials before returning settings to the frontend.
    Never returns raw API keys; returns boolean 'has_api_key' and status 'configured'.
    """
    safe_data = copy.deepcopy(settings_dict)

    root_env = app_settings.BASE_DIR / ".env"
    root_vals = dotenv_values(root_env) if root_env.exists() else {}

    if "ai" in safe_data and "providers" in safe_data["ai"]:
        for p in safe_data["ai"]["providers"]:
            env_var = p.get("api_key_env", "")
            # Check if key is configured in root .env or system env
            val_env = root_vals.get(env_var)
            val_sys = os.environ.get(env_var, "")

            effective_val = val_env if (val_env and len(val_env.strip()) > 3) else (val_sys if (val_sys and len(val_sys.strip()) > 3) else "")
            if effective_val:
                has_key = True
                key_source = "Đã lưu trong .env" if val_env else "Biến môi trường hệ thống"
                tail = effective_val[-4:] if len(effective_val) >= 4 else effective_val
                masked_key = f"••••{tail}"
            else:
                has_key = False
                key_source = None
                masked_key = None

            p.pop("api_key", None)  # Ensure no key field exists
            p["has_api_key"] = has_key
            p["masked_key"] = masked_key
            p["status"] = "configured" if has_key else "not_configured"
            p["key_source"] = key_source
            if "enabled" not in p:
                p["enabled"] = True

    return safe_data


async def update_settings(db: AsyncSession, new_settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate, save API keys to .env, persist section overrides to DB, and return masked active settings.
    """
    validate_settings(new_settings)

    clean_settings = copy.deepcopy(new_settings)

    # Extract and persist API keys for providers
    if "ai" in clean_settings and "providers" in clean_settings["ai"]:
        for p in clean_settings["ai"]["providers"]:
            api_key = p.pop("api_key", None)
            env_var = p.get("api_key_env")
            if api_key and isinstance(api_key, str) and len(api_key.strip()) > 3:
                save_api_key_to_env(env_var, api_key.strip())

    # Save to database
    sections = ["export", "ai", "voting", "crawl"]
    for sec in sections:
        if sec in clean_settings:
            val = clean_settings[sec]
            existing = await db.get(Setting, sec)
            if existing:
                existing.value = val
            else:
                db.add(Setting(key=sec, value=val))

    await db.commit()

    # Invalidate cached AI check service instance so new provider config is active immediately
    from backend.app.modules.analysis import ai_check
    ai_check._ai_service_instance = None

    active = await get_active_settings(db)
    return mask_settings_for_api(active)


async def reset_settings(db: AsyncSession) -> Dict[str, Any]:
    """
    Reset settings to config.yaml defaults by clearing database overrides.
    """
    await db.execute(delete(Setting))
    await db.commit()

    from backend.app.modules.analysis import ai_check
    ai_check._ai_service_instance = None

    active = await get_active_settings(db)
    return mask_settings_for_api(active)

