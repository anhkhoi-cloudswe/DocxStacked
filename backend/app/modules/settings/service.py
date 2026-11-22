import copy
import json
import os
from pathlib import Path
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from dotenv import dotenv_values, load_dotenv
from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Setting, Exam, Question

logger = get_logger(__name__)
app_settings = get_settings()


def get_invalid_key_providers_file() -> Path:
    return get_settings().STORAGE_DIR / "cache" / "ai_invalid_providers.json"


def get_invalid_key_providers() -> Set[str]:
    """Retrieve set of provider names whose API key returned 401 Unauthorized."""
    f = get_invalid_key_providers_file()
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(data)
        except Exception as e:
            logger.warning(f"Could not read invalid providers file: {e}")
    return set()


def record_invalid_key_provider(provider_name: str) -> None:
    """Persist provider name as having an invalid API key (401)."""
    f = get_invalid_key_providers_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        items = get_invalid_key_providers()
        items.add(provider_name.strip().lower())
        f.write_text(json.dumps(list(items), indent=2), encoding="utf-8")
        logger.info(f"Recorded invalid API key for provider '{provider_name}'.")
    except Exception as e:
        logger.warning(f"Could not persist invalid provider: {e}")


def get_key_validation_history_file() -> Path:
    return app_settings.STORAGE_DIR / "cache" / "ai_keys_validation.json"


def get_key_validation_history() -> Dict[str, Dict[str, Any]]:
    f = get_key_validation_history_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Could not read key validation history file: {e}")
    return {}


def record_key_validation_result(provider_name: str, valid: bool, message: str = "") -> None:
    f = get_key_validation_history_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        data = get_key_validation_history()
        now_dt = datetime.now()
        data[provider_name.strip().lower()] = {
            "valid": valid,
            "message": message,
            "timestamp": now_dt.isoformat(),
            "time_formatted": now_dt.strftime("%H:%M"),
        }
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not save key validation history: {e}")


