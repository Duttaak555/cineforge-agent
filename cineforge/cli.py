import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from cineforge.config import settings


def doctor(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="cineforge-doctor")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any required endpoint, VLM model, or production C2PA cert is unavailable.",
    )
    args = parser.parse_args(argv)

    endpoints = {
        "ComfyUI (Video)": f"{settings.comfyui_url.rstrip('/')}/system_stats",
        "Kokoro-82M (TTS)": f"{settings.kokoro_url.rstrip('/')}/models",
        "Ollama (VLM QA)": f"{settings.ollama_url.rstrip('/')}/api/tags",
        "MuseTalk (LipSync)": f"{settings.lipsync_url.rstrip('/')}/docs",
    }
    print(f"CineForge Studio Doctor (MODE={settings.mode}, STRICT={args.strict})\n" + "-" * 64)

    failures: list[str] = []
    for name, url in endpoints.items():
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                extra = ""
                if "11434" in url and resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m["name"] for m in data.get("models", [])]
                    extra = f" | Models: {models}"
                    if settings.ollama_vlm_model not in models:
                        failures.append(f"Ollama missing pinned model {settings.ollama_vlm_model}")
                print(f"[ONLINE ] {name:20s} -> {url} (HTTP {resp.status}){extra}")
        except (OSError, urllib.error.URLError, ValueError) as exc:
            print(f"[OFFLINE] {name:20s} -> {url} ({type(exc).__name__})")
            failures.append(f"{name} unreachable at {url}")

    if settings.require_c2pa_signing:
        cert_ok = bool(settings.c2pa_cert_path) and Path(settings.c2pa_cert_path).is_file()
        key_ok = bool(settings.c2pa_key_path) and Path(settings.c2pa_key_path).is_file()
        if not (cert_ok and key_ok):
            msg = "C2PA signing required in production mode, but C2PA_CERT_PATH or C2PA_KEY_PATH is missing."
            print(f"[MISSING] {'C2PA Signing Cert':20s} -> {msg}")
            failures.append(msg)
        else:
            print(f"[OK     ] {'C2PA Signing Cert':20s} -> {settings.c2pa_cert_path}")

    if args.strict and failures:
        print(f"\nSTRICT DOCTOR FAILED ({len(failures)} issue(s)):", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    doctor()
