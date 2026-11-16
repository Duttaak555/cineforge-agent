from abc import ABC, abstractmethod
from pathlib import Path
from cineforge.schemas.bible import CharacterEntity
from cineforge.schemas.timeline import Shot, QAReport

class VideoProvider(ABC):
    @abstractmethod
    async def generate_shot(self, shot: Shot, grounded_prompt: str, output_dir: Path, seed: int = 42) -> tuple[Path, float]: pass

class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, character: CharacterEntity, output_path: Path, speed: float = 1.0) -> tuple[Path, float]: pass

class VLMQAProvider(ABC):
    @abstractmethod
    async def inspect_shot(self, shot: Shot, grounded_prompt: str, keyframe_path: Path) -> QAReport: pass
