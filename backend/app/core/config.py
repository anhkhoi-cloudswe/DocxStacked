from functools import lru_cache
from pathlib import Path
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

    # Storage Paths
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

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

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
    settings = Settings()
    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    settings.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return settings

