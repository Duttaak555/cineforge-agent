import subprocess
from pathlib import Path
from cineforge.providers.base import VideoProvider, TTSProvider, VLMQAProvider
from cineforge.schemas.bible import CharacterEntity
from cineforge.schemas.timeline import Shot, QAReport

class MockVideoProvider(VideoProvider):
    async def generate_shot(self, shot: Shot, grounded_prompt: str, output_dir: Path, seed: int = 42) -> tuple[Path, float]:
        out = output_dir / f"{shot.shot_id}.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=24:duration={shot.duration_sec}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return out, 0.01

class MockTTSProvider(TTSProvider):
    async def synthesize(self, text: str, character: CharacterEntity, output_path: Path, speed: float = 1.0) -> tuple[Path, float]:
        dur = max(1.0, len(text.split()) * 0.4)
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=24000:duration={dur}", "-af", "volume=0.05", str(output_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_path, 0.0

class MockVLMQAProvider(VLMQAProvider):
    async def inspect_shot(self, shot: Shot, grounded_prompt: str, keyframe_path: Path) -> QAReport:
        if "FORCE_QA_FAIL" in grounded_prompt and shot.retry_count == 0:
            return QAReport(passed=False, score=0.42, critique="Simulated hand anatomy distortion on frame 12")
        return QAReport(passed=True, score=0.96, critique="Prompt fidelity, lighting, and anatomy verified.")
