import pytest

from cineforge.config import settings
from cineforge.core.orchestrator import BudgetExceededError
from cineforge.mcp.server import add_shot, init_project, register_character, register_environment, run_pipeline


@pytest.mark.asyncio
async def test_end_to_end_mixed_engines_and_export(tmp_path):
    settings.workspace_dir = tmp_path
    pid = "ci_test_proj"
    init_project(pid, "CI Verification Film", budget_usd=1.0)
    register_character(pid, "c1", "Maya", "Cyberpunk architect, neon visor", "af_bella")
    register_environment(pid, "e1", "Lab", "Cool cyan volumetric lighting")
    add_shot(
        pid,
        "s1",
        1,
        1,
        1.5,
        "e1",
        "Maya inspecting timeline FORCE_QA_FAIL",
        character_ids=["c1"],
        dialogue_text="All systems nominal.",
        speaker_entity_id="c1",
        requires_lip_sync=True,
    )
    add_shot(pid, "s2", 1, 2, 1.0, "e1", "HTML Title", engine="html_motion", html_template_spec="<div>TITLE</div>")
    summary = await run_pipeline(pid, mode="mock")
    assert "ci_test_proj_master.mp4" in summary
    assert "Unsigned Provenance Sidecar" in summary
    assert (tmp_path / pid / "ci_test_proj_master.mp4").exists()
    assert (tmp_path / pid / "ci_test_proj_master.unsigned_c2pa.json").exists()
    assert (tmp_path / pid / "ci_test_proj.otio").exists()


def test_path_traversal_blocked(tmp_path):
    settings.workspace_dir = tmp_path
    with pytest.raises(ValueError, match="Invalid project_id"):
        init_project("../escape_attempt", "Malicious Project")


@pytest.mark.asyncio
async def test_budget_cap_enforced(tmp_path):
    settings.workspace_dir = tmp_path
    pid = "budget_proj"
    init_project(pid, "Tight Budget", budget_usd=0.01)
    register_environment(pid, "e1", "Lab", "Dim")
    add_shot(pid, "s1", 1, 1, 1.0, "e1", "Shot 1")
    add_shot(pid, "s2", 1, 2, 1.0, "e1", "Shot 2")
    with pytest.raises(BudgetExceededError):
        await run_pipeline(pid, mode="mock")
