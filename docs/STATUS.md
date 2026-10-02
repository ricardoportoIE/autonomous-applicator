# Delivery and validation record

Version 0.3.0 reviewed and locally validated on 2 October 2026. Repository: [ricardoportoIE/autonomous-applicator](https://github.com/ricardoportoIE/autonomous-applicator).

## Implemented

- Read-only submission preflight, current gate explanations, actual daily attempt capacity, searchable/filterable/sortable queues and application-specific activity.
- Single-connection queue reads, indexed journals and quota queries, required-cover-PDF checks and LinkedIn identity validation before reservation.
- Locally compiled Tailwind CSS, responsive layouts, semantic navigation, agent readiness, session locking and outcome counts.
- Request-stream limits, stale profile edit detection, transactional evidence changes and latest-attempt receipt protection.
- Loopback dashboard, local token authentication, same-origin checks and browser security headers.
- Versioned candidate profile, qualifications, evidence, approved questionnaire answers and historical application documents.
- Transparent job fit and 80/50 routing, sponsorship exclusions, mandatory-condition review and stale-material invalidation.
- Manual and Greenhouse imports; LinkedIn discovery, bounded Easy Apply, approved text/select/radio answers, document uploads and confirmation checks.
- European recruiter discovery and controlled invitations; no public profile edits.
- Accessible profile links for every connection state, spaced queue controls and a local candidate-confirmation explanation with a review shortcut.
- Current semantic and legacy LinkedIn profile cards, primary-result link selection, exact invitation identity checks and readable browser-error diagnostics.
- Ten daily application attempts and three daily networking attempts by default, pause controls, durable attempt journalling, deduplication, uncertain-state recovery and outcome recording.
- A4, single-column, selectable-text PDF CVs, optional cover letters and editable DOCX versions, with job-specific evidence selection and document hash checks.
- Optional `gpt-6.1-sol` adviser using structured evidence identifiers. No factual generation or private chain-of-thought logging.

## Local validation

| Check | Result |
| --- | --- |
| Python tests | 190 passed, including backend and real-browser integration tests |
| JavaScript unit tests | 8 passed |
| Python statement coverage | 98.61% (1,280 / 1,298 statements) |
| Python branch coverage | 95.97% (357 / 372 branches) |
| Combined statement/branch coverage | 98.02%; CI minimum 90% |
| Dashboard JavaScript browser line coverage | 98.94% (938 / 948 lines), across app.js and ui.js |
| Dashboard JavaScript browser branch coverage | 96.16% (251 / 261 branches) |
| Dashboard JavaScript browser function coverage | 100% (51 / 51 functions) |
| Helper unit coverage | 100% lines, branches and functions in ui.js |
| Frontend journeys | 42 scenarios, including 16 axe scans across six views, application detail and populated networking queues at desktop and mobile widths |
| Responsive checks | 390, 768 and 1,440 pixels; keyboard navigation and 200% text enlargement |
| Ruff | Passed |
| Frontend checks | ESLint and Prettier passed |
| Strict mypy | Passed for all 12 source modules |
| Dependency audits | Python and npm reported no known vulnerabilities; the unpublished local package is not a PyPI audit target |
| Packaging | Source archive and wheel built; packaged dashboard assets match current source, private data absent |
| Document QA | PDF/DOCX content and layout checks repeated; earlier visual inspection of the unchanged renderer produced a two-page CV and one-page cover letter |
| Browser journeys | Dashboard/profile/evidence/job/settings journey, local upload/submission fixture, intercepted LinkedIn Easy Apply and recruiter-discovery fixtures |
| Persistence and security | Threshold properties, concurrent reservation, daily limits, unknown answers, altered documents, origin/Host/token checks, crash recovery and SQLite backup/restore |
| Repository hygiene | Credential patterns and private contact details absent from 55 tracked files |

The improvement pass adds 22 Python regressions and three JavaScript helper tests. Diagnostics are explicitly tested to leave records, journals, attempt counts and submission adapters untouched. A browser submission journey uses a mocked provider adapter, records its fictional receipt and checks the quota and timeline. Preview screenshots use fictional example records only. Both 0.3.0 distributions were verified, including byte-for-byte dashboard assets and exclusion of private runtime paths.

Browser coverage uses precise V8 ranges from the actual local application, converted with v8-to-istanbul. Helper unit coverage is reported separately. The browser report gate requires 90% lines and 80% branches. Python coverage explicitly traces Playwright greenlets and API worker threads using the C tracing core, following the [Coverage.py configuration guidance](https://coverage.readthedocs.io/en/latest/config.html).

The [complete source review](CODE_REVIEW.md) records the line-by-line inspection and regression findings. The CI matrix checks Linux and Windows with Python 3.12 and 3.14, using Node.js 24. It also rebuilds the committed Tailwind CSS and verifies unchanged output, runs frontend checks, audits dependencies and publishes coverage reports. For implementation commit `4cd7862`, the [remote CI run](https://github.com/ricardoportoIE/autonomous-applicator/actions/runs/37061851242) passed both Linux versions and Windows/Python 3.12. Windows/Python 3.14 is being rerun after its existing pause regression exceeded a five-second UI assertion timeout; 189 tests passed in that first attempt, including the new networking scenarios. The same pause regression passed again locally in isolation, and the complete local suite passed all 190 tests. The rerun is pending; a complete green remote matrix is not yet claimed. The earlier recruiter-discovery repair `77a7be6`, browser-login correction `aa35892` and version 0.3.0 implementation `2f5ebcf` passed their complete matrices. This final record changes documentation only. The [improvement assessment](IMPROVEMENTS.md) distinguishes delivered capabilities from proposed next priorities.

## Required live setup and limits

The current coverage measurements and full-suite counts above refer to implementation commit `4cd7862`, including the browser-login cleanup correction, recruiter-discovery repair and connection profile links. The login correction has three tests distinguishing expected window closure from setup or unrelated failures. The discovery repair adds 19 regressions covering semantic/deeply wrapped/legacy cards, ambiguous or incomplete identity, wrong contact-information links, result scoping, canonical deduplication, bounded discovery, sanitised API errors and frontend recovery. Invitation checks require the same primary profile identity, role and location; redirects stop before examining invitation controls.

The networking UI follow-up adds three browser scenarios. Populated queues pass desktop/mobile accessibility checks; member links open intercepted fictional profiles in isolated tabs without a referrer. Links remain available after sent or uncertain outcomes. The unconfirmed-profile journey verifies the explanation, review shortcut, explicit confirmation/save flow, and continued pause enforcement without an invitation attempt. The live local server serves the updated assets; its three contacts remain queued with zero invitation attempts, an unconfirmed candidate record and both automation/networking disabled.

Manual LinkedIn sign-in was completed in the dedicated local profile on 2 October 2026. A separate read-only check reopened that saved profile headlessly and reached both the authenticated feed and the configured job search. It imported no records and sent no applications or invitations. This verifies session reuse and search access; Easy Apply uploads and submission selectors still need live validation.

Recruiter discovery was subsequently checked against the authenticated account and observed profile layout. The actual local discovery endpoint returned HTTP 200 with three matching European recruiters, retained as queued contacts in the ignored database. Their invitation attempt dates and receipts remain empty, and automation remains paused. No invitation was sent. Live member identities and browser snapshots were not published.

The candidate-declared LinkedIn scope for discovery, Easy Apply and networking is configured in the local workspace. The initial adapter still requires validation against the authenticated account and current live selectors. All LinkedIn traffic in the automated tests is intercepted; tests send no real applications or invitations. A missing visible confirmation after a submission click is explicitly tested as uncertain, without automatic retry.

The local candidate profile was translated from the supplied documents and awaits contact/fact confirmation. The accounting specialisation remains unapproved pending certificate review. Use `browser-login` to renew authentication when needed. Configure a fresh, rotated API key locally to use live AI advice. The credential shared in chat was not used or committed. No paid OpenAI request was made during implementation/testing.

Automation remains paused locally. Unknown or unsupported questions stop for review; employer-specific portals without an adapter use manual hand-off. Feedback currently provides recorded outcomes and cautious observations, not self-training or automatic factual/policy changes. This is a tested local prototype, not a guarantee of defect-free live job applications or ATS acceptance.
