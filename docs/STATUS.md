# Delivery and validation record

Version 0.1.0 implemented and locally validated on 2 October 2026. Repository: [ricardoportoIE/autonomous-applicator](https://github.com/ricardoportoIE/autonomous-applicator).

## Implemented

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
| Automated tests | 72 passed |
| Python statement coverage | 97.89% (1,111 / 1,135 statements) |
| Python branch coverage | 92.68% (291 / 314 branches) |
| Combined statement/branch coverage | 96.76%; CI minimum 90% |
| Ruff | Passed |
| Strict mypy | Passed for all 12 source modules |
| Dependency audit | No known dependency vulnerabilities reported; the unpublished local package is not a PyPI audit target |
| Packaging | Source distribution and wheel built; dashboard assets present, private data absent |
| Document QA | Private preview rendered and visually inspected; two-page CV and one-page cover letter, without clipping or overlap |
| Browser journeys | Dashboard/profile/evidence/job/settings journey, local upload/submission fixture, intercepted LinkedIn Easy Apply and recruiter-discovery fixtures |
| Persistence and security | Threshold properties, concurrent reservation, daily limits, unknown answers, altered documents, origin/Host/token checks, crash recovery and SQLite backup/restore |
| Repository hygiene | Credential patterns and private contact details absent from tracked files |

JavaScript is checked through browser journeys; no JavaScript statement-coverage percentage is claimed. [Remote CI passed in all four combinations](https://github.com/ricardoportoIE/autonomous-applicator/actions/runs/37001153213): Linux and Windows, each with Python 3.12 and 3.14, for implementation commit `6d8cc84`. Coverage explicitly traces Playwright greenlets and API worker threads using the C tracing core, following the [Coverage.py configuration guidance](https://coverage.readthedocs.io/en/latest/config.html).

## Required live setup and limits

The candidate declared LinkedIn scope for discovery, Easy Apply and networking. The initial adapter still requires validation against the authenticated account and current live selectors. All LinkedIn traffic in the automated tests is intercepted; tests send no real applications or invitations.

The local candidate profile was translated from the supplied documents and awaits contact/fact confirmation. The accounting specialisation remains unapproved pending certificate review. The candidate must sign in with `browser-login` and configure a fresh, rotated API key locally to use live AI advice. The credential shared in chat was not used or committed. No paid OpenAI request was made during implementation/testing.

Automation starts paused. Unknown or unsupported questions stop for review; employer-specific portals without an adapter use manual hand-off. Feedback currently provides recorded outcomes and cautious observations, not self-training or automatic factual/policy changes. This is a tested local prototype, not a guarantee of defect-free live job applications or ATS acceptance.
