import subprocess
from pathlib import Path
import opentimelineio as otio
from cineforge.schemas.bible import EntityBible
from cineforge.schemas.timeline import ShotList, ShotStatus
from cineforge.core.provenance import sign_c2pa_manifest

def export_to_otio(shotlist: ShotList, output_path: Path, fps: int = 24) -> Path:
    timeline = otio.schema.Timeline(name=f"CineForge_{shotlist.project_id}")
    v_track, a_track = otio.schema.Track(name="V1_AI_Shots", kind=otio.schema.TrackKind.Video), otio.schema.Track(name="A1_Dialogue_TTS", kind=otio.schema.TrackKind.Audio)
    for shot in sorted(shotlist.shots, key=lambda s: (s.scene_number, s.order_index)):
        if shot.status != ShotStatus.APPROVED or not shot.video_path: continue
        tr = otio.opentime.TimeRange(start_time=otio.opentime.RationalTime(0, fps), duration=otio.opentime.RationalTime(shot.duration_sec * fps, fps))
        v_track.append(otio.schema.Clip(name=shot.shot_id, media_reference=otio.schema.ExternalReference(target_url=str(Path(shot.video_path).resolve())), source_range=tr))
        if shot.audio_path:
            a_track.append(otio.schema.Clip(name=f"{shot.shot_id}_audio", media_reference=otio.schema.ExternalReference(target_url=str(Path(shot.audio_path).resolve())), source_range=tr))
        else:
            a_track.append(otio.schema.Gap(source_range=tr))
    timeline.tracks.extend([v_track, a_track])
    otio.adapters.write_to_file(timeline, str(output_path))
    return output_path

def render_master_mp4(shotlist: ShotList, bible: EntityBible, output_mp4: Path, cert_path: str = "", key_path: str = "") -> Path:
    approved = [s for s in sorted(shotlist.shots, key=lambda s: (s.scene_number, s.order_index)) if s.status == ShotStatus.APPROVED and s.video_path]
    if not approved: raise ValueError("No QA-approved shots available.")
    work_dir, muxed_clips = output_mp4.parent, []
    for shot in approved:
        muxed = work_dir / f"_mux_{shot.shot_id}.mp4"
        if shot.audio_path and Path(shot.audio_path).exists():
            subprocess.run(["ffmpeg", "-y", "-i", shot.video_path, "-i", shot.audio_path, "-c:v", "copy", "-c:a", "aac", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-shortest", str(muxed)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["ffmpeg", "-y", "-i", shot.video_path, "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", "-c:v", "copy", "-c:a", "aac", "-shortest", str(muxed)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        muxed_clips.append(muxed)
    concat_list = work_dir / "_concat.txt"
    concat_list.write_text("\n".join(f"file '{c.resolve()}'" for c in muxed_clips))
    unsigned_mp4 = work_dir / f"_unsigned_{output_mp4.name}"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(unsigned_mp4)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return sign_c2pa_manifest(unsigned_mp4, output_mp4, bible, cert_path=cert_path, key_path=key_path)
