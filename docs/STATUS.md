# Delivery and validation record

Version 0.3.0 reviewed and locally validated on 3 October 2026. Repository: [ricardoportoIE/autonomous-applicator](https://github.com/ricardoportoIE/autonomous-applicator).

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
- Accessible profile links for every connection state, spaced controls and independent single-contact invitations in a visible dedicated browser.
- Durable Started/Running/Done/Failed/Needs review feedback, primary-card Connect/More selection, concurrent status reads and lock/reload observation without resending.
- Current semantic and legacy LinkedIn profile cards, primary-result link selection, exact invitation identity checks and readable browser-error diagnostics.
- Ten daily application attempts and three daily networking attempts by default, pause controls, durable attempt journalling, deduplication, uncertain-state recovery and outcome recording.
- A4, single-column, selectable-text PDF CVs, optional cover letters and editable DOCX versions, with job-specific evidence selection and document hash checks.
- Optional `gpt-6.1-sol` adviser using structured evidence identifiers. No factual generation or private chain-of-thought logging.

## Local validation

### Recruiter discovery and archive follow-up

Manual recruiter discovery now uses the saved daily connection limit as its target instead of a fixed three. Background discovery uses the remaining networking quota. Existing contacts are excluded regardless of state, and the adapter reviews at most ten new primary results to fill the requested number of suitable European hiring contacts. Searches can return fewer matches when available suitable results are exhausted.

The search button displays Searching, an activity indicator and an accessible status message until completion, no results or failure. Duplicate clicks are suppressed and a locked workspace discards late responses. Active and Archived tabs show counts and support keyboard navigation. Confirmed sent contacts move automatically to Archived, preserving profile links, delivery confirmation, historical records and quotas. Failed and uncertain contacts remain active for review.

Fifteen new regressions cover saved limits, remaining quota, known-contact exclusion, filtered results and bounded inspection, search progress/outcomes, duplicate suppression, locking, automatic archiving, keyboard tabs and desktop/mobile accessibility. An older mocked receipt fixture now configures the combined button/link locator used by the Pending check; provider ambiguity guards are unchanged. A read-only check of the running local dashboard confirmed the saved limit and archived history, without searching or sending invitations. Packaging and repository hygiene checks passed; test screenshots use fictional contacts.

### Pending invitation confirmation follow-up

The live LinkedIn profile layout renders **Pending** as a link whose accessible name includes an invitation-withdrawal description. The previous confirmation check accepted only a button, so a successful invitation could remain uncertain. Confirmation now accepts a visible button or link, with either a plain or extended Pending label, and requires exactly one matching control on the verified primary member card. Recommended members' controls cannot confirm an invitation.

Five intercepted-provider regressions cover plain Pending links, extended button/link labels, a recommended member's pending control and duplicate confirmations. A separate read-only account inspection confirmed existing invitations and reconciled the corresponding local records without clicking Connect, Follow, Send or Withdraw. Private identities and runtime records remain outside the repository.

Follow-up validation: **45 tests passed** across the manual-networking and contact-discovery modules. Ruff checks, Python formatting and strict mypy also passed. These checks do not repeat the complete frontend suite or establish live submission behaviour for every LinkedIn layout.

The full-suite results below are from implementation commit `cc82fac`, including both networking follow-ups.

| Check | Result |
| --- | --- |
| Python tests | 240 passed, including backend and real-browser integration tests |
| JavaScript unit tests | 8 passed |
| Python statement coverage | 98.29% (1,382 / 1,406 statements) |
| Python branch coverage | 95.31% (406 / 426 branches) |
| Combined statement/branch coverage | 97.60%; CI minimum 90% |
| Dashboard JavaScript browser line coverage | 99.11% (1,121 / 1,131 lines), across app.js and ui.js |
| Dashboard JavaScript browser branch coverage | 96.04% (316 / 329 branches) |
| Dashboard JavaScript browser function coverage | 100% (59 / 59 functions) |
| Helper unit coverage | 100% lines, branches and functions in ui.js |
| Frontend journeys | 59 scenarios, including 40 axe scans across six views, application detail, invitation progress, search outcomes and the active/archive tabs at desktop and mobile widths |
| Responsive checks | 390, 768 and 1,440 pixels; keyboard navigation and 200% text enlargement |
| Ruff | Passed |
| Frontend checks | ESLint and Prettier passed |
| Strict mypy | Passed for all 12 source modules |
| Dependency audits | Python and npm reported no known vulnerabilities; the unpublished local package is not a PyPI audit target |
| Packaging | Source archive and wheel built; packaged dashboard assets match current source, private data absent |
| Document QA | PDF/DOCX content and layout checks repeated; earlier visual inspection of the unchanged renderer produced a two-page CV and one-page cover letter |
| Browser journeys | Dashboard/profile/evidence/job/settings journey, local upload/submission fixture, intercepted LinkedIn Easy Apply and recruiter-discovery fixtures |
| Persistence and security | Threshold properties, concurrent reservation, daily limits, unknown answers, altered documents, origin/Host/token checks, crash recovery and SQLite backup/restore |
| Repository hygiene | Credential patterns and private contact details absent from 56 tracked files |

The improvement pass adds 22 Python regressions and three JavaScript helper tests. Diagnostics are explicitly tested to leave records, journals, attempt counts and submission adapters untouched. A browser submission journey uses a mocked provider adapter, records its fictional receipt and checks the quota and timeline. Preview screenshots use fictional example records only. Both 0.3.0 distributions were verified, including byte-for-byte dashboard assets and exclusion of private runtime paths.

Browser coverage uses precise V8 ranges from the actual local application, converted with v8-to-istanbul. Helper unit coverage is reported separately. The browser report gate requires 90% lines and 80% branches. Python coverage explicitly traces Playwright greenlets and API worker threads using the C tracing core, following the [Coverage.py configuration guidance](https://coverage.readthedocs.io/en/latest/config.html).

The [complete source review](CODE_REVIEW.md) records the line-by-line inspection and regression findings. The CI matrix checks Linux and Windows with Python 3.12 and 3.14, using Node.js 24. It also rebuilds the committed Tailwind CSS and verifies unchanged output, runs frontend checks, audits dependencies and publishes coverage reports. [Remote CI passed all four combinations](https://github.com/ricardoportoIE/autonomous-applicator/actions/runs/37075132135) for implementation commit `cc82fac`. The earlier member-link implementation `4cd7862` also passed its complete matrix, following a rerun of a Windows/Python 3.14 pause assertion timeout; its assertions were not weakened. Earlier recruiter-discovery, browser-login and version 0.3.0 matrices passed as well. This final record changes documentation only. The [improvement assessment](IMPROVEMENTS.md) distinguishes delivered capabilities from proposed next priorities.

## Required live setup and limits

The current coverage measurements and full-suite counts above refer to implementation commit `cc82fac`, including recruiter discovery limits, visible search progress, automatic archiving and Pending link confirmation. The login correction has three tests distinguishing expected window closure from setup or unrelated failures. The discovery repair adds 19 regressions covering semantic/deeply wrapped/legacy cards, ambiguous or incomplete identity, wrong contact-information links, result scoping, canonical deduplication, bounded discovery, sanitised API errors and frontend recovery. Invitation checks require the same primary profile identity, role and location; redirects stop before examining invitation controls.

The initial networking UI follow-up added isolated member links. The independent invitation implementation adds 30 test cases: 22 backend/provider cases and eight frontend scenarios. A single manual invitation works with no candidate facts and paused background queues, shares the networking quota, and opens the selected profile with visible-browser intent. Intercepted browser cases exercise direct buttons and links, More menus and delayed popovers, rendering delays, Follow-only and recommended-member controls, duplicate controls, identity/location changes, login challenges, redirects, revoked scope and missing confirmation. Other checks cover sanitised failures, database migration, interrupted-run ownership, readable concurrent status and immediate busy-browser rejection. Frontend checks verify phase changes, failure/uncertainty, independent navigation, duplicate suppression, lost responses, status errors, reload observation and locking without resending. No real invitation was sent during these checks.

The updated local server was restarted after an SQLite backup and a check that no invitation was in flight. Authenticated status reads verify the new fields and retained historical uncertainty; unauthorised reads and unknown records are rejected. Background application automation remains disabled. A read-only inspection of available live profiles verified primary More controls and a Connect menu item where available. The inspection opened menus but did not click Connect, Follow or Send. An unavailable Connect action remains a bounded failure, rather than a fallback to Follow. Live invitation submission and receipt behaviour still require account-level validation.

Manual LinkedIn sign-in was completed in the dedicated local profile on 2 October 2026. A separate read-only check reopened that saved profile headlessly and reached both the authenticated feed and the configured job search. It imported no records and sent no applications or invitations. This verifies session reuse and search access; Easy Apply uploads and submission selectors still need live validation.

Recruiter discovery was subsequently checked against the authenticated account and observed profile layout. The actual local discovery endpoint returned HTTP 200 with three matching European recruiters, retained as queued contacts in the ignored database. Their invitation attempt dates and receipts remain empty, and automation remains paused. No invitation was sent. Live member identities and browser snapshots were not published.

The candidate-declared LinkedIn scope for discovery, Easy Apply and networking is configured in the local workspace. The initial adapter still requires validation against the authenticated account and current live selectors. All LinkedIn traffic in the automated tests is intercepted; tests send no real applications or invitations. A missing visible confirmation after a submission click is explicitly tested as uncertain, without automatic retry.

The local candidate profile was translated from the supplied documents and subsequently confirmed in the local workspace. Unapproved evidence remains excluded until candidate review. This confirmation does not independently certify qualifications. Use `browser-login` to renew authentication when needed. Configure a fresh, rotated API key locally to use live AI advice. The credential shared in chat was not used or committed. No paid OpenAI request was made during implementation/testing.

Automation remains paused locally. Unknown or unsupported questions stop for review; employer-specific portals without an adapter use manual hand-off. Feedback currently provides recorded outcomes and cautious observations, not self-training or automatic factual/policy changes. This is a tested local prototype, not a guarantee of defect-free live job applications or ATS acceptance.
