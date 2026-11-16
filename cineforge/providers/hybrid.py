import urllib.request
from cineforge.config import settings
from cineforge.providers.base import VideoProvider, TTSProvider, VLMQAProvider
from cineforge.providers.lipsync import LipSyncProvider, MuseTalkLipSyncProvider, PassthroughLipSyncProvider
from cineforge.providers.mock import MockVideoProvider, MockTTSProvider, MockVLMQAProvider
from cineforge.providers.registry import ComfyUIWan22Provider, KokoroTTSProvider, OllamaVLMQAProvider


def _is_reachable(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


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
        KokoroTTSProvider(settings.kokoro_url, cost_per_1k_chars=settings.kokoro_cost_per_1k_chars)
        if kokoro_up
        else MockTTSProvider()
    )
    q_prov: VLMQAProvider = (
        OllamaVLMQAProvider(settings.ollama_url, settings.ollama_vlm_model)
        if ollama_up
        else MockVLMQAProvider()
    )
    l_prov: LipSyncProvider = (
        MuseTalkLipSyncProvider(settings.lipsync_url)
        if musetalk_up
        else PassthroughLipSyncProvider()
    )

    status_map = {
        "video": "ComfyUIWan22" if comfy_up else "MockVideo (fallback)",
        "tts": "KokoroTTS" if kokoro_up else "MockTTS (fallback)",
        "vlm_qa": f"OllamaVLM({settings.ollama_vlm_model})" if ollama_up else "MockVLM (fallback)",
        "lipsync": "MuseTalk" if musetalk_up else "Passthrough (fallback)",
    }
    return v_prov, t_prov, q_prov, l_prov, status_map
