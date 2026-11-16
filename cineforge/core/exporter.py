import subprocess
from pathlib import Path

import opentimelineio as otio

from cineforge.core.provenance import sign_c2pa_manifest
from cineforge.schemas.bible import EntityBible
from cineforge.schemas.timeline import ShotList, ShotStatus

ASPECT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


def export_to_otio(shotlist: ShotList, output_path: Path, fps: int = 24) -> Path:
    timeline = otio.schema.Timeline(name=f"CineForge_{shotlist.project_id}")
    v_track = otio.schema.Track(name="V1_AI_Shots", kind=otio.schema.TrackKind.Video)
    a_track = otio.schema.Track(name="A1_Dialogue_TTS", kind=otio.schema.TrackKind.Audio)

    for shot in sorted(shotlist.shots, key=lambda s: (s.scene_number, s.order_index)):
        if shot.status != ShotStatus.APPROVED or not shot.video_path:
            continue
        tr = otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, fps),
            duration=otio.opentime.RationalTime(shot.duration_sec * fps, fps),
        )
        v_track.append(
            otio.schema.Clip(
                name=shot.shot_id,
                media_reference=otio.schema.ExternalReference(target_url=str(Path(shot.video_path).resolve())),
                source_range=tr,
            )
        )
        if shot.audio_path:
            a_track.append(
                otio.schema.Clip(
                    name=f"{shot.shot_id}_audio",
                    media_reference=otio.schema.ExternalReference(target_url=str(Path(shot.audio_path).resolve())),
                    source_range=tr,
                )
            )
        else:
            a_track.append(otio.schema.Gap(source_range=tr))

    timeline.tracks.extend([v_track, a_track])
    otio.adapters.write_to_file(timeline, str(output_path))
    return output_path


def render_master_mp4(
    shotlist: ShotList,
    bible: EntityBible,
    output_mp4: Path,
    cert_path: str = "",
    key_path: str = "",
    require_signed: bool = False,
) -> tuple[Path, bool]:
    approved = [
        s
        for s in sorted(shotlist.shots, key=lambda s: (s.scene_number, s.order_index))
        if s.status == ShotStatus.APPROVED and s.video_path
    ]
    if not approved:
        raise ValueError("No QA-approved shots available.")

    target_w, target_h = ASPECT_DIMENSIONS.get(bible.aspect_ratio, (1920, 1080))
    scale_pad_vf = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps={bible.fps},format=yuv420p"
    )

    work_dir = output_mp4.parent
    normalized_clips: list[Path] = []
    for shot in approved:
        assert shot.video_path is not None
        norm_clip = work_dir / f"_norm_{shot.shot_id}.mp4"
        if shot.audio_path and Path(shot.audio_path).exists():
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    shot.video_path,
                    "-i",
                    shot.audio_path,
                    "-vf",
                    scale_pad_vf,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-c:a",
                    "aac",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-af",
                    "loudnorm=I=-14:TP=-1.5:LRA=11",
                    "-shortest",
                    str(norm_clip),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    shot.video_path,
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-vf",
                    scale_pad_vf,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-c:a",
                    "aac",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-shortest",
                    str(norm_clip),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        normalized_clips.append(norm_clip)

    concat_list = work_dir / "_concat.txt"
    concat_list.write_text("\n".join(f"file '{c.resolve()}'" for c in normalized_clips))
    unsigned_mp4 = work_dir / f"_unsigned_{output_mp4.name}"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(unsigned_mp4)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return sign_c2pa_manifest(
        unsigned_mp4, output_mp4, bible, cert_path=cert_path, key_path=key_path, require_signed=require_signed
    )
