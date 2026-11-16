# Contributing to CineForge-Agent

1. Fork and clone `https://github.com/Duttaak555/cineforge-agent.git`.
2. Run `uv venv --python 3.12 && source .venv/bin/activate && uv pip install -e '.[dev]' && playwright install chromium`.
3. Verify `pytest -v` and `python examples/run_demo.py` pass before opening a PR.
