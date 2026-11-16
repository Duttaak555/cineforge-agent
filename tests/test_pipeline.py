import pytest
from cineforge.config import settings
from cineforge.mcp.server import init_project, register_character, register_environment, add_shot, run_pipeline

@pytest.mark.asyncio
async def test_end_to_end_self_healing_and_export(tmp_path):
    settings.workspace_dir = tmp_path
    pid = "ci_test_proj"
    init_project(pid, "CI Verification Film", budget_usd=1.0)
    register_character(pid, "c1", "Maya", "Cyberpunk architect, neon visor", "af_bella")
    register_environment(pid, "e1", "Lab", "Cool cyan volumetric lighting")
    add_shot(pid, "s1", 1, 1, 1.5, "e1", "Maya inspecting timeline FORCE_QA_FAIL", character_ids=["c1"], dialogue_text="All systems nominal.", speaker_entity_id="c1", requires_lip_sync=True)
    summary = await run_pipeline(pid, mode="mock")
    assert "ci_test_proj_master.mp4" in summary
    assert (tmp_path / pid / "ci_test_proj_master.mp4").exists()
    assert (tmp_path / pid / "ci_test_proj_master.c2pa.json").exists()
    assert (tmp_path / pid / "ci_test_proj.otio").exists()
