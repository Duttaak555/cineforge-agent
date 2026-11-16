import urllib.request
from pathlib import Path

from cineforge.config import settings
from cineforge.providers.base import LipSyncProvider, TTSProvider, VideoProvider, VLMQAProvider
from cineforge.providers.lipsync import MuseTalkLipSyncProvider, PassthroughLipSyncProvider
from cineforge.providers.mock import MockTTSProvider, MockVideoProvider, MockVLMQAProvider
from cineforge.providers.registry import ComfyUIWan22Provider, KokoroTTSProvider, OllamaVLMQAProvider
from cineforge.schemas.bible import CharacterEntity
from cineforge.schemas.timeline import QAReport, Shot


def _is_reachable(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


class FallbackTTSProvider(TTSProvider):
    def __init__(self, primary: TTSProvider, fallback: TTSProvider):
        self.primary = primary
        self.fallback = fallback

    def estimate_cost(self, text: str) -> float:
        return self.primary.estimate_cost(text)

    async def synthesize(
        self, text: str, character: CharacterEntity, output_path: Path, speed: float = 1.0
    ) -> tuple[Path, float]:
        try:
            return await self.primary.synthesize(text, character, output_path, speed=speed)
        except Exception:
            return await self.fallback.synthesize(text, character, output_path, speed=speed)


class FallbackVLMQAProvider(VLMQAProvider):
    """Fails safe (passed=False) on VLM timeout unless allow_unverified_fallback=True."""

    def __init__(self, primary: VLMQAProvider, fallback: VLMQAProvider, allow_unverified_fallback: bool = False):
        self.primary = primary
        self.fallback = fallback
        self.allow_unverified_fallback = allow_unverified_fallback

    async def inspect_shot(self, shot: Shot, grounded_prompt: str, keyframe_path: Path) -> QAReport:
        try:
            return await self.primary.inspect_shot(shot, grounded_prompt, keyframe_path)
        except Exception as exc:
            if not self.allow_unverified_fallback:
                return QAReport(
                    passed=False,
                    score=0.0,
                    critique=f"VLM QA runtime error/timeout ({type(exc).__name__}); failing safe.",
                )
            report = await self.fallback.inspect_shot(shot, grounded_prompt, keyframe_path)
            report.critique = f"[Unverified Fallback QA after {type(exc).__name__}] {report.critique}"
            return report


def resolve_hybrid_providers() -> tuple[VideoProvider, TTSProvider, VLMQAProvider, LipSyncProvider, dict[str, str]]:
    comfy_up = _is_reachable(f"{settings.comfyui_url.rstrip('/')}/system_stats")
    kokoro_up = _is_reachable(f"{settings.kokoro_url.rstrip('/')}/models")
    ollama_up = _is_reachable(f"{settings.ollama_url.rstrip('/')}/api/tags")
    musetalk_up = _is_reachable(f"{settings.lipsync_url.rstrip('/')}/docs")

    v_prov: VideoProvider = (
        ComfyUIWan22Provider(settings.comfyui_url, cost_per_shot=settings.comfyui_cost_per_shot)
        if comfy_up
        else MockVideoProvider()
    )
    t_prov: TTSProvider = (
        FallbackTTSProvider(
            KokoroTTSProvider(settings.kokoro_url, cost_per_1k_chars=settings.kokoro_cost_per_1k_chars),
            MockTTSProvider(),
        )
        if kokoro_up
        else MockTTSProvider()
    )
    q_prov: VLMQAProvider = (
        FallbackVLMQAProvider(
            OllamaVLMQAProvider(
                settings.ollama_url, settings.ollama_vlm_model, timeout_sec=settings.ollama_timeout_sec
            ),
            MockVLMQAProvider(),
            allow_unverified_fallback=settings.allow_unverified_qa_fallback,
        )
        if ollama_up
        else MockVLMQAProvider()
    )
    l_prov: LipSyncProvider = (
        MuseTalkLipSyncProvider(settings.lipsync_url) if musetalk_up else PassthroughLipSyncProvider()
    )

    status_map = {
        "video": "ComfyUIWan22" if comfy_up else "MockVideo (fallback)",
        "tts": "KokoroTTS (runtime fallback)" if kokoro_up else "MockTTS (fallback)",
        "vlm_qa": f"OllamaVLM({settings.ollama_vlm_model})" if ollama_up else "MockVLM (fallback)",
        "lipsync": "MuseTalk" if musetalk_up else "Passthrough (fallback)",
    }
    return v_prov, t_prov, q_prov, l_prov, status_map
