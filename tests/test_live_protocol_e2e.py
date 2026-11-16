import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cineforge.config import settings
from cineforge.mcp.server import add_shot, init_project, register_character, register_environment, run_pipeline


def _build_valid_mp4(path: Path) -> bytes:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=24:duration=1.0",
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


def _build_valid_wav(path: Path) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000:duration=1.0", str(path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return path.read_bytes()


@pytest.mark.asyncio
async def test_production_mode_over_real_local_http_sockets(tmp_path: Path) -> None:
    sample_mp4 = _build_valid_mp4(tmp_path / "fixture.mp4")
    sample_wav = _build_valid_wav(tmp_path / "fixture.wav")

    class ProductionStubHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            _ = self.rfile.read(length)
            if self.path == "/prompt":
                self._send_json({"prompt_id": "live_socket_job_1"})
            elif self.path == "/v1/audio/speech":
                self._send_bytes(sample_wav, "audio/wav")
            elif self.path == "/api/generate":
                self._send_json(
                    {"response": json.dumps({"passed": True, "score": 0.98, "critique": "Verified over TCP"})}
                )
            elif self.path == "/v1/lipsync":
                self._send_bytes(sample_mp4, "video/mp4")
            else:
                self.send_response(404)
                self.end_headers()

        def do_GET(self) -> None:
            if self.path.startswith("/history/live_socket_job_1"):
                self._send_json(
                    {
                        "live_socket_job_1": {
                            "outputs": {"60": {"videos": [{"filename": "wan.mp4", "subfolder": "", "type": "output"}]}}
                        }
                    }
                )
            elif self.path.startswith("/view"):
                self._send_bytes(sample_mp4, "video/mp4")
            else:
                self.send_response(404)
                self.end_headers()

        def _send_json(self, obj: dict[str, object]) -> None:
            data = json.dumps(obj).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_bytes(self, raw: bytes, mime: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), ProductionStubHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        base_url = f"http://127.0.0.1:{port}"
        settings.workspace_dir = tmp_path
        settings.comfyui_url = base_url
        settings.kokoro_url = f"{base_url}/v1"
        settings.ollama_url = base_url
        settings.lipsync_url = base_url

        pid = "socket_e2e_proj"
        init_project(pid, "Real Socket E2E", budget_usd=2.0)
        register_character(pid, "c1", "Arjun", "Founder", "am_eric")
        register_environment(pid, "e1", "Studio", "Soft daylight")
        add_shot(
            pid,
            "s1",
            1,
            1,
            1.0,
            "e1",
            "Arjun speaking to camera",
            character_ids=["c1"],
            dialogue_text="Verified over TCP.",
            speaker_entity_id="c1",
            requires_lip_sync=True,
        )
        summary = await run_pipeline(pid, mode="production")
        assert "socket_e2e_proj_master.mp4" in summary
        assert (tmp_path / pid / "socket_e2e_proj_master.mp4").exists()
        assert (tmp_path / pid / "socket_e2e_proj.otio").exists()
    finally:
        server.shutdown()
        server.server_close()
