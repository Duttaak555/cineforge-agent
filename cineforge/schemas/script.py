from pydantic import BaseModel


class DialogueLine(BaseModel):
    line_id: str
    speaker_entity_id: str
    raw_text: str
    ssml_text: str
    emotion: str = "neutral"
    requires_lip_sync: bool = True


class Scene(BaseModel):
    scene_number: int
    env_entity_id: str
    summary: str
    estimated_duration_sec: float
    dialogue: list[DialogueLine] = []


class Script(BaseModel):
    project_id: str
    logline: str
    target_duration_sec: int
    scenes: list[Scene]
