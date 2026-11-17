# Contributing to CineForge-Agent

Thank you for contributing to **CineForge-Agent**! Whether you are adding a new TTS/video provider adapter, a ComfyUI workflow JSON template, or an NLE export enhancement, please follow the lightweight workflow below so every pull request passes CI cleanly.

## 1. Local Development Setup

Ensure you have **Python 3.11+**, **FFmpeg**, and **[Uv](https://docs.astral.sh/uv/)** installed:

```bash
git clone https://github.com/Duttaak555/cineforge-agent.git
cd cineforge-agent
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev]"
playwright install chromium
```

You can verify endpoint reachability on your machine anytime with:

```bash
cineforge-doctor
```

## 2. Code Quality & Verification Gate

GitHub Actions enforces formatting, static typing, unit/socket tests, and container builds on every pull request. Run these checks locally before opening a PR:

```bash
ruff check --fix .
ruff format .
mypy cineforge
pytest -v
```

### Testing Conventions
* **No Live GPU/API Keys Required in CI:** All new provider adapters (ComfyUI, TTS, VLM QA, Lip-Sync) must include deterministic HTTP protocol tests using `httpx.MockTransport` or local `ThreadingHTTPServer` stubs so CI runs reliably without external credentials or CUDA hardware.
* **Async Subprocesses:** Never call blocking `subprocess.run` directly inside `async def` functions—use `asyncio.to_thread(subprocess.run, ...)` so Ruff's `ASYNC221` check passes.
* **Narrow Exception Handling:** Catch specific exception classes (`httpx.HTTPError`, `OSError`, `ValueError`) rather than bare `Exception` (`BLE001`).

## 3. Pull Request Guidelines

1. **Branch Naming:** Create a focused branch from `main` (e.g., `feat/elevenlabs-tts`, `fix/srt-timestamps`, `docs/comfyui-guide`).
2. **Conventional Commits:** Prefix commit messages with `feat:`, `fix:`, `docs:`, `test:`, or `chore:`.
3. **Update `.env.example` & `README.md`:** If your PR introduces new environment variables or CLI flags, document them in `.env.example` and keep the Verification Scope Matrix in `README+nm` accurate.
4. **Keep PRs Focused:** Address one issue or feature per pull request and link the corresponding GitHub issue (`Closes #<issue_number>`).

## License

By contributing to CineForge-Agent, you agree that your contributions will be licensed under the **Apache License 2.0**.
