from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, Field


class MediaProbeReport(BaseModel):
    duration_seconds: float = Field(gt=0.0)
    video_codec: str
    audio_codec: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    has_video: bool
    has_audio: bool


class LiveSmokeVerificationReport(BaseModel):
    services_verified: list[str]
    media: MediaProbeReport
    otio_clips_checked: int
    c2pa_verified: bool


def verify_mp4_with_ffprobe(mp4_path: Path) -> MediaProbeReport:
    """Run ffprobe on a mastered MP4 and assert valid playable video + audio streams."""
    if not mp4_path.exists() or mp4_path.stat().st_size == 0:
        raise FileNotFoundError(f"Master MP4 missing or empty: {mp4_path}")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height",
        "-of",
        "json",
        str(mp4_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    payload: dict[str, Any] = json.loads(proc.stdout)

    streams = payload.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if not video_streams or not audio_streams:
        raise ValueError(
            f"Expected both video and audio streams in {mp4_path}, got "
            f"video={len(video_streams)}, audio={len(audio_streams)}"
        )

    v0 = video_streams[0]
    a0 = audio_streams[0]
    duration = float(payload.get("format", {}).get("duration", 0.0))
    if duration <= 0.0:
        raise ValueError(f"Invalid media duration ({duration}s) in {mp4_path}")

    return MediaProbeReport(
        duration_seconds=duration,
        video_codec=str(v0.get("codec_name", "")),
        audio_codec=str(a0.get("codec_name", "")),
        width=int(v0.get("width", 0)),
        height=int(v0.get("height", 0)),
        has_video=True,
        has_audio=True,
    )


def verify_otio_references_resolve(otio_path: Path) -> int:
    """Parse an .otio JSON timeline and confirm every ExternalReference target_url exists on disk."""
    if not otio_path.exists():
        raise FileNotFoundError(f"OTIO timeline missing: {otio_path}")

    raw = json.loads(otio_path.read_text(encoding="utf-8"))
    target_urls: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("OTIO_SCHEMA", "").startswith("ExternalReference") and node.get("target_url"):
                target_urls.append(str(node["target_url"]))
            for val in node.values():
                _walk(val)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(raw)
    if not target_urls:
        raise ValueError(f"No ExternalReference media clips found in {otio_path}")

    for url in target_urls:
        parsed = urlparse(url)
        raw_path = unquote(parsed.path) if parsed.scheme == "file" else url
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (otio_path.parent / candidate).resolve()
        if not candidate.exists() or candidate.stat().st_size == 0:
            raise FileNotFoundError(f"Unresolved OTIO media reference: {url} -> {candidate}")

    return len(target_urls)


def generate_test_c2pa_cert_and_sign(
    input_mp4: Path,
    output_mp4: Path,
    work_dir: Path,
) -> bool:
    """Generate an ephemeral self-signed X.509 cert via OpenSSL, sign MP4 with c2patool, and verify."""
    if shutil.which("openssl") is None or shutil.which("c2patool") is None:
        raise RuntimeError("Both 'openssl' and 'c2patool' binaries must be installed in PATH")

    work_dir.mkdir(parents=True, exist_ok=True)
    key_path = work_dir / "test_c2pa_es256.key"
    cert_path = work_dir / "test_c2pa_es256.pem"
    manifest_path = work_dir / "manifest.json"

    subprocess.run(
        ["openssl", "ecparam", "-genkey", "-name", "prime256v1", "-noout", "-out", str(key_path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-x509",
            "-key",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-subj",
            "/CN=CineForge-Smoke-Test-Signer/O=CineForge",
        ],
        check=True,
        capture_output=True,
    )

    manifest = {
        "alg": "es256",
        "private_key": str(key_path),
        "sign_cert": str(cert_path),
        "claim_generator": "CineForge-Agent/0.2.0-smoke",
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {"actions": [{"action": "c2pa.created"}]},
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    subprocess.run(
        [
            "c2patool",
            str(input_mp4),
            "-m",
            str(manifest_path),
            "-o",
            str(output_mp4),
            "-f",
        ],
        check=True,
        capture_output=True,
    )

    verify_proc = subprocess.run(
        ["c2patool", str(output_mp4)],
        check=True,
        capture_output=True,
        text=True,
    )
    return "CineForge-Agent/0.2.0-smoke" in verify_proc.stdout
