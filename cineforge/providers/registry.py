import asyncio
import base64
import json
import subprocess
from pathlib import Path

import httpx

from cineforge.providers.base import TTSProvider, VideoProvider, VLMQAProvider
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
    ):
        self.base_url = base_url.rstrip("/")
        self.workflow_path = workflow_template_path or Path("workflows/wan22_t2v_api.json")
        self.cost_per_shot = cost_per_shot

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
            while True:
                hist = (await client.get(f"{self.base_url}/history/{pid}")).json()
                if pid in hist:
                    outputs = hist[pid].get("outputs", {})
                    break
                await asyncio.sleep(2.0)

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
        img_b64 = base64.b64encode(keyframe_path.read_bytes()).decode("utf-8")
        prompt = (
            'Audit frame vs prompt. Reply ONLY JSON {"passed": bool, "score": float, "critique": "str"}.\n'
            f"Prompt: {grounded_prompt}"
        )
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            res = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "images": [img_b64],
                    "format": "json",
                    "stream": False,
                    "keep_alive": "10m",
                },
            )
            res.raise_for_status()
            raw = json.loads(res.json()["response"])
            return QAReport(
                passed=bool(raw.get("passed", False)),
                score=float(raw.get("score", 0.0)),
                critique=str(raw.get("critique", "")),
            )
