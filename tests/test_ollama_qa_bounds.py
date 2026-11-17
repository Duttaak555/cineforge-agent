import base64
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from cineforge.qa.ollama_critic import (
    MAX_QA_EDGE_PX,
    encode_keyframe_bounded,
    evaluate_keyframe,
    prewarm_ollama_vlm,
)


def test_encode_keyframe_downscales_to_768px(tmp_path: Path) -> None:
    src = tmp_path / "frame_4k.png"
    Image.new("RGB", (3840, 2160), color=(40, 90, 160)).save(src)

    b64_str, byte_len = encode_keyframe_bounded(src)
    assert byte_len > 0

    with Image.open(io.BytesIO(base64.b64decode(b64_str))) as out:
        assert max(out.size) == MAX_QA_EDGE_PX
        assert out.size == (768, 432)


@pytest.mark.asyncio
async def test_prewarm_and_evaluate_with_mock_transport(tmp_path: Path) -> None:
    src = tmp_path / "shot_01.png"
    Image.new("RGB", (1920, 1080), color=(120, 120, 120)).save(src)
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        body = json.loads(request.content.decode("utf-8"))
        if request.url.path == "/api/generate":
            assert body["keep_alive"] == "15m"
            assert body["options"]["num_ctx"] == 4096
            return httpx.Response(200, json={"response": "ready", "done": True})
        if request.url.path == "/api/chat":
            img_b64 = body["messages"][1]["images"][0]
            with Image.open(io.BytesIO(base64.b64decode(img_b64))) as sent_img:
                assert max(sent_img.size) <= MAX_QA_EDGE_PX
            return httpx.Response(
                200,
                json={"message": {"content": json.dumps({"passed": True, "score": 0.94, "defects": []})}},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        warm = await prewarm_ollama_vlm(client, "http://localhost:11434")
        assert warm["status"] == "warm"

        result = await evaluate_keyframe(client, "http://localhost:11434", src, "Wide shot of studio")
        assert result.passed is True
        assert result.score == pytest.approx(0.94)
        assert seen_paths == ["/api/generate", "/api/chat"]
