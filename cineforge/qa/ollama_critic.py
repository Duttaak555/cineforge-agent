from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image
from pydantic import BaseModel, Field

MAX_QA_EDGE_PX = 768
QA_JPEG_QUALITY = 85


class QACritiqueResult(BaseModel):
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    defects: list[str] = Field(default_factory=list)
    latency_ms: int
    encoded_bytes: int


def encode_keyframe_bounded(
    image_path: Path,
    max_edge: int = MAX_QA_EDGE_PX,
    quality: int = QA_JPEG_QUALITY,
) -> tuple[str, int]:
    """Downscale keyframe to <= max_edge on longest side and return (base64_str, byte_len)."""
    with Image.open(image_path) as img:
        rgb = img.convert("RGB")
        width, height = rgb.size
        longest = max(width, height)
        if longest > max_edge:
            scale = max_edge / float(longest)
            new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
            rgb = rgb.resize(new_size, Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=quality, optimize=True)
        raw = buf.getvalue()
        return base64.b64encode(raw).decode("ascii"), len(raw)


async def prewarm_ollama_vlm(
    client: httpx.AsyncClient,
    base_url: str,
    model: str = "qwen2.5vl:7b",
    keep_alive: str = "15m",
    num_ctx: int = 4096,
) -> dict[str, Any]:
    """Load Qwen2.5-VL into VRAM prior to shot generation so QA passes never pay cold-load latency."""
    t0 = time.perf_counter()
    resp = await client.post(
        f"{base_url.rstrip('/')}/api/generate",
        json={
            "model": model,
            "prompt": "ready",
            "stream": False,
            "keep_alive": keep_alive,
            "options": {"num_ctx": num_ctx, "num_predict": 1, "temperature": 0.0},
        },
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
    )
    resp.raise_for_status()
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {"model": model, "status": "warm", "warmup_ms": elapsed_ms, "keep_alive": keep_alive}


async def evaluate_keyframe(
    client: httpx.AsyncClient,
    base_url: str,
    image_path: Path,
    shot_brief: str,
    model: str = "qwen2.5vl:7b",
    keep_alive: str = "15m",
) -> QACritiqueResult:
    """Run bounded-resolution, bounded-timeout Qwen2.5-VL inspection on a rendered keyframe."""
    b64_img, encoded_bytes = encode_keyframe_bounded(image_path)
    t0 = time.perf_counter()

    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "keep_alive": keep_alive,
        "options": {"num_ctx": 4096, "temperature": 0.1, "num_predict": 256},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict cinema QA critic. Return JSON only: "
                    '{"passed": bool, "score": float (0-1), "defects": [str]}.'
                ),
            },
            {
                "role": "user",
                "content": f"Verify visual adherence, framing, and anatomy against shot brief: {shot_brief}",
                "images": [b64_img],
            },
        ],
    }

    resp = await client.post(
        f"{base_url.rstrip('/')}/api/chat",
        json=payload,
        timeout=httpx.Timeout(connect=10.0, read=90.0, write=15.0, pool=10.0),
    )
    resp.raise_for_status()
    raw_content = resp.json()["message"]["content"]
    data = json.loads(raw_content)
    return QACritiqueResult(
        passed=bool(data["passed"]),
        score=float(data["score"]),
        defects=list(data.get("defects", [])),
        latency_ms=int((time.perf_counter() - t0) * 1000),
        encoded_bytes=encoded_bytes,
    )
