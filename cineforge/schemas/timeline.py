from enum import Enum
from typing import List, Optional
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
    lip_sync_confidence: Optional[float] = None

class Shot(BaseModel):
    shot_id: str
    scene_number: int
    order_index: int
    engine: RenderEngineType = RenderEngineType.T2V_I2V
    duration_sec: float
    character_ids: List[str] = Field(default_factory=list)
    env_id: str
    visual_prompt: str
    camera_motion: str = "static"
    html_template_spec: Optional[str] = None
    dialogue_line_id: Optional[str] = None
    status: ShotStatus = ShotStatus.PENDING
    retry_count: int = 0
    cost_usd: float = 0.0
    keyframe_path: Optional[str] = None
    audio_path: Optional[str] = None
    video_path: Optional[str] = None
    qa_report: Optional[QAReport] = None

class ShotList(BaseModel):
    project_id: str
    total_budget_usd: float = 5.0
    spent_usd: float = 0.0
    shots: List[Shot] = Field(default_factory=list)
