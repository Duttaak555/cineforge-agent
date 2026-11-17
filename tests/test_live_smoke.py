import asyncio
import inspect
import json
import os
import shutil
from pathlib import Path

import pytest

from cineforge.config import settings
from cineforge.mcp.server import run_pipeline
from cineforge.safety.production_gate import ProductionGateError
from cineforge.verification.smoke_verifier import (
    LiveSmokeVerificationReport,
    verify_mp4_with_ffprobe,
    verify_otio_references_resolve,
)


def test_verify_otio_references_resolve_validates_paths(tmp_path: Path) -> None:
    clip_file = tmp_path / "shots" / "shot_01.mp4"
    clip_file.parent.mkdir(parents=True)
    clip_file.write_bytes(b"fake-mp4-bytes")

    otio_file = tmp_path / "timeline.otio"
    otio_file.write_text(
        json.dumps(
            {
                "OTIO_SCHEMA": "Timeline.1",
                "name": "smoke_timeline",
                "tracks": {
                    "OTIO_SCHEMA": "Stack.1",
                    "children": [
                        {
                            "OTIO_SCHEMA": "Track.1",
                            "children": [
                                {
                                    "OTIO_SCHEMA": "Clip.2",
                                    "media_reference": {
                                        "OTIO_SCHEMA": "ExternalReference.1",
                                        "target_url": "shots/shot_01.mp4",
                                    },
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    assert verify_otio_references_resolve(otio_file) == 1


@pytest.mark.asyncio
async def test_run_pipeline_blocks_production_without_c2pa_certs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "production")
    monkeypatch.setattr(settings, "require_c2pa_signing", True)
    monkeypatch.setattr(settings, "c2pa_cert_path", "")
    monkeypatch.setattr(settings, "c2pa_key_path", "")

    sig = inspect.signature(run_pipeline)
    kwargs = {}
    for name in sig.parameters:
        if name == "project_id":
            kwargs[name] = "smoke_test_proj"
        elif "prompt" in name or "concept" in name or "script" in name or "brief" in name:
            kwargs[name] = "A single 2-second studio test shot."

    with pytest.raises(ProductionGateError, match="C2PA_CERT_PATH"):
        res = run_pipeline(**kwargs)
        if inspect.isawaitable(res):
            await res


@pytest.mark.live_smoke
@pytest.mark.asyncio
async def test_full_stack_live_smoke_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt-in live GPU smoke test: executes run_pipeline end-to-end and validates MP4, OTIO, and C2PA."""
    if os.getenv("CINEFORGE_RUN_LIVE_SMOKE") != "1":
        pytest.skip("Set CINEFORGE_RUN_LIVE_SMOKE=1 on reference Linux+NVIDIA host to run live pipeline smoke gate")

    monkeypatch.setattr(settings, "mode", "production")
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)

    sig = inspect.signature(run_pipeline)
    kwargs = {}
    for name in sig.parameters:
        if name == "project_id":
            kwargs[name] = "smoke_test_proj"
        elif "prompt" in name or "concept" in name or "script" in name or "brief" in name:
            kwargs[name] = "A 2-second wide establishing shot of a neon-lit rain street at night."

    res = run_pipeline(**kwargs)
    if inspect.isawaitable(res):
        res = await res

    mp4_files = list(tmp_path.rglob("*.mp4"))
    otio_files = list(tmp_path.rglob("*.otio"))
    assert mp4_files, f"run_pipeline produced no MP4 artifact under {tmp_path}"
    assert otio_files, f"run_pipeline produced no .otio timeline under {tmp_path}"

    master_mp4 = max(mp4_files, key=lambda p: p.stat().st_size)
    media_report = verify_mp4_with_ffprobe(master_mp4)
    clips_checked = verify_otio_references_resolve(otio_files[0])

    c2pa_verified = False
    if shutil.which("c2patool"):
        proc = await asyncio.create_subprocess_exec(
            "c2patool", str(master_mp4), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout_b, _ = await proc.communicate()
        assert proc.returncode == 0
        stdout_txt = stdout_b.decode("utf-8", errors="replace")
        c2pa_verified = "claim_generator" in stdout_txt or "assertions" in stdout_txt

    summary = LiveSmokeVerificationReport(
        services_verified=["ollama", "comfyui", "kokoro", "musetalk"],
        media=media_report,
        otio_clips_checked=clips_checked,
        c2pa_verified=c2pa_verified,
    )
    assert summary.media.has_video and summary.media.has_audio
