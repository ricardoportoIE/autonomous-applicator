# Autonomous Applicator

A local job application workbench that links every candidate claim to evidence, explains job fit, prepares tailored CVs and cover letters, and controls application queues.

Inspect submission readiness without opening a browser or consuming a daily attempt. Search and sort the queue, follow an individual application's activity, and see the remaining London-day attempt budget.

The agent processes opportunities in arrival order, completing each vacancy's evidence selection, documents, checks and submission before starting the next. A live monitor shows the current opportunity, stage, elapsed time and run identifier. Failed and interrupted work retains its recorded stage for review. See [Application queue operation](docs/APPLICATION_QUEUE.md).

Manage European hiring contacts in active and archived queues, with private circular portraits, highlighted locations, profile links and visible invitation progress.

![Local application dashboard with fictional example data](docs/assets/dashboard.png)

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
uv sync --extra dev --python 3.14
# Uses installed Edge on Windows; otherwise install Chromium:
uv run python -m playwright install chromium
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# Set a fresh OPENAI_API_KEY locally only if enabling the optional AI adviser.
uv run python -m applicator.cli serve
```

Open `http://127.0.0.1:8765`. The first run generates a local access token. The command prints the token required by the dashboard. Keep the server bound to loopback.

```powershell
uv run python -m ruff check .
uv run python -m mypy src
npm ci
npm run build:css
npm test
uv run python -m pytest
npm run coverage:browser
uv run python -m pip_audit
```

## Documentation

- [Requirements and acceptance criteria](docs/REQUIREMENTS.md)
- [Architecture and submission invariants](docs/ARCHITECTURE.md)
- [Security and privacy](docs/SECURITY.md)
- [Operating guide](docs/OPERATIONS.md)
- [Delivery and validation record](docs/STATUS.md)
- [Complete source review and regression findings](docs/CODE_REVIEW.md)
- [Live OpenAI performance and evidence-selection comparison](docs/AI_BENCHMARK.md)
- [Vacancy-specific CV preparation and model provenance](docs/CV_PREPARATION.md)
- [Improvements and next priorities](docs/IMPROVEMENTS.md)

## Frontend development and testing

The dashboard uses locally compiled [Tailwind CSS](https://tailwindcss.com/docs/installation/tailwind-cli). Node.js is required for frontend development and the full test suite. Running the installed application uses the committed CSS and needs no Node.js process or CDN.

```powershell
npm ci
npm run build:css
npm run lint
npm run format:check
npm test
uv run python -m pytest
npm run coverage:browser
```

Frontend unit tests cover presentation and parsing helpers. Real-browser tests cover the dashboard and collect V8 coverage for `app.js` and `ui.js`. Reports are saved under the ignored `test-results/frontend-report` directory. The suite also runs local axe scans and verifies mobile/tablet/desktop layouts, keyboard use, enlarged text, stale edits, token expiry and request concurrency. The Content Security Policy stays enabled during these checks.

## AI integration

The optional adviser uses the OpenAI Responses API with `gpt-6.1-sol`, structured output and `store=False`. It selects and ranks existing evidence identifiers; the renderer preserves approved factual wording. Unknown form answers require candidate input. No hidden chain of thought is stored. Documents retain model provenance, evidence references and candidate/job fingerprints.

Set `OPENAI_API_KEY` in the ignored local `.env` file, keep `OPENAI_MODEL=gpt-6.1-sol`, and restart the server after saving. Enable **Use GPT-6.1 Sol for document preparation by default** in Agent settings for ordinary and automatic preparation. AI failures remain in review without a local fallback. The explicit **Select evidence with GPT-6.1 Sol** button remains available. Contact discovery and invitations use local rules and do not require an OpenAI request. See the [operating guide](docs/OPERATIONS.md) and [live CV audit](docs/CV_PREPARATION.md).

LinkedIn prohibits unauthorised automated access under its [User Agreement](https://www.linkedin.com/legal/user-agreement). The candidate has declared specific authorisation for discovery, Easy Apply and networking. Enable that scope explicitly after local sign-in. The adapter performs bounded browser actions and holds unknown questions or changed job details for review. Fixture tests do not certify the current live LinkedIn interface. Other employer portals use manual hand-off unless a permitted adapter is configured.
