from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    workspace_dir: Path = Path("./workspace")
    mode: str = "hybrid"
    comfyui_url: str = "http://localhost:8188"
    comfyui_cost_per_shot: float = 0.05
    kokoro_url: str = "http://localhost:8880/v1"
    kokoro_cost_per_1k_chars: float = 0.01
    ollama_url: str = "http://localhost:11434"
    ollama_vlm_model: str = "qwen2.5vl:7b"
    ollama_timeout_sec: float = 300.0
    allow_unverified_qa_fallback: bool = False
    lipsync_url: str = "http://localhost:8000"
    gemini_api_key: str = ""
    c2pa_cert_path: str = ""
    c2pa_key_path: str = ""


settings = Settings()
