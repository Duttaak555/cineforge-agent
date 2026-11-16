import subprocess
from pathlib import Path

from playwright.async_api import async_playwright


async def render_html_motion_shot(
    html_body: str, duration_sec: float, output_mp4: Path, width: int = 1920, height: int = 1080, fps: int = 24
) -> tuple[Path, float]:
    temp_dir = output_mp4.parent / f"_webm_{output_mp4.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    html_file = temp_dir / "scene.html"
    html_file.write_text(
        f'<!DOCTYPE html><html><head><meta charset="utf-8"/>'
        f'<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>'
        f"<style>html,body{{margin:0;padding:0;width:{width}px;height:{height}px;overflow:hidden;background:#0b0f19;color:#f8fafc;font-family:system-ui,sans-serif;}}</style>"
        f"</head><body>{html_body}</body></html>",
        encoding="utf-8",
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            record_video_dir=str(temp_dir),
            record_video_size={"width": width, "height": height},
        )
        page = await context.new_page()
        await page.goto(html_file.resolve().as_uri())
        await page.wait_for_timeout(int(duration_sec * 1000))
        video_obj = page.video
        await context.close()
        await browser.close()
        if video_obj is None:
            raise RuntimeError("Playwright did not record a video stream.")
        webm_path = Path(await video_obj.path())

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(webm_path),
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-t",
            str(duration_sec),
            str(output_mp4),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return output_mp4, 0.0
