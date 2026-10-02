# Delivery and validation record

Version 0.2.0 reviewed and locally validated on 2 October 2026. Repository: [ricardoportoIE/autonomous-applicator](https://github.com/ricardoportoIE/autonomous-applicator).

## Implemented

- Locally compiled Tailwind CSS, responsive layouts, semantic navigation, agent readiness, session locking and outcome counts.
- Request-stream limits, stale profile edit detection, transactional evidence changes and latest-attempt receipt protection.
- Loopback dashboard, local token authentication, same-origin checks and browser security headers.
- Versioned candidate profile, qualifications, evidence, approved questionnaire answers and historical application documents.
- Transparent job fit and 80/50 routing, sponsorship exclusions, mandatory-condition review and stale-material invalidation.
- Manual and Greenhouse imports; LinkedIn discovery, bounded Easy Apply, approved text/select/radio answers, document uploads and confirmation checks.
- European recruiter discovery and controlled invitations; no public profile edits.
- Ten daily application attempts and three daily networking attempts by default, pause controls, durable attempt journalling, deduplication, uncertain-state recovery and outcome recording.
- A4, single-column, selectable-text PDF CVs, optional cover letters and editable DOCX versions, with job-specific evidence selection and document hash checks.
- Optional `gpt-6.1-sol` adviser using structured evidence identifiers. No factual generation or private chain-of-thought logging.

## Local validation

| Check | Result |
| --- | --- |
| Python tests | 143 passed, including backend and real-browser integration tests |
| JavaScript unit tests | 5 passed |
| Python statement coverage | 98.56% (1,167 / 1,184 statements) |
| Python branch coverage | 95.88% (326 / 340 branches) |
| Combined statement/branch coverage | 97.97%; CI minimum 90% |
| Dashboard JavaScript browser line coverage | 97.62% (782 / 801 lines), across app.js and ui.js |
| Dashboard JavaScript browser branch coverage | 95.37% (206 / 216 branches) |
| Dashboard JavaScript browser function coverage | 95.55% (43 / 45 functions) |
| Helper unit coverage | 100% lines, branches and functions in ui.js |
| Frontend journeys | 32 scenarios, including 12 axe scans across six views at desktop and mobile widths |
| Responsive checks | 390, 768 and 1,440 pixels; keyboard navigation and 200% text enlargement |
| Ruff | Passed |
| Frontend checks | ESLint and Prettier passed |
| Strict mypy | Passed for all 12 source modules |
| Dependency audits | Python and npm reported no known vulnerabilities; the unpublished local package is not a PyPI audit target |
| Packaging | Source archive and wheel built; packaged dashboard assets match current source, private data absent |
| Document QA | PDF/DOCX content and layout checks repeated; earlier visual inspection of the unchanged renderer produced a two-page CV and one-page cover letter |
| Browser journeys | Dashboard/profile/evidence/job/settings journey, local upload/submission fixture, intercepted LinkedIn Easy Apply and recruiter-discovery fixtures |
| Persistence and security | Threshold properties, concurrent reservation, daily limits, unknown answers, altered documents, origin/Host/token checks, crash recovery and SQLite backup/restore |
| Repository hygiene | Credential patterns and private contact details absent from 53 tracked files |

Browser coverage uses precise V8 ranges from the actual local application, converted with v8-to-istanbul. Helper unit coverage is reported separately. The browser report gate requires 90% lines and 80% branches. Python coverage explicitly traces Playwright greenlets and API worker threads using the C tracing core, following the [Coverage.py configuration guidance](https://coverage.readthedocs.io/en/latest/config.html).

The [complete source review](CODE_REVIEW.md) records the line-by-line inspection and regression findings. The CI matrix checks Linux and Windows with Python 3.12 and 3.14, using Node.js 24. It also rebuilds the committed Tailwind CSS and verifies unchanged output, runs frontend checks, audits dependencies and publishes coverage reports. [Remote CI passed in all four combinations](https://github.com/ricardoportoIE/autonomous-applicator/actions/runs/37007225803) for implementation commit `e67b2a8`: Linux and Windows, each with Python 3.12 and 3.14. This final record changes documentation only.

## Required live setup and limits

The candidate-declared LinkedIn scope for discovery, Easy Apply and networking is configured in the local workspace. The initial adapter still requires validation against the authenticated account and current live selectors. All LinkedIn traffic in the automated tests is intercepted; tests send no real applications or invitations. A missing visible confirmation after a submission click is explicitly tested as uncertain, without automatic retry.

The local candidate profile was translated from the supplied documents and awaits contact/fact confirmation. The accounting specialisation remains unapproved pending certificate review. The candidate must sign in with `browser-login` and configure a fresh, rotated API key locally to use live AI advice. The credential shared in chat was not used or committed. No paid OpenAI request was made during implementation/testing.

Automation remains paused locally. Unknown or unsupported questions stop for review; employer-specific portals without an adapter use manual hand-off. Feedback currently provides recorded outcomes and cautious observations, not self-training or automatic factual/policy changes. This is a tested local prototype, not a guarantee of defect-free live job applications or ATS acceptance.
