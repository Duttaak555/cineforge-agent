"""Bind values to ComfyUI API workflow templates without interpolating JSON text."""

import json
from pathlib import Path
from typing import Any


def render_wan22_i2v_workflow(
    template_path: Path, *, positive_prompt: str, negative_prompt: str, seed: int, image_path: str
) -> dict[str, Any]:
    """Build the prompt graph for an image that is already in ComfyUI's input folder."""
    graph: dict[str, Any] = json.loads(template_path.read_text(encoding="utf-8"))
    values: dict[str, str | int] = {
        "{{positive_prompt}}": positive_prompt,
        "{{negative_prompt}}": negative_prompt,
        "{{seed}}": seed,
        "{{image_path}}": image_path,
    }
    bound: set[str] = set()
    for node in graph.values():
        for name, value in node["inputs"].items():
            if isinstance(value, str) and value in values:
                node["inputs"][name] = values[value]
                bound.add(value)
    if missing := values.keys() - bound:
        raise ValueError(f"Missing I2V placeholders: {', '.join(sorted(missing))}")
    return graph
