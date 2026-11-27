from pathlib import Path

import pytest

from cineforge.core.orchestrator import VideoOrchestrator
from cineforge.providers.workflow_templates import render_wan22_i2v_workflow
from cineforge.schemas.bible import CharacterEntity, EntityBible
from cineforge.schemas.timeline import Shot

TEMPLATE = Path(__file__).resolve().parents[1] / "workflows" / "wan22_i2v_api.json"


def test_wan22_i2v_binds_entity_bible_into_prompt_graph(tmp_path: Path) -> None:
    character = CharacterEntity(
        entity_id="lead",
        name="Lead",
        visual_descriptor='green coat and "silver" glasses',
        voice_id="unused",
        locked_seed=71,
        reference_image_paths=["shots/opening frame.png"],
    )
    bible = EntityBible(project_id="demo", title="Demo", characters={"lead": character})
    shot = Shot(
        shot_id="opening",
        scene_number=1,
        order_index=0,
        duration_sec=2,
        character_ids=["lead"],
        env_id="station",
        visual_prompt="The camera moves left.",
    )
    prompt = VideoOrchestrator(tmp_path).compile_grounded_prompt(shot, bible)
    graph = render_wan22_i2v_workflow(
        TEMPLATE,
        positive_prompt=prompt,
        negative_prompt="blurry",
        seed=character.locked_seed,
        image_path=character.reference_image_paths[0],
    )

    assert 'green coat and "silver" glasses' in graph["6"]["inputs"]["text"] == prompt
    assert graph["7"]["inputs"]["text"] == "blurry"
    assert graph["3"]["inputs"]["seed"] == 71
    assert graph["56"]["inputs"]["image"] == "shots/opening frame.png"
    assert graph["55"]["class_type"] == "Wan22ImageToVideoLatent"
    assert graph["55"]["inputs"]["start_image"] == ["56", 0]
    assert graph["3"]["inputs"]["latent_image"] == ["55", 0]
    assert graph["58"]["inputs"]["video"] == ["57", 0]

    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                source, output_index = value
                assert source in graph
                assert isinstance(output_index, int)


def test_wan22_i2v_rejects_an_incomplete_template(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"56":{"inputs":{"image":"not-a-placeholder"}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="Missing I2V placeholders"):
        render_wan22_i2v_workflow(broken, positive_prompt="shot", negative_prompt="", seed=1, image_path="image.png")
