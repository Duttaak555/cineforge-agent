from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import c2pa
import httpx
import pytest

from cineforge.config import settings
from cineforge.mcp.server import init_project, run_pipeline


@pytest.fixture(scope="session")
def live_smoke_report() -> Any:
    telemetry: dict[str, Any] = {
        "schema_version": "1.0.0",
        "release_tag": "v0.2.0-ref-linux-gpu",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": subprocess.getoutput("git rev-parse HEAD").strip(),
        "gpu": subprocess.getoutput(
            "nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader"
        ).strip(),
        "checks": {},
    }
    yield telemetry

    if os.getenv("CINEFORGE_RUN_LIVE_SMOKE") == "1":
        report_path = Path(
            os.getenv("CINEFORGE_VERIFICATION_REPORT", "artifacts/verification-v0.2.0-ref-linux-gpu.json")
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(telemetry, indent=2), encoding="utf-8")


@pytest.mark.live_smoke
@pytest.mark.asyncio
async def test_full_stack_live_smoke_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    live_smoke_report: dict[str, Any],
) -> None:
    """Opt-in live GPU smoke test: verifies all 4 GPU services, end-to-end run_pipeline, FFprobe, OTIO, and C2PA."""
    if os.getenv("CINEFORGE_RUN_LIVE_SMOKE") != "1":
        pytest.skip("Set CINEFORGE_RUN_LIVE_SMOKE=1 on reference Linux+NVIDIA host to run live smoke gate")

    ollama_url = os.getenv("OLLAMA_URL", settings.ollama_url).rstrip("/")
    comfy_url = os.getenv("COMFYUI_URL", settings.comfyui_url).rstrip("/")
    kokoro_url = os.getenv("KOKORO_URL", settings.kokoro_url).rstrip("/")
    lipsync_url = os.getenv("LIPSYNC_URL", settings.lipsync_url).rstrip("/")

    async with httpx.AsyncClient(timeout=15.0) as client:
        for name, probe_url in [
            ("ollama", f"{ollama_url}/api/tags"),
            ("comfyui", f"{comfy_url}/system_stats"),
            ("kokoro", f"{kokoro_url}/models"),
            ("musetalk", f"{lipsync_url}/docs"),
        ]:
            resp = await client.get(probe_url)
            assert resp.status_code == 200, f"{name} probe failed at {probe_url}: HTTP {resp.status_code}"
            if name == "ollama":
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                assert any(m.startswith("qwen2.5vl") for m in models), f"Missing qwen2.5vl in Ollama models: {models}"

    assert settings.c2pa_cert_path and Path(settings.c2pa_cert_path).is_file(), "C2PA_CERT_PATH must exist in production"
    assert settings.c2pa_key_path and Path(settings.c2pa_key_path).is_file(), "C2PA_KEY_PATH must exist in production"
    monkeypatch.setattr(settings, "mode", "production")
    if hasattr(settings, "projects_dir"):
        monkeypatch.setattr(settings, "projects_dir", tmp_path)

    init_kwargs: dict[str, Any] = {
        "project_id": "live_gpu_smoke",
        "title": "Live GPU Smoke",
    }
    init_project(**init_kwargs)

    result_str = await run_pipeline(
        project_id="live_gpu_smoke",
        mode="production",
        allow_partial=False,
        require_signed_c2pa=True,
    )
    assert "[C2PA X.509 Signed]" in result_str, f"Expected signed C2PA output in production mode, got: {result_str}"

    mp4_files = list(tmp_path.rglob("*_master.mp4"))
    otio_files = list(tmp_path.rglob("*.otio"))
    assert mp4_files, f"No *_master.mp4 artifact found under {tmp_path}"
    assert otio_files, f"No *.otio timeline found under {tmp_path}"

    master_mp4 = mp4_files[0]
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "json",
        str(master_mp4),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    assert proc.returncode == 0, f"ffprobe failed: {stderr_bytes.decode()}"
    streams = [s.get("codec_type") for s in json.loads(stdout_bytes.decode()).get("streams", [])]
    assert "video" in streams and "audio" in streams, f"Master MP4 missing video/audio streams: {streams}"

    reader = c2pa.Reader.from_file(str(master_mp4))
    manifest_json = json.loads(reader.json())
    active_label = manifest_json.get("active_manifest")
    assert active_label, f"C2PA manifest missing active_manifest: {manifest_json}"

    live_smoke_report["checks"] = {
        "endpoints_verified": ["ollama", "comfyui", "kokoro", "musetalk"],
        "pipeline_result": result_str,
        "master_mp4_bytes": master_mp4.stat().st_size,
        "ffprobe_streams": streams,
        "otio_file": otio_files[0].name,
        "c2pa_active_manifest": active_label,
    }
