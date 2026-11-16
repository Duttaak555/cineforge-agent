import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from cineforge.config import settings
from cineforge.mcp.server import init_project, register_character, register_environment, add_shot, run_pipeline


def _build_valid_wav(path: Path) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000:duration=1.0", str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return path.read_bytes()


@pytest.mark.asyncio
async def test_hybrid_mode_runtime_timeout_fallback(tmp_path):
    """Verifies MODE=hybrid falls back gracefully when a reachable Ollama endpoint times out mid-inference."""
    sample_wav = _build_valid_wav(tmp_path / 'hybrid.wav')

    class SlowOllamaHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            if self.path in ("/v1/models", "/api/tags"):
                data = json.dumps({"models": [{"name": "qwen2.5vl:7b"}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            _ = self.rfile.read(length)
            if self.path == "/v1/audio/speech":
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(sample_wav)))
                self.end_headers()
                self.wfile.write(sample_wav)
            elif self.path == "/api/generate":
                time.sleep(1.5)
            else:
                self.send_response(404)
                self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowOllamaHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        base_url = f"http://127.0.0.1:{port}"
        settings.workspace_dir = tmp_path
        settings.comfyui_url = "http://127.0.0.1:59991"
        settings.lipsync_url = "http://127.0.0.1:59992"
        settings.kokoro_url = f"{base_url}/v1"
        settings.ollama_url = base_url
        settings.ollama_timeout_sec = 0.2

        pid = "mac_hybrid_timeout_proj"
        init_project(pid, "MacBook Hybrid Timeout Fallback", budget_usd=1.0)
        register_character(pid, "c1", "Arjun", "Founder", "am_eric")
        register_environment(pid, "e1", "Office", "Natural light")
        add_shot(pid, "s1", 1, 1, 1.0, "e1", "Arjun presenting", character_ids=["c1"], dialogue_text="Graceful timeout fallback.", speaker_entity_id="c1", requires_lip_sync=True)
        summary = await run_pipeline(pid, mode="hybrid")
        assert "MockVideo (fallback)" in summary
        assert "with runtime fallback" in summary
        assert (tmp_path / pid / "mac_hybrid_timeout_proj_master.mp4").exists()
    finally:
        settings.ollama_timeout_sec = 300.0
        server.shutdown()
        server.server_close()
