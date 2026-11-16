import shutil
from pathlib import Path

import httpx

from cineforge.providers.base import LipSyncProvider


class MuseTalkLipSyncProvider(LipSyncProvider):
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")

    async def sync_lips(self, video_path: Path, audio_path: Path, output_path: Path) -> tuple[Path, float]:
        async with httpx.AsyncClient(timeout=300.0) as client:
            with video_path.open("rb") as vf, audio_path.open("rb") as af:
                files = {"video": (video_path.name, vf, "video/mp4"), "audio": (audio_path.name, af, "audio/wav")}
                res = await client.post(f"{self.base_url}/v1/lipsync", files=files)
                res.raise_for_status()
                output_path.write_bytes(res.content)
        return output_path, 0.0


class PassthroughLipSyncProvider(LipSyncProvider):
    async def sync_lips(self, video_path: Path, audio_path: Path, output_path: Path) -> tuple[Path, float]:
        shutil.copy2(video_path, output_path)
        return output_path, 0.0
