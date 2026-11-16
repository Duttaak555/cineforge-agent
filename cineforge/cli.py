import json
import urllib.request

from cineforge.config import settings


def doctor() -> None:
    endpoints = {
        "ComfyUI (Video)": f"{settings.comfyui_url.rstrip('/')}/system_stats",
        "Kokoro-82M (TTS)": f"{settings.kokoro_url.rstrip('/')}/models",
        "Ollama (VLM QA)": f"{settings.ollama_url.rstrip('/')}/api/tags",
        "MuseTalk (LipSync)": f"{settings.lipsync_url.rstrip('/')}/docs",
    }
    print(f"CineForge Studio Doctor (MODE={settings.mode})\n" + "-" * 60)
    for name, url in endpoints.items():
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                extra = ""
                if "11434" in url and resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m["name"] for m in data.get("models", [])]
                    extra = f" | Models: {models}"
                print(f"[ONLINE ] {name:20s} -> {url} (HTTP {resp.status}){extra}")
        except Exception as exc:
            print(f"[OFFLINE] {name:20s} -> {url} ({type(exc).__name__})")


if __name__ == "__main__":
    doctor()
