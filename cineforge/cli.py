from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from cineforge.config import settings


def doctor(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cineforge-doctor")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any required endpoint, VLM model, or production C2PA credential is missing.",
    )
    args = parser.parse_args(argv)

    endpoints = {
        "ComfyUI (Video)": f"{settings.comfyui_url.rstrip('/')}/system_stats",
        "Kokoro-82M (TTS)": f"{settings.kokoro_url.rstrip('/')}/models",
        "Ollama (VLM QA)": f"{settings.ollama_url.rstrip('/')}/api/tags",
        "MuseTalk (LipSync)": f"{settings.lipsync_url.rstrip('/')}/docs",
    }
    print(f"CineForge Studio Doctor (MODE={settings.mode})\n" + "-" * 60)
    failures: list[str] = []

    for name, url in endpoints.items():
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                extra = ""
                if "11434" in url and resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m["name"] for m in data.get("models", [])]
                    extra = f" | Models: {models}"
                    if args.strict and not any(m.startswith("qwen2.5vl") for m in models):
                        failures.append("Ollama missing qwen2.5vl model")
                print(f"[ONLINE ] {name:20s} -> {url} (HTTP {resp.status}){extra}")
        except (OSError, urllib.error.URLError, ValueError) as exc:
            print(f"[OFFLINE] {name:20s} -> {url} ({type(exc).__name__})")
            failures.append(f"{name} offline")

    if args.strict and str(settings.mode).lower() == "production":
        cert_ok = bool(settings.c2pa_cert_path and Path(settings.c2pa_cert_path).is_file())
        key_ok = bool(settings.c2pa_key_path and Path(settings.c2pa_key_path).is_file())
        if not (cert_ok and key_ok):
            print("[MISSING] C2PA Signing Credentials -> C2PA_CERT_PATH / C2PA_KEY_PATH")
            failures.append("Missing C2PA_CERT_PATH or C2PA_KEY_PATH in production mode")
        else:
            print(f"[READY  ] C2PA Credentials     -> {settings.c2pa_cert_path}")

    if args.strict and failures:
        print(f"\nStrict check failed ({len(failures)} issue(s)): " + "; ".join(failures), file=sys.stderr)
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    doctor()
