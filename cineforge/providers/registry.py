from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx

from cineforge.providers.base import TTSProvider, VideoProvider, VLMQAProvider
from cineforge.qa.ollama_critic import evaluate_keyframe
from cineforge.safety.production_gate import poll_until_complete
from cineforge.schemas.bible import CharacterEntity
from cineforge.schemas.timeline import QAReport, Shot


def extract_mid_frame(video_path: Path, frame_out: Path, max_width: int = 512) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"select=eq(n\\,12),scale={max_width}:-1",
            "-vframes",
            "1",
            str(frame_out),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return frame_out


class ComfyUIWan22Provider(VideoProvider):
    def __init__(
        self,
        base_url: str = "http://localhost:8188",
        workflow_template_path: Path | None = None,
        cost_per_shot: float = 0.05,
        max_poll_seconds: float = 300.0,
        poll_interval_seconds: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.workflow_path = workflow_template_path or Path("workflows/wan22_t2v_api.json")
        self.cost_per_shot = cost_per_shot
        self.max_poll_seconds = max_poll_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def estimate_cost(self, shot: Shot) -> float:
        return self.cost_per_shot

    async def generate_shot(
        self, shot: Shot, grounded_prompt: str, output_dir: Path, seed: int = 42
    ) -> tuple[Path, float]:
        workflow = json.loads(self.workflow_path.read_text())
        if "6" in workflow:
            workflow["6"]["inputs"]["text"] = grounded_prompt
        if "3" in workflow:
            workflow["3"]["inputs"]["seed"] = seed
        if "50" in workflow:
            workflow["50"]["inputs"]["length"] = max(17, int(shot.duration_sec * 16) + 1)

        async with httpx.AsyncClient(timeout=600.0) as client:
            res = await client.post(f"{self.base_url}/prompt", json={"prompt": workflow})
            res.raise_for_status()
            pid = res.json()["prompt_id"]

            async def _check_comfy() -> dict[str, Any]:
                hist = (await client.get(f"{self.base_url}/history/{pid}")).json()
                if pid in hist:
                    status_info = hist[pid].get("status", {})
                    if str(status_info.get("status_str", "")).lower() == "error":
                        return {"status": "failed", "detail": status_info}
                    return {"status": "completed", "outputs": hist[pid].get("outputs", {})}
                return {"status": "running"}

            poll_result = await poll_until_complete(
                _check_comfy,
                deadline_seconds=self.max_poll_seconds,
                interval_seconds=self.poll_interval_seconds,
            )
            outputs = poll_result.get("outputs", {})

            meta = next((i for o in outputs.values() for i in (o.get("videos") or o.get("gifs") or [])), None)
            if not meta:
                raise RuntimeError(f"ComfyUI prompt {pid} returned no video.")
            vid = (
                await client.get(
                    f"{self.base_url}/view",
                    params={
                        "filename": meta["filename"],
                        "subfolder": meta.get("subfolder", ""),
                        "type": meta.get("type", "output"),
                    },
                )
            ).content
            out = output_dir / f"{shot.shot_id}.mp4"
            out.write_bytes(vid)
            return out, self.estimate_cost(shot)


class KokoroTTSProvider(TTSProvider):
    def __init__(self, base_url: str = "http://localhost:8880/v1", cost_per_1k_chars: float = 0.01):
        self.base_url = base_url.rstrip("/")
        self.cost_per_1k_chars = cost_per_1k_chars

    def estimate_cost(self, text: str) -> float:
        return round(max(0.001, (len(text) / 1000.0) * self.cost_per_1k_chars), 4)

    async def synthesize(
        self, text: str, character: CharacterEntity, output_path: Path, speed: float = 1.0
    ) -> tuple[Path, float]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(
                f"{self.base_url}/audio/speech",
                json={
                    "model": "kokoro",
                    "input": text,
                    "voice": character.voice_id,
                    "response_format": "wav",
                    "speed": speed,
                },
            )
            res.raise_for_status()
            output_path.write_bytes(res.content)
        return output_path, self.estimate_cost(text)


class OllamaVLMQAProvider(VLMQAProvider):
    def __init__(
        self, base_url: str = "http://localhost:11434", model: str = "qwen2.5vl:7b", timeout_sec: float = 300.0
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec

    async def inspect_shot(self, shot: Shot, grounded_prompt: str, keyframe_path: Path) -> QAReport:
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            critique = await evaluate_keyframe(
                client=client,
                base_url=self.base_url,
                image_path=keyframe_path,
                shot_brief=grounded_prompt,
                model=self.model,
            )
        summary = "; ".join(critique.defects) if critique.defects else "Passed visual QA inspection."
        return QAReport(
            passed=critique.passed,
            score=critique.score,
            critique=summary,
        )
