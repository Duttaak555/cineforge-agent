from abc import ABC, abstractmethod
from pathlib import Path

from cineforge.schemas.bible import CharacterEntity
from cineforge.schemas.timeline import QAReport, Shot


class VideoProvider(ABC):
    def estimate_cost(self, shot: Shot) -> float:
        return 0.0

    @abstractmethod
    async def generate_shot(
        self, shot: Shot, grounded_prompt: str, output_dir: Path, seed: int = 42
    ) -> tuple[Path, float]:
        pass


class TTSProvider(ABC):
    def estimate_cost(self, text: str) -> float:
        return 0.0

    @abstractmethod
    async def synthesize(
        self, text: str, character: CharacterEntity, output_path: Path, speed: float = 1.0
    ) -> tuple[Path, float]:
        pass


class VLMQAProvider(ABC):
    @abstractmethod
    async def inspect_shot(self, shot: Shot, grounded_prompt: str, keyframe_path: Path) -> QAReport:
        pass


class LipSyncProvider(ABC):
    @abstractmethod
    async def sync_lips(self, video_path: Path, audio_path: Path, output_path: Path) -> tuple[Path, float]:
        pass
