# Autonomous Applicator

A local job application workbench that links every candidate claim to evidence, explains job fit, prepares tailored CVs and cover letters, and controls application queues.

Built for an Ireland and UK technology job search. The interface, code, prompts and documentation use British English. Personal information, credentials, generated documents and browser sessions stay outside Git.

## Delivery status

The implementation and validation record is maintained in [docs/STATUS.md](docs/STATUS.md). This repository must not describe simulated applications as real submissions. Live provider capabilities are explicitly registered; unsupported websites remain manual.

## Decision rules

- **80–100:** eligible for automatic submission when all factual, document and provider checks pass.
- **50–79:** manual review queue.
- **0–49:** not prioritised.
- Explicit incompatibilities, missing required answers, stale evidence, an uncertain previous submission or disabled automation prevent automatic submission regardless of score.

The fit score is a transparent heuristic, not an ATS score or a hiring probability. Seniority and requested years alone are not rejection rules. Unmentioned sponsorship is unknown rather than refused.

## Local setup

```powershell
uv sync --extra dev
uv run playwright install chromium
Copy-Item .env.example .env
# Set a fresh OPENAI_API_KEY locally only if enabling the optional AI adviser.
uv run applicator serve
```

Open `http://127.0.0.1:8765`. The first run generates a local access token. The command prints the token required by the dashboard. Keep the server bound to loopback.

```powershell
uv run ruff check .
uv run mypy src
uv run pytest
uv run pip-audit
```

## Documentation

- [Requirements and acceptance criteria](docs/REQUIREMENTS.md)
- [Architecture and submission invariants](docs/ARCHITECTURE.md)
- [Security and privacy](docs/SECURITY.md)
- [Operating guide](docs/OPERATIONS.md)
- [Delivery and validation record](docs/STATUS.md)

## AI integration

The optional adviser uses the OpenAI Responses API with `gpt-6.1-sol`, structured output and `store=False`. It selects existing evidence identifiers rather than inventing candidate history. Unknown form answers require candidate input. No hidden chain of thought is stored; the application records concise explanations and evidence references.

LinkedIn prohibits unauthorised automated access under its [User Agreement](https://www.linkedin.com/legal/user-agreement). The initial LinkedIn integration is a manual hand-off. Browser automation is tested on a local fixture; live sites require an explicitly configured, permitted adapter.
