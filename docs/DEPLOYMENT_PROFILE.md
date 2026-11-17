# Reference Deployment Profile (`v0.2.0-ref-linux-gpu`)

Production readiness claims for **CineForge-Agent** apply **exclusively** to this verified Linux + NVIDIA reference stack. Deployments outside this specification should be run in `mock` or `hybrid` mode.

## 1. Hardware & OS Baseline

| Component | Minimum Verified Spec | Notes |
| :--- | :--- | :--- |
| **Operating System** | Ubuntu `22.04` or `24.04` LTS (`x86_64`) | Kernel `6.5+` with NVIDIA Driver `550+` |
| **GPU & VRAM** | 1× NVIDIA GPU (`>= 24 GB` VRAM) | Tested targets: RTX 3090, RTX 4090, A10G, L4 |
| **System RAM** | `32 GB` DDR4/DDR5 | Prevents host OOM during Wan 2.2 + `Qwen2.5-VL` weight loading |
| **Storage** | `100 GB` NVMe SSD | Required for Wan 2.2 checkpoints, Ollama weights, and intermediate WAV/MP4 renders |
| **Container Runtime** | Docker Engine `26.0+` & Docker Compose `v2.24+` | With `nvidia-container-toolkit` configured as default runtime |

## 2. Pinned Service Versions

| Service | Pinned Image / Version | Port | Purpose |
| :--- | :--- | :--- | :--- |
| **Ollama** | `ollama/ollama:0.5.7` (`qwen2.5vl:7b`) | `11434` | Vision QA critic (`<= 768px` keyframes, pre-warmed) |
| **ComfyUI** | `ghcr.io/comfyanonymous/comfyui:v0.3.14-cuda12.4` | `8188` | Wan 2.2 video generation backend |
| **Kokoro-82M** | `ghcr.io/remsky/kokoro-fastapi-gpu:v0.2.2` | `8880` | Neural dialogue & narration synthesis |
| **FFmpeg & OTIO** | `ffmpeg 6.1+`, `opentimelineio 0.17+`, `c2patool 0.9+` | Local CLI | `-14 LUFS` EBU R128 mastering, `.otio` timelines, C2PA signing |

## 3. Clean Install, Storage & Upgrade Path

1. **Configure `.env`:** Copy `.env.example` to `.env` and set `CINEFORGE_MODE=production`, `OLLAMA_URL`, `COMFYUI_URL`, `KOKORO_URL`, `C2PA_CERT_PATH`, and `C2PA_KEY_PATH`.
2. **Start Services & Pull Weights:** Run `docker compose -f docker-compose.prod.yml up -d ollama comfyui kokoro-tts`, run `docker exec -it cineforge-ollama ollama pull qwen2.5vl:7b`, and mount Wan 2.2 weights into `comfyui_models` plus your ES256 certificate/key into `cineforge_certs`.
3. **Verify Gates:** Run `cineforge-doctor --strict` and `CINEFORGE_RUN_LIVE_SMOKE=1 pytest -v -m live_smoke`.
4. **Upgrade & Rollback:** Snapshot `cineforge_outputs` and `cineforge_certs`, check out the target tag, run `docker compose -f docker-compose.prod.yml up -d --build`, and re-run `cineforge-doctor --strict` (roll back via `git checkout v0.1.9` against existing volumes).
