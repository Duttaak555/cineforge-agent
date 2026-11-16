import re
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from cineforge.config import settings
from cineforge.core.exporter import export_to_otio, render_master_mp4
from cineforge.core.orchestrator import VideoOrchestrator
from cineforge.providers.base import LipSyncProvider, TTSProvider, VideoProvider, VLMQAProvider
from cineforge.providers.hybrid import resolve_hybrid_providers
from cineforge.providers.lipsync import MuseTalkLipSyncProvider, PassthroughLipSyncProvider
from cineforge.providers.mock import MockTTSProvider, MockVideoProvider, MockVLMQAProvider
from cineforge.providers.registry import ComfyUIWan22Provider, KokoroTTSProvider, OllamaVLMQAProvider
from cineforge.schemas.bible import CharacterEntity, EntityBible, EnvironmentEntity
from cineforge.schemas.script import DialogueLine, Scene, Script
from cineforge.schemas.timeline import RenderEngineType, Shot, ShotList, ShotStatus

mcp = MCPServer("CineForge-Studio")
PROJECT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _resolve_project_dir(project_id: str) -> Path:
    if not PROJECT_ID_RE.match(project_id):
        raise ValueError(f"Invalid project_id '{project_id}'. Must match ^[a-zA-Z0-9_-]{{1,64}}$.")
    base = settings.workspace_dir.resolve()
    base.mkdir(parents=True, exist_ok=True)
    target = (base / project_id).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"Path traversal blocked for project_id '{project_id}'.")
    return target


@mcp.tool()
def init_project(project_id: str, title: str, aspect_ratio: str = "16:9", budget_usd: float = 5.0) -> str:
    """Initialize a new CineForge video project with an EntityBible and ShotList."""
    proj_dir = _resolve_project_dir(project_id)
    orch = VideoOrchestrator(proj_dir)
    orch.save_state(
        EntityBible(project_id=project_id, title=title, aspect_ratio=aspect_ratio),
        ShotList(project_id=project_id, total_budget_usd=budget_usd),
    )
    return f"Initialized '{project_id}' with ${budget_usd:.2f} budget cap."


@mcp.tool()
def register_character(
    project_id: str, entity_id: str, name: str, visual_descriptor: str, voice_id: str, locked_seed: int = 42
) -> str:
    """Lock a character's visual tokens, seed, and voice ID in the EntityBible."""
    orch = VideoOrchestrator(_resolve_project_dir(project_id))
    bible, shotlist, script = orch.load_state()
    bible.characters[entity_id] = CharacterEntity(
        entity_id=entity_id,
        name=name,
        visual_descriptor=visual_descriptor,
        voice_id=voice_id,
        locked_seed=locked_seed,
    )
    orch.save_state(bible, shotlist, script)
    return f"Registered character '{name}'."


@mcp.tool()
def register_environment(project_id: str, env_id: str, name: str, lighting_and_atmosphere: str) -> str:
    """Lock a recurring location and lighting profile in the EntityBible."""
    orch = VideoOrchestrator(_resolve_project_dir(project_id))
    bible, shotlist, script = orch.load_state()
    bible.environments[env_id] = EnvironmentEntity(
        env_id=env_id, name=name, lighting_and_atmosphere=lighting_and_atmosphere
    )
    orch.save_state(bible, shotlist, script)
    return f"Registered environment '{name}'."


