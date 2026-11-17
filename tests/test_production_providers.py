import json
import subprocess

import httpx
import pytest

from cineforge.providers.lipsync import MuseTalkLipSyncProvider
from cineforge.providers.registry import ComfyUIWan22Provider, KokoroTTSProvider, OllamaVLMQAProvider
from cineforge.schemas.bible import CharacterEntity
from cineforge.schemas.timeline import Shot


def _make_dummy_mp4(path):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=24:duration=1.0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return path.read_bytes()


@pytest.mark.asyncio
async def test_comfyui_wan22_provider_integration(tmp_path, monkeypatch):
    sample_mp4 = _make_dummy_mp4(tmp_path / "sample.mp4")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompt":
            payload = json.loads(request.content)
            assert "Cyberpunk skyline" in payload["prompt"]["6"]["inputs"]["text"]
            return httpx.Response(200, json={"prompt_id": "job_999"})
        if request.url.path == "/history/job_999":
            return httpx.Response(
                200,
                json={
                    "job_999": {
                        "outputs": {"60": {"videos": [{"filename": "out.mp4", "subfolder": "", "type": "output"}]}}
                    }
                },
            )
        if request.url.path == "/view":
            return httpx.Response(200, content=sample_mp4)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    orig_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: orig_client(transport=transport))

    prov = ComfyUIWan22Provider("http://comfy.local:8188", cost_per_shot=0.05)
    shot = Shot(
        shot_id="s_wan", scene_number=1, order_index=1, duration_sec=2.0, env_id="e1", visual_prompt="Cyberpunk skyline"
    )
    out_path, cost = await prov.generate_shot(shot, "Cyberpunk skyline", tmp_path, seed=108)
    assert out_path.exists()
    assert cost == 0.05


@pytest.mark.asyncio
async def test_kokoro_ollama_musetalk_providers(tmp_path, monkeypatch):
    sample_mp4 = _make_dummy_mp4(tmp_path / "base.mp4")
    dummy_png = tmp_path / "frame.png"
    dummy_png.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82')

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/audio/speech":
            return httpx.Response(200, content=b"RIFF_MOCK_WAV_BYTES")
        if request.url.path in ("/api/generate", "/api/chat"):
            return httpx.Response(
                200, json={"message": {"content": '{"passed": true, "score": 0.94, "defects": []}'}, "response": json.dumps({"passed": True, "score": 0.94, "critique": "Clean frame"})}
            )
        if request.url.path == "/v1/lipsync":
            return httpx.Response(200, content=sample_mp4)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    orig_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: orig_client(transport=transport))

    char = CharacterEntity(entity_id="c1", name="Arjun", visual_descriptor="Founder", voice_id="am_eric")
    tts = KokoroTTSProvider("http://kokoro.local:8880/v1", cost_per_1k_chars=0.01)
    wav_path, tts_cost = await tts.synthesize("Testing neural speech.", char, tmp_path / "out.wav")
    assert wav_path.read_bytes() == b"RIFF_MOCK_WAV_BYTES"
    assert tts_cost > 0

    vlm = OllamaVLMQAProvider("http://ollama.local:11434")
    shot = Shot(shot_id="s_qa", scene_number=1, order_index=1, duration_sec=1.0, env_id="e1", visual_prompt="Test")
    report = await vlm.inspect_shot(shot, "Test", dummy_png)
    assert report.passed is True and report.score == 0.94

    lip = MuseTalkLipSyncProvider("http://musetalk.local:8000")
    synced_path, _ = await lip.sync_lips(tmp_path / "base.mp4", wav_path, tmp_path / "synced.mp4")
    assert synced_path.exists()
