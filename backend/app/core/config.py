import os
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = BASE_DIR / "backend" / "config"


class ExamConfig(BaseModel):
    default_count: int = 4
    min_count: int = 1
    order: str = "newest_first"


class CrawlConfig(BaseModel):
    delay_seconds: List[float] = [1.5, 4.0]
    concurrency: int = 1
    headless: bool = False
    max_retries: int = 3


class AnalysisConfig(BaseModel):
    use_ai: bool = True
    max_ai_calls: int = 300
    vote_weight: str = "log_upvotes"
    multi_choice_threshold: float = 0.5
    confident_min_ratio: float = 0.7
    confident_min_comments: int = 2
    use_llm_for_ambiguous: bool = False
    dedupe: bool = True
    dedupe_hamming: int = 6


class AIProviderConfig(BaseModel):
    name: str
    model: str
    api_key_env: str
    base_url: Optional[str] = None
    enabled: bool = False


class AIConfig(BaseModel):
    enabled: bool = True
    ensemble: bool = False
    max_ai_calls: int = 300
    backoff_seconds: float = 2.0
    max_retries: int = 2
    ai_disagreement_policy: str = "flag"  # 'flag', 'conflict', or 'ignore'
    providers: List[AIProviderConfig] = Field(default_factory=list)


class ExportConfig(BaseModel):
    formats: List[str] = ["docx"]
    image_width_cm: float = 16.51
    image_zoom_percent: int = 100
    highlight_low_confidence: bool = True
    answer_format: str = "letter_keyword"
    multi_choice_format: str = "comma"
    merge: bool = False


class ImageCropConfig(BaseModel):
    red_min_r: int = 170
    red_max_g: int = 80
    red_max_b: int = 80
    red_min_frac: float = 0.3
    white_min_val: int = 252
    closing_kernel_size: int = 9
    white_panel_min_area_ratio: float = 0.02
    white_panel_max_width_ratio: float = 0.95
    dark_threshold: int = 140
    color_diff_threshold: int = 60
    border_dark_ratio: float = 0.50
    border_edge_depth: int = 15
    padding_px: int = 12
    crop_too_large_ratio: float = 0.85
    min_height_px: int = 100
    min_width_px: int = 150
    warning_rate_threshold: float = 0.20


class AppYamlConfig(BaseModel):
    exam: ExamConfig = Field(default_factory=ExamConfig)
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    image_crop: ImageCropConfig = Field(default_factory=ImageCropConfig)


class Settings(BaseSettings):
    # App & Environment
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    FRONTEND_URL: str = "http://localhost:5173"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///data/docxstacked.db"
    SYNC_DATABASE_URL: str = "sqlite:///data/docxstacked.db"

    # Storage Paths & Data Dir Override
    DOCXSTACKED_DATA_DIR: Optional[str] = None
    BASE_DIR: Path = BASE_DIR
    STORAGE_DIR: Path = BASE_DIR / "data"
    DATA_DIR: Path = BASE_DIR / "data"
    OUTPUT_DIR: Path = BASE_DIR / "data" / "output"
    BROWSER_PROFILE_DIR: Path = BASE_DIR / "data" / "browser_profile"
    CONFIG_DIR: Path = CONFIG_DIR

    # Crawler Runtime Overrides
    HEADLESS: bool = False
    BROWSER_CHANNEL: str = "chromium"
    CONCURRENCY: int = 1
    MIN_DELAY_SECONDS: float = 1.5
    MAX_DELAY_SECONDS: float = 4.0

    # Local Ingestion (for browser extension, pinned fixed ID)
    INGEST_TOKEN: Optional[str] = None
    EXTENSION_ID: str = "kicplcdfmbcfjildbbimpfiljlmfokea"
    MAX_INGEST_PAYLOAD_BYTES: int = 100 * 1024 * 1024  # 100 MB max payload for base64 images

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        custom_data_dir = os.environ.get("DOCXSTACKED_DATA_DIR") or self.DOCXSTACKED_DATA_DIR
        if custom_data_dir:
            effective_data = Path(custom_data_dir).resolve()
        else:
            effective_data = self.BASE_DIR / "data"

        self.DATA_DIR = effective_data
        self.STORAGE_DIR = effective_data
        self.OUTPUT_DIR = effective_data / "output"
        self.BROWSER_PROFILE_DIR = effective_data / "browser_profile"

        db_file = effective_data / "docxstacked.db"
        db_posix = db_file.as_posix()
        if "data/docxstacked.db" in self.DATABASE_URL or "data/gomde.db" in self.DATABASE_URL:
            self.DATABASE_URL = f"sqlite+aiosqlite:///{db_posix}"
        if "data/docxstacked.db" in self.SYNC_DATABASE_URL or "data/gomde.db" in self.SYNC_DATABASE_URL:
            self.SYNC_DATABASE_URL = f"sqlite:///{db_posix}"

    @property
    def yaml_config(self) -> AppYamlConfig:
        config_path = self.CONFIG_DIR / "config.yaml"
        if not config_path.exists():
            return AppYamlConfig()
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return AppYamlConfig.model_validate(data)

    @property
    def selectors(self) -> Dict[str, Any]:
        selectors_path = self.CONFIG_DIR / "selectors.yaml"
        if not selectors_path.exists():
            return {}
        with open(selectors_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}


@lru_cache()
def get_settings() -> Settings:
    # Auto-generate INGEST_TOKEN on first run if missing in .env
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        try:
            content = env_file.read_text(encoding="utf-8")
            if not re.search(r"^\s*INGEST_TOKEN\s*=\s*\S+", content, re.MULTILINE):
                import secrets
                token = secrets.token_urlsafe(32)
                if re.search(r"^\s*INGEST_TOKEN\s*=", content, re.MULTILINE):
                    new_content = re.sub(r"^\s*INGEST_TOKEN\s*=.*$", f"INGEST_TOKEN={token}", content, flags=re.MULTILINE)
                else:
                    new_content = content.rstrip() + f"\nINGEST_TOKEN={token}\n"
                env_file.write_text(new_content, encoding="utf-8")
                os.environ["INGEST_TOKEN"] = token
        except Exception:
            pass

    settings = Settings()
    if not settings.INGEST_TOKEN:
        import secrets
        settings.INGEST_TOKEN = os.environ.get("INGEST_TOKEN") or secrets.token_urlsafe(32)
    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    settings.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return settings

