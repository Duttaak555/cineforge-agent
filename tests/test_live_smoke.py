import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from cineforge.qa.ollama_critic import evaluate_keyframe, prewarm_ollama_vlm
from cineforge.verification.smoke_verifier import (
    LiveSmokeVerificationReport,
    generate_test_c2pa_cert_and_sign,
    verify_mp4_with_ffprobe,
    verify_otio_references_resolve,
)


def test_verify_otio_references_resolve_validates_paths(tmp_path: Path) -> None:
    clip_file = tmp_path / "shots" / "shot_01.mp4"
    clip_file.parent.mkdir(parents=True)
    clip_file.write_bytes(b"fake-mp4-bytes")

    otio_file = tmp_path / "timeline.otio"
    otio_payload = {
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
    otio_file.write_text(json.dumps(otio_payload), encoding="utf-8")

    assert verify_otio_references_resolve(otio_file) == 1


def test_verify_otio_references_raises_on_missing_clip(tmp_path: Path) -> None:
    otio_file = tmp_path / "broken.otio"
    otio_file.write_text(
        json.dumps(
            {
                "OTIO_SCHEMA": "Timeline.1",
                "media_reference": {
                    "OTIO_SCHEMA": "ExternalReference.1",
                    "target_url": "shots/does_not_exist.mp4",
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError, match="Unresolved OTIO media reference"):
        verify_otio_references_resolve(otio_file)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe not installed"
)
def test_verify_mp4_with_ffprobe_on_synthetic_av(tmp_path: Path) -> None:
    sample_mp4 = tmp_path / "master.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=640x360:d=1.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.5",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(sample_mp4),
        ],
        check=True,
        capture_output=True,
    )

    report = verify_mp4_with_ffprobe(sample_mp4)
    assert report.has_video is True
    assert report.has_audio is True
    assert report.video_codec == "h264"
    assert report.audio_codec == "aac"
    assert report.width == 640
    assert report.height == 360
    assert report.duration_seconds >= 1.4


@pytest.mark.live_smoke
@pytest.mark.asyncio
async def test_full_stack_live_smoke_gate(tmp_path: Path) -> None:
    """Opt-in live GPU smoke test: verifies live Ollama Qwen2.5-VL, ComfyUI, Kokoro, FFprobe, OTIO, and C2PA."""
    if os.getenv("CINEFORGE_RUN_LIVE_SMOKE") != "1":
        pytest.skip("Set CINEFORGE_RUN_LIVE_SMOKE=1 on reference Linux+NVIDIA host to run live smoke gate")

    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    comfy_url = os.getenv("COMFYUI_URL", "http://localhost:8188")
    kokoro_url = os.getenv("KOKORO_URL", "http://localhost:8880")
    verified_services: list[str] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for name, probe_url in [
            ("ollama", f"{ollama_url.rstrip('/')}/api/tags"),
            ("comfyui", f"{comfy_url.rstrip('/')}/system_stats"),
            ("kokoro", f"{kokoro_url.rstrip('/')}/health"),
        ]:
            resp = await client.get(probe_url)
            resp.raise_for_status()
            verified_services.append(name)

        warm = await prewarm_ollama_vlm(client, ollama_url)
        assert warm["status"] == "warm"

        # Generate a test frame & verify bounded Qwen2.5-VL critique latency (<90s)
        frame_png = tmp_path / "live_keyframe.png"
        proc1 = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1920x1080:d=0.1",
            "-frames:v",
            "1",
            str(frame_png),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc1.communicate()
        assert proc1.returncode == 0
        qa_res = await evaluate_keyframe(client, ollama_url, frame_png, "Solid dark slate test frame")
        assert qa_res.latency_ms < 90_000

    # Master a 2-second test MP4, verify ffprobe, OTIO resolution, and C2PA signing
    raw_mp4 = tmp_path / "smoke_raw.mp4"
    signed_mp4 = tmp_path / "smoke_signed.mp4"
    proc2 = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=navy:s=1280x720:d=2.0",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=520:duration=2.0",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-shortest",
        str(raw_mp4),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc2.communicate()
    assert proc2.returncode == 0

    c2pa_ok = generate_test_c2pa_cert_and_sign(raw_mp4, signed_mp4, tmp_path / "certs")
    assert c2pa_ok is True

    media_report = verify_mp4_with_ffprobe(signed_mp4)
    otio_file = tmp_path / "smoke.otio"
    otio_file.write_text(
        json.dumps(
            {
                "OTIO_SCHEMA": "Timeline.1",
                "media_reference": {
                    "OTIO_SCHEMA": "ExternalReference.1",
                    "target_url": str(signed_mp4),
                },
            }
        ),
        encoding="utf-8",
    )
    clips_checked = verify_otio_references_resolve(otio_file)

    summary = LiveSmokeVerificationReport(
        services_verified=verified_services,
        media=media_report,
        otio_clips_checked=clips_checked,
        c2pa_verified=c2pa_ok,
    )
    assert len(summary.services_verified) == 3
