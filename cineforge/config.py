from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    workspace_dir: Path = Field(
        default=Path("./workspace"),
        validation_alias=AliasChoices("WORKSPACE_DIR", "CINEFORGE_OUTPUT_DIR"),
    )
    mode: str = Field(
        default="hybrid",
        validation_alias=AliasChoices("MODE", "CINEFORGE_MODE"),
    )
    comfyui_url: str = "http://localhost:8188"
    comfyui_cost_per_shot: float = 0.05
    kokoro_url: str = "http://localhost:8880/v1"
    kokoro_cost_per_1k_chars: float = 0.01
    ollama_url: str = "http://localhost:11434"
    ollama_vlm_model: str = "qwen2.5vl:7b"
    ollama_timeout_sec: float = 90.0
    allow_unverified_qa_fallback: bool = False
    lipsync_url: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("LIPSYNC_URL", "MUSETALK_URL"),
    )
    gemini_api_key: str = ""
    c2pa_cert_path: str = ""
    c2pa_key_path: str = ""
    require_c2pa_signing: bool | None = None
    max_budget_usd: float = Field(
        default=10.0,
        validation_alias=AliasChoices("MAX_BUDGET_USD", "CINEFORGE_MAX_BUDGET_USD"),
    )

    @model_validator(mode="after")
    def _enforce_production_defaults(self) -> "Settings":
        self.mode = self.mode.strip().lower()
        if self.require_c2pa_signing is None:
            self.require_c2pa_signing = self.mode == "production"
        return self


settings = Settings()
