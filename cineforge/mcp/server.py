from mcp.server.fastmcp import FastMCP
from cineforge.config import settings
from cineforge.schemas.bible import EntityBible, CharacterEntity, EnvironmentEntity
from cineforge.schemas.script import Script, Scene, DialogueLine
from cineforge.schemas.timeline import ShotList, Shot, RenderEngineType
from cineforge.core.orchestrator import VideoOrchestrator
from cineforge.core.exporter import export_to_otio, render_master_mp4
from cineforge.providers.registry import ComfyUIWan22Provider, KokoroTTSProvider, OllamaVLMQAProvider
from cineforge.providers.lipsync import MuseTalkLipSyncProvider, PassthroughLipSyncProvider
from cineforge.providers.mock import MockVideoProvider, MockTTSProvider, MockVLMQAProvider

mcp = FastMCP("CineForge-Studio")

@mcp.tool()
def init_project(project_id: str, title: str, aspect_ratio: str = "16:9", budget_usd: float = 5.0) -> str:
    orch = VideoOrchestrator(settings.workspace_dir / project_id)
    orch.save_state(EntityBible(project_id=project_id, title=title, aspect_ratio=aspect_ratio), ShotList(project_id=project_id, total_budget_usd=budget_usd))
    return f"Initialized '{project_id}' with ${budget_usd:.2f} budget cap."

@mcp.tool()
def register_character(project_id: str, entity_id: str, name: str, visual_descriptor: str, voice_id: str, locked_seed: int = 42) -> str:
    orch = VideoOrchestrator(settings.workspace_dir / project_id)
    bible, shotlist, script = orch.load_state()
    bible.characters[entity_id] = CharacterEntity(entity_id=entity_id, name=name, visual_descriptor=visual_descriptor, voice_id=voice_id, locked_seed=locked_seed)
    orch.save_state(bible, shotlist, script)
    return f"Registered character '{name}'."

@mcp.tool()
def register_environment(project_id: str, env_id: str, name: str, lighting_and_atmosphere: str) -> str:
    orch = VideoOrchestrator(settings.workspace_dir / project_id)
    bible, shotlist, script = orch.load_state()
    bible.environments[env_id] = EnvironmentEntity(env_id=env_id, name=name, lighting_and_atmosphere=lighting_and_atmosphere)
    orch.save_state(bible, shotlist, script)
    return f"Registered environment '{name}'."

@mcp.tool()
def add_shot(project_id: str, shot_id: str, scene_number: int, order_index: int, duration_sec: float, env_id: str, visual_prompt: str, character_ids: list[str] | None = None, engine: str = "t2v_i2v", html_template_spec: str | None = None, dialogue_text: str | None = None, speaker_entity_id: str | None = None, requires_lip_sync: bool = False) -> str:
    orch = VideoOrchestrator(settings.workspace_dir / project_id)
    bible, shotlist, script = orch.load_state()
    if script is None: script = Script(project_id=project_id, logline=bible.title, target_duration_sec=60, scenes=[])
    line_id = None
    if dialogue_text and speaker_entity_id:
        line_id = f"line_{shot_id}"
        scene = next((s for s in script.scenes if s.scene_number == scene_number), None)
        if not scene:
            scene = Scene(scene_number=scene_number, env_entity_id=env_id, summary=f"Scene {scene_number}", estimated_duration_sec=duration_sec)
            script.scenes.append(scene)
        scene.dialogue.append(DialogueLine(line_id=line_id, speaker_entity_id=speaker_entity_id, raw_text=dialogue_text, ssml_text=f"<speak>{dialogue_text}</speak>", requires_lip_sync=requires_lip_sync))
    shotlist.shots.append(Shot(shot_id=shot_id, scene_number=scene_number, order_index=order_index, duration_sec=duration_sec, env_id=env_id, visual_prompt=visual_prompt, character_ids=character_ids or [], engine=RenderEngineType(engine), html_template_spec=html_template_spec, dialogue_line_id=line_id))
    orch.save_state(bible, shotlist, script)
    return f"Added {shot_id}."

@mcp.tool()
async def run_pipeline(project_id: str, mode: str | None = None) -> str:
    active_mode = mode or settings.mode
    proj_dir = settings.workspace_dir / project_id
    orch = VideoOrchestrator(proj_dir)
    if active_mode == "production":
        v_prov, t_prov, q_prov, l_prov = ComfyUIWan22Provider(settings.comfyui_url), KokoroTTSProvider(settings.kokoro_url), OllamaVLMQAProvider(settings.ollama_url, settings.ollama_vlm_model), MuseTalkLipSyncProvider(settings.lipsync_url)
    else:
        v_prov, t_prov, q_prov, l_prov = MockVideoProvider(), MockTTSProvider(), MockVLMQAProvider(), PassthroughLipSyncProvider()
    shotlist = await orch.run(v_prov, t_prov, q_prov, l_prov)
    bible, _, _ = orch.load_state()
    otio_path = export_to_otio(shotlist, proj_dir / f"{project_id}.otio", fps=bible.fps)
    mp4_path = render_master_mp4(shotlist, bible, proj_dir / f"{project_id}_master.mp4", settings.c2pa_cert_path, settings.c2pa_key_path)
    return f"Completed! Master MP4: {mp4_path.resolve()} | NLE: {otio_path.resolve()} | Spend: ${shotlist.spent_usd:.2f}"

def main(): mcp.run()
if __name__ == "__main__": main()
