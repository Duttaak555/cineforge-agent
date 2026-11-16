import asyncio
from cineforge.mcp.server import init_project, register_character, register_environment, add_shot, run_pipeline

async def main():
    pid = "cyber_launch_01"
    print(init_project(pid, "Project Neo-Bengaluru", aspect_ratio="16:9", budget_usd=2.50))
    print(register_character(pid, "char_arjun", "Arjun", "Indian tech founder, charcoal blazer", "am_eric"))
    print(register_environment(pid, "env_rooftop", "Bengaluru Rooftop", "Golden hour dusk, warm rim light"))
    print(add_shot(pid, "shot_01", 1, 1, 2.0, "env_rooftop", "Arjun overlooking skyline FORCE_QA_FAIL", character_ids=["char_arjun"], dialogue_text="The next era of autonomous video starts today.", speaker_entity_id="char_arjun", requires_lip_sync=True))
    print(add_shot(pid, "shot_02", 1, 2, 2.0, "env_rooftop", "Kinetic title card", engine="html_motion", html_template_spec='<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:72px;font-weight:800;">CINEFORGE AI</div>'))
    print("\nPIPELINE OUTPUT:\n", await run_pipeline(pid, mode="mock"))

if __name__ == "__main__": asyncio.run(main())