@mcp.tool()
def add_shot(
    project_id: str,
    shot_id: str,
    scene_number: int,
    order_index: int,
    duration_sec: float,
    env_id: str,
    visual_prompt: str,
    character_ids: list[str] | None = None,
    engine: str = "t2v_i2v",
    html_template_spec: str | None = None,
    dialogue_text: str | None = None,
    speaker_entity_id: str | None = None,
    requires_lip_sync: bool = False,
) -> str:
    """Add a generative, HTML motion graphic, or lip-synced talking-head shot to the timeline."""
    orch = VideoOrchestrator(_resolve_project_dir(project_id))
    bible, shotlist, script = orch.load_state()
    if script is None:
        script = Script(project_id=project_id, logline=bible.title, target_duration_sec=60, scenes=[])
    line_id = None
    if dialogue_text and speaker_entity_id:
        line_id = f"line_{shot_id}"
        scene = next((s for s in script.scenes if s.scene_number == scene_number), None)
        if not scene:
            scene = Scene(
                scene_number=scene_number,
                env_entity_id=env_id,
                summary=f"Scene {scene_number}",
                estimated_duration_sec=duration_sec,
            )
            script.scenes.append(scene)
        scene.dialogue.append(
            DialogueLine(
                line_id=line_id,
                speaker_entity_id=speaker_entity_id,
                raw_text=dialogue_text,
                ssml_text=f"<speak>{dialogue_text}</speak>",
                requires_lip_sync=requires_lip_sync,
            )
        )
    shotlist.shots.append(
        Shot(
            shot_id=shot_id,
            scene_number=scene_number,
            order_index=order_index,
            duration_sec=duration_sec,
            env_id=env_id,
            visual_prompt=visual_prompt,
            character_ids=character_ids or [],
            engine=RenderEngineType(engine),
            html_template_spec=html_template_spec,
            dialogue_line_id=line_id,
        )
    )
    orch.save_state(bible, shotlist, script)
    return f"Added {shot_id}."


@mcp.tool()
async def run_pipeline(
    project_id: str, mode: str | None = None, allow_partial: bool = False, require_signed_c2pa: bool = False
) -> str:
    """Execute TTS, video/HTML rendering, lip-sync, VLM QA retries, Master MP4 + C2PA signing, and .otio export."""
    active_mode = (mode or settings.mode).lower()
    proj_dir = _resolve_project_dir(project_id)
    orch = VideoOrchestrator(proj_dir)

    v_prov: VideoProvider
    t_prov: TTSProvider
    q_prov: VLMQAProvider
    l_prov: LipSyncProvider

    if active_mode == "production":
        v_prov = ComfyUIWan22Provider(settings.comfyui_url, cost_per_shot=settings.comfyui_cost_per_shot)
        t_prov = KokoroTTSProvider(settings.kokoro_url, cost_per_1k_chars=settings.kokoro_cost_per_1k_chars)
        q_prov = OllamaVLMQAProvider(
            settings.ollama_url, settings.ollama_vlm_model, timeout_sec=settings.ollama_timeout_sec
        )
        l_prov = MuseTalkLipSyncProvider(settings.lipsync_url)
        provider_summary = "production (ComfyUI + Kokoro + Ollama + MuseTalk)"
    elif active_mode == "hybrid":
        v_prov, t_prov, q_prov, l_prov, status_map = resolve_hybrid_providers()
        provider_summary = "hybrid (" + ", ".join(f"{k}={v}" for k, v in status_map.items()) + ")"
    else:
        v_prov = MockVideoProvider()
        t_prov = MockTTSProvider()
        q_prov = MockVLMQAProvider()
        l_prov = PassthroughLipSyncProvider()
        provider_summary = "mock (offline zero-GPU)"

    shotlist = await orch.run(v_prov, t_prov, q_prov, l_prov, allow_partial=allow_partial)
    bible, _, _ = orch.load_state()
    otio_path = export_to_otio(shotlist, proj_dir / f"{project_id}.otio", fps=bible.fps)
    mp4_path, is_signed = render_master_mp4(
        shotlist,
        bible,
        proj_dir / f"{project_id}_master.mp4",
        settings.c2pa_cert_path,
        settings.c2pa_key_path,
        require_signed=require_signed_c2pa,
    )
    failed = [s.shot_id for s in shotlist.shots if s.status != ShotStatus.APPROVED]
    c2pa_status = "C2PA X.509 Signed" if is_signed else "Unsigned Provenance Sidecar (.unsigned_c2pa.json)"
    status_label = f"Completed (Partial — skipped QA-failed shots: {failed})" if failed else "Completed"
    return f"{status_label} [{provider_summary}]! Master MP4: {mp4_path.resolve()} [{c2pa_status}] | NLE: {otio_path.resolve()} | Spend: ${shotlist.spent_usd:.2f}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
