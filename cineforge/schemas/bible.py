from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class CharacterEntity(BaseModel):
    entity_id: str
    name: str
    visual_descriptor: str
    reference_image_paths: List[str] = Field(default_factory=list)
    lora_weights: Optional[str] = None
    voice_provider: str = "kokoro"
    voice_id: str
    locked_seed: int = 42

class EnvironmentEntity(BaseModel):
    env_id: str
    name: str
    lighting_and_atmosphere: str
    reference_image_path: Optional[str] = None
    color_lut_path: Optional[str] = None

class EntityBible(BaseModel):
    project_id: str
    title: str
    aspect_ratio: str = Field(default="16:9", pattern="^(16:9|9:16|1:1)$")
    fps: int = 24
    global_style_prompt: str = "Cinematic 35mm film grain, natural dynamic range, high detail"
    characters: Dict[str, CharacterEntity] = Field(default_factory=dict)
    environments: Dict[str, EnvironmentEntity] = Field(default_factory=dict)
