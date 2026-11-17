# Security Policy

## Supported Versions

The following versions of **CineForge-Agent** currently receive security updates:

| Version | Supported |
| :--- | :--- |
| 0.1.x | :white_check_mark: |
| < 0.1.0 | :x: |

## Reporting a Vulnerability

Please **do not** report security vulnerabilities through public GitHub issues.

Instead, report them privately via GitHub Security Advisories:
- Navigate to https://github.com/Duttaak555/cineforge-agent/security/advisories/new
- Include a description of the issue, steps to reproduce, and any potential impact (e.g., path traversal in MCP tools, command injection in FFmpeg/Playwright runners, or C2PA key handling).

You will receive an acknowledgment within 72 hours and a timeline for a patch once verified.

## Security Best Practices

- Keep `C2PA_KEY_PATH` and `GEMINI_API_KEY` in a git-ignored `.env` file or secrets manager; never commit private keys or test certificates to the repository.
- Only expose the MCP server over local `stdio` transport unless placed behind an authenticated reverse proxy.