def clear_invalid_key_provider(provider_name: str) -> None:
    """Remove provider from invalid key set after user updates API key."""
    f = get_invalid_key_providers_file()
    if f.exists():
        try:
            items = get_invalid_key_providers()
            norm = provider_name.strip().lower()
            if norm in items:
                items.remove(norm)
                f.write_text(json.dumps(list(items), indent=2), encoding="utf-8")
                logger.info(f"Cleared invalid API key status for provider '{provider_name}'.")
        except Exception as e:
            logger.warning(f"Could not update invalid providers file: {e}")
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
                "base_url": getattr(p, "base_url", None),
                "enabled": getattr(p, "enabled", False),
            })
    else:
        providers_list = [
            {"name": "gemini", "model": "gemini-2.5-flash", "api_key_env": "GEMINI_API_KEY", "base_url": None, "enabled": True},
            {"name": "groq", "model": "llama-3.2-11b-vision-preview", "api_key_env": "GROQ_API_KEY", "base_url": "https://api.groq.com/openai/v1", "enabled": False},
            {"name": "anthropic", "model": "claude-3-5-haiku-20241022", "api_key_env": "ANTHROPIC_API_KEY", "base_url": None, "enabled": False},
            {"name": "openai_compatible", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY", "base_url": "https://api.openai.com/v1", "enabled": False},
        ]

    return {
        "export": {
            "formats": list(getattr(yaml_cfg.export, "formats", ["docx"])),
            "image_width_cm": float(getattr(yaml_cfg.export, "image_width_cm", 16.51)),
            "image_zoom_percent": int(getattr(yaml_cfg.export, "image_zoom_percent", 100)),
            "highlight_low_confidence": bool(getattr(yaml_cfg.export, "highlight_low_confidence", True)),
            "answer_format": "letter_keyword",  # 'letter' or 'letter_keyword'
            "multi_choice_format": getattr(yaml_cfg.export, "multi_choice_format", "comma"),  # 'comma' ("A, B, C") or 'joined' ("ABC")
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
        "storage": {
            "retention_days": 14,
            "auto_clean": True,
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


def get_env_file_path() -> Path:
    custom_data = os.environ.get("DOCXSTACKED_DATA_DIR")
    if custom_data:
        p = Path(custom_data) / ".env"
        return p
    return app_settings.BASE_DIR / ".env"


def save_api_key_to_env(env_var_name: str, key_value: str) -> None:
    """
    Persist API key securely to the environment file.
    Logs key name and length without leaking raw secret.
    """
    clean_val = key_value.strip()
    root_env = get_env_file_path()

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
        logger.info(f"đã ghi {env_var_name} (len {len(clean_val)}) vào .env")
    except Exception as e:
        logger.warning(f"Could not update .env file: {e}")

    # Update in-memory os.environ
    os.environ[env_var_name] = clean_val


def delete_api_key_from_env(env_var_name: str) -> None:
    """
    Remove API key securely from the environment file and in-memory os.environ.
    """
    root_env = get_env_file_path()
    try:
        if root_env.exists():
            content = root_env.read_text(encoding="utf-8")
            pattern = re.compile(rf"^{re.escape(env_var_name)}=.*(?:\r?\n)?", re.MULTILINE)
            new_content = pattern.sub("", content)
            root_env.write_text(new_content, encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not remove {env_var_name} from .env: {e}")

    os.environ.pop(env_var_name, None)


def mask_settings_for_api(settings_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mask all sensitive credentials before returning settings to the frontend.
    Never returns raw API keys; returns boolean 'has_api_key' and status 'configured'.
    """
    safe_data = copy.deepcopy(settings_dict)

    root_env = get_env_file_path()
    root_vals = dotenv_values(root_env) if root_env.exists() else {}

    if "ai" in safe_data and "providers" in safe_data["ai"]:
        invalid_set = get_invalid_key_providers()
        for p in safe_data["ai"]["providers"]:
            p_name = (p.get("name") or "").strip().lower()
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
                key_length = len(effective_val)
            else:
                has_key = False
                key_source = None
                masked_key = None
                key_length = 0

            p.pop("api_key", None)  # Ensure no key field exists
            p["has_api_key"] = has_key
            p["masked_key"] = masked_key
            p["key_length"] = key_length
            is_key_invalid = p_name in invalid_set
            p["key_invalid"] = is_key_invalid
            p["status"] = "key_invalid" if is_key_invalid else ("configured" if has_key else "not_configured")
            p["key_source"] = key_source
            if is_key_invalid:
                p["enabled"] = False
            elif "enabled" not in p:
                p["enabled"] = False

    return safe_data


async def update_settings(db: AsyncSession, new_settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate, save API keys to .env, persist section overrides to DB, and return masked active settings.
    """
    validate_settings(new_settings)

    clean_settings = copy.deepcopy(new_settings)

    # Extract and persist API keys for providers
    if "ai" in clean_settings and "providers" in clean_settings["ai"]:
        invalid_set = get_invalid_key_providers()
        for p in clean_settings["ai"]["providers"]:
            p_name = p.get("name", "").strip().lower()
            api_key = p.pop("api_key", None)
            env_var = p.get("api_key_env")
            if env_var:
                if api_key == "__DELETE__":
                    delete_api_key_from_env(env_var)
                    clear_invalid_key_provider(p.get("name", ""))
                    invalid_set.discard(p_name)
                    p["enabled"] = False
                elif api_key and isinstance(api_key, str) and len(api_key.strip()) > 3:
                    save_api_key_to_env(env_var, api_key.strip())
                    clear_invalid_key_provider(p.get("name", ""))
                    invalid_set.discard(p_name)
            if p_name in invalid_set and p.get("enabled"):
                p["enabled"] = False

    # Extract and persist extension_id if provided
    if "extension" in clean_settings and isinstance(clean_settings["extension"], dict):
        ext_id = clean_settings["extension"].get("extension_id")
        if ext_id is not None:
            clean_ext_id = str(ext_id).strip()
            save_api_key_to_env("EXTENSION_ID", clean_ext_id)
            app_settings.EXTENSION_ID = clean_ext_id

    # Save to database
    sections = ["export", "ai", "voting", "crawl", "extension"]
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


async def clean_expired_data(
    db: AsyncSession,
    retention_days: int = 14,
    dry_run: bool = False,
    vacuum: bool = True,
) -> Dict[str, Any]:
    """
    Delete raw and cropped images of completed/exported exams older than `retention_days`.
    Optionally execute SQLite VACUUM to reclaim storage space.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    query = select(Exam).where(Exam.status.in_(["completed", "exported"]))
    if retention_days > 0:
        query = query.where(Exam.updated_at <= cutoff)

    result = await db.execute(query)
    exams = result.scalars().all()

    deleted_files = 0
    reclaimed_bytes = 0
    cleaned_exams = 0
    storage_dir = app_settings.STORAGE_DIR

    for exam in exams:
        q_result = await db.execute(select(Question).where(Question.exam_id == exam.id))
        questions = q_result.scalars().all()
        exam_deleted_any = False

        for q in questions:
            for attr in ["local_image_path", "cropped_image_path", "choice_hint_path"]:
                path_str = getattr(q, attr, None)
                if path_str:
                    p = Path(path_str)
                    if not p.is_absolute():
                        p = storage_dir / p
                    if p.exists() and p.is_file():
                        file_sz = p.stat().st_size
                        if not dry_run:
                            try:
                                p.unlink(missing_ok=True)
                                setattr(q, attr, None)
                            except Exception as e:
                                logger.warning(f"Could not delete {p}: {e}")
                                continue
                        deleted_files += 1
                        reclaimed_bytes += file_sz
                        exam_deleted_any = True

        cropped_exam_dir = storage_dir / "cropped" / f"exam_{exam.id}"
        if cropped_exam_dir.exists() and cropped_exam_dir.is_dir():
            for child in cropped_exam_dir.glob("*"):
                if child.is_file():
                    sz = child.stat().st_size
                    if not dry_run:
                        try:
                            child.unlink(missing_ok=True)
                        except Exception:
                            pass
                    deleted_files += 1
                    reclaimed_bytes += sz
                    exam_deleted_any = True
            if not dry_run:
                try:
                    if not any(cropped_exam_dir.iterdir()):
                        cropped_exam_dir.rmdir()
                except Exception:
                    pass

        if exam_deleted_any:
            cleaned_exams += 1

    # Also clean orphaned cache files older than cutoff
    cache_dir = storage_dir / "cache"
    if cache_dir.exists():
        for f in cache_dir.glob("*.png"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if retention_days == 0 or mtime <= cutoff:
                    sz = f.stat().st_size
                    if not dry_run:
                        f.unlink(missing_ok=True)
                    deleted_files += 1
                    reclaimed_bytes += sz
            except Exception:
                pass

    if not dry_run:
        await db.commit()

    vacuum_done = False
    if vacuum and not dry_run:
        try:
            await db.execute(text("VACUUM"))
            vacuum_done = True
        except Exception as e:
            logger.warning(f"VACUUM execution failed: {e}")

    reclaimed_mb = round(reclaimed_bytes / (1024 * 1024), 2)
    return {
        "success": True,
        "retention_days": retention_days,
        "exams_cleaned": cleaned_exams,
        "files_deleted": deleted_files,
        "reclaimed_bytes": reclaimed_bytes,
        "reclaimed_mb": reclaimed_mb,
        "vacuum_performed": vacuum_done,
        "message": f"Đã dọn dẹp {deleted_files} tệp ({reclaimed_mb} MB) từ {cleaned_exams} đề và {'tối ưu hóa DB (VACUUM)' if vacuum_done else 'không chạy VACUUM'}."
    }


