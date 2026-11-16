from pathlib import Path

from cineforge.providers.base import TTSProvider, VideoProvider, VLMQAProvider
from cineforge.providers.lipsync import LipSyncProvider
from cineforge.providers.registry import extract_mid_frame
from cineforge.renderers.html_motion import render_html_motion_shot
from cineforge.schemas.bible import EntityBible
from cineforge.schemas.script import Script
from cineforge.schemas.timeline import RenderEngineType, Shot, ShotList, ShotStatus


class BudgetExceededError(RuntimeError):
    pass


class PipelineIncompleteError(RuntimeError):
    pass


class VideoOrchestrator:
    def __init__(self, workspace_dir: Path, max_retries: int = 2):
        self.workspace = workspace_dir
        self.assets_dir = workspace_dir / "assets"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.bible_path = self.workspace / "bible.json"
        self.script_path = self.workspace / "script.json"
        self.shotlist_path = self.workspace / "shotlist.json"

    def save_state(self, bible: EntityBible, shotlist: ShotList, script: Script | None = None) -> None:
        self.bible_path.write_text(bible.model_dump_json(indent=2))
        self.shotlist_path.write_text(shotlist.model_dump_json(indent=2))
        if script:
            self.script_path.write_text(script.model_dump_json(indent=2))

    def load_state(self) -> tuple[EntityBible, ShotList, Script | None]:
        return (
            EntityBible.model_validate_json(self.bible_path.read_text()),
            ShotList.model_validate_json(self.shotlist_path.read_text()),
            Script.model_validate_json(self.script_path.read_text()) if self.script_path.exists() else None,
        )

    def compile_grounded_prompt(self, shot: Shot, bible: EntityBible) -> str:
        env = bible.environments.get(shot.env_id)
        env_desc = f"{env.name}, {env.lighting_and_atmosphere}" if env else ""
        char_descs = [
            f"[{bible.characters[c].name}: {bible.characters[c].visual_descriptor}]"
            for c in shot.character_ids
            if c in bible.characters
        ]
        return " | ".join(
            p
            for p in [
                bible.global_style_prompt,
                env_desc,
                " ".join(char_descs),
                shot.visual_prompt,
                f"Camera: {shot.camera_motion}",
            ]
            if p
        )

    async def run(
        self,
        video_provider: VideoProvider,
        tts_provider: TTSProvider,
        qa_provider: VLMQAProvider,
        lipsync_provider: LipSyncProvider,
        allow_partial: bool = False,
    ) -> ShotList:
        bible, shotlist, script = self.load_state()
        dialogue_lookup = {line.line_id: line for scene in (script.scenes if script else []) for line in scene.dialogue}

        for shot in shotlist.shots:
            if shot.status == ShotStatus.APPROVED:
                continue

            line = dialogue_lookup.get(shot.dialogue_line_id) if shot.dialogue_line_id else None
            if line and line.speaker_entity_id in bible.characters:
                est_tts = tts_provider.estimate_cost(line.raw_text)
                if round(shotlist.spent_usd + est_tts, 4) > shotlist.total_budget_usd:
                    self.save_state(bible, shotlist, script)
                    raise BudgetExceededError(
                        f"Projected TTS cost (${est_tts:.4f}) would exceed budget cap ${shotlist.total_budget_usd:.2f}."
                    )
                audio_path, tts_cost = await tts_provider.synthesize(
                    line.raw_text,
                    bible.characters[line.speaker_entity_id],
                    self.assets_dir / f"{shot.shot_id}_voice.wav",
                )
                shot.audio_path = str(audio_path)
                shotlist.spent_usd = round(shotlist.spent_usd + tts_cost, 4)

            grounded_prompt = self.compile_grounded_prompt(shot, bible)
            seed = bible.characters[shot.character_ids[0]].locked_seed if shot.character_ids else 42

            while shot.retry_count <= self.max_retries:
                is_html = shot.engine == RenderEngineType.HTML_MOTION and bool(shot.html_template_spec)
                est_render = 0.0 if is_html else video_provider.estimate_cost(shot)
                if round(shotlist.spent_usd + est_render, 4) > shotlist.total_budget_usd:
                    self.save_state(bible, shotlist, script)
                    raise BudgetExceededError(
                        f"Projected render cost (${est_render:.4f}) on {shot.shot_id} would exceed budget cap ${shotlist.total_budget_usd:.2f}."
                    )

                if is_html:
                    raw_vid, cost = await render_html_motion_shot(
                        shot.html_template_spec,
                        shot.duration_sec,
                        self.assets_dir / f"{shot.shot_id}.mp4",
                        fps=bible.fps,
                    )
                else:
                    raw_vid, cost = await video_provider.generate_shot(
                        shot, grounded_prompt, self.assets_dir, seed=seed
                    )

                shot.cost_usd = round(shot.cost_usd + cost, 4)
                shotlist.spent_usd = round(shotlist.spent_usd + cost, 4)

                if line and line.requires_lip_sync and shot.audio_path:
                    final_vid, ls_cost = await lipsync_provider.sync_lips(
                        raw_vid, Path(shot.audio_path), self.assets_dir / f"{shot.shot_id}_synced.mp4"
                    )
                    shotlist.spent_usd = round(shotlist.spent_usd + ls_cost, 4)
                else:
                    final_vid = raw_vid

                shot.video_path, shot.status = str(final_vid), ShotStatus.RENDERED
                frame_png = extract_mid_frame(final_vid, self.assets_dir / f"{shot.shot_id}_qa.png")
                shot.keyframe_path = str(frame_png)
                report = await qa_provider.inspect_shot(shot, grounded_prompt, frame_png)
                shot.qa_report = report

                if report.passed:
                    shot.status = ShotStatus.APPROVED
                    break
                shot.status = ShotStatus.QA_FAILED
                shot.retry_count += 1
                grounded_prompt += f" | FIX ARTIFACT: {report.critique}"

            self.save_state(bible, shotlist, script)

        failed_shots = [s.shot_id for s in shotlist.shots if s.status != ShotStatus.APPROVED]
        if failed_shots and not allow_partial:
            raise PipelineIncompleteError(
                f"Pipeline halted: shots {failed_shots} failed VLM QA after {self.max_retries} retries."
            )
        return shotlist
