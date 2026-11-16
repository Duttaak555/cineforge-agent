from enum import Enum

from pydantic import BaseModel, Field


class RenderEngineType(str, Enum):
    T2V_I2V = "t2v_i2v"
    HTML_MOTION = "html_motion"
    REMOTION = "remotion"


class ShotStatus(str, Enum):
    PENDING = "pending"
    RENDERED = "rendered"
    QA_FAILED = "qa_failed"
    APPROVED = "approved"


class QAReport(BaseModel):
    passed: bool
    score: float = Field(..., ge=0.0, le=1.0)
    critique: str
    lip_sync_confidence: float | None = None


class Shot(BaseModel):
    shot_id: str
    scene_number: int
    order_index: int
    engine: RenderEngineType = RenderEngineType.T2V_I2V
    duration_sec: float
    character_ids: list[str] = Field(default_factory=list)
    env_id: str
    visual_prompt: str
    camera_motion: str = "static"
    html_template_spec: str | None = None
    dialogue_line_id: str | None = None
    status: ShotStatus = ShotStatus.PENDING
    retry_count: int = 0
    cost_usd: float = 0.0
    keyframe_path: str | None = None
    audio_path: str | None = None
    video_path: str | None = None
    qa_report: QAReport | None = None


class ShotList(BaseModel):
    project_id: str
    total_budget_usd: float = 5.0
    spent_usd: float = 0.0
    shots: list[Shot] = Field(default_factory=list)
